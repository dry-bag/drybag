"""Ending a command's whole process group, in the one order that cannot end an unrelated one.

A command stayfixed runs for a project, a test command `prove` runs, starts in a session of
its own, so what it starts shares its process group, and that group is
ended however the command finishes: exit, timeout or interrupt. A descendant that leaves the
group (a new session, or a job-control shell's own group) is not reached, and nor is one stayfixed
may not signal (a sudo or setuid descendant). A timeout or an interrupt ends the group with
SIGTERM first (`end`), so a command that ends such a descendant on it, as `stayfixed prove` ends
its runner, can; then SIGKILL.

The group's id is the command's pid, so the order is the point: the exit is watched without
reaping (`exited`), the group is ended (`kill_group`), and only then is the command reaped, while
its pid is still taken and so names no group but its own.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time

# Reaping a command whose group was sent SIGKILL. The signal cannot be caught or ignored, so this
# is slack for the kernel, not a second bound on the command.
KILL_WAIT_SECONDS = 5


def kill_group(process: subprocess.Popen[bytes], signum: int = signal.SIGKILL) -> None:
    """Send `signum`, SIGKILL unless told otherwise, to the command's whole process group; a group
    with nothing left to end is no fault.

    Empty, the group answers `ProcessLookupError`; left with only the exited, unreaped command,
    macOS answers `PermissionError` rather than nothing, as it does for any group of zombies. A
    member stayfixed may not signal, a sudo or setuid descendant, answers `PermissionError` too,
    and is not ended: the command's own exit still answers for it.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signum)


def exited(process: subprocess.Popen[bytes], seconds: float) -> None:
    """Return once the command has exited, leaving it unreaped where the platform allows it.

    The group's id is the command's pid, and a reaped pid is free for the system to hand to an
    unrelated process that then leads a group of its own, which a later `killpg` would end. An
    exited command that is not yet reaped keeps its pid taken, so `os.waitid` with `WNOWAIT`
    watches for the exit without reaping, the group is ended, and only then is the command
    reaped. Where `os.waitid` is missing (macOS before Python 3.13) the command is reaped here,
    as `Popen.wait` does, and the group is ended just after.

    Raises `subprocess.TimeoutExpired` past `seconds`, as `Popen.wait` does.
    """
    _watched(process, seconds)


def _watched(process: subprocess.Popen[bytes], seconds: float) -> None:
    """`exited`'s wait, which `end` asks too: a caller that stands in for `exited` (a test's own
    timeout or interrupt) leaves `end`'s wait for the command it ends as it is."""
    if not hasattr(os, "waitid"):
        process.wait(timeout=seconds)
        return
    deadline = time.monotonic() + seconds
    delay = 0.0005
    flags = os.WEXITED | os.WNOHANG | os.WNOWAIT
    while os.waitid(os.P_PID, process.pid, flags) is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, seconds)
        delay = min(delay * 2, remaining, 0.05)
        time.sleep(delay)


def end(process: subprocess.Popen[bytes], grace: float) -> None:
    """End the command's whole process group and reap it: SIGTERM first, so that a command which
    ends what it started on it (`stayfixed prove`, whose runner is in a session of its own) does;
    then, once the command has exited or `grace` seconds have passed, SIGKILL to the whole group,
    which a member that ignored SIGTERM cannot outlast; then the reap, within
    `KILL_WAIT_SECONDS`. The command is watched without being reaped, as `exited` watches it, so
    the SIGKILL still reaches its group alone. An interrupt in the grace (a second Ctrl-C) still
    sends the SIGKILL, and reaps, before it goes on up.

    The grace watches the command alone, so behind a shell leader that dies on SIGTERM (`sh -c
    "stayfixed prove -- …"`) it is the leader's: the SIGKILL follows at once and ends `prove`
    inside its own grace, and a runner in a session of its own that ignores SIGTERM outlives
    both, a limit of this bound rather than a case it ends."""
    try:
        kill_group(process, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            _watched(process, grace)
    finally:
        kill_group(process)
        process.wait(timeout=KILL_WAIT_SECONDS)
