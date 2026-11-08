"""The repository's scripts, loaded by path for the tests that drive them.

`scripts/` is not an importable package, so each script is loaded from its file. `load` is the one
loader: the mutation oracle's declarations (`tests/declarations.py`), the release script, the two
smoke scripts and the artifact checker all go through it, so a change to how a script is loaded is
made once. `release` is the release script, loaded once for every module that reads it — its own
tests, the repository's manifest test, and the two walks over every reader of a document that may
not parse. `plugin_tree` is the reader of the plugin's paths, loaded once in the same way: the
scripts run it as a program, and only the tests import it. `publish_plugin` is the publisher of
that tree to the plugin's own repository, and `publish_template` the publisher of the overlay
template repository, each loaded once for its tests.
"""

from __future__ import annotations

import functools
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from tests.floor import developer_free_environ

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(path: Path, name: str) -> ModuleType:
    """A fresh copy of the script at `path`, under the module name `name`.

    Registered in `sys.modules` before it is executed: every script is written under
    `from __future__ import annotations`, so every annotation is a string, and `@dataclass`
    resolves a field's annotations through `sys.modules[cls.__module__]` — a module absent from
    there makes the decorator raise before any test runs. A script that fails to load is taken
    out again, so the next load does not find half a module under its name.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


@functools.cache
def release() -> ModuleType:
    """`scripts/release.py` as a module, loaded once."""
    return load(SCRIPTS / "release.py", "release_script_under_test")


@functools.cache
def plugin_tree() -> ModuleType:
    """`scripts/plugin_tree.py` as a module, loaded once."""
    return load(SCRIPTS / "plugin_tree.py", "plugin_tree_script_under_test")


@functools.cache
def publish_plugin() -> ModuleType:
    """`scripts/publish_plugin.py` as a module, loaded once."""
    return load(SCRIPTS / "publish_plugin.py", "publish_plugin_script_under_test")


@functools.cache
def publish_template() -> ModuleType:
    """`scripts/publish_template.py` as a module, loaded once."""
    return load(SCRIPTS / "publish_template.py", "publish_template_script_under_test")


def without_drybag(
    name: str, where: Path, *args: str, missing: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """The script `name` run as an owner runs it without `uv run`, where no `drybag` can be
    imported: a copy in `where`, outside this repository, under `-I -S`. `-I` alone would still
    find this checkout's package through the environment's `site-packages`, where `uv sync`
    installs it; `-S` leaves only the standard library. `missing` names standard modules this
    interpreter is to lack as an older one does (`tomllib` before 3.11): each is set to `None` in
    `sys.modules` before the script runs, which makes importing it raise `ImportError`."""
    copy = where / name
    shutil.copyfile(SCRIPTS / name, copy)
    boot = (
        "import runpy, sys; sys.modules.update(dict.fromkeys(sys.argv[1].split(',')) if "
        "sys.argv[1] else {}); sys.argv[:] = sys.argv[2:]; runpy.run_path(sys.argv[0], "
        "run_name='__main__')"
    )
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", boot, ",".join(missing), str(copy), *args],
        cwd=where,
        capture_output=True,
        text=True,
        check=False,
        env=developer_free_environ(),
    )
