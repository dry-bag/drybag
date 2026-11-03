"""Every footprint command plans through `project.footprint.Passes`, and nothing else in the
project area plans at all.

`Passes` binds the ownership relation into every plan and runs the ignore guard over every
prediction, so a command that plans through it cannot leave either behind. The engine's own `plan`
keeps its `owners` keyword optional, because `stayfixed.overlay` keeps nothing out of git and has no
relation to pass; so the seam is what holds the project area, and this is what holds the seam.
Required instead, the keyword would make every overlay call and a hundred engine tests say
`owners=None`, and would still let a new command (`adopt`) pass `None` beside them: the bypass is
importing the planner, so that is what is checked.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.errors import Refusal
from stayfixed.project.footprint import prepare
from tests.project.repos import DOCUMENT, repository

ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "src" / "stayfixed" / "project"
SEAM = AREA / "footprint.py"
# The planner and what binds its guards: the engine's plan and the ignore guard. The seam module
# binds both at its top level, so importing one from it is the same bypass as importing it from
# where it is defined.
PLANNERS = {
    "stayfixed.scaffold": {"plan"},
    "stayfixed.scaffold.engine": {"plan"},
    "stayfixed.project.ignored": {"refuse_ignored"},
    "stayfixed.project.footprint": {"plan", "refuse_ignored"},
}
# The package every checked module sits in, which a relative import is resolved against.
PACKAGE = "stayfixed.project"


def _absolute(node: ast.ImportFrom) -> str:
    """The module an `ImportFrom` names, a relative one resolved against `PACKAGE`."""
    if not node.level:
        return node.module or ""
    parts = PACKAGE.split(".")[: len(PACKAGE.split(".")) - node.level + 1]
    return ".".join([*parts, *([node.module] if node.module else [])])


def _chain(node: ast.expr) -> list[str]:
    """`a.b.c` as `["a", "b", "c"]`, or `[]` when the chain is not rooted at a plain name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return [node.id, *reversed(parts)] if isinstance(node, ast.Name) else []


