#!/usr/bin/env python3
"""Apply each mutation `mutations/` declares and check that the named tests go red.

The plans ask that "every new assertion ships with the mutation that reddens it, or a sentence
saying why none exists", and until now those mutations existed only as English sentences inside
multi-thousand-line plan documents. A contributor could satisfy the rule only by hand-editing
source and reverting, and a reviewer had no way to check they had.

This is not a general mutation tester — `mutmut` is, and is far too slow to gate a pull request
on. It is the curated set: the guards whose *load-bearingness* has to be proven rather than
merely covered, which is exactly the distinction that let `fsops.open_within` be fully covered
by twelve tests and still contain nothing.

Each entry names one file, one exact substring to replace, and the tests that must fail when it
is. A mutation that survives — the tests still pass with the guard broken — is a finding, and so
is one whose `before` no longer appears in the file, because that means the assertion and the
line it is about have drifted apart. Each entry's `name` is its own across every group file,
because a comment anywhere in the tree cites an entry by its name.

Usage:

    uv run python scripts/mutation_oracle.py            # every declared mutation
    uv run python scripts/mutation_oracle.py fsops      # only those whose name or file matches
    uv run python scripts/mutation_oracle.py --jobs 2   # at most two entries at a time

Every mutation is applied to a throwaway worktree of `HEAD`; the working tree is never written.
One such worktree per job, each proving one entry at a time: as many jobs as this process may
use CPUs, at most four, unless `--jobs` says otherwise. So a test a `reddens` names runs beside
other tests in other processes, and has to be safe to.

Exit codes match the rest of the project: 0 all held, 1 findings, and 2 for a usage error.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import itertools
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import tomllib
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# The declarations, one TOML file per group of the tree rather than one file: the set grows with
# every guard, and a single file had passed the 256 KiB at which the plugin directory holds the
# version for a reviewer. Every `*.toml` here is read; which file an entry belongs in is
# `GROUP_OF`'s.
DECLARATIONS = ROOT / "mutations"
# Which group file an entry belongs in, by the path its `file` names: the longest prefix that
# matches wins, so the order of the rows decides nothing, and the empty prefix takes everything no
# other row names. This table is the one place the groups are spelled: each group file's header
# says what its group holds in words and points here, `scripts/check_artifacts.py` globs the
# directory rather than naming its files, and the tests hold every entry to the file its `file`
# routes to.
#
# **A hand-kept table, and the one deliberate exception to CONTRIBUTING's "areas are discovered
# by name — there is no shared registry to edit".** One file per area would need no table, and it
# would be about twenty files, not eleven. The groups were sized for the plugin directory's limit
# of 512 files, while the repository root was the plugin folder and every tracked file counted
# against it. The plugin's tree (`scripts/plugin_tree.py`) no longer holds `mutations/`, so that
# limit no longer reaches these files, and no size cap holds a group file. The table stays because
# regrouping the declarations into one file per area would rewrite every entry's history and
# collide with every open branch's entries, for no reader's gain. CONTRIBUTING.md, "Tests", states
# the same ruling.
GROUP_OF: tuple[tuple[str, str], ...] = (
    ("src/stayfixed/attach/", "attach"),
    ("src/stayfixed/project/", "project"),
    ("src/stayfixed/templates/", "project"),
    ("src/stayfixed/presets/", "project"),
    ("src/stayfixed/scaffold/", "scaffold"),
    ("src/stayfixed/guards/", "guards"),
    ("src/stayfixed/hints/", "guards"),
    ("src/stayfixed/setup/", "install"),
    ("src/stayfixed/overlay/", "install"),
    ("src/stayfixed/doctor/", "doctor"),
    ("src/stayfixed/memory/", "records"),
    ("src/stayfixed/docs/", "records"),
    ("src/stayfixed/", "core"),
    ("scripts/publish_plugin.py", "publish"),
    ("scripts/", "tooling"),
    (".github/", "tooling"),
    ("", "repository"),
)
# Where scratch checkouts are made and where the sweep looks for leaked ones. A module-level
# name rather than a `gettempdir()` call at each site, for the reason `ROOT` is one: this
# module deletes directories, and its own tests have to be able to aim both halves somewhere
# harmless. `tests/scripts/test_mutation_oracle.py` redirects this beside `ROOT` — before it
# did, every run of that module swept the developer's real temporary directory, which is a
# thing the suite must not touch and which would have destroyed a concurrent oracle's checkout.
TEMPDIR = Path(tempfile.gettempdir())


@dataclass(frozen=True)
class Mutation:
    name: str
    file: Path
    before: str
    after: str
    reddens: tuple[str, ...]


def group_for(file: str) -> str:
    """The group whose file declares a mutation of `file`, a path from the repository root: the
    group of the longest `GROUP_OF` prefix that `file` starts with."""
    _, group = max(
        ((prefix, group) for prefix, group in GROUP_OF if file.startswith(prefix)),
        key=lambda row: len(row[0]),
    )
    return group


def group_files() -> list[Path]:
    """Every group file, in sorted order: the one place the declarations directory is globbed."""
    return sorted(DECLARATIONS.glob("*.toml"))


def declared() -> list[Mutation]:
    """Every entry of every group file: the files in sorted order, each file's in its own."""
    found: list[Mutation] = []
    for path in group_files():
        found.extend(_entries(tomllib.loads(path.read_text(encoding="utf-8"))))
    return found


