"""The project footprint as `Template`s, built from a configuration.

Under the module root beside `templates/overlay/` and resolved by `stayfixed.templates.tree`, the
one resolver both shipped trees go through. The three write-once files are `Kind.ONCE`
artifacts in a pass of their own, because two artifacts cannot target one file in one pass;
everything else is the footprint pass. Every target is a `config.paths` value, which the
loader has bounded to `PATH_VALUE` and contained; what this module adds is a file name under
it.

This module builds templates and decides nothing about a manifest. What `[artifacts] local` may
not move out of git, and the order of the footprint pass, are the policy `init` applies to what it
builds, and they are `project.footprint`'s.

**Every write-once file this renders answers to the configuration, including the two that look
like fixed text.** `CLAUDE.md` is a one-line pointer and its one line is `[paths] agents_md`: it
was the literal `@AGENTS.md`, so a project that renamed the instruction file got a pointer at a
file that was not there and a `docs check` that passed anyway, and every session in it followed
the dangling pointer. The skeleton's budget sentence is the same shape — it states the numbers
`stayfixed docs check` enforces, so it is filled from `Budgets.effective` rather than from three
literals copied out of the preset.

"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cached_property, partial
from typing import TYPE_CHECKING

from stayfixed.config.layout import IGNORE_BODY, IGNORE_REGION, rules_file
from stayfixed.config.loader import CONFIG_FILE
from stayfixed.config.schema import Config, Paths
from stayfixed.docs.api import trail_target
from stayfixed.errors import Failure, Refusal
from stayfixed.fsops import path_key
from stayfixed.ledger.api import BUG_AUDITS, BUG_RUNBOOK, bug_register, ledger_path, render_index
from stayfixed.project.layout import PROJECT_FILES
from stayfixed.scaffold import Kind, Style, Template, validate_sources
from stayfixed.templates import tree

if TYPE_CHECKING:
    from stayfixed.profiles import Profile

PROJECT = "project"
# The provenance namespace for an artifact whose bytes this module *computes*, so that a record
# of one never claims a file the wheel does not carry.
#
# `Template.source` becomes `Record.template` in `.stayfixed/manifest.json`, which is committed and
# is where a reader finds out where an artifact's bytes came from. Three artifacts
# here have no shipped file at all — `config` is the rendered document, `bug-index` is
# `render_index([], bug_register(config))`, `gitignore` is `IGNORE_BODY` — and all three recorded
# `project/<id>`, a name absent from `PROJECT_FILES` and from the tree, which `read` itself
# refuses. Nothing broke today only because each one overrides `render`; the committed fixture's
# manifest carried `"template": "project/gitignore"`, a pointer at nothing, for as long as it has
# existed.
#
# A separate namespace rather than a name that looks readable: "there is no shipped file, these
# bytes are built" is the honest answer, and a reader — a person, `doctor` — can tell
# it from `project/roadmap.md` without asking the wheel. It stays one string, so the manifest
# format is untouched. `_computed` is the only place it is spelled, and
# `tests/project/test_templates.py` holds every source both passes build to one rule or the other.
COMPUTED = "computed"
# The provenance namespace for an artifact whose bytes are a shipped profile's file:
# `profile/<name>/rules.md` names a file the wheel carries under `stayfixed/profiles/`.
PROFILE = "profile"
CLAUDE_MD = "CLAUDE.md"
HARNESS_REGION = "harness"
# The two artifact ids a command's own rules name, spelled once: neither may be kept out of git.
# An id is also what every initialised repository's committed manifest records, so neither is
# renamed lightly: `tests/project/test_templates.py` holds both to the ids the templates build.
CONFIG_ARTIFACT = "config"
IGNORE_ARTIFACT = "gitignore"
_SENTINEL = re.compile(r"%%[A-Z_]+%%")


# Which `[paths]` key each artifact's target is built from, so the collision refusal below can
# name what to edit. Two statements of one thing, the way `PROJECT_FILES` and the shipped tree
# are: `tests/project/test_templates.py` holds this mapping's key set to the artifact ids both
# passes actually produce, so an artifact added without a line here reddens rather than being
# named by the wrong key at the moment somebody's configuration collides. A harness's rendition
# is not listed: its target is the harness's own fixed name, which is what the refusal calls an
# id with no row (`OWN_NAME`), so a harness added to the registry needs no line here.
OWN_NAME = "a fixed name of stayfixed's own"
PATH_KEYS = {
    CONFIG_ARTIFACT: OWN_NAME,
    "agents-skeleton": "paths.agents_md",
    "claude-md": OWN_NAME,
    "documentation-policy": "paths.architecture",
    "adr-template": "paths.adr",
    "ledger-runbook": "paths.runbooks",
    "ledger-audits": "paths.bugs",
    "bug-index": "paths.bug_index",
    "roadmap": "paths.roadmap",
    "roadmap-history": "paths.roadmap_history",
    "trail": "paths.roadmap",
    "specs-keep": "paths.specs",
    "plans-keep": "paths.plans",
    IGNORE_ARTIFACT: OWN_NAME,
    "agents-md": "paths.agents_md",
    "profile-rules": "paths.stayfixed",
}
# The whole files a project may keep out of git, under `.stayfixed/local/artifacts/`, with every
# gate still passing (`tests/project/test_answer_flags.py` runs every gate with each one kept).
# `init --questions` offers exactly these and `init --yes --local` takes only these. Every other
# artifact is read at its committed path by a gate (`bug-index`, `ledger-audits`, `roadmap`,
# `trail`), has no purpose outside git (the two `.gitkeep` files), works only at the root
# (`config`, `gitignore`), or is read where it is committed (`CLAUDE.md`, the `AGENTS.md`
# skeleton and its region, the workflow, the profile's rules and each harness's pointer to
# them); `docs/cli.md`'s `--local` paragraph says the same to a person.
LOCAL_ELIGIBLE = ("documentation-policy", "adr-template", "ledger-runbook", "roadmap-history")
# The one pair of artifacts built to share a file, and the one exception `Owners` makes.
SHARED_FILE = frozenset({"agents-skeleton", "agents-md"})
# Fixed text with two artifact ids and two `[paths]` key names interpolated — all four are
# stayfixed's own vocabulary. The colliding path is a repository-authored value and is not printed.
ONE_FILE = (
    "{first} ({first_key}) and {second} ({second_key}) resolve to one file, and only the "
    "AGENTS.md skeleton and its region share a file by design: any other pair would have one "
    "artifact judged, overwritten or removed as the other. Separate them under [paths] in "
    "stayfixed.toml, then run the command again"
)


@dataclass(frozen=True)
class Owners:
    """Which artifacts this build is built to write each place: the one relation both rules that
    ask "whose file is this?" read, so they cannot come apart.

    **The relation.** `could_write` is `Prepared.could_write`: for each artifact id, every target
    this build could produce for it under any configuration — this run's templates, every shipped
    profile's rules and each harness's rendition of them.
    A place is `foreign` to an id when another id is built to write it. Which ids exist and where
    each could write are this build's; the `[paths]` values those places are built from are
    committed, and all a value can do here is add a place, never take one away. Places are one
    file when `fsops.path_key` says so, as on the default filesystems of macOS and Windows, so
    `roadmap = "claude.md"` is `CLAUDE.md`'s file on every filesystem and every rule below reddens
    on Linux as on macOS.

    **The one exception is `SHARED_FILE`**, and it is how the build is made: the `AGENTS.md`
    skeleton, written once, and the region every later run refreshes inside it, both built from
    `[paths] agents_md`, share a file by design, which is the reason there are two passes. Nothing
    a repository writes makes another pair: a place two other ids reach because committed values
    coincide is foreign to both.

    **The collision refusal** (`_no_file_of_another`) refuses a template at a place foreign to its
    id, in either pass, before anything is planned. Within one pass: `scaffold.engine.plan` has no
    duplicate-target detection, so with `roadmap` and `roadmap_history` set to one path both plans
    reported zero refusals, `apply` wrote both, the file held only the second artifact's bytes and
    the manifest recorded two different digests for one path — the roadmap's trail block lost,
    one record read as hand-edited for ever, and `uninstall` removing a file that held the other
    artifact; `agents_md = "CLAUDE.md"` collides the same way in the write-once pass. Across the
    passes, and against a file only another configuration builds (another profile's rules, a
    harness's rule this project does not list, the workflow), because that is the same collision
    a run later. The anchor is this module's artifact list, a constant in the installed package;
    the refusal names two ids and their `[paths]` keys so that the remedy is one edit, and never
    the value, which is the repository's bytes.

    **The ledger rule** (`scaffold.engine.left_copies`): an entry of the ledger of files kept out
    of git (`scaffold.local.LocalDigests`) under one id never names a place there foreign to that
    id, which is another artifact's copy, judged under its own id or not at all. The ledger is
    kept out of git and a clone can force-add it anyway. Without the rule, an entry under
    `roadmap` naming the `CLAUDE.md` stayfixed had kept out of git, stamped with the digest of those
    unedited and so predictable bytes, had `upgrade` remove that copy as the roadmap's relocated
    one: `upgrade` plans only the footprint pass, so no template of its plan claimed the file, and
    nothing ever wrote it again. An exception taken from coinciding `[paths]` values instead of
    from `SHARED_FILE` handed `roadmap` that place as soon as `roadmap = "CLAUDE.md"` was committed
    beside the entry; the collision refusal stops that configuration first, and the relation
    withholds the place from both ids anyway. An artifact's own earlier places are in nobody's
    list (a `[paths]` value that moved is a place this configuration no longer builds), so a copy
    it left there is still judged.
    """

    could_write: Mapping[str, frozenset[str]]

    def foreign(self, artifact_id: str, place: str) -> frozenset[str]:
        """Every other artifact built to write `place`, or none when that is `artifact_id`'s
        alone or shared with it only as `SHARED_FILE` shares it."""
        others = frozenset(
            owner
            for owner, places in self.could_write.items()
            if owner != artifact_id and path_key(place) in {path_key(p) for p in places}
        )
        return frozenset() if {artifact_id, *others} <= SHARED_FILE else others


@dataclass(frozen=True)
class Prepared:
    """Both passes, the reasons an artifact was not rendered, and every target this build could
    write for each artifact id under any configuration.

    `could_write` is built at the lines that build the templates, from the same calls, so it
    cannot describe a target the footprint could not have: for the conditional artifacts it holds
    each shipped profile's neutral rules and renditions, whichever of them this configuration asks
    for. `owners` is the relation read from it.
    """

    once: tuple[Template, ...]
    footprint: tuple[Template, ...]
    skipped: dict[str, str]
    could_write: Mapping[str, frozenset[str]]
    # How many names in `[stayfixed] agents` no harness answers to; counted, never quoted.
    unknown_harnesses: int = 0
    # The profile's own artifacts in this footprint. Every reader of them, the `AGENTS.md`
    # pointer and each harness's rule, names the committed path.
    profiled: frozenset[str] = frozenset()

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


def fill(text: str, **values: str) -> str:
    """Replace every `%%KEY%%` sentinel, and refuse a template with one left in it.

    A sentinel that survives would be written into a project's file verbatim — a `uses:` line
    pinned to the literal `%%REF%%`, or an instruction file headed `%%NAME%%`. Refusing costs
    the artifact; writing it costs the project's CI.
    """
    for key, value in values.items():
        text = text.replace(f"%%{key}%%", value)
    left = _SENTINEL.search(text)
    if left is not None:
        raise Failure(f"a template sentinel was left unfilled: {left.group(0)}")
    return text


def _budget(config: Config, name: str) -> str:
    """One budget, rendered the way the skeleton's prose reads it.

    The skeleton tells a project the numbers `stayfixed docs check` will hold it to, and those
    numbers were three literals — the preset's — written into a file `init` renders into somebody
    else's repository. A project that lowers `agents_md_lines` to 250 was handed a document
    stayfixed itself wrote saying 300 was fine, and then failed at 251 by the same tool. So the
    numbers come from `Budgets.effective`, which is the preset lowered by any override, and the
    template carries sentinels instead.

    **Grouped, with `,`.** One rule for all three rather than one per number: the prose this
    replaces read "at most 300 lines and 3,000 words ... under 50 lines", so grouping is what it
    already did, and `format(n, ",")` reproduces those three bytes exactly at the preset's
    defaults. A four-digit budget written bare would read as a different kind of number from the
    one the sentence next to it carries.
    """
    return format(config.budgets.effective(name), ",")


def _bug_ledger_documents(paths: Paths) -> list[Template]:
    """The bug ledger's runbook and audits README, each where its index links it: built from
    `[paths]` and the two names `bug_register` builds those links from, joined as it joins them."""
    runbook = ledger_path(paths.runbooks, BUG_RUNBOOK)
    audits = ledger_path(paths.bugs, BUG_AUDITS)
    return [
        _template("ledger-runbook", runbook, "bug-reports-runbook.md"),
        _template("ledger-audits", f"{audits}/README.md", "audits-readme.md"),
    ]


def _template(
    artifact_id: str,
    target: str,
    name: str,
    *,
    kind: Kind = Kind.TEMPLATE,
    render: Callable[[], str] | None = None,
    region: str | None = None,
    style: Style = Style.MARKDOWN,
) -> Template:
    """An artifact whose bytes begin as `templates/project/<name>`, shipped in the wheel.

    `name` is a `PROJECT_FILES` entry — `read` refuses anything else — and it is also the
    provenance recorded for the artifact. A `render` override here still reads that file and
    fills its sentinels, so the record's `project/<name>` stays true of it; an artifact with no
    shipped file at all is `_computed`'s and not this one's.
    """
    return Template(
        id=artifact_id,
        kind=kind,
        target=target,
        source=f"{PROJECT}/{name}",
        render=render or partial(read, name),
        region=region,
        style=style,
    )


def _computed(
    artifact_id: str,
    target: str,
    render: Callable[[], str],
    *,
    kind: Kind = Kind.TEMPLATE,
    region: str | None = None,
    style: Style = Style.MARKDOWN,
) -> Template:
    """An artifact this module builds, whose provenance therefore names no shipped file.

    A second constructor rather than a flag or a `None` name on `_template`: which artifacts have
    a file in the wheel is decided here, once per artifact, at the line that builds it — and
    every argument of both functions is then total, with no arm that a caller could reach only by
    passing an impossible pair. `render` is required for the same reason: there is nothing to
    fall back to reading.
    """
    return Template(
        id=artifact_id,
        kind=kind,
        target=target,
        source=f"{COMPUTED}/{artifact_id}",
        render=render,
        region=region,
        style=style,
    )


def _profiled(artifact_id: str, target: str, profile: Profile) -> Template:
    """An artifact whose bytes are a shipped profile's file, so its provenance names that file.

    The third constructor beside `_template` and `_computed`, for the reason those two give for
    being two: which namespace an artifact's bytes come from is decided at the line that builds
    it.
    """
    from stayfixed.profiles import RULES_FILE

    return Template(
        id=artifact_id,
        kind=Kind.TEMPLATE,
        target=target,
        source=f"{PROFILE}/{profile.name}/{RULES_FILE}",
        render=lambda: profile.rules,
    )


PROFILE_BLOCK = (
    "\n\nThe `{name}` profile's rules are in `{path}`. Before the first command:\n\n{lines}"
)


def _profile_block(profile: Profile | None, rules: str) -> str:
    """The universal adapter: what every harness reading `AGENTS.md` is handed.

    It opens with the blank line that separates it from the region's paragraph and ends without
    a newline, so a project with no profile renders the region byte for byte as before.
    """
    if profile is None:
        return ""
    lines = "\n".join(f"- {line}" for line in profile.essentials)
    return PROFILE_BLOCK.format(name=profile.name, path=rules, lines=lines)


def _no_file_of_another(prepared: Prepared) -> None:
    """Refuse an artifact of either pass at a place `Owners.foreign` gives another artifact."""
    for template in (*prepared.once, *prepared.footprint):
        others = prepared.owners.foreign(template.id, template.target)
        if not others:
            continue
        second = min(others - SHARED_FILE or others)
        raise Refusal(
            ONE_FILE.format(
                first=template.id,
                first_key=PATH_KEYS.get(template.id, OWN_NAME),
                second=second,
                second_key=PATH_KEYS.get(second, OWN_NAME),
            )
        )


def project_templates(
    config: Config,
    *,
    document: str,
) -> Prepared:
    """The footprint this configuration asks for, split into the engine's two passes.

    Nothing here reads the disk for a target: `trail_target` is a location, like every
    `[paths]`-built target, and the engine contains each one when it plans it. So this can be
    asked about paths no run will use, which `ignored._preset_places` does with the preset's.
    """
    from stayfixed.harnesses import HARNESSES, select
    from stayfixed.profiles import load_profile, shipped

    # The engine's rule first: an unshipped or malformed name is refused naming the grammar and
    # the listing, before `load_profile`'s own refusal, which names neither.
    validate_sources(config)
    # Each shipped profile loaded once: every one is built below for `could_write`, and the
    # configured one, which `validate_sources` has just held to the listing, is one of them.
    loaded = {name: load_profile(name) for name in shipped()}
    profile = loaded[config.stayfixed.profile] if config.stayfixed.profile else None
    rules = rules_file(config, profile.name) if profile is not None else ""
    harnesses, unknown_harnesses = select(config.stayfixed.agents)
    p = config.paths
    once = (
        _computed(CONFIG_ARTIFACT, CONFIG_FILE, lambda: document, kind=Kind.ONCE),
        _template(
            "agents-skeleton",
            p.agents_md,
            "agents-skeleton.md",
            kind=Kind.ONCE,
            render=lambda: fill(
                read("agents-skeleton.md"),
                NAME=config.project.name,
                LINES=_budget(config, "agents_md_lines"),
                WORDS=_budget(config, "agents_md_words"),
                STATUS_LINES=_budget(config, "status_lines"),
            ),
        ),
        _template(
            "claude-md",
            CLAUDE_MD,
            "claude.md",
            kind=Kind.ONCE,
            render=lambda: fill(read("claude.md"), AGENTS_MD=p.agents_md),
        ),
    )
    footprint: list[Template] = [
        _template("documentation-policy", f"{p.architecture}/documentation.md", "documentation.md"),
        _template("adr-template", f"{p.adr}/0000-template.md", "adr-template.md"),
        *_bug_ledger_documents(p),
        _computed("bug-index", p.bug_index, lambda: render_index([], bug_register(config))),
        _template("roadmap", p.roadmap, "roadmap.md"),
        _template("roadmap-history", p.roadmap_history, "roadmap-history.md"),
        _template("trail", trail_target(config), "trail.toml"),
        _template("specs-keep", f"{p.specs}/.gitkeep", "gitkeep"),
        _template("plans-keep", f"{p.plans}/.gitkeep", "gitkeep"),
        _computed(
            IGNORE_ARTIFACT,
            ".gitignore",
            lambda: IGNORE_BODY,
            kind=Kind.MANAGED_REGION,
            region=IGNORE_REGION,
            style=Style.HASH,
        ),
        _template(
            "agents-md",
            p.agents_md,
            "agents-region.md",
            kind=Kind.MANAGED_REGION,
            render=lambda: fill(
                read("agents-region.md"),
                BUG_INDEX=p.bug_index,
                BUGS=p.bugs,
                ROADMAP=p.roadmap,
                SPECS=p.specs,
                PLANS=p.plans,
                PROFILE=_profile_block(profile, rules),
            ),
            region=HARNESS_REGION,
        ),
    ]
    skipped: dict[str, str] = {}
    could_write: dict[str, set[str]] = {}
    profiled: set[str] = set()
    # Every shipped profile's artifacts are built, so `could_write` lists where each could land;
    # only the configured profile's, for the harnesses this project lists, join the footprint.
    for name, candidate in loaded.items():
        candidate_rules = rules_file(config, name)
        built = [(True, _profiled("profile-rules", candidate_rules, candidate))]
        for harness in HARNESSES:
            if harness.render_profile is not None:
                rendition = harness.render_profile(candidate, candidate_rules)
                template = _computed(rendition.artifact_id, rendition.target, rendition.render)
                built.append((harness in harnesses, template))
        for wanted, template in built:
            could_write.setdefault(template.id, set()).add(template.target)
            if wanted and name == config.stayfixed.profile:
                footprint.append(template)
                profiled.add(template.id)
    for template in (*once, *footprint):
        could_write.setdefault(template.id, set()).add(template.target)
    prepared = Prepared(
        once,
        tuple(footprint),
        skipped,
        could_write={artifact_id: frozenset(t) for artifact_id, t in could_write.items()},
        unknown_harnesses=unknown_harnesses,
        profiled=frozenset(profiled),
    )
    _no_file_of_another(prepared)
    return prepared
