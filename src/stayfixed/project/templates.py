"""The project footprint as `Template`s, built from a configuration.

Under the module root beside `templates/overlay/` and resolved by `stayfixed.templates.tree`, the
one resolver both shipped trees go through. `stayfixed.toml` and the files the surviving pack
commands need — the bug ledger's audits README, which keeps its directory in git, the generated bug
index, the roadmap with its trail markers, and `trail.toml` beside it — are create-once artifacts,
and the `.gitignore` region that keeps `.stayfixed/local/` out of git is rewritten in place, so a
second `init` writes what is missing and touches nothing else. Every target but `.gitignore` is a
`config.paths` value, which the loader has bounded to `PATH_VALUE` and contained; what this module
adds is a file name under it.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from stayfixed.config.loader import CONFIG_FILE
from stayfixed.config.schema import Config
from stayfixed.docs.api import trail_target
from stayfixed.errors import Failure, Refusal
from stayfixed.fsops import path_key
from stayfixed.ledger.api import BUG_AUDITS, bug_register, ledger_path, render_index
from stayfixed.project.layout import PROJECT_FILES
from stayfixed.scaffold import Kind, Style, Template
from stayfixed.templates import tree

PROJECT = "project"
# The artifact ids of `stayfixed.toml` and of the `.gitignore` region, spelled once.
CONFIG_ARTIFACT = "config"
IGNORE_ARTIFACT = "gitignore"
# The `.gitignore` region's name and body: the note, and the one path it keeps out of git,
# `.stayfixed/local/`, where the `local-only` notes and attach's ledger live.
IGNORE_REGION = "ignore"
IGNORE_BODY = "# stayfixed's local state: yours, never a collaborator's.\n.stayfixed/local/"


# Which `[paths]` key each artifact's target is built from, so the collision refusal below can
# name what to edit. Two statements of one thing, the way `PROJECT_FILES` and the shipped tree
# are: `tests/project/test_templates.py` holds this mapping's key set to the artifact ids
# `project_templates` produces, so an artifact added without a line here reddens rather than being
# named by the wrong key at the moment somebody's configuration collides.
OWN_NAME = "a fixed name of stayfixed's own"
PATH_KEYS = {
    CONFIG_ARTIFACT: OWN_NAME,
    "ledger-audits": "paths.bugs",
    "bug-index": "paths.bug_index",
    "roadmap": "paths.roadmap",
    "trail": "paths.roadmap",
    IGNORE_ARTIFACT: OWN_NAME,
}
# Fixed text with two artifact ids and two `[paths]` key names interpolated — all four are
# stayfixed's own vocabulary. The colliding path is a repository-authored value and is not printed.
ONE_FILE = (
    "{first} ({first_key}) and {second} ({second_key}) resolve to one file, so one artifact "
    "would be judged or overwritten as the other. Separate them under [paths] in "
    "stayfixed.toml, then run the command again"
)


def read(name: str) -> str:
    """One shipped template's text, refusing a name this package does not ship.

    The check is before the join and not after: `name` decides which file under the tree is
    opened, and `PROJECT_FILES` is the plugin's own list — the party being contained here is a
    caller inside this package, and the anchor is a constant in the wheel beside the files it
    names, which nothing a repository writes can move.
    """
    if name not in PROJECT_FILES:
        raise Failure(f"{name} is not a shipped project template")
    root = tree(PROJECT)
    if not root.is_dir():
        raise Failure(f"the project template tree is not readable at {root}")
    return (root / name).read_text(encoding="utf-8")


def _once(artifact_id: str, target: str, render: Callable[[], str]) -> Template:
    return Template(id=artifact_id, kind=Kind.ONCE, target=target, render=render)


def _no_file_of_another(templates: tuple[Template, ...]) -> None:
    """Refuse two artifacts at one file, before anything is planned.

    `scaffold.engine.plan` has no duplicate-target detection, so with `roadmap` and `bug_index`
    set to one path the plan reported no refusal, `apply` wrote both and the file held only the
    second artifact's bytes. Places are one file when `fsops.path_key` says so, as on the default
    filesystems of macOS and Windows, so `roadmap = "STAYFIXED.TOML"` is `stayfixed.toml`'s file on
    every filesystem and the refusal reddens on Linux as on macOS. It names two ids and their
    `[paths]` keys so that the remedy is one edit, and never the value, which is the repository's
    bytes.
    """
    seen: dict[str, str] = {}
    for template in templates:
        first = seen.setdefault(path_key(template.target), template.id)
        if first != template.id:
            raise Refusal(
                ONE_FILE.format(
                    first=first,
                    first_key=PATH_KEYS[first],
                    second=template.id,
                    second_key=PATH_KEYS[template.id],
                )
            )


def project_templates(config: Config, *, document: str) -> tuple[Template, ...]:
    """The footprint this configuration asks for.

    Nothing here reads the disk for a target: `trail_target` is a location, like every
    `[paths]`-built target, and the engine contains each one when it plans it. The bug index is
    rendered only where it is written, so a `[ledger]` value `bug_register` refuses stops a run that
    writes the index and no other, as it stops every command that builds the register.
    """
    p = config.paths
    # The audits README is where the bug index links it, built from `[paths] bugs` and the name
    # `bug_register` builds that link from, joined as it joins them. Without a file under the
    # ledger's directory, `bugs index --check` and `bugs check` read the index as orphaned.
    audits = ledger_path(p.bugs, BUG_AUDITS)
    templates = (
        _once(CONFIG_ARTIFACT, CONFIG_FILE, lambda: document),
        _once("ledger-audits", f"{audits}/README.md", partial(read, "audits-readme.md")),
        _once("bug-index", p.bug_index, lambda: render_index([], bug_register(config))),
        _once("roadmap", p.roadmap, partial(read, "roadmap.md")),
        _once("trail", trail_target(config), partial(read, "trail.toml")),
        Template(
            id=IGNORE_ARTIFACT,
            kind=Kind.MANAGED_REGION,
            target=".gitignore",
            render=lambda: IGNORE_BODY,
            region=IGNORE_REGION,
            style=Style.HASH,
        ),
    )
    _no_file_of_another(templates)
    return templates
