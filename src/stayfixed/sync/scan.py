"""The secret scan: the overlay's pinned gitleaks build, and the three scans the job runs with it.

The job commits through a temporary index and never runs `git commit`, so the overlay's pre-commit
hook does not run by itself; the job runs the scan instead. The scanner is the build `pre-commit
install-hooks` already made for the overlay's pinned hook, found through pre-commit's own database
and never downloaded or built here: the row whose `repo` and `rev` are the pin's, in the
environment the pin's `language_version` names, else `default`, else `system` (the same source at
the same revision either way). With no build the job records `scan_unavailable` (`NO_SCANNER`).

`gitleaks git --pre-commit --staged` scans the index `GIT_INDEX_FILE` names, `gitleaks git
--log-opts=A..B` the patches of a range and nothing else, so `gitleaks stdin` scans what else a
push sends (each commit's author, message and path names). Only the JSON report names a finding's
commit, and the exit is 1 for a finding and for a failed scan alike, so the report, not the exit
code, tells them apart. Every scan runs on rules and ignores pinned to `HEAD` (`_pinned`): the
committed `.gitleaks.toml`, else the build's own default, and the committed `.gitleaksignore`,
else none, never a file the working tree holds now or a `GITLEAKS_*` variable of the session. The
scan is a check against an honest mistake, as the anchor is the pinned build and `HEAD`; an agent
with a shell can push by hand anyway.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stayfixed import fsops
from stayfixed.sync.git import git, run, timed

GITLEAKS_REPO = "https://github.com/gitleaks/gitleaks"
GITLEAKS_HOOK = "gitleaks"
CONFIG = ".pre-commit-config.yaml"
RULES = ".gitleaks.toml"
IGNORES = ".gitleaksignore"
NO_SCANNER = (
    "no gitleaks build for the overlay's pinned hook, so nothing is committed or pushed; "
    "run `pre-commit install-hooks` in {overlay}"
)
# What a result shows of a failed scan or a list of findings: lines and characters. Named caps on
# what reaches the state file; no shipped file states them.
DETAIL_LINES = 5
DETAIL_CHARS = 600
# Named caps, no shipped file states them: how long to wait on a locked pre-commit database, and
# how much of the overlay's own `.pre-commit-config.yaml` to read.
DB_TIMEOUT = 5.0
CONFIG_BYTES = 1024 * 1024
# One configuration entry, given the way `git -c` would give it, for every git gitleaks starts:
# its `git log -p` never carries signature checks into what it parses.
NO_SIGNATURES = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "log.showSignature",
    "GIT_CONFIG_VALUE_0": "false",
}
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_REPO = re.compile(r"\s*-\s*repo:\s*(.+)$")
_REV = re.compile(r"\s*rev:\s*(.+)$")
_HOOK = re.compile(r"\s*-\s*id:\s*(.+)$")
_VERSION = re.compile(r"\s*(?:-\s*)?language_version:\s*(.+)$")
_GOLANG = re.compile(r"\s+golang:\s*(.+)$")


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    check_id: str
    detail: str
    timed_out: bool
    finding_commit: str | None


def _scalar(text: str) -> str:
    """A YAML scalar as the overlay's configuration writes it: bare or quoted, maybe commented."""
    text = re.sub(r"\s+#.*$", "", text).strip()
    return text[1:-1] if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"" else text


def gitleaks_pin(overlay: Path) -> tuple[str, str, str | None] | None:
    """`(repo, rev, language_version)` for the overlay's gitleaks hook, or `None` if it has none.

    Read line by line from `.pre-commit-config.yaml`: the standard library has no YAML, and the
    file is the overlay's own, written in block style. The version is the hook's
    `language_version`, else the file's `default_language_version.golang`; `None` when neither
    says more than `default`, which pre-commit reads as "not set here".
    """
    try:
        lines = fsops.read_regular_text(overlay / CONFIG, limit=CONFIG_BYTES).splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    top = repo = rev = hook = default = hooked = found = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            top = line.split(":", 1)[0].strip()
        elif top == "default_language_version" and (match := _GOLANG.match(line)):
            default = _scalar(match[1])
        elif top == "repos":
            if match := _REPO.match(line):
                repo, rev, hook = _scalar(match[1]), None, None
            elif match := _REV.match(line):
                rev = _scalar(match[1])
            elif match := _HOOK.match(line):
                hook = _scalar(match[1])
            elif (match := _VERSION.match(line)) and (repo, hook) == (GITLEAKS_REPO, GITLEAKS_HOOK):
                hooked = _scalar(match[1])
            if rev and (repo, hook) == (GITLEAKS_REPO, GITLEAKS_HOOK):
                found = rev
    if found is None:
        return None
    return GITLEAKS_REPO, found, next((v for v in (hooked, default) if v and v != "default"), None)


