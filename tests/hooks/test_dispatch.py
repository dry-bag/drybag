# tests/hooks/test_dispatch.py
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import errno
import io
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from stayfixed.gitenv import _git_toplevel
from stayfixed.harnesses import CLAUDE, HARNESSES, Harness
from stayfixed.hooks.api import Handler, HookEvent, HookResult, NullSink
from stayfixed.hooks.commands import run_hook
from stayfixed.hooks.dispatch import TRUNCATION_MARK, Recorder, dispatch, read_event
from tests.gitfixture import git
from tests.sessions import NO_CONFIG

CLAUDE_ENV = {"CLAUDE_PROJECT_DIR": "/p", "CLAUDE_PLUGIN_ROOT": "/r"}


def event(name: str = "PreToolUse", **raw: object) -> HookEvent:
    payload: dict[str, object] = {
        "hook_event_name": name,
        "session_id": "s",
        "cwd": "/tmp",
        "tool_name": "Bash",
    }
    payload.update(raw)
    return read_event(payload, CLAUDE_ENV)


def handler(
    name: str,
    result: HookResult | BaseException,
    once_key: str | None = None,
    event_name: str = "PreToolUse",
) -> Handler:
    def run(ev: HookEvent, config: object) -> HookResult:
        if isinstance(result, BaseException):
            raise result
        return result

    return Handler(name=name, event=event_name, run=run, once_key=once_key)


def test_contexts_are_joined_into_the_claude_shape() -> None:
    handlers = [
        handler("a", HookResult(context="A")),
        handler("b", HookResult(context="B")),
    ]
    outcome = dispatch(event(), handlers, NO_CONFIG, harness=CLAUDE, sink=Recorder())
    assert outcome.exit_code == 0
    assert json.loads(outcome.stdout) == {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "A\n\nB"}
    }


@pytest.mark.parametrize(
    ("registered", "other"), [("PostToolUse", "PreToolUse"), ("PreToolUse", "PostToolUse")]
)
def test_a_handler_stays_silent_on_every_event_but_its_own(registered: str, other: str) -> None:
    # `discover()` hands the dispatcher every area's handlers at once, so the event filter is
    # the only thing keeping a PostToolUse hint off a PreToolUse call.
    guard = handler("g", HookResult(context="G"), event_name=registered)
    heard = dispatch(event(registered), [guard], NO_CONFIG, harness=CLAUDE, sink=Recorder())
    assert json.loads(heard.stdout)["hookSpecificOutput"]["additionalContext"] == "G"
    silent = dispatch(event(other), [guard], NO_CONFIG, harness=CLAUDE, sink=Recorder())
    assert "additionalContext" not in json.loads(silent.stdout)["hookSpecificOutput"]
    assert silent.stderr == ""


def test_a_handler_that_raises_is_swallowed_and_recorded() -> None:
    recorder = Recorder()
    outcome = dispatch(
        event(),
        [handler("a", RuntimeError("boom"))],
        NO_CONFIG,
        harness=CLAUDE,
        sink=recorder,
    )
    assert outcome.exit_code == 0
    assert "boom" in outcome.stderr
    assert recorder.records[0]["handler"] == "a"
    assert recorder.records[0]["error"] == "RuntimeError"


def test_a_handlers_non_string_context_is_swallowed_and_a_later_one_lands() -> None:
    # `result.context` used to be joined into the payload outside every per-handler `try`, so
    # one handler's malformed context took the whole dispatch down with a TypeError instead of
    # failing that handler alone.
    recorder = Recorder()
    broken = handler("a-broken", HookResult(context=cast(str, 42)))
    ok = handler("b-ok", HookResult(context="B"))
    outcome = dispatch(event(), [broken, ok], NO_CONFIG, harness=CLAUDE, sink=recorder)
    assert outcome.exit_code == 0
    assert "unrecognised context" in outcome.stderr
    assert recorder.records[0]["error"] == "unrecognised-context"
    assert recorder.records[0]["context"] == "42"
    assert json.loads(outcome.stdout)["hookSpecificOutput"]["additionalContext"] == "B"


