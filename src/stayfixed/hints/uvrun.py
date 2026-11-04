"""Where `uv run` stops and the command it launches starts, for `bashscan.read_launch`.

uv is one stack's launcher, and this module is where the shared scanner keeps it, so the scanner
itself names no stack (`tests/test_language_neutral.py` pardons this file for that reason). None
of uv's option grammar is read: the command starts at the first word after `run` that the caller
recognises (`bashscan.read_launch`), and every word before it is the launcher's, handed to uv as
typed. It never runs uv.
"""

from __future__ import annotations

from collections.abc import Sequence

_UV = "uv"
_UV_RUN = "run"


def is_launcher(name: str) -> bool:
    """Whether a command's program, by its bare name, is uv."""
    return name == _UV


def past_run(segment: Sequence[str], index: int) -> int | None:
    """Where the words after `run` start in `segment`, read from `index`, just past the word `uv`
    (`is_launcher`); `None` where no `run` follows, a uv command that launches nothing."""
    if _UV_RUN not in segment[index:]:
        return None
    return segment.index(_UV_RUN, index) + 1
