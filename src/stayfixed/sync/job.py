"""The note sync's job: commit the overlay's notes, take in upstream's, push its own.

Each step is bounded in time and records what it did in the context the job's state is written
from: guard; align the real index first where a killed job left that owed; pre-render the indexes
(`sync.render`); commit memory through a temporary index; fetch `origin main` into the job's own
ref; integrate that sha, only when everything it brings is memory, by replay; resolve a conflict
confined to rendered indexes by union; push the checked range.

It never writes a non-memory path of the working tree or the real index, stashes, rebases, pulls
or force-pushes. Every move of `main` is a compare-and-swap recorded before it is made, and is
followed by aligning the real index's memory entries with the new `HEAD`, or the owner's next
`git commit` would carry the old notes back.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stayfixed import fsops
from stayfixed.config.overlay import overlay_root
from stayfixed.sync import scan
from stayfixed.sync.git import (
    UNMERGED,
    GitError,
    GitTimeout,
    Ran,
    checked,
    git,
    guard,
    job_env,
    timed,
)
from stayfixed.sync.render import prerender, unsafe_parent
from stayfixed.sync.rules import (
    MEMORY_PATHSPEC,
    MEMORY_SPECS,
    RawEntry,
    commit_entries,
    dirty_memory,
    entry_offends,
    index_of,
    is_memory_path,
    memory_path,
    offending_paths,
    range_is_memory_only,
)
from stayfixed.sync.state import (
    EMPTY_HOLDS,
    LOCK_FILE,
    PENDING_FILE,
    SCRATCH,
    SLEEPER_LOCK_FILE,
    THROTTLE_SECONDS,
    Holds,
    Lock,
    Outcome,
    PendingAlign,
    StateUnreadable,
    SyncState,
    iso,
    mark_pending,
    parse_time,
    read_state,
    state_directory,
    take_pending,
    write_state,
)
from stayfixed.sync.switch import enabled

# Named caps on the alignment's wait for an `index.lock` the owner's own git holds: five tries a
# fifth of a second apart, past which the job records `index_stale`. No shipped file states them.
ALIGN_RETRIES = 5
ALIGN_PAUSE_SECONDS = 0.2
ALIGN_COMMAND = "git reset -q -- " + " ".join(f"'{spec}'" for spec in MEMORY_PATHSPEC)
SWAP_MESSAGE = "stayfixed note sync"


@dataclass(frozen=True)
class Limits:
    """Wall-clock limits in seconds, each a named cap no shipped file states: the network calls,
    both commit checks together, both push scans together, the whole job, and any other single
    git call. Injectable, so a test can wait one second where the job waits sixty."""

    fetch: float = 30.0
    push: float = 30.0
    checks: float = 60.0
    job: float = 180.0
    local: float = 30.0


class JobTimeout(Exception):
    """The whole job ran out of time; the job records `timeout` with this message."""


class JobStopped(Exception):
    """A step ended the job with this outcome from deep inside (a signing failure in a replay)."""

    def __init__(self, outcome: Outcome) -> None:
        super().__init__(outcome.state)
        self.outcome = outcome


@dataclass
class JobContext:
    """What one job run carries between its steps. `remarks` are what the end's detail also says
    (an index left out, a hold and how to review it); `notices` the ends that do not stop the job
    (a failed commit check, a path not written, indexes united); `pending` the alignment still
    owed; `refused` the memory-named paths left out of a commit because they are not notes;
    `holds` as this job leaves them, changed only by integration and push."""

    overlay: Path
    state_dir: Path
    home: Path
    host: str
    now: Callable[[], datetime]
    limits: Limits = field(default_factory=Limits)
    deadline: float | None = None
    remarks: list[str] = field(default_factory=list)
    notices: list[Outcome] = field(default_factory=list)
    pending: PendingAlign | None = None
    fetched_sha: str | None = None
    resolved: set[str] = field(default_factory=set)
    refused: list[str] = field(default_factory=list)
    holds: Holds = EMPTY_HOLDS
    _env: dict[str, str] | None = field(default=None, repr=False)

    def limit(self, step: float) -> float:
        """`step`, cut to what is left of the whole job; `JobTimeout` when nothing is."""
        if self.deadline is None:
            return step
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise JobTimeout(f"the job did not finish within {self.limits.job:g} s")
        return min(step, left)

    @property
    def env(self) -> dict[str, str]:
        """What every git call of the job is given (`sync.git.job_env`), built once."""
        if self._env is None:
            self._env = job_env(self.overlay, timeout=self.limit(self.limits.local))
        return self._env


def _outcome(ctx: JobContext, state: str, detail: str | None = None) -> Outcome:
    return Outcome(state, iso(ctx.now()), detail)


def _git(
    ctx: JobContext,
    *args: str,
    timeout: float | None = None,
    index_file: Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin: bytes | None = None,
) -> Ran:
    return git(
        ctx.overlay,
        *args,
        timeout=ctx.limit(ctx.limits.local if timeout is None else timeout),
        env={**ctx.env, **(env or {})},
        index_file=index_file,
        stdin=stdin,
    )


def _ok(
    ctx: JobContext, *args: str, index_file: Path | None = None, stdin: bytes | None = None
) -> str:
    """`git <args>` that must succeed; its standard output."""
    return checked(_git(ctx, *args, index_file=index_file, stdin=stdin), f"git {args[0]}").out


def _nul(text: str) -> list[str]:
    return [item for item in text.split("\0") if item]


def _rev(ctx: JobContext, rev: str) -> str:
    return _ok(ctx, "rev-parse", "--verify", "-q", "--end-of-options", f"{rev}^{{commit}}").strip()


def _literal(path: str) -> str:
    """A pathspec that matches exactly `path`, whatever characters it holds."""
    return f":(top,literal){path}"


def _paths_in(paths: Iterable[str]) -> bytes:
    """`paths` NUL-terminated, for a git command reading them from standard input."""
    return b"".join(path.encode("utf-8", "surrogateescape") + b"\0" for path in paths)


@contextlib.contextmanager
def _scratch(ctx: JobContext) -> Iterator[Path]:
    """The job's one scratch directory, `scratch/` in the state directory: emptied for one use
    (temporary indexes, a union's blobs, scan reports), removed whole after it, never two uses at
    once. A fixed name, so a killed job's leftovers are removed by the next."""
    directory = ctx.state_dir / SCRATCH
    ctx.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(mode=0o700)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _blobs(ctx: JobContext, rev: str) -> dict[str, tuple[str, str]]:
    """`{path: (mode, sha)}` for every memory path in `rev`'s tree."""
    found: dict[str, tuple[str, str]] = {}
    for entry in _nul(_ok(ctx, "ls-tree", "-r", "-z", "--full-tree", "--end-of-options", rev)):
        meta, _, path = entry.partition("\t")
        mode, _, sha = meta.split(" ")[:3]
        if is_memory_path(path):
            found[path] = (mode, sha)
    return found


def _worktree_has(ctx: JobContext, path: str, blob: tuple[str, str] | None) -> bool:
    """Whether the working tree holds `blob` at `path` (`None`: holds nothing there)."""
    full = ctx.overlay / path
    if unsafe_parent(ctx.overlay, path) is not None:
        return False
    if blob is None:
        return not (fsops.exists(full) or fsops.is_symlink(full))
    if fsops.is_symlink(full) or not fsops.is_file(full):
        return False
    return _ok(ctx, "hash-object", "--", path).strip() == blob[1]


# -- the commit through a temporary index ---------------------------------------------------------


def _before_swap() -> None:
    """Nothing; the moment between building a commit and moving `main` (a test seam)."""


def _reset_paths(ctx: JobContext, index: Path, rev: str, paths: Iterable[str]) -> None:
    """Put `paths` in the temporary `index` back to what `rev` has (or nothing)."""
    specs = [_literal(path) for path in paths]
    if specs:
        _ok(ctx, "reset", "-q", "--end-of-options", rev, "--", *specs, index_file=index)


def _refuse(ctx: JobContext, paths: Iterable[str]) -> None:
    """Name `paths` as left out of the commit; the job goes on, and its end names them."""
    ctx.refused.extend(path for path in paths if path not in ctx.refused)


def _staged(ctx: JobContext, index: Path, rev: str, *only: str) -> list[str]:
    """The paths `index` stages against `rev`, of the `--diff-filter` letters in `only`."""
    filters = (f"--diff-filter={''.join(only)}",) if only else ()
    return _nul(
        _ok(
            ctx, "diff", "--cached", "--name-only", "-z", "--no-renames", *filters,
            "--end-of-options", rev, "--", index_file=index,
        )
    )  # fmt: skip


def _message(ctx: JobContext, paths: list[str]) -> bytes:
    parsed = [entry for entry in map(memory_path, paths) if entry is not None]
    notes = sum(1 for entry in parsed if not entry.is_index)
    scopes = "\n".join(sorted({entry.root.rpartition("/")[0] for entry in parsed}))
    return f"memory: {notes} notes from {ctx.host}\n\n{scopes}\n".encode()


def _signing(ctx: JobContext) -> bool:
    """Whether `commit.gpgsign` asks for a signature; a timed-out answer is never "no"."""
    answer = timed(_git(ctx, "config", "--type=bool", "--get", "commit.gpgsign"), "git config")
    return answer.code == 0 and answer.out.strip() == "true"


def _commit_tree(
    ctx: JobContext,
    tree: str,
    parents: list[str],
    message: bytes,
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, Outcome | None]:
    """`git commit-tree` with `message` on standard input, signed when `commit.gpgsign` says so:
    the sha, or `signing_failed`. Signing asked for is never switched off."""
    signed = ("-S",) if _signing(ctx) else ()
    parented = tuple(part for parent in parents for part in ("-p", parent))
    result = _git(
        ctx, "commit-tree", *parented, *signed, "--end-of-options", tree, env=env, stdin=message
    )
    if signed and (result.timed_out or result.code != 0):
        said = scan.first_lines(result.err) or (
            "waited for a passphrase" if result.timed_out else ""
        )
        detail = f"commit.gpgsign is set and signing failed: {said}"
        return None, _outcome(ctx, "signing_failed", detail)
    return checked(result, "git commit-tree").out.strip(), None


def _swap(ctx: JobContext, new: str, old: str) -> bool:
    """Move `main` from `old` to `new` only if it is still at `old`."""
    result = _git(
        ctx, "update-ref", "-m", SWAP_MESSAGE, "--end-of-options", "refs/heads/main", new, old
    )
    return timed(result, "git update-ref").code == 0


def _unmerged_now(ctx: JobContext) -> Outcome | None:
    """`skipped` when the real index holds unmerged entries now, asked right before every move of
    `main`: a `stash pop` that conflicts while the job runs leaves notes holding conflict markers,
    which a commit would carry and the alignment's reset would erase from the owner's view."""
    found = timed(_git(ctx, "ls-files", "--unmerged", "-z"), "git ls-files")
    if found.code != 0 or found.out:
        return _outcome(ctx, "skipped", UNMERGED)
    return None


def _record_pending(ctx: JobContext, pending: PendingAlign | None) -> None:
    """Write `pending` into the state on disk before `main` moves, so a kill after the move is
    finished by the next job (and `None` back when the move did not happen). The rest of the state
    is kept as the file has it, or started afresh when it is unreadable or another overlay's."""
    try:
        previous = read_state(ctx.state_dir)
    except StateUnreadable:
        previous = None  # the job replaces it at its end anyway
    if previous is None or previous.overlay != str(ctx.overlay):
        said = "a job was stopped while moving main; the next job finishes it"
        previous = SyncState(
            str(ctx.overlay), _outcome(ctx, "skipped", said), EMPTY_HOLDS, None, None, None
        )
    write_state(ctx.state_dir, replace(previous, pending_align=pending))


def _move_main(ctx: JobContext, pending: PendingAlign) -> bool:
    """Move `main` from `pending.from_sha` to `pending.to_sha` by compare-and-swap: whether it
    moved. The record is on disk before the swap, so a kill after it is finished by the next job
    (`align_first`), and taken back when `main` had moved meanwhile."""
    _record_pending(ctx, pending)
    ctx.pending = pending
    _before_swap()
    if _swap(ctx, pending.to_sha, pending.from_sha):
        return True
    ctx.pending = None
    _record_pending(ctx, None)
    return False


def _run_checks(ctx: JobContext, index: Path, paths: list[str]) -> Outcome | None:
    """The secret scan of what `index` stages, before any tree is written; the failure, if any."""
    binary = scan.gitleaks_binary(ctx.home, ctx.overlay)
    if binary is None:
        detail = scan.NO_SCANNER.format(overlay=ctx.overlay)
        return _outcome(ctx, "scan_unavailable", detail)
    result = scan.scan_index(
        ctx.overlay, index, binary, ctx.limit(ctx.limits.checks), env=ctx.env, scratch=index.parent
    )
    if result.ok:
        return None
    state = "timeout" if result.timed_out else "hook_failed"
    return _outcome(ctx, state, f"gitleaks: {result.detail}")


def commit_memory(ctx: JobContext, *, also: Iterable[str] = ()) -> Outcome | None:
    """Pre-render, then commit every memory change; the outcome that stops the job (`raced`,
    `skipped`, `timeout`, `index_stale`), or `None`.

    A failed scan, no scanner or a failed signature does not stop it: what is already committed
    still integrates and pushes. It is a notice, and nothing is committed. Paths that are not
    notes are left out and named (`_refuse`); the notes beside them are committed. `also` names
    projects to render whatever changed (a union's, whose lines the render harvests).

    Built in a temporary index read from `HEAD`. Apart from the indexes the pre-render writes,
    the working tree and the real index are only read until `main` has moved; after that, only
    the real index's memory entries are touched (`align`).
    """
    also = tuple(also)
    dirty = dirty_memory(ctx.overlay, timeout=ctx.limit(ctx.limits.local), env=ctx.env)
    if not dirty and not also:
        return None
    ctx.limit(ctx.limits.job)  # the render is in process: only the job's own deadline bounds it
    left_out = prerender(ctx.overlay, dirty, ctx.state_dir, also=also)
    for project, reason in sorted(left_out.items()):
        ctx.remarks.append(f"{index_of(project)} left out of the commit: {reason}")
    old = _rev(ctx, "HEAD")
    with _scratch(ctx) as scratch:
        index = scratch / "index"
        _ok(ctx, "read-tree", "--end-of-options", old, index_file=index)
        for spec, root in MEMORY_SPECS:
            link = unsafe_parent(ctx.overlay, f"{root}/-")
            if link is not None:
                _refuse(ctx, [link])  # nothing behind it is added, nothing deleted
                continue
            added = _git(ctx, "add", "-A", "--", spec, index_file=index)
            if added.code == 128 and "did not match any files" in added.err:
                continue  # nothing under this pathspec at all: an overlay without projects
            checked(added, "git add")
        _reset_paths(ctx, index, old, [index_of(project) for project in left_out])
        # A link in place of `projects/<p>` or its `memory` hides the notes behind it from
        # `git add -A`, which then stages each as deleted: not the owner's deletions. A literal
        # reset of the link's path puts back everything below it.
        deleted = (unsafe_parent(ctx.overlay, path) for path in _staged(ctx, index, old, "D"))
        beyond = list(dict.fromkeys(link for link in deleted if link is not None))
        _reset_paths(ctx, index, old, beyond)
        _refuse(ctx, beyond)
        refused = offending_paths(
            ctx.overlay, "--cached", old, index_file=index, timeout=ctx.limit(ctx.limits.local),
            env=ctx.env,
        )  # fmt: skip
        _reset_paths(ctx, index, old, refused)
        _refuse(ctx, refused)
        paths = _staged(ctx, index, old)
        if not paths:
            return None
        new = None
        failed = _run_checks(ctx, index, paths)
        if failed is None:
            tree = _ok(ctx, "write-tree", index_file=index).strip()
            new, failed = _commit_tree(ctx, tree, [old], _message(ctx, paths))
    if new is None:
        if failed is not None and failed.state == "timeout":
            return failed  # what is left of the job's time is not enough to go on
        ctx.notices.extend([failed] if failed is not None else [])
        return None
    # No paths to write: the working tree was this commit's source, so the alignment owes the
    # index only, and a note the owner changed or removed since stays as the owner left it.
    pending = PendingAlign(old, new, ())
    unmerged = _unmerged_now(ctx)
    if unmerged is not None:
        return unmerged
    if not _move_main(ctx, pending):
        detail = (
            "main moved while the memory commit was built; nothing was lost, the next job retries"
        )
        return _outcome(ctx, "raced", detail)
    return _settle(ctx, pending)


# -- aligning the real index ----------------------------------------------------------------------


def _prune_empty(overlay: Path, path: str) -> None:
    """Remove directories a removal left empty, up to (never including) the memory root."""
    parsed = memory_path(path)
    if parsed is None:
        return
    parts = path.split("/")[:-1]
    while len(parts) > len(parsed.root.split("/")):
        try:
            fsops.rmdir_within(overlay, "/".join(parts))
        except OSError:
            return
        parts.pop()


def _finish_worktree(ctx: JobContext, pending: PendingAlign) -> list[str]:
    """Write the paths a move of `main` brought in, where the working tree still has the old; the
    paths it may not write, because a link or a file stands above them.

    Only a path still at its `from` version is written (the owner's later edit wins), only one
    `HEAD` still has at its `to` version, and only through git (`checkout-index` from a temporary
    index) or `fsops`, after checking no directory above it is a link.
    """
    if not pending.paths or not _is_ancestor(ctx, pending.to_sha, "HEAD"):
        return []  # nothing to write, or `main` never moved to `to`
    head, to = _blobs(ctx, "HEAD"), _blobs(ctx, pending.to_sha)
    before = _blobs(ctx, pending.from_sha)
    refused: list[str] = []
    writes: list[str] = []
    for path in pending.paths:
        want = to.get(path)
        if head.get(path) != want or _worktree_has(ctx, path, want):
            continue
        if unsafe_parent(ctx.overlay, path) is not None:
            refused.append(path)
            continue
        if not _worktree_has(ctx, path, before.get(path)):
            continue  # changed by hand since: left for the next commit
        if want is None:
            fsops.remove_within(ctx.overlay, path)
            _prune_empty(ctx.overlay, path)
        else:
            writes.append(path)
    if writes:
        with _scratch(ctx) as scratch:
            index = scratch / "index"
            _ok(ctx, "read-tree", "--end-of-options", pending.to_sha, index_file=index)
            _ok(
                ctx,
                "checkout-index",
                "-f",
                "-z",
                "--stdin",
                index_file=index,
                stdin=_paths_in(writes),
            )
    return refused


def align(ctx: JobContext, pending: PendingAlign | None) -> Outcome | None:
    """Make the real index's memory entries equal `HEAD`'s; `index_stale`, which stops the job,
    if it cannot.

    With `pending` (a move of `main` that brought paths in), those paths are first written to the
    working tree where it still holds their old version. The reset is retried while another git
    holds `index.lock`. A path that could not be written (a link above it) leaves the index
    aligned and is a notice, `hook_failed` naming it: the job does not pretend it arrived.
    """
    refused = _finish_worktree(ctx, pending) if pending is not None else []
    result: Ran | None = None
    for attempt in range(ALIGN_RETRIES + 1):
        result = _git(ctx, "reset", "-q", "--", *MEMORY_PATHSPEC)
        if result.code == 0 and not result.timed_out:
            if refused:
                detail = "job: not written, a link or a file stands above it: " + ", ".join(refused)
                ctx.notices.append(_outcome(ctx, "hook_failed", detail))
            return None
        if "index.lock" not in result.err or attempt == ALIGN_RETRIES:
            break
        time.sleep(ALIGN_PAUSE_SECONDS)
    said = (
        (scan.first_lines(result.err).splitlines() or ["no answer"])[0] if result else "no answer"
    )
    detail = (
        f"the index's memory entries could not be aligned with HEAD ({said}); the next job "
        f"retries first, or run: {ALIGN_COMMAND}"
    )
    return _outcome(ctx, "index_stale", detail)


def _index_needs_align(ctx: JobContext) -> bool:
    """The shape a killed job leaves: memory entries of the index differ from `HEAD` while the
    working tree equals `HEAD` at those paths. The owner's own staging (the tree differs too) is
    not it."""
    staged = _nul(
        _ok(
            ctx, "--no-optional-locks", "diff", "--cached", "--name-only", "-z", "--no-renames",
            "HEAD", "--", *MEMORY_PATHSPEC,
        )
    )  # fmt: skip
    if not staged:
        return False
    head = _blobs(ctx, "HEAD")
    return any(_worktree_has(ctx, path, head.get(path)) for path in staged)


def _settle(ctx: JobContext, pending: PendingAlign | None) -> Outcome | None:
    """`align`, then drop `ctx.pending` unless the alignment is still owed (`index_stale`)."""
    stale = align(ctx, pending)
    if stale is None:
        ctx.pending = None
    return stale


def align_first(ctx: JobContext) -> Outcome | None:
    """Before the commit: finish an alignment a previous job owes (`ctx.pending`, or the shape).

    A record whose move never happened -- the job was killed between writing it and the swap --
    owes nothing, and is dropped without touching the index: the owner's staged notes stay staged.
    """
    pending = ctx.pending
    if pending is not None and not _is_ancestor(ctx, pending.to_sha, "HEAD"):
        ctx.pending = pending = None
    if pending is None and not _index_needs_align(ctx):
        return None
    return _settle(ctx, pending)


# -- fetch ----------------------------------------------------------------------------------------

# What git and ssh print when the remote cannot be reached, and when it refuses who we are; the
# second is matched first, since an HTTPS refusal also says "unable to access".
_OFFLINE = (
    "could not resolve host", "could not resolve hostname", "network is unreachable",
    "no route to host", "connection refused", "connection timed out", "operation timed out",
    "connection reset", "temporary failure in name resolution", "connection closed by",
    "unable to access",
)  # fmt: skip
_AUTH = (
    "permission denied", "authentication failed", "could not read username",
    "could not read password", "host key verification failed", "terminal prompts disabled",
    "invalid username or password", "returned error: 401", "returned error: 403",
)  # fmt: skip
FETCHED_REF = "refs/stayfixed/fetched"


def _remote_failure(ctx: JobContext, result: Ran, what: str, limit: float) -> Outcome:
    """`timeout`, `auth_failed`, `offline`, or `hook_failed` naming the job, for a network call."""
    said = scan.first_lines(result.err) or scan.first_lines(result.out) or f"exit {result.code}"
    if result.timed_out:
        return _outcome(ctx, "timeout", f"{what} did not finish within {limit:g} s")
    text = result.err.lower()
    if any(pattern in text for pattern in _AUTH):
        return _outcome(ctx, "auth_failed", f"{what}: {said}")
    if any(pattern in text for pattern in _OFFLINE):
        return _outcome(ctx, "offline", f"{what}: {said}")
    return _outcome(ctx, "hook_failed", f"job: {what} failed: {said}")


def fetch(ctx: JobContext) -> tuple[str | None, Outcome | None]:
    """`git fetch origin main` into the job's own ref; the fetched sha, or the failure.

    The sha is read once, here, from that ref, never `FETCH_HEAD`, which the owner's own fetch
    rewrites at any moment: a second pusher, or the owner's fetch, changes nothing this job
    integrates. Every object received is checked (`fetch.fsckObjects`), so a tree holding a `..`
    or `.git` name is refused before any rule reads it. No tag, no submodule.
    """
    limit = ctx.limit(ctx.limits.fetch)
    result = _git(
        ctx, "-c", "fetch.fsckObjects=true", "fetch", "--no-tags", "--no-recurse-submodules",
        "origin", f"+refs/heads/main:{FETCHED_REF}", timeout=limit,
    )  # fmt: skip
    if result.timed_out or result.code != 0:
        return None, _remote_failure(ctx, result, "git fetch origin main", limit)
    upstream = _rev(ctx, FETCHED_REF)
    ctx.fetched_sha = upstream
    return upstream, None


# -- integrate by replay, and the index union -----------------------------------------------------

# How the owner takes a held range or integrates a fetched sha by hand: read all of it, memory
# included, and take it at the sha that was held and read, never at `origin/main`, which the next
# fetch moves past it. A rebase rather than a fast-forward, since the notes committed here usually
# sit beside the held sha; with none, it is a fast-forward.
REVIEW = "git log -p --no-renames HEAD..{sha}, then git rebase {sha}"
_AUTHOR = re.compile(r"author (.*) <([^<>]*)> (\d+ [+-]\d{4})")


def union_index(local: bytes, upstream: bytes) -> bytes:
    """The upstream index plus every bullet line only the local one has, in local order: a line
    an agent appended survives whichever side committed first, for the next render to harvest."""
    present = set(upstream.splitlines())
    extra: list[bytes] = []
    for line in local.splitlines():
        if line.startswith(b"- ") and line not in present:
            extra.append(line)
            present.add(line)
    if not extra:
        return upstream
    base = upstream if not upstream or upstream.endswith(b"\n") else upstream + b"\n"
    return base + b"".join(line + b"\n" for line in extra)


def _blob(ctx: JobContext, rev: str, path: str) -> bytes | None:
    """`path`'s content in `rev`; `None` when `rev` has no such file."""
    return scan.blob(ctx.overlay, f"{rev}:{path}", ctx.limit(ctx.limits.local), ctx.env)


def _entry(ctx: JobContext, path: str, data: bytes) -> bytes:
    """`data` written as a blob, and the `update-index -z --index-info` line naming it at `path`."""
    sha = _ok(ctx, "hash-object", "-w", "--stdin", stdin=data).strip()
    return f"100644 {sha}\t{path}".encode("utf-8", "surrogateescape") + b"\0"


def _resolve_by_union(
    ctx: JobContext, scratch: Path, tree: str, tip: str, commit: str, conflicted: list[str]
) -> str | None:
    """`tree` with each conflicted index replaced by its union; `None` if one cannot be."""
    parsed = [memory_path(path) for path in conflicted]
    if not conflicted or not all(entry is not None and entry.is_index for entry in parsed):
        return None
    entries = b""
    for path in conflicted:
        upstream, local = _blob(ctx, tip, path), _blob(ctx, commit, path)
        if upstream is None or local is None:
            return None  # deleted on one side: not a pair of renderings to unite
        entries += _entry(ctx, path, union_index(local, upstream))
    index = scratch / "union-index"
    index.unlink(missing_ok=True)
    _ok(ctx, "read-tree", "--end-of-options", tree, index_file=index)
    _ok(ctx, "update-index", "-z", "--index-info", index_file=index, stdin=entries)
    return _ok(ctx, "write-tree", index_file=index).strip()


def _original(ctx: JobContext, commit: str) -> tuple[dict[str, str], bytes]:
    """`commit`'s author, as the environment that names it, and its message as bytes, its
    `encoding` header given back as a `git -c`-style entry: from the commit object itself, never
    `git log --format`, which `log.showSignature` prefixes with the signature check."""
    raw = _ok(ctx, "cat-file", "commit", "--end-of-options", commit)
    header, _, message = raw.encode("utf-8", "surrogateescape").partition(b"\n\n")
    env: dict[str, str] = {}
    for line in header.decode("utf-8", "surrogateescape").split("\n"):
        if (author := _AUTHOR.fullmatch(line)) is not None:
            name, email, date = author.groups()
            env.update(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_DATE=date)
        elif line.startswith("encoding "):
            encoding = line.removeprefix("encoding ")
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="i18n.commitEncoding")
            env.update(GIT_CONFIG_VALUE_0=encoding)
    if "GIT_AUTHOR_NAME" not in env:
        raise GitError(f"commit {commit} has no readable author line")
    return env, message