@pytest.mark.parametrize("raised", [asyncio.CancelledError(), KeyboardInterrupt()], ids=type)
def test_a_base_exception_from_a_handler_costs_that_handler_alone(raised: BaseException) -> None:
    # A handler that awaits anything surfaces CancelledError and a Ctrl-C mid-hook surfaces
    # KeyboardInterrupt; neither inherits Exception, so both used to escape every guard and
    # exit the process. CancelledError leads: a regression on it fails one test, where
    # KeyboardInterrupt aborts the whole session and would otherwise be the only signal.
    recorder = Recorder()
    outcome = dispatch(event(), [handler("g", raised)], NO_CONFIG, harness=CLAUDE, sink=recorder)
    assert outcome.exit_code == 0
    assert type(raised).__name__ in outcome.stderr
    assert recorder.records[0]["error"] == type(raised).__name__


def test_an_earlier_context_survives_a_later_handlers_malformed_return() -> None:
    # Reading `.context` off a later handler's `None` raised an AttributeError out of `dispatch`
    # and took the earlier handler's answer with it.
    recorder = Recorder()
    note = handler("a-note", HookResult(context="A"), event_name="PostToolUse")
    broken = handler("b-broken", cast(HookResult, None), event_name="PostToolUse")
    outcome = dispatch(
        event("PostToolUse"), [note, broken], NO_CONFIG, harness=CLAUDE, sink=recorder
    )
    assert outcome.exit_code == 0
    assert json.loads(outcome.stdout)["hookSpecificOutput"]["additionalContext"] == "A"
    assert recorder.records[0] == {
        "event": "PostToolUse",
        "handler": "b-broken",
        "error": "TypeError",
    }


def test_a_null_sink_forgets_a_marker_instead_of_suppressing_it() -> None:
    # The shipped `run_hook` passes a NullSink, so this is production's `once_key` semantics.
    sink = NullSink()
    sink.mark("ledger-notes")
    assert sink.seen("ledger-notes") is False


def test_a_once_key_handler_runs_every_time_under_the_null_sink() -> None:
    runs: list[int] = []

    def count(ev: HookEvent, config: object) -> HookResult:
        runs.append(1)
        return HookResult(context="A")

    once = Handler(name="a", event="PreToolUse", run=count, once_key="ledger-notes")
    for _ in range(2):
        dispatch(event(), [once], NO_CONFIG, harness=CLAUDE, sink=NullSink())
    assert runs == [1, 1]


def test_a_cap_below_the_envelope_is_recorded_and_emits_nothing() -> None:
    # No JSON envelope fits in 20 characters, so the honest output is none at all: anything
    # longer than the cap is replaced by the platform with a preview and a file path.
    recorder = Recorder()
    handlers = [handler("a", HookResult(context="x" * 50))]
    outcome = dispatch(event(), handlers, NO_CONFIG, harness=CLAUDE, sink=recorder, cap=20)
    assert outcome.stdout == ""
    assert recorder.records[0]["error"] == "context-truncated"


def test_the_notice_counts_inside_the_cap_and_is_never_cut() -> None:
    # The notice goes out twice, whole to the person and at the head of the model's context, and
    # the cap bounds the string that carries both: the context loses its tail, never the notice.
    # Mutation (`mutations/`'s "the clamp cuts the notice from its answer"): the clamped answer
    # carries no `systemMessage`.
    handlers = [handler("a", HookResult(context="y" * 500), event_name="SessionStart")]
    session = dataclasses.replace(NO_CONFIG, project_warnings=("a notice",))
    outcome = dispatch(
        event("SessionStart"), handlers, session, harness=CLAUDE, sink=Recorder(), cap=300
    )
    assert len(outcome.stdout) <= 300
    payload = json.loads(outcome.stdout)
    assert payload["systemMessage"] == "a notice"
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("a notice\n\nyyy") and context.endswith(TRUNCATION_MARK)


def test_context_at_a_realistic_cap_keeps_its_leading_content_and_the_mark() -> None:
    handlers = [handler("a", HookResult(context="y" * 500))]
    outcome = dispatch(event(), handlers, NO_CONFIG, harness=CLAUDE, sink=Recorder(), cap=200)
    context = json.loads(outcome.stdout)["hookSpecificOutput"]["additionalContext"]
    # Every kept character here is plain ASCII, so nothing widens under JSON escaping and the
    # search always lands exactly on the cap: what is left of it after the envelope and the mark
    # is the true optimum for this event name and context, not merely a value close to it.
    assert len(outcome.stdout) == 200
    assert context == "y" * (len(context) - len(TRUNCATION_MARK)) + TRUNCATION_MARK


