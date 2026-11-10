"""Where two tags hold one name: `collisions`, the sentences `doctor` warns with."""

from __future__ import annotations

from pathlib import Path

from drybag.attach.tags import collisions
from drybag.config.classes import Layer, LayerName
from drybag.config.plates import plates
from tests.tagged import with_tags


def _overlay(tmp_path: Path, *tags: str) -> Path:
    """An overlay whose project `p` lists `tags`, each with a `tags/<tag>/` directory."""
    return with_tags(tmp_path / "overlay", "p", list(tags))


def _hold(overlay: Path, plate: str, relative: str) -> None:
    path = overlay / plate / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")


def test_each_kind_of_item_is_named_with_its_tags_in_list_order_and_the_winner(
    tmp_path: Path,
) -> None:
    overlay = _overlay(tmp_path, "b", "a")
    for tag in ("a", "b"):
        _hold(overlay, f"tags/{tag}", "claude/rules/r.md")
        _hold(overlay, f"tags/{tag}", "claude/skills/review/SKILL.md")
        _hold(overlay, f"tags/{tag}", "claude/agents/helper.md")
        _hold(overlay, f"tags/{tag}", "codex/c.rules")
    # A dot-named file, a rule that is not Markdown and a name held once collide with nothing.
    for tag in ("a", "b"):
        _hold(overlay, f"tags/{tag}", "claude/rules/.hidden.md")
        _hold(overlay, f"tags/{tag}", "claude/rules/notes.txt")
    _hold(overlay, "tags/a", "claude/rules/only-a.md")
    found = collisions(plates(overlay, "p")[0], ())
    assert sorted(found) == sorted(
        f"the {kind} {name} is held by the tags b, a: the later, a, wins"
        for kind, name in (
            ("rule", "r.md"),
            ("Codex rule", "c.rules"),
            ("skill", "review"),
            ("agent", "helper.md"),
        )
    )


def test_a_setting_two_tag_layers_hold_is_named_and_a_common_one_is_not(tmp_path: Path) -> None:
    # `[paths] memory` is the repository's alone: `resolve` refuses it in both tags, so no tag wins
    # it. Mutation (oracle): `mutations/`'s "a setting collision counts a key no tag may set".
    layers = (
        Layer(LayerName.OVERLAY_COMMON, {"memory.mode": "overlay"}),
        Layer(
            LayerName.OVERLAY_TAG,
            {"memory.mode": "local-only", "personal.x": 1, "paths.memory": "x"},
            "a",
        ),
        Layer(LayerName.OVERLAY_TAG, {"memory.mode": "overlay", "paths.memory": "x"}, "b"),
        Layer(LayerName.OVERLAY_PROJECT, {"memory.mode": "overlay", "personal.x": 2}),
    )
    overlay = _overlay(tmp_path, "a", "b")
    assert collisions(plates(overlay, "p")[0], layers) == (
        "the setting memory.mode is held by the tags a, b: the later, b, wins",
    )


def test_a_name_off_the_overlays_disk_prints_quoted(tmp_path: Path) -> None:
    # The file name is the owner's, but a name with a line break must not start a line of output.
    overlay = _overlay(tmp_path, "a", "b")
    for tag in ("a", "b"):
        _hold(overlay, f"tags/{tag}", "claude/rules/x\n::error::y.md")
    (sentence,) = collisions(plates(overlay, "p")[0], ())
    assert "\n" not in sentence and "\\n::error::y.md" in sentence


def test_a_name_held_by_a_tag_and_the_project_alone_is_precedence_and_not_named(
    tmp_path: Path,
) -> None:
    overlay = _overlay(tmp_path, "a")
    _hold(overlay, "tags/a", "claude/rules/r.md")
    _hold(overlay, "projects/p", "claude/rules/r.md")
    _hold(overlay, "common", "claude/rules/r.md")
    assert collisions(plates(overlay, "p")[0], ()) == ()
