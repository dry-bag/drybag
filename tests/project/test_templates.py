"""The eleven shipped files, and the `Template` list a configuration produces from them."""

from __future__ import annotations

import posixpath
import re
from dataclasses import replace
from importlib import resources
from pathlib import Path

import pytest

from stayfixed.config.layout import IGNORE_BODY, IGNORE_REGION
from stayfixed.config.loader import CONFIG_FILE, preset_defaults
from stayfixed.config.schema import BRANCH_NAME, Config
from stayfixed.errors import Failure, Refusal
from stayfixed.harnesses import HARNESSES
from stayfixed.ledger.api import BUG_AUDITS, BUG_RUNBOOK, bug_register, render_index
from stayfixed.profiles import load_profile
from stayfixed.project.api import PROJECT_FILES, Prepared, project_templates
from stayfixed.project.footprint import LOCAL_PROFILE, refuse_local_profile
from stayfixed.project.templates import (
    COMPUTED,
    CONFIG_ARTIFACT,
    IGNORE_ARTIFACT,
    LOCAL_ELIGIBLE,
    ONE_FILE,
    OWN_NAME,
    PATH_KEYS,
    PROFILE,
    PROJECT,
    SHARED_FILE,
    Owners,
    fill,
    read,
)
from stayfixed.scaffold import Kind, Style, upsert
from stayfixed.templates import tree
from tests.gitfixture import needs_git, run_git

DOCUMENT = '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n'


def _prepared(config: Config) -> Prepared:
    return project_templates(config, document=DOCUMENT)


def test_every_declared_file_exists_and_no_file_is_undeclared_at_any_depth() -> None:
    # `rglob`, not `iterdir`: a stray file in a subdirectory would ship in the wheel unseen.
    root = tree("project")
    assert root.is_dir()
    present = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert present == sorted(PROJECT_FILES)


def test_the_three_write_once_artifacts_are_once_and_the_rest_are_not() -> None:
    prepared = _prepared(preset_defaults("widget"))
    assert [t.id for t in prepared.once] == ["config", "agents-skeleton", "claude-md"]
    assert all(t.kind is Kind.ONCE for t in prepared.once)
    assert {t.id: t.render() for t in prepared.once}["config"] == DOCUMENT
    assert "# widget" in {t.id: t.render() for t in prepared.once}["agents-skeleton"]
    assert not any(t.kind is Kind.ONCE for t in prepared.footprint)


def test_the_claude_md_pointer_names_the_configured_instruction_file() -> None:
    """The rendered bytes, not the template's: the pointer is one line and that line is a path.

    `claude.md` shipped as the literal `@AGENTS.md` and was built with no `render` override, so
    `[paths] agents_md = "CONTEXT.md"` produced `CLAUDE.md` pointing at a file the run did not
    write, `CONTEXT.md` beside it, and a `stayfixed docs check` that passed — every Claude Code
    session in that project following a dangling pointer, with nothing anywhere saying so.

    Mutation (oracle): `AGENTS_MD=p.agents_md` -> `AGENTS_MD=CLAUDE_MD` -> the pointer names the
    pointer and the renamed case reddens. The self-pointer that mutation writes is one the
    collision refusal (`templates.Owners`) refuses when a repository asks for it, so this is the
    only way to reach it.
    """
    config = preset_defaults("widget")
    by_id = {t.id: t for t in _prepared(config).once}
    assert by_id["claude-md"].render() == "@AGENTS.md\n"
    moved = replace(config, paths=replace(config.paths, agents_md="CONTEXT.md"))
    renamed = {t.id: t for t in _prepared(moved).once}
    # The pointer and the file the skeleton is written to are one path, asserted together: a
    # pointer that merely changed would still be wrong if it named something else.
    assert renamed["claude-md"].render() == "@CONTEXT.md\n"
    assert renamed["agents-skeleton"].target == "CONTEXT.md"
    assert "%%" not in renamed["claude-md"].render()


