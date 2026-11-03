"""What a consumer asks for, and what the engine answers.

`Template` is a description, not a file: the areas that own template *content*
(`templates/`, `overlay/`) build these, and this area never reads the plugin's own directory.
That is what keeps the engine testable without shipping any template at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stayfixed.scaffold.manifest import Kind, Record
from stayfixed.scaffold.regions import Style


class Verb(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    SKIP_MODIFIED = "skip_modified"
    REMOVE = "remove"
    REGION_UPDATE = "region_update"
    ENTRIES_UPDATE = "entries_update"


WRITING = frozenset({Verb.CREATE, Verb.UPDATE, Verb.REGION_UPDATE, Verb.ENTRIES_UPDATE})


@dataclass(frozen=True)
class Template:
    id: str
    kind: Kind
    target: str
    source: str
    render: Callable[[], str]
    region: str | None = None
    style: Style = Style.MARKDOWN
    entries: dict[str, list[dict[str, Any]]] | None = None


@dataclass(frozen=True)
class Action:
    verb: Verb
    artifact_id: str
    target: str
    payload: str | None
    reason: str
    record: Record | None


@dataclass(frozen=True)
class Refused:
    artifact_id: str
    target: str
    reason: str


@dataclass(frozen=True)
class Plan:
    """What `plan` decided, and what `apply` then writes — the same object, unchanged between.

    `frozen=True` with three `list` fields froze the *bindings* and nothing else, so the plan a
    user approved through `render_report` could still be appended to, or have an action's target
    rewritten, before `apply` consumed it. That weakens the one claim this split exists to make:
    "the report a user approves is produced by the same code path that then runs". The fields
    are tuples, so the object really is what it was when it was rendered.

    `plan` builds its three lists as lists and hands them here; the conversion happens once, at
    the boundary, which is where the guarantee begins.
    """

    actions: tuple[Action, ...] = ()
    refusals: tuple[Refused, ...] = ()
    unchanged: tuple[str, ...] = ()

    @property
    def writes(self) -> list[str]:
        return [
            action.target
            for action in self.actions
            if action.verb in WRITING or action.verb is Verb.REMOVE
        ]


@dataclass(frozen=True)
class Applied:
    """What `apply` actually did. Tuples for the same reason `Plan` uses them: it is a report."""

    written: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
