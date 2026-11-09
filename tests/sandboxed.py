"""Writes refused as Claude Code's sandbox refuses an agent's shell a write outside the working
directory, for the tests of the writers that must say so rather than end in a traceback.

macOS's sandbox answers such a write with `PermissionError` `EPERM` (`trust.boundary`'s docstring
says how that was measured), so the stand-ins raise exactly that, through the `fsops` writers every
write goes through, and only for a target at or under the path a test names: every other write of
the run goes on as it would.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from drybag import fsops


def _refused(path: Path) -> PermissionError:
    return PermissionError(errno.EPERM, os.strerror(errno.EPERM), str(path))


def refuse_writes_under(monkeypatch: pytest.MonkeyPatch, place: Path) -> list[Path]:
    """Make `fsops.write_atomically` and `fsops.write_within` refuse, with `EPERM`, every target
    that is `place` or lies under it; returns the targets refused, in order, for a test to assert
    the refusal was met."""
    refused: list[Path] = []
    real_atomically = fsops.write_atomically
    real_within = fsops.write_within

    def under(path: Path) -> bool:
        return path == place or place in path.parents

    def atomically(path: Path, text: str, **kwargs: Any) -> None:
        if under(path):
            refused.append(path)
            raise _refused(path)
        real_atomically(path, text, **kwargs)

    def within(root: Path, target: str, text: str, **kwargs: Any) -> None:
        if under(root / target):
            refused.append(root / target)
            raise _refused(root / target)
        real_within(root, target, text, **kwargs)

    monkeypatch.setattr(fsops, "write_atomically", atomically)
    monkeypatch.setattr(fsops, "write_within", within)
    return refused
