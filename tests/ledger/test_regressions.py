"""`stayfixed bugs regressions` through the real frame: each fixed entry's `regression` run, one
line an entry, and an exit code that says whether every one passed.

Each case builds a scratch repository holding a ledger whose regressions are `sh -c` scripts: the
verdict is the exit code, so no test runner is needed to say what one would.

stayfixed:ledger:fixtures — the identifiers below are sample data, not claims about a ledger.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from stayfixed.ledger import regressions as module
from stayfixed.ledger.commands import NO_REGRESSIONS, REGRESSIONS_RAN
from tests.cli import cli
from tests.gitfixture import git, needs_git

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
release_branch = "main"
"""

ENTRY = """---
id: {id}
title: a widget renders the wrong total
status: {status}
severity: low
area: widget rendering
found: 2026-10-18
source:
fixed_in:
related:
regression: {regression}
---

Body prose.
"""

PASSING = ["sh", "-c", "exit 0"]
FAILING = ["sh", "-c", "exit 3"]


def ledger(tmp_path: Path, entries: Mapping[str, tuple[str, Sequence[str]]]) -> Path:
    """A committed repository with one entry per `entries` item: its identifier, then its status
    and its `regression`."""
    root = tmp_path / "widget"
    (root / "docs" / "bugs").mkdir(parents=True)
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    for identifier, (status, argv) in entries.items():
        text = ENTRY.format(id=identifier, status=status, regression=json.dumps(list(argv)))
        (root / "docs" / "bugs" / f"{identifier}.md").write_text(text, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "the regression fixture")
    return root


def regressions(tmp_path: Path, root: Path, *flags: str) -> tuple[int, str, str]:
    return cli(root, tmp_path, "bugs", "regressions", *flags)


def as_json(tmp_path: Path, root: Path, *flags: str) -> tuple[int, dict[str, object]]:
    code, out, _ = regressions(tmp_path, root, "--json", *flags)
    return code, json.loads(out)


@needs_git
def test_an_exit_0_is_passed_and_any_other_exit_failed(tmp_path: Path) -> None:
    # The exit code is the verdict, and only `passed` is counted as passed. Mutation (oracle):
    # `mutations/`'s "bugs regressions reads every exit code as passed" and "bugs regressions
    # counts every verdict as passed" -> exit 0.
    root = ledger(tmp_path, {"BR-001": ("fixed", PASSING), "BR-002": ("fixed", FAILING)})
    code, out, _ = regressions(tmp_path, root)
    assert (code, out.splitlines()) == (
        1,
        [
            "BR-001: passed: exit 0",
            "BR-002: failed: exit 3",
            REGRESSIONS_RAN.format(ran=2, not_passed=1),
        ],
    )


@needs_git
def test_every_regression_passing_exits_0(tmp_path: Path) -> None:
    root = ledger(tmp_path, {"BR-001": ("fixed", PASSING)})
    code, data = as_json(tmp_path, root)
    assert (code, data["not_passed"]) == (0, 0)
    assert data["regressions"] == [
        {
            "id": "BR-001",
            "path": "docs/bugs/BR-001.md",
            "verdict": "passed",
            "line": "passed: exit 0",
        }
    ]


@needs_git
def test_only_fixed_entries_run(tmp_path: Path) -> None:
    # Why only `fixed`: `docs/cli.md`'s `stayfixed bugs regressions`. Mutation (oracle):
    # `mutations/`'s "bugs regressions runs an entry of any status" -> all five run.
    entries = {
        "BR-001": ("open", FAILING),
        "BR-002": ("partial", FAILING),
        "BR-003": ("rejected", FAILING),
        "BR-004": ("void", FAILING),
        "BR-005": ("fixed", FAILING),
    }
    code, data = as_json(tmp_path, ledger(tmp_path, entries))
    assert [row["id"] for row in data["regressions"]] == ["BR-005"]  # type: ignore[attr-defined]
    assert (code, data["not_passed"]) == (1, 1)


@needs_git
def test_an_argv_that_cannot_start_is_not_run(tmp_path: Path) -> None:
    root = ledger(tmp_path, {"BR-001": ("fixed", [str(tmp_path / "no-such-program")])})
    code, data = as_json(tmp_path, root)
    assert data["regressions"][0]["line"] == f"not-run: {os.strerror(errno.ENOENT)}"  # type: ignore[index]
    assert (code, data["not_passed"]) == (1, 1)


