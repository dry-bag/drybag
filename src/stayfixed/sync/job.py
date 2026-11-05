"""The note sync's job: commit the overlay's notes, take in upstream's, push its own.

Each step is bounded in time and records what it did in the context the job's state is written
from: guard; commit the changed notes by `git commit --only`; fetch `origin main` into the job's
own ref; integrate that sha, only when everything it brings is memory, by replay; push the checked
range. A project's `MEMORY.md` is never among them: each machine renders its own (`sync.rules`).

It never writes a non-memory path of the working tree or the real index, stashes, rebases, pulls
or force-pushes. git does every write: `git commit --only` moves `main` and the real index for the
notes it commits, and an integration has `git read-tree -m -u` write the incoming notes and the
index before `main` moves by compare-and-swap, so a job killed anywhere leaves a state the next
job converges from, with nothing recorded.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path

from stayfixed import fsops
from stayfixed.config.overlay import overlay_root
from stayfixed.gitenv import answer_bytes
from stayfixed.sync import scan
from stayfixed.sync.git import (
    JOB_SETTINGS,
    UNMERGED,
    GitError,
    GitTimeout,
    Ran,
    checked,
    git,
    guard,
    timed,
    with_config,
)
from stayfixed.sync.rules import (
    RawEntry,
    commit_entries,
    diff_entries,
    entry_offends,
    memory_path,
    range_is_memory_only,
    status,
    unsafe_parent,
)
from stayfixed.sync.state import (
    EMPTY_HOLDS,
    LOCAL_REWRITE,
    LOCK_FILE,
    OUTSIDE,
    PENDING_FILE,
    REWRITTEN,
    SCRATCH,
    SLEEPER_LOCK_FILE,
    THROTTLE_SECONDS,
    UNREADABLE,
    Holds,
    Lock,
    Outcome,
    StateUnreadable,
    SyncState,
    full_sha,
    iso,
    mark_pending,
    notes_mark,
    parse_time,
    read_state,
    state_directory,
    take_pending,
    write_state,
)
from stayfixed.sync.switch import enabled

SWAP_MESSAGE = "stayfixed note sync"


@dataclass(frozen=True)
class Limits:
    """Wall-clock limits in seconds, each a named cap no shipped file states: the network calls,
    both commit checks together, both push scans together, the whole job, and any other single
    git call. Injectable, so a test can wait one second where the job waits sixty."""

    fetch: float = 30.0
    push: float = 30.0
    checks: float = 60.0
    job: float = 180.0
    local: float = 30.0


class JobTimeout(Exception):
    """The whole job ran out of time; the job records `timeout` with this message."""


class JobStopped(Exception):
    """A step ended the job with this outcome from deep inside (a signing failure in a replay)."""

    def __init__(self, outcome: Outcome) -> None:
        super().__init__(outcome.state)
        self.outcome = outcome


@dataclass
class JobContext:
    """What one job run carries between its steps. `remarks` are what the end's detail also says
    (a hold and how to review it); `notices` the ends that do not stop the job (a failed commit
    check, a note left out for a secret); `refused` the memory-named paths left out of a commit
    because they are not notes;
    `holds` as this job leaves them, changed only by integration and push; `last_head` the `HEAD`
    the last job left."""

    overlay: Path
    state_dir: Path
    home: Path
    host: str
    now: Callable[[], datetime]
    limits: Limits = field(default_factory=Limits)
    deadline: float | None = None
    remarks: list[str] = field(default_factory=list)
    notices: list[Outcome] = field(default_factory=list)
    fetched_sha: str | None = None
    dirty: str | None = None
    refused: list[str] = field(default_factory=list)
    holds: Holds = EMPTY_HOLDS
    last_head: str | None = None

    def limit(self, step: float) -> float:
        """`step`, cut to what is left of the whole job; `JobTimeout` when nothing is."""
        if self.deadline is None:
            return step
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise JobTimeout(f"the job did not finish within {self.limits.job:g} s")
        return min(step, left)

    @cached_property
    def scanner(self) -> Path | None:
        """The `gitleaks` on `PATH` (`scan.gitleaks`), looked up once for this job."""
        return scan.gitleaks()

    @property
    def env(self) -> Mapping[str, str]:
        """What every git call of the job is given (`sync.git.JOB_SETTINGS`); it asks nothing."""
        return JOB_SETTINGS


def _outcome(ctx: JobContext, state: str, detail: str | None = None) -> Outcome:
    return Outcome(state, iso(ctx.now()), detail)


def _git(
    ctx: JobContext,
    *args: str,
    timeout: float | None = None,
    index_file: Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin: bytes | None = None,
) -> Ran:
    return git(
        ctx.overlay,
        *args,
        timeout=ctx.limit(ctx.limits.local if timeout is None else timeout),
        env={**ctx.env, **(env or {})},
        index_file=index_file,
        stdin=stdin,
    )


def _ok(
    ctx: JobContext, *args: str, index_file: Path | None = None, stdin: bytes | None = None
) -> str:
    """`git <args>` that must succeed; its standard output."""
    return checked(_git(ctx, *args, index_file=index_file, stdin=stdin), f"git {args[0]}").out


def _nul(text: str) -> list[str]:
    return [item for item in text.split("\0") if item]


def _rev(ctx: JobContext, rev: str) -> str:
    return _ok(ctx, "rev-parse", "--verify", "-q", "--end-of-options", f"{rev}^{{commit}}").strip()


def _paths_in(paths: Iterable[str]) -> bytes:
    """`paths` NUL-terminated, for a git command reading them from standard input."""
    return b"".join(path.encode("utf-8", "surrogateescape") + b"\0" for path in paths)


@contextlib.contextmanager
def _scratch(ctx: JobContext) -> Iterator[Path]:
    """The job's one scratch directory, `scratch/` in the state directory: emptied for one use (a
    scan, a commit's message, a readability check's index), removed whole after it, never two uses
    at once. A fixed name, so a killed job's leftovers are removed by the next."""
    directory = ctx.state_dir / SCRATCH
    ctx.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(mode=0o700)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# -- the commit, by `git commit --only` ------------------------------------------------------------

