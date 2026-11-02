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

import contextlib
import shutil
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from stayfixed import fsops
from stayfixed.sync import scan
from stayfixed.sync.git import UNMERGED, Ran, checked, git, job_env, timed
from stayfixed.sync.render import prerender, unsafe_parent
from stayfixed.sync.rules import (
    MEMORY_PATHSPEC,
    MEMORY_SPECS,
    dirty_memory,
    index_of,
    is_memory_path,
    memory_path,
    offending_paths,
)
from stayfixed.sync.state import (
    EMPTY_HOLDS,
    SCRATCH,
    Holds,
    Outcome,
    PendingAlign,
    StateUnreadable,
    SyncState,
    iso,
    read_state,
    write_state,
)

# Named caps on the alignment's wait for an `index.lock` the owner's own git holds: five tries a
# fifth of a second apart, past which the job records `index_stale`. No shipped file states them.
ALIGN_RETRIES = 5
ALIGN_PAUSE_SECONDS = 0.2
ALIGN_COMMAND = "git reset -q -- " + " ".join(f"'{spec}'" for spec in MEMORY_PATHSPEC)
SWAP_MESSAGE = "stayfixed note sync"


@dataclass(frozen=True)
class Limits:
    """Wall-clock limits in seconds, each a named cap no shipped file states: the network calls,
    the pre-render, both commit checks together, the whole job, and any other single git call.
    Injectable, so a test can wait one second where the job waits sixty."""

    fetch: float = 30.0
    push: float = 30.0
    prerender: float = 30.0
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
    last_fetch_ok: str | None = None
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


def _outcome(
    ctx: JobContext,
    state: str,
    detail: str | None = None,
    *,
    paths: Iterable[str] = (),
    commits: Iterable[str] = (),
) -> Outcome:
    return Outcome(state, iso(ctx.now()), detail, tuple(paths), tuple(commits))


def _said(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[: scan.DETAIL_LINES])[: scan.DETAIL_CHARS]


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


REFUSED = (
    "job: not committed, not a plain-text note under a memory name (a link -- at the path or in "
    "place of a directory above it --, a nested repository, an executable, a dot-file or "
    "dot-directory, a name not ending in .md, or a file git calls binary): "
)


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
        said = _said(result.err) or ("waited for a passphrase" if result.timed_out else "")
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
            str(ctx.overlay), _outcome(ctx, "skipped", said), EMPTY_HOLDS, None, None, None, None
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
        return _outcome(ctx, "scan_unavailable", detail, paths=paths)
    result = scan.scan_index(
        ctx.overlay, index, binary, ctx.limit(ctx.limits.checks), env=ctx.env, scratch=index.parent
    )
    if result.ok:
        return None
    state = "timeout" if result.timed_out else "hook_failed"
    return _outcome(ctx, state, f"{result.check_id}: {result.detail}", paths=paths)


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
    ctx.limit(ctx.limits.prerender)
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
        return _outcome(ctx, "raced", detail, paths=paths, commits=[new])
    stale = _settle(ctx, pending)
    return replace(stale, paths=tuple(paths)) if stale is not None else None


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


def _moved_to(ctx: JobContext, sha: str) -> bool:
    """Whether `main` did move to `sha` (it is in `HEAD`'s history). A commit that never became
    reachable may have been pruned since: git's error then means "no" as well."""
    result = _git(ctx, "merge-base", "--is-ancestor", "--end-of-options", sha, "HEAD")
    return timed(result, "git merge-base").code == 0


def _finish_worktree(ctx: JobContext, pending: PendingAlign) -> list[str]:
    """Write the paths a move of `main` brought in, where the working tree still has the old; the
    paths it may not write, because a link or a file stands above them.

    Only a path still at its `from` version is written (the owner's later edit wins), only one
    `HEAD` still has at its `to` version, and only through git (`checkout-index` from a temporary
    index) or `fsops`, after checking no directory above it is a link.
    """
    if not pending.paths or not _moved_to(ctx, pending.to_sha):
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
                ctx.notices.append(_outcome(ctx, "hook_failed", detail, paths=refused))
            return None
        if "index.lock" not in result.err or attempt == ALIGN_RETRIES:
            break
        time.sleep(ALIGN_PAUSE_SECONDS)
    said = (_said(result.err).splitlines() or ["no answer"])[0] if result else "no answer"
    detail = (
        f"the index's memory entries could not be aligned with HEAD ({said}); the next job "
        f"retries first, or run: {ALIGN_COMMAND}"
    )
    return _outcome(ctx, "index_stale", detail, paths=pending.paths if pending else ())


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
    if pending is not None and not _moved_to(ctx, pending.to_sha):
        ctx.pending = pending = None
    if pending is None and not _index_needs_align(ctx):
        return None
    return _settle(ctx, pending)
