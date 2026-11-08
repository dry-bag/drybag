"""The three checks every `api.py` is held to, asked once of every package that publishes one:
each area with a surface, and the `release` and `trust` packages, which are not areas and are
held to their surfaces like one.

CONTRIBUTING states the contract once for all of them: "`api.py` is the area's import surface.
Other areas import from it and from nothing else, and its `__all__` must equal exactly what it
imports — a test parses the file and checks." Nine modules each carried a copy of that parse,
eight of them byte-identical; six carried a copy of the derived signature check and four did
not; and `stayfixed.hooks.api` had no surface test at all, because a contract enforced by ten
hand-written copies is enforced only where somebody remembered to write the eleventh.

What stays in `tests/<area>/test_surface.py` is the one thing that is genuinely the area's own:
the list of names it publishes, with the argument for each beside it. That list is a decision
per area. These three checks are not.

`stayfixed.scaffold` is not here. It publishes from the package rather than from an `api.py` —
the scaffold engine's contract, frozen — and `tests/scaffold/test_surface.py` holds it to its
own shape.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import typing
from pathlib import Path
from types import ModuleType

import pytest

from stayfixed.config.schema import Config
from stayfixed.config.session import SessionConfig

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "stayfixed"

# Every package with an `api.py`: the areas that publish one and the `release` and `trust`
# packages, which are not areas; `AREAS` and the parameter `area` are named for the ten that are.
# Derived from the tree rather than listed, so an area added tomorrow is covered the day it
# arrives — which is the whole of what went wrong with `hooks`.
AREAS = sorted(path.parent.name for path in SOURCE.glob("*/api.py"))

# The one area whose `api.py` **defines** rather than re-exports, named rather than skipped silently
# — for `tests/boundaries/test_api_surface.py`'s stated reason, that an exemption nobody can see is
# how the violation a guard exists to catch gets merged green. `stayfixed.hooks.api`'s own docstring
# argues it and CONTRIBUTING records it: the handler vocabulary is what `registry`, `dispatch`,
# `sink` and every area's `hooks.py` import, so re-exporting a name defined in one of those would be
# an import cycle. The back-door half of the rule still applies to it in full.
DEFINES_ITS_OWN = frozenset({"hooks"})

# The names an area's modules import only under `if TYPE_CHECKING:`, so that an annotation
# naming one can still be resolved here. Supplied rather than tolerated: a further such name
# fails the check below by name, which is a decision to record and not a hint to drop. Without
# this the check errored with a bare `NameError` on four of the ten areas — accidental redness,
# which reads as coverage and is the shape this suite exists to refuse.
TYPE_CHECKING_NAMES: dict[str, object] = {
    "Config": Config,
    "Path": Path,
    # `HandlerFn`'s second argument: the hooks surface names the session it hands a handler, and
    # imports it only for annotations, since discovery must not load the configuration layer.
    "SessionConfig": SessionConfig,
}


def _hints(thing: object) -> dict[str, object]:
    try:
        return typing.get_type_hints(thing, localns=TYPE_CHECKING_NAMES)
    except NameError as exc:
        raise AssertionError(
            f"{getattr(thing, '__module__', '?')}.{getattr(thing, '__qualname__', thing)}: "
            f"an annotation names something this check cannot resolve ({exc}). "
            "Add it to TYPE_CHECKING_NAMES with the reason it is not importable at runtime."
        ) from exc


def _defined_here(tree: ast.AST) -> set[str]:
    """Module-level names an `api.py` defines itself, rather than re-exporting."""
    names: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names - {"__all__"}


def test_every_package_with_a_surface_is_walked() -> None:
    # The floor for the three parametrisations below: a `glob` that stopped matching would turn
    # all three into zero test cases, and a suite that collects nothing reports nothing. Pinned
    # to the exact twelve — ten areas and the `release` and `trust` packages — because a
    # package gaining or losing a published surface is a decision.
    assert AREAS == [
        "attach",
        "docs",
        "doctor",
        "guards",
        "hooks",
        "memory",
        "overlay",
        "project",
        "release",
        "setup",
        "trust",
    ], AREAS


def _surface(area: str) -> ModuleType:
    return importlib.import_module(f"stayfixed.{area}.api")


@pytest.mark.parametrize("area", AREAS)
def test_the_export_list_is_exactly_what_the_module_imports_from_its_area(area: str) -> None:
    # `assert getattr(surface, name) is not None` was the whole of this check in the first
    # module that had one, and every attribute a module actually has is not None — it could not
    # fail for any `__all__` the module is able to import. What the contract needs asserting is
    # the three ways the list and the imports come apart: a name in `__all__` with no import
    # behind it is an `AttributeError` at the consumer, an import with no `__all__` entry is a
    # name the contract does not really offer (and `from ... import *` will not hand over), and
    # an import from outside the area would quietly make this module a back door into another.
    surface = _surface(area)
    imported: set[str] = set()
    tree = ast.parse(Path(surface.__file__ or "").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Import), "the surface re-exports, it does not import"
        if not isinstance(node, ast.ImportFrom) or node.module == "__future__":
            continue
        assert node.module is not None
        # The back-door half, and it holds for every area including the one that defines its own: a
        # surface that reached into another area would make this module a way past that area's
        # `api.py` with none of the crossings `tests/boundaries/test_api_surface.py` counts. Scoped
        # to the other areas and not to every `stayfixed.` name, for that walk's own reason — the
        # configuration layer and the leaves are not areas, and `stayfixed.hooks.api` names
        # `stayfixed.config.session.SessionConfig` in `HandlerFn` because that is the handler
        # signature.
        parts = node.module.split(".")
        elsewhere = parts[0] == "stayfixed" and parts[1:2] and parts[1] in set(AREAS) - {area}
        assert not elsewhere, node.module
        if node.module.startswith(f"stayfixed.{area}."):
            imported |= {alias.asname or alias.name for alias in node.names}
    defined = _defined_here(tree) if area in DEFINES_ITS_OWN else set()
    if area not in DEFINES_ITS_OWN:
        # Spelled as its own assertion so the failure says which it is: a surface that grew a
        # definition has changed kind, and that is a decision for `DEFINES_ITS_OWN`.
        assert not _defined_here(tree), f"{area}/api.py defines rather than re-exports"
    assert imported | defined == set(surface.__all__)
    for name in surface.__all__:
        assert hasattr(surface, name)


@pytest.mark.parametrize("area", AREAS)
def test_every_type_the_surface_names_in_a_signature_is_on_the_surface(area: str) -> None:
    # Derived rather than restated. The two lists the check above compares cannot catch a name
    # nobody added to either side: one is a list a person maintains, and the other compares the
    # module against itself. `memory.link` was given a `Links` return type by the commit that
    # taught it to withdraw the harness link, and neither half noticed — leaving `attach`, the
    # area that binds and links, able to hold the value and unable to declare it, which is the
    # one thing a surface exists to prevent.
    #
    # Only in a *signature*: `raise` is not one, so a class reachable only by writing it down —
    # `scaffold`'s three — stays on the area's own
    # list with the argument for it, and is not derived here.
    surface = _surface(area)

    def area_types(annotation: object) -> set[str]:
        found: set[str] = set()
        if isinstance(annotation, type) and annotation.__module__.startswith(f"stayfixed.{area}"):
            found.add(annotation.__name__)
        for argument in typing.get_args(annotation):
            found |= area_types(argument)
        return found

    exported = set(surface.__all__)
    missing: dict[str, set[str]] = {}
    examined: list[str] = []
    for name in sorted(exported):
        thing = getattr(surface, name)
        is_record = isinstance(thing, type) and dataclasses.is_dataclass(thing)
        if not (inspect.isfunction(thing) or is_record):
            continue
        examined.append(name)
        named: set[str] = set()
        for hint in _hints(thing).values():
            named |= area_types(hint)
        if named - exported:
            missing[name] = named - exported
    # The walk states it is non-empty first: a surface whose callables all stopped being
    # callables would otherwise leave `missing` empty and this green while checking nothing.
    # `tests/memory/test_surface.py`'s copy was the one without this line.
    assert examined, f"{area}: the surface exports no function or record, so this checked nothing"
    assert not missing, f"{area}: named by the surface and absent from it: {missing}"


@pytest.mark.parametrize("area", AREAS)
def test_the_surface_is_a_module_not_the_package_init(area: str) -> None:
    # Measured: with the re-export list in `__init__.py`, `discover()` imports the whole area —
    # configuration layer included — on every call, because area discovery imports a package
    # before it imports the submodule it wants, and `tests/boundaries/test_discovery.py` goes red.
    package = importlib.import_module(f"stayfixed.{area}")
    init = Path(next(iter(package.__path__))) / "__init__.py"
    tree = ast.parse(init.read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]
