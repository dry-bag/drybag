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
value: a definition holds argv and environment, which may hold a secret. A file that is there and
cannot be read as an object of servers makes the fold unusable (`Fold.usable`), and then no
server is delivered or taken back and no deny entry written or withdrawn: a merge's conflict
markers must not read as "the overlay serves nothing".

**The reconcile** brings Claude Code's local-scope entries of the main checkout in line with the
served names, through `claude mcp add-json` and `remove` alone, under a ledger that holds each name
`attach` owns with the digest it delivered, or `UNSETTLED` where a call for it was started and its
outcome is not known to be good. Every name to touch is marked `UNSETTLED` in one save before the
first call, so no state exists in which an entry `attach` wrote is in `~/.claude.json` and the
ledger does not hold its name, and an interrupted run is settled by the next one with no advice. A
name whose digest is unchanged is never touched, since `remove` of a remote server signs it out.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from drybag import fsops
from drybag.attach.items import PROJECT_CLAUDE
from drybag.attach.render import MCP_ADD_JSON_LOCAL, MCP_REMOVE_LOCAL, filled
from drybag.binding import MCP_LEDGER_FILE, MCP_LEDGER_NAME, common_directory
from drybag.config.plates import Plate
from drybag.jsonobject import json_object
from drybag.printed import answered, quoted
from drybag.runner import NOT_FOUND, TIMED_OUT, Completed, Runner

MCP_FILE = "mcp.json"
SERVERS_KEY = "mcpServers"
OFF = "off"
ON = "on"

UNUSABLE = (
    "{path} cannot be read as a JSON object whose mcpServers is an object, so no MCP server or "
    "deny entry changes until it can"
)
NOT_THE_KEY = "{path}: a top-level key other than mcpServers is ignored"
BAD_VALUE = (
    '{path}: an mcpServers entry is not an object, "off" or "on", or holds NaN or Infinity; it is '
    "skipped (entry {position})"
)
UNPASSABLE = (
    "{path}: an mcpServers name holds a NUL or a lone surrogate, which no command line can carry; "
    "it is skipped (entry {position})"
)
ON_ALONE = '{path}: {name} is "on" and no plate defines it or switches it off, so it does nothing'


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
    usable: bool = True


def digest(definition: Mapping[str, object]) -> str:
    """The sha256 of a definition's canonical JSON, so key order is no difference."""
    text = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _entries(plate: Plate, notes: list[str]) -> dict[str, object] | None:
    """The `mcpServers` object of `plate`'s file, nothing where there is no file, and `None` with
    a note where the file is there and unusable."""
    path = plate.directory / PROJECT_CLAUDE / MCP_FILE
    shown = quoted(str(path))
    try:
        document = json_object(fsops.read_regular_text(path), shown, error=ValueError)
        servers = document.get(SERVERS_KEY, {})
        if not isinstance(servers, dict):
            raise ValueError(SERVERS_KEY)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        notes.append(UNUSABLE.format(path=shown))
        return None
    if any(key != SERVERS_KEY for key in document):
        notes.append(NOT_THE_KEY.format(path=shown))
    kept: dict[str, object] = {}
    for position, (name, value) in enumerate(servers.items(), 1):
        if "\0" in name or not _encodes(name):
            notes.append(UNPASSABLE.format(path=shown, position=position))
        elif value not in (OFF, ON) and not (isinstance(value, dict) and _finite(value)):
            notes.append(BAD_VALUE.format(path=shown, position=position))
        else:
            kept[name] = value
    return kept


