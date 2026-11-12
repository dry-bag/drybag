"""Which `git` this project runs, the environment it is given, and the bound on how long it may
take.

One module, because every caller needs the same rule: a git answer must be about the repository
asked, never one an inherited `GIT_DIR` produced. The hook path's project root (`checkout_root`)
feeds every hook decision, and the memory store's queries decide whose notes a session reads.
A leaf module: it imports no area, so the hook path pays no area import to reach it.

`git` is the one on `PATH`, given `scrubbed_env`: `PATH`, `HOME` and what a push or a clone needs,
so the owner's `git`, `safe.directory` and excludes answer. Every other variable is dropped —
every `GIT_CONFIG_*`, `GIT_SSH_COMMAND` and `XDG_CONFIG_HOME` among them — so none names another
repository, a configuration git would not otherwise read, or a program to run.

`git_run` is the one runner for a question about a repository, behind one lossless decoding
boundary; `git_call` is the same git for a caller that reads stderr and lays its own settings over
the environment. The `Runner` seam in `drybag.runner`, for the owner's own commands, is the other.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from drybag import fsops
from drybag.errors import Failure, Refusal
from drybag.printed import quoted
from drybag.processes import Ran, run_bounded

# Everything else is dropped, an inherited `GIT_DIR` and `GIT_WORK_TREE` above all. The ssh agent
# and the proxy variables curl reads are kept: a push and a clone need them, and neither changes
# where git reaches, only how it gets there.
GIT_ENV_KEEP = (
    "PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "SSH_AUTH_SOCK",
    "http_proxy", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY",
)  # fmt: skip

# A named cap (CONTRIBUTING.md#named-caps), and no shipped file changes with it: the wall-clock
# bound on one local, read-only query that neither reaches the network nor grows with the
# repository (`rev-parse`, `remote get-url`, `--version`). It guards against a `git` that hangs,
# without leaving a hook blocked for long; a query of another shape passes its own bound.
GIT_TIMEOUT_SECONDS = 5
# The wider bound on one local query that grows with the repository (a `log --all`, a listing of
# every tracked file); running out is never "nothing found": the note sync's job records it.
QUERY_TIMEOUT_SECONDS = 30

# The one input that raises the least bound `git_run` gives a call; unset, there is no floor.
# drybag's own test suite sets it (`tests/conftest.py`), so a verdict does not turn on how loaded
# the machine is.
#
# It is read from this process's environment and from nothing a repository commits, and it can
# only raise a bound: `git_run` takes the larger of it and the caller's, and a value that is not a
# positive number is ignored. Whatever reaches the environment for a repository (a harness's `env`
# block, `direnv`, a devcontainer) can set `PATH` as readily, which chooses the `git` outright, so
# setting this gains it only a longer wait, capped at `FLOOR_CEILING_SECONDS` so that a hook still
# ends before the harness's own timeout on the entry.
FLOOR_VARIABLE = "DRYBAG_GIT_FLOOR_SECONDS"
# Ten minutes: far above what any load makes a local `git` take, and far below a timeout that
# `subprocess` cannot represent — `timeout=1e300` raises `OverflowError`, which `git_run` does
# not catch, so an uncapped value would end every caller as an internal error.
FLOOR_CEILING_SECONDS: float = 600

# What `git_run`'s `(-1, "")` means, in one clause a caller's message can build on. None of the
# three is an answer about the repository, so a caller that words `-1` as one cause is wrong about
# the other two; `git_answer`, whose refusal names the cause, reads it from `_ask`.
NO_ANSWER = "git could not be run, ran past its time limit, or could not be given its input"


def bound_floor() -> float:
    """The least bound `git_run` gives a call now: `FLOOR_VARIABLE` when it is a positive number,
    at most `FLOOR_CEILING_SECONDS`, and zero otherwise. Read at every call, so a test that removes
    the variable is under the product's own bounds from its next call."""
    try:
        asked = float(os.environ.get(FLOOR_VARIABLE, ""))
    except ValueError:
        return 0.0
    # Written so that `nan`, which compares false with everything, falls to zero with the rest.
    if not asked > 0:
        return 0.0
    return min(asked, FLOOR_CEILING_SECONDS)


