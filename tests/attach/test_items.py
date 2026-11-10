"""The fold over an overlay's plates (`src/drybag/attach/items.py`), through the plates the
overlay gives (`config.plates.plates`) rather than plates built by hand."""

from __future__ import annotations

from pathlib import Path

from drybag.attach.items import SKILL, fold
from drybag.attach.permissions import HOOKS_FILE, claude_sources
from drybag.config.plates import plates
from tests.tagged import list_tags


def skill(parent: Path, name: str, text: str) -> Path:
    path = parent / "claude" / "skills" / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(text, encoding="utf-8")
    return path


def test_a_sub_plate_skill_wins_its_parents(tmp_path: Path) -> None:
    # Mutation ("the fold skips the sub-plates"): every reader of items would then ignore the
    # machine's own copy, and no other test reads a sub-plate through a reader.
    root = tmp_path / "overlay"
    common = root / "common"
    tag = root / "tags" / "t1"
    parent_s = skill(common, "s", "common's")
    sub_s = skill(common / "machines" / "m1", "s", "m1's")
    parent_u = skill(tag, "u", "t1's")
    sub_u = skill(tag / "machines" / "m1", "u", "t1 on m1's")
    list_tags(root, "p", ["t1"])
    hooks = common / "machines" / "m1" / "claude" / HOOKS_FILE
    hooks.write_text("{}", encoding="utf-8")

    found, _ = plates(root, "p", machine="m1")
    assert fold(found, SKILL).winners == {"s": sub_s, "u": sub_u}
    assert (hooks, None) in claude_sources(found, HOOKS_FILE)

    other, _ = plates(root, "p", machine="m2")
    assert fold(other, SKILL).winners == {"s": parent_s, "u": parent_u}
    assert (hooks, None) not in claude_sources(other, HOOKS_FILE)
