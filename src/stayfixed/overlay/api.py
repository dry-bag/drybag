"""The overlay area's import surface: everything another area may import from it.

The list is chosen from what consumers outside this area actually reach for. An area that needs
something absent from it grows it deliberately, in a commit that says which area and why — it
does not import a private module of this area.

`setup` builds an overlay and so needs `generate`, `render`, `finish`, `target_root`,
`require_overlay` and `overlay_fault`; `Created` comes with the first two, because a return type
absent from this list is a value `setup` can hold and cannot declare. `scripts/publish_template.py`
renders the template it publishes and holds its names to one path segment, and so needs
`render_template`, `segment` and `TEMPLATE_REPOSITORY`, the one spelling of the repository `setup`'s
`create:` looks for. `attach` reads `common/claude`
and `common/codex` inside the layout (`COMMON_CLAUDE`, `COMMON_CODEX`). The runner is a leaf module
(`stayfixed.runner`), not this area's: every area that launches a program imports it from there, and
none reaches it through this surface.

One name is here with no importer in `src/`, on purpose: `COMMON_MEMORY`, the third of the three
`common/` directories beside `COMMON_CLAUDE` and `COMMON_CODEX`. The layout is what a consumer
reads; publishing two thirds of it invites the third to be spelled again by hand, which is the
drift these constants exist to stop.

`OVERLAY_FILES` is here for `scripts/check_artifacts.py`, which asks whether a built wheel
carries every template file and can only answer that against this list. It is the one consumer
outside `src/`, and the reason this docstring names it is that an earlier trim removed the
export on the strength of "nothing outside this area imports it" while that script, added in the
same branch, imported it out of `layout` — a sentence and a violation merged green together,
because the surface rule walked `src/` alone. It walks `scripts/` too now
(`tests/boundaries/test_api_surface.py`).

**Trimmed, when the area boundaries were drawn tight.** `COMMON` had no importer anywhere.
`CAPABILITY_FILES`, `template_root`, `templates`, `upgrade` and `OverlayUpgrade` had none outside
this area: `upgrade` is driven by this area's own command module, and the template tree was
published against a sentence predicting that the `release` package would need it,
which nothing in `stayfixed.release` does. If it ever does, it grows the list then, which is what
this docstring asks of every other area.

`requires_of`, `satisfies`, `Sync` and `overlay_sync` are published for the `attach` area's
session-start handler. The floor is one grammar and two readers, and the other is this area's own
`overlay-requires` row in `stayfixed doctor` (`overlay/doctor.py`); the overlay's sync state is the
overlay's question, asked where the overlay is owned.

`later`, the order of two versions, is the core's `stayfixed.semver`, which the floor's reader
builds on; `doctor` imports it from there.
"""

from stayfixed.overlay.create import (
    TEMPLATE_REPOSITORY,
    Created,
    finish,
    generate,
    render,
    render_template,
    target_root,
)
from stayfixed.overlay.identity import overlay_fault, require_overlay, segment
from stayfixed.overlay.layout import (
    COMMON_CLAUDE,
    COMMON_CODEX,
    COMMON_MEMORY,
    OVERLAY_FILES,
)
from stayfixed.overlay.requires import requires_of, satisfies
from stayfixed.overlay.sync import Sync, overlay_sync

__all__ = [
    "COMMON_CLAUDE",
    "COMMON_CODEX",
    "COMMON_MEMORY",
    "OVERLAY_FILES",
    "TEMPLATE_REPOSITORY",
    "Created",
    "Sync",
    "finish",
    "generate",
    "overlay_fault",
    "overlay_sync",
    "render",
    "render_template",
    "require_overlay",
    "requires_of",
    "satisfies",
    "segment",
    "target_root",
]
