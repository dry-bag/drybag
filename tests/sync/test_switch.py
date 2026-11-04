"""The per-machine switch: `[sync] enabled = true` in the machine file, and nothing else.

Off is the default and the failure mode: every shape of the file that is not an unambiguous `true`
reads as off, because the hooks that ask run on every turn of every session and must never raise
into one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stayfixed.config.classes import REFUSED_LAYER_NOTE
from stayfixed.config.loader import loads, loads_noting
from stayfixed.config.owner import resolve_owner
from stayfixed.config.reading import ConfigError
from stayfixed.sync.switch import KEY, SECTION, enabled
from tests.pathfaults import ROOT_SEARCHES_EVERYTHING, unsearchable

MINIMAL = '[stayfixed]\nversion = "0.1.0"\npreset = "recommended"\n\n[project]\nname = "sample"\n'


def machine_file(tmp_path: Path, text: str | None) -> Path:
    path = tmp_path / "config.toml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(None, False, id="no-file"),
        pytest.param('[personal]\npreset = "x"\n', False, id="no-section"),
        pytest.param("[sync]\n", False, id="no-key"),
        pytest.param('[sync]\nenabled = "yes"\n', False, id="a-string"),
        pytest.param('[sync]\nenabled = "true"\n', False, id="the-string-true"),
        pytest.param("[sync]\nenabled = 1\n", False, id="an-integer"),
        pytest.param("[sync]\nenabled = false\n", False, id="false"),
        pytest.param("sync = true\n", False, id="not-a-table"),
        pytest.param("[sync]\nenabled = true\n", True, id="true"),
    ],
)
def test_enabled_only_for_a_true_bool(tmp_path: Path, text: str | None, expected: bool) -> None:
    # Mutation (`mutations/`'s "a string 'true' switches sync on"): `is True` becomes a truthiness
    # test, and the string and integer cases redden.
    assert enabled(machine_file(tmp_path, text)) is expected


@pytest.mark.parametrize(
    "text", ["[sync\nenabled = true\n", "[sync]\nenabled = true\nenabled = 1\n"]
)
def test_a_machine_file_that_does_not_parse_is_off(tmp_path: Path, text: str) -> None:
    assert enabled(machine_file(tmp_path, text)) is False


def test_a_machine_file_that_is_not_text_is_off(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"[sync]\nenabled = true\n\xff\xfe")
    assert enabled(path) is False


@ROOT_SEARCHES_EVERYTHING
def test_a_machine_file_that_cannot_be_asked_about_is_off(tmp_path: Path) -> None:
    # `fsops.is_file` raises for a directory nobody may search; the hook that asks must not.
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "config.toml").write_text("[sync]\nenabled = true\n", encoding="utf-8")
    with unsearchable(locked):
        assert enabled(locked / "config.toml") is False


def test_the_default_machine_file_is_the_one_under_home(tmp_path: Path) -> None:
    # The autouse scratch `HOME` is the owner's home here; no argument means that file.
    assert enabled() is False
    path = Path.home() / ".config" / "stayfixed" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f"[{SECTION}]\n{KEY} = true\n", encoding="utf-8")
    assert enabled() is True


def test_a_repository_cannot_set_sync(tmp_path: Path) -> None:
    # A clone's `stayfixed.toml` must not switch a machine's sync on. The loader refuses the
    # section outright on a command's load, and on a session's load notes the refused key and
    # drops it; neither reads it into a place `enabled` looks. `[sync]` is machine-only
    # (`config.classes`), and the machine owner's file in the home is the one anchor.
    # Mutation (`mutations/`'s "the repository may set a machine-only key") reddens the second arm.
    text = MINIMAL + "\n[sync]\nenabled = true\n"
    with pytest.raises(ConfigError, match=r"unknown section\(s\): sync"):
        loads(text, tmp_path, machine=tmp_path / "none.toml")
    got = loads_noting(text, tmp_path, owner=resolve_owner(None))
    assert got.notes == (REFUSED_LAYER_NOTE.format(key="sync.enabled", layer="repository"),)
    assert "sync" not in got.document
