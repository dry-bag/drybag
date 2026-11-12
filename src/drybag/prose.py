"""The one grammar for "a backticked path in hand-written prose".

The plan lint and the always-loaded document's link check ask the same question of different
documents: which backticked spans claim that a path exists. Two copies of that question drift
silently, so there is one, here. No list of extensions is closed: a `.rs`, a `.go` or a `.java`
file is claimed as a `.py` one is.

Four rules, each a decision rather than a default:

* a span is a path claim only when the whole span looks like a file: a name ending in an
  extension that starts with a letter (`lib.rs`, `a.d.ts`, `.env`, not `0.1.9`), optionally
  followed by a location in the file (`:12`, `:12:4`, `::symbol::path`);
* fences are BLANKED, not deleted, so every line below one keeps its number;
* a bare filename (`config.py`) is prose, a sentence about a file and not where it is;
* a claim that lands outside the project root is not settled against the filesystem at all
  (`resolves_within`).

A leaf module: `docs.plans` and `docs.hygiene` import it, and neither may import the other's area.
"""

from __future__ import annotations

import os.path
import re
from collections.abc import Iterator
from pathlib import Path

from drybag import fsops

# The path, ending in an extension that starts with a letter; then, outside the group, a line and
# column or a symbol path. An open extension reads `owner/lib.js` or `release/v1.x` as a path.
# The symbol path is one run, its colons judged after (`_BROKEN_SYMBOL`): a repeat of its parts
# keeps a record per part in `re`, and a possessive one misreads on Python 3.11.0 to 3.11.4
# (CONTRIBUTING.md, "Tests").
_REFERENCE = re.compile(
    r"`([A-Za-z0-9_./-]+\.[A-Za-z][A-Za-z0-9]*)"
    r"(?::\d+(?::\d+)?|(::[\w.:]+))?`"
)
# Where such a run is no symbol path: three colons in a row, a colon alone, or a colon at its end.
# Every other run is parts of word characters and dots, each after its own `::`.
_BROKEN_SYMBOL = re.compile(r":::|(?<!:):(?!:)|:\Z")
# A fenced block: a line opening with three or more backticks or tildes, closed by the first later
# line that is the same run alone between blanks. Read a line at a time, in linear time.
_FENCE_MARKS = "`~"
_FENCE_MIN = 3
# A first path component that is a host (`example.com/`), not a directory: a dot after another
# character and a label of two or more. `.github/` and `changelog.d/` stay paths; `app.config/`
# reads as a host and is under-reported, the safe direction for a dead-reference check.
HOST = re.compile(r"[^/]*[^./]\.[A-Za-z][A-Za-z0-9-]+/")


def blank_fences(text: str) -> str:
    """``text`` with each fenced block replaced by its own height in blank lines.

    An opening line's run is tried at its full length first and then one mark shorter, down to
    three: the first length some later line closes alone chooses the block, and the first such
    line ends it. Lines are read top to bottom, so for each run the lines that close it are
    passed over once each, and the whole text is read in time linear in its length.
    """
    lines = text.split("\n")
    closers: dict[tuple[str, int], list[int]] = {}
    for number, line in enumerate(lines):
        bare = line.strip(" \t")
        if len(bare) >= _FENCE_MIN and bare[0] in _FENCE_MARKS and bare == bare[0] * len(bare):
            closers.setdefault((bare[0], len(bare)), []).append(number)
    # For each run, how many of the lines that close it lie above the line being read.
    passed = dict.fromkeys(closers, 0)
    number = 0
    while number < len(lines):
        body = lines[number].lstrip(" \t")
        mark = body[:1]
        run = len(body) - len(body.lstrip(mark)) if mark and mark in _FENCE_MARKS else 0
        end = None
        for length in range(run, _FENCE_MIN - 1, -1):
            later = closers.get((mark, length))
            if later is None:
                continue
            index = passed[mark, length]
            while index < len(later) and later[index] <= number:
                index += 1
            passed[mark, length] = index
            if index < len(later):
                end = later[index]
                break
        if end is None:
            number += 1
            continue
        lines[number : end + 1] = [""] * (end + 1 - number)
        number = end + 1
    return "\n".join(lines)


def path_references(line: str) -> Iterator[str]:
    """Every backticked span in ``line`` that claims a path; bare filenames, and a span whose
    first component is a host (`HOST`), are prose."""

    at = 0
    while (match := _REFERENCE.search(line, at)) is not None:
        if match.group(2) is not None and _BROKEN_SYMBOL.search(match.group(2)):
            # No claim opens at this backtick, and the next may open at the very next one.
            at = match.start() + 1
            continue
        at = match.end()
        target = match.group(1)
        if "/" in target and not HOST.match(target):
            yield target


def resolves_within(root: Path, target: str, *, base: Path | None = None) -> Path | None:
    """Where a path claim lands, or None when it lands outside ``root``.

    A document writes whatever it likes, `/etc/passwd.md` and `../../secrets/keys.py` included,
    and a reader that asked the filesystem about those would answer about the developer's disk:
    a path that exists only locally passes, and the reader is an existence oracle outside the root.

    Lexical, with `normpath` and never `resolve()`, so no probe is made before the decision.
    ``base`` is where a RELATIVE claim is read from (a markdown link's own directory), defaulting
    to ``root``; containment is judged against ``root`` either way.
    """
    landed = Path(os.path.normpath(os.path.join(str(base if base is not None else root), target)))
    return landed if landed.is_relative_to(os.path.normpath(str(root))) else None


def present_within(root: Path, landed: Path) -> bool | None:
    """Whether the path at `landed` names something inside `root`: `True` or `False`, or `None`
    when its real path leaves `root`, so the claim is not settled at all.

    `resolves_within` is lexical, and `exists()` follows symlinks, so a committed `docs/l -> /`
    would make every claim under it a question about the machine. The answer is taken from the
    claim's real path, only inside the root's; a symlink inside the tree is followed. A name too
    long for the filesystem names nothing (`fsops.exists`), and one under a directory that cannot
    be searched is `False` rather than an exception.
    """
    try:
        real = Path(os.path.realpath(landed))
        if not real.is_relative_to(os.path.realpath(root)):
            return None
        return fsops.exists(real)
    except OSError:
        return False