def _entries(raw: dict[str, Any]) -> list[Mutation]:
    return [
        Mutation(
            name=str(entry["name"]),
            file=ROOT / str(entry["file"]),
            before=str(entry["before"]),
            after=str(entry["after"]),
            reddens=tuple(str(t) for t in entry["reddens"]),
        )
        for entry in raw.get("mutation", [])
    ]


class WorktreeUnavailable(RuntimeError):
    """`git worktree add` did not produce a checkout; the message is git's own stderr."""


class ConcurrentRun(RuntimeError):
    """Another oracle holds the lock; the message names it and the process that does."""


def _holder(lock: Path) -> str | None:
    """What is written in the lock file if the process that wrote it is still alive.

    **Unreadable is treated as alive, and that is the conservative direction.** The failure this
    lock prevents is one run deleting another's checkout, and the cost of being wrong the other
    way is a message telling a person which file to remove. A lock whose contents this process
    cannot parse is far more likely to be a live run on a filesystem doing something odd than a
    dead one, so it refuses and says where to look.
    """
    try:
        content = lock.read_text(encoding="utf-8").strip()
    except OSError:
        return "a process this one cannot ask about"
    pid = content.partition(" ")[0]
    if not pid.isdigit():
        return content or "a process this one cannot name"
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        # Alive and owned by somebody else, which is still alive.
        return content
    except OSError:
        return content
    return content


@contextlib.contextmanager
def single_run(tempdir: Path | None = None) -> Iterator[Path]:
    """Hold the one-oracle-at-a-time lock, or refuse naming what holds it.

    **`sweep_stale_scratch` assumes a single writer, and this is what enforces it:** a second run
    started beside a first would sweep the first's checkout out from under it, and every mutation
    after that point would report a false `FINDING`.

    `O_CREAT | O_EXCL` is the whole mechanism: the create either wins or raises, with no window
    between the test and the write. A lock whose writer has died is taken over rather than
    obeyed, because a `SIGKILL` runs no `finally` and a stale lock that refused for ever would
    be a worse failure than the one this prevents. The retry is bounded at one: losing the race
    twice means another run really is starting, and that is a refusal rather than a spin.
    """
    lock = (tempdir or TEMPDIR) / LOCK_NAME
    mine = f"{os.getpid()} {ROOT}"
    for attempt in range(2):
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            holder = _holder(lock)
            if holder is not None:
                raise ConcurrentRun(
                    f"another mutation oracle is running ({holder}); this one refuses rather "
                    f"than sweeping its scratch checkout out from under it. Wait for it, or "
                    f"remove {lock} if you are sure it is gone"
                ) from None
            if attempt:
                raise ConcurrentRun(
                    f"{lock} changed hands while a stale one was being cleared; another run is "
                    f"starting"
                ) from None
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as writing:
            writing.write(mine)
        try:
            yield lock
        finally:
            # Only if it is still ours: a run that took this one over as stale owns it now, and
            # unlinking its lock on the way out would be this function doing the very thing it
            # was written to stop.
            try:
                held = lock.read_text(encoding="utf-8").strip()
            except OSError:
                held = ""
            if held == mine:
                lock.unlink(missing_ok=True)
        return