def test_the_skeleton_states_the_budgets_this_project_will_be_held_to() -> None:
    """The rendered bytes again, and the numbers are `Budgets.effective`'s and not the preset's.

    The three numbers were literals in the shipped template — 300, 3,000 and 50, the preset's
    own. A project that lowered `agents_md_lines` to 250 received a document stayfixed wrote
    telling it 300 was fine, and `stayfixed docs check` then failed the same document at 251.
    Nothing held the literals to the preset, so nothing could see them drift either.

    Mutation (oracle): `LINES=_budget(config, "agents_md_lines")` ->
    `LINES=_budget(config, "agents_md_words")` -> the lowered case reddens.
    """
    config = preset_defaults("widget")
    body = {t.id: t for t in _prepared(config).once}["agents-skeleton"].render()
    assert "at most 300\nlines and 3,000 words" in body and "below at most 50 lines" in body
    # A configured budget is the one in force, lowered or raised, so the rendered sentence follows
    # the value both ways -- `effective`'s rule, read through the file that states it.
    # `agents_md_words` is left at the preset in the same case, so a fill that took one number for
    # all three cannot pass.
    moved = replace(
        config,
        budgets=replace(config.budgets, configured={"agents_md_lines": 250, "status_lines": 999}),
    )
    body = {t.id: t for t in _prepared(moved).once}["agents-skeleton"].render()
    assert "at most 250\nlines and 3,000 words" in body and "below at most 999 lines" in body
    assert "300" not in body and "at most 50 " not in body and "%%" not in body


def test_targets_follow_the_configured_paths_and_not_the_preset() -> None:
    config = preset_defaults("widget")
    moved = replace(
        config,
        paths=replace(
            config.paths,
            specs="docs/design/specs",
            plans="docs/design/plans",
            roadmap="docs/plan/roadmap.md",
        ),
    )
    by_id = {t.id: t for t in _prepared(moved).footprint}
    assert by_id["specs-keep"].target == "docs/design/specs/.gitkeep"
    assert by_id["trail"].target == "docs/plan/trail.toml"
    assert by_id["gitignore"].kind is Kind.MANAGED_REGION
    assert by_id["gitignore"].region == IGNORE_REGION
    assert by_id["gitignore"].style is Style.HASH and by_id["gitignore"].render() == IGNORE_BODY
    assert by_id["agents-md"].region == "harness"
    assert "docs/plan/roadmap.md" in by_id["agents-md"].render()
    assert by_id["bug-index"].render() == render_index([], bug_register(moved))


def test_init_writes_the_runbook_and_audits_readme_where_the_bug_index_links_them() -> None:
    # The index `init` writes links the runbook and the audits directory, so the two files `init`
    # writes beside it are found where it links them, on a layout where every path moved.
    # Mutation (oracle): the audits README written under a directory the register does not name
    # -> its link resolves to nothing `init` wrote.
    config = preset_defaults("widget")
    moved = replace(
        config,
        paths=replace(
            config.paths, bugs="ledger/entries", bug_index="ledger/INDEX.md", runbooks="guides"
        ),
    )
    by_id = {t.id: t for t in _prepared(moved).footprint}
    preamble = by_id["bug-index"].render().split("\n## ", 1)[0]
    directory = posixpath.dirname(by_id["bug-index"].target)
    linked = {
        posixpath.normpath(f"{directory}/{link}") for link in re.findall(r"\]\(([^)]+)\)", preamble)
    }
    assert by_id["ledger-runbook"].target == "guides/bug-reports.md"
    assert by_id["ledger-audits"].target == "ledger/entries/audits/README.md"
    assert by_id["ledger-runbook"].target in linked
    assert posixpath.dirname(by_id["ledger-audits"].target) in linked


def test_the_runbook_and_audits_readme_take_their_names_from_the_bug_ledgers_register() -> None:
    # The register links the runbook and the audits directory, and `init` writes both files; the
    # two names live once, beside the register, so neither side can be respelled alone and no
    # target is built from a link a register may leave unset. Mutations (oracle): `mutations/`'s
    # "init writes the runbook where the bug index does not link it" and "init writes the audits
    # README under a directory the bug index does not link" -> the equalities below redden.
    config = preset_defaults("widget")
    moved = replace(config, paths=replace(config.paths, bugs="ledger", runbooks="guides"))
    ledger = bug_register(moved)
    by_id = {t.id: t for t in _prepared(moved).footprint}
    assert ledger.runbook == f"guides/{BUG_RUNBOOK}" == by_id["ledger-runbook"].target
    assert ledger.audits == BUG_AUDITS
    assert by_id["ledger-audits"].target == f"ledger/{BUG_AUDITS}/README.md"