def replay(ctx: JobContext, onto: str, commits: list[str]) -> tuple[str | None, list[str]]:
    """Replay `commits` (oldest first) onto `onto`: the new tip, or `None` and the paths that
    conflict. Each is `merge-tree --write-tree --merge-base=c^ tip c` and `commit-tree` with `c`'s
    author and message, so nothing touches the working tree or the real index; a conflict confined
    to rendered indexes is resolved by union. A failed signature stops the job (`JobStopped`)."""
    tip = onto
    with _scratch(ctx) as scratch:
        for commit in commits:
            result = _git(
                ctx, "merge-tree", "--write-tree", "-z", "--name-only", "--no-messages",
                f"--merge-base={commit}^", "--end-of-options", tip, commit,
            )  # fmt: skip
            if timed(result, "git merge-tree").code not in (0, 1):
                checked(result, "git merge-tree")
            tree, *conflicted = _nul(result.out)
            if result.code == 1:
                resolved = _resolve_by_union(ctx, scratch, tree, tip, commit, conflicted)
                if resolved is None:
                    return None, conflicted
                ctx.resolved.update(_projects(conflicted))
                tree = resolved
            own = _tree_of(ctx, commit) == _tree_of(ctx, f"{commit}^")
            if tree == _tree_of(ctx, tip) and not own:
                # Already upstream: an empty commit would list no path, and be held. One that
                # was empty in its own right (`--allow-empty`) is the owner's, and is kept.
                continue
            author, message = _original(ctx, commit)
            new, failed = _commit_tree(ctx, tree, [tip], message, env=author)
            if failed is not None or new is None:
                raise JobStopped(failed or _outcome(ctx, "hook_failed", "job: no commit made"))
            tip = new
    return tip, []