def _planners_reached(path: Path) -> set[str]:
    """Each planner name `path` imports, or reaches as an attribute of a module it imports: one
    attribute deep (`scaffold.plan`) or at the end of a dotted chain rooted at an imported
    package (`stayfixed.scaffold.engine.plan`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    # Each name the module binds by an import, and the dotted module it stands for.
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _absolute(node)
            for alias in node.names:
                if alias.name in PLANNERS.get(module, set()):
                    found.add(alias.name)
                bound[alias.asname or alias.name] = f"{module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    bound[top] = top
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain = _chain(node.value)
            if chain and chain[0] in bound:
                module = ".".join([bound[chain[0]], *chain[1:]])
                if node.attr in PLANNERS.get(module, set()):
                    found.add(node.attr)
    return found


def test_only_the_planning_seam_imports_the_planner_or_the_ignore_guard() -> None:
    # The walk first: the seam itself must be seen reaching all of them, or a check that
    # matched nothing would pass every module. Mutation (oracle): `mutations/`'s "a footprint
    # command imports the planner past the seam" -> `init` imports `plan` again, and this reddens.
    assert _planners_reached(SEAM) == {"plan", "refuse_ignored"}
    modules = sorted(p for p in AREA.glob("*.py") if p != SEAM)
    assert len(modules) >= 9, modules
    reached = {p.name: _planners_reached(p) for p in modules}
    assert {name: found for name, found in reached.items() if found} == {}


def test_only_the_seam_calls_its_private_planner() -> None:
    # `Passes._plan` plans without the order check, and it is private only by convention: a
    # command that called it would plan what no `predict` asked the ignore guard about. The seam
    # is seen calling it first, so a check that matched nothing would not pass every module.
    # Mutation (oracle): `mutations/`'s "a footprint command plans through the seam's private
    # planner" -> `init` re-plans with `passes._plan`, and this reddens.
    def calls(path: Path) -> bool:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return any(isinstance(n, ast.Attribute) and n.attr == "_plan" for n in ast.walk(tree))

    assert calls(SEAM)
    assert [p.name for p in sorted(AREA.glob("*.py")) if p != SEAM and calls(p)] == []


def test_the_checker_sees_a_planner_reached_through_the_seam_module(tmp_path: Path) -> None:
    # The seam module binds the planner at its top level, so a command could import it from
    # there and plan past every guard the seam binds. Mutation (oracle): `mutations/`'s "the
    # planning seam's checker stops knowing the seam module binds the planner" -> the seam's row in
    # `PLANNERS` deleted, and this finds nothing.
    module = tmp_path / "bypass.py"
    module.write_text("from stayfixed.project.footprint import plan\n", encoding="utf-8")
    assert _planners_reached(module) == {"plan"}


def test_the_checker_sees_a_fully_dotted_planner(tmp_path: Path) -> None:
    # `import stayfixed.scaffold.engine` binds only `stayfixed`, so a check that looked one
    # attribute deep saw `stayfixed.scaffold`, never the planner at the chain's end. Mutation
    # (oracle): `mutations/`'s "the planning seam's checker stops resolving a dotted chain" -> the
    # dotted branch records nothing, and this finds nothing.
    module = tmp_path / "dotted.py"
    module.write_text(
        "import stayfixed.scaffold.engine\n\n\ndef f(root):\n"
        "    return stayfixed.scaffold.engine.plan(root)\n",
        encoding="utf-8",
    )
    assert _planners_reached(module) == {"plan"}


def test_the_checker_sees_a_planner_imported_relatively(tmp_path: Path) -> None:
    # Nothing in the tree imports relatively today, which is why a check that read `.footprint`
    # as a module named `footprint` passed; the first relative import would have been a bypass
    # it could not see. Mutation (oracle): `mutations/`'s "the planning seam's checker reads a
    # relative import as a top-level module" -> `_absolute` ignores the level, both spellings find
    # nothing, and this reddens.
    module = tmp_path / "relative.py"
    module.write_text(
        "from . import footprint\nfrom .ignored import refuse_ignored\n\n\ndef f(root):\n"
        "    return footprint.plan(root)\n",
        encoding="utf-8",
    )
    assert _planners_reached(module) == {"plan", "refuse_ignored"}


def test_replanning_before_predicting_is_refused(tmp_path: Path) -> None:
    # `replan` plans without asking the ignore guard, because `predict` already asked it about
    # the same templates at the same targets; before `predict` nothing has asked it, so a
    # command that called `replan` first would write where git hides a file. Mutation (oracle):
    # `mutations/`'s "a footprint command replans what it never predicted" -> the order check
    # disabled, and `replan` plans instead of raising.
    root = repository(tmp_path)
    (root / CONFIG_FILE).write_text(DOCUMENT, encoding="utf-8")
    config = load(root, machine=tmp_path / "absent.toml")
    passes = prepare(root, config, document=DOCUMENT)
    with pytest.raises(RuntimeError, match="only after predict"):
        passes.replan(passes.footprint)
    passes.predict(passes.footprint)
    assert passes.replan(passes.footprint).actions


def test_a_predict_the_ignore_guard_refused_leaves_replanning_refused(tmp_path: Path) -> None:
    # The flag is set only after the guard passed: a `predict` it refused has asked it about
    # nothing a command may write, so `replan` must stay shut. Mutation (oracle): `mutations/`'s "a
    # refused prediction opens replan" -> the flag set before the guard, and `replan` plans.
    root = repository(tmp_path)
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    document = DOCUMENT + '\n[paths]\nagents_md = ".env"\n'
    (root / CONFIG_FILE).write_text(document, encoding="utf-8")
    config = load(root, machine=tmp_path / "absent.toml")
    passes = prepare(root, config, document=document)
    with pytest.raises(Refusal):
        passes.predict(passes.footprint)
    with pytest.raises(RuntimeError, match="only after predict"):
        passes.replan(passes.footprint)
