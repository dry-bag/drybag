"""What the `sync` row in `drybag doctor` answers, one case per arm.

Every case runs the whole report through `run_checks`, as a user's `drybag doctor` does, with the
fixtures of the doctor area's own tests. The overlay is a plain repository, the scanner the
stand-in of this directory's `conftest.py` on a `PATH` that holds no other `gitleaks`, and the
state a file the job's own writer made in the test's `HOME`.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drybag.cli import build_parser, discover_registrars, run
from drybag.doctor import checks
from drybag.doctor.api import OK, SKIP, WARN
from drybag.printed import CLIPPED_CHARS
from drybag.setup.api import setup
from drybag.sync import git as G
from drybag.sync import job as J
from drybag.sync.state import (
    EMPTY_HOLDS,
    LOCAL_REWRITE,
    OUTSIDE,
    REWRITTEN,
    UNREADABLE,
    Holds,
    Outcome,
    SyncState,
    state_directory,
    write_state,
)
from tests.doctor.test_checks import _by_name, _checks, _env, _initialised, _overlay
from tests.floor import is_developers
from tests.gitfixture import git
from tests.runners import Recorder, real_git
from tests.sync.conftest import gitleaks_on_path, path_without_gitleaks

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

AT = "2026-10-12T12:00:00+00:00"
UPSTREAM = "0123456789abcdef0123456789abcdef01234567"


class Machine:
    """A report's inputs: the overlay, the machine file that records it, the environment, and a
    `PATH` with no `gitleaks` on it until `scanner` puts the stand-in there."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.overlay = _overlay(tmp_path)
        self.file = tmp_path / "machine.toml"
        self.env = _env(tmp_path)
        monkeypatch.setenv("PATH", path_without_gitleaks(tmp_path / "git-only"))

    def write(self, switch: str = "[sync]\nenabled = true\n", *, overlay: bool = True) -> Machine:
        root = f'[overlay]\nroot = "{self.overlay}"\n' if overlay else ""
        self.file.write_text(root + switch, encoding="utf-8")
        return self

    def scanner(self) -> Machine:
        """The stand-in on `PATH`."""
        gitleaks_on_path(self.tmp_path / "bin", self.monkeypatch)
        return self

    def state(
        self,
        outcome: str = "ok",
        detail: str | None = None,
        holds: Holds = EMPTY_HOLDS,
        overlay: Path | None = None,
        fetched: str | None = None,
    ) -> Machine:
        recorded = Outcome(outcome, AT, detail)
        write_state(
            state_directory(),
            SyncState(str(overlay or self.overlay), recorded, holds, fetched, AT, None, None),
        )
        return self

    def row(self) -> tuple[str, str, str]:
        root = _initialised(self.tmp_path)
        found = _by_name(_checks(self.tmp_path, root, machine=self.file, env=self.env), "sync")
        return found.status, found.detail, found.remedy


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Machine:
    return Machine(tmp_path, monkeypatch).write()


def test_a_machine_that_does_not_switch_sync_on_skips_naming_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Off is the ordinary state, so it is a skip with no remedy; it names the file and the key
    # that switch it on, for the reader who wonders why nothing syncs.
    off = Machine(tmp_path, monkeypatch).write("[sync]\nenabled = false\n")
    status, detail, remedy = off.row()
    assert (status, remedy) == (SKIP, "")
    assert str(off.file) in detail
    assert "[sync] enabled = true" in detail


def test_on_with_no_overlay_recorded_is_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, detail, remedy = Machine(tmp_path, monkeypatch).write(overlay=False).row()
    assert status == WARN
    assert "no overlay" in detail
    assert "drybag setup --overlay" in remedy


def test_on_with_a_recorded_overlay_that_is_gone_is_a_warning(machine: Machine) -> None:
    shutil.rmtree(machine.overlay)
    status, detail, _ = machine.row()
    assert (status, "not a directory" in detail) == (WARN, True)


