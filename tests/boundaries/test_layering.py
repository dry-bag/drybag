"""Layering: what each layer of the runtime may import. The runtime imports nothing but the
standard library and itself, a leaf nothing of stayfixed, and the packages and the modules under
`src/stayfixed/` import one another without a cycle."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from tests.boundaries import astscan

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "stayfixed"


def test_runtime_modules_import_only_the_standard_library() -> None:
    # Hooks run under whatever python3 the wrapper finds, before any environment exists, so a
    # third-party import works on the developer's machine and fails inside a hook on the next one.
    # `sys.stdlib_module_names` belongs to the running interpreter, which is why CI runs this on
    # every supported version. A module named in a string is the delivery rule's
    # (`tests/boundaries/test_delivery.py`), which also holds every module to `STANDARD_IMPORTS`, a
    # part of what this allows. Mutation: none of the code's; watched red by planting a function
    # that imports `yaml` in `src/stayfixed/tomlout.py`.
    allowed = set(sys.stdlib_module_names) | {"stayfixed"}
    offenders: dict[str, list[str]] = {}
    walked: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC)
        walked.append(relative.as_posix())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = ("stayfixed", *relative.parts[:-1])
        roots = {module.split(".")[0] for _, module in astscan.imported_modules(tree, package)}
        if offending := sorted(roots - allowed):
            offenders[relative.as_posix()] = offending
    # The walk first: one that stopped finding files passes vacuously.
    assert "cli.py" in walked, walked
    assert offenders == {}


def test_the_runner_is_a_leaf_and_not_an_area() -> None:
    # `runner.py` is a leaf: it sits beside `fsops.py`, `gitenv.py` and `tomlout.py` and imports
    # nothing from `stayfixed` but `gitenv`, another leaf, whose environment its `git` is given.
    # Pinned as an import check rather than by walking the tree, because
    # the surface rule's walk treats a leaf as invisible on purpose. No mutation: adding a
    # stayfixed import to a leaf is a review finding the standard-library walk above does not
    # catch, and this is the one line that does.
    source = SRC / "runner.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    # The walk states it is non-empty first: an `imported` that came back empty — a parse that
    # found no imports at all, or a filter that stopped matching — satisfies the filter below
    # without reading a single name. `runner.py` imports five stdlib modules.
    assert imported
    assert not [n for n in imported if n.startswith("stayfixed") and n != "stayfixed.gitenv"]


def _package_imports(where: str, text: str, packages: frozenset[str]) -> set[tuple[str, str]]:
    """The package graph's edges one file gives: `(its package, a package it imports)` for every
    import statement that runs when the file is imported (`astscan.imports`), to a package out of
    `packages` other than its own. A package is a subpackage or a module directly under
    `src/stayfixed/`, named by its first path component."""
    parts = Path(where).parts
    importer = parts[0].removesuffix(".py")
    edges: set[tuple[str, str]] = set()
    for node in astscan.imports([ast.parse(text)], inside_functions=False):
        for _, module in astscan.imported_modules(node, ("stayfixed", *parts[:-1])):
            bits = module.split(".")
            if bits[0] == "stayfixed" and bits[1:2] and bits[1] in packages - {importer}:
                edges.add((importer, bits[1]))
    return edges


def _cycles(edges: set[tuple[str, str]]) -> list[list[str]]:
    """Every strongly connected component of more than one package, each sorted, in sorted
    order: the packages that import one another, directly or around a longer loop."""
    after: dict[str, set[str]] = {}
    for importer, imported in edges:
        after.setdefault(importer, set()).add(imported)

    def reachable(start: str) -> set[str]:
        seen: set[str] = set()
        pending = [start]
        while pending:
            for following in after.get(pending.pop(), set()) - seen:
                seen.add(following)
                pending.append(following)
        return seen

    reach = {package: reachable(package) for package in sorted(after)}
    components = {
        frozenset(
            {package} | {other for other in reach if package in reach[other] and other in found}
        )
        for package, found in reach.items()
    }
    return sorted(sorted(component) for component in components if len(component) > 1)


def test_the_packages_import_one_another_without_a_cycle_at_module_level() -> None:
    # Two package cycles stood in the tree: the session guard imported a stack's hint machinery
    # while that hint imported the guard's roots, and the configuration loader printed through
    # `findings`, which printed through `printed`, which read its grammar from the
    # configuration's schema. Neither failed an import, because each was entered from
    # one side only, so nothing said so until a review drew the graph.
    #
    # What is counted is an import that runs when its module is imported -- the same reading the
    # doctor rule makes (`tests/boundaries/test_discovery.py`): module level, a class body, a
    # `try`, a `with`, an `if` and the `else` of `if TYPE_CHECKING:`. What is not: an import
    # inside a function, which is how this codebase defers a load until a command asks for it
    # (every import of a discovered `hooks.py` and `doctor.py`), cannot leave a module
    # half-initialised, and is held where it crosses from one side to another by
    # `tests/boundaries/test_delivery.py`; and an `if TYPE_CHECKING:` body, which never runs and is
    # the idiom for naming a type from a package that depends on this one. The nodes are the
    # packages under `src/stayfixed/`, delivery areas included, and imports within one package are
    # not edges.
    #
    # Mutation (declared): `mutations/`'s "the path grammar reads the configuration's schema
    # again".
    packages = frozenset(
        path.name.removesuffix(".py")
        for path in SRC.iterdir()
        if path.suffix == ".py" or (path / "__init__.py").is_file()
    )
    edges: set[tuple[str, str]] = set()
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        edges |= _package_imports(relative, path.read_text(encoding="utf-8"), packages)
    # The walk reads the edges the second cycle was made of, so a reader that stopped finding
    # imports cannot pass by finding no cycle.
    assert {("config", "findings"), ("findings", "printed")} <= edges
    assert _cycles(edges) == []


def test_the_package_graph_reads_imports_that_run_and_finds_every_cycle() -> None:
    # The walk above can show the reading only for the spellings the tree carries. Measured by
    # hand: reading function bodies, reading `if TYPE_CHECKING:` bodies or dropping the
    # own-package filter each reddens the first assertion, and a `_cycles` that kept components
    # of one package, or read reachability one way only, reddens the second.
    packages = frozenset({"config", "findings", "guards", "printed", "ledger"})
    text = (
        "from stayfixed.findings import listed\n"
        "if TYPE_CHECKING:\n    from stayfixed.config.schema import Config\n"
        "else:\n    import stayfixed.printed\n"
        "def f():\n    from stayfixed.guards.api import contained_roots\n"
        "from . import sibling\nfrom stayfixed.ledger import scan\n"
        "from stayfixed import nothing_here\n"
    )
    assert _package_imports("ledger/check.py", text, packages) == {
        ("ledger", "findings"),
        ("ledger", "printed"),
    }
    edges = {("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"), ("d", "e"), ("e", "d"), ("f", "a")}
    assert _cycles(edges) == [["a", "b", "c"], ["d", "e"]]


def _packages_above(module: str) -> set[str]:
    """Every package a dotted name sits in: `a` and `a.b` for `a.b.c`."""
    bits = module.split(".")
    return {".".join(bits[:end]) for end in range(1, len(bits))}


def _module_imports(where: str, text: str, modules: frozenset[str]) -> set[tuple[str, str]]:
    """The module graph's edges one file gives: `(its module, a module it imports)` for every
    import statement in it that can run (`astscan.imports`), to a module out of `modules`
    other than itself. `from package import name` is an edge to the module `name` when there is
    one, and to the package's `__init__` either way, since Python runs it to look the name up.

    **And every import is an edge to each package above the module it names**, relative imports
    resolved first: `from stayfixed.scaffold.model import Template` runs `scaffold/__init__.py`
    before `scaffold/model.py`, so whatever that `__init__` imports is reached through it. Not the
    packages above the importer itself, which Python started before the importer ran and does not
    run again."""
    parts = Path(where).with_suffix("").parts
    importer = ".".join(("stayfixed", *(parts[:-1] if parts[-1] == "__init__" else parts)))
    package = ("stayfixed", *Path(where).parts[:-1])
    started = _packages_above(importer) | {importer}
    edges: set[tuple[str, str]] = set()
    for node in astscan.imports([ast.parse(text)], inside_functions=True):
        for _, module in astscan.imported_modules(node, package):
            for name in {module} | (_packages_above(module) - started):
                if name in modules and name != importer:
                    edges.add((importer, name))
    return edges


def test_the_modules_import_one_another_without_a_cycle_even_inside_functions() -> None:
    # The package graph above leaves out an import inside a function, which defers a load and
    # cannot leave a module half-initialised. It cannot leave a cycle out of the layering, though:
    # `attach --check` once lived in `permissions` and imported the ledger's reader from `write`
    # inside the function, while `write` imports `permissions` at module level. Nothing failed,
    # and the first change to hoist that import, the house style everywhere a load is not being
    # deferred, would have stopped every `attach` and `detach` at import. So the modules under
    # `src/stayfixed/` are a graph of their own here, every import that can run is an edge,
    # module level or inside a function alike, and only an `if TYPE_CHECKING:` body, which never
    # runs, is left out. No cycle is pinned: a new one is a layering to fix, not a row to add.
    #
    # Mutations (declared): `mutations/`'s "permissions reads the writer again inside a function"
    # and "printed reads the scaffold inside a function".
    files = {path.relative_to(SRC).as_posix(): path for path in sorted(SRC.rglob("*.py"))}
    modules = frozenset(
        ".".join(("stayfixed", *Path(where).with_suffix("").parts)).removesuffix(".__init__")
        for where in files
    )
    edges: set[tuple[str, str]] = set()
    for where, path in files.items():
        edges |= _module_imports(where, path.read_text(encoding="utf-8"), modules)
    # The walk reads an edge that runs only inside a function, and the edge that import makes to the
    # package above the module it names, so a reader that stopped finding either cannot pass by
    # finding no cycle.
    assert ("stayfixed.config.overlay_layers", "stayfixed.binding") in edges
    assert ("stayfixed.memory.doctor", "stayfixed.doctor") in edges
    assert _cycles(edges) == []


def test_the_module_graph_reads_imports_inside_functions_and_names_the_module_imported() -> None:
    # The walk above can show the reading only for the spellings the tree carries. Measured by
    # hand: skipping function bodies, reading `if TYPE_CHECKING:` bodies, dropping the edge to a
    # package's `__init__` or reading a relative import from the wrong package each reddens this.
    modules = frozenset(
        {
            "stayfixed.attach",
            "stayfixed.attach.permissions",
            "stayfixed.attach.write",
            "stayfixed.config.schema",
            "stayfixed.printed",
        }
    )
    text = (
        "from stayfixed.attach.write import ledger\n"
        "if TYPE_CHECKING:\n    from stayfixed.config.schema import Config\n"
        "def f():\n    from stayfixed.printed import quoted\n"
        "from . import permissions\n"
        "from stayfixed.attach import nothing_here\n"
    )
    assert _module_imports("attach/check.py", text, modules) == {
        ("stayfixed.attach.check", "stayfixed.attach"),
        ("stayfixed.attach.check", "stayfixed.attach.permissions"),
        ("stayfixed.attach.check", "stayfixed.attach.write"),
        ("stayfixed.attach.check", "stayfixed.printed"),
    }
    # A package's own `__init__` is named after the package, and imports nothing of itself.
    assert _module_imports("attach/__init__.py", "from . import write\n", modules) == {
        ("stayfixed.attach", "stayfixed.attach.write"),
    }


def test_the_module_graph_runs_every_package_above_the_module_imported() -> None:
    # Python runs a package's `__init__.py` before the submodule an import names, and the graph
    # once gave such an import no edge to it. A review planted one inside a function in
    # `gitenv.py`, through a package whose `__init__` reached `gitenv` again, so it closed a cycle,
    # and every cycle test above passed. Hoisted to module level, the same import stops the
    # importer on a partially initialised module. Mutations (declared): `mutations/`'s "the module
    # graph stops running the packages above the module imported", and "printed reads the
    # scaffold inside a function", the same shape in today's tree.
    modules = frozenset(
        {
            "stayfixed",
            "stayfixed.attach",
            "stayfixed.attach.write",
            "stayfixed.printed",
            "stayfixed.scaffold",
            "stayfixed.scaffold.engine",
            "stayfixed.scaffold.model",
        }
    )
    planted = (
        "def _probe():\n    from stayfixed.scaffold.model import Template\n    return Template\n"
    )
    assert _module_imports("printed.py", planted, modules) == {
        ("stayfixed.printed", "stayfixed.scaffold"),
        ("stayfixed.printed", "stayfixed.scaffold.model"),
    }
    edges = (
        _module_imports("printed.py", planted, modules)
        | _module_imports("scaffold/__init__.py", "from .engine import plan\n", modules)
        | _module_imports("scaffold/engine.py", "from stayfixed.printed import quoted\n", modules)
    )
    assert _cycles(edges) == [
        ["stayfixed.printed", "stayfixed.scaffold", "stayfixed.scaffold.engine"],
    ]
    # `import a.b.c` runs the same packages, and so does a relative import once resolved. The
    # packages above the importer itself are not edges: Python started them before it, and an
    # edge to each would put every package that imports its own submodules in a cycle.
    text = (
        "import stayfixed.scaffold.model\n"
        "from .write import ledger\n"
        "def f():\n    from ..scaffold.engine import plan\n"
    )
    assert _module_imports("attach/check.py", text, modules) == {
        ("stayfixed.attach.check", "stayfixed.attach.write"),
        ("stayfixed.attach.check", "stayfixed.scaffold"),
        ("stayfixed.attach.check", "stayfixed.scaffold.engine"),
        ("stayfixed.attach.check", "stayfixed.scaffold.model"),
    }
