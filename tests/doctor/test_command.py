"""The `doctor` command: one line, the right exit code, and a remedy the skill can relay.

The report itself is `tests/doctor/test_checks.py`'s. What is untested until this file is the
argparse wiring, the two exit codes — 0 for a report with no red row, and 1, the findings exit
code, for one with any — and the one property of the output that decides whether the skill is
any use: a remedy missing from `--json` is a remedy the user never sees.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import stayfixed
from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.doctor import checks
from stayfixed.doctor.api import OK, RED, SKIP, WARN, Check
from stayfixed.doctor.commands import summarise
from stayfixed.findings import LISTED_LIMIT
from tests.boundaries.test_discovery import UNIMPORTABLE, plant_area
from tests.doctor.test_checks import _initialised
from tests.floor import is_developers
from tests.snapshot import assert_snapshot_unchanged, snapshot


@pytest.fixture(autouse=True)
def _nothing_of_the_developers_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The seam `tests/doctor/test_checks.py` closes with `_env`, closed here instead.

    `run_doctor` passes no `env=`, so `run_checks` falls back to `os.environ` — and that is the
    real environment, which no test in this suite may read: `ignored-env` reports whichever of
    two real variables is set, `diagnostics` finds the harness data root in it and this suite is
    plausibly run inside a session where that points at a real log, and
    `load(root, machine=None)` resolves the developer's own `~/.config/stayfixed/config.toml`.
    The flag cases below cannot pass an environment through argparse, so the environment is made
    hermetic instead of passed.

    `_own_root` is stood down for the same reason and one more: it would otherwise answer with
    this checkout, and the `wrapper` check **executes** what it answers. Every case
    here would then spawn a real `hooks/run-hook.sh`, and `test_a_clean_installation_exits_zero`
    would become false the day that run goes red on somebody's machine — which is a fact about
    their interpreters, not about the argparse wiring this file is for. What the two checks do
    with a plugin root is `tests/doctor/test_checks.py`'s.
    """
    # `is_developers` keeps the suite's floor under the product's `git` bounds, which is the test
    # runner's rather than the developer's: `doctor` runs its `git` in this process, and without
    # the floor a loaded machine could run a five-second `rev-parse` out.
    for name in list(os.environ):
        if is_developers(name):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(checks, "_own_root", lambda: None)


def invoke(argv: list[str]) -> int:
    return run(argv, parser=build_parser(discover_registrars()))


def test_the_command_is_discovered() -> None:
    assert "doctor" in build_parser(discover_registrars()).format_help()


def test_a_clean_installation_exits_zero_with_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every command prints a one-line result. Eighteen rows on stdout would make `doctor`
    # the one command a caller has to parse rather than read, and `--json` is where the rows are.
    root = _initialised(tmp_path)
    code = invoke(["doctor", "--root", str(root), "--home", str(tmp_path / "home")])
    out = capsys.readouterr().out
    assert code == 0
    assert len(out.strip().splitlines()) == 1


def test_a_second_report_is_the_first_and_neither_writes_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The lifecycle's "re-run, nothing changed": `doctor` only reads, so a second run over the
    # same tree reports what the first did and leaves the tree, the home directory included, as
    # it was. No mutation: the command has no write for one to take away, so this holds a
    # property of the whole run rather than one line.
    root = _initialised(tmp_path)
    argv = ["doctor", "--json", "--root", str(root), "--home", str(tmp_path / "home")]
    (tmp_path / "home").mkdir(exist_ok=True)
    before = snapshot(tmp_path)
    first = (invoke(argv), capsys.readouterr().out)
    second = (invoke(argv), capsys.readouterr().out)
    assert first == second and json.loads(first[1])["checks"]
    assert_snapshot_unchanged(tmp_path, before)


