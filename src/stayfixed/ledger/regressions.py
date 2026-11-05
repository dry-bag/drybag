"""`stayfixed bugs regressions`: run each fixed entry's `regression` and answer by its exit code.

Which statuses run, and why the run is a convenience and not a control, `docs/cli.md`'s
`stayfixed bugs regressions` says, once.

Each argv runs from the project root, under the caller's environment, with the command's
`--timeout` as its bound, in a session of its own, so what it starts shares its process group,
which `stayfixed.processes` ends on a timeout or an interrupt. No runner's report is read: exit 0 is
`passed`, any other exit `failed`.
"""

from __future__ import annotations

import signal
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from stayfixed import fsops, processes
from stayfixed.ledger.entries import Entry, load_entries
from stayfixed.ledger.register import bug_register

if TYPE_CHECKING:
    from stayfixed.config.schema import Config

# A named cap: how long one regression may run when `--timeout` does not say, in seconds. Ten
# minutes, the bound regressions ran under before this command had an option of its own.
DEFAULT_TIMEOUT_SECONDS = 600

PASSED = "passed"
FAILED = "failed"
TIMED_OUT = "timed-out"
INTERRUPTED = "interrupted"
NOT_RUN = "not-run"


@dataclass(frozen=True)
class Run:
    """One regression's verdict, and what the line says beside it."""

    verdict: str
    detail: str


def regressions(root: Path, config: Config, *, timeout: int) -> list[tuple[Entry, Run]]:
    """Every fixed entry that carries a `regression`, in identifier order, with its run. A run an
    interrupt ended (a Ctrl-C, or the SIGTERM or SIGHUP that a caller's bound or a closed terminal
    sends, each read as a Ctrl-C while the runs go) is the last."""
    ran: list[tuple[Entry, Run]] = []
    signals = (signal.SIGTERM, signal.SIGHUP)
    for number in signals:
        signal.signal(number, signal.default_int_handler)
    for entry in load_entries(root, bug_register(config)):
        argv = entry.lists["regression"]
        if entry.status != "fixed" or not argv:
            continue
        run = _run(argv, root, timeout)
        ran.append((entry, run))
        if run.verdict == INTERRUPTED:
            break
    return ran


def _run(argv: Sequence[str], root: Path, timeout: int) -> Run:
    try:
        # S603: the entry's own argv, list form, never a shell. Standard input is `/dev/null`, so a
        # command that reads it ends at once instead of waiting on the terminal until `--timeout`;
        # its standard output is stayfixed's standard error, so that under `--json` standard output
        # holds the one object.
        process = subprocess.Popen(  # noqa: S603
            list(argv), cwd=root, stdin=subprocess.DEVNULL, stdout=2, start_new_session=True
        )
    except OSError as error:
        return Run(NOT_RUN, fsops.said(error))
    stopped: Run | None = None
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stopped = Run(TIMED_OUT, f"ran past {timeout} s and was ended")
    except KeyboardInterrupt:
        stopped = Run(INTERRUPTED, "the run was interrupted and ended")
    if stopped is not None:
        # Not yet reaped, so its pid still names its own group alone: what it started goes with it.
        processes.kill_group(process)
        process.wait(timeout=processes.KILL_WAIT_SECONDS)
        return stopped
    code = process.returncode
    return Run(PASSED if code == 0 else FAILED, f"exit {code}")