def test_git_below_the_floor_is_a_warning_that_says_the_job_does_nothing(
    machine: Machine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A scanner is present, so the one finding the row can make is the git. Mutation (oracle): the
    # row calls an old git green.
    machine.scanner()
    shim = tmp_path / "old-git"
    shim.mkdir()
    real = shutil.which("git")
    (shim / "git").write_text(
        f'#!/bin/sh\nif [ "$1" = version ]; then echo "git version 2.42.1"; exit 0; fi\n'
        f'exec "{real}" "$@"\n',
        encoding="utf-8",
    )
    (shim / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")
    status, detail, remedy = machine.row()
    assert status == WARN
    assert "2.43" in detail
    assert "does nothing" in detail
    assert "2.42.1" in detail
    assert remedy


def test_no_gitleaks_on_path_is_a_warning_with_the_remedy_the_job_gives(machine: Machine) -> None:
    # Mutation (oracle): the row calls a missing scanner green. A warning, not red: `setup
    # --overlay` switches the sync on without installing gitleaks, so red would fail every freshly
    # set-up machine, while the job itself fails closed.
    status, detail, remedy = machine.row()
    assert status == WARN
    assert detail == "no gitleaks on PATH, so nothing is committed or pushed"
    assert remedy == "install gitleaks on the PATH the sessions run with"

    assert machine.scanner().row()[0] == OK


def test_an_upstream_hold_is_a_warning_naming_the_paths_and_the_review_command(
    machine: Machine,
) -> None:
    held = Holds(("common/claude/hooks/launch.sh",), ())
    status, detail, remedy = machine.scanner().state("ok", holds=held, fetched=UPSTREAM).row()
    assert status == WARN
    assert "common/claude/hooks/launch.sh" in detail
    assert f"git log -p --no-renames HEAD..{UPSTREAM}, then git rebase {UPSTREAM}" in remedy


def test_an_unreadable_upstream_tree_is_named_as_such_with_the_jobs_remedy(
    machine: Machine,
) -> None:
    # Not "outside memory", and not a rebase onto a tree git cannot read. Mutation (oracle):
    # `mutations/`'s "doctor calls every upstream hold outside memory".
    held = Holds(("projects/alpha/memory/GIT~1/n.md",), (), UNREADABLE)
    status, detail, remedy = machine.scanner().state("ok", holds=held, fetched=UPSTREAM).row()
    assert status == WARN
    assert "cannot be checked out" in detail and "outside memory" not in detail
    assert f"git diff --stat HEAD {UPSTREAM}" in remedy and "rebase" not in remedy


def test_a_rewritten_upstream_names_the_commits_it_dropped(machine: Machine) -> None:
    dropped = "fedcba9876543210fedcba9876543210fedcba98"
    held = Holds((dropped,), (), REWRITTEN)
    status, detail, remedy = machine.scanner().state("ok", holds=held, fetched=UPSTREAM).row()
    assert status == WARN
    assert "rewritten" in detail and dropped in detail
    assert f"git log -p {UPSTREAM}..HEAD" in remedy and f"git rebase -i {UPSTREAM}" in remedy


def test_a_local_rewrite_names_the_commits_and_both_commands(machine: Machine) -> None:
    purged = "fedcba9876543210fedcba9876543210fedcba98"
    held = Holds((purged,), (), LOCAL_REWRITE)
    status, detail, remedy = machine.scanner().state("ok", holds=held, fetched=UPSTREAM).row()
    assert status == WARN
    assert "main no longer has" in detail and "origin/main still has" in detail
    assert purged in detail
    assert f"git push --force-with-lease=refs/heads/main:{UPSTREAM} origin main" in remedy
    assert f"git rebase {UPSTREAM}" in remedy


@pytest.mark.parametrize("fetched", ["x; touch owned", "HEAD~1", None])
def test_a_recorded_sha_reaches_a_command_only_when_it_is_one(
    machine: Machine, fetched: str | None
) -> None:
    # `doctor` prints commands an agent may run: a planted `fetched_sha` never becomes one, and
    # without a sha the row names no command rather than one at a moving ref. Mutation (oracle):
    # `mutations/`'s "doctor puts any recorded sha into a command".
    held = Holds(("common/claude/hooks/launch.sh",), ())
    _, _, remedy = machine.scanner().state("ok", holds=held, fetched=fetched).row()
    assert "git " not in remedy and "touch" not in remedy
    assert "by hand" in remedy


def test_a_local_hold_is_a_warning_naming_the_commits(machine: Machine) -> None:
    held = Holds((), ("abc1234", "def5678"))
    status, detail, remedy = machine.scanner().state("ok", holds=held).row()
    assert status == WARN
    assert "abc1234" in detail
    assert "def5678" in detail
    assert "by hand" in remedy


def test_a_hold_is_named_whatever_the_last_outcome_was(machine: Machine) -> None:
    # An outcome and a hold are different: a later `offline` never clears a hold, and the row
    # names the hold first.
    held = Holds((), ("abc1234",))
    _, detail, _ = machine.scanner().state("offline", holds=held).row()
    assert "abc1234" in detail


def test_a_last_outcome_that_is_a_failure_is_a_warning_with_its_first_line(
    machine: Machine,
) -> None:
    status, detail, remedy = machine.scanner().state("offline", "first line\nsecond line").row()
    assert status == WARN
    assert "offline" in detail
    assert "first line" in detail
    assert "second line" not in detail
    assert remedy


def test_the_first_line_of_an_outcome_is_printed_as_data(machine: Machine) -> None:
    # The detail can hold what a remote or a path said: it prints escaped, never raw.
    _, detail, _ = machine.scanner().state("offline", "x\x1b[31m red\nnext").row()
    assert "\x1b" not in detail


def test_an_ok_last_outcome_is_ok_and_says_when(machine: Machine) -> None:
    status, detail, _ = machine.scanner().state("ok").row()
    assert status == OK
    assert AT in detail
    assert "ok" in detail


SKIPPED_FIX = "the job acts once this is resolved; the next session event runs it"
STANDING_FIX = "a rerun meets this again until you act on what it says"
RETRIED_FIX = "a later session event retries"


def test_a_feature_branch_is_a_warning_with_its_remedy(machine: Machine) -> None:
    # The guard's refusal is `skipped`: the sync is not running, which green would hide.
    # Mutation (oracle): `mutations/`'s "doctor calls a guard refusal green".
    git(machine.overlay, "checkout", "-q", "-b", "feature")
    reason = G.guard(machine.overlay)
    status, detail, remedy = machine.scanner().state("skipped", reason).row()
    assert (status, remedy) == (WARN, SKIPPED_FIX)
    assert "on feature, not main" in detail and "`git switch main`" in detail


def test_a_rendered_overlay_with_no_remote_warns_until_it_has_one(
    machine: Machine, tmp_path: Path
) -> None:
    # `setup --overlay <path>` renders an overlay with no remote and switches the sync on: its
    # job is `skipped` until the owner gives it one, and the row says how.
    destination = tmp_path / "rendered"
    setup(
        "recommended", home=tmp_path / "home", machine=machine.file,
        runner=Recorder(on_call=real_git), overlay=str(destination),
    )  # fmt: skip
    machine.scanner()

    def job() -> None:
        now = lambda: datetime.now(UTC)  # noqa: E731
        J.run_job(J.JobContext(destination, state_directory(), "host", now))

    job()
    status, detail, remedy = machine.row()
    assert (status, remedy) == (WARN, SKIPPED_FIX)
    assert "`git remote add origin <url>`, a commit, then `git push -u origin main`" in detail

    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(destination, "add", "-A")
    git(destination, "commit", "-q", "--no-verify", "-m", "chore: the rendered overlay")
    git(destination, "remote", "add", "origin", str(bare))
    git(destination, "push", "-q", "-u", "origin", "main")
    job()
    assert machine.row()[0] == OK


@pytest.mark.parametrize("outcome", ["secret_found", "conflict", "signing_failed"])
def test_a_standing_failure_says_a_rerun_meets_it(machine: Machine, outcome: str) -> None:
    # Mutation (oracle): `mutations/`'s "doctor promises a retry for a standing failure".
    status, detail, remedy = machine.scanner().state(outcome, "what it needs\nfindings").row()
    assert (status, remedy) == (WARN, STANDING_FIX)
    assert "what it needs" in detail and "findings" not in detail


def test_conflict_row_carries_the_whole_remedy(
    machine: Machine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The job's detail for a conflict is longer than `clipped` prints, and its one command comes
    # last, so the row gives that command apart from the detail, from the sha the job recorded,
    # in the row and in `--json`, where the doctor skill reads it.
    command = J.REVIEW.format(sha=UPSTREAM)
    detail = "x" * CLIPPED_CHARS + command
    assert f"then git rebase {UPSTREAM}" in command
    machine.scanner().state("conflict", detail, fetched=UPSTREAM)

    status, _, remedy = machine.row()
    assert status == WARN and command in remedy

    for name in list(os.environ):
        if is_developers(name):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(checks, "_own_root", lambda: None)  # `wrapper` would run this checkout
    root = _initialised(tmp_path)
    argv = ["doctor", "--json", "--root", str(root), "--home", str(tmp_path / "home")]
    run([*argv, "--machine", str(machine.file)], parser=build_parser(discover_registrars()))
    rows = json.loads(capsys.readouterr().out)["checks"]
    assert command in next(row for row in rows if row["name"] == "sync")["remedy"]

    # A planted `fetched_sha` never becomes a command. Mutation (oracle): `mutations/`'s "doctor
    # puts any recorded sha into a conflict's command".
    assert machine.state("conflict", detail, fetched="x; touch owned").row()[2] == STANDING_FIX


def test_a_retried_failure_says_a_later_event_retries(machine: Machine) -> None:
    status, _, remedy = machine.scanner().state("offline", "no route to host").row()
    assert (status, remedy) == (WARN, RETRIED_FIX)


def test_an_upstream_merge_is_named_as_one(machine: Machine) -> None:
    # A commit that lists no path is held by its sha, which is no path outside memory.
    merge = "fedcba9876543210fedcba9876543210fedcba98"
    held = Holds((merge, "common/claude/hooks/launch.sh"), (), OUTSIDE)
    _, detail, _ = machine.scanner().state("ok", holds=held, fetched=UPSTREAM).row()
    assert "changes outside memory, or a commit that lists no path (a merge)" in detail
    held = Holds(("common/claude/hooks/launch.sh",), (), OUTSIDE)
    _, detail, _ = machine.state("ok", holds=held, fetched=UPSTREAM).row()
    assert "a merge" not in detail


def test_a_stale_index_lock_is_named_with_its_remedy(machine: Machine) -> None:
    # A lock a killed git left makes every job `raced`, which is never backed off; the job never
    # removes it, since it cannot tell a stale lock from a live one, so the row names it once it
    # is older than any job runs.
    lock = machine.overlay / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    raced = machine.scanner().state("raced", "fatal: Unable to create '.../index.lock'")
    assert raced.row()[2] == RETRIED_FIX  # fresh: a git may be running
    old = time.time() - J.Limits().job - 60
    os.utime(lock, (old, old))
    status, detail, remedy = raced.row()
    assert status == WARN and str(lock) in detail
    assert remedy == f"remove {lock} if no git is running"
    assert machine.state("offline").row()[2] == RETRIED_FIX  # only a raced job names it


def test_a_linked_worktree_overlays_lock_is_found_where_git_keeps_it(machine: Machine) -> None:
    # `.git` is a file there, and the lock lives in the worktree's own directory under the main
    # one: the row asks git where, and does not guess `<overlay>/.git/index.lock`.
    git(machine.overlay, "commit", "-q", "--allow-empty", "-m", "first")
    linked = machine.tmp_path / "linked"
    git(machine.overlay, "worktree", "add", "-q", "-b", "other", str(linked))
    machine.overlay = linked
    machine.write()
    where = git(linked, "rev-parse", "--path-format=absolute", "--git-path", "index.lock")
    lock = Path(where.strip())
    assert lock.parent != linked / ".git" and not (linked / ".git").is_dir()
    lock.write_text("", encoding="utf-8")
    old = time.time() - J.Limits().job - 60
    os.utime(lock, (old, old))
    status, detail, remedy = machine.scanner().state("raced", "Unable to create index.lock").row()
    assert status == WARN and str(lock) in detail
    assert remedy == f"remove {lock} if no git is running"


def test_a_machine_that_never_ran_the_job_is_ok(machine: Machine) -> None:
    status, detail, _ = machine.scanner().row()
    assert (status, "has not run" in detail) == (OK, True)


def test_a_state_recorded_for_another_overlay_reads_as_never_run(
    machine: Machine, tmp_path: Path
) -> None:
    # The job starts afresh on such a state, so a hold or a failure recorded for the old path is
    # not this overlay's.
    held = Holds((), ("abc1234",))
    stale = machine.scanner().state("offline", holds=held, overlay=tmp_path / "elsewhere")
    status, detail, _ = stale.row()
    assert (status, "has not run" in detail) == (OK, True)


def test_a_state_nobody_can_read_is_a_warning(machine: Machine) -> None:
    directory = state_directory()
    directory.mkdir(parents=True)
    (directory / "state.json").write_text("{not json", encoding="utf-8")
    status, detail, _ = machine.scanner().row()
    assert (status, "state.json" in detail) == (WARN, True)
