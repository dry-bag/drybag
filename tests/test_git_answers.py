"""Every site that asks git a question reads the answer through `gitenv.git_run`, exactly.

Six sites ran `git` through a `subprocess.run(text=True)` of their own and decoded its answer
strictly in the locale's codec: one byte that was not UTF-8 in the answer — a checkout path, an
`origin` URL, a hooks path, a dirty file's name — raised `UnicodeDecodeError` out of the command,
and every hook, as an internal error. `git_run` decodes losslessly in the filesystem's codec, and
each site now decides what an answer it cannot use as text means: a path is compared with and
opened on the disk as it is, a count counts it, and a value that must be written into a UTF-8
file is refused by name before anything is written.

The bytes are planted in `.git/config` or the index, or printed by a stand-in `git`, so every case
runs where the disk cannot hold such a name (APFS refuses one).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from stayfixed.attach.write import attach, main_checkout_of
from stayfixed.errors import Refusal
from stayfixed.gitenv import GitUnavailable, Unasked, _git_toplevel, hooks_dir, origin_remote
from stayfixed.guards.commit import commits_in
from stayfixed.hints.hygiene import dirty_count
from stayfixed.overlay.sync import overlay_sync
from stayfixed.project.detect import NOT_DERIVABLE, detect
from tests.attach.test_write import RULE, _attachable
from tests.cli import cli
from tests.gitfixture import git, needs_git, plant_path, stand_in_git
from tests.hints.test_hygiene import repo
from tests.project.repos import repository
from tests.runners import Recorder

# An `origin` URL whose last byte is latin-1, and the `str` the filesystem's codec spells it as.
LATIN1_URL = b"https://example.com/caf\xe9"
DECODED_URL = os.fsdecode(LATIN1_URL)


def _append(path: Path, raw: bytes) -> None:
    with path.open("ab") as handle:
        handle.write(raw)


def _stand_in_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, printed: bytes) -> None:
    """A `git` the product runs (`stand_in_git`) that prints `printed` for any question."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    octal = "".join(f"\\{byte:03o}" for byte in printed)
    (bin_dir / "git").write_text(f"#!/bin/sh\nprintf '{octal}'\n", encoding="utf-8")
    (bin_dir / "git").chmod(0o755)
    stand_in_git(monkeypatch, bin_dir / "git")


def test_the_hook_path_reads_a_checkout_path_that_is_not_utf_8_as_that_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `checkout_root` feeds every hook decision, and its git fallback decoded strictly: on
    # Linux a checkout under a latin-1 directory made every hook an internal error, which
    # PreToolUse turns into a refusal of every tool call (reproduced in a Linux container with
    # a payload that names no `cwd`). The answer is the path on disk, byte for byte — a trailing
    # space included, which the old `strip()` took off. Mutation (declared, on `gitenv`): the
    # decode made strict again -> this reddens.
    _stand_in_git(tmp_path, monkeypatch, b"/checkouts/caf\xe9 \n")
    assert _git_toplevel(tmp_path) == Path(os.fsdecode(b"/checkouts/caf\xe9 "))


@needs_git
def test_an_origin_url_that_is_not_utf_8_is_answered_as_itself(tmp_path: Path) -> None:
    # Reproduced: `printf '[remote "origin"]\n\turl = https://x/caf\xe9\n' >> .git/config`, then
    # `stayfixed init --questions` and `init --yes` both ended as `internal error:
    # UnicodeDecodeError`. The answer is the URL as the filesystem's codec spells it, so it can
    # still be compared with a recorded one; it never equals one read out of a TOML file.
    # Mutation (declared, on `gitenv`): the decode made strict again -> this reddens.
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    _append(root / ".git" / "config", b'[remote "origin"]\n\turl = ' + LATIN1_URL + b"\n")
    assert origin_remote(root) == DECODED_URL
    # The name `init` suggests from it is outside the name grammar, so it is asked for rather
    # than suggested, and refused by the grammar under `--yes`, never with the URL's bytes.
    assert (detect(root, lenient=True).name, detect(root, lenient=True).sources["name"]) == (
        "",
        NOT_DERIVABLE,
    )
    with pytest.raises(Refusal) as refused:
        detect(root)
    assert "caf" not in str(refused.value)


@needs_git
def test_a_git_that_fails_everything_is_not_a_repository_without_an_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both answers off one checkout with no `origin`: git that runs says "no such remote" with a
    # non-zero exit, which is `None`, and a git that exits non-zero for everything — the Xcode
    # shim with an unaccepted licence — must not read the same way, or the user is sent to
    # `stayfixed attach` about their own `git`. And its remedy is to check that `git` runs, never
    # to run the command again, which would repeat for ever. Mutations (declared): `mutations/`'s
    # "a broken git reads as a repository that answered" and "a broken git is told to run the
    # command again".
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    assert origin_remote(root) is None

    def broken(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 69, b"", b"You have not agreed to the licence\n")

    monkeypatch.setattr("stayfixed.gitenv.subprocess.run", broken)
    with pytest.raises(GitUnavailable, match=re.escape(Unasked.BROKEN.value)):
        origin_remote(root)


@needs_git
def test_init_questions_on_an_origin_url_that_is_not_utf_8_asks_and_does_not_crash(
    tmp_path: Path,
) -> None:
    # The command it was reproduced with, through the real parser. Mutation (declared, on
    # `gitenv`): the decode made strict again -> this reddens.
    code, out, err = cli(repository(tmp_path, origin=DECODED_URL), tmp_path, "init", "--questions")
    assert code == 0, err
    assert "internal error" not in err
    assert "caf" not in out