# How the job hands git a list of paths: NUL-separated on standard input, each matched literally.
_FROM_STDIN = ("--pathspec-from-file=-", "--pathspec-file-nul")
_LITERAL = {"GIT_LITERAL_PATHSPECS": "1"}


def _refuse(ctx: JobContext, paths: Iterable[str]) -> None:
    """Name `paths` as left out of the commit; the job goes on, and its end names them."""
    ctx.refused.extend(path for path in paths if path not in ctx.refused)


def _message(ctx: JobContext, paths: list[str]) -> bytes:
    parsed = [entry for entry in map(memory_path, paths) if entry is not None]
    scopes = "\n".join(sorted({entry.root.rpartition("/")[0] for entry in parsed}))
    return f"memory: {len(parsed)} notes from {ctx.host}\n\n{scopes}\n".encode()


def _signing(ctx: JobContext) -> bool:
    """Whether `commit.gpgsign` asks for a signature; a timed-out answer is never "no"."""
    answer = timed(_git(ctx, "config", "--type=bool", "--get", "commit.gpgsign"), "git config")
    return answer.code == 0 and answer.out.strip() == "true"


def _unsigned(ctx: JobContext, result: Ran) -> Outcome:
    """`signing_failed` for a commit git could not sign, with git's words."""
    said = scan.first_lines(result.err) or ("waited for a passphrase" if result.timed_out else "")
    return _outcome(ctx, "signing_failed", f"commit.gpgsign is set and signing failed: {said}")


def _commit_tree(
    ctx: JobContext,
    tree: str,
    parents: list[str],
    message: bytes,
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, Outcome | None]:
    """`git commit-tree` with `message` on standard input, signed when `commit.gpgsign` says so:
    the sha, or `signing_failed`. Signing asked for is never switched off."""
    signed = ("-S",) if _signing(ctx) else ()
    parented = tuple(part for parent in parents for part in ("-p", parent))
    result = _git(
        ctx, "commit-tree", *parented, *signed, "--end-of-options", tree, env=env, stdin=message
    )
    if signed and (result.timed_out or result.code != 0):
        return None, _unsigned(ctx, result)
    return checked(result, "git commit-tree").out.strip(), None


def _swap(ctx: JobContext, new: str, old: str) -> bool:
    """Move `main` from `old` to `new` only if it is still at `old`."""
    result = _git(
        ctx, "update-ref", "-m", SWAP_MESSAGE, "--end-of-options", "refs/heads/main", new, old
    )
    return timed(result, "git update-ref").code == 0


def _unmerged_now(ctx: JobContext) -> Outcome | None:
    """`skipped` when the real index holds unmerged entries now, asked right before the commit and
    every move of `main`: a `stash pop` that conflicts while the job runs leaves notes holding
    conflict markers, which `git commit --only` carries when it lists them, and commits beside."""
    found = timed(_git(ctx, "ls-files", "--unmerged", "-z"), "git ls-files")
    if found.code != 0 or found.out:
        return _outcome(ctx, "skipped", UNMERGED)
    return None


def _committed_rules(ctx: JobContext) -> bytes | None:
    """`HEAD`'s `.gitleaks.toml`, or `None` when it commits none: never what the working tree
    holds now. `None` only makes the scan stricter (gitleaks' defaults)."""
    found = timed(
        _git(ctx, "cat-file", "blob", "--end-of-options", f"HEAD:{scan.RULES}"), "git cat-file"
    )
    return answer_bytes(found.out) if found.code == 0 else None


def _objects(ctx: JobContext, names: list[str]) -> list[bytes]:
    """Each object `names` lists, raw, in order, from one `git cat-file --batch`: no filter, no
    textconv and no replace ref (`JOB_SETTINGS`) stands between git's bytes and the scan."""
    asked = "".join(f"{name}\n" for name in names).encode()
    out = answer_bytes(_ok(ctx, "cat-file", "--batch", stdin=asked))
    found: list[bytes] = []
    at = 0
    for name in names:
        end = out.find(b"\n", at)
        header = out[at:end].split(b" ") if end >= 0 else []
        if len(header) != 3 or not header[2].isdigit():
            raise GitError(f"git cat-file --batch: no object {name}")
        found.append(out[end + 1 : end + 1 + int(header[2])])
        at = end + 2 + int(header[2])
    return found


