"""Keyed entries inside a settings file a person and several tools share.

Keying on a marker inside the command string rather than on position is what lets `upgrade`
replace what stayfixed installed while a foreign entry beside it — another plugin's, or the
owner's own — survives untouched and stays visible to `doctor`.

Two rules make "foreign entries untouched" true rather than approximately true. A group that
mixes a marked entry with an unmarked one is **split**, not replaced: the unmarked half keeps
its matcher and its position. And what the manifest stamps is `owned(document)` — the marked
entries alone — never the whole file, so a user adding a `permissions` block beside the hooks
does not freeze stayfixed's own entries forever.

The second rule is why an *unmarked* entry arriving from a caller is a refusal and not a thing
to install: unmarked, it is by definition one of the foreign entries those two rules exist to
leave alone, so nothing downstream can tell stayfixed's own wiring from somebody else's ever
again. `unmarked()` is that check, and `mark()` is what a caller is supposed to have called.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from stayfixed.errors import Refusal
from stayfixed.harnesses import lenient_settings
from stayfixed.jsonobject import json_object, json_text
from stayfixed.printed import clipped

ENTRY_MARKER = "# stayfixed:"
_MARKER = re.compile(r"#\s*stayfixed:([A-Za-z0-9][A-Za-z0-9._-]*)\s*$")
# What every refusal of a settings document calls it: the engine is handed text, never a path.
_DOCUMENT = "settings document"


class EntriesError(Refusal):
    """A settings document the engine cannot rewrite without guessing."""


class ParserLimitError(EntriesError):
    """A settings document that is valid JSON and passes a limit of this interpreter's parser.

    Its own kind, because it is not malformed: a harness whose parser has no such limit reads it,
    and may run the hooks in it. A reader that reports on such a file cannot say "it would not
    load anyway", which it may say of one that does not parse.
    """


def marker_id(command: str) -> str | None:
    match = _MARKER.search(command)
    return match.group(1) if match else None


def mark(command: str, entry_id: str) -> str:
    if marker_id(command) == entry_id:
        return command
    return f"{command}  {ENTRY_MARKER}{entry_id}"


def unmarked(wanted: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Every command in a caller's `entries` that carries no `# stayfixed:<id>` marker.

    The marker is not decoration: it is the key this whole module is built on. `owned()`
    renders the marked entries alone, and the engine stamps that rendering — so entries with
    no marker make `owned()` answer `{}` on both sides of the comparison, the digests match,
    and the artifact is reported *unchanged* while the user's settings file was never written
    and the wiring was never installed.

    Reported as a list rather than a bool so the refusal can name the offending command. The
    shape is checked on the way past for the same reason the marker is: `apply_entries` writes
    `wanted` into the user's file verbatim, and nothing between a caller and that write looks at
    it — `_entries_of` validates the *document*, never the mapping coming in. An entry that is
    not an object, or whose command is not a string, cannot be keyed either, and `marker_id`
    raises on a non-string rather than answering about one.
    """
    found: list[str] = []
    for groups in wanted.values():
        for group in groups:
            for entry in group.get("hooks") or []:
                command = entry.get("command") if isinstance(entry, dict) else entry
                if not isinstance(command, str) or marker_id(command) is None:
                    found.append(str(command))
    return found


def _past_parser(label: str) -> Callable[[str], ParserLimitError]:
    """The refusal for a settings document past a limit of the parser, named by `label`: a kind of
    its own, for the reason `ParserLimitError` gives."""
    return lambda clause: ParserLimitError(f"{label} {clause}")


def settings_object(
    document: str, label: str = _DOCUMENT, *, numbers: Callable[[str], object] = int
) -> dict[str, Any]:
    """The document as an object, with each integer literal handed to `numbers`, and empty text
    as an empty one. `label` names it in every refusal.

    Public because `attach` reads the settings file it merges into, and the overlay's files it
    merges from, by this rule: one reader, so a document the engine would refuse is one `attach`
    refuses too.
    """
    if not document.strip():
        return {}
    # A settings document may be one a clone committed, so valid JSON past the parser's reach is
    # refused rather than left to escape the callers that catch the refusal, and refused as a
    # limit and not as a shape: see `ParserLimitError`.
    return json_object(
        document,
        label,
        error=EntriesError,
        limit=_past_parser(label),
        numbers=numbers,
    )


