"""When a session's hook event starts the note sync's job, a sleeper, or nothing.

Imported by `sync.hooks` only once the machine file switches the sync on. `decide` reads one `git
status` of the overlay and the state file, and one `rev-parse` of `origin/main` when an unchanged
hold would back it off, and answers one of three things: **run** the job now; **schedule** it,
marking a trigger pending and spawning a sleeper that waits out the throttle (the job's own
`sleeper.lock` makes a second sleeper exit at once, so a burst of turns is one run); or **none**.

A `Stop` or `SessionEnd` starts a job when a memory path is dirty or untracked, when `@{u}..HEAD`
holds commits, or when the last outcome is not `ok` or `skipped` or a hold is recorded; a session
start always does, to fetch, except after a compaction, which is the same session going on.
While a hold is recorded and neither `HEAD` nor the upstream ref moved since the last job, a
`Stop` and a `SessionEnd` wait (`state.backed_off`), unpushed commits included, since a local
hold's own commits keep `@{u}..HEAD` non-empty; a dirty note is never backed off. A trigger
inside the throttle, or while a job runs, is scheduled, never dropped; `SessionEnd` is never
throttled, since no later turn would pick it up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stayfixed import fsops
from stayfixed.config.overlay import overlay_root
from stayfixed.hooks.api import HookEvent
from stayfixed.sync import job
from stayfixed.sync.git import git
from stayfixed.sync.render import remember_checkout
from stayfixed.sync.rules import MEMORY_PATHSPEC
from stayfixed.sync.state import (
    LOCK_FILE,
    SETTLED,
    THROTTLE_SECONDS,
    Lock,
    StateUnreadable,
    SyncState,
    backed_off,
    mark_pending,
    parse_time,
    read_state,
    state_directory,
    throttled,
)

# A named cap: how long the trigger's own git questions may take, well inside the ten seconds
# `hooks/hooks.json` gives each sync entry.
STATUS_TIMEOUT = 5.0


@dataclass(frozen=True)
class Tree:
    """What the one `git status` says: dirty memory, commits ahead of `@{u}`, and `HEAD`."""

    dirty: bool
    ahead: int
    head: str | None


def _tree(overlay: Path) -> Tree | None:
    """The overlay's memory status and branch line from one `git status`; `None` if it fails.
    `--no-optional-locks` keeps it from writing the index while the owner's own git may run."""
    result = git(
        overlay, "--no-optional-locks", "status", "--porcelain=v2", "--branch", "-z",
        "--untracked-files=all", "--no-renames", "--", *MEMORY_PATHSPEC, timeout=STATUS_TIMEOUT,
    )  # fmt: skip
    if result.timed_out or result.code != 0:
        return None
    dirty, ahead, head = False, 0, None
    for record in result.out.split("\0"):
        if record.startswith("# branch.oid "):
            oid = record.removeprefix("# branch.oid ").strip()
            head = oid if oid != "(initial)" else None
        elif record.startswith("# branch.ab "):  # "+<ahead> -<behind>", only with an upstream
            text = record.removeprefix("# branch.ab ").split()[0].lstrip("+")
            ahead = int(text) if text.isdigit() else 0
        elif record and not record.startswith("# "):
            dirty = True  # an entry under the pathspec: changed, staged, unmerged or untracked
    return Tree(dirty, ahead, head)


def _upstream(overlay: Path) -> str | None:
    """The sha `origin/main` names now; `None` when it cannot be read."""
    result = git(
        overlay, "rev-parse", "-q", "--verify", "refs/remotes/origin/main^{commit}",
        timeout=STATUS_TIMEOUT,
    )  # fmt: skip
    return result.out.strip() or None if result.code == 0 and not result.timed_out else None


def _backed_off(overlay: Path, state: SyncState, tree: Tree | None, now: datetime) -> bool:
    """Whether a standing hold and unpushed commits are old news."""
    if tree is None or tree.head is None or not backed_off(state, tree.head, now):
        return False
    # Only now is the upstream ref worth reading: the owner's own fetch moving it is news.
    return backed_off(state, tree.head, now, upstream=_upstream(overlay))


def _triggered(overlay: Path, d: Path, now: datetime, tree: Tree | None) -> bool:
    """Whether a `Stop` or `SessionEnd` finds something for a job to do."""
    if tree is not None and tree.dirty:
        return True  # a note to commit is never backed off
    try:
        state = read_state(d)
    except StateUnreadable:
        return True  # a state nobody can read is not `ok`; the job replaces it
    ahead = tree is not None and tree.ahead > 0
    if state is None:
        return ahead
    if _backed_off(overlay, state, tree, now):
        return False
    return ahead or state.outcome.state not in SETTLED or state.holds.any


def _busy(d: Path) -> bool:
    """Whether a job holds `job.lock` now. Taking it for an instant is safe: a job that found it
    busy in that instant only marked pending, and the run or sleeper spawned next follows it."""
    try:
        lock = Lock.try_acquire(d / LOCK_FILE)
    except OSError:
        return False
    if lock is None:
        return True
    lock.release()
    return False


def decide(
    event: str, source: str | None, overlay: Path, d: Path, now: datetime
) -> tuple[str, datetime | None]:
    """`("run", None)`, `("schedule", <wake time>)` or `("none", None)` for `event` with the
    session start's `source`, the overlay at `overlay` and the state directory `d`."""
    if not fsops.exists(overlay / ".git"):
        return "none", None
    if event == "SessionStart":
        if source == "compact":
            return "none", None
    elif not _triggered(overlay, d, now, _tree(overlay)):
        return "none", None
    if event == "SessionEnd":
        return "run", None
    throttle = timedelta(seconds=THROTTLE_SECONDS)
    if _busy(d):
        return "schedule", now + throttle  # the running job ends some time from now
    try:
        state = read_state(d)
    except StateUnreadable:
        state = None
    last = state.last_job_at if state is not None else None
    if last is not None and throttled(last, now):
        return "schedule", parse_time(last) + throttle
    return "run", None


def trigger(event: HookEvent) -> None:
    """The handler's work once the sync is on: record a session start's checkout for the
    pre-render, decide, and spawn the job or a sleeper."""
    overlay = overlay_root(None)
    if overlay is None:
        return
    d = state_directory()
    if event.name == "SessionStart" and event.project_root is not None:
        remember_checkout(event.project_root, d)
    source = event.raw.get("source")
    named = source if isinstance(source, str) else None
    decision, wake = decide(event.name, named, overlay, d, datetime.now(UTC))
    if decision == "schedule":
        mark_pending(d)
    if decision != "none":
        job.spawn(overlay, wake=wake)
