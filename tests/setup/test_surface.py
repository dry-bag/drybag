"""The setup area's `api.py` is held to the same contract every other area's is.

CONTRIBUTING states it once for all of them: "`api.py` is the area's import surface. Other
areas import from it and from nothing else, and its `__all__` must equal exactly what it
imports — a test parses the file and checks."
"""

from __future__ import annotations

import drybag.setup.api as setup


def test_the_surface_carries_what_every_consumer_reaches_for() -> None:
    # An equality and not a subset, for the reason tests/guards/test_surface.py gives: a subset
    # lets an export arrive unnoticed. What each name is doing here is written beside it, so
    # this set states the policy `api.py`'s docstring states rather than freezing today's list.
    # No mutation entry: the mutation is adding an export, which is two lines in `api.py` (the
    # import and the `__all__` entry) and not one substituted line. Measured by hand instead —
    # re-exporting `machine.Written` reddens this test and this test alone.
    required = {
        # what doctor checks `setup` installed against — the whole of what an area imports here
        "USER_SETTINGS",
        # the run itself and its report, for tests/test_install_path.py's walkthrough
        "setup",
        "SetupReport",
    }
    assert required == set(setup.__all__)
