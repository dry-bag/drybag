"""What this area publishes. The three checks every surface is held to are
`tests/test_surfaces.py`'s; this list is the one thing that is this area's own."""

from __future__ import annotations

import stayfixed.ledger.api as ledger


def test_the_surface_carries_what_every_consumer_reaches_for() -> None:
    # An equality, for the reason tests/guards/test_surface.py gives: a subset let an export
    # arrive unnoticed. No mutation entry: the mutation is adding an export (two lines).
    # Measured by hand instead — re-exporting `write.file_entry` reddens this test and this
    # test alone.
    #
    # Outside this area, `stayfixed.assess.gates` imports `bugs_gate`,
    # `stayfixed.project.templates` imports `render_index`, `bug_register`, `BUG_RUNBOOK`,
    # `BUG_AUDITS` and `ledger_path`, and `stayfixed.docs.plans` imports
    # `bug_register`; the other names stay on the argument written beside them in `api.py`: the
    # two artifacts this area leaves on a project's disk, and the register they are read and
    # written against.
    required = {
        # the entry file's grammar, and the error a file that will not parse raises
        "Entry",
        "parse_entry",
        "load_entries",
        "LedgerError",
        # the generated index: writing one, and recognising one already there rather than
        # overwriting a file a person wrote
        "render_index",
        "is_generated_index",
        # the register both are read and written against, and the bug ledger's: the three types
        # are derived from the signatures above by tests/test_surfaces.py
        "Register",
        "Schema",
        "Section",
        "bug_register",
        # the names `init` writes the bug ledger's runbook and audits README under, which its
        # register links, and the join of each to its root-relative directory that both share
        "BUG_RUNBOOK",
        "BUG_AUDITS",
        "ledger_path",
        # the bugs gate stayfixed.assess.gates runs, bugs check's own function
        "bugs_gate",
    }
    assert required == set(ledger.__all__)
