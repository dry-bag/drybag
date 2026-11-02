"""The floor: a session's guards run whatever its configuration, and a configuration that does not
load whole is said once, at `SessionStart`, and never refuses a tool call
(`src/stayfixed/config/session.py`, `src/stayfixed/hooks/commands.py`).

Every hook here is a real `stayfixed hook` process (`tests/hooks/test_hook_command.py`'s `hook`),
under a home of its own: the machine file a hook reads is `<home>/.config/stayfixed/config.toml`,
and none of these reads the developer's."""

from __future__ import annotations

import json
import resource
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from stayfixed.attach.hooks import register as attach_handlers
from stayfixed.config.session import (
    FALLBACK_WARNING,
    MACHINE_FILE_WARNING,
    NEWER_RELEASE_WARNING,
    SessionConfig,
    session_config,
)
from stayfixed.hints.hooks import register as hints_handlers
from stayfixed.hooks.api import DIAGNOSTICS, DIRECTORY, Handler, HookEvent, HookResult
from stayfixed.hooks.commands import CONFIG_FALLBACK
from tests.config.test_session import densest_file, long_file_of_gates_that_run
from tests.gitfixture import git
from tests.hooks.test_hook_command import (
    BACKGROUND_SLEEP,
    CONFIG,
    TOOL_CALL,
    hinted,
    hook,
    notice_texts,
)
from tests.memory.test_commands import CONFIG as MEMORY_CONFIG
from tests.memory.test_commands import NOTE, invoke
from tests.sessions import NO_CONFIG

SESSION_START = {"hook_event_name": "SessionStart", "session_id": "floor"}
LATER = CONFIG.replace('version = "0.1.0"', 'version = "999.0.0"')


def machine_with(home: Path, text: str) -> None:
    """The machine file of the hook's home."""
    directory = home / ".config" / "stayfixed"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.toml").write_text(text, encoding="utf-8")


def no_file(root: Path, home: Path) -> None:
    return None


def unparseable(root: Path, home: Path) -> None:
    (root / "stayfixed.toml").write_text("[[[", encoding="utf-8")


def newer_release(root: Path, home: Path) -> None:
    # A file a newer release wrote: an unknown section, an unknown key and an unknown enum value
    # together.
    text = LATER + '\n[newer]\nx = 1\n[memory]\nmode = "cloud"\nfuture = 1\n'
    (root / "stayfixed.toml").write_text(text, encoding="utf-8")


def broken_machine_file(root: Path, home: Path) -> None:
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    machine_with(home, "[guards\n")


def both_broken(root: Path, home: Path) -> None:
    unparseable(root, home)
    machine_with(home, "[guards\n")


def _setup(tmp_path: Path, project: Callable[[Path, Path], None]) -> tuple[Path, Path]:
    root = tmp_path / "project"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    project(root, home)
    return root, home


@pytest.mark.parametrize(
    "project",
    [no_file, unparseable, newer_release, broken_machine_file, both_broken],
    ids=lambda f: f.__name__,
)
def test_the_background_guard_judges_whatever_the_configuration(
    tmp_path: Path, project: Callable[[Path, Path], None]
) -> None:
    # With no stayfixed.toml the guard said nothing; with one that did not load, or a broken
    # machine file, every tool call was refused. Now the guard judges in each, on the preset and
    # the owner's layer. Mutation (`mutations/`'s "a session lets a file that is not TOML raise"):
    # `unparseable` refuses `ls` too.
    root, home = _setup(tmp_path, project)
    assert hinted(hook("PreToolUse", json.dumps(BACKGROUND_SLEEP), root, home=home))
    allowed = hook("PreToolUse", json.dumps(TOOL_CALL), root, home=home)
    # The control: never refused for its configuration.
    assert (allowed.returncode, allowed.stderr) == (0, "")


# Ten thousand custom gates that cannot run: about 200 KB of committed `stayfixed.toml`. Read key by
# key, each gate cost the NOTE load a whole build, and the hook ran past its ten-second timeout,
# which Claude Code answers by letting the call through.
MANY_UNUSABLE_GATES = (
    CONFIG + "\n[gates.custom]\n" + "".join(f"g{n} = {{ run = [] }}\n" for n in range(10_000))
)
# Well above what the hook takes with the file refused whole, and well below the ten-second
# timeout `hooks/hooks.json` gives the `PreToolUse` entry.
HOOK_BOUND_SECONDS = 5
# The most a hook may spend on the densest file, as a multiple of what it spends on the same gates
# built once: five builds at the read cap, with the parse and the start-up, come to one and a half
# times the one build, and 65 builds to ten or eleven. Two hooks on the same machine, so a slower
# runner moves both sides of the ratio, and four leaves room on each: eight such tests at once, or
# one on efficiency cores, put the five builds at 1.5 to 1.6.
DENSE_BUILDS_BOUND = 4