def settings_text(raw: dict[str, Any], label: str = _DOCUMENT, *, sort_keys: bool = False) -> str:
    """A settings document `settings_object` read, as the indented text written back, or the
    refusal `settings_object` gives a document nested past the parser: see `jsonobject.json_text`
    for why one the parser read can still be too deep to write. Public for `attach`, which writes
    the settings file it merges into by this rule too."""
    return json_text(
        raw,
        label,
        error=EntriesError,
        limit=_past_parser(label),
        indent=2,
        sort_keys=sort_keys,
    )


def _hooks_table(raw: dict[str, Any]) -> dict[str, Any]:
    hooks = raw.get("hooks", {})
    if not isinstance(hooks, dict):
        raise EntriesError("'hooks' is not an object")
    return hooks


def _groups(raw: dict[str, Any], event: str) -> list[dict[str, Any]]:
    """The groups under one event, or a refusal — a shape this module cannot read is never
    filtered away. `apply_entries` writes the structure it built back over the user's file, so
    dropping a group it did not recognise deletes somebody else's hook and says nothing."""
    groups = _hooks_table(raw).get(event, [])
    # The event through `printed.clipped`: it is a key of a document a clone can commit, and this
    # refusal reaches a terminal and a model.
    if not isinstance(groups, list):
        raise EntriesError(f"'hooks.{clipped(event)}' is not a list")
    for group in groups:
        if not isinstance(group, dict):
            raise EntriesError(
                f"'hooks.{clipped(event)}' holds an entry group that is not an object"
            )
    return groups


def _entries_of(group: dict[str, Any]) -> list[dict[str, Any]]:
    """One group's entries, or a refusal, for the reason `_groups` gives. Both the list and the
    entries inside it are checked: an entry filtered out of an otherwise well-formed group is
    deleted just as silently as a whole group is, and hides better."""
    entries = group.get("hooks", [])
    if not isinstance(entries, list):
        raise EntriesError("an entry group's 'hooks' is not a list")
    for entry in entries:
        if not isinstance(entry, dict):
            raise EntriesError("an entry group holds an entry that is not an object")
    return entries


def _claimed(entry: dict[str, Any]) -> str | None:
    command = entry.get("command")
    return marker_id(command) if isinstance(command, str) else None


def _without_marked(group: dict[str, Any]) -> dict[str, Any] | None:
    """The group with stayfixed's own entries removed, or `None` when nothing foreign is left."""
    kept = [entry for entry in _entries_of(group) if _claimed(entry) is None]
    if not kept:
        return None
    return {**group, "hooks": kept}


