"""The note sync's triggers: when `SessionStart`, `Stop` and `SessionEnd` start a job, a sleeper,
or nothing.

The decision reads one `git status` of the overlay and the state file, and one `rev-parse` of
`origin/main` only when an unchanged hold would back it off. It is tested in process against a
real clone; the spawn is a spy, so no test here starts a job but the one that runs `run_job`
itself. With the sync off, which every machine is until its machine file says otherwise, the
handlers read the machine file and return: no git, no spawn, on every turn of every session.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from stayfixed.config.machine import machine_config_path
from stayfixed.hooks.api import HookEvent, HookResult
from stayfixed.hooks.commands import run_hook
from stayfixed.sync import git as G
from stayfixed.sync import job as J
from stayfixed.sync import trigger as T
from stayfixed.sync.hooks import register
from stayfixed.sync.render import checkouts
from stayfixed.sync.state import (
    BACK_OFF_MINUTES,
    LOCK_FILE,
    PENDING_FILE,
    STATE_FILE,
    THROTTLE_SECONDS,
    Holds,
    Lock,
    Outcome,
    SyncState,
    iso,
    notes_mark,
    write_state,
)
from tests.floor import developer_free_environ
from tests.sync.conftest import NOW, Overlays, commit_all, context, git, head, push_note, write

NOTE = "common/memory/fresh.md"
UTC_NOW = datetime(2026, 10, 12, 13, 0, 0, tzinfo=UTC)


def _state(
    world: Overlays,
    *,
    outcome: str = "ok",
    ago: float = 600.0,
    head_sha: str | None = None,
    upstream: tuple[str, ...] = (),
    local: tuple[str, ...] = (),
    fetched: str | None = None,
    now: datetime = UTC_NOW,
) -> None:
    at = iso(now - timedelta(seconds=ago))
    write_state(
        world.state_dir,
        SyncState(
            overlay=str(world.a),
            outcome=Outcome(outcome, at, None),
            holds=Holds(upstream, local),
            fetched_sha=fetched,
            last_job_at=at,
            pending_align=None,
            head=head_sha,
            dirty=notes_mark(world.a, ()),  # the job left no note dirty
        ),
    )


def decide(
    world: Overlays, event: str, source: str | None = None, *, at: datetime = UTC_NOW
) -> str:
    return T.decide(event, source, world.a, world.state_dir, at)[0]


def a_hold(world: Overlays, ago: float, **changed: Any) -> None:
    """An upstream hold the last job recorded `ago` seconds ago, on this `HEAD` and this
    `origin/main`, unless `changed` says otherwise."""
    values: dict[str, Any] = {
        "head_sha": head(world.a),
        "fetched": head(world.a, "refs/remotes/origin/main"),
        "upstream": ("common/claude/hooks/launch.sh",),
    }
    _state(world, ago=ago, **(values | changed))


# -- when a job starts ----------------------------------------------------------------------------


def test_a_compaction_starts_nothing(overlays: Overlays) -> None:
    write(overlays.a, NOTE, "a note\n")
    _state(overlays, outcome="offline")  # every other trigger holds as well

    assert decide(overlays, "SessionStart", "compact") == "none"


def test_every_other_session_start_runs(overlays: Overlays) -> None:
    sha = head(overlays.a)
    _state(overlays, head_sha=sha, fetched=sha)  # clean, ok, pushed

    for source in ("startup", "resume", "clear", None):
        assert decide(overlays, "SessionStart", source) == "run", source

    # A hold that backs a `Stop` off does not back a session start off.
    a_hold(overlays, 60)
    assert decide(overlays, "Stop") == "none"
    assert decide(overlays, "SessionStart", "startup") == "schedule"  # throttled, not dropped
    a_hold(overlays, 1200)
    assert decide(overlays, "SessionStart", "resume") == "run"


def test_a_dirty_or_untracked_note_starts_a_job(overlays: Overlays) -> None:
    _state(overlays, head_sha=head(overlays.a))
    assert decide(overlays, "Stop") == "none"  # clean tree, ok outcome, nothing unpushed

    write(overlays.a, "projects/alpha/memory/project-stable/odd nameé.md", "a note\n")
    assert decide(overlays, "Stop") == "run"
    assert decide(overlays, "SessionEnd") == "run"


def test_a_dirty_path_outside_memory_starts_nothing(overlays: Overlays) -> None:
    _state(overlays, head_sha=head(overlays.a))
    write(overlays.a, "common/claude/hooks/x.py", "print('edited')\n")
    write(overlays.a, "projects/alpha/checkout/memory/x.md", "not a note\n")

    assert decide(overlays, "Stop") == "none"


def test_commits_ahead_of_the_upstream_start_a_job(overlays: Overlays) -> None:
    a = overlays.a
    _state(overlays, head_sha=head(a))
    write(a, NOTE, "a note\n")
    commit_all(a, "memory: by hand")
    assert git(a, "status", "--porcelain", "--", "common/memory") == ""

    assert decide(overlays, "Stop") == "run"


def test_a_standing_outcome_or_hold_starts_a_job(overlays: Overlays) -> None:
    sha = head(overlays.a)
    for outcome in ("offline", "rejected", "index_stale", "hook_failed"):
        _state(overlays, outcome=outcome, head_sha=sha)
        assert decide(overlays, "Stop") == "run", outcome
    # A united index is a success: nothing stopped the job. Mutation (oracle): `mutations/`'s "a
    # united index is not settled".
    for outcome in ("ok", "skipped", "resolved_index"):
        _state(overlays, outcome=outcome, head_sha=sha)
        assert decide(overlays, "Stop") == "none", outcome

    # A hold on a `HEAD` the last job did not leave is news: not backed off.
    _state(overlays, head_sha="0" * 40, local=("abc",), fetched=sha)
    assert decide(overlays, "Stop") == "run"
    _state(overlays, head_sha=sha, local=("abc",), fetched=sha)
    assert decide(overlays, "Stop") == "none"  # the same hold on the same HEAD: backed off

    # A state file nobody can read is not "ok": a job replaces it.
    (overlays.state_dir / STATE_FILE).write_text("{not json", encoding="utf-8")
    assert decide(overlays, "Stop") == "run"


def test_an_unchanged_hold_backs_off_until_something_moves(overlays: Overlays) -> None:
    a_hold(overlays, 60)
    assert decide(overlays, "Stop") == "none"  # a second Stop a minute later starts no job
    assert decide(overlays, "SessionEnd") == "none"
    a_hold(overlays, (BACK_OFF_MINUTES - 1) * 60)
    assert decide(overlays, "Stop") == "none"
    a_hold(overlays, (BACK_OFF_MINUTES + 1) * 60)
    assert decide(overlays, "Stop") == "run"

    a_hold(overlays, 60, head_sha="0" * 40)  # HEAD moved since that job
    assert decide(overlays, "Stop") == "schedule"
    a_hold(overlays, 60, fetched="1" * 40)  # the upstream ref moved since that job's fetch
    assert decide(overlays, "Stop") == "schedule"

    a_hold(overlays, 60)
    write(overlays.a, NOTE, "a note\n")  # a dirty note is never backed off
    assert decide(overlays, "Stop") == "schedule"
    assert decide(overlays, "SessionEnd") == "run"


def test_an_unchanged_local_hold_with_unpushed_commits_backs_off(overlays: Overlays) -> None:
    # The local hold's own commits keep `@{u}..HEAD` non-empty; that alone is no news.
    a = overlays.a
    write(a, "common/claude/hooks/x.py", "print('local hook edit')\n")
    hook_commit = commit_all(a, "hooks: local edit")
    assert git(a, "rev-list", "--count", "@{u}..HEAD").strip() == "1"

    a_hold(overlays, 5 * 60, upstream=(), local=(hook_commit,))
    assert decide(overlays, "Stop") == "none"
    assert decide(overlays, "SessionEnd") == "none"
    assert decide(overlays, "SessionStart", "startup") == "run"

    a_hold(overlays, (BACK_OFF_MINUTES + 1) * 60, upstream=(), local=(hook_commit,))
    assert decide(overlays, "Stop") == "run"
    assert decide(overlays, "SessionEnd") == "run"


def test_the_back_off_ends_when_the_upstream_ref_moves(overlays: Overlays) -> None:
    a_hold(overlays, 5 * 60)
    assert decide(overlays, "Stop") == "none"

    push_note(overlays.b, "common/memory/elsewhere.md", "from b\n")
    git(overlays.a, "fetch", "-q", "origin")  # the owner fetched by hand
    assert decide(overlays, "Stop") == "run"


def test_a_failure_only_the_owner_can_clear_backs_off_until_the_notes_change(
    overlays: Overlays,
) -> None:
    # A note the commit refuses for ever (not `.md`) keeps the tree dirty and the outcome
    # `hook_failed`: without the back-off every `Stop` would run the whole job, a fetch
    # included, every two minutes for as long as sessions run. The same outcome on the same
    # `HEAD`, upstream and notes waits; an edit of the notes is news. Mutations (oracle):
    # `mutations/`'s "the back-off ignores a standing outcome" and "the back-off ignores changed
    # notes".
    a = overlays.a
    write(a, "common/memory/notes.txt", "never a note\n")

    state = J.run_job(context(overlays, a))

    assert state is not None and state.outcome.state == "hook_failed", state
    later = NOW + timedelta(minutes=3)  # past the throttle
    assert decide(overlays, "Stop", at=later) == "none"
    assert decide(overlays, "SessionStart", "startup", at=later) == "run"
    write(a, "common/memory/notes.txt", "edited, still never a note\n")
    assert decide(overlays, "Stop", at=later) == "run"
    assert decide(overlays, "Stop", at=NOW + timedelta(minutes=BACK_OFF_MINUTES + 1)) == "run"


def test_no_scanner_backs_off_once_the_indexes_it_rendered_are_recorded(
    overlays: Overlays,
) -> None:
    # The default on a freshly set-up machine: no build, a note waiting. The first job's render
    # leaves the indexes dirty, which is news once; the second records them, and the next `Stop`
    # waits.
    (overlays.home / ".cache" / "pre-commit" / "db.db").unlink()
    write(overlays.a, "common/memory/waiting.md", "a note\n")
    for _ in range(2):
        state = J.run_job(context(overlays, overlays.a))
        assert state is not None and state.outcome.state == "scan_unavailable", state

    assert decide(overlays, "Stop", at=NOW + timedelta(minutes=3)) == "none"


def test_a_real_jobs_upstream_hold_backs_off_the_next_stop(overlays: Overlays) -> None:
    # The back-off compares `origin/main` with the sha the job fetched. The job fetches into a ref
    # of its own, so `origin/main` moves only by git's opportunistic update of the tracking ref;
    # without it every Stop would start a job, and a fetch, while the hold stands.
    b = overlays.b
    write(b, "common/claude/hooks/launch.sh", "#!/bin/sh\necho changed upstream\n")
    commit_all(b, "hooks: an upstream edit")
    git(b, "push", "-q", "origin", "main")

    state = J.run_job(context(overlays, overlays.a))

    assert state is not None
    assert state.holds.upstream_paths == ("common/claude/hooks/launch.sh",)
    assert head(overlays.a, "refs/remotes/origin/main") == state.fetched_sha
    assert decide(overlays, "Stop", at=NOW + timedelta(minutes=1)) == "none"
    assert decide(overlays, "Stop", at=NOW + timedelta(minutes=BACK_OFF_MINUTES + 1)) == "run"


# -- the throttle: schedule, never drop -----------------------------------------------------------


def test_a_trigger_inside_the_throttle_is_scheduled(overlays: Overlays) -> None:
    write(overlays.a, NOTE, "a note\n")
    _state(overlays, ago=30, head_sha=head(overlays.a))
    decision, wake = T.decide("Stop", None, overlays.a, overlays.state_dir, UTC_NOW)
    assert decision == "schedule"
    assert wake == UTC_NOW - timedelta(seconds=30) + timedelta(seconds=THROTTLE_SECONDS)

    _state(overlays, ago=600, head_sha=head(overlays.a))
    assert T.decide("Stop", None, overlays.a, overlays.state_dir, UTC_NOW) == ("run", None)


def test_a_trigger_during_a_job_only_marks_it_pending(
    overlays: Overlays, spied: dict[str, list[object]]
) -> None:
    # The running job takes the mark and runs a round for it; a sleeper as well would run one
    # more job, a fetch included, inside the throttle. Mutation (oracle): `mutations/`'s "a
    # trigger while a job runs is dropped".
    overlays.sync = True
    overlays.use(overlays.a)
    write(overlays.a, NOTE, "a note\n")
    _state(overlays, ago=600, head_sha=head(overlays.a))
    held = Lock.try_acquire(overlays.state_dir / LOCK_FILE)  # a job is running
    assert held is not None
    try:
        assert decide(overlays, "Stop") == "pending"
        assert _handle(_event(overlays, "Stop")) == [HookResult()]
    finally:
        held.release()

    assert spied["spawn"] == []
    assert (overlays.state_dir / PENDING_FILE).exists()


def test_session_end_is_never_throttled(overlays: Overlays) -> None:
    write(overlays.a, NOTE, "a note\n")
    _state(overlays, ago=10, head_sha=head(overlays.a))
    assert decide(overlays, "Stop") == "schedule"
    assert decide(overlays, "SessionEnd") == "run"

    held = Lock.try_acquire(overlays.state_dir / LOCK_FILE)
    assert held is not None
    try:
        assert decide(overlays, "SessionEnd") == "run"  # the job finds it busy and marks pending
    finally:
        held.release()


def test_the_trigger_check_is_one_git_status(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `Stop` fires on every turn: what it asks of git is one status, which carries `HEAD`, the
    # count ahead and the dirty notes in one answer; `origin/main` only for an unchanged hold.
    sha = head(overlays.a)
    _state(overlays, head_sha=sha, fetched=sha)
    calls: list[list[str]] = []
    real = G.run

    def counting(argv: Any, **kwargs: Any) -> G.Ran:
        calls.append(list(argv))
        return real(argv, **kwargs)

    monkeypatch.setattr(G, "run", counting)
    for dirty, expected in ((False, "none"), (True, "run")):
        if dirty:
            write(overlays.a, NOTE, "changed\n")
        calls.clear()
        assert decide(overlays, "Stop") == expected
        assert len(calls) == 1 and "status" in calls[0], calls


# -- the handlers ---------------------------------------------------------------------------------


def _event(world: Overlays, name: str, **raw: object) -> HookEvent:
    checkout = world.checkouts["beta"]
    return HookEvent(
        name, "s", None, None, {}, checkout, checkout, {"hook_event_name": name, **raw}
    )


def _handle(event: HookEvent) -> list[HookResult]:
    session = cast(Any, None)  # no handler of this area reads the session's configuration
    return [handler.run(event, session) for handler in register() if handler.event == event.name]


@pytest.fixture
def spied(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:
    """Every git the sync's runner starts and every job spawned, recorded and not run."""
    seen: dict[str, list[object]] = {"git": [], "spawn": []}
    real = G.run

    def recorded(argv: Any, **kwargs: Any) -> G.Ran:
        seen["git"].append(list(argv))
        return real(argv, **kwargs)

    monkeypatch.setattr(G, "run", recorded)
    monkeypatch.setattr(J, "spawn", lambda overlay, *, wake=None: seen["spawn"].append(wake))
    return seen