def _tree_of(ctx: JobContext, rev: str) -> str:
    return _ok(ctx, "rev-parse", "--verify", "-q", "--end-of-options", f"{rev}^{{tree}}").strip()


def _projects(paths: Iterable[str]) -> list[str]:
    """The projects whose memory `paths` lie in, once each."""
    found = (memory_path(path) for path in paths)
    return list(dict.fromkeys(e.name for e in found if e and e.scope == "project" and e.name))


def _blocked(ctx: JobContext, incoming: list[str]) -> tuple[list[str], list[str]]:
    """The incoming paths the working tree is not ready for -- dirty there (or a dirty path above
    or below one), or reached through a link or a file where git needs a directory -- and the
    dirty indexes to unite instead once `main` has moved: an index holds no work in progress, only
    a rendering and lines agents appended, which the union keeps."""
    dirty = dirty_memory(ctx.overlay, timeout=ctx.limit(ctx.limits.local), env=ctx.env)
    blocked: list[str] = []
    unite: list[str] = []
    for path in incoming:
        if unsafe_parent(ctx.overlay, path) is not None or fsops.is_symlink(ctx.overlay / path):
            blocked.append(path)
            continue
        clashes = [
            entry
            for entry in dirty
            if entry == path
            or path.startswith(entry.rstrip("/") + "/")
            or entry.startswith(path + "/")
        ]
        parsed = memory_path(path)
        if clashes == [path] and parsed is not None and parsed.is_index:
            unite.append(path)
        elif clashes:
            blocked.append(path)
    return blocked, unite


