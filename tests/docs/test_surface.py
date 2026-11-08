"""What this area publishes. The three checks every surface is held to are
`tests/test_surfaces.py`'s; this list is the one thing that is this area's own."""

from __future__ import annotations

import stayfixed.docs.api as docs


def test_the_surface_carries_what_every_consumer_reaches_for() -> None:
    # An equality and not a subset, for the reason tests/guards/test_surface.py gives: a subset
    # lets an export arrive unnoticed. No mutation entry: the mutation is adding an export,
    # which is two lines in `api.py` (the import and the `__all__` entry) and not one
    # substituted line. Measured by hand instead — re-exporting `trail.TRAIL_FILE` reddens this
    # test and this test alone.
    #
    # The names below have no importer and stay on the argument written beside them in `api.py`.
    required = {
        # two checks this area is, one call each
        "check_budgets",
        "check_links",
    }
    assert required == set(docs.__all__)
