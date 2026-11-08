from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.findings import LISTED_LIMIT
from tests.gitfixture import git


def invoke(argv: list[str]) -> int:
    return run(argv, parser=build_parser(discover_registrars()))


CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"

# On, since the preset leaves the check off: what these cases judge is the check itself.
[commit_messages]
attribution_check = true
"""

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def repo(tmp_path: Path, *messages: str) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "chore: seed")
    git(root, "tag", "base")
    for index, message in enumerate(messages):
        (root / f"f{index}.txt").write_text("x\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", message)
    return root


@needs_git
def test_commit_check_passes_a_clean_range(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, "feat: one", "fix(x): two")
    argv = [
        "commit",
        "check",
        "--range",
        "base..HEAD",
        "--root",
        str(root),
        "--machine",
        str(tmp_path / "m.toml"),
    ]
    assert invoke(argv) == 0
    assert "OK: 2 commit message(s) checked" in capsys.readouterr().out


@needs_git
def test_commit_check_names_the_offence_not_the_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, "fix: dirty\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n")
    argv = [
        "commit",
        "check",
        "--range",
        "base..HEAD",
        "--root",
        str(root),
        "--machine",
        str(tmp_path / "m.toml"),
        "--json",
    ]
    assert invoke(argv) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["violations"][0]["offences"] == [
        {"line": 3, "label": "attribution trailer naming an AI tool"}
    ]
    assert "noreply@anthropic.com" not in json.dumps(out)


@needs_git
def test_commit_check_refuses_a_range_git_cannot_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path)
    argv = [
        "commit",
        "check",
        "--range",
        "nope..HEAD",
        "--root",
        str(root),
        "--machine",
        str(tmp_path / "m.toml"),
    ]
    assert invoke(argv) == 2
    assert "refused" in capsys.readouterr().err


def test_commit_strip_rewrites_the_file_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        "fix: thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n", encoding="utf-8"
    )
    assert invoke(["commit", "strip", str(message)]) == 0
    assert message.read_text(encoding="utf-8") == "fix: thing\n"
    assert "stripped 1" in capsys.readouterr().out


def test_commit_strip_leaves_a_message_that_is_only_attribution(tmp_path: Path) -> None:
    # Emptying it would abort the commit with a confusing "empty message"; CI explains instead.
    message = tmp_path / "COMMIT_EDITMSG"
    original = "Co-Authored-By: Claude <noreply@anthropic.com>\n"
    message.write_text(original, encoding="utf-8")
    assert invoke(["commit", "strip", str(message)]) == 0
    assert message.read_text(encoding="utf-8") == original


def test_commit_strip_keeps_the_files_mode(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("fix: t\n\nGenerated with Codex\n", encoding="utf-8")
    message.chmod(0o640)
    assert invoke(["commit", "strip", str(message)]) == 0
    assert (message.stat().st_mode & 0o777) == 0o640


def test_commit_strip_never_writes_through_a_symlink(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    real = tmp_path / "real.txt"
    real.write_text("fix: t\n\nGenerated with Codex\n", encoding="utf-8")
    link = tmp_path / "COMMIT_EDITMSG"
    link.symlink_to(real)
    assert invoke(["commit", "strip", str(link)]) == 2
    # `write_atomically` replaces the *link* with a regular file rather than following it, so
    # the target is untouched with or without the guard; what the guard preserves is the link.
    assert link.is_symlink()


def test_commit_strip_reports_a_message_file_that_is_not_utf_8_as_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `except OSError` does not catch `UnicodeDecodeError`, so a legitimately non-UTF-8 message
    # file (git has `i18n.commitEncoding` for exactly this) reached the CLI frame as
    # `internal error: UnicodeDecodeError` and exit 2 — the code this project's callers are told
    # never to read as permission. It is a file the command cannot read, like the `OSError`
    # beside it, so it is exit 1. Both assertions matter: the exit code, and that the offending
    # byte the exception names does not travel into the message.
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_bytes("fix: thing\n\nCo-Authored-By: Claude\n".encode("cp1251") + b"\xff\xfe")
    assert invoke(["commit", "strip", str(message)]) == 1
    err = capsys.readouterr().err
    assert "UnicodeDecodeError" not in err
    assert "0xff" not in err


def test_commit_strip_refuses_an_option_shaped_path() -> None:
    assert invoke(["commit", "strip", "--", "-weird"]) == 2


def test_commit_strip_keeps_gits_trailing_comment_block_intact(tmp_path: Path) -> None:
    # A realistic `prepare-commit-msg` file — subject, blank, an attribution trailer,
    # then git's own comment block (`core.commentChar` default `#`). `offending_lines` judges
    # only the message's *trailing attribution block* (commit.py's docstring), and in this file
    # the last paragraph is git's comment block, which is not attribution and therefore ends
    # that block where it starts — so a strip that does not split the comment block off first
    # would no-op here, on exactly the path the hook exists for.
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        "fix: thing\n"
        "\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\n"
        "\n"
        "# Please enter the commit message for your changes. Lines starting\n"
        "# with '#' will be ignored, and an empty message aborts the commit.\n"
        "#\n"
        "# On branch main\n"
        "# Changes to be committed:\n"
        "#\tnew file:   widget.py\n"
        "#\n",
        encoding="utf-8",
    )
    assert invoke(["commit", "strip", str(message)]) == 0
    result = message.read_text(encoding="utf-8")
    assert result == (
        "fix: thing\n"
        "\n"
        "# Please enter the commit message for your changes. Lines starting\n"
        "# with '#' will be ignored, and an empty message aborts the commit.\n"
        "#\n"
        "# On branch main\n"
        "# Changes to be committed:\n"
        "#\tnew file:   widget.py\n"
        "#\n"
    )
    assert "Co-Authored-By" not in result


# Everything git appends below the message under `commit.verbose = true`, captured from a real
# `prepare-commit-msg` hook in a repository with the key set, and retyped. Kept separate from the
# message above it so the assertion that it comes back byte for byte is against a fixed literal.
VERBOSE_TAIL = (
    "\n"
    "# Please enter the commit message for your changes. Lines starting\n"
    "# with '#' will be ignored, and an empty message aborts the commit.\n"
    "#\n"
    "# On branch main\n"
    "# Changes to be committed:\n"
    "#\tmodified:   a.txt\n"
    "#\n"
    "# ------------------------ >8 ------------------------\n"
    "# Do not modify or remove the line above.\n"
    "# Everything below it will be ignored.\n"
    "diff --git a/a.txt b/a.txt\n"
    "index 4cb29ea..6addb9b 100644\n"
    "--- a/a.txt\n"
    "+++ b/a.txt\n"
    "@@ -1,3 +1,4 @@\n"
    " one\n"
    "-two\n"
    "+TWO\n"
    " three\n"
    "+four\n"
)
VERBOSE_EDITMSG = "fix: thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n" + VERBOSE_TAIL


def test_commit_strip_still_strips_when_commit_verbose_appends_the_diff(tmp_path: Path) -> None:
    """One config key turned the whole local layer into a silent no-op. Measured, not foreseen.

    `commit.verbose = true` makes git append the staged diff below a scissors line, and a diff's
    lines begin with `diff`, `+`, `-`, `@@` or a space — none of which is a comment or a blank.
    The walk back from the end of the file stopped at the first of them, the whole file read as
    "message", the attribution block was no longer trailing, and nothing was stripped:

        A) CONTROL, no verbose      : stripped 2 attribution line(s); trailer stored: 0
        B) SAME, commit.verbose=true: trailer in the stored message: 1   (DEFECT)

    The fixture is git's own output, captured from a `prepare-commit-msg` hook in a real
    repository with `commit.verbose` set, and retyped here.

    Both assertions are needed. "The trailer is gone" alone is satisfied by a split that threw
    the diff away, which would be a corruption rather than a no-op; the second is against a fixed
    literal and says every byte git appended comes back. The diff is what the earlier
    comment-block test cannot pin, because without `verbose` there is none.
    """
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(VERBOSE_EDITMSG, encoding="utf-8")
    assert invoke(["commit", "strip", str(message)]) == 0
    result = message.read_text(encoding="utf-8")
    assert "Co-Authored-By" not in result
    assert result == "fix: thing\n" + VERBOSE_TAIL


def test_a_scissors_line_is_found_by_its_marker_not_by_gits_english_sentence(
    tmp_path: Path,
) -> None:
    # The two lines under the scissors ("Do not modify or remove the line above.") go through
    # gettext, so a rule keyed on that wording stops splitting in a translated checkout and the
    # hook silently no-ops there. The ruler and its `>8` are not translated. This fixture is the
    # same file with those two lines in another language; the answer must not move.
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        VERBOSE_EDITMSG.replace(
            "# Do not modify or remove the line above.\n# Everything below it will be ignored.\n",
            "# Ne modifiez pas et ne supprimez pas la ligne ci-dessus.\n"
            "# Tout ce qui suit sera ignore.\n",
        ),
        encoding="utf-8",
    )
    assert invoke(["commit", "strip", str(message)]) == 0
    result = message.read_text(encoding="utf-8")
    assert result.startswith("fix: thing\n\n# Please enter")
    assert "Co-Authored-By" not in result


@needs_git
def test_commit_check_names_at_most_the_listed_limit_of_offences(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A range holds any number of commits, so the offences on the line are bounded in number by
    # nothing: it counts every commit, names the first `LISTED_LIMIT` offences, and says how many
    # more, and `--json`'s `violations` carries every one. Mutation (oracle): `mutations/`'s "commit
    # check names every offence" -> this reddens.
    dirty = "fix: dirty\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
    root = repo(tmp_path, *[dirty] * (LISTED_LIMIT + 2))
    argv = ["commit", "check", "--range", "base..HEAD", "--root", str(root)]
    assert invoke([*argv, "--machine", str(tmp_path / "m.toml")]) == 1
    line = capsys.readouterr().out.strip()
    assert line.startswith(f"FAIL: {LISTED_LIMIT + 2} of {LISTED_LIMIT + 2} commit message(s)")
    assert line.count("[attribution trailer naming an AI tool]") == LISTED_LIMIT
    assert "[attribution trailer naming an AI tool], and 2 more. " in line
