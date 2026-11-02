"""The advisory memory link graph: every `[[link]]` resolves to a document in the store, no link is
immediately repeated, no ledger identifier is bracketed. Advice, never a verdict: the store is
shared by every session on the machine, so `memory refs` reports these as notices that never
change its exit code.

The wiki-link grammar is defined here, as the link graph's own, and `memory.refs` reads it through
`wiki_links` for its audience check; the identifier grammar is the bug ledger's, read through
`stayfixed.ledger.api`, and what counts as prose is `stayfixed.prose`'s. The notes come from the
walk `memory.refs` already made for its own findings, so `memory refs` reads the store once.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING

from stayfixed.findings import Finding
from stayfixed.ledger.api import bug_register
from stayfixed.memory.store import walked_groups
from stayfixed.prose import blank_code_spans, blank_fences

if TYPE_CHECKING:
    from stayfixed.config.schema import Config
    from stayfixed.memory.notes import Walk
    from stayfixed.memory.store import Store

# `[[name]]` addresses a note by its stem: the one spelling, which `memory.refs` reads through
# `wiki_links` rather than respelling it. A link is what the pattern `\[\[([^\]]+)\]\]` finds, and
# where it finds none from an opening `[[`, it finds none from any `[[` before the next `]`, which
# reaches the same `]`: so the second alternative takes that stretch whole, and the text is read
# once. Found from every `[[`, a note of 16,000 `[` took half a second, four times as long at each
# doubling.
_LINK = re.compile(r"\[\[(?:([^\]]++)\]\]|[^\]]*+)")
# What may stand between two links that repeat one note: the list forms a bulk repoint collapses
# into, `, `, `, and `, ` or `. Possessive, so `re` keeps no record per separator: greedy, a
# mebibyte of blanks between two links took 154 MiB more to read.
_SEPARATORS = re.compile(r"(?:[,\s]|\band\b|\bor\b)*+")


def wiki_links(text: str) -> Iterator[re.Match[str]]:
    """Every `[[name]]` in `text`, in order; a match's first group is the name."""
    return (link for link in _LINK.finditer(text) if link.group(1) is not None)


def repeated_links(text: str) -> Iterator[str]:
    """The name of each link in `text` that the next link repeats with only separators between.

    Pairs of neighbours, not a pair matched and consumed: in `[[a]] [[b]] [[b]]` the a-b pair must
    not take the left half of the real b-b pair."""
    before = None
    for link in wiki_links(text):
        if (
            before is not None
            and before.group(1) == link.group(1)
            and _SEPARATORS.fullmatch(text, before.end(), link.start())
        ):
            yield link.group(1)
        before = link


def check_memory_graph(store: Store, config: Config, walked: Walk) -> list[Finding]:
    """The graph's notices over `walked`, the walk of `store`'s configured groups."""
    groups = walked_groups(store, config)
    linkable = {p.stem for p in store.path.glob("*.md")}
    for group in groups:
        linkable |= {p.stem for p in (store.path / group).glob("*.md")}
    ids = bug_register(config).ids
    found: list[Finding] = []
    for note in walked.notes:
        where = note.path.relative_to(store.path).as_posix()
        # Fences first (they can contain backticks), then spans; the span placeholder keeps
        # `[[a]] `x` [[a]]` from reading as a repeat.
        text = blank_code_spans(blank_fences(note.body))
        for link in wiki_links(text):
            target = link.group(1)
            if ids.is_identifier(target):
                found.append(Finding("bracketed-identifier", where, None, target))
            elif target not in linkable:
                found.append(Finding("dead-wiki-link", where, None, target))
        for repeat in repeated_links(text):
            found.append(Finding("repeated-link", where, None, repeat))
    return found
