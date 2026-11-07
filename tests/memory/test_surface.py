"""What this area publishes. The three checks every surface is held to are
`tests/test_surfaces.py`'s; this list is the one thing that is this area's own."""

from __future__ import annotations

import stayfixed.memory.api as memory


def test_the_memory_surface_carries_what_every_consumer_reaches_for() -> None:
    # This list is the contract. A consumer that needs something absent from it grows the list
    # deliberately, in a commit that says which consumer and why — it does not import a private
    # module, and it does not get told after the fact that its import was a review finding.
    #
    # An equality, because every name below has its argument, in `api.py` or beside it here, and
    # a subset lets an export arrive unnoticed — the hole `tests/guards/test_surface.py` names.
    #
    # No entry in `mutations/`, for the reason every other area's surface test gives: the
    # mutation is adding an export, which is two lines in `api.py` — the import and the
    # `__all__` entry — and not one substituted line. Measured by hand instead: re-exporting
    # `store.refusal_reason` reddens this test and this test alone, and under the old
    # `required <= set(...)` it reddened nothing at all.
    required = {
        # the resolver and the store it yields, for attach
        "resolve",
        "Store",
        "project_notes",
        # the overlay's per-project layout: attach writes it, overlay renders it
        "PROJECTS",
        "RECORD",
        "STORE_DIR",
        "reserved",
        # the three roots of the overlay's notes, which `sync` builds its pathspecs from
        "COMMON",
        # the index render `sync` runs in process from a bound checkout before it commits, and
        # what that render answers
        "rerender_overlay_index",
        "Rerendered",
        # the one reader of the overlay's project record, which attach reads with a policy of its
        # own
        "read_binding_record",
        # every path the composed store's links point at in the overlay, which attach asks the
        # length of before its first write
        "link_sources",
        # the composed store attach builds, points the harness at and renders the missing index
        # of, and detach withdraws, and its directory, which the attached row compares the pointer
        # with
        "build_composed",
        "composed_directory",
        "render_missing_index",
        "withdraw_composed",
        # the bundle slots, which tests/hooks/test_hooks_json.py holds the hooks file to
        "SLOTS",
        # the trust region, whole. Reading one needs `markers` and `DELIMITER`, which
        # tests/test_install_path.py already imports; producing one needs `wrap`, which draws its
        # own nonce. Half a closed vocabulary cannot be used by the consumer handed a value from
        # it.
        "markers",
        "DELIMITER",
        "wrap",
        # the binding's one classifier and its whole vocabulary: `attach`, `attach --check`,
        # the `attached` row and the session-start line answer the binding question with it, where
        # a second classifier in `attach` had drifted from this one
        "binding_state",
        "BINDING_STATES",
        "BOUND",
        "UNBOUND",
        # the note a moved `origin` earns, which attach and the session-start line say
        "origin_note",
        # the unreviewed notes of the overlay's share for a project recorded as reviewed, which
        # `setup --restore --yes` runs for each project it attaches
        "promote_share",
        # the project's memory directories the composed store leaves unlinked for being in the
        # tag namespace, which the `attached` row names
        "reserved_project_groups",
    }
    assert required == set(memory.__all__)
