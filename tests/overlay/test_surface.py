"""The overlay area's `api.py` is held to the same contract every other area's is.

CONTRIBUTING states it once for all of them: "`api.py` is the area's import surface. Other
areas import from it and from nothing else, and its `__all__` must equal exactly what it
imports — a test parses the file and checks."

This area shipped with the install path and without the test, and it was the new surface with
the most consumers — `attach`, `doctor` and `setup` all imported from it, and `attach` and `setup`
still do — so it is the one whose contract went unasserted longest.
"""

from __future__ import annotations

import drybag.overlay.api as overlay


def test_the_surface_carries_what_every_consumer_reaches_for() -> None:
    # An equality and not a subset, for the reason tests/guards/test_surface.py gives: a subset
    # lets an export arrive unnoticed. What each name is doing here is written beside it, so
    # this set states the policy `api.py`'s docstring states rather than freezing today's list.
    # No mutation entry: the mutation is adding an export, which is two lines in `api.py` (the
    # import and the `__all__` entry) and not one substituted line. Measured by hand instead —
    # re-exporting `layout.COMMON` reddens this test and this test alone.
    # The runner is a leaf now (`drybag.runner`); an area's surface does not re-export a
    # leaf, which is why the three names this list used to carry are absent from it.
    required = {
        # creating an overlay, rendering one and finishing either, for setup
        "generate",
        "render",
        "finish",
        "Created",
        "target_root",
        "require_overlay",
        "overlay_fault",
        # rendering the template, the repository it is published as and the name grammar, for
        # `scripts/publish_template.py`
        "render_template",
        "TEMPLATE_REPOSITORY",
        "segment",
        # the layout attach reads inside the overlay
        "COMMON_CLAUDE",
        "COMMON_CODEX",
        "COMMON_MEMORY",  # the third of the three; two thirds of a layout invites a hand-spelling
        # the shipped template file list, for `scripts/check_artifacts.py` — the one consumer
        # outside `src/`, which a walk of `src/` alone does not see
        "OVERLAY_FILES",
        # the floor an overlay declares and whether a running drybag meets it, for the
        # `attach` area's session-start handler
        "requires_of",
        "satisfies",
        # the overlay repository's own sync state, for the `attach` area's session-start
        # handler
        "Sync",
        "overlay_sync",
    }
    assert required == set(overlay.__all__)