def _hold_upstream(ctx: JobContext, paths: Iterable[str], remark: str) -> None:
    """Hold upstream on `paths`, with `remark`, which says why and how to review it."""
    ctx.remarks.append(remark)
    ctx.holds = replace(ctx.holds, upstream_paths=tuple(paths))


def _unite_worktree(ctx: JobContext, tip: str, path: str) -> bool:
    """Write the union of the index at `path`, as the working tree has it, and `tip`'s into the
    working tree, through git; whether it was written. Not when `tip` has no such index, nor when
    the file changed while the union was built (an agent appending its line)."""
    full = ctx.overlay / path
    upstream = _blob(ctx, tip, path)
    if upstream is None or fsops.is_symlink(full) or unsafe_parent(ctx.overlay, path):
        return False
    local = _read(full)
    if local is None:
        return False
    with _scratch(ctx) as scratch:
        index = scratch / "index"
        entry = _entry(ctx, path, union_index(local, upstream))
        _ok(ctx, "update-index", "-z", "--index-info", index_file=index, stdin=entry)
        if _read(full) != local:
            return False
        _ok(ctx, "checkout-index", "-f", "-z", "--stdin", index_file=index, stdin=_paths_in([path]))
    return True


def _read(path: Path) -> bytes | None:
    try:
        return fsops.read_regular_bytes(path)
    except OSError:
        return None


