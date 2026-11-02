"""The probes no gate runs: what an inventory reads from files and the git index alone.

Each probe is a small function over the repository, with no network and no tool run. Its id,
principle, severity and remedy live once, on its `Probe`; the function returns only what it saw,
and `run_probes` builds the items, so the attribute a test reads off `PROBES` is the attribute
an item carries.

**A probe that could not look says so.** Every git query runs under `QUERY_TIMEOUT_SECONDS`,
and an exit that is not one of that query's own answers — `git_run`'s `-1` included, which is a
timeout or a git that could not start — is `unread`. So is a file
the probe cannot read or parse, and a path through a symlink. `run_probes` turns `unread` into
one `could-not-look` warning per probe and never into "nothing found": an empty answer read
from a query that did not finish would say no secret is committed.

**No repository byte can end the inventory.** Everything a probe's reading can raise on
repository content is caught where it is read and becomes `unread`.

**Nothing here is printed.** A `where` label is a path the repository chose, a sha, or this
module's own words, and it goes to the machine-readable output only; the summary that reports
these items prints counts and this module's vocabulary.

Two inventory items are not built. Another tool's design-document directories are that tool's
convention, and stayfixed names no other tool's convention. And whether a test exercises what
its name says can be judged only by reading one stack's test files, which the inventory does not
read.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from stayfixed import fsops
from stayfixed.assess.model import Item, item
from stayfixed.config.loader import preset_defaults
from stayfixed.config.paths import PathEscape, contained
from stayfixed.config.schema import COMMIT_TYPE_WORD, IN_REPO_MODE
from stayfixed.findings import Severity
from stayfixed.fsops import read_bounded, read_regular_text
from stayfixed.gitenv import QUERY_TIMEOUT_SECONDS, git_run
from stayfixed.printed import clipped
from stayfixed.roots import contained_roots, dropped_roots
from stayfixed.scaffold import EntriesError, judged_entries

if TYPE_CHECKING:
    from stayfixed.config.schema import Config

COULD_NOT_LOOK = "could-not-look"
PROFILE = "profile"
PROFILE_NOT_SHIPPED = "profile-not-shipped"

COULD_NOT_LOOK_REMEDY = (
    "stayfixed could not read all of what `where` names, so open each file it names and read it "
    "yourself; a git query that timed out may answer once the repository is idle"
)
# Formatted with `", ".join(profiles.shipped()) or "none"`: stayfixed's own listing.
PROFILE_NOT_SHIPPED_REMEDY = (
    "set [stayfixed] profile to a profile this stayfixed ships ({shipped}), or to an empty string"
)
# Each word spelled so this line is not one of the markers it searches for.
_MARKERS = "T[O]DO|F[I]XME|X[X]X"
_SUBJECT = re.compile(rf"^({COMMIT_TYPE_WORD})(\([^)]*\))?!?: ")
_ENV_KEEP = (".example", ".sample", ".template")
_CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")  # GitHub's order
_WORKFLOWS = ".github/workflows"
_UNOWNED = f"{_WORKFLOWS}/"
# What reading a file the repository wrote can raise: a path through a symlink, a file that
# cannot be opened, bytes that are not UTF-8 (a `ValueError`), and a settings document the engine
# refuses, JSON nested past the parser's depth included (`scaffold.ParserLimitError`).
_UNREADABLE = (PathEscape, OSError, ValueError, EntriesError)


@dataclass(frozen=True)
class ProbeContext:
    root: Path
    config: Config
    window: int  # how many commits `commit-types` reads


@dataclass(frozen=True)
class Looked:
    where: tuple[str, ...] = ()  # what was found
    unread: tuple[str, ...] = ()  # what could not be looked at


@dataclass(frozen=True)
class Probe:
    id: str
    principle: int | None
    severity: Severity
    remedy: str
    run: Callable[[ProbeContext], Looked]


def _git(context: ProbeContext, *args: str, answers: tuple[int, ...] = (0,)) -> str | None:
    """Standard output, or `None` when git's exit is not one of `answers` (a timeout is -1)."""
    code, out = git_run(context.root, *args, timeout=QUERY_TIMEOUT_SECONDS)
    return out if code in answers else None


def _head(context: ProbeContext) -> str | None:
    """`HEAD`'s sha, `""` in a repository with no commit, `None` when git cannot answer."""
    out = _git(context, "rev-parse", "--verify", "--quiet", "HEAD", answers=(0, 1))
    return None if out is None else out.strip()


def _names(out: str) -> list[str]:
    """NUL-terminated names, the empty tail dropped."""
    return [name for name in out.split("\0") if name]


def _code_roots(context: ProbeContext) -> Looked:
    """Each `[ledger] code_roots` entry `dropped_roots` names, through `clipped`: almost every one,
    `.` and `..` among them, lies outside the path grammar, where `printable` withholds them all."""
    config = context.config
    preset = preset_defaults(config.project.name, preset=config.stayfixed.preset).ledger.code_roots
    dropped = dropped_roots(context.root, config, defaults=preset)
    return Looked(tuple(f"{clipped(entry)}: {reason}" for entry, reason in dropped))