# The `.gitignore` region as a project carries it, copied from the smoke fixture's `.gitignore`
# and never read back from the code that writes it: `init` records the region in the manifest by
# its digest, so a change to these bytes is a change every `upgrade` reports as drift.
IGNORE_BLOCK = (
    "# stayfixed:ignore:begin\n"
    "# stayfixed's local state: yours, never a collaborator's.\n"
    ".stayfixed/local/\n"
    ".stayfixed/assessment.json\n"
    "# stayfixed:ignore:end\n"
)


def test_the_ignore_block_init_writes_is_the_block_a_project_carries() -> None:
    # `init` records the region in the manifest by its digest, so a change to its bytes is drift
    # every `upgrade` reports on every project that carries it. Held to the bytes a project
    # already carries, into an empty file. Mutation (declared): `mutations/`'s "the ignore block's
    # note changes under its writer".
    template = {t.id: t for t in _prepared(preset_defaults("widget")).footprint}[IGNORE_ARTIFACT]
    assert template.region is not None
    assert upsert("", template.region, template.render(), template.style) == IGNORE_BLOCK


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

    Both passes, because the write-once pass collides too — `paths.agents_md = "CLAUDE.md"` puts
    the skeleton and the pointer on one file. One refusal holds both passes and the pair across
    them, read off one relation (`templates.Owners`); a guard of its own for one pass, which this
    test used to pin, was shadowed by it and is gone.

    Mutation (oracle): `mutations/`'s "an artifact may target a file another artifact is built to
    write" -> no refusal, and every case reddens; "places are compared case-sensitively for
    ownership" -> the case-variant case does.
    """
    config = preset_defaults("widget")
    footprint_clash = replace(
        config, paths=replace(config.paths, roadmap="docs/x.md", roadmap_history="docs/x.md")
    )
    with pytest.raises(Refusal) as caught:
        _prepared(footprint_clash)
    message = str(caught.value)
    assert message == ONE_FILE.format(
        first="roadmap",
        first_key="paths.roadmap",
        second="roadmap-history",
        second_key="paths.roadmap_history",
    )
    # The colliding value is the repository's own bytes and is named nowhere.
    assert "docs/x.md" not in message
    # One file where case folds, as on the default macOS and Windows filesystems, so one file
    # here on every filesystem.
    variant = replace(
        config, paths=replace(config.paths, roadmap="docs/x.md", roadmap_history="docs/X.md")
    )
    with pytest.raises(Refusal) as caught:
        _prepared(variant)
    assert str(caught.value) == message

    once_clash = replace(config, paths=replace(config.paths, agents_md="CLAUDE.md"))
    with pytest.raises(Refusal) as caught:
        _prepared(once_clash)
    assert str(caught.value) == ONE_FILE.format(
        first="agents-skeleton",
        first_key="paths.agents_md",
        second="claude-md",
        second_key=OWN_NAME,
    )


def test_one_relation_says_whose_file_a_place_is_and_excepts_only_the_agents_md_pair() -> None:
    """`Owners` is what both the collision refusal and the ledger rule read, so its answers are
    asked directly: the designed pair shares `AGENTS.md` and nothing else shares anything, a
    place is one file in any case.

    Mutations (oracle): `mutations/`'s "the AGENTS.md skeleton and its region stop sharing a file by
    design" -> the pair's place is foreign to each; "places are compared case-sensitively for
    ownership" -> `claude.md` is nobody's.
    """
    owners = _prepared(preset_defaults("widget")).owners
    assert owners.foreign("agents-md", "AGENTS.md") == frozenset()
    assert owners.foreign("agents-skeleton", "AGENTS.md") == frozenset()
    assert owners.foreign("roadmap", "AGENTS.md") == SHARED_FILE
    assert owners.foreign("roadmap", "CLAUDE.md") == {"claude-md"}
    assert owners.foreign("roadmap", "claude.md") == {"claude-md"}
    assert owners.foreign("claude-md", "CLAUDE.md") == frozenset()
    # A place nobody is built to write is nobody's.
    assert owners.foreign("roadmap", "elsewhere/notes.md") == frozenset()
    # Two ids a configuration put on one place are each other's, in any case.
    placed = Owners({"a": frozenset({"x.md"}), "b": frozenset({"X.md"})})
    assert placed.foreign("a", "x.md") == {"b"}


def test_the_artifact_ids_the_commands_name_are_the_ones_the_templates_build() -> None:
    """`CONFIG_ARTIFACT` and `IGNORE_ARTIFACT` are what the placement refusals name an artifact
    by. Each must be the id of the
    template at its own place, and each must stay the string it is: every initialised
    repository's committed manifest records it, and `attach`'s `detach` reads the ignore region's
    record by that literal, since the attach area imports nothing from this one.

    Mutation (advisory): rename a constant -> the last assertion reddens.
    """
    prepared = project_templates(preset_defaults("widget"), document=DOCUMENT)
    built = (*prepared.once, *prepared.footprint)
    assert {t.id for t in prepared.once if t.target == CONFIG_FILE} == {CONFIG_ARTIFACT}
    assert {t.id for t in built if t.region == IGNORE_REGION} == {IGNORE_ARTIFACT}
    assert {t.target for t in built if t.id == IGNORE_ARTIFACT} == {".gitignore"}
    assert (CONFIG_ARTIFACT, IGNORE_ARTIFACT) == ("config", "gitignore")


def test_every_artifact_both_passes_build_has_a_paths_key_recorded_for_it() -> None:
    """The anti-drift half of `PATH_KEYS`: an artifact added without a line there would reach a
    `KeyError` only once somebody's configuration happened to collide, which is the worst moment
    for this module to raise something other than its own refusal."""
    prepared = project_templates(_python(tuple(h.name for h in HARNESSES)), document=DOCUMENT)
    ids = {t.id for t in (*prepared.once, *prepared.footprint)}
    # The walk is stated non-empty first, and at its full size: a `Prepared` that built nothing
    # would make the comparison below vacuous in both directions. A harness's rendition has no
    # row in `PATH_KEYS`; its id is asked of the registry, so a harness added there is covered
    # here with no edit.
    assert len(ids) == 16 + len(_renditions()), sorted(ids)
    expected = set(PATH_KEYS) | _renditions()
    assert ids == expected, (sorted(ids ^ expected),)


def test_every_id_offered_as_local_is_a_whole_file_of_the_footprint_pass() -> None:
    # `init --questions` offers these ids as files a project may keep out of git; one that named
    # no artifact, a write-once file or a region inside a host file would be an answer the
    # engine could not act on. Mutation (oracle): a typo in one id -> it is in no `PATH_KEYS` row
    # and this reddens.
    footprint = {t.id: t for t in _prepared(preset_defaults("widget")).footprint}
    assert LOCAL_ELIGIBLE
    for artifact_id in LOCAL_ELIGIBLE:
        assert artifact_id in PATH_KEYS, artifact_id
        assert footprint[artifact_id].kind is Kind.TEMPLATE, artifact_id


def test_every_source_both_passes_build_is_a_shipped_file_or_is_declared_computed() -> None:
    """The same anti-drift rule over `Template.source`, which had no guard and was wrong.

    `source` becomes `Record.template` in `.stayfixed/manifest.json` — committed, and where a
    reader finds out where an artifact's bytes came from. Three artifacts recorded
    `project/config`, `project/bug-index` and `project/gitignore`: names `PROJECT_FILES` does not
    carry, that the wheel does not ship, and that `read` refuses by name. Nothing raised, because
    all three build their own bytes — but the provenance was a pointer at nothing, and the
    committed smoke fixture's manifest has carried `"template": "project/gitignore"` for as long
    as it has existed.

    Three rules: a source is `project/<a file the wheel ships>`; or it is
    `computed/<artifact id>` and this module or a harness builds the bytes; or it is
    `profile/<name>/<a file that profile ships>`.

    Mutation (oracle): `_computed`'s source is spelled `f"{PROJECT}/{artifact_id}"` -> the
    computed set's assertion reddens, and so does the fixture module's provenance assertion.
    """
    prepared = project_templates(_python(tuple(h.name for h in HARNESSES)), document=DOCUMENT)
    sources = {t.id: t.source for t in (*prepared.once, *prepared.footprint)}
    # Non-empty and at full size first, for `PATH_KEYS`' reason: nothing built makes every
    # comparison below true of nothing.
    assert len(sources) == 16 + len(_renditions()), sorted(sources)
    computed = {name for name, source in sources.items() if source.startswith(f"{COMPUTED}/")}
    # As the set and not as a count: an artifact that moved from one rule to the other is exactly
    # the drift this test exists to see, and a count would not see it.
    assert computed == {"config", "bug-index", "gitignore"} | _renditions()
    root = tree(PROJECT)
    for artifact_id, source in sources.items():
        if artifact_id in computed:
            assert source == f"{COMPUTED}/{artifact_id}"
            continue
        if source.startswith(f"{PROFILE}/"):
            _, name, file = source.split("/")
            assert (resources.files("stayfixed.profiles") / name / file).is_file(), source
            continue
        area, _, name = source.partition("/")
        assert area == PROJECT and name in PROJECT_FILES, source
        # And the name is a file that is really there: `project/<name>` claims the bytes were
        # read from the wheel, and the three names above could never have been read at all.
        assert (root / name).is_file(), source


def test_a_template_sentinel_left_unfilled_costs_the_artifact_rather_than_shipping() -> None:
    """`fill` refuses text still carrying a `%%KEY%%`, and nothing proved it did.

    Measured: with `left = _SENTINEL.search(text)` replaced by `left = None`, `tests/project`
    was 39 passed — so the guard whose absence puts `# %%NAME%%` at the head of the file every
    session loads was executed by the suite and asserted by none of it.

    The sentinel's own name prints: it is a string from a template this package ships, which is
    stayfixed's own text and not a repository's. The names below are deliberately *not* ones this
    package ships — the subject is any unfilled sentinel, not the two real ones.

    Mutation (oracle): the search is made to answer `None` -> the first assertion reddens.
    """
    assert fill("a %%ONE%% b", ONE="1") == "a 1 b"
    with pytest.raises(Failure, match=re.escape("%%SHA%%")):
        fill("uses: x/check.yml@%%SHA%%")
    # Filling one and leaving the other is the real shape of the fault: a `fill` call that has
    # grown a sentinel its caller does not pass yet.
    with pytest.raises(Failure, match=re.escape("%%GATE_BRANCH%%")):
        fill("@%%SHA%% on %%GATE_BRANCH%%", SHA="a" * 40)


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
    assert read("claude.md") == "@%%AGENTS_MD%%\n"


def _python(agents: tuple[str, ...] = ("claude", "codex")) -> Config:
    config = preset_defaults("widget")
    return replace(config, stayfixed=replace(config.stayfixed, profile="python", agents=agents))


def _renditions() -> set[str]:
    """Every harness rendition's artifact id, asked of the registry."""
    profile = load_profile("python")
    return {
        h.render_profile(profile, "rules.md").artifact_id
        for h in HARNESSES
        if h.render_profile is not None
    }


