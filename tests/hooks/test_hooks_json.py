from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from drybag.cli import build_parser, discover_registrars
from drybag.harnesses import CLAUDE
from drybag.hints.hooks import BASH
from drybag.hooks.api import EVENTS
from drybag.hooks.registry import discover

# `drybag.memory.api` and not `drybag.memory.bundles`: an area is imported through its
# published surface, never through a private module, and `SLOTS` is on that surface.
from drybag.memory.api import SLOTS

ROOT = Path(__file__).resolve().parents[2]
HOOKS = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
# Every command runs the wrapper under the plugin root Claude Code names, which the harness
# registry states and `doctor`'s `wrapper` row sets: one name, so the file and the row cannot part.
WRAPPER = f'"${{{CLAUDE.plugin_root_env}}}/hooks/run-hook.sh"'


def _entries() -> list[tuple[str, str, dict[str, Any]]]:
    """Every entry with the event key it is filed under **and** its group's matcher.

    The matcher used to be dropped here, and `type` was read by nothing at all. Both are the
    entry's own fields and both decide whether it ever runs: the reviewer changed `"matcher":
    "Bash"` to `"bash"` -- which retires `bg-cleanup` -- and `"type": "command"` to
    `"commandd"`, and every one of the ten assertions below passed.
    A walk that discards a field is a walk that cannot be asked about it.
    """
    return [
        (event, group.get("matcher", ""), entry)
        for event, groups in HOOKS["hooks"].items()
        for group in groups
        for entry in group["hooks"]
    ]


# The `source` values Claude Code sends on SessionStart. Dropping one from the matcher silences
# every injection bundle for that kind of session start -- `resume` and `compact` are the two a
# long session actually hits -- with nothing else anywhere saying so.
SESSION_SOURCES = {"startup", "resume", "clear", "compact", "fork"}


def test_there_are_entries_at_all() -> None:
    # The non-vacuity guard every walk-driven assertion below depends on: an empty `hooks`
    # object satisfies all six of them.
    assert len(_entries()) == 12


def test_every_command_parses_against_the_real_parser() -> None:
    # A shipped file no type checker reads. The failure mode it prevents is the expensive one:
    # a typo here is discovered by a user whose guard silently stopped guarding.
    parser = build_parser(discover_registrars())
    for _, _matcher, entry in _entries():
        words = entry["command"].split()
        assert words[0] == WRAPPER
        parser.parse_args(words[1:])


def test_no_entry_passes_json() -> None:
    # `bundles.py`'s CAP_MARGIN comment, addressing `drybag.hooks` by name: "the `hooks.json`
    # entries must not pass `--json`. The margin is additive only because `memory
    # session-context` prints the text raw." `memory/commands.py` records that this invariant
    # is owned outside `memory` and asserted by no test there. This is that test.
    for _, _matcher, entry in _entries():
        assert "--json" not in entry["command"].split()


def test_there_is_one_session_start_entry_per_declared_bundle_slot() -> None:
    # A bundle that overflows is split across further entries, and raising N edits this
    # shipped file — so N is asserted from SLOTS rather than counted by hand.
    declared = [
        (words[words.index("--bundle") + 1], words[words.index("--part") + 1])
        for event, _matcher, entry in _entries()
        if event == "SessionStart" and "--bundle" in (words := entry["command"].split())
    ]
    assert set(declared) == {
        (bundle.value, str(part)) for bundle, parts in SLOTS.items() for part in range(1, parts + 1)
    }
    # And in order, behind the dispatcher: each bundle's parts in sequence, standing rules before
    # volatile notes. The set above cannot see an order, so two entries that swap their parts
    # still pass it.
    #
    # Mutations (oracle): `mutations/`'s "a session-start part is filed twice and another not at
    # all" -> the set reddens; "two session-start parts swap places in the hooks file" -> the set
    # holds and the order reddens.
    session_start = [
        entry["command"].split()[1:]
        for event, _matcher, entry in _entries()
        if event == "SessionStart"
    ]
    assert session_start[0] == ["hook", "SessionStart"]
    assert declared == [
        ("standing-rules", "1"),
        ("standing-rules", "2"),
        ("standing-rules", "3"),
        ("volatile-notes", "1"),
        ("volatile-notes", "2"),
        ("volatile-notes", "3"),
    ]


def test_every_dispatched_event_has_at_least_one_handler() -> None:
    # An entry for an event nothing handles spawns a process to emit an empty envelope, and
    # looks installed in doctor's listing. The dispatcher carries six events; two of them
    # have no handler in this build, and a handler added for one arrives with its entry.
    events = {handler.event for handler in discover()}
    for _, _matcher, entry in _entries():
        words = entry["command"].split()
        if words[1] == "hook":
            assert words[2] in events