SCRATCH_PREFIX = "stayfixed-oracle-"
# The one-run-at-a-time lock, beside the scratch checkouts it exists to protect. A **file** and
# not a directory, which is what keeps it out of `sweep_stale_scratch`'s own housekeeping: that
# walk globs this prefix and removes directories, and the `is_dir()` arm is what spares this.
# Asserted rather than assumed — `tests/scripts/test_mutation_oracle.py` holds the sweep to it.
LOCK_NAME = f"{SCRATCH_PREFIX}lock"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(ROOT), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def sweep_stale_scratch(keep: Path | None = None, *, tempdir: Path | None = None) -> list[str]:
    """Drop every leaked scratch checkout but this run's, and return what was dropped.

    **`git worktree prune` does not clear these, and the docstring that said it did was wrong
    in both halves.** `prune` only drops entries whose directory is *gone*, and an interrupted
    run leaves the `mkdtemp` tree standing — so the registration survived every prune, the
    commit stayed pinned against `git gc`, and the tree stayed on disk. One was found in the
    development repository during review: 6.5 MB, and `git worktree prune --dry-run -v` printed
    nothing about it.

    The order matters: `worktree remove --force` first so git forgets the registration, then
    `rmtree` for anything `remove` declined, then `prune` to collect whatever is now missing a
    directory. Failures are not raised — this is housekeeping at the top of a run, and a
    temporary directory another user owns is not this run's business.

    **The cost, stated rather than hidden: this assumes one oracle at a time.** A second run started
    while the first is working would sweep the first's checkout out from under it. That is the same
    single-writer assumption the rest of the oracle already makes — the scratch checkout exists so
    that two oracles, or an oracle beside an editor, cannot interleave writes over one file — and CI
    runs exactly one. The sweep is at the *top* of `main` and never again, so nothing a live run
    creates afterwards is in reach of it.
    """
    dropped: list[str] = []
    listing = _git("worktree", "list", "--porcelain")
    registered = [
        Path(line[len("worktree ") :])
        for line in listing.stdout.splitlines()
        if line.startswith("worktree ")
    ]
    for tree in registered:
        if tree.name != "tree" or not tree.parent.name.startswith(SCRATCH_PREFIX):
            continue
        if keep is not None and tree == keep:
            continue
        _git("worktree", "remove", "--force", str(tree))
        shutil.rmtree(tree.parent, ignore_errors=True)
        dropped.append(str(tree.parent))
    # And the trees no `git worktree` entry points at any more: `_run`'s `TemporaryDirectory`
    # leaks the same way on a kill, under the same prefix.
    #
    # `tempdir` overrides `TEMPDIR` for one call; both exist because this function deletes
    # directories and a test has to be able to aim it somewhere harmless. With `gettempdir()`
    # hard-coded here, every run of `tests/scripts/test_mutation_oracle.py` swept the
    # developer's real temporary directory — measured with a canary planted there, which the
    # suite removed — and a real oracle running at that moment would have lost its checkout.
    for stale in (tempdir or TEMPDIR).glob(f"{SCRATCH_PREFIX}*"):
        if keep is not None and keep.parent == stale:
            continue
        if str(stale) in dropped or not stale.is_dir():
            continue
        shutil.rmtree(stale, ignore_errors=True)
        dropped.append(str(stale))
    _git("worktree", "prune")
    return dropped


@contextlib.contextmanager
def scratch_checkout() -> Iterator[Path]:
    """A detached worktree of HEAD under a temporary directory, removed afterwards.

    The oracle proves HEAD and never the working tree. `--detach` so no branch is
    created or moved. The parent directory is created by `mkdtemp` and the tree goes one level
    below it, because `git worktree add` refuses a path that already exists.

    **Cleanup, which is the half this used to get wrong.** The `finally` removes the *tree*
    before asking git to drop the registration, so an entry whose `worktree remove` fails is
    at least left prunable rather than pinned for ever; `prune` then collects it. A `SIGTERM`
    is turned into `SystemExit` so that a terminate runs the `finally` at all — without the
    handler, the ordinary way CI and an interrupted agent stop a process left everything
    behind. `SIGKILL` cannot be caught by anything, which is what `sweep_stale_scratch` at the
    top of `main` is for.
    """
    parent = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=TEMPDIR))
    tree = parent / "tree"
    added = _git("worktree", "add", "--detach", "--quiet", str(tree), "HEAD")
    if added.returncode != 0:
        shutil.rmtree(parent, ignore_errors=True)
        raise WorktreeUnavailable(added.stderr.strip() or f"exit {added.returncode}")
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _terminate)
    try:
        yield tree
    finally:
        signal.signal(signal.SIGTERM, previous)
        # `rmtree` BEFORE `worktree remove`: git refuses to remove a worktree it considers
        # dirty, and a run interrupted mid-mutation leaves exactly that. Removing the directory
        # first makes the entry prunable whatever `remove` then says.
        shutil.rmtree(parent, ignore_errors=True)
        _git("worktree", "remove", "--force", str(tree))
        _git("worktree", "prune")


def _terminate(signum: int, frame: object) -> None:
    """A terminate becomes an exception, so every `finally` on the stack runs."""
    raise SystemExit(f"terminated by signal {signum}")


@dataclass(frozen=True)
class Outcome:
    """One pytest run, as the two facts the oracle reasons about.

    `code` alone is not enough, and that is the whole point of this type. Exit 0 is "nothing
    failed", which a run of zero tests satisfies just as well as a run of twenty — so an
    oracle that reads only the exit code cannot tell a green assertion from an absent one.
    `executed` is how many tests actually ran and reported a result, taken from pytest's own
    JUnit report rather than parsed out of its prose.
    """

    code: int
    executed: int

    @property
    def passed(self) -> bool:
        return self.code == 0 and self.executed > 0


