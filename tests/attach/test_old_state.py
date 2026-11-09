"""The state an earlier name of this project left on a machine is not this project's to read."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from drybag.cli import build_parser, discover_registrars, run
from tests.doctor.test_checks import ORIGIN, _overlay
from tests.gitfixture import git as _git

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

# Split so that `tests/test_name.py` does not find the former name in this file.
FORMER = "stay" + "fixed"
BINDING_ID = "0123456789abcdef0123456789abcdef"


def _reports(root: Path, capsys: pytest.CaptureFixture[str]) -> list[tuple[int, str, str]]:
    reports = []
    for argv in (
        ["doctor", "--json", "--root", str(root)],
        ["attach", "--check", "--json", "--root", str(root)],
    ):
        code = run(argv, parser=build_parser(discover_registrars()))
        captured = capsys.readouterr()
        reports.append((code, captured.out, captured.err))
    return reports


def _leave_the_former_state(home: Path, root: Path, overlay: Path) -> None:
    config = home / ".config" / FORMER
    config.mkdir(parents=True)
    (config / "config.toml").write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    bindings = home / ".local" / "share" / FORMER / "bindings"
    bindings.mkdir(parents=True)
    (bindings / f"{BINDING_ID}.toml").write_text(
        f'project = "p"\ncheckout = "{root}"\norigin = "{ORIGIN}"\n', encoding="utf-8"
    )
    state = root / ".git" / FORMER
    state.mkdir()
    (state / "binding").write_text(BINDING_ID, encoding="utf-8")
    (root / f"{FORMER}.toml").write_text(
        '[memory]\nmode = "overlay"\n\n[project]\nname = "p"\n', encoding="utf-8"
    )


def test_old_state_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    overlay = _overlay(tmp_path)
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", ORIGIN)
    monkeypatch.chdir(root)
    on_an_empty_home = _reports(root, capsys)

    _leave_the_former_state(Path.home(), root, overlay)
    reports = _reports(root, capsys)

    assert reports == on_an_empty_home
    printed = "\n".join(out + err for _, out, err in reports)
    assert [line for line in printed.splitlines() if FORMER in line.lower()] == []
