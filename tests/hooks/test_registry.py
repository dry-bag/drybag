"""Discovery owns the event vocabulary, so a mistype is not a silent no-op."""

from __future__ import annotations

import pytest

from drybag.hooks.api import EVENTS, Handler, HookEvent, HookResult
from drybag.hooks.registry import UnknownHookEvent, discover


class Area:
    """Stands in for `drybag.<area>.hooks`, which no shipped area provides yet."""

    def __init__(self, name: str, handlers: list[Handler]) -> None:
        self.__name__ = name
        self._handlers = handlers

    def register(self) -> list[Handler]:
        return self._handlers


def guard(event: str) -> Handler:
    def run(ev: HookEvent, config: object) -> HookResult:
        return HookResult()

    return Handler(name="background-cleanup", event=event, run=run)


def area_of(monkeypatch: pytest.MonkeyPatch, *handlers: Handler) -> None:
    area = Area("drybag.example.hooks", list(handlers))
    monkeypatch.setattr("drybag.hooks.registry.area_modules", lambda submodule: [area])


def test_a_mistyped_event_name_is_refused_and_named(monkeypatch: pytest.MonkeyPatch) -> None:
    area_of(monkeypatch, guard("PreToolUSe"))
    with pytest.raises(UnknownHookEvent) as raised:
        discover()
    message = str(raised.value)
    assert "drybag.example.hooks" in message
    assert "'background-cleanup'" in message
    assert "'PreToolUSe'" in message


def test_a_handler_on_a_known_event_registers_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = guard("PreToolUse")
    area_of(monkeypatch, handler)
    assert discover() == [handler]


def test_the_vocabulary_is_the_eight_events_the_design_table_carries() -> None:
    # An area that needs a ninth adds it to EVENTS deliberately; widening it by accident is
    # what turns a mistyped handler back into a guard that never fires. The sixth,
    # `PostToolUseFailure`, is where Claude Code delivers a command that exited non-zero; `Stop`
    # and `SessionEnd` are where the note sync starts its job.
    # Mutation: `mutations/`'s "the dispatcher stops carrying the event a failed command arrives
    # on".
    assert EVENTS == (
        "SessionStart",
        "UserPromptSubmit",
        "UserPromptExpansion",
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "Stop",
        "SessionEnd",
    )


def test_a_session_start_runs_no_step_that_links_memory() -> None:
    # The harness reaches the composed store through `autoMemoryDirectory` in the main checkout's
    # settings file, which every worktree reads, so no `SessionStart` step links a store into a
    # worktree: the shipped handlers there are the owner-held files a new linked worktree lacks
    # (`owner-files`, first), the overlay's status line and its standing rules, the index render,
    # which writes the overlay's index and notes, the count of the store's unreviewed notes, which
    # writes nothing in any checkout, and the note sync's trigger, which writes only in the data
    # directory.
    names = [handler.name for handler in discover() if handler.event == "SessionStart"]
    assert names == [
        "owner-files",
        "overlay-status",
        "overlay-rules",
        "index-render",
        "unreviewed-notes",
        "note-sync-start",
    ]
