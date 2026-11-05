"""The note sync's row in `stayfixed doctor`: `sync`.

One row, read off this machine's own records: the switch in the machine file, the git the job
needs, the `gitleaks` on `PATH` it needs, and the state its last job left. It runs nothing but
`git version`, and writes nothing. `doctor`'s core discovers this module by name (CONTRIBUTING.md,
"Areas"); every import sits inside a function body, as in a `hooks.py`, because discovery imports
it before the report asks anything and the note layout and the job pull in the configuration layer.

The arms, in the order they are asked: off (a skip, the ordinary state), no overlay recorded, git
below the job's floor, no gitleaks on `PATH`, a hold, a last outcome that is a failure, and
otherwise green. A state recorded for another overlay is not this overlay's: it reads as never
run, as the job reads it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from stayfixed.doctor.api import Context, Contribution, Row
    from stayfixed.sync.state import Holds

# A named cap: how long `git version` may take. The five seconds the report's other git queries
# get; no shipped file states it.
VERSION_TIMEOUT = 5.0
# How many names of a hold the row prints before it counts the rest.
SHOWN = 3


def _names(names: tuple[str, ...]) -> str:
    from stayfixed.printed import clipped

    shown = ", ".join(clipped(name) for name in names[:SHOWN])
    return shown + (f" and {len(names) - SHOWN} more" if len(names) > SHOWN else "")


def _held(holds: Holds, fetched: str | None, overlay: Path) -> Row:
    """The warning for a hold: what is held, and how to take it. A command names the recorded
    upstream sha only when it is one: `state.json` is a file, and an agent may run what this
    prints."""
    from stayfixed.doctor.api import WARN, Row
    from stayfixed.sync.job import LOCAL_REVIEW, REVIEW, REWRITE, UNREADABLE_REVIEW
    from stayfixed.sync.state import LOCAL_REWRITE, OUTSIDE, REWRITTEN, UNREADABLE, full_sha

    held = {
        OUTSIDE: ("upstream holds changes outside memory", REVIEW),
        UNREADABLE: ("upstream's tree cannot be checked out here", UNREADABLE_REVIEW),
        REWRITTEN: ("upstream was rewritten and dropped commits this overlay has", REWRITE),
        LOCAL_REWRITE: ("main no longer has commits that origin/main still has", LOCAL_REVIEW),
    }
    said: list[str] = []
    fixes: list[str] = []
    if holds.upstream_paths:
        what, review = held[holds.upstream_why or OUTSIDE]
        said.append(f"{what} ({_names(holds.upstream_paths)}), so nothing is integrated or pushed")
        fixes.append(
            f"in {overlay}: {review.format(sha=fetched)}"
            if full_sha(fetched)
            else "review upstream by hand; the next job clears the hold once it is settled"
        )
    if holds.local_commits:
        said.append(f"local commits outside memory are not pushed ({_names(holds.local_commits)})")
        fixes.append("review the commits and push them by hand")
    return Row(WARN, "; ".join(said), "; ".join(fixes))


def _sync(context: Context) -> Row:
    from pathlib import Path

    from stayfixed import fsops
    from stayfixed.config.machine import machine_config_path
    from stayfixed.doctor.api import OK, SKIP, WARN, Row
    from stayfixed.printed import clipped
    from stayfixed.sync import scan
    from stayfixed.sync.git import MIN_GIT, git, version_ok
    from stayfixed.sync.state import SETTLED, StateUnreadable, read_state, state_directory

    if not context.session.owner.sync.enabled:
        where = context.machine or machine_config_path() or "the machine file"
        return Row(SKIP, f"the note sync is off; `[sync] enabled = true` in {where} switches it on")
    overlay = context.overlay_root
    if not isinstance(overlay, Path) or not fsops.is_dir(overlay):
        return Row(
            WARN,
            "the note sync is on and this machine records no overlay, or one that is not a "
            "directory, so the job has nothing to sync",
            "record the overlay with `stayfixed setup --overlay <path>`",
        )
    version = git(overlay, "version", timeout=VERSION_TIMEOUT)
    if version.code != 0 or not version_ok(version.out):
        found = clipped(version.out.strip() or version.err.strip() or "no answer")
        floor = ".".join(map(str, MIN_GIT))
        return Row(
            WARN,
            f"git {floor} or newer is needed and the job does nothing without it; found: {found}",
            f"install git {floor} or newer",
        )
    if scan.gitleaks() is None:
        said, _, remedy = scan.NO_SCANNER.partition("; ")
        return Row(WARN, said, remedy)
    try:
        state = read_state(state_directory())
    except StateUnreadable as error:
        return Row(
            WARN,
            f"the job's record is unreadable ({error})",
            "remove it; the next job writes a new one",
        )
    if state is None or state.overlay != str(overlay):
        return Row(OK, "the note sync is on and its job has not run for this overlay yet")
    if state.holds.any:
        return _held(state.holds, state.fetched_sha, overlay)
    outcome = state.outcome
    first = clipped(outcome.detail.splitlines()[0]) if outcome.detail else ""
    said = f"the last job ended {outcome.at}: {outcome.state}" + (f" ({first})" if first else "")
    if outcome.state in SETTLED:
        return Row(OK, said)
    return Row(WARN, said, "a later session event retries; the detail says what stopped the job")


def register() -> Contribution:
    """The one `sync` row."""
    from stayfixed.doctor.api import Contribution

    return Contribution(checks=(("sync", _sync),))
