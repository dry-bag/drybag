"""Keyed entries inside a settings file a person and several tools share.

Keying on a marker inside the command string rather than on position is what lets stayfixed
withdraw what it installed while a foreign entry beside it — another plugin's, or the owner's own
— survives untouched and stays visible to `doctor`. A group that mixes a withdrawn entry with one
that stays is **split**, not dropped: the rest keeps its matcher and its position.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from stayfixed.errors import Refusal
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


def settings_text(raw: dict[str, Any], label: str = _DOCUMENT) -> str:
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
    )


def _hooks_table(raw: dict[str, Any]) -> dict[str, Any]:
    hooks = raw.get("hooks", {})
    if not isinstance(hooks, dict):
        raise EntriesError("'hooks' is not an object")
    return hooks


def _groups(raw: dict[str, Any], event: str) -> list[dict[str, Any]]:
    """The groups under one event, or a refusal — a shape this module cannot read is never
    filtered away. `withdraw_entries` writes the structure it built back over the user's file, so
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


def _read_entries(document: str) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Every hook entry in the document with its event and the group holding it, in document
    order, read as strictly as `withdraw_entries` reads it: a shape the withdrawal would refuse is
    refused here too, so a reader reporting on a settings file never accounts for one the engine
    could not rewrite.

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


def withdraw_entries(document: str, recorded: Mapping[str, str]) -> str:
    """The document without each entry `recorded` names: its marker id, under the event the record
    gives it. Every other entry stays where it is, one claiming the marker that the record does not
    name included, so a caller's record and never the marker alone decides what goes; a group left
    with no entry is dropped, an event with no group, and `hooks` with no event. A shape it cannot
    read is refused, for the reason `_groups` gives."""
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
    if hooks:
        raw["hooks"] = hooks
    else:
        raw.pop("hooks", None)
    return settings_text(raw) + "\n"
