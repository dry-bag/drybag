"""The two smoke scripts, run here against the checkout as the plugin root.

CI runs them against the INSTALLED copy; this proves the scripts' own logic — that a
mismatch is reported and a match is not — so a green CI row means the plugin, not the script.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from stayfixed import gitenv
from tests.floor import SUITE_GIT_FLOOR_SECONDS
from tests.gitfixture import needs_git
from tests.scriptload import SCRIPTS, load

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    return load(SCRIPTS / f"{name}.py", name)


def _plugin(tmp_path: Path, *, launcher: str | None = None, hooks: Path | None = None) -> Path:
    """A plugin root: the shipped `hooks/`, and either the real launcher or a planted one."""
    planted = tmp_path / "plugin"
    _copy_hooks(hooks or ROOT / "hooks", planted)
    if launcher is None:
        shutil.copytree(ROOT / "scripts", planted / "scripts")
    else:
        (planted / "scripts").mkdir()
        (planted / "scripts" / "stayfixed").write_text(launcher, encoding="utf-8")
    return planted


def _copy_hooks(hooks: Path, planted: Path) -> None:
    shutil.copytree(hooks, planted / "hooks")


# A launcher that answers everything the way a broken plugin does: something on stderr, exit 1,
# which the wrapper turns into exit 0 and a line on stderr.
FAULTY = """
import sys

sys.stderr.write("boom\\n")
sys.exit(1)
"""


@needs_git
def test_every_hook_entry_answers_its_sample_event_through_the_checkout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The wrapper's own exit mapping lives in tests/hooks/test_wrapper.py; this is the positive
    # row per entry: every `hooks.json` command, fed the event it is filed under, exits 0 with
    # what its handler says.
    #
    # The summary line and not only the exit code: `main` returns 0 over a report with one row
    # exactly as it does over a report with fourteen, and the sibling files in this same tree
    # state their own count for that reason (`test_check_artifacts.py`, `test_mutation_oracle`).
    # Mutation (declared): blind the entries-and-rows floor.
    smoke = _load("smoke_hooks")
    code = smoke.main(
        [
            "--plugin-root",
            str(ROOT),
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "smoke-project"),
            "--scratch",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "12 entries, 13 row(s), 0 failure(s)" in out, out


@needs_git
def test_a_launcher_fault_is_not_mistaken_for_an_injection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    smoke = _load("smoke_hooks")
    code = smoke.main(
        [
            "--plugin-root",
            str(_plugin(tmp_path, launcher=FAULTY)),
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "smoke-project"),
            "--scratch",
            str(tmp_path / "s"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1, out
    # The entries that carry repository bytes emitted nothing, which is what every one of them
    # did against the checkout before the fixture had a store at all.
    #
    # Mutation (declared, `mutations/`'s "the hook smoke stops reading what an injection entry
    # injected"): the registry lookup answers `None` -> this reddens.
    assert "injected nothing carrying '<<<stayfixed:repository-data'" in out, out


# A launcher that is the real one for everything but the red-run entry, which it answers as an
# entry whose handler said nothing does: exit 0 and the event's envelope with no context in it.
SILENT_ON_FAILURE = f"""
import json, runpy, sys

if sys.argv[1:3] == ["hook", "PostToolUseFailure"]:
    sys.stdin.read()
    print(json.dumps({{"hookSpecificOutput": {{"hookEventName": "PostToolUseFailure"}}}}))
    sys.exit(0)