def integrate(ctx: JobContext, upstream: str) -> Outcome | None:
    """Bring the checked sha `upstream` in, if `HEAD..upstream` is memory-only; the outcome that
    stops the job, or `None`.

    The upstream hold in `ctx.holds` is set or cleared here; the local hold is the push's. Indexes
    united -- conflicting in a replay, or changed here and not committed -- are re-rendered and
    committed, and are a notice (`resolved_index`).
    """
    ctx.resolved.clear()
    head = _rev(ctx, "HEAD")
    if _is_ancestor(ctx, upstream, head):
        ctx.holds = replace(ctx.holds, upstream_paths=())
        return None
    memory_only, offending = range_is_memory_only(
        ctx.overlay, head, upstream, timeout=ctx.limit(ctx.limits.local), env=ctx.env
    )
    if not memory_only:
        remark = (
            "upstream holds changes outside memory; nothing is integrated or pushed until they "
            f"are taken by hand. Review and take: {REVIEW.format(sha=upstream)}"
        )
        _hold_upstream(ctx, offending, remark)
        return None
    ctx.holds = replace(ctx.holds, upstream_paths=())
    by_hand = f"integrate {upstream} by hand: {REVIEW.format(sha=upstream)}"
    local = _nul(_ok(ctx, "rev-list", "-z", "--reverse", "--end-of-options", f"{upstream}..{head}"))
    merges = _nul(_ok(ctx, "rev-list", "-z", "--merges", "--end-of-options", f"{upstream}..{head}"))
    if merges:
        detail = f"local merge commits are not replayed ({', '.join(merges)}); {by_hand}"
        return _outcome(ctx, "conflict", detail)
    tip, conflicted = replay(ctx, upstream, local) if local else (upstream, [])
    if tip is None:
        ctx.resolved.clear()
        detail = (
            f"a local commit conflicts with upstream on {', '.join(conflicted)}; main was not "
            f"moved. To {by_hand}"
        )
        return _outcome(ctx, "conflict", detail)
    incoming = _nul(
        _ok(ctx, "diff", "--no-renames", "--name-only", "-z", "--end-of-options", head, tip)
    )
    blocked, unite = _blocked(ctx, incoming)
    if blocked:
        detail = (
            f"incoming notes are changed here and not committed yet ({', '.join(blocked)}); the "
            "next job commits them first, then integrates"
        )
        return _outcome(ctx, "waiting_clean_tree", detail)
    # A tree git will not put in an index cannot be written to the working tree either: moving
    # `main` to it would leave an alignment no job can finish. It is held, `main` unmoved.
    with _scratch(ctx) as scratch:
        readable = _git(ctx, "read-tree", "--end-of-options", tip, index_file=scratch / "index")
    if timed(readable, "git read-tree").code != 0:
        remark = (
            f"upstream's tree cannot be checked out ({scan.first_lines(readable.err)}); nothing is "
            "integrated or pushed until upstream is repaired. Review: "
            f"git diff --stat HEAD {upstream}"
        )
        _hold_upstream(ctx, incoming, remark)
        return None
    pending = PendingAlign(head, tip, tuple(incoming))
    unmerged = _unmerged_now(ctx)
    if unmerged is not None:
        return unmerged
    if not _move_main(ctx, pending):
        return _outcome(ctx, "raced", "main moved during the integration; the next job retries")
    stale = _settle(ctx, pending)
    if stale is not None:
        return stale
    for path in unite:
        if _unite_worktree(ctx, tip, path):
            ctx.resolved.update(_projects([path]))
    if not ctx.resolved:
        return None
    projects = sorted(ctx.resolved)
    detail = "indexes changed on both sides were united: " + ", ".join(projects)
    ctx.notices.append(_outcome(ctx, "resolved_index", detail))
    # The union's own lines are harvested into their notes, and both committed with this job's.
    return commit_memory(ctx, also=projects)