def _executed(report: Path) -> int:
    """How many tests ran and reported a result, from pytest's own JUnit XML.

    Machine-readable on purpose. The alternative — looking for the word "passed" in `-q`
    output — makes the oracle's own correctness depend on the wording of a summary line, and
    this file's history is a run of defects where the oracle could not tell one state from
    another. A report pytest never wrote (a usage error, which is exactly what a mistyped test
    id produces) counts as zero, which is the honest answer and the fail-closed one.

    **`errors` are subtracted as well as `skipped`, and that is the whole of the count's
    meaning.** A module that cannot be imported still produces a JUnit report with one
    `<testcase>` in it carrying an `<error>`, so `tests - skipped` came to 1 for a run in which
    the named test never executed — measured: `code 4 executed 1`. The question this number
    answers is "did the assertion get to run", and a collection error, a fixture that raised
    and a mistyped id are all "no". Subtracting them is what lets `_check` tell a mutation that
    reddened a guard from one that stopped the guard's test from running at all.
    """
    if not report.is_file():
        return 0
    try:
        # `S314`, with the reasoning where a reviewer sees it, as the two `subprocess` sites
        # below already do. This document is not untrusted input: it was written moments ago by
        # the pytest this process launched, into a `TemporaryDirectory` this process created,
        # and it is read before that directory is removed. Nothing a repository authors reaches
        # it except through pytest's own attribute escaping.
        root = ElementTree.parse(report).getroot()  # noqa: S314
    except ElementTree.ParseError:
        return 0
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    return sum(
        int(suite.get("tests", 0)) - int(suite.get("skipped", 0)) - int(suite.get("errors", 0))
        for suite in suites
    )


def _environment(cwd: Path, cache: Path, *, writes_bytecode: bool) -> dict[str, str]:
    """The environment every pytest this module launches in `cwd` runs under.

    The scratch checkout's `src` goes FIRST: the editable install of the main checkout is on
    `sys.path` through site-packages, and PYTHONPATH is the only entry that precedes it. Without
    this the named tests import the unmutated modules and every mutation "survives" — measured
    before the line was written, by the test that pins it.
    """
    inherited = os.environ.get("PYTHONPATH", "")
    pythonpath = str(cwd / "src") + (os.pathsep + inherited if inherited else "")
    env = {**os.environ, "PYTHONPATH": pythonpath, "PYTHONPYCACHEPREFIX": str(cache)}
    if writes_bytecode:
        env.pop("PYTHONDONTWRITEBYTECODE", None)
    else:
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def warm_cache(tree: Path) -> Path:
    """A bytecode cache for `tree`, filled from HEAD's bytes before any mutation is applied.

    **Half of every run used to be compiling.** `_run` pointed `PYTHONPYCACHEPREFIX` at a fresh
    empty directory each time, so every one of roughly eleven hundred pytest launches compiled
    pytest, its plugins, the standard library it touches and some two hundred of this project's
    own modules from source before running a single test: measured on one entry, 1.53 s of CPU
    cold against 0.63 s warm. One `--collect-only` of the whole suite, run once per checkout
    while it still holds exactly HEAD, pays that once instead.

    **What makes a shared cache safe here is `_check`, not this function.** The hazard the empty
    cache was answering is real — see `_run` — and it is answered now by never letting a mutated
    file carry the mtime of any bytecode already cached for it: `_check` stamps each mutated
    write with a whole-second mtime no other content of that file has had, and puts HEAD's own
    mtime back with HEAD's bytes. Every `.pyc` written here is for HEAD's bytes under HEAD's
    mtime, so it is valid exactly when the file holds HEAD's bytes, which is the only time it
    matches.

    A collection that fails or times out leaves a partial cache and is not a refusal: whatever
    it did write is still HEAD's bytecode, and whatever it did not is compiled from source on
    each run as it always was. A HEAD that cannot be collected is reported by the clean runs
    that follow.
    """
    cache = tree.parent / "bytecode"
    # Bounded as `collected_ids` bounds the same collection: a HEAD whose collection hangs
    # costs five minutes and a cold cache, not the job's whole budget.
    with contextlib.suppress(subprocess.TimeoutExpired):
        subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
            cwd=tree,
            # Captured and never decoded, as `_run`'s output is: what this leaves behind is the
            # cache, and a byte no codec reads in the collection's output killed the oracle.
            capture_output=True,
            timeout=300,
            check=False,
            env=_environment(tree, cache, writes_bytecode=True),
        )
    return cache


