"""The one key stayfixed rewrites inside a document somebody else owns.

`[stayfixed] version` is stayfixed's to rewrite (`docs/cli.md#configuration`). Every other key of
`stayfixed.toml` is the user's, and so is the file around them: its comments, its order, its blank
lines. `tomllib` reads and nothing in the standard library writes, and `tomlout.dumps` renders a
whole document with the comments gone, so this module edits lines.

**The read-back is the contract; the line editor is one implementation of it.** Each key is
edited and proved on its own: the text after the edit must parse to exactly the document before
it with that one key set to its value. The editor does not understand every shape: a dotted
key, a quoted key, an inline table, a value that is not a one-line string, a header-looking line
inside a multi-line string. None of those ever yields a wrong
file; each yields an `OwnedKeyError` naming the key that failed and the line to write by hand.
stayfixed's own renderer never produces those shapes. A person may, and the refusal is the honest
answer to them. The proof covers values and not comments, because a comment is not part of the
parsed document: the editor keeps a line's trailing comment by pattern, and nothing proves it.

**What a message prints, and why that is safe.** The table and key come from `OWNED`. The value is
one stayfixed chose, rendered through `tomlout.quoted`: a version. A document that does not parse is
answered with the parser's position alone, as the loader answers it.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from typing import Any

from stayfixed.config.loader import CONFIG_FILE
from stayfixed.config.reading import UNPARSEABLE, toml_position
from stayfixed.errors import Refusal
from stayfixed.tomlout import quoted

Value = str
OWNED: frozenset[tuple[str, str]] = frozenset({("stayfixed", "version")})
UNEDITABLE = (
    "[{table}] {key} is written in a shape stayfixed does not rewrite in place, so nothing was "
    "written; set it by hand to `{key} = {literal}` and run the command again"
)
UNPARSED = "{file} is not valid TOML {position}, so nothing was written"
# A plain `[name]` header with nothing but a comment after it. `[[array]]` and `[a.b]` are
# headers too: they end the current table without starting one this module edits.
_HEADER = re.compile(r"^[ \t]*\[[ \t]*([A-Za-z0-9_-]+)[ \t]*\][ \t]*(?:#.*)?$")
_ANY_HEADER = re.compile(r"^[ \t]*\[")
_ASSIGNMENT = (
    r"^(?P<lead>[ \t]*){key}(?P<eq>[ \t]*=[ \t]*)"
    r"(?P<value>\"(?:[^\"\\]|\\.)*\"|'[^'\n]*')(?P<tail>[ \t]*(?:#.*)?)$"
)


class OwnedKeyError(Refusal):
    """A tool-owned key that could not be rewritten without touching anything else."""


class UnparsedDocument(OwnedKeyError):
    """The document does not parse at all, so no key's shape is the problem: a caller that
    words its own remedy for a key it could not rewrite passes this one on unchanged."""


def _lines(text: str) -> list[str]:
    """`text` cut after each `\\n`, which is TOML's only newline.

    Not `str.splitlines`: it also cuts at U+2028, U+0085, a form feed and five more characters,
    each of which is an ordinary character inside a TOML string or comment.
    """
    *whole, last = text.split("\n")
    return [line + "\n" for line in whole] + ([last] if last else [])


def _set(lines: list[str], table: str, key: str, value: Value, newline: str) -> list[str]:
    assignment = re.compile(_ASSIGNMENT.format(key=re.escape(key)))
    current: str | None = None
    header: int | None = None
    hits: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        found = _HEADER.match(body)
        if found:
            current = found.group(1)
            if current == table:
                header = index
            continue
        if _ANY_HEADER.match(body):
            current = None
            continue
        if current == table:
            match = assignment.match(body)
            if match:
                hits.append((index, match))
    out = list(lines)
    if len(hits) == 1:
        index, match = hits[0]
        ending = lines[index][len(lines[index].rstrip("\r\n")) :]
        out[index] = f"{match['lead']}{key}{match['eq']}{quoted(value)}{match['tail']}{ending}"
    elif not hits and header is not None:
        if not out[header].endswith("\n"):
            out[header] += newline
        out.insert(header + 1, f"{key} = {quoted(value)}{newline}")
    elif not hits:
        if out and not out[-1].endswith("\n"):
            out[-1] += newline
        out += [newline, f"[{table}]{newline}", f"{key} = {quoted(value)}{newline}"]
    # Two hits means one of them sits inside a string, because `tomllib` refuses a duplicate
    # key. Nothing is edited, and the read-back refuses the unchanged text.
    return out


def rewrite(text: str, changes: Mapping[tuple[str, str], Value]) -> str:
    """`text` with each `(table, key)` set to its value, or an `OwnedKeyError`.

    A change naming a key outside `OWNED` is a caller's bug and raises `ValueError`. A change to
    the value already there returns `text` unchanged, byte for byte, which is what lets a caller
    compare the result with the input to learn whether anything needs writing.
    """
    stray = set(changes) - OWNED
    if stray:
        raise ValueError(f"{sorted(stray)} is not a tool-owned key")
    try:
        expected: dict[str, Any] = tomllib.loads(text)
    except UNPARSEABLE as exc:
        raise UnparsedDocument(
            UNPARSED.format(file=CONFIG_FILE, position=toml_position(exc))
        ) from None
    newline = "\r\n" if "\r\n" in text else "\n"
    result = text
    for (table, key), value in sorted(changes.items()):
        current = expected.get(table)
        if isinstance(current, dict) and current.get(key) == value:
            continue
        refusal = OwnedKeyError(UNEDITABLE.format(table=table, key=key, literal=quoted(value)))
        if current is not None and not isinstance(current, dict):
            raise refusal
        candidate = "".join(_set(_lines(result), table, key, value, newline))
        expected.setdefault(table, {})[key] = value
        try:
            proved = tomllib.loads(candidate) == expected
        except UNPARSEABLE:
            proved = False
        if not proved:
            raise refusal
        result = candidate
    return result
