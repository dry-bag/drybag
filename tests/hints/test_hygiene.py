"""What could have falsified a red run and belongs to no stack, named before the diff is blamed.

A stack's own faults -- Python's stale bytecode -- are its profile's, and are pinned beside it
(`tests/profiles/python/test_hygiene.py`); which profile speaks after which command is
`tests/profiles/test_hints.py`'s.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.config.schema import Config
from stayfixed.guards.roots import (
    NOT_A_DIRECTORY,
    NOT_CONTAINED,
    ROOT_ITSELF,
    contained_roots,
    dropped_roots,
)
from stayfixed.hints.hygiene import dirty_count, notice, red_exit, simple_commands
from tests.gitfixture import git

# Per test: `red_exit`, `notice` and `simple_commands` are pure, and a module-level skip would
# void them.
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

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
def test_a_dirty_tree_is_counted(tmp_path: Path) -> None:
    # A TRACKED file modified after its commit, never merely an untracked one: `dirty_count`
    # runs `git` under `gitenv.scrubbed_env()`, which keeps the real `HOME` by design, so the
    # developer's own `status.showUntrackedFiles = no` or `core.excludesFile` could hide an
    # untracked file and make this assertion environment-dependent. Reddened by mutating
    # `dirty_count`'s `sum(...)` to `return 0`; measured.
    root = repo(tmp_path)
    (root / "src" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    assert dirty_count(root) == 1


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


@needs_git
def test_a_clean_tree_with_nothing_from_a_hint_says_nothing(tmp_path: Path) -> None:
    # Reddened by mutating `notice`'s `if not lines: return None` to `return LEAD`; measured.
    root = repo(tmp_path)
    assert notice(dirty_count(root), []) is None


@needs_git
def test_the_notice_carries_counts_and_no_root_names(tmp_path: Path) -> None:
    # Reddened by mutating `notice`'s `if dirty:` to `if False:`; measured.
    root = repo(tmp_path)
    (root / "src" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    text = notice(dirty_count(root), [])
    assert text is not None and "1 uncommitted change(s)" in text


def test_a_git_that_cannot_answer_is_none_not_zero(tmp_path: Path) -> None:
    # Reddened by mutating `dirty_count`'s `if code != 0: return None` to `return 0`; measured.
    # `None` and `0` are what `test hygiene` turns into exit 2 and exit 0, so collapsing them
    # reports an unjudgeable tree as clean.
    root = tmp_path / "not-a-repo"
    (root / "src").mkdir(parents=True)
    assert dirty_count(root) is None


def test_a_command_the_scanner_cannot_read_is_asked_of_no_hint() -> None:
    # The substring fallback is gone on purpose: guessing from the text of a command the scanner
    # cannot read would hand one stack's advice to whatever the text happens to name. Such a
    # run gets no note, which under-reports rather than misleads. Reddened by mutating
    # `simple_commands`'s `return []` for an unreadable command to `return [command.split()]`;
    # measured.
    assert simple_commands("pytest 'unbalanced") == []


def test_each_simple_command_is_unwrapped_to_its_own_program() -> None:
    # What every hint is handed: one argv per simple command, past assignments and the
    # scanner's wrappers, in the order the command line gives them; `uv run` up to the first
    # word a runner adapter recognises. Reddened by mutating `simple_commands`'s `words =
    # bashscan.command_words(segment, …)` to `words = segment`; measured.
    assert simple_commands("FOO=1 uv run --locked pytest -q && env cargo test -q") == [
        ["pytest", "-q"],
        ["cargo", "test", "-q"],
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"tool_response": {"exit_code": 1}}, 1),
        ({"tool_response": {"exit_code": 0}}, None),
        ({"tool_response": {"exit_code": True}}, None),
        ({"tool_response": {"stdout": "1 failed"}}, None),
        ({"error": "Exit code 2\nFAILED tests/x.py"}, 2),
        ({"error": "Exit code 0"}, None),
        ({"error": "Cannot find module"}, None),
        # Not in the ported table, added so `_EXIT_CODE_ERROR`'s anchoring is load-bearing:
        # unanchored, a number is read out of arbitrary captured stderr, and the documented
        # shape puts `Exit code N` at the very start of `error`. Note that swapping `.match`
        # for `.search` is a NO-OP while the pattern keeps `\A` — measured — so the mutation
        # this row reddens is `re.search(r"Exit code (\d+)", error)`, anchor dropped.
        ({"error": "FAILED tests/x.py\nExit code 2"}, None),
        # A run of digits no exit code has: read whole, `int()` raised past 4,300 of them, and
        # the note was lost to the error. It says nothing, as for any `error` it cannot read.
        # Mutation: `mutations/`'s "the red-run hint reads an exit code of any length".
        ({"error": "Exit code " + "9" * 5000}, None),
        ({}, None),
    ],
)
def test_red_exit_reads_both_payload_shapes(raw: dict[str, object], expected: int | None) -> None:
    # The source read `tool_response.exit_code`; the hooks reference documents the
    # Bash `tool_response` without one and a non-zero exit arriving as `PostToolUseFailure`'s
    # `error` field. Both are read, so the notice is not keyed on a field one harness lacks.
    # Reddened three ways, each measured: dropping the `not isinstance(code, bool)` test (the
    # `True` row), dropping the whole `error` branch (the `Exit code 2` row), and dropping the
    # pattern's `\A` (the row above).
    assert red_exit(raw) == expected
