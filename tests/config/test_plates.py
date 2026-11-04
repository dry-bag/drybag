"""The overlay's plates for a bound project (`src/stayfixed/config/plates.py`): `common`, the tags
the overlay's record of the project lists, in list order, then the project.

The tags are the owner's, read from `projects/<name>/project.toml` of the project this machine's
binding record names, so every case builds an overlay and never a repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stayfixed.config.plates import (
    GROUPS,
    PROJECTS,
    RECORD,
    Plate,
    PlateKind,
    plates,
    tags,
)
from stayfixed.printed import quoted

PROJECT = "sample"


def overlay(tmp_path: Path, record: str | None, *groups: str) -> Path:
    """An overlay holding `groups/<group>/` for each group and, given, the project's record."""
    root = tmp_path / "overlay"
    (root / "common").mkdir(parents=True)
    for group in groups:
        (root / GROUPS / group).mkdir(parents=True)
    if record is not None:
        (root / PROJECTS / PROJECT).mkdir(parents=True)
        (root / PROJECTS / PROJECT / RECORD).write_text(record, encoding="utf-8")
    return root


def record_path(root: Path) -> str:
    return quoted(str(root / PROJECTS / PROJECT / RECORD))


def test_plates_are_common_then_tags_in_list_order_then_the_project(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "plates keeps the tags in sorted order instead of list order"):
    # `["b", "a"]` would come back `a`, `b`, and the later tag would not be the one that wins.
    root = overlay(tmp_path, 'tags = ["b", "a"]\n', "a", "b")
    found, notes = plates(root, PROJECT)
    assert [plate.kind for plate in found] == [
        PlateKind.COMMON,
        PlateKind.TAG,
        PlateKind.TAG,
        PlateKind.PROJECT,
    ]
    assert [plate.name for plate in found] == ["common", "b", "a", PROJECT]
    assert found[1] == Plate(PlateKind.TAG, "b", root / GROUPS / "b")
    assert found[0].directory == root / "common"
    assert found[3].directory == root / PROJECTS / PROJECT
    assert notes == ()


def test_the_project_plate_is_there_whether_or_not_its_directory_is(tmp_path: Path) -> None:
    # Readers already handle an absent share, so the plate list does not decide it.
    found, notes = plates(overlay(tmp_path, None), PROJECT)
    assert [plate.name for plate in found] == ["common", PROJECT]
    assert notes == ()


def test_a_tag_listed_twice_is_one_plate(tmp_path: Path) -> None:
    # At its first place, and silently: a repeated name is no mistake the owner needs told of.
    root = overlay(tmp_path, 'tags = ["a", "b", "a"]\n', "a", "b")
    assert tags(root, PROJECT) == (("a", "b"), ())


def test_a_tag_outside_the_grammar_is_skipped_with_a_note(tmp_path: Path) -> None:
    # The name becomes a directory name and a link name, so `../x` must reach neither. Each is
    # skipped alone: a bad tag does not take the good one beside it.
    bad = ["../x", "X", "", "a" * 41]
    listed = ", ".join(f'"{tag}"' for tag in [*bad, "good"])
    root = overlay(tmp_path, f"tags = [{listed}]\n", "good")
    used, notes = tags(root, PROJECT)
    assert used == ("good",)
    assert len(notes) == len(bad)
    for tag, note in zip(bad, notes, strict=True):
        assert quoted(tag) in note
        assert record_path(root) in note


def test_a_tag_with_no_directory_is_skipped_with_a_note(tmp_path: Path) -> None:
    root = overlay(tmp_path, 'tags = ["gone", "here"]\n', "here")
    used, notes = tags(root, PROJECT)
    assert used == ("here",)
    assert len(notes) == 1 and "gone" in notes[0]


def test_a_tag_that_is_a_file_is_not_a_directory(tmp_path: Path) -> None:
    root = overlay(tmp_path, 'tags = ["file"]\n')
    (root / GROUPS).mkdir()
    (root / GROUPS / "file").write_text("", encoding="utf-8")
    used, notes = tags(root, PROJECT)
    assert used == () and len(notes) == 1


def test_a_tag_that_links_to_a_directory_is_a_directory(tmp_path: Path) -> None:
    # The overlay is the owner's, so a link of theirs is theirs to make.
    root = overlay(tmp_path, 'tags = ["linked"]\n')
    (tmp_path / "elsewhere").mkdir()
    (root / GROUPS).mkdir()
    (root / GROUPS / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert tags(root, PROJECT) == (("linked",), ())


@pytest.mark.parametrize("record", ['tags = "a"\n', "tags = [1]\n", 'tags = ["a", 1]\n'])
def test_tags_that_are_not_a_list_of_strings_are_a_note(tmp_path: Path, record: str) -> None:
    root = overlay(tmp_path, record, "a")
    used, notes = tags(root, PROJECT)
    assert used == ()
    assert len(notes) == 1 and record_path(root) in notes[0]


def test_an_unparseable_record_gives_no_tags_and_a_note(tmp_path: Path) -> None:
    root = overlay(tmp_path, "tags = [\n", "a")
    used, notes = tags(root, PROJECT)
    assert used == ()
    assert len(notes) == 1 and "is not valid TOML" in notes[0]
    # The overlay's bytes print only as a position, never as the parser's own message.
    assert "tags = [" not in notes[0]


def test_a_record_that_is_not_utf8_gives_no_tags_and_a_note(tmp_path: Path) -> None:
    root = overlay(tmp_path, "")
    (root / PROJECTS / PROJECT / RECORD).write_bytes(b"tags = [\xff]\n")
    used, notes = tags(root, PROJECT)
    assert used == () and len(notes) == 1 and "UTF-8" in notes[0]


def test_a_record_that_is_a_directory_gives_no_tags_and_a_note(tmp_path: Path) -> None:
    root = overlay(tmp_path, None)
    (root / PROJECTS / PROJECT / RECORD).mkdir(parents=True)
    used, notes = tags(root, PROJECT)
    assert used == () and len(notes) == 1


def test_no_record_gives_no_tags_and_no_note(tmp_path: Path) -> None:
    assert tags(overlay(tmp_path, None), PROJECT) == ((), ())


def test_a_record_with_no_tags_key_gives_no_tags_and_no_note(tmp_path: Path) -> None:
    assert tags(overlay(tmp_path, 'remote = "r"\n'), PROJECT) == ((), ())
