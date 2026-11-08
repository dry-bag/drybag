from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from stayfixed import __version__
from stayfixed.cli import (
    Registrar,
    SubParsers,
    build_parser,
    discover_registrars,
    main,
    run,
    split_json_flag,
)
from stayfixed.errors import Failure, Refusal
from stayfixed.result import Result
from tests.cli import subparsers


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_module_entry_point_runs_without_the_console_script() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "stayfixed", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert __version__ in completed.stdout


def _area(name: str, func: Callable[[argparse.Namespace], Result]) -> Registrar:
    def register(groups: SubParsers) -> None:
        group = groups.add_parser(name)
        sub = group.add_subparsers(dest="command", metavar="<command>")
        cmd = sub.add_parser("go")
        cmd.set_defaults(func=func)

    return register


def _ok(args: argparse.Namespace) -> Result:
    return Result("probe ran", {"n": 1})


def _failing(args: argparse.Namespace) -> Result:
    raise Failure("three findings")


def _refusing(args: argparse.Namespace) -> Result:
    raise Refusal("an absent guard is not permission")


def test_a_result_prints_its_summary_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go"], parser=build_parser([_area("probe", _ok)])) == 0
    assert capsys.readouterr().out.strip() == "probe ran"


# A name git or the disk handed over in bytes that are not UTF-8 reaches Python with a
# surrogate escape per byte, and a summary that names the path carries it to stdout.
UNDECODABLE = os.fsdecode(b"caf\xe9.md")


def _names_a_path(args: argparse.Namespace) -> Result:
    return Result(f"FAIL: {UNDECODABLE}", {"path": UNDECODABLE})


def _stdout(monkeypatch: pytest.MonkeyPatch, errors: str) -> io.BytesIO:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="utf-8", errors=errors, write_through=True)
    monkeypatch.setattr(sys, "stdout", stream)
    return raw


def test_a_summary_naming_a_path_that_is_not_utf_8_prints_under_a_strict_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Under a UTF-8 locale such as `en_US.UTF-8`, Python's stdout encodes strictly, so `print`
    # raised `UnicodeEncodeError` on the escape and the frame reported `internal error`, exit 2,
    # in place of the command's own answer. The escape is printed as `\udce9` instead, and the
    # exit code is the command's. Mutation (advisory): drop the reconfiguration in `run` — this
    # reddens on the exit code.
    raw = _stdout(monkeypatch, "strict")
    assert run(["probe", "go"], parser=build_parser([_area("probe", _names_a_path)])) == 0
    assert raw.getvalue() == b"FAIL: caf\\udce9.md\n"


def test_json_output_is_unchanged_by_the_strict_stdout_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `--json` escapes every non-ASCII character itself, so the machine-readable output never
    # reaches the fallback: the bytes are what they were, and a JSON reader gets the path back.
    raw = _stdout(monkeypatch, "strict")
    assert run(["probe", "go", "--json"], parser=build_parser([_area("probe", _names_a_path)])) == 0
    assert raw.getvalue().isascii()
    assert json.loads(raw.getvalue())["path"] == UNDECODABLE


def test_a_stdout_that_carries_the_bytes_already_is_left_as_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # In Python's UTF-8 mode (`LANG` unset, or `C`) stdout is `surrogateescape`, which writes the
    # original byte back: the path as it is on disk. That is kept; only a strict stream changes.
    # Mutation (advisory): reconfigure every stream whatever its handler — this reddens.
    raw = _stdout(monkeypatch, "surrogateescape")
    assert run(["probe", "go"], parser=build_parser([_area("probe", _names_a_path)])) == 0
    assert raw.getvalue() == b"FAIL: caf\xe9.md\n"


