"""The secret scan: finding the overlay's pinned gitleaks build, and the three scans.

The job commits through a temporary index and never runs `git commit`, so the overlay's
pre-commit hooks do not run by themselves; this module runs the scan itself. The scanner is the
build pre-commit already made for the overlay's pinned hook -- found through pre-commit's own
database, never downloaded -- and it must scan the TEMPORARY index, not the real one. The
stand-in in `conftest.py` answers as the real build does: `git --pre-commit --staged` reads the
index `GIT_INDEX_FILE` names, `git --log-opts=A..B` scans a range, `stdin` scans what else a push
sends, a JSON report names each finding's commit, the exit is 1 for a finding and for a failed
scan alike, and a failed scan leaves an empty report.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import stayfixed
from stayfixed.sync import git as G
from stayfixed.sync import scan as S
from tests.sync.conftest import (
    DEFAULT_RULES,
    GITLEAKS_REPO,
    GITLEAKS_REV,
    LEAK,
    SLOW,
    build_gitleaks,
    commit_all,
    git,
    head,
    init,
    pre_commit_store,
    write,
)

OTHER_REV = "v8.0.0"


def _config(
    overlay: Path,
    *,
    rev: str = GITLEAKS_REV,
    language_version: str | None = None,
    default_golang: str | None = None,
) -> Path:
    overlay.mkdir(parents=True, exist_ok=True)
    version = f"        language_version: {language_version}\n" if language_version else ""
    defaults = f"default_language_version:\n  golang: {default_golang}\n" if default_golang else ""
    (overlay / ".pre-commit-config.yaml").write_text(
        f"# a comment\n{defaults}repos:\n"
        f"  - repo: {GITLEAKS_REPO}\n"
        f"    rev: {rev}  # frozen: v8.30.1\n"
        "    hooks:\n"
        "      - id: gitleaks\n"
        f"{version}"
        "\n  - repo: local\n    hooks:\n      - id: other\n"
        "        language_version: other\n",
        encoding="utf-8",
    )
    return overlay


class Machine:
    """A scratch cache holding pre-commit's database, and the environment that names it."""

    def __init__(self, root: Path) -> None:
        self.home = root / "home"
        self.cache = root / "cache"
        self.build_dir = root / "pc" / "repoA"
        self.env = {"XDG_CACHE_HOME": str(self.cache)}

    def row(self, *rows: tuple[str, str, Path]) -> None:
        pre_commit_store(self.cache, list(rows))

    def pinned(self, environment: str | None = "default", rev: str = GITLEAKS_REV) -> Path | None:
        """Register the pinned row, with a build in `environment` when one is named."""
        self.row((GITLEAKS_REPO, rev, self.build_dir))
        return None if environment is None else build_gitleaks(self.build_dir, environment)

    def binary(self, overlay: Path) -> Path | None:
        return S.gitleaks_binary(self.home, overlay, self.env)


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    return Machine(tmp_path)


# -- finding the build ----------------------------------------------------------------------------


def test_the_pin_is_read_from_the_overlays_config(tmp_path: Path) -> None:
    assert S.gitleaks_pin(_config(tmp_path / "plain")) == (GITLEAKS_REPO, GITLEAKS_REV, None)
    hook = _config(tmp_path / "hook", language_version="1.22")
    assert S.gitleaks_pin(hook) == (GITLEAKS_REPO, GITLEAKS_REV, "1.22")
    # The file's default applies where the hook says nothing, and the hook's own wins.
    assert S.gitleaks_pin(_config(tmp_path / "d", default_golang="1.21"))[2] == "1.21"  # type: ignore[index]
    both = _config(tmp_path / "both", default_golang="1.21", language_version="1.22")
    assert S.gitleaks_pin(both)[2] == "1.22"  # type: ignore[index]
    # `default` is pre-commit's "not set here": the next step decides.
    assert S.gitleaks_pin(_config(tmp_path / "e", language_version="default"))[2] is None  # type: ignore[index]
    # Another repository's hook never lends its `language_version`.
    assert S.gitleaks_pin(_config(tmp_path / "f"))[2] is None  # type: ignore[index]


def test_the_pin_in_the_template_the_overlay_ships_is_understood() -> None:
    template = Path(stayfixed.__file__).parent / "templates" / "overlay"

    pin = S.gitleaks_pin(template)

    assert pin is not None and pin[0] == GITLEAKS_REPO and pin[2] is None
    assert len(pin[1]) == 40  # a full commit sha: a tag is a name its owner can move


