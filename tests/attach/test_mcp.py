"""The fold of the overlay's `claude/mcp.json` over the plates (`src/drybag/attach/mcp.py`).

Each case builds plates as directories under `tmp_path` and never a repository."""

from __future__ import annotations

import json
from pathlib import Path

from drybag.attach.mcp import digest, fold_mcp
from drybag.config.plates import Plate, PlateKind

MARKER = "sekret-marker-9f3"


def _plate(
    tmp_path: Path,
    kind: PlateKind,
    name: str,
    body: object | None = None,
    machine: str | None = None,
) -> Plate:
    directory = tmp_path / name if machine is None else tmp_path / name / "machines" / machine
    (directory / "claude").mkdir(parents=True)
    if body is not None:
        text = body if isinstance(body, str) else json.dumps(body)
        (directory / "claude" / "mcp.json").write_text(text, encoding="utf-8")
    return Plate(kind, name, directory, machine=machine)


def _servers(**entries: object) -> dict[str, object]:
    return {"mcpServers": entries}


def test_later_plate_wins_the_whole_definition(tmp_path: Path) -> None:
    a = _plate(tmp_path, PlateKind.COMMON, "common", _servers(srv1={"command": "a", "args": ["x"]}))
    b = _plate(tmp_path, PlateKind.PROJECT, "p", _servers(srv1={"command": "b"}))
    fold = fold_mcp([a, b])
    assert fold.served["srv1"].definition == {"command": "b"}
    assert fold.served["srv1"].defined_in == b
    assert fold.off == {}


def test_on_restores_an_earlier_definition(tmp_path: Path) -> None:
    common = _plate(tmp_path, PlateKind.COMMON, "common", _servers(srv1={"command": "a"}))
    t1 = _plate(tmp_path, PlateKind.TAG, "t1", _servers(srv1="off"))
    p = _plate(tmp_path, PlateKind.PROJECT, "p", _servers(srv1="on"))
    fold = fold_mcp([common, t1, p])
    served = fold.served["srv1"]
    assert served.definition == {"command": "a"}
    assert served.defined_in == common
    assert served.state_in == p
    assert fold.off == {}


def test_off_after_a_definition_denies_and_delivers_nothing(tmp_path: Path) -> None:
    common = _plate(tmp_path, PlateKind.COMMON, "common", _servers(srv1={"command": "a"}))
    t1 = _plate(tmp_path, PlateKind.TAG, "t1", _servers(srv1="off"))
    fold = fold_mcp([common, t1])
    assert fold.served == {}
    assert fold.off == {"srv1": t1}


def test_on_with_no_definition_is_nothing(tmp_path: Path) -> None:
    p = _plate(tmp_path, PlateKind.PROJECT, "p", _servers(srv1="on"))
    fold = fold_mcp([p])
    assert fold.served == {}
    assert fold.off == {}
    assert fold.notes == ()


def test_digest_ignores_key_order() -> None:
    assert digest({"a": 1, "b": {"c": 2, "d": 3}}) == digest({"b": {"d": 3, "c": 2}, "a": 1})
    assert digest({"a": 1}) != digest({"a": 2})


def test_bad_values_are_notes_and_never_print_a_value(tmp_path: Path) -> None:
    bad_value = _plate(tmp_path, PlateKind.COMMON, "c1", _servers(srv1=MARKER, srv2=[MARKER]))
    bad_key = _plate(tmp_path, PlateKind.TAG, "t1", {"other": MARKER, "mcpServers": {}})
    not_object = _plate(tmp_path, PlateKind.TAG, "t2", [MARKER])
    servers_list = _plate(tmp_path, PlateKind.TAG, "t3", {"mcpServers": [MARKER]})
    broken = _plate(tmp_path, PlateKind.TAG, "t4", "{" + MARKER)
    fold = fold_mcp([bad_value, bad_key, not_object, servers_list, broken])
    assert len(fold.notes) == 6
    for note in fold.notes:
        assert MARKER not in note
    assert fold.served == {}
    assert str(bad_value.directory / "claude" / "mcp.json") in fold.notes[0]


def test_a_sub_plate_definition_wins_its_parents(tmp_path: Path) -> None:
    parent = _plate(tmp_path, PlateKind.PROJECT, "p", _servers(srv1={"command": "a"}))
    sub = _plate(tmp_path, PlateKind.PROJECT, "p", _servers(srv1={"command": "m"}), machine="m1")
    fold = fold_mcp([parent, sub])
    assert fold.served["srv1"].definition == {"command": "m"}
    assert fold.served["srv1"].defined_in == sub
