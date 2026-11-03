"""What the `sync` row in `stayfixed doctor` answers, one case per arm.

Every case runs the whole report through `run_checks`, as a user's `stayfixed doctor` does, with the
fixtures of the doctor area's own tests. The overlay is a plain repository, the scanner the
stand-in of this directory's `conftest.py` found through a pre-commit database written under
`tmp_path`, and the state a file the job's own writer made in the test's `HOME`.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from stayfixed.doctor.api import OK, RED, SKIP, WARN
from stayfixed.sync.state import (
    EMPTY_HOLDS,
    Holds,
    Outcome,
    SyncState,
    state_directory,
    write_state,
)
from tests.doctor.test_checks import _by_name, _checks, _env, _initialised, _overlay
from tests.sync.conftest import (
    GITLEAKS_REPO,
    GITLEAKS_REV,
    PRE_COMMIT_CONFIG,
    build_gitleaks,
    pre_commit_store,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

AT = "2026-10-12T12:00:00+00:00"
UPSTREAM = "0123456789abcdef0123456789abcdef01234567"


class Machine:
    """A report's inputs: the overlay, the machine file that records it, and the environment that
    lets pre-commit's database be found."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.overlay = _overlay(tmp_path)
        self.file = tmp_path / "machine.toml"
        self.env = _env(tmp_path)

    def write(self, switch: str = "[sync]\nenabled = true\n", *, overlay: bool = True) -> Machine:
        root = f'[overlay]\nroot = "{self.overlay}"\n' if overlay else ""
        self.file.write_text(root + switch, encoding="utf-8")
        return self

    def scanner(self) -> Machine:
        """The overlay pins gitleaks and pre-commit holds a build of that pin."""
        (self.overlay / ".pre-commit-config.yaml").write_text(PRE_COMMIT_CONFIG, encoding="utf-8")
        build = self.tmp_path / "gitleaks-source"
        build_gitleaks(build)
        cache = self.tmp_path / "cache"
        pre_commit_store(cache, [(GITLEAKS_REPO, GITLEAKS_REV, build)])
        self.env = _env(self.tmp_path, XDG_CACHE_HOME=str(cache))
        return self

    def state(
        self,
        outcome: str = "ok",
        detail: str | None = None,
        holds: Holds = EMPTY_HOLDS,
        overlay: Path | None = None,
        fetched: str | None = None,
    ) -> Machine:
        recorded = Outcome(outcome, AT, detail, (), ())
        write_state(
            state_directory(),
            SyncState(str(overlay or self.overlay), recorded, holds, None, fetched, AT, None, None),
        )
        return self

    def row(self) -> tuple[str, str, str]:
        root = _initialised(self.tmp_path)
        found = _by_name(_checks(self.tmp_path, root, machine=self.file, env=self.env), "sync")
        return found.status, found.detail, found.remedy


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    return Machine(tmp_path).write()


def test_a_machine_that_does_not_switch_sync_on_skips_naming_the_key(tmp_path: Path) -> None:
    # Off is the ordinary state, so it is a skip with no remedy; it names the file and the key
    # that switch it on, for the reader who wonders why nothing syncs.
    off = Machine(tmp_path).write("[sync]\nenabled = false\n")
    status, detail, remedy = off.row()
    assert (status, remedy) == (SKIP, "")
    assert str(off.file) in detail
    assert "[sync] enabled = true" in detail


def test_on_with_no_overlay_recorded_is_a_warning(tmp_path: Path) -> None:
    status, detail, remedy = Machine(tmp_path).write(overlay=False).row()
    assert status == WARN
    assert "no overlay" in detail
    assert "stayfixed setup --overlay" in remedy


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


def test_no_scanner_build_is_red_with_the_remedy_the_job_gives(machine: Machine) -> None:
    # Mutation (oracle): the row calls a missing scanner green. Red because nothing is committed
    # or pushed while it is missing, and a machine that switched sync on expects both.
    status, detail, remedy = machine.row()
    assert status == RED
    assert "nothing is committed or pushed" in detail
    assert remedy == f"run `pre-commit install-hooks` in {machine.overlay}"


def test_an_upstream_hold_is_a_warning_naming_the_paths_and_the_review_command(
    machine: Machine,
) -> None:
    held = Holds(("common/claude/hooks/launch.sh",), AT, (), None)
    status, detail, remedy = machine.scanner().state("ok", holds=held, fetched=UPSTREAM).row()
    assert status == WARN
    assert "common/claude/hooks/launch.sh" in detail
    assert f"git log -p --no-renames HEAD..{UPSTREAM}, then git rebase {UPSTREAM}" in remedy


def test_a_local_hold_is_a_warning_naming_the_commits(machine: Machine) -> None:
    held = Holds((), None, ("abc1234", "def5678"), AT)
    status, detail, remedy = machine.scanner().state("ok", holds=held).row()
    assert status == WARN
    assert "abc1234" in detail
    assert "def5678" in detail
    assert "by hand" in remedy


def test_a_hold_is_named_whatever_the_last_outcome_was(machine: Machine) -> None:
    # An outcome and a hold are different: a later `offline` never clears a hold, and the row
    # names the hold first.
    held = Holds((), None, ("abc1234",), AT)
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


@pytest.mark.parametrize("outcome", ["ok", "skipped"])
def test_a_settled_last_outcome_is_ok_and_says_when(machine: Machine, outcome: str) -> None:
    status, detail, _ = machine.scanner().state(outcome).row()
    assert status == OK
    assert AT in detail
    assert outcome in detail


def test_a_machine_that_never_ran_the_job_is_ok(machine: Machine) -> None:
    status, detail, _ = machine.scanner().row()
    assert (status, "has not run" in detail) == (OK, True)


def test_a_state_recorded_for_another_overlay_reads_as_never_run(
    machine: Machine, tmp_path: Path
) -> None:
    # The job starts afresh on such a state, so a hold or a failure recorded for the old path is
    # not this overlay's.
    held = Holds((), None, ("abc1234",), AT)
    stale = machine.scanner().state("offline", holds=held, overlay=tmp_path / "elsewhere")
    status, detail, _ = stale.row()
    assert (status, "has not run" in detail) == (OK, True)


def test_a_state_nobody_can_read_is_a_warning(machine: Machine) -> None:
    directory = state_directory()
    directory.mkdir(parents=True)
    (directory / "state.json").write_text("{not json", encoding="utf-8")
    status, detail, _ = machine.scanner().row()
    assert (status, "state.json" in detail) == (WARN, True)