def _read_entries(document: str) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Every hook entry in the document with its event and the group holding it, in document
    order, read as strictly as `apply_entries` reads it: a shape the merge would refuse is refused
    here too, so a reader reporting on a settings file never accounts for one the engine could not
    rewrite.

    Integers are read as their text: no entry's id, event or marker is a number, and one longer
    than the interpreter converts must not keep a reader from the entries beside it. A settings
    file is one a clone can commit, and the harness reads such a number.
    """
    raw = _entry_document(document)
    for event in _hooks_table(raw):
        for group in _groups(raw, event):
            for entry in _entries_of(group):
                yield event, group, entry


def _entry_document(document: str) -> dict[str, Any]:
    """The settings document as every walk for entries reads it: integers as their text, for the
    reason `_read_entries` gives."""
    return settings_object(document, numbers=str)


def owned_ids(document: str) -> dict[str, str]:
    """Every id stayfixed claims in this document, mapped to its event."""
    return {
        claimed: event
        for event, _, entry in _read_entries(document)
        if (claimed := _claimed(entry)) is not None
    }


def entry_count(document: str) -> int:
    """How many hook entries the document holds, **one per entry**, never keyed by id: two
    entries sharing one id are two, and an entry with no readable command is one too. Refuses
    what `owned_ids` refuses, read by the same walk.
    """
    return sum(1 for _ in _read_entries(document))


@dataclass(frozen=True)
class Walked:
    """What a walk for live hook entries read out of a settings document.

    `entries` is how many entries it read. `partly` is whether it skipped a part that could hold
    a command.
    """

    entries: int
    partly: bool


def _admitted(value: object, kind: type, skipped: list[object]) -> bool:
    """Whether `value` is the `kind` the walk reads at its place in the `hooks` section.

    The measured rule, stated once: a scalar where a list or an object belongs holds no command
    and is skipped, as Claude Code skipped it (`harnesses.LENIENT_SETTINGS` says what, where
    and when that was measured); a container of the wrong kind was not measured and may hold a
    command, so it is skipped and kept in `skipped`, for the reader to say so.
    """
    if isinstance(value, kind):
        return True
    if isinstance(value, dict | list):
        skipped.append(value)
    return False


def live_entries(document: str) -> Walked:
    """How many hook entries a harness runs out of the document, counted as `entry_count` counts.

    `entry_count` reads as strictly as `apply_entries` writes, because a merge must not rewrite
    a shape it cannot read; that is the wrong question for which entries are live. What is
    skipped is `_admitted`'s rule. One shape more is set aside without a measurement: an object
    where a group goes that carries a `command` or a `type`, as an entry does, and no `hooks` list
    -- a reader may run it as an entry, so it is kept with the skipped parts. Refuses what
    `entry_count` refuses above the events -- a document that is not a JSON object, and a
    `hooks` that is not an object -- which was not measured either.
    """
    raw = _entry_document(document)
    found = 0
    skipped: list[object] = []
    for groups in _hooks_table(raw).values():
        if not _admitted(groups, list, skipped):
            continue
        for group in groups:
            if not _admitted(group, dict, skipped):
                continue
            if "command" in group or "type" in group:
                skipped.append({key: value for key, value in group.items() if key != "hooks"})
            entries = group.get("hooks", [])
            if not _admitted(entries, list, skipped):
                continue
            for entry in entries:
                if _admitted(entry, dict, skipped):
                    found += 1
    return Walked(found, bool(skipped))


def judged_entries(document: str, *, lenient: bool) -> Walked:
    """The hook entries a reader judges in a settings file, and what it skipped.

    `lenient` for a file a harness was measured running partly malformed (`harnesses.
    LENIENT_SETTINGS`): `live_entries`, past a leading byte-order mark. Otherwise the strict
    `entry_count`, which refuses every shape the merge would, so it skips nothing.
    """
    if lenient:
        return live_entries(lenient_settings(document))
    return Walked(entry_count(document), partly=False)


def owned(document: str) -> str:
    """A canonical rendering of only the entries stayfixed claims — what the manifest stamps."""
    raw = settings_object(document)
    claimed: dict[str, list[dict[str, Any]]] = {}
    for event in sorted(_hooks_table(raw)):
        for group in _groups(raw, event):
            mine = [entry for entry in _entries_of(group) if _claimed(entry) is not None]
            if mine:
                claimed.setdefault(event, []).append({**group, "hooks": mine})
    return settings_text(claimed, sort_keys=True)


def apply_entries(document: str, wanted: dict[str, list[dict[str, Any]]]) -> str:
    raw = settings_object(document)
    hooks = dict(_hooks_table(raw))
    for event in sorted(set(hooks) | set(wanted)):
        foreign = [kept for group in _groups(raw, event) if (kept := _without_marked(group))]
        merged = foreign + list(wanted.get(event, []))
        if merged:
            hooks[event] = merged
        else:
            hooks.pop(event, None)
    return _with_hooks(raw, hooks)


def _with_hooks(raw: dict[str, Any], hooks: dict[str, Any]) -> str:
    """`raw` written back with `hooks` as its hook table, and with none where it is empty."""
    if hooks:
        raw["hooks"] = hooks
    else:
        raw.pop("hooks", None)
    return settings_text(raw) + "\n"


def withdraw_entries(document: str, recorded: Mapping[str, str]) -> str:
    """The document without each entry `recorded` names: its marker id, under the event the record
    gives it. Every other entry stays where it is, one claiming the marker that the record does not
    name included, so a caller's record and never the marker alone decides what goes; a group left
    with no entry is dropped, an event with no group, and `hooks` with no event. Read as strictly
    as `apply_entries` reads, for the reason `_groups` gives."""
    raw = settings_object(document)
    hooks = dict(_hooks_table(raw))
    for event in list(hooks):
        groups = []
        for group in _groups(raw, event):
            entries = _entries_of(group)
            kept = [entry for entry in entries if recorded.get(_claimed(entry) or "") != event]
            if kept:
                groups.append(group if len(kept) == len(entries) else {**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event)
    return _with_hooks(raw, hooks)
