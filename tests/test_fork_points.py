"""`gitenv.fork_points`: every commit HEAD forked from a base at, or why they are not known.

The question `plan` asks of git about a base. Its own tests say what an answer means to it;
these pin the answer itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from drybag import gitenv
from drybag.gitenv import DISJOINT, NO_ANSWER, SHALLOW, ForkUnknown, fork_points
from tests.gitfixture import answer_shallow_check, criss_cross, dated, git, needs_git


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "state.txt").write_text("before\n", encoding="utf-8")
    git(root, "add", "-A")
    dated(root, 1, "commit", "-q", "-m", "first")
    return root


@needs_git
def test_every_merge_base_is_named_in_git_s_order(tmp_path: Path) -> None:
    # A criss-cross has two, and the one git picks alone comes first. Mutation (declared):
    # `--all` dropped -> only git's pick is named.
    root = _repo(tmp_path)
    shape = criss_cross(root, lambda: (root / "state.txt").write_text("after\n", "utf-8"))
    assert fork_points(root, shape.base) == [shape.side, shape.fixed]


@needs_git
def test_a_shallow_clone_is_not_known(tmp_path: Path) -> None:
    # Mutation (declared): the shallow answer ignored -> the clone's tip is named.
    root = _repo(tmp_path)
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", "--branch", "main", root.as_uri(), str(shallow))
    assert fork_points(shallow, "origin/main") == ForkUnknown(SHALLOW, answered=True)


@needs_git
@pytest.mark.parametrize(
    ("code", "unknown"),
    [
        (-1, ForkUnknown(NO_ANSWER, answered=False)),
        (-9, ForkUnknown(NO_ANSWER, answered=False)),
        (128, ForkUnknown("git exited 128", answered=True)),
    ],
    ids=["no-answer", "signalled", "refused"],
)
def test_a_shallow_check_git_does_not_answer_is_not_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, unknown: ForkUnknown
) -> None:
    # Read as "not shallow", a shallow clone would go on to the older merge base it can see. A
    # git a signal ended answered nothing either, whatever number `subprocess` gives it.
    # Mutations (declared): the shallow check's failure ignored -> the real merge base is named;
    # only `-1` read as no answer -> the signalled case reads as a refusal.
    root = _repo(tmp_path)
    answer_shallow_check(monkeypatch, code)
    assert fork_points(root, "HEAD") == unknown


@needs_git
def test_a_base_that_shares_no_commit_is_not_known_and_says_so(tmp_path: Path) -> None:
    # Mutation (declared): no merge base read as none to compare -> `[]`.
    root = _repo(tmp_path)
    git(root, "checkout", "-q", "--orphan", "unrelated")
    git(root, "commit", "-q", "-m", "no shared history")
    other = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "-f", "main")
    assert fork_points(root, other) == ForkUnknown(DISJOINT, answered=True)


@needs_git
@pytest.mark.parametrize(
    ("code", "unknown"),
    [(-9, ForkUnknown(NO_ANSWER, answered=False)), (None, ForkUnknown("git exited 128", True))],
    ids=["signalled", "missing-ref"],
)
def test_a_merge_base_git_does_not_give_is_not_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int | None, unknown: ForkUnknown
) -> None:
    root = _repo(tmp_path)
    if code is not None:
        real = gitenv.git_run

        def ended(where: Path, *args: str, **kwargs: Any) -> tuple[int, str]:
            return (code, "") if args[0] == "merge-base" else real(where, *args, **kwargs)

        monkeypatch.setattr(gitenv, "git_run", ended)
    assert fork_points(root, "refs/remotes/origin/main") == unknown
