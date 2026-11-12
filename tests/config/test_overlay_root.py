"""Which overlay root this machine records: `None` for "not recorded", and a failure for a file
that cannot be read, never the one mistaken for the other."""

from __future__ import annotations

from pathlib import Path

import pytest

from drybag.config.overlay import overlay_root
from drybag.config.reading import MachineConfigError


def test_a_recorded_root_is_answered_and_an_empty_machine_file_records_none(
    tmp_path: Path,
) -> None:
    # The recorded root anchors where the note store may resolve, so it is answered as recorded;
    # an empty file is valid TOML that records nothing, so it is "not recorded" and never a broken
    # file or a root nobody wrote. Measured by hand: with the last line answering `None` whatever
    # `root` holds, the first assertion reddens. The absent file is held below.
    overlay = tmp_path / "o"
    overlay.mkdir()
    machine = tmp_path / "machine.toml"
    machine.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    assert overlay_root(machine) == overlay
    machine.write_text("", encoding="utf-8")
    assert overlay_root(machine) is None


def test_a_machine_file_that_is_not_valid_toml_is_not_an_unrecorded_overlay(
    tmp_path: Path,
) -> None:
    # `config.owner.resolve_owner` raises `MachineConfigError` for this very file and this very
    # syntax error. This reader answered `None`, which the store renders as "no overlay root is
    # recorded … run `drybag setup`" — wrong advice for a file that is already there. One
    # class, so the one file has one failure whichever reader meets it first.
    broken = tmp_path / "machine.toml"
    broken.write_text("[overlay\nroot = 'x'\n", encoding="utf-8")
    with pytest.raises(MachineConfigError, match=r"is not valid TOML \(at line 1"):
        overlay_root(broken)


def test_a_machine_file_recording_no_overlay_still_answers_none(tmp_path: Path) -> None:
    blank = tmp_path / "machine.toml"
    blank.write_text("[personal]\n", encoding="utf-8")
    assert overlay_root(blank) is None
    assert overlay_root(tmp_path / "absent.toml") is None


# Machine files that are valid TOML and record no usable overlay root: an `[overlay]` that is not a
# table, and a `root` that is empty or not text.
NO_USABLE_ROOT = {
    "overlay-not-a-table": "overlay = 5\n",
    "root-empty": '[overlay]\nroot = ""\n',
    "root-not-text": "[overlay]\nroot = 5\n",
}


@pytest.mark.parametrize("case", sorted(NO_USABLE_ROOT))
def test_a_machine_file_with_no_usable_overlay_root_records_none(tmp_path: Path, case: str) -> None:
    # Each is a file that parses and records no overlay, so the answer is "not recorded", never an
    # exception past every caller's catch and never a root nobody recorded. Measured by hand:
    # without the `isinstance(section, dict)` arm, `overlay-not-a-table` raises `AttributeError`;
    # without `and value`, `root-empty` answers the working directory, `Path(".")`; without
    # `isinstance(value, str)`, `root-not-text` answers `Path("5")`.
    machine = tmp_path / "machine.toml"
    machine.write_text(NO_USABLE_ROOT[case], encoding="utf-8")
    assert overlay_root(machine) is None


def test_a_root_under_tilde_is_the_owners_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A `~` in this file is the home the file lives under.
    owner = tmp_path / "owner"
    monkeypatch.setenv("HOME", str(owner))
    machine = tmp_path / "machine.toml"
    machine.write_text('[overlay]\nroot = "~/drybag-private"\n', encoding="utf-8")
    assert overlay_root(machine) == owner / "drybag-private"
    machine.write_text('[overlay]\nroot = "~"\n', encoding="utf-8")
    assert overlay_root(machine) == owner


@pytest.mark.parametrize("root", ["drybag-private", "./o"])
def test_a_relative_overlay_root_is_a_machine_file_fault(tmp_path: Path, root: str) -> None:
    # Read as it stands, a relative root names a directory under wherever the command runs, a
    # clone's checkout on the hook path, as a relative `HOME` would (`owner_home`). Refused in the
    # words every command prints for a machine file that does not load. Mutation (oracle):
    # `mutations/`'s "a relative overlay root is read from the working directory" -> this reddens.
    machine = tmp_path / "machine.toml"
    machine.write_text(f'[overlay]\nroot = "{root}"\n', encoding="utf-8")
    with pytest.raises(MachineConfigError) as raised:
        overlay_root(machine)
    assert str(raised.value) == (
        f"{machine}: [overlay] root must be an absolute path or start with ~/"
    )


def test_a_root_under_tilde_is_not_recorded_where_there_is_no_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Never a `~` left in place, which every later path would read as a directory named `~`
    # inside the current one.
    monkeypatch.setenv("HOME", "")
    machine = tmp_path / "machine.toml"
    machine.write_text('[overlay]\nroot = "~/drybag-private"\n', encoding="utf-8")
    assert overlay_root(machine) is None
    # Nor a `~user` the password database does not list, which `Path.expanduser` raised for.
    machine.write_text('[overlay]\nroot = "~drybag-no-such-user/o"\n', encoding="utf-8")
    assert overlay_root(machine) is None
