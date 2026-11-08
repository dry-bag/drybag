"""The `setup` command surface: CLI wiring over `setup.run.setup` and `guards.githooks`.

`tests/setup/test_setup.py` and `tests/setup/test_git_hooks.py` already exercise the two
behaviours directly; what is untested until this file is the argparse wiring itself — the
group is registered, the flags reach the functions those tests call, and a real command-line
invocation exits 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from drybag import fsops
from drybag.cli import build_parser, discover_registrars, run
from drybag.overlay.identity import NOT_A_RECORD
from drybag.overlay.layout import IDENTITY_RECORD
from drybag.printed import quoted
from drybag.setup.api import SetupReport
from drybag.setup.machine import SETUP_SANDBOXED
from tests.parserlimits import LONG_NUMBER
from tests.runners import Recorder
from tests.sandboxed import refuse_writes_under


def invoke(argv: list[str]) -> int:
    return run(argv, parser=build_parser(discover_registrars()))


def test_the_command_is_discovered() -> None:
    help_text = build_parser(discover_registrars()).format_help()
    assert "setup" in help_text


@pytest.mark.parametrize(
    "name",
    ["Superpowers", "-flag", "a b", "x@evil", "../x", "a\x1b[2J"],
    ids=["capital", "option-shaped", "space", "marketplace", "path", "escape"],
)
def test_the_parser_refuses_a_plugin_name_outside_its_grammar_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    # `--plugin NAME` is joined to the preset's marketplace into one argv element, so a name is
    # lowercase letters, digits and `-`, led by a letter or a digit: nothing that reads as an
    # option, names a marketplace of its own or reaches past the name. Refused by the parser, naming
    # the rule and never the value, before anything is written or run. Mutation: `mutations/`'s
    # "setup --plugin takes any name".
    from drybag.setup.commands import PLUGIN_RULE

    stub = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: stub)
    machine = tmp_path / "config.toml"
    argv = ["setup", "--home", str(tmp_path / "home"), "--machine", str(machine)]
    with pytest.raises(SystemExit):
        invoke([*argv, f"--plugin={name}"])
    err = capsys.readouterr().err
    assert PLUGIN_RULE in err, err
    assert name not in err, err
    assert not machine.exists() and not stub.calls


def test_the_preset_flow_runs_through_the_cli_with_a_stubbed_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Patched at `drybag.setup.commands` itself, not at `overlay.api`: that module-level import
    # is what `run_setup` calls directly, so a test that wants to keep this command away from a real
    # `claude`/`codex` monkeypatches a name this module owns rather than reaching two hops into a
    # dependency's own attribute. The recorder answers every call with success, because the run
    # names a plugin to install and a test here must never reach a real `claude` or `codex`.
    stub = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: stub)
    home = tmp_path / "home"
    machine = tmp_path / "config.toml"
    code = invoke(
        [
            "setup",
            "--preset",
            "recommended",
            "--home",
            str(home),
            "--machine",
            str(machine),
            "--plugin",
            "superpowers",
        ]
    )
    assert code == 0
    assert (home / ".claude" / "settings.json").is_file()
    assert machine.is_file()
    assert ["claude", "plugin", "install", "superpowers@claude-plugins-official"] in stub.calls
    # The seam actually fired: at least the marketplace-add call reached the stub rather than
    # a real binary. An empty list here would mean the patch above stopped applying.
    assert stub.calls, "the stubbed runner was never called; the patch may have stopped applying"


def test_uninstall_without_git_hooks_refuses_and_runs_no_machine_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--uninstall` means something only beside `--git-hooks`. Taken alone it was dropped and the
    # machine setup ran, exit 0, for a person who asked for a hook to be removed.
    #
    # Mutation (`mutations/`'s "setup drops a lone --uninstall and runs the machine setup"): the
    # run exits 0, writes the machine file and reaches the runner, and this reddens.
    stub = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: stub)
    home = tmp_path / "home"
    machine = tmp_path / "config.toml"
    argv = ["setup", "--uninstall", "--home", str(home), "--machine", str(machine)]
    assert invoke(argv) == 2
    assert "--git-hooks" in capsys.readouterr().err
    assert not machine.exists()
    assert not stub.calls


def test_machine_setup_refuses_root_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--root` says which repository `--git-hooks` installs into, and machine setup reads no
    # repository: it took the flag, read nothing of it and configured the machine, exit 0, for a
    # person who named a repository. Refused before anything is written, as `--uninstall` is.
    #
    # Mutation: `mutations/`'s "setup drops --root and runs the machine setup".
    from drybag.setup.commands import _ROOT_ALONE

    stub = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: stub)
    machine = tmp_path / "config.toml"
    argv = ["setup", "--root", str(tmp_path), "--home", str(tmp_path / "home")]
    assert invoke([*argv, "--machine", str(machine)]) == 2
    assert capsys.readouterr().err == f"drybag: refused: {_ROOT_ALONE}\n"
    assert not machine.exists()
    assert not stub.calls


def test_the_machine_default_is_the_file_every_reader_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `--machine`'s default once took the `isatty` sniff that no *reader* took. With
    # `XDG_CONFIG_HOME` set, an owner running `drybag setup` in their own shell wrote
    # `/xdg/drybag/config.toml`, got exit 0, and every reader then said "no overlay root is
    # recorded in the machine configuration; run `drybag setup`" — the defect
    # `config.loader.load`'s docstring describes, on the write side.
    #
    # Mutation (`mutations/`'s "the machine path honours XDG_CONFIG_HOME again"): the file lands
    # under `XDG_CONFIG_HOME` and this reddens on both paths below.
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    # An interactive shell is what makes the sniff answer yes; the reader's answer must not
    # depend on it.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    stub = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: stub)
    argv = ["setup", "--preset", "recommended", "--home", str(home), "--plugin", "superpowers"]
    assert invoke(argv) == 0
    assert (home / ".config" / "drybag" / "config.toml").is_file()
    assert not (xdg / "drybag" / "config.toml").exists()
    assert stub.calls, "the stubbed runner was never called; the patch may have stopped applying"


def test_an_empty_home_is_no_default_for_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--home` defaults to `HOME` wherever this runs, and an empty `HOME` names no home, where
    # `Path.home` answers `/`: this command wrote the machine file and then refused to write
    # `/.claude/settings.json`. It now says so before anything is written. `setup.run.setup` is
    # replaced by a recorder, so a mutated run writes nothing under `/` either. Mutation (oracle):
    # `mutations/`'s "setup takes the root directory for an empty HOME".
    seen: list[Path] = []

    def recorded(*_: object, home: Path, **__: object) -> SetupReport:
        seen.append(home)
        return SetupReport(False, (), False, False, None, ())

    monkeypatch.setattr("drybag.setup.run.setup", recorded)
    monkeypatch.setenv("HOME", "")
    machine = tmp_path / "config.toml"
    assert invoke(["setup", "--preset", "recommended", "--machine", str(machine)]) == 1
    assert capsys.readouterr().err == (
        "drybag: failed: HOME names no home directory, so there is no default for --home or "
        "--machine; set HOME to your home directory, or pass --home PATH and --machine PATH\n"
    )
    assert seen == []
    assert not machine.exists()


def test_a_relative_home_is_no_default_for_home_from_any_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Taken as typed, `HOME=h` gave every working directory a machine file and a user settings
    # file of its own, under `<cwd>/h`. A relative `HOME` names no home, as an empty one does, so
    # `setup` refuses from either directory before anything is written. Mutation (oracle):
    # `mutations/`'s "a relative HOME is read against the working directory".
    stub = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: stub)
    monkeypatch.setenv("HOME", "h")
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        monkeypatch.chdir(tmp_path / name)
        assert invoke(["setup", "--preset", "recommended"]) == 1
        assert capsys.readouterr().err == (
            "drybag: failed: HOME names no home directory, so there is no default for --home "
            "or --machine; set HOME to your home directory, or pass --home PATH and --machine "
            "PATH\n"
        )
    assert [p.relative_to(tmp_path).as_posix() for p in sorted(tmp_path.rglob("*"))] == ["a", "b"]
    assert not stub.calls


def test_setup_help_names_no_path_from_the_machine_the_parser_was_built_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The second half of the same finding: both defaults used to be computed when the parser is
    # built, so `drybag setup --help` printed the developer's own home directory — and it was
    # computed on every run of every command, since the parser is built for all of them.
    with pytest.raises(SystemExit):
        invoke(["setup", "--help"])
    printed = capsys.readouterr().out
    assert "--machine" in printed
    assert str(Path.home()) not in printed
    assert "~/.config/drybag/config.toml" in printed


# An identity record `tomllib` meets with neither a `TOMLDecodeError` nor an answer: nested past
# what it follows, and holding an integer longer than it converts (4,300 digits by default).
PAST_THE_PARSER = {
    "nested": "layout = " + "[" * 20_000 + "]" * 20_000,
    "long-number": "layout = " + LONG_NUMBER,
}


@pytest.mark.parametrize("case", sorted(PAST_THE_PARSER))
def test_an_overlay_record_past_the_parser_is_refused_as_unreadable_through_the_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    # `tomllib` meets neither document with a `TOMLDecodeError`: nesting past what it follows
    # raises `RecursionError`, and the long integer a plain `ValueError`. A reader catching only
    # the first would end `drybag setup --overlay` in an internal error instead of refusing a
    # tree whose record it cannot read. Nothing is recorded, and the runner is never reached: the
    # probe runs above every write.
    #
    # Mutation (oracle): `mutations/`'s "the identity record reader lets a document past the
    # parser raise" -> the internal error comes back and both cases redden.
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / IDENTITY_RECORD).write_text(PAST_THE_PARSER[case], encoding="utf-8")
    stub = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: stub)
    machine = tmp_path / "config.toml"
    argv = ["setup", "--overlay", str(overlay), "--home", str(tmp_path / "home")]
    code = invoke([*argv, "--machine", str(machine)])
    err = capsys.readouterr().err
    assert "internal error" not in err
    refused = NOT_A_RECORD.format(root=quoted(str(overlay)))
    assert f"drybag: refused: {refused}" in err
    assert code == 2
    assert not machine.exists()
    assert stub.calls == []


def test_setup_with_no_home_names_machine_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The default machine file is under `HOME`, and an empty one names none, so the command says
    # to name one, and runs nothing.
    monkeypatch.setenv("HOME", "")
    stub = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: stub)
    home = tmp_path / "home"
    home.mkdir()
    assert invoke(["setup", "--preset", "recommended", "--home", str(home)]) == 1
    assert "--machine PATH" in capsys.readouterr().err
    assert not stub.calls
    assert list(tmp_path.rglob("config.toml")) == []


def test_setup_where_the_home_cannot_be_written_fails_naming_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    locked, home = tmp_path / "locked-home", tmp_path / "home"
    locked.mkdir()
    home.mkdir()
    locked.chmod(0o555)
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: Recorder())
    try:
        monkeypatch.setenv("HOME", str(locked))
        assert invoke(["setup", "--preset", "recommended", "--home", str(home)]) == 1
    finally:
        locked.chmod(0o755)
    err = capsys.readouterr().err
    assert f"{locked / '.config' / 'drybag'} cannot be written" in err
    assert "without --machine it is under HOME" in err
    assert "internal error" not in err


def test_setup_whose_named_machine_file_cannot_be_written_says_nothing_of_running_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The failure said where the file goes "without --machine" to a run that had named one, as
    # if the flag had not been given. Named, the file is where the flag says, and the line names
    # its directory and the reason alone. Mutation: `mutations/`'s "setup tells a run that named
    # its machine file where the file goes without --machine".
    locked, home = tmp_path / "locked", tmp_path / "home"
    locked.mkdir()
    home.mkdir()
    locked.chmod(0o555)
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: Recorder())
    named = locked / "drybag" / "config.toml"
    try:
        argv = ["setup", "--preset", "recommended", "--home", str(home)]
        assert invoke([*argv, "--machine", str(named)]) == 1
    finally:
        locked.chmod(0o755)
    err = capsys.readouterr().err
    assert f"{named.parent} cannot be written" in err
    assert "--machine" not in err


@pytest.mark.parametrize("refused", ["machine-file", "settings-file", "settings-directory"])
def test_setup_from_a_sandboxed_shell_says_a_person_must_run_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    refused: str,
) -> None:
    # An agent's sandbox refuses every write outside the working directory, answering the write
    # `EPERM` and `os.access` no (`trust.boundary`'s docstring and `setup.run._not_writable` say
    # how each was measured). Whichever of setup's writes meets it -- the machine file, the user
    # settings file, or the question asked of the settings directory before the first write --
    # setup ends in exit 2 and its constant sentence, never a traceback. Mutations (`mutations/`'s
    # "setup says nothing of the sandbox that refused its machine file" -> `machine-file` fails
    # naming the directory, exit 1; "setup says nothing of the sandbox that refused its settings
    # file" -> `settings-file` refuses naming the file; "setup reads a directory the sandbox
    # refuses as one its mode refuses" -> `settings-directory` says the directory is not
    # writable).
    home, machine = tmp_path / "home", tmp_path / "machine" / "config.toml"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: Recorder())
    met: list[Path] = []
    if refused == "machine-file":
        met = refuse_writes_under(monkeypatch, machine.parent)
    elif refused == "settings-file":
        met = refuse_writes_under(monkeypatch, home / ".claude")
    else:
        real = fsops.creatable
        monkeypatch.setattr(
            fsops, "creatable", lambda path: path.parent != home / ".claude" and real(path)
        )
    argv = ["setup", "--preset", "recommended", "--home", str(home)]
    assert invoke([*argv, "--machine", str(machine)]) == 2
    assert capsys.readouterr().err == f"drybag: refused: {SETUP_SANDBOXED}\n"
    assert (
        met
        == {
            "machine-file": [machine],
            "settings-file": [home / ".claude" / "settings.json"],
            "settings-directory": [],
        }[refused]
    )
    assert not (home / ".claude" / "settings.json").exists()


def test_setup_s_sandbox_sentence_says_what_a_person_in_their_own_terminal_meets() -> None:
    # As the trust record's: the sandbox's answer is also a read-only mount's or an immutable
    # flag's, met by a person already in their own terminal. Mutation (`mutations/`'s "the sandbox
    # sentence sends a person in their own terminal there again"): it ends at the sandbox.
    from drybag.trust.boundary import OWN_TERMINAL_TOO

    assert SETUP_SANDBOXED.endswith(OWN_TERMINAL_TOO)
