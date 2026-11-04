"""The sync's git layer: a bounded runner, the job's environment and the guard.

Every call the job makes goes through `run`, which ends the child's whole process group on a
timeout, so an ssh or a credential helper under git cannot outlive the step that started it.
`gitenv.git_run` cannot serve: it keeps only `PATH` and `HOME`, which loses the ssh agent a push
needs. This runner inherits the environment less git's repository variables, so a job started
from inside a git hook still addresses the overlay and its real index. A helper's `timeout` is its
whole budget: one that makes several calls gives each what is left (`left`). `env` is laid over
every call a helper makes; the job passes `job_env`.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from stayfixed import fsops
from stayfixed.processes import KILL_WAIT_SECONDS, kill_group

# A named cap: how long one local query over the overlay's notes (a `log`, `diff` or `status`) may
# take, for a git that hangs. No shipped file states it.
LOCAL_TIMEOUT = 30.0
# What makes ssh fail instead of ask: no prompt, and ten seconds (a named cap, no shipped file
# states it) to connect.
SSH_OPTIONS = " -o BatchMode=yes -o ConnectTimeout=10"
# `merge-tree --write-tree --merge-base` (2.40), `GIT_ATTR_SOURCE` (2.41), which an older git
# ignores without a word, and a `merge-tree` that reads attributes from it without crashing (2.43).
MIN_GIT = (2, 43)

# `git rev-parse --local-env-vars`: each redirects git to another repository, index or object store.
REPOSITORY_VARIABLES = frozenset((
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_CONFIG", "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_GRAFT_FILE", "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_OBJECT_DIRECTORY", "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE", "GIT_WORK_TREE",
))  # fmt: skip
# The programs git and ssh ask for a password before the terminal, which no unattended job may
# start: an editor's terminal sets the first, a desktop the second.
ASKPASS = frozenset(("GIT_ASKPASS", "SSH_ASKPASS"))
_VERSION = re.compile(r"git version (\d+)\.(\d+)")


class GitError(RuntimeError):
    """A git call the rules depend on failed; the message carries git's own words."""


class GitTimeout(GitError):
    """A git call ran out of its time; the job records `timeout`, not a failure."""


@dataclass(frozen=True)
class Ran:
    code: int
    out: str
    err: str
    timed_out: bool


def _text(data: bytes) -> str:
    # surrogateescape: a path that is not UTF-8 survives the round trip back into an argv.
    return data.decode("utf-8", "surrogateescape")


