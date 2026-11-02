"""The red-run notice's shared test fixtures: the handler, a red event, and hints that stand in for
a profile's, shipped through the seam `stayfixed.profiles.hints.shipped_hints` reads from."""

from __future__ import annotations

import sys
import types
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from stayfixed.config.loader import load
from stayfixed.config.schema import Config
from stayfixed.hints.hooks import register
from stayfixed.hooks.api import Handler, HookEvent
from stayfixed.profiles.hints import COUNT_LIMIT

# `profile = ""` on purpose: the note is chosen by the command that failed, so a repository that
# names no profile, or names one stack while running another's tests, still gets the right advice.
CONFIG = """
[stayfixed]
version = "0.1.0"
enforced = ["docs", "bugs", "plan", "commit", "trail"]
preset = "recommended"
profile = ""
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
release_branch = "main"

[ledger]
code_roots = ["src"]
"""

RED = {"tool_response": {"exit_code": 1}}

# The core's own lines, as the code before the move rendered them, captured from that code and
# pasted here, never derived from the code under test.
LEAD = "Before calling this red a flake, pre-existing, or caused by the branch:"
DIRTY_ONE = (
    "1 uncommitted change(s) in the tree -- this run measured a tree nobody is merging. "
    "A stashed-baseline A/B cannot see this: both halves run in it."
)


def hygiene() -> Handler:
    return next(h for h in register() if h.name == "test-hygiene")


def red_event(root: Path, command: str) -> HookEvent:
    tool_input: dict[str, object] = {"command": command}
    return HookEvent(
        name="PostToolUse",
        session_id="s1",
        agent_id=None,
        tool_name="Bash",
        tool_input=tool_input,
        cwd=root,
        project_root=root,
        raw={"tool_name": "Bash", "tool_input": tool_input, **RED},
    )


def config_of(root: Path) -> Config:
    return load(root, machine=root.parent / "absent.toml")


class FakeHint:
    """A hint for one runner, whose report and note are fixed, and which can be told to raise.
    A `note` of `None` is a hint with nothing to say."""

    def __init__(self, runner: str, note: str | None, *, raises_in: str = "") -> None:
        self.runner = runner
        self.said = note
        self.raises_in = raises_in

    def _maybe_raise(self, where: str) -> None:
        if self.raises_in == where:
            raise RuntimeError(f"{self.runner} broke in {where}")

    def recognises(self, argv: Sequence[str]) -> bool:
        self._maybe_raise("recognises")
        return argv[0] == self.runner

    def report(self, roots: Sequence[Path]) -> Mapping[str, int]:
        self._maybe_raise("report")
        return {"found": 1}

    def note(self, counts: Mapping[str, int]) -> str | None:
        self._maybe_raise("note")
        if self.said is None:
            return None
        return f"{self.said} ({counts['found']})"


class WordlessHint(FakeHint):
    """A hint whose note is something other than text, which the protocol does not allow."""

    def note(self, counts: Mapping[str, int]) -> str | None:
        return ["a", "list"]  # type: ignore[return-value]


class EmptyHint(FakeHint):
    """A hint whose note is the empty string: text, with nothing in it."""

    def note(self, counts: Mapping[str, int]) -> str | None:
        return ""


class NamedUndeterminedHint(FakeHint):
    """A hint with a real count called `undetermined`, which is a count name like any other."""

    def report(self, roots: Sequence[Path]) -> Mapping[str, int]:
        return {"found": 1, "undetermined": 1}


class Word(str):
    """A key that passes the count-name grammar and prints as something else."""

    def __str__(self) -> str:
        return "/etc/passwd"


class Count(int):
    """A value that is an `int` and formats as something else."""

    def __format__(self, spec: str) -> str:
        return "/etc/passwd"


class LoudHint(FakeHint):
    """A hint whose report carries more than counts, and which keeps what its note was given."""

    def __init__(self, runner: str, note: str) -> None:
        super().__init__(runner, note)
        self.returned: dict[object, object] = {}
        self.given: object = None

    def report(self, roots: Sequence[Path]) -> Mapping[str, int]:
        self.returned = {
            "found": 1,
            "path": "/etc/passwd",
            "flag": True,
            "ratio": 0.5,
            "below": -1,
            "beyond": COUNT_LIMIT,
            "subclassed": Count(4),
            Word("worded"): 5,
            7: 3,
            "src/notes.txt": 2,
        }
        return self.returned  # type: ignore[return-value]

    def note(self, counts: Mapping[str, int]) -> str | None:
        self.given = counts
        return super().note(counts)


def ship(monkeypatch: pytest.MonkeyPatch, hints: Mapping[str, FakeHint]) -> None:
    """Replace the shipped hints with `hints`, through the seam `shipped_hints` reads from.

    The modules go into `sys.modules` under the names `shipped_hints` imports, so the import
    path the handler takes in production is the one this exercises.
    """
    for name, hint in hints.items():
        module = types.ModuleType(f"stayfixed.profiles.{name}.hygiene")
        module.HINT = hint  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr("stayfixed.profiles.hints.hint_modules", lambda: tuple(sorted(hints)))
