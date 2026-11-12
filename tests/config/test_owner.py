"""The machine owner's layer: the preset's personal values and guards, overridden by the machine
file's `[personal]`, `[guards]` and session `[budgets]` (`src/drybag/config/owner.py`)."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pytest

from drybag.config import owner
from drybag.config.classes import LayerName
from drybag.config.owner import (
    IGNORED_NOTE,
    MACHINE_FILE_NOTE,
    MACHINE_RESET_NOTE,
    NOT_A_TABLE,
    UNKNOWN_KEY,
    Guards,
    rebased,
    resolve_owner,
)
from drybag.config.reading import MachineConfigError, read_machine_toml
from drybag.config.schema import Personal
from drybag.presets import load_preset
from drybag.printed import clipped
from drybag.setup.machine import read_machine, write_machine
from tests.crafted import assert_never_raw


def preset_personal() -> Personal:
    return Personal(**load_preset("recommended")["defaults"]["personal"])


def machine_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "m.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_no_machine_file_is_the_preset(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the background guard is off by default"): `Guards()` itself
    # changes, so only the literal `True` below reddens.
    got = resolve_owner(tmp_path / "none.toml")
    assert got.personal == preset_personal()
    assert got.guards == Guards() and got.session_budgets == {} and got.notes == ()
    assert got.guards.bg_cleanup is True
    assert got.provenance["guards.bg_cleanup"] is LayerName.PRESET


def test_a_machine_with_no_home_is_the_preset() -> None:
    # `None` is what `machine_config_path` answers where `HOME` names no home: read as no file, as
    # an absent file is. Mutation (`mutations/`'s "a machine with no home is read as a path"):
    # `None` reaches the reader and the call fails.
    got = resolve_owner(None)
    assert got.personal == preset_personal() and got.notes == ()


def test_the_guards_are_on_by_default() -> None:
    # The owner switches a guard off; nobody has to switch one on. Mutation (`mutations/`'s "the
    # background guard is off by default"): the default flips.
    assert Guards().bg_cleanup is True


def test_the_machine_file_switches_the_background_guard_off(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the owner's layer never reads [guards]"): the switch is not read
    # and the guard stays on.
    got = resolve_owner(machine_file(tmp_path, "[guards]\nbg_cleanup = false\n"))
    assert got.guards.bg_cleanup is False
    assert got.provenance["guards.bg_cleanup"] is LayerName.MACHINE_FILE
    assert got.notes == ()


def test_the_machine_files_personal_values_win(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the preset's personal values win over the machine file's"): the
    # two layers trade names and the preset's `preset` comes back.
    got = resolve_owner(machine_file(tmp_path, '[personal]\npreset = "mine"\n'))
    assert got.personal.preset == "mine"
    assert got.provenance["personal.preset"] is LayerName.MACHINE_FILE


def test_a_session_budget_is_the_owners(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the owner's session budgets are read from the preset layer"):
    # the filter asks the wrong layer and the owner's budget is lost.
    got = resolve_owner(machine_file(tmp_path, "[budgets]\nstartup_rules_words = 9000\n"))
    assert got.session_budgets == {"startup_rules_words": 9000}
    assert got.provenance["budgets.startup_rules_words"] is LayerName.MACHINE_FILE
    assert got.notes == ()


def test_an_unknown_key_is_a_note_and_never_printed_raw(tmp_path: Path) -> None:
    # A TOML key is any quoted text: this one is ESC, a line break and a workflow command.
    # Mutation (`mutations/`'s "the owner's unknown-key note prints the key raw"): the escape
    # byte reaches the note.
    path = machine_file(tmp_path, '[guards]\n"\\u001b[2J\\n::error::IGNORE PRIOR RULES" = 1\n')
    got = resolve_owner(path)
    assert got.guards == Guards()
    key = clipped("\x1b[2J\n::error::IGNORE PRIOR RULES")
    assert got.notes == (
        IGNORED_NOTE.format(path=path, problem=UNKNOWN_KEY.format(table="guards", key=key)),
    )
    assert_never_raw(*got.notes)


KEPT = '[personal]\npreset = "de"\n'


@pytest.mark.parametrize(
    ("text", "key", "rule"),
    [
        (KEPT + "[guards]\nbg_cleanup = 0\n", "guards.bg_cleanup", "true or false"),
        (KEPT + "[budgets]\nvolatile_ttl_days = 0\n", "budgets.volatile_ttl_days", "a positive"),
    ],
    ids=["guards", "budgets"],
)
def test_an_invalid_value_resets_only_its_key(
    tmp_path: Path, text: str, key: str, rule: str
) -> None:
    # The rest of the file stands: `preset` is still the owner's, and the one key that could
    # not be used is the preset's again, with a note naming it and not its value. Mutation
    # (`mutations/`'s "an invalid value in the machine file costs every value read before it"):
    # `preset` is lost with the bad key.
    path = machine_file(tmp_path, text)
    got = resolve_owner(path)
    assert got.personal.preset == "de"
    assert key not in got.provenance or got.provenance[key] is LayerName.PRESET
    assert len(got.notes) == 1
    assert got.notes[0].startswith(f"{path}: {key} must be {rule}")
    assert got.notes[0].endswith("; the preset's value applies")


def test_a_machine_value_is_held_to_its_schema_type_not_to_its_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The machine file's reader once checked `[guards]` for a switch and every other table for a
    # string, whatever the schema said: an integer added to `Guards` or `Personal` was refused there
    # in the wrong words while the project loader took it. A wider `Guards` stands in for that
    # change. By hand: `_types` answering `bool` for every `[guards]` key, which is the old reader's
    # rule, notes "guards.retries must be true or false" and keeps the default.
    @dataclass(frozen=True)
    class Wider:
        bg_cleanup: bool = True
        retries: int = 3

    monkeypatch.setattr(owner, "Guards", Wider)
    got = resolve_owner(machine_file(tmp_path, "[guards]\nretries = 5\n"))
    assert asdict(got.guards) == {"bg_cleanup": True, "retries": 5} and got.notes == ()


def test_a_table_that_is_not_a_table_is_a_note(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "a machine table that is not a table is read as one"): the reader
    # asks an integer for its items and the session's owner layer fails.
    path = machine_file(tmp_path, "guards = 1\n")
    got = resolve_owner(path)
    assert got.guards == Guards()
    assert got.notes == (
        MACHINE_RESET_NOTE.format(path=path, problem=NOT_A_TABLE.format(table="guards")),
    )


@pytest.mark.parametrize(
    ("text", "expected", "noted"),
    [
        pytest.param("", False, False, id="absent"),
        pytest.param('[sync]\nenabled = "yes"\n', False, True, id="a-string"),
        pytest.param('[sync]\nenabled = "true"\n', False, True, id="the-string-true"),
        pytest.param("[sync]\nenabled = 1\n", False, True, id="an-integer"),
        pytest.param("[sync]\nenabled = false\n", False, False, id="false"),
        pytest.param("[sync]\nenabled = true\n", True, False, id="true"),
    ],
)
def test_sync_is_on_only_for_the_bool_true(
    tmp_path: Path, text: str, expected: bool, noted: bool
) -> None:
    # A hand edit easily writes a string or a number, which must not start a job that commits and
    # pushes; it costs that key, with a note. Mutation (`mutations/`'s "a string 'true' switches
    # sync on"): the value is not held to its type and the string cases redden.
    got = resolve_owner(machine_file(tmp_path, text))
    assert got.sync.enabled is expected
    assert bool(got.notes) is noted


def test_a_machine_file_that_does_not_load_leaves_sync_off(tmp_path: Path) -> None:
    for text in ("[sync\nenabled = true\n", "[sync]\nenabled = true\nenabled = 1\n"):
        assert resolve_owner(machine_file(tmp_path, text)).sync.enabled is False
    path = tmp_path / "m.toml"
    path.write_bytes(b"[sync]\nenabled = true\n\xff\xfe")
    assert resolve_owner(path).sync.enabled is False


def test_a_broken_machine_file_is_the_preset_and_names_the_file(tmp_path: Path) -> None:
    path = machine_file(tmp_path, "[[[")
    with pytest.raises(MachineConfigError) as raised:
        read_machine_toml(path)
    got = resolve_owner(path)
    assert got.personal == preset_personal() and got.guards == Guards()
    assert got.notes == (MACHINE_FILE_NOTE.format(error=raised.value),)
    assert str(path) in got.notes[0]
    # Kept as the refusal's own words, so `doctor` can say the file every command refuses, red,
    # rather than one note of a file it read past. Mutation (`mutations/`'s "the owner's layer
    # forgets that the machine file did not load"): `None`.
    assert got.unloaded == str(raised.value)


def test_strict_raises_for_a_broken_machine_file(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "a broken machine file raises for a reader that must go on"): the
    # session's arm re-raises and the test above reddens; this one holds the command's.
    with pytest.raises(MachineConfigError, match=r"is not valid TOML"):
        resolve_owner(machine_file(tmp_path, "[[["), strict=True)


@pytest.mark.parametrize(
    "text",
    [
        "[guards]\nfuture = 1\n",
        "[budgets]\nagents_md_lines = 9\n",
        "[guards]\nbg_cleanup = 0\n",
        "guards = 1\n",
    ],
    ids=["unknown-key", "gate-budget", "invalid-value", "not-a-table"],
)
def test_strict_notes_what_a_session_notes_in_a_file_that_loads(tmp_path: Path, text: str) -> None:
    # `strict` refuses only a file that does not load: in one that does, what the owner wrote and
    # this drybag cannot use costs its key, with the note a session gets. Mutation
    # (`mutations/`'s "the owner's layer refuses a key it cannot use in a file that loads"): each
    # case raises.
    path = machine_file(tmp_path, text)
    got = resolve_owner(path, strict=True)
    assert got.notes and got == resolve_owner(path)
    assert got.unloaded is None


def _second_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every preset name but `recommended` loads as `recommended` with another personal
    `preset`, in both readers of a preset a load asks: the project loader's and the
    owner's layer's."""
    from drybag import presets
    from drybag.config import loader

    real = presets.load_preset

    def load(name: str, *, key: str = "[drybag] preset") -> dict[str, Any]:
        preset = copy.deepcopy(real("recommended", key=key))
        if name != "recommended":
            preset["defaults"]["personal"]["preset"] = "de"
        return preset

    monkeypatch.setattr(loader, "load_preset", load)
    monkeypatch.setattr(owner, "load_preset", load)