def test_json_flag_works_anywhere_on_the_line(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go", "--json"], parser=build_parser([_area("probe", _ok)])) == 0
    assert json.loads(capsys.readouterr().out) == {"summary": "probe ran", "n": 1}
    assert run(["--json", "probe", "go"], parser=build_parser([_area("probe", _ok)])) == 0
    assert json.loads(capsys.readouterr().out) == {"summary": "probe ran", "n": 1}


def test_failure_exits_one_and_refusal_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go"], parser=build_parser([_area("probe", _failing)])) == 1
    assert "three findings" in capsys.readouterr().err
    assert run(["probe", "go"], parser=build_parser([_area("probe", _refusing)])) == 2
    assert "refused: an absent guard" in capsys.readouterr().err


def test_failures_emit_json_when_asked(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go", "--json"], parser=build_parser([_area("probe", _failing)])) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "failed"


def test_every_command_describes_itself_and_names_json_in_its_own_help() -> None:
    # `stayfixed attach --help` printed `usage:` and jumped to the options: the one sentence the
    # area registered with `help=` reached the parent's listing and nothing else. And `--json`
    # is stripped before argparse sees it, so no command could mention it -- while the README
    # promised it works everywhere. Mutation: `_finish` not called from `build_parser` reddens
    # every assertion below.
    parser = build_parser(discover_registrars())
    top = parser.format_help()
    assert "--json" in top
    groups = subparsers(parser)
    assert groups is not None
    listed = [action.dest for action in groups._choices_actions]
    assert listed == sorted(listed)
    for name, sub in groups.choices.items():
        text = sub.format_help()
        assert sub.description, f"`stayfixed {name}` has no description"
        assert "--json" in text, f"`stayfixed {name} --help` never mentions --json"
        nested = subparsers(sub)
        for leaf_name, leaf in (nested.choices if nested is not None else {}).items():
            assert leaf.description, f"`stayfixed {name} {leaf_name}` has no description"
            assert "--json" in leaf.format_help()


def test_areas_are_discovered_from_the_package() -> None:
    names = {registrar.__module__ for registrar in discover_registrars()}
    assert "stayfixed.doctor.commands" in names


def _subcommands(group: str) -> set[str]:
    """The commands the real parser registers under `stayfixed <group>`."""
    groups = subparsers(build_parser(discover_registrars()))
    assert groups is not None
    nested = subparsers(groups.choices[group])
    assert nested is not None
    return set(nested.choices)


def _exploding(args: argparse.Namespace) -> Result:
    raise KeyError("no such key")


def test_an_internal_error_in_a_command_exits_two_not_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Exit 1 is reserved for findings, so a command's own bug must not read as three findings.
    assert run(["probe", "go"], parser=build_parser([_area("probe", _exploding)])) == 2
    assert "stayfixed: internal error: KeyError: 'no such key'" in capsys.readouterr().err


def test_an_internal_error_still_renders_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go", "--json"], parser=build_parser([_area("probe", _exploding)])) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "internal error"


def _broken() -> list[Registrar]:
    raise RuntimeError("area exploded at import time")


def test_a_broken_area_module_maps_to_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("stayfixed.cli.discover_registrars", _broken)
    assert main([]) == 2
    assert "stayfixed: internal error: RuntimeError: area exploded at import time" in (
        capsys.readouterr().err
    )


@pytest.mark.parametrize("event", ["UserPromptSubmit", "SessionStart", "PreToolUse"])
def test_a_broken_area_never_costs_a_hook_event(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], event: str
) -> None:
    # One later area's import-time bug in its commands.py must not cost the user what they
    # typed (exit 2 on UserPromptSubmit erases the prompt) nor block a tool call.
    monkeypatch.setattr("stayfixed.cli.discover_registrars", _broken)
    assert main(["hook", event]) == 0
    err = capsys.readouterr().err
    assert "area exploded at import time" in err
    assert "continuing open" in err


def test_the_json_flag_does_not_hide_the_hook_event_from_the_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("stayfixed.cli.discover_registrars", _broken)
    assert main(["--json", "hook", "UserPromptSubmit"]) == 0


def test_a_broken_area_on_a_non_hook_command_still_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("stayfixed.cli.discover_registrars", _broken)
    assert main(["doctor"]) == 2
    assert "stayfixed: internal error: RuntimeError" in capsys.readouterr().err


def _broken_by_keyboard_interrupt() -> list[Registrar]:
    raise KeyboardInterrupt()


@pytest.mark.parametrize(
    ("argv", "code"),
    [(["hook", "SessionStart"], 0), (["hook", "PreToolUse"], 0), (["doctor"], 2)],
)
def test_discovery_raising_a_base_exception_gets_the_same_verdicts_as_an_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    code: int,
) -> None:
    # `main`'s own guard around discovery and the parser build stayed `except Exception` after
    # `dispatch`, `run_hook` and `cli.run` were widened to `BaseException`, so an area importing
    # something that raises KeyboardInterrupt or asyncio.CancelledError at import time bypassed
    # `_discovery_failed` entirely instead of degrading open on a hook and refusing on a
    # non-hook command, exactly like a RuntimeError already does.
    monkeypatch.setattr("stayfixed.cli.discover_registrars", _broken_by_keyboard_interrupt)
    assert main(argv) == code
    err = capsys.readouterr().err
    assert "stayfixed: internal error: KeyboardInterrupt" in err
    assert ("continuing open" in err) == (code == 0)