def _run(targets: tuple[str, ...], cwd: Path, *, cache: Path | None = None) -> Outcome:
    """Run only the named tests, against a bytecode cache that cannot be stale.

    **Why this used to run against an empty cache every time, and what answers that now.** A
    `.pyc` header records the source's mtime **truncated to whole seconds**, so two writes to one
    file inside the same second that leave it the same size are indistinguishable to the import
    system. Two of the mutations below happen to change `memory/notes.py` by exactly the same 20
    bytes each; on a fast runner the second one was written within a second of the first one's
    restore, Python reused the bytecode compiled under the *first* mutation, and the second was
    reported as surviving when it does not — which CI found. A fresh empty
    `PYTHONPYCACHEPREFIX` per run was the answer, at the price of compiling everything on
    every run.

    **The load-bearing rule is now `_check`'s mtime stamp**, which gives every mutated write an
    mtime no other content of that file has had, so no bytecode — whoever wrote it — can match
    bytes it was not compiled from. That is what lets `cache` be the one `warm_cache` filled from
    HEAD. `-B` and `PYTHONDONTWRITEBYTECODE` stay as defence in depth: with the stamp in place,
    bytecode a run wrote for mutated bytes could never be matched again, so dropping them would
    cost only cache churn. `cache` omitted is a fresh empty directory, as before.

    **`--basetemp` inside this run's own scratch directory**, because several jobs run pytest at
    once and pytest's default is one directory per user shared by all of them. Each pytest that
    exits prunes the older numbered directories there, and a neighbour's is protected only by a
    lock file it creates just after the directory — so a job's `tmp_path` can be removed under a
    running test, which then fails for a reason that is not the mutation. Seen once before this
    line existed: on a four-job run, one clean run of 1,138 failed with a test that passes alone
    every time and does nothing but write under `tmp_path` — the shared state this removes.
    """
    with tempfile.TemporaryDirectory(prefix=f"{SCRATCH_PREFIX}cache-", dir=TEMPDIR) as scratch:
        report = Path(scratch) / "report.xml"
        with _living:
            if _stopping.is_set():
                raise Stopped("the run is being stopped; no further pytest is started")
            child = subprocess.Popen(  # noqa: S603
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--no-header",
                    f"--basetemp={Path(scratch) / 'basetemp'}",
                    f"--junit-xml={report}",
                    *targets,
                ],
                cwd=cwd,
                # Captured to keep it off the terminal and never decoded: the verdict is the exit
                # code and the junit report, and a failing test's diff can carry a byte no codec
                # reads — a strict decode then killed the run on a mutation it had caught.
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_environment(cwd, cache or Path(scratch), writes_bytecode=False),
            )
            _live.add(child)
        try:
            child.communicate()
        except BaseException:
            # What `subprocess.run` did on the way out, kept: an interrupted wait kills the
            # child rather than leaving it running against a checkout about to be removed.
            child.kill()
            child.wait()
            raise
        finally:
            with _living:
                _live.discard(child)
        return Outcome(child.returncode, _executed(report))


class Stopped(RuntimeError):
    """`_run` was asked to start pytest after `_stop_runs`; the entry it was for is abandoned."""


_live: set[subprocess.Popen[bytes]] = set()
_living = threading.Lock()
_stopping = threading.Event()


def _stop_runs() -> None:
    """Terminate every pytest a job is waiting on, and refuse to start another.

    A job's pytest runs in a worker thread, where no signal reaches it, so without this a
    terminate would wait for every in-flight entry to run to its end — two whole pytest runs a
    job — before the checkouts could go. Under the same lock `_run` starts children with, so no
    child is started after the refusal is set and missed by the terminate.
    """
    with _living:
        _stopping.set()
        for child in _live:
            child.terminate()


def anchor_finding(text: str, before: str) -> str | None:
    """Why `before` cannot anchor a mutation in `text`, or `None` when it occurs exactly once.

    The one anchor rule: `_check` applies it inside a run, and `static_findings` before any.
    """
    occurrences = text.count(before)
    if occurrences == 0:
        return (
            "its `before` line is not in the file any more — the assertion and the line it is "
            "about have drifted apart, so update the entry or delete it"
        )
    if occurrences > 1:
        return f"its `before` line appears {occurrences} times; make it unique"
    return None


def collected_ids(root: Path, files: set[str]) -> frozenset[str] | None:
    """Every test id a collection of `files` under `root` yields, or `None` if it failed.

    The only way to see a parametrized id's bracketed part, which is built at collection time.
    One `--collect-only` over just the files that carry such ids, so under a second here.
    """
    if not files:
        return frozenset()
    try:
        done = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                *sorted(files),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return frozenset(line.strip() for line in done.stdout.splitlines() if "::" in line)


def undefined_tests(
    reddens: tuple[str, ...],
    root: Path,
    *,
    parsed: dict[Path, ast.Module | None] | None = None,
    collected: frozenset[str] | None = None,
) -> list[str]:
    """The ids in `reddens` that name no test of theirs.

    A plain id is resolved in its file's syntax tree: a top-level function, or a method of a
    top-level class, by name. So a test defined by assignment, by import, by inheritance or
    under an `if` reads as missing, and a function nested in another reads as present — neither
    shape exists in this repository's `reddens`. A parametrized id is looked up whole in
    `collected`, which `static_findings` computes once; given none, it is collected here.
    `parsed` is a parse cache the caller may share across calls.
    """
    cache: dict[Path, ast.Module | None] = {} if parsed is None else parsed
    if collected is None:
        bracketed = {node_id.split("::", 1)[0] for node_id in reddens if "[" in node_id}
        collected = collected_ids(root, bracketed) if bracketed else frozenset()
    missing: list[str] = []
    for node_id in reddens:
        path, *names = node_id.split("[", 1)[0].split("::")
        source = root / path
        if source not in cache:
            cache[source] = (
                ast.parse(source.read_text(encoding="utf-8")) if source.is_file() else None
            )
        scope: ast.AST | None = cache[source]
        for name in names:
            body = getattr(scope, "body", [])
            scope = next(
                (
                    node
                    for node in body
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                    and node.name == name
                ),
                None,
            )
        if scope is None or not names or ("[" in node_id and node_id not in (collected or ())):
            missing.append(node_id)
    return missing


# An action pinned by its full commit id, as `.github/dependabot.yml` keeps every `uses:` under
# `.github/workflows/` and rewrites on each bump.
_ACTION_PIN = re.compile(r"@[0-9a-f]{40}\b")