def run(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
    index_file: Path | None = None,
    stdin: bytes | None = None,
    unset_prefixes: tuple[str, ...] = (),
) -> Ran:
    """Run `argv` in `cwd` with `env` laid over ours, ending its process group on a timeout.

    The inherited repository variables, the askpass programs, and any starting with one of
    `unset_prefixes`, are dropped first: `env` and `index_file` are the only way to set them.
    `PATH` keeps only its absolute entries: every call runs in the overlay, where an empty or `.`
    entry would find a `git` or an `ssh` planted at its root. Standard input is `stdin`, or empty:
    nothing the job runs may wait for an answer. A program or directory that is not there is code
    127, as a shell says it.
    """
    full = {
        key: value
        for key, value in os.environ.items()
        if key not in REPOSITORY_VARIABLES | ASKPASS and not key.startswith(unset_prefixes)
    }
    full.update(env or {})
    full["PATH"] = os.pathsep.join(
        entry for entry in full.get("PATH", "").split(os.pathsep) if os.path.isabs(entry)
    )
    if index_file is not None:
        full["GIT_INDEX_FILE"] = str(index_file)
    try:
        process = subprocess.Popen(  # noqa: S603 - list form, never a shell; the callers' argv
            argv,
            cwd=cwd,
            env=full,
            stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        return Ran(127, "", f"{argv[0]}: {fsops.said(error)}", False)
    try:
        out, err = process.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(process)
        try:
            out, err = process.communicate(timeout=KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            # A descendant left the group and still holds the pipes: stop reading them.
            process.wait()
            out = err = b""
        return Ran(process.returncode, _text(out), _text(err), True)
    return Ran(process.returncode, _text(out), _text(err), False)


def git(
    repo: Path,
    *args: str,
    timeout: float,
    env: Mapping[str, str] | None = None,
    index_file: Path | None = None,
    stdin: bytes | None = None,
) -> Ran:
    """`git <args>` in `repo`; `index_file` is `GIT_INDEX_FILE` for this call only."""
    return run(
        ["git", *args], cwd=repo, timeout=timeout, env=env, index_file=index_file, stdin=stdin
    )


def left(deadline: float, what: str) -> float:
    """What is left of a helper's budget for its next call; `GitTimeout` when nothing is."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GitTimeout(f"{what} did not finish in time")
    return remaining


def timed(result: Ran, what: str) -> Ran:
    """`result`, or `GitTimeout` when the call ran out of its time: never read as an answer."""
    if result.timed_out:
        raise GitTimeout(f"{what} timed out")
    return result


def checked(result: Ran, what: str) -> Ran:
    """`result` of a call that must succeed: `GitTimeout` on a timeout, `GitError` on a failure."""
    if timed(result, what).code != 0:
        raise GitError(f"{what} failed ({result.code}): {result.err.strip()[:500]}")
    return result


def ask(repo: Path, deadline: float, env: Mapping[str, str] | None, *args: str) -> Ran:
    """`git <args>` given what is left of a helper's budget; never a timed-out answer."""
    return timed(git(repo, *args, timeout=left(deadline, "a git call"), env=env), f"git {args[0]}")


def with_config(env: Mapping[str, str], entries: Mapping[str, str]) -> dict[str, str]:
    """`env` with `entries` added to the configuration it gives git (`GIT_CONFIG_COUNT`), as
    `git -c` would give them, after any it already gives."""
    given = dict(env)
    count = int(given.get("GIT_CONFIG_COUNT", "0"))
    for offset, (key, value) in enumerate(entries.items(), start=count):
        given.update({f"GIT_CONFIG_KEY_{offset}": key, f"GIT_CONFIG_VALUE_{offset}": value})
    given["GIT_CONFIG_COUNT"] = str(count + len(entries))
    return given


def _is_ssh(command: str) -> bool:
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    return bool(words) and os.path.basename(words[0]) == "ssh"


def job_env(repo: Path, *, timeout: float) -> dict[str, str]:
    """What every git call of the job is given on top of our environment.

    `GIT_TERMINAL_PROMPT=0`, `core.askPass` emptied and `SSH_ASKPASS_REQUIRE=never` (with the
    askpass variables `run` drops); the ssh command git would use made non-interactive;
    `GIT_NO_REPLACE_OBJECTS=1`, since a `refs/replace/` entry must not show the checks one commit
    while the push sends another; and `GIT_ATTR_SOURCE=HEAD`: attributes come from the committed
    tree, never from a `.gitattributes` a memory writer left in the working tree, where a filter
    would make the job commit, and the scanner read, something other than the note.

    The command is the one git itself would pick -- `$GIT_SSH_COMMAND`, else `core.sshCommand`,
    else `$GIT_SSH` (a program path, so quoted), else `ssh` -- and gets `SSH_OPTIONS` only when
    its program is `ssh`; a wrapper is used as is, its options its own business.
    """
    command = os.environ.get("GIT_SSH_COMMAND", "")
    if not command:
        configured = timed(
            git(repo, "config", "--get", "core.sshCommand", timeout=timeout), "git config"
        )
        command = configured.out.rstrip("\n") if configured.code == 0 else ""
    if not command:
        program = os.environ.get("GIT_SSH", "")
        command = shlex.quote(program) if program else "ssh"
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "SSH_ASKPASS_REQUIRE": "never",
        "GIT_SSH_COMMAND": command + (SSH_OPTIONS if _is_ssh(command) else ""),
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_ATTR_SOURCE": "HEAD",
    }
    return with_config(env, {"core.askPass": ""})


@dataclass(frozen=True)
class Guard:
    ok: bool
    reason: str | None


def version_ok(text: str) -> bool:
    """Whether `git version` output names `MIN_GIT` or newer; an unreadable answer is not."""
    match = _VERSION.search(text)
    return match is not None and (int(match[1]), int(match[2])) >= MIN_GIT


UNMERGED = "the overlay has unmerged paths; the sync waits until they are resolved"
# The marker each operation in progress leaves, by `--git-path` name, and how to say it.
_IN_PROGRESS = {
    "rebase-merge": "mid-rebase",
    "rebase-apply": "mid-rebase (or mid-am)",
    "MERGE_HEAD": "mid-merge",
    "CHERRY_PICK_HEAD": "mid-cherry-pick",
    "REVERT_HEAD": "mid-revert",
}
_MARKER_PATHS = tuple(part for name in _IN_PROGRESS for part in ("--git-path", name))


def guard(repo: Path, *, timeout: float, env: Mapping[str, str] | None = None) -> Guard:
    """Whether the overlay is in a shape the sync may act on at all.

    Refused, with the reason the state shows: git older than `MIN_GIT`, not a repository, an
    operation in progress, unmerged paths, `HEAD` not on `main`, or `main` not tracking
    `origin/main`. Work in progress, staged or not and anywhere outside memory, is no reason: the
    job never touches it. `timeout` bounds the guard as a whole, and a call that runs out of it is
    `GitTimeout`, never an answer (a timed-out `symbolic-ref` is not a detached `HEAD`).
    """
    deadline = time.monotonic() + timeout
    version = ask(repo, deadline, env, "version")
    if version.code != 0 or not version_ok(version.out):
        found = version.out.strip() or version.err.strip() or "no answer"
        return Guard(
            False,
            "git 2.43 or newer is needed (merge-tree --write-tree --merge-base, GIT_ATTR_SOURCE); "
            f"found: {found}",
        )
    markers = ask(repo, deadline, env, "rev-parse", *_MARKER_PATHS)
    if markers.code != 0:
        return Guard(False, f"not a git repository: {markers.err.strip()[:200] or repo}")
    for saying, marker in zip(_IN_PROGRESS.values(), markers.out.splitlines(), strict=False):
        if fsops.exists(repo / marker):
            return Guard(False, f"the overlay is {saying}; the sync waits until it is finished")
    # A conflicted `stash pop`, `checkout -m` or `apply --3way` leaves no marker, only unmerged
    # entries and a working tree with conflict markers, which the job would commit as notes.
    unmerged = ask(repo, deadline, env, "ls-files", "--unmerged", "-z")
    if unmerged.code != 0 or unmerged.out:
        return Guard(False, UNMERGED)
    head = ask(repo, deadline, env, "symbolic-ref", "-q", "HEAD")
    if head.code != 0:
        return Guard(False, "HEAD is detached; the sync runs only on main")
    if (branch := head.out.strip().removeprefix("refs/heads/")) != "main":
        return Guard(False, f"the overlay is on {branch}, not main")
    remote = ask(repo, deadline, env, "config", "--get", "branch.main.remote").out.strip()
    merge = ask(repo, deadline, env, "config", "--get", "branch.main.merge").out.strip()
    if (remote, merge) != ("origin", "refs/heads/main"):
        tracking = f"{remote}/{merge.removeprefix('refs/heads/')}" if remote else "nothing"
        return Guard(False, f"main tracks {tracking}, not origin/main")
    return Guard(True, None)
