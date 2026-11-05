from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from stayfixed import __version__
from tests.gitfixture import git
from tests.test_launcher import _old_python

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "hooks" / "run-hook.sh"


def _plugin_root(
    base: Path, exit_code: int, *, echo_cwd: bool = False, with_launcher: bool = True
) -> Path:
    """A plugin root: a copy of the shipped wrapper, and a fake launcher beside it.

    The wrapper finds its launcher relative to its own path, so a plugin root is a real directory
    pair — `hooks/run-hook.sh` and `scripts/stayfixed` — which is what an installed plugin is. A
    fake launcher, because these cases are about the wrapper's exit mapping and its argv, and a
    real `stayfixed` run would couple them to every command in the package. With `echo_cwd` it
    prints the physical directory it runs in, which is what `Path.resolve()` names.
    """
    root = base / "plugin"
    (root / "scripts").mkdir(parents=True)
    (root / "hooks").mkdir(parents=True)
    shutil.copy(WRAPPER, root / "hooks" / WRAPPER.name)
    (root / "hooks" / WRAPPER.name).chmod(0o755)
    if not with_launcher:
        return root
    launcher = root / "scripts" / "stayfixed"
    body = "import os\n\nprint(os.getcwd())\n" if echo_cwd else ""
    launcher.write_text(
        f"#!/usr/bin/env python3\n{body}raise SystemExit({exit_code})\n", encoding="utf-8"
    )
    launcher.chmod(0o755)
    return root


def _path_without_uv() -> str:
    """This process's `PATH` less every directory that holds a `uv`.

    The suite runs under `uv run`, so its own `PATH` holds uv, and a wrapper that falls back to
    uv's interpreter would pass every case below that expects `off()` from a missing or sub-floor
    `python3`. Those cases are about the wrapper's own interpreter lookup, so they get this.
    """
    kept = [
        directory
        for directory in os.environ.get("PATH", "").split(os.pathsep)
        if directory and not os.access(os.path.join(directory, "uv"), os.X_OK)
    ]
    return os.pathsep.join(kept)


