"""Each former name survives only in its own history."""

from __future__ import annotations

import re

from tests.test_neutral import ROOT, tracked_files

# Split so this file does not match itself; separators are allowed so a hyphenated, spaced or
# wrapped spelling is caught as well as the contiguous one, and the initials are caught where
# they prefixed the wrapper's error tokens.
FORMER = re.compile("keel" + r"[\s_.-]*" + "line|" + r"(?-i:\bK" + r"L_[A-Z])", re.IGNORECASE)
RENAME_DAY = "2026-09-28"
RENAME_PLAN = f"{RENAME_DAY}-rename-" + "stay" + "fixed.md"

# The name after that one, split for the same reason, and the day it was given up.
SECOND_FORMER = re.compile("stay" + "fixed", re.IGNORECASE)
SECOND_RENAME_DAY = "2026-11-08"

DATED = re.compile(r"\d{4}-\d{2}-\d{2}-.+")


def _plan_dated_before(relative: str, day: str) -> bool:
    """A file or directory directly under `docs/plans/` whose dated name sorts before `day`."""
    entry = relative.removeprefix("docs/plans/").partition("/")[0]
    return relative.startswith("docs/plans/") and bool(DATED.fullmatch(entry)) and entry < day


def _first_history(relative: str) -> bool:
    return _plan_dated_before(relative, RENAME_DAY) or relative == f"docs/plans/{RENAME_PLAN}"


def _second_history(relative: str) -> bool:
    return (
        relative == "CHANGELOG.md"
        or relative.startswith("changelog.d/")
        or _plan_dated_before(relative, SECOND_RENAME_DAY)
    )


NAMES = ((FORMER, _first_history), (SECOND_FORMER, _second_history))


def test_each_former_name_survives_only_in_its_history() -> None:
    # Watched red on eight planted files: a path carrying the name, a file mentioning it, a
    # hyphenated and a line-wrapped spelling, an error token under the initials, and three plans
    # outside the exemption: undated (`1-notes.md`, which sorts before the date), nested
    # (`2025/old.md`) and dated the rename day.
    hits = []
    for path in tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        hits += [
            relative
            for former, historical in NAMES
            if not historical(relative) and (former.search(relative) or former.search(text))
        ]
    assert hits == [], hits
