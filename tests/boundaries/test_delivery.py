"""The sides: every module under `src/stayfixed/` is on one of three, delivery, the pack or the
core, as `stayfixed.areas` lists them. The core imports neither side and the two sides import each
other only through the statements pinned here, each with what removes it; importing the core loads
neither side; and no module imports by a string or reaches the import machinery but where pinned,
so the import rules cannot be walked around."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import pytest

import stayfixed.areas
from tests.boundaries import astscan
from tests.boundaries.test_discovery import area_names

ROOT = Path(__file__).resolve().parents[2]

DELIVERY, PACK, CORE = "delivery", "pack", "core"

Row = tuple[str, str, frozenset[str]]
Direction = tuple[str, str]

# Every import by which a module reaches a package on another side, one row per import statement
# and one table per direction: the importing file relative to `src/stayfixed/`, the module the
# statement names cut to three dotted parts, and the names it takes out of that module. Each table
# is held as a multiset and by equality in both directions, so a new crossing reddens its test, and
# so do a row whose import has gone, a second statement beside a pinned one, and a pinned statement
# that takes one more name: the pardon covers exactly the statements and names written here, and
# cutting a crossing is deleting its rows in the same commit. Each row says what removes it.
# Importing the core is no crossing from either side, and neither is an import within one side.
CORE_TO_DELIVERY: tuple[Row, ...] = ()
CORE_TO_PACK: tuple[Row, ...] = (
    # The harness registry names a profile's type in the rendering a harness gives a profile's
    # rules, under `if TYPE_CHECKING:`, so it never runs. Goes with the profiles.
    ("harnesses.py", "stayfixed.profiles", frozenset({"Profile"})),
    # The scaffold engine checks `[stayfixed] profile` against the profiles that ship, inside the
    # one function that checks it. Goes with the profiles.
    ("scaffold/engine.py", "stayfixed.profiles", frozenset()),
)
PACK_TO_DELIVERY: tuple[Row, ...] = (
    # `stayfixed test hygiene` counts the uncommitted changes the red-run note counts, so the two
    # cannot disagree. Goes when that count moves into the core, or the command leaves `guards`.
    ("guards/commands.py", "stayfixed.hints.api", frozenset({"dirty_count"})),
    # `stayfixed uninstall` detaches an attached repository before it takes the scaffold back,
    # inside the one function that runs it. Goes when `stayfixed uninstall` is deleted.
    ("project/uninstall.py", "stayfixed.attach.api", frozenset({"detach"})),
    # `prove` reads a test command's launch the way the red-run hints read it, at module level.
    # Goes with `prove`.
    ("prove/run.py", "stayfixed.hints.api", frozenset({"Launch", "read_launch", "run_directory"})),
)
DELIVERY_TO_PACK: tuple[Row, ...] = (
    # The red-run note asks every shipped profile's hint and adapter, and names a hint's type
    # under `if TYPE_CHECKING:`. All three go with the profiles.
    ("hints/hygiene.py", "stayfixed.profiles.adapters", frozenset({"shipped_adapters"})),
    ("hints/hygiene.py", "stayfixed.profiles.hints", frozenset({"answer", "shipped_hints"})),
    ("hints/hygiene.py", "stayfixed.profiles.hints", frozenset({"RedRunHint"})),
    # The note graph flags a bug id written as a link, and asks the bug register which words are
    # ids. Goes when the note graph takes the id rule from the core.
    ("memory/graph.py", "stayfixed.ledger.api", frozenset({"bug_register"})),
    # `stayfixed setup --git-hooks` installs and removes the commit-message hook, inside the one
    # function that runs it. Goes when the commit-hook installer leaves `setup`.
    ("setup/commands.py", "stayfixed.guards.api", frozenset({"Found", "install", "uninstall"})),
)
PINNED: dict[Direction, tuple[Row, ...]] = {
    (CORE, DELIVERY): CORE_TO_DELIVERY,
    (CORE, PACK): CORE_TO_PACK,
    (PACK, DELIVERY): PACK_TO_DELIVERY,
    (DELIVERY, PACK): DELIVERY_TO_PACK,
}


def _side(name: str, delivery: frozenset[str], pack: frozenset[str]) -> str:
    """The side of the module or package `name` directly under `src/stayfixed/`: one neither side
    lists is the core's."""
    return DELIVERY if name in delivery else PACK if name in pack else CORE