def _run_checks(
    ctx: JobContext, scratch: Path, paths: list[str]
) -> tuple[Outcome | None, tuple[str, ...]]:
    """The secret scan of the working-tree bytes of the notes `paths` names, before the commit:
    the failure that keeps every note out, or the `secret_found` notice and the notes it names."""
    binary = ctx.scanner
    if binary is None:
        return _outcome(ctx, "scan_unavailable", scan.NO_SCANNER), ()
    try:
        items = [(path, fsops.read_regular_bytes(ctx.overlay / path)) for path in paths]
    except OSError as error:
        detail = f"gitleaks: a note cannot be read: {fsops.said(error)}"
        return _outcome(ctx, "hook_failed", detail), ()
    result = scan.scan(items, binary, _committed_rules(ctx), ctx.limit(ctx.limits.checks), scratch)
    if result.found:
        remedy = f"remove the secret from {', '.join(result.found)}; the next job commits it"
        return _outcome(ctx, "secret_found", f"{remedy}\n{result.detail}"), result.found
    if result.ok:
        return None, ()
    state = "timeout" if result.timed_out else "hook_failed"
    return _outcome(ctx, state, f"gitleaks: {result.detail}"), ()


def _locked(ctx: JobContext, result: Ran) -> Ran:
    """`result`, or the stop `raced` when git names `index.lock`: another git holds the real
    index, or one killed mid-write left the lock. The job cannot tell which, so it never removes
    it, and says git's words."""
    if "index.lock" in result.err:
        said = scan.first_lines(result.err).splitlines()[0]
        raise JobStopped(_outcome(ctx, "raced", f"{said}; the next job retries"))
    return result


def _drop(ctx: JobContext, paths: list[str]) -> None:
    """Remove the intent-to-add entries `git add -N` made for `paths` again, and only those: a
    deletion the owner staged at such a path stays staged."""
    if paths:
        removed = _git(
            ctx, "update-index", "--force-remove", "-z", "--stdin", stdin=_paths_in(paths)
        )
        checked(_locked(ctx, removed), "git update-index")


def _commit(ctx: JobContext, scratch: Path, paths: list[str]) -> None:
    """`git commit --only` of exactly `paths`, its message a file in `scratch`: git writes the
    commit, moves `main` and updates the real index for those paths alone, signed as
    `commit.gpgsign` says. A failure is a notice, `signing_failed` or `hook_failed` with git's
    words; a locked index stops the job (`_locked`)."""
    message = scratch / "message"
    message.write_bytes(_message(ctx, paths))
    result = _locked(
        ctx,
        _git(
            ctx, "commit", "--only", "-q", "-F", str(message), *_FROM_STDIN, env=_LITERAL,
            stdin=_paths_in(paths),
        ),
    )  # fmt: skip
    if result.code == 0 and not result.timed_out:
        return
    if _signing(ctx):
        ctx.notices.append(_unsigned(ctx, result))
        return
    said = scan.first_lines(timed(result, "git commit").err) or f"exit {result.code}"
    ctx.notices.append(_outcome(ctx, "hook_failed", f"job: git commit failed: {said}"))


def commit_memory(ctx: JobContext) -> Outcome | None:
    """Commit every changed note by `git commit --only` of exactly those, with no hook; the
    outcome that stops the job (`raced`, `skipped`, `timeout`), or `None`.

    The status's dirty paths are the candidates. One that is not a note by name, or that a link or
    a file stands above (git would read it through the link), is left out and named (`_refuse`). A
    new one is added intent-to-add, so that `git diff HEAD` judges what git would record from the
    working tree for each: one that may not move (`entry_offends`) is left out and named, and so
    is one the scan finds a secret in, in a `secret_found` notice; the intent-to-add entry of a
    note left out is removed again. A failed scan, no scanner or a failed signature keeps every
    note out and does not stop the job: what is already committed still integrates and pushes.
    """
    found = status(ctx.overlay, timeout=ctx.limit(ctx.limits.local), env=ctx.env)
    ctx.dirty = notes_mark(ctx.overlay, found.paths)  # what a trigger finds unchanged if this fails
    notes: list[str] = []
    for path in found.paths:
        link, parsed = unsafe_parent(ctx.overlay, path), memory_path(path)
        if link is not None or parsed is None or not parsed.is_note:
            _refuse(ctx, [link or path.rstrip("/")])
        else:
            notes.append(path)
    if not notes:
        return None
    added = [path for path in notes if path in found.untracked]
    if added:
        intent = _git(ctx, "add", "-N", *_FROM_STDIN, env=_LITERAL, stdin=_paths_in(added))
        checked(_locked(ctx, intent), "git add")
    limit = ctx.limit(ctx.limits.local)
    entries = diff_entries(ctx.overlay, "HEAD", paths=notes, timeout=limit, env=ctx.env)
    _refuse(ctx, [entry.path for entry in entries if entry_offends(entry)])
    kept = [entry for entry in entries if not entry_offends(entry)]
    with _scratch(ctx) as scratch:
        said, secret = _run_checks(ctx, scratch, [each.path for each in kept if each.status != "D"])
        stops_all = said is not None and not secret
        paths = [] if stops_all else [each.path for each in kept if each.path not in secret]
        _drop(ctx, [path for path in added if path not in paths])
        if said is not None and said.state == "timeout":
            return said  # what is left of the job's time is not enough to go on
        ctx.notices.extend([said] if said is not None else [])
        if not paths:
            return None
        unmerged = _unmerged_now(ctx)
        if unmerged is None:
            _commit(ctx, scratch, paths)
    return unmerged


