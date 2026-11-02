"""What `stayfixed.hints.api` publishes, and for whom."""

from __future__ import annotations

from stayfixed.hints import api


def test_the_surface_is_what_consumers_reach_for() -> None:
    # The three checks every surface is held to are `tests/test_surfaces.py`'s; this is the list,
    # with the argument for each in `api.py`. No entry in `mutations/`: the mutation is adding an
    # export, two lines in `api.py`, as `tests/guards/test_surface.py` says of its own list.
    required = {
        # how a command reads past its launch, for prove to ask the adapters what it runs, to
        # put its assignments in the run's environment and to hand an adapter the launcher alone
        "read_launch",
        "Launch",
        # where that launcher runs the command, for prove to judge it in that directory
        "run_directory",
        # the uncommitted changes the red-run note counts, for the guards area's `test hygiene`
        "dirty_count",
    }
    assert required == set(api.__all__)
