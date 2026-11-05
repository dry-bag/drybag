"""The secret scan: the gitleaks on `PATH`, over content alone.

The scanner is the `gitleaks` the `PATH` of the one git environment finds, never pre-commit's
build. Every scan is `gitleaks dir .` over the items' bytes written as files `1`, `2`, ... in the
job's scratch, so no note's name and no file at the overlay's root reaches it. The stand-in in
`conftest.py` answers as the real one does: a JSON report naming each finding's file, exit 1 for
a finding and for a failed scan alike, an empty report for a failed one; and it skips a file whose
name holds `allowlisted`, as a path allowlist would.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from stayfixed.sync import job as J
from stayfixed.sync import scan as S
from stayfixed.sync.state import SCRATCH
from tests.sync.conftest import (
    LEAK,
    SLOW,
    Overlays,
    commit_all,
    context,
    git,
    gitleaks_on_path,
    head,
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


# -- the scan -------------------------------------------------------------------------------------


def _argv(binary: Path) -> list[str]:
    return json.loads((binary.parent / "argv.json").read_text())  # type: ignore[no-any-return]


def _seen(binary: Path) -> dict[str, str]:
    return json.loads((binary.parent / "seen.json").read_text())  # type: ignore[no-any-return]


def _scan(scanner: Path, tmp_path: Path, items: list[tuple[str, bytes]], **kwargs: Any) -> Any:
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    return S.scan(items, scanner, kwargs.get("rules"), kwargs.get("timeout", SLOW), scratch)


def test_a_finding_names_rule_and_label_never_the_secret(tmp_path: Path, scanner: Path) -> None:
    items = [("common/memory/one.md", b"clean\n"), ("common/memory/leak.md", f"{LEAK}\n".encode())]

    result = _scan(scanner, tmp_path, items)

    assert (result.ok, result.timed_out, result.found) == (False, False, ("common/memory/leak.md",))
    assert result.detail == "fake-secret in common/memory/leak.md"
    assert _argv(scanner)[:2] == ["dir", "."] and "--redact" in _argv(scanner)

    clean = _scan(scanner, tmp_path, items[:1])
    assert (clean.ok, clean.detail, clean.found) == (True, "no leaks found", ())


def test_a_long_list_of_findings_is_cut_and_counted(tmp_path: Path, scanner: Path) -> None:
    items = [(f"leak{number}", f"{LEAK}\n".encode()) for number in range(S.DETAIL_LINES + 2)]

    result = _scan(scanner, tmp_path, items)

    assert len(result.found) == S.DETAIL_LINES + 2
    assert len(result.detail.splitlines()) == S.DETAIL_LINES + 1
    assert result.detail.splitlines()[-1] == "... 2 more"


def test_a_failed_scan_is_not_a_finding(tmp_path: Path, scanner: Path) -> None:
    """Exit 1 with an empty report is a scan that did not run, which must not read as a pass
    and must not name a file either."""
    (scanner.parent / "mode").write_text("fail")

    result = _scan(scanner, tmp_path, [("a", f"{LEAK}\n".encode())])

    assert (result.ok, result.found, result.timed_out) == (False, (), False)
    assert "failed to scan" in result.detail


def test_a_scanner_that_is_not_there_fails_the_scan(tmp_path: Path) -> None:
    result = _scan(tmp_path / "gone" / "gitleaks", tmp_path, [("a", b"a\n")])

    assert (result.ok, result.timed_out) == (False, False)
    assert result.detail


def test_a_scan_that_outlives_its_bound_is_timed_out(tmp_path: Path, scanner: Path) -> None:
    (scanner.parent / "mode").write_text("sleep")

    started = time.monotonic()
    result = _scan(scanner, tmp_path, [("a", b"a\n")], timeout=1)

    assert (result.ok, result.timed_out) == (False, True)
    assert time.monotonic() - started < 25  # not the stand-in's 30 s


def test_no_committed_rules_scan_on_gitleaks_defaults(tmp_path: Path, scanner: Path) -> None:
    assert _scan(scanner, tmp_path, [("a", b"a\n")]).ok is True
    config = _argv(scanner)[_argv(scanner).index("--config") + 1]
    assert _seen(scanner)["rules"] == config
    assert _seen(scanner)["rules_text"] == "[extend]\nuseDefault = true\n"

    _scan(scanner, tmp_path, [("a", b"a\n")], rules=b"# the owner's committed rules\n")
    assert _seen(scanner)["rules_text"] == "# the owner's committed rules\n"


def test_the_report_and_the_items_are_written_under_the_scratch_directory_and_removed(
    tmp_path: Path, scanner: Path
) -> None:
    # Mutation (oracle): `mutations/`'s "a scan's report is written in TMPDIR".
    _scan(scanner, tmp_path, [("a", b"a\n")])

    args = _argv(scanner)
    scratch = (tmp_path / "scratch").resolve()
    assert Path(args[args.index("--report-path") + 1]).resolve().parent.parent == scratch
    assert Path(_seen(scanner)["source"]).parent.parent == scratch
    assert list(scratch.iterdir()) == []  # the scan's directory went with it


def test_the_metadata_scan_names_the_commit(tmp_path: Path, scanner: Path) -> None:
    # Mutation (oracle): `mutations/`'s "the metadata scan reads nothing".
    commits = [
        ("a" * 40, b"author A <a@x> 1 +0000\n\nclean\n"),
        ("b" * 40, f"author B <b@x> 1 +0000\n\ntoken {LEAK}\n".encode()),
    ]

    result = _scan(scanner, tmp_path, commits)

    assert (result.ok, result.found) == (False, ("b" * 40,))
    assert "b" * 40 in result.detail and LEAK not in result.detail


@pytest.mark.skipif(REAL is None, reason="no gitleaks on PATH")
def test_the_real_gitleaks_finds_a_token_under_allowlisted_names(tmp_path: Path) -> None:
    # The four notes of the plan's measurement: the default rules' path allowlist skips the last
    # three by name when gitleaks is shown their paths, and the scan shows it none.
    assert REAL is not None
    token = "ghp_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tV9wX1yZ3bC5"  # split: no scanner flags this file
    names = [
        "common/memory/plain.md",
        "common/memory/gitleaks.toml-tips.md",
        "projects/node_modules/memory/note.md",
        "projects/a/memory/vendor/bundle/note.md",
    ]

    result = _scan(
        Path(REAL), tmp_path, [(name, f"the token is {token}\n".encode()) for name in names]
    )

    assert (result.ok, result.timed_out) == (False, False), result.detail
    assert sorted(result.found) == sorted(names)
    assert token not in result.detail


# -- what the job scans ---------------------------------------------------------------------------


def _leak_note(overlays: Overlays, name: str = "common/memory/leak.md") -> str:
    write(overlays.a, name, f"key = {LEAK}\n")
    return name


def _commit_notice(overlays: Overlays) -> Any:
    ctx = context(overlays, overlays.a)
    assert J.commit_memory(ctx) is None
    assert len(ctx.notices) <= 1, ctx.notices
    return ctx.notices[0] if ctx.notices else None


def _push(overlays: Overlays) -> Any:
    return J.push(context(overlays, overlays.a), head(overlays.a, "origin/main"))


def test_a_note_name_never_exempts_it_from_the_scan(overlays: Overlays) -> None:
    # A note named as a path allowlist names (the stand-in skips such a name, as the real
    # default rules skip `gitleaks.toml-tips.md`): its bytes are scanned under a neutral name.
    # Mutation (oracle): `mutations/`'s "a scanned file is named after its note".
    a, before = overlays.a, head(overlays.bare, "main")
    name = _leak_note(overlays, "common/memory/allowlisted.md")

    notice = _commit_notice(overlays)
    assert notice is not None and notice.state == "hook_failed" and name in notice.detail

    git(a, "add", "--", name)
    leaky = commit_all(a, "memory: by hand")
    stopped = _push(overlays)
    assert stopped is not None and stopped.state == "secret_found", stopped
    assert f"{leaky} {name}" in stopped.detail and LEAK not in stopped.detail
    assert head(overlays.bare, "main") == before


def test_a_scan_reads_no_file_at_the_overlays_root(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A confused agent silencing a pre-commit false positive -- a working-tree `.gitleaks.toml`
    # allowing everything, a `.gitleaksignore` -- disarms no scan, from the job's own working
    # directory, the overlay. Mutations (oracle): `mutations/`'s "a scan runs at the overlay's
    # root" and "the scan reads the rules from the working tree".
    a = overlays.a
    monkeypatch.chdir(a)
    write(a, ".gitleaks.toml", "allow-all\n")
    write(a, ".gitleaksignore", "ignore-all\n")
    name = _leak_note(overlays)

    notice = _commit_notice(overlays)

    assert notice is not None and notice.state == "hook_failed" and name in notice.detail
    source = Path(_seen(overlays.gitleaks)["source"])
    assert source.parent.parent == (overlays.state_dir / SCRATCH).resolve()


def test_committed_rules_apply(overlays: Overlays) -> None:
    a = overlays.a
    write(a, ".gitleaks.toml", "allow-all\n")
    commit_all(a, "the owner's rules")
    git(a, "push", "-q", "origin", "main")  # outside memory: pushed by hand, as the owner would
    name = _leak_note(overlays)

    assert _commit_notice(overlays) is None
    assert git(a, "log", "-1", "--format=%s").startswith("memory: 1 notes")
    assert _push(overlays) is None
    assert name in git(overlays.bare, "ls-tree", "-r", "--name-only", "main")


def test_a_textconv_cannot_hide_a_note(overlays: Overlays) -> None:
    # A `diff` driver whose `textconv` prints nothing shows gitleaks no patch at all; the scan
    # reads the bytes, not a diff.
    a = overlays.a
    (a / ".git" / "info").mkdir(exist_ok=True)
    (a / ".git" / "info" / "attributes").write_text("*.md diff=hide\n")
    git(a, "config", "diff.hide.textconv", "true")
    name = _leak_note(overlays)

    notice = _commit_notice(overlays)
    assert notice is not None and notice.state == "hook_failed" and name in notice.detail

    git(a, "add", "--", name)
    commit_all(a, "memory: by hand")
    stopped = _push(overlays)
    assert stopped is not None and stopped.state == "secret_found", stopped