def _python_on_path(base: Path, interpreter: str = sys.executable) -> str:
    """A `PATH` whose first `python3` runs `interpreter`, then this process's own, without uv."""
    directory = base / "python-on-path"
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "python3"
    shim.write_text(f'#!/bin/sh\nexec "{interpreter}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return f"{directory}{os.pathsep}{_path_without_uv()}"


def _run(
    *argv: str,
    plugin_root: Path,
    cwd: Path | None = None,
    project: Path | None = None,
    path: str | None = None,
    extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the wrapper inside `plugin_root`, the way an installed plugin's entry does.

    `cwd` defaults to `plugin_root`, which is under `tmp_path` and is not a repository, so the
    wrapper's `git` names no project root unless a case gives it one. `path` defaults to this
    process's own, whose first `python3` under `uv run` is the suite's interpreter.
    """
    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    if path is not None:
        env["PATH"] = path
    env.update(extra or {})
    return subprocess.run(
        [str(plugin_root / "hooks" / WRAPPER.name), *argv],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(cwd if cwd is not None else plugin_root),
        stdin=subprocess.DEVNULL,
    )


def test_no_python3_on_path_degrades_open(tmp_path: Path) -> None:
    # A session never dies of its configuration: a machine with no `python3` gets one line on
    # stderr and an exit Claude Code reads as no objection.
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _run("hook", "PreToolUse", plugin_root=_plugin_root(tmp_path, 0), path=str(empty))
    assert result.returncode == 0
    assert "no python3 on PATH" in result.stderr


def test_no_python3_and_no_uv_degrades_open(tmp_path: Path) -> None:
    # The wrapper's uv fallback is taken only where a uv is named: with an empty `PATH` there is
    # neither a `python3` nor a uv, and the answer is today's line.
    result = _run("hook", "PreToolUse", plugin_root=_plugin_root(tmp_path, 0), path="")
    assert result.returncode == 0
    assert "no python3 on PATH" in result.stderr


def test_uv_is_asked_from_a_neutral_directory_and_a_repository_script_never_runs(
    tmp_path: Path,
) -> None:
    # Measured with uv 0.12.19: asked from a project, `uv python find` runs the executable at
    # `.venv/bin/python` in its working directory or a parent to ask its version, an explicit
    # `>=3.11` request included, so a repository that commits one chooses the program every hook
    # starts. A `.python-version` naming a script is ignored, and is planted beside it as the file
    # the requirement names. Asked from `/`, uv looks at no repository. No `python3` on `PATH`:
    # one directory holds a link to the real uv and another a link named `python3.<minor>` to the
    # interpreter the suite's venv came from, which uv finds and the wrapper's own `python3` lookup
    # does not. Skips only where no uv is on `PATH`; CI runs the suite under `uv run`, so it runs
    # there.
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("no uv on PATH; CI runs the suite under `uv run`")
    uv_dir, python_dir = tmp_path / "uv-only", tmp_path / "interpreter-only"
    uv_dir.mkdir()
    python_dir.mkdir()
    (uv_dir / "uv").symlink_to(uv)
    (python_dir / f"python3.{sys.version_info.minor}").symlink_to(_base_interpreter())
    marker = tmp_path / "script-ran"
    # `echo` is a builtin: the wrapper's `PATH` here holds no `touch`.
    script = f"#!/bin/sh\necho ran > '{marker}'\nexit 1\n"
    project = tmp_path / "project"
    planted = project / ".venv" / "bin" / "python"
    planted.parent.mkdir(parents=True)
    planted.write_text(script, encoding="utf-8")
    planted.chmod(0o755)
    (project / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    pinned = tmp_path / "repository-python"
    pinned.write_text(script, encoding="utf-8")
    pinned.chmod(0o755)
    (project / ".python-version").write_text(f"{pinned}\n", encoding="utf-8")
    result = _run(
        "hook",
        "PreToolUse",
        plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True),
        project=project,
        path=f"{uv_dir}{os.pathsep}{python_dir}",
        # Under `uv run` the suite's own venv is the active one, which uv answers before it looks
        # at any `.venv` in the directory it runs in.
        extra={"VIRTUAL_ENV": "", "CONDA_PREFIX": ""},
    )
    assert not marker.exists()
    assert result.returncode == 0 and "continuing open" not in result.stderr
    # The launcher ran, in the project: only `uv`'s `cd /` stayed in the substitution's subshell.
    assert Path(result.stdout.strip()) == project.resolve()


def test_an_interpreter_below_the_floor_degrades_open(tmp_path: Path) -> None:
    # A real sub-floor interpreter rather than a fake that exits non-zero for every argument,
    # which could not exercise `sys.version_info` at all. Without the probe the launcher's own
    # floor check answers in its own words. `_old_python` is the tree's own seam,
    # and CI pins it through STAYFIXED_OLD_PYTHON so this runs there rather than skipping.
    old = _old_python()
    if old is None:
        pytest.skip("no interpreter below 3.11 on this machine; set STAYFIXED_OLD_PYTHON")
    result = _run(
        "hook",
        "PreToolUse",
        plugin_root=_plugin_root(tmp_path, 2),
        path=_python_on_path(tmp_path, old),
    )
    assert result.returncode == 0
    assert "is not python 3.11 or newer" in result.stderr


OFF = "stayfixed's hooks are off in this session: "
TO_DO = ". Install Python 3.11 or newer on PATH."


def _no_python3(tmp_path: Path) -> tuple[str, str]:
    empty = tmp_path / "empty"
    empty.mkdir()
    return str(empty), "there is no python3 on PATH"


def _a_python3_below_the_floor(tmp_path: Path) -> tuple[str, str]:
    # A `python3` that fails the probe, so this runs where no real sub-floor interpreter exists:
    # what is under test is what the wrapper says, not the probe. Its directory carries the two
    # bytes a JSON string must escape, and a non-ASCII one, since a `PATH` directory may be named
    # anything and the line goes out inside a JSON string the harness parses.
    directory = tmp_path / 'a "quoted\\ dir é'
    directory.mkdir()
    shim = directory / "python3"
    shim.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    shim.chmod(0o755)
    # Each byte outside the narrow set is a `?`, the `é` two of them.
    return str(directory), f"{tmp_path}/a ?quoted? dir ??/python3 is not Python 3.11 or newer"


@pytest.mark.parametrize(
    "state", [_no_python3, _a_python3_below_the_floor], ids=["no-python3", "below-the-floor"]
)
def test_the_dispatching_session_start_says_the_hooks_are_off(
    tmp_path: Path, state: Callable[[Path], tuple[str, str]]
) -> None:
    # Measured on a machine whose `PATH` held only a 3.9 `/usr/bin/python3`: every entry said why
    # on stderr, which nobody reads on a `0`, and stayfixed was off with nothing said. So the one
    # entry that dispatches `SessionStart` says it where Claude Code shows the person
    # (`systemMessage`) and where the model reads (`additionalContext`), and still exits 0.
    path, why = state(tmp_path)
    result = _run("hook", "SessionStart", plugin_root=_plugin_root(tmp_path, 0), path=path)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    line = f"{OFF}{why}{TO_DO}"
    assert payload["systemMessage"] == line
    assert payload["hookSpecificOutput"] == {
        "hookEventName": "SessionStart",
        "additionalContext": line,
    }
    assert "continuing open" in result.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ("memory", "session-context", "--bundle", "standing-rules", "--part", "1"),
        ("hook", "PreToolUse"),
    ],
    ids=["memory-session-context", "hook-pretooluse"],
)
def test_every_other_entry_stays_silent_without_a_usable_python(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    # Seven entries run on `SessionStart`; the six memory ones saying it too would put the line
    # before the session seven times, and on a tool event stdout is a contract about the call.
    path, _ = _no_python3(tmp_path)
    result = _run(*argv, plugin_root=_plugin_root(tmp_path, 0), path=path)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "no python3 on PATH" in result.stderr


def test_a_usable_interpreter_leaves_session_start_to_stayfixed(tmp_path: Path) -> None:
    # The positive row: with a usable `python3` the wrapper adds nothing to what stayfixed prints.
    result = _run(
        "hook", "SessionStart", plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True), cwd=tmp_path
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.splitlines() == [str(tmp_path.resolve())]


def test_an_interpreter_at_the_floor_is_accepted(tmp_path: Path) -> None:
    # The positive row: without it a probe that rejected everything would pass every case above.
    result = _run("hook", "PreToolUse", plugin_root=_plugin_root(tmp_path, 0))
    assert (result.returncode, result.stderr) == (0, "")


def test_a_missing_launcher_degrades_open(tmp_path: Path) -> None:
    # Without the check a missing launcher reaches Python as a missing script, and the line that
    # names the fault is CPython's.
    result = _run("hook", "PreToolUse", plugin_root=_plugin_root(tmp_path, 0, with_launcher=False))
    assert result.returncode == 0
    assert "no readable launcher" in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file at mode 000")
def test_a_launcher_that_cannot_be_read_degrades_open(tmp_path: Path) -> None:
    # `test -f` tests existence, not readability: a launcher at mode 000 reached CPython, which
    # printed its own "Permission denied" and exited 2.
    root = _plugin_root(tmp_path, 0)
    (root / "scripts" / "stayfixed").chmod(0o000)
    try:
        result = _run("hook", "PreToolUse", plugin_root=root)
    finally:
        (root / "scripts" / "stayfixed").chmod(0o755)
    assert result.returncode == 0
    assert "no readable launcher" in result.stderr


@pytest.mark.parametrize("rc", [1, 2, 3, 126, 127])
def test_any_non_zero_exit_degrades_open_and_says_so(tmp_path: Path, rc: int) -> None:
    # No handler refuses a call, so a non-zero exit is always a fault, and a 2 passed through
    # would block every Bash call on one.
    result = _run("hook", "PreToolUse", plugin_root=_plugin_root(tmp_path, rc))
    assert result.returncode == 0
    assert f"stayfixed exited {rc}" in result.stderr


def test_a_zero_exit_passes_through_untouched(tmp_path: Path) -> None:
    result = _run("hook", "PreToolUse", plugin_root=_plugin_root(tmp_path, 0))
    assert (result.returncode, result.stderr) == (0, "")


def _executable(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)


def _empty_path_element(project: Path, script: str) -> str:
    # An empty `PATH` element is the working directory, so a `python3` committed to the project.
    _executable(project / "python3", script)
    return f"{os.pathsep}{_path_without_uv()}"


def _version_manager_shim(project: Path, script: str) -> str:
    # A pyenv, asdf or mise shim runs what the `.python-version` where it runs names.
    _executable(project / "pinned", script)
    (project / ".python-version").write_text(f"{project / 'pinned'}\n", encoding="utf-8")
    shims = project.parent / "shims"
    shims.mkdir()
    read = 'test -e .python-version && read -r v < .python-version && exec "$v" "$@"'
    _executable(shims / "python3", f'{read}\nexec "{sys.executable}" "$@"\n')
    return f"{shims}{os.pathsep}{_path_without_uv()}"


@pytest.mark.parametrize(
    "plant", [_empty_path_element, _version_manager_shim], ids=["empty-element", "shim"]
)
def test_a_repository_never_chooses_the_interpreter(
    tmp_path: Path, plant: Callable[[Path, str], str]
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    marker = tmp_path / "planted-ran"
    path = plant(project, f"echo ran > '{marker}'\nexit 1\n")
    result = _run(
        "hook",
        "PreToolUse",
        plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True),
        project=project,
        path=path,
    )
    assert not marker.exists()
    # The hook still ran, on the real interpreter, in the project root.
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.splitlines() == [str(project.resolve())]


def test_stayfixed_runs_from_the_project_root(tmp_path: Path) -> None:
    # Every hooks.json entry but the dispatcher's relies on `--root` defaulting to `.`, and the
    # harness does not promise to launch a hook in the project. The wrapper changes into
    # CLAUDE_PROJECT_DIR, else git's toplevel, so one rule serves every entry.
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = _run(
        "memory",
        "session-context",
        "--bundle",
        "standing-rules",
        plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True),
        cwd=elsewhere,
        project=project,
    )
    assert result.stdout.strip() == str(project.resolve())


def test_the_project_root_is_never_taken_from_an_inherited_git_environment(tmp_path: Path) -> None:
    # `cd repoA` with GIT_DIR/GIT_WORK_TREE naming repoB put the launcher in repoB, so the whole
    # hook read another repository's stayfixed.toml, budgets and note store. The Codex path,
    # where CLAUDE_PROJECT_DIR is unset.
    here, there = tmp_path / "here", tmp_path / "there"
    for repository in (here, there):
        repository.mkdir()
        git(repository, "init", "-q")
    result = _run(
        "hook",
        "PreToolUse",
        plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True),
        cwd=here,
        extra={"GIT_DIR": str(there / ".git"), "GIT_WORK_TREE": str(there)},
    )
    assert result.stdout.strip() == str(here.resolve())


def test_a_project_root_that_cannot_be_entered_says_so(tmp_path: Path) -> None:
    # A root that was named and cannot be entered left the process in the harness's directory,
    # and if that was another stayfixed project every `--root`-defaulting entry read its
    # configuration, with nothing said.
    result = _run(
        "hook",
        "PreToolUse",
        plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True),
        cwd=tmp_path,
        project=tmp_path / "not-on-disk",
    )
    assert result.returncode == 0
    assert "cannot enter the project root" in result.stderr
    # Non-vacuous: the launcher was not reached at all, which would have printed a directory.
    assert result.stdout == ""


def test_a_cdpath_never_chooses_the_directory_the_hook_runs_in(tmp_path: Path) -> None:
    # With `CDPATH` set and a relative root, `cd` writes the destination it chose to stdout, ahead
    # of anything the launcher prints, and a hook's stdout is a contract the harness parses.
    decoy = tmp_path / "decoy-parent" / "target"
    decoy.mkdir(parents=True)
    real = tmp_path / "real-parent" / "target"
    real.mkdir(parents=True)
    result = _run(
        "hook",
        "PreToolUse",
        plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True),
        project=Path("target"),
        cwd=real.parent,
        extra={"CDPATH": str(decoy.parent)},
    )
    # Exactly one line, so nothing was written ahead of the launcher, and the real tree.
    assert result.stdout.splitlines() == [str(real.resolve())]


def test_a_project_root_whose_name_begins_with_a_dash_is_a_destination_and_not_an_option(
    tmp_path: Path,
) -> None:
    dashed = tmp_path / "parent" / "-dashed"
    dashed.mkdir(parents=True)
    result = _run(
        "hook",
        "PreToolUse",
        plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True),
        project=Path("-dashed"),
        cwd=dashed.parent,
    )
    assert result.stdout.splitlines() == [str(dashed.resolve())]


def test_the_wrapper_is_committed_executable() -> None:
    # A 0644 wrapper is never executed, so no code of ours runs; this assertion and `doctor`'s
    # wrapper probe are the whole defence.
    assert stat.S_IMODE(WRAPPER.stat().st_mode) & 0o111, "run-hook.sh must ship executable"


class Planting(NamedTuple):
    """A module planted where an interpreter started without `-I` imports it at startup, the
    variables that make it so, and the file it appends to each time it runs."""

    interpreter: str
    env: dict[str, str]
    record: Path


def _planted_module(directory: Path, name: str, record: Path) -> None:
    """Write `<directory>/<name>.py`, which appends its `sys.argv` to `record` on each run.

    `sitecustomize` and `usercustomize` are the two names CPython's `site` imports at startup
    from whatever `sys.path` holds by then, before the program's first line.
    """
    directory.mkdir(parents=True)
    (directory / f"{name}.py").write_text(
        f"import sys\nwith open({str(record)!r}, 'a') as f:\n    f.write(repr(sys.argv) + '\\n')\n",
        encoding="utf-8",
    )


def _base_interpreter() -> str:
    """The interpreter the suite's venv was made from, which has a user site where the venv has
    none: a venv disables the user site, so a case about it run under `sys.executable` would be
    green with the guard deleted.

    `sys._base_executable` is private to CPython, and nothing public names the interpreter a venv
    was made from. Outside a venv it is `sys.executable`, as is the fallback.
    """
    return getattr(sys, "_base_executable", None) or sys.executable


def _python_path_case(tmp_path: Path) -> Planting:
    planted = tmp_path / "planted-sitecustomize"
    record = tmp_path / "sitecustomize-ran"
    _planted_module(planted, "sitecustomize", record)
    return Planting(sys.executable, {"PYTHONPATH": str(planted)}, record)


def _user_site_case(tmp_path: Path) -> Planting:
    interpreter = _base_interpreter()
    base = tmp_path / "userbase"
    # Asked of the interpreter itself, because the layout differs by build: a macOS framework
    # build puts it under `lib/python/`, every other one under `lib/python3.N/`.
    site_dir = subprocess.run(
        [interpreter, "-c", "import site; print(site.getusersitepackages())"],
        capture_output=True,
        text=True,
        check=True,
        env=dict(os.environ, PYTHONUSERBASE=str(base)),
    ).stdout.strip()
    record = tmp_path / "usercustomize-ran"
    _planted_module(Path(site_dir), "usercustomize", record)
    return Planting(interpreter, {"PYTHONUSERBASE": str(base)}, record)


@pytest.mark.parametrize(
    "case", [_python_path_case, _user_site_case], ids=["pythonpath", "user-site"]
)
def test_a_module_the_environment_plants_never_runs(
    tmp_path: Path, case: Callable[[Path], Planting]
) -> None:
    # A developer's `PYTHONPATH` or user site would otherwise be imported before the launcher's
    # first line, once for the version probe and once for the launcher. Reddens on either `-I`
    # removed, which is two entries in `mutations/`. The shipped wrapper and launcher, run in
    # place: the other half of this case is that the real launcher still finds its own `src`
    # under `-I`. Run from `tmp_path`, outside every repository.
    planting = case(tmp_path)
    # Non-vacuous: the planting does run in an interpreter started without `-I`.
    subprocess.run(
        [planting.interpreter, "-c", "pass"],
        check=True,
        env=dict(os.environ, **planting.env),
        cwd=tmp_path,
    )
    assert planting.record.read_text(encoding="utf-8") == "['-c']\n"
    planting.record.unlink()
    result = _run(
        "--version",
        plugin_root=ROOT,
        cwd=tmp_path,
        path=_python_on_path(tmp_path, planting.interpreter),
        extra=planting.env,
    )
    assert not planting.record.exists(), planting.record.read_text(encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"stayfixed {__version__}"
