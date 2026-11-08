"""Contracts for the pipe hint: a test run piped into a reader without `pipefail`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drybag.harnesses import CLAUDE
from drybag.hints import bgcleanup
from drybag.hints.hooks import register
from drybag.hints.pipes import NOTICE, notice_for
from drybag.hooks.api import Handler, HookEvent
from drybag.hooks.dispatch import Recorder, dispatch
from tests.hints.test_hooks import bash_event
from tests.sessions import NO_CONFIG


@pytest.mark.parametrize(
    "command",
    [
        "pytest -x 2>&1 | tail -20",
        "cargo test 2>&1 | head -50",
        "npm test | grep -i fail",
        "go test ./... | tee log | tail",
        "cd a && pytest | tail",
        "pytest -x 2>&1 |\n  tail -20",
        "pytest | grep -E '(FAIL|ERROR)'",
        "pytest tests/{a,b}.py | tail",
        "pytest ${ARGS} | tail",
        'pytest -k "not (slow)" | tail',
        "uv run pytest | grep FAIL",
        "PYTHONPATH=src pytest | tail",
    ],
)
def test_a_test_run_piped_into_a_reader_gets_the_hint(command: str) -> None:
    assert notice_for(command) == NOTICE


@pytest.mark.parametrize(
    "command",
    [
        "set -o pipefail; pytest | tail",
        "set -euo pipefail\npytest | tail",
        "pytest | tail; echo ${PIPESTATUS[0]}",
        "pytest | tee log",
        "pytest > log; tail log",
        "pytest; ls | tail",
        "grep x log | tail",
        "tail -f log | grep pytest",
        "pytest 'a | tail",
        "setopt PIPE_FAIL; pytest | tail",
        "setopt pipe_fail; pytest | tail",
        "pytest | tail; echo $pipestatus[1]",
        "pytest $(git ls-files | head -3)",
        "pytest `git ls-files | head -3`",
        "(pytest | tail)",
        "{ pytest | tail; }",
        "cat <<EOF\npytest | tail\nEOF",
    ],
)
def test_no_hint_where_the_status_is_kept_or_no_test_run_is_piped(command: str) -> None:
    assert notice_for(command) is None


def test_a_reader_ahead_of_the_run_is_not_the_hint() -> None:
    # The reader must come after the run: `tail` feeding `pytest` hides nothing of its status.
    assert notice_for("tail -n 5 list | pytest") is None


def test_a_command_past_the_scan_cap_is_not_read() -> None:
    padding = "echo " + "x" * bgcleanup.MAX_COMMAND_CHARS
    assert notice_for(f"{padding}; pytest | tail") is None


def test_a_fused_pipe_and_ampersand_is_a_bound_not_a_pipe() -> None:
    # `|&` reaches the scanner as the two pieces `|` and `&`, and `&` ends a pipeline, so the
    # run and the reader are two pipelines. The bound is stated in `pipes`' docstring.
    assert notice_for("pytest |& tail") is None


def pipe_status() -> Handler:
    return next(h for h in register() if h.name == "pipe-status")


def test_the_handler_speaks_with_no_configuration_and_never_decides(tmp_path: Path) -> None:
    handler = pipe_status()
    result = handler.run(bash_event(tmp_path, "pytest | tail", background=False), NO_CONFIG)
    assert (handler.event, result.context) == ("PreToolUse", NOTICE)
    assert handler.run(bash_event(tmp_path, "pytest", background=False), NO_CONFIG).context is None


def test_a_non_bash_call_is_ignored(tmp_path: Path) -> None:
    event = bash_event(tmp_path, "pytest | tail", background=False)
    other = HookEvent(**{**event.__dict__, "tool_name": "Edit"})
    assert pipe_status().run(other, NO_CONFIG).context is None


def test_the_hint_is_given_once_per_context(tmp_path: Path) -> None:
    recorder = Recorder()
    notes = []
    for _ in range(2):
        outcome = dispatch(
            bash_event(tmp_path, "pytest | tail", background=False),
            register(),
            NO_CONFIG,
            harness=CLAUDE,
            sink=recorder,
        )
        assert outcome.exit_code == 0, outcome.stderr
        notes.append(json.loads(outcome.stdout)["hookSpecificOutput"].get("additionalContext"))
    assert notes == [NOTICE, None]
