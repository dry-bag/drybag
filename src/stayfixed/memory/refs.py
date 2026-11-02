"""Backticked repository paths in notes that no longer resolve (`memory refs`), and the link
graph's advice beside them, over one walk of the store.

Notes are read as authoritative and they age silently: nothing in the tree points back at
them, so a module they name can be deleted without anything going red, and the next session
is sent after it. A candidate is dropped whenever the tree can explain it: shorthand under a
source root, an absolute path outside this repository, a placeholder, or a path the
repository's own ignore rules cover — except a reference into the store itself, which the
ignore rules cover wholesale and which is therefore always settled against the filesystem.
Intent is not inferred: a reference wrapped in prose saying the file is gone is still reported;
write such a path in *italics*, and the prose says what it said with nothing to report.

What the walk could not read is reported beside what it found: a note that exists and would
not parse is not a clean note, for the reason the ledger's sweep reports a file it could not
read. A configured group the resolver could not provide is a refusal, from the resolver's own
record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from stayfixed.config.overlay import overlay_root
from stayfixed.config.schema import OVERLAY_MODE, Config
from stayfixed.errors import Failure
from stayfixed.findings import Finding
from stayfixed.fsops import read_regular_text, resolved, said
from stayfixed.gitenv import git_run
from stayfixed.memory.graph import check_memory_graph, wiki_links
from stayfixed.memory.notes import Note, Walk, walk
from stayfixed.memory.store import Store, permitted_roots
from stayfixed.printed import quoted
from stayfixed.prose import blank_fences, path_references, present_within
from stayfixed.roots import contained_roots

# Deliberate placeholders a note may write without claiming a file. Not a config key.
_PLACEHOLDER_STEMS = frozenset({"foo", "bar", "baz", "qux", "xxx"})
DEAD_REFERENCE = "dead-reference"
AUDIENCE = "audience"


@dataclass(frozen=True)
class RefsReport:
    findings: list[Finding]
    unavailable: dict[str, str]  # group -> the resolver's reason (`Store.unavailable`)
    unreadable: list[tuple[Path, str]]  # `Walk.unreadable`: notes that exist and would not parse
    notices: list[Finding]  # the link graph's advice (`memory.graph`), which never gates


def source_roots(root: Path, config: Config) -> tuple[str, ...]:
    """Where shorthand resolves: the root, every contained code root, and the parent of every
    configured document path (`docs` for the defaults) — never one project's list."""
    names = [""]
    names.extend(d.relative_to(root).as_posix() for d in contained_roots(root, config))
    for value in config.paths.as_dict().values():
        parent = str(PurePosixPath(value).parent)
        if parent not in (".", "") and parent not in names:
            names.append(parent)
    return tuple(names)


def _is_placeholder(target: str) -> bool:
    """Matched per path component, and on the stem alone, so `docs/foo/thing.py` is a
    placeholder while a real module whose name merely contains one — `widget/foobar.py` — is
    still settled against the tree."""
    return any(PurePosixPath(part).stem in _PLACEHOLDER_STEMS for part in target.split("/"))


def _resolves(root: Path, target: str, roots: tuple[str, ...]) -> bool:
    if target.startswith("/"):
        # A path from another host's filesystem: notes quote deployment layouts verbatim. An
        # absolute path that does happen to sit in this checkout is still checked.
        return not Path(target).is_relative_to(root) or _settled(root, Path(target))
    return any(_settled(root, root / prefix / target) for prefix in roots)


def _settled(root: Path, path: Path) -> bool:
    """A candidate names something in the tree, or leads out of it through a symlink and is
    not this repository's to answer (`prose.present_within`): either way it is not reported."""
    return present_within(root, path) is not False


def _inside_store(root: Path, store: Store, target: str) -> bool:
    # Through `fsops.resolved`, which answers a symlink loop as an `OSError` on every interpreter:
    # both the note's path and the loop are bytes a clone can commit.
    try:
        return resolved(root / target).is_relative_to(resolved(store.path))
    except OSError:
        return False