def in_work_tree(root: Path) -> bool:
    """Whether `root` or a directory above it holds a `.git` entry, as git itself finds the
    repository. Read off the disk and never asked of git: a `rev-parse` that times out, or exits
    128 on a checkout of dubious ownership or a worktree whose gitdir is gone, would read as "no
    repository" and let a guard's caller through."""
    return any(os.path.lexists(directory / ".git") for directory in (root, *root.parents))


def scrubbed_env() -> dict[str, str]:
    """The variables `GIT_ENV_KEEP` names, `PATH` with its absolute entries alone (`os.defpath`
    where it has none), and no terminal prompt: what every git drybag starts is handed. An empty
    or `.` entry of `PATH` would find a `git`, or git an `ssh`, planted at the root of a clone."""
    env = {key: os.environ[key] for key in GIT_ENV_KEEP if key in os.environ}
    if "PATH" in env:
        entries = env["PATH"].split(os.pathsep)
        env["PATH"] = (
            os.pathsep.join(entry for entry in entries if os.path.isabs(entry)) or os.defpath
        )
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def pipe_encoding() -> str:
    """The codec `git_run` decodes git's output and encodes its `stdin` with, under
    `surrogateescape`: the filesystem's, which `os.fsdecode`, `Path.iterdir` and `sys.argv` use.

    Not the locale's: on macOS the filesystem codec is UTF-8 whatever `LC_ALL` says, and a latin-1
    locale's codec would turn git's `café.md` into mojibake, so no comparison of git's answer with
    a path would match. Named once so `answer_bytes` undoes exactly what `git_run` did.
    """
    return sys.getfilesystemencoding()


def answer_lines(answer: str) -> list[str]:
    """A line-oriented `git_run` answer, split at `\\n` alone, where git ended each line.

    Never `str.splitlines()`, which also breaks at `\\r`, `\\v`, `\\f` and other separators git
    prints raw inside a path; a single-line answer is `answer.removesuffix("\\n")`, never
    `strip()`, for the same reason. No answer is no lines.
    """
    lines = answer.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def answer_bytes(answer: str) -> bytes:
    """The bytes git printed for a `git_run` answer, exactly, for a caller that must read them as
    UTF-8 whatever the locale."""
    return answer.encode(pipe_encoding(), "surrogateescape")


def git_run(
    root: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS, stdin: str | None = None
) -> tuple[int, str]:
    """`(returncode, stdout)` of `git -C root args`; `(-1, "")` when git gave no answer.

    Every argument list is built from constants by the caller, every pathspec follows `--` or
    `--end-of-options`, no configuration value reaches it without `contained()` having refused the
    `-`-shaped ones, and git is handed `scrubbed_env`. A non-zero exit is returned, not collapsed:
    `check-ignore` answers 1 for "nothing matched".

    Run in bytes and decoded here in `pipe_encoding` with `surrogateescape`, both ways: a name git
    prints that is not UTF-8 comes back as the `str` `os.listdir` gives for it, never as an error or
    as no answer, and no `\\r` is translated, so a name holding one stays that name. A caller that
    writes the answer into a UTF-8 file checks it itself.

    No answer is `NO_ANSWER`'s three causes: git could not be launched, it ran past `timeout`, or
    `stdin` held a character the filesystem's codec has no bytes for.
    """
    asked = _ask(root, *args, timeout=timeout, stdin=stdin)
    return (-1, "") if isinstance(asked, _NoAnswer) else asked


# What `git_call` gives back: both streams decoded as `git_run` decodes its answer.
Called = Ran[str]


def git_call(
    root: Path,
    *args: str,
    timeout: float,
    env: Mapping[str, str] | None = None,
    stdin: bytes | None = None,
) -> Called:
    """`git <args>` in `root`, given `scrubbed_env()` with `env` laid over it, bounded by the
    larger of `bound_floor()` and `timeout`, its whole group ended past that. Both streams decoded
    as `git_run` decodes; `stdin` is bytes or closed; a `git` that cannot start is code 127."""
    codec = pipe_encoding()
    ran = run_bounded(
        ["git", *args],
        cwd=root,
        env=scrubbed_env() | dict(env or {}),
        timeout=max(timeout, bound_floor()),
        stdin=stdin,
    )
    out, err = (data.decode(codec, "surrogateescape") for data in (ran.out, ran.err))
    return Called(ran.code, out, err, ran.timed_out)