# -- fetch ----------------------------------------------------------------------------------------

# What git and ssh print when the remote cannot be reached, and when it refuses who we are; the
# second is matched first, since an HTTPS refusal also says "unable to access".
_OFFLINE = (
    "could not resolve host", "could not resolve hostname", "network is unreachable",
    "no route to host", "connection refused", "connection timed out", "operation timed out",
    "connection reset", "temporary failure in name resolution", "connection closed by",
    "unable to access",
)  # fmt: skip
_AUTH = (
    "permission denied", "authentication failed", "could not read username",
    "could not read password", "host key verification failed", "terminal prompts disabled",
    "invalid username or password", "returned error: 401", "returned error: 403",
)  # fmt: skip
FETCHED_REF = "refs/stayfixed/fetched"


def _remote_failure(ctx: JobContext, result: Ran, what: str, limit: float) -> Outcome:
    """`timeout`, `auth_failed`, `offline`, or `hook_failed` naming the job, for a network call."""
    said = scan.first_lines(result.err) or scan.first_lines(result.out) or f"exit {result.code}"
    if result.timed_out:
        return _outcome(ctx, "timeout", f"{what} did not finish within {limit:g} s")
    text = result.err.lower()
    if any(pattern in text for pattern in _AUTH):
        return _outcome(ctx, "auth_failed", f"{what}: {said}")
    if any(pattern in text for pattern in _OFFLINE):
        return _outcome(ctx, "offline", f"{what}: {said}")
    return _outcome(ctx, "hook_failed", f"job: {what} failed: {said}")


def fetch(ctx: JobContext) -> tuple[str | None, Outcome | None]:
    """`git fetch origin main` into the job's own ref; the fetched sha, or the failure.

    The sha is read once, here, from that ref, never `FETCH_HEAD`, which the owner's own fetch
    rewrites at any moment: a second pusher, or the owner's fetch, changes nothing this job
    integrates. Every object received is checked (`fetch.fsckObjects`), so a tree holding a `..`
    or `.git` name is refused before any rule reads it. No tag, no submodule.
    """
    limit = ctx.limit(ctx.limits.fetch)
    result = _git(
        ctx, "-c", "fetch.fsckObjects=true", "fetch", "--no-tags", "--no-recurse-submodules",
        "origin", f"+refs/heads/main:{FETCHED_REF}", timeout=limit,
    )  # fmt: skip
    if result.timed_out or result.code != 0:
        return None, _remote_failure(ctx, result, "git fetch origin main", limit)
    return _rev(ctx, FETCHED_REF), None


# -- integrate by replay ---------------------------------------------------------------------------

# How the owner takes a held range or integrates a fetched sha by hand: read all of it, memory
# included, and take it at the sha that was held and read, never at `origin/main`, which the next
# fetch moves past it. A rebase rather than a fast-forward, since the notes committed here usually
# sit beside the held sha; with none, it is a fast-forward.
REVIEW = "git log -p --no-renames HEAD..{sha}, then git rebase {sha}"
# How the owner settles a rewritten upstream {sha}: read what this overlay has that it dropped,
# then take the rewrite or undo it.
REWRITE = (
    "git log -p {sha}..HEAD, then git rebase -i {sha} dropping them to take the rewrite, or git "
    "rebase {sha} and a push to undo it"
)
# How the owner settles a rewrite here of notes upstream {sha} still has: keep it, or undo it.
LOCAL_REVIEW = (
    "to keep the rewrite, `git push --force-with-lease=refs/heads/main:{sha} origin main` by "
    "hand; to undo it, `git rebase {sha}`"
)
# How the owner reads an upstream {sha} git will not check out, which only upstream can repair.
UNREADABLE_REVIEW = "git diff --stat HEAD {sha}, then repair upstream"
_AUTHOR = re.compile(r"author (.*) <([^<>]*)> (\d+ [+-]\d{4})")


def _original(ctx: JobContext, commit: str) -> tuple[dict[str, str], bytes]:
    """`commit`'s author, as the environment that names it, and its message as bytes, its
    `encoding` header given back as a `git -c`-style entry: from the commit object itself, never
    `git log --format`, which `log.showSignature` prefixes with the signature check."""
    raw = _ok(ctx, "cat-file", "commit", "--end-of-options", commit)
    header, _, message = raw.encode("utf-8", "surrogateescape").partition(b"\n\n")
    env: dict[str, str] = {}
    for line in header.decode("utf-8", "surrogateescape").split("\n"):
        if (author := _AUTHOR.fullmatch(line)) is not None:
            name, email, date = author.groups()
            env.update(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_DATE=date)
        elif line.startswith("encoding "):
            env.update(
                with_config(ctx.env, {"i18n.commitEncoding": line.removeprefix("encoding ")})
            )
    if "GIT_AUTHOR_NAME" not in env:
        raise GitError(f"commit {commit} has no readable author line")
    return env, message


