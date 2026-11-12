"""Root containment for the `[paths]` fields, and for nothing else yet.

`validate_paths` iterates `config.paths.as_dict()`, so the guard covers exactly the fields of
`schema.Paths`. Two path-shaped, repository-writable fields never reach `contained()`:
`memory.groups` and `memory.index_extra`, which load whatever they hold. `drybag.memory` must call
`contained()` itself on the fields it consumes; widening the guard here would change `Config`'s
shape, so it belongs with the module that first reads those fields.

Two rules: `PATH_VALUE` is the grammar half, what a value must match before it may be printed
anywhere, and `contained()` the root half, whether it may be written *here*. The two fields above
are unguarded by both. The component rule is `fsops.checked_components`, borrowed and never
restated, so a value `plan()` accepts is one `apply()` can write.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path

from drybag.config.machine import owner_home
from drybag.config.schema import Config
from drybag.errors import Failure, Refusal
from drybag.fsops import (
    REACHES_NO_FILE,
    UnsafePath,
    checked_components,
    names_component,
    names_control_directory,
    resolved,
    said,
)
from drybag.grammar import PATH_VALUE


class PathEscape(Refusal):
    """A configured path that leaves the project root or passes through a symlink, or one
    `contained()` cannot say either of (`PathUnasked`). `key` is the `[paths]` key `validate_paths`
    refused, which the loader's NOTE path removes so the preset's value applies; `None` otherwise.
    """

    def __init__(self, message: str, *, key: str | None = None) -> None:
        super().__init__(message)
        self.key = key


class PathUnasked(PathEscape):
    """A configured path with an ancestor no `lstat` could ask about, and no symlink above it: a
    `PathEscape`, since no path is contained until every ancestor is asked. A caller with its own
    words for an escape catches this first. `fault` is the system's words, never the path."""

    def __init__(self, message: str, *, fault: str) -> None:
        super().__init__(message)
        self.fault = fault


def contained(
    root: Path,
    relative: str,
    *,
    allow_final_symlink: bool = False,
    resolved_root: Path | None = None,
) -> Path:
    try:
        # The empty path, an absolute path, `..`, `.`, an empty segment and git's control
        # directory, read off the caller's own spelling by the one rule in `fsops`; a leaf owns
        # no user-facing verdict, so its `UnsafePath` becomes a `Refusal` here.
        parts = checked_components(relative)
    except UnsafePath as exc:
        raise PathEscape(str(exc)) from exc
    target = root.joinpath(*parts)
    # Asked from the root down, and no further than the first ancestor that reaches no file:
    # nothing below one reaches a file either, so a long value that reaches nothing costs one
    # question. The answers are then judged from the deepest up.
    answers: list[tuple[Path, int | OSError]] = []
    ancestor = root
    for part in parts:
        ancestor = ancestor / part
        # `lstat`, each fault given its answer, never `Path.is_symlink()`, which answers them
        # differently across interpreters. A path past the longest one is reached only by the
        # descriptor walk every write goes through (`fsops.open_within`), which refuses a link of
        # its own accord; any other fault leaves the question unanswered, which is a refusal.
        try:
            answers.append((ancestor, os.lstat(ancestor).st_mode))
        except OSError as exc:
            if exc.errno in REACHES_NO_FILE:
                break
            answers.append((ancestor, exc))
    unasked: PathUnasked | None = None
    for ancestor, answer in reversed(answers):
        if isinstance(answer, OSError):
            # The deepest such ancestor is refused, once every ancestor above it has been asked
            # for a link: a committed link into a directory nobody may search is the cause to
            # name. By its place under the root and the fault's words, never `str(exc)`, which
            # carries the absolute path.
            if unasked is None:
                place = ancestor.relative_to(root).as_posix()
                unasked = PathUnasked(
                    f"{relative!r} cannot be checked for a symlink at {place!r} ({said(answer)})",
                    fault=said(answer),
                )
                unasked.__cause__ = answer
            continue
        if stat.S_ISLNK(answer) and not (allow_final_symlink and ancestor == target):
            # Through `repr`, which escapes every line break and control character, since the
            # ancestor's name is the repository's; by its place under the root, never the absolute
            # path. `ancestor` is below `root`, since the walk starts below it.
            named = ancestor.relative_to(root).as_posix()
            raise PathEscape(f"{relative!r} passes through a symlink at {named!r}")
    if unasked is not None:
        raise unasked
    # Defence in depth: the guards above refuse every escape a path string can express, and this
    # is the net for the form nobody anticipated. A caller validating many paths passes
    # `resolved_root` so the root resolves once; `fsops.resolved` makes a loop an `OSError` on
    # every interpreter. Compared by components, both resolved, rather than over every parent.
    if resolved_root is None:
        resolved_root = resolved(root)
    reached = resolved(target.parent) / target.name if allow_final_symlink else resolved(target)
    if reached.parts[: len(resolved_root.parts)] != resolved_root.parts:
        raise PathEscape(f"{relative!r} resolves outside the project root")
    return target