def _crossings(
    where: str, text: str, delivery: frozenset[str], pack: frozenset[str]
) -> list[tuple[Direction, Row]]:
    """The rule, for one file: every import statement by which it reaches a package on another
    side, as `((its side, the side reached), (where, module, names))` with the module cut to three
    dotted parts. Reaching the core is no crossing, and neither is reaching a package of one's own
    side.

    One row per import statement, keyed on the module the statement names and never on its
    aliases: `astscan.imported_modules` also yields `stayfixed.overlay.api.create` for every name a
    `from` imports, which would turn one import of four names into four rows. The names are the
    row's third part instead, as written, so a pardon is for one statement and what it takes; a
    statement that imports a module itself (`import stayfixed.overlay.api`) takes no names. The
    one spelling whose aliases are the modules is `from stayfixed import memory`, and it is read
    as such: a row per package, importing the package itself. A module is on the side its first
    path part is listed on, so `cli.py`, `config/` and every other module and subpackage that
    neither side lists are the core's.
    """
    parts = Path(where).parts
    origin = _side(parts[0], delivery, pack)
    rows: list[tuple[Direction, Row]] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            taken = [(alias.name, frozenset[str]()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # `astscan.imported_modules` yields the statement's own module first, resolved when
            # the import is relative, and then one name per alias.
            module = astscan.imported_modules(node, ("stayfixed", *parts[:-1]))[0][1]
            taken = [(module, frozenset(alias.name for alias in node.names))]
            if module == "stayfixed":
                taken = [(f"{module}.{alias.name}", frozenset[str]()) for alias in node.names]
        else:
            continue
        for module, names in taken:
            bits = module.split(".")
            ours = bits[0] == "stayfixed" and len(bits) > 1
            target = _side(bits[1], delivery, pack) if ours else CORE
            if target not in (origin, CORE):
                rows.append(((origin, target), (where, ".".join(bits[:3]), names)))
    return rows


def _unpinned_or_gone(*directions: Direction) -> dict[str, dict[str, Counter[Row]]]:
    """For each of `directions` whose rows the whole package's walk does not find exactly as
    `PINNED` has them: the rows found and not pinned (`unpinned`) and pinned and not found
    (`gone`). Empty when every one is held."""
    source = ROOT / "src" / "stayfixed"
    paths = sorted(source.rglob("*.py"))
    # A walk that stopped walking finds no crossing, which an empty table holds, so the walk is
    # held first: a floor well under the package's size, not kept current.
    assert len(paths) >= 100, len(paths)
    found: Counter[tuple[Direction, Row]] = Counter()
    for path in paths:
        found.update(
            _crossings(
                path.relative_to(source).as_posix(),
                path.read_text(encoding="utf-8"),
                stayfixed.areas.DELIVERY_AREAS,
                stayfixed.areas.PACK_PACKAGES,
            )
        )
    differences: dict[str, dict[str, Counter[Row]]] = {}
    for direction in directions:
        walked = Counter({row: n for (way, row), n in found.items() if way == direction})
        pinned = Counter(PINNED[direction])
        if walked != pinned:
            differences[" -> ".join(direction)] = {
                "unpinned": walked - pinned,
                "gone": pinned - walked,
            }
    return differences


def test_the_core_imports_neither_side_but_where_pinned() -> None:
    # CONTRIBUTING, "Areas": either side may import the core, and the core may not import either
    # side, through `api.py` or not, at module level or inside a function, but for the statements
    # `CORE_TO_DELIVERY` and `CORE_TO_PACK` pin.
    #
    # Mutation (declared): `mutations/`'s "a core module imports the bug ledger".
    assert _unpinned_or_gone((CORE, DELIVERY), (CORE, PACK)) == {}


def test_delivery_and_the_pack_import_each_other_only_where_pinned() -> None:
    # The two sides each import the core and import each other through the statements
    # `PACK_TO_DELIVERY` and `DELIVERY_TO_PACK` pin and no other, so each can be reworked without
    # the other; an import within one side is no crossing. Held as the core's rule is, in both
    # directions.
    #
    # Mutations (declared): `mutations/`'s "the note store imports the bug ledger", "a pinned
    # crossing's import goes while its row stays" and "setup imports one more name from the guards
    # area in a statement of its own", the last of which a comparison of `(file, module)` sets let
    # through.
    assert _unpinned_or_gone((PACK, DELIVERY), (DELIVERY, PACK)) == {}


# Imports every module it is handed, then prints every `stayfixed` module the interpreter loaded.
IMPORT_EACH = (
    "import importlib, sys\n"
    "for name in sys.argv[1:]:\n"
    "    importlib.import_module(name)\n"
    "print(' '.join(sorted(m for m in sys.modules if m.startswith('stayfixed'))))\n"
)


def core_files(source: Path) -> list[tuple[str, Path]]:
    """Every core file under `source`, relative to it: each module on neither side, `cli.py` and
    the subpackages that are not areas included."""
    sides = stayfixed.areas.DELIVERY_AREAS | stayfixed.areas.PACK_PACKAGES
    return [
        (path.relative_to(source).as_posix(), path)
        for path in sorted(source.rglob("*.py"))
        if path.relative_to(source).parts[0] not in sides
    ]


def test_in_isolation_no_core_module_loads_either_side() -> None:
    # The source rules above read statements, and a statement inside a function, or under
    # `if TYPE_CHECKING:`, is pardoned there because it is a pinned crossing. What they cannot see
    # is when that statement runs: a crossing stood at module level in `setup/run.py`,
    # `setup/api.py` re-exports from that module, and `doctor/entries.py` imported `setup.api` for
    # `USER_SETTINGS` — so importing `doctor`'s report loaded `overlay.api`, `overlay.create`,
    # `memory.store` and the rest of the private layer, with every rule green. So every core module
    # is imported in one clean interpreter, which loads the union of their import closures, and no
    # module of either side may be among what it loaded: the core loads a side only when a command
    # asks for it.
    #
    # Mutation (declared): `mutations/`'s "the harness registry loads the profiles at import".
    source = ROOT / "src" / "stayfixed"
    # Every core module, dotted. `__main__` is left out because importing it runs the CLI: its
    # whole body is `main()`.
    modules = [
        ".".join(("stayfixed", *Path(where).with_suffix("").parts)).removesuffix(".__init__")
        for where, _ in core_files(source)
        if Path(where).name != "__main__.py"
    ]
    # The walk names the modules the pinned crossings start from and the report that once loaded
    # the private layer, so a list that stopped holding them cannot keep this green.
    assert {
        "stayfixed.cli",
        "stayfixed.doctor.api",
        "stayfixed.doctor.checks",
        "stayfixed.harnesses",
        "stayfixed.scaffold.engine",
    } <= set(modules), modules
    completed = subprocess.run(
        [sys.executable, "-c", IMPORT_EACH, *modules],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(source.parent)},
    )
    assert completed.returncode == 0, completed.stderr
    loaded = completed.stdout.split()
    assert "stayfixed.doctor.checks" in loaded, "the probe imported nothing"
    delivery, pack = stayfixed.areas.DELIVERY_AREAS, stayfixed.areas.PACK_PACKAGES
    tops = {name: name.split(".")[1] for name in loaded if "." in name}
    assert [name for name, top in tops.items() if _side(top, delivery, pack) != CORE] == []


def test_every_area_is_on_exactly_one_side() -> None:
    # The import rules judge a module by the side its first path part is listed on, and a module
    # listed on neither is the core's, so an area dropped from its side would join the core
    # unseen and be held to the core's rule, and one listed on two sides would be read as the
    # first. So every area discovery finds is listed on exactly one side, `DELIVERY_AREAS` and
    # `CORE_AREAS` list areas, `PACK_PACKAGES` lists packages (the profiles are one and not an
    # area), and every listed name names one: an area joins its side in the change that writes it.
    #
    # Mutations (declared): `mutations/`'s "trust drops out of every side" and "memory stops being
    # a delivery area".
    source = ROOT / "src" / "stayfixed"
    delivery, pack = stayfixed.areas.DELIVERY_AREAS, stayfixed.areas.PACK_PACKAGES
    core = stayfixed.areas.CORE_AREAS
    listed = Counter([*delivery, *pack, *core])
    assert [name for name, sides in listed.items() if sides > 1] == []
    areas = set(area_names(source))
    assert areas - set(listed) == set()
    packages = {path.name for path in source.iterdir() if (path / "__init__.py").is_file()}
    assert (delivery | core) - areas | pack - packages == set()


def test_the_delivery_rule_judges_the_importer_and_the_imported() -> None:
    # The walks above can only show the rules holding for the imports the tree happens to make, so
    # the rule is put in front of spellings the tree does not carry. A core module reaching a
    # delivery area relatively and from inside a function is a crossing, named exactly; a delivery
    # module reaching another delivery area is not, because an import within one side is no
    # crossing.
    #
    # Mutations (declared): `mutations/`'s "the delivery rule stops recognising a delivery
    # module" -> the first arm reddens; "the delivery rule holds a delivery module to the core's
    # rule" -> the second does.
    delivery = frozenset({"attach", "memory", "overlay"})
    pack = frozenset({"ledger", "profiles"})
    assert _crossings(
        "doctor/commands.py", "def check():\n    from ..memory import api\n", delivery, pack
    ) == [((CORE, DELIVERY), ("doctor/commands.py", "stayfixed.memory", frozenset({"api"})))]
    assert _crossings("memory/x.py", "import stayfixed.overlay.api\n", delivery, pack) == []

    # Every direction, and the core reached from each: one text, imported from each side. Measured
    # by hand: reading an import of the core as a crossing, or reading the pack as delivery, each
    # reddens one of these.
    text = "import stayfixed.ledger.api\nimport stayfixed.memory.store\nimport stayfixed.fsops\n"
    assert _crossings("cli.py", text, delivery, pack) == [
        ((CORE, PACK), ("cli.py", "stayfixed.ledger.api", frozenset())),
        ((CORE, DELIVERY), ("cli.py", "stayfixed.memory.store", frozenset())),
    ]
    assert _crossings("ledger/x.py", text, delivery, pack) == [
        ((PACK, DELIVERY), ("ledger/x.py", "stayfixed.memory.store", frozenset()))
    ]
    assert _crossings("memory/x.py", text, delivery, pack) == [
        ((DELIVERY, PACK), ("memory/x.py", "stayfixed.ledger.api", frozenset()))
    ]

    # The one spelling whose module is the package itself, so the area is in an alias: read by
    # alias, and only for that spelling. Mutation (declared): `mutations/`'s "the delivery rule
    # reads `from stayfixed import memory` as importing nothing".
    assert _crossings("cli.py", "from stayfixed import fsops, memory\n", delivery, pack) == [
        ((CORE, DELIVERY), ("cli.py", "stayfixed.memory", frozenset()))
    ]

    # Two statements naming one module are two rows, each with the names it takes, so a pardon
    # for one statement is never a pardon for a second one beside it. Mutation (declared):
    # `mutations/`'s "the delivery rule forgets which names a statement takes".
    two = "from stayfixed.overlay.api import create\nfrom stayfixed.overlay.api import create\n"
    assert _crossings("doctor/checks.py", two, delivery, pack) == [
        ((CORE, DELIVERY), ("doctor/checks.py", "stayfixed.overlay.api", frozenset({"create"}))),
        ((CORE, DELIVERY), ("doctor/checks.py", "stayfixed.overlay.api", frozenset({"create"}))),
    ]
    assert _crossings(
        "doctor/checks.py",
        "from stayfixed.overlay.api import create, target_root\n",
        delivery,
        pack,
    ) == [
        (
            (CORE, DELIVERY),
            ("doctor/checks.py", "stayfixed.overlay.api", frozenset({"create", "target_root"})),
        )
    ]


# The names through which a module is loaded without an import statement of its own, which the
# import rules above read no more than discovery's caller does: `import_module` and `__import__`
# import by a string, a module's own `__spec__` and `__loader__` and the finders on `sys`'s
# `meta_path`, `path_hooks` and `path_importer_cache` load a module by its file with no import at
# all, and `sys.breakpointhook` and `sys.__breakpointhook__` import whatever `PYTHONBREAKPOINT`
# names. Each is read as an attribute of anything, as a bare name, and inside a string constant
# that is not a docstring: a message that names one is a row, to pin or to reword.
DYNAMIC_IMPORTS = frozenset(
    {
        "__breakpointhook__",
        "__import__",
        "__loader__",
        "__spec__",
        "breakpointhook",
        "import_module",
        "meta_path",
        "path_hooks",
        "path_importer_cache",
    }
)
# The builtins that run code built from text, and the module that holds every builtin, which hands
# `__import__` over by a computed name. Read as a bare name unless, by Python's scoping, it resolves
# to a function's own binding, a comprehension's variable or an import from any module but
# `builtins`, in that scope or one around it; as a binding made in a module or a class body, which
# Python looks up at run time, so that the binding may not have run, may have been deleted, or may
# be the builtin itself (`exec = exec`), and which therefore hides nothing and is a row to pin or
# rename; under any alias `from builtins import` gives one; and as a whole string constant (a
# choice spelled `"eval"` is a row too, to pin or to reword). Not as an attribute: `compile` is
# `re.compile` there, and `builtins.exec` needs `builtins`, which the machinery rule below holds.
# `__builtins__` is the exception: every module carries it, so it is read as an attribute of
# anything (`json.__builtins__`), and a `from` of it from any module is a row, under any alias.
TEXT_RUNNERS = frozenset({"__builtins__", "breakpoint", "compile", "eval", "exec"})

# The one module whose job is importing modules by name: discovery, which imports
# `stayfixed.<area>.<submodule>` for the submodules `area_modules` is called with (held below), and
# is how every area, on either side or in the core, plugs into the core.
DISCOVERY_MODULE = "areas.py"
# What discovery itself reads of the names below, by function: its two imports by name.
DISCOVERY_READS = (("area_modules", "import_module"), ("area_imports", "import_module"))

# Every other place a module imports by a string, one row per reference: the file relative to
# `src/stayfixed/`, the innermost function, and the name it reaches. Held as a multiset and by
# equality in both directions, as the crossings are.
#
# One row, meant to stay. `profiles/__init__.py`'s `stack_module` imports
# `stayfixed.profiles.<name>.<module>` for a `name` that `stack_directories` listed from this
# package's own directories through `importlib.resources` — stack discovery, which CONTRIBUTING's
# "Areas" describes beside area discovery, and the one import both a red-run hint
# (`profiles/hints.py`) and a runner adapter (`profiles/adapters.py`) are loaded through. It names
# no area and no repository path, so it is pinned here rather than moved into `areas.py`, which
# knows nothing of profiles.
DYNAMIC_IMPORTERS = (("profiles/__init__.py", "stack_module", "import_module"),)


def _dynamic_imports(tree: ast.Module) -> list[tuple[str, str]]:
    """Every reference in `tree` to a `DYNAMIC_IMPORTS` or `TEXT_RUNNERS` name, as `(function,
    name)`, `function` being the innermost enclosing `def` or `<module>`.

    Read as: a `DYNAMIC_IMPORTS` name as an attribute of anything (`importlib.import_module`,
    `builtins.__import__`, `sys.meta_path`, `module.__spec__`), by its bare name, by any name a
    `from … import` binds it to, and anywhere inside a string constant that is not a docstring,
    which covers `getattr(importlib, "import_module")` and a string annotation that
    `typing.get_type_hints` would evaluate; a `TEXT_RUNNERS` name by its bare name unless it
    resolves, by Python's scoping (`astscan.shadowed`), to a binding that hides it
    (`astscan.scope_bindings`: a function's local or parameter, a comprehension's variable, or an
    import from any module but `builtins`), by any name `from builtins import` binds it to (`from`
    any module, for `__builtins__`, which is also read as an attribute of anything), as a whole
    string constant, which is how `getattr(builtins, "exec")` spells it, and as a binding that
    lands in a module or a class body (`exec = exec`, `del exec`, `def breakpoint`, a walrus in a
    module-level comprehension), which Python looks up at run time. The `from` statement itself is
    a row: of any module for a `DYNAMIC_IMPORTS` name or `__builtins__`, of `builtins` for another
    `TEXT_RUNNERS` one, and `from importlib import *`. A docstring, or any string standing alone as
    a statement, is prose and is not read (`astscan.walk`).
    """

    def binds(node: ast.ImportFrom, names: frozenset[str]) -> list[ast.alias]:
        if names is TEXT_RUNNERS and node.module != "builtins":
            return [alias for alias in node.names if alias.name == "__builtins__"]
        return [alias for alias in node.names if alias.name in names]

    bound = set(DYNAMIC_IMPORTS) | {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for names in (DYNAMIC_IMPORTS, TEXT_RUNNERS)
        for alias in binds(node, names)
    }
    walrus = {id(node.target) for node in ast.walk(tree) if isinstance(node, ast.NamedExpr)}
    found: list[tuple[str, str]] = []

    for child, function, chain in astscan.walk(tree):
        if isinstance(child, ast.Attribute) and (
            child.attr in DYNAMIC_IMPORTS or child.attr == "__builtins__"
        ):
            found.append((function, child.attr))
        elif isinstance(child, ast.Name) and (
            child.id in bound
            or (
                child.id in TEXT_RUNNERS
                and type(child.ctx) is ast.Load
                and not astscan.shadowed(child.id, chain)
            )
        ):
            found.append((function, child.id))
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            if child.value in TEXT_RUNNERS:
                found.append((function, child.value))
            found.extend(
                (function, name) for name in sorted(DYNAMIC_IMPORTS) if name in child.value
            )
        elif isinstance(child, ast.ImportFrom) and (
            binds(child, DYNAMIC_IMPORTS)
            or binds(child, TEXT_RUNNERS)
            or (child.module == "importlib" and any(a.name == "*" for a in child.names))
        ):
            found.append((function, f"from {child.module} import"))
        elif (
            (binding := astscan.bound_name(child)) is not None
            and binding in TEXT_RUNNERS
            and astscan.binds_at_run_time(binding, chain, walrus=id(child) in walrus)
        ):
            found.append((function, binding))
    return found


def test_no_core_module_imports_by_a_string_but_discovery() -> None:
    # The delivery rule reads import statements, so a function-level
    # `importlib.import_module("stayfixed.memory.store")` or `__import__(...)` in a core file
    # crossed into the private layer with every boundary test green. A string import is
    # discovery's alone, and the one other one — profile discovery — is pinned with its reason.
    # So were a module's own loader (`type(__spec__.loader)(name, path).exec_module(module)`), a
    # finder on `sys.meta_path`, and `exec` of a string that imports. This reads those names; the
    # standard library's other ways to import by a string are held where they must be imported
    # from, by `test_no_core_module_reaches_the_import_machinery_…`. Both read every module, the
    # two sides' as well as the core's, since the import rules hold all three and a string would
    # walk around any of them.
    #
    # Mutations (declared): `mutations/`'s "a core function imports the note store through
    # importlib", "a core function imports the note store through __import__", "a core function
    # imports the note store through an alias of import_module", "a core function loads the note
    # store through its own module's loader", "a core function loads the note store through a
    # finder on sys.meta_path", "a core function imports the note store by running text", "a core
    # function reaches __import__ through __builtins__" and "a core function's string annotation
    # imports the note store".
    source = ROOT / "src" / "stayfixed"
    rows: list[tuple[str, str, str]] = []
    discovery: list[tuple[str, str]] = []
    for path in sorted(source.rglob("*.py")):
        where = path.relative_to(source).as_posix()
        found = _dynamic_imports(ast.parse(path.read_text(encoding="utf-8")))
        if where == DISCOVERY_MODULE:
            discovery += found
        else:
            rows += [(where, function, name) for function, name in found]
    # Discovery's exemption is its two `importlib.import_module` calls and nothing else, so an
    # `exec` or a `sys.meta_path` read in `areas.py` is caught like one anywhere else, and a reader
    # that stopped seeing the spelling the pardon is written in cannot pass by finding nothing.
    assert Counter(discovery) == Counter(DISCOVERY_READS), discovery
    found_rows, pinned = Counter(rows), Counter(DYNAMIC_IMPORTERS)
    assert found_rows == pinned, {"unpinned": found_rows - pinned, "gone": pinned - found_rows}


def test_the_string_import_rules_read_every_spelling() -> None:
    # The walk above can only show the rule holding for the spellings the tree carries, so it is
    # put in front of the ones it does not. Measured by hand: reading `from importlib import`
    # aliases no more reddens the first assertion, and dropping the string-constant arm the
    # second. In `texts`, dropping the attribute arm of `_dynamic_imports`, any one of its names,
    # the bare reading of `TEXT_RUNNERS`, their whole constant arm, the substring arm, reading
    # `from` statements of `importlib` alone, or reading `__builtins__` as no attribute or in a
    # `from` of `builtins` alone each reddens it. In `quiet`, reading docstrings, reading a
    # `TEXT_RUNNERS` `from` of any module, or reading a name the file binds itself (a local, a
    # parameter, an import) each reddens it. In `scoped`, hiding a builtin wherever the file binds
    # its name, letting a class body be seen by its methods, not following `global`, letting a
    # `global` alone hide the builtin, giving a comprehension no scope, binding no parameter,
    # reading a store as a use, or reading a function's annotations in its own scope each reddens
    # it. In `generic`, on 3.12 and later, leaving a function's or a class's type parameters
    # unread reddens it. The scoping is `tests/boundaries/astscan.py`'s, whose own cases hold it
    # too. Mutations (declared): `mutations/`'s "the name rule hides a builtin across the whole
    # file again", "a module or a class body hides a builtin by any binding again", "a binding of a
    # text runner in a module or a class body is no row", "a function's store of a text runner
    # under global is no row", "a walrus in a comprehension binds in the comprehension", "a walrus
    # target is taken to land in its comprehension", "import builtins under a text runner's name
    # hides the builtin", "a function's type parameters are not read", "a class's type parameters
    # are not read", "__builtins__ read off another module is no row" and "a from of __builtins__
    # out of another module is no row".
    aliased = "from importlib import import_module as load\ndef f():\n    load('x')\n"
    assert _dynamic_imports(ast.parse(aliased)) == [
        ("<module>", "from importlib import"),
        ("f", "load"),
    ]
    reflected = "import importlib\ndef f():\n    getattr(importlib, 'import_module')('x')\n"
    assert _dynamic_imports(ast.parse(reflected)) == [("f", "import_module")]
    texts = (
        "def f(x: \"__import__('stayfixed.memory.store')\"):\n    type(__spec__.loader)\n"
        "    sys.meta_path\n    m.__loader__\n    getattr(importlib, 'import_module')\n"
        "exec(text)\ngetattr(builtins, 'eval')\nfrom builtins import compile as c\nbreakpoint()\n"
        "__builtins__\nre.compile('x')\nfrom sys import path_hooks\nsys.path_importer_cache\n"
        "sys.breakpointhook(None, None)\nsys.__breakpointhook__\n"
        "json.__builtins__\nfrom re import __builtins__ as b\nb\n"
    )
    assert sorted(_dynamic_imports(ast.parse(texts))) == [
        ("<module>", "__breakpointhook__"),
        ("<module>", "__builtins__"),
        ("<module>", "__builtins__"),
        ("<module>", "__import__"),
        ("<module>", "b"),
        ("<module>", "breakpoint"),
        ("<module>", "breakpointhook"),
        ("<module>", "eval"),
        ("<module>", "exec"),
        ("<module>", "from builtins import"),
        ("<module>", "from re import"),
        ("<module>", "from sys import"),
        ("<module>", "path_importer_cache"),
        ("f", "__loader__"),
        ("f", "__spec__"),
        ("f", "import_module"),
        ("f", "meta_path"),
    ]
    # Prose and a name of the file's own are not the builtin: a docstring naming a finder, a
    # `compile` imported from another module under its name or an alias, and a parameter or a
    # local named after a builtin that runs text.
    quiet = (
        '"""Names no finder on sys.meta_path."""\n'
        "from re import compile as _c\n_R = _c('x')\nfrom re import compile\ncompile('y')\n"
        "def f(eval):\n    exec = 1\n    return eval, exec\n"
    )
    assert _dynamic_imports(ast.parse(quiet)) == []
    # A function's binding hides a builtin in that function and the scopes it encloses, never
    # beyond: the builtin read in another function, beside a comprehension's variable, in a method
    # beside a class attribute, or after another function's `global` names it, is still the
    # builtin, while a nested function reading its enclosing function's parameter, and a function
    # reading what a walrus in its comprehension bound, read the file's own. A binding that lands
    # in a module or a class body is a row of its own and hides nothing, since Python looks it up
    # at run time: a class attribute, a store under `global`, `__builtins__ = {}`, `exec = exec`
    # and a walrus in a module-level comprehension. `import builtins` under the name hides nothing.
    scoped = (
        "def g(exec):\n    return exec\nexec('x')\n"
        "_ = [0 for eval in ()]\ndef h():\n    return eval('x')\n"
        "class K:\n    compile = len\n    def m(self):\n        return compile('x')\n"
        "def r():\n    global breakpoint\n    breakpoint = print\ndef s():\n    breakpoint()\n"
        "def outer(compile):\n    def inner():\n        return compile\n    return inner\n"
        "__builtins__ = {}\ndef t():\n    return __builtins__\n"
        "def u(exec):\n    def v():\n        global exec\n        return exec('x')\n    return v\n"
        "exec = exec\n_ = [(eval := e) for e in ()]\n"
        "def w():\n    _ = [(compile := c) for c in ()]\n    return compile('x')\n"
        "import builtins as breakpoint\nbreakpoint.exec('x')\n"
    )
    assert sorted(_dynamic_imports(ast.parse(scoped))) == [
        ("<module>", "__builtins__"),
        ("<module>", "breakpoint"),
        ("<module>", "compile"),
        ("<module>", "eval"),
        ("<module>", "exec"),
        ("<module>", "exec"),
        ("<module>", "exec"),
        ("h", "eval"),
        ("m", "compile"),
        ("r", "breakpoint"),
        ("s", "breakpoint"),
        ("t", "__builtins__"),
        ("v", "exec"),
    ]
    # Type parameters are evaluated around the `def` or `class` they belong to. The syntax is
    # 3.12's, so this case is parsed from text there and has nothing to read on 3.11.
    if sys.version_info >= (3, 12):
        generic = "def f[T: exec('x')]():\n    pass\nclass C[T: __import__('x')]:\n    pass\n"
        assert _dynamic_imports(ast.parse(generic)) == [
            ("<module>", "exec"),
            ("<module>", "__import__"),
        ]


# The standard library modules a module may import with no row, by name or as a package whose
# submodules are all allowed: each one whose public functions import no module named by a string
# and run no code built from text but through a name the rule above reads (`sys.breakpointhook`,
# `typing.get_type_hints` of a string spelling `__import__`). Every other module is the machinery:
# an import of one is a row of `MACHINERY_IMPORTERS` below, with what the file reaches in it.
# Read the other way round, a deny-list of the modules that can import by a string stayed open to
# every one nobody had measured yet (`timeit`, `xml.dom.pulldom`'s `xml.sax`, `inspect`'s
# `importlib`, `builtins`). `importlib` and `pkgutil` are not on the list: discovery imports through
# them, and their rows say what each file reaches. `urllib` is listed as `urllib.parse`: an import
# of any other submodule of it is a row, while a read off the `urllib` that `import urllib.parse`
# binds is not judged, since no read off an allowed import is (an attribute chain, below).
#
# This rule and the name rule above are a tripwire, not a proof: they read import statements and a
# list of names, so they catch a crossing written the ordinary way and prove nothing about one
# written to hide. What they cannot read: an attribute chain through an allowed module
# (`dataclasses.inspect.importlib`, `typing.sys.modules`), a module already in `sys.modules`, a
# loader or a finder reached by a computed name (`getattr(sys, "meta" + "_path")`), an import in a
# module or a class body that fails and is caught, which hides a builtin the name rule then takes
# for the file's own, code built from text at run time, and a string an allowed module evaluates
# (`typing.get_type_hints` of an annotation built at run time).
# `test_in_isolation_no_core_module_loads_either_side` sees what loads at import time and nothing
# a function does later.
STANDARD_IMPORTS = frozenset(
    {
        "__future__",
        "argparse",
        "collections",
        "configparser",
        "contextlib",
        "copy",
        "dataclasses",
        "datetime",
        "enum",
        "errno",
        "fcntl",
        "functools",
        "hashlib",
        "io",
        "itertools",
        "json",
        "os",
        "pathlib",
        "posixpath",
        "pwd",
        "re",
        # `prove` waits for its command's report on standard output without blocking forever
        # (`selectors`) and copies it in a thread of its own while the command runs
        # (`threading`); neither imports a module by a name.
        "selectors",
        # `binding` draws the binding id (`secrets.token_hex`), which imports no module by a name.
        "secrets",
        "shlex",
        "shutil",
        "signal",
        # `sync` reads pre-commit's database, a SQLite file, read-only; `sqlite3` imports no module
        # by a name.
        "sqlite3",
        "stat",
        "string",
        "struct",
        "subprocess",
        "sys",
        "tempfile",
        "threading",
        "time",
        "tomllib",
        "types",
        "typing",
        "unicodedata",
        "urllib.parse",
        "xml.parsers.expat",
    }
)
# `importlib.resources` reads package data, and imports a module only as the anchor `files` is
# handed: given a module's name, it imports that module. So it is outside the rule for exactly two
# reads, which import nothing that is not already loaded. One is `files` called on the package
# itself, `__package__` (a module's own package) or the literal `"stayfixed"`, in a module
# that never binds `__package__` itself. The other is `importlib.resources.abc`, which holds types.
# Every other read of it, the same function given any other argument, the module handed on and the
# functions that take an anchor of their own (`read_text`, `open_binary` …), is the machinery.
RESOURCES = "importlib.resources"

# Every import of a module off `STANDARD_IMPORTS`, one row per statement: the file relative
# to `src/stayfixed/`, the module the statement names, and what the file reaches through it -- the
# names a `from` statement takes, or each attribute path read off the name an `import` binds
# (`<value>` when the name itself is handed on, where anything could be read off it). Held as a
# multiset and by equality in both directions, as `DYNAMIC_IMPORTERS` is.
MACHINERY_IMPORTERS = (
    # Discovery: imports `stayfixed.<area>.<submodule>` by name, and lists the areas.
    ("areas.py", "importlib", frozenset({"import_module"})),
    ("areas.py", "pkgutil", frozenset({"iter_modules"})),
    # Stack discovery: imports `stayfixed.profiles.<name>.<module>`, pinned in `DYNAMIC_IMPORTERS`.
    ("profiles/__init__.py", "importlib", frozenset({"import_module"})),
    # Reads the running interpreter's bytecode magic, the first four bytes of every `.pyc` it would
    # open; it imports nothing.
    ("profiles/python/hygiene.py", "importlib.util", frozenset({"util.MAGIC_NUMBER"})),
    # `prove`'s tee decodes a report on standard output across reads for a caller's stream that
    # takes text alone: the codec of the literal "utf-8", the interpreter's own and already
    # loaded, so the lookup imports nothing.
    ("prove/run.py", "codecs", frozenset({"getincrementaldecoder"})),
)


def _attribute_path(node: ast.AST, parents: dict[int, ast.AST]) -> tuple[str, ast.AST]:
    """The dotted attributes read off the name `node`, outermost last (`util.MAGIC_NUMBER` for
    `importlib.util.MAGIC_NUMBER`), or `<value>` when the name is used as anything but the root
    of an attribute read; and the outermost node of that read, which a call would be made on."""
    path: list[str] = []
    while isinstance(parent := parents.get(id(node)), ast.Attribute) and parent.value is node:
        path.append(parent.attr)
        node = parent
    return ".".join(path) or "<value>", node


def _within(module: str, listed: Iterable[str]) -> bool:
    return any(module == entry or module.startswith(f"{entry}.") for entry in listed)


def _reads_data(dotted: str, node: ast.AST, parents: dict[int, ast.AST], rebound: bool) -> bool:
    """Whether reading `dotted` at `node` is one of the two reads of `RESOURCES` that import
    nothing: anything in its `abc`, or a call of its `files` with one positional argument, the
    literal `"stayfixed"` or `__package__` in a module that never binds it (`rebound`)."""
    if _within(dotted, {f"{RESOURCES}.abc"}):
        return True
    call = parents.get(id(node))
    if dotted != f"{RESOURCES}.files" or not isinstance(call, ast.Call) or call.func is not node:
        return False
    if call.keywords or len(call.args) != 1:
        return False
    (anchor,) = call.args
    if isinstance(anchor, ast.Name):
        return anchor.id == "__package__" and not rebound
    return isinstance(anchor, ast.Constant) and anchor.value == "stayfixed"


def _machinery_imports(tree: ast.AST) -> list[tuple[str, frozenset[str]]]:
    """Every statement in `tree` that imports a module neither `stayfixed`'s own nor on
    `STANDARD_IMPORTS`, as `(module, reach)`: for `from m import a, b` the names taken that are not
    allowed modules themselves (`from urllib import parse` takes none), for `import m.n [as x]`
    every attribute path read off the name it binds, anywhere in the file. A `RESOURCES` name,
    and an `import` of it, counts only for its reads `_reads_data` does not pass, and is no row
    when that leaves none."""
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    # A module that binds `__package__` itself can point it at any module at all.
    rebound = any(
        (isinstance(node, ast.Name) and node.id == "__package__" and type(node.ctx) is not ast.Load)
        or (isinstance(node, ast.arg) and node.arg == "__package__")
        for node in ast.walk(tree)
    )

    def reached(bound: str, dotted: str) -> set[str]:
        """The reads off the name `bound`, which stands for `dotted`, past what imports nothing."""
        paths: set[str] = set()
        for name in ast.walk(tree):
            if isinstance(name, ast.Name) and name.id == bound:
                path, outer = _attribute_path(name, parents)
                full = dotted if path == "<value>" else f"{dotted}.{path}"
                if not _reads_data(full, outer, parents, rebound):
                    paths.add(path)
        return paths

    def allowed(module: str) -> bool:
        return module.split(".")[0] == "stayfixed" or _within(module, STANDARD_IMPORTS)

    found: list[tuple[str, frozenset[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names: set[str] = set()
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                if allowed(node.module) or allowed(dotted):
                    continue
                data = alias.name != "*" and _within(dotted, {RESOURCES})
                if data and not reached(alias.asname or alias.name, dotted):
                    continue
                names.add(alias.name)
            if names:
                found.append((node.module, frozenset(names)))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # An allowed import is no row, and nothing read off the name it binds is judged:
                # `import urllib.parse` binds `urllib`, and `urllib.request` read off it passes.
                if allowed(alias.name):
                    continue
                bound = alias.asname or alias.name.split(".")[0]
                dotted = alias.name if alias.asname else bound
                reach = reached(bound, dotted)
                if reach or not _within(alias.name, {RESOURCES}):
                    found.append((alias.name, frozenset(reach)))
    return found


def test_no_core_module_reaches_the_import_machinery_but_where_pinned() -> None:
    # The rule above reads a list of names, and `pkgutil.resolve_name("stayfixed.memory.store")`,
    # `importlib.util.find_spec` and a loader's `exec_module`, `importlib.resources.files` handed
    # the store's name, `pydoc.locate`, `pickle.loads`, `logging.config`'s resolver, `timeit` and
    # `xml.sax.make_parser` each crossed into the private layer from a core function with every
    # boundary test green. So every module, on either side or in the core, imports the standard
    # library from `STANDARD_IMPORTS` alone, and any other import is pinned with what it reaches: a
    # new importer is a new row, and a pinned importer reaching one more name changes its row.
    # `importlib.resources` is no row while it only reads the package's own data. What this cannot
    # see is in the comment over `STANDARD_IMPORTS`: it is a tripwire, not a proof.
    #
    # Mutations (declared): `mutations/`'s "a core function imports the note store through
    # pkgutil.resolve_name", "profile discovery reaches importlib.util as well", "a core function
    # opens the note store's resources by its module name", "a core function opens the note
    # store's resources through files imported by name", "a core function imports the note store
    # through pydoc.locate", "a core function unpickles a reference to the note store", "a core
    # function loads code through marshal", "a core function resolves the note store through
    # logging.config", "a core function runs an import through timeit", "a core function reaches
    # xml.sax through a sibling submodule's import" and "a core function takes __import__ from
    # builtins by a computed name".
    source = ROOT / "src" / "stayfixed"
    rows = [
        (path.relative_to(source).as_posix(), module, reach)
        for path in sorted(source.rglob("*.py"))
        for module, reach in _machinery_imports(ast.parse(path.read_text(encoding="utf-8")))
    ]
    found_rows, pinned = Counter(rows), Counter(MACHINERY_IMPORTERS)
    assert found_rows == pinned, {"unpinned": found_rows - pinned, "gone": pinned - found_rows}
    # Every module is held to the standard library (`tests/boundaries/test_layering.py`), and here
    # to the part of it listed, so the list may name nothing outside it: a listed module
    # the runtime may not import would admit here what the layer below refuses. Mutation
    # (declared): `mutations/`'s "the core's import list admits a module outside the standard
    # library" -> this reddens.
    outside = {
        name for name in STANDARD_IMPORTS if name.split(".")[0] not in sys.stdlib_module_names
    }
    assert outside == set(), outside


def test_the_machinery_rule_reads_every_spelling() -> None:
    # The walk above can show the rule holding only for the spellings the tree carries, so it is
    # put in front of the ones it does not: a `from` import of a submodule, an aliased `import`,
    # the name handed on as a value, and `importlib.resources` read for the package's own data in
    # each spelling left alone, though not what is read off the `importlib` its `import` binds.
    # Measured by hand: dropping the `RESOURCES` check of the `from` arm of `_machinery_imports`,
    # the `<value>` fallback, or `_reads_data`'s `files` arm each reddens it.
    spellings = (
        "from importlib import resources\nfrom importlib.resources.abc import Traversable\n"
        "import importlib.resources\nimportlib.resources.files(__package__)\n"
        "importlib.import_module('x')\nfrom importlib import resources, util\n"
        "from importlib.util import find_spec\nimport pkgutil as p\np.resolve_name('x')\n"
        "import runpy\nf(runpy)\nrunpy.run_module('x')\n"
    )
    assert sorted(_machinery_imports(ast.parse(spellings)), key=str) == sorted(
        [
            ("importlib.resources", frozenset({"import_module"})),
            ("importlib", frozenset({"util"})),
            ("importlib.util", frozenset({"find_spec"})),
            ("pkgutil", frozenset({"resolve_name"})),
            ("runpy", frozenset({"<value>", "run_module"})),
        ],
        key=str,
    )


@pytest.mark.parametrize(
    ("source", "rows"),
    [
        pytest.param(
            "from importlib import resources\nresources.files(__package__).joinpath('x')\n"
            "resources.files('stayfixed')\n",
            [],
            id="files-on-the-package",
        ),
        pytest.param(
            "import importlib.resources\nimport importlib.resources as r\n"
            "importlib.resources.files(__package__)\nr.files('stayfixed')\n",
            [],
            id="files-on-the-package-through-import",
        ),
        pytest.param(
            "from importlib.resources.abc import Traversable\nx: Traversable\n", [], id="abc"
        ),
        pytest.param(
            "from importlib import resources\nresources.files('stayfixed.memory.store')\n",
            [("importlib", frozenset({"resources"}))],
            id="files-on-a-module-name",
        ),
        pytest.param(
            "import importlib.resources\nimportlib.resources.files(name)\n",
            [("importlib.resources", frozenset({"resources.files"}))],
            id="files-on-a-computed-name",
        ),
        pytest.param(
            "import importlib.resources as r\nr.files(anchor=__package__)\n",
            [("importlib.resources", frozenset({"files"}))],
            id="files-by-keyword",
        ),
        pytest.param(
            "from importlib.resources import files\nfiles('stayfixed.memory.store')\n",
            [("importlib.resources", frozenset({"files"}))],
            id="files-imported-by-name",
        ),
        pytest.param(
            "from importlib import resources\nresources.read_text(__package__, 'x')\n",
            [("importlib", frozenset({"resources"}))],
            id="an-anchor-of-its-own",
        ),
        pytest.param(
            "from importlib import resources\nload(resources)\n",
            [("importlib", frozenset({"resources"}))],
            id="handed-on",
        ),
        pytest.param(
            "from importlib import resources\n__package__ = 'stayfixed.memory.store'\n"
            "resources.files(__package__)\n",
            [("importlib", frozenset({"resources"}))],
            id="package-rebound",
        ),
        pytest.param(
            "from importlib import resources\ndef f(__package__):\n"
            "    return resources.files(__package__)\n",
            [("importlib", frozenset({"resources"}))],
            id="package-a-parameter",
        ),
        pytest.param(
            "import pydoc\npydoc.locate('x')\n", [("pydoc", frozenset({"locate"}))], id="pydoc"
        ),
        pytest.param(
            "from pickle import loads as load\n", [("pickle", frozenset({"loads"}))], id="pickle"
        ),
        pytest.param(
            "import marshal as m\nm.loads(data)\n",
            [("marshal", frozenset({"loads"}))],
            id="marshal",
        ),
        pytest.param(
            "import logging.config\nlogging.config.dictConfig({})\n",
            [("logging.config", frozenset({"config.dictConfig"}))],
            id="logging-config",
        ),
        pytest.param(
            "from logging import config, getLogger\n",
            [("logging", frozenset({"config", "getLogger"}))],
            id="logging-off-the-list",
        ),
        pytest.param(
            "from multiprocessing.reduction import ForkingPickler\n",
            [("multiprocessing.reduction", frozenset({"ForkingPickler"}))],
            id="a-submodule-off-the-list",
        ),
        pytest.param(
            "import xml.dom.pulldom\nxml.sax.make_parser(['x'])\n",
            [("xml.dom.pulldom", frozenset({"sax.make_parser"}))],
            id="a-sibling-read-off-the-package-an-import-binds",
        ),
        pytest.param(
            "from xml.dom import pulldom\n", [("xml.dom", frozenset({"pulldom"}))], id="xml-dom"
        ),
        pytest.param(
            "import timeit\ntimeit.timeit('x')\n", [("timeit", frozenset({"timeit"}))], id="timeit"
        ),
        pytest.param(
            "import builtins\ngetattr(builtins, name)\n",
            [("builtins", frozenset({"<value>"}))],
            id="builtins",
        ),
        pytest.param(
            "import inspect\ninspect.importlib\n",
            [("inspect", frozenset({"importlib"}))],
            id="inspect",
        ),
        pytest.param(
            "import os.path\nfrom collections.abc import Mapping\nimport urllib.parse\n"
            "from urllib import parse\nfrom os import path\nimport stayfixed.areas\n"
            "from . import sibling\n",
            [],
            id="on-the-list-or-our-own",
        ),
        pytest.param(
            "from urllib import parse, request\nimport urllib.request\n",
            [("urllib", frozenset({"request"})), ("urllib.request", frozenset())],
            id="a-package-allowed-in-part",
        ),
    ],
)
def test_the_machinery_rule_reads_resources_by_its_anchor_and_every_other_module(
    source: str, rows: list[tuple[str, frozenset[str]]]
) -> None:
    # `importlib.resources.files` imports the anchor it is handed when that names a module, so
    # it is data only on the package itself, and every other read of `importlib.resources` is a
    # row. Every module off `STANDARD_IMPORTS` is a row, a submodule of an allowed package
    # included, and nothing on it is. Measured by hand: dropping the `rebound` check, the keyword
    # check, the `abc` arm, the `RESOURCES` check of the `import` arm, the `allowed` check of
    # either statement, the dotted name's own check in the `from` arm, the `stayfixed` exemption,
    # or reading the list by top-level name each reddens a case.
    assert _machinery_imports(ast.parse(source)) == rows