def test_the_cap_bounds_the_emitted_string_not_the_field_inside_it() -> None:
    handlers = [handler("a", HookResult(context="x" * 20000))]
    outcome = dispatch(event(), handlers, NO_CONFIG, harness=CLAUDE, sink=Recorder(), cap=10000)
    assert len(outcome.stdout) <= 10000
    context = json.loads(outcome.stdout)["hookSpecificOutput"]["additionalContext"]
    assert context.endswith(TRUNCATION_MARK)


def test_json_escaping_is_charged_to_the_same_budget() -> None:
    # Each kept `\n` costs two rendered characters once JSON-escaped, so of two adjacent caps one
    # leaves a budget that cannot be spent to the last character: the true optimum lands on one
    # cap and one short of the other. Asking both pins that without depending on which one is
    # odd, which the envelope's and the mark's widths decide and a rename moves. Mutations (by
    # hand): `_clamp`'s `<= cap` as `< cap` -> [1, 2]; as `<= cap + 1` -> [-1, 0]; each reddens.
    handlers = [handler("a", HookResult(context="\n" * 500))]
    shortfall = []
    for cap in (200, 201):
        stdout = dispatch(
            event(), handlers, NO_CONFIG, harness=CLAUDE, sink=Recorder(), cap=cap
        ).stdout
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        assert context.endswith(TRUNCATION_MARK)
        assert set(context.removesuffix(TRUNCATION_MARK)) == {"\n"}
        shortfall.append(cap - len(stdout))
    assert sorted(shortfall) == [0, 1]


def test_a_once_per_context_handler_runs_once_and_is_skipped_afterwards() -> None:
    recorder = Recorder()
    once = handler("a", HookResult(context="A"), once_key="ledger-notes")
    first = json.loads(dispatch(event(), [once], NO_CONFIG, harness=CLAUDE, sink=recorder).stdout)
    second = json.loads(dispatch(event(), [once], NO_CONFIG, harness=CLAUDE, sink=recorder).stdout)
    assert first["hookSpecificOutput"]["additionalContext"] == "A"
    assert "additionalContext" not in second["hookSpecificOutput"]
    assert recorder.marks == {"ledger-notes"}


def test_a_once_per_context_handler_that_says_nothing_keeps_its_one_delivery() -> None:
    """An empty result is not a delivery, so the handler is asked again.

    `dispatch` banks a `once_key` only for a result with a context -- spending a handler's single
    delivery on a result that said nothing would let the first unrelated Bash
    call of a session consume a notice meant for the first failing test run. That is the right
    rule and it has a consequence worth stating: a handler whose healthy answer is silence runs
    on every matching event, and pays whatever it pays to decide that, every time.
    `attach/hooks.py` is the handler that made this worth writing down -- its own docstring said
    the opposite about which path its `git` calls fall on.

    Mutation: `mutations/`'s "a silent handler spends its one delivery".
    """
    recorder = Recorder()
    silent = handler("a", HookResult(), once_key="overlay-status")
    for _ in range(3):
        outcome = dispatch(event(), [silent], NO_CONFIG, harness=CLAUDE, sink=recorder)
        assert "additionalContext" not in json.loads(outcome.stdout)["hookSpecificOutput"]
    assert recorder.marks == set()
    # Non-vacuous: the same handler with something to say does bank it, so this is about the
    # emptiness of the result and not about the key being ignored.
    speaking = handler("a", HookResult(context="A"), once_key="overlay-status")
    dispatch(event(), [speaking], NO_CONFIG, harness=CLAUDE, sink=recorder)
    assert recorder.marks == {"overlay-status"}


def test_a_handler_without_a_once_key_runs_every_time() -> None:
    recorder = Recorder()
    every = handler("a", HookResult(context="A"))
    for _ in range(2):
        outcome = dispatch(event(), [every], NO_CONFIG, harness=CLAUDE, sink=recorder)
        assert json.loads(outcome.stdout)["hookSpecificOutput"]["additionalContext"] == "A"
    assert recorder.marks == set()


