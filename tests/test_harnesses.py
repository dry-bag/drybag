"""The harness registry, and the one profile rendering there is: Claude Code's path-scoped rule."""

from __future__ import annotations

import ast
import itertools
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from stayfixed import harnesses
from stayfixed.harnesses import (
    CANONICAL,
    CLAUDE,
    CODEX,
    HARNESSES,
    Harness,
    Surface,
    detect,
    select,
)
from tests.test_language_neutral import _docstrings

ROOT = Path(__file__).resolve().parents[1]


def test_select_answers_the_listed_harnesses_and_counts_the_rest() -> None:
    assert select(["claude", "codex"]) == ((CLAUDE, CODEX), 0)
    assert select(["codex"]) == ((CODEX,), 0)
    assert select(["claude", "cursor", "x\x1b"]) == ((CLAUDE,), 2)


def test_every_harness_is_registered_once_and_codex_reads_only_the_standard() -> None:
    names = [harness.name for harness in HARNESSES]
    assert len(names) == len(set(names))
    assert CLAUDE.settings == (".claude/settings.json",)
    assert CODEX.settings == (".codex/hooks.json",)
    # `project.detect` reads these instead of spelling the directories a second time.
    assert (CLAUDE.marker_dir, CODEX.marker_dir) == (".claude", ".codex")


# What a hook may say about a tool call, in either harness's schema. A harness's `render` shapes
# context and nothing else: a deny travels on the exit code alone (`hooks.dispatch.dispatch`), and
# an allow spelled in JSON would let one through that a guard never judged.
DECISION_KEYS = frozenset({"permissionDecision", "decision", "continue"})

# The inputs detection is asked about, as the two harnesses send them and as neither does.
ENVIRONMENTS: tuple[dict[str, str], ...] = (
    {},
    {"CLAUDE_PROJECT_DIR": "/p"},
    {"CLAUDE_PLUGIN_ROOT": "/r", "CLAUDE_PROJECT_DIR": "/p"},
    {"PLUGIN_ROOT": "/r"},
    {"PLUGIN_ROOT": "/r", "PLUGIN_DATA": "/d", "CLAUDE_PLUGIN_ROOT": "/r"},
)
PAYLOADS: tuple[dict[str, object] | None, ...] = (
    None,
    {},
    {"hook_event_name": "SessionStart", "cwd": "/tmp"},
    {"model": "m"},
    {"permission_mode": "p"},
    {"model": "m", "permission_mode": "p"},
)
# A harness no release serves, told by a variable of its own, and the inputs it sends. Its
# variable is in none of the inputs above, as a new harness's would be in neither of theirs.
OTHER = Harness(
    name="other",
    marker_dir=".other",
    settings=(),
    local_settings=(),
    project_dir_env=None,
    render=CANONICAL.render,
    reach=CLAUDE.reach,
    plugin_root_env="OTHER_PLUGIN_ROOT",
    detects=lambda env, payload: "OTHER_HARNESS" in env,
)
OTHER_INPUTS: tuple[tuple[dict[str, str], dict[str, object] | None], ...] = (
    ({"OTHER_HARNESS": "1"}, None),
    ({"OTHER_HARNESS": "1", "CLAUDE_PROJECT_DIR": "/p"}, {"hook_event_name": "SessionStart"}),
)


def test_an_environment_codex_sets_is_codex() -> None:
    # Codex mirrors its `PLUGIN_ROOT` as `CLAUDE_PLUGIN_ROOT`, so Claude Code's names identify
    # nothing beside it; and Codex's stdin carries `model` and `permission_mode`, which Claude
    # Code's does not, whatever variables the process inherited. Mutation (declared, on
    # `harnesses`): `detect` answers `CANONICAL` before asking any value -> both redden.
    assert detect({"PLUGIN_ROOT": "/r", "CLAUDE_PLUGIN_ROOT": "/r"}, None) is CODEX
    pair = {"hook_event_name": "SessionStart", "model": "m", "permission_mode": "p"}
    assert detect({"CLAUDE_PLUGIN_ROOT": "/r", "CLAUDE_PROJECT_DIR": "/p"}, pair) is CODEX