class _NoAnswer(Enum):
    """Which of `NO_ANSWER`'s three causes `_ask` met, kept where it is known: `git_answer`'s
    refusal says what to do, and a timeout and a `git` that cannot start need different words."""

    UNLAUNCHABLE = "unlaunchable"
    TIMED_OUT = "timed out"
    UNENCODABLE_INPUT = "unencodable input"


def _ask(
    root: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS, stdin: str | None = None
) -> tuple[int, str] | _NoAnswer:
    """`git_run`'s question, answered as `(returncode, stdout)` or as why there was no answer. A
    `returncode` below zero is a `git` a signal ended."""
    codec = pipe_encoding()
    try:
        given = None if stdin is None else stdin.encode(codec, "surrogateescape")
        completed = subprocess.run(  # noqa: S603 - see `git_run`'s docstring
            ["git", "-C", str(root), *args],  # noqa: S607 - the `git` on PATH
            input=given,
            capture_output=True,
            check=False,
            timeout=max(timeout, bound_floor()),
            env=scrubbed_env(),
        )
    except subprocess.TimeoutExpired:
        return _NoAnswer.TIMED_OUT
    except UnicodeEncodeError:
        return _NoAnswer.UNENCODABLE_INPUT
    except (OSError, subprocess.SubprocessError):
        return _NoAnswer.UNLAUNCHABLE
    answer = completed.stdout.decode(codec, "surrogateescape")
    return completed.returncode, answer


def _git_toplevel(cwd: Path) -> Path | None:
    """The checkout git names for `cwd`, as the path on disk, or `None` when git named none.
    Through `git_run`, so no inherited `GIT_DIR` chooses it and a directory named in bytes that are
    not UTF-8 is that directory; only the line ending is taken off."""
    code, out = git_run(cwd, "rev-parse", "--show-toplevel")
    top = out.removesuffix("\n")
    return Path(top) if code == 0 and top else None


def _walk_to_git_root(cwd: Path) -> Path | None:
    """`.git` is a directory in a clone and a file in a worktree or a submodule; both count.

    Resolved, because `rev-parse --show-toplevel` resolves symlinks in `cwd`, so the walk agrees
    with git about a repository reached through a symlink. Asked through `fsops.exists`, so a
    `.git` past the longest path is nothing there on every interpreter, and the walk goes on.
    """
    if not cwd.is_absolute():
        return None
    for directory in [cwd, *cwd.parents]:
        if fsops.exists(directory / ".git"):
            return directory.resolve()
    return None


def checkout_root(cwd: Path) -> Path | None:
    """The checkout `cwd` sits in: a walk for `.git`, else git itself; `None` if neither names one.

    The hook's project root when no harness variable names one (`hooks.dispatch.read_event` asks
    those first), so it runs on every tool call: the walk is far cheaper than a `git` process, and
    git stays behind it for what a walk cannot see, such as `GIT_DIR` and a bare repository.
    """
    return _walk_to_git_root(cwd) or _git_toplevel(cwd)


def git_path(root: Path, name: str, what: str) -> Path:
    """Where git keeps `name` for `root`, as `git rev-parse --git-path` names it: `hooks` for
    `setup --git-hooks` and `doctor`, `info/exclude` for `attach` and `detach`. `--git-path` maps
    a name to the common directory every worktree shares and honours `core.hooksPath`, which a path
    computed by hand gets wrong. `name` is a caller's constant and `what` its word in a refusal. No
    `--` after `name`: git would print it as a second line."""
    code, out = git_run(root, "rev-parse", "--git-path", name)
    # Neither refusal carries git's stderr, which is repository-authored (it quotes a config value,
    # `core.hooksPath` included); only `root` is printed, through `quoted`, since a clone's
    # directory can be given any name.
    if code == -1:
        raise Refusal(f"git could not name the {what} of {quoted(str(root))} ({NO_ANSWER})")
    answer = out.removesuffix("\n")
    if code != 0 or not answer:
        raise Refusal(
            f"git could not name the {what} of {quoted(str(root))}; run it yourself to see why"
        )
    path = Path(answer)
    return path if path.is_absolute() else root / path


