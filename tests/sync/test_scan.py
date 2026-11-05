"""The secret scan: the gitleaks on `PATH`, and the three scans.

The job commits through a temporary index and never runs `git commit`, so the overlay's
pre-commit hooks do not run by themselves; this module runs the scan itself. The scanner is the
`gitleaks` the `PATH` of the one git environment finds, never pre-commit's build, and it must scan
the TEMPORARY index, not the real one. The stand-in in `conftest.py` answers as the real one does:
`git --pre-commit --staged` reads the index `GIT_INDEX_FILE` names, `git --log-opts=A..B` scans a
range, `stdin` scans what else a push sends, a JSON report names each finding's commit, the exit
is 1 for a finding and for a failed scan alike, and a failed scan leaves an empty report.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from stayfixed.sync import git as G
from stayfixed.sync import job as J
from stayfixed.sync import scan as S
from tests.sync.conftest import (
    LEAK,
    SLOW,
    Overlays,
    commit_all,
    context,
    git,
    gitleaks_on_path,
    head,
    init,
    memory_status,
    path_without_gitleaks,
    write,
)

# The `gitleaks` on this machine's `PATH`, when there is one: found before any fixture puts the
# stand-in first.
REAL = shutil.which("gitleaks")


@pytest.fixture
def scanner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return gitleaks_on_path(tmp_path / "bin", monkeypatch)


# -- finding the scanner --------------------------------------------------------------------------


def test_the_scanner_is_the_gitleaks_on_path(
    tmp_path: Path, scanner: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert S.gitleaks() == scanner

    # The `PATH` every git is given: a relative entry, which would find one planted at the root
    # of the repository a hook runs in, is not on it.
    planted = gitleaks_on_path(tmp_path / "work" / "tools", monkeypatch)
    monkeypatch.chdir(tmp_path / "work")
    monkeypatch.setenv("PATH", f"tools{os.pathsep}{path_without_gitleaks(tmp_path / 'g')}")
    assert planted.exists() and S.gitleaks() is None


def test_no_gitleaks_on_path_is_scan_unavailable_with_the_remedy(overlays: Overlays) -> None:
    # Mutation (oracle): `mutations/`'s "no scanner, and the commit goes on".
    a = overlays.a
    overlays.gitleaks.unlink()
    write(a, "common/memory/new.md", "a note\n")
    before = head(a)

    ctx = context(overlays, a)
    assert J.commit_memory(ctx) is None
    assert [(notice.state, notice.detail) for notice in ctx.notices] == [
        ("scan_unavailable", S.NO_SCANNER)
    ]
    assert head(a) == before and "?? common/memory/new.md" in memory_status(a)

    write(a, "common/memory/by-hand.md", "a note committed by hand\n")
    commit_all(a, "memory: by hand")
    stopped = J.push(context(overlays, a), head(a, "origin/main"))
    assert stopped is not None and (stopped.state, stopped.detail) == (
        "scan_unavailable",
        S.NO_SCANNER,
    )
    assert head(overlays.bare, "main") == before
    assert S.NO_SCANNER.endswith("install gitleaks on the PATH the sessions run with")


def test_a_pre_commit_database_chooses_no_scanner(
    overlays: Overlays, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A session's `PRE_COMMIT_HOME` naming a database whose row for the overlay's pin is a script
    # that finds nothing: the scanner is still the `gitleaks` on `PATH`, and the secret is found.
    a = overlays.a
    rev = "83d9cd684c87d95d656c1458ef04895a7f1cbd8e"
    write(
        a,
        ".pre-commit-config.yaml",
        f"repos:\n  - repo: https://github.com/gitleaks/gitleaks\n    rev: {rev}\n"
        "    hooks:\n      - id: gitleaks\n",
    )
    commit_all(a, "pin the hook")
    blind = write(tmp_path / "pc" / "repo", "golangenv-default/bin/gitleaks", "#!/bin/sh\nexit 0\n")
    blind.chmod(0o755)
    store = tmp_path / "pre-commit-home"
    store.mkdir()
    with contextlib.closing(sqlite3.connect(store / "db.db")) as db, db:
        db.execute("CREATE TABLE repos (repo TEXT, ref TEXT, path TEXT)")
        db.execute(
            "INSERT INTO repos VALUES (?, ?, ?)",
            ("https://github.com/gitleaks/gitleaks", rev, str(tmp_path / "pc" / "repo")),
        )
    monkeypatch.setenv("PRE_COMMIT_HOME", str(store))
    write(a, "common/memory/leak.md", f"key = {LEAK}\n")

    ctx = context(overlays, a)
    assert J.commit_memory(ctx) is None

    assert [notice.state for notice in ctx.notices] == ["hook_failed"]
    assert "common/memory/leak.md" in str(ctx.notices[0].detail)


# -- the scans ------------------------------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    repo = init(tmp_path / "repo")
    write(repo, "common/memory/a.md", "a note\n")
    commit_all(repo, "base")
    return repo


def _temporary_index(repo: Path, tmp_path: Path, name: str = "sync.index") -> Path:
    index = tmp_path / name
    git(repo, "read-tree", "HEAD", "--index-output", str(index))
    return index


def _stage_in(repo: Path, index: Path, relative: str) -> None:
    assert G.git(repo, "add", "--", relative, index_file=index).code == 0


def _leak_staged(repo: Path, tmp_path: Path) -> Path:
    write(repo, "common/memory/leak.md", f"key = {LEAK}\n")
    index = _temporary_index(repo, tmp_path)
    _stage_in(repo, index, "common/memory/leak.md")
    return index


def _argv(binary: Path) -> list[str]:
    return json.loads((binary.parent / "argv.json").read_text())  # type: ignore[no-any-return]


def _seen(binary: Path) -> dict[str, object]:
    return json.loads((binary.parent / "seen.json").read_text())  # type: ignore[no-any-return]


def test_a_staged_scan_reads_the_temporary_index_and_finds_the_leak(
    tmp_path: Path, scanner: Path
) -> None:
    repo = _repo(tmp_path)
    index = _leak_staged(repo, tmp_path)

    result = S.scan_index(repo, index, scanner, SLOW)

    assert (result.ok, result.timed_out) == (False, False)
    assert "common/memory/leak.md" in result.detail and LEAK not in result.detail
    args = _argv(scanner)
    assert args[0] == "git" and {"--pre-commit", "--staged", "--redact"} <= set(args)
    assert (
        git(repo, "status", "--porcelain") == "?? common/memory/leak.md\n"
    )  # the real index never saw it


def test_the_owners_staged_work_is_not_scanned(tmp_path: Path, scanner: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "common/claude/hooks/wip.py", f"token = '{LEAK}'\n")
    git(repo, "add", "common/claude/hooks/wip.py")  # the owner's staged work, secret and all
    write(repo, "common/memory/b.md", "a clean note\n")
    index = _temporary_index(repo, tmp_path)
    _stage_in(repo, index, "common/memory/b.md")

    result = S.scan_index(repo, index, scanner, SLOW)

    assert result.ok is True, result.detail
    assert result.finding_commit is None


def test_a_finding_names_rule_file_and_commit_never_the_secret(
    tmp_path: Path, scanner: Path
) -> None:
    repo = _repo(tmp_path)
    base = head(repo)
    write(repo, "common/memory/one.md", "clean\n")
    commit_all(repo, "one")
    write(repo, "common/memory/leak.md", f"{LEAK}\n")
    leaky = commit_all(repo, "leak")
    write(repo, "common/memory/two.md", "clean\n")
    tip = commit_all(repo, "two")

    result = S.scan_range(repo, base, tip, scanner, SLOW)

    assert (result.ok, result.finding_commit) == (False, leaky)
    assert result.detail == f"fake-secret in common/memory/leak.md (commit {leaky})"
    assert f"--log-opts={base}..{tip}" in _argv(scanner) and "--redact" in _argv(scanner)

    clean = S.scan_range(repo, base, f"{leaky}^", scanner, SLOW)
    assert (clean.ok, clean.detail, clean.finding_commit) == (True, "no leaks found", None)


def test_a_long_list_of_findings_is_cut_and_counted(tmp_path: Path, scanner: Path) -> None:
    repo = _repo(tmp_path)
    base = head(repo)
    for number in range(S.DETAIL_LINES + 2):
        write(repo, f"common/memory/leak{number}.md", f"{LEAK}\n")
    tip = commit_all(repo, "leaks")

    result = S.scan_range(repo, base, tip, scanner, SLOW)

    assert len(result.detail.splitlines()) == S.DETAIL_LINES + 1
    assert result.detail.splitlines()[-1] == "... 2 more"


def test_a_failed_scan_is_not_a_finding(tmp_path: Path, scanner: Path) -> None:
    """Exit 1 with an empty report is a scan that did not run, which must not read as a pass
    and must not name a commit either."""
    (scanner.parent / "mode").write_text("fail")
    repo = _repo(tmp_path)

    result = S.scan_range(repo, "HEAD", "HEAD", scanner, SLOW)

    assert (result.ok, result.finding_commit, result.timed_out) == (False, None, False)
    assert "failed to scan" in result.detail


def test_a_scanner_that_is_not_there_fails_the_scan(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    result = S.scan_range(repo, "HEAD", "HEAD", tmp_path / "gone" / "gitleaks", SLOW)

    assert (result.ok, result.timed_out) == (False, False)
    assert result.detail


def test_a_scan_that_outlives_its_bound_is_timed_out(tmp_path: Path, scanner: Path) -> None:
    (scanner.parent / "mode").write_text("sleep")
    repo = _repo(tmp_path)

    started = time.monotonic()
    result = S.scan_range(repo, "HEAD", "HEAD", scanner, 1)

    assert (result.ok, result.timed_out) == (False, True)
    assert time.monotonic() - started < 25  # not the stand-in's 30 s


def test_rules_and_ignores_come_from_head(
    tmp_path: Path, scanner: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A confused agent silencing a pre-commit false positive -- an untracked `.gitleaks.toml`,
    a `GITLEAKS_CONFIG` -- must not also disarm the unattended scan."""
    repo = _repo(tmp_path)
    write(repo, ".gitleaks.toml", "allow-all\n")
    monkeypatch.setenv(
        "GITLEAKS_CONFIG", str(write(tmp_path / "elsewhere", "rules.toml", "allow-all\n"))
    )
    index = _leak_staged(repo, tmp_path)

    result = S.scan_index(repo, index, scanner, SLOW)

    assert result.ok is False and "common/memory/leak.md" in result.detail
    assert _seen(scanner)["rules_text"] == S.DEFAULTS.decode()  # none committed: the defaults

    write(repo, ".gitleaks.toml", "# the owner's committed rules\n")
    git(repo, "add", ".gitleaks.toml")
    git(repo, "commit", "-q", "-m", "rules")
    write(repo, ".gitleaks.toml", "allow-all\n")  # and loosened again, uncommitted

    assert S.scan_index(repo, index, scanner, SLOW).ok is False
    assert _seen(scanner)["rules_text"] == "# the owner's committed rules\n"


