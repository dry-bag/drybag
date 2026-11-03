"""The project footprint as `Template`s, built from a configuration.

Under the module root beside `templates/overlay/` and resolved by `stayfixed.templates.tree`, the
one resolver both shipped trees go through. `stayfixed.toml` is a `Kind.ONCE` artifact in a pass of
its own; the files the surviving pack commands need — the bug ledger's audits README, which keeps
its directory in git, the generated bug index, the roadmap with its trail markers, and `trail.toml`
beside it — are the footprint pass. Every target is a `config.paths`
value, which the loader has bounded to `PATH_VALUE` and contained; what this module adds is a file
name under it.

This module builds templates and decides nothing about a manifest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cached_property, partial

from stayfixed.config.loader import CONFIG_FILE
from stayfixed.config.schema import Config
from stayfixed.docs.api import trail_target
from stayfixed.errors import Failure, Refusal
from stayfixed.fsops import path_key
from stayfixed.ledger.api import BUG_AUDITS, bug_register, ledger_path, render_index
from stayfixed.project.layout import PROJECT_FILES
from stayfixed.scaffold import Kind, Template, validate_sources
from stayfixed.templates import tree

PROJECT = "project"
# The provenance namespace for an artifact whose bytes this module *computes*, so that a record
# of one never claims a file the wheel does not carry.
#
# `Template.source` becomes `Record.template` in `.stayfixed/manifest.json`, which is committed and
# is where a reader finds out where an artifact's bytes came from. Two artifacts here have no
# shipped file at all — `config` is the rendered document, `bug-index` is
# `render_index([], bug_register(config))` — and a record naming `project/<id>` for one of them
# would point at a name absent from `PROJECT_FILES` and from the tree, which `read` itself refuses.
#
# A separate namespace rather than a name that looks readable: "there is no shipped file, these
# bytes are built" is the honest answer, and a reader — a person, `doctor` — can tell
# it from `project/roadmap.md` without asking the wheel. It stays one string, so the manifest
# format is untouched. `_computed` is the only place it is spelled, and
# `tests/project/test_templates.py` holds every source both passes build to one rule or the other.
COMPUTED = "computed"
# The artifact id of `stayfixed.toml`, spelled once. An id is also what every initialised
# repository's committed manifest records, so it is not renamed lightly:
# `tests/project/test_templates.py` holds it to the id the templates build.
CONFIG_ARTIFACT = "config"


# Which `[paths]` key each artifact's target is built from, so the collision refusal below can
# name what to edit. Two statements of one thing, the way `PROJECT_FILES` and the shipped tree
# are: `tests/project/test_templates.py` holds this mapping's key set to the artifact ids both
# passes actually produce, so an artifact added without a line here reddens rather than being
# named by the wrong key at the moment somebody's configuration collides.
OWN_NAME = "a fixed name of stayfixed's own"
PATH_KEYS = {
    CONFIG_ARTIFACT: OWN_NAME,
    "ledger-audits": "paths.bugs",
    "bug-index": "paths.bug_index",
    "roadmap": "paths.roadmap",
    "trail": "paths.roadmap",
}
# Fixed text with two artifact ids and two `[paths]` key names interpolated — all four are
# stayfixed's own vocabulary. The colliding path is a repository-authored value and is not printed.
ONE_FILE = (
    "{first} ({first_key}) and {second} ({second_key}) resolve to one file, so one artifact "
    "would be judged or overwritten as the other. Separate them under [paths] in "
    "stayfixed.toml, then run the command again"
)


@dataclass(frozen=True)
class Owners:
    """Which artifacts this build is built to write each place.

    **The relation.** `could_write` is `Prepared.could_write`: for each artifact id, every target
    this run's templates give it. A place is `foreign` to an id when another id is built to write
    it. Which ids exist are this build's; the `[paths]` values those places are built from are
    committed, and all a value can do here is add a place, never take one away. Places are one
    file when `fsops.path_key` says so, as on the default filesystems of macOS and Windows, so
    `roadmap = "STAYFIXED.TOML"` is `stayfixed.toml`'s file on every filesystem and the rule
    below reddens on Linux as on macOS.

    **The collision refusal** (`_no_file_of_another`) refuses a template at a place foreign to its
    id, in either pass, before anything is planned. `scaffold.engine.plan` has no duplicate-target
    detection, so with `roadmap` and `bug_index` set to one path both plans reported zero
    refusals, `apply` wrote both, the file held only the second artifact's bytes and the manifest
    recorded two different digests for one path. The anchor is this module's artifact list, a
    constant in the installed package; the refusal names two ids and their `[paths]` keys so that
    the remedy is one edit, and never the value, which is the repository's bytes.
    """

    could_write: Mapping[str, frozenset[str]]

    def foreign(self, artifact_id: str, place: str) -> frozenset[str]:
        """Every other artifact built to write `place`, or none when that is `artifact_id`'s
        alone."""
        return frozenset(
            owner
            for owner, places in self.could_write.items()
            if owner != artifact_id and path_key(place) in {path_key(p) for p in places}
        )


@dataclass(frozen=True)
class Prepared:
    """Both passes, the reasons an artifact was not rendered, and every target this build writes
    for each artifact id under this configuration.

    `could_write` is built at the lines that build the templates, from the same calls, so it
    cannot describe a target the footprint could not have. `owners` is the relation read from it.
    """

    once: tuple[Template, ...]
    footprint: tuple[Template, ...]
    skipped: dict[str, str]
    could_write: Mapping[str, frozenset[str]]

    @cached_property
    def owners(self) -> Owners:
        return Owners(self.could_write)


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


def _template(artifact_id: str, target: str, name: str) -> Template:
    """An artifact whose bytes are `templates/project/<name>`, shipped in the wheel.

    `name` is a `PROJECT_FILES` entry — `read` refuses anything else — and it is also the
    provenance recorded for the artifact; an artifact with no shipped file at all is
    `_computed`'s and not this one's.
    """
    return Template(
        id=artifact_id,
        kind=Kind.TEMPLATE,
        target=target,
        source=f"{PROJECT}/{name}",
        render=partial(read, name),
    )


def _computed(
    artifact_id: str, target: str, render: Callable[[], str], *, kind: Kind = Kind.TEMPLATE
) -> Template:
    """An artifact this module builds, whose provenance therefore names no shipped file.

    A second constructor rather than a flag or a `None` name on `_template`: which artifacts have
    a file in the wheel is decided here, once per artifact, at the line that builds it. `render`
    is required for the same reason: there is nothing to fall back to reading.
    """
    return Template(
        id=artifact_id,
        kind=kind,
        target=target,
        source=f"{COMPUTED}/{artifact_id}",
        render=render,
    )


def _no_file_of_another(prepared: Prepared) -> None:
    """Refuse an artifact of either pass at a place `Owners.foreign` gives another artifact."""
    for template in (*prepared.once, *prepared.footprint):
        others = prepared.owners.foreign(template.id, template.target)
        if not others:
            continue
        second = min(others)
        raise Refusal(
            ONE_FILE.format(
                first=template.id,
                first_key=PATH_KEYS.get(template.id, OWN_NAME),
                second=second,
                second_key=PATH_KEYS.get(second, OWN_NAME),
            )
        )


def project_templates(config: Config, *, document: str) -> Prepared:
    """The footprint this configuration asks for, split into the engine's two passes.

    Nothing here reads the disk for a target: `trail_target` is a location, like every
    `[paths]`-built target, and the engine contains each one when it plans it.
    """
    # The engine's rule first: an unshipped or malformed profile is refused naming the grammar and
    # the listing.
    validate_sources(config)
    p = config.paths
    once = (_computed(CONFIG_ARTIFACT, CONFIG_FILE, lambda: document, kind=Kind.ONCE),)
    # The audits README is where the bug index links it, built from `[paths] bugs` and the name
    # `bug_register` builds that link from, joined as it joins them. Without a file under the
    # ledger's directory, `bugs index --check` and `bugs check` read the index as orphaned.
    audits = ledger_path(p.bugs, BUG_AUDITS)
    footprint = (
        _template("ledger-audits", f"{audits}/README.md", "audits-readme.md"),
        _computed("bug-index", p.bug_index, lambda: render_index([], bug_register(config))),
        _template("roadmap", p.roadmap, "roadmap.md"),
        _template("trail", trail_target(config), "trail.toml"),
    )
    could_write: dict[str, set[str]] = {}
    for template in (*once, *footprint):
        could_write.setdefault(template.id, set()).add(template.target)
    prepared = Prepared(
        once,
        footprint,
        {},
        could_write={artifact_id: frozenset(t) for artifact_id, t in could_write.items()},
    )
    _no_file_of_another(prepared)
    return prepared
