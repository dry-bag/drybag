"""The four values `init --yes` reads off a repository without asking, and where each came from."""

from __future__ import annotations

from pathlib import Path

import pytest

from stayfixed.errors import Refusal
from stayfixed.project.detect import Detected, detect
from tests.gitfixture import git, needs_git
from tests.project.repos import repository

MIXED_CASE = "git@github.com:Owner/Widget.git"


@needs_git
def test_the_name_comes_from_origin_lower_cased_and_stripped(tmp_path: Path) -> None:
    assert detect(repository(tmp_path, origin=MIXED_CASE)).name == "widget"
    gadget = repository(tmp_path / "b", origin="https://example.com/Owner/Gadget")
    assert detect(gadget).name == "gadget"
    # Lower-cased before `.git` is stripped, so an upper-case suffix goes too. Mutation (by
    # hand): strip, then lower-case -> `widget.git`.
    upper = repository(tmp_path / "d", origin="https://github.com/Owner/Widget.GIT")
    assert detect(upper).name == "widget"
    # No origin: the directory name, the branch checked out, and every other value the default
    # it falls back to, each saying so.
    assert detect(repository(tmp_path / "c", origin=None, directory="Local")) == Detected(
        "local",
        "main",
        {"name": "directory name", "base_branch": "current branch"},
    )


@needs_git
def test_the_base_branch_is_the_remotes_head_when_it_is_known(tmp_path: Path) -> None:
    root = repository(tmp_path, origin=MIXED_CASE)
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
    found = detect(root)
    assert found.base_branch == "develop" and found.sources["base_branch"] == "origin/HEAD"


@needs_git
def test_a_remote_head_outside_the_branch_grammar_is_reported_as_the_default(
    tmp_path: Path,
) -> None:
    # `origin/HEAD` is written by `git clone` from what the remote says, so a branch named with
    # a backtick reaches this checkout and would reach `init --questions`' card and the workflow
    # `init` renders around it. Mutation (oracle): the grammar check reduced to "is it empty" ->
    # the branch comes back as detected and this reddens.
    root = repository(tmp_path, origin=MIXED_CASE)
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/`id`")
    found = detect(root)
    assert (found.base_branch, found.sources["base_branch"]) == ("main", "default")


