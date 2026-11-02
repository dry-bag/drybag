"""Contracts for the table of test-runner program names the hints read."""

from __future__ import annotations

import pytest

from stayfixed.hints import bashscan
from stayfixed.hints.runners import names_a_test_run


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        "pytest -x tests/a.py",
        "py.test",
        "python -m pytest",
        "python3 -m pytest -q",
        "python3.13 -m pytest",
        ".venv/bin/pytest",
        "go test ./...",
        "cargo test",
        "cargo nextest run",
        "npm test",
        "npm t",
        "npm run test",
        "pnpm test",
        "yarn test",
        "bun test",
        "npx jest",
        "npx vitest run",
        "jest",
        "vitest",
        "deno test",
        "dotnet test",
        "mvn test",
        "gradle test",
        "./gradlew test",
        "rspec",
        "bundle exec rspec",
        "phpunit",
        "mix test",
        "tox",
        "nox",
        "ctest",
        "swift test",
        "make test",
    ],
)
def test_a_common_runner_is_named_by_its_program(command: str) -> None:
    assert names_a_test_run(command.split())


@pytest.mark.parametrize(
    "command",
    [
        "go vet ./...",
        "cargo build",
        "npm install",
        "npm run build",
        "echo pytest",
        "grep pytest x",
        "python -m pip install pytest",
        "make",
        "git test",
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
    assert names_a_test_run(bashscan.command_words(segment, names_a_test_run))


def test_an_option_between_the_program_and_its_subcommand_is_no_match() -> None:
    # The table's documented bound: no option is read, so the subcommand must follow the program.
    assert not names_a_test_run(["npm", "--prefix", "x", "test"])


def test_an_empty_command_is_not_named() -> None:
    assert not names_a_test_run([])
