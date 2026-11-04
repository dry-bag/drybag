# tests/guards/test_surface.py
"""What this area publishes. The three checks every surface is held to are
`tests/test_surfaces.py`'s; this list is the one thing that is this area's own."""

from __future__ import annotations

import stayfixed.guards.api as guards


def test_the_surface_carries_what_every_consumer_reaches_for() -> None:
    # This list is the contract. A consumer that needs something absent from it grows the list
    # deliberately, in a commit that says which consumer and why — and an EQUALITY is what makes
    # that true. `required <= set(__all__)` let an export be added and pass, and so did the
    # parse that compares `__all__` against this module's own imports: adding an import and an
    # `__all__` entry together satisfied both, so between them the two could only catch a
    # REMOVED export.
    #
    # No entry in `mutations/`: the mutation is adding an export, which is two lines in
    # `api.py` (the import and the `__all__` entry) and not one substituted line. Measured by
    # hand instead — re-exporting `commit.strip_message` reddens this test and this test alone,
    # and under the old `required <= set(...)` the very same change left all three tests green.
    #
    # What is below is what another area reaches for, with the argument for each in `api.py`.
    required = {
        # the git hook, for setup, the two results its verbs return, and what uninstall found
        "HOOK_NAME",
        "HOOK_MARKER",
        "Found",
        "Installed",
        "Removed",
        "install",
        "uninstall",
    }
    assert required == set(guards.__all__)