def test_a_profile_lands_once_neutrally_and_once_per_adapted_harness() -> None:
    by_id = {t.id: t for t in _prepared(_python()).footprint}
    assert by_id["profile-rules"].target == "docs/stayfixed/rules/python.md"
    assert by_id["profile-rules"].source == "profile/python/rules.md"
    assert by_id["profile-rules"].render() == load_profile("python").rules
    assert by_id["claude-rules"].target == ".claude/rules/stayfixed-python.md"
    assert by_id["claude-rules"].source == "computed/claude-rules"
    assert "`docs/stayfixed/rules/python.md`" in by_id["claude-rules"].render()


def test_a_harness_not_listed_gets_no_file_of_its_own() -> None:
    ids = {t.id for t in _prepared(_python(agents=("codex",))).footprint}
    assert "profile-rules" in ids and "claude-rules" not in ids


def test_a_profile_artifact_kept_out_of_git_is_refused() -> None:
    """The `AGENTS.md` pointer and the Claude rule read `profile-rules` at its committed path;
    kept local it lands under `.stayfixed/local/artifacts/`, and both point at nothing (a review
    reproduced all three files). Mutation (declared): the refusal's condition dropped -> this
    reddens.
    """
    config = _python()
    refuse_local_profile(_prepared(config), config)
    for local in (("profile-rules",), ("claude-rules",), ("profile-rules", "roadmap")):
        kept = replace(config, artifacts=replace(config.artifacts, local=local))
        with pytest.raises(Refusal, match=re.escape(LOCAL_PROFILE.format(count=1))):
            refuse_local_profile(_prepared(kept), kept)