def test_no_input_is_claimed_by_two_harnesses() -> None:
    # Detection answers the first value that claims an input, so two values claiming one would
    # make the registry's order decide which harness a session gets. Only Codex detects anything
    # today, and one detecting value cannot claim an input twice, so a second one stands beside
    # it here, with the inputs it sends. Mutation (declared, on `harnesses`): Codex's detection
    # claims every input -> the other value's inputs are claimed twice and this reddens.
    positive = [harness for harness in (*HARNESSES, OTHER) if harness.detects is not None]
    assert len(positive) >= 2, "fewer than two values detect anything, so none can collide"
    claimed: set[str] = set()
    for env, payload in (*itertools.product(ENVIRONMENTS, PAYLOADS), *OTHER_INPUTS):
        claims = [h.name for h in positive if h.detects is not None and h.detects(env, payload)]
        assert len(claims) <= 1, (env, payload, claims)
        claimed.update(claims)
    # A value the walk never asks about anything it claims could collide with nothing.
    assert claimed == {harness.name for harness in positive}


def test_an_input_no_harness_claims_is_the_canonical_harness() -> None:
    # Claude Code's hook schema is the one other harnesses imitate, so it is the fallback, and
    # it detects nothing of its own: the answer when no value claims an input. Half the Codex
    # pair is not the pair. Mutation (by hand): `detect`'s fallback as `HARNESSES[-1]` -> the
    # last three assertions redden.
    assert CANONICAL is CLAUDE and CLAUDE.detects is None
    assert detect({}, None) is CANONICAL
    assert detect({"CLAUDE_PLUGIN_ROOT": "/r", "CLAUDE_PROJECT_DIR": "/p"}, {}) is CANONICAL
    assert detect({"CLAUDE_PROJECT_DIR": "/p"}, {"model": "m"}) is CANONICAL


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= _keys(item)
        return found
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


# A harness whose answer is plain text, which a later harness's may be: `render` is a function of
# the event and the context, and nothing promises it emits JSON.
TEXT = Harness(
    name="text",
    marker_dir=".text",
    settings=(),
    local_settings=(),
    project_dir_env=None,
    render=lambda event, context, notice: f"{notice}[{event}] {context}",
    reach=CLAUDE.reach,
    plugin_root_env="TEXT_PLUGIN_ROOT",
)


@pytest.mark.parametrize("harness", (*HARNESSES, TEXT), ids=lambda h: h.name)
@pytest.mark.parametrize("event", ["SessionStart", "PreToolUse", "PostToolUse"])
@pytest.mark.parametrize(
    "context",
    ["", "a note", '{"permissionDecision": "deny", "decision": "block", "continue": false}'],
    ids=["empty", "plain", "deny-shaped"],
)
def test_no_harness_renders_a_decision(harness: Harness, event: str, context: str) -> None:
    # A rendering is context in an envelope, and a context or a notice shaped like a decision is
    # still a string inside it, never a key of the envelope. Mutation (declared, on `harnesses`):
    # the canonical render adds `"permissionDecision": "allow"` beside `hookEventName` -> every
    # Claude Code and Codex case reddens, since both render through the same function.
    assert not _decisions(harness.render(event, context, context), context)


def test_every_harness_renders_through_the_canonical_render() -> None:
    # What `detect` answers is a repository's to steer, so while every value renders the same way
    # the answer changes nothing a harness receives. A value with a render of its own makes that
    # answer choose an output shape, which is safe only on a signal no repository reaches.
    # Mutation (declared, on `harnesses`): Codex given a render of its own -> this reddens.
    for harness in HARNESSES:
        assert harness.render is CANONICAL.render, (
            f"`{harness.name}` has a render of its own. A harness may get one only together with "
            "a detection signal a repository cannot steer: not the environment and not stdin, "
            "but one the wrapper controls, such as its argv (`stayfixed.harnesses.detect`)."
        )


def _decisions(rendered: str, context: str) -> set[str]:
    """The decision keys a rendering carries outside the context it was handed.

    A JSON object is read for its keys, at any depth, so the context stays a string value however
    it is shaped. Anything else is read as text, with the context taken out first, since a
    deny-shaped context is spelled inside it by design: what is left is the envelope, and a
    decision key spelled there is one the harness may act on.
    """
    try:
        parsed = json.loads(rendered)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return _keys(parsed) & DECISION_KEYS
    envelope = rendered.replace(context, "") if context else rendered
    return {key for key in DECISION_KEYS if key in envelope}