def _todo_markers(context: ProbeContext) -> Looked:
    """Files under the code roots that carry a marker as a word. `-z` so a name git would quote
    is never read as the quoted form."""
    roots = [
        path.relative_to(context.root).as_posix()
        for path in contained_roots(context.root, context.config)
    ]
    if not roots:
        return Looked()
    out = _git(
        context, "grep", "-I", "-l", "-z", "-w", "-E", _MARKERS, "--", *roots, answers=(0, 1)
    )
    if out is None:
        return Looked(unread=("git grep",))
    return Looked(tuple(sorted(_names(out))))


def _tracked_env(context: ProbeContext) -> Looked:
    out = _git(context, "ls-files", "-z")
    if out is None:
        return Looked(unread=("git ls-files",))
    return Looked(
        tuple(
            sorted(
                name
                for name in _names(out)
                if (base := PurePosixPath(name).name) == ".env"
                or (base.startswith(".env.") and not base.endswith(_ENV_KEEP))
            )
        )
    )


def _memory_history(context: ProbeContext) -> Looked:
    if context.config.memory.mode == IN_REPO_MODE:
        return Looked()  # the store is meant to be committed
    # Every ref, not `HEAD`'s history: notes committed on one branch are readable from a clone
    # checked out on an orphan one. With no commit anywhere git answers 0 and prints nothing.
    store = context.config.paths.memory
    out = _git(context, "log", "--all", "--format=%H", "-1", "--", store)
    if out is None:
        return Looked(unread=("git log",))
    return Looked((store,) if out.strip() else ())


def _foreign_hooks(context: ProbeContext) -> Looked:
    """Committed settings files of the selected harnesses that hold any hook entry, read by
    `scaffold.judged_entries`, lenient for the files a harness was measured running partly
    malformed. Every way repository content can make reading fail is "could not look", and so is
    a part of the file the walk skipped that could hold a command. The file is decoded strictly,
    so a byte that is not UTF-8 is "could not look" too.

    **An entry claiming stayfixed's marker is foreign here too.** stayfixed writes no hook entry
    into a committed settings file -- `attach` merges into the one a repository keeps out of git --
    so a marker in a committed file is the repository's word alone, and the walk does not read
    one."""
    from stayfixed.harnesses import LENIENT_SETTINGS, select

    harnesses, _ = select(context.config.stayfixed.agents)
    found: list[str] = []
    unread: list[str] = []
    for relative in sorted({s for h in harnesses for s in h.settings}):
        try:
            path = contained(context.root, relative)
            # To the read cap: a committed file past it is one this probe could not look at,
            # never one read to its end.
            text = read_regular_text(path) if fsops.is_file(path) else ""
            # Raises `EntriesError` for a shape the walk cannot read.
            walked = judged_entries(text, lenient=relative in LENIENT_SETTINGS)
        except _UNREADABLE:
            unread.append(relative)
            continue
        if walked.partly:
            unread.append(relative)
        if walked.entries:
            found.append(relative)
    return Looked(tuple(found), tuple(unread))


def _foreign_workflows(context: ProbeContext) -> Looked:
    from stayfixed.project.api import CI_WORKFLOW

    own = PurePosixPath(CI_WORKFLOW).name
    try:
        directory = contained(context.root, _WORKFLOWS)
        names = sorted(
            p.name
            for pattern in ("*.yml", "*.yaml")
            for p in directory.glob(pattern)
            if p.name != own
        )
    except (PathEscape, OSError):
        return Looked(unread=(_WORKFLOWS,))
    return Looked(tuple(f"{_WORKFLOWS}/{name}" for name in names))


# GitHub does not load a code-owners file of 3 MB or more. Decimal megabytes: of the two
# readings it is the smaller bound, so a file between them is read as naming no `.github`.
CODEOWNERS_MAX_BYTES = 3_000_000


def _exact_file(path: Path) -> bool:
    """A file under exactly this name: a case-folding filesystem answers `is_file()` for
    `codeowners` when asked for `CODEOWNERS`, and GitHub reads only the exact name."""
    return fsops.is_file(path) and path.name in os.listdir(path.parent)


def _codeowners(context: ProbeContext) -> Looked:
    """Whether the code-owners file GitHub reads, the first of `_CODEOWNERS` under its exact
    name, has a line that is not a comment naming `.github`: a substring, not GitHub's matching."""
    if context.config.ci.mode == "none":
        return Looked()  # stayfixed renders no workflow to protect
    for relative in _CODEOWNERS:
        try:
            path = contained(context.root, relative)
            if not _exact_file(path):
                continue
            # Read to one byte under GitHub's limit, and a file that has that byte is one GitHub
            # does not load; a regular file only, so no committed link reads on past it.
            content, over = read_bounded(path, CODEOWNERS_MAX_BYTES - 1)
            lines = [] if over else content.decode("utf-8").splitlines()
        except (PathEscape, OSError, ValueError):
            return Looked(unread=(relative,))
        named = any(".github" in line for line in lines if not line.lstrip().startswith("#"))
        return Looked() if named else Looked((_UNOWNED,))
    return Looked((_UNOWNED,))


