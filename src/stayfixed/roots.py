"""`ledger.code_roots`, contained. `config.paths` guards `[paths]` and names this field as one
the consuming module must check itself, and this module is that check for every consumer:
`ledger.scan` and the `hints` area's red-run note each import it here, because
two spellings of which roots a configuration reaches would be two answers.
`dropped_roots` names the entries the walks leave out from the same loop, so
the entries named and the entries walked cannot disagree. A profile's red-run hint is handed what
`contained_roots` returns by the note that asks the hint, so a stack's code never imports it."""

from __future__ import annotations

from collections.abc import Collection, Iterator
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from stayfixed import fsops
from stayfixed.config.paths import PathEscape, contained

if TYPE_CHECKING:
    from stayfixed.config.schema import Config

# Why an entry is left out of every walk, one fixed reason each, in `dropped_roots`. No entry is
# refused: `ledger.code_roots` is written by the preset and the repository only, and a walk that
# takes too much costs only that repository's own sessions, so the entry is named, not stopped.
ROOT_ITSELF = (
    "names the repository root, so a walk would take in every environment and worktree under it"
)
NOT_CONTAINED = "is no readable path inside the repository free of links, `..` and `.git`"
NOT_A_DIRECTORY = "names no directory here"


def contained_roots(root: Path, config: Config) -> list[Path]:
    """`ledger.code_roots` that pass `contained()` and exist as directories, in config order.

    `config.paths` says the four path-shaped fields it does not guard and names
    `ledger.code_roots` first; this is the call it asks the consuming module to make.

    NO DIRECTORY IS RETURNED TWICE, and no directory under another returned one is returned
    beside it. Every consumer of this list walks each entry and adds up what it
    finds, so `code_roots = ["src", "src"]` doubled every stale `.pyc` in the count the
    hygiene notice prints, and `["src", "src/stayfixed"]` doubled the part of the tree they
    share -- a wrong number in a notice whose whole job is to be believed about a number.

    **An entry is folded before it is asked about.** `contained()` refuses a trailing `/`, a
    doubled `/` and a leading `./` since it shares the write's component rule, and that rule is
    right for a target the engine writes. A code root is only walked, and `"src/"` is the way
    many people write a directory: refused here, it was dropped from the hygiene counts and the
    citation roots with nothing saying so. `PurePosixPath` folds exactly those
    three spellings and nothing else -- it keeps `..` and an absolute root, which `contained()`
    still refuses.

    Comparing the paths `contained()` returns is enough to collapse two spellings of one
    directory, not just two copies of one spelling: the fold above has already removed `./`
    and repeated separators, and `contained()` refuses a `..` component, an absolute path and a
    symlink anywhere from the root to the target inclusive -- so no two surviving entries can
    name the same directory by different routes. Order is the config's. Between an ancestor
    and a descendant the ANCESTOR wins whichever way round they are written, because it is the
    wider walk and dropping it would lose files; between two entries naming the same
    directory, the first keeps its place.
    """
    found: list[Path] = []
    for _, candidate in _judged(root, config):
        if not isinstance(candidate, Path):
            continue
        if any(_covers(kept, candidate) for kept in found):
            continue
        found = [kept for kept in found if not _covers(candidate, kept)]
        found.append(candidate)
    return found


def dropped_roots(
    root: Path, config: Config, *, defaults: Collection[str] = ()
) -> list[tuple[str, str]]:
    """Each `ledger.code_roots` entry `contained_roots` leaves out, in config order, with its
    reason: `ROOT_ITSELF`, `NOT_CONTAINED` or `NOT_A_DIRECTORY`. An entry inside another one is
    not here: the wider walk takes it in. Nor, while some entry is walked, is a missing directory
    `defaults` (the preset's `code_roots`) lists, folded as `_judged` folds: it loses no walk, and
    dropping it from the list would leave it unwalked once the repository makes it. The entry is
    the repository's own text, so a caller prints it through `stayfixed.printed`."""
    judged = list(_judged(root, config))
    walked = any(isinstance(found, Path) for _, found in judged)
    quiet = {(PurePosixPath(entry).as_posix(), NOT_A_DIRECTORY) for entry in defaults}
    return [
        (entry, found)
        for entry, found in judged
        if isinstance(found, str)
        and not (walked and (PurePosixPath(entry).as_posix(), found) in quiet)
    ]


def _judged(root: Path, config: Config) -> Iterator[tuple[str, Path | str]]:
    """Each entry with the directory it names, or the reason no walk takes it: the one loop both
    functions above read, so the entries walked and the entries named cannot disagree."""
    resolved_root = root.resolve()
    for entry in config.ledger.code_roots:
        folded = PurePosixPath(entry).as_posix()
        if folded == ".":
            # `contained()` refuses `.` as it refuses `..`, and the reason is not the same.
            yield entry, ROOT_ITSELF
            continue
        try:
            candidate = contained(root, folded, resolved_root=resolved_root)
        except PathEscape:
            yield entry, NOT_CONTAINED
            continue
        yield entry, candidate if fsops.is_dir(candidate) else NOT_A_DIRECTORY


def _covers(directory: Path, other: Path) -> bool:
    """Whether walking ``directory`` already walks everything under ``other``.

    `is_relative_to`, never a string prefix: `src` would otherwise be read as covering
    `src-vendor`, which shares its first three characters and none of its files.
    """
    return other == directory or other.is_relative_to(directory)