def gitleaks_binary(home: Path, overlay: Path, env: Mapping[str, str] | None = None) -> Path | None:
    """The gitleaks build pre-commit made for the overlay's pinned hook, or `None`.

    The environment is the pin's `language_version`, which has no substitute, else `default`, else
    `system`: the same source at the same `rev`, built by whichever go was there. `None` when the
    overlay pins no gitleaks, the database is missing or unreadable, no row has the pinned `repo`
    and `rev` (a row of another `rev` is never a substitute), or no allowed environment holds an
    executable build. `env` names pre-commit's cache the way pre-commit reads it.
    """
    pin = gitleaks_pin(overlay)
    env = os.environ if env is None else env
    if pin is None:
        return None
    repo, rev, version = pin
    if env.get("PRE_COMMIT_HOME"):
        database = Path(env["PRE_COMMIT_HOME"]) / "db.db"
    else:
        database = Path(env.get("XDG_CACHE_HOME") or home / ".cache") / "pre-commit" / "db.db"
    if not fsops.is_file(database):
        return None
    try:
        with contextlib.closing(
            sqlite3.connect(f"{database.absolute().as_uri()}?mode=ro", uri=True, timeout=DB_TIMEOUT)
        ) as db:
            row = db.execute("SELECT path FROM repos WHERE repo = ? AND ref = ?", (repo, rev))
            path = row.fetchone()
    except sqlite3.Error:
        return None
    if path is None:
        return None
    row_path = os.path.realpath(path[0])
    for name in [version] if version else ["default", "system"]:
        binary = Path(path[0]) / f"golangenv-{name}" / "bin" / "gitleaks"
        # Anchor: the resolved path. A build directory that links out of the row, by a link or by a
        # `language_version` naming a path, is not it.
        if (
            fsops.is_file(binary)
            and os.access(binary, os.X_OK)
            and os.path.commonpath((os.path.realpath(binary), row_path)) == row_path
        ):
            return binary
    return None


def _first_lines(text: str) -> str:
    lines = [line.rstrip() for line in _ANSI.sub("", text).splitlines() if line.strip()]
    return "\n".join(lines[:DETAIL_LINES])[:DETAIL_CHARS]


def _findings(report: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(fsops.read_regular_text(report))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _committed(
    repo: Path, name: str, timeout: float, env: Mapping[str, str] | None
) -> bytes | None:
    """The file `name` at the root of `HEAD`, as committed; `None` when it cannot be read, which
    only ever makes the scan stricter (the default rules, no ignores)."""
    result = timed(
        git(repo, "cat-file", "blob", f"HEAD:{name}", timeout=timeout, env=env),
        f"git cat-file HEAD:{name}",
    )
    return result.out.encode("utf-8", "surrogateescape") if result.code == 0 else None


def _pinned(
    repo: Path,
    binary: Path,
    directory: Path,
    timeout: float,
    env: Mapping[str, str] | None,
    *,
    in_repo: bool,
) -> tuple[list[str], str | None]:
    """The arguments that pin the scan's rules and ignore list to what `HEAD` commits, written
    into `directory`; or why they cannot be.

    Left to itself, gitleaks reads `--config`, else `$GITLEAKS_CONFIG`, else the scanned
    directory's `.gitleaks.toml`, and its ignore list from `--gitleaks-ignore-path` and from the
    scanned directory: an untracked file or an inherited variable would decide what the unattended
    scan may miss. With no rules committed, the build's own default (`config/gitleaks.toml` of the
    pinned source) is named explicitly. A scan whose source is the overlay (`in_repo`) cannot keep
    gitleaks from reading the root's `.gitleaksignore`, so one that is not the committed file stops
    it.
    """
    committed = _committed(repo, IGNORES, timeout, env)
    if in_repo:
        try:
            present: bytes | None = fsops.read_regular_bytes(repo / IGNORES)
        except FileNotFoundError:
            present = None
        except OSError as error:
            return [], f"{IGNORES} at the overlay's root cannot be read: {fsops.said(error)}"
        if present is not None and present != committed:
            return [], (
                f"{IGNORES} at the overlay's root is not the committed one, and gitleaks reads it "
                "whatever it is told: commit it or remove it"
            )
    rules = _committed(repo, RULES, timeout, env)
    if rules is not None:
        config = directory / RULES
        config.write_bytes(rules)
    else:
        config = binary.parent.parent.parent / "config" / "gitleaks.toml"
        if not fsops.is_file(config):
            return (
                [],
                f"no {RULES} is committed and the build's default rules are missing: {config}",
            )
    ignores = directory / "ignores"
    ignores.mkdir()
    if committed is not None:
        (ignores / IGNORES).write_bytes(committed)
    return ["--config", str(config), "--gitleaks-ignore-path", str(ignores)], None


def _scan(
    repo: Path,
    arguments: list[str],
    binary: Path,
    timeout: float,
    *,
    index_file: Path | None = None,
    env: Mapping[str, str] | None = None,
    scratch: Path | None = None,
    stdin: bytes | None = None,
) -> tuple[CheckResult, list[dict[str, Any]]]:
    """Run `binary` with `arguments` (its subcommand, flags and source) on its pinned rules; the
    result and what it found. The report names files and commits, so it is written in `scratch`
    (the job's own directory, removed with the scan) and not in `$TMPDIR`.

    A scan of standard input runs in a directory of its own, so nothing at the overlay's root
    applies to it.
    """
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix="scan-", dir=scratch) as name:
        directory = Path(name)
        pinned, unpinned = _pinned(repo, binary, directory, timeout, env, in_repo=stdin is None)
        if unpinned:
            return CheckResult(False, "gitleaks", unpinned, False, None), []
        report = directory / "report.json"
        result = run(
            [
                str(binary),
                *arguments[:1],
                *pinned,
                "--redact",
                "--no-banner",
                "--no-color",
                "--report-format",
                "json",
                "--report-path",
                str(report),
                *arguments[1:],
            ],
            cwd=repo if stdin is None else directory,
            timeout=max(deadline - time.monotonic(), 0.0),
            env={**(env or {}), **NO_SIGNATURES},
            index_file=index_file,
            stdin=stdin,
            unset_prefixes=("GITLEAKS_",),
        )
        findings = _findings(report)
    if result.timed_out:
        out = f"gitleaks did not finish within {timeout:g} s"
        return CheckResult(False, "gitleaks", out, True, None), []
    if result.code == 0:
        return CheckResult(True, "gitleaks", "no leaks found", False, None), []
    if not findings:
        # A failed scan, not a finding: exit 1 with an empty report.
        detail = (
            _first_lines(result.err) or _first_lines(result.out) or f"gitleaks exited {result.code}"
        )
        return CheckResult(False, "gitleaks", detail, False, None), []
    commit = next((str(item["Commit"]) for item in findings if item.get("Commit")), None)
    # Rule, file and commit only: never the match or the secret, redacted or not.
    lines = [
        f"{item.get('RuleID', 'secret')} in {item.get('File', '?')}"
        + (f" (commit {item['Commit']})" if item.get("Commit") else "")
        for item in findings[:DETAIL_LINES]
    ]
    if len(findings) > DETAIL_LINES:
        lines.append(f"... {len(findings) - DETAIL_LINES} more")
    return CheckResult(False, "gitleaks", "\n".join(lines), False, commit), findings


