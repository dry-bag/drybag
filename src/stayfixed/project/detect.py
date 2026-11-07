"""What `init --yes` can read off a repository without asking, and where each value came from.

Two values, each one `git` question: the name and the base branch. `origin_remote` is
`gitenv`'s, so "what is this checkout's origin" is asked one way wherever it is asked.

**Three of them are repository-authored strings, and each is held to a grammar before it is
returned:** the remote's last path segment and the checkout's directory name to `[project]
name`'s, and `origin/HEAD`'s branch — or, in a repository with no remote at all, the branch
checked out — to `BRANCH_NAME`, git's own rules for a branch. A name outside its grammar is
refused naming the grammar and never the value, or, leniently, returned as `""` and `not
derivable`, so `init --questions` asks for it rather than suggesting it. A branch outside its
grammar is reported as the default.

Each value also says where it came from, in one of this module's fixed phrases, because a
default is only as good as its source: `origin/HEAD` is set by `git clone`, `git remote
set-head`, or a `git fetch` from git 2.48 on that finds none, and goes stale after the remote's
default branch is renamed, since git does not refresh one it has.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from stayfixed.config.schema import BRANCH_NAME, NAME_RULE, PROJECT_NAME
from stayfixed.errors import Refusal
from stayfixed.gitenv import GitUnavailable, git_run, in_work_tree, origin_remote, repository_name

DEFAULT_BRANCH = "main"
ORIGIN_PREFIX = "refs/remotes/origin/"
HEADS_PREFIX = "refs/heads/"
NOT_A_NAME = (
    f"the project name this repository suggests is not {NAME_RULE}, so `init` cannot choose "
    "one; answer it with `stayfixed init --yes "
    "--name NAME`, or write `[project] name` into stayfixed.toml by hand and run `stayfixed init "
    "--yes` again, which keeps what you wrote"
)
# Where a value came from: the only words `Detected.sources` holds.
DEFAULT = "default"
NOT_DERIVABLE = "not derivable"
ORIGIN_REMOTE = "origin remote"
DIRECTORY_NAME = "directory name"
ORIGIN_HEAD = "origin/HEAD"
CURRENT_BRANCH = "current branch"


@dataclass(frozen=True)
class Detected:
    name: str
    base_branch: str
    # Keyed "name" and "base_branch"; each value one of this module's phrases.
    sources: Mapping[str, str] = field(default_factory=dict)
    # `origin/HEAD` named a branch outside the grammar, so the base branch is the default in its
    # place. A flag and never the name: the name is the text the grammar refused.
    head_refused: bool = False
    # There is a remote and no `origin/HEAD` recorded, so the base branch is the default: the
    # branch checked out is as likely a feature branch as the remote's default.
    head_unrecorded: bool = False
    # git could not list the remotes of the repository this is in, so whether there is one is not
    # known and the base branch is the default rather than the branch checked out.
    remotes_unknown: bool = False


def _origin(root: Path) -> str | None:
    """The `origin` remote's URL, or `None` when there is none or `git` could not say."""
    try:
        return origin_remote(root)
    except GitUnavailable:
        return None


def _name(root: Path, origin: str | None) -> tuple[str, str]:
    if origin:
        return repository_name(origin), ORIGIN_REMOTE
    return root.name.lower(), DIRECTORY_NAME


def _symbolic(root: Path, ref: str, prefix: str) -> str | None:
    """The branch the symbolic `ref` names below `prefix`, unchecked; `""` when it names a ref
    outside `prefix`, and `None` when git records no such symbolic ref.

    The full ref and never `--short`: git shortens a ref only as far as it stays unambiguous, so
    a tag or a local branch named `origin/develop` made `origin/HEAD` read back as
    `remotes/origin/develop`, which passed the grammar and was written as the base branch. The
    clone carries the tag, so that was repository-authored input choosing the configuration.
    """
    code, out = git_run(root, "symbolic-ref", ref)
    if code != 0:
        return None
    full = out.removesuffix("\n")
    return full.removeprefix(prefix) if full.startswith(prefix) else ""


def _remotes(root: Path) -> bool | None:
    """Whether the repository has any remote; `None` when git gave no answer inside one.

    Outside a repository there is no remote and no branch checked out, so that is `False`.
    """
    code, out = git_run(root, "remote")
    if code == 0:
        return bool(out.strip())
    return None if in_work_tree(root) else False


def _base_branch(root: Path) -> tuple[str, str, bool, bool, bool]:
    """The base branch, where it came from, whether `origin/HEAD` named one outside the grammar,
    whether a remote has no `origin/HEAD` recorded, and whether git could not list the remotes;
    in each of the last three the default stands in.

    Only a repository with no remote at all takes the branch checked out, held to the same
    grammar: a fresh repository on `develop` had `main` written as its base, and a workflow
    that never ran for a pull request into `develop`. A repository created here and pushed
    (`git push -u origin main`) has a remote and no `origin/HEAD` until `git clone`, `git remote
    set-head`, or a `git fetch` from git 2.48 on records one, and it is typically adopted from a
    feature branch: taking that branch wrote it as the base, so the workflow gated the feature
    branch. So does one whose only remote is `upstream`, pushed or cloned with `-o upstream`:
    only `origin/HEAD` is read. There the default stands, and the caller says how to answer it.
    A detached or unreadable `HEAD`, or a branch outside the grammar, leaves the default too.
    """
    head = _symbolic(root, "refs/remotes/origin/HEAD", ORIGIN_PREFIX)
    if head is not None:
        if BRANCH_NAME.match(head):
            return head, ORIGIN_HEAD, False, False, False
        return DEFAULT_BRANCH, DEFAULT, True, False, False
    remotes = _remotes(root)
    if remotes is None:
        return DEFAULT_BRANCH, DEFAULT, False, False, True
    if remotes:
        return DEFAULT_BRANCH, DEFAULT, False, True, False
    current = _symbolic(root, "HEAD", HEADS_PREFIX)
    if current and BRANCH_NAME.match(current):
        return current, CURRENT_BRANCH, False, False, False
    return DEFAULT_BRANCH, DEFAULT, False, False, False


def detect(root: Path, *, lenient: bool = False) -> Detected:
    """The name and the base branch, each with its source.

    The refusal is the whole of what this does with a name outside the grammar: the remote's
    last path segment and the checkout's directory name both arrive from outside, so one that is
    not a `PROJECT_NAME` is answered with the grammar and the remedy and with none of its own
    bytes. The loader refuses the same grammar the same way, so writing the name by hand and
    running `init` again is a remedy that reaches the end. `lenient` returns it as `""`, `not
    derivable`, instead, for a caller that asks rather than writes.
    """
    origin = _origin(root)
    name, name_source = _name(root, origin)
    if not PROJECT_NAME.match(name):
        if not lenient:
            raise Refusal(NOT_A_NAME)
        name, name_source = "", NOT_DERIVABLE
    base_branch, branch_source, head_refused, head_unrecorded, remotes_unknown = _base_branch(root)
    return Detected(
        name,
        base_branch,
        {"name": name_source, "base_branch": branch_source},
        head_refused=head_refused,
        head_unrecorded=head_unrecorded,
        remotes_unknown=remotes_unknown,
    )
