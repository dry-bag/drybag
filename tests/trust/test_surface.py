"""The trust package's `api.py` is held to the same contract every other area's is.

CONTRIBUTING states it once for all of them: the list "is what consumers actually reach for, not
what the area finds tidy"."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import drybag.trust.api as trust
from tests.boundaries.test_delivery import IMPORT_EACH

ROOT = Path(__file__).resolve().parents[2]


def test_the_surface_carries_what_every_consumer_reaches_for() -> None:
    # An equality and not a subset, as `tests/doctor/test_surface.py` holds its own: a subset lets
    # an export arrive unnoticed, and this surface once published `approve` and `revoke`, which only
    # tests called, so both left it. What each name is doing here is written beside it. No mutation
    # entry, for that file's reason: the mutation is adding an export, two lines in `api.py` and not
    # one substituted line.
    required = {
        # where the record lives, which `setup --approval-boundary` names
        "record_path",
        # `setup --approval-boundary`'s advice: the deny rules, the user setting and the managed
        # settings that keep an agent's shell out of the record, and where managed settings live
        "record_deny_rules",
        "SANDBOX_ON",
        "ENFORCING_SETTINGS",
        "managed_named",
        # a write an agent's sandbox refused: telling one (`setup`), and the one sentence every
        # writer says it in with its remedy
        "sandbox_refused",
        "SANDBOX_REFUSED",
        "RUN_OUTSIDE",
        # the reviewed-note record `memory` keeps under kind `reviewed`: read once, with the
        # approvals it answers in and its refusal, and written by `memory promote`
        "recorded",
        "Approval",
        "UnreadableTrust",
        "approve_all",
    }
    assert required == set(trust.__all__)


def test_the_records_surface_loads_no_cli_frame() -> None:
    # The surface the record is reached through loads no CLI frame. Imported from this checkout's
    # own `src/`, and not under `-I`, which would ignore `PYTHONPATH` and import whichever
    # drybag the environment installed. No mutation of its own: the surface imports `boundary`
    # and `record`, neither of which imports the command frame.
    source = ROOT / "src"
    probe = IMPORT_EACH + "print(sys.modules['drybag'].__file__)\n"
    completed = subprocess.run(
        [sys.executable, "-c", probe, "drybag.trust.api"],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(source)},
    )
    *lines, origin = completed.stdout.splitlines()
    loaded = " ".join(lines).split()
    assert Path(origin).is_relative_to(source), origin
    assert "drybag.trust.api" in loaded
    assert "drybag.command" not in loaded