def test_the_region_hands_every_harness_the_pointer_and_the_essentials() -> None:
    # Advisory output, so its mutation stays here: `lines = "\n".join(...)` -> `lines = ""` in
    # `_profile_block` reddens the loop.
    region = next(
        t for t in _prepared(_python(agents=("codex",))).footprint if t.id == "agents-md"
    ).render()
    assert "`docs/stayfixed/rules/python.md`" in region
    for line in load_profile("python").essentials:
        assert f"- {line}" in region
    # The block follows the paragraph after one blank line and adds none before the end marker.
    assert "\n\n\n" not in region and not region.endswith("\n\n")


def test_no_profile_means_no_profile_artifact_and_the_region_is_unchanged() -> None:
    config = preset_defaults("widget")
    prepared = _prepared(config)
    assert not {t.id for t in prepared.footprint} & {"profile-rules", "claude-rules"}
    region = next(t for t in prepared.footprint if t.id == "agents-md").render()
    # Byte for byte what the region was before profiles: the shipped template with its
    # `%%PROFILE%%` sentinel taken out and every other sentinel filled. Mutation: make
    # `_profile_block` return `PROFILE_BLOCK` unfilled for no profile -> the equality reddens.
    p = config.paths
    before = fill(
        read("agents-region.md").replace("%%PROFILE%%", ""),
        BUG_INDEX=p.bug_index,
        BUGS=p.bugs,
        ROADMAP=p.roadmap,
        SPECS=p.specs,
        PLANS=p.plans,
    )
    assert region == before
    # That equality holds wherever the sentinel sits, so the position is its own assertion: the
    # sentinel ends the region's last line, and no blank line is left where it sat. Mutation:
    # put `%%PROFILE%%` on a line of its own -> this reddens.
    assert not region.endswith("\n\n")