def _released(fifo: int) -> bool:
    """Whether every writer of the FIFO behind the non-blocking `fifo` has closed it, waiting a
    little for an ended process's descriptors to close."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if os.read(fifo, 1) == b"":
                return True
        except BlockingIOError:
            pass
        time.sleep(0.05)
    return False


@needs_git
def test_a_timed_out_regression_ends_its_whole_group(tmp_path: Path) -> None:
    # The command's background child holds the FIFO open for as long as it lives, and an ended
    # child's descriptors close: the FIFO reads its end only once the whole group is gone, not
    # the command alone. Mutation (oracle): `mutations/`'s "a timed-out custom gate's children run
    # on after it reported" -> the child outlives the run.
    pipe = tmp_path / "held"
    os.mkfifo(pipe)
    fifo = os.open(pipe, os.O_RDONLY | os.O_NONBLOCK)
    try:
        held = ["sh", "-c", f"exec 3>'{pipe}'; sleep 30 & wait"]
        root = ledger(tmp_path, {"BR-001": ("fixed", held)})
        code, data = as_json(tmp_path, root, "--timeout", "1")
        assert data["regressions"][0]["verdict"] == "timed-out"  # type: ignore[index]
        assert (code, data["not_passed"]) == (1, 1)
        assert _released(fifo)
    finally:
        os.close(fifo)


@needs_git
@pytest.mark.parametrize("signal_name", ["INT", "TERM", "HUP"])
def test_an_interrupted_regression_starts_no_further_one(tmp_path: Path, signal_name: str) -> None:
    # The first regression sends stayfixed the signal a Ctrl-C, a caller's bound or a closed
    # terminal would, while its background child holds the FIFO open; the second would leave a
    # file behind. A loop that went on would start it after the signal, and a group left running
    # would keep the FIFO open. A SIGTERM or SIGHUP the command takes no handler for lands on this
    # case's own, which does nothing, so the run times out instead of ending this process.
    # Mutation (oracle): `mutations/`'s "bugs regressions goes on past an interrupt" -> the second
    # entry runs; "bugs regressions lets a SIGTERM end stayfixed" -> `TERM` times out; "bugs
    # regressions lets a SIGHUP end stayfixed" -> `HUP` times out.
    pipe = tmp_path / "held"
    os.mkfifo(pipe)
    fifo = os.open(pipe, os.O_RDONLY | os.O_NONBLOCK)
    quiet = {
        number: signal.signal(number, lambda *_: None) for number in (signal.SIGTERM, signal.SIGHUP)
    }
    try:
        late = tmp_path / "late"
        signalled = [
            "sh",
            "-c",
            f"exec 3>'{pipe}'; sleep 30 & sleep 0.2; kill -{signal_name} {os.getpid()}; wait",
        ]
        entries = {"BR-001": ("fixed", signalled), "BR-002": ("fixed", ["touch", str(late)])}
        code, data = as_json(tmp_path, ledger(tmp_path, entries), "--timeout", "3")
        released = _released(fifo)
    finally:
        for number, handler in quiet.items():
            signal.signal(number, handler)
        os.close(fifo)
    rows = data["regressions"]
    assert [(row["id"], row["verdict"]) for row in rows] == [("BR-001", "interrupted")]  # type: ignore[attr-defined]
    assert code == 1
    assert not late.exists()
    assert released


@needs_git
def test_a_regression_reads_nothing_piped_into_stayfixed(tmp_path: Path) -> None:
    # Whatever feeds stayfixed's standard input, an agent or a pipe upstream, could drive the
    # command (a runner's debugger takes its commands there), so each run's is `/dev/null` and a
    # command that reads it sees its end at once. Mutation (oracle): `mutations/`'s "bugs
    # regressions hands the command the caller's standard input" -> it reads the line and fails.
    root = ledger(tmp_path, {"BR-001": ("fixed", ["sh", "-c", "! read line"])})
    reader, writer = os.pipe()
    os.write(writer, b"pass\n")
    os.close(writer)
    saved = os.dup(0)
    try:
        os.dup2(reader, 0)
        code, data = as_json(tmp_path, root)
    finally:
        os.dup2(saved, 0)
        os.close(reader)
        os.close(saved)
    assert (code, data["not_passed"]) == (0, 0)


@needs_git
def test_no_fixed_entry_with_a_regression_is_one_sentence_and_exit_0(tmp_path: Path) -> None:
    root = ledger(tmp_path, {"BR-001": ("fixed", []), "BR-002": ("open", FAILING)})
    assert regressions(tmp_path, root) == (0, f"{NO_REGRESSIONS}\n", "")


@needs_git
def test_json_stays_one_object_while_the_command_prints(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # A command inherits file descriptors, not Python's streams: one that wrote to descriptor 1
    # would land between whatever reads standard output and the object it parses, which `capfd`
    # sees and the frame's own redirection does not. Mutation (oracle): `mutations/`'s "bugs
    # regressions prints the command's output on standard output" -> descriptor 1 holds it.
    root = ledger(tmp_path, {"BR-001": ("fixed", ["sh", "-c", "echo said-by-the-command"])})
    code, out, _ = regressions(tmp_path, root, "--json")
    assert code == 0
    assert json.loads(out)["regressions"][0]["verdict"] == "passed"
    captured = capfd.readouterr()
    assert "said-by-the-command" in captured.err
    assert captured.out == ""


@needs_git
def test_the_timeout_is_the_option_or_ten_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each run's bound is the command's own option, through the real parser: ten minutes when it
    # is not given, the value `[gates] custom_timeout_seconds` held in the preset before the gates
    # went, and what `--timeout` says when it is. Anything but a whole number of seconds above 0
    # is the parser's refusal, exit 2, before any entry runs.
    bounds: list[object] = []

    def recorded(argv: Sequence[str], root: Path, timeout: int) -> module.Run:
        bounds.append(timeout)
        return module.Run(module.PASSED, "exit 0")

    monkeypatch.setattr(module, "_run", recorded)
    root = ledger(tmp_path, {"BR-001": ("fixed", PASSING)})
    regressions(tmp_path, root)
    regressions(tmp_path, root, "--timeout", "5")
    assert bounds == [600, 5]
    for value in ("0", "-1", "1.5", "five"):
        with pytest.raises(SystemExit) as refused:
            regressions(tmp_path, root, "--timeout", value)
        assert refused.value.code == 2, value
    assert bounds == [600, 5]
