"""The former name survives only in the plans dated before the rename and the plan performing it."""

from __future__ import annotations

import re

from tests.test_neutral import ROOT, tracked_files

# Split so this file does not match itself; separators are allowed so a hyphenated, spaced or
# wrapped spelling is caught as well as the contiguous one, and the initials are caught where
# they prefixed the wrapper's error tokens.
FORMER = re.compile("keel" + r"[\s_.-]*" + "line|" + r"(?-i:\bK" + r"L_[A-Z])", re.IGNORECASE)
RENAME_DAY = "2026-09-28"
RENAME_PLAN = f"{RENAME_DAY}-rename-" + "stay" + "fixed.md"
DATED = re.compile(r"\d{4}-\d{2}-\d{2}-[^/]+\.md")

# The name after that one, split for the same reason, and the day it was given up.
SECOND_FORMER = re.compile("stay" + "fixed", re.IGNORECASE)
SECOND_RENAME_DAY = "2026-11-08"
DATED_ENTRY = re.compile(r"\d{4}-\d{2}-\d{2}-.+")


def _historical(relative: str) -> bool:
    """A dated plan directly under `docs/plans/`, written before the rename or spelling it."""
    name = relative.removeprefix("docs/plans/")
    if name == relative or not DATED.fullmatch(name):
        return False
    return name < RENAME_DAY or name == RENAME_PLAN


def _history_of_the_second_name(relative: str) -> bool:
    """The changelog, or a plan file or directory dated before the second rename."""
    if relative == "CHANGELOG.md" or relative.startswith("changelog.d/"):
        return True
    entry = relative.removeprefix("docs/plans/").partition("/")[0]
    if not relative.startswith("docs/plans/") or not DATED_ENTRY.fullmatch(entry):
        return False
    return entry < SECOND_RENAME_DAY


def test_the_former_name_survives_only_in_the_historical_plans() -> None:
    # Watched red on eight planted files: a path carrying the name, a file mentioning it, a
    # hyphenated and a line-wrapped spelling, an error token under the initials, and three plans
    # outside the exemption: undated (`1-notes.md`, which sorts before the date), nested
    # (`2025/old.md`) and dated the rename day.
    hits = [
        relative
        for path in tracked_files()
        if not _historical(relative := path.relative_to(ROOT).as_posix())
        and (
            FORMER.search(relative)
            or FORMER.search(path.read_text(encoding="utf-8", errors="replace"))
        )
    ]
    assert hits == [], hits


def test_second_former_name_survives_only_in_history() -> None:
    hits = [
        relative
        for path in tracked_files()
        if not _history_of_the_second_name(relative := path.relative_to(ROOT).as_posix())
        and (
            SECOND_FORMER.search(relative)
            or SECOND_FORMER.search(path.read_text(encoding="utf-8", errors="replace"))
        )
    ]
    assert hits == [], hits