def _commit_types(context: ProbeContext) -> Looked:
    """Shas of the last `window` commits whose subject's type is outside the vocabulary. The
    records are NUL-delimited and paired by position, as the commit gate reads them: a subject
    may carry any byte but NUL, and nothing from one lands in `where`."""
    head = _head(context)
    if head is None:
        return Looked(unread=("git rev-parse",))
    if not head:
        return Looked()  # no commit yet
    out = _git(context, "log", "--no-merges", "-z", f"-n{context.window}", "--format=%H%x00%s")
    if out is None:
        return Looked(unread=("git log",))
    fields = out.split("\0")
    allowed = set(context.config.commit_messages.types)
    return Looked(
        tuple(
            fields[i]
            for i in range(0, len(fields) - 1, 2)
            if (m := _SUBJECT.match(fields[i + 1])) is None or m.group(1) not in allowed
        )
    )


PROBES: tuple[Probe, ...] = (
    Probe(
        "code-roots",
        None,
        Severity.ADVICE,
        "name each code root as a directory inside the repository that no link leads through, "
        "such as `src`: no check walks an entry named here",
        _code_roots,
    ),
    Probe(
        "todo-markers",
        1,
        Severity.ADVICE,
        "file each marker that is a real defect with `stayfixed bugs new`, and delete the rest",
        _todo_markers,
    ),
    Probe(
        "tracked-env",
        None,
        Severity.WARNING,
        "remove the file from the index with `git rm --cached`, and rotate what it held",
        _tracked_env,
    ),
    Probe(
        "memory-history",
        8,
        Severity.WARNING,
        "notes committed to history stay readable in every clone; keep the store out of git",
        _memory_history,
    ),
    Probe(
        "foreign-hooks",
        5,
        Severity.ADVICE,
        "committed hooks run without a trust prompt in non-interactive sessions; keep only those "
        "you would run on every clone",
        _foreign_hooks,
    ),
    Probe(
        "foreign-workflows",
        None,
        Severity.ADVICE,
        "stayfixed's workflow runs beside these; nothing needs changing unless one repeats a gate",
        _foreign_workflows,
    ),
    Probe(
        "codeowners",
        7,
        Severity.ADVICE,
        "add a CODEOWNERS line covering /.github/ and require code-owner review on the gate "
        "branch: a pull request can otherwise rewrite the workflow that judges it",
        _codeowners,
    ),
    Probe(
        "commit-types",
        None,
        Severity.ADVICE,
        "write subjects as `<type>: <intent>`, or `<type>(<area>): <intent>`, with a type from "
        "[commit_messages] types",
        _commit_types,
    ),
)


def _could_not_look(probe: str, principle: int | None, unread: tuple[str, ...]) -> Item:
    return item(probe, COULD_NOT_LOOK, principle, Severity.WARNING, COULD_NOT_LOOK_REMEDY, unread)


def _profile_items(context: ProbeContext) -> list[Item]:
    """One item per failed check of the configured profile, at the check's own level.

    An empty `[stayfixed] profile` is no profile and runs nothing. A name this build does not
    ship is one warning and the rest of the inventory still runs; a shipped profile that does
    not parse stays `ProfileError`, because that is a defect in the build. A `tracked` check git
    gave no answer for is "could not look", never an untracked file.
    """
    name = context.config.stayfixed.profile
    if not name:
        return []
    from stayfixed import profiles

    shipped = profiles.shipped()
    if name not in shipped:
        remedy = PROFILE_NOT_SHIPPED_REMEDY.format(shipped=", ".join(shipped) or "none")
        return [
            item(
                PROFILE,
                PROFILE_NOT_SHIPPED,
                None,
                Severity.WARNING,
                remedy,
                ["[stayfixed] profile"],
            )
        ]
    items: list[Item] = []
    unanswered: dict[str, None] = {}
    for outcome in profiles.evaluate(profiles.load_profile(name), context.root):
        check = outcome.check
        if outcome.located:
            items.append(
                item(PROFILE, check.id, None, check.level, check.remedy, outcome.located, count=1)
            )
        unanswered.update(dict.fromkeys(outcome.unanswered))
    if unanswered:
        items.append(_could_not_look(PROFILE, None, tuple(unanswered)))
    return items


def run_probes(context: ProbeContext) -> list[Item]:
    """Every probe's items in `PROBES` order, then the profile's: per probe, what it found (the
    probe's id is the rule) and one `could-not-look` item for what it could not read."""
    items: list[Item] = []
    for probe in PROBES:
        looked = probe.run(context)
        if looked.where:
            items.append(
                item(
                    probe.id,
                    probe.id,
                    principle=probe.principle,
                    severity=probe.severity,
                    remedy=probe.remedy,
                    where=looked.where,
                )
            )
        if looked.unread:
            items.append(_could_not_look(probe.id, probe.principle, looked.unread))
    return items + _profile_items(context)
