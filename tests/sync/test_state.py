"""The job's state file, lock, pending marker and pacing.

The state file is what `doctor` reads and the job reads back on every trigger, so both directions
are held: what is written comes back field for field, and a file that cannot be read says so
instead of passing for "never ran". The lock is the kernel's, on an open descriptor, so the tests
that matter run it across real processes, one of them killed with SIGKILL.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import stat
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from stayfixed.sync import state as S

NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)
HEAD = "7" * 40
OVERLAY = "/home/owner/overlay"


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _state(**changes: object) -> S.SyncState:
    """A state with every field set to something distinguishable."""
    state = S.SyncState(
        overlay=OVERLAY,
        outcome=S.Outcome(
            state="conflict",
            at=_iso(NOW - timedelta(minutes=3)),
            detail="common/memory/a.md conflicts",
            paths=("common/memory/a.md", "projects/x/memory/b c ü.md"),
            commits=("1" * 40,),
        ),
        holds=S.Holds(
            upstream_paths=("README.md",),
            upstream_since=_iso(NOW - timedelta(hours=2)),
            local_commits=("2" * 40, "3" * 40),
            local_since=_iso(NOW - timedelta(hours=1)),
        ),
        last_fetch_ok=_iso(NOW - timedelta(minutes=4)),
        fetched_sha="4" * 40,
        last_job_at=_iso(NOW - timedelta(minutes=3)),
        pending_align=S.PendingAlign(
            from_sha="5" * 40, to_sha="6" * 40, paths=("common/memory/n.md",)
        ),
        head=HEAD,
    )
    return replace(state, **changes)  # type: ignore[arg-type]


def _document(path: Path) -> dict[str, object]:
    return json.loads((path / S.STATE_FILE).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# -- where it lives, and what is written --------------------------------------------------------


def test_state_lives_in_the_data_directory() -> None:
    assert S.state_directory() == Path.home() / ".local/share/stayfixed/sync"


def test_the_outcomes_are_the_fifteen_in_order() -> None:
    assert S.OUTCOMES == (
        "ok", "skipped", "conflict", "resolved_index", "raced", "rejected", "offline",
        "auth_failed", "timeout", "hook_failed", "scan_unavailable", "signing_failed",
        "secret_found", "waiting_clean_tree", "index_stale",
    )  # fmt: skip


def test_a_state_round_trips_and_carries_its_overlay(tmp_path: Path) -> None:
    state = _state()
    S.write_state(tmp_path, state)
    assert S.read_state(tmp_path) == state
    assert S.read_state(tmp_path) != _state(overlay="/elsewhere")
    assert stat.S_IMODE((tmp_path / S.STATE_FILE).stat().st_mode) == 0o600
    # A pending alignment of none, and a state that never fetched, come back as they went.
    bare = _state(
        pending_align=None, fetched_sha=None, last_fetch_ok=None, last_job_at=None, head=None
    )
    S.write_state(tmp_path, bare)
    assert S.read_state(tmp_path) == bare


def test_the_written_shape_is_the_documented_one(tmp_path: Path) -> None:
    # `doctor` and a person read these keys, so they are a contract and not an implementation.
    S.write_state(tmp_path, _state())
    data = _document(tmp_path)
    assert set(data) == {
        "overlay", "outcome", "holds", "last_fetch_ok", "fetched_sha", "last_job_at",
        "pending_align", "head",
    }  # fmt: skip
    assert set(data["outcome"]) == {"state", "at", "detail", "paths", "commits"}  # type: ignore[call-overload]
    assert data["holds"] == {
        "upstream": {"paths": ["README.md"], "since": _iso(NOW - timedelta(hours=2))},
        "local": {"commits": ["2" * 40, "3" * 40], "since": _iso(NOW - timedelta(hours=1))},
    }
    assert data["pending_align"] == {
        "from": "5" * 40,
        "to": "6" * 40,
        "paths": ["common/memory/n.md"],
    }


def test_the_directory_is_made_private(tmp_path: Path) -> None:
    target = tmp_path / "a" / "sync"
    S.write_state(target, _state())
    assert S.read_state(target) == _state()
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_a_write_that_dies_leaves_the_old_state_and_no_stray_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    S.write_state(tmp_path, _state())
    real = os.replace

    def refuse(source: str, target: str, **kwargs: object) -> None:
        if target == S.STATE_FILE:
            raise OSError("disk full")
        real(source, target, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        S.write_state(tmp_path, _state(fetched_sha="8" * 40))
    monkeypatch.undo()
    assert S.read_state(tmp_path) == _state()
    assert [p.name for p in tmp_path.iterdir()] == [S.STATE_FILE]


def test_a_write_names_only_an_outcome_the_job_has(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the state writer accepts an outcome the job lacks").
    state = _state(outcome=replace(_state().outcome, state="fine"))
    with pytest.raises(ValueError, match="fine"):
        S.write_state(tmp_path, state)
    assert not (tmp_path / S.STATE_FILE).exists()


def test_a_later_outcome_keeps_the_holds(tmp_path: Path) -> None:
    first = _state()
    S.write_state(tmp_path, first)
    later = replace(first, outcome=S.Outcome("offline", _iso(NOW), "no route", (), ()))
    S.write_state(tmp_path, later)
    after = S.read_state(tmp_path)
    assert after is not None and after.outcome.state == "offline" and after.holds == first.holds


def test_a_hold_is_any_upstream_path_or_local_commit() -> None:
    assert not S.EMPTY_HOLDS.any
    assert replace(S.EMPTY_HOLDS, upstream_paths=("a",)).any
    assert replace(S.EMPTY_HOLDS, local_commits=("a",)).any


# -- reading what cannot be used ----------------------------------------------------------------


def test_no_state_is_none_and_not_unreadable(tmp_path: Path) -> None:
    assert S.read_state(tmp_path) is None
    assert S.read_state(tmp_path / "missing") is None


def _without(path: str, data: dict[str, object]) -> str:
    node: dict[str, object] = data
    *parents, last = path.split(".")
    for name in parents:
        node = node[name]  # type: ignore[assignment]
    del node[last]
    return json.dumps(data)


def _written(tmp_path: Path) -> dict[str, object]:
    S.write_state(tmp_path, _state())
    return _document(tmp_path)


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        pytest.param(lambda d: "{not json", "JSON", id="bad-json"),
        pytest.param(lambda d: "", "JSON", id="empty"),
        pytest.param(lambda d: "[]", "not a JSON object", id="a-list"),
        pytest.param(lambda d: "[" * 100000 + "]" * 100000, "nested", id="deep-nesting"),
        pytest.param(lambda d: _without("overlay", d), "overlay is missing", id="no-overlay"),
        pytest.param(lambda d: _without("outcome.at", d), "outcome.at is missing", id="no-time"),
        pytest.param(
            lambda d: json.dumps({**d, "overlay": 3}), "overlay is not a valid string", id="type"
        ),
        pytest.param(
            lambda d: json.dumps({**d, "outcome": {**d["outcome"], "state": "fine"}}),
            "not a sync outcome",
            id="unknown-outcome",
        ),
        pytest.param(
            lambda d: json.dumps({**d, "last_job_at": "yesterday"}),
            "not a valid timestamp",
            id="time",
        ),
        pytest.param(
            lambda d: json.dumps(
                {**d, "holds": {"upstream": {"paths": "a", "since": None}, "local": {}}}
            ),
            "not a valid string list",
            id="paths",
        ),
        pytest.param(
            lambda d: json.dumps({**d, "outcome": []}), "outcome is not a valid object", id="shape"
        ),
    ],
)
def test_a_corrupt_state_is_unreadable_not_absent(
    tmp_path: Path, make: object, reason: str
) -> None:
    # `doctor` says "unknown" for a file it cannot use and "never ran" for none; a reader that
    # took the first for the second would hide a broken sync behind a quiet one. Mutation
    # (`mutations/`'s "a state naming an outcome the job lacks is accepted") reddens the
    # unknown-outcome case.
    text = make(_written(tmp_path))  # type: ignore[operator]
    (tmp_path / S.STATE_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(S.StateUnreadable, match=reason):
        S.read_state(tmp_path)


def test_a_state_that_is_not_text_or_not_a_file_is_unreadable(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "an unreadable state reads as absent"): the directory case reddens.
    (tmp_path / S.STATE_FILE).write_bytes(b"\xff\xfe")
    with pytest.raises(S.StateUnreadable, match="UTF-8"):
        S.read_state(tmp_path)
    (tmp_path / S.STATE_FILE).unlink()
    (tmp_path / S.STATE_FILE).mkdir()
    with pytest.raises(S.StateUnreadable, match="cannot be read"):
        S.read_state(tmp_path)


def test_a_state_past_the_cap_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    S.write_state(tmp_path, _state())
    monkeypatch.setattr(S, "STATE_BYTES", 100)
    with pytest.raises(S.StateUnreadable, match="cannot be read"):
        S.read_state(tmp_path)


# -- locks --------------------------------------------------------------------------------------

_HOLDER = """
import sys, time
from pathlib import Path
from stayfixed.sync.state import Lock
lock = Lock.try_acquire(Path(sys.argv[1]))
print("held" if lock else "busy", flush=True)
time.sleep(float(sys.argv[2]))
"""


@contextlib.contextmanager
def _within(seconds: int) -> Iterator[None]:
    """A lock taken without its non-blocking flag waits for ever; this fails that test instead."""

    def out(*_: object) -> None:
        raise AssertionError("blocked on a lock that another holds")

    previous = signal.signal(signal.SIGALRM, out)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@contextlib.contextmanager
def _running(script: str, *args: object) -> Iterator[tuple[subprocess.Popen[str], list[str]]]:
    """A child running `script` that has printed its first line, killed and reaped afterwards."""
    process = subprocess.Popen(
        [sys.executable, "-c", script, *map(str, args)], stdout=subprocess.PIPE, text=True
    )
    assert process.stdout is not None
    try:
        yield process, process.stdout.readline().split()
    finally:
        process.kill()
        process.wait()
        process.stdout.close()


def test_a_lock_held_elsewhere_is_busy_and_released_on_close(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the job lock waits for its holder instead of reporting busy").
    path = tmp_path / S.LOCK_FILE
    with _running(_HOLDER, path, 30) as (_, said):
        assert said == ["held"]
        with _within(20):
            assert S.Lock.try_acquire(path) is None
            other = subprocess.run(
                [sys.executable, "-c", _HOLDER, str(path), "0"],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
        assert other.stdout.strip() == "busy"
    lock = S.Lock.try_acquire(path)
    assert lock is not None
    with lock, _within(20):
        assert S.Lock.try_acquire(path) is None
    again = S.Lock.try_acquire(path)
    assert again is not None
    again.release()
    again.release()  # a second release is nothing


def test_a_lock_dies_with_its_holder(tmp_path: Path) -> None:
    path = tmp_path / "nested" / S.SLEEPER_LOCK_FILE
    with _running(_HOLDER, path, 30) as (holder, said):
        assert said == ["held"]
        with _within(20):
            assert S.Lock.try_acquire(path) is None
        os.kill(holder.pid, signal.SIGKILL)
        holder.wait()
        lock = S.Lock.try_acquire(path)
        assert lock is not None
        lock.release()


_LEAVES_A_CHILD = """
import subprocess, sys, time
from pathlib import Path
from stayfixed.sync.state import Lock
lock = Lock.try_acquire(Path(sys.argv[1]))
child = subprocess.Popen(["sleep", "30"], close_fds=False)
print("held", child.pid, flush=True)
time.sleep(30)
"""


def test_a_child_of_a_killed_job_does_not_keep_the_lock(tmp_path: Path) -> None:
    # A git child outliving its killed job must not hold the lock: it is started with
    # `close_fds=False`, so only the descriptor's close-on-exec flag stands between it and the lock.
    # Mutation (`mutations/`'s "the job lock descriptor is inherited by its children").
    path = tmp_path / S.LOCK_FILE
    with _running(_LEAVES_A_CHILD, path) as (holder, said):
        word, child = said
        assert word == "held"
        try:
            os.kill(holder.pid, signal.SIGKILL)
            holder.wait()
            os.kill(int(child), 0)  # the child is still running
            with _within(20):
                lock = S.Lock.try_acquire(path)
            assert lock is not None, "the orphaned child inherited the lock"
            lock.release()
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(child), signal.SIGKILL)


# -- the pending marker -------------------------------------------------------------------------


def test_pending_is_taken_once(tmp_path: Path) -> None:
    d = tmp_path / "state"
    assert S.take_pending(d) is False
    S.mark_pending(d)
    S.mark_pending(d)  # two triggers are still one pending run
    assert S.take_pending(d) is True
    assert S.take_pending(d) is False
    assert stat.S_IMODE(d.stat().st_mode) == 0o700


# -- time and pacing ----------------------------------------------------------------------------


def test_times_are_utc_seconds_and_a_naive_time_is_utc() -> None:
    zone = timezone(timedelta(hours=3))
    assert S.iso(datetime(2026, 11, 2, 15, 0, 0, 999, tzinfo=zone)) == "2026-11-02T12:00:00+00:00"
    assert S.iso(datetime(2026, 11, 2, 12, 0, 0)) == "2026-11-02T12:00:00+00:00"
    assert S.parse_time("2026-11-02T12:00:00") == NOW
    with pytest.raises(ValueError):
        S.parse_time("yesterday")


def test_throttle_covers_the_interval_and_not_a_second_more() -> None:
    # Mutation (`mutations/`'s "the throttle holds a job two minutes old").
    assert S.throttled(_iso(NOW - timedelta(seconds=119)), NOW) is True
    assert S.throttled(_iso(NOW), NOW) is True
    assert S.throttled(_iso(NOW - timedelta(seconds=S.THROTTLE_SECONDS)), NOW) is False
    assert S.throttled(None, NOW) is False
    assert S.throttled("yesterday", NOW) is False


def test_throttle_and_back_off_treat_a_future_time_as_long_past() -> None:
    # A clock that jumped back must not stall the sync for as long as the jump.
    # Mutation (`mutations/`'s "a future last-job time still throttles").
    assert S.throttled(_iso(NOW + timedelta(hours=1)), NOW) is False
    assert S.backed_off(_held(last_job_at=_iso(NOW + timedelta(hours=1))), HEAD, NOW) is False


def _held(**changes: object) -> S.SyncState:
    """A state whose last job, five minutes ago, recorded a hold at `HEAD`."""
    five_minutes_ago = _iso(NOW - timedelta(minutes=5))
    return _state(
        **{
            "outcome": S.Outcome("ok", five_minutes_ago, None, (), ()),
            "last_job_at": five_minutes_ago,
            **changes,
        }
    )


def test_back_off_needs_a_hold_the_same_head_and_the_same_upstream() -> None:
    # Each comparison has a mutation of its own (declared): `mutations/`'s "the back-off ignores a
    # moved HEAD", "the back-off ignores a moved upstream", "the back-off ignores an absent hold"
    # and "the back-off outlasts its window".
    assert S.backed_off(_held(), HEAD, NOW) is True
    assert S.backed_off(_held(), "9" * 40, NOW) is False  # HEAD moved: the owner did something
    assert S.backed_off(_held(), HEAD, NOW, upstream="a" * 40) is False
    assert S.backed_off(_held(), HEAD, NOW, upstream="4" * 40) is True
    assert S.backed_off(_held(holds=S.EMPTY_HOLDS), HEAD, NOW) is False
    assert S.backed_off(_held(head=None), HEAD, NOW) is False
    assert S.backed_off(_held(last_job_at=None), HEAD, NOW) is False
    limit = timedelta(minutes=S.BACK_OFF_MINUTES)
    assert S.backed_off(_held(last_job_at=_iso(NOW - limit)), HEAD, NOW) is False
    assert (
        S.backed_off(_held(last_job_at=_iso(NOW - limit + timedelta(seconds=1))), HEAD, NOW) is True
    )


def test_back_off_holds_for_a_local_hold_alone() -> None:
    local = replace(S.EMPTY_HOLDS, local_commits=("2" * 40,), local_since=_iso(NOW))
    assert S.backed_off(_held(holds=local), HEAD, NOW) is True
