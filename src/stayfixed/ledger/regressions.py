"""`stayfixed bugs regressions`: run each fixed entry's `regression` and answer by its exit code.

Which statuses run, and why the run is a convenience and not a control, `docs/cli.md`'s
`stayfixed bugs regressions` says, once.

Each argv runs from the project root, under the caller's environment, with the command's
`--timeout` as its bound, in a session of its own, so what it starts shares its process group,
which `stayfixed.processes` ends however the run finishes. No runner's report is read: exit 0 is
`passed`, any other exit `failed`.
"""

from __future__ import annotations

import signal
import subprocess
import sys
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
# minutes, the value `[gates] custom_timeout_seconds` held in `presets/recommended.toml` before
# the gates went, so a project that ran its regressions under that bound runs them under the same.
DEFAULT_TIMEOUT_SECONDS = 600
# A named cap: how long a regression's group has to exit on SIGTERM before it is sent SIGKILL
# (`processes.end`): long enough for a command that ends what it started on SIGTERM, short beside
# any timeout, so a group that ignores SIGTERM is still ended.
TERM_GRACE_SECONDS = 2

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
    kept = {number: signal.signal(number, signal.default_int_handler) for number in signals}
    try:
        for entry in load_entries(root, bug_register(config)):
            argv = entry.lists["regression"]
            if entry.status != "fixed" or not argv:
                continue
            run = _run(argv, root, timeout)
            ran.append((entry, run))
            if run.verdict == INTERRUPTED:
                break
    finally:
        for number, handler in kept.items():
            signal.signal(number, handler)
    return ran


def _run(argv: Sequence[str], root: Path, timeout: int) -> Run:
    sys.stderr.flush()
    try:
        # S603: the entry's own argv, list form, never a shell. Standard input is `/dev/null`, never
        # the caller's, which could drive the command; its standard output is stayfixed's standard
        # error, so that under `--json` standard output holds the one object.
        process = subprocess.Popen(  # noqa: S603
            list(argv), cwd=root, stdin=subprocess.DEVNULL, stdout=2, start_new_session=True
        )
    except OSError as error:
        return Run(NOT_RUN, fsops.said(error))
    stopped: Run | None = None
    try:
        processes.exited(process, timeout)
    except subprocess.TimeoutExpired:
        stopped = Run(TIMED_OUT, f"ran past {timeout} s and was ended")
    except KeyboardInterrupt:
        stopped = Run(INTERRUPTED, "the run was interrupted and ended")
    finally:
        # However it finished, what it left in its group goes, while its pid is unreaped.
        processes.end(process, TERM_GRACE_SECONDS)
    if stopped is not None:
        return stopped
    code = process.returncode
    return Run(PASSED if code == 0 else FAILED, f"exit {code}")
