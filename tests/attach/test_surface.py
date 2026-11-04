"""The attach area's `api.py` is held to the same contract every other area's is.

CONTRIBUTING states it once for all of them: "`api.py` is the area's import surface. Other
areas import from it and from nothing else, and its `__all__` must equal exactly what it
imports — a test parses the file and checks."
"""

from __future__ import annotations

import stayfixed.attach.api as attach


def test_the_surface_carries_what_every_consumer_reaches_for() -> None:
    # An equality and not a subset, for the reason tests/guards/test_surface.py gives: a subset
    # lets an export arrive unnoticed. What each name is doing here is written beside it, so
    # this set states the policy `api.py`'s docstring states — a name is on the surface because
    # a consumer outside this area reaches for it, or because an exported name's signature or
    # vocabulary requires it — rather than freezing whatever the list happened to hold.
    #
    # `attach` is on it since `setup --restore` runs it on each checkout the overlay's projects
    # file lists, with `Attached` it returns and `Carried`, the type of two of its fields.
    # `detach` is not, since no area runs it once `uninstall` was deleted.
    #
    # No mutation entry: the mutation is adding an export, which is two lines in `api.py` (the
    # import and the `__all__` entry) and not one substituted line. Measured by hand instead —
    # re-exporting `check` reddens this test and this test alone.
    required = {
        # the ledger and the binding, which the suite reads from outside this area; the ledger's
        # path and the `.gitignore` block are `config.layout`'s, since the core names them too
        "ledger",
        "AttachLedger",  # what `ledger` returns; a consumer cannot annotate it otherwise
        "Rendered",  # the type of `AttachLedger.render`, for the same reason
        "read_binding",
        "Binding",
        "LOCAL_SETTINGS",  # the file an earlier release merged the overlay's hook entries into
        "attach",  # `setup --restore` attaches each listed checkout
        "Attached",  # what `attach` returns
        "Carried",  # the type of two of `Attached`'s fields
    }
    assert required == set(attach.__all__)
