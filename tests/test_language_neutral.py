"""drybag names no language stack, so a repository in several languages works with no
configuration.

The walk reads every module under `src/drybag/` with `ast`, so comments and docstrings are prose
and are never read; string and bytes constants (an f-string's literal parts included) and
identifiers are code and are. A word counts where it stands alone, letters and
digits on neither side, so `PYTEST`, `is_pytest_run` and `"*.pyc"` are mentions and
`pipeline` is not.

`STACK_NAMED` is every mention the walk finds, each with the reason it stays, and the comparison
is equality both ways: a new mention reddens this test, and so does a pardon whose mention is gone,
so the list never outlives what it excuses.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "drybag"

# One stack's test runner, build artifacts or package manager, for the common stacks. `uv` stands
# for itself rather than for `uv run`: the walk reads one constant at a time, and the command
# scanner's `uv run` reading (`hints/runners.py`) spells its wrapper as the two words `"uv"` and
# `"run"`.
STACK_WORDS = (
    "python",
    "python3",
    "pyproject",
    "pytest",
    "pyc",
    "pycache",
    "venv",
    "pip",
    "poetry",
    "tox",
    "uv",
    "node_modules",
    "npm",
    "npx",
    "yarn",
    "pnpm",
    "jest",
    "vitest",
    "cargo",
    "mvn",
    "gradle",
)
_MENTION = re.compile(
    r"(?<![a-z0-9])(" + "|".join(re.escape(word) for word in STACK_WORDS) + r")(?![a-z0-9])"
)

STACK_NAMED = {
    # The table of test-runner program names (`hints/runners.py`) names runners only to say that a
    # command is a test run, never to run, plan or advise one, and it is the one place the hints
    # look this up, so no other hint names a stack to recognise a run. It also holds the unwrap of
    # `uv run <cmd>` to `<cmd>` up to the first word the table reads as a test run, which
    # `hints/bashscan.py` calls, so the scanner names no stack itself: `uv run` is a Python
    # launcher every stack's runner may stand behind.
    ("src/drybag/hints/runners.py", "uv"),
    ("src/drybag/hints/runners.py", "cargo"),
    ("src/drybag/hints/runners.py", "gradle"),
    ("src/drybag/hints/runners.py", "jest"),
    ("src/drybag/hints/runners.py", "mvn"),
    ("src/drybag/hints/runners.py", "npm"),
    ("src/drybag/hints/runners.py", "npx"),
    ("src/drybag/hints/runners.py", "pnpm"),
    ("src/drybag/hints/runners.py", "pytest"),
    ("src/drybag/hints/runners.py", "python"),
    ("src/drybag/hints/runners.py", "python3"),
    ("src/drybag/hints/runners.py", "tox"),
    ("src/drybag/hints/runners.py", "vitest"),
    ("src/drybag/hints/runners.py", "yarn"),
    # drybag's own installer, `uv tool install`, named in two of `doctor`'s remedies
    # (`cli-path` in the core's checks, `overlay-requires` in the overlay area's) and in `setup`'s
    # pinned install command: the tool drybag itself is installed with, not a stack a project
    # is written in.
    ("src/drybag/doctor/checks.py", "uv"),
    ("src/drybag/overlay/doctor.py", "uv"),
    ("src/drybag/setup/run.py", "uv"),
    # The git hook drybag installs runs drybag itself, under the `python3` that can import it:
    # drybag's own interpreter in its own hook, not the interpreter of a project's stack.
    ("src/drybag/guards/githooks.py", "python3"),
    # `setup --restore` says when the machine has neither `python3` nor `uv`: the two programs the
    # hook wrapper looks for to run drybag itself, not the stack of any project.
    ("src/drybag/setup/restore.py", "python3"),
    ("src/drybag/setup/restore.py", "uv"),
}


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))
    return found


def _code_text(tree: ast.AST) -> Iterator[str]:
    """Every string constant that is not a docstring, and every name the code spells."""
    prose = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in prose:
                yield node.value
        elif isinstance(node, ast.Constant) and isinstance(node.value, bytes):
            # Latin-1 maps every byte to one character, so an ASCII word in a bytes literal reads
            # as that word and no byte makes the decode fail.
            yield node.value.decode("latin-1")
        elif isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield node.name
        elif isinstance(node, ast.arg | ast.keyword) and node.arg is not None:
            yield node.arg
        elif isinstance(node, ast.alias):
            yield node.name
            if node.asname is not None:
                yield node.asname
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.module


def _core_modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def stack_mentions(modules: list[Path]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = path.relative_to(ROOT).as_posix()
        for text in _code_text(tree):
            for match in _MENTION.finditer(text.lower()):
                found.add((module, match.group(1)))
    return found


def words(text: str) -> set[str]:
    return {match.group(1) for match in _MENTION.finditer(text)}


def test_the_walk_reads_words_and_not_fragments() -> None:
    # The matcher's two edges, pinned on samples rather than inferred from the tree: a word is a
    # mention wherever an underscore, a dot or a space bounds it, and a longer word that merely
    # contains one is not. Reddened by dropping the lookbehind from `_MENTION` (`unpip` reads as
    # `pip`), and by dropping the lookahead (`pytests` reads as `pytest`); both measured.
    assert words("is_pytest_run *.pyc __pycache__ .venv tox_ini") == {
        "pytest",
        "pyc",
        "pycache",
        "venv",
        "tox",
    }
    assert words("pipeline unpip uvula pytests") == set()


def _read_the_core(modules: list[Path]) -> None:
    """A walk that read nothing -- a moved package, a wrong root -- would find no mention and
    pass but for `STACK_NAMED` happening not to be empty. The package's own `__init__.py` is read
    for as long as the package exists, so a walk without it is not reading it. Reddened by making
    `_core_modules` return `[]`; measured."""
    assert PACKAGE / "__init__.py" in modules


def test_no_core_module_names_a_stack_it_does_not_pardon() -> None:
    # Oracle: `mutations/`'s "the core names pytest again".
    modules = _core_modules()
    _read_the_core(modules)
    assert stack_mentions(modules) == STACK_NAMED
