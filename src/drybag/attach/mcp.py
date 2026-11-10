"""The overlay's MCP servers, folded over the plates by definition and by state.

Each plate may keep `claude/mcp.json`, an object whose one key is `mcpServers`. Under it a name
maps to an object (a definition, and the name is on), to `"off"` or to `"on"`. The two folds
are independent, and a later plate wins each of them whole:

* **state** is the last plate's value of any kind, an object counting as on;
* **definition** is the last plate's object, never a field-wise merge.

So `"on"` in a later plate restores the definition an earlier plate gave, and `"off"` after a
definition switches the server off without losing it. A name is *served* when its state is on and
some plate defined it; it is *off* when its state is off, defined or not.

Every fault of the file is a note and never a refusal, and a note names the file's path and never a
value: a definition holds argv and environment, which may hold a secret.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from drybag import fsops
from drybag.config.plates import Plate
from drybag.printed import quoted

MCP_FILE = "mcp.json"
SERVERS_KEY = "mcpServers"
OFF = "off"
ON = "on"

UNREADABLE = "{path}: the file cannot be read, so it holds no MCP servers"
NOT_PARSEABLE = "{path}: the file does not parse, so it holds no MCP servers"
NOT_AN_OBJECT = "{path}: the top level is not an object, so it holds no MCP servers"
NOT_THE_KEY = "{path}: a top-level key other than mcpServers is ignored"
SERVERS_NOT_AN_OBJECT = "{path}: mcpServers is not an object, so it holds no MCP servers"
BAD_VALUE = (
    '{path}: an mcpServers entry is not an object, "off" or "on"; it is skipped (entry {position})'
)


@dataclass(frozen=True)
class Served:
    """A server to deliver: the definition of the last plate that gave one, its digest, and the
    plates its definition and its state come from."""

    definition: Mapping[str, object]
    digest: str
    defined_in: Plate
    state_in: Plate


@dataclass(frozen=True)
class Fold:
    """`served`: names on with a definition; `off`: names switched off, with the plate that says
    so; `notes`: what in the files could not be read."""

    served: dict[str, Served]
    off: dict[str, Plate]
    notes: tuple[str, ...]


def digest(definition: Mapping[str, object]) -> str:
    """The sha256 of a definition's canonical JSON, so key order is no difference."""
    text = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entries(plate: Plate, notes: list[str]) -> dict[str, object]:
    """The `mcpServers` object of `plate`'s file, or nothing with a note."""
    path = plate.directory / "claude" / MCP_FILE
    shown = quoted(str(path))
    try:
        text = fsops.read_regular_text(path)
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError):
        notes.append(UNREADABLE.format(path=shown))
        return {}
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        notes.append(NOT_PARSEABLE.format(path=shown))
        return {}
    if not isinstance(document, dict):
        notes.append(NOT_AN_OBJECT.format(path=shown))
        return {}
    if any(key != SERVERS_KEY for key in document):
        notes.append(NOT_THE_KEY.format(path=shown))
    servers = document.get(SERVERS_KEY, {})
    if not isinstance(servers, dict):
        notes.append(SERVERS_NOT_AN_OBJECT.format(path=shown))
        return {}
    kept: dict[str, object] = {}
    for position, (name, value) in enumerate(servers.items(), 1):
        if isinstance(value, dict) or value in (OFF, ON):
            kept[name] = value
        else:
            notes.append(BAD_VALUE.format(path=shown, position=position))
    return kept


def fold_mcp(plates: Sequence[Plate]) -> Fold:
    """Fold the plates' `claude/mcp.json` by definition and by state."""
    notes: list[str] = []
    definitions: dict[str, tuple[Mapping[str, object], Plate]] = {}
    states: dict[str, tuple[bool, Plate]] = {}
    for plate in plates:
        for name, value in _entries(plate, notes).items():
            if isinstance(value, dict):
                definitions[name] = (value, plate)
                states[name] = (True, plate)
            else:
                states[name] = (value == ON, plate)
    served: dict[str, Served] = {}
    off: dict[str, Plate] = {}
    for name, (on, state_plate) in states.items():
        if not on:
            off[name] = state_plate
        elif name in definitions:
            definition, defined_plate = definitions[name]
            served[name] = Served(definition, digest(definition), defined_plate, state_plate)
    return Fold(served, off, tuple(notes))