def _clone_on_develop(tmp_path: Path, *, remote: str = "origin") -> Path:
    """A clone whose `<remote>/HEAD` names `refs/remotes/<remote>/develop`, as `git clone` leaves
    it."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-q", "-b", "develop")
    git(upstream, "commit", "-q", "--allow-empty", "-m", "one")
    git(tmp_path, "clone", "-q", "-o", remote, str(upstream), "clone")
    return tmp_path / "clone"


@needs_git
@pytest.mark.parametrize("shadow", ["tag", "branch"])
def test_a_ref_named_like_the_remote_branch_never_reaches_the_base_branch(
    tmp_path: Path, shadow: str
) -> None:
    # git shortens a ref only as far as it stays unambiguous, so with a tag or a local branch
    # named `origin/develop`, `symbolic-ref --short` answered `remotes/origin/develop`, which
    # passed the grammar and was written as the base branch: a workflow that never ran and a
    # base no command could resolve. The clone carries the tag. Mutation (oracle): `mutations/`'s
    # "origin/HEAD is read in its short form" -> both cases come back `remotes/origin/develop`.
    root = _clone_on_develop(tmp_path)
    if shadow == "tag":
        git(root, "tag", "origin/develop")
    else:
        git(root, "branch", "origin/develop")
    found = detect(root)
    assert (found.base_branch, found.sources["base_branch"]) == ("develop", "origin/HEAD")
    assert not found.head_refused


@needs_git
def test_a_remote_head_outside_the_remote_s_namespace_is_reported_as_the_default(
    tmp_path: Path,
) -> None:
    # `origin/HEAD` pointed by hand at a local branch: `refs/heads/develop` passes the branch
    # grammar whole, so only the exact `refs/remotes/origin/` prefix decides. Mutation (oracle):
    # `mutations/`'s "a remote head outside refs/remotes/origin/ is read whole" ->
    # `refs/heads/develop` comes back as the base branch.
    root = _clone_on_develop(tmp_path)
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/heads/develop")
    found = detect(root)
    assert (found.base_branch, found.sources["base_branch"]) == ("main", "default")
    assert found.head_refused


@needs_git
def test_with_no_remote_head_the_base_branch_is_the_branch_checked_out(tmp_path: Path) -> None:
    # A repository nobody cloned has no `origin/HEAD`, and one on `develop` had `main` written as
    # its base and a workflow that never ran for its own pull requests. Mutation (oracle):
    # `mutations/`'s "no remote head leaves the default whatever is checked out" -> `main`,
    # `default`.
    root = repository(tmp_path, origin=None)
    git(root, "symbolic-ref", "HEAD", "refs/heads/develop")
    found = detect(root)
    assert (found.base_branch, found.sources["base_branch"]) == ("develop", "current branch")
    assert not found.head_refused


FEATURE = "chore/adopt-stayfixed"


def _adopting(tmp_path: Path, shape: str) -> Path:
    """A repository on the feature branch an adoption is made on: created here and pushed to
    `origin` or to `upstream` (a remote, no `origin/HEAD`), never pushed (no remote), cloned (an
    `origin/HEAD` naming `develop`), or cloned with `-o upstream` (`upstream/HEAD` naming
    `develop`, and no `origin`)."""
    if shape == "cloned":
        root = _clone_on_develop(tmp_path)
    elif shape == "cloned-as-upstream":
        root = _clone_on_develop(tmp_path, remote="upstream")
    else:
        root = repository(tmp_path, origin=None)
        git(root, "commit", "-q", "--allow-empty", "-m", "one")
    if shape in ("pushed", "pushed-to-upstream"):
        remote = "origin" if shape == "pushed" else "upstream"
        bare = tmp_path / f"{remote}.git"
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
        git(root, "remote", "add", remote, str(bare))
        git(root, "push", "-q", "-u", remote, "main")
    git(root, "checkout", "-q", "-b", FEATURE)
    return root


@needs_git
@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ("pushed", ("main", "default", True)),
        ("pushed-to-upstream", ("main", "default", True)),
        ("cloned-as-upstream", ("main", "default", True)),
        ("unpushed", (FEATURE, "current branch", False)),
        ("cloned", ("develop", "origin/HEAD", False)),
    ],
)
def test_a_feature_branch_is_the_base_only_where_there_is_no_remote_at_all(
    tmp_path: Path, shape: str, expected: tuple[str, str, bool]
) -> None:
    # A repository created here and pushed with `git push -u origin main` has an `origin` and no
    # `origin/HEAD` (until `git clone`, `git remote set-head`, or a `git fetch` from git 2.48 on
    # records one), and it is adopted from a feature branch: taking the branch checked out wrote
    # the feature branch as the base, so the workflow gated it and `assess` compared the branch
    # with itself. The same holds for a repository whose only remote is `upstream`, pushed or
    # cloned with `-o upstream`: a remote is there, and only `origin/HEAD` is read. With any
    # remote the default stands and is flagged for the note; with none, the branch checked out
    # is all there is to go on. Mutations (oracle): `mutations/`'s "a remote with no origin/HEAD
    # takes the branch checked out" -> all three remote shapes come back as the feature branch;
    # "only an origin remote keeps the default" -> the two `upstream` shapes do.
    found = detect(_adopting(tmp_path, shape))
    base_branch, source, unrecorded = expected
    assert (found.base_branch, found.sources["base_branch"]) == (base_branch, source)
    assert (found.head_unrecorded, found.head_refused) == (unrecorded, False)
    assert not found.remotes_unknown


@needs_git
def test_a_repository_whose_remotes_git_cannot_list_keeps_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Whether there is a remote is the whole question the checked-out branch hangs on, so a `git
    # remote` that gave no answer is not "no remote": the default stands, flagged for a note of
    # its own. Mutation (oracle): `mutations/`'s "remotes git cannot list read as none" -> the
    # feature branch comes back.
    from stayfixed.gitenv import git_run as real

    root = _adopting(tmp_path, "unpushed")

    def unanswered(where: Path, *args: str, **kwargs: object) -> tuple[int, str]:
        return (-1, "") if args[0] == "remote" else real(where, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("stayfixed.project.detect.git_run", unanswered)
    found = detect(root)
    assert (found.base_branch, found.sources["base_branch"]) == ("main", "default")
    assert (found.remotes_unknown, found.head_unrecorded) == (True, False)


@needs_git
@pytest.mark.parametrize("head", ["detached", "outside-the-grammar"])
def test_a_checked_out_branch_nothing_can_name_leaves_the_default(
    tmp_path: Path, head: str
) -> None:
    # A detached `HEAD` answers no branch, and `a+b` is a branch git accepts and the grammar
    # does not: both leave the default, and neither is a remote head to report as refused.
    # Mutation (oracle): `mutations/`'s "the checked-out branch skips the grammar" -> `a+b` comes
    # back.
    root = repository(tmp_path, origin=None)
    git(root, "commit", "-q", "--allow-empty", "-m", "one")
    if head == "detached":
        git(root, "checkout", "-q", "--detach")
    else:
        git(root, "checkout", "-q", "-b", "a+b")
    found = detect(root)
    assert (found.base_branch, found.sources["base_branch"]) == ("main", "default")
    assert not found.head_refused


@needs_git
def test_a_name_outside_the_grammar_is_refused_without_being_quoted(tmp_path: Path) -> None:
    # `+` is outside `PROJECT_NAME` (`_` is not — the grammar admits it). Mutation (oracle):
    # interpolate the value into the refusal -> the `not in` reddens.
    root = repository(tmp_path, origin="git@github.com:Owner/My+Repo.git")
    with pytest.raises(Refusal) as caught:
        detect(root)
    assert "[project] name" in str(caught.value) and "my+repo" not in str(caught.value).lower()


@needs_git
def test_leniently_a_name_outside_the_grammar_is_not_derivable(tmp_path: Path) -> None:
    # The same name, asked for rather than refused: `init --questions` leaves it to the person,
    # and never offers the repository's bytes as the default.
    found = detect(repository(tmp_path, origin="git@github.com:Owner/My+Repo.git"), lenient=True)
    assert (found.name, found.sources["name"]) == ("", "not derivable")
