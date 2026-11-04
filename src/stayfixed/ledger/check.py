"""Every violation of one register under a root, most structural first, as `Finding`s.

The register is handed in: its directory, index, identifiers and schema are the register's, and
`config` is read only for what no register owns, the roots the scan walks. Every text below
names the register's paths and its command group, so the bug ledger's read as they always have.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from stayfixed import fsops
from stayfixed.committed import committed_document, repository_prefix
from stayfixed.config.loader import CONFIG_FILE, loads
from stayfixed.config.reading import NOT_UTF8
from stayfixed.errors import Failure, Refusal
from stayfixed.findings import Finding, listed
from stayfixed.gitenv import ForkUnknown, fork_points, git_run
from stayfixed.ledger.entries import (
    ID_LINE,
    Entry,
    LedgerError,
    entry_dir,
    entry_paths,
    parse_entry,
    read_ledger_text,
)
from stayfixed.ledger.index import (
    ENTRIES_MISSING,
    FOREIGN_CONTENT,
    foreign_index_lines,
    index_text,
    is_generated_index,
    render_index,
)
from stayfixed.ledger.register import (
    EVIDENCE_LABEL,
    EVIDENCE_PLACEHOLDER,
    Register,
    bug_register,
    located_bug_register,
)
from stayfixed.ledger.scan import code_mentions, entry_citations
from stayfixed.printed import clipped, quoted

if TYPE_CHECKING:
    from collections.abc import Callable

    from stayfixed.config.schema import Config, Personal


# The negative lookahead is the point: the scaffold writes this line with its own placeholder
# text, so a bare match on the label would let every freshly filed entry satisfy the rule
# without anyone having written a word — a placeholder that satisfies its own check is the
# failure mode this rule exists to prevent.
# `[^\S\n]*` (same-line whitespace) and not `\s*`: the latter crosses newlines under MULTILINE
# and would let a bare label pass as long as anything followed it anywhere later in the body.
_EVIDENCE_BOUNDARY = re.compile(
    rf"^{re.escape(EVIDENCE_LABEL)}[^\S\n]*(?!{re.escape(EVIDENCE_PLACEHOLDER)})\S", re.MULTILINE
)
_CONFLICT_MARKER = re.compile(r"^(<{7} |={7}$|>{7} )", re.MULTILINE)
# `{name}` is the register's command group, `bugs` for the bug ledger; `{directory}` and `{index}`
# are its paths, and `{void}` its schema's void status.
LEDGER_REMOVED = (
    "a commit this change forked from the base at carries the ledger ({directory} or {index}) "
    "and this tree has neither; deleting the ledger does not switch the {name} gate off: restore "
    "it from the base"
)
ENTRY_REMOVED = (
    "a commit this change forked from the base at carries this entry and this tree does not; "
    "ledger entries are never deleted: restore it from the base, and move one with `stayfixed "
    "{name} renumber`, which leaves a `{void}` entry at the old number"
)
# `{what}` is the paths the failing read asked about: the ledger's directory and index, or a fork
# point's `stayfixed.toml`. `{base}` is the caller's, printed through `printed.quoted`.
_BASE_UNREAD = (
    "what the commits HEAD forked from `{base}` at hold of {what} is unknown "
    "under {root} ({cause}), so whether this change deleted the ledger or an entry of it is "
    "unknown and the {name} gate proved nothing. Fetch the whole history (`fetch-depth: 0` in "
    "CI), or pass a `--base` this clone holds that shares history with HEAD"
)
# What the loader calls a fork point's copy, so its reason names the right file: its own words
# would name `<root>/stayfixed.toml`, which is the change's copy.
FORK_COPY = "the stayfixed.toml of a commit this change forked from the base at"
# The one cause the three `FORK_*` refusals share, and what it costs the gate.
_FORK_UNKNOWN = (
    "where a commit this change forked from `{base}` at kept the ledger is unknown, so the "
    "{name} gate proved nothing: "
)
# `{reason}` is the loader's own, bounded where it was raised.
FORK_DOES_NOT_LOAD = _FORK_UNKNOWN + "its stayfixed.toml does not load ({reason})"
FORK_REFUSED = (
    _FORK_UNKNOWN + "loading its stayfixed.toml against this tree met a refusal: {reason}"
)
# The load succeeded and the prefix it names is one the identifier grammar refuses, by which no
# entry of that commit can be found. `{prefix}` is the base's own, through `printed.clipped`.
FORK_UNPLACED = (
    _FORK_UNKNOWN + "its stayfixed.toml places its ledger by an identifier prefix the ledger "
    "refuses, {prefix}"
)


@dataclass(frozen=True)
class _BaseLedger:
    entries: tuple[str, ...]  # the entry files directly under the directory there, by name
    # The directory and index of the first fork point that carried the ledger, where that
    # commit's own configuration put them; `None` when none carried one.
    place: tuple[str, str] | None


def _unread(register: Register, base: str, root: Path, cause: str, what: str) -> Failure:
    return Failure(
        _BASE_UNREAD.format(
            what=what, name=register.name, base=quoted(base), root=root, cause=cause
        )
    )


def _body_state_bullet(register: Register) -> re.Pattern[str]:
    """A body bullet restating the status or the level, which live in the frontmatter alone:
    `**Status:**` and, for the bug ledger, `**Severity:**`."""
    level = re.escape(register.schema.level.capitalize())
    return re.compile(rf"^- \*\*(Status|{level}):\*\*", re.MULTILINE)


def uninitialised(root: Path, register: Register) -> bool:
    """No ledger yet: no ledger directory *and* no index this tool generated. The second half
    is the point — the directory missing on its own also describes a ledger whose entry files
    were deleted under a generated index that still links every one of them. Only citations
    are checked here, so the gate can be registered before the first entry."""
    directory = entry_dir(root, register)
    return not fsops.is_dir(directory) and not is_generated_index(index_text(root, register))


def _base_ledger(
    root: Path,
    register: Register,
    base: str,
    locate: Callable[[str], Register] | None,
) -> _BaseLedger:
    """What the commits HEAD forked from `base` at carry of the ledger: where the first of them
    that has the directory or the index keeps it, and the `<PREFIX>-nnn.md` entry files directly
    under the directory in any of them.

    Each commit's ledger is read where that commit kept it: `locate` builds the register a fork
    point configured (`_fork_register`, bound once by `register_gate`). Read at the tree's paths,
    a change that moved the ledger by `[paths]` found nothing there at the fork, so it could
    delete an entry in the same change and pass. A register no configuration builds is read at
    its own paths at every commit (`locate` is `None`).

    Those commits are `git merge-base --all <base> HEAD`, every best common ancestor, the ones
    `plan` diffs against too. What the base gained after the change forked is not the change's to
    have kept, so a branch behind its base is not blamed for an entry filed since; and what the
    change forked with, it still answers for, on a stale branch as on the merge commit CI checks
    out, whose base parent the base can have moved past. A history the change shapes itself can
    give it several merge bases, and the one `merge-base` alone answers, the newest by date, can
    predate an entry another of them carries: a merge deletes that entry all the same. So each
    is listed with one `git ls-tree -r` of the two configured paths, whose names come back
    relative to `root`, and their entries are united. Entries are append-only, so on a base that
    kept its entries the union refuses no branch that deleted nothing; an entry removed from the
    base itself, by a direct push, is still named on a branch whose merge bases include one from
    before the removal, and is restored on the base.

    A base shaped like an option is refused, as `plan check` refuses it. Fork points
    `gitenv.fork_points` cannot name — a base git cannot resolve, one that shares no commit with
    HEAD, a shallow clone, and one git cannot say is shallow or not — and a listing git does not
    give, are a `Failure` — "could not run" to a gate — and never "the base has no ledger",
    which would pass exactly the change this question exists to catch.
    """
    if base.startswith("-"):
        raise Refusal(f"{quoted(base)} looks like an option, not a base ref")
    forks = fork_points(root, base)
    if isinstance(forks, ForkUnknown):
        raise _unread(register, base, root, forks.cause, _paths(register))
    place: tuple[str, str] | None = None
    entries: set[str] = set()
    for fork in forks:
        held = register if locate is None else locate(fork)
        code, out = git_run(
            root, "ls-tree", "-r", "-z", "--name-only", fork, "--", held.directory, held.index
        )
        if code != 0:
            raise _unread(register, base, root, ForkUnknown.of(code).cause, _paths(held))
        names = [name for name in out.split("\0") if name]
        if names and place is None:
            place = (held.directory, held.index)
        under = f"{held.directory}/"
        entries.update(
            name.removeprefix(under)
            for name in names
            if name.startswith(under)
            and name.endswith(".md")
            and held.ids.is_identifier(name.removeprefix(under).removesuffix(".md"))
        )
    return _BaseLedger(tuple(sorted(entries)), place)


def _paths(register: Register) -> str:
    return f"{register.directory} and {register.index}"


def _fork_register(
    fork: str,
    *,
    root: Path,
    prefix: str,
    personal: Personal,
    register: Register,
    locate: Callable[[Config], Register],
    base: str,
) -> Register:
    """The register as the commit `fork` configured it, out of its own `stayfixed.toml`.

    Found by `committed.committed_document`, at the project root's path inside the repository,
    `prefix`, and loaded through the loader, against this tree's disk, under its own label, with the
    `[personal]` this command already read, so no second machine file is read.

    A commit with no copy there is the bootstrap, the change that adds the configuration, and
    `register` decides. A copy that does not load, is
    not UTF-8 or meets a refusal is no answer, and never the tree's paths in its place: read
    there, a change that moved the ledger would pass the deletion this exists to catch.
    """

    def failed(code: int) -> Failure:
        return _unread(register, base, root, ForkUnknown.of(code).cause, CONFIG_FILE)

    def does_not_load(reason: object) -> Failure:
        return Failure(
            FORK_DOES_NOT_LOAD.format(base=quoted(base), name=register.name, reason=reason)
        )

    raw = committed_document(root, fork, CONFIG_FILE, prefix=prefix, failed=failed)
    if raw is None:
        return register
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise does_not_load(NOT_UTF8.format(path=FORK_COPY)) from None
    try:
        copy = loads(decoded, root, label=FORK_COPY, personal=personal)
    except Refusal as exc:
        refused = FORK_REFUSED.format(base=quoted(base), name=register.name, reason=exc)
        raise Refusal(refused) from None
    except Failure as exc:
        raise does_not_load(exc) from None
    try:
        return locate(copy)
    except Refusal:
        prefix_named = clipped(copy.ledger.id_prefix)
        unplaced = FORK_UNPLACED.format(base=quoted(base), name=register.name, prefix=prefix_named)
        raise Refusal(unplaced) from None


def _removed_entries(root: Path, register: Register, base: _BaseLedger | None) -> list[Finding]:
    """Every entry file `base` carries whose exact name this tree's ledger directory does not
    hold, one finding each.

    Entries are append-only: `renumber` leaves a void entry at the number it moves from,
    so no command this project ships deletes one, and a change that does is refused whatever
    still mentions the identifier. The mentions cannot decide it, and nor can the fixtures
    marker, which is an exemption a file grants itself.

    The names are compared with the directory's own listing, never looked up one by one: a
    filesystem that folds case finds `BR-001.md` at `br-001.md`, which the ledger, loading its
    entries by exact name, does not, so a rename in case alone passed there and failed on Linux.
    A directory that is not there, or cannot be listed, holds no entry.
    """
    if base is None:
        return []
    try:
        present = set(os.listdir(entry_dir(root, register)))
    except OSError:
        present = set()
    removed = ENTRY_REMOVED.format(name=register.name, void=register.schema.void)
    return [
        Finding("entry-removed", f"{register.directory}/{name}", None, removed)
        for name in base.entries
        if name not in present
    ]


def _dangling_mentions(
    root: Path, config: Config, register: Register, known: set[str]
) -> list[Finding]:
    """Every identifier the scanned files mention that `known` does not hold, one finding per
    identifier at its first mention."""
    found: list[Finding] = []
    for identifier, locations in sorted(code_mentions(root, config, register).items()):
        if identifier not in known:
            path_, line = locations[0]
            found.append(
                Finding(
                    "dangling-mention",
                    path_.as_posix(),
                    line,
                    f"mentions {identifier}, which has no entry file "
                    f"(referenced {len(locations)} time(s))",
                )
            )
    return found


def _unledgered(
    root: Path, config: Config, register: Register, base: _BaseLedger | None
) -> list[Finding]:
    """The findings for a tree with no ledger: the ledger the change forked with, when it
    forked with one, and every mention and citation of an entry, since with no ledger each one
    dangles.

    "No ledger" is read off the tree, which a pull request writes, so the tree's word for it
    cannot be what switches the gate off: the commits the change forked from the base at are
    asked whether it had one, and a mention of an identifier is as much a reference as a
    citation of its file. A project that registers the gate before its first entry has no
    ledger there and mentions none, and stays green, as does a branch forked before the base's
    first entry. With no `base` — `bugs check` run without `--base` — only the tree is judged.
    The one `ledger-removed` finding stands for every entry that commit carried.
    """
    found: list[Finding] = []
    if base is not None and base.place is not None:
        # Where the base kept it, which is what "restore it from the base" restores: after a
        # change that moved `[paths]`, the tree's own paths are ones no commit ever carried.
        directory, index = base.place
        removed = LEDGER_REMOVED.format(directory=directory, index=index, name=register.name)
        found.append(Finding("ledger-removed", directory, None, removed))
    empty: set[str] = set()
    found.extend(_dangling_mentions(root, config, register, empty))
    return found + _dangling_citations(root, config, register, empty)


def _dangling_citations(
    root: Path, config: Config, register: Register, known: set[str]
) -> list[Finding]:
    """Every entry file a document or source cites that `known` does not hold, one finding per
    identifier at its first citation."""
    found: list[Finding] = []
    for identifier, locations in sorted(entry_citations(root, config, register).items()):
        if identifier not in known:
            path_, line = locations[0]
            found.append(
                Finding(
                    "dangling-citation",
                    path_.as_posix(),
                    line,
                    f"cites {register.directory}/{identifier}.md, which does not exist "
                    f"(referenced {len(locations)} time(s))",
                )
            )
    return found


def register_gate(
    root: Path,
    config: Config,
    register: Register,
    base: str = "",
    *,
    locate: Callable[[Config], Register] | None = None,
) -> list[Finding]:
    """One register's gate, whole: every violation of `register` under `root`, most structural
    first.

    Before the ledger directory exists *and* before this tool has written an index there is
    nothing it owns, which is what lets the check be registered in CI one change before the
    first entry is filed: only a reference to an entry is reported then, since with no ledger
    every one of them dangles, and, against a `base`, a ledger the change forked with
    (`_unledgered`). A generated index with no ledger directory behind it is the other thing
    that shape describes, and it is the ledger having been deleted. Against a `base`, every arm
    past that one also names each entry the change forked with and the tree lacks
    (`entry-removed`). Both are read at every commit HEAD forked from `base` at
    (`_base_ledger`), where that commit's own configuration put the ledger when `locate`
    says how a configuration builds this register.
    """
    carried = None
    if base:
        # The strategy bound once: every fork point is located with the same root, prefix,
        # `[personal]` and fallback. The prefix is asked only when a fork's own copy is read,
        # and refuses a root git and the caller spell differently.
        at = None
        if locate is not None:
            at = partial(
                _fork_register,
                root=root,
                prefix=repository_prefix(root),
                personal=config.personal,
                register=register,
                locate=locate,
                base=base,
            )
        carried = _base_ledger(root, register, base, at)
    if uninitialised(root, register):
        return _unledgered(root, config, register, carried)
    schema = register.schema
    directory = entry_dir(root, register)
    index_name = register.index
    # First: a deleted entry is the most structural finding a ledger can have.
    found = _removed_entries(root, register, carried)
    if not fsops.is_dir(directory):
        missing = ENTRIES_MISSING.format(directory=register.directory, index=index_name)
        return [Finding("entries-missing", index_name, None, missing), *found]

    entries: list[Entry] = []
    texts: dict[str, str] = {}
    required = set(register.evidence_boundary_for)
    restated = _body_state_bullet(register)
    for path in entry_paths(root, register):
        # Parsed against the repo-relative path, which is the one every message here names:
        # these are printed by CI, where an absolute path is a runner's scratch directory.
        relative = path.relative_to(root).as_posix()
        try:
            text = read_ledger_text(path, where=path.relative_to(root))
        except LedgerError as error:
            found.append(Finding("unreadable-entry", relative, None, str(error)))
            continue
        if _CONFLICT_MARKER.search(text):
            found.append(Finding("conflict-marker", relative, None, "unresolved conflict marker"))
            continue
        try:
            entry = parse_entry(text, path=path.relative_to(root), register=register)
        except LedgerError as error:
            found.append(Finding("unreadable-entry", relative, None, str(error)))
            continue
        if entry.id != path.stem:
            found.append(
                Finding(
                    "id-mismatch", relative, None, f"`id` {entry.id} does not match its filename"
                )
            )
        if restated.search(entry.body):
            found.append(
                Finding(
                    "state-in-body",
                    relative,
                    None,
                    f"body restates `**Status:**`/`**{schema.level.capitalize()}:**`; those live "
                    "in the frontmatter alone",
                )
            )
        level = entry.fields[schema.level]
        if level in required and not _EVIDENCE_BOUNDARY.search(entry.body):
            found.append(
                Finding(
                    "evidence-boundary",
                    relative,
                    None,
                    f"{schema.level} `{level}` needs a filled `{EVIDENCE_LABEL}` line — a "
                    "plan built on this entry inherits its silences as premises",
                )
            )
        entries.append(entry)
        texts.setdefault(entry.id, text)

    known = {entry.id for entry in entries}
    by_id: defaultdict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        by_id[entry.id].append(entry)
    for identifier, holders in sorted(by_id.items()):
        if len(holders) > 1:
            # Capped, and nothing is lost from `--json`: only one holder's file name can be the
            # identifier, and every other one has an `id-mismatch` finding naming it, so that
            # one is named first, inside the cap whatever the sort puts after it.
            first = sorted(holders, key=lambda h: h.path.stem != identifier)
            joined = listed([str(h.path) for h in first])
            found.append(
                Finding(
                    "duplicate-id",
                    "",
                    None,
                    f"{identifier} is claimed by more than one file: {joined}",
                )
            )
    for entry in entries:
        for identifier in entry.related:
            if identifier not in known:
                found.append(
                    Finding(
                        "dangling-related",
                        entry.path.as_posix(),
                        None,
                        f"`related` names {identifier}, which has no entry file",
                    )
                )

    current = index_text(root, register)
    foreign = foreign_index_lines(root, current, register)
    if foreign:
        found.append(
            Finding(
                "foreign-index-content",
                index_name,
                None,
                FOREIGN_CONTENT.format(index=index_name, count=len(foreign), first=foreign[0]),
            )
        )
    # Suppressed while the index holds foreign content: regenerating is what deletes it, so
    # recommending it here would hand the operator the destructive step.
    elif current != render_index(sorted(entries, key=lambda e: e.number), register):
        moves = _half_done_moves(register, entries, texts, current)
        found.append(Finding("stale-index", index_name, None, _stale(register, moves)))

    found.extend(_dangling_mentions(root, config, register, known))
    # Wider than the scan above, and reported separately because a citation says something a
    # bare mention does not: it names a path, so a reader who follows it gets a 404 rather than
    # an unfamiliar identifier. Closing an entry and renaming its file is the shape that leaves
    # one behind, and it lands in a docs-only commit.
    return found + _dangling_citations(root, config, register, known)


def _stale(register: Register, moves: list[tuple[str, str]]) -> str:
    """The stale index's line: the one renumber that finishes it, each of several that could,
    or `index` when none explains it.

    **Several are named and none is chosen.** Two entries that differ only in `id:`, which a
    `bugs new` run twice files, make a move of either explain the same tree, and the one that
    was not started voids an entry nobody moved and leaves the other live beside its new number.
    """
    commands = [f"stayfixed {register.name} renumber {old} {new}" for old, new in moves]
    if len(commands) > 1:
        return (
            "is stale; more than one unfinished renumber explains it, and only the one that was "
            f"started finishes it: {', or '.join(commands)}"
        )
    return f"is stale; run: {commands[0] if commands else f'stayfixed {register.name} index'}"


def _half_done_moves(
    register: Register, entries: list[Entry], texts: dict[str, str], current: str
) -> list[tuple[str, str]]:
    """Every renumber, `(old, new)`, whose interruption explains the stale index `current`
    exactly, once each and in the order they were tried.

    A `renumber` writes the index last, so a run killed before it leaves the index it found:
    rendered from the ledger as it stood before the move. That state is recognised as
    `renumber` recognises it — `new` holding `old`'s text with its `id:` line rewritten, or
    `old` the void pointer the move titles toward `new` — and confirmed by the index alone: the
    entries with `new`'s text restored to `old` render it, every line either as it is or as the
    sweep left it (`_swept_from`). The sweep runs before the index write and rewrites the other
    entry files too: a void pointer an earlier move left toward `old` is retitled toward `new`,
    and so is a live entry whose title names `old`. Sent to `bugs index` instead, the operator
    turned the check green over two live entries for one bug or over mentions the sweep never
    reached, which a re-run then took for a finished move's and left alone. Anything else stale,
    a finished move's neighbour edited since included, is `bugs index`'s, and so is no answer.
    """
    by_text: defaultdict[str, list[str]] = defaultdict(list)
    for identifier, text in texts.items():
        by_text[ID_LINE.sub("id:", text, count=1)].append(identifier)
    pairs = [(old, new) for same in by_text.values() for old in same for new in same if old != new]
    void = register.schema.void
    pairs += [
        (entry.id, entry.related[0])
        for entry in entries
        if entry.status == void
        and len(entry.related) == 1
        and entry.title.startswith(f"renumbered to {entry.related[0]} — ")
    ]
    explained: list[tuple[str, str]] = []
    for old, new in dict.fromkeys(pairs):
        if new not in texts:
            continue
        restored = ID_LINE.sub(f"id: {old}", texts[new], count=1)
        try:
            moved = parse_entry(
                restored, path=Path(register.directory) / f"{old}.md", register=register
            )
        except LedgerError:
            continue
        before = [entry for entry in entries if entry.id not in (old, new)] + [moved]
        rendered = render_index(sorted(before, key=lambda e: e.number), register)
        if _swept_from(current, rendered, old=old, new=new):
            explained.append((old, new))
    return explained


def _swept_from(found: str, rendered: str, *, old: str, new: str) -> bool:
    """Whether `rendered` is the index `found` with a move's sweep applied to any of its lines.

    Compared forward, line by line: each line of the entries as they stand is the line the index
    found, or that line with `old` rewritten to `new`, which is what the sweep writes into an entry.
    The sweep is a function and its inverse is not — a `new` the sweep wrote and one an entry
    held before the move read alike — so reading the whole ledger back left both kinds of row at
    once unexplained. The rows of other entries keep their places: the sweep rewrites no
    identifier of theirs, no status and no date, so the order and the section counts are the
    found index's.
    """
    was, now = found.splitlines(), rendered.splitlines()
    if len(was) != len(now):
        return False
    sweep = re.compile(rf"\b{re.escape(old)}\b")
    return all(
        line in (before, sweep.sub(new, before)) for before, line in zip(was, now, strict=True)
    )


def bugs_gate(root: Path, config: Config, base: str = "") -> list[Finding]:
    """The `bugs` gate: the bug ledger's `register_gate`, in the `(root, config, base)` shape.

    `bugs check` answers with this function, with `--base` as `base` or `""`, which judges the
    tree alone; every gate run passes the base it judges against.
    """
    return register_gate(root, config, bug_register(config), base, locate=located_bug_register)