def _register_explodes(groups: SubParsers) -> None:
    raise RuntimeError("register exploded")


def _claims_doctor(groups: SubParsers) -> None:
    groups.add_parser("doctor")


BROKEN_BUILDS: dict[str, list[Registrar]] = {
    "register-raises": [_register_explodes],
    "two-areas-claim-one-group": [_claims_doctor, _claims_doctor],
}


@pytest.mark.parametrize("registrars", list(BROKEN_BUILDS.values()), ids=list(BROKEN_BUILDS))
@pytest.mark.parametrize(
    ("argv", "code"),
    [(["hook", "PreToolUse"], 0), (["hook", "UserPromptSubmit"], 0), (["doctor"], 2)],
)
def test_a_broken_parser_build_is_judged_like_a_broken_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    registrars: list[Registrar],
    argv: list[str],
    code: int,
) -> None:
    # An area's `register()` runs during the parser build, one line outside the try that judged its
    # import, and returned 1 where a hook must degrade open. Two areas claiming one group name
    # is the same failure, and a plausible merge accident in an architecture that adds areas.
    monkeypatch.setattr("stayfixed.cli.discover_registrars", lambda: list(registrars))
    assert main(argv) == code
    err = capsys.readouterr().err
    assert "stayfixed: internal error" in err
    assert ("continuing open" in err) == (code == 0)


def _unserialisable(args: argparse.Namespace) -> Result:
    return Result("ok", {"where": Path("/tmp")})


def test_a_result_json_cannot_render_refuses_instead_of_reading_as_findings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Only the machine-readable path breaks on a Path in `Result.data` — the path CI consumes —
    # so serialising must sit inside the try that reserves exit 1 for findings.
    parser = build_parser([_area("probe", _unserialisable)])
    assert run(["probe", "go", "--json"], parser=parser) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "internal error"


def test_the_plain_text_path_still_prints_a_summary_it_cannot_serialise(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser([_area("probe", _unserialisable)])
    assert run(["probe", "go"], parser=parser) == 0
    assert capsys.readouterr().out.strip() == "ok"


@pytest.mark.parametrize("returned", [None, "x"])
def test_a_command_that_returns_neither_a_result_nor_an_exit_code_refuses(
    capsys: pytest.CaptureFixture[str], returned: object
) -> None:
    parser = build_parser([_area("probe", lambda args: cast(Result, returned))])
    assert run(["probe", "go"], parser=parser) == 2
    assert "stayfixed: internal error" in capsys.readouterr().err


@pytest.mark.parametrize("raised", [asyncio.CancelledError(), KeyboardInterrupt()], ids=type)
def test_a_base_exception_in_a_command_is_an_internal_error_not_the_interpreters_code(
    capsys: pytest.CaptureFixture[str], raised: BaseException
) -> None:
    def interrupted(args: argparse.Namespace) -> Result:
        raise raised

    parser = build_parser([_area("probe", interrupted)])
    assert run(["probe", "go"], parser=parser) == 2
    assert f"internal error: {type(raised).__name__}" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "kept", "as_json"),
    [
        (["doctor", "--json"], ["doctor"], True),
        (["--json", "doctor"], ["doctor"], True),
        (["doctor"], ["doctor"], False),
    ],
)
def test_json_is_read_anywhere_on_the_line(argv: list[str], kept: list[str], as_json: bool) -> None:
    assert split_json_flag(argv) == (kept, as_json)
