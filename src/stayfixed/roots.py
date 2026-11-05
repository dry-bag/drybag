"""`ledger.code_roots`, contained. `config.paths` guards `[paths]` and names this field as one
the consuming module must check itself, and this module is that check: `ledger.scan` imports it
here, because two spellings of which roots a configuration reaches would be two answers."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from stayfixed import fsops
from stayfixed.config.paths import PathEscape, contained

if TYPE_CHECKING:
    from stayfixed.config.schema import Config


def contained_roots(root: Path, config: Config) -> list[Path]:
    """`ledger.code_roots` that pass `contained()` and exist as directories, in config order.

    `config.paths` says the four path-shaped fields it does not guard and names
    `ledger.code_roots` first; this is the call it asks the consuming module to make.

    NO DIRECTORY IS RETURNED TWICE, and no directory under another returned one is returned
    beside it. Where git cannot list the files, `ledger.scan` walks each entry and adds up what
    it finds, so without this `code_roots = ["src", "src/pkg"]` has `bugs check` say of one
    mention under `src/pkg` that it is "referenced 2 time(s)".

    **An entry is folded before it is asked about.** `contained()` refuses a trailing `/`, a
    doubled `/` and a leading `./` since it shares the write's component rule, and that rule is
    right for a target the engine writes. A code root is only walked, and `"src/"` is the way
    many people write a directory: refused here, it was dropped from the mention and citation
    scans with nothing saying so. `PurePosixPath` folds exactly those
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
    resolved_root = root.resolve()
    for entry in config.ledger.code_roots:
        folded = PurePosixPath(entry).as_posix()
        try:
            candidate = contained(root, folded, resolved_root=resolved_root)
        except PathEscape:
            continue
        if not fsops.is_dir(candidate):
            continue
        if any(_covers(kept, candidate) for kept in found):
            continue
        found = [kept for kept in found if not _covers(candidate, kept)]
        found.append(candidate)
    return found


def _covers(directory: Path, other: Path) -> bool:
    """Whether walking ``directory`` already walks everything under ``other``.

    `is_relative_to`, never a string prefix: `src` would otherwise be read as covering
    `src-vendor`, which shares its first three characters and none of its files.
    """
    return other == directory or other.is_relative_to(directory)
