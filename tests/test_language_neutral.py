"""The core names no language stack: what one stack's runner, artifacts or package manager need
lives in that stack's profile directory, `src/stayfixed/profiles/<name>/`, so a repository in
several languages works with no configuration.

The walk reads every module under `src/stayfixed/` outside those stack directories with `ast` --
the profiles' own machinery directly under `profiles/` is core and is read -- so comments and
docstrings are prose and are never read; string and bytes constants (an f-string's literal parts
included) and identifiers are code and are. A word counts where it stands alone, letters and
digits on neither side, so `PYTEST`, `is_pytest_run` and `"*.pyc"` are mentions and
`pipeline` is not.

`STACK_NAMED` is every mention the walk finds, each with the reason it stays in the core, and the
comparison is equality both ways: a new mention reddens this test, and so does a pardon whose
mention is gone, so the list never outlives what it excuses.

The words catch a stack named in the core; they do not catch the core importing a stack's own
code, because `stayfixed.profiles.python.hygiene` holds no listed word. So the same walk also reads
every import, and a core module that imports from a stack's directory, a profile's or one holding
code alone, fails on its own.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from stayfixed.profiles import shipped

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "stayfixed"
PROFILES = PACKAGE / "profiles"

# One stack's test runner, build artifacts or package manager, for the common stacks. `uv` stands
# for itself rather than for `uv run`: the walk reads one constant at a time, and the command
# scanner's `uv run` reading (`hints/uvrun.py`) spells its wrapper as the two words `"uv"` and
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
    # The ledger scan's exclusions. `EXCLUDED_DIRNAMES` (`node_modules`, `.git`, `.venv`, `dist`,
    # `build`, `__pycache__`) are directories neither the mention scan nor the sweep walks into,
    # because they hold vendored, installed or generated trees in which nobody filed a reference;
    # `BINARY_SUFFIXES` (images, a PDF, audio, web fonts, `.zip` and `.pyc`) are files no
    # identifier can be read out of. The lists are not even-handed across stacks: they name
    # Python's and Node's trees and Python's bytecode suffix, and no other stack's (no `target/`,
    # no `vendor/`), so another stack's generated tree is scanned where these are skipped. What
    # they decide is which files the ledger reads, never which stack's runner is asked or advised.
    ("src/stayfixed/ledger/scan.py", "node_modules"),
    ("src/stayfixed/ledger/scan.py", "venv"),
    ("src/stayfixed/ledger/scan.py", "pycache"),
    ("src/stayfixed/ledger/scan.py", "pyc"),
    # The command scanner unwraps `uv run <cmd>` to `<cmd>`, as it unwraps `env <cmd>`, up to
    # the first word a runner adapter recognises; this module is that unwrap and the directory
    # uv runs the command in, which `hints/bashscan.py` and `prove` call, so neither names a
    # stack itself. `uv run` is a Python launcher, and it stays beside the shared scanner rather
    # than in the Python profile because every stack's runner may stand behind it.
    ("src/stayfixed/hints/uvrun.py", "uv"),
    # stayfixed's own installer, `uv tool install`, named in two of `doctor`'s remedies
    # (`cli-path` in the core's checks, `overlay-requires` in the overlay area's) and in `setup`'s
    # pinned install command: the tool stayfixed itself is installed with, not a stack a project
    # is written in.
    ("src/stayfixed/doctor/checks.py", "uv"),
    ("src/stayfixed/overlay/doctor.py", "uv"),
    ("src/stayfixed/setup/run.py", "uv"),
    # The git hook stayfixed installs runs stayfixed itself, under the `python3` that can import it:
    # stayfixed's own interpreter in its own hook, not the interpreter of a project's stack.
    ("src/stayfixed/guards/githooks.py", "python3"),
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


def _in_a_stack_directory(path: Path) -> bool:
    """True under `profiles/<name>/`, where one stack's knowledge belongs; `profiles/hints.py`
    and the rest of the machinery beside it are core."""
    return PROFILES in path.parents and path.parent != PROFILES


def _core_modules() -> list[Path]:
    return [path for path in sorted(PACKAGE.rglob("*.py")) if not _in_a_stack_directory(path)]


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
    """A walk that read nothing -- a moved package, a wrong root -- would find no mention and no
    import and pass. The package's own `__init__.py` and the profiles' machinery beside the stack
    directories are core for as long as the package exists, so a walk without them is not
    reading the core. Reddened by making `_core_modules` return `[]`; measured. Without it the
    import walk would pass on an empty walk, and the mention walk would fail only because
    `STACK_NAMED` happens not to be empty."""
    assert PACKAGE / "__init__.py" in modules
    assert PROFILES / "hints.py" in modules


def test_no_core_module_names_a_stack_it_does_not_pardon() -> None:
    # Oracle: `mutations/`'s "the core names pytest again".
    modules = _core_modules()
    _read_the_core(modules)
    assert stack_mentions(modules) == STACK_NAMED


def _dotted(path: Path) -> str:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported(path: Path, tree: ast.AST) -> Iterator[str]:
    """Every module `tree` imports, by its absolute name, with a relative import resolved against
    `path`'s package and `from package import name` read as `package.name` too, since `name` may
    be a module."""
    package = _dotted(path) if path.name == "__init__.py" else _dotted(path).rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package.split(".")
            if node.level:
                base = base[: len(base) - node.level + 1]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            yield module
            yield from (f"{module}.{alias.name}" for alias in node.names)


def stack_packages(profiles: Path) -> tuple[str, ...]:
    """Every stack's directory under `profiles`, a profile or not: a stack may ship a runner's
    adapters and no profile, and its code is a stack's all the same. `__pycache__` and any other
    name no stack could have are left out."""
    return tuple(
        sorted(
            p.name for p in profiles.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))
        )
    )


def stack_imports(modules: list[Path]) -> set[tuple[str, str]]:
    stacks = tuple(f"stayfixed.profiles.{name}" for name in stack_packages(PROFILES))
    found: set[tuple[str, str]] = set()
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in imported(path, tree):
            if any(module == stack or module.startswith(stack + ".") for stack in stacks):
                found.add((path.relative_to(ROOT).as_posix(), module))
    return found


@pytest.mark.parametrize(
    ("source", "module"),
    [
        ("import stayfixed.profiles.python.hygiene", "stayfixed.profiles.python.hygiene"),
        ("from stayfixed.profiles import python", "stayfixed.profiles.python"),
        ("from .python import hygiene", "stayfixed.profiles.python.hygiene"),
    ],
)
def test_the_import_reader_resolves_every_spelling_of_a_stack_import(
    source: str, module: str
) -> None:
    # Pinned on samples, read as if from the profiles' own machinery, rather than inferred from
    # the tree, which holds no such import. Reddened by yielding `node.module` alone for an
    # `ImportFrom` (the second and third cases), and by dropping the relative resolution (the
    # third); both measured.
    assert module in set(imported(PROFILES / "hints.py", ast.parse(source)))


def test_every_stack_directory_is_read_whether_or_not_it_holds_a_profile(tmp_path: Path) -> None:
    # A stack may ship its runner's adapters with no `profile.toml` beside them, and a core import
    # of that code is a stack import all the same; reading `shipped()` alone left it unseen.
    # Measured by hand: `stack_packages` returning `shipped()` drops `go` here.
    for name, file in (("python", "profile.toml"), ("go", "adapters.py"), ("__pycache__", "x.pyc")):
        (tmp_path / name).mkdir()
        (tmp_path / name / file).write_text("", encoding="utf-8")
    assert stack_packages(tmp_path) == ("go", "python")
    assert set(shipped()) <= set(stack_packages(PROFILES))


def test_no_core_module_imports_a_stack_profiles_code() -> None:
    # The core reaches a stack's code only by discovering it (`stayfixed.profiles.hints`), never
    # by naming it in an import. Oracle: `mutations/`'s "the core imports the Python profile's
    # hint".
    modules = _core_modules()
    _read_the_core(modules)
    assert stack_imports(modules) == set()
