"""A strict reader for the YAML subset this repository's workflows are written in.

The repository carries no YAML parser, and the suite imports only what the runtime does plus its
declared development tools, so the workflow tests used to read a workflow by line pattern — one
pattern per question. Each of those readers could stop early or skip a line: an `env:` reader
that ended at the first comment left every key after it unread, and a step walk that knew two
spellings of a step folded a third into the step above it. So there is one reader, and it reads
the whole file into mappings, lists and strings, or fails.

**The subset, and the rule for everything outside it.** Block mappings of plain keys, block
sequences, plain scalars on one line, double- and single-quoted scalars on one line, flow
sequences of such scalars (`[main]`), literal block scalars (`|`, `|-`), and comments — a
comment line at any indentation, and one after a value past a space. Anything else is refused
with the line it is on: a flow mapping, an anchor, an alias, a tag, a folded scalar, a key that
is quoted or repeated in its mapping, a plain scalar that continues on the next line, a tab in
the indentation, a line indented where nothing can own it, a sequence at its key's own
indentation, an empty block scalar, a document that does not start at column 0. A refusal is a
red test in front of whoever wrote the shape, which is the safe direction; a reader that skipped
the shape would report clean over it.

**How YAML ends a block, and this reader with it.** A block ends at the first line of content
that is not indented past its key: a comment never ends one, whatever its indentation, and a
blank line never does. A literal block scalar's indentation is its first non-blank line's, and
it ends at the first non-blank line indented less, comment or not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

Node = dict[str, "Node"] | list["Node"] | str | None

_KEY = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?: +(?P<value>.*))?$")
_PLAIN_ITEM = re.compile(r"[^\s,\[\]{}#'\"][^,\[\]{}#]*")
# What may not begin a plain scalar here: YAML indicators this subset does not read.
_REFUSED_START = tuple("{&*!%@`>?")


class WorkflowYamlError(ValueError):
    """The text is outside the subset: it names the line and what was found there."""


@dataclass
class _Line:
    number: int
    indent: int
    text: str  # without the indentation

    @property
    def content(self) -> bool:
        return bool(self.text) and not self.text.startswith("#")


def _refuse(line: _Line, why: str) -> WorkflowYamlError:
    return WorkflowYamlError(f"line {line.number}: {why}: {line.text!r}")


def _strip_comment(value: str) -> str:
    """The value without a trailing ` # comment`. A quoted value's comment can only follow its
    closing quote; a plain value's begins at the first ` #`."""
    start = 0
    if value[:1] in ("'", '"'):
        close = value.find(value[0], 1)
        while value[0] == "'" and close != -1 and value[close + 1 : close + 2] == "'":
            close = value.find("'", close + 2)
        if close == -1:
            return value.rstrip()
        start = close + 1
    cut = value.find(" #", start)
    return (value if cut == -1 else value[:cut]).rstrip()


def _scalar(value: str, line: _Line) -> Node:
    if value.startswith('"'):
        try:
            text = json.loads(value)
        except ValueError:
            raise _refuse(line, "a double-quoted scalar this reader cannot read") from None
        if not isinstance(text, str):
            raise _refuse(line, "a double-quoted scalar this reader cannot read")
        return text
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'") or "'" in value[1:-1].replace("''", ""):
            raise _refuse(line, "a single-quoted scalar this reader cannot read")
        return value[1:-1].replace("''", "'")
    if value.startswith("["):
        if not value.endswith("]"):
            raise _refuse(line, "a flow sequence on more than one line")
        inner = value[1:-1].strip()
        items: list[Node] = []
        for part in [p.strip() for p in inner.split(",")] if inner else []:
            if part.startswith(("'", '"')):
                items.append(_scalar(part, line))
            elif _PLAIN_ITEM.fullmatch(part):
                items.append(part)
            else:
                raise _refuse(line, "a flow sequence item this reader cannot read")
        return items
    if value.startswith(_REFUSED_START) or value.startswith(("- ", "|", ">")):
        raise _refuse(line, "a value this reader does not read")
    if ": " in value or value.endswith(":"):
        raise _refuse(line, "a plain scalar that reads as a mapping")
    return value