# drybag's own directory: `.drybag/local/` in a project (attach's ledger, the local-only note
# store), and the scaffold engine's manifest in an overlay. Spelled here because `config` imports
# no area and every area that keeps a file there imports `config`.
DRYBAG_DIRECTORY = ".drybag"


def names_drybag_directory(relative: str) -> bool:
    """Whether any component of `relative` is drybag's own directory, spelled in any case
    (`fsops.names_component`). Any depth, because a package initialised on its own inside a
    monorepo keeps its own `.drybag/local/`; any case, because macOS and Windows fold it."""
    return names_component(relative, DRYBAG_DIRECTORY)


# A named cap: the longest `[paths]` value, in characters, which the grammar holds to ASCII and so
# to as many bytes. 1024 is the longest path macOS opens by name (`PATH_MAX`; Linux takes 4096),
# so a longer value names nothing a person meant, and every `PreToolUse` hook reads every value.
# Asked before the grammar; the refusal names the key, never the value. No shipped file states it.
PATH_VALUE_LIMIT = 1024


# `PATH_VALUE` in words, for the refusal a person reads: a change to the grammar changes this too.
PATH_RULE = (
    "segments of letters, digits, `.`, `_` and `-` joined by single `/`, none of them `.` or "
    "`..`, the first not starting with `-`, and no `/` at either end"
)


def validate_paths(config: Config, root: Path) -> dict[str, Path]:
    """Every `[paths]` value contained in `root`, or a `PathEscape` keyed to the first that is
    not, so the loader's NOTE path can put that one key back to the preset's value."""
    return validate_path_values(config.paths.as_dict(), root)


def validate_path_values(values: Mapping[str, str], root: Path) -> dict[str, Path]:
    """`validate_paths` for `values`, `[paths]` values by their key's name: the loader's NOTE
    path asks it of a preset's value before it puts a key back to that value, so a value that
    does not hold in this repository either is named rather than reset to."""
    resolved_root = root.resolve()
    for name, relative in values.items():
        if len(relative) > PATH_VALUE_LIMIT:
            raise PathEscape(
                f"paths.{name} is longer than the {PATH_VALUE_LIMIT} characters a configured path "
                "may be",
                key=f"paths.{name}",
            )
        if not PATH_VALUE.match(relative):
            # Named and never quoted: this is the value a report would otherwise print. The rule
            # in words, because `PATH_VALUE.pattern` is no sentence a person can act on.
            raise PathEscape(
                f"paths.{name} is not a plain relative path: {PATH_RULE}", key=f"paths.{name}"
            )
        if names_control_directory(relative):
            # Named and never quoted, for the same reason. The grammar admits a leading dot, so a
            # clone could otherwise point a value at `.git/hooks/pre-commit`. The anchor is the
            # project root the CLI resolved, and `.git` is git's own name inside it; the clone
            # authors this value and nothing else. `.git` and not "a leading dot", because
            # `.github/` is an ordinary directory.
            raise PathEscape(
                f"paths.{name} names git's control directory, which is git's and not "
                "drybag's to write into",
                key=f"paths.{name}",
            )
        if names_drybag_directory(relative):
            # Named and never quoted. `.drybag/` holds drybag's manifest and, under
            # `.drybag/local/`, state git never sees and cannot restore, while a `[paths]` value is
            # committed. The anchor is the project root the CLI resolved and `DRYBAG_DIRECTORY`, a
            # constant in the installed package; the clone authors the value and nothing else. No
            # configured path belongs there: drybag finds every file it keeps there by a constant.
            raise PathEscape(
                f"paths.{name} names drybag's own directory {DRYBAG_DIRECTORY}, which holds "
                "its manifest and state git never sees and is not a place for a configured path",
                key=f"paths.{name}",
            )
    found: dict[str, Path] = {}
    for name, relative in values.items():
        try:
            found[name] = contained(
                root,
                relative,
                allow_final_symlink=(name == "memory"),
                resolved_root=resolved_root,
            )
        except PathEscape as exc:
            # `contained()` is every caller's and names no key; this caller knows which one.
            exc.key = f"paths.{name}"
            raise
    return found


# The machine's data directory under `HOME`, on every platform: the binding records
# (`drybag.binding`) among what it holds. No `XDG_*` variable is read, as `config.machine` reads
# none: an environment a repository can set would choose which records bind it.
DATA_DIRECTORY = Path(".local") / "share" / "drybag"
NO_HOME = (
    "HOME names no home directory, so this machine has no data directory to keep its binding "
    "records in; set HOME to your home directory"
)


def data_directory() -> Path:
    """`$HOME/.local/share/drybag`, or `Failure` where `HOME` names no home directory."""
    home = owner_home()
    if home is None:
        raise Failure(NO_HOME)
    return home / DATA_DIRECTORY
