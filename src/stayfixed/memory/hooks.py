"""What a session hears about the store's unreviewed notes: one count line, when the set is news.

`unreviewed-notes` counts the notes the owner has not promoted at their current bytes
(`memory.reviewed`) and says so on `SessionStart` only when that set differs from the one the last
session over the same store was told about, so a store nobody changed costs no line. The set is
remembered as one digest of the notes' resolved paths, in `<data>/unreviewed/`, a file per store
named by a hash of the store's path; it holds no path and no name. The line is fixed text with a
count interpolated, so nothing a note or a repository wrote reaches it.

No `once_key`: a compacted or cleared context asks again, and hears nothing unless the set moved.
Every import below the vocabulary is inside the handler body, for discovery's reason
(`attach/hooks.py` says it).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stayfixed.hooks.api import Handler, HookEvent, HookResult

if TYPE_CHECKING:
    from stayfixed.config.session import SessionConfig

# Read by the model as well as the person, so it names the owner as the one who promotes: a line
# telling a session to run `promote` would have the agent turn unreviewed notes into standing rules.
UNREVIEWED_COUNT = (
    "stayfixed: {count} notes are unreviewed; promoting them is the owner's call "
    "(`stayfixed memory promote`)"
)
# Under the machine's data directory: the digest of the unreviewed set each store last announced.
SEEN = "unreviewed"


def _segment(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _unreviewed(event: HookEvent, session: SessionConfig) -> HookResult:
    from stayfixed.config.schema import HARNESS_MODE

    config = session.config
    if config is None or event.project_root is None or config.memory.mode == HARNESS_MODE:
        return HookResult()
    try:
        from stayfixed import fsops
        from stayfixed.config.paths import data_directory
        from stayfixed.memory.notes import walk
        from stayfixed.memory.reviewed import subject, unreviewed
        from stayfixed.memory.store import resolved, walked_groups

        store = resolved(event.project_root, config, machine=None)[0]
        if store is None:
            return HookResult()
        pending = unreviewed(store, walk(store.path, walked_groups(store, config)).notes)
        now = _segment("\n".join(sorted(subject(note.path) for note in pending)))
        base, name = data_directory() / SEEN, _segment(str(store.path.resolve()))
        try:
            before = fsops.read_regular_text(base / name)
        except (OSError, UnicodeDecodeError):
            before = None
        if before == now:
            return HookResult()
        # The plain-path form for the directory itself, as `attach.rules` writes its own records
        # under the data directory; the record goes through the walk that refuses a symlink. A
        # record that cannot be written costs a repeated line, never the line.
        try:
            base.mkdir(parents=True, exist_ok=True)
            fsops.write_within(base, name, now)
        except (OSError, fsops.UnsafePath):
            pass
        return HookResult(context=UNREVIEWED_COUNT.format(count=len(pending)) if pending else None)
    # An open handler never costs a session.
    except Exception:
        return HookResult()


def register() -> list[Handler]:
    return [Handler(name="unreviewed-notes", event="SessionStart", run=_unreviewed)]