def scan_index(
    repo: Path,
    index_file: Path,
    binary: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
    scratch: Path | None = None,
) -> CheckResult:
    """Scan what `index_file` stages against `HEAD`; the real index is not read."""
    arguments = ["git", "--pre-commit", "--staged", "."]
    return _scan(repo, arguments, binary, timeout, index_file=index_file, env=env, scratch=scratch)[
        0
    ]


def scan_range(
    repo: Path,
    base: str,
    tip: str,
    binary: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
    scratch: Path | None = None,
) -> CheckResult:
    """Scan the patches of `base..tip`; a finding names its commit in `finding_commit`."""
    arguments = ["git", f"--log-opts={base}..{tip}", "."]
    return _scan(repo, arguments, binary, timeout, env=env, scratch=scratch)[0]


def scan_commits(
    repo: Path,
    commits: list[tuple[str, str]],
    binary: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
    scratch: Path | None = None,
) -> CheckResult:
    """Scan what a push sends besides the patches -- each commit's author and committer, its
    message and its path names, given as `[(sha, text)]` -- through `gitleaks stdin`.

    One run over all of them; only when that one finds something, one run per commit, so the
    finding names its commit. Found in the whole but in no single commit, it names none (and so
    cannot be pushed either).
    """
    deadline = time.monotonic() + timeout
    whole = "".join(text for _, text in commits).encode("utf-8", "surrogateescape")
    result, findings = _scan(
        repo, ["stdin"], binary, timeout, env=env, scratch=scratch, stdin=whole
    )
    if not findings:
        return result
    for sha, text in commits:
        one, found = _scan(
            repo,
            ["stdin"],
            binary,
            max(deadline - time.monotonic(), 0.0),
            env=env,
            scratch=scratch,
            stdin=text.encode("utf-8", "surrogateescape"),
        )
        if one.timed_out:
            return one
        if found:
            rules = ", ".join(sorted({str(item.get("RuleID", "secret")) for item in found}))
            detail = f"{rules} in the author, message or path names of commit {sha}"
            return CheckResult(False, "gitleaks", detail, False, sha)
    detail = "a finding in the commits' metadata, in no one commit"
    return CheckResult(False, "gitleaks", detail, False, None)
