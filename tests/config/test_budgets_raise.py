"""A budget is what the layer that may set it says (`Budgets.effective`): the base branch's
`drybag.toml` may raise a gate's budget above the preset, and the owner's machine file a
session's."""

from __future__ import annotations

from pathlib import Path

from drybag.config.loader import loads
from drybag.config.owner import resolve_owner
from drybag.presets import load_preset
from tests.config.test_loader import MINIMAL

PRESET = load_preset("recommended")["budgets"]


def test_the_base_branch_raises_a_gate_budget(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "a budget is still only ever lowered"): `effective` keeps the
    # smaller of the two, and the raise reads the preset's.
    assert PRESET["agents_md_lines"] < 900
    config = loads(MINIMAL + "[budgets]\nagents_md_lines = 900\n", tmp_path, machine=None)
    assert config.budgets.effective("agents_md_lines") == 900


def test_the_owner_raises_a_session_budget(tmp_path: Path) -> None:
    # The owner's session budgets are configured values like the document's. Mutation: as above.
    machine = tmp_path / "machine.toml"
    machine.write_text("[budgets]\nmemory_index_words = 9000\n", encoding="utf-8")
    assert PRESET["memory_index_words"] < 9000
    config = loads(MINIMAL, tmp_path, owner=resolve_owner(machine))
    assert config.budgets.effective("memory_index_words") == 9000


def test_a_budget_nobody_set_is_the_presets_and_a_lowered_one_is_lowered(tmp_path: Path) -> None:
    # The two other arms of `effective`. No mutation of its own: a mutation that dropped the
    # configured value reddens the raises above, and one that dropped the preset raises KeyError.
    config = loads(MINIMAL + "[budgets]\nstatus_lines = 7\n", tmp_path, machine=None)
    assert config.budgets.effective("status_lines") == 7
    assert config.budgets.effective("agents_md_words") == PRESET["agents_md_words"]
