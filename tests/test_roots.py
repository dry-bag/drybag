"""`ledger.code_roots`, contained: which entries every walk takes, an entry folded the way a
directory is written, and each entry no walk takes, named with its reason. The walks that add up
what they find under these roots are pinned beside their own modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.config.schema import Config
from stayfixed.roots import (
    NOT_A_DIRECTORY,
    NOT_CONTAINED,
    ROOT_ITSELF,
    contained_roots,
    dropped_roots,
)
from tests.gitfixture import git, needs_git

CONFIG = """
[stayfixed]
version = "0.1.0"
enforced = ["docs", "bugs", "plan", "commit", "trail"]
preset = "recommended"
profile = ""
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
release_branch = "main"

[ledger]
code_roots = ["src", "tests"]
"""


def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "chore: seed")
    return root


def config(root: Path) -> Config:
    return load(root, machine=root.parent / "absent.toml")


@needs_git
def test_a_code_root_spelled_with_a_trailing_or_leading_slash_is_still_walked(
    tmp_path: Path,
) -> None:
    """`"src/"` and `"./tests"` are how many people write a directory, and they were dropped.

    `contained()` took on the write's component rule, which refuses a trailing `/`, a doubled
    `/` and a leading `./` because the engine cannot write through them. A code root is only
    walked, and `contained_roots` caught the refusal and moved on — so both entries left the
    hygiene counts and the citation roots with nothing saying so. They are folded before the
    question now.

    Oracle: `mutations/`'s "a code root spelled with a slash is dropped again".
    """
    root = repo(tmp_path)
    (root / "tests").mkdir()
    (root / CONFIG_FILE).write_text(
        CONFIG.replace('code_roots = ["src", "tests"]', 'code_roots = ["src/", ".//tests"]'),
        encoding="utf-8",
    )
    assert contained_roots(root, config(root)) == [root / "src", root / "tests"]


@needs_git
@pytest.mark.parametrize(
    ("roots", "dropped"),
    [
        ('["."]', [(".", ROOT_ITSELF)]),
        ('["./"]', [("./", ROOT_ITSELF)]),
        ('["src", "lib"]', [("lib", NOT_A_DIRECTORY)]),
        ('["../shared"]', [("../shared", NOT_CONTAINED)]),
        ('["src/", "./src"]', []),
    ],
    ids=["dot", "dot-slash", "missing", "outside", "folded"],
)
def test_each_code_root_no_walk_takes_is_named_with_its_reason(
    tmp_path: Path, roots: str, dropped: list[tuple[str, str]]
) -> None:
    """Every entry `contained_roots` leaves out, in config order, with why; a spelling the fold
    takes in is walked and not named. `../shared` exists, so it is the containment that drops
    it and not the directory check."""
    root = repo(tmp_path)
    (root.parent / "shared").mkdir()
    (root / CONFIG_FILE).write_text(
        CONFIG.replace('code_roots = ["src", "tests"]', f"code_roots = {roots}"),
        encoding="utf-8",
    )
    assert dropped_roots(root, config(root)) == dropped