def replay(ctx: JobContext, onto: str, commits: list[str]) -> tuple[str | None, list[str]]:
    """Replay `commits` (oldest first) onto `onto`: the new tip, or `None` and the paths that
    conflict. Each is `merge-tree --write-tree --merge-base=c^ tip c` and `commit-tree` with `c`'s
    author and message, so nothing touches the working tree or the real index. A failed signature
    stops the job (`JobStopped`)."""
    tip = onto
    for commit in commits:
        result = _git(
            ctx, "merge-tree", "--write-tree", "-z", "--name-only", "--no-messages",
            f"--merge-base={commit}^", "--end-of-options", tip, commit,
        )  # fmt: skip
        if timed(result, "git merge-tree").code not in (0, 1):
            checked(result, "git merge-tree")
        tree, *conflicted = _nul(result.out)
        if result.code == 1:
            return None, conflicted
        if tree == _tree_of(ctx, tip):
            continue  # already upstream: an empty commit would list no path, and be held
        author, message = _original(ctx, commit)
        new, failed = _commit_tree(ctx, tree, [tip], message, env=author)
        if failed is not None or new is None:
            raise JobStopped(failed or _outcome(ctx, "hook_failed", "job: no commit made"))
        tip = new
    return tip, []


def _tree_of(ctx: JobContext, rev: str) -> str:
    return _ok(ctx, "rev-parse", "--verify", "-q", "--end-of-options", f"{rev}^{{tree}}").strip()


def _hold_upstream(ctx: JobContext, why: str | None, names: Iterable[str], remark: str) -> None:
    """Hold upstream for `why` on `names`, with `remark`, which says how to review it; `why`
    `None`, with no names, clears the hold."""
    ctx.remarks.extend([remark] if remark else [])
    ctx.holds = replace(ctx.holds, upstream_paths=tuple(names), upstream_why=why)


def _missing(ctx: JobContext, rev: str | None, without: str) -> list[str]:
    """The commits `rev` has and `without` lacks, newest first; none when `rev` is no sha, or one
    git cannot find (pruned): nothing of it is in `without`."""
    if not full_sha(rev):
        return []
    found = _git(ctx, "rev-list", "-z", "--end-of-options", str(rev), f"^{without}")
    return _nul(found.out) if timed(found, "git rev-list").code == 0 else []


def _lost(
    ctx: JobContext, recorded: str | None, upstream: str, head: str, local: list[str]
) -> tuple[list[str], list[str]]:
    """What a rewrite on either side dropped. First, the commits of `local` (`upstream..HEAD`)
    that upstream once had: those of the sha the last job recorded as upstream's that `upstream`
    lost, and those a standing rewrite hold names. Second, the commits of `HEAD..upstream` that
    `HEAD` once had: those of the `HEAD` the last job left that `head` lost, and those a standing
    local-rewrite hold names. A first job, with nothing recorded, has neither."""

    def held(why: str) -> set[str]:
        return set(ctx.holds.upstream_paths) if ctx.holds.upstream_why == why else set()

    had = held(REWRITTEN) | set(_missing(ctx, recorded, upstream))
    gone = held(LOCAL_REWRITE) | set(_missing(ctx, ctx.last_head, head))
    incoming = _missing(ctx, upstream, head) if gone else []
    return [sha for sha in local if sha in had], [sha for sha in incoming if sha in gone]


def integrate(ctx: JobContext, upstream: str, recorded: str | None = None) -> Outcome | None:
    """Bring the checked sha `upstream` in, if `HEAD..upstream` is memory-only and so is every
    local commit; the outcome that stops the job, or `None`. `recorded` is the sha the last job
    recorded as upstream's.

    The upstream hold in `ctx.holds` is set or cleared here; the local hold is the push's, which
    judges the same local range: the owner's own commits are never rebuilt, so a local range
    outside memory leaves `HEAD` as it is.
    """
    head = _rev(ctx, "HEAD")
    local = _nul(_ok(ctx, "rev-list", "-z", "--reverse", "--end-of-options", f"{upstream}..{head}"))
    dropped, purged = _lost(ctx, recorded, upstream, head, local)
    # Recorded only once the rewrite check has judged it: a job stopped before then leaves the
    # last sha, so the next job still sees what upstream lost.
    ctx.fetched_sha = upstream
    if dropped:
        remark = (
            f"upstream was rewritten: it no longer has {', '.join(dropped)}, which this overlay "
            "still has; nothing is integrated or pushed until the owner settles it by hand: "
            + REWRITE.format(sha=upstream)
        )
        _hold_upstream(ctx, REWRITTEN, dropped, remark)
        return None
    if purged:
        remark = (
            f"main no longer has {', '.join(purged)}, which origin/main still has; nothing is "
            "integrated or pushed until the owner settles it by hand: "
            + LOCAL_REVIEW.format(sha=upstream)
        )
        _hold_upstream(ctx, LOCAL_REWRITE, purged, remark)
        return None
    if _is_ancestor(ctx, upstream, head):
        _hold_upstream(ctx, None, (), "")
        return None
    memory_only, offending = range_is_memory_only(
        ctx.overlay, head, upstream, timeout=ctx.limit(ctx.limits.local), env=ctx.env
    )
    if not memory_only:
        remark = (
            "upstream holds changes outside memory; nothing is integrated or pushed until they "
            f"are taken by hand. Review and take: {REVIEW.format(sha=upstream)}"
        )
        _hold_upstream(ctx, OUTSIDE, offending, remark)
        return None
    _hold_upstream(ctx, None, (), "")
    by_hand = f"integrate {upstream} by hand: {REVIEW.format(sha=upstream)}"
    owned = range_is_memory_only(
        ctx.overlay, upstream, head, timeout=ctx.limit(ctx.limits.local), env=ctx.env
    )[0]
    if not owned:
        ctx.remarks.append(
            f"upstream is not integrated past local commits outside memory; {by_hand}"
        )
        return None
    tip, conflicted = replay(ctx, upstream, local) if local else (upstream, [])
    if tip is None:
        detail = (
            f"a local commit conflicts with upstream on {', '.join(conflicted)}; main was not "
            f"moved. To {by_hand}"
        )
        return _outcome(ctx, "conflict", detail)
    incoming = _nul(
        _ok(ctx, "diff", "--no-renames", "--name-only", "-z", "--end-of-options", head, tip)
    )
    # A tree git will not put in an index is not an index to write: it is held, `main` unmoved,
    # since only upstream can repair it.
    with _scratch(ctx) as scratch:
        readable = _git(ctx, "read-tree", "--end-of-options", tip, index_file=scratch / "index")
    if timed(readable, "git read-tree").code != 0:
        remark = (
            f"upstream's tree cannot be checked out ({scan.first_lines(readable.err)}); nothing is "
            "integrated or pushed until upstream is repaired: "
            + UNREADABLE_REVIEW.format(sha=upstream)
        )
        _hold_upstream(ctx, UNREADABLE, incoming, remark)
        return None
    unmerged = _unmerged_now(ctx)
    if unmerged is not None:
        return unmerged
    # git writes the incoming notes and the index first, refusing before it writes anything a
    # note changed here, an untracked file or a link in the way; only then does `main` move. A
    # kill between the two leaves the notes staged on the old `main`, which the next job commits
    # and finds upstream already (`replay`). The refresh is `read-tree -u`'s own precondition: a
    # note rewritten byte for byte would otherwise read as changed here.
    checked(_locked(ctx, _git(ctx, "update-index", "-q", "--refresh")), "git update-index")
    written = _locked(ctx, _git(ctx, "read-tree", "-m", "-u", "--end-of-options", head, tip))
    if timed(written, "git read-tree").code != 0:
        said = (scan.first_lines(written.err).splitlines() or [f"exit {written.code}"])[0]
        detail = (
            f"the incoming notes cannot be written here ({said}); the next job commits a note "
            "changed here first, and anything else in the way is yours to move"
        )
        return _outcome(ctx, "waiting_clean_tree", detail)
    if not _swap(ctx, tip, head):
        detail = "main moved meanwhile; the incoming notes are written, and the next job converges"
        return _outcome(ctx, "raced", detail)
    return None