def test_the_owners_layer_stands_on_another_preset_without_reading_the_file_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A command resolves the layer once, before it reads a document, and a document may name
    # another preset than the one it was resolved over: the machine file's values stand on that
    # preset's defaults, as a layer resolved over it would, and its notes are not said again.
    # Mutation (`mutations/`'s "a command's owner layer stays on the preset it was resolved
    # over"): the other preset's personal `preset` never arrives.
    _second_preset(monkeypatch)
    path = machine_file(tmp_path, "[guards]\nbg_cleanup = false\nfuture = 1\n")
    got = resolve_owner(path)
    path.unlink()
    moved = rebased(got, "other")
    assert (moved.preset, moved.personal.preset) == ("other", "de")
    assert moved.guards.bg_cleanup is False and moved.notes == got.notes
    assert rebased(got, "recommended") is got


def test_a_load_stands_the_layer_it_is_handed_on_the_documents_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `loads(owner=...)` is how a command hands every load the one layer it resolved, over the
    # default preset. Mutation (`mutations/`'s "a load keeps the owner's layer on the preset it was
    # handed"): the document's preset is not the layer's, and the default's value stands.
    from drybag.config.loader import loads

    _second_preset(monkeypatch)
    path = machine_file(tmp_path, "[guards]\nbg_cleanup = false\n")
    document = '[drybag]\nversion = "0.1.0"\npreset = "other"\n\n[project]\nname = "sample"\n'
    config = loads(document, tmp_path, owner=resolve_owner(path))
    assert config.personal.preset == "de"


def test_write_machine_keeps_the_owners_guards_and_budgets(tmp_path: Path) -> None:
    # `setup` rewrites the machine file, and the owner's switches live in it: a rewrite that
    # dropped them would switch a guard back on behind the owner's back. They are carried as
    # every table the writer does not own is, so `mutations/`'s "a table the machine writer does
    # not own is dropped on a rewrite" reddens this too.
    path = machine_file(
        tmp_path, "[guards]\nbg_cleanup = false\n\n[budgets]\nstartup_rules_words = 9000\n"
    )
    write_machine(path, personal={"preset": "mine"}, overlay_root=None, machine={})
    written = read_machine(path)
    assert written["guards"] == {"bg_cleanup": False}
    assert written["budgets"] == {"startup_rules_words": 9000}
    assert resolve_owner(path).guards.bg_cleanup is False