def _encodes(name: str) -> bool:
    """Whether `name` can be an argv word: a lone surrogate, which `json.loads` makes of a
    `\\ud800`, encodes as no UTF-8. A definition is passed as ASCII JSON and always can."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _finite(definition: dict[str, object]) -> bool:
    """Whether `definition` holds no `NaN` or `Infinity`, which `json.loads` reads and Claude Code
    refuses on every run."""
    try:
        json.dumps(definition, allow_nan=False)
    except ValueError:
        return False
    return True


def fold_mcp(plates: Sequence[Plate]) -> Fold:
    """Fold the plates' `claude/mcp.json` by definition and by state."""
    notes: list[str] = []
    definitions: dict[str, tuple[Mapping[str, object], Plate]] = {}
    states: dict[str, tuple[bool, Plate]] = {}
    switched: set[str] = set()
    usable = True
    for plate in plates:
        entries = _entries(plate, notes)
        usable = usable and entries is not None
        for name, value in (entries or {}).items():
            if isinstance(value, dict):
                definitions[name] = (value, plate)
                states[name] = (True, plate)
            else:
                states[name] = (value == ON, plate)
                if value == OFF:
                    switched.add(name)
    served: dict[str, Served] = {}
    off: dict[str, Plate] = {}
    for name, (on, state_plate) in states.items():
        if not on:
            off[name] = state_plate
        elif name in definitions:
            definition, defined_plate = definitions[name]
            served[name] = Served(definition, digest(definition), defined_plate, state_plate)
        elif name not in switched:
            path = state_plate.directory / PROJECT_CLAUDE / MCP_FILE
            notes.append(ON_ALONE.format(path=quoted(str(path)), name=quoted(name)))
    return Fold(served, off, tuple(notes), usable)


MCP_LEDGER_FORMAT = 1
# A name the ledger owns whose call was started and whose outcome is not known to be good.
UNSETTLED = None
# An MCP ledger that is there and unreadable here, damaged or a newer drybag's, is the only record
# of the entries it names in `~/.claude.json`: it is never written over, and no MCP change is made.
BAD_LEDGER = (
    "{name} is not a ledger this drybag can read (damaged, or a newer drybag's), so no MCP server "
    "or deny entry changes: repair it, or remove it once you have taken back by hand every server "
    "it names"
)


@dataclass(frozen=True)
class McpLedger:
    """What `attach` recorded of the MCP servers, in `attach-mcp.json`.

    `deny` is the server names whose `deniedMcpServers` entry `attach` added, and the only entries
    a later run or `detach` may take out. `mcp` is the digest of each server `attach` delivered,
    `None` for one it could not; it is empty until a run delivers any. `fault` is `BAD_LEDGER`
    where the file is there and records nothing this drybag can read.
    """

    deny: tuple[str, ...] = ()
    mcp: dict[str, str | None] = field(default_factory=dict)
    fault: str | None = field(default=None, compare=False)


def read_mcp_ledger(root: Path) -> McpLedger:
    """The MCP ledger in `root`'s git common directory. A file that is absent is an empty ledger,
    and one that cannot be read, is not well shaped or is of another format is an empty ledger
    with its `fault`."""
    try:
        text = fsops.read_regular_text(common_directory(root) / MCP_LEDGER_FILE)
        raw = json_object(text, MCP_LEDGER_NAME, error=ValueError)
    except FileNotFoundError:
        return McpLedger()
    except (OSError, ValueError):
        raw = {}
    deny, mcp = raw.get("deny"), raw.get("mcp", {})
    if (
        raw.get("format") == MCP_LEDGER_FORMAT
        and isinstance(deny, list)
        and all(isinstance(name, str) for name in deny)
        and isinstance(mcp, dict)
        and all(isinstance(sha, str) or sha is UNSETTLED for sha in mcp.values())
    ):
        return McpLedger(tuple(deny), dict(mcp))
    return McpLedger(fault=BAD_LEDGER.format(name=MCP_LEDGER_NAME))


def write_mcp_ledger(root: Path, ledger: McpLedger) -> None:
    """Write `ledger` whole, through the same contained write as the other ledger."""
    document = {"format": MCP_LEDGER_FORMAT, "deny": list(ledger.deny), "mcp": ledger.mcp}
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    fsops.write_within(common_directory(root), MCP_LEDGER_FILE, text)