# -- push the checked range -----------------------------------------------------------------------

REMEDY = (
    "rewrite this commit locally: `git rebase -i {sha}^` and edit it; the job pushes the "
    "rewritten range"
)


def _before_push() -> None:
    """Nothing; the moment between the range's checks and its push (a test seam)."""


def _scan_push(ctx: JobContext, commits: list[tuple[str, list[RawEntry]]]) -> Outcome | None:
    """The content scan of what the push of `commits` sends, within `Limits.checks`: each commit's
    metadata -- the commit object whole, every header and the message, and the name of every path
    -- and every blob it adds or changes, read by one `git cat-file --batch`; the failure, if any.
    A finding is `secret_found`, its detail opening with the rewrite from the oldest commit found,
    which takes every newer one with it."""
    binary = ctx.scanner
    if binary is None:
        return _outcome(ctx, "scan_unavailable", scan.NO_SCANNER)
    added = [(sha, each) for sha, entries in commits for each in entries if each.status != "D"]
    objects = iter(_objects(ctx, [sha for sha, _ in commits] + [each.blob for _, each in added]))
    items = [
        (sha, b"\n".join([next(objects).rstrip(b"\n"), *(answer_bytes(e.path) for e in entries)]))
        for sha, entries in commits
    ]
    items += [(f"{sha} {each.path}", next(objects)) for sha, each in added]
    with _scratch(ctx) as scratch:
        limit = ctx.limit(ctx.limits.checks)
        result = scan.scan(items, binary, _committed_rules(ctx), limit, scratch)
    if result.timed_out:
        return _outcome(ctx, "timeout", f"gitleaks: {result.detail}")
    if result.ok:
        return None
    named = {label.split(" ", 1)[0] for label in result.found}
    oldest = next((sha for sha, _ in reversed(commits) if sha in named), None)
    if oldest is None:  # a failed scan, not a finding
        return _outcome(ctx, "hook_failed", f"gitleaks: {result.detail}")
    return _outcome(ctx, "secret_found", f"{REMEDY.format(sha=oldest)}\n{result.detail}")