def _ignored(root: Path, targets: set[str]) -> set[str]:
    """Paths the repository's own ignore rules cover: whether one exists is a fact about a
    checkout, not about the tree. `--no-index` because a tracked path is never "ignored";
    exit 1 is "nothing matched", an answer, which is why the runner does not collapse it.

    `-z`, because the answer is matched back against the path that was asked about. Without it
    git C-quotes any path holding a non-ASCII byte or a space on OUTPUT, so `build/caf\303\251.py`
    comes back quoted and escaped and never equals the target this function sent: the ignore
    rules cover it, this set does not contain it, and the note carries a `dead-reference` its
    author has no way to satisfy — the file is ignored, so creating it changes nothing. `-z`
    also makes the INPUT NUL-separated, so a path is never split on a byte of its own name."""
    if not targets:
        return set()
    code, out = git_run(
        root, "check-ignore", "--no-index", "--stdin", "-z", stdin="\0".join(sorted(targets))
    )
    if code not in (0, 1):
        return set()
    return {name for name in out.split("\0") if name}


def _lines(note: Note) -> list[tuple[int, str]]:
    """Every prose line of the note with its file line number; fenced code is blanked.

    The note is re-read here rather than taken from `Note.body`, which drops the frontmatter and
    with it the line numbers every finding carries — so the decode can fail again even though
    `read_note` already succeeded, and it must fail as the operator's file being wrong (1) and
    never as an internal error (2).
    """
    try:
        # To the read cap, as the walk read it: a note past it by now is named, never read whole.
        text = read_regular_text(note.path)
    except OSError as exc:
        raise Failure(f"{quoted(note.path.name)} cannot be read ({said(exc)})") from exc
    except UnicodeDecodeError as exc:
        raise Failure(f"{quoted(note.path.name)} is not valid UTF-8 ({exc.reason})") from None
    return list(enumerate(blank_fences(text).splitlines(), start=1))


def _where(note: Note, store: Store) -> str:
    return note.path.relative_to(store.path).as_posix()


def unresolved(root: Path, config: Config, store: Store, walked: Walk) -> list[Finding]:
    roots = source_roots(root, config)
    candidates: list[tuple[Note, int, str]] = []
    for note in walked.notes:
        for number, line in _lines(note):
            for target in path_references(line):
                if _is_placeholder(target) or _resolves(root, target, roots):
                    continue
                candidates.append((note, number, target))
    ignored = _ignored(root, {t for _, _, t in candidates if not _inside_store(root, store, t)})
    return [
        Finding(DEAD_REFERENCE, _where(note, store), number, target)
        for note, number, target in candidates
        if target not in ignored
    ]


def audience_violations(store: Store, config: Config, walked: Walk) -> list[Finding]:
    """A note in the cross-project group must not `[[link]]` into a project-scoped one,
    because that link dangles for every other project. Empty for a store with no cross-project
    group — every non-overlay store."""
    overlay = overlay_root(store.machine)
    if overlay is None or store.mode != OVERLAY_MODE:
        return []
    common = permitted_roots(overlay, config.project.name)[0]
    common_groups = {
        name
        for name, path in store.groups.items()
        if path.resolve().is_relative_to(common.resolve())
    }
    project_notes = {n.name for n in walked.notes if n.store_group not in common_groups}
    found: list[Finding] = []
    for note in walked.notes:
        if note.store_group not in common_groups:
            continue
        for number, line in _lines(note):
            for link in wiki_links(line):
                if link.group(1) in project_notes:
                    found.append(Finding(AUDIENCE, _where(note, store), number, link.group(1)))
    return found


def check_refs(root: Path, config: Config, store: Store) -> RefsReport:
    # One walk for every report below: the link graph reads the notes this walk found, rather
    # than walking the store again for the same groups.
    walked = walk(store.path, [g for g in config.memory.groups if g in store.groups])
    return RefsReport(
        unresolved(root, config, store, walked) + audience_violations(store, config, walked),
        dict(store.unavailable),
        list(walked.unreadable),
        check_memory_graph(store, config, walked),
    )