def test_one_handler_for_each_of_the_three_events() -> None:
    assert sorted(handler.event for handler in register()) == ["SessionEnd", "SessionStart", "Stop"]


def test_with_sync_off_stop_runs_no_git_and_spawns_nothing(
    overlays: Overlays, spied: dict[str, list[object]]
) -> None:
    # Everything else would start a job: a dirty note, a standing outcome.
    write(overlays.a, NOTE, "a note\n")
    _state(overlays, outcome="offline")
    assert not overlays.sync

    for name in ("SessionStart", "Stop", "SessionEnd"):
        assert _handle(_event(overlays, name, source="startup")) == [HookResult()]

    assert spied == {"git": [], "spawn": []}
    assert not (overlays.state_dir / PENDING_FILE).exists()


def test_with_sync_on_the_handlers_spawn_the_job(
    overlays: Overlays, spied: dict[str, list[object]]
) -> None:
    overlays.sync = True
    overlays.use(overlays.a)
    write(overlays.a, NOTE, "a note\n")

    assert _handle(_event(overlays, "Stop")) == [HookResult()]
    assert spied["spawn"] == [None]

    # A job ended ten seconds ago, by the clock the handler reads.
    _state(overlays, ago=10, head_sha=head(overlays.a), now=datetime.now(UTC))
    assert _handle(_event(overlays, "Stop")) == [HookResult()]
    [_, wake] = spied["spawn"]
    assert isinstance(wake, datetime) and wake > datetime.now(UTC)
    assert (overlays.state_dir / PENDING_FILE).exists()


