"""The secret scan: the gitleaks on `PATH`, and the three scans the job runs with it.

The job commits through a temporary index and never runs `git commit`, so the overlay's pre-commit
hook does not run by itself; the job runs the scan instead. The scanner is the `gitleaks` the
`PATH` of the one git environment finds (`gitenv.scrubbed_env`, its absolute entries alone),
looked up once per job; pre-commit's build, or any other a session's environment could name, is
never read. With none the job records `scan_unavailable` (`NO_SCANNER`).

`gitleaks git --pre-commit --staged` scans the index `GIT_INDEX_FILE` names, `gitleaks git
--log-opts=A..B` the patches of a range and nothing else, so `gitleaks stdin` scans what else a
push sends (each commit's author, message and path names). Only the JSON report names a finding's
commit, and the exit is 1 for a finding and for a failed scan alike, so the report, not the exit
code, tells them apart. Every scan runs on rules and ignores pinned to `HEAD` (`_pinned`): the
committed `.gitleaks.toml`, else gitleaks' own defaults, and the committed `.gitleaksignore`,
else none, never a file the working tree holds now or a `GITLEAKS_*` variable of the session. The
scan is a check against an honest mistake; an agent with a shell can push by hand anyway.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stayfixed import fsops
from stayfixed.gitenv import scrubbed_env
from stayfixed.processes import run_bounded
from stayfixed.sync.git import git, timed, with_config

RULES = ".gitleaks.toml"
IGNORES = ".gitleaksignore"
# The rules a scan runs on where `HEAD` commits none: gitleaks' own.
DEFAULTS = b"[extend]\nuseDefault = true\n"
NO_SCANNER = (
    "no gitleaks on PATH, so nothing is committed or pushed; "
    "install gitleaks on the PATH the sessions run with"
)
# What a result shows of a failed scan or a list of findings: lines and characters. Named caps on
# what reaches the state file; no shipped file states them.
DETAIL_LINES = 5
DETAIL_CHARS = 600
# The configuration every git gitleaks starts is given: its `git log -p` and `git diff` print the
# patch its parser reads, which a signature check or a colour code the owner's configuration asks
# for leaves with no file to scan, and the scan passing. Its source passes no `--no-color`.
SCAN_CONFIG = {
    "log.showSignature": "false",
    "color.ui": "false",
    "color.diff": "false",
}
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str
    timed_out: bool
    finding_commit: str | None


def gitleaks() -> Path | None:
    """The `gitleaks` on the `PATH` every git stayfixed starts is given, or `None`."""
    found = shutil.which("gitleaks", path=scrubbed_env().get("PATH", ""))
    return None if found is None else Path(found)


def first_lines(text: str) -> str:
    """The first lines of what a program said, colour codes stripped, cut for the state."""
    lines = [line.rstrip() for line in _ANSI.sub("", text).splitlines() if line.strip()]
    return "\n".join(lines[:DETAIL_LINES])[:DETAIL_CHARS]


def _findings(report: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(fsops.read_regular_text(report))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def blob(repo: Path, spec: str, timeout: float, env: Mapping[str, str] | None) -> bytes | None:
    """The blob `spec` (`<rev>:<path>`) names, as committed; `None` when there is none. For the
    scan's rules and ignores, `None` only ever makes the scan stricter (the default rules, no
    ignores)."""
    result = timed(
        git(repo, "cat-file", "blob", "--end-of-options", spec, timeout=timeout, env=env),
        f"git cat-file {spec}",
    )
    return result.out.encode("utf-8", "surrogateescape") if result.code == 0 else None


def _pinned(
    repo: Path,
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
    scan may miss. With no rules committed, a file that extends gitleaks' own defaults is named. A
    scan whose source is the overlay (`in_repo`) cannot keep gitleaks from reading the root's
    `.gitleaksignore`, so one that is not the committed file stops it.
    """
    committed = blob(repo, f"HEAD:{IGNORES}", timeout, env)
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
    rules = blob(repo, f"HEAD:{RULES}", timeout, env)
    config = directory / RULES
    config.write_bytes(DEFAULTS if rules is None else rules)
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
        pinned, unpinned = _pinned(repo, directory, timeout, env, in_repo=stdin is None)
        if unpinned:
            return CheckResult(False, unpinned, False, None), []
        report = directory / "report.json"
        given = with_config(env or {}, SCAN_CONFIG)
        if index_file is not None:
            given["GIT_INDEX_FILE"] = str(index_file)
        result = run_bounded(
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
            env=scrubbed_env() | given,
            timeout=max(deadline - time.monotonic(), 0.0),
            stdin=stdin,
        )
        findings = _findings(report)
    err, out = (data.decode("utf-8", "replace") for data in (result.err, result.out))
    if result.timed_out:
        out = f"gitleaks did not finish within {timeout:g} s"
        return CheckResult(False, out, True, None), []
    if result.code == 0:
        return CheckResult(True, "no leaks found", False, None), []
    if not findings:
        # A failed scan, not a finding: exit 1 with an empty report.
        detail = first_lines(err) or first_lines(out) or f"gitleaks exited {result.code}"
        return CheckResult(False, detail, False, None), []
    commit = next((str(item["Commit"]) for item in findings if item.get("Commit")), None)
    # Rule, file and commit only: never the match or the secret, redacted or not.
    lines = [
        f"{item.get('RuleID', 'secret')} in {item.get('File', '?')}"
        + (f" (commit {item['Commit']})" if item.get("Commit") else "")
        for item in findings[:DETAIL_LINES]
    ]
    if len(findings) > DETAIL_LINES:
        lines.append(f"... {len(findings) - DETAIL_LINES} more")
    return CheckResult(False, "\n".join(lines), False, commit), findings


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
            return CheckResult(False, detail, False, sha)
    detail = "a finding in the commits' metadata, in no one commit"
    return CheckResult(False, detail, False, None)