def test_every_registered_handler_has_an_entry() -> None:
    # The other direction, and the more expensive one to get wrong: a handler with no entry
    # never runs, and `scripts/smoke_hooks.py` could not see it.
    dispatched = {
        words[2]
        for _, _matcher, entry in _entries()
        if (words := entry["command"].split())[1] == "hook"
    }
    assert {handler.event for handler in discover()} <= dispatched


def test_no_entry_is_async() -> None:
    # Codex async hooks cannot block. Unmeasured by the spikes — which is a reason to
    # hold the line in the file, not a reason to test it against the platform.
    for _, _matcher, entry in _entries():
        assert entry.get("async") is not True


def test_session_start_entries_declare_the_codex_spill_key() -> None:
    # Measured: both harnesses tolerate this key at install time on both events. The same
    # measurement gave NO cap verdict for it: a 20-character canary cannot separate an ignored
    # key from one honoured with 0 meaning unlimited. So it is declared and relied on for
    # nothing — the bound that IS measured is `bundles._cap`'s margin under `hook_output_chars`,
    # recorded beside `CAP_MARGIN`.
    for event, _matcher, entry in _entries():
        if event == "SessionStart":
            assert entry.get("additionalContextLimit") == 0


def test_every_entry_is_a_command_entry() -> None:
    # `type` is what tells the harness this entry is a command to run at all. Nothing read it:
    # `"type": "commandd"` shipped green, and an entry the harness cannot classify is a guard
    # that silently never fires -- the same failure mode as a mistyped event, one field over.
    #
    # Mutation: `"type": "command"` -> `"commandd"` on any entry in hooks/hooks.json -> reddens.
    for _, _matcher, entry in _entries():
        assert entry["type"] == "command", entry


def test_every_tool_matched_entry_matches_the_name_both_handlers_filter_on() -> None:
    # `hints.hooks.BASH` is the name `bash_command` compares `event.tool_name` against, so the
    # matcher in this file and that constant are two spellings of one thing. The matcher is a
    # case-sensitive regular expression: `"bash"` matches no tool Claude Code or Codex reports,
    # which retires `bg-cleanup` and the `test-hygiene` notice with it, permanently and silently.
    #
    # Asserted from the constant rather than spelled here, for the reason
    # `test_there_is_one_session_start_entry_per_declared_bundle_slot` gives about SLOTS.
    #
    # Mutation: `"matcher": "Bash"` -> `"bash"` in hooks/hooks.json -> reddens.
    matched = {
        matcher
        for event, matcher, _ in _entries()
        if event in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}
    }
    assert matched == {BASH}


def test_the_session_start_matcher_carries_every_source_a_session_can_start_from() -> None:
    # The same field on the other event, where it selects `source` rather than a tool. A source
    # dropped from this alternation is every injection bundle missing from that kind of session
    # start -- `resume` and `compact` are the two a long session actually reaches -- reported
    # by nothing, because a hook that is not invoked emits no diagnostic.
    #
    # Mutation: delete `|resume` from the SessionStart matcher in hooks/hooks.json -> reddens.
    matchers = {matcher for event, matcher, _ in _entries() if event == "SessionStart"}
    assert len(matchers) == 1, matchers
    assert set(matchers.pop().split("|")) == SESSION_SOURCES


def test_every_entry_is_filed_under_the_event_its_command_dispatches() -> None:
    # Both event tests above read the event out of the *argv* and never out of the JSON key it
    # is filed under, so `"PostToolUSe"` as a key passed every one of them: the command still
    # said `hook PostToolUse` and still named a registered handler, while the harness -- which
    # dispatches on the key -- emitted nothing for it ever again. The key is what runs the
    # entry, so the key is what is asserted, against `hooks.api.EVENTS` and against the argv.
    #
    # Mutation: rename the `"PostToolUse"` key to `"PostToolUSe"` in hooks/hooks.json -> reddens.
    keys = list(HOOKS["hooks"])
    assert keys, "no event keys at all, so the assertions below measure nothing"
    for key in keys:
        assert key in EVENTS, key
    for event, _matcher, entry in _entries():
        words = entry["command"].split()
        if words[1] == "hook":
            assert words[2] == event, entry["command"]


def test_the_shipped_hooks_register_post_tool_use_failure_for_bash() -> None:
    # Claude Code delivers a Bash command that exits non-zero to `PostToolUseFailure`, so the
    # red-run hint has an entry there, matched on the shell tool, and dispatching that
    # event. Codex reads this file too and ignores the key (measured on Codex CLI
    # 0.162.0-alpha.17.2); it delivers a failed command on `PostToolUse`, whose entry stays.
    # Mutation: `mutations/`'s "the hooks file loses the entry for a failed command".
    groups = HOOKS["hooks"].get("PostToolUseFailure")
    assert groups == [
        {
            "matcher": BASH,
            "hooks": [
                {
                    "type": "command",
                    "timeout": 10,
                    "command": f"{WRAPPER} hook PostToolUseFailure",
                }
            ],
        }
    ]