def test_a_config_without_gitleaks_or_without_a_file_has_no_pin(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    assert S.gitleaks_pin(overlay) is None
    (overlay / ".pre-commit-config.yaml").write_text("repos:\n  - repo: local\n    hooks: []\n")
    assert S.gitleaks_pin(overlay) is None
    (overlay / ".pre-commit-config.yaml").write_bytes(b"\xff\xfe")
    assert S.gitleaks_pin(overlay) is None


def test_the_binary_is_found_through_pre_commits_database(machine: Machine, tmp_path: Path) -> None:
    binary = machine.pinned("default")

    assert machine.binary(_config(tmp_path / "o")) == binary


def test_the_cache_follows_the_home_when_no_variable_names_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    directory = tmp_path / "pc" / "repoA"
    binary = build_gitleaks(directory)
    pre_commit_store(home / ".cache", [(GITLEAKS_REPO, GITLEAKS_REV, directory)])

    assert S.gitleaks_binary(home, _config(tmp_path / "o"), {}) == binary


def test_pre_commit_home_is_honoured(machine: Machine, tmp_path: Path) -> None:
    binary = machine.pinned("default")
    moved = tmp_path / "elsewhere"
    (machine.cache / "pre-commit").rename(moved)
    overlay = _config(tmp_path / "o")

    assert machine.binary(overlay) is None
    machine.env["PRE_COMMIT_HOME"] = str(moved)
    assert machine.binary(overlay) == binary


def test_no_row_for_the_pinned_rev_is_no_scanner(machine: Machine, tmp_path: Path) -> None:
    overlay = _config(tmp_path / "o")
    assert machine.binary(overlay) is None  # a machine where pre-commit never ran

    other = tmp_path / "pc" / "repoB"
    build_gitleaks(other)
    machine.row((GITLEAKS_REPO, OTHER_REV, other))  # an older rev is never a substitute
    assert machine.binary(overlay) is None


def test_the_pinned_rev_row_is_the_one_chosen(machine: Machine, tmp_path: Path) -> None:
    """Two gitleaks rows, as a machine that upgraded has: only the configured `rev` counts."""
    older = tmp_path / "pc" / "repoB"
    pinned = machine.build_dir
    older_build = build_gitleaks(older)
    pinned_build = build_gitleaks(pinned)
    machine.row((GITLEAKS_REPO, OTHER_REV, older), (GITLEAKS_REPO, GITLEAKS_REV, pinned))

    assert machine.binary(_config(tmp_path / "o1")) == pinned_build
    assert machine.binary(_config(tmp_path / "o2", rev=OTHER_REV)) == older_build


def test_an_explicit_version_has_no_substitute(machine: Machine, tmp_path: Path) -> None:
    machine.pinned("default")
    build_gitleaks(machine.build_dir, "system")
    pinned = machine.build_dir

    # The hook's version, or the file's default: that build or nothing.
    assert machine.binary(_config(tmp_path / "o1", language_version="1.22")) is None
    assert machine.binary(_config(tmp_path / "o2", default_golang="1.22")) is None
    versioned = build_gitleaks(pinned, "1.22")
    assert machine.binary(_config(tmp_path / "o3", language_version="1.22")) == versioned
    assert machine.binary(_config(tmp_path / "o4", default_golang="1.22")) == versioned
    # `system` written out is an explicit version too, and `default` is not one.
    system = pinned / "golangenv-system" / "bin" / "gitleaks"
    assert machine.binary(_config(tmp_path / "o5", language_version="system")) == system


def test_default_then_system(machine: Machine, tmp_path: Path) -> None:
    overlay = _config(tmp_path / "o")
    machine.pinned(None)
    assert machine.binary(overlay) is None  # a row, nothing built

    system = build_gitleaks(machine.build_dir, "system")
    assert machine.binary(overlay) == system  # the same source at the same rev, built by another go
    default = build_gitleaks(machine.build_dir, "default")
    assert machine.binary(overlay) == default  # and `default` first when both are there


def test_a_version_that_leaves_the_pinned_row_selects_nothing(
    machine: Machine, tmp_path: Path
) -> None:
    """A `language_version` with a separator or `..` would name a binary outside the pinned row."""
    machine.pinned("default")
    build_gitleaks(tmp_path / "pc" / "evil", "x")  # pc/evil/golangenv-x/bin/gitleaks

    for number, version in enumerate(
        ("default/../../evil/golangenv-x", "../repoA/golangenv-default", "a/b", "a\\b")
    ):
        overlay = _config(tmp_path / f"o-{number}", language_version=version)
        assert machine.binary(overlay) is None, version


def test_a_build_linking_out_of_its_row_is_not_it(machine: Machine, tmp_path: Path) -> None:
    machine.pinned("default")
    evil = build_gitleaks(tmp_path / "pc" / "evil", "x")
    (machine.build_dir / "golangenv-1.22").symlink_to(evil.parents[1])

    assert machine.binary(_config(tmp_path / "o", language_version="1.22")) is None


def test_a_build_that_is_not_executable_is_not_a_scanner(machine: Machine, tmp_path: Path) -> None:
    binary = machine.pinned("default")
    assert binary is not None
    binary.chmod(0o644)

    assert machine.binary(_config(tmp_path / "o")) is None


# -- the scans ------------------------------------------------------------------------------------


@pytest.fixture
def scanner(machine: Machine) -> Path:
    binary = machine.pinned("default")
    assert binary is not None
    return binary


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
    assert G.git(repo, "add", "--", relative, timeout=SLOW, index_file=index).code == 0


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
    assert _seen(scanner)["rules_text"] == DEFAULT_RULES  # none committed: the build's own

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


def test_without_committed_rules_or_a_default_the_scan_fails(tmp_path: Path, scanner: Path) -> None:
    (scanner.parents[2] / "config" / "gitleaks.toml").unlink()
    repo = _repo(tmp_path)

    result = S.scan_range(repo, "HEAD", "HEAD", scanner, SLOW)

    assert (result.ok, result.finding_commit) == (False, None)
    assert "default rules are missing" in result.detail


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


def test_gitleaks_reads_a_log_without_signature_lines(tmp_path: Path, scanner: Path) -> None:
    """Its own `git log -p` parses a patch: a `log.showSignature` in the owner's configuration
    would put a verification into what it reads."""
    repo = _repo(tmp_path)
    git(repo, "config", "log.showSignature", "true")

    S.scan_range(repo, "HEAD", "HEAD", scanner, SLOW)

    assert (scanner.parent / "show_signature").read_text() == "false"


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


def test_no_scanner_has_one_remedy() -> None:
    detail = S.NO_SCANNER.format(overlay="/home/o/overlay")

    assert detail.endswith("run `pre-commit install-hooks` in /home/o/overlay")
