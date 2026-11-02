"""The sync's hook handlers: none yet, the ones for its three events arrive with the job.

The module is here so that discovery finds the area, which is what puts it on the delivery side
(`stayfixed.areas`) now that its rules read the note layout from `memory`.
"""

from __future__ import annotations

from stayfixed.hooks.api import Handler


def register() -> list[Handler]:
    return []