def static_findings(mutations: list[Mutation]) -> list[str]:
    """What is wrong with `mutations` that no pytest run is needed to see.

    A file that does not exist, a `before` that does not occur exactly once, a `reddens` id that
    names no test, an entry repeating another's `(file, before, after)` — which proves nothing
    the first did not, since an entry is caught when any of its ids reddens — a `name` another
    entry also carries, and a `before` in a workflow that quotes an action pin. A name is how
    every comment cites an entry (CONTRIBUTING.md, "Tests"), so two entries under one name make
    each such citation point at two guards, and the suite's citation test resolves a name to an
    entry only while there is one. A quoted pin stops occurring at Dependabot's next bump, and
    the entry then turns that pull request red on a change it did not make. Over the entries this
    is handed: an unfiltered run, and the suite, see every group file at once. One read and one
    parse per file, and one collection for every parametrized id.
    """
    findings: list[str] = []
    texts: dict[Path, str | None] = {}
    seen: dict[tuple[Path, str, str], str] = {}
    named: set[str] = set()
    for mutation in mutations:
        if mutation.file not in texts:
            texts[mutation.file] = (
                mutation.file.read_text(encoding="utf-8") if mutation.file.is_file() else None
            )
        text = texts[mutation.file]
        anchor = (
            f"{mutation.file.relative_to(ROOT)} does not exist"
            if text is None
            else anchor_finding(text, mutation.before)
        )
        if anchor is not None:
            findings.append(f"{mutation.name}: {anchor}")
        if mutation.file.is_relative_to(ROOT / ".github" / "workflows") and _ACTION_PIN.search(
            mutation.before
        ):
            findings.append(
                f"{mutation.name}: its `before` quotes an action pin Dependabot rewrites; anchor "
                "it on the step's other lines"
            )
        key = (mutation.file, mutation.before, mutation.after)
        if key in seen:
            findings.append(f"{mutation.name}: repeats the mutation of {seen[key]!r}")
        seen.setdefault(key, mutation.name)
        if mutation.name in named:
            findings.append(f"{mutation.name}: another entry is declared under this name")
        named.add(mutation.name)
    bracketed = {
        node_id.split("::", 1)[0] for m in mutations for node_id in m.reddens if "[" in node_id
    }
    collected = collected_ids(ROOT, bracketed)
    if collected is None:
        return [*findings, f"pytest could not collect {', '.join(sorted(bracketed))}"]
    parsed: dict[Path, ast.Module | None] = {}
    for mutation in mutations:
        findings.extend(
            f"{mutation.name}: {node_id} names no test"
            for node_id in undefined_tests(
                mutation.reddens, ROOT, parsed=parsed, collected=collected
            )
        )
    return findings


_SECOND = 1_000_000_000
_stamps = itertools.count(1)
_stamping = threading.Lock()


def _next_stamp() -> int:
    """A whole number of seconds no earlier mutated write in this process was offset by."""
    with _stamping:
        return next(_stamps)


