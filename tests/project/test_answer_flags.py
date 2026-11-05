"""`stayfixed init --yes`'s answers: each reaches the document this run creates.

The answers are given here as `Given` straight to `init`; `tests/project/test_command.py` gives
them as flags through the real parser, built from `init --questions --json`.
"""

from __future__ import annotations

from pathlib import Path

from stayfixed.config.loader import load
from stayfixed.project.init import Given, InitReport, init
from tests.gitfixture import needs_git
from tests.project.repos import repository


def _init(
    root: Path,
    tmp_path: Path,
    given: Given,
) -> InitReport:
    return init(root, machine=tmp_path / "absent.toml", yes=True, dry_run=False, given=given)


@needs_git
def test_each_answer_reaches_the_document_this_run_creates(tmp_path: Path) -> None:
    # Each flag replaces one default.
    root = repository(tmp_path)
    _init(
        root,
        tmp_path,
        Given(
            name="gadget",
            base_branch="develop",
            memory_mode="in-repo",
        ),
    )
    config = load(root, machine=tmp_path / "absent.toml")
    assert config.project.name == "gadget"
    assert config.project.base_branch == "develop"
    assert config.memory.mode == "in-repo"