def test_an_unknown_harness_name_is_counted_for_the_report() -> None:
    prepared = _prepared(_python(agents=("claude", "cursor")))
    assert prepared.unknown_harnesses == 1


def test_a_rendition_that_collides_is_refused_naming_the_harness_s_fixed_name() -> None:
    # A rendition has no row in `PATH_KEYS`: its target is the harness's own fixed name, which is
    # what the refusal calls an id with no row. Mutation (oracle): look the second id up with no
    # fallback -> the collision is a `KeyError`, not a refusal, and this reddens.
    config = _python(("claude",))
    clash = replace(
        config, paths=replace(config.paths, roadmap=".claude/rules/stayfixed-python.md")
    )
    with pytest.raises(Refusal, match=r"claude-rules \(a fixed name of stayfixed's own\)"):
        _prepared(clash)


def test_every_target_any_configuration_writes_is_one_every_configuration_could() -> None:
    # `could_write` is the anchor the collision refusal reads: what one configuration wrote must
    # be listed by every other configuration. So it is built at the lines that build the
    # templates, and this holds it across every toggle that turns an artifact on or off.
    base = preset_defaults("widget")
    configs = [
        replace(base, stayfixed=replace(base.stayfixed, profile=profile, agents=agents))
        for profile in ("", "python")
        for agents in ((), ("codex",), ("claude", "codex"))
    ]
    prepared = [_prepared(config) for config in configs]
    written = {(t.id, t.target) for p in prepared for t in (*p.once, *p.footprint)}
    for each in prepared:
        listed = {(i, target) for i, targets in each.could_write.items() for target in targets}
        assert written <= listed


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
