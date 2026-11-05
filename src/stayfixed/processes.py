"""Ending a command's whole process group.

A command stayfixed starts in a session of its own, so what it starts shares its process group,
and that group is ended with SIGKILL, which no member can catch or ignore. A descendant that leaves
the group (a new session, or a job-control shell's own group) is not reached, and nor is one
stayfixed may not signal (a sudo or setuid descendant). The group's id is the command's pid, so the
group is ended before the command is reaped, while that pid names no group but its own.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess

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