def test_a_file_of_thousands_of_unusable_keys_never_outlasts_the_hook(tmp_path: Path) -> None:
    # The guard's own verdict, in time: the file is refused whole past `NOTE_REMOVAL_LIMIT`
    # removals, so the hook answers on the preset and the owner's layer long before the harness
    # would give up on it. Mutation (`mutations/`'s "the NOTE path removes every key it cannot use,
    # however many"): the hook takes about fifteen seconds.
    root, home = _setup(tmp_path, no_file)
    (root / "stayfixed.toml").write_text(MANY_UNUSABLE_GATES, encoding="utf-8")
    started = time.monotonic()
    answer = hook("PreToolUse", json.dumps(BACKGROUND_SLEEP), root, home=home)
    elapsed = time.monotonic() - started
    assert hinted(answer)
    assert elapsed < HOOK_BOUND_SECONDS, elapsed


def _hook_seconds(tmp_path: Path, document: str) -> float:
    """The CPU time a `PreToolUse` hook spends hinting at a background sleep beside `document`.

    Counted in the hook's own process: timed inside the suite's process, a CI runner measured its
    coverage tracer and its scheduler, 6.6 s for a read that takes 0.4 s, and neither is what a
    session pays. CPU time and not the wall clock, which the suite's other workers stretch."""
    tmp_path.mkdir(exist_ok=True)
    root, home = _setup(tmp_path, no_file)
    (root / "stayfixed.toml").write_text(document, encoding="utf-8")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    answer = hook("PreToolUse", json.dumps(BACKGROUND_SLEEP), root, home=home)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    assert hinted(answer)
    return (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)


def test_a_long_file_of_gates_that_run_never_outlasts_the_hook(tmp_path: Path) -> None:
    # A file of thousands of gates that run is built once per removal its length allows
    # (`loader.NOTE_REBUILT_LIMIT`), so what one build costs is paid that often, and the hook still
    # answers well inside its timeout. By hand, `_enforcement` asking the tuple of gate names
    # rather than a set: the hook takes about ten seconds of CPU.
    spent = _hook_seconds(tmp_path, long_file_of_gates_that_run())
    assert spent < HOOK_BOUND_SECONDS, spent


def test_the_densest_file_a_session_reads_never_outlasts_the_hook(tmp_path: Path) -> None:
    # Dotted gates that run, filled to the read cap, beside 64 keys the NOTE load cannot use, each
    # refused only once every gate before it is built (`tests/config/test_session.py`'s
    # `densest_file`): built five times, the most its length allows, and dropped whole, so the hook
    # spends about 0.4 s of CPU here, one and a half times what the same gates built once cost it.
    # Under the hook's bound, and the ratio is what tells five builds from 65, which the bound
    # alone could not: mutation (`mutations/`'s "the NOTE path's removals are bounded by their
    # count alone"), the hook spends 2.2 to 2.9 s, ten times what the one build costs it. The one
    # build is timed first, so a cold bytecode cache, paid by the first hook, can only lower the
    # ratio.
    once = _hook_seconds(tmp_path / "once", densest_file(unusable=False))
    spent = _hook_seconds(tmp_path / "unusable", densest_file())
    assert spent < HOOK_BOUND_SECONDS, spent
    assert spent < DENSE_BUILDS_BOUND * once, (spent, once)


# A `[paths]` value of forty thousand components, eighty kilobytes, none of which is there.
DEEP_PATH = "a/" * 40_000 + "AGENTS.md"


def test_a_path_value_of_thousands_of_components_never_outlasts_the_hook(tmp_path: Path) -> None:
    # `contained()` walked up from the target, building every ancestor and comparing it with the
    # root, and compared every parent of the resolved target with the root again, so each hook
    # took seconds over this one value. It is held twice, and no one mutation reddens it: the value
    # is longer than `config.paths.PATH_VALUE_LIMIT` allows, so the NOTE load puts the preset's
    # back before `contained()` sees it (`mutations/`'s "a [paths] value may be any length"), and
    # `contained()` walks down and stops at the first ancestor that is not there (`mutations/`'s
    # "contained asks every ancestor of a value that reaches no file"). By hand, both undone: the
    # hook spends 11.6 s of CPU, against 0.14 s.
    spent = _hook_seconds(tmp_path, CONFIG + f'\n[paths]\nagents_md = "{DEEP_PATH}"\n')
    assert spent < HOOK_BOUND_SECONDS, spent


