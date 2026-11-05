"""`setup --approval-boundary`: the advice that keeps an agent's shell out of the trust record.

The record holds against repository bytes, and against an agent only while the harness's sandbox
keeps that agent's shell out of its directory, which is the person's to set and stayfixed's never
to check (`trust.boundary` says why). So the command prints the deny rule measured on Claude Code
2.1.296 (macOS) on 2026-10-16 -- `Edit(//<absolute path>/**)` in `permissions.deny` stopped both the
sandboxed shell and the file tools, where one leading slash and a `Write(...)` rule stopped neither
-- and the sandbox settings, and writes nothing. Every path the tests write is under `tmp_path`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.setup.commands import BOUNDARY_ADVICE
from stayfixed.setup.machine import USER_SETTINGS
from stayfixed.trust.api import ENFORCING_SETTINGS, SANDBOX_ON, managed_named
from stayfixed.trust.boundary import NO_MANAGED_PATH, deny_rule


def invoke(argv: list[str]) -> int:
    return run(argv, parser=build_parser(discover_registrars()))


def _advice(tmp_path: Path, machine: Path, *extra: str) -> list[str]:
    home = tmp_path / "home"
    return [
        "setup",
        "--approval-boundary",
        "--home",
        str(home),
        "--machine",
        str(machine),
        *extra,
    ]


def test_the_advice_names_the_rule_and_the_sandbox_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The flag is advice only: the deny rule over the directory the trust record lies in, the
    # user settings file it belongs in, the setting that turns the sandbox on and the managed ones
    # that keep a repository from turning it off -- and no machine file, no settings file, not
    # even the home's `.claude`, since a rule stayfixed wrote would read as a boundary stayfixed
    # keeps. Mutation (`mutations/`'s "setup --approval-boundary runs the machine setup"): the
    # machine file and the settings are written, and the advice is never printed.
    machine = tmp_path / "machine" / "config.toml"
    assert invoke(_advice(tmp_path, machine)) == 0
    out = capsys.readouterr().out
    rule = deny_rule(machine.parent)
    settings = tmp_path / "home" / USER_SETTINGS
    assert out == (
        BOUNDARY_ADVICE.format(
            rules=rule,
            settings=settings,
            sandbox=SANDBOX_ON,
            enforcing=ENFORCING_SETTINGS,
            managed=managed_named(),
        )
        + "\n"
    )
    assert list(tmp_path.iterdir()) == []


def test_the_advice_s_json_carries_the_rule_and_the_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--json` carries the rule and the two files it names, for a skill that relays them.
    machine = tmp_path / "machine" / "config.toml"
    assert invoke(_advice(tmp_path, machine, "--json")) == 0
    data = json.loads(capsys.readouterr().out)
    assert {key: data[key] for key in ("deny_rules", "settings", "managed")} == {
        "deny_rules": [deny_rule(machine.parent)],
        "settings": str(tmp_path / "home" / USER_SETTINGS),
        "managed": managed_named(),
    }


def test_a_linked_machine_directory_gets_a_rule_for_each_spelling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The machine file's directory reached through a symbolic link: the harness compares a write
    # against the path it resolves, so a rule over the link's spelling alone denies nothing. Both
    # are named. Mutation (`mutations/`'s "the approval boundary covers only the directory as
    # named"): the resolved rule is missing.
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real)
    assert invoke(_advice(tmp_path, linked / "config.toml", "--json")) == 0
    rules = json.loads(capsys.readouterr().out)["deny_rules"]
    assert rules == [deny_rule(linked), deny_rule(real.resolve())]
    assert rules[0] != rules[1]


def test_a_looping_machine_directory_is_refused_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A symbolic-link loop where the machine file's directory should be: resolving it for the
    # second spelling raises, which ended in `internal error`. Mutation (`mutations/`'s
    # "setup --approval-boundary lets a looping machine directory raise"): the `OSError` reaches
    # `cli.run`.
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    assert invoke(_advice(tmp_path, loop / "config.toml")) == 2
    err = capsys.readouterr().err
    assert "cannot be checked" in err
    assert "internal error" not in err


@pytest.mark.parametrize(
    "flag",
    [
        pytest.param(["--preset", "recommended"], id="preset"),
        pytest.param(["--overlay", "elsewhere"], id="overlay"),
        pytest.param(["--plugin", "superpowers"], id="plugin"),
        pytest.param(["--git-hooks"], id="git-hooks"),
        pytest.param(["--uninstall"], id="uninstall"),
    ],
)
def test_the_advice_beside_a_flag_that_writes_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: list[str]
) -> None:
    # A flag that names something to write has no run to belong to beside advice that writes
    # nothing: refused, rather than dropped behind the person's back or run beside it.
    # `--uninstall` was dropped, exit 0, for a person who asked for a hook to be removed. Mutations
    # (`mutations/`'s "setup --git-hooks and --approval-boundary drop --preset" -> `preset`
    # prints the advice; "setup --git-hooks and --approval-boundary drop --overlay" -> `overlay`
    # does; "setup --git-hooks and --approval-boundary drop --plugin" -> `plugin` does;
    # "setup --approval-boundary takes --git-hooks" -> `git-hooks` does; "setup
    # --approval-boundary takes --uninstall" -> `uninstall` does).
    machine = tmp_path / "machine" / "config.toml"
    assert invoke(_advice(tmp_path, machine, *flag)) == 2
    assert "--approval-boundary prints what to set and writes nothing" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_the_deny_rule_is_the_measured_spelling() -> None:
    # Two leading slashes: one anchors the path at the working directory, which was measured to
    # stop nothing outside it. Mutation (`mutations/`'s "the approval boundary is spelled with one
    # leading slash"): `Edit(/Users/...)`.
    assert deny_rule(Path("/Users/me/.config/stayfixed")) == "Edit(//Users/me/.config/stayfixed/**)"


@pytest.mark.parametrize(
    ("machine", "directory"),
    [
        pytest.param("config.toml", ".", id="bare-name"),
        pytest.param("sub/config.toml", "sub", id="subdirectory"),
    ],
)
def test_a_relative_machine_and_home_are_advised_as_absolute_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    machine: str,
    directory: str,
) -> None:
    # `--machine sub/config.toml` printed `Edit(/sub/**)` and `--machine config.toml`
    # `Edit(/./**)`: one leading slash anchors a rule at the working directory, so pasted into user
    # settings each denied edits to a subtree of, or the whole of, every project, and not the
    # record's directory. The rule is over the directory made absolute, and the settings file a
    # relative `--home` names is printed absolute beside it. `tmp_path` is resolved, so the
    # resolved spelling is the same rule and one is named. Mutations (`mutations/`'s "the approval
    # boundary is anchored at the working directory for a relative --machine" -> the rule;
    # "setup --approval-boundary names a relative settings file as given" -> the file).
    monkeypatch.chdir(tmp_path)
    argv = ["setup", "--approval-boundary", "--home", "home", "--machine", machine, "--json"]
    assert invoke(argv) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["deny_rules"] == [deny_rule(tmp_path / directory)]
    assert all(rule.startswith("Edit(//") for rule in data["deny_rules"])
    assert data["settings"] == str(tmp_path / "home" / USER_SETTINGS)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("platform", "named"),
    [
        pytest.param(
            "darwin", "/Library/Application Support/ClaudeCode/managed-settings.json", id="darwin"
        ),
        pytest.param("linux", "/etc/claude-code/managed-settings.json", id="linux"),
        pytest.param("win32", "the managed settings file", id="unmeasured"),
    ],
)
def test_the_managed_settings_file_is_the_documented_path_on_each_platform(
    platform: str, named: str
) -> None:
    # Literal, and not built from `MANAGED_SETTINGS`: every other test here builds its expected
    # output from the constants, so a wrong path passed them all and the CLI advised a file no
    # administrator's Claude Code reads. The paths are the ones `trust.boundary` cites, read again
    # in Claude Code's managed-settings page on 2026-10-17 (Linux's is WSL's too); a platform
    # where none was measured gets `NO_MANAGED_PATH`, and never the text `None`. The platform is
    # passed, so each host reaches every branch. Mutations (`mutations/`'s "the advice names
    # another macOS managed settings file" -> `darwin`; "the advice names another Linux managed
    # settings file" -> `linux`; "the advice names managed settings on the host's platform only"
    # -> `darwin` or `linux`, whichever the host is not; "the advice names no managed settings
    # file where none was measured" and "the advice names a missing managed settings file as None"
    # -> `unmeasured`).
    assert managed_named(platform) == named
    if platform == "win32":
        assert named == NO_MANAGED_PATH


def test_the_sandbox_settings_are_the_documented_keys_and_values() -> None:
    # Literal for the reason the managed path's test gives: `allowUnsandboxedCommands = true`
    # passed every test built from `ENFORCING_SETTINGS` and advised a sandbox an agent may leave.
    # The keys are the sandboxing reference's recipe for enforcing the sandbox, read again on
    # 2026-10-17. Mutations (`mutations/`'s "the advice turns the sandbox off" -> both; "the
    # advice lets Claude Code start without the sandbox" and "the advice lets a command run
    # outside the sandbox" -> the enforcing line).
    assert SANDBOX_ON == "sandbox.enabled = true"
    assert ENFORCING_SETTINGS == (
        "sandbox.enabled = true, sandbox.failIfUnavailable = true and "
        "sandbox.allowUnsandboxedCommands = false"
    )
