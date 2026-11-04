"""The three shipped files, and the `Template` list a configuration produces from them."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, preset_defaults
from stayfixed.config.schema import BRANCH_NAME, Config
from stayfixed.errors import Failure, Refusal
from stayfixed.ledger.api import bug_register, render_index
from stayfixed.project.api import PROJECT_FILES, Prepared, project_templates
from stayfixed.project.templates import (
    COMPUTED,
    CONFIG_ARTIFACT,
    IGNORE_ARTIFACT,
    ONE_FILE,
    OWN_NAME,
    PATH_KEYS,
    PROJECT,
    Owners,
    read,
)
from stayfixed.scaffold import Kind, Style, upsert
from stayfixed.templates import tree
from tests.gitfixture import needs_git, run_git

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n'


def _prepared(config: Config) -> Prepared:
    return project_templates(config, document=DOCUMENT)


def test_every_declared_file_exists_and_no_file_is_undeclared_at_any_depth() -> None:
    # `rglob`, not `iterdir`: a stray file in a subdirectory would ship in the wheel unseen.
    root = tree("project")
    assert root.is_dir()
    present = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert present == sorted(PROJECT_FILES)


def test_the_write_once_artifact_is_once_and_the_rest_are_not() -> None:
    prepared = _prepared(preset_defaults("widget"))
    assert [t.id for t in prepared.once] == ["config"]
    assert all(t.kind is Kind.ONCE for t in prepared.once)
    assert {t.id: t.render() for t in prepared.once}["config"] == DOCUMENT
    assert [t.id for t in prepared.footprint] == [
        "ledger-audits",
        "bug-index",
        "roadmap",
        "trail",
        "gitignore",
    ]
    assert not any(t.kind is Kind.ONCE for t in prepared.footprint)


def test_targets_follow_the_configured_paths_and_not_the_preset() -> None:
    config = preset_defaults("widget")
    moved = replace(
        config,
        paths=replace(config.paths, roadmap="docs/plan/roadmap.md", bug_index="docs/bugs.md"),
    )
    by_id = {t.id: t for t in _prepared(moved).footprint}
    assert by_id["roadmap"].target == "docs/plan/roadmap.md"
    assert by_id["trail"].target == "docs/plan/trail.toml"
    assert by_id["bug-index"].target == "docs/bugs.md"
    assert by_id["bug-index"].render() == render_index([], bug_register(moved))


def test_no_two_artifacts_of_one_pass_resolve_to_the_same_file() -> None:
    """The two-pass design's premise, which nothing made true until the collision refusal.

    `scaffold.engine.plan` has no duplicate-target detection and the scaffold engine's contract is
    frozen, so with two `[paths]` keys aimed at one file both plans reported zero refusals, `apply`
    wrote both, the file held only the second artifact's bytes, and the manifest recorded two
    different `sha256` values for one target. Measured on this tree before the guard, with
    `paths.roadmap = paths.roadmap_history = "docs/x.md"`: `refusals: 0 0`, the manifest held a
    record for `roadmap` and one for `roadmap-history` both naming `docs/x.md` and carrying
    different `sha256` values, the file began `# Roadmap history`, and `"Design and plan trail" in
    body` was `False`. (The two digests are not quoted here: `tests/test_neutral.py`'s
    bare-commit-id arm reads an eight-character hex run as an abbreviated commit id, and it is
    right to — measured, this docstring reddened that gate on its first draft.)

    One refusal holds both passes and the pair across them, read off one relation
    (`templates.Owners`).

    Mutation (oracle): `mutations/`'s "an artifact may target a file another artifact is built to
    write" -> no refusal, and every case reddens; "places are compared case-sensitively for
    ownership" -> the case-variant case does.
    """
    config = preset_defaults("widget")
    footprint_clash = replace(
        config, paths=replace(config.paths, roadmap="docs/x.md", bug_index="docs/x.md")
    )
    with pytest.raises(Refusal) as caught:
        _prepared(footprint_clash)
    message = str(caught.value)
    assert message == ONE_FILE.format(
        first="bug-index",
        first_key="paths.bug_index",
        second="roadmap",
        second_key="paths.roadmap",
    )
    # The colliding value is the repository's own bytes and is named nowhere.
    assert "docs/x.md" not in message
    # One file where case folds, as on the default macOS and Windows filesystems, so one file
    # here on every filesystem.
    variant = replace(
        config, paths=replace(config.paths, roadmap="docs/x.md", bug_index="docs/X.md")
    )
    with pytest.raises(Refusal) as caught:
        _prepared(variant)
    assert str(caught.value) == message
    # Across the passes: the bug index on `stayfixed.toml`.
    across = replace(config, paths=replace(config.paths, bug_index=CONFIG_FILE))
    with pytest.raises(Refusal) as caught:
        _prepared(across)
    assert str(caught.value) == ONE_FILE.format(
        first="config", first_key=OWN_NAME, second="bug-index", second_key="paths.bug_index"
    )


def test_one_relation_says_whose_file_a_place_is() -> None:
    """`Owners` is what the collision refusal reads, so its answers are asked directly: nothing
    shares a place, and a place is one file in any case.

    Mutation (oracle): `mutations/`'s "places are compared case-sensitively for ownership" ->
    `STAYFIXED.TOML` is nobody's.
    """
    owners = _prepared(preset_defaults("widget")).owners
    assert owners.foreign("roadmap", CONFIG_FILE) == {"config"}
    assert owners.foreign("roadmap", "STAYFIXED.TOML") == {"config"}
    assert owners.foreign("config", CONFIG_FILE) == frozenset()
    # A place nobody is built to write is nobody's.
    assert owners.foreign("roadmap", "elsewhere/notes.md") == frozenset()
    # Two ids a configuration put on one place are each other's, in any case.
    placed = Owners({"a": frozenset({"x.md"}), "b": frozenset({"X.md"})})
    assert placed.foreign("a", "x.md") == {"b"}


def test_the_artifact_id_the_manifest_records_is_the_one_the_templates_build() -> None:
    """`CONFIG_ARTIFACT` and `IGNORE_ARTIFACT` are the ids of the templates at `stayfixed.toml` and
    `.gitignore`, and each must stay the string it is: every initialised repository's committed
    manifest records it.

    Mutation (advisory): rename either constant -> the last assertion reddens.
    """
    prepared = project_templates(preset_defaults("widget"), document=DOCUMENT)
    assert {t.id for t in prepared.once if t.target == CONFIG_FILE} == {CONFIG_ARTIFACT}
    assert {t.id for t in prepared.footprint if t.target == ".gitignore"} == {IGNORE_ARTIFACT}
    assert (CONFIG_ARTIFACT, IGNORE_ARTIFACT) == ("config", "gitignore")


# The `.gitignore` region as a project carries it, copied from the smoke fixture's `.gitignore`
# and never read back from the code that writes it: `init` records the region in the manifest by
# its digest, so a change to these bytes is drift on every project that carries it.
IGNORE_BLOCK = (
    "# stayfixed:ignore:begin\n"
    "# stayfixed's local state: yours, never a collaborator's.\n"
    ".stayfixed/local/\n"
    "# stayfixed:ignore:end\n"
)


def test_the_ignore_block_init_writes_is_the_block_a_project_carries() -> None:
    # Held to the bytes a project already carries, into an empty file, and as a hash-style region
    # in the file git reads.
    template = {t.id: t for t in _prepared(preset_defaults("widget")).footprint}[IGNORE_ARTIFACT]
    assert template.kind is Kind.MANAGED_REGION and template.style is Style.HASH
    assert template.region is not None
    assert upsert("", template.region, template.render(), template.style) == IGNORE_BLOCK
    assert (ROOT / "tests/fixtures/smoke-project/.gitignore").read_text("utf-8") == IGNORE_BLOCK


def test_every_artifact_both_passes_build_has_a_paths_key_recorded_for_it() -> None:
    """The anti-drift half of `PATH_KEYS`: an artifact added without a line there would reach a
    `KeyError` only once somebody's configuration happened to collide, which is the worst moment
    for this module to raise something other than its own refusal."""
    prepared = project_templates(preset_defaults("widget"), document=DOCUMENT)
    ids = {t.id for t in (*prepared.once, *prepared.footprint)}
    # The walk is stated non-empty first, and at its full size: a `Prepared` that built nothing
    # would make the comparison below vacuous in both directions.
    assert len(ids) == 6, sorted(ids)
    assert ids == set(PATH_KEYS), (sorted(ids ^ set(PATH_KEYS)),)


def test_every_source_both_passes_build_is_a_shipped_file_or_is_declared_computed() -> None:
    """The same anti-drift rule over `Template.source`, which had no guard and was wrong.

    `source` becomes `Record.template` in `.stayfixed/manifest.json` — committed, and where a
    reader finds out where an artifact's bytes came from. Artifacts recorded `project/config` and
    `project/bug-index`: names `PROJECT_FILES` does not carry, that the wheel does not ship, and
    that `read` refuses by name. Nothing raised, because both build their own bytes — but the
    provenance was a pointer at nothing.

    Two rules: a source is `project/<a file the wheel ships>`; or it is `computed/<artifact id>`
    and this module builds the bytes.

    Mutation (oracle): `_computed`'s source is spelled `f"{PROJECT}/{artifact_id}"` -> the
    computed set's assertion reddens.
    """
    prepared = project_templates(preset_defaults("widget"), document=DOCUMENT)
    sources = {t.id: t.source for t in (*prepared.once, *prepared.footprint)}
    # Non-empty and at full size first, for `PATH_KEYS`' reason: nothing built makes every
    # comparison below true of nothing.
    assert len(sources) == 6, sorted(sources)
    computed = {name for name, source in sources.items() if source.startswith(f"{COMPUTED}/")}
    # As the set and not as a count: an artifact that moved from one rule to the other is exactly
    # the drift this test exists to see, and a count would not see it.
    assert computed == {"config", "bug-index", "gitignore"}
    root = tree(PROJECT)
    for artifact_id, source in sources.items():
        if artifact_id in computed:
            assert source == f"{COMPUTED}/{artifact_id}"
            continue
        area, _, name = source.partition("/")
        assert area == PROJECT and name in PROJECT_FILES, source
        # And the name is a file that is really there: `project/<name>` claims the bytes were
        # read from the wheel.
        assert (root / name).is_file(), source


def test_read_refuses_a_name_this_package_does_not_ship_before_it_joins_it() -> None:
    """The containment check in `read`, which nothing proved either.

    Measured: with `if name not in PROJECT_FILES:` replaced by `if False:`, `tests/project` was
    39 passed. The anchor is `PROJECT_FILES` — a constant in the wheel beside the files it names
    — and the party contained is a caller inside this package, which is why the check is before
    the join and not after: `name` decides which file under the tree is opened.

    Mutation (oracle): the membership check is dropped -> the traversal name reaches
    `read_text` and raises `OSError` instead of this module's own `Failure`.
    """
    for name in ("../../../etc/passwd", "stayfixed.toml", ".", ""):
        with pytest.raises(Failure, match="is not a shipped project template"):
            read(name)
    # And a name it does ship is read, so the check is not simply refusing everything.
    assert read("trail.toml").startswith("# The forward track")


def test_every_target_a_configuration_writes_is_one_its_relation_lists() -> None:
    # `could_write` is the anchor the collision refusal reads: what a configuration writes must be
    # listed by it. So it is built at the lines that build the templates.
    prepared = _prepared(preset_defaults("widget"))
    written = {(t.id, t.target) for t in (*prepared.once, *prepared.footprint)}
    listed = {(i, target) for i, targets in prepared.could_write.items() for target in targets}
    assert written == listed


# Names inside the grammar's character set, each one git's branch-name rules accept or refuse.
BRANCH_NAMES = (
    "main",
    "develop",
    "release/2.0",
    "release/2.x",
    "v1.2.3",
    "feature/a-b_c",
    "a..b",
    "a//b",
    "a/",
    "a.",
    "a.lock",
    "a/b.lock",
    "a.lock/b",
    "a/.b",
    "a/..",
    ".a",
    "-a",
    "HEAD",
    "a/HEAD",
    "HEADS",
)


@needs_git
@pytest.mark.parametrize("name", BRANCH_NAMES)
def test_the_gate_branch_grammar_refuses_what_git_refuses(tmp_path: Path, name: str) -> None:
    # `--base-branch`, a detected `origin/HEAD` and the loaded `[project]` branches are all held
    # to `BRANCH_NAME`; a name git itself refuses as a branch (`a..b`, `a//b`, a trailing `/` or
    # `.`, a `.lock` component, a component starting with `.`, the name `HEAD`) is a branch no
    # repository can have, so the grammar refuses it too, and `release/2.0` and `a/HEAD` stay
    # legal. Mutations (oracle): `mutations/`'s "the gate branch grammar takes a '..' git
    # refuses", "the gate branch grammar takes a '.lock' component git refuses" and "the gate
    # branch grammar takes the name HEAD git refuses" -> the `a..b`, `.lock` and `HEAD` cases
    # redden.
    accepted = run_git(tmp_path, "check-ref-format", "--branch", name).returncode == 0
    assert bool(BRANCH_NAME.match(name)) == accepted, name
