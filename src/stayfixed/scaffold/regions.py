"""Marker-delimited regions inside files a person owns.

The rule that makes these safe is narrow: the tool reads and rewrites what is between its two
markers and returns every other byte unchanged. So a project keeps its own `.gitignore` while
`init` writes one section of it, and `attach` one section of the repository's `info/exclude`.

"Every other byte" is meant literally, which is why this module splits with `keepends=True`
and never re-joins with `"\\n"`: a file with CRLF endings, or a form feed in a paragraph, must
come back out as it went in. `str.splitlines()` alone splits on eleven characters and
normalises all of them.

**Where a line ends depends on who reads the file.** A hash-style region lives in a file git reads
(`.gitignore`, `info/exclude`), and git ends a line at `\n` alone: read as also ending at a lone
`\r`, a last line `/zz\r` counted as ended, the block's begin marker was glued onto it, and git
lost the `/zz` pattern. A Markdown region keeps the lone `\r` as a line end, as a Markdown reader
does.
"""

from __future__ import annotations

import re
from enum import StrEnum

from stayfixed.errors import Refusal

_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)?")
# git's own split, for `Style.HASH`: a line ends at `\n` alone, and a `\r` before it is the line's.
_GIT_LINE = re.compile(r"[^\n]*\n?")


class RegionError(Refusal):
    """A region the engine cannot rewrite without guessing where it ends."""


class Style(StrEnum):
    MARKDOWN = "markdown"
    HASH = "hash"


def markers(name: str, style: Style) -> tuple[str, str]:
    if style is Style.MARKDOWN:
        return (f"<!-- stayfixed:{name}:begin -->", f"<!-- stayfixed:{name}:end -->")
    return (f"# stayfixed:{name}:begin", f"# stayfixed:{name}:end")


def _lines(text: str, style: Style) -> list[str]:
    """Every line with its own ending preserved; `"".join(_lines(t, s)) == t` for any `t`."""
    pattern = _GIT_LINE if style is Style.HASH else _LINE
    return [m.group(0) for m in pattern.finditer(text) if m.group(0)]


def _ended(line: str, style: Style) -> bool:
    return line.endswith("\n") if style is Style.HASH else line.endswith(("\n", "\r"))


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _bounds(lines: list[str], name: str, style: Style, label: str) -> tuple[int, int] | None:
    begin, end = markers(name, style)
    starts = [i for i, line in enumerate(lines) if line.strip() == begin]
    ends = [i for i, line in enumerate(lines) if line.strip() == end]
    if not starts:
        if ends:
            # Not "the region is absent": a begin marker somebody deleted, or a merge that kept
            # one side's end line. Reading it as absent makes `upsert` append a second end
            # marker, and every run after that refuses a file the tool broke itself.
            raise RegionError(
                f"region {label!r} has an end marker with no beginning; resolve it by hand"
            )
        return None
    if len(starts) > 1 or len(ends) > 1:
        raise RegionError(f"region {label!r} is opened or closed twice; resolve it by hand")
    if not ends:
        raise RegionError(f"region {label!r} has no end marker; resolve it by hand")
    if ends[0] < starts[0]:
        raise RegionError(f"region {label!r} ends before it begins; resolve it by hand")
    return starts[0], ends[0]


def extract(text: str, name: str, style: Style) -> str | None:
    """The region's body with its trailing newline removed, or `None` when it is absent.

    Trailing-newline-insensitive on purpose: the caller compares this against the body a
    template rendered, and a template that ends with a newline would otherwise be reported
    hand-edited on every run.
    """
    lines = _lines(text, style)
    found = _bounds(lines, name, style, name)
    if found is None:
        return None
    start, end = found
    body = "".join(lines[start + 1 : end])
    return body.rstrip("\r\n")


def upsert(text: str, name: str, body: str, style: Style) -> str:
    begin, end = markers(name, style)
    newline = _newline(text)
    block = [begin + newline]
    block += [line if _ended(line, style) else line + newline for line in _lines(body, style)]
    block.append(end + newline)
    lines = _lines(text, style)
    found = _bounds(lines, name, style, name)
    if found is None:
        head = list(lines)
        if head and not _ended(head[-1], style):
            # git drops one `\r` before the `\n` that ends a line, so a last line ending in a
            # lone `\r` is ended by `\n` alone: the file's own `\r\n` there would leave git
            # reading the pattern with a `\r` on it, a pattern for another name.
            lone_cr = style is Style.HASH and head[-1].endswith("\r")
            head[-1] = head[-1] + ("\n" if lone_cr else newline)
        return "".join(head + block)
    start, stop = found
    return "".join(lines[:start] + block + lines[stop + 1 :])


def drop(text: str, name: str, style: Style) -> str:
    lines = _lines(text, style)
    found = _bounds(lines, name, style, name)
    if found is None:
        return text
    start, stop = found
    return "".join(lines[:start] + lines[stop + 1 :])