class _Reader:
    def __init__(self, text: str) -> None:
        self.lines: list[_Line] = []
        for number, raw in enumerate(text.splitlines(), start=1):
            body = raw.lstrip(" ")
            if body.startswith("\t"):
                raise WorkflowYamlError(f"line {number}: a tab in the indentation")
            self.lines.append(_Line(number, len(raw) - len(body), body.rstrip()))
        self.index = 0

    def _next_content(self) -> _Line | None:
        """The next line of content, skipping blanks and comment lines at any indentation."""
        while self.index < len(self.lines) and not self.lines[self.index].content:
            self.index += 1
        return self.lines[self.index] if self.index < len(self.lines) else None

    def document(self) -> Node:
        first = self._next_content()
        if first is None:
            return None
        if first.indent != 0:
            raise _refuse(first, "the document does not start at column 0")
        node = self._block(0)
        rest = self._next_content()
        if rest is not None:
            raise _refuse(rest, "a line indented where nothing can own it")
        return node

    def _block(self, indent: int) -> Node:
        line = self._next_content()
        assert line is not None and line.indent == indent
        if line.text == "-" or line.text.startswith("- "):
            return self._sequence(indent)
        return self._mapping(indent, first_text=None)

    def _mapping(self, indent: int, first_text: str | None) -> dict[str, Node]:
        """A block mapping whose keys sit at `indent`. `first_text` is a key already read off a
        sequence item's dash line."""
        mapping: dict[str, Node] = {}
        pending = first_text
        while True:
            if pending is not None:
                line = self.lines[self.index]
                text, pending = pending, None
            else:
                line_or_none = self._next_content()
                if line_or_none is None or line_or_none.indent < indent:
                    return mapping
                line = line_or_none
                if line.indent > indent:
                    raise _refuse(line, "a line indented where nothing can own it")
                if line.text == "-" or line.text.startswith("- "):
                    return mapping
                text = line.text
            match = _KEY.match(text)
            if match is None:
                raise _refuse(line, "not a plain key")
            key = match.group("key")
            if key in mapping:
                raise _refuse(line, f"the key {key!r} twice in one mapping")
            value = _strip_comment(match.group("value") or "")
            self.index += 1
            if value in ("|", "|-"):
                mapping[key] = self._literal(indent, chomp=value == "|-")
            elif value:
                mapping[key] = _scalar(value, line)
                following = self._next_content()
                if following is not None and following.indent > indent:
                    raise _refuse(following, "a plain scalar that continues on the next line")
            else:
                child = self._next_content()
                if child is None or child.indent <= indent:
                    if child is not None and child.indent == indent and child.text.startswith("-"):
                        raise _refuse(child, "a sequence at its key's own indentation")
                    mapping[key] = None
                else:
                    mapping[key] = self._block(child.indent)

    def _sequence(self, indent: int) -> list[Node]:
        items: list[Node] = []
        while True:
            line = self._next_content()
            if line is None or line.indent < indent:
                return items
            if line.indent > indent:
                raise _refuse(line, "a line indented where nothing can own it")
            if not (line.text == "-" or line.text.startswith("- ")):
                return items
            rest = line.text[2:].lstrip(" ") if line.text != "-" else ""
            item_indent = indent + (len(line.text) - len(rest) if rest else 2)
            if not rest:
                self.index += 1
                child = self._next_content()
                if child is None or child.indent <= indent:
                    items.append(None)
                else:
                    items.append(self._block(child.indent))
            elif _KEY.match(rest):
                items.append(self._mapping(item_indent, first_text=rest))
            else:
                self.index += 1
                items.append(_scalar(_strip_comment(rest), line))
                following = self._next_content()
                if following is not None and following.indent > indent:
                    raise _refuse(following, "a plain scalar that continues on the next line")

    def _literal(self, indent: int, *, chomp: bool) -> str:
        """A literal block scalar under a key at `indent`: its lines, dedented."""
        start = self.index
        body_indent: int | None = None
        taken: list[str] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.text:
                if body_indent is None:
                    if line.indent <= indent:
                        break
                    body_indent = line.indent
                elif line.indent < body_indent:
                    break
                taken.append(" " * (line.indent - body_indent) + line.text)
            else:
                taken.append("")
            self.index += 1
        if body_indent is None:
            raise WorkflowYamlError(f"line {self.lines[start - 1].number}: an empty block scalar")
        while taken and not taken[-1]:
            taken.pop()
        return "\n".join(taken) + ("" if chomp else "\n")


def load(text: str) -> Node:
    """The document, or `WorkflowYamlError` naming the first line outside the subset."""
    return _Reader(text).document()


def runs(node: Node) -> list[Node]:
    """Every value of every `run` key in the document, at any depth, in document order: a step's
    script is a string, and `defaults: run:` is a mapping."""
    found: list[Node] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "run":
                found.append(value)
            found.extend(runs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(runs(item))
    return found