def test_session_start_records_the_checkout_when_sync_is_on(
    overlays: Overlays, spied: dict[str, list[object]]
) -> None:
    beta = overlays.checkouts["beta"]
    (overlays.state_dir / "checkouts.json").unlink()
    _handle(_event(overlays, "SessionStart", source="startup"))
    assert checkouts(overlays.state_dir) == []  # off: nothing recorded

    overlays.sync = True
    overlays.use(overlays.a)
    _handle(_event(overlays, "SessionStart", source="compact"))

    assert checkouts(overlays.state_dir) == [beta]
    assert spied["spawn"] == []  # a compaction records and starts nothing


def test_no_overlay_or_not_a_repository_spawns_nothing(
    overlays: Overlays, spied: dict[str, list[object]], tmp_path: Path
) -> None:
    overlays.sync = True
    overlays.use(tmp_path / "not-a-repository")
    (tmp_path / "not-a-repository").mkdir()
    for name in ("SessionStart", "Stop", "SessionEnd"):
        _handle(_event(overlays, name, source="startup"))
    assert T.decide(
        "SessionStart", "startup", tmp_path / "absent", overlays.state_dir, UTC_NOW
    ) == (
        "none",
        None,
    )

    machine = machine_config_path()
    assert machine is not None
    machine.write_text("[sync]\nenabled = true\n", encoding="utf-8")  # on, and no overlay
    for name in ("SessionStart", "Stop", "SessionEnd"):
        _handle(_event(overlays, name, source="startup"))

    assert spied["spawn"] == []