def test_the_owner_switches_the_guard_off_with_no_stayfixed_toml(tmp_path: Path) -> None:
    # No `stayfixed.toml`, and the machine file switches the background guard off: the machine
    # file is read with no project configuration too.
    root, home = _setup(tmp_path, no_file)
    machine_with(home, "[guards]\nbg_cleanup = false\n")
    assert not hinted(hook("PreToolUse", json.dumps(BACKGROUND_SLEEP), root, home=home))
    machine_with(home, "")  # the control
    assert hinted(hook("PreToolUse", json.dumps(BACKGROUND_SLEEP), root, home=home))


def test_a_repository_sets_the_guards_default_and_the_owner_overrides_it(tmp_path: Path) -> None:
    # The same switch in `stayfixed.toml` is the repository's default: the guard is off, until the
    # machine file, one of the owner's layers above it, switches it back on.
    root, home = _setup(tmp_path, no_file)
    (root / "stayfixed.toml").write_text(CONFIG + "\n[guards]\nbg_cleanup = false\n", "utf-8")
    assert not hinted(hook("PreToolUse", json.dumps(BACKGROUND_SLEEP), root, home=home))
    machine_with(home, "[guards]\nbg_cleanup = true\n")
    assert hinted(hook("PreToolUse", json.dumps(BACKGROUND_SLEEP), root, home=home))


@pytest.mark.parametrize(
    ("project", "warnings"),
    [
        (unparseable, [FALLBACK_WARNING]),
        (newer_release, [NEWER_RELEASE_WARNING.format(count=3)]),
        (broken_machine_file, [MACHINE_FILE_WARNING]),
        (both_broken, [FALLBACK_WARNING, MACHINE_FILE_WARNING]),
    ],
    ids=["unparseable", "newer-release", "broken-machine-file", "both-broken"],
)
def test_session_start_carries_each_warning_once(
    tmp_path: Path, project: Callable[[Path, Path], None], warnings: list[str]
) -> None:
    # Parsed, never a raw-string count: once to the person, once to the model, ahead of any
    # handler's context. Mutations (`mutations/`'s "the notice never reaches the person" -> the
    # `systemMessage` is empty; "the notice never reaches the model" -> the context lacks it).
    root, home = _setup(tmp_path, project)
    started = hook("SessionStart", json.dumps(SESSION_START), root, home=home)
    assert (started.returncode, started.stderr) == (0, "")
    person, model = notice_texts(json.loads(started.stdout))
    # The machine file's warning names the file the hook read, under its pinned home.
    warnings = [w.format(path=home / ".config" / "stayfixed" / "config.toml") for w in warnings]
    assert person == warnings
    assert model[: len(warnings)] == warnings
    assert all(model.count(warning) == 1 for warning in warnings)


def test_pre_tool_use_prints_no_warning_and_logs_it_once(tmp_path: Path) -> None:
    # A notice on every tool call would repeat itself, and a refused call's stderr is the
    # model's: the tool call's answer is the bare envelope, and the sink records the fallback
    # once for the session. Mutations (`mutations/`'s "dispatch renders the notice on every
    # event" -> stdout carries it; "the hook logs a configuration fallback on every call" -> two
    # records; "the hook never logs a configuration fallback" -> none).
    root, home = _setup(tmp_path, unparseable)
    data = tmp_path / "data"
    data.mkdir()
    call = {**TOOL_CALL, "session_id": "floor"}
    for _ in range(2):
        completed = hook("PreToolUse", json.dumps(call), root, data=data, home=home)
        assert (completed.returncode, completed.stderr) == (0, "")
        assert json.loads(completed.stdout) == {
            "hookSpecificOutput": {"hookEventName": "PreToolUse"}
        }
    log = (data / DIRECTORY / DIAGNOSTICS).read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in log]
    assert [record.get("error") for record in records] == [CONFIG_FALLBACK]