def test_the_decision_check_finds_a_decision_in_either_shape() -> None:
    # The check above passes for every shipped value, so it is held here against renderings that
    # do carry a decision, as JSON and as text, and against a text envelope that only quotes one
    # in its context. Mutation (by hand): `_decisions` answers `set()` for a rendering that is not
    # a JSON object -> the text assertions redden.
    deny = '{"permissionDecision": "deny"}'
    assert _decisions(json.dumps({"hookSpecificOutput": {"decision": "block"}}), "") == {"decision"}
    assert _decisions(json.dumps(["permissionDecision"]), "") == {"permissionDecision"}
    assert _decisions("continue: false\n[PreToolUse] a note", "a note") == {"continue"}
    assert _decisions(TEXT.render("PreToolUse", deny, ""), deny) == set()


def test_every_harness_states_every_surface() -> None:
    # The README's table reads a harness's reach, and a surface a value leaves out is one it can
    # say nothing true about: the table would lose a cell. Mutation (declared, on
    # `harnesses`): drop the session-notices row from Codex's reach -> this reddens.
    for harness in HARNESSES:
        assert set(harness.reach) == set(Surface), harness.name
        for surface, reach in harness.reach.items():
            assert reach.evidence, (harness.name, surface)
            # "Not claimed on this agent" is a statement a reader acts on, so it rests on evidence
            # (a measured absence, or a measurement that stopped short of stayfixed's own
            # surfaces); a surface nothing was measured of keeps the tier it was built for.
            if reach.tier is None:
                assert reach.evidence != "unmeasured", (harness.name, surface)
    # Claude Code's own files, then the one it keeps out of git, which `attach` merges into:
    # `doctor`'s settings walk is these, over every harness.
    assert CLAUDE.local_settings == (".claude/settings.local.json",)
    assert CODEX.local_settings == ()


def test_a_harness_can_key_a_set_and_a_dict() -> None:
    # A harness is a value, and a value is hashable: it keys a dict and sits in a set as it did
    # before it carried a mapping of its reach. Mutation (declared, on `harnesses`): `reach`
    # without `field(hash=False)` -> hashing raises and this reddens.
    assert len(set(HARNESSES)) == len(HARNESSES)
    assert {harness: harness.name for harness in HARNESSES}[CODEX] == "codex"


# Every harness name in a string a module of the package spells outside this registry, as the
# words `claude` and `codex` and Codex's own `PLUGIN_ROOT` and `PLUGIN_DATA`, standing alone:
# letters and digits on neither side, any case, so `CLAUDE_PROJECT_DIR`, `.claude/skills` and
# `common/codex` are mentions. Docstrings and comments are prose and are not read; every other
# string constant, an f-string's literal parts included, is.
HARNESS_WORDS = ("claude", "codex", "plugin_root", "plugin_data")
_HARNESS_MENTION = re.compile(
    r"(?<![a-z0-9])(" + "|".join(HARNESS_WORDS) + r")(?![a-z0-9])", re.IGNORECASE
)

