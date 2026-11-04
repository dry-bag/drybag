"""The release package's `api.py` is held to the same contract every area's is.

CONTRIBUTING states it once for all of them: "`api.py` is the area's import surface. Other
areas import from it and from nothing else, and its `__all__` must equal exactly what it
imports — a test parses the file and checks."
"""

from __future__ import annotations

import stayfixed.release.api as release


def test_the_surface_carries_what_every_consumer_reaches_for() -> None:
    # An equality and not a subset, for the reason tests/doctor/test_surface.py gives: a subset
    # lets an export arrive unnoticed. `scripts/release.py`, which checks the version, reads
    # `tag_for` and `PACKAGE`.
    required = {
        # what a release is tagged as, for the script's `check --tag`, and the package name the
        # platform's tag carries, which the script also looks the package up by in `uv.lock`
        "tag_for",
        "PACKAGE",
    }
    assert required == set(release.__all__)
