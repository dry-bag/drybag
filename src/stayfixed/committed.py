"""A document as one commit holds it at the project's own path, read the one way every reader
of a commit's copy reads it.

The ledger's base comparison asks, for the `stayfixed.toml` of each commit a change forked from,
which says where that commit kept its ledger. The answer decides what a pull request is judged
against, so it is read at the project root's path inside the repository as git spells it, with the
pathspec literal and from the repository's top, and a root whose path git and the caller spell
differently is refused rather than guessed at (`repository_prefix`). Read any other way, a
change could make the path empty — a symlinked root, a directory named like pathspec magic —
and pass as the change that adds the configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from stayfixed import fsops
from stayfixed.errors import Failure, Refusal
from stayfixed.gitenv import NO_ANSWER, answer_bytes, git_run, in_work_tree

NOT_A_REPOSITORY = (
    "the project root is not inside a git repository, so it has no base to compare with"
)
ROOT_UNANSWERED = (
    "git gave no answer about the repository the project root is in, so its base cannot be "
    f"read: {NO_ANSWER}, or git refused the repository (a checkout of dubious ownership, a "
    "worktree whose git directory is gone)"
)
ROOT_DOT_DOT = (
    "the project root is given with a `..` component, and `..` after a component that is a link "
    "is not the directory the spelling names, so the base's stayfixed.toml could be looked for "
    "in the wrong place; pass the root by its real path, with no `..`"
)
ROOT_THROUGH_SYMLINK = (
    "the project root is reached through a symlink, or git spells its path differently from the "
    "caller, so the base's stayfixed.toml would be looked for in the wrong place; pass the root by "
    "its real path"
)


def repository_top(root: Path) -> Path:
    """The top of the work tree git finds from `root`, as git spells it."""
    code, out = git_run(root, "rev-parse", "--show-toplevel")
    if code != 0:
        raise Failure(ROOT_UNANSWERED if in_work_tree(root) else NOT_A_REPOSITORY)
    return Path(out.rstrip("\n"))


def repository_prefix(root: Path) -> str:
    """The project root's path inside its repository, `""` at the top or `"a/b/"` below it: git's
    spelling, which is refused unless it is also the caller's."""
    lexical = root.absolute()
    if ".." in lexical.parts:
        raise Refusal(ROOT_DOT_DOT)
    code, out = git_run(lexical, "rev-parse", "--show-toplevel", "--show-prefix")
    if code != 0:
        # Read off the disk, as git finds a repository: git refuses a checkout of dubious
        # ownership exactly as it refuses a directory outside any repository.
        raise Failure(ROOT_UNANSWERED if in_work_tree(lexical) else NOT_A_REPOSITORY)
    top, _, prefix = out.partition("\n")
    # The HIGHEST ancestor that resolves to the top, not the nearest: a component linked back
    # to the top (`app -> .`) resolves to the top as well, and a spelling read below it skips it.
    chain = (*reversed(lexical.parents), lexical)
    ancestor = next((path for path in chain if path.resolve() == Path(top)), None)
    if ancestor is None:
        raise Refusal(ROOT_THROUGH_SYMLINK)
    below = lexical.parts[len(ancestor.parts) :]
    linked = any(fsops.is_symlink(ancestor.joinpath(*below[: n + 1])) for n in range(len(below)))
    spelled = "".join(f"{part}/" for part in below)
    if linked or spelled != prefix.rstrip("\n"):
        raise Refusal(ROOT_THROUGH_SYMLINK)
    return spelled


def committed_document(
    root: Path, commit: str, name: str, *, prefix: str, failed: Callable[[int], Exception]
) -> bytes | None:
    """The bytes `commit` holds at `<prefix><name>`, or `None` when git listed nothing there.

    `prefix` is `repository_prefix(root)`. Any git failure raises what `failed` builds from
    git's exit code: "git did not answer" is never "no copy". The bytes are the ones git printed,
    so each caller reads them as UTF-8 the way the loader reads the tree's copy: the text
    `git_run` decoded with the filesystem's codec is neither refused nor read the same where that
    codec is latin-1 (Linux under a latin-1 locale), because every byte decodes.
    """
    path = f"{prefix}{name}"
    # Literal: git reads a pathspec starting `:/` as "from the top", so under a directory named
    # `:` the listing would look elsewhere, answer nothing, and make the change the bootstrap.
    # No `--` after `--end-of-options`: every argument past it is literal, and a `--` there is a
    # path, which listed a top-level file of that name.
    code, listed = git_run(
        root,
        "--literal-pathspecs",
        "ls-tree",
        "--full-tree",
        "--name-only",
        "--end-of-options",
        commit,
        path,
    )
    if code != 0:
        raise failed(code)
    if not listed:
        return None
    code, text = git_run(root, "cat-file", "blob", "--end-of-options", f"{commit}:{path}")
    if code != 0:
        raise failed(code)
    return answer_bytes(text)