# -- push the checked range -----------------------------------------------------------------------

REMEDY = (
    "rewrite this commit locally: `git rebase -i {sha}^` and edit it; the job pushes the "
    "rewritten range"
)


def _before_push() -> None:
    """Nothing; the moment between the range's checks and its push (a test seam)."""


def _range(ctx: JobContext, base: str, tip: str) -> list[tuple[str, list[RawEntry]]]:
    return commit_entries(
        ctx.overlay, f"{base}..{tip}", timeout=ctx.limit(ctx.limits.local), env=ctx.env
    )


def _metadata(ctx: JobContext, base: str, tip: str) -> list[tuple[str, str]]:
    """`[(sha, text)]` for each commit of `base..tip`: what its push sends besides the patches,
    the commit object whole (every header, the message) and the name of every path."""
    return [
        (sha, "\n".join([_ok(ctx, "cat-file", "commit", "--end-of-options", sha).rstrip("\n"),
                         *(entry.path for entry in entries)]) + "\n")
        for sha, entries in _range(ctx, base, tip)
    ]  # fmt: skip


def _scan_push(ctx: JobContext, upstream: str, tip: str) -> Outcome | None:
    """Both scans of what the push sends, within `Limits.checks` together; the failure, if any."""
    binary = scan.gitleaks_binary(ctx.home, ctx.overlay)
    if binary is None:
        return _outcome(ctx, "scan_unavailable", scan.NO_SCANNER.format(overlay=ctx.overlay))
    deadline = time.monotonic() + ctx.limits.checks
    with _scratch(ctx) as scratch:
        result = scan.scan_range(
            ctx.overlay, upstream, tip, binary, ctx.limit(ctx.limits.checks), ctx.env, scratch
        )
        left = deadline - time.monotonic()
        if result.ok and left <= 0:
            return _outcome(ctx, "timeout", f"the push's scans took over {ctx.limits.checks:g} s")
        if result.ok:
            blocks = _metadata(ctx, upstream, tip)
            result = scan.scan_commits(
                ctx.overlay, blocks, binary, ctx.limit(left), ctx.env, scratch
            )
    if result.timed_out:
        return _outcome(ctx, "timeout", f"gitleaks: {result.detail}")
    if result.ok:
        return None
    if result.finding_commit:
        detail = f"{result.detail}\n{REMEDY.format(sha=result.finding_commit)}"
        return _outcome(ctx, "secret_found", detail)
    return _outcome(ctx, "hook_failed", f"gitleaks: {result.detail}")


