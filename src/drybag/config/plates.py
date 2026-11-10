"""The overlay's plates for a bound project, in the one order every reader takes them.

A plate is a directory of the owner's overlay that holds layers of one kind: `common/`, then one
`tags/<tag>/` for each tag the project lists, then `projects/<name>/`. A later plate wins a value
or an item name and content otherwise unions, so the order is the precedence: `common`, the
project's tags in list order, the project, and (for a value) the machine file after all of them.

**A plate's `machines/<name>/` is a sub-plate** on the machine whose name is `[machine] name` in
the machine file (`config.overlay.machine_name`; this module reads no file, its caller says which
machine it is). It comes right after its parent and before the next plate, so on that machine it
wins over its parent and loses to every later plate. A machine with no name, and every other
machine's directory, has no sub-plate; a `machines/<x>` directory
whose name is outside `TAG` is a note and no plate.

**The tags are read from the overlay's record of the project, never from the repository.** The
record is `projects/<name>/project.toml`, its `tags` key a list of names, and the project is the
one this machine's binding record names (`binding.bound_project`), so a clone that commits a
`drybag.toml` or a note naming a tag chooses none: the owner's overlay and the owner's machine
are the anchors, and the repository can write neither. A tag is `TAG`, a name that is also a
directory name, a link name and a TOML string; one outside it, one with no `tags/<tag>/`
directory and a record that cannot be read are each a note and no plate, never a refusal, because
a session never dies of its configuration. A tag listed twice is one plate, at its first place; a
`tags/<tag>` that is a link to a directory is a directory, the overlay being the owner's.

The record has one reader, `read_record`, which raises what it meets and has no policy of its own:
`tags` says what an unreadable record means here (a note), and `memory.store.read_binding_record`
and `attach` say what it means to them.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from drybag import fsops
from drybag.config.reading import UNPARSEABLE, read_fault
from drybag.printed import clipped, quoted

COMMON = "common"
TAGS = "tags"
MACHINES = "machines"
PROJECTS = "projects"
RECORD = "project.toml"
# The name a tag's notes take as a link in the composed store, `tag-<tag>`: the project side of the
# store gives up this prefix (`memory.store.reserved`), and `attach` creates no group directory
# that starts with it. Named here, in the core, because both delivery areas spell it.
TAG_LINK_PREFIX = "tag-"
# A named cap: a tag is at most forty characters, from a lowercase letter or digit, then those and
# hyphens. The name becomes a directory name, a link name, an index heading and a TOML string, and
# forty is past every tag a person types. No shipped file states it.
TAG_SHAPE = r"[a-z0-9][a-z0-9-]{0,39}"
TAG = re.compile(rf"\A{TAG_SHAPE}\Z")

UNLISTED = "so the project lists no tags"
NOT_A_LIST = "{path}: tags must be a list, so the project lists no tags"
NOT_A_STRING = "{path}: the tags entry {position} is not a string; it is skipped"
NOT_A_TAG = (
    "{path}: the tag {tag} is not 1 to 40 lowercase letters, digits and hyphens, "
    "starting with a letter or digit; it is skipped"
)
BAD_MACHINE_DIRECTORY = (
    "{path}: the directory {name} is not 1 to 40 lowercase letters, digits and hyphens, "
    "starting with a letter or digit, so it is no machine's sub-plate"
)
NO_TAG_DIRECTORY = "{path}: the tag {tag} has no directory {directory}; it is skipped"


class PlateKind(StrEnum):
    """Which kind of directory a plate is."""

    COMMON = "common"
    TAG = "tag"
    PROJECT = "project"


@dataclass(frozen=True)
class Plate:
    """One directory of the overlay: `name` is `common`, the tag, or the project's name. A
    sub-plate (`machines/<machine>/` of a plate) keeps its parent's `kind` and `name` and sets
    `machine`."""

    kind: PlateKind
    name: str
    directory: Path
    machine: str | None = None


def read_record(path: Path) -> dict[str, Any]:
    """The project record at `path` as `tomllib` parses it.

    The one reader of `projects/<name>/project.toml`, with no failure policy: an `OSError`, a
    `UnicodeDecodeError` and each of `UNPARSEABLE` are raised as met, because what a record that
    cannot be read means is each caller's to say. Read through `fsops.read_regular_text`, so a
    record swapped for a FIFO or a device is refused unread and one past the cap is refused too.
    """
    return tomllib.loads(fsops.read_regular_text(path))


def _listed(overlay: Path, project: str) -> tuple[list[Any], str | None]:
    """The entries of the `tags` list `project`'s record holds, and the note for a record that is
    present and unusable (`record_fault`): it cannot be read, or `tags` is not a list. No record, or
    a record with no `tags` key, lists none and is no fault. An entry that is not a string is
    `tags`' to note, not a fault."""
    record = overlay / PROJECTS / project / RECORD
    shown = quoted(str(record))
    try:
        listed = read_record(record).get("tags")
    except FileNotFoundError:
        return [], None
    except (UnicodeDecodeError, OSError, *UNPARSEABLE) as exc:
        return [], read_fault(shown, exc, UNLISTED)
    if listed is None:
        return [], None
    if not isinstance(listed, list):
        return [], NOT_A_LIST.format(path=shown)
    return listed, None


