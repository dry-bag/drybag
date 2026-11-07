"""The one `git` the suite runs against a fixture repository, and the environment it runs in.

Twenty-three test modules each defined their own, and the copies had drifted apart in five
ways at once: thirteen inherited `os.environ` whole, seven pinned `HOME` under `tmp_path` and
thirteen left the developer's real one, five forced a committer identity and fifteen took
whatever the machine had, four never set `GIT_TERMINAL_PROMPT`, and twelve lines across four
modules had drifted from `os.devnull` to the literal `"/dev/null"`. Nothing held them to each
other, so each fixture was protected by whichever subset its author happened to write.

Here rather than in each module because there is no reason left for the copies: the sentence
that used to justify them — "`tests/` is not a package (CONTRIBUTING…)" — was false and is
gone from CONTRIBUTING.md, `tests/__init__.py` is tracked, and `tests/snapshot.py` is the
precedent for a shared test module.

**The environment is sealed rather than inherited, and that is the hardening.** An inherited
`GIT_DIR`, `GIT_WORK_TREE` or `GIT_INDEX_FILE` points `git` at a repository other than the one
it was given — which is the defect `stayfixed.gitenv` and `stayfixed.runner` both exist to close,
and it is worse here than in production: these calls are `init`, `add` and `commit`, so a
redirected fixture does not read the wrong repository, it *writes* to it. `GIT_CONFIG_GLOBAL`
and `GIT_CONFIG_SYSTEM` go to `os.devnull` for the reason `tests/memory/test_store.py` gave in
prose: `commit.gpgsign`, `core.hooksPath` and `init.templateDir` can each hang or fail a commit
that has nothing to do with the code under test. `GIT_CONFIG_NOSYSTEM` is set beside them
because on macOS the second is not enough: Apple's git also reads a gitconfig inside Xcode that
no path variable replaces, and that file names the default branch.

**`PATH` is passed through rather than pinned**, for the reason `stayfixed.gitenv`'s module
docstring gives about production: the machine owner's own `git` is the one that must answer,
and a hardcoded `/usr/bin:/bin` is what picks the Xcode shim on macOS over the `git` they
installed. Two modules pinned it; that was a narrowing nothing needed, and this widens it.

**The committer identity is forced**, so a machine whose `user.email` is only in the global
configuration this module has just pointed at `os.devnull` can still commit, and so that two
runs of the same fixture on two machines produce the same author. Three modules were passing
`-c user.email=…` at the call site to buy exactly this; those call sites still work and are
now merely redundant.

**Git's automatic maintenance is off**, because it outlives the command that started it. A
`commit`, `merge`, `fetch`, `pull`, `am` or `rebase`, and the `receive-pack` behind a push, ends
by starting `git maintenance run --auto --detach`, and from git 2.55 the process that detaches
keeps `objects/maintenance.lock` until its background work is done — after the fixture's
`commit` has returned. A test that removes or walks `.git` straight after one races it: on
2026-10-05 `shutil.rmtree(root / ".git")` listed the lock and then found it gone, and the test
failed with `FileNotFoundError: 'maintenance.lock'` on one leg of four (Python 3.13's `rmtree`
ignores a file that vanishes; 3.11's and 3.12's raise). `maintenance.auto = false` stops the
spawn, and `gc.auto = 0` stops the `gc --auto` an older git ran in its place. They go in as
`GIT_CONFIG_COUNT` entries, which reach every `git` the fixture's own starts in the same
repository. They do not reach the other side of a push to a local remote: git unsets
`GIT_CONFIG_COUNT` for the `receive-pack` it starts there, so a pushed-to bare repository can
still be left with maintenance running, and no test removes or walks one after pushing to it.
The `git` the product runs reads neither variable, and `tests/conftest.py` gives it the same two
keys through the `HOME` it does read.

`home` defaults to `root.parent`, which is inside `tmp_path` for every fixture in this suite:
CONTRIBUTING.md's Tests section holds a test to never reading or writing the developer's real
home, and pointing the two configuration variables at `os.devnull` is the first half of that,
not the whole of it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from stayfixed import gitenv

# The one spelling of the skip, published here because five modules had written it out.
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

# The variable a session sets to give every git it starts a configuration of its own, a `pushurl`
# or an `insteadOf` among them. Spelled here, the one module that may name it, for the tests that
# set it in the process to show that no git stayfixed starts reads it.
SESSION_CONFIG = "GIT_CONFIG_GLOBAL"

# What survives from the ambient environment. `PATH` for the reason in the module docstring;
# the rest is what makes `git` able to run and report at all on the three platforms. Everything
# else is dropped, `GIT_DIR` and `GIT_WORK_TREE` above all — the same rule
# `stayfixed.gitenv.GIT_ENV_KEEP` states for production, with `TMPDIR` added because these
# fixtures are built under one.
ENV_KEEP = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR")

# The configuration that keeps every `git` the suite runs from leaving maintenance running behind
# it, for the reason in the module docstring: as `GIT_CONFIG_COUNT` entries in `env` below, and as
# the per-test global configuration `tests/conftest.py` writes for the product's own `git`.
MAINTENANCE_OFF = (("maintenance.auto", "false"), ("gc.auto", "0"))


def gitconfig(entries: tuple[tuple[str, str], ...]) -> str:
    """`entries`, each a dotted `section.name` and its value, as the text of a gitconfig file."""
    lines: list[str] = []
    for key, value in entries:
        section, _, name = key.partition(".")
        lines += [f"[{section}]", f"\t{name} = {value}"]
    return "".join(f"{line}\n" for line in lines)


def env(home: Path, **extra: str) -> dict[str, str]:
    """The sealed environment one fixture `git` runs in, with `extra` layered on top.

    `extra` is for a module whose difference is real: `tests/guards/test_githooks.py` puts a
    `stayfixed` shim on `PATH` because its `git commit` has to run the commit-msg hook it just
    installed, and that shim is the branch the test exists to exercise; it adds the suite's
    floor (`tests/floor.py`) as well, for the `stayfixed` that hook starts.
    """
    sealed = {key: os.environ[key] for key in ENV_KEEP if key in os.environ}
    sealed.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            # Apple's git reads one more file, below the system one, that `GIT_CONFIG_SYSTEM`
            # does not replace and this does: it sets `init.defaultBranch = main`, which no CI
            # runner has, so an `init` without `-b` made `main` on a Mac and `master` in CI.
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
    )
    sealed["GIT_CONFIG_COUNT"] = str(len(MAINTENANCE_OFF))
    for index, (key, value) in enumerate(MAINTENANCE_OFF):
        sealed[f"GIT_CONFIG_KEY_{index}"] = key
        sealed[f"GIT_CONFIG_VALUE_{index}"] = value
    sealed.update(extra)
    return sealed


def run_git(
    root: Path, *args: str, home: Path | None = None, **extra: str
) -> subprocess.CompletedProcess[str]:
    """`git -C root args` in the sealed environment, whatever it exits with.

    For the handful of call sites whose subject *is* the exit code or the streams — a
    `check-ignore` that answers 1 for "no match", a `git commit` expected to be rejected by the
    hook under test, a `config --get` expected to find nothing. `git` below is this with
    `check=True` and only the stdout, which is what every other call site wants.

    `stdin` is closed rather than inherited, which is the second half of what
    `GIT_TERMINAL_PROMPT` buys and the reason `stayfixed.runner` gives for the same line: every
    call here captures its output, so a credential prompt would be invisible and would block
    until the test run was killed.
    """
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env(home if home is not None else root.parent, **extra),
        stdin=subprocess.DEVNULL,
    )


def git(root: Path, *args: str, home: Path | None = None, **extra: str) -> str:
    """`git -C root args` in the sealed environment; its stdout, raising on a non-zero exit."""
    done = run_git(root, *args, home=home, **extra)
    done.check_returncode()
    return done.stdout


def git_bytes(root: Path, *args: str, stdin: bytes = b"", home: Path | None = None) -> bytes:
    """`git -C root args` in the sealed environment, in bytes both ways; raising on a non-zero exit.

    For a call whose answer is not text: `tests/test_payload.py` reads every blob of a tree
    through `cat-file --batch`, and a binary blob has no decoding. `stdin` is the whole input
    rather than an inherited stream, for the reason `run_git` closes it.
    """
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin,
        capture_output=True,
        check=True,
        env=env(home if home is not None else root.parent),
    ).stdout


def plant_path(root: Path, raw: bytes, content: str = "planted\n") -> None:
    """Stage a blob at the path `raw`, as bytes, whether or not this disk could hold that name.

    `update-index --cacheinfo` takes the name as it is given, so a path that is not UTF-8 —
    which APFS refuses to create — reaches the index on every platform, and every `git` that
    prints the index or a commit of it prints those bytes. The blob's source is written inside
    `.git`, so the working tree gains nothing.
    """
    source = root / ".git" / "planted-blob"
    source.write_text(content, encoding="utf-8")
    blob = git(root, "hash-object", "-w", str(source)).strip()
    git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{os.fsdecode(raw)}")


def dated(root: Path, tick: int, *args: str) -> str:
    """`git args` with the author and committer date of the `tick`th commit, stripped of its
    trailing newline, so git orders merge bases as the test says rather than by the clock."""
    stamp = f"@{1_700_000_000 + tick * 1000} +0000"
    return git(root, *args, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp).strip()


@dataclass(frozen=True)
class CrissCross:
    base: str  # `main`, having merged the side branch
    fixed: str  # the commit on `main` the side branch forked before
    side: str  # the side branch's tip, committed after `fixed`: git's own pick


def criss_cross(root: Path, fix: Callable[[], object]) -> CrissCross:
    """Two merge bases between `main` and HEAD, the one git picks alone being the older state.

    From the commit `main` has checked out, which the caller made at tick 1: `fix()` edits the
    tree and is committed on `main` (tick 2); a side branch forks before it and commits
    `side.txt` after it (tick 3); `main` merges the side branch (tick 4); and HEAD is left
    detached on the fix merged with the side branch (tick 5). The premise is asserted here, so
    no caller's test can pass because git changed its pick: the merge bases are the fix and the
    side branch, and `git merge-base` alone answers the side branch.
    """
    first = git(root, "rev-parse", "HEAD").strip()
    fix()
    git(root, "add", "-A")
    dated(root, 2, "commit", "-q", "-m", "the fix")
    fixed = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "-b", "side", first)
    (root / "side.txt").write_text("side\n", encoding="utf-8")
    git(root, "add", "-A")
    dated(root, 3, "commit", "-q", "-m", "a colleague's side branch")
    side = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "main")
    dated(root, 4, "merge", "-q", "--no-ff", "--no-edit", "side")
    base = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "--detach", fixed)
    dated(root, 5, "merge", "-q", "--no-ff", "--no-edit", side)
    assert sorted(git(root, "merge-base", "--all", base, "HEAD").split()) == sorted([fixed, side])
    assert git(root, "merge-base", base, "HEAD").strip() == side
    return CrissCross(base, fixed, side)


def answer_shallow_check(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    """Make the shallow check `gitenv.fork_points` asks exit `code` with nothing on stdout;
    every other git call, that one's merge base included, is the real one."""
    real = gitenv.git_run

    def answered(where: Path, *args: str, **kwargs: Any) -> tuple[int, str]:
        if args[:2] == ("rev-parse", "--is-shallow-repository"):
            return code, ""
        return real(where, *args, **kwargs)

    monkeypatch.setattr(gitenv, "git_run", answered)


def stand_in_git(monkeypatch: pytest.MonkeyPatch, stand_in: Path) -> None:
    """Have the product run `stand_in` wherever it runs `git`, for the length of one test: the
    first `git` on `PATH`, which a `Runner` launch and every `git_run` resolve it through."""
    monkeypatch.setenv("PATH", f"{stand_in.parent}{os.pathsep}{os.environ.get('PATH', '')}")


def no_git(monkeypatch: pytest.MonkeyPatch, nowhere: Path) -> None:
    """Have no `git` the product can launch, for the length of one test: `PATH` names only
    `nowhere`, a directory with no `git` in it."""
    monkeypatch.setenv("PATH", str(nowhere))
