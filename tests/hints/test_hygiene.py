"""What could have falsified a red run and belongs to no stack, named before the diff is blamed.

Which failed command gets the note is `tests/hints/test_hooks.py`'s, through the handler.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE
from stayfixed.hints.hygiene import dirty_count, notice, red_exit, simple_commands
from tests.gitfixture import git

# Per test: `red_exit`, `notice` and `simple_commands` are pure, and a module-level skip would
# void them.
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
agents = ["claude"]

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
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "chore: seed")
    return root


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
def test_a_clean_tree_says_nothing(tmp_path: Path) -> None:
    # Reddened by mutating `notice`'s `if not dirty: return None` to `return LEAD`; measured.
    root = repo(tmp_path)
    assert notice(dirty_count(root)) is None


@needs_git
def test_the_notice_carries_counts_and_no_root_names(tmp_path: Path) -> None:
    # Reddened by mutating `notice`'s `if not dirty:` to `if True:`; measured.
    root = repo(tmp_path)
    (root / "src" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    text = notice(dirty_count(root))
    assert text is not None and "1 uncommitted change(s)" in text


def test_a_git_that_cannot_answer_is_none_not_zero(tmp_path: Path) -> None:
    # Reddened by mutating `dirty_count`'s `if code != 0: return None` to `return 0`; measured.
    # `None` and `0` are "could not tell" and "clean", so collapsing them reports an
    # unjudgeable tree as clean.
    root = tmp_path / "not-a-repo"
    (root / "src").mkdir(parents=True)
    assert dirty_count(root) is None


def test_a_command_the_scanner_cannot_read_is_no_test_run() -> None:
    # The substring fallback is gone on purpose: guessing from the text of a command the scanner
    # cannot read would take whatever the text happens to name for a test run. Such a run gets
    # no note, which under-reports rather than misleads. Reddened by mutating
    # `simple_commands`'s `return []` for an unreadable command to `return [command.split()]`;
    # measured.
    assert simple_commands("pytest 'unbalanced") == []


def test_each_simple_command_is_unwrapped_to_its_own_program() -> None:
    # What the runner table is asked: one argv per simple command, past assignments and the
    # scanner's wrappers, in the order the command line gives them; `uv run` up to the first
    # word the table reads as a test run. Reddened by mutating `simple_commands`'s `words =
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