def test_a_once_per_context_handler_that_raises_is_not_marked() -> None:
    recorder = Recorder()
    once = handler("a", RuntimeError("boom"), once_key="ledger-notes")
    assert "boom" in dispatch(event(), [once], NO_CONFIG, harness=CLAUDE, sink=recorder).stderr
    assert recorder.marks == set()
    assert "boom" in dispatch(event(), [once], NO_CONFIG, harness=CLAUDE, sink=recorder).stderr


def test_a_once_per_context_handler_whose_result_is_rejected_keeps_its_one_delivery() -> None:
    # The delivery used to be banked above the validation that can discard the result. A truthy
    # non-string `context` marked `once_key` and then raised into the per-handler `except`: the
    # context never reached stdout, and the handler was skipped for the rest of the session.
    #
    # Asserted from both sides, because "not marked" alone is satisfied by a handler that
    # never ran: the rejected dispatch records the failure and marks nothing, and the NEXT
    # dispatch still delivers, which is the property the mark exists to protect.
    #
    # Mutation (declared): mark above the validation -> the first dispatch marks
    # `ledger-notes`, the second is skipped, and the last two assertions redden.
    recorder = Recorder()
    results = [HookResult(context=cast(str, 42)), HookResult(context="A")]

    def run(ev: HookEvent, config: object) -> HookResult:
        return results.pop(0)

    once = Handler(name="a", event="PreToolUse", run=run, once_key="ledger-notes")
    first = dispatch(event(), [once], NO_CONFIG, harness=CLAUDE, sink=recorder)
    assert "unrecognised" in first.stderr, first.stderr
    assert recorder.marks == set()
    second = dispatch(event(), [once], NO_CONFIG, harness=CLAUDE, sink=recorder)
    assert json.loads(second.stdout)["hookSpecificOutput"]["additionalContext"] == "A"
    assert recorder.marks == {"ledger-notes"}


def test_one_handler_cannot_blank_what_the_next_one_reads() -> None:
    seen: list[object] = []

    def blank(ev: HookEvent, config: object) -> HookResult:
        ev.tool_input["command"] = ""
        ev.raw["tool_name"] = "Write"
        return HookResult()

    def read(ev: HookEvent, config: object) -> HookResult:
        seen.append(ev.tool_input.get("command"))
        seen.append(ev.raw.get("tool_name"))
        return HookResult()

    handlers = [
        Handler(name="a-blank", event="PreToolUse", run=blank),
        Handler(name="b-read", event="PreToolUse", run=read),
    ]
    dispatch(
        event(tool_input={"command": "rm -rf /"}),
        handlers,
        NO_CONFIG,
        harness=CLAUDE,
        sink=Recorder(),
    )
    assert seen == ["rm -rf /", "Bash"]


def test_a_handlers_view_keeps_tool_input_aliased_to_raw_like_read_event_does() -> None:
    # `read_event` makes `ev.tool_input is ev.raw["tool_input"]` true; the per-handler view
    # must preserve that aliasing, not just isolate handlers from each other, so a handler that
    # writes through `tool_input` and reads back through `raw` sees its own write.
    seen: dict[str, object] = {}

    def write_through_tool_input_read_through_raw(ev: HookEvent, config: object) -> HookResult:
        seen["aliased"] = ev.tool_input is ev.raw["tool_input"]
        ev.tool_input["command"] = "mutated"
        seen["raw_command_after"] = ev.raw["tool_input"]["command"]
        return HookResult()

    handlers = [
        Handler(
            name="a",
            event="PreToolUse",
            run=write_through_tool_input_read_through_raw,
        )
    ]
    dispatch(
        event(tool_input={"command": "ls"}), handlers, NO_CONFIG, harness=CLAUDE, sink=Recorder()
    )
    assert seen == {"aliased": True, "raw_command_after": "mutated"}


def test_non_string_contract_fields_become_none_instead_of_reaching_a_guard() -> None:
    ev = read_event(
        {
            "hook_event_name": "PreToolUse",
            "cwd": "/tmp",
            "session_id": 7,
            "agent_id": ["a"],
            "tool_name": {"name": "Bash"},
        },
        CLAUDE_ENV,
    )
    assert ev.session_id is None
    assert ev.agent_id is None
    assert ev.tool_name is None


def _forbidden(cwd: Path) -> Path | None:
    raise AssertionError(f"git was forked for {cwd}")