def test_an_uncommitted_gitleaksignore_at_the_root_stops_the_scan(
    tmp_path: Path, scanner: Path
) -> None:
    """gitleaks reads the scanned directory's `.gitleaksignore` whatever it is told, so one that
    is not the committed file stops the scan instead of silencing it."""
    repo = _repo(tmp_path)
    index = _leak_staged(repo, tmp_path)
    write(repo, ".gitleaksignore", "ignore-all\n")

    result = S.scan_index(repo, index, scanner, SLOW)

    assert (result.ok, result.finding_commit) == (False, None)
    assert ".gitleaksignore" in result.detail and "not the committed one" in result.detail
    assert not (scanner.parent / "argv.json").exists()  # never ran

    write(repo, ".gitleaksignore", "# the owner's committed ignores\n")
    git(repo, "add", ".gitleaksignore")
    git(repo, "commit", "-q", "-m", "ignores")

    assert S.scan_index(repo, index, scanner, SLOW).ok is False  # the leak is still found
    assert _seen(scanner)["ignore_text"] == "# the owner's committed ignores\n"


def test_a_gitleaksignore_that_cannot_be_read_stops_the_scan(tmp_path: Path, scanner: Path) -> None:
    repo = _repo(tmp_path)
    index = _leak_staged(repo, tmp_path)
    (repo / ".gitleaksignore").mkdir()

    result = S.scan_index(repo, index, scanner, SLOW)

    assert (result.ok, result.finding_commit) == (False, None)
    assert "cannot be read" in result.detail
    assert not (scanner.parent / "argv.json").exists()