def _check(mutation: Mutation, tree: Path, *, cache: Path | None = None) -> str | None:
    """`None` when the mutation was caught; the finding otherwise.

    Every read and write lands in `tree`, a throwaway checkout of HEAD, at the same path
    relative to `ROOT` the entry names. The working tree is never touched.

    **The clean-tree run comes first, and it is not a formality.** Without it this function
    read "the named tests did not pass" as "the mutation was caught" — and a mistyped test id
    makes pytest exit 4, which is not zero, which read as caught. So an entry could name
    `test_this_does_not_exist`, the oracle would print `caught`, CI would go green, and the
    guard it claims to prove would be provably unprotected. An oracle whose own failures look
    exactly like its successes is worse than no oracle.

    A run of zero tests is the same hole wearing a different face, so `Outcome.passed`
    demands that something actually ran: an entry whose tests are all skipped in this
    environment proves nothing here, and says so rather than banking the skip as a proof.

    **The mutated file's mtime is set, not left to the clock**, because `cache` may be warm (see
    `warm_cache`) and a `.pyc` is trusted on mtime-in-whole-seconds and size alone. The mutated
    bytes get HEAD's mtime plus a number of seconds no other write in this run has used, so no
    cached bytecode — HEAD's, or any a test's own subprocess might have written for an earlier
    mutation — can match them; HEAD's bytes get HEAD's mtime back, so HEAD's cached bytecode is
    valid again for the entries after this one. The stamp is read back rather than assumed,
    because a filesystem with coarser timestamps would round two stamps together silently.
    """
    subject = tree / mutation.file.relative_to(ROOT)
    if not subject.is_file():
        return f"{mutation.file.relative_to(ROOT)} does not exist"
    original = subject.read_text(encoding="utf-8")
    anchor = anchor_finding(original, mutation.before)
    if anchor is not None:
        return anchor
    clean = _run(mutation.reddens, tree, cache=cache)
    if not clean.passed:
        return (
            f"{', '.join(mutation.reddens)} did not pass on a clean tree "
            f"(pytest exited {clean.code}, {clean.executed} test(s) ran) — so nothing here can "
            "tell a mutation this entry caught from one it never tested; fix or rename them"
        )
    head = subject.stat()
    stamp = _next_stamp()
    subject.write_text(original.replace(mutation.before, mutation.after), encoding="utf-8")
    try:
        os.utime(subject, ns=(head.st_atime_ns, head.st_mtime_ns + stamp * _SECOND))
        if subject.stat().st_mtime_ns // _SECOND != head.st_mtime_ns // _SECOND + stamp:
            return (
                f"{mutation.file.relative_to(ROOT)} did not keep the mtime it was given, so "
                "cached bytecode could stand in for the mutated source — this filesystem cannot "
                "host the oracle's scratch checkout"
            )
        mutated = _run(mutation.reddens, tree, cache=cache)
    finally:
        subject.write_text(original, encoding="utf-8")
        os.utime(subject, ns=(head.st_atime_ns, head.st_mtime_ns))
    if mutated.code == 0:
        return f"survived — {', '.join(mutation.reddens)} still passed with the guard broken"
    # **The clean run's reasoning, applied to the mutated run, which is the half that was
    # left open.** The paragraphs above argue at length that an exit code alone cannot tell a
    # green assertion from an absent one — and then judged the mutated run by `mutated.code`
    # alone, computing `mutated.executed` and discarding it. A mutation that makes the module
    # unimportable exits 2 from a collection error, which is not zero, which read as `caught`
    # although the named test never ran. Demonstrated on a synthetic entry whose `after` was
    # `import a_module_that_does_not_exist`: `caught`, `all 1 mutations were caught`, exit 0.
    #
    # Not an equality with `clean.executed`, because a guard that legitimately stops one
    # parametrised case from being generated is a real thing; zero is the line, and a count
    # that fell is reported so a reader can judge it.
    if mutated.executed == 0:
        return (
            f"the mutation stopped {', '.join(mutation.reddens)} from running at all "
            f"({clean.executed} test(s) ran on the clean tree, 0 with the mutation applied) "
            "rather than reddening them — pytest's exit code says only that something went "
            "wrong, and this entry proves nothing about the guard"
        )
    return None


def _uncommitted(files: set[Path]) -> str | None:
    """`None` when every file is committed as it stands; the refusal otherwise.

    The oracle proves HEAD in a scratch checkout, so an uncommitted edit is simply work this
    run cannot see: the entry would be proved against the committed bytes while its author
    reads the result as being about the ones on screen. `main` therefore passes **both** the
    mutated files and the test files every selected entry's `reddens` names — an uncommitted
    edit to a test is as invisible to a HEAD checkout as one to a source, and the first draft
    of this guard swept only the sources.

    **"Could not ask" is not "clean"**: it
    read any non-zero `git` exit as a clean tree, which is precisely the state an unpacked
    sdist is in (`scripts/**` and `mutations/` ship in it, and it is not a checkout) and
    the state a broken `git` installation produces. `git status` exits 128 outside a
    repository, so the one arrangement with no way to recover a clobbered file was the one
    where the guard stood down.

    A `git` that cannot be launched at all raises rather than returning, and is caught here for
    the same reason: an oracle that cannot establish the precondition refuses, it does not
    proceed.
    """
    try:
        status = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain", "--", *sorted(str(f) for f in files)],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return (
            f"`git` could not be run ({exc}), so this cannot tell whether the files it is "
            "about to rewrite hold uncommitted work — refusing rather than risking it"
        )
    if status.returncode != 0:
        detail = status.stderr.strip() or f"exit {status.returncode}"
        return (
            f"`git status` could not answer here ({detail}), so this cannot tell whether the "
            "files it is about to rewrite hold uncommitted work — refusing rather than risking "
            "it. Run the oracle from a git checkout of the project"
        )
    if status.stdout.strip():
        return (
            "refusing: these files have uncommitted changes, and the oracle proves HEAD in a "
            "scratch checkout, so an edit here is work this run cannot see — commit first:\n"
            + status.stdout
        )
    return None


# The default ceiling on jobs, which `--jobs` lifts. Four is what CI's runner has, so the set is
# proved locally at the concurrency it is proved at there; on the maintainer's ten-core Mac eight
# jobs came to 321 s against 304 s for four, so the extra checkouts bought nothing. And every job
# is one more pytest beside the others, which is the assumption a `reddens` test that misbehaves
# under load would break — in the direction that reads as `caught`.
DEFAULT_JOBS = 4


