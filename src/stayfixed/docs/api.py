"""The import surface: everything a consumer may import from this area.

A module and not the package's `__init__`, for the reason `stayfixed.guards.api`,
and `stayfixed.memory.api` both give: area discovery imports a package
before it imports the submodule it wants, so a re-export list in `__init__.py` would pull this
whole area — and with it the configuration layer — into every `discover()` call.
`tests/docs/test_surface.py` asserts the `__init__` imports nothing at all.

**Outside this area, `project` imports `trail_target` (the paragraphs on `trail_path` and
`trail_target` say why); nothing imports any other name on this list**, measured over `src/`,
`scripts/` and `tests/`: this area's own tests reach `stayfixed.docs.plans`,
`stayfixed.docs.hygiene` and `stayfixed.docs.trail` directly, and every other area runs the
commands.
So every other name below is here on an argument rather than on a caller, and the argument is
written beside it — a surface that survives a trim with no explanation is what made the trim
necessary.

The two besides `trail_target` are checks this area *is*, one call each: `check_budgets` and
`check_links` each answer one question about the documentation tree and return `Finding`s from
`stayfixed.findings`, the leaf three areas share — a consumer imports the finding shape from there,
not from here.

`lint` and the `Lint` it returns are **not** here: `plan check` is this area's own.

`Finding` and `labels` are **not** here: they are `stayfixed.findings`', and a consumer imports
them from there.

**The trail half is not here.** The markers, the file name, `Trail`, `read_trail`,
`trail_path`, `render_listing`, `rebuild` and `undeclared_new_documents` stay in
`stayfixed.docs.trail`, which `docs/commands.py` and this area's own tests reach directly: no
other area reads them, and an area that needs one grows this list, in a commit that says which
area and why.

The two checks above have no importer; they stay on an argument about shape — one call per
check rather than the machinery behind it — and on `tests/test_surfaces.py`'s floor, which
refuses a surface exporting no function or record at all. Whether this area publishes at all
is a structural decision and the owner's.

**`trail_target`, for the `project` area**, which ships `trail.toml` beside the roadmap template
and must put it where `docs trail` reads it, under the *preset's* `[paths]`, a place this
configuration may never use. It is the location with no disk access, and the engine contains
every target it plans: `trail_path` contains its answer against the root, so asked there it
would refuse whenever that place passed through a symlink, and it stays in
`stayfixed.docs.trail` for this area's own commands.
"""

from stayfixed.docs.hygiene import check_budgets, check_links
from stayfixed.docs.trail import trail_target

__all__ = [
    "check_budgets",
    "check_links",
    "trail_target",
]
