"""No script under `scripts/` imports another, but the one exemption named here; CONTRIBUTING.md,
under "Areas", says why.

The walk reads every import statement in every `scripts/*.py` and the launcher `scripts/drybag`
through `tests/boundaries/astscan.py`, as the area rules do, and an offence is a module reached by a
sibling's stem or by the directory's own name, which a package-qualified or relative import goes
through. What it cannot see is reviewed by hand: a script run through `runpy` or loaded through
`importlib`, and a name built at run time. `sys.path` is not followed, so a module of a sibling's
name found elsewhere is an offence all the same.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.boundaries.astscan import imported_modules
from tests.scriptload import SCRIPTS

# The scripts allowed to import a sibling, as (the importing file's name, the module it imports).
# Both are CI smoke drivers run from the checkout, never from the tag's objects, so each sibling
# is always beside them: `smoke_exfiltration.py` reuses `smoke_hooks`'s fixture repository and
# developer-free environment rather than keep a second copy of each.
EXEMPT: frozenset[tuple[str, str]] = frozenset({("smoke_exfiltration.py", "smoke_hooks")})


def _script_files() -> list[Path]:
    """Every script the walk reads: the `*.py` files and the launcher."""
    return [*sorted(SCRIPTS.glob("*.py")), SCRIPTS / "drybag"]


def _script_modules() -> frozenset[str]:
    """The names a sibling script is reached under: the stems of the `*.py` files, and the
    directory's own name, through which an import reaches them package-qualified."""
    return frozenset({*(path.stem for path in SCRIPTS.glob("*.py")), SCRIPTS.name})


def _script_imports() -> set[tuple[str, str]]:
    """Every (file name, script module) pair an import statement in a script names; `scripts`
    stands for any sibling reached through the directory's name, a relative import's included."""
    modules = _script_modules()
    found: set[tuple[str, str]] = set()
    for path in _script_files():
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for _, name in imported_modules(tree, (SCRIPTS.name,)):
            top = name.split(".")[0]
            if top in modules:
                found.add((path.name, top))
    return found


def test_the_walk_reads_every_script() -> None:
    # A walk-based assertion states its walk is non-empty, and the launcher is in it.
    files = _script_files()
    assert len(files) > 5, files
    assert all(path.is_file() for path in files), files
    assert {"release", "plugin_tree", "smoke_hooks"} <= _script_modules()


def test_no_script_imports_another_but_the_named_exemption() -> None:
    # Mutations (oracle): `mutations/`'s "the release script imports the plugin tree script" ->
    # `release.py` imports a sibling and this reddens; "the release script imports the plugin tree
    # script through the directory's name" -> `from scripts import plugin_tree`, which a walk
    # reading only the stems missed, reddens it too.
    offences = sorted(_script_imports() - EXEMPT)
    assert offences == []


def test_every_exemption_is_still_used() -> None:
    # Non-vacuous: the walk saw the exempt import, so an exemption whose import is gone reddens
    # here and is dropped rather than left to excuse a later one. Mutation (oracle): `mutations/`'s
    # "the exfiltration smoke stops importing the hooks smoke" -> this reddens, and the test above
    # stays green.
    found_imports = _script_imports()
    assert sorted(EXEMPT - found_imports) == []  # EXEMPT <= found_imports, naming what is gone
