"""The note sync's triggers: one handler on each of `SessionStart`, `Stop` and `SessionEnd`.

`Stop` fires on every turn of every session, so with the sync off, as every machine is until its
machine file says `[sync] enabled = true`, a handler reads that file and returns: no git, no
spawn. Only then does it import what decides (`sync.trigger`), which loads the note layout and
the job. Every import sits inside the handler body, so discovery stays light
(`tests/boundaries/test_discovery.py`). A handler returns an empty `HookResult` on every path and
lets nothing escape: what it prints carries no `decision`, which on `Stop` would keep the turn
from ending.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from stayfixed.hooks.api import Handler, HookEvent, HookResult

if TYPE_CHECKING:
    from stayfixed.config.session import SessionConfig


def _sync(event: HookEvent, session: SessionConfig) -> HookResult:
    with contextlib.suppress(Exception):
        from stayfixed.sync.switch import enabled

        if enabled():
            from stayfixed.sync.trigger import trigger

            trigger(event)
    return HookResult()


def register() -> list[Handler]:
    return [
        Handler(name="note-sync-start", event="SessionStart", run=_sync),
        Handler(name="note-sync-stop", event="Stop", run=_sync),
        Handler(name="note-sync-end", event="SessionEnd", run=_sync),
    ]
