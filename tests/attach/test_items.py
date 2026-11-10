"""The one fold over the plates (`src/drybag/attach/items.py`)."""

from __future__ import annotations

from pathlib import Path

from drybag.attach import items
from drybag.config.plates import Plate, PlateKind


def test_a_sub_plate_skill_wins_its_parents(tmp_path: Path) -> None:
    # Mutation ("a sub-plate comes before its parent"): the parent's skill would win the name.
    parent = tmp_path / "common"
    sub = parent / "machines" / "m1"
    for directory in (parent, sub):
        (directory / "claude" / "skills" / "alpha").mkdir(parents=True)
    folded = items.fold(
        (
            Plate(PlateKind.COMMON, "common", parent),
            Plate(PlateKind.COMMON, "common", sub, machine="m1"),
        ),
        items.SKILL,
    )
    assert folded.winners["alpha"] == sub / "claude" / "skills" / "alpha"
    assert [plate.machine for plate in folded.holders["alpha"]] == [None, "m1"]
