"""The surface rule: a package that publishes an `api.py`, and every area, is reached from outside
it through that `api.py` alone, from `src/stayfixed/` and from `scripts/`."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from tests.boundaries import astscan
from tests.boundaries.test_discovery import area_names

ROOT = Path(__file__).resolve().parents[2]


def _ruled_packages(source: Path) -> list[str]:
    """Every subpackage the import rule holds: each area, and each package that publishes an
    `api.py` whether or not anything discovers it.

    Discovery is how the CLI finds a command; the rule is about the surface. A package with an
    `api.py` and no `commands.py` (`release`) is held to that surface all the same, and an area
    with no `api.py` (`assess`) publishes nothing, so nothing outside it may import any of its
    modules."""
    surfaces = {path.parent.name for path in source.glob("*/api.py")}
    return sorted(set(area_names(source)) | surfaces)


def _boundary_offences(where: str, text: str, ruled: Sequence[str]) -> tuple[list[str], list[str]]:
    """The rule, for one file: the imports it makes into a `ruled` package other than its own, and
    the ones that break it. `ruled` is every package the surface rule holds — each area, and each
    package that publishes an `api.py`.

    A function rather than a loop body, so the test below can put a spelling in front of it that
    `src/stayfixed/` does not currently contain. A guard whose rule can only be exercised by the
    tree it walks cannot be shown to hold for anything the tree does not happen to do.
    """
    parts = Path(where).parts
    here = parts[0] if len(parts) > 1 else None
    crossings: list[str] = []
    offences: list[str] = []
    for line, module in astscan.imported_modules(ast.parse(text), ("stayfixed", *parts[:-1])):
        bits = module.split(".")
        if len(bits) < 3 or bits[0] != "stayfixed" or bits[1] not in ruled or bits[1] == here:
            continue
        crossings.append(f"{where} -> {module}")
        if bits[2] == "api":
            continue
        offences.append(f"{where}:{line} imports {module}")
    return crossings, offences


def test_no_module_reaches_into_another_packages_private_module() -> None:
    # CONTRIBUTING: "`api.py` is the area's import surface. Other areas import from it and from
    # nothing else." Nothing asserted it, and an external review found the first two violations
    # in this repository's history — `memory/commands.py` importing `hooks.dispatch` and
    # `doctor/checks.py` importing `hooks.sink` — both merged green.
    #
    # Three mutations: `mutations/`'s "an area reaches past another area's api.py again" -> a
    # violation is back (doctor reading the setup area's private `machine` module); "the
    # cross-area import guard walks ten files instead of the package" -> the walk narrows, and a
    # guard that silently stops walking reports no offences for the same reason a guard with
    # nothing to report does; and "the boundary rule ignores a relative import again" -> a
    # relative import goes unresolved, which the test below holds, because this walk has none to
    # find.
    source = ROOT / "src" / "stayfixed"
    areas = area_names(source)
    ruled = _ruled_packages(source)
    files = sorted(source.rglob("*.py"))
    # `scripts/` is walked too, and the reason is the violation that merged green under a walk
    # that was not: `scripts/check_artifacts.py` imported `stayfixed.overlay.layout` for the very
    # constant `overlay/api.py`'s docstring said had been trimmed *because* nothing outside the
    # area imported it. A walk one directory narrower than the code that can break the rule is a
    # walk that will eventually report nothing. The script paths are relative to `ROOT` rather
    # than to `source`, so `here` is `scripts` — not an area, so every stayfixed import a script
    # makes is a crossing and has to go through an `api.py`.
    scripts = sorted((ROOT / "scripts").glob("*.py"))
    crossings: list[str] = []
    offences: list[str] = []
    for path in files:
        found, broken = _boundary_offences(
            str(path.relative_to(source)), path.read_text(encoding="utf-8"), ruled
        )
        crossings += found
        offences += broken
    for path in scripts:
        found, broken = _boundary_offences(
            str(path.relative_to(ROOT)), path.read_text(encoding="utf-8"), ruled
        )
        crossings += found
        offences += broken
    # The walk is asserted before anything is asserted about it. Both floors are well under
    # today's numbers and are there to fail on a walk that stopped walking, not to be kept
    # current. Re-measured 2026-10-04, by running this module's own `_ruled_packages` and
    # `_boundary_offences` over the same two globs in an interpreter: 144 files, 11 areas and
    # one further package with an `api.py`, 5 scripts and 242 crossings, with a walk narrowed to
    # `commands.py` alone counting 9 under `src/` and 24 with the scripts — which is what the
    # crossings floor of 60 has to be below. `trust` became the twelfth area since, with its
    # `commands.py`, `prove` the thirteenth, and `hints`, with the `hooks.py` it took from
    # `guards`, the fourteenth.
    assert len(areas) == 14, areas
    # The packages held to a surface without being discovered, pinned by name for the reason
    # `tests/test_surfaces.py` pins its list: gaining or losing one is a decision.
    assert sorted(set(ruled) - set(areas)) == ["release"], ruled
    assert len(files) >= 70, len(files)
    # The script walk's own floor: without it a `glob` that stopped matching would take the
    # `scripts/` half of this guard back to the state that hid the violation, and the crossing
    # count below has enough headroom to absorb the loss.
    assert len(scripts) >= 3, scripts
    assert len(crossings) >= 60, crossings
    assert not offences, "a module reached past another package's api.py:\n" + "\n".join(offences)


def test_the_boundary_rule_resolves_a_relative_import_before_judging_it() -> None:
    # The hole the guard above shipped with, and the reason it needs a test of its own: there is
    # not one relative import under `src/stayfixed/`, so the walk cannot exercise this spelling
    # and a synthetic module has to. `from ..hooks.sink import DIRECTORY` inside
    # `doctor/checks.py` is the violation this whole guard exists to end, written the way a
    # contributor who prefers relative imports would write it.
    #
    # Asserted as the exact offence rather than as "some offence": a rule that resolved the
    # module to any other name would also produce a non-empty list, from the wrong reading.
    ruled = ["doctor", "hooks", "memory", "setup"]
    crossings, offences = _boundary_offences(
        "doctor/checks.py", "from ..hooks.sink import DIRECTORY\n", ruled
    )
    assert offences == [
        "doctor/checks.py:1 imports stayfixed.hooks.sink",
        "doctor/checks.py:1 imports stayfixed.hooks.sink.DIRECTORY",
    ]
    assert crossings == [
        "doctor/checks.py -> stayfixed.hooks.sink",
        "doctor/checks.py -> stayfixed.hooks.sink.DIRECTORY",
    ]

    # The published spelling of the same import, relatively: a crossing and not an offence. This
    # is the arm that fails if the rule is made to refuse every relative import rather than read
    # it, which is the other repair this could have had.
    crossings, offences = _boundary_offences(
        "doctor/checks.py", "from ..hooks.api import DIRECTORY\n", ruled
    )
    assert crossings == [
        "doctor/checks.py -> stayfixed.hooks.api",
        "doctor/checks.py -> stayfixed.hooks.api.DIRECTORY",
    ]
    assert not offences

    # And an area's own modules, reached relatively, are its own business at any depth — a
    # module's package is itself for one dot, and `from . import x` carries no module at all.
    crossings, offences = _boundary_offences(
        "doctor/checks.py", "from .checks import OK\nfrom . import commands\n", ruled
    )
    assert (crossings, offences) == ([], [])


def test_a_package_that_publishes_an_api_py_is_held_to_it_without_being_an_area() -> None:
    # An area is how the CLI and the hook registry find code; the surface rule is about
    # `api.py`. `release` publishes one and carries neither `commands.py` nor `hooks.py`, so
    # while the rule was keyed on discovery alone, a reach past its surface — from a module
    # under `src/` or from a script — was not even a crossing. Read off the tree rather than
    # with a hand-picked list, so the probe is of the set the walk above actually uses.
    source = ROOT / "src" / "stayfixed"
    assert "release" not in area_names(source)
    ruled = _ruled_packages(source)

    crossings, offences = _boundary_offences(
        "doctor/checks.py", "from stayfixed.release.pins import released\n", ruled
    )
    assert offences == [
        "doctor/checks.py:1 imports stayfixed.release.pins",
        "doctor/checks.py:1 imports stayfixed.release.pins.released",
    ]
    crossings, offences = _boundary_offences(
        "scripts/release.py", "from stayfixed.release.pins import tag_for\n", ruled
    )
    assert offences == [
        "scripts/release.py:1 imports stayfixed.release.pins",
        "scripts/release.py:1 imports stayfixed.release.pins.tag_for",
    ]

    # The published spelling is a crossing and not an offence: the arm that fails if the
    # package is refused outright instead of being held to its surface.
    crossings, offences = _boundary_offences(
        "scripts/release.py", "from stayfixed.release.api import tag_for\n", ruled
    )
    assert crossings == [
        "scripts/release.py -> stayfixed.release.api",
        "scripts/release.py -> stayfixed.release.api.tag_for",
    ]
    assert not offences
