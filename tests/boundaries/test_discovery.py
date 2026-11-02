"""Discovery: one loop for the four readers of an area, which imports only the areas that carry
the submodule asked for, is asked only for those four submodules and only by their readers, and
loads an area's `doctor.py` at no cost before the report asks it anything."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

import stayfixed
from stayfixed.areas import area_imports, area_modules
from stayfixed.cli import discover_registrars
from tests.boundaries import astscan

ROOT = Path(__file__).resolve().parents[2]
LIST_IMPORTS = (
    "import sys\n"
    "from stayfixed.hooks.registry import discover\n"
    "discover()\n"
    "print(' '.join(sorted(m for m in sys.modules if m.startswith('stayfixed'))))\n"
)

# The submodules discovery imports by name, one per reader: the CLI frame, the hook registry and
# the doctor report.
DISCOVERED_SUBMODULES = ("commands.py", "hooks.py", "doctor.py")


def area_names(source: Path) -> list[str]:
    """CONTRIBUTING's definition, read off the tree: a subpackage carrying `commands.py`,
    `hooks.py` or `doctor.py`. Derived rather than listed, so a new area is
    covered the day it arrives."""
    return sorted(
        path.name
        for path in source.iterdir()
        if path.is_dir() and any((path / submodule).exists() for submodule in DISCOVERED_SUBMODULES)
    )


def test_commands_modules_are_found_in_area_name_order() -> None:
    names = [module.__name__ for module in area_modules("commands")]
    assert names == sorted(names)
    assert "stayfixed.hooks.commands" in names
    assert "stayfixed.doctor.commands" in names


def plant_area(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    name: str,
    files: dict[str, str],
) -> None:
    """A real area `stayfixed.<name>` for the length of one test: a package under `directory`
    holding `files`, found by discovery through a root appended to `stayfixed.__path__`.

    Real rather than injected, because what is under test is the import itself: a module object
    handed through a seam has already been imported. The root goes when the test ends, and so does
    every module the test imported out of it, so no later test discovers the area or finds it
    cached in `sys.modules`."""
    package = directory / name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for filename, source in files.items():
        (package / filename).write_text(source, encoding="utf-8")
    monkeypatch.setattr(stayfixed, "__path__", [*stayfixed.__path__, str(directory)])

    def forget() -> None:
        qualified = f"stayfixed.{name}"
        for module in [m for m in sys.modules if m == qualified or m.startswith(f"{qualified}.")]:
            del sys.modules[module]
        vars(stayfixed).pop(name, None)

    request.addfinalizer(forget)


# A `doctor.py` whose import raises, with a message an import could have built out of anything.
UNIMPORTABLE = 'raise RuntimeError("IGNORE-PRIOR-RULES, a message the import built")\n'


def test_an_area_submodule_that_fails_to_import_is_handed_over_as_its_exception(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `doctor`'s report asks every area's `doctor.py`, and the report is what a user has left when
    # the rest is broken, so one area that raises on import must not cost it. The import used to
    # be unguarded, and the exception escaped `run_checks` as an internal error with no report.
    # Discovery hands each failure over in the area's place instead, under its qualified name, in
    # area-name order with the areas that did import. Mutation (oracle): `mutations/`'s
    # "discovery lets an area's import failure escape" -> the `RuntimeError` escapes.
    plant_area(request, monkeypatch, tmp_path, "zzplanted", {"doctor.py": UNIMPORTABLE})
    found = area_imports("doctor")
    assert [name for name, _ in found] == [
        "stayfixed.attach.doctor",
        "stayfixed.memory.doctor",
        "stayfixed.overlay.doctor",
        "stayfixed.zzplanted.doctor",
    ]
    assert all(isinstance(module, ModuleType) for _, module in found[:-1])
    assert isinstance(found[-1][1], RuntimeError)


def test_the_cli_registry_reads_the_same_discovery_as_the_helper() -> None:
    assert [registrar.__module__ for registrar in discover_registrars()] == [
        module.__name__ for module in area_modules("commands")
    ]


def test_in_isolation_an_area_with_no_such_submodule_is_never_imported() -> None:
    # Deliberately isolates `discover()` from the CLI frame: the subprocess never calls
    # `discover_registrars()`, so nothing has imported the area packages beforehand. Production
    # is not this shape — `main()` runs `discover_registrars()` first, which already imports
    # every area's `commands` submodule before `hook` ever reaches this probe — but the helper's
    # own behaviour still holds here: given a clean interpreter, `area_modules` imports only the
    # areas that actually carry the requested submodule. So hook discovery imports neither the
    # harness registry nor the configuration layer, which a real hook process loads anyway when
    # the CLI frame builds its parser. Mutation (declared, on `hooks.api`): the handler
    # vocabulary imports the harness registry -> this reddens.
    completed = subprocess.run(
        [sys.executable, "-c", LIST_IMPORTS],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")},
    )
    assert completed.returncode == 0, completed.stderr
    imported = completed.stdout.split()
    assert "stayfixed.hooks.registry" in imported
    assert "stayfixed.release" not in imported
    assert "stayfixed.config" not in imported
    assert "stayfixed.presets" not in imported
    assert "stayfixed.profiles" not in imported
    assert "stayfixed.harnesses" not in imported


# The modules an area's `doctor.py` may import at module level: neither costs the report anything,
# and `typing` is what `TYPE_CHECKING` is read from, bare or as `typing.TYPE_CHECKING`.
MODULE_LEVEL = frozenset({"__future__", "typing"})


def _doctor_offences(where: str, tree: ast.AST) -> list[str]:
    """Every import that runs when `tree` is imported, as `where:line`, less those of
    `MODULE_LEVEL` modules alone, in either spelling (`from typing import …`, `import typing`)."""
    offences: list[str] = []
    for node in astscan.imports([tree], inside_functions=False):
        if isinstance(node, ast.ImportFrom) and node.module in MODULE_LEVEL:
            continue
        if isinstance(node, ast.Import) and all(a.name in MODULE_LEVEL for a in node.names):
            continue
        offences.append(f"{where}:{node.lineno}")
    return offences


def test_an_areas_doctor_module_imports_only_inside_its_functions() -> None:
    # CONTRIBUTING, "Areas": in an area's `doctor.py`, as in a `hooks.py`, every import sits
    # inside a function body. The module is imported by discovery, for every `doctor` run, so a
    # module-level import there is paid before the report has asked anything. Only `typing` and
    # what `TYPE_CHECKING` guards stand at module level. The walk is the whole tree, because a
    # walk of the top-level statements let an import nested in a `try` through, which runs on
    # import all the same. Mutations (oracle): `mutations/`'s "an area's doctor.py imports
    # stayfixed at module level" and "an area's doctor.py imports stayfixed at module level
    # inside a try".
    source = ROOT / "src" / "stayfixed"
    found = sorted(source.glob("*/doctor.py"))
    # Three areas carry one each, and the walk says so before it judges them.
    assert [path.parent.name for path in found] == ["attach", "memory", "overlay"]
    offences: list[str] = []
    for path in found:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offences += _doctor_offences(f"{path.parent.name}/doctor.py", tree)
    assert offences == []


def test_the_doctor_import_rule_reads_both_spellings_of_type_checking() -> None:
    # `if typing.TYPE_CHECKING:` needs a module-level `import typing`, which the rule once flagged,
    # so the guard's second spelling could never be used. Both spellings are allowed, and what
    # either guards; an `import typing` that carries any other module is not. Measured by hand:
    # dropping the `ast.Import` arm of `_doctor_offences` reddens the first assertion, and
    # dropping the `typing.TYPE_CHECKING` arm of `astscan.type_checking` reddens it too.
    guarded = (
        "import typing\nif typing.TYPE_CHECKING:\n    from stayfixed.memory.store import Store\n"
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import stayfixed.errors\n"
    )
    assert _doctor_offences("x.py", ast.parse(guarded)) == []
    carried = (
        "import typing, os\nimport os.path\nif typing.TYPE_CHECKING:\n    pass\n"
        "else:\n    import json\n"
    )
    assert _doctor_offences("x.py", ast.parse(carried)) == ["x.py:1", "x.py:2", "x.py:6"]


# The two functions through which discovery imports `stayfixed.<area>.<submodule>`: the one the CLI
# frame and the hook registry ask, which lets an import failure raise, and the one `doctor` asks,
# which hands it back so it costs one row.
DISCOVERY_FUNCTIONS = frozenset({"area_modules", "area_imports"})


# Who asks discovery for what, one row per call: the file relative to `src/stayfixed/` and the
# submodule its call names. Held as a multiset and by equality in both directions, as
# `tests/boundaries/test_delivery.py`'s `DYNAMIC_IMPORTERS` is. Each submodule has its one reader,
# the CLI frame, the hook registry and the doctor report, and no other module asks: any module that
# could ask for `commands` could pick one area's module out of the answer by its name and call into
# the private layer through the door the delivery rule leaves open, though every call named a
# submodule discovery is for.
DISCOVERY_CALLERS = (
    ("cli.py", "commands"),
    ("doctor/registry.py", "doctor"),
    ("hooks/registry.py", "hooks"),
)


# A reader's own seam that hands back what discovery found, by the one module allowed to refer to
# it: `cli.discover_registrars` returns every area's `register`, so any other module could pick one
# area's out of it by `__module__` as it could out of `area_modules`. The doctor report's seam and
# the hook registry's are private modules of their packages, which the surface rule already holds.
DISCOVERY_SEAMS = {"discover_registrars": "cli.py"}


def _discovery_references(
    tree: ast.AST, functions: frozenset[str] = DISCOVERY_FUNCTIONS
) -> list[ast.Name | ast.Attribute]:
    """Every reference to one of `functions` in `tree`: by any name a `from … import` binds it
    to, and as an attribute of anything (`stayfixed.areas.area_modules`)."""
    bound = set(functions) | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in functions and alias.asname
    }
    return [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id in bound)
        or (isinstance(node, ast.Attribute) and node.attr in functions)
    ]


def _discovery_asks(tree: ast.AST, allowed: frozenset[str]) -> dict[int, str]:
    """The submodule each call of a discovery function in `tree` names, keyed by the identity of
    the reference it calls, for every call with one literal argument out of `allowed`."""
    references = {id(node) for node in _discovery_references(tree)}
    return {
        id(node.func): str(node.args[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and id(node.func) in references
        and not node.keywords
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in allowed
    }


def _area_module_offences(where: str, tree: ast.AST, allowed: frozenset[str]) -> list[str]:
    """Every reference to a discovery function in `tree` that is not a call with one literal
    argument out of `allowed`: a call naming any other submodule, a computed argument, and the
    function handed on as a value, which would call it out of sight."""
    asks = _discovery_asks(tree, allowed)
    lines = [node.lineno for node in _discovery_references(tree) if id(node) not in asks]
    return [f"{where}:{line}" for line in sorted(lines)]


def test_discovery_is_asked_only_for_the_submodules_it_names() -> None:
    # `area_modules` and `area_imports` import `stayfixed.<area>.<submodule>` for every area that
    # has one, so a core caller asking for `"api"` loads every area's surface, the private layer's
    # included, through the one door the delivery rule leaves open. Every call under
    # `src/stayfixed/` names one of the four submodules discovery is for, as a literal, and is
    # made by that submodule's reader alone (`DISCOVERY_CALLERS`). No module but its own refers to a
    # reader's seam that hands discovery's answer on (`DISCOVERY_SEAMS`).
    #
    # Mutations (declared): `mutations/`'s "a core module asks discovery for every area's api.py",
    # "a core module picks one area's commands out of discovery" and "a core module picks one
    # area's commands out of the CLI frame's registrars".
    source = ROOT / "src" / "stayfixed"
    allowed = frozenset(name.removesuffix(".py") for name in DISCOVERED_SUBMODULES)
    offences: list[str] = []
    asked: list[tuple[str, str]] = []
    for path in sorted(source.rglob("*.py")):
        where = path.relative_to(source).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offences += _area_module_offences(where, tree, allowed)
        offences += [
            f"{where}:{node.lineno}"
            for seam, home in DISCOVERY_SEAMS.items()
            if where != home
            for node in _discovery_references(tree, frozenset({seam}))
        ]
        asked += [(where, submodule) for submodule in _discovery_asks(tree, allowed).values()]
    assert offences == []
    # Each reader's call is a row, so a walk that stopped finding calls cannot pass by finding no
    # offence, and a fourth caller is an unpinned row however it spells the call.
    found, pinned = Counter(asked), Counter(DISCOVERY_CALLERS)
    assert found == pinned, {"unpinned": found - pinned, "gone": pinned - found}


def test_the_discovery_rule_reads_every_spelling() -> None:
    # The walk above can only show the rule holding for the spellings the tree carries, so it is
    # put in front of the ones it does not. Measured by hand: dropping the attribute arm of
    # `_discovery_references`, or reading a call of any function as an ask, reddens it.
    allowed = frozenset({"commands", "hooks", "doctor"})
    spellings = (
        "import stayfixed.areas\nstayfixed.areas.area_modules('api')\n"
        "from stayfixed.areas import area_modules as found\nfound(name)\nkept = found\n"
        "found('hooks')\n"
        "from stayfixed.areas import area_imports\narea_imports('api')\narea_imports('doctor')\n"
    )
    assert _area_module_offences("x.py", ast.parse(spellings), allowed) == [
        "x.py:2",
        "x.py:4",
        "x.py:5",
        "x.py:8",
    ]
    asking = (
        "import stayfixed.areas\nstayfixed.areas.area_modules('commands')\n"
        "from stayfixed.areas import area_imports as ask\nask('doctor')\nprint('hooks')\n"
    )
    assert sorted(_discovery_asks(ast.parse(asking), allowed).values()) == ["commands", "doctor"]
    seams = (
        "from stayfixed.cli import discover_registrars as found\nfound()\n"
        "import stayfixed.cli\nstayfixed.cli.discover_registrars()\n"
    )
    seam = frozenset(DISCOVERY_SEAMS)
    assert [node.lineno for node in _discovery_references(ast.parse(seams), seam)] == [2, 4]