def test_the_runner_this_command_builds_is_bounded_for_a_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one call this area makes that leaves the machine is bounded, and here is where it is.

    `runner.NETWORK_TIMEOUT_SECONDS` is five minutes, written for `gh repo create --clone` and
    the clone behind it. `doctor` inherited it for the `ci-ref` row's single `git ls-remote` —
    and `stayfixed init` recording a `[ci] ref` is what made a five-minute block reachable on a
    command whose whole output is one line. The row's own `git` questions go through `gitenv`'s
    five seconds and the wrapper probe through this module's thirty, so the bound here is the
    module's own thirty and `checks.CI_REF_TIMEOUT_SECONDS` carries the argument for it.

    Asserted where the runner is *built*, because that is the only place the choice exists: the
    `Runner` protocol has no timeout and every stub in this suite is bounded at nothing. The
    factory is imported inside `run_doctor`, so patching the module attribute is the seam.

    Mutation (`mutations/`'s "doctor asks the public repository with no bound of its own"):
    `subprocess_runner(timeout=CI_REF_TIMEOUT_SECONDS)` -> `subprocess_runner()` -> this reddens
    on the recorded keyword.
    """
    import stayfixed.runner as runner

    asked: list[float | None] = []
    real = runner.subprocess_runner

    def spy(*, timeout: float | None = None) -> runner.Runner:
        asked.append(timeout)
        return real(timeout=timeout)

    monkeypatch.setattr(runner, "subprocess_runner", spy)
    root = _initialised(tmp_path)
    assert invoke(["doctor", "--root", str(root), "--home", str(tmp_path / "home")]) == 0
    assert asked == [checks.CI_REF_TIMEOUT_SECONDS]
    # And it is narrower than the seam's own default, which is the whole point of asking.
    assert checks.CI_REF_TIMEOUT_SECONDS < runner.NETWORK_TIMEOUT_SECONDS


def test_a_skip_is_not_a_finding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # `ci-ref` skips on a state this repository is in: it records no `[ci] ref`. If a skip
    # exited 1, `doctor` would be red on every correct installation.
    root = _initialised(tmp_path)
    code = invoke(["doctor", "--root", str(root), "--home", str(tmp_path / "home"), "--json"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert [check["name"] for check in report["checks"] if check["status"] == "skip"]


def test_any_red_check_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Exit 1 is "findings". A doctor that always exits 0 is a doctor nothing can gate on: a
    # script or a CI step that runs it reads the exit code, since `stayfixed assess` runs no
    # doctor check. A `stayfixed.toml` that is not TOML is the cheapest red there is, and the
    # report's own first row; a directory with none at all is a warning, which exits 0. Mutation
    # (`mutations/`'s "not-initialised is red with no stayfixed.toml"): the second run exits 1.
    (tmp_path / "stayfixed.toml").write_text("[[[", encoding="utf-8")
    code = invoke(["doctor", "--root", str(tmp_path), "--home", str(tmp_path / "home")])
    assert code == 1
    assert "not-initialised" in capsys.readouterr().out
    (tmp_path / "stayfixed.toml").unlink()
    assert invoke(["doctor", "--root", str(tmp_path), "--home", str(tmp_path / "home")]) == 0


def test_a_machine_file_that_does_not_load_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every command that reads the machine file refuses one that does not load, with exit 1, and
    # `doctor`, which reads it as a session does, exited 0 on it with one warning. Mutation
    # (`mutations/`'s "the preferences row reads a machine file that does not load as one it read
    # past"): exit 0.
    root = _initialised(tmp_path)
    machine = tmp_path / "machine.toml"
    machine.write_text("[personal\nx = 1\n", encoding="utf-8")
    argv = ["doctor", "--root", str(root), "--home", str(tmp_path / "home"), "--json"]
    assert invoke([*argv, "--machine", str(machine)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in report["checks"] if c["status"] == RED] == ["preferences"]


def test_an_area_whose_doctor_module_fails_to_import_costs_one_red_row_and_not_the_report(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # End to end, through a real import: an area whose `doctor.py` raises when imported is one
    # red row named after the area, exit 1 for it, and every other row exactly as a report without
    # the area gives it. Imported unguarded, the exception would leave `run_checks` for the CLI,
    # which turns it into an internal error with no report at all. Mutation (oracle):
    # `mutations/`'s "discovery lets an area's import failure escape" -> the `RuntimeError`
    # escapes and nothing is reported.
    root = _initialised(tmp_path)
    argv = ["doctor", "--root", str(root), "--home", str(tmp_path / "home"), "--json"]
    assert invoke(argv) == 0
    baseline = json.loads(capsys.readouterr().out)["checks"]
    plant_area(request, monkeypatch, tmp_path / "areas", "zzplanted", {"doctor.py": UNIMPORTABLE})
    code = invoke(argv)
    out = capsys.readouterr().out
    assert code == 1
    assert json.loads(out)["checks"] == [
        *baseline,
        {
            "name": "zzplanted",
            "status": "red",
            "detail": "stayfixed.zzplanted.doctor could not be imported: RuntimeError",
            "remedy": "report this, with the command you ran",
        },
    ]
    assert "IGNORE" not in out


def test_the_json_form_carries_every_check_and_its_remedy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The skill relays remedies verbatim, so a remedy missing from `--json` is a remedy the
    # user never sees — and the summary line has room for none of them. The count is the
    # report's fifteen rows, held beside `README.md`, `docs/cli.md`, the doctor skill and the
    # smoke workflow by `tests/test_documents.py`.
    (tmp_path / "stayfixed.toml").write_text("[[[", encoding="utf-8")
    code = invoke(["doctor", "--root", str(tmp_path), "--home", str(tmp_path / "home"), "--json"])
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert len(report["checks"]) == 15
    assert all({"name", "status", "detail", "remedy"} <= set(check) for check in report["checks"])
    red = next(check for check in report["checks"] if check["status"] == "red")
    assert red["remedy"]


def test_doctor_json_carries_no_codex_hooks_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The row no build could answer, a skip on every machine, left the report for the README's
    # Codex reach table: `doctor --json` carries no `codex-hooks`, even where `[stayfixed] agents`
    # lists Codex.
    root = tmp_path / "project"
    root.mkdir()
    (root / "stayfixed.toml").write_text(
        f'[stayfixed]\nversion = "{stayfixed.__version__}"\n'
        'agents = ["claude", "codex"]\n\n[project]\nname = "p"\n',
        encoding="utf-8",
    )
    invoke(["doctor", "--root", str(root), "--home", str(tmp_path / "home"), "--json"])
    names = [check["name"] for check in json.loads(capsys.readouterr().out)["checks"]]
    assert "wrapper" in names and "codex-hooks" not in names


def test_the_summary_line_is_bounded() -> None:
    # `findings.LISTED_LIMIT` exists because an unbounded summary pushes the repairing command
    # off the end of the line, and fourteen checks is already past eight. Asserted over a
    # synthetic report rather than a fixture, because arranging nine simultaneous real failures
    # would be a test about the fixture.
    checks = [Check(f"check-{n}", RED, "d", "r") for n in range(LISTED_LIMIT + 3)]
    summary = summarise(checks)
    assert len(summary.splitlines()) == 1
    assert "and 3 more" in summary
    assert "check-10" not in summary


def test_the_summary_counts_every_status(tmp_path: Path) -> None:
    # The vacuity guard for the line above: a summary that named only the red rows would pass
    # it while saying nothing about a warning or a skip.
    summary = summarise(
        [
            Check("a", OK, "", ""),
            Check("b", WARN, "", ""),
            Check("c", SKIP, "", ""),
            Check("d", RED, "", ""),
        ]
    )
    assert "1 red" in summary
    assert "1 warn" in summary
    assert "1 skipped" in summary
