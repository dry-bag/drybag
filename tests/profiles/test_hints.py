"""The red-run hint's machinery, with hints that stand in for a profile's: which hints speak after
which command, and what a hint that fails costs. The Python profile's own hint is pinned beside it
(`tests/profiles/python/test_hygiene.py`), and `stayfixed test hygiene` in
`tests/guards/test_commands.py`."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE
from stayfixed.harnesses import CLAUDE
from stayfixed.hints.hooks import register
from stayfixed.hooks.dispatch import Recorder, dispatch
from tests.gitfixture import git, needs_git
from tests.profiles.redrun import (
    CONFIG,
    DIRTY_ONE,
    LEAD,
    FakeHint,
    LoudHint,
    WordlessHint,
    config_of,
    hygiene,
    red_event,
    ship,
)
from tests.sessions import session_of


def a_project(tmp_path: Path) -> Path:
    # Not a git repository, so the dirty count is "could not answer" and adds no line: what is
    # left is exactly what the hints said.
    root = tmp_path / "project"
    root.mkdir()
    (root / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    return root


def a_dirty_project(tmp_path: Path) -> Path:
    """A committed tree with one uncommitted change: a tracked file modified after its commit,
    since the dirty count runs under the owner's own git, whose `status.showUntrackedFiles` could
    hide an untracked file and make the count depend on the machine."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "notes.txt").write_text("a\n", encoding="utf-8")
    (root / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "chore: seed")
    (root / "notes.txt").write_text("b\n", encoding="utf-8")
    return root


def test_two_recognising_hints_both_speak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A repository in two stacks runs both suites in one command; each stack whose runner
    # failed gets its own line, in name order, and a third whose runner did not run says
    # nothing. Oracle: `mutations/`'s "only the first recognising hint speaks".
    ship(
        monkeypatch,
        {
            "alpha": FakeHint("alpha-test", "alpha says"),
            "beta": FakeHint("beta-test", "beta says"),
            "gamma": FakeHint("gamma-test", "gamma says"),
        },
    )
    root = a_project(tmp_path)
    result = hygiene().run(red_event(root, "alpha-test && beta-test"), session_of(config_of(root)))
    assert result.context == f"{LEAD}\n- alpha says (1)\n- beta says (1)"


def test_a_hint_that_raises_costs_its_note_not_the_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One stack's broken hint must cost that stack's line and nothing else: not the other
    # stacks' lines, and not the handler, whose failure the dispatcher would record and swallow
    # whole. Through the real dispatcher, so "nothing else" includes stderr.
    # Oracle: `mutations/`'s "a hint's note is computed outside its guard" and "a hint's
    # recognition is asked outside its guard".
    ship(
        monkeypatch,
        {
            "alpha": FakeHint("x", "alpha says", raises_in="recognises"),
            "beta": FakeHint("x", "beta says", raises_in="report"),
            "delta": FakeHint("x", "delta says", raises_in="note"),
            "gamma": FakeHint("x", "gamma says"),
        },
    )
    root = a_project(tmp_path)
    outcome = dispatch(
        red_event(root, "x"),
        register(),
        session_of(config_of(root)),
        harness=CLAUDE,
        sink=Recorder(),
    )
    assert outcome.exit_code == 0
    assert outcome.stderr == ""
    answer = json.loads(outcome.stdout)["hookSpecificOutput"]
    assert answer["additionalContext"] == f"{LEAD}\n- gamma says (1)"


@needs_git
def test_a_hint_that_cannot_load_or_gives_no_text_costs_only_its_own_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The per-hint guards cover recognising, reporting and noting; a profile's module that does
    # not import, one that has no `HINT`, and a note that is not text sit outside them unless
    # they are handled on their own. Each must cost that profile's line and nothing else: the
    # dirty-tree line and every other stack's line stay. Through the real dispatcher, so
    # "nothing else" includes stderr. Oracle: `mutations/`'s "a hint module is imported outside
    # its guard" and "a note that is not text passes as one".
    ship(
        monkeypatch,
        {"delta": WordlessHint("x", "delta says"), "gamma": FakeHint("x", "gamma says")},
    )
    # `alpha` has no module at all, and `beta`'s module defines no `HINT`.
    beta = types.ModuleType("stayfixed.profiles.beta.hygiene")
    monkeypatch.setitem(sys.modules, beta.__name__, beta)
    monkeypatch.setattr(
        "stayfixed.profiles.hints.hint_modules", lambda: ("alpha", "beta", "delta", "gamma")
    )
    root = a_dirty_project(tmp_path)
    outcome = dispatch(
        red_event(root, "x"),
        register(),
        session_of(config_of(root)),
        harness=CLAUDE,
        sink=Recorder(),
    )
    assert outcome.exit_code == 0
    assert outcome.stderr == ""
    answer = json.loads(outcome.stdout)["hookSpecificOutput"]
    assert answer["additionalContext"] == f"{LEAD}\n- {DIRTY_ONE}\n- gamma says (1)"


def test_a_note_is_handed_counts_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The trust rule for a hint's line holds because `note` is handed counts and nothing else,
    # so the core hands it a fresh mapping of count names to plain integers, whatever `report`
    # returned: a path, a boolean (an `int` to Python), a float, a negative and an unbounded
    # integer, an `int` or `str` subclass that prints as something else, a non-string key and a
    # key shaped like a path are dropped before the hint renders anything, and the hint never sees
    # the very object it returned. A key is text too, and one a hint built from the tree it walked
    # would carry that tree's names into `note` and into `stayfixed test hygiene --json`. Oracle:
    # `mutations/`'s "a hint's note is handed its report as returned", "a count keeps any string
    # for its name", "a count takes an int subclass, a boolean included, for a count", "a count
    # keeps a str subclass for its name" and "a count keeps a negative or unbounded integer".
    loud = LoudHint("x", "loud says")
    ship(monkeypatch, {"alpha": loud})
    root = a_project(tmp_path)
    result = hygiene().run(red_event(root, "x"), session_of(config_of(root)))
    assert result.context == f"{LEAD}\n- loud says (1)"
    assert loud.given == {"found": 1}
    assert loud.given is not loud.returned