def test_no_committed_rules_scan_on_gitleaks_defaults(tmp_path: Path, scanner: Path) -> None:
    repo = _repo(tmp_path)

    result = S.scan_range(repo, "HEAD", "HEAD", scanner, SLOW)

    assert result.ok is True, result.detail
    config = _argv(scanner)[_argv(scanner).index("--config") + 1]
    assert _seen(scanner)["rules"] == config
    assert _seen(scanner)["rules_text"] == "[extend]\nuseDefault = true\n"


def test_gitleaks_variables_are_dropped(
    tmp_path: Path, scanner: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "GITLEAKS_CONFIG", str(write(tmp_path / "elsewhere", "rules.toml", "allow-all\n"))
    )
    monkeypatch.setenv("GITLEAKS_LOG_LEVEL", "debug")
    repo = _repo(tmp_path)

    S.scan_range(repo, "HEAD", "HEAD", scanner, SLOW)

    assert _seen(scanner)["env"] == []


def test_gitleaks_reads_a_patch_with_no_signature_lines_and_no_colour(
    tmp_path: Path, scanner: Path
) -> None:
    """Its own `git log -p` and `git diff` give it a patch to parse: a `log.showSignature` in the
    owner's configuration would put a verification into it, and a `color.ui = always` escape
    codes, which leave its parser no file to scan and the scan passing. Mutations (oracle):
    `mutations/`'s "gitleaks reads a log with signature lines", "the scan's git colours its patch"
    and "the scan's git colours its diff"."""
    repo = _repo(tmp_path)
    for key, value in (("log.showSignature", "true"), ("color.ui", "always")):
        git(repo, "config", key, value)
    git(repo, "config", "color.diff", "always")
    index = _temporary_index(repo, tmp_path)
    expected = {"log.showSignature": "false", "color.ui": "false", "color.diff": "false"}

    S.scan_range(repo, "HEAD", "HEAD", scanner, SLOW, env={"GIT_CONFIG_COUNT": "0"})
    assert json.loads((scanner.parent / "git_config.json").read_text()) == expected
    S.scan_index(repo, index, scanner, SLOW)
    assert json.loads((scanner.parent / "git_config.json").read_text()) == expected


