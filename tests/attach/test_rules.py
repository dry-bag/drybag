"""The overlay's rules: standing ones for every session, path-scoped ones once per file per session.

The project a rule is read for is the one this machine's binding record names, so every case
binds its checkout the way `attach` does (`binding.record`) and records the overlay in the machine
file under the test's own `HOME` (`tests/conftest.py`).
"""

from __future__ import annotations

import os
from pathlib import Path

from drybag import binding
from drybag.attach.rules import SCOPED_LEAD, STANDING_LEAD, scoped_exist, scoped_for, standing
from drybag.config.plates import plates
from tests.gitfixture import git, needs_git
from tests.tagged import with_tags

STANDING = "Always say which test proves a change."
SCOPED = "Files under scoped/ are generated; edit the generator instead."


def _overlay(tmp_path: Path) -> Path:
    """An overlay holding one standing rule in `common/` and one path-scoped rule in project
    `p`, recorded in the machine file under `HOME`."""
    overlay = tmp_path / "overlay"
    common = overlay / "common" / "claude" / "rules"
    project = overlay / "projects" / "p" / "claude" / "rules"
    common.mkdir(parents=True)
    project.mkdir(parents=True)
    (common / "proof.md").write_text(f"{STANDING}\n", encoding="utf-8")
    (project / "generated.md").write_text(
        f'---\npaths: ["scoped/**"]\n---\n\n{SCOPED}\n', encoding="utf-8"
    )
    machine = Path(os.environ["HOME"]) / ".config" / "drybag" / "config.toml"
    machine.parent.mkdir(parents=True)
    machine.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    return overlay


def _checkout(tmp_path: Path, *, bound: bool = True) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    # A clone naming one of the owner's projects binds nothing by that name (`binding`).
    (root / "drybag.toml").write_text('[project]\nname = "p"\n', encoding="utf-8")
    if bound:
        binding.record(root, "p", None)
    return root


def _scoped(root: Path, relative: str = "scoped/a.txt") -> str:
    return f"{SCOPED_LEAD.format(path=relative)}\n\n{SCOPED}"


@needs_git
def test_a_bound_checkout_hears_its_standing_rules_and_never_a_scoped_one(tmp_path: Path) -> None:
    _overlay(tmp_path)
    root = _checkout(tmp_path)
    assert standing(root) == f"{STANDING_LEAD}\n\n{STANDING}"


@needs_git
def test_a_scoped_rule_is_said_once_per_file_per_session(tmp_path: Path) -> None:
    # The record is keyed by the session and the path: a second read in one session says nothing,
    # and a new session hears the rule again. Mutation: the record keyed by the path alone -> the
    # `s2` read says nothing, and this reddens (`mutations/attach.toml`).
    _overlay(tmp_path)
    root = _checkout(tmp_path)
    target = str(root / "scoped" / "a.txt")
    assert scoped_for(root, target, "s1") == _scoped(root)
    assert scoped_for(root, target, "s1") == ""
    assert scoped_for(root, target, "s2") == _scoped(root)
    # Another file the rule matches is its own record, and a path relative to the checkout is the
    # same file as its absolute spelling.
    assert scoped_for(root, "scoped/b.txt", "s1") == _scoped(root, "scoped/b.txt")
    assert scoped_for(root, str(root / "scoped" / "b.txt"), "s1") == ""
    # A file no rule matches, and one outside the checkout, hear nothing.
    assert scoped_for(root, str(root / "other.txt"), "s1") == ""
    assert scoped_for(root, str(tmp_path / "scoped" / "a.txt"), "s3") == ""


@needs_git
def test_an_unbound_checkout_gets_no_rule(tmp_path: Path) -> None:
    # Its `drybag.toml` names the overlay's project, and no binding record names the checkout.
    _overlay(tmp_path)
    root = _checkout(tmp_path, bound=False)
    assert standing(root) == ""
    assert scoped_for(root, str(root / "scoped" / "a.txt"), "s1") == ""


@needs_git
def test_a_session_without_an_id_hears_the_rule_on_every_read(tmp_path: Path) -> None:
    # No id, no record: the rule is said again rather than silenced under a name anything could
    # have planted in advance.
    _overlay(tmp_path)
    root = _checkout(tmp_path)
    target = str(root / "scoped" / "a.txt")
    assert scoped_for(root, target, None) == _scoped(root)
    assert scoped_for(root, target, None) == _scoped(root)


