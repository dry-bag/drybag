"""The overlay area's import surface: everything another area may import from it.

A name is added when a consumer needs it, in a commit that says which; a name nothing imports may
go. No other area imports a private module of this one.

`setup` builds an overlay and so needs `generate`, `render`, `finish`, `target_root`,
`require_overlay` and `overlay_fault`; `Created` comes with the first two, because a return type
absent from this list is a value `setup` can hold and cannot declare. `scripts/publish_template.py`
renders the template it publishes and holds its names to one path segment, and so needs
`render_template`, `segment` and `TEMPLATE_REPOSITORY`, the one spelling of the repository `setup`'s
`create:` looks for. The runner is a leaf module
(`drybag.runner`), not this area's: every area that launches a program imports it from there, and
none reaches it through this surface.

Three names are here with no importer in `src/`, on purpose: `COMMON_CLAUDE`, `COMMON_CODEX` and
`COMMON_MEMORY`, the three `common/` directories. The layout is what a consumer reads; publishing
part of it invites the rest to be spelled again by hand, which is the drift these constants exist to
stop.

`OVERLAY_FILES` is here for `scripts/check_artifacts.py`, which asks whether a built wheel
carries every template file and can only answer that against this list. It is the one consumer
outside `src/`; the surface rule walks `scripts/` too (`tests/boundaries/test_api_surface.py`).
`upgrade` is driven by this area's own command module.

`requires_of`, `satisfies`, `Sync` and `overlay_sync` are published for the `attach` area's
session-start handler. The floor is one grammar and two readers, and the other is this area's own
`overlay-requires` row in `drybag doctor` (`overlay/doctor.py`); the overlay's sync state is the
overlay's question, asked where the overlay is owned.

`later`, the order of two versions, is the core's `drybag.semver`, which the floor's reader
builds on; `doctor` imports it from there.
"""

from drybag.overlay.create import (
    TEMPLATE_REPOSITORY,
    Created,
    finish,
    generate,
    render,
    render_template,
    target_root,
)
from drybag.overlay.identity import overlay_fault, require_overlay, segment
from drybag.overlay.layout import (
    COMMON_CLAUDE,
    COMMON_CODEX,
    COMMON_MEMORY,
    OVERLAY_FILES,
)
from drybag.overlay.requires import requires_of, satisfies
from drybag.overlay.sync import Sync, overlay_sync

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