runpy.run_path({str(ROOT / "scripts" / "stayfixed")!r}, run_name="__main__")
"""


@needs_git
def test_a_red_run_entry_that_says_nothing_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The red-run note is all the `PostToolUseFailure` entry is for, and an envelope naming the
    # event, exit 0, is what that entry prints whether or not its handler spoke: the row asks for
    # the note by its words. Every other row is the real launcher's, so the one failure is this
    # row's. Mutation (declared, `mutations/`'s "the hook smoke stops reading the context an
    # entry printed"): the `context_says` check never fails -> this reddens.
    smoke = _load("smoke_hooks")
    code = smoke.main(
        [
            "--plugin-root",
            str(_plugin(tmp_path, launcher=SILENT_ON_FAILURE)),
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "smoke-project"),
            "--scratch",
            str(tmp_path / "s"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1, out
    assert "the context does not say 'Before calling this red a flake" in out, out
    assert "12 entries, 13 row(s), 1 failure(s)" in out, out


@needs_git
def test_a_wrapper_that_answers_wrongly_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The script's own oracle: an installed wrapper that exits 2, which blocks a `PreToolUse`
    # call, must make that row fail. Mutation (declared): drop the `expected != done.returncode`
    # comparison in `smoke_hooks.check_entry` -> the row's reason goes and this reddens.
    smoke = _load("smoke_hooks")
    planted = tmp_path / "plugin"
    _copy_hooks(ROOT / "hooks", planted)
    (planted / "hooks" / "run-hook.sh").write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    (planted / "scripts").mkdir()
    (planted / "scripts" / "stayfixed").write_text("raise SystemExit(0)\n", encoding="utf-8")
    code = smoke.main(
        [
            "--plugin-root",
            str(planted),
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "smoke-project"),
            "--scratch",
            str(tmp_path),
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "exited 2, expected 0" in out


@needs_git
def test_hooks_json_losing_an_event_fails_instead_of_running_fewer_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The guard held one direction. `unsampled = events - SAMPLES.keys()` catches `hooks.json`
    # GAINING an event with no sample; `hooks.json` LOSING one shrinks `found`, leaves
    # `unsampled` empty, runs fewer rows and prints a green summary — the entry stopped being
    # smoke-tested and the script said nothing. That is the vacuous shape this repository names,
    # arriving through the guard written to prevent it.
    #
    # `PostToolUse` is the event removed because it is the one with exactly one sample, so its
    # rows are the whole of what goes missing.
    #
    # Mutation (declared, `mutations/`'s "the hook smoke stops noticing an event that lost its
    # entry"): the `unentered` set is emptied -> the run proceeds on the remaining entries, every
    # row passes, `main` returns 0, and both assertions below redden.
    smoke = _load("smoke_hooks")
    planted = tmp_path / "plugin"
    _copy_hooks(ROOT / "hooks", planted)
    shutil.copytree(ROOT / "scripts", planted / "scripts")
    entries = planted / "hooks" / "hooks.json"
    document = json.loads(entries.read_text(encoding="utf-8"))
    assert "PostToolUse" in document["hooks"], "the fixture removes an event that is there"
    del document["hooks"]["PostToolUse"]
    entries.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    code = smoke.main(
        [
            "--plugin-root",
            str(planted),
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "smoke-project"),
            "--scratch",
            str(tmp_path),
        ]
    )
    assert code == 1
    assert "no hook entry for ['PostToolUse']" in capsys.readouterr().out


@needs_git
def test_hooks_json_losing_a_bundle_fails_instead_of_injecting_one_fewer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same question for the six entries that carry repository bytes. `SAMPLES` is keyed by
    # EVENT, so dropping one of the seven `SessionStart` entries leaves every event still
    # sampled, runs one row fewer and prints a green summary — the bundle stopped being
    # smoke-tested and nothing said so.
    #
    # Mutation (declared, `mutations/`'s "the hook smoke stops noticing a bundle that lost its
    # entry"): the `ungathered` set is emptied -> the run proceeds on eight entries and both
    # assertions below redden.
    smoke = _load("smoke_hooks")
    planted = _plugin(tmp_path)
    entries = planted / "hooks" / "hooks.json"
    document = json.loads(entries.read_text(encoding="utf-8"))
    groups = document["hooks"]["SessionStart"][0]["hooks"]
    dropped = "--bundle volatile-notes --part 3"
    kept = [entry for entry in groups if dropped not in entry["command"]]
    assert len(kept) == len(groups) - 1, "the fixture removes an entry that is there"
    document["hooks"]["SessionStart"][0]["hooks"] = kept
    entries.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    code = smoke.main(
        [
            "--plugin-root",
            str(planted),
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "smoke-project"),
            "--scratch",
            str(tmp_path / "s"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1, out
    assert "hooks.json lost a bundle" in out, out


@needs_git
def test_hooks_json_gaining_an_entry_is_reported_rather_than_quietly_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The other side of the count, and the one neither event set can see: a duplicated entry
    # changes no event and no bundle, runs a twelfth row and prints a summary that reads
    # green. The floor is the only thing that answers.
    #
    # Mutation (declared, `mutations/`'s "the hook smoke stops counting its own entries and rows"):
    # the comparison against `EXPECTED_ENTRIES`/`EXPECTED_ROWS` is disabled -> `main` returns 0
    # and both assertions below redden.
    smoke = _load("smoke_hooks")
    planted = _plugin(tmp_path)
    entries = planted / "hooks" / "hooks.json"
    document = json.loads(entries.read_text(encoding="utf-8"))
    groups = document["hooks"]["SessionStart"][0]["hooks"]
    groups.append(dict(groups[0]))
    entries.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    code = smoke.main(
        [
            "--plugin-root",
            str(planted),
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "smoke-project"),
            "--scratch",
            str(tmp_path / "s"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1, out
    assert "13 entries and 14 rows, expected 12 and 13" in out, out


@needs_git
def test_the_exfiltration_scenario_holds_against_the_checkout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The clone-to-exfiltration scenario: a hostile clone with in-repo memory at `startup: -1`,
    # a `project.name` naming another project, and a committed settings `env` block naming a
    # machine configuration inside the clone. Asserted separately: the clone's notes reach a
    # session only as data and never as a standing rule, the hook ignored the clone's
    # STAYFIXED_CONFIG, and `attach` refuses.
    # The MCP arm is
    # not run: stayfixed ships no MCP server yet (the README lists the memory MCP server under
    # "Not yet"), and the script says so in its own output.
    #
    # The count as well as the exit code, because four of the five rows assert an ABSENCE and a
    # report holding one row satisfies `failures == 0` identically. Measured: with
    # `report.rows = report.rows[:1]` before the summary, this file was still five green.
    # Mutation (declared, `mutations/`'s "the exfiltration scenario stops recording the rows that
    # passed"): `Report.row` banks only the failures, the report empties, and the floor is what
    # notices.
    exfil = _load("smoke_exfiltration")
    code = exfil.main(
        [
            "--plugin-root",
            str(ROOT),
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "hostile-project"),
            "--scratch",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "5 row(s), 0 failure(s)" in out, out


@needs_git
def test_the_exfiltration_scenario_reports_a_row_that_went_the_wrong_way(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same oracle for the other script, and the reason the scenario's first row carries a
    # positive control: every other row asserts an ABSENCE, and a scenario whose pipeline is
    # broken prints the same absences. Here the volatile note is emptied before the run, so the
    # control — the clone's note reaching a session as data — is what turns the row red; the
    # other four negative rows stay green on a store with nothing in it, which is the point.
    exfil = _load("smoke_exfiltration")
    fixture = tmp_path / "fixture"
    shutil.copytree(ROOT / "tests" / "fixtures" / "hostile-project", fixture)
    note = fixture / "docs" / "memory" / "volatile" / "carried.md"
    note.write_text(note.read_text(encoding="utf-8").replace("CANARY-AS-DATA", "nothing"), "utf-8")
    code = exfil.main(
        ["--plugin-root", str(ROOT), "--fixture", str(fixture), "--scratch", str(tmp_path / "s")]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL  the clone's notes reach a session as data and never as a standing rule" in out, (
        out
    )


def test_the_hook_smoke_asks_for_the_red_run_note_in_the_words_the_note_opens_with() -> None:
    # `RED_RUN_NOTE` is copied from `stayfixed.hints.hygiene.LEAD` rather than imported, as
    # `FLOOR_VARIABLE` is, and held equal here: a lead reworded in the guard would otherwise turn
    # the `PostToolUseFailure` row red in CI for a note that still speaks. Mutation (oracle):
    # `mutations/`'s "the hook smoke asks for a red-run note the guard does not open with".
    from stayfixed.hints.hygiene import LEAD

    assert _load("smoke_hooks").RED_RUN_NOTE == LEAD


def test_a_hook_entry_keeps_the_suite_floor_and_no_other_stayfixed_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both smoke scripts strip every `STAYFIXED_*` variable so an entry never reads this
    # developer's own stayfixed, and without an exception that strip would take the suite's floor
    # under the product's `git` bounds too. The floor alone is kept, spelled as the product
    # spells it, in the one base environment both scripts build on. Mutation (oracle):
    # `mutations/`'s "the hook smoke strips the suite's floor" -> this reddens.
    smoke = _load("smoke_hooks")
    assert smoke.FLOOR_VARIABLE == gitenv.FLOOR_VARIABLE
    monkeypatch.setenv("STAYFIXED_CONFIG", str(tmp_path / "developer.toml"))
    env = smoke.session_env(plugin_root=ROOT, project=tmp_path, home=tmp_path, data=tmp_path)
    assert env[gitenv.FLOOR_VARIABLE] == str(SUITE_GIT_FLOOR_SECONDS)
    assert "STAYFIXED_CONFIG" not in env