def test_a_harness_registered_first_never_takes_the_root_from_claude_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The registry's order is a choice about presentation, and adding a harness ahead of Claude Code
    # must not change which directory a Claude Code session's configuration loads from. So the
    # canonical harness's variable is asked first, whatever the registry order, and the others'
    # after it. Mutation (declared, on `harnesses`): the variables are asked in registry order ->
    # the fake's root wins and this reddens.
    project = tmp_path / "project"
    project.mkdir()
    fake = _harness(lambda name, context, notice: context, project_dir_env="FAKE_PROJECT_DIR")
    monkeypatch.setattr("stayfixed.harnesses.HARNESSES", (fake, *HARNESSES))
    monkeypatch.setattr("stayfixed.gitenv._git_toplevel", _forbidden)
    env = {"CLAUDE_PROJECT_DIR": str(project), "FAKE_PROJECT_DIR": str(tmp_path / "elsewhere")}
    ev = read_event({"hook_event_name": "PreToolUse", "cwd": str(tmp_path)}, env)
    assert ev.project_root == project


def test_the_walk_finds_the_root_through_a_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "a" / "b").mkdir(parents=True)
    monkeypatch.setattr("stayfixed.gitenv._git_toplevel", _forbidden)
    ev = read_event({"hook_event_name": "PreToolUse", "cwd": str(tmp_path / "a" / "b")}, {})
    assert ev.project_root == tmp_path


def test_the_walk_finds_the_root_through_a_git_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A worktree and a submodule carry `.git` as a file, so `is_dir()` would miss both.
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w\n", encoding="utf-8")
    (tmp_path / "a").mkdir()
    monkeypatch.setattr("stayfixed.gitenv._git_toplevel", _forbidden)
    ev = read_event({"hook_event_name": "PreToolUse", "cwd": str(tmp_path / "a")}, {})
    assert ev.project_root == tmp_path


def test_the_walk_finds_the_root_above_a_directory_too_deep_to_name_its_dot_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Within a few characters of the longest path, `<cwd>/.git` is past it. `Path.exists()` raised
    # on that up to Python 3.13 and answered `False` from 3.14, so under Codex, where `cwd` is the
    # payload's, every hook in such a directory was an internal error on one interpreter. The
    # walk reads it as no `.git` there on every
    # interpreter and goes on to the parents. Mutations (oracle): `mutations/`'s "the path
    # predicates read a name longer than the system takes as a fault" -> this reddens on every
    # interpreter; "the hook's walk for .git asks pathlib what is there" -> it reddens up to 3.13.
    (tmp_path / ".git").mkdir()
    longest = os.pathconf(tmp_path, "PC_PATH_MAX")
    deep = tmp_path
    # Each step adds a separator and at least one character, so the loop ends whatever length
    # `tmp_path` starts at. One character short of the mark, a step of none left `deep` where it
    # was, and a 72-character `tmp_path` under Linux's 4096 met that and hung.
    while len(str(deep)) < longest - 3:
        deep = deep / ("d" * max(1, min(200, longest - 4 - len(str(deep)))))
    deep.mkdir(parents=True)
    # The premise: the path to its `.git` is one no `stat` can be handed.
    with pytest.raises(OSError) as past:
        os.stat(deep / ".git")
    assert past.value.errno == errno.ENAMETOOLONG
    monkeypatch.setattr("stayfixed.gitenv._git_toplevel", _forbidden)
    ev = read_event({"hook_event_name": "PreToolUse", "cwd": str(deep)}, {})
    assert ev.project_root == tmp_path


def test_the_walk_resolves_a_symlinked_root_the_way_git_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # git resolves a symlink in `cwd` before reporting the toplevel; a walk that returns the
    # unresolved directory it stopped at would report a different `project_root` for the same
    # repository depending on whether it was reached through the real path or a symlink to it.
    real_repo = tmp_path / "realrepo"
    (real_repo / ".git").mkdir(parents=True)
    (real_repo / "sub").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_repo)
    monkeypatch.setattr("stayfixed.gitenv._git_toplevel", _forbidden)
    ev = read_event({"hook_event_name": "PreToolUse", "cwd": str(link / "sub")}, {})
    assert ev.project_root == real_repo.resolve()


