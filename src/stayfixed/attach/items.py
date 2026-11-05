"""The overlay's named items, and the one fold over the plates that settles a name two plates hold.

An item is what a plate holds under a name (`config.plates`): a rule, a `*.md` regular file in
`claude/rules/`; a Codex rule file, a regular file in `codex/`; a skill or an agent, an entry
directly in `claude/skills/` or `claude/agents/`, a directory or a file. Dot-names are the
editor's and the system's, and none is an item. `fold` takes the plates in their order and **the
later plate wins the whole item, which takes the winning plate's place**: a common-only item comes
before one a tag replaced. Every reader of an item takes its winners from here (`attach.rules`,
`permissions.codex_rules`, `render.read_parts`), and `attach.tags` names a name two tags hold from
its holders, so the order is spelled once. Hook entries and allow rules are not items: they union.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from stayfixed import fsops
from stayfixed.config.plates import Plate

# The per-harness subdirectories of a plate.
PROJECT_CLAUDE = "claude"
PROJECT_CODEX = "codex"


@dataclass(frozen=True)
class Kind:
    """One kind of item: as a sentence says it, the harness directory and the directory inside it
    the items stand in (`""` for the harness directory itself), the suffix a name carries (`""`
    for any) and whether only regular files count."""

    said: str
    harness: str
    directory: str
    suffix: str
    files: bool


RULE = Kind("rule", PROJECT_CLAUDE, "rules", ".md", files=True)
CODEX_RULE = Kind("Codex rule", PROJECT_CODEX, "", "", files=True)
SKILL = Kind("skill", PROJECT_CLAUDE, "skills", "", files=False)
AGENT = Kind("agent", PROJECT_CLAUDE, "agents", "", files=False)
KINDS = (RULE, CODEX_RULE, SKILL, AGENT)


@dataclass(frozen=True)
class Folded:
    """`winners`, each name's path in the plate that wins it, in fold order; `holders`, the plates
    holding each name, in plate order."""

    winners: dict[str, Path]
    holders: dict[str, tuple[Plate, ...]]


def fold(
    plates: Sequence[Plate],
    kind: Kind,
    unlisted: Callable[[Path, OSError], Exception] | None = None,
) -> Folded:
    """`kind`'s items over `plates`, each plate's in name order. A directory that cannot be listed,
    or whose entries cannot be asked about, raises what `unlisted` makes of it, each reader's own
    failure; with no `unlisted` it holds nothing."""
    winners: dict[str, Path] = {}
    holders: dict[str, list[Plate]] = {}
    for plate in plates:
        directory = plate.directory / kind.harness / kind.directory
        for name in _names(directory, kind, unlisted):
            winners.pop(name, None)
            winners[name] = directory / name
            holders.setdefault(name, []).append(plate)
    return Folded(winners, {name: tuple(held) for name, held in holders.items()})


def _names(
    directory: Path, kind: Kind, unlisted: Callable[[Path, OSError], Exception] | None
) -> list[str]:
    try:
        if not fsops.is_dir(directory):
            return []
        return [
            name
            for name in sorted(os.listdir(directory))
            if not name.startswith(".")
            and name.endswith(kind.suffix)
            and (not kind.files or fsops.is_file(directory / name))
        ]
    except OSError as exc:
        if unlisted is None:
            return []
        raise unlisted(directory, exc) from exc
