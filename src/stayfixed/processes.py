"""Ending a command's whole process group, in the one order that cannot end an unrelated one.

A command stayfixed runs for a project, a regression `bugs regressions` runs, starts in a session
of its own, so what it starts shares its process group, and that group is ended however the
command finishes: exit, timeout or interrupt. A descendant that leaves the group (a new session,
or a job-control shell's own group) is not reached, and nor is one stayfixed may not signal (a
sudo or setuid descendant). The group is ended with SIGKILL, which no member can catch or ignore.

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


def kill_group(process: subprocess.Popen[bytes]) -> None:
    """Send SIGKILL to the command's whole process group; a group with nothing left to end is no
    fault.

    Empty, the group answers `ProcessLookupError`; left with only the exited, unreaped command,
    macOS answers `PermissionError` rather than nothing, as it does for any group of zombies. A
    member stayfixed may not signal, a sudo or setuid descendant, answers `PermissionError` too,
    and is not ended: the command's own exit still answers for it.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)


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