@needs_git
def test_a_project_rule_replaces_the_common_rule_of_the_same_name(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    project = overlay / "projects" / "p" / "claude" / "rules"
    (project / "proof.md").write_text("Prove it in p.\n", encoding="utf-8")
    (overlay / "common" / "claude" / "rules" / "a-first.md").write_text(
        "First.\n", encoding="utf-8"
    )
    root = _checkout(tmp_path)
    # Common first and the project's second, each in name order, the project's copy of a name
    # winning.
    assert standing(root) == f"{STANDING_LEAD}\n\nFirst.\n\nProve it in p."


@needs_git
def test_paths_are_read_in_each_frontmatter_form(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    project = overlay / "projects" / "p" / "claude" / "rules"
    (project / "generated.md").unlink()
    (project / "block.md").write_text(
        "---\ndescription: block list\npaths:\n  - 'docs/*.md'\n  - \"src/**/*.{ts,tsx}\"\n---\n"
        "Block.\n",
        encoding="utf-8",
    )
    (project / "flow.md").write_text("---\npaths: [src/x.py]\n---\nFlow.\n", encoding="utf-8")
    root = _checkout(tmp_path)
    lead = SCOPED_LEAD.format

    def said(relative: str) -> str:
        return scoped_for(root, str(root / relative), relative)

    assert said("docs/a.md") == f"{lead(path='docs/a.md')}\n\nBlock."
    assert said("docs/deep/a.md") == ""
    assert said("src/app.tsx") == f"{lead(path='src/app.tsx')}\n\nBlock."
    assert said("src/ui/app.ts") == f"{lead(path='src/ui/app.ts')}\n\nBlock."
    assert said("src/app.js") == ""
    assert said("src/x.py") == f"{lead(path='src/x.py')}\n\nFlow."
    # Neither is a standing rule.
    assert standing(root) == f"{STANDING_LEAD}\n\n{STANDING}"


def test_whether_a_scoped_rule_exists_decides_the_rendered_entry(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay"
    assert not scoped_exist(plates(overlay, "p")[0])
    rules = overlay / "common" / "claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "standing.md").write_text("Standing.\n", encoding="utf-8")
    assert not scoped_exist(plates(overlay, "p")[0])
    (rules / "scoped.md").write_text('---\npaths: ["a/**"]\n---\nScoped.\n', encoding="utf-8")
    assert scoped_exist(plates(overlay, "p")[0])


def _tagged(overlay: Path, **rules: str) -> None:
    """Project `p` listing the tags named by the keywords (in order), each `tags/<tag>/` holding
    the rule file `x.md` with the body given."""
    with_tags(overlay, "p", list(rules), "claude/rules")
    for tag, body in rules.items():
        (overlay / "tags" / tag / "claude" / "rules" / "x.md").write_text(
            f"{body}\n", encoding="utf-8"
        )


@needs_git
def test_a_tag_rule_arrives_and_a_later_plate_wins_its_name(tmp_path: Path) -> None:
    # Mutation (oracle): `mutations/`'s "a tag's rule replaces the project's rule of its name" ->
    # the tags are read after the project, and the second assertion reddens.
    overlay = _overlay(tmp_path)
    rules = overlay / "common" / "claude" / "rules"
    project = overlay / "projects" / "p" / "claude" / "rules"
    (rules / "x.md").write_text("Common x.\n", encoding="utf-8")
    (rules / "only-common.md").write_text("Only common.\n", encoding="utf-8")
    (project / "only-project.md").write_text("Only project.\n", encoding="utf-8")
    _tagged(overlay, a="Tag x.")
    (overlay / "tags" / "a" / "claude" / "rules" / "only-tag.md").write_text(
        "Only tag.\n", encoding="utf-8"
    )
    root = _checkout(tmp_path)
    # Every distinct name arrives in plate order, and the tag's body replaces the common one.
    assert standing(root) == (
        f"{STANDING_LEAD}\n\nOnly common.\n\n{STANDING}\n\nOnly tag.\n\nTag x.\n\nOnly project."
    )
    # The project's file of the same name wins over the tag's.
    (project / "x.md").write_text("Project x.\n", encoding="utf-8")
    said = standing(root)
    assert "Project x." in said and "Tag x." not in said and "Common x." not in said
    assert said.index("Only tag.") < said.index("Project x.")


@needs_git
def test_two_tags_hold_one_rule_name_and_the_later_wins(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    _tagged(overlay, a="From a.", b="From b.")
    root = _checkout(tmp_path)
    said = standing(root)
    assert "From b." in said and "From a." not in said
    # List order is the precedence: reversed, the other wins.
    _tagged(overlay, b="From b.", a="From a.")
    said = standing(root)
    assert "From a." in said and "From b." not in said