@needs_git
def test_a_hooks_path_that_is_not_utf_8_is_the_directory_git_names(tmp_path: Path) -> None:
    # `core.hooksPath` is the machine owner's to set, in any bytes; decoded strictly, `setup
    # --git-hooks`, `attach` and `doctor`'s pre-commit row all ended as an internal error. The
    # answer is the directory itself, so the hook lands where git will run it. Mutation
    # (declared, on `gitenv`): the decode made strict again -> this reddens.
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    _append(root / ".git" / "config", b"[core]\n\thooksPath = hooks-caf\xe9\n")
    assert hooks_dir(root) == root / os.fsdecode(b"hooks-caf\xe9")


@needs_git
def test_a_dirty_name_that_is_not_utf_8_is_counted_and_not_raised(tmp_path: Path) -> None:
    # `git status --porcelain` prints a name raw under `core.quotePath=false`, a common setting
    # for anyone whose names are not ASCII; decoded strictly, the red-run hint
    # became an internal error. Planted in the index, so the name is both added and missing
    # from the disk: one entry. Mutation (declared, on `gitenv`): the decode made strict again
    # -> this reddens.
    root = repo(tmp_path)
    git(root, "config", "core.quotePath", "false")
    plant_path(root, b"caf\xe9.py")
    assert dirty_count(root) == 1


@needs_git
def test_the_commit_range_is_read_in_utf_8_whatever_git_is_told_to_print(tmp_path: Path) -> None:
    # The range's messages are judged as UTF-8, and git prints a log in whatever
    # `i18n.logOutputEncoding` says — the machine owner's global configuration reaches it
    # through `HOME`. Under latin-1 output a plain `café` in a message arrived in bytes that are
    # not UTF-8 and the range was refused as unjudgeable. The log asks for UTF-8 by name.
    # Mutation (declared): drop `--encoding=UTF-8` from the argv -> this reddens.
    root = repo(tmp_path)
    git(root, "config", "i18n.logOutputEncoding", "ISO-8859-1")
    git(root, "commit", "-q", "--allow-empty", "-m", "fix: café")
    [commit] = commits_in(root, "HEAD~1..HEAD")
    assert commit.message.startswith("fix: café")


def _worktree_with_a_carriage_return(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    git(main, "commit", "-q", "--allow-empty", "-m", "chore: seed")
    linked = tmp_path / "wt\rx"
    git(main, "worktree", "add", "-q", "-b", "side", str(linked))
    return main, linked


@needs_git
def test_a_worktree_whose_path_holds_a_carriage_return_is_listed_by_its_own_path(
    tmp_path: Path,
) -> None:
    # `worktree list --porcelain` ends each line with `\n` and prints a path's `\r` raw, and
    # `str.splitlines()` breaks at both: measured, `attach` named a main checkout at `…/ma` for
    # one at `…/ma\rin`, a directory it then writes into. Lines are split where git ends them.
    # Mutation (declared): split with `splitlines()` again -> this reddens.
    main, linked = _worktree_with_a_carriage_return(tmp_path)
    odd = tmp_path / "ma\rin"
    odd.mkdir()
    git(odd, "init", "-q", "-b", "main")
    assert main_checkout_of(odd) == odd.resolve()
    assert main_checkout_of(linked) == main.resolve()


@needs_git
def test_attach_binds_an_origin_it_cannot_record_and_records_none(tmp_path: Path) -> None:
    # The records are UTF-8 TOML, and an `origin` URL in other bytes cannot be written into them:
    # read losslessly, it raised `UnicodeEncodeError` at the overlay record's write, after the
    # ignore region, the Codex rules, the settings merge and the ledger, and was then refused
    # above every write. The remote binds nothing now, so the binding is made and records none.
    from stayfixed import binding

    hooks = {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hello"}]}]}
    root, store, machine = _attachable(
        tmp_path, allow=(RULE,), hooks=hooks, codex="# a standing rule\n", origin=DECODED_URL
    )
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    found = binding.bound_project(root)
    assert found is not None and found.origin is None
    assert "remote" not in (store.parent / "project.toml").read_text(encoding="utf-8")


@needs_git
def test_a_dirty_name_holding_a_line_separator_is_one_entry(tmp_path: Path) -> None:
    # U+2028 is valid UTF-8, `status --porcelain` prints it raw under `core.quotePath=false`,
    # and `str.splitlines()` breaks at it: one planted name counted as two in the red-run
    # hint and in the overlay's sync row. Counted by the lines git wrote. Mutation (declared):
    # count with `splitlines()` again -> this reddens.
    root = repo(tmp_path)
    git(root, "config", "core.quotePath", "false")
    plant_path(root, "a\u2028b.py".encode())
    assert dirty_count(root) == 1
    assert overlay_sync(root).dirty == 1


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("https://user:s3cret@example.com/o/p.git", "https://example.com/o/p.git"),
        ("https://ghp_token@github.com/o/p", "https://github.com/o/p"),
        ("http://a:b@c@example.com/o/p", "http://example.com/o/p"),
        ("ssh://git:pw@example.com/o/p", "ssh://git@example.com/o/p"),
        ("ssh://git@example.com/o/p", "ssh://git@example.com/o/p"),
        ("git@example.com:o/p.git", "git@example.com:o/p.git"),
        ("https://example.com/o/p", "https://example.com/o/p"),
        ("https://example.com/o/p@v1", "https://example.com/o/p@v1"),
    ],
)
def test_an_origin_loses_its_credentials_and_keeps_an_ssh_user(url: str, kept: str) -> None:
    # A remote URL can carry a token as its userinfo (`https://user:token@host/…`), and `attach`
    # prints the origin and records it on this machine. Everything before the authority's last
    # `@` goes on every scheme but ssh, whose user (`git@`) is no secret and is part of how the
    # same remote is recognised; there only a password goes. The scp form carries no password.
    from stayfixed.gitenv import without_userinfo

    assert without_userinfo(url) == kept
