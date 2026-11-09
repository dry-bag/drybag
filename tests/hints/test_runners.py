"""Contracts for the table of test-runner program names the hints read."""

from __future__ import annotations

import pytest

from drybag.hints import bashscan
from drybag.hints.runners import names_a_test_run


@pytest.mark.parametrize(
    "command",
    [
        "pytest -x tests/a.py",
        "python3 -m pytest -q",
        "python3.13 -m pytest",
        ".venv/bin/pytest",
        "./mvnw test",
        "./gradlew test",
        "npx vitest run",
    ],
)
def test_a_runner_is_named_by_its_program_whatever_follows_its_row(command: str) -> None:
    assert names_a_test_run(command.split())


@pytest.mark.parametrize(
    "command",
    [
        "cargo build",
        "npm run build",
        "echo pytest",
        "python -m pip install pytest",
        "git test",
        "cargo nextest list",
    ],
)
def test_a_command_that_runs_no_tests_is_not_named(command: str) -> None:
    assert not names_a_test_run(command.split())


@pytest.mark.parametrize(
    "command",
    ["uv run pytest -x", "uv run --locked pytest", "PYTHONPATH=src pytest", "env CI=1 npm test"],
)
def test_a_runner_behind_a_launcher_or_an_assignment_is_named(command: str) -> None:
    [segment] = bashscan.segments(bashscan.tokenize(command) or [])
    assert names_a_test_run(bashscan.command_words(segment, test_runs=True))


def test_an_option_between_the_program_and_its_subcommand_is_no_match() -> None:
    # The table's documented bound: no option is read, so the subcommand must follow the program.
    assert not names_a_test_run(["npm", "--prefix", "x", "test"])


def test_an_empty_command_is_not_named() -> None:
    assert not names_a_test_run([])