def push(ctx: JobContext, upstream: str) -> Outcome | None:
    """Push `upstream..H`, `H` the sha checked here and never `main`, if it is memory-only; the
    outcome that stops the job, or `None`.

    The local range is judged even when an upstream hold skips the push, so both holds are
    recorded at once; one that is not memory-only is a local hold naming its commits. Every byte
    pushed is scanned first. Never forced, and no tag follows.
    """
    tip = _rev(ctx, "HEAD")
    if _is_ancestor(ctx, tip, upstream):
        ctx.holds = replace(ctx.holds, local_commits=())
        return None
    listed = commit_entries(
        ctx.overlay, f"{upstream}..{tip}", timeout=ctx.limit(ctx.limits.local), env=ctx.env
    )
    pushable, offending = range_is_memory_only(
        ctx.overlay, upstream, tip, timeout=ctx.limit(ctx.limits.local), env=ctx.env,
        commits=listed,
    )  # fmt: skip
    if not pushable:
        held = [
            sha
            for sha, entries in listed
            if not entries or any(entry_offends(entry) for entry in entries)
        ] or offending
        ctx.remarks.append(
            "local commits outside memory are not pushed; push them by hand when reviewed: "
            + ", ".join(held)
        )
        ctx.holds = replace(ctx.holds, local_commits=tuple(held))
        return None
    ctx.holds = replace(ctx.holds, local_commits=())
    if ctx.holds.upstream_paths:
        ctx.remarks.append("not pushed while upstream is held")
        return None
    failed = _scan_push(ctx, listed)
    if failed is not None:
        return failed
    _before_push()
    limit = ctx.limit(ctx.limits.push)
    result = _git(
        ctx, "push", "--porcelain", "--no-follow-tags", "origin", f"{tip}:refs/heads/main",
        timeout=limit,
    )  # fmt: skip
    if result.code == 0 and not result.timed_out:
        ctx.fetched_sha = tip  # what upstream now has: the next job's rewrite check starts here
        return None
    said = (result.out + result.err).lower()
    if not result.timed_out and any(
        word in said for word in ("[rejected]", "fetch first", "non-fast-forward")
    ):
        detail = "origin/main moved before the push; the next trigger fetches and retries"
        return _outcome(ctx, "rejected", detail)
    return _remote_failure(ctx, result, "git push origin", limit)


def _is_ancestor(ctx: JobContext, ancestor: str, rev: str) -> bool:
    result = _git(ctx, "merge-base", "--is-ancestor", "--end-of-options", ancestor, rev)
    return timed(result, "git merge-base").code == 0


# -- the job's end, its run loop and its entry point ----------------------------------------------

# Named caps, no shipped file states them: how many rounds a running job adds for triggers that
# arrived while it ran; the characters of the outcome's detail kept in the state; and how long
# the last read of `HEAD` may take, made even when the job's own time is spent.
LOOPS = 2
DETAIL_LIMIT = 2000
HEAD_TIMEOUT = 10.0
# What the detached process runs, under `-I`: the working directory (the overlay), `PYTHONPATH`
# and the user site are not on `sys.path`, and only the imported package's own directory, which
# `job_argv` hands it, is put back.
BOOT = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from stayfixed.sync.job import main; sys.exit(main(sys.argv[1:]))"
)


def _refusal_detail(refused: list[str]) -> str:
    return (
        "job: not committed, not a plain-text note under a memory name (a link, at the path or in "
        "place of a directory above it, a nested repository, an executable, a dot-file or "
        "dot-directory, a name not ending in .md, or a file git calls binary): "
        + ", ".join(refused)
    )


def _end(ctx: JobContext, stopped: Outcome | None) -> Outcome:
    """The job's outcome, by one rule: a stop is the end; otherwise the latest notice, the paths
    left out of a commit (`ctx.refused`) counting as the earliest; with neither, `ok`. Every other
    candidate is named in the detail, after the end's own words and before the remarks, and the
    same failure met twice is said once."""
    notices = list(ctx.notices)
    if ctx.refused:
        refusal = _outcome(ctx, "hook_failed", _refusal_detail(ctx.refused))
        notices.insert(0, refusal)
    ranked: list[Outcome] = []
    for each in ([stopped] if stopped is not None else []) + notices[::-1]:
        if all((each.state, each.detail) != (kept.state, kept.detail) for kept in ranked):
            ranked.append(each)
    end = ranked[0] if ranked else _outcome(ctx, "ok")
    others = [f"also {other.state}: {other.detail}" for other in ranked[1:]]
    return replace(end, detail=_detail([end.detail, *others, *ctx.remarks]))


def _detail(parts: list[str | None]) -> str | None:
    """`parts` a line apart, each said once; when they are too long together each is cut to an
    equal share, so the last is never dropped for the first."""
    said = list(dict.fromkeys(part for part in parts if part))
    joined = "\n".join(said)
    if len(joined) <= DETAIL_LIMIT:
        return joined or None
    share = DETAIL_LIMIT // len(said) - 1
    return "\n".join(part if len(part) <= share else part[: share - 3] + "..." for part in said)


def _steps(ctx: JobContext) -> Outcome | None:
    """Guard, commit, fetch, integrate, push; the outcome that stopped it."""
    checked_out = guard(ctx.overlay, timeout=ctx.limit(ctx.limits.local), env=ctx.env)
    if not checked_out.ok:
        return _outcome(ctx, "skipped", checked_out.reason)
    stopped = commit_memory(ctx)
    if stopped is not None:
        return stopped
    recorded = ctx.fetched_sha
    upstream, stopped = fetch(ctx)
    if upstream is None:
        return stopped
    return integrate(ctx, upstream, recorded) or push(ctx, upstream)


