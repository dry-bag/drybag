"""`stayfixed init --yes`'s answers: each reaches the document this run creates.

The answers are given here as `Given` straight to `init`; `tests/project/test_command.py` gives
them as flags through the real parser, built from `init --questions --json`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
    # Each flag replaces one default. Mutation (by hand): `_tables` ignores `given.agents` ->
    # the agents assertion reddens (the repository carries no harness directory, so the
    # default is both).
    root = repository(tmp_path)
    _init(
        root,
        tmp_path,
        Given(
            name="gadget",
            base_branch="develop",
            agents=("codex",),
            memory_mode="in-repo",
        ),
    )
    config = load(root, machine=tmp_path / "absent.toml")
    assert config.project.name == "gadget"
    assert (config.project.base_branch, config.project.release_branch) == ("develop", "develop")
    assert config.stayfixed.agents == ("codex",)
    assert config.memory.mode == "in-repo"


@needs_git
@pytest.mark.parametrize(
    ("profile", "markers", "expected"),
    [("python", False, "python"), ("", True, "")],
    ids=["named", "none-over-markers"],
)
def test_a_profile_answer_replaces_what_the_markers_suggest(
    tmp_path: Path, profile: str, markers: bool, expected: str
) -> None:
    # `""` is an answer: no profile, even where the root carries a shipped profile's markers.
    # Mutation (by hand): `profile = given.profile or found.profile` -> the `none-over-markers`
    # case writes `python` and reddens.
    root = repository(tmp_path)
    if markers:
        (root / "pyproject.toml").write_text("[project]\nname = 'widget'\n", encoding="utf-8")
    _init(root, tmp_path, Given(profile=profile))
    assert load(root, machine=tmp_path / "absent.toml").stayfixed.profile == expected
