from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.harnesses import CLAUDE
from stayfixed.hints import bgcleanup
from stayfixed.hints.hooks import register
from stayfixed.hooks.api import EVENTS, Handler, HookEvent
from stayfixed.hooks.dispatch import Recorder, dispatch
from tests.floor import floor_env
from tests.gitfixture import git
from tests.sessions import NO_CONFIG, session_of

ROOT = Path(__file__).resolve().parents[2]
CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
release_branch = "main"
"""

LIST_IMPORTS = (
    "import sys\n"
    "from stayfixed.hooks.registry import discover\n"
    "names = [h.name for h in discover()]\n"
    "assert 'bg-cleanup' in names, names\n"
    "print(' '.join(sorted(m for m in sys.modules if m.startswith('stayfixed'))))\n"
)


def a_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    return root


def bash_event(
    root: Path, command: str, *, background: bool = True, tool: str = "Bash"
) -> HookEvent:
    tool_input: dict[str, object] = {"command": command}
    if background:
        tool_input["run_in_background"] = True
    return HookEvent(
        name="PreToolUse",
        session_id="s1",
        agent_id=None,
        tool_name=tool,
        tool_input=tool_input,
        cwd=root,
        project_root=root,
        raw={"tool_name": tool, "tool_input": tool_input},
    )


def guard() -> Handler:
    return next(h for h in register() if h.name == "bg-cleanup")


def test_every_handler_declares_a_known_event() -> None:
    handlers = register()
    assert handlers != []
    for handler in handlers:
        assert handler.event in EVENTS


def test_no_config_silences_the_hygiene_note_and_never_the_guard(tmp_path: Path) -> None:
    # With no stayfixed.toml the guard was silent too, by design, so a repository that had not
    # run `stayfixed init` was not guarded. It judges with any configuration now, none included,
    # and the hygiene note, which is about the project, stays silent. Mutation (`mutations/`'s
    # "the hygiene note judges with no project configuration"): the note raises on `None`.
    verdicts = {
        (handler.name, handler.event): handler.run(bash_event(tmp_path, "sleep 300 &"), NO_CONFIG)
        for handler in register()
    }
    assert verdicts["bg-cleanup", "PreToolUse"].context == bgcleanup.SLEEP_HINT
    for event in ("PostToolUse", "PostToolUseFailure"):
        assert verdicts["test-hygiene", event].context is None


def test_a_leaking_background_call_is_hinted(tmp_path: Path) -> None:
    root = a_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    result = guard().run(bash_event(root, "python -m http.server 8000 &"), session_of(config))
    assert result.context == bgcleanup.LEAK_HINT


def test_every_leaking_call_of_a_session_is_hinted_not_only_the_first(tmp_path: Path) -> None:
    # The guard carries no `once_key`: the dispatcher banks one after any delivery, so with a key
    # the second leaking call of a session would go unnamed. Two calls through the dispatcher and
    # one recording sink, which is where that key is banked.
    root = a_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    recorder = Recorder()
    for _ in range(2):
        outcome = dispatch(
            bash_event(root, "python -m http.server 8000 &"),
            register(),
            session_of(config),
            harness=CLAUDE,
            sink=recorder,
        )
        output = json.loads(outcome.stdout)["hookSpecificOutput"]
        assert (outcome.exit_code, output["additionalContext"]) == (0, bgcleanup.LEAK_HINT)


def test_a_non_bash_tool_is_ignored(tmp_path: Path) -> None:
    # Carries `run_in_background: true` deliberately: without it the flag check would be what
    # stops this event, and the assertion would say nothing about `tool_name`.
    root = a_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    result = guard().run(bash_event(root, "sleep 300 &", tool="Edit"), session_of(config))
    assert result.context is None


def test_a_trailing_restore_arrives_as_context_not_a_decision(tmp_path: Path) -> None:
    root = a_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    command = "cp a a.bak; sed -i '' 's/x/y/' a; pytest; cp a.bak a"
    result = guard().run(bash_event(root, command, background=False), session_of(config))
    assert result.context is not None and "trap" in result.context


def test_a_masking_echo_arrives_as_context_not_a_decision(tmp_path: Path) -> None:
    root = a_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    command = 'pytest -q > out.log 2>&1; echo "EXIT=$?" >> out.log'
    result = guard().run(bash_event(root, command, background=True), session_of(config))
    assert result.context is not None and "notification" in result.context


def test_discovery_imports_no_guards_module_but_hooks(tmp_path: Path) -> None:
    # Every real import lives inside a handler body, so registering costs discovery nothing.
    completed = subprocess.run(
        [sys.executable, "-c", LIST_IMPORTS],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")},
    )
    assert completed.returncode == 0, completed.stderr
    imported = set(completed.stdout.split())
    assert "stayfixed.hints.hooks" in imported
    assert "stayfixed.hints.bgcleanup" not in imported
    assert "stayfixed.hints.bashscan" not in imported
    # The test-hygiene notice's modules, named explicitly: `hygiene` imports `bashscan` and
    # `gitenv` at module scope, so a module-level import of it in `hooks.py` would be caught by
    # the line above too — but only by accident of what it happens to import.
    assert "stayfixed.hints.hygiene" not in imported
    assert "stayfixed.config" not in imported


def hook(event: str, stdin: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    # A home of its own with no machine file, so nothing of the developer's is read.
    home = cwd.parent / "no-home"
    return subprocess.run(
        [sys.executable, "-m", "stayfixed", "hook", event],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(ROOT / "src"),
            "HOME": str(home),
            "CLAUDE_PROJECT_DIR": str(cwd),
            **floor_env(),
        },
    )


def test_a_leaking_background_call_is_hinted_through_the_real_dispatcher(tmp_path: Path) -> None:
    # The production path end to end: stdin in, the hint out. This is what the wrapper runs.
    root = a_project(tmp_path)
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": "sleep 300 &", "run_in_background": True},
    }
    completed = hook("PreToolUse", json.dumps(payload), root)
    output = json.loads(completed.stdout)["hookSpecificOutput"]
    assert (completed.returncode, output["additionalContext"]) == (0, bgcleanup.SLEEP_HINT)
    allowed = dict(payload, tool_input={"command": "make && make test", "run_in_background": True})
    completed = hook("PreToolUse", json.dumps(allowed), root)
    assert completed.returncode == 0, completed.stderr
    assert "additionalContext" not in json.loads(completed.stdout)["hookSpecificOutput"]


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def post_event(
    root: Path, command: str, raw_extra: dict[str, object], *, name: str = "PostToolUse"
) -> HookEvent:
    tool_input: dict[str, object] = {"command": command}
    raw: dict[str, object] = {"tool_name": "Bash", "tool_input": tool_input, **raw_extra}
    return HookEvent(
        name=name,
        session_id="s1",
        agent_id=None,
        tool_name="Bash",
        tool_input=tool_input,
        cwd=root,
        project_root=root,
        raw=raw,
    )


def dirty_project(tmp_path: Path) -> Path:
    # A tracked file modified after its commit, not merely an untracked one: the dirty count
    # comes from `git status --porcelain` under the owner's own git, and
    # `status.showUntrackedFiles = no` or a broad excludes file would hide an untracked file.
    root = a_project(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "m.py").write_text("x = 1\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "chore: seed"]):
        git(root, *args, home=tmp_path)
    (root / "src" / "m.py").write_text("x = 2\n", encoding="utf-8")
    return root


def hygiene(event: str = "PostToolUse") -> Handler:
    """The `test-hygiene` handler registered on `event`: it is registered on two."""
    return next(h for h in register() if h.name == "test-hygiene" and h.event == event)


# The two events the red-run note is registered on: Claude Code's `PostToolUseFailure`, and
# `PostToolUse`, where Codex delivers a failed command but no exit code to read.
RED_RUN_EVENTS = ("PostToolUse", "PostToolUseFailure")


@pytest.mark.parametrize("event", RED_RUN_EVENTS)
def test_the_hygiene_notice_has_one_once_key_on_each_event(event: str) -> None:
    # `once_key` is asserted against the literal "test-hygiene" rather than against
    # `ONCE_TEST_HYGIENE`, so the expected value is a fixed one and not one read from the subject;
    # it is the same literal on both events because one key is what holds a context to one note,
    # whichever event carries it.
    handler = hygiene(event)
    assert handler.event == event
    assert handler.once_key == "test-hygiene"


@needs_git
@pytest.mark.parametrize(
    "extra", [{"tool_response": {"exit_code": 1}}, {"error": "Exit code 1\nFAILED"}]
)
def test_a_red_pytest_over_a_dirty_tree_is_noticed(
    tmp_path: Path, extra: dict[str, object]
) -> None:
    # Both payload shapes through the handler, not only through `red_exit`: which field says a
    # run was red depends on what the harness actually sends, so the parametrisation has to
    # reach `event.raw`.
    # Reddened by mutating `_test_hygiene`'s last line to `return HookResult()`; measured.
    root = dirty_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    result = hygiene().run(post_event(root, "pytest -q", extra), session_of(config))
    assert result.context is not None and "uncommitted" in result.context


@needs_git
def test_a_green_run_or_a_non_pytest_command_is_silence(tmp_path: Path) -> None:
    # Reddened by dropping `_test_hygiene`'s `if red_exit(event.raw) is None: return
    # HookResult()` (the first assertion) and by dropping `context_for`'s `if not speaking:
    # return None` (the second); both measured.
    root = dirty_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    assert (
        hygiene()
        .run(post_event(root, "pytest -q", {"tool_response": {"stdout": "ok"}}), session_of(config))
        .context
        is None
    )
    assert (
        hygiene()
        .run(post_event(root, "ls", {"tool_response": {"exit_code": 1}}), session_of(config))
        .context
        is None
    )


@needs_git
@pytest.mark.parametrize(
    ("command", "noted"),
    [
        ("cargo test -q", True),
        ("FOO=1 uv run --locked go test ./...", True),
        ("poetry run pytest", False),
    ],
)
def test_the_note_follows_the_runner_table(tmp_path: Path, command: str, noted: bool) -> None:
    # Which failed command is a test run is `runners.names_a_test_run`'s answer for one of its
    # simple commands, unwrapped behind assignments and `uv run` the way the table's other caller
    # unwraps them, whatever the stack: `cargo test` gets the note, and `poetry run`, a launcher
    # the scanner does not read through, is no test run.
    root = dirty_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    result = hygiene().run(
        post_event(root, command, {"tool_response": {"exit_code": 1}}), session_of(config)
    )
    assert (result.context is not None) is noted


# One red run in each event's own shape: an exit code in `tool_response`, which `red_exit` reads
# on `PostToolUse`, and Claude Code's `error` on `PostToolUseFailure`.
RED_ON: dict[str, dict[str, object]] = {
    "PostToolUse": {"tool_response": {"exit_code": 1}},
    "PostToolUseFailure": {"error": "Exit code 1"},
}


@needs_git
@pytest.mark.parametrize("event", RED_RUN_EVENTS)
def test_a_hygiene_failure_is_recorded_and_never_costs_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str
) -> None:
    # The dispatcher swallows and records. The handler does not need its own try/except, and
    # must not have one — a silent swallow is how a broken notice goes unnoticed. The stderr
    # assertion is reddened by giving `_test_hygiene` its own try/except around `context_for`.
    from stayfixed.hints import hygiene as module

    def broken(command: str, root: Path) -> str | None:
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "context_for", broken)
    root = dirty_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    recorder = Recorder()
    outcome = dispatch(
        post_event(root, "pytest", RED_ON[event], name=event),
        register(),
        session_of(config),
        harness=CLAUDE,
        sink=recorder,
    )
    assert outcome.exit_code == 0
    assert "test-hygiene: RuntimeError: boom" in outcome.stderr


@needs_git
def test_an_unrelated_call_does_not_consume_the_one_delivery(tmp_path: Path) -> None:
    # The defect this pins: `dispatch` used to call `sink.mark(handler.once_key)` after EVERY
    # successful run, including one that returned an empty `HookResult`, so once a durable
    # sink exists the first unrelated Bash call of a session silently spends this handler's
    # single delivery.
    root = dirty_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    recorder = Recorder()
    dispatch(
        post_event(root, "ls", {"tool_response": {"stdout": ""}}),
        register(),
        session_of(config),
        harness=CLAUDE,
        sink=recorder,
    )
    outcome = dispatch(
        post_event(root, "pytest", {"tool_response": {"exit_code": 1}}),
        register(),
        session_of(config),
        harness=CLAUDE,
        sink=recorder,
    )
    assert "uncommitted" in json.loads(outcome.stdout)["hookSpecificOutput"].get(
        "additionalContext", ""
    )


@needs_git
@pytest.mark.parametrize(
    "order", [RED_RUN_EVENTS, RED_RUN_EVENTS[::-1]], ids=["post-first", "failure-first"]
)
def test_the_red_run_note_is_delivered_once_per_context_whichever_event_carries_it(
    tmp_path: Path, order: tuple[str, str]
) -> None:
    # Two different red runs in one session, one on each event the note is registered on,
    # through the dispatcher and one recording sink, which is where the dispatcher banks a
    # `once_key`: the note is delivered for the first and not for the second, in either order,
    # because both registrations carry the one key. No measured harness delivers one red run on
    # both events; what the key holds is at most one note per context. Mutation:
    # `mutations/`'s "the red-run hint on a failure forgets that the note was delivered".
    root = dirty_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    recorder = Recorder()
    notes = []
    for event in order:
        outcome = dispatch(
            post_event(root, "pytest -q", RED_ON[event], name=event),
            register(),
            session_of(config),
            harness=CLAUDE,
            sink=recorder,
        )
        assert outcome.exit_code == 0, outcome.stderr
        output = json.loads(outcome.stdout)["hookSpecificOutput"]
        assert output["hookEventName"] == event
        notes.append(output.get("additionalContext"))
    assert notes[0] is not None and "uncommitted" in notes[0]
    assert notes[1] is None


# One red run, as Claude Code reports a Bash command that exited non-zero: on `PostToolUseFailure`,
# with no `tool_response`, and the exit code at the head of `error`. The command is a test run the
# runner table names, so the note speaks.
RED_RUN = "uv run pytest -q"


def failure_payload(root: Path, error: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PostToolUseFailure",
            "session_id": "s",
            "cwd": str(root),
            "tool_name": "Bash",
            "tool_input": {"command": RED_RUN},
            "error": error,
        }
    )


@needs_git
@pytest.mark.parametrize(
    "error",
    [
        "Exit code 1",
        "Exit code 1\nFAILED tests/test_m.py::test_x - assert 1 == 2",
        "Exit code 143\nCommand timed out after 4s",
    ],
    ids=["bare", "with-output", "killed-at-its-timeout"],
)
def test_a_red_run_on_post_tool_use_failure_is_annotated(tmp_path: Path, error: str) -> None:
    # The hint was registered on `PostToolUse` alone, and Claude Code delivers a Bash command that
    # exits non-zero to `PostToolUseFailure` and never to `PostToolUse`: the note never reached a
    # red run there. `bare` is the shape measured on Claude Code 2.1.296 for `false`, the exit
    # code and nothing after it; `killed-at-its-timeout` the shape it gave, with background tasks
    # disabled, for a foreground command killed at its timeout, a real non-zero exit annotated
    # like any red run. Through the real dispatcher, so what is asserted is what the harness
    # reads. Mutation: `mutations/`'s "the red-run hint is not registered on the event a failed
    # command arrives on".
    root = dirty_project(tmp_path)
    completed = hook("PostToolUseFailure", failure_payload(root, error), root)
    assert completed.returncode == 0, completed.stderr
    out = json.loads(completed.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"
    assert "uncommitted" in out["hookSpecificOutput"]["additionalContext"]


@needs_git
def test_a_failure_whose_error_does_not_begin_with_an_exit_code_is_not_annotated(
    tmp_path: Path,
) -> None:
    # The same fixture and command as the cases above, with an `error` whose first line is not
    # the exit code: the hint says nothing rather than guess at what failed. The shape is an
    # assumption, not one observed on Claude Code 2.1.296, which put the exit code first in every
    # failure measured. Beside its positive twins this is what shows the handler, not the absence
    # of one, is what stays silent. Silent as the dispatcher says it: the event's envelope with
    # no context in it, which it writes for every event it dispatches.
    root = dirty_project(tmp_path)
    error = "Command timed out after 2m 0s\nExit code 143"
    completed = hook("PostToolUseFailure", failure_payload(root, error), root)
    assert completed.returncode == 0, completed.stderr
    out = json.loads(completed.stdout)
    assert out == {"hookSpecificOutput": {"hookEventName": "PostToolUseFailure"}}
