"""The shipped files, and the `Template`s a configuration produces from them."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, preset_defaults
from stayfixed.config.schema import BRANCH_NAME, Config
from stayfixed.errors import Failure, Refusal
from stayfixed.project.api import PROJECT_FILES, project_templates
from stayfixed.project.templates import IGNORE_ARTIFACT, ONE_FILE, OWN_NAME, PATH_KEYS, read
from stayfixed.scaffold import Kind, Style, Template, upsert
from stayfixed.templates import tree
from tests.gitfixture import needs_git, run_git

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n'


def _prepared(config: Config) -> tuple[Template, ...]:
    return project_templates(config, document=DOCUMENT)


def test_every_declared_file_exists_and_no_file_is_undeclared_at_any_depth() -> None:
    # `rglob`, not `iterdir`: a stray file in a subdirectory would ship in the wheel unseen.
    root = tree("project")
    assert root.is_dir()
    present = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert present == sorted(PROJECT_FILES)


def test_every_artifact_is_create_once_but_the_ignore_region() -> None:
    # What makes a second `init` write what is missing and touch nothing else: a file already at
    # an artifact's place is never looked inside, and the region is rewritten in place.
    prepared = _prepared(preset_defaults("widget"))
    assert {t.id: t.kind for t in prepared} == {
        "config": Kind.ONCE,
        "roadmap": Kind.ONCE,
        "trail": Kind.ONCE,
        "gitignore": Kind.MANAGED_REGION,
    }
    assert {t.id: t.render() for t in prepared}["config"] == DOCUMENT


def test_targets_follow_the_configured_paths_and_not_the_preset() -> None:
    config = preset_defaults("widget")
    moved = replace(config, paths=replace(config.paths, roadmap="docs/plan/roadmap.md"))
    by_id = {t.id: t for t in _prepared(moved)}
    assert by_id["roadmap"].target == "docs/plan/roadmap.md"
    assert by_id["trail"].target == "docs/plan/trail.toml"


def test_no_two_artifacts_resolve_to_the_same_file() -> None:
    """`scaffold.engine.plan` has no duplicate-target detection, so with two `[paths]` keys aimed
    at one file the plan reported no refusal, `apply` wrote both, and the file held only the second
    artifact's bytes. Measured on an earlier tree, with two artifacts at `docs/x.md`: the file
    began with the second's heading, and the first's was gone.

    Mutation (oracle): `mutations/`'s "an artifact may target a file another artifact is built to
    write" -> no refusal, and every case reddens; "places are compared case-sensitively for
    ownership" -> the case-variant case does.
    """
    config = preset_defaults("widget")
    footprint_clash = replace(config, paths=replace(config.paths, roadmap=".gitignore"))
    with pytest.raises(Refusal) as caught:
        _prepared(footprint_clash)
    message = str(caught.value)
    assert message == ONE_FILE.format(
        first="roadmap",
        first_key="paths.roadmap",
        second="gitignore",
        second_key=OWN_NAME,
    )
    # The colliding value is the repository's own bytes and is named nowhere.
    assert ".gitignore" not in message
    # One file where case folds, as on the default macOS and Windows filesystems, so one file
    # here on every filesystem.
    variant = replace(config, paths=replace(config.paths, roadmap=".GitIgnore"))
    with pytest.raises(Refusal) as caught:
        _prepared(variant)
    assert str(caught.value) == message
    # The roadmap on `stayfixed.toml`.
    across = replace(config, paths=replace(config.paths, roadmap=CONFIG_FILE))
    with pytest.raises(Refusal) as caught:
        _prepared(across)
    assert str(caught.value) == ONE_FILE.format(
        first="config", first_key=OWN_NAME, second="roadmap", second_key="paths.roadmap"
    )


# The `.gitignore` region as a project carries it, copied from the smoke fixture's `.gitignore`
# and never read back from the code that writes it: `init` rewrites the region in place, so a
# change to these bytes rewrites every project's `.gitignore` on its next run.
IGNORE_BLOCK = (
    "# stayfixed:ignore:begin\n"
    "# stayfixed's local state: yours, never a collaborator's.\n"
    ".stayfixed/local/\n"
    "# stayfixed:ignore:end\n"
)


def test_the_ignore_block_init_writes_is_the_block_a_project_carries() -> None:
    # Held to the bytes a project already carries, into an empty file, and as a hash-style region
    # in the file git reads.
    template = {t.id: t for t in _prepared(preset_defaults("widget"))}[IGNORE_ARTIFACT]
    assert template.kind is Kind.MANAGED_REGION and template.style is Style.HASH
    assert template.region is not None
    assert upsert("", template.region, template.render(), template.style) == IGNORE_BLOCK
    assert (ROOT / "tests/fixtures/smoke-project/.gitignore").read_text("utf-8") == IGNORE_BLOCK


def test_every_artifact_init_builds_has_a_paths_key_recorded_for_it() -> None:
    """The anti-drift half of `PATH_KEYS`: an artifact added without a line there would reach a
    `KeyError` only once somebody's configuration happened to collide, which is the worst moment
    for this module to raise something other than its own refusal."""
    ids = {t.id for t in _prepared(preset_defaults("widget"))}
    # The walk is stated non-empty first, and at its full size: a build of nothing would make the
    # comparison below vacuous in both directions.
    assert len(ids) == 4, sorted(ids)
    assert ids == set(PATH_KEYS), (sorted(ids ^ set(PATH_KEYS)),)


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