@pytest.mark.skipif(REAL is None, reason="no gitleaks on PATH")
def test_the_real_gitleaks_finds_a_token_whatever_colour_the_owner_asks_for(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End to end with the real gitleaks: its parser reads git's patch text, and a coloured one
    # made the scan pass and the token travel. Skipped where no gitleaks is on PATH.
    assert REAL is not None
    monkeypatch.setattr(S, "gitleaks", lambda: Path(REAL))
    a = overlays.a
    git(a, "config", "color.ui", "always")
    token = "ghp_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tV9wX1yZ3bC5"  # split: no scanner flags this file
    write(a, "common/memory/pasted.md", f"the token is {token}\n")

    state = J._one_job(context(overlays, a))

    assert state.outcome.state != "ok", state.outcome
    assert "pasted.md" not in git(overlays.bare, "ls-tree", "-r", "--name-only", "main")


def test_the_report_is_written_under_the_scratch_directory_and_removed(
    tmp_path: Path, scanner: Path
) -> None:
    repo = _repo(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    S.scan_range(repo, "HEAD", "HEAD", scanner, SLOW, scratch=scratch)

    args = _argv(scanner)
    report = Path(args[args.index("--report-path") + 1])
    assert report.parent.parent == scratch
    assert list(scratch.iterdir()) == []  # the scan's directory went with it


def test_the_metadata_scan_names_the_commit(tmp_path: Path, scanner: Path) -> None:
    repo = _repo(tmp_path)
    commits = [
        ("a" * 40, "author A <a@x> 1 +0000\n\nclean\n"),
        ("b" * 40, f"author B <b@x> 1 +0000\n\ntoken {LEAK}\n"),
    ]

    result = S.scan_commits(repo, commits, scanner, SLOW)

    assert (result.ok, result.finding_commit) == (False, "b" * 40)
    assert "b" * 40 in result.detail and LEAK not in result.detail
    assert _argv(scanner)[0] == "stdin"
    assert S.scan_commits(repo, commits[:1], scanner, SLOW).ok is True


def test_a_metadata_scan_reads_nothing_at_the_overlays_root(tmp_path: Path, scanner: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, ".gitleaksignore", "ignore-all\n")
    write(repo, ".gitleaks.toml", "allow-all\n")

    result = S.scan_commits(repo, [("b" * 40, f"token {LEAK}\n")], scanner, SLOW)

    assert (result.ok, result.finding_commit) == (False, "b" * 40)


def test_a_finding_in_the_whole_but_in_no_single_commit_names_none(
    tmp_path: Path, scanner: Path
) -> None:
    repo = _repo(tmp_path)
    half = LEAK[: len(LEAK) // 2]
    # Each commit alone is clean; only the two joined carry the token.
    commits = [("a" * 40, f"{half}"), ("b" * 40, f"{LEAK[len(half) :]}\n")]

    result = S.scan_commits(repo, commits, scanner, SLOW)

    assert (result.ok, result.finding_commit) == (False, None)
    assert "no one commit" in result.detail