# A real file under which each handler about the project speaks, and the handler.
def _overlay_status(root: Path) -> tuple[Handler, HookEvent]:
    text = CONFIG + '\n[memory]\nmode = "overlay"\n'
    (root / "stayfixed.toml").write_text(text, encoding="utf-8")
    handler = next(h for h in attach_handlers() if h.name == "overlay-status")
    return handler, _event("SessionStart", root)


def _test_hygiene(root: Path) -> tuple[Handler, HookEvent]:
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    git(root, "init", "-q")
    handler = next(h for h in hints_handlers() if h.event == "PostToolUseFailure")
    event = _event("PostToolUseFailure", root, {"command": "uv run pytest -q"})
    event.raw["error"] = "Exit code 1"
    return handler, event


def _event(name: str, root: Path, tool_input: dict[str, object] | None = None) -> HookEvent:
    given = tool_input or {}
    return HookEvent(
        name=name,
        session_id="floor",
        agent_id=None,
        tool_name="Bash" if tool_input else None,
        tool_input=given,
        cwd=root,
        project_root=root,
        raw={"tool_name": "Bash", "tool_input": given} if tool_input else {},
    )


def run_handler(handler: Handler, event: HookEvent, session: SessionConfig) -> HookResult:
    return handler.run(event, session)


@pytest.mark.parametrize("speaks", [_overlay_status, _test_hygiene], ids=lambda f: f.__name__[1:])
def test_project_handlers_speak_on_a_file_and_stay_silent_without_one(
    tmp_path: Path, speaks: Callable[[Path], tuple[Handler, HookEvent]]
) -> None:
    # A handler about the project answers nothing without its configuration, and something with
    # it: the first half alone would pass for a handler that never speaks. Mutations
    # (`mutations/`'s "the overlay status judges with no project configuration" ->
    # `overlay_status` raises on `None`; "the hygiene note judges with no project configuration"
    # -> `test_hygiene` raises on `None`).
    root = tmp_path / "project"
    root.mkdir()
    handler, event = speaks(root)
    assert run_handler(handler, event, session_config(root, machine=tmp_path / "none.toml")).context
    assert not run_handler(handler, event, NO_CONFIG).context


def test_memory_session_context_reads_a_newer_key_with_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # `memory session-context` refused a file a newer stayfixed wrote, so every bundle a session
    # starts with came back empty. It reads the file the way a session does now. Mutation
    # (`mutations/`'s "memory session-context refuses what a session reads"): nothing is printed.
    root = tmp_path / "project"
    notes = root / ".stayfixed" / "local" / "memory" / "project-volatile"
    notes.mkdir(parents=True)
    meta = "metadata:\n  type: project\n"
    (notes / "a.md").write_text(NOTE.format(name="a", meta=meta, body="Body."), encoding="utf-8")
    (root / "stayfixed.toml").write_text(MEMORY_CONFIG, encoding="utf-8")
    machine = tmp_path / "machine.toml"
    machine.write_text("", encoding="utf-8")
    common = ["--root", str(root), "--machine", str(machine)]
    with (root / "stayfixed.toml").open("a", encoding="utf-8") as document:
        document.write("\n[newer]\nx = 1\n")
    capsys.readouterr()
    argv = ["memory", "session-context", "--bundle", "volatile-notes", *common]
    assert invoke(argv) == 0
    assert "Body." in capsys.readouterr().out


def test_memory_session_context_reads_past_a_broken_machine_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A machine file that does not load ended `memory session-context` with exit 1 in every memory
    # mode, so a session lost its notes while its `SessionStart` notice said the preset's
    # values stood in. The store now reads such a file as no overlay recorded, and the notes still
    # arrive. Mutation (`mutations/`'s "the store's overlay read lets a machine file it cannot read
    # end a session's notes"): exit 1 and nothing printed.
    root = tmp_path / "project"
    notes = root / ".stayfixed" / "local" / "memory" / "project-volatile"
    notes.mkdir(parents=True)
    meta = "metadata:\n  type: project\n"
    (notes / "a.md").write_text(NOTE.format(name="a", meta=meta, body="Body."), encoding="utf-8")
    (root / "stayfixed.toml").write_text(MEMORY_CONFIG, encoding="utf-8")
    machine = tmp_path / "machine.toml"
    machine.write_text("", encoding="utf-8")
    common = ["--root", str(root), "--machine", str(machine)]
    machine.write_text("[overlay\n", encoding="utf-8")
    capsys.readouterr()
    argv = ["memory", "session-context", "--bundle", "volatile-notes", *common]
    assert invoke(argv) == 0
    assert "Body." in capsys.readouterr().out
