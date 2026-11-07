"""`ledger.code_roots`, contained: which entries every walk takes, and an entry folded the way a
directory is written. The walks that add up what they find under these roots are pinned beside
their own modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.config.schema import Config
from stayfixed.roots import contained_roots

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"

[ledger]
code_roots = ["src", "tests"]
"""


def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    return root


def config(root: Path) -> Config:
    return load(root, machine=root.parent / "absent.toml")


def test_a_code_root_spelled_with_a_trailing_or_leading_slash_is_still_walked(
    tmp_path: Path,
) -> None:
    """`"src/"` and `"./tests"` are how many people write a directory, and they were dropped.

    `contained()` took on the write's component rule, which refuses a trailing `/`, a doubled
    `/` and a leading `./` because the engine cannot write through them. A code root is only
    walked, and `contained_roots` caught the refusal and moved on — so both entries left the
    mention and citation scans with nothing saying so. They are folded before the question now.

    Oracle: `mutations/`'s "a code root spelled with a slash is dropped again".
    """
    root = repo(tmp_path)
    (root / "tests").mkdir()
    (root / CONFIG_FILE).write_text(
        CONFIG.replace('code_roots = ["src", "tests"]', 'code_roots = ["src/", ".//tests"]'),
        encoding="utf-8",
    )
    assert contained_roots(root, config(root)) == [root / "src", root / "tests"]


@pytest.mark.parametrize(
    "roots", ['["src", "src/pkg"]', '["src/pkg", "src"]'], ids=["inside", "around"]
)
def test_no_directory_is_walked_twice(tmp_path: Path, roots: str) -> None:
    # Where git cannot list the files, `ledger.scan` walks each root and adds up what it finds:
    # with `["src", "src/pkg"]`, `bugs check` said one mention was "referenced 2 time(s)".
    # Mutations (oracle): `mutations/`'s "a code root inside a kept one is walked again" ->
    # `inside`; "a code root around a kept one leaves it walked" -> `around`.
    root = repo(tmp_path)
    (root / "src" / "pkg").mkdir()
    (root / CONFIG_FILE).write_text(
        CONFIG.replace('code_roots = ["src", "tests"]', f"code_roots = {roots}"),
        encoding="utf-8",
    )
    assert contained_roots(root, config(root)) == [root / "src"]
