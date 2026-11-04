"""`stayfixed bugs regressions` through the real frame: each fixed entry's `regression` run through
`prove`, one line an entry, and an exit code that says whether every one was proved.

Each case builds a scratch repository holding a ledger and a pytest project, and runs pytest from
the project's own environment, first on `PATH`, with its entry-point plugins off so the suite's
own (coverage, workers) never join the run. The cases a declared mutation names run no real
runner: an argv no adapter recognises is `not proven` without anything being started.

stayfixed:ledger:fixtures — the identifiers below are sample data, not claims about a ledger.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from stayfixed.ledger import regressions as module
from stayfixed.ledger.commands import NO_REGRESSIONS, REGRESSIONS_RAN
from stayfixed.prove.run import INTERRUPTED, Receipt, Verdict
from tests.cli import cli
from tests.gitfixture import git, needs_git
from tests.prove.projects import pytest_project
from tests.prove.real_runners import needs_runner, runner_directory

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
profile = ""
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

PASSING = ["pytest", "test_scratch.py::test_pass_0"]
FAILING = ["pytest", "test_scratch.py::test_fail_0"]
# No adapter recognises `sh`, so `prove` starts nothing and the receipt is `not proven`.
UNRECOGNISED = ["sh", "-c", "echo 3 passed"]


def ledger(tmp_path: Path, entries: Mapping[str, tuple[str, Sequence[str]]]) -> Path:
    """A committed repository with a pytest project of one passing and one failing test, and one
    entry per `entries` item: its identifier, then its status and its `regression`."""
    root = pytest_project(tmp_path / "widget", passing=1, failing=1)
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    (root / "docs" / "bugs").mkdir(parents=True)
    for identifier, (status, argv) in entries.items():
        text = ENTRY.format(id=identifier, status=status, regression=json.dumps(list(argv)))
        (root / "docs" / "bugs" / f"{identifier}.md").write_text(text, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "the regression fixture")
    return root


@pytest.fixture
def real_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    """The project's own pytest first on the `PATH` the regressions run under, its plugins off."""
    path = os.pathsep.join([str(runner_directory("pytest")), os.environ.get("PATH", "")])
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


def regressions(tmp_path: Path, root: Path, *flags: str) -> tuple[int, str, str]:
    return cli(root, tmp_path, "bugs", "regressions", *flags)


def as_json(tmp_path: Path, root: Path) -> tuple[int, dict[str, object]]:
    code, out, _ = regressions(tmp_path, root, "--json")
    return code, json.loads(out)


@needs_git
@needs_runner("pytest")
@pytest.mark.usefixtures("real_pytest")
def test_a_fixed_entry_whose_regression_passes_is_proved(tmp_path: Path) -> None:
    root = ledger(tmp_path, {"BR-001": ("fixed", PASSING)})
    code, out, _ = regressions(tmp_path, root)
    assert code == 0
    first, last = out.splitlines()
    assert first.startswith("BR-001: proved: ")
    assert last == REGRESSIONS_RAN.format(ran=1, not_proved=0)


@needs_git
@needs_runner("pytest")
@pytest.mark.usefixtures("real_pytest")
def test_a_failing_regression_exits_1_and_names_its_entry(tmp_path: Path) -> None:
    root = ledger(tmp_path, {"BR-002": ("fixed", FAILING)})
    code, out, _ = regressions(tmp_path, root)
    assert code == 1
    assert out.splitlines()[0].startswith("BR-002: failed: ")


@needs_git
@needs_runner("pytest")
@pytest.mark.usefixtures("real_pytest")
def test_a_passing_sibling_is_not_counted_as_not_proved(tmp_path: Path) -> None:
    root = ledger(tmp_path, {"BR-001": ("fixed", PASSING), "BR-002": ("fixed", FAILING)})
    code, data = as_json(tmp_path, root)
    assert code == 1
    assert data["not_proved"] == 1
    assert [(row["id"], row["verdict"]) for row in data["regressions"]] == [  # type: ignore[attr-defined]
        ("BR-001", "proved"),
        ("BR-002", "failed"),
    ]
    assert data["regressions"][0]["path"] == "docs/bugs/BR-001.md"  # type: ignore[index]