def record_fault(overlay: Path, project: str) -> str | None:
    """Why `project`'s record cannot say which tags it lists, where it cannot. Readers of a
    session take that as no tags and say it; `attach` refuses it, since a run that took it so
    would withdraw what the tags delivered."""
    return _listed(overlay, project)[1]


def tags(overlay: Path, project: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The usable tags of `project` in list order, each once, and the notes: `record_fault`, a tag
    outside `TAG`, an entry that is not a string and a tag with no `tags/<tag>/` directory, each
    noted once however often it is listed."""
    listed, fault = _listed(overlay, project)
    if fault is not None:
        return (), (fault,)
    shown = quoted(str(overlay / PROJECTS / project / RECORD))
    usable: list[str] = []
    notes: list[str] = []
    seen: set[str] = set()
    for position, tag in enumerate(listed, 1):
        if not isinstance(tag, str):
            notes.append(NOT_A_STRING.format(path=shown, position=position))
            continue
        if tag in seen:
            continue
        seen.add(tag)
        if TAG.match(tag) is None:
            notes.append(NOT_A_TAG.format(path=shown, tag=clipped(tag)))
        elif not _directory(overlay / TAGS / tag):
            notes.append(
                NO_TAG_DIRECTORY.format(path=shown, tag=tag, directory=quoted(f"{TAGS}/{tag}"))
            )
        else:
            usable.append(tag)
    return tuple(usable), tuple(notes)


def plates(
    overlay: Path, project: str, *, machine: str | None
) -> tuple[tuple[Plate, ...], tuple[str, ...]]:
    """`common`, each usable tag of `project`, then the project, each followed by its sub-plate on
    this machine (`machines/<machine>/`, `machine` being this machine's name or `None`) where that
    directory exists, and the notes `tags` and the sub-plates gave. It reads no machine file: every
    caller says which machine it is. The project's plate is present whether or not its directory
    exists: readers already handle an absent share."""
    used, notes = tags(overlay, project)
    name = machine
    found = [*notes]
    parents = _parents(overlay, project, used)
    ordered: list[Plate] = []
    for parent in parents:
        ordered.append(parent)
        found.extend(_bad_machine_directories(parent.directory / MACHINES))
        if name is not None and _directory(parent.directory / MACHINES / name):
            ordered.append(
                Plate(parent.kind, parent.name, parent.directory / MACHINES / name, machine=name)
            )
    return tuple(ordered), tuple(found)


def _parents(overlay: Path, project: str, used: tuple[str, ...]) -> tuple[Plate, ...]:
    """The plates that have no machine: `common`, the usable tags `used`, the project."""
    return (
        Plate(PlateKind.COMMON, COMMON, overlay / COMMON),
        *(Plate(PlateKind.TAG, tag, overlay / TAGS / tag) for tag in used),
        Plate(PlateKind.PROJECT, project, overlay / PROJECTS / project),
    )


def bad_machine_directories(overlay: Path, project: str) -> tuple[str, ...]:
    """The notes `plates` gives for the `machines/` directories of `project`'s plates whose names
    are outside `TAG`, and no other: what `doctor`'s `machine` row says of them."""
    parents = _parents(overlay, project, tags(overlay, project)[0])
    return tuple(
        note for parent in parents for note in _bad_machine_directories(parent.directory / MACHINES)
    )


def _bad_machine_directories(machines: Path) -> list[str]:
    """One note for each directory of `machines` whose name is outside `TAG`; a `machines` that is
    absent or cannot be listed has none."""
    try:
        if not fsops.is_dir(machines):
            return []
        listed = sorted(os.listdir(machines))
    except OSError:
        return []
    return [
        BAD_MACHINE_DIRECTORY.format(path=quoted(str(machines / entry)), name=clipped(entry))
        for entry in listed
        if not entry.startswith(".")
        and TAG.fullmatch(entry) is None
        and _directory(machines / entry)
    ]


def _directory(path: Path) -> bool:
    """`path` reaches a directory; one that cannot be asked about is not one."""
    try:
        return fsops.is_dir(path)
    except OSError:
        return False
