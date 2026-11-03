"""The job's run loop, its entry point and its detached start.

`run_job` takes the per-machine lock, runs the steps once, writes the state and releases; a
trigger that arrived meanwhile runs it again, at most twice more, and one still pending after that
gets a sleeper. `main` is what the detached process runs: it reads the switch and the overlay from
the machine file itself, and exits 0 whatever happens. `spawn` starts it isolated (`-I`), so a
module planted at the overlay's root, its working directory, is never imported.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stayfixed.config.machine import machine_config_path
from stayfixed.sync import job as J
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
    SyncState,
    iso,
    mark_pending,
    parse_time,
    read_state,
    write_state,
)
from tests.sync.conftest import NOW, Overlays, context, git, head, note_text, write

NOTE = "common/memory/new.md"


def job(world: Overlays) -> SyncState | None:
    return J.run_job(context(world, world.a))


def remote_files(world: Overlays) -> list[str]:
    return git(world.bare, "ls-tree", "-r", "--name-only", "main").split()


@pytest.fixture
def on(overlays: Overlays) -> Overlays:
    """The overlays with this machine's sync switched on in the machine file."""
    overlays.sync = True
    overlays.use(overlays.a)
    return overlays


# -- the loop -------------------------------------------------------------------------------------


def test_a_trigger_during_the_release_runs_a_second_round(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    released: list[int] = []

    def a_trigger_lands_during_the_release() -> None:
        if not released:
            write(overlays.a, "common/memory/late.md", note_text("late"))
            mark_pending(overlays.state_dir)
        released.append(1)

    monkeypatch.setattr(J, "_released", a_trigger_lands_during_the_release)

    state = job(overlays)

    assert len(released) == 2
    assert state is not None and state.outcome.state == "ok", state
    assert "common/memory/late.md" in remote_files(overlays)
    assert not (overlays.state_dir / PENDING_FILE).exists()


def test_busy_lock_marks_pending_and_the_job_loops(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two sessions ending at once: the second trigger finds the first job's lock, only marks
    # pending, and returns at once; the running job takes the mark and runs a second round, which
    # carries the note the second session wrote.
    rounds: list[int] = []
    second: list[SyncState | None] = []
    real_fetch = J.fetch

    def a_second_session_ends_meanwhile(ctx: J.JobContext) -> Any:
        if not second:
            write(overlays.a, "common/memory/second.md", note_text("second"))
            second.append(J.run_job(context(overlays, overlays.a)))
        return real_fetch(ctx)

    monkeypatch.setattr(J, "fetch", a_second_session_ends_meanwhile)
    monkeypatch.setattr(J, "_released", lambda: rounds.append(1))
    a = overlays.a
    write(a, NOTE, note_text("new"))

    state = J.run_job(context(overlays, a))

    # The second trigger ran no job: it returned what was on disk, where no job had ended yet.
    [found] = second
    assert found is None or found.last_job_at is None
    assert len(rounds) == 2
    assert state is not None and state.outcome.state == "ok", state
    assert {"common/memory/new.md", "common/memory/second.md"} <= set(remote_files(overlays))
    assert not (overlays.state_dir / PENDING_FILE).exists()


def test_the_loop_stops_after_two_more_rounds(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds: list[int] = []
    spawned: list[tuple[Path, datetime | None]] = []

    def always_pending() -> None:
        rounds.append(1)
        mark_pending(overlays.state_dir)

    monkeypatch.setattr(J, "_released", always_pending)
    monkeypatch.setattr(J, "spawn", lambda overlay, *, wake=None: spawned.append((overlay, wake)))

    state = job(overlays)

    assert len(rounds) == 3
    # Still pending at the cap, and nothing would run it: a sleeper does, a throttle after this
    # job, started as the hooks start one.
    assert state is not None and state.last_job_at is not None
    assert spawned == [
        (overlays.a, parse_time(state.last_job_at) + timedelta(seconds=THROTTLE_SECONDS))
    ]


def test_no_sleeper_when_nothing_is_pending_at_the_cap(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds: list[int] = []
    spawned: list[object] = []

    def pending_twice() -> None:
        rounds.append(1)
        if len(rounds) < 3:
            mark_pending(overlays.state_dir)

    monkeypatch.setattr(J, "_released", pending_twice)
    monkeypatch.setattr(J, "spawn", lambda overlay, *, wake=None: spawned.append(overlay))

    job(overlays)

    assert len(rounds) == 3 and spawned == []


def test_a_busy_lock_marks_pending_and_returns_the_state(overlays: Overlays) -> None:
    held = Lock.try_acquire(overlays.state_dir / LOCK_FILE)
    assert held is not None
    try:
        assert job(overlays) is None
    finally:
        held.release()

    assert (overlays.state_dir / PENDING_FILE).exists()
    assert read_state(overlays.state_dir) is None


# -- the state a job starts from ------------------------------------------------------------------


def test_a_state_for_another_overlay_is_not_used(overlays: Overlays) -> None:
    # The overlay moved: holds, the fetched sha and an alignment recorded for the old path are
    # not this checkout's, so the job starts afresh and says so.
    elsewhere = overlays.a.parent / "the-old-overlay"
    write_state(
        overlays.state_dir,
        SyncState(
            overlay=str(elsewhere),
            outcome=Outcome("offline", iso(NOW), None, (), ()),
            holds=Holds(("common/claude/hooks/launch.sh",), iso(NOW), ("0" * 40,), iso(NOW)),
            last_fetch_ok=iso(NOW),
            fetched_sha="1" * 40,
            last_job_at=iso(NOW),
            pending_align=PendingAlign("2" * 40, "3" * 40, ("common/memory/first.md",)),
        ),
    )

    state = job(overlays)

    assert state is not None and state.outcome.state == "ok", state
    assert state.overlay == str(overlays.a)
    assert state.holds == EMPTY_HOLDS and state.pending_align is None
    assert state.fetched_sha == head(overlays.a, "refs/stayfixed/fetched")
    assert state.outcome.detail is not None and str(elsewhere) in state.outcome.detail
    assert read_state(overlays.state_dir) == state


def test_the_scratch_directory_is_removed_whole_at_the_start_and_the_end(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = overlays.state_dir / SCRATCH
    (scratch / "left-by-a-killed-job").mkdir(parents=True)
    seen: list[bool] = []
    real_steps = J._steps

    def steps(ctx: J.JobContext) -> Outcome | None:
        seen.append(scratch.exists())
        return real_steps(ctx)

    monkeypatch.setattr(J, "_steps", steps)
    write(overlays.a, NOTE, note_text("new"))

    state = job(overlays)

    assert state is not None and state.outcome.state == "ok", state
    assert seen == [False]
    assert not scratch.exists()


# -- main -----------------------------------------------------------------------------------------


def test_main_runs_no_job_with_sync_off_or_no_overlay(
    overlays: Overlays, capsys: pytest.CaptureFixture[str]
) -> None:
    write(overlays.a, NOTE, note_text("new"))
    assert J.main([]) == 0  # the machine file records the overlay, and no `[sync]`
    machine = machine_config_path()
    assert machine is not None
    machine.write_text("[sync]\nenabled = true\n", encoding="utf-8")  # on, and no overlay
    assert J.main([]) == 0
    absent = overlays.bare.parent / "absent"
    machine.write_text(f'[overlay]\nroot = "{absent}"\n[sync]\nenabled = true\n', encoding="utf-8")
    assert J.main([]) == 0  # recorded, and not there
    machine.write_text("[sync\n", encoding="utf-8")  # a file that does not parse
    assert J.main([]) == 0
    assert J.main(["--not-an-option"]) == 0

    assert read_state(overlays.state_dir) is None
    assert capsys.readouterr() == ("", "")


def test_main_runs_a_job_on_the_overlay_the_machine_file_records(
    on: Overlays, capsys: pytest.CaptureFixture[str]
) -> None:
    write(on.a, NOTE, note_text("new"))

    assert J.main([]) == 0

    assert git(on.bare, "rev-parse", "main").strip() == head(on.a)
    state = read_state(on.state_dir)
    assert state is not None and state.outcome.state == "ok", state
    assert state.overlay == str(on.a)
    assert capsys.readouterr() == ("", "")


def test_a_sleeper_waits_then_runs_and_a_second_sleeper_exits(on: Overlays) -> None:
    write(on.a, NOTE, note_text("new"))
    held = Lock.try_acquire(on.state_dir / SLEEPER_LOCK_FILE)
    assert held is not None
    try:
        started = time.monotonic()
        assert J.main(["--sleep-until", iso(datetime.now(UTC))]) == 0
        assert time.monotonic() - started < 5
        assert read_state(on.state_dir) is None  # another sleeper holds it: exits at once
    finally:
        held.release()

    soon = iso(datetime.now(UTC) + timedelta(seconds=2))
    started = time.monotonic()
    assert J.main(["--sleep-until", soon]) == 0
    assert time.monotonic() - started >= 1
    assert git(on.bare, "rev-parse", "main").strip() == head(on.a)


def test_a_sleeper_woken_after_sync_was_switched_off_runs_no_job(
    on: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(on.a, NOTE, note_text("new"))

    def the_owner_switches_it_off_meanwhile(text: str, now: datetime) -> None:
        on.sync = False
        on.use(on.a)

    monkeypatch.setattr(J, "_sleep_until", the_owner_switches_it_off_meanwhile)

    assert J.main(["--sleep-until", iso(datetime.now(UTC))]) == 0

    assert read_state(on.state_dir) is None
    assert "?? common/memory/new.md" in git(on.a, "status", "--porcelain")


# -- the detached start ---------------------------------------------------------------------------


def test_the_job_argv_is_isolated_and_carries_only_the_wake_time() -> None:
    wake = datetime(2026, 10, 12, 12, 2, 0, tzinfo=UTC)
    plain, sleeper = J.job_argv(wake=None), J.job_argv(wake=wake)

    assert plain[:4] == [sys.executable, "-I", "-c", J.BOOT]
    assert Path(plain[4]) == Path(J.__file__).resolve().parents[2]
    assert (Path(plain[4]) / "stayfixed" / "sync" / "job.py").is_file()
    assert plain[5:] == []
    assert sleeper[5:] == ["--sleep-until", iso(wake)]


def _started(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    """Record each process `spawn` starts, so a test waits for and kills only its own."""
    started: list[subprocess.Popen[bytes]] = []
    real = subprocess.Popen

    def recording(argv: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = real(argv, **kwargs)
        if "close_fds" in kwargs:  # `spawn`'s, and not the git runner's
            started.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", recording)
    return started


def _end(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def test_the_job_imports_nothing_from_the_overlay(
    on: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The job runs in the overlay, a directory its notes' authors write. Without `-I` the
    # interpreter puts that directory first on `sys.path`, and a `json.py` there runs inside the
    # job; with `BOOT` putting the package's own directory first, a `stayfixed/` there is not
    # the one imported either.
    a = on.a
    marker = a.parent / "planted-module-ran"
    planted = f"open({str(marker)!r}, 'a').write(__name__ + '\\n')\n"
    write(a, "json.py", planted)
    write(a, "stayfixed/__init__.py", planted)
    write(a, "stayfixed/sync/__init__.py", planted)
    write(a, "stayfixed/sync/job.py", planted)
    write(a, NOTE, note_text("new"))
    started = _started(monkeypatch)
    try:
        J.spawn(a)
        [process] = started
        assert process.wait(timeout=120) == 0
    finally:
        _end(started)

    assert not marker.exists(), marker.read_text()
    state = read_state(on.state_dir)
    assert state is not None and state.outcome.state == "ok", state
    assert git(on.bare, "rev-parse", "main").strip() == head(a)


STAND_IN = """\
import json, os, sys
from pathlib import Path

def null(fd):
    try:
        return os.path.samestat(os.fstat(fd), os.stat(os.devnull))
    except OSError:
        return False

def open_above_2():
    found = []
    for fd in range(3, 256):
        try:
            os.fstat(fd)
        except OSError:
            continue
        found.append(fd)
    return found

Path(sys.argv[1]).write_text(json.dumps({
    "pid": os.getpid(), "sid": os.getsid(0), "pgrp": os.getpgrp(), "cwd": os.getcwd(),
    "null": [null(fd) for fd in (0, 1, 2)], "fds": open_above_2(), "argv": sys.argv[2:],
}))
"""


def test_the_job_is_spawned_detached_with_nothing_inherited(
    overlays: Overlays, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seen from inside the spawned process: its own session (so its own process group), standard
    # streams on `/dev/null` (a hook's caller reads its stdout to the end, and would wait for the
    # job), no descriptor above 2 even when the spawner holds an inheritable one, and the overlay
    # as its working directory rather than wherever the session started.
    script, seen = tmp_path / "stand-in.py", tmp_path / "seen.json"
    script.write_text(STAND_IN, encoding="utf-8")
    monkeypatch.setattr(
        J, "job_argv", lambda *, wake: [sys.executable, str(script), str(seen), iso(wake)]
    )
    started = _started(monkeypatch)
    read_end, write_end = os.pipe()
    os.set_inheritable(write_end, True)
    try:
        J.spawn(overlays.a, wake=NOW)
        [process] = started
        assert process.wait(timeout=60) == 0
    finally:
        os.close(write_end)
        os.close(read_end)
        _end(started)

    found = json.loads(seen.read_text())
    assert (found["sid"], found["pgrp"]) == (found["pid"], found["pid"])
    assert found["sid"] != os.getsid(0)
    assert found["null"] == [True, True, True]
    assert found["fds"] == []
    assert Path(found["cwd"]).resolve() == overlays.a.resolve()
    assert found["argv"] == [iso(NOW)]
