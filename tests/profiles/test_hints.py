"""The red-run hint's machinery, with a hint that stands in for a profile's. The Python profile's
own hint is pinned beside it (`tests/profiles/python/test_hygiene.py`)."""

from __future__ import annotations

from stayfixed.profiles.hints import answer
from tests.profiles.redrun import EmptyHint


def test_an_empty_note_is_nothing_to_report() -> None:
    # An empty note is text with nothing in it: nothing to report, the same answer the hook gives
    # by leaving the line out. Oracle: `mutations/`'s "an empty note is something to report".
    assert answer(EmptyHint("x", "alpha says"), [])[1] is None
