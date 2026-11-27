"""The machine owner's session budgets reach every command that measures what a session loads, as
they reach the session (`config.loader.load` folds the owner's layer that `config.session` folds).

A command and a session that read one machine file on two sets of budgets gave two answers to one
question: with `[budgets] volatile_notes_words` raised in the machine file, a command passed a
bundle the session rendered into a part no hook slot holds, while `doctor`'s `bundles` row, which
reads the session's configuration, was red; and `memory_index_words` from the machine file reached
nothing a command enforced.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from drybag.config.classes import REFUSED_LAYER_NOTE
from drybag.config.loader import load
from drybag.config.owner import MACHINE_RESET_NOTE
from drybag.config.reading import NOT_A_SWITCH, MachineConfigError
from drybag.config.session import session_config
from drybag.doctor.api import OK, RED
from tests.doctor.test_checks import _by_name, _checks
from tests.memory.test_commands import CONFIG, NOTE, invoke

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _project(tmp_path: Path, machine: str, *, volatile: int = 0) -> tuple[Path, Path]:
    """A local-only project with `volatile` long volatile notes, and its machine file."""
    root = tmp_path / "project"
    base = root / ".drybag" / "local" / "memory"
    for group in ("developer", "project-volatile"):
        (base / group).mkdir(parents=True)
    (base / "developer" / "a.md").write_text(
        NOTE.format(name="a", meta="metadata:\n  type: project\n  startup: 1\n", body="Body."),
        encoding="utf-8",
    )
    for n in range(volatile):
        body = " ".join(f"word{n}x{m}" for m in range(600))
        meta = "metadata:\n  type: project\n  as_of: 2026-10-01\n"
        (base / "project-volatile" / f"v{n:02}.md").write_text(
            NOTE.format(name=f"v{n:02}", meta=meta, body=body), encoding="utf-8"
        )
    (root / "drybag.toml").write_text(CONFIG, encoding="utf-8")
    path = tmp_path / "machine.toml"
    path.write_text(machine, encoding="utf-8")
    return root, path


def test_a_command_loads_the_session_budgets_the_session_runs_on(tmp_path: Path) -> None:
    # The one reader: `load` and `session_config` fold one owner's layer, so the effective value
    # of every session budget the machine file sets is the same through both. Mutation
    # (`mutations/`'s "a command's load reads no machine file for the owner's layer"): `load`
    # folds the preset's layer alone, and reads the preset's 1200 and 400.
    root, machine = _project(
        tmp_path, "[budgets]\nmemory_index_words = 9000\nvolatile_notes_words = 999999\n"
    )
    command = load(root, machine=machine).budgets
    session = session_config(root, machine=machine).config
    assert session is not None
    for name, value in (("memory_index_words", 9000), ("volatile_notes_words", 999999)):
        assert command.effective(name) == session.budgets.effective(name) == value


@pytest.mark.parametrize(
    ("machine", "code"),
    [("", 0), ("[budgets]\nmemory_index_words = 1\n", 1)],
    ids=["preset-budget", "owner-budget"],
)
def test_memory_index_judges_by_the_owners_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], machine: str, code: int
) -> None:
    # `memory_index_words` from the machine file is what `memory index` enforces, as the session
    # and `doctor` read it. Mutation (`mutations/`'s "a command's load reads no machine file for
    # the owner's layer"): the preset's 1200 words pass the one-word budget's index.
    root, path = _project(tmp_path, machine)
    common = ["--root", str(root), "--machine", str(path)]
    invoke(["memory", "index", *common])
    capsys.readouterr()
    assert invoke(["--json", "memory", "index", "--check", *common]) == code
    summary = json.loads(capsys.readouterr().out)["summary"]
    assert ("over its 1-word budget" in summary) is bool(code)


@pytest.mark.parametrize(
    ("machine", "status"),
    [("", OK), ("[budgets]\nvolatile_notes_words = 999999\n", RED)],
    ids=["preset-budget", "owner-raised-budget"],
)
def test_doctor_judges_the_bundles_by_the_owners_budget(
    tmp_path: Path, machine: str, status: str
) -> None:
    # Twelve long volatile notes fit their slots under the preset's budget, and need a fourth part,
    # which no hook slot holds, once the machine file raises it, so `doctor`'s `bundles` row reads
    # the machine file as the session does.
    root, path = _project(tmp_path, machine, volatile=12)
    row = _by_name(_checks(tmp_path, root, machine=path), "bundles")
    assert row.status == status, row.detail


@pytest.mark.parametrize(
    ("table", "note"),
    [
        (
            "[guards]\nbg_cleanup = 3\n",
            MACHINE_RESET_NOTE.format(
                path="{machine}", problem=NOT_A_SWITCH.format(key="guards.bg_cleanup")
            ),
        ),
        (
            "[budgets]\nagents_md_lines = 9\n",
            REFUSED_LAYER_NOTE.format(key="budgets.agents_md_lines", layer="machine file"),
        ),
    ],
    ids=["guard-not-a-switch", "gate-budget"],
)
def test_a_command_reads_past_a_machine_file_key_it_cannot_use_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], table: str, note: str
) -> None:
    # What the owner sets is honoured and what this drybag cannot use is said, never a block: a
    # key a later release's `setup` writes once stopped every older command on the machine. A
    # command goes on as a session does, on the preset's value, and says the key on stderr; the
    # load itself says nothing, since a command that loads twice would say it twice. Mutations
    # (`mutations/`'s "the owner's layer refuses a key it cannot use in a file that loads" -> the
    # load raises; "a command keeps quiet about what it read past in the machine file" -> stderr is
    # empty).
    root, machine = _project(tmp_path, table)
    config = load(root, machine=machine)
    assert config.budgets.effective("agents_md_lines") != 9
    assert capsys.readouterr().err == ""
    invoke(["--json", "memory", "inventory", "--root", str(root), "--machine", str(machine)])
    assert capsys.readouterr().err == f"drybag: {note.format(machine=machine)}\n"


def test_a_command_refuses_a_machine_file_that_does_not_load(tmp_path: Path) -> None:
    # Only a file that does not load is refused, as `[overlay] root`'s reader refuses it: nothing
    # of it can be read past key by key. Mutation (`mutations/`'s "a command's load reads the
    # owner's layer as a session does"): the load notes the file and goes on.
    root, machine = _project(tmp_path, "[[[\n")
    with pytest.raises(MachineConfigError, match=r"is not valid TOML"):
        load(root, machine=machine)