def _available_cpus() -> int:
    """The CPUs this process may run on, which is what bounds useful parallelism."""
    if hasattr(os, "process_cpu_count"):  # 3.13
        return os.process_cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):  # Linux before 3.13
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"a whole number of jobs, not {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {value}")
    return value


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="mutation_oracle.py",
        description="Apply each mutation mutations/ declares and check the named tests go red.",
    )
    parser.add_argument(
        "pattern", nargs="?", default="", help="only entries whose name or file contains this"
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=_positive,
        default=None,
        help="entries proved at once, each in a scratch checkout of its own "
        f"(default: the CPUs available, at most {DEFAULT_JOBS})",
    )
    options = parser.parse_args(argv)
    pattern = options.pattern
    mutations = [
        m for m in declared() if not pattern or pattern in m.name or pattern in str(m.file)
    ]
    if not mutations:
        print(f"no mutation matches {pattern!r}", file=sys.stderr)
        return 1
    # Before any pytest run: a drifted anchor or a missing test is found in about a second
    # rather than at the end of a run that takes most of CI's oracle budget.
    static = static_findings(mutations)
    if static:
        for finding in static:
            print(f"FINDING  {finding}", file=sys.stderr)
        print(f"\n{len(static)} declaration finding(s); nothing was run", file=sys.stderr)
        return 1
    named_tests = {ROOT / target.split("::", 1)[0] for m in mutations for target in m.reddens}
    watched = {m.file for m in mutations} | {path for path in named_tests if path.is_file()}
    dirty = _uncommitted(watched)
    if dirty is not None:
        print(dirty, file=sys.stderr)
        return 1

    # The lock is taken before the sweep and held to the end, because the sweep is the
    # destructive half: `sweep_stale_scratch` removes every scratch checkout but this run's, and
    # "but this run's" is only safe while there is one run. A second oracle refuses here rather
    # than deleting the first one's tree.
    jobs = min(options.jobs or min(_available_cpus(), DEFAULT_JOBS), len(mutations))
    try:
        with single_run():
            return _prove(mutations, jobs)
    except ConcurrentRun as exc:
        print(exc, file=sys.stderr)
        return 1


def _prove(mutations: list[Mutation], jobs: int) -> int:
    """Sweep, then apply every mutation across `jobs` scratch checkouts. Called holding the lock.

    **One checkout per job, and a checkout is only ever in one job's hands.** Two entries
    mutating one tree at once would interleave their writes over a shared file and each would
    run against the other's mutation — the very hazard the scratch checkout exists to remove,
    moved inside the oracle. So the checkouts sit in a queue: a job takes one, proves one entry
    in it, restores it and puts it back. There are exactly as many threads as checkouts, which
    is what keeps a job from ever waiting on the queue for long; the threads only wait on
    pytest, so the interpreter lock is not what bounds them.

    **Which makes one assumption the sequential oracle did not: every test a `reddens` names is
    safe to run beside another in a separate process.** The suite isolates `HOME` per test and
    works under `tmp_path`, so nothing found so far shares state; a test that did — or that
    carries a wall-clock bound contention could break — would fail on the mutated run for a
    reason that is not the mutation, and that reads as `caught`.

    Per-entry lines are printed as entries finish, which is not declaration order once there is
    more than one job; the findings summary is sorted back into declaration order so two runs
    of one tree report alike.
    """
    # Housekeeping before the run, not after it: a `SIGKILL` runs no `finally`, so the entries
    # an earlier killed run left behind are cleared here or never. `git worktree prune` alone
    # does not do it — it only drops entries whose directory is gone, and these leave theirs.
    swept = sweep_stale_scratch()
    for leaked in swept:
        print(f"swept a leaked scratch checkout: {leaked}", file=sys.stderr)

    findings: dict[int, str] = {}
    _stopping.clear()
    try:
        with contextlib.ExitStack() as stack:
            trees = [stack.enter_context(scratch_checkout()) for _ in range(jobs)]
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                free: queue.SimpleQueue[tuple[Path, Path]] = queue.SimpleQueue()
                for tree, cache in zip(trees, pool.map(warm_cache, trees), strict=True):
                    free.put((tree, cache))

                def prove(mutation: Mutation) -> str | None:
                    tree, cache = free.get()
                    try:
                        return _check(mutation, tree, cache=cache)
                    finally:
                        free.put((tree, cache))

                try:
                    pending: dict[Future[str | None], int] = {
                        pool.submit(prove, mutation): index
                        for index, mutation in enumerate(mutations)
                    }
                    for done in as_completed(pending):
                        index = pending[done]
                        finding = done.result()
                        mark = "caught " if finding is None else "FINDING"
                        print(f"{mark}  {mutations[index].name}", flush=True)
                        if finding is not None:
                            findings[index] = f"{mutations[index].name}: {finding}"
                except BaseException:
                    # A terminate, an interrupt or an entry that raised: stop handing out
                    # entries and end the pytest runs in flight, then wait for the jobs to let
                    # go — so no pytest is left running orphaned, and none is still writing into
                    # a checkout while `rmtree` walks it, which would leave a half-removed tree
                    # for the next run's sweep.
                    _stop_runs()
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise
    except WorktreeUnavailable as exc:
        print(
            f"could not create a scratch worktree of HEAD ({exc}); the oracle never mutates "
            "the working tree, so there is nothing to fall back to",
            file=sys.stderr,
        )
        return 1
    print()
    if findings:
        for _, finding in sorted(findings.items()):
            print(f"  {finding}", file=sys.stderr)
        print(f"\n{len(findings)} of {len(mutations)} mutations were not caught", file=sys.stderr)
        return 1
    print(f"all {len(mutations)} mutations were caught")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