@pytest.mark.parametrize("sync", [False, True])
def test_stop_and_session_end_print_nothing_that_blocks(
    overlays: Overlays,
    spied: dict[str, list[object]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sync: bool,
) -> None:
    # `Stop` fires on every turn: a `decision` in what it prints would keep the turn from ending.
    # Through the command as the harness runs it, with a note waiting so the handler, when the
    # sync is on, really decides to start a job.
    overlays.sync = sync
    overlays.use(overlays.a)
    write(overlays.a, NOTE, "a note\n")
    for name in ("Stop", "SessionEnd"):
        payload = {"session_id": "s", "cwd": str(overlays.checkouts["beta"])}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        assert run_hook(argparse.Namespace(event=name)) == 0
        out, err = capsys.readouterr()
        assert err == ""
        assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": name}}
    assert len(spied["spawn"]) == (2 if sync else 0)


def test_the_command_prints_nothing_that_blocks_in_a_process_of_its_own(
    overlays: Overlays,
) -> None:
    # The same through `python -m stayfixed`, sync off and on; with nothing waiting, the sync on
    # decides `none`, so no job is started by a process this test cannot reach.
    a = overlays.a
    _state(overlays, ago=600, head_sha=head(a), fetched=head(a))
    for sync in (False, True):
        overlays.sync = sync
        overlays.use(a)
        for name in ("Stop", "SessionEnd"):
            done = subprocess.run(
                [sys.executable, "-m", "stayfixed", "hook", name],
                input=json.dumps({"session_id": "s", "cwd": str(overlays.checkouts["beta"])}),
                capture_output=True,
                text=True,
                timeout=60,
                env=developer_free_environ(),
                check=False,
            )
            assert done.returncode == 0 and done.stderr == "", done
            assert "decision" not in done.stdout
            assert json.loads(done.stdout) == {"hookSpecificOutput": {"hookEventName": name}}
    assert not (overlays.state_dir / PENDING_FILE).exists()