# Claude Code's answer to `remove` of a name local scope does not hold, measured on 2.1.319 as exit
# 1 and `No MCP server named "q" in local scope`. Exit 1 also answers a `remove` that could not
# write, so only exit 0 or this answer for the name drops it; any other (no `claude`, a spawn
# error, a signal, a timeout, another wording) leaves the name unsettled, never lost.
ABSENT = 'No MCP server named "{name}"'


@dataclass(frozen=True)
class McpPlan:
    """What a reconcile changes, by name: `add` the served names the ledger does not hold,
    `readd` those it holds under another digest or `UNSETTLED`, and `take_back` the names it holds
    that are not served. `attach --check` lists it; `reconcile` marks exactly these."""

    add: tuple[str, ...]
    readd: tuple[str, ...]
    take_back: tuple[str, ...]


def planned_mcp(served: Mapping[str, Served], owned: Mapping[str, str | None]) -> McpPlan:
    """The one marking rule, so `attach --check` and `attach` cannot disagree about a name."""
    held = {name: owned[name] for name in served if name in owned}
    return McpPlan(
        tuple(sorted(name for name in served if name not in held)),
        tuple(sorted(name for name, value in held.items() if value != served[name].digest)),
        tuple(sorted(name for name in owned if name not in served)),
    )


@dataclass(frozen=True)
class Reconciled:
    """`owned` is the ledger the reconcile leaves; `replaced` the served names whose `remove`
    found an entry though the ledger held no digest for them at the start, one made by hand or left
    by an interrupted run; `failed` each name a call did not settle, with what Claude Code said,
    through `printed.answered`."""

    owned: dict[str, str | None]
    replaced: tuple[str, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()


def _stopping(answer: Completed) -> Completed | None:
    """`answer` where it says `claude` is missing or hung, which every later call would say too."""
    return answer if answer.code in (NOT_FOUND, TIMED_OUT) else None


def reconcile(
    main: Path,
    served: Mapping[str, Served],
    owned: Mapping[str, str | None],
    runner: Runner,
    save: Callable[[dict[str, str | None]], None],
) -> Reconciled:
    """Mark, deliver, take back, then save what is left; every call runs from `main`, the main
    checkout, which is what makes `remove`'s answer that a name is absent mean absent there. Once
    a call finds `claude` missing or hung, nothing more is launched and every name left fails with
    that answer, unsettled."""
    plan = planned_mcp(served, owned)
    marked = (*plan.add, *plan.readd, *plan.take_back)
    left = dict(owned)
    if not marked:
        return Reconciled(left)
    left.update(dict.fromkeys(marked, UNSETTLED))
    save(dict(left))
    replaced: list[str] = []
    failed: list[tuple[str, str]] = []
    stopped: Completed | None = None
    for name in sorted((*plan.add, *plan.readd)):
        removed = stopped or runner.launch(filled(MCP_REMOVE_LOCAL, name), main)
        if removed.code == 0 and owned.get(name) is None:
            replaced.append(name)
        stopped = stopped or _stopping(removed)
        definition = json.dumps(served[name].definition)
        added = stopped or runner.launch(filled(MCP_ADD_JSON_LOCAL, name, definition), main)
        stopped = stopped or _stopping(added)
        if added.code == 0:
            left[name] = served[name].digest
        else:
            failed.append((name, answered(added)))
    for retired in plan.take_back:
        answer = stopped or runner.launch(filled(MCP_REMOVE_LOCAL, retired), main)
        stopped = stopped or _stopping(answer)
        absent = answer.code == 1 and ABSENT.format(name=retired) in answer.stderr
        if answer.code == 0 or absent:
            del left[retired]
        else:
            failed.append((retired, answered(answer)))
    save(dict(left))
    return Reconciled(left, tuple(replaced), tuple(failed))
