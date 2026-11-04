"""The pre-render: the overlay's `MEMORY.md` indexes, rendered before the job commits.

An index renders only from a checkout bound to its project, so the `SessionStart` handler records
each project root this machine's sessions open (`remember_checkout`), and the job renders through
the newest one bound to each project whose notes changed, and through every recorded one when a
shared or a group note did: which projects carry a group is another reader's. A project it cannot
render keeps its index out of the commit, named; its notes still travel.

It never renders through a link on the overlay's side: with `projects/<name>`, its `memory` or
`common/memory` a link, the notes the render harvests into and the index it writes are somewhere
else. And it renders only while the machine file records this overlay, since the render writes
into the overlay the machine file records.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from stayfixed import fsops
from stayfixed.binding import bound_project
from stayfixed.errors import StayfixedError
from stayfixed.memory.api import COMMON, PROJECTS, STORE_DIR, rerender_overlay_index
from stayfixed.sync.rules import INDEX_NAME, index_of, memory_path
from stayfixed.sync.state import CHECKOUTS_FILE

# A named cap: how many project roots `checkouts.json` keeps, newest first; a machine opens far
# fewer. No shipped file states it.
CHECKOUTS_KEPT = 64
# A named cap on the bytes of `checkouts.json` read: 64 paths are far under it.
CHECKOUTS_BYTES = 256 * 1024
NO_CHECKOUT = "not pre-rendered: no checkout this machine's sessions opened is bound to it"
LINKED = "not pre-rendered: a link (or a file) stands at {path}, so the store is not the overlay's"


def checkouts(d: Path) -> list[Path]:
    """The project roots recorded in `d`, newest first; none when the file is absent or garbled."""
    try:
        data = json.loads(fsops.read_regular_text(d / CHECKOUTS_FILE, limit=CHECKOUTS_BYTES))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    items = data if isinstance(data, list) else []
    return [Path(item) for item in items if isinstance(item, str) and Path(item).is_absolute()]


def remember_checkout(root: Path, d: Path) -> None:
    """Put `root` first in `d`'s record of checkouts, keeping the newest `CHECKOUTS_KEPT`."""
    kept = [root, *(path for path in checkouts(d) if path != root)][:CHECKOUTS_KEPT]
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = json.dumps([str(path) for path in kept], indent=2) + "\n"
    fsops.write_atomically(d / CHECKOUTS_FILE, text)


def unsafe_parent(overlay: Path, path: str) -> str | None:
    """The first directory above the top-relative `path` that is a link or not a directory, or
    `None` when each is a real directory or absent. Anchor: what is at each ancestor, unfollowed."""
    parts = path.split("/")[:-1]
    for depth in range(1, len(parts) + 1):
        current = overlay.joinpath(*parts[:depth])
        if fsops.is_symlink(current) or (fsops.exists(current) and not fsops.is_dir(current)):
            return "/".join(parts[:depth])
    return None


def _render(overlay: Path, root: Path, project: str) -> str | None:
    """Render `project`'s index from the checkout `root`; why it was not, or `None`."""
    index = index_of(project)
    for path in (index, f"{COMMON.as_posix()}/{INDEX_NAME}"):
        linked = unsafe_parent(overlay, path)
        if linked is not None:
            return LINKED.format(path=linked)
    if fsops.is_symlink(overlay / index):
        return LINKED.format(path=index)
    done = rerender_overlay_index(root, machine=None)
    if done.reason is not None:
        return f"not pre-rendered: {done.reason}"
    if done.overlay_store != (overlay / index).parent.resolve():
        return "not pre-rendered: its checkout's index is not this overlay's"
    return None


def prerender(
    overlay: Path, dirty: list[str], d: Path, *, also: Iterable[str] = ()
) -> dict[str, str]:
    """Render the index of every project whose notes in `dirty` changed, and of `also`; every
    recorded checkout's when a shared or a group note changed. Each project whose index was not
    rendered, and why: the caller keeps those indexes out of its commit."""
    parsed = [entry for entry in map(memory_path, dirty) if entry is not None]
    named = {entry.name for entry in parsed if entry.scope == "project" and entry.name}
    wanted = {name for name in named | set(also) if _plain(name)}
    shared = any(entry.scope != "project" for entry in parsed)
    reasons: dict[str, str] = {}
    done: set[str] = set()
    for root in checkouts(d):
        try:
            found = bound_project(root)
        except (StayfixedError, OSError):
            continue
        if found is None or found.project in done or not _plain(found.project):
            continue
        project = found.project
        share = overlay / PROJECTS / project / STORE_DIR
        if project not in wanted and not (shared and fsops.is_dir(share)):
            continue
        done.add(project)
        reason = _render(overlay, root, project)
        if reason is not None:
            reasons[project] = reason
    reasons.update(dict.fromkeys(sorted(wanted - done), NO_CHECKOUT))
    return reasons


def _plain(project: str) -> bool:
    """Whether `project` is a name whose notes may move at all (`MemoryPath.is_note`)."""
    parsed = memory_path(index_of(project))
    return parsed is not None and parsed.is_note
