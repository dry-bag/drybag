"""The overlay's plates for a bound project (`src/drybag/config/plates.py`): `common`, the tags
the overlay's record of the project lists, in list order, then the project.

The tags are the owner's, read from `projects/<name>/project.toml` of the project this machine's
binding record names, so every case builds an overlay and never a repository.
"""

from __future__ import annotations

from pathlib import Path

from drybag.config import overlay_layers
from drybag.config.overlay import machine_record
from drybag.config.plates import (
    MACHINES,
    PROJECTS,
    RECORD,
    TAGS,
    Plate,
    PlateKind,
    plates,
    record_fault,
    tags,
)
from drybag.printed import quoted

PROJECT = "sample"


def overlay(tmp_path: Path, record: str | None, *groups: str) -> Path:
    """An overlay holding `tags/<group>/` for each group and, given, the project's record."""
    root = tmp_path / "overlay"
    (root / "common").mkdir(parents=True)
    for group in groups:
        (root / TAGS / group).mkdir(parents=True)
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
    found, notes = plates(root, PROJECT, machine=None)
    assert [plate.kind for plate in found] == [
        PlateKind.COMMON,
        PlateKind.TAG,
        PlateKind.TAG,
        PlateKind.PROJECT,
    ]
    assert [plate.name for plate in found] == ["common", "b", "a", PROJECT]
    assert found[1] == Plate(PlateKind.TAG, "b", root / TAGS / "b")
    assert found[0].directory == root / "common"
    assert found[3].directory == root / PROJECTS / PROJECT
    assert notes == ()


def test_the_project_plate_is_there_whether_or_not_its_directory_is(tmp_path: Path) -> None:
    # Readers already handle an absent share, so the plate list does not decide it.
    found, notes = plates(overlay(tmp_path, None), PROJECT, machine=None)
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
    (root / TAGS).mkdir()
    (root / TAGS / "file").write_text("", encoding="utf-8")
    used, notes = tags(root, PROJECT)
    assert used == () and len(notes) == 1


def test_a_tag_that_links_to_a_directory_is_a_directory(tmp_path: Path) -> None:
    # The overlay is the owner's, so a link of theirs is theirs to make.
    root = overlay(tmp_path, 'tags = ["linked"]\n')
    (tmp_path / "elsewhere").mkdir()
    (root / TAGS).mkdir()
    (root / TAGS / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert tags(root, PROJECT) == (("linked",), ())


def test_tags_that_are_not_a_list_are_a_note(tmp_path: Path) -> None:
    root = overlay(tmp_path, 'tags = "a"\n', "a")
    used, notes = tags(root, PROJECT)
    assert used == ()
    assert len(notes) == 1 and record_path(root) in notes[0]
    assert record_fault(root, PROJECT) == notes[0]


def test_an_entry_that_is_not_a_string_is_a_note_naming_its_position(tmp_path: Path) -> None:
    # Like an ungrammatical name: skipped alone, the others still count, and `attach` has no
    # record fault to refuse on.
    root = overlay(tmp_path, 'tags = ["ops", 1]\n', "ops")
    used, notes = tags(root, PROJECT)
    assert used == ("ops",)
    assert len(notes) == 1 and record_path(root) in notes[0] and "2" in notes[0]
    assert record_fault(root, PROJECT) is None


def test_an_unusable_tag_listed_twice_is_noted_once(tmp_path: Path) -> None:
    root = overlay(tmp_path, 'tags = ["Bad", "Bad", "gone", "gone"]\n')
    used, notes = tags(root, PROJECT)
    assert used == () and len(notes) == 2


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


def with_sub_plates(tmp_path: Path, *names: str) -> Path:
    """An overlay of `common`, tags `t1` and `t2` and the project, each holding `machines/<name>/`
    for each name."""
    root = overlay(tmp_path, 'tags = ["t1", "t2"]\n', "t1", "t2")
    for parent in (
        root / "common",
        root / TAGS / "t1",
        root / TAGS / "t2",
        root / PROJECTS / PROJECT,
    ):
        for name in names:
            (parent / MACHINES / name).mkdir(parents=True)
    return root


def shown(found: tuple[Plate, ...]) -> list[str]:
    return [p.name if p.machine is None else f"{p.name}/{p.machine}" for p in found]


def test_sub_plates_follow_each_parent(tmp_path: Path) -> None:
    # Mutation ("a sub-plate comes before its parent"): the machine's directory would lose to its
    # parent, and the order every reader folds would not be the order the docs state.
    root = with_sub_plates(tmp_path, "m1")
    found, notes = plates(root, PROJECT, machine="m1")
    assert shown(found) == [
        "common", "common/m1", "t1", "t1/m1", "t2", "t2/m1", PROJECT, f"{PROJECT}/m1",
    ]  # fmt: skip
    assert found[1] == Plate(
        PlateKind.COMMON, "common", root / "common" / MACHINES / "m1", machine="m1"
    )
    assert notes == ()


def test_other_machines_sub_plates_are_absent(tmp_path: Path) -> None:
    root = with_sub_plates(tmp_path, "m1", "m2")
    found, _ = plates(root, PROJECT, machine="m1")
    assert all(plate.machine in (None, "m1") for plate in found)
    assert len(found) == 8


def test_no_machine_name_means_no_sub_plates(tmp_path: Path) -> None:
    root = with_sub_plates(tmp_path, "m1")
    found, notes = plates(root, PROJECT, machine=None)
    assert shown(found) == ["common", "t1", "t2", PROJECT]
    assert notes == ()


def test_bad_machine_directory_is_a_note(tmp_path: Path) -> None:
    root = with_sub_plates(tmp_path)
    (root / "common" / MACHINES / "Bad").mkdir(parents=True)
    (root / "common" / MACHINES / "stray.txt").write_text("", encoding="utf-8")
    found, notes = plates(root, PROJECT, machine="m1")
    assert shown(found) == ["common", "t1", "t2", PROJECT]
    assert len(notes) == 1
    assert "Bad" in notes[0]


def test_an_overlay_drybag_toml_cannot_set_the_machine(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the overlay layer accepts a [machine] table"): an overlay file would
    # then hold a setting no reader refuses, where only the machine file names this machine.
    root = with_sub_plates(tmp_path, "m1", "m2")
    (root / "common" / "drybag.toml").write_text('[machine]\nname = "m2"\n', encoding="utf-8")
    machine = tmp_path / "machine.toml"
    machine.write_text(f'[overlay]\nroot = "{root}"\n[machine]\nname = "m1"\n', encoding="utf-8")

    record = machine_record(machine)
    assert record.name == "m1"
    found, _ = plates(root, PROJECT, machine=record.name)
    sub = root / "common" / MACHINES
    assert sub / "m1" in [plate.directory for plate in found]
    assert sub / "m2" not in [plate.directory for plate in found]

    _, notes, _ = overlay_layers.read(None, machine=machine)
    path = quoted(str(root / "common" / "drybag.toml"))
    assert overlay_layers.UNKNOWN.format(path=path, name="machine") in notes
