"""What the note sync's hooks and its detached job share, in the data directory.

The hooks decide and the job acts; they meet only in `state_directory()`: `state.json`, which the
job writes and `doctor` reads, `job.lock` held by the running job, `sleeper.lock` held by the one
sleeper waiting out the throttle, `pending`, a trigger that arrived while the job was busy,
`checkouts.json`, the project roots this machine's sessions opened, and `scratch/`, which the job
removes whole.

An outcome and a hold are different: the outcome is what the last job did, a hold a range the sync
refuses to move until its owner acts, and a later outcome (`offline`, say) never clears a hold. A
state file that is there and cannot be read is `StateUnreadable`, apart from none at all: `doctor`
says "unknown" for the first and "never ran" for the second.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from stayfixed import fsops
from stayfixed.config.paths import data_directory
from stayfixed.jsonobject import json_object

OUTCOMES: tuple[str, ...] = (
    "ok", "skipped", "conflict", "resolved_index", "raced", "rejected", "offline", "auth_failed",
    "timeout", "hook_failed", "scan_unavailable", "signing_failed", "secret_found",
    "waiting_clean_tree", "index_stale",
)  # fmt: skip

# The outcomes after which the sync has nothing to answer for: the hooks start no job on them and
# `doctor` reports them green.
SETTLED = ("ok", "skipped")

STATE_FILE = "state.json"
LOCK_FILE = "job.lock"
SLEEPER_LOCK_FILE = "sleeper.lock"
PENDING_FILE = "pending"
CHECKOUTS_FILE = "checkouts.json"
SCRATCH = "scratch"

# A trigger that follows a job by less than this does not start another: a session's turns end
# every few seconds, and the notes a turn changed are not worth a fetch each. No shipped file
# states it.
THROTTLE_SECONDS = 120
# How long a trigger that only repeats a recorded hold waits, while neither `HEAD` nor the fetched
# upstream moved. A hold needs its owner, so asking the remote again sooner learns nothing.
BACK_OFF_MINUTES = 15
# A named cap: the most bytes of `state.json` read, since `doctor` and every hook read it. The job
# writes a few kilobytes, far under this; no shipped file states it.
STATE_BYTES = 4 * 1024 * 1024


class StateUnreadable(Exception):
    """`state.json` is there and cannot be used; the message says why."""


@dataclass(frozen=True)
class Outcome:
    state: str
    at: str
    detail: str | None
    paths: tuple[str, ...]
    commits: tuple[str, ...]


@dataclass(frozen=True)
class Holds:
    upstream_paths: tuple[str, ...]
    upstream_since: str | None
    local_commits: tuple[str, ...]
    local_since: str | None

    @property
    def any(self) -> bool:
        return bool(self.upstream_paths or self.local_commits)


EMPTY_HOLDS = Holds((), None, (), None)


@dataclass(frozen=True)
class PendingAlign:
    """A move of `main` recorded before it is made, so a job killed after it aligns the index."""

    from_sha: str
    to_sha: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class SyncState:
    """`overlay` is the root the state was recorded for, as the machine file spells it. `head` is
    the `HEAD` the last job left, which the back-off compares."""

    overlay: str
    outcome: Outcome
    holds: Holds
    last_fetch_ok: str | None
    fetched_sha: str | None
    last_job_at: str | None
    pending_align: PendingAlign | None
    head: str | None = None


def state_directory() -> Path:
    """`~/.local/share/stayfixed/sync`, under the data directory every other record is in."""
    return data_directory() / "sync"


def iso(moment: datetime) -> str:
    """The one timestamp format the state uses: UTC, seconds, with its offset."""
    return _aware(moment).astimezone(UTC).isoformat(timespec="seconds")


def parse_time(text: str) -> datetime:
    """A state timestamp as an aware datetime, a naive one taken as UTC; `ValueError` if none."""
    return _aware(datetime.fromisoformat(text))


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _get(data: Any, key: str, where: str, kind: str = "string", *, none: bool = False) -> Any:
    """`data[key]` held to `kind` (`string`, `timestamp`, `string list` as a tuple, `object`), or
    `None` where `none` allows it; `where` is the dotted path to `data`, for the message."""
    if not isinstance(data, dict):
        raise StateUnreadable(f"{where.rstrip('.') or 'the state'} is not an object")
    if key not in data:
        raise StateUnreadable(f"{where}{key} is missing")
    value = data[key]
    if value is None and none:
        return None
    text = isinstance(value, str)
    ok = {
        "string": text,
        "timestamp": text and _readable_time(value),
        "string list": isinstance(value, list) and all(isinstance(item, str) for item in value),
        "object": isinstance(value, dict),
    }[kind]
    if not ok:
        raise StateUnreadable(f"{where}{key} is not a valid {kind}")
    return tuple(value) if kind == "string list" else value


def _readable_time(text: str) -> bool:
    try:
        parse_time(text)
    except ValueError:
        return False
    return True


def _parse(data: dict[str, Any]) -> SyncState:
    raw = _get(data, "outcome", "", "object")
    state = _get(raw, "state", "outcome.")
    if state not in OUTCOMES:
        raise StateUnreadable("outcome.state is not a sync outcome")
    outcome = Outcome(
        state=state,
        at=_get(raw, "at", "outcome.", "timestamp"),
        detail=_get(raw, "detail", "outcome.", none=True),
        paths=_get(raw, "paths", "outcome.", "string list"),
        commits=_get(raw, "commits", "outcome.", "string list"),
    )
    raw = _get(data, "holds", "", "object")
    up, local = _get(raw, "upstream", "holds.", "object"), _get(raw, "local", "holds.", "object")
    holds = Holds(
        upstream_paths=_get(up, "paths", "holds.upstream.", "string list"),
        upstream_since=_get(up, "since", "holds.upstream.", "timestamp", none=True),
        local_commits=_get(local, "commits", "holds.local.", "string list"),
        local_since=_get(local, "since", "holds.local.", "timestamp", none=True),
    )
    raw = _get(data, "pending_align", "", "object", none=True)
    align = None
    if raw is not None:
        align = PendingAlign(
            _get(raw, "from", "pending_align."),
            _get(raw, "to", "pending_align."),
            _get(raw, "paths", "pending_align.", "string list"),
        )
    return SyncState(
        overlay=_get(data, "overlay", ""),
        outcome=outcome,
        holds=holds,
        last_fetch_ok=_get(data, "last_fetch_ok", "", "timestamp", none=True),
        fetched_sha=_get(data, "fetched_sha", "", none=True),
        last_job_at=_get(data, "last_job_at", "", "timestamp", none=True),
        pending_align=align,
        head=_get(data, "head", "", none=True),
    )


def read_state(d: Path) -> SyncState | None:
    """The state in `d`; `None` when there is none; `StateUnreadable` when it cannot be used."""
    try:
        raw = fsops.read_regular_bytes(d / STATE_FILE, limit=STATE_BYTES)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StateUnreadable(f"{STATE_FILE} cannot be read ({fsops.said(exc)})") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise StateUnreadable(f"{STATE_FILE} is not UTF-8 text") from None
    return _parse(json_object(text, STATE_FILE, error=StateUnreadable))


def write_state(d: Path, s: SyncState) -> None:
    """Write `s` into `d` in one step, mode 0600: a job killed mid-write leaves the old state or
    the new, never half."""
    if s.outcome.state not in OUTCOMES:
        raise ValueError(f"{s.outcome.state} is not a sync outcome")
    align = s.pending_align
    document = {
        "overlay": s.overlay,
        "outcome": {
            "state": s.outcome.state,
            "at": s.outcome.at,
            "detail": s.outcome.detail,
            "paths": list(s.outcome.paths),
            "commits": list(s.outcome.commits),
        },
        "holds": {
            "upstream": {"paths": list(s.holds.upstream_paths), "since": s.holds.upstream_since},
            "local": {"commits": list(s.holds.local_commits), "since": s.holds.local_since},
        },
        "last_fetch_ok": s.last_fetch_ok,
        "fetched_sha": s.fetched_sha,
        "last_job_at": s.last_job_at,
        "pending_align": None
        if align is None
        else {"from": align.from_sha, "to": align.to_sha, "paths": list(align.paths)},
        "head": s.head,
    }
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    with fsops.open_directory(d) as directory:
        text = json.dumps(document, indent=2) + "\n"
        fsops.write_atomically_at(directory, STATE_FILE, text, mode=0o600)


class Lock:
    """An exclusive `flock` on an open descriptor: the kernel drops it when the holder dies.

    The descriptor is close-on-exec, so a git child of the job never inherits it: a child that
    outlived a killed job would otherwise keep the lock, and every later trigger would find the sync
    busy for as long as that child ran.
    """

    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    @classmethod
    def try_acquire(cls, path: Path) -> Lock | None:
        """The lock on `path`, made if need be, or `None` at once if another holds it."""
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                return None
            raise
        return cls(fd)

    def release(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)  # closing the descriptor drops the lock

    def __enter__(self) -> Lock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def mark_pending(d: Path) -> None:
    """Record that a trigger arrived while the job ran; any number of marks is one pending run."""
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.close(os.open(d / PENDING_FILE, os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC, 0o600))


def take_pending(d: Path) -> bool:
    """Consume the marker: `True` if it was set. One `unlink`, so two takers cannot both win."""
    try:
        os.unlink(d / PENDING_FILE)
    except FileNotFoundError:
        return False
    return True


def _age(last: str | None, now: datetime) -> timedelta | None:
    """How long ago `last` was; `None` when unknown, unparseable or in the future.

    A time in the future means the clock jumped back since it was written. Waiting it out could
    stall the sync for as long as the jump, so such a time counts as long past.
    """
    if last is None:
        return None
    try:
        age = _aware(now) - parse_time(last)
    except ValueError:
        return None
    return age if age >= timedelta(0) else None


def throttled(last_job_at: str | None, now: datetime) -> bool:
    """Whether the last job ended less than `THROTTLE_SECONDS` ago."""
    age = _age(last_job_at, now)
    return age is not None and age < timedelta(seconds=THROTTLE_SECONDS)


def backed_off(state: SyncState, head: str, now: datetime, *, upstream: str | None = None) -> bool:
    """Whether a trigger that only repeats a recorded hold should wait.

    True while a hold is recorded, `head` is the one the last job left, the upstream sha the caller
    sees (`upstream`, when it knows one) is the one that job fetched, and that job is under
    `BACK_OFF_MINUTES` old. The outcome needs no comparison: only a job changes it, and a job also
    restarts the window. The caller still starts a job for dirty notes or on `SessionStart`.
    """
    if not state.holds.any:
        return False
    if state.head is None or state.head != head:
        return False
    if upstream is not None and upstream != state.fetched_sha:
        return False
    age = _age(state.last_job_at, now)
    return age is not None and age < timedelta(minutes=BACK_OFF_MINUTES)