def test_git_is_still_asked_when_the_walk_finds_no_dot_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[Path] = []

    def fake(cwd: Path) -> Path | None:
        asked.append(cwd)
        return Path("/from-git")

    monkeypatch.setattr("stayfixed.gitenv._git_toplevel", fake)
    ev = read_event({"hook_event_name": "PreToolUse", "cwd": str(tmp_path)}, {})
    assert ev.project_root == Path("/from-git")
    assert asked == [tmp_path]


def test_an_inherited_git_dir_never_reaches_the_hook_paths_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The memory store's git helper scrubbed and said why — "it must be a real git answer, not one
    # an inherited `GIT_DIR` produced" — while this one passed no `env=` at all. The checkout root
    # feeds *every* hook decision, so an inherited `GIT_DIR` or `GIT_WORK_TREE` made every
    # handler in the process answer for a different repository than the session is in.
    #
    # `_git_toplevel` directly, and a `cwd` with no `.git` above it: `checkout_root` tries
    # `_walk_to_git_root` first and would find the answer without ever asking `git`.
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git is not installed")

    victim = tmp_path / "victim"
    victim.mkdir()
    git(victim, "init", "-q", "-b", "main")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.setenv("GIT_DIR", str(victim / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(victim))
    assert _git_toplevel(elsewhere) is None


# --- the harness a hook answers through ---------------------------------------------------------
#
# Every harness's payload is read by `read_event` the same way whichever value was detected, and
# the detected value contributes the shape of its stdout to the answer and nothing to the event.
# These tests hold both halves: a handler sees one event under every answer, the value detection
# chose is the one that renders, and the clamp measures the envelope that is actually emitted.

# Every variable either harness sets, so a test of detection is not answered by the environment
# the suite happens to run in.
HARNESS_VARIABLES = (
    "PLUGIN_ROOT",
    "PLUGIN_DATA",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PLUGIN_DATA",
    "CLAUDE_PROJECT_DIR",
)


def _harness(
    render: Callable[[str, str, str], str],
    *,
    detects: Callable[[Mapping[str, str], Mapping[str, Any] | None], bool] | None = None,
    project_dir_env: str | None = None,
) -> Harness:
    return Harness(
        name="fake",
        settings=(),
        local_settings=(),
        project_dir_env=project_dir_env,
        render=render,
        reach=CLAUDE.reach,
        plugin_root_env="FAKE_PLUGIN_ROOT",
        detects=detects,
    )


def _hook(
    monkeypatch: pytest.MonkeyPatch,
    event_name: str,
    payload: dict[str, object],
    probe: Handler,
    *,
    env: Mapping[str, str] | None = None,
) -> int:
    """`run_hook` in this process, with `probe` as the only handler and no harness variable but
    the ones `env` sets."""
    for variable in HARNESS_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    for variable, value in (env or {}).items():
        monkeypatch.setenv(variable, value)
    monkeypatch.setattr("stayfixed.hooks.commands.discover", lambda: [probe])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return run_hook(argparse.Namespace(event=event_name))


def test_a_detected_harness_renders_its_own_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A harness whose output differs is a value of its own, registered beside the others, and
    # the hook answers through the value detection chose. The handler sees the same event it
    # would under any harness, with the root from the first project-root variable set, the
    # canonical harness's asked first; here only the fake's own is set. Mutation (declared, on
    # `hooks.dispatch`): `dispatch` renders with `CANONICAL` instead of the detected harness ->
    # stdout is Claude Code's JSON and this reddens.
    fake = _harness(
        lambda name, context, notice: f"fake:{name}:{context}",
        detects=lambda env, payload: payload is not None and "fake_session" in payload,
        project_dir_env="FAKE_PROJECT_DIR",
    )
    monkeypatch.setattr("stayfixed.harnesses.HARNESSES", (fake, *HARNESSES))
    monkeypatch.setenv("FAKE_PROJECT_DIR", str(tmp_path))
    seen: list[Path | None] = []

    def note(ev: HookEvent, config: object) -> HookResult:
        seen.append(ev.project_root)
        return HookResult(context="a note")

    probe = Handler(name="probe", event="SessionStart", run=note)
    payload: dict[str, object] = {"fake_session": "x", "cwd": str(tmp_path)}
    assert _hook(monkeypatch, "SessionStart", payload, probe) == 0
    assert capsys.readouterr().out == "fake:SessionStart:a note"
    assert seen == [tmp_path]


def test_a_handler_sees_one_event_whichever_harness_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The harness a process detects is one a repository can choose (a committed `env` block can
    # set `PLUGIN_ROOT`), so nothing a handler sees may depend on it: the same stdin and the same
    # project-root variable make the same event under Claude Code, under Codex and under a value
    # registered first, and the root is the one `CLAUDE_PROJECT_DIR` names in each, never the
    # checkout `cwd` sits in. Each run records the harness `dispatch` was handed, so the three
    # steers are known to have reached three harnesses rather than Claude Code three times.
    # Mutations (declared, on `hooks.commands`): the event is read with no environment under a
    # harness that names no root variable -> the Codex event's root is the other checkout and
    # this reddens; detection is asked with neither environment nor payload -> every run is
    # Claude Code's and this reddens.
    project = tmp_path / "project"
    project.mkdir()
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    fake = _harness(
        lambda name, context, notice: context, detects=lambda env, payload: "FAKE_HARNESS" in env
    )
    monkeypatch.setattr("stayfixed.harnesses.HARNESSES", (fake, *HARNESSES))
    monkeypatch.setattr("stayfixed.gitenv._git_toplevel", _forbidden)
    seen: list[HookEvent] = []
    detected: list[str] = []

    def answered(*args: Any, harness: Harness, **kwargs: Any) -> Any:
        detected.append(harness.name)
        return dispatch(*args, harness=harness, **kwargs)

    monkeypatch.setattr("stayfixed.hooks.commands.dispatch", answered)

    def note(ev: HookEvent, config: object) -> HookResult:
        seen.append(ev)
        return HookResult()

    probe = Handler(name="probe", event="PreToolUse", run=note)
    payload: dict[str, object] = {"cwd": str(other), "session_id": "s", "tool_name": "Bash"}
    for steer in ({}, {"PLUGIN_ROOT": "/r"}, {"FAKE_HARNESS": "1"}):
        monkeypatch.delenv("FAKE_HARNESS", raising=False)
        env = {**steer, "CLAUDE_PROJECT_DIR": str(project)}
        assert _hook(monkeypatch, "PreToolUse", payload, probe, env=env) == 0
    assert detected == ["claude", "codex", "fake"]
    assert [ev.project_root for ev in seen] == [project] * 3
    assert seen[0] == seen[1] == seen[2]


def test_an_unknown_harness_renders_the_canonical_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No harness variable and no field only Codex sends: detection still answers, with Claude
    # Code's schema, which other harnesses imitate. Pinned as the bytes a harness reads rather
    # than compared with `CANONICAL.render`, which would agree with whatever it was changed to.
    # Mutation (by hand): the canonical render's `additionalContext` misspelled -> reddens.
    (tmp_path / ".git").mkdir()
    probe = Handler(
        name="probe",
        event="PreToolUse",
        run=lambda ev, config: HookResult(context="a note"),
    )
    payload: dict[str, object] = {"cwd": str(tmp_path), "tool_name": "Bash"}
    assert _hook(monkeypatch, "PreToolUse", payload, probe) == 0
    assert capsys.readouterr().out == (
        '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "a note"}}'
    )


def test_a_clamped_answer_is_the_detected_harnesss_envelope() -> None:
    # The cap bounds the string the harness reads, so the largest prefix that fits is searched
    # for in the detected harness's own envelope; one measured against Claude Code's would be the
    # wrong width for any other. Mutation (declared, on `hooks.dispatch`): the clamp handed
    # `CANONICAL.render` -> the clamped stdout is Claude Code's JSON and this reddens.
    def wide(name: str, context: str, notice: str) -> str:
        return json.dumps({"an-envelope-of-another-width": {"event": name, "text": context}})

    handlers = [handler("a", HookResult(context="y" * 500))]
    recorder = Recorder()
    outcome = dispatch(event(), handlers, NO_CONFIG, harness=_harness(wide), sink=recorder, cap=200)
    assert len(outcome.stdout) == 200
    text = json.loads(outcome.stdout)["an-envelope-of-another-width"]["text"]
    assert text == "y" * (len(text) - len(TRUNCATION_MARK)) + TRUNCATION_MARK
    assert recorder.records == [
        {"event": "PreToolUse", "handler": "*", "error": "context-truncated"}
    ]