# The mentions that are harness facts the registry does not carry, each with how many string
# constants of its module make it and the phrase of `harnesses`' module docstring that lists it,
# which must be there: a fact moved onto the registry takes its pardon with it, and a new one needs
# a new item in that list. Counted, so a new constant beside a pardoned one reddens too. A site
# whose constants make more than one fact gives a phrase for each.
LISTED = {
    ("src/stayfixed/setup/run.py", "claude"): (4, "`_MARKETPLACE_ADD` and `_PLUGIN_INSTALL`"),
    ("src/stayfixed/setup/run.py", "codex"): (4, "`_MARKETPLACE_ADD` and `_PLUGIN_INSTALL`"),
    ("src/stayfixed/setup/restore.py", "claude"): (10, "`install_listed` in `setup/restore.py`"),
    ("src/stayfixed/setup/restore.py", "codex"): (2, "`install_listed` in `setup/restore.py`"),
    ("src/stayfixed/attach/render.py", "claude"): (
        6,
        "`PLUGIN_MARKETPLACE_ADD_LOCAL` and `PLUGIN_INSTALL_LOCAL`",
    ),
    ("src/stayfixed/overlay/layout.py", "claude"): (1, "(`overlay.layout`"),
    ("src/stayfixed/overlay/layout.py", "codex"): (1, "(`overlay.layout`"),
    ("src/stayfixed/overlay/api.py", "claude"): (1, "re-exported by `overlay.api`"),
    ("src/stayfixed/overlay/api.py", "codex"): (1, "re-exported by `overlay.api`"),
    ("src/stayfixed/attach/permissions.py", "claude"): (
        1,
        "(`attach.permissions`, `attach.write`)",
    ),
    ("src/stayfixed/attach/permissions.py", "codex"): (2, "(`attach.permissions`, `attach.write`)"),
    ("src/stayfixed/attach/write.py", "claude"): (4, "(`attach.permissions`, `attach.write`)"),
    ("src/stayfixed/attach/write.py", "codex"): (4, "(`attach.permissions`, `attach.write`)"),
    ("src/stayfixed/hooks/api.py", "claude"): (1, "`hooks.api.DATA_ROOT_VARIABLES`"),
    ("src/stayfixed/hooks/api.py", "plugin_data"): (2, "`hooks.api.DATA_ROOT_VARIABLES`"),
    ("src/stayfixed/doctor/checks.py", "claude"): (
        3,
        "every variable under Claude Code's and Codex's",
    ),
    ("src/stayfixed/doctor/checks.py", "codex"): (1, "names Codex in the `cli-path`"),
    ("src/stayfixed/doctor/checks.py", "plugin_root"): (
        1,
        "names `CLAUDE_PLUGIN_ROOT` in the remedy",
    ),
    ("src/stayfixed/doctor/checks.py", "plugin_data"): (1, "`${CLAUDE_PLUGIN_DATA}` in the"),
    ("src/stayfixed/trust/boundary.py", "claude"): (2, "`trust.boundary` spells"),
    ("src/stayfixed/guards/commands.py", "claude"): (
        1,
        "`commit strip` gives way to Claude Code's `attribution.commit`",
    ),
}
# The mentions that are no fact the code acts on, each with how many constants make it and why.
PROSE = {
    # Messages naming the Codex rule files `attach` places, and `--check` would place.
    ("src/stayfixed/attach/check.py", "codex"): 1,
    # The sentence `doctor` warns with where two tags hold one Codex rule file.
    ("src/stayfixed/attach/tags.py", "codex"): 1,
    # The instruction file Claude Code reads beside `AGENTS.md`, which `owner-files` asks the
    # session to read now when it placed either.
    ("src/stayfixed/attach/checkout.py", "claude"): 1,
    ("src/stayfixed/attach/commands.py", "codex"): 2,
    # The advice `setup --approval-boundary` prints, which names the harness whose settings it is.
    ("src/stayfixed/setup/commands.py", "claude"): 1,
    # The commit-trailer guard's names of tools that sign commits as authors: the agent as an
    # author of a commit, not as a harness stayfixed runs under.
    ("src/stayfixed/guards/commit.py", "claude"): 2,
    ("src/stayfixed/guards/commit.py", "codex"): 2,
    # The recommended plugins question's lines, which say where `setup` installs them and how to
    # take one out: Claude Code is the one harness with a verified marketplace for them.
    ("src/stayfixed/project/questions.py", "claude"): 3,
}


def _harness_mentions() -> Counter[tuple[str, str]]:
    """How many string constants of each module outside the registry name each harness word."""
    found: Counter[tuple[str, str]] = Counter()
    for path in sorted((ROOT / "src" / "stayfixed").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative == "src/stayfixed/harnesses.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prose = _docstrings(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in prose
            ):
                words = {word.lower() for word in _HARNESS_MENTION.findall(node.value)}
                found.update((relative, word) for word in words)
    return found


def test_every_harness_fact_outside_the_registry_is_listed_where_the_registry_says() -> None:
    # The registry's docstring lists what a new harness still touches outside it, and four sites
    # were missing from that list while it said every other fact was asked of the registry. Every
    # mention is pardoned here, and the comparison is equality both ways: a new mention reddens
    # this test, and so does a pardon whose mention is gone. Mutation (oracle): `mutations/`'s
    # "doctor spells the project-root variable again" -> one constant more than its pardon.
    assert not LISTED.keys() & PROSE.keys()
    pardoned = Counter({site: count for site, (count, _) in LISTED.items()}) + Counter(PROSE)
    assert _harness_mentions() == pardoned
    listed = harnesses.__doc__ or ""
    missing = {
        site: phrase
        for site, (_, phrases) in LISTED.items()
        for phrase in ((phrases,) if isinstance(phrases, str) else phrases)
        if phrase not in listed
    }
    assert missing == {}