@needs_git
def test_only_fixed_entries_run(tmp_path: Path) -> None:
    # Why only `fixed`: `docs/cli.md`'s `stayfixed bugs regressions`. Mutation (oracle):
    # `mutations/`'s "bugs regressions runs an entry of any status" -> all five run.
    failing = ["sh", "-c", "exit 1"]
    entries = {
        "BR-001": ("open", failing),
        "BR-002": ("partial", failing),
        "BR-003": ("rejected", failing),
        "BR-004": ("void", failing),
        "BR-005": ("fixed", UNRECOGNISED),
    }
    code, data = as_json(tmp_path, ledger(tmp_path, entries))
    assert [row["id"] for row in data["regressions"]] == ["BR-005"]  # type: ignore[attr-defined]
    assert (code, data["not_proved"]) == (1, 1)


@needs_git
def test_an_argv_no_adapter_recognises_is_not_proved(tmp_path: Path) -> None:
    # The argv prints a runner's green summary and exits 0, and nothing counts a report of it.
    # Mutation (oracle): `mutations/`'s "bugs regressions counts every verdict as proved" -> exit
    # 0 and nothing not proved.
    root = ledger(tmp_path, {"BR-001": ("fixed", UNRECOGNISED)})
    code, data = as_json(tmp_path, root)
    assert data["regressions"][0]["verdict"] == "not proven"  # type: ignore[index]
    assert (code, data["not_proved"]) == (1, 1)


@needs_git
def test_no_fixed_entry_with_a_regression_is_one_sentence_and_exit_0(tmp_path: Path) -> None:
    root = ledger(tmp_path, {"BR-001": ("fixed", []), "BR-002": ("open", UNRECOGNISED)})
    assert regressions(tmp_path, root) == (0, f"{NO_REGRESSIONS}\n", "")


@needs_git
def test_an_interrupted_regression_starts_no_further_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `prove` returns an interrupted receipt rather than raising, for a Ctrl-C or the SIGTERM a
    # custom gate's bound sends: a loop that went on would start the next runner after the signal.
    # Mutation (oracle): `mutations/`'s "bugs regressions goes on past an interrupt" -> the second
    # entry runs.
    started: list[tuple[str, ...]] = []

    def interrupted(argv: Sequence[str], **_: object) -> Receipt:
        started.append(tuple(argv))
        return Receipt(Verdict.NOT_PROVEN, INTERRUPTED, "", tuple(argv))

    monkeypatch.setattr(module, "prove", interrupted)
    root = ledger(tmp_path, {"BR-001": ("fixed", PASSING), "BR-002": ("fixed", FAILING)})
    code, data = as_json(tmp_path, root)
    assert started == [tuple(PASSING)]
    assert [row["id"] for row in data["regressions"]] == ["BR-001"]  # type: ignore[attr-defined]
    assert code == 1


@needs_git
@needs_runner("pytest")
@pytest.mark.usefixtures("real_pytest")
def test_json_stays_one_object_while_the_runner_prints(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # A runner inherits file descriptors, not Python's streams: one that wrote to descriptor 1
    # would land between whatever reads standard output and the object it parses, which `capfd`
    # sees and the frame's own redirection does not.
    root = ledger(tmp_path, {"BR-001": ("fixed", PASSING)})
    code, out, err = regressions(tmp_path, root, "--json")
    assert code == 0
    assert json.loads(out)["regressions"][0]["verdict"] == "proved"
    assert "1 passed" in err
    assert capfd.readouterr().out == ""


@needs_git
def test_the_timeout_is_the_option_or_ten_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each run's bound is the command's own option, through the real parser: ten minutes when it
    # is not given, the value `[gates] custom_timeout_seconds` held in the preset before the gates
    # went, and what `--timeout` says when it is. Anything but a whole number of seconds above 0
    # is the parser's refusal, exit 2, before any entry runs.
    bounds: list[object] = []

    def recorded(argv: Sequence[str], **kwargs: object) -> Receipt:
        bounds.append(kwargs["timeout"])
        return Receipt(Verdict.NOT_PROVEN, "", "", tuple(argv))

    monkeypatch.setattr(module, "prove", recorded)
    root = ledger(tmp_path, {"BR-001": ("fixed", UNRECOGNISED)})
    regressions(tmp_path, root)
    regressions(tmp_path, root, "--timeout", "5")
    assert bounds == [600, 5]
    for value in ("0", "-1", "1.5", "five"):
        with pytest.raises(SystemExit) as refused:
            regressions(tmp_path, root, "--timeout", value)
        assert refused.value.code == 2, value
    assert bounds == [600, 5]