def hooks_dir(root: Path) -> Path:
    """The directory git runs `root`'s hooks from, as git names it: `core.hooksPath` when set."""
    return git_path(root, "hooks", "hooks directory")


class GitUnavailable(Failure):
    """`git` could not be run, or failed: read as "git said no", that would tell the user to run
    `drybag attach` when the real fault is their `git` — the state a macOS machine is in when
    `/usr/bin/git` is the Xcode shim with an unaccepted licence (`GIT_ENV_KEEP` drops its
    `DEVELOPER_DIR`).

    `cause` is the `GitAnswer.cause` the refusal was built from, so a caller walking several
    checkouts can tell a directory that went away (`Unasked.GONE`) from a fault it has to report.
    """

    def __init__(self, message: str, cause: Unasked | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class Unasked(Enum):
    """Why `git_answer` has no answer. Each value is the sentence a refusal ends with, and ends in
    what to do, so a refusal names the cause it found rather than "check that `git` runs here"."""

    TIMED_OUT = (
        "`git` gave this question no answer within its time limit, which a heavily loaded "
        "machine causes; run the command again"
    )
    ENDED = (
        "`git` was ended by a signal before it answered, which a machine out of memory causes; "
        "run the command again"
    )
    GONE = (
        "the directory it was asked in no longer exists, which a worktree removed while the "
        "command ran causes"
    )
    NOT_STARTED = "`git` could not be started here; check that `git` runs here"
    BROKEN = "`git` fails here even for `git --version`; check that `git` runs here"


def _unanswered(asked: _NoAnswer) -> Unasked:
    """The cause a question `_ask` got no answer to is refused for. An input `git` could not be
    given is a `git` never started, and `git_answer` gives none, so it reads as one."""
    return Unasked.TIMED_OUT if asked is _NoAnswer.TIMED_OUT else Unasked.NOT_STARTED


@dataclass(frozen=True)
class GitAnswer:
    """git's one-line answer to one question: an answer (`value`), no answer, or could not ask
    (`cause`). An empty stdout and a refusal from a `git` that works are "no answer", a fact about
    the repository that carries no cause."""

    value: str | None
    cause: Unasked | None = None

    def require(self, refusal: str) -> str | None:
        """The answer, or `GitUnavailable` when `git` could not be asked: `refusal` is the caller's
        words for what went unanswered, and the cause, which says what to do, follows it."""
        if self.cause is not None:
            raise GitUnavailable(f"{refusal}: {self.cause.value}", self.cause)
        return self.value


def git_answer(root: Path, *args: str) -> GitAnswer:
    """git's one-line answer to `args` asked in `root`, through `_ask`, `git_run`'s own call, less
    its line ending alone.

    When there is no answer, why, read where it is known: no process is `_ask`'s own cause, and a
    negative exit is a `git` a signal ended. A positive exit is "git declined" or "git is broken",
    told apart only after it: first whether `root` is still a directory (`git -C <gone>` exits 128
    for `--version` too), then `git --version` from the same `root`, which needs no repository and
    which a broken install fails too.
    """
    asked = _ask(root, *args)
    if isinstance(asked, _NoAnswer):
        return GitAnswer(None, _unanswered(asked))
    code, out = asked
    if code == 0:
        return GitAnswer(out.removesuffix("\n") or None)
    if code < 0:
        return GitAnswer(None, Unasked.ENDED)
    if not fsops.is_dir(root):
        return GitAnswer(None, Unasked.GONE)
    probe = _ask(root, "--version")
    if isinstance(probe, _NoAnswer):
        return GitAnswer(None, _unanswered(probe))
    if probe[0] != 0:
        return GitAnswer(None, Unasked.BROKEN)
    return GitAnswer(None)


# A URL's scheme and the userinfo before the authority's last `@`: `[^/?#]*` stops at the path, so
# an `@` in the path (`…/p@v1`) is not userinfo, and a password holding `@` is taken whole.
_USERINFO = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^/?#]*)@")


def without_userinfo(url: str) -> str:
    """`url` as it may be printed or recorded: a remote can carry a token as its userinfo
    (`https://user:token@host/…`), and `attach` prints the origin and keeps it on this machine.

    Every scheme loses its userinfo but ssh's, whose user (`ssh://git@host/…`) is no secret and
    tells one remote from another (`memory.store`); there only a `:password` goes. The scp form
    (`git@host:path`) carries no password and is left as it is."""
    found = _USERINFO.match(url)
    if found is None:
        return url
    scheme, userinfo = found["scheme"], found["userinfo"]
    rest = url[found.end() :]
    if "ssh" in scheme.lower():
        user = userinfo.split(":", 1)[0]
        return f"{scheme}{user}@{rest}" if user else f"{scheme}{rest}"
    return f"{scheme}{rest}"


def repository_name(url: str) -> str:
    """The name a remote `url` gives its repository: the last segment of its path, `:` read as the
    scp form's `/`, lower-cased and with one `.git` taken off. `attach` binds a repository with no
    `drybag.toml` under it by this name, and holds it to the name rule itself."""
    segment = url.rstrip("/").replace(":", "/").rsplit("/", 1)[-1]
    # Lower-cased first, so `Widget.GIT` loses its suffix as `Widget.git` does.
    return segment.lower().removesuffix(".git")


def origin_remote(root: Path) -> str | None:
    """This checkout's `origin` URL, or `None` when `git` ran and there is no such remote.

    Public so `attach` asks it through `git_run`, scrubbed, rather than a `subprocess.run` of its
    own. A URL in bytes that are not UTF-8 is answered as the filesystem's codec spells it. Raises
    `GitUnavailable` rather than answering `None` when `git` could not be asked: "no origin" reads
    as *not this one*, while "could not ask" is a fault on this machine.

    The value is repository-authored (principle 5): a clone chooses its own remote URL, so a caller
    that shows it wraps it first.
    """
    return git_answer(root, "remote", "get-url", "origin").require(
        "`git` could not read this repository's origin remote — the fault is on this "
        "machine rather than in the repository"
    )


SHALLOW = (
    "this clone is shallow, so the commits HEAD forked from can be cut off and an older one "
    "stand in for them"
)
DISJOINT = "HEAD and the base share no commit"


@dataclass(frozen=True)
class ForkUnknown:
    """Why the commits HEAD forked from a base at are not known: `cause` in words, and whether
    git answered at all, since a git that gave no answer sends a reader to a different remedy
    than a clone that is shallow or a base it refused."""

    cause: str
    answered: bool

    @classmethod
    def of(cls, code: int) -> ForkUnknown:
        """A question git exited `code` on. Any negative code is no answer: `git_run`'s `-1`,
        and a git a signal ended, which `subprocess` reports as the signal's negative."""
        if code < 0:
            return cls(NO_ANSWER, answered=False)
        return cls(f"git exited {code}", answered=True)


def fork_points(root: Path, base: str) -> list[str] | ForkUnknown:
    """Every commit HEAD forked from `base` at — `git merge-base --all <base> HEAD`, in git's
    order — or why they are not known.

    Every one, because a history the change shapes can have several, and git's pick of one is a
    tree the change can choose. A shallow clone (asked first: no answer is not "not shallow"), a
    question git does not answer, and a base sharing no commit with HEAD are all not known, and
    each caller says what that means. The caller refuses an option-shaped `base` before this.
    """
    code, out = git_run(root, "rev-parse", "--is-shallow-repository")
    if code != 0:
        return ForkUnknown.of(code)
    if out.strip() == "true":
        return ForkUnknown(SHALLOW, answered=True)
    code, out = git_run(root, "merge-base", "--all", base, "HEAD")
    forks = out.split()
    if code == 1 and not forks:
        return ForkUnknown(DISJOINT, answered=True)
    if code != 0 or not forks:
        return ForkUnknown.of(code)
    return forks
