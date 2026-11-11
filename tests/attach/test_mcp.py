"""The fold of the overlay's `claude/mcp.json` over the plates (`src/drybag/attach/mcp.py`).

Each case builds plates as directories under `tmp_path` and never a repository."""

from __future__ import annotations

import json
from pathlib import Path

from drybag.attach.mcp import ON_ALONE, UNUSABLE, digest, fold_mcp
from drybag.config.plates import Plate, PlateKind
from drybag.jsonobject import DEPTH_CAP
from drybag.printed import quoted

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


def _file(plate: Plate) -> Path:
    return plate.directory / "claude" / "mcp.json"


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


def test_on_with_no_definition_and_no_off_is_a_note(tmp_path: Path) -> None:
    # After an "off" it withdraws the deny entry, which is something; alone it does nothing.
    t1 = _plate(tmp_path, PlateKind.TAG, "t1", _servers(srv2="off"))
    p = _plate(tmp_path, PlateKind.PROJECT, "p", _servers(srv1="on", srv2="on"))
    fold = fold_mcp([t1, p])
    assert (fold.served, fold.off) == ({}, {})
    assert fold.notes == (ON_ALONE.format(path=quoted(str(_file(p))), name="srv1"),)


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


def test_an_entry_no_claude_mcp_call_can_take_is_a_note(tmp_path: Path) -> None:
    # A NUL ends an argv word and a lone surrogate encodes as no UTF-8, so neither reaches the
    # digest, the ledger or a launch; the name's own rule is Claude Code's, and stays its own.
    lone, nul = "\ud800", "\0"
    entries = {f"m{nul}1": {"command": "a"}, f"m{lone}2": "off", "m3": {"args": [lone]}}
    plate = _plate(tmp_path, PlateKind.COMMON, "c1", _servers(**entries, **{"m.4": "off"}))
    fold = fold_mcp([plate])
    # A definition is passed as ASCII JSON, so only a name can be one no call can take.
    assert (list(fold.served), list(fold.off)) == (["m3"], ["m.4"])
    assert len(fold.notes) == 2
    assert all(lone not in note and nul not in note for note in fold.notes)


def test_a_sub_plate_definition_wins_its_parents(tmp_path: Path) -> None:
    parent = _plate(tmp_path, PlateKind.PROJECT, "p", _servers(srv1={"command": "a"}))
    sub = _plate(tmp_path, PlateKind.PROJECT, "p", _servers(srv1={"command": "m"}), machine="m1")
    fold = fold_mcp([parent, sub])
    assert fold.served["srv1"].definition == {"command": "m"}
    assert fold.served["srv1"].defined_in == sub


def test_a_file_there_and_unusable_makes_the_fold_unusable(tmp_path: Path) -> None:
    # A merge's conflict markers must not read as "this plate serves nothing": the run then
    # changes no MCP server and no deny entry (`write.plan_writes`).
    common = _plate(tmp_path, PlateKind.COMMON, "common", _servers(m1={"command": "a"}))
    assert fold_mcp([common, _plate(tmp_path, PlateKind.TAG, "t0")]).usable
    for name, body in (("t1", "<<<<<<< HEAD\n{}"), ("t2", [1]), ("t3", {"mcpServers": []})):
        broken = _plate(tmp_path, PlateKind.TAG, name, body)
        fold = fold_mcp([common, broken])
        assert not fold.usable
        assert fold.notes == (UNUSABLE.format(path=quoted(str(_file(broken)))),)


def test_a_definition_nested_past_the_readers_cap_is_unusable(tmp_path: Path) -> None:
    # Read through `jsonobject`'s depth cap: on 3.14 the parser goes on past what the digest's
    # encoder follows, and a definition nested that deep ended `attach` in a `RecursionError`.
    depth = DEPTH_CAP + 1
    text = '{"mcpServers": {"m1": ' + '{"a": ' * depth + "1" + "}" * depth + "}}"
    fold = fold_mcp([_plate(tmp_path, PlateKind.COMMON, "c1", text)])
    assert (fold.served, fold.usable) == ({}, False)


def test_nan_or_infinity_in_a_definition_is_skipped_with_a_note(tmp_path: Path) -> None:
    # `json.loads` reads them, and Claude Code refuses the definition they are sent in.
    text = '{"mcpServers": {"m1": {"env": {"N": NaN}}, "m2": {"t": 1e999}, "m3": {"command": "c"}}}'
    fold = fold_mcp([_plate(tmp_path, PlateKind.COMMON, "c1", text)])
    assert list(fold.served) == ["m3"]
    assert len(fold.notes) == 2
