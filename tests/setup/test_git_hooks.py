# tests/setup/test_git_hooks.py
"""`stayfixed setup --git-hooks`: the CLI wiring over `guards.githooks`'s already-tested
installer (`tests/guards/test_githooks.py` covers the hook's own chaining behaviour end to
end). What is untested until this file is the command that calls it and the report it prints.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pytest

from stayfixed.errors import Refusal
from stayfixed.gitenv import hooks_dir
from stayfixed.guards.api import HOOK_MARKER, HOOK_NAME
from stayfixed.printed import quoted
from stayfixed.setup.commands import run_setup
from tests import gitfixture

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _scrubbed_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The same guard `tests/guards/test_githooks.py` carries, for the same reason: without a
    # scrubbed HOME and no global/system gitconfig, a real `core.hooksPath` on this machine
    # would decide where these tests install a hook — outside `tmp_path`.
    monkeypatch.setenv("HOME", str(tmp_path))
    probe = tmp_path / "probe"
    probe.mkdir()
    _git(tmp_path, probe, "init", "-q")
    if tmp_path not in hooks_dir(probe).parents:
        pytest.skip("a system-wide core.hooksPath points these tests outside tmp_path")


def _env(tmp_path: Path) -> dict[str, str]:
    """The shared fixture environment, with `tmp_path` as `HOME`.

    It used to pin `PATH` to `/usr/bin:/bin`; `tests/gitfixture.py` passes the real one
    through, for the reason `stayfixed.gitenv`'s docstring gives — a hardcoded path is what
    picks the Xcode shim on macOS over the `git` the machine owner installed.
    """
    return gitfixture.env(tmp_path)


def _git(tmp_path: Path, root: Path, *args: str) -> str:
    return gitfixture.git(root, *args, home=tmp_path)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(tmp_path, root, "init", "-q", "-b", "main")
    return root


def _args(**over: object) -> argparse.Namespace:
    # `home`/`machine` are absolute paths under a directory nothing in this test creates, on
    # purpose: `run_setup`'s git-hooks branch must never reach them, and a relative placeholder
    # here once resolved against the real repository root and, when a stashed pre-Task-14
    # `run_setup` fell through to the preset flow instead of refusing early, `setup()`'s own
    # `home.mkdir(parents=True, exist_ok=True)` created a real directory in this checkout. An
    # absolute path outside any root this test controls turns that class of mistake into an
    # `OSError` under `/nonexistent` instead of a write into the tree.
    base: dict[str, object] = {
        "preset": None,
        "home": "/nonexistent/stayfixed-test-guard/home",
        "machine": "/nonexistent/stayfixed-test-guard/config.toml",
        "overlay": None,
        "plugin": None,
        "git_hooks": True,
        "approval_boundary": False,
        "uninstall": False,
        "root": ".",
    }
    base.update(over)
    return argparse.Namespace(**base)


@pytest.mark.parametrize(
    "over",
    [{"preset": "recommended"}, {"overlay": "elsewhere"}, {"plugin": ["superpowers"]}],
    ids=["preset", "overlay", "plugin"],
)
def test_git_hooks_refuses_every_flag_that_asks_machine_setup_to_act(
    tmp_path: Path, over: dict[str, object]
) -> None:
    # `--git-hooks` does nothing of machine setup's. Only `--preset` was refused beside it, and
    # `--overlay` was dropped and the hook installed, exit 0. Asked of a real repository, where an
    # install that is not refused succeeds. Mutations (`mutations/`'s "setup --git-hooks drops
    # --preset" -> the first case installs; "setup --git-hooks drops --overlay" -> the second
    # does; "setup --git-hooks drops --plugin" -> the third does).
    root = _repo(tmp_path)
    with pytest.raises(Refusal) as refused:
        run_setup(_args(root=str(root), **over))
    assert "--git-hooks" in str(refused.value)
    assert not (hooks_dir(root) / HOOK_NAME).exists()


def test_the_hook_is_installed_into_the_repositorys_own_hooks_path(tmp_path: Path) -> None:
    # The hook is installed per repository into `git rev-parse --git-path hooks`, never into
    # `core.hooksPath`. The "never" is the assertion: `core.hooksPath` is global state this command
    # has no business owning. Assert the file lands under `gitenv.hooks_dir(root)` and that
    # `git config --get core.hooksPath` is still unset afterwards.
    root = _repo(tmp_path)
    run_setup(_args(root=str(root)))
    assert (hooks_dir(root) / HOOK_NAME).is_file()
    # `run_git`: `config --get` exits 1 when the key is unset, which is the answer here.
    completed = gitfixture.run_git(root, "config", "--get", "core.hooksPath", home=tmp_path)
    assert completed.returncode != 0 and completed.stdout.strip() == ""


def test_a_foreign_hook_is_kept_and_chained_to(tmp_path: Path) -> None:
    # The reason this is not a plain overwrite: a developer's own prepare-commit-msg is theirs, and
    # silently replacing it is data loss. Mutation: none of this test's own — the preserve-and-chain
    # guard is `guards.githooks.install`'s, already load-bearing as `mutations/`'s "the hook stops
    # chaining to the hook it displaced"; this test is about the CLI reporting the same outcome, not
    # a new guard.
    root = _repo(tmp_path)
    directory = hooks_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    foreign = directory / HOOK_NAME
    foreign.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    foreign.chmod(0o755)
    run_setup(_args(root=str(root)))
    local = directory / (HOOK_NAME + ".local")
    assert local.read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"
    assert HOOK_MARKER in (directory / HOOK_NAME).read_text(encoding="utf-8")


def test_uninstall_restores_the_foreign_hook(tmp_path: Path) -> None:
    # The round trip, byte for byte: the `.local` file goes back to its original name with its
    # original content and mode.
    root = _repo(tmp_path)
    directory = hooks_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    foreign = directory / HOOK_NAME
    original = "#!/bin/sh\necho mine\n"
    foreign.write_text(original, encoding="utf-8")
    foreign.chmod(0o700)
    run_setup(_args(root=str(root)))
    run_setup(_args(root=str(root), uninstall=True))
    assert not (directory / (HOOK_NAME + ".local")).exists()
    restored = directory / HOOK_NAME
    assert restored.read_text(encoding="utf-8") == original
    assert oct(restored.stat().st_mode)[-3:] == "700"


def test_the_report_names_what_it_moved(tmp_path: Path) -> None:
    # The report prints what it moved, because a `.local` file nobody was told about is
    # indistinguishable from a lost one.
    root = _repo(tmp_path)
    directory = hooks_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    foreign = directory / HOOK_NAME
    foreign.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    foreign.chmod(0o755)
    result = run_setup(_args(root=str(root)))
    local = directory / (HOOK_NAME + ".local")
    assert str(local) in result.summary
    assert result.data["preserved"] == str(local)


def test_the_two_modes_refuse_to_combine(tmp_path: Path) -> None:
    # One writes machine-level files and the other writes into one repository; an invocation
    # that did both would have two exit codes to report and one to return. Mutation: drop the
    # `if args.preset is not None: raise Refusal(...)` guard in `run_setup` → this test reddens
    # because the call then falls into the git-hooks branch and returns a `Result` instead.
    with pytest.raises(Refusal):
        run_setup(_args(root=str(tmp_path), preset="recommended"))


def test_uninstall_with_nothing_installed_reports_that_and_writes_nothing(tmp_path: Path) -> None:
    # The other half of the round trip: `--uninstall` before any `--git-hooks` run has ever
    # happened here is not an error, and the report says there was nothing to restore.
    root = _repo(tmp_path)
    result = run_setup(_args(root=str(root), uninstall=True))
    assert not (hooks_dir(root) / HOOK_NAME).exists()
    assert result.data["restored"] is None


# What `--uninstall` finds at the hook path — whether a foreign hook was there first, and whether
# stayfixed's was installed over it — and the line it prints, `{hook}` being that path.
UNINSTALLED = {
    "ours": (False, True, "removed {hook}; there was no foreign hook to restore"),
    "chained": (True, True, "removed {hook}; restored the foreign hook chained to it"),
    "nothing": (False, False, "there is no stayfixed hook at {hook}; nothing was removed"),
    "foreign": (
        True,
        False,
        "left {hook} as it was: it is not stayfixed's hook; nothing was removed",
    ),
}


@pytest.mark.parametrize(("mine", "ours", "line"), UNINSTALLED.values(), ids=UNINSTALLED)
def test_uninstall_says_whether_it_removed_stayfixeds_hook(
    tmp_path: Path, mine: bool, ours: bool, line: str
) -> None:
    # It said "removed …; there was no foreign hook to restore" whatever it found: with no hook
    # there it removed nothing, and with a foreign hook there both halves were false, that hook
    # being in place and untouched. The installed hook's own text names this command, so the line
    # says which of the four it met, and `--json` carries it as `found`. Mutations:
    # `mutations/`'s "uninstall says it removed a hook when there was none" and "uninstall says
    # it removed a hook when the hook there is not stayfixed's".
    root = _repo(tmp_path)
    directory = hooks_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    hook = directory / HOOK_NAME
    if mine:
        hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
        hook.chmod(0o755)
    if ours:
        run_setup(_args(root=str(root)))
    result = run_setup(_args(root=str(root), uninstall=True))
    assert result.summary == line.format(hook=quoted(str(hook)))
    found = "removed" if ours else "foreign" if mine else "absent"
    assert result.data["found"] == found
    if mine:
        assert hook.read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"


def test_uninstall_over_a_directory_at_the_hook_path_leaves_it_and_says_so(tmp_path: Path) -> None:
    # The command's half of `tests/guards/test_githooks.py`'s case: what is not a regular file at
    # the hook path is not stayfixed's, so the line says it was left, and the run exits 0, where
    # it refused with exit 2. Mutation: `mutations/`'s "uninstall reads a hook that is not a
    # regular file".
    root = _repo(tmp_path)
    hook = hooks_dir(root) / HOOK_NAME
    hook.mkdir(parents=True)
    result = run_setup(_args(root=str(root), uninstall=True))
    assert (
        result.summary
        == f"left {quoted(str(hook))} as it was: it is not stayfixed's hook; nothing was removed"
    )
    assert (result.exit_code, result.data["found"]) == (0, "foreign")
    assert hook.is_dir()


@pytest.mark.parametrize("run", ["installed", "chained", "reinstalled", "uninstalled"])
def test_every_summary_prints_the_hooks_path_git_names_quoted(tmp_path: Path, run: str) -> None:
    # The hooks directory is git's answer, from a `core.hooksPath` the repository sets, and the
    # summaries printed it raw where the refusals quote it: an escape sequence and a bell in it
    # drove the terminal that read the report. Mutations (`mutations/`'s "setup --git-hooks
    # prints the installed hook's path raw" -> `installed`, `chained` and `reinstalled`; "setup
    # --git-hooks --uninstall prints the hook's path raw" -> `uninstalled`).
    root = _repo(tmp_path)
    _git(tmp_path, root, "config", "core.hooksPath", ".hooks\x1b]0;owned\x07")
    hook = hooks_dir(root) / HOOK_NAME
    if run == "chained":
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
        hook.chmod(0o755)
    if run in ("reinstalled", "uninstalled"):
        run_setup(_args(root=str(root)))
    result = run_setup(_args(root=str(root), uninstall=run == "uninstalled"))
    assert "\x1b" not in result.summary and "\x07" not in result.summary, result.summary
    assert "\\x1b]0;owned\\x07" in result.summary, result.summary
    assert result.data["path"] == str(hook)


@pytest.mark.parametrize("uninstall", [False, True], ids=["install", "uninstall"])
def test_a_root_through_a_symlink_loop_is_refused_naming_it(
    tmp_path: Path, uninstall: bool
) -> None:
    # Python 3.11 and 3.12 raised `RuntimeError` resolving a looping `--root`, and
    # `setup --git-hooks` ended in `internal error` there; 3.13 handed the loop to `git`, which
    # could not name a hooks directory in it. Resolved through `fsops.resolved`, it is refused
    # naming `--root` on every interpreter, before `git` is asked. Mutation (`mutations/`'s
    # "setup --git-hooks resolves --root past fsops") -> each reddens.
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    with pytest.raises(Refusal) as refused:
        run_setup(_args(root=str(loop), uninstall=uninstall))
    assert str(refused.value) == (
        f"--root {quoted(str(loop))} cannot be checked (Too many levels of symbolic links), so "
        f"nothing was written"
    )


def test_a_second_install_over_our_own_hook_reports_a_reinstall(tmp_path: Path) -> None:
    # `installed.replaced` is true when the hook already there is ours, not a stranger's —
    # `run_git_hooks` reports that case with its own summary rather than the "kept and chained
    # to" one, which would misreport a hook that was never foreign.
    root = _repo(tmp_path)
    run_setup(_args(root=str(root)))
    result = run_setup(_args(root=str(root)))
    assert "reinstalled" in result.summary
    assert result.data["preserved"] is None and result.data["replaced"] is True