def push(ctx: JobContext, upstream: str) -> Outcome | None:
    """Push `upstream..H`, `H` the sha checked here and never `main`, if it is memory-only; the
    outcome that stops the job, or `None`.

    The local range is judged even when an upstream hold skips the push, so both holds are
    recorded at once; one that is not memory-only is a local hold naming its commits. Every byte
    pushed is scanned first. Never forced, and no tag follows.
    """
    tip = _rev(ctx, "HEAD")
    if _is_ancestor(ctx, tip, upstream):
        ctx.holds = replace(ctx.holds, local_commits=())
        return None
    pushable, offending = range_is_memory_only(
        ctx.overlay, upstream, tip, timeout=ctx.limit(ctx.limits.local), env=ctx.env
    )
    if not pushable:
        commits = [
            sha
            for sha, entries in _range(ctx, upstream, tip)
            if not entries or any(entry_offends(entry) for entry in entries)
        ] or offending
        ctx.remarks.append(
            "local commits outside memory are not pushed; push them by hand when reviewed: "
            + ", ".join(commits)
        )
        ctx.holds = replace(ctx.holds, local_commits=tuple(commits))
        return None
    ctx.holds = replace(ctx.holds, local_commits=())
    if ctx.holds.upstream_paths:
        ctx.remarks.append("not pushed while upstream is held")
        return None
    failed = _scan_push(ctx, upstream, tip)
    if failed is not None:
        return failed
    _before_push()
    limit = ctx.limit(ctx.limits.push)
    result = _git(
        ctx, "push", "--porcelain", "--no-follow-tags", "origin", f"{tip}:refs/heads/main",
        timeout=limit,
    )  # fmt: skip
    if result.code == 0 and not result.timed_out:
        return None
    said = (result.out + result.err).lower()
    if not result.timed_out and any(
        word in said for word in ("[rejected]", "fetch first", "non-fast-forward")
    ):
        detail = "origin/main moved before the push; the next trigger fetches and retries"
        return _outcome(ctx, "rejected", detail)
    return _remote_failure(ctx, result, "git push origin", limit)


def _is_ancestor(ctx: JobContext, ancestor: str, rev: str) -> bool:
    result = _git(ctx, "merge-base", "--is-ancestor", "--end-of-options", ancestor, rev)
    return timed(result, "git merge-base").code == 0


# -- the job's end, its run loop and its entry point ----------------------------------------------

# Named caps, no shipped file states them: how many rounds a running job adds for triggers that
# arrived while it ran; the characters of the outcome's detail kept in the state; and how long
# the last read of `HEAD` may take, made even when the job's own time is spent.
LOOPS = 2
DETAIL_LIMIT = 2000
HEAD_TIMEOUT = 10.0
# What the detached process runs, under `-I`: the working directory (the overlay), `PYTHONPATH`
# and the user site are not on `sys.path`, and only the imported package's own directory, which
# `job_argv` hands it, is put back.
BOOT = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from stayfixed.sync.job import main; sys.exit(main(sys.argv[1:]))"
)


def _refusal_detail(refused: list[str]) -> str:
    return (
        "job: not committed, not a plain-text note under a memory name (a link, at the path or in "
        "place of a directory above it, a nested repository, an executable, a dot-file or "
        "dot-directory, a name not ending in .md, or a file git calls binary): "
        + ", ".join(refused)
    )


def _end(ctx: JobContext, stopped: Outcome | None) -> Outcome:
    """The job's outcome, by one rule: a stop is the end; otherwise the latest notice, the paths
    left out of a commit (`ctx.refused`) counting as the earliest; with neither, `ok`. Every other
    candidate is named in the detail, after the end's own words and before the remarks, and the
    same failure met twice is said once."""
    notices = list(ctx.notices)
    if ctx.refused:
        refusal = _outcome(ctx, "hook_failed", _refusal_detail(ctx.refused))
        notices.insert(0, refusal)
    ranked: list[Outcome] = []
    for each in ([stopped] if stopped is not None else []) + notices[::-1]:
        if all((each.state, each.detail) != (kept.state, kept.detail) for kept in ranked):
            ranked.append(each)
    end = ranked[0] if ranked else _outcome(ctx, "ok")
    others = [f"also {other.state}: {other.detail}" for other in ranked[1:]]
    return replace(end, detail=_detail([end.detail, *others, *ctx.remarks]))


def _detail(parts: list[str | None]) -> str | None:
    """`parts` a line apart, each said once; when they are too long together each is cut to an
    equal share, so the last is never dropped for the first."""
    said = list(dict.fromkeys(part for part in parts if part))
    joined = "\n".join(said)
    if len(joined) <= DETAIL_LIMIT:
        return joined or None
    share = DETAIL_LIMIT // len(said) - 1
    return "\n".join(part if len(part) <= share else part[: share - 3] + "..." for part in said)


