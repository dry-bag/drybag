"""This machine's name, read from the machine file alone (`config.overlay.machine_record`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from drybag.config.overlay import machine_record
from drybag.printed import clipped


def machine_name(path: Path) -> tuple[str | None, str | None]:
    record = machine_record(path)
    return record.name, record.note


def machine_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "machine.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_name_comes_from_the_machine_table(tmp_path: Path) -> None:
    assert machine_name(machine_file(tmp_path, '[machine]\nname = "m1"\n')) == ("m1", None)


def test_no_file_or_no_table_is_no_name(tmp_path: Path) -> None:
    assert machine_name(tmp_path / "absent.toml") == (None, None)
    assert machine_name(machine_file(tmp_path, '[overlay]\nroot = "/x"\n')) == (None, None)
    assert machine_name(machine_file(tmp_path, "[machine]\n")) == (None, None)


def test_setups_machine_table_without_a_name_is_no_name(tmp_path: Path) -> None:
    # `setup` writes `version` and `installed` into this table; it is the usual real file.
    text = '[machine]\nversion = "0.7.1"\ninstalled = ["a"]\n'
    assert machine_name(machine_file(tmp_path, text)) == (None, None)


@pytest.mark.parametrize("value", ['"M1"', '"-x"', '"' + "a" * 41 + '"', "7"])
def test_name_outside_the_tag_shape_is_a_note(tmp_path: Path, value: str) -> None:
    path = machine_file(tmp_path, f"[machine]\nname = {value}\n")
    name, note = machine_name(path)
    assert name is None
    assert note is not None
    assert clipped(str(path)) in note
    assert "a" * 200 not in note


def test_a_very_long_name_is_clipped_in_the_note(tmp_path: Path) -> None:
    path = machine_file(tmp_path, f'[machine]\nname = "{"a" * 300}"\n')
    _, note = machine_name(path)
    assert note is not None
    assert "a" * 200 not in note
    assert "(300 chars)" in note