def _one_job(ctx: JobContext) -> SyncState:
    """The steps once, within the job's limit; the state written for them. A state recorded for
    another overlay, or one that cannot be read, is not used, and the detail says so."""
    ctx = replace(
        ctx, deadline=time.monotonic() + ctx.limits.job, remarks=[], notices=[], fetched_sha=None,
        dirty=None, refused=[], holds=EMPTY_HOLDS, last_head=None,
    )  # fmt: skip
    scratch = ctx.state_dir / SCRATCH
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        previous = read_state(ctx.state_dir)
    except StateUnreadable as error:
        previous = None
        ctx.remarks.append(f"the previous state could not be read and was replaced: {error}")
    if previous is not None and previous.overlay != str(ctx.overlay):
        ctx.remarks.append(
            f"the state recorded for {previous.overlay} is not used: the overlay moved"
        )
        previous = None
    if previous is not None:
        ctx.holds, ctx.fetched_sha, ctx.last_head = (
            previous.holds,
            previous.fetched_sha,
            previous.head,
        )
    try:
        stopped = _steps(ctx)
    except (JobTimeout, GitTimeout) as error:
        stopped = _outcome(ctx, "timeout", str(error))
    except JobStopped as stop:
        stopped = stop.outcome
    except Exception as error:  # every failure becomes state, never a traceback
        said = scan.first_lines(str(error)) or type(error).__name__
        stopped = _outcome(ctx, "hook_failed", f"job: {said}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    head = git(
        ctx.overlay, "rev-parse", "-q", "--verify", "HEAD", timeout=HEAD_TIMEOUT, env=ctx.env
    )
    state = SyncState(
        overlay=str(ctx.overlay),
        outcome=_end(ctx, stopped),
        holds=ctx.holds,
        fetched_sha=ctx.fetched_sha,
        last_job_at=iso(ctx.now()),
        head=head.out.strip() if head.code == 0 and not head.timed_out else None,
        dirty=ctx.dirty,
    )
    write_state(ctx.state_dir, state)
    return state


def _released() -> None:
    """Nothing; the moment right after a job released its lock (a test seam)."""


def run_job(ctx: JobContext) -> SyncState | None:
    """Take the lock, run the job, write the state, release; loop while triggers arrived.

    With the lock busy, the trigger is marked pending for the running job and the current state
    returned. After each release the mark is taken once more, so a trigger that landed while the
    job ran runs it again, at most `LOOPS` more times; one still pending after that gets a
    sleeper, a throttle after this job, as the hooks schedule one.
    """
    state: SyncState | None = None
    for round_number in range(LOOPS + 1):
        lock = Lock.try_acquire(ctx.state_dir / LOCK_FILE)
        if lock is None:
            mark_pending(ctx.state_dir)
            if state is None:
                with contextlib.suppress(StateUnreadable):
                    state = read_state(ctx.state_dir)
            return state
        with lock:
            take_pending(ctx.state_dir)  # this round covers every trigger so far
            state = _one_job(ctx)
        _released()
        if round_number == LOOPS:
            if fsops.exists(ctx.state_dir / PENDING_FILE) and state.last_job_at is not None:
                wake = parse_time(state.last_job_at) + timedelta(seconds=THROTTLE_SECONDS)
                spawn(ctx.overlay, wake=wake)
        elif not take_pending(ctx.state_dir):
            break
    return state


def job_argv(*, wake: datetime | None) -> list[str]:
    """The detached job's command: isolated, given the package's directory, and `--sleep-until`
    for a sleeper. It reads the switch and the overlay from the machine file itself."""
    package_parent = str(Path(__file__).resolve().parents[2])
    sleep = ["--sleep-until", iso(wake)] if wake is not None else []
    return [sys.executable, "-I", "-c", BOOT, package_parent, *sleep]


def spawn(overlay: Path, *, wake: datetime | None = None) -> None:
    """Start the job detached and return at once: its own session, standard streams on
    `/dev/null` (a hook's caller reads its output to the end), no inherited descriptor, and the
    overlay as its working directory."""
    subprocess.Popen(  # noqa: S603 - list form, never a shell
        job_argv(wake=wake),
        cwd=overlay,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _sleep_until(text: str, now: datetime) -> None:
    """Sleep until `text`, never longer than the throttle: a clock that jumped must not park the
    sleeper for hours."""
    with contextlib.suppress(ValueError):
        seconds = (parse_time(text) - now).total_seconds()
        time.sleep(min(max(seconds, 0.0), THROTTLE_SECONDS))


def _switched_on() -> Path | None:
    """The overlay the machine file records, when it also switches the sync on."""
    overlay = overlay_root(None) if enabled() else None
    return overlay if overlay is not None and fsops.exists(overlay / ".git") else None


def main(argv: list[str] | None = None) -> int:
    """`[--sleep-until ISO]`: the detached job. Exits 0 whatever happens, and runs no job while
    the machine file does not switch the sync on, read again when a sleeper wakes."""
    try:
        parser = argparse.ArgumentParser(prog="stayfixed-sync", add_help=False)
        parser.add_argument("--sleep-until")
        with contextlib.redirect_stderr(io.StringIO()):
            args = parser.parse_args(argv)
        if _switched_on() is None:
            return 0
        state_dir = state_directory()
        if args.sleep_until:
            sleeper = Lock.try_acquire(state_dir / SLEEPER_LOCK_FILE)
            if sleeper is None:
                return 0  # another sleeper already waits
            with sleeper:
                _sleep_until(args.sleep_until, datetime.now(UTC))
        overlay = _switched_on()
        if overlay is None:
            return 0
        host = os.uname().nodename.split(".")[0] or "unknown"
        context = JobContext(overlay, state_dir, Path.home(), host, lambda: datetime.now(UTC))
        run_job(context)
    except (Exception, SystemExit):  # noqa: S110 - the job exits 0 whatever happens
        pass
    return 0
