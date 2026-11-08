"""What `overlay_sync` reports about the overlay's own repository, and why it declares no mutation.

**No entry in `mutations/` for this module, stated rather than left silent.** Every value here
comes from `git` itself under constant arguments — `status --porcelain` and
`rev-list --count @{upstream}..HEAD`, in the overlay root this machine recorded — and nothing
downstream reads the answer as permission: `attach/hooks.py` turns it into one session line and
`doctor` into one row, both advisory, and neither gates an exit code or a write. Its two guards
are `code != 0 -> asked=False`, which keeps "git could not be asked" apart from "there is nothing
to report" and which the last case below asserts, and `isdigit()` before `int()`, which keeps a
reader that must answer for every input from raising into a handler whose backstop would take the
whole result with it. `mutations/` is for load-bearing guards — a containment check, a trust
gate, a refusal something reads as permission — and breaking either of these costs a line of a
nudge, so there is none here.
"""

from __future__ import annotations

from pathlib import Path

from drybag.overlay.api import Sync, overlay_sync
from tests.gitfixture import git, needs_git


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "overlay"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# overlay\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "chore: first")
    return root


@needs_git
def test_a_clean_repository_with_no_upstream_reports_no_upstream(tmp_path: Path) -> None:
    assert overlay_sync(_repo(tmp_path)) == Sync(dirty=0, ahead=None, asked=True)


@needs_git
def test_an_untracked_file_counts_as_uncommitted(tmp_path: Path) -> None:
    # A note the owner wrote and never added is exactly the change the other machine will
    # not see. Mutation (comment): `--untracked-files=no` -> this reddens.
    root = _repo(tmp_path)
    (root / "note.md").write_text("x\n", encoding="utf-8")
    assert overlay_sync(root).dirty == 1


@needs_git
def test_commits_ahead_of_the_upstream_are_counted(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-q", "-u", "origin", "main")
    assert overlay_sync(root).ahead == 0
    (root / "README.md").write_text("# overlay\n\nmore\n", encoding="utf-8")
    git(root, "commit", "-qam", "docs: more")
    assert overlay_sync(root) == Sync(dirty=0, ahead=1, asked=True)


def test_a_directory_git_cannot_answer_for_is_not_asked(tmp_path: Path) -> None:
    assert overlay_sync(tmp_path / "nowhere").asked is False
