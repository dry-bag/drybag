"""The secret scan: the gitleaks on `PATH`, over the bytes the job commits and pushes.

The scanner is the `gitleaks` the `PATH` of the one git environment finds (`gitenv.scrubbed_env`,
its absolute entries alone), looked up once per job; pre-commit's build, or any other a session's
environment could name, is never read. With none the job records `scan_unavailable`
(`NO_SCANNER`).

Every scan reads content only. The items, bytes each with a label, are written as files named `1`,
`2`, ... in a directory of the job's scratch and scanned by `gitleaks dir .` run there, with
`--config` naming the committed `.gitleaks.toml` the caller hands in or, with none, a file that
extends gitleaks' own defaults. No path of the overlay reaches gitleaks, so no path allowlist and
no `.gitleaksignore` applies, whatever a note is named, and no file at the overlay's root is read;
a committed rule set's content allowlists still do. The exit is 1 for a finding and for a failed
scan alike, so the report, not the exit code, tells them apart. The scan is a check against an
honest mistake; an agent with a shell can push by hand anyway.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stayfixed import fsops
from stayfixed.gitenv import scrubbed_env
from stayfixed.processes import run_bounded

RULES = ".gitleaks.toml"
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
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass(frozen=True)
class Scanned:
    """What one scan said: whether it passed, its detail, whether it ran out of its time, and the
    labels of the items gitleaks reported."""

    ok: bool
    detail: str
    timed_out: bool
    found: tuple[str, ...]


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


def scan(
    items: Sequence[tuple[str, bytes]],
    binary: Path,
    rules: bytes | None,
    timeout: float,
    scratch: Path,
) -> Scanned:
    """Scan `items`, `(label, bytes)` each, with `rules` (a committed `.gitleaks.toml`, or `None`
    for gitleaks' defaults), within `timeout`. The items, the rules and the report, which names
    files, are written in a directory of `scratch` (the job's own) removed with the scan, never in
    `$TMPDIR`. A detail names rule and label, never the match or the secret, redacted or not."""
    with tempfile.TemporaryDirectory(prefix="scan-", dir=scratch) as name:
        directory = Path(name)
        source = directory / "items"
        source.mkdir()
        for number, (_, data) in enumerate(items, start=1):
            (source / str(number)).write_bytes(data)
        config = directory / RULES
        config.write_bytes(DEFAULTS if rules is None else rules)
        report = directory / "report.json"
        result = run_bounded(
            [
                str(binary), "dir", ".", "--config", str(config), "--redact", "--no-banner",
                "--no-color", "--report-format", "json", "--report-path", str(report),
            ],
            cwd=source,
            env=scrubbed_env(),
            timeout=timeout,
        )  # fmt: skip
        findings = _findings(report)
    if result.timed_out:
        return Scanned(False, f"gitleaks did not finish within {timeout:g} s", True, ())
    if result.code == 0:
        return Scanned(True, "no leaks found", False, ())
    if not findings:
        # A failed scan, not a finding: exit 1 with an empty report.
        err, out = (data.decode("utf-8", "replace") for data in (result.err, result.out))
        detail = first_lines(err) or first_lines(out) or f"gitleaks exited {result.code}"
        return Scanned(False, detail, False, ())
    labels = {str(number): label for number, (label, _) in enumerate(items, start=1)}
    order = list(labels)
    hits = sorted(
        (order.index(file) if file in labels else len(order), labels.get(file, file), rule)
        for item in findings
        for file, rule in [(str(item.get("File", "")), str(item.get("RuleID", "secret")))]
    )
    lines = [f"{rule} in {label}" for _, label, rule in hits[:DETAIL_LINES]]
    if len(hits) > DETAIL_LINES:
        lines.append(f"... {len(hits) - DETAIL_LINES} more")
    found = tuple(dict.fromkeys(label for _, label, _ in hits))
    return Scanned(False, "\n".join(lines), False, found)
