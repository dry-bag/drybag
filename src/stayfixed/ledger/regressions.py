"""`stayfixed bugs regressions`: run each fixed entry's `regression` through `prove`.

Which statuses run, and why the run is a convenience and not a control, `docs/cli.md`'s
`stayfixed bugs regressions` says, once.

Each argv runs as `prove` runs a command, from the project root, under the caller's environment,
with the command's `--timeout` as its bound; and every receipt is judged as `prove` judges it, so
an argv no runner adapter recognises is `not proven` and nothing is started for it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from stayfixed.ledger.entries import Entry, load_entries
from stayfixed.ledger.register import bug_register
from stayfixed.prove.api import INTERRUPTED, Receipt, prove

if TYPE_CHECKING:
    from stayfixed.config.schema import Config

# A named cap: how long one regression may run when `--timeout` does not say, in seconds. Ten
# minutes, the value `[gates] custom_timeout_seconds` held in `presets/recommended.toml` before
# the gates went, so a project that ran its regressions under that bound runs them under the same.
DEFAULT_TIMEOUT_SECONDS = 600


def regressions(
    root: Path, config: Config, *, timeout: int, echo: TextIO
) -> list[tuple[Entry, Receipt]]:
    """Every fixed entry that carries a `regression`, in identifier order, with the receipt of its
    run; the runner's standard output goes to `echo`. A run an interrupt ended (a Ctrl-C, or the
    SIGTERM a caller's bound sends) is the last: `prove` returns its receipt rather than
    raising, so going on would start the next runner after the signal."""
    ran: list[tuple[Entry, Receipt]] = []
    for entry in load_entries(root, bug_register(config)):
        argv = entry.lists["regression"]
        if entry.status != "fixed" or not argv:
            continue
        receipt = prove(argv, cwd=root, environ=os.environ, timeout=timeout, echo=echo)
        ran.append((entry, receipt))
        if receipt.reason == INTERRUPTED:
            break
    return ran