def _steps(ctx: JobContext) -> Outcome | None:
    """Guard, align what is owed, commit, fetch, integrate, push; the outcome that stopped it."""
    checked_out = guard(ctx.overlay, timeout=ctx.limit(ctx.limits.local), env=ctx.env)
    if not checked_out.ok:
        return _outcome(ctx, "skipped", checked_out.reason)
    stopped = align_first(ctx) or commit_memory(ctx)
    if stopped is not None:
        return stopped
    upstream, stopped = fetch(ctx)
    if upstream is None:
        return stopped
    return integrate(ctx, upstream) or push(ctx, upstream)


def _one_job(ctx: JobContext) -> SyncState:
    """The steps once, within the job's limit; the state written for them. A state recorded for
    another overlay, or one that cannot be read, is not used, and the detail says so."""
    ctx = replace(
        ctx, deadline=time.monotonic() + ctx.limits.job, remarks=[], notices=[], pending=None,
        fetched_sha=None, resolved=set(), refused=[], holds=EMPTY_HOLDS,
    )  # fmt: skip
    scratch = ctx.state_dir / SCRATCH
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        previous = read_state(ctx.state_dir)
    except StateUnreadable as error:
        previous = None
        ctx.remarks.append(f"the previous state could not be read and was replaced: {error}")
    if previous is not None and previous.overlay != str(ctx.overlay):
        ctx.remarks.append(
            f"the state recorded for {previous.overlay} is not used: the overlay moved"
        )
        previous = None
    if previous is not None:
        ctx.holds, ctx.pending = previous.holds, previous.pending_align
    try:
        stopped = _steps(ctx)
    except (JobTimeout, GitTimeout) as error:
        stopped = _outcome(ctx, "timeout", str(error))
    except JobStopped as stop:
        stopped = stop.outcome
    except Exception as error:  # every failure becomes state, never a traceback
        said = scan.first_lines(str(error)) or type(error).__name__
        stopped = _outcome(ctx, "hook_failed", f"job: {said}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    # Not `ctx.env`, which past the deadline would not be built: `rev-parse` asks no remote.
    head = git(ctx.overlay, "rev-parse", "-q", "--verify", "HEAD", timeout=HEAD_TIMEOUT)
    state = SyncState(
        overlay=str(ctx.overlay),
        outcome=_end(ctx, stopped),
        holds=ctx.holds,
        fetched_sha=ctx.fetched_sha or (previous.fetched_sha if previous else None),
        last_job_at=iso(ctx.now()),
        pending_align=ctx.pending,
        head=head.out.strip() if head.code == 0 and not head.timed_out else None,
    )
    write_state(ctx.state_dir, state)
    return state


def _released() -> None:
    """Nothing; the moment right after a job released its lock (a test seam)."""


def run_job(ctx: JobContext) -> SyncState | None:
    """Take the lock, run the job, write the state, release; loop while triggers arrived.

    With the lock busy, the trigger is marked pending for the running job and the current state
    returned. After each release the mark is taken once more, so a trigger that landed while the
    job ran runs it again, at most `LOOPS` more times; one still pending after that gets a
    sleeper, a throttle after this job, as the hooks schedule one.
    """
    state: SyncState | None = None
    for round_number in range(LOOPS + 1):
        lock = Lock.try_acquire(ctx.state_dir / LOCK_FILE)
        if lock is None:
            mark_pending(ctx.state_dir)
            if state is None:
                with contextlib.suppress(StateUnreadable):
                    state = read_state(ctx.state_dir)
            return state
        with lock:
            take_pending(ctx.state_dir)  # this round covers every trigger so far
            state = _one_job(ctx)
        _released()
        if round_number == LOOPS:
            if fsops.exists(ctx.state_dir / PENDING_FILE) and state.last_job_at is not None:
                wake = parse_time(state.last_job_at) + timedelta(seconds=THROTTLE_SECONDS)
                spawn(ctx.overlay, wake=wake)
        elif not take_pending(ctx.state_dir):
            break
    return state


def job_argv(*, wake: datetime | None) -> list[str]:
    """The detached job's command: isolated, given the package's directory, and `--sleep-until`
    for a sleeper. It reads the switch and the overlay from the machine file itself."""
    package_parent = str(Path(__file__).resolve().parents[2])
    sleep = ["--sleep-until", iso(wake)] if wake is not None else []
    return [sys.executable, "-I", "-c", BOOT, package_parent, *sleep]


def spawn(overlay: Path, *, wake: datetime | None = None) -> None:
    """Start the job detached and return at once: its own session, standard streams on
    `/dev/null` (a hook's caller reads its output to the end), no inherited descriptor, and the
    overlay as its working directory."""
    subprocess.Popen(  # noqa: S603 - list form, never a shell
        job_argv(wake=wake),
        cwd=overlay,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _sleep_until(text: str, now: datetime) -> None:
    """Sleep until `text`, never longer than the throttle: a clock that jumped must not park the
    sleeper for hours."""
    with contextlib.suppress(ValueError):
        seconds = (parse_time(text) - now).total_seconds()
        time.sleep(min(max(seconds, 0.0), THROTTLE_SECONDS))


def _switched_on() -> Path | None:
    """The overlay the machine file records, when it also switches the sync on."""
    overlay = overlay_root(None) if enabled() else None
    return overlay if overlay is not None and fsops.exists(overlay / ".git") else None


def main(argv: list[str] | None = None) -> int:
    """`[--sleep-until ISO]`: the detached job. Exits 0 whatever happens, and runs no job while
    the machine file does not switch the sync on, read again when a sleeper wakes."""
    try:
        parser = argparse.ArgumentParser(prog="stayfixed-sync", add_help=False)
        parser.add_argument("--sleep-until")
        with contextlib.redirect_stderr(io.StringIO()):
            args = parser.parse_args(argv)
        if _switched_on() is None:
            return 0
        state_dir = state_directory()
        if args.sleep_until:
            sleeper = Lock.try_acquire(state_dir / SLEEPER_LOCK_FILE)
            if sleeper is None:
                return 0  # another sleeper already waits
            with sleeper:
                _sleep_until(args.sleep_until, datetime.now(UTC))
        overlay = _switched_on()
        if overlay is None:
            return 0
        host = os.uname().nodename.split(".")[0] or "unknown"
        context = JobContext(overlay, state_dir, Path.home(), host, lambda: datetime.now(UTC))
        run_job(context)
    except (Exception, SystemExit):  # noqa: S110 - the job exits 0 whatever happens
        pass
    return 0
