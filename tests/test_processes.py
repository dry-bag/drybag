"""The core's bounded launch: a session of its own, standard input closed or given, and the whole
group ended on a timeout, so a helper under the command cannot outlive the step that started it.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

from stayfixed.processes import Ran, run_bounded

ENV = {"PATH": os.environ["PATH"]}


def test_a_timeout_ends_the_whole_group(tmp_path: Path) -> None:
    # The grandchild holds the pipes, so a kill of the child alone leaves it running and the
    # reads waiting. Mutations (oracle): `mutations/`'s "a timeout ends the child and not its
    # group" and "the child shares the caller's session" -> this reddens.
    pidfile = tmp_path / "grandchild.pid"
    script = f"sleep 300 & echo $! > '{pidfile}'; wait"

    ran = run_bounded(["sh", "-c", script], cwd=tmp_path, env=ENV, timeout=2)

    assert ran.timed_out is True
    pid = int(pidfile.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    os.kill(pid, signal.SIGKILL)  # the one pid this test started
    pytest.fail("the grandchild outlived the timeout: only the child was ended, not its group")


def test_a_program_that_is_not_there_is_127(tmp_path: Path) -> None:
    missing = run_bounded([str(tmp_path / "no-such-program")], cwd=tmp_path, env=ENV, timeout=60)
    assert (missing.code, missing.timed_out) == (127, False)
    assert b"no-such-program" in missing.err

    nowhere = run_bounded(["sh", "-c", "true"], cwd=tmp_path / "absent", env=ENV, timeout=60)
    assert nowhere.code == 127 and nowhere.err


def test_stdin_is_the_bytes_or_closed(tmp_path: Path) -> None:
    given = run_bounded(["cat"], cwd=tmp_path, env=ENV, timeout=60, stdin=b"bytes in\n")
    assert given == Ran(0, b"bytes in\n", b"", False)
    # Nothing a bounded launch runs may wait for an answer: with no input given, stdin is empty.
    assert run_bounded(["cat"], cwd=tmp_path, env=ENV, timeout=60).out == b""


def test_the_child_gets_the_environment_it_is_handed_and_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STAYFIXED_INHERITED", "1")
    ran = run_bounded(["env"], cwd=tmp_path, env={**ENV, "GIVEN": "yes"}, timeout=60)
    assert b"GIVEN=yes" in ran.out and b"STAYFIXED_INHERITED" not in ran.out
