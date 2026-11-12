"""What the `attached` row in `drybag doctor` answers, now that `attach` contributes it.

Every case runs the whole report through `run_checks`, so the row is asked the way a user's
`drybag doctor` asks it: discovered in this area's `doctor.py`, with the note store resolved by
the lazy value its `register()` creates and the overlay root by the report's `Context`. The
fixtures are the doctor area's own (`tests/doctor/test_checks.py`), shared rather than respelled.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from drybag import binding
from drybag.attach import doctor as attach_doctor
from drybag.attach import hooks as attach_hooks
from drybag.attach.api import LOCAL_SETTINGS
from drybag.attach.check import check as attach_check
from drybag.attach.mcp import BAD_LEDGER, UNUSABLE, McpLedger, digest, write_mcp_ledger
from drybag.attach.render import MARKETPLACE_FILE, read_parts
from drybag.attach.render import write as render_write
from drybag.attach.write import attach
from drybag.binding import (
    LEDGER_NAME,
    MCP_LEDGER_FILE,
    MCP_LEDGER_NAME,
    common_directory,
    delivery_directory,
)
from drybag.config.loader import CONFIG_FILE, load
from drybag.config.plates import plates
from drybag.doctor import checks as doctor_checks
from drybag.doctor.api import OK, RED, SKIP, WARN, Check
from drybag.errors import Refusal
from drybag.hooks.api import HookEvent
from drybag.memory.api import PROJECTS, RECORD
from drybag.overlay.api import COMMON_CLAUDE, COMMON_CODEX
from drybag.printed import quoted
from tests.attach.test_write import (
    NOT_LEDGERS,
    _attachable,
    _committed,
    ledger_file,
    rewritten,
)
from tests.doctor.test_checks import (
    LOCAL_ONLY,
    OVERLAY,
    _attached,
    _by_name,
    _checks,
    _env,
    _initialised,
    _machine,
    _no_overlay_machine,
    _overlay,
)
from tests.gitfixture import git as _git
from tests.parserlimits import LONG_NUMBER
from tests.runners import Recorder
from tests.sessions import NO_CONFIG
from tests.tagged import with_tags

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _past_a_name(tmp_path: Path, path: Path) -> None:
    """Make `path` a symbolic link to a name longer than a file name may be on Linux and macOS.

    Asked about through it, `stat` raises `ENAMETOOLONG` on every supported Python;
    `Path.is_file()` raises it on 3.11 to 3.13 and answers `False` from 3.14.
    """
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.is_symlink() or path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(tmp_path / ("x" * 300))


# The row as `drybag doctor --json` prints it for a project that was never attached, pasted here
# and never derived from the code under test. The overlay case is the bytes captured before the row
# moved into this area; the `local-only` one changed when delivery stopped depending on the memory
# mode, since `attach` delivers to such a repository too, and "there is no overlay to bind to" was
# no longer true of it.
UNATTACHED = {
    "overlay": Check(
        "attached",
        "warn",
        f"memory.mode is overlay and {LEDGER_NAME} does not exist, so nothing records an attach",
        "run `drybag attach --check`",
    ),
    "local-only": Check(
        "attached", "ok", f"{LEDGER_NAME} does not exist, so nothing records an attach", ""
    ),
}


@pytest.mark.parametrize("mode", sorted(UNATTACHED))
def test_an_unattached_project_reports_attached_as_it_did(tmp_path: Path, mode: str) -> None:
    # A checkout with a `drybag.toml` and a git repository and nothing `attach` wrote: the
    # state `detach` leaves, and the state of a fresh clone. The whole row is compared, status,
    # sentence and remedy, because a move that reworded any of them is a change a reader of the
    # report sees. The `local-only` case is the row's one green answer without an overlay, the arm
    # that keeps the red and warning arms out of an ordinary unattached project's reach. Mutation
    # (oracle): `mutations/`'s "the unattached row's sentence is reworded" -> the `overlay` case
    # reddens.
    template = OVERLAY if mode == "overlay" else LOCAL_ONLY
    root = _initialised(tmp_path, template=template)
    _git(root, "init", "-q", "-b", "main")
    rows = _checks(tmp_path, root)
    assert [row for row in rows if row.name == "attached"] == [UNATTACHED[mode]]


def test_an_overlay_recording_another_remote_leaves_a_bound_checkout_attached(
    tmp_path: Path,
) -> None:
    # The overlay's project record of another remote was a red row: the binding was the record.
    # The binding is this machine's record of the checkout's id now, so a record naming another
    # remote -- written from another machine, or before `origin` moved -- changes nothing here.
    root = _attached(tmp_path)
    (tmp_path / "overlay" / PROJECTS / "p" / RECORD).write_text(
        'remote = "git@github.com:somebody/else.git"\nfirst_attach = "2026-09-18"\n',
        encoding="utf-8",
    )
    check = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert "the binding is bound" in check.detail
    # The other repository's remote is overlay-authored, not repository-authored — but it is
    # still somebody's private URL, and this row has no reason to print one.
    assert "somebody/else" not in check.detail and "somebody/else" not in check.remedy


def test_an_overlay_project_with_no_ledger_is_a_warning_naming_the_file(tmp_path: Path) -> None:
    # `memory.mode = "overlay"` and nothing recording an attach. Not red: a project may be
    # configured for an overlay before anyone has run `drybag attach` in this checkout, which
    # is the ordinary state of a fresh clone. The remedy is the command that ends it.
    root = _attached(tmp_path)
    ledger_file(root).unlink()
    check = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert check.status == "warn"
    assert LEDGER_NAME in check.detail
    assert "drybag attach" in check.remedy


def test_an_empty_home_is_told_it_is_home_that_names_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The render and the composed store are under the home's data directory, and an empty `HOME`
    # names no home. The row says so, as a warning and never "this check could not run". Asked of
    # the row directly, which is how a person runs `doctor`. Mutation (oracle): `mutations/`'s
    # "the attached row dies on a home it cannot name".
    from drybag.attach.doctor import _attached as attached_row
    from drybag.attach.doctor import _Ledger
    from tests.doctor.test_checks import _context

    root = _attached(tmp_path)
    monkeypatch.setenv("HOME", "")
    config = load(root, machine=_machine(tmp_path))
    context = _context(root, config)
    row = attached_row(context, config, _Ledger())
    assert (row.status, row.detail, row.remedy) == (
        WARN,
        "HOME names no home directory, so there is no data directory to check the delivery in",
        "set HOME to your home directory",
    )


def _row(tmp_path: Path, checkout: Path) -> Check:
    return _by_name(_checks(tmp_path, checkout, machine=_machine(tmp_path)), "attached")


POINTED = (
    "attached; the delivery is in place; autoMemoryDirectory points the harness at the composed "
    "store; the binding is bound"
)


def test_the_pointer_at_the_composed_store_is_green_and_red_once_the_store_is_gone(
    tmp_path: Path,
) -> None:
    # The harness reads the directory `autoMemoryDirectory` names, so the pointer `attach` writes
    # is the row's answer: ok while the composed store is there, red once it is gone, since the
    # harness then reads no memory and nothing else says so. Mutation (oracle): `mutations/`'s
    # "doctor reads the pointer at the composed store as a key set elsewhere" -> the first reads
    # red.
    from drybag.memory.api import composed_directory

    root = _attached(tmp_path)
    assert (_row(tmp_path, root).status, _row(tmp_path, root).detail) == (OK, POINTED)
    shutil.rmtree(composed_directory(_id(root)))
    row = _row(tmp_path, root)
    assert (row.status, row.detail) == (
        RED,
        f"attached; the delivery is in place; {attach_doctor.STORE_GONE}; the binding is bound",
    )


def test_a_composed_store_whose_link_dangles_warns(tmp_path: Path) -> None:
    # The overlay moved and the machine file records the new root, and no attach followed: every
    # link of the composed store still names the old place, so the harness reads none of those
    # notes while the row said the pointer was in place.
    from drybag.memory.api import composed_directory

    root = _attached(tmp_path)
    link = composed_directory(_id(root)) / "developer"
    link.unlink()
    link.symlink_to(tmp_path / "moved-away" / "common" / "memory", target_is_directory=True)
    row = _row(tmp_path, root)
    assert (row.status, row.detail) == (
        WARN,
        f"attached; the delivery is in place; {attach_doctor.STORE_DANGLES}; the binding is bound",
    )
    assert "drybag attach" in row.remedy


def _pointer_set(root: Path, value: object) -> None:
    """The main checkout's settings file with `autoMemoryDirectory` set to `value`, or without the
    key where `value` is `None`."""
    path = root / LOCAL_SETTINGS
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("autoMemoryDirectory", None)
    if value is not None:
        document["autoMemoryDirectory"] = value
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def test_a_missing_pointer_warns_and_a_pointer_elsewhere_is_red(tmp_path: Path) -> None:
    # Claude Code rewrites the file whole and keeps the key, so a missing key is an attach that did
    # not finish, and a warning; a key naming any other directory has the harness read notes this
    # repository is not bound to, and is red. The value is never printed.
    root = _attached(tmp_path)
    _pointer_set(root, None)
    row = _row(tmp_path, root)
    missing = attach_doctor.POINTER_MISSING.format(settings=LOCAL_SETTINGS)
    assert (row.status, row.detail) == (
        WARN,
        f"attached; the delivery is in place; {missing}; the binding is bound",
    )
    elsewhere = tmp_path / "somebody-elses-notes"
    _pointer_set(root, str(elsewhere))
    row = _row(tmp_path, root)
    assert row.status == RED
    assert attach_doctor.POINTER_ELSEWHERE.format(settings=LOCAL_SETTINGS) in row.detail
    assert str(elsewhere) not in row.detail and str(elsewhere) not in row.remedy


def test_a_settings_file_that_cannot_be_read_as_settings_warns(tmp_path: Path) -> None:
    # What the harness makes of a file that is not one JSON object is the harness's, so the row
    # warns that where the harness reads memory is not known, and never reads it as no key.
    root = _attached(tmp_path)
    (root / LOCAL_SETTINGS).write_text("{not json\n", encoding="utf-8")
    row = _row(tmp_path, root)
    assert row.status == WARN
    assert attach_doctor.POINTER_UNREAD.format(settings=LOCAL_SETTINGS) in row.detail


def test_a_ledger_with_no_binding_in_the_overlay_is_a_warning_and_never_an_attach(
    tmp_path: Path,
) -> None:
    # The binding this machine keeps is the other half of an attach, so the row asks it: a ledger
    # with no binding id behind it in the git common directory is a warning that names the file.
    #
    # Mutation (declared): `if state == UNBOUND or id is None:` -> `if False:` -> the row falls
    # through to the harness-shape branch and this reddens on the sentence.
    root = _attached(tmp_path)
    kept = root / ".git" / "drybag" / "binding"
    assert kept.is_file(), "the fixture must have recorded a binding for this to be a probe"
    kept.unlink()
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert row.status == WARN
    assert "records no binding of this checkout to this project" in row.detail
    assert "drybag attach" in row.remedy


def test_a_ledger_naming_a_store_the_overlay_does_not_permit_is_a_warning(tmp_path: Path) -> None:
    # `_attached` asked the overlay only for its *state*, and `read_binding` answers with a
    # `Refusal` — not a state — when the store the ledger names is not this project's share of
    # the recorded overlay. That refusal used to collapse into the same `None` as "no overlay
    # recorded", the row skipped both new arms, and a ledger naming any store it liked was
    # reported `attached: ok`.
    #
    # `warn` and not `skip`: this is a fact about the ledger, and `skip` never reaches the exit
    # code.
    #
    # Mutation (declared): `except Refusal: return UNRESOLVED` -> `return UNASKABLE` -> the row
    # becomes a skip about this machine and this reddens on the status and the sentence.
    root = _attached(tmp_path)
    recorded = json.loads(ledger_file(root).read_text(encoding="utf-8"))
    recorded["store"] = str(tmp_path / "somewhere-else" / "memory")
    ledger_file(root).write_text(json.dumps(recorded), encoding="utf-8")
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert row.status == WARN
    assert "is not this project's directory inside the overlay" in row.detail
    assert "attached;" not in row.detail, "a ledger the overlay does not confirm is not an attach"
    assert "drybag attach" in row.remedy


def test_a_ledger_on_a_machine_that_records_no_overlay_skips_and_never_reads_as_attached(
    tmp_path: Path,
) -> None:
    # The universal case on a machine where `setup` has never run, and the other refusal beside the
    # one the test above covers: `read_binding` refuses for this too, and the row used to print
    # "attached" over it. It is a fact about *our own inputs*, so it is a `skip` that says what
    # could not be asked — never a warning that accuses the repository, and never the word
    # "attached".
    #
    # Mutation (declared): `if context.overlay_root is None: return NO_OVERLAY` ->
    # `if False:` -> the reason becomes `UNRESOLVED` (the refusal is indistinguishable once the
    # arm is gone) and this reddens on the status and the sentence.
    root = _attached(tmp_path)
    row = _by_name(_checks(tmp_path, root, machine=_no_overlay_machine(tmp_path)), "attached")
    assert row.status == SKIP
    assert "records no overlay to check it against" in row.detail
    assert "attached;" not in row.detail
    assert "drybag setup --overlay" in row.remedy


def test_a_ledger_on_a_machine_whose_file_does_not_load_skips_in_words_of_its_own(
    tmp_path: Path,
) -> None:
    # Whether a machine whose file nobody could read records an overlay is not known, which is
    # neither of the two arms beside it: read as no overlay, the row told the owner to run
    # `drybag setup --overlay`; read as an overlay that could not be asked, it blamed `git`. The
    # `preferences` row is red on the file and carries the remedy, so this skip carries none.
    # Mutations (`mutations/`'s "the attached row reads a machine file nobody could read as an
    # overlay that could not be asked" and "the report reads a machine file it could not read as
    # one that records no overlay"): the sentence and remedy of the other arms.
    root = _attached(tmp_path)
    machine = tmp_path / "unreadable.toml"
    machine.write_text("[personal\nx = 1\n", encoding="utf-8")
    row = _by_name(_checks(tmp_path, root, machine=machine), "attached")
    assert row.status == SKIP and row.remedy == "", row
    assert "the machine configuration file could not be read" in row.detail, row
    assert "the `preferences` row says why" in row.detail and "attached;" not in row.detail


def test_an_overlay_record_this_process_cannot_read_is_a_warning_beside_the_binding(
    tmp_path: Path,
) -> None:
    # The overlay's `projects/<name>/project.toml` binds nothing, so one that will not parse
    # leaves the binding readable: the row reports it, with the record's fault as a warning and
    # where the parser stopped, never the file's text.
    root = _attached(tmp_path)
    overlay = _overlay(tmp_path)
    (overlay / PROJECTS / "p" / RECORD).write_text("remote = [", encoding="utf-8")
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert row.status == WARN
    assert f"{RECORD} is not valid TOML" in row.detail and "attached;" in row.detail
    assert row.remedy == attach_doctor.RECORD_REPAIR


def test_an_attached_checkout_the_overlay_confirms_is_still_green_and_says_the_binding(
    tmp_path: Path,
) -> None:
    # The vacuity guard for the three above: refusing to print "attached" whenever the overlay
    # did not answer must not become refusing to print it at all. The fixture is the state a
    # real attach leaves, the overlay's record matches this checkout's remote, and the row says
    # so with the binding's own label on it.
    root = _attached(tmp_path)
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert row.status == OK
    assert row.detail.startswith("attached;")
    assert "the binding is bound" in row.detail


# The `attached` row beside a ledger that cannot be read, pasted rather than read back from the
# code under test.
UNREADABLE_LEDGER_ATTACHED = Check(
    "attached",
    "warn",
    f"{LEDGER_NAME} is here and cannot be read as a ledger, so nothing in it can be corroborated "
    f"and this checkout's attach state is unknown",
    f"take back by hand what {LEDGER_NAME} records, move it aside, then run "
    "`drybag attach --check`",
)


def test_one_report_reads_the_ledger_once_and_the_configuration_not_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `attached` reads the ledger more than once, and the row needs the binding behind it. The
    # ledger had three readers that asked three ways — one of them the
    # `is_file()` that a link to an over-long name defeats — and parsed the file twice, and the
    # binding was read through `read_binding` without the report's `Config`, so `drybag.toml`
    # and the machine file were loaded a second time. Measured by hand: `_Ledger.state` asking
    # `_ledger_state` every time -> three ledger reads; `read_binding` without `config=` -> one
    # load.
    from drybag.attach import binding, write

    reads: list[Path] = []
    loads: list[Path] = []
    real_ledger = write.read_ledger

    def counted_ledger(path: Path) -> object:
        reads.append(path)
        return real_ledger(path)

    def counted_load(root: Path, *, machine: Path | None) -> object:
        # `load` is the loader's own, which `binding` imports by name; only `read_binding` calls it
        # through that module.
        loads.append(root)
        return load(root, machine=machine)

    monkeypatch.setattr(write, "read_ledger", counted_ledger)
    monkeypatch.setattr(binding, "load", counted_load)
    root = _attached(tmp_path)
    rows = _checks(tmp_path, root, machine=_machine(tmp_path))
    # Non-vacuous: the row asked, and the binding was read behind the ledger.
    assert _by_name(rows, "attached").detail.startswith("attached;")
    assert (len(reads), len(loads)) == (1, 0)


def test_one_report_resolves_the_overlay_root_once_for_every_area(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The overlay root is a key of the machine file, the core's, and two areas read it: `attach`
    # for the binding, `overlay` for its two rows. What the report caches is
    # `Context.overlay_root`: resolved on its first read and kept, so every row that reads the root
    # through the `Context` shares one read of the machine file. That is all it caches. The binding
    # and the note store this area reads behind the row resolve the root again on their own, and
    # nothing caches the `git` answers they ask, so this counts only the reads through the
    # `Context`. Mutation (oracle): `mutations/`'s "the report resolves the overlay root for every
    # reader" -> five reads, three of `attach`'s and two of `overlay`'s.
    from drybag.config.overlay import MachineRecord, machine_record

    asked: list[Path | None] = []

    def counted(machine: Path | None) -> MachineRecord:
        asked.append(machine)
        return machine_record(machine)

    # The name the report's `Context` calls the machine file's reader by, in `doctor.model`.
    monkeypatch.setattr("drybag.doctor.model.recorded_machine_record", counted)
    root = _attached(tmp_path)
    rows = _checks(tmp_path, root, machine=_machine(tmp_path))
    # Non-vacuous: both areas read the root, and found the overlay there.
    assert _by_name(rows, "attached").detail.startswith("attached;")
    assert _by_name(rows, "pre-commit").status != SKIP
    assert asked == [_machine(tmp_path)]


# --- the ledger's path, the binding record and the overlay's shape -----------------------------


# Where a symbolic link to a name longer than a file name may be makes `stat` unable to answer
# about the ledger on any supported Python: the ledger itself, and the directory that holds it.
UNCHECKABLE_LEDGERS = ("the-ledger", "its-directory")


@pytest.mark.parametrize("shape", UNCHECKABLE_LEDGERS)
def test_a_ledger_doctor_cannot_ask_about_leaves_the_attached_row_its_own_answer(
    tmp_path: Path, shape: str
) -> None:
    # `attached` asked `is_file()` of the ledger, which raised `ENAMETOOLONG` on Python 3.11 to
    # 3.13 and reached `_guarded`: the row became that guard's warning. On 3.14 `is_file()`
    # answered `False`, and the row said the ledger does not exist. Mutations (oracle):
    # `mutations/`'s "attached asks is_file() of the ledger again" -> the guard's warning on 3.11
    # to 3.13 and the ledger does not exist on 3.14; "a ledger doctor cannot ask about reads as no
    # ledger" -> the ledger does not exist.
    root = _attached(tmp_path)
    path = ledger_file(root)
    _past_a_name(tmp_path, path.parent if shape == "its-directory" else path)
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert row == UNREADABLE_LEDGER_ATTACHED
    # A ledger that will not read is never blamed on `git`, which has nothing to do with it.
    assert "`git`" not in row.detail and "`git`" not in row.remedy


def test_a_dangling_link_at_the_ledgers_path_is_no_ledger(tmp_path: Path) -> None:
    # The vacuity guard for the case above: not every path that holds no ledger is one that cannot
    # be read.
    root = _attached(tmp_path)
    path = ledger_file(root)
    path.unlink()
    path.symlink_to(tmp_path / "nothing-here")
    check = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert check == UNATTACHED["overlay"]


@pytest.mark.parametrize("text", ["this is not json", "[" * 99999])
def test_a_ledger_that_does_not_parse_warns_and_never_reads_as_no_ledger(
    tmp_path: Path, text: str
) -> None:
    # Green here while `detach` exited on the same file: one answer from the reader, and `doctor`'s
    # is the warning. Mutation (oracle): `mutations/`'s "a ledger doctor cannot ask about reads as
    # no ledger".
    root = _attached(tmp_path)
    ledger_file(root).write_text(text, encoding="utf-8")
    assert _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached") == (
        UNREADABLE_LEDGER_ATTACHED
    )


@pytest.mark.parametrize("fields", NOT_LEDGERS, ids=str)
def test_a_ledger_of_the_wrong_shape_warns_as_one_that_does_not_parse(
    tmp_path: Path, fields: dict[str, object]
) -> None:
    root = _attached(tmp_path)
    rewritten(root, fields)
    assert _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached") == (
        UNREADABLE_LEDGER_ATTACHED
    )


def test_a_copy_the_team_committed_is_no_finding_once_the_overlay_dropped_it(
    tmp_path: Path,
) -> None:
    # Red for good, with a remedy that took the team's file out of the index: the row is about a
    # name attach still vouches for, and a re-attach forgets this one.
    root, store, machine = _attachable(tmp_path, codex="# standing rule\n")
    _committed(root)
    run = Recorder()
    attach(root, store=store, machine=machine, runner=run)
    _git(root, "add", "-f", ".codex/rules/common.rules")
    _git(root, "commit", "-qm", "the team keeps the rule")
    (store.parents[2] / COMMON_CODEX / "common.rules").unlink()
    attach(root, store=store, machine=machine, runner=run)
    row = _by_name(_checks(tmp_path, root, machine=machine), "attached")
    assert row.status != RED and "tracks" not in row.detail


def test_the_attached_row_names_a_refused_rebind(tmp_path: Path) -> None:
    # A pulled commit renames `[project] name`, so the ledger's store is another project's: the row
    # said only that the store is not this project's directory. It says the rebind as `attach`
    # refuses it, with `--project` as the way out. Mutation: `mutations/`'s "the attached row reads
    # a rebind as a store that is not this project's".
    from drybag.attach.binding import REBIND

    root, store, machine = _attachable(tmp_path)
    attach(root, store=store, machine=machine, runner=Recorder())
    named = (root / CONFIG_FILE).read_text(encoding="utf-8").replace('name = "p"', 'name = "q"')
    (root / CONFIG_FILE).write_text(named, encoding="utf-8")
    row = _by_name(_checks(tmp_path, root, machine=machine), "attached")
    assert (row.status, row.remedy) == (WARN, "run `drybag attach --project q`")
    assert REBIND.format(bound="p", named="q") in row.detail


@pytest.mark.parametrize(
    "shape",
    [
        "projects-is-a-file",
        "overlay-root-is-a-file",
        "projects-is-a-dangling-link",
        "overlay-root-is-a-dangling-link",
    ],
)
def test_a_bound_checkouts_damaged_overlay_is_named_and_never_answered_by_removing_the_ledger(
    tmp_path: Path, shape: str
) -> None:
    # A bound project whose overlay's `projects/`, or whose overlay root, became a file. The row
    # once read that as no binding, warned that the overlay "has no binding for this project" and
    # offered to remove the ledger, which is the one remedy that destroys this checkout's record of
    # a real attach. It names the path that is not a directory and says to repair the overlay, a
    # warning, and no row turns red. Mutation (declared): the attached row asks nothing about the
    # overlay's shape -> "has no binding" comes back.
    root = _attached(tmp_path)
    overlay = tmp_path / "overlay"
    broken = overlay / PROJECTS if shape.startswith("projects") else overlay
    shutil.rmtree(broken)
    if shape.endswith("dangling-link"):
        broken.symlink_to(broken.parent / "nowhere")
    else:
        broken.write_text("not a directory\n", encoding="utf-8")
    rows = _checks(tmp_path, root, machine=_machine(tmp_path))
    attached = _by_name(rows, "attached")
    assert attached == Check(
        "attached",
        WARN,
        f"{LEDGER_NAME} records an attach, but {broken} is not a directory, so the overlay this "
        f"machine records is damaged and holds none of this checkout's notes or grants",
        f"repair the overlay so that {broken} is a directory again (or clone the overlay afresh), "
        f"then run `drybag doctor` again",
    )
    assert "remove the ledger" not in attached.remedy
    assert [row.name for row in rows if row.status == "red"] == []


# A binding record that will not parse, as an owner's mistake or a broken disk leaves one.
UNPARSEABLE_RECORD = "remote = [unterminated\n"


# `attached` for a checkout whose binding record will not read: the overlay could not be asked,
# which is a fact about this machine and so a skip, with the way to the record's own error.
@pytest.mark.parametrize("record", ["unterminated", "number-past-the-parser"])
def test_an_owner_whose_own_binding_record_will_not_parse_is_told_where_to_look(
    tmp_path: Path, record: str
) -> None:
    # The owner's own record will not read: `attached` and `attach --check` both say where. A
    # number past the parser's reach is valid TOML that `tomllib`
    # answers with a plain `ValueError`, which none of the record's readers caught: `attached`,
    # `bundles` and `store-debris` each went red "this check could not run: ValueError", and
    # `attach --check` ended in an internal error. Mutation (declared): `ValueError` dropped from
    # `UNPARSEABLE`.
    root = _attached(tmp_path)
    record_path = tmp_path / "overlay" / PROJECTS / "p" / RECORD
    text = UNPARSEABLE_RECORD if record == "unterminated" else f"x = {LONG_NUMBER}\n"
    record_path.write_text(text, encoding="utf-8")
    machine = _machine(tmp_path)
    rows = _checks(tmp_path, root, machine=machine)
    attached = _by_name(rows, "attached")
    assert attached.status == WARN and f"/{RECORD} is not valid TOML" in attached.detail
    for name in ("bundles", "memory"):
        assert "could not run" not in _by_name(rows, name).detail
    store = tmp_path / "overlay" / PROJECTS / "p" / "memory"
    (tmp_path / "home").mkdir(exist_ok=True)
    with pytest.raises(Refusal, match=f"/{RECORD}.* is not valid TOML"):
        attach_check(root, store=store, machine=machine)


# --- the delivery ------------------------------------------------------------------------------
#
# What the binding delivers, read where `attach` left it: the render under the machine's data
# directory and the paths it placed in the checkout. Each state is asserted by its constant in
# `drybag.attach.doctor`, formatted as the row formats it.

# The remedy every delivery state but the named ones carries.
RERUN = "run `drybag attach`"


def _id(root: Path) -> str:
    found = binding.read_id(root)
    assert found is not None
    return found


def _attached_detail(clause: str) -> str:
    return f"attached; {clause}; {attach_doctor.POINTER_IN_PLACE}; the binding is bound"


def _delivered_row(tmp_path: Path, root: Path) -> Check:
    return _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")


def test_the_delivery_in_place_is_green_and_says_so(tmp_path: Path) -> None:
    # The vacuity guard for every state below: the fixture is the state a real attach leaves, the
    # render under this machine's data directory with its digest in the ledger, every placed path
    # ignored and untracked.
    root = _attached(tmp_path)
    assert _delivered_row(tmp_path, root) == Check(
        "attached", OK, _attached_detail(attach_doctor.DELIVERY_IN_PLACE), ""
    )


def test_a_render_directory_that_is_gone_is_red_and_names_it(tmp_path: Path) -> None:
    # Claude Code runs the plugin from the render directory in place, and with it gone loads
    # nothing and says nothing, so this row is the one place that says so. Mutation (oracle):
    # `mutations/`'s "the attached row reads a render directory that is gone as in place" -> green.
    root = _attached(tmp_path)
    directory = delivery_directory(_id(root))
    shutil.rmtree(directory)
    clause = attach_doctor.RENDER_GONE.format(
        short=binding.short(_id(root)), parent=quoted(str(directory.parent))
    )
    assert _delivered_row(tmp_path, root) == Check(
        "attached", RED, _attached_detail(clause), f"{RERUN}, which renders it again"
    )
    # The id is a secret: the row names the render by its first eight characters.
    assert _id(root) not in _delivered_row(tmp_path, root).detail


def test_a_render_without_its_marketplace_file_is_red(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    (delivery_directory(_id(root)) / MARKETPLACE_FILE).unlink()
    clause = attach_doctor.MARKETPLACE_GONE.format(
        short=binding.short(_id(root)), file=MARKETPLACE_FILE
    )
    assert _delivered_row(tmp_path, root) == Check(
        "attached", RED, _attached_detail(clause), f"{RERUN}, which renders it again"
    )


def test_an_overlay_that_moved_is_red_and_names_where_it_was(tmp_path: Path) -> None:
    # The delivered hooks run the overlay's scripts in place, so an overlay moved away leaves them
    # nothing to run, and the render that still loads says nothing of it.
    root = _attached(tmp_path)
    overlay = tmp_path / "overlay"
    overlay.rename(tmp_path / "moved")
    row = _delivered_row(tmp_path, root)
    assert row.status == RED, row
    assert attach_doctor.OVERLAY_GONE.format(path=quoted(str(overlay))) in row.detail
    assert "drybag setup --overlay <path>" in row.remedy


def test_a_placed_path_the_repository_tracks_is_red(tmp_path: Path) -> None:
    # A tracked file is one every collaborator gets, and no exclude line hides it.
    root = _attached(tmp_path)
    _git(root, "add", "-f", LOCAL_SETTINGS)
    clause = attach_doctor.PLACED_TRACKED.format(paths=LOCAL_SETTINGS)
    row = _delivered_row(tmp_path, root)
    assert (row.status, row.detail) == (RED, _attached_detail(clause))
    assert row.remedy.startswith("take each out of the index with `git rm --cached`")


def test_a_placed_path_a_gitignore_re_includes_is_red(tmp_path: Path) -> None:
    # A `!` line in a tracked `.gitignore` outranks the exclude block, so a pull request adding one
    # shows the settings file that names the binding id. Red once attached, as `attach` refuses it
    # before it writes.
    root = _attached(tmp_path)
    (root / ".gitignore").write_text(f"!{LOCAL_SETTINGS}\n", encoding="utf-8")
    clause = attach_doctor.PLACED_SHOWN.format(paths=LOCAL_SETTINGS)
    row = _delivered_row(tmp_path, root)
    assert (row.status, row.detail) == (RED, _attached_detail(clause))


def test_a_session_start_counts_the_placed_paths_a_gitignore_re_includes(tmp_path: Path) -> None:
    # The same state, said where someone is about to stage it: a hint, once per context, and a
    # `compact` is the context asking again. Mutation (`mutations/`'s "the session start stops
    # counting what a `.gitignore` re-included"): the count is 0 -> the second assertion reddens.
    root = _attached(tmp_path)
    handler = next(h for h in attach_hooks.register() if h.name == "overlay-placed-shown")
    assert handler.once_key == "overlay-placed-shown"
    event = HookEvent("SessionStart", "s", None, None, {}, root, root, {})
    assert handler.run(event, NO_CONFIG).context is None
    (root / ".gitignore").write_text(f"!{LOCAL_SETTINGS}\n", encoding="utf-8")
    assert handler.run(event, NO_CONFIG).context == attach_hooks.PLACED_SHOWN.format(count=1)
    assert handler.run(replace(event, raw={"source": "compact"}), NO_CONFIG).context is None


def test_a_tracked_file_naming_the_delivery_is_red_and_never_prints_the_id(tmp_path: Path) -> None:
    # The delivery's name carries the binding id, the one name a clone would need to run this
    # machine's delivery; a tracked file holding it is a leak on its way out. Asked for the whole
    # name: this repository's own sources spell the prefix.
    root = _attached(tmp_path)
    name = f"drybag-delivery-{_id(root)}"
    (root / "notes.md").write_text(f"enabled: overlay-x@{name}\n", encoding="utf-8")
    (root / "prefix.md").write_text("drybag-delivery-<id>\n", encoding="utf-8")
    _git(root, "add", "notes.md", "prefix.md")
    row = _delivered_row(tmp_path, root)
    assert (row.status, row.detail) == (
        RED,
        _attached_detail(attach_doctor.ID_COMMITTED.format(paths="notes.md")),
    )
    assert _id(root) not in row.detail + row.remedy


def test_a_git_that_cannot_say_what_it_tracks_warns_and_never_reads_as_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "Could not ask" is never "nothing tracked": a git that cannot answer leaves the placed paths
    # unchecked, which the row says.
    from drybag.attach import exclude

    def unanswered(root: Path, relatives: object) -> tuple[str, ...]:
        raise Refusal(exclude.UNANSWERED)

    root = _attached(tmp_path)
    monkeypatch.setattr(exclude, "tracked", unanswered)
    row = _delivered_row(tmp_path, root)
    assert (row.status, row.detail) == (WARN, _attached_detail(attach_doctor.PLACED_UNASKED))


def _ledger_field(root: Path, **fields: object) -> None:
    recorded = json.loads(ledger_file(root).read_text(encoding="utf-8"))
    ledger_file(root).write_text(json.dumps({**recorded, **fields}), encoding="utf-8")


def test_a_ledger_that_records_no_install_warns(tmp_path: Path) -> None:
    # `attach` records the render only once `claude plugin install` succeeded.
    root = _attached(tmp_path)
    _ledger_field(root, render=None)
    assert _delivered_row(tmp_path, root) == Check(
        "attached", WARN, _attached_detail(attach_doctor.UNINSTALLED), f"{RERUN}, which installs it"
    )


def test_an_overlay_that_changed_since_the_render_warns_of_drift(tmp_path: Path) -> None:
    # What runs is what the last attach rendered; an overlay edited since is said, and refused
    # nowhere.
    root = _attached(tmp_path)
    hooks = tmp_path / "overlay" / COMMON_CLAUDE / "hooks.json"
    hooks.write_text(hooks.read_text(encoding="utf-8").replace("echo hi", "echo changed"), "utf-8")
    assert _delivered_row(tmp_path, root) == Check(
        "attached",
        WARN,
        _attached_detail(attach_doctor.DRIFTED),
        f"{RERUN}, which renders the overlay as it is now",
    )


def test_an_overlay_whose_parts_cannot_be_read_warns_and_says_where_to_look(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    (tmp_path / "overlay" / COMMON_CLAUDE / "hooks.json").write_text("{", encoding="utf-8")
    assert _delivered_row(tmp_path, root) == Check(
        "attached",
        WARN,
        _attached_detail(attach_doctor.OVERLAY_UNREAD),
        "run `drybag attach --check`, which says why",
    )


def test_a_launcher_the_path_scoped_rules_run_through_that_is_gone_warns(tmp_path: Path) -> None:
    # The path-scoped rules' entry runs `hook PostToolUse` through the launcher that ran `attach`,
    # by its absolute path; the render keeps it, so a drybag moved or uninstalled since leaves
    # those rules undelivered. The digest is taken with the launcher the render holds, so the
    # report reads no drift for a launcher of its own.
    root = _attached(tmp_path)
    overlay = tmp_path / "overlay"
    rules = overlay / COMMON_CLAUDE / "rules"
    rules.mkdir()
    (rules / "scoped.md").write_text("---\npaths: src/**\n---\nA rule.\n", encoding="utf-8")
    gone = tmp_path / "gone" / "run-hook.sh"
    command = f'"{gone}" hook PostToolUse'
    rendered = render_write(
        _id(root), read_parts(plates(overlay, "p", machine=None)[0], command=command)
    )
    _ledger_field(root, render={"digest": rendered.digest})
    assert _delivered_row(tmp_path, root) == Check(
        "attached",
        WARN,
        _attached_detail(attach_doctor.LAUNCHER_GONE.format(path=quoted(str(gone)))),
        f"{RERUN} from the drybag you run now, which renders the entry through it",
    )


def test_an_owners_checkout_whose_origin_moved_keeps_its_binding_and_says_so(
    tmp_path: Path,
) -> None:
    # An owner points `origin` at a fork. The binding is this machine's record of the checkout's
    # id, so it stays bound; the remote it was recorded with is said beside it, a warning, since
    # the next attach records the new one.
    root = _attached(tmp_path)
    _git(root, "remote", "set-url", "origin", "https://github.com/fork/p.git")
    row = _delivered_row(tmp_path, root)
    assert row.status == WARN, row
    assert row.detail.endswith("; the binding is bound")
    assert "`origin` is" in row.detail and "fork/p.git" in row.detail
    assert row.remedy == RERUN


def test_a_red_delivery_beside_a_pointer_warning_keeps_its_red_and_both_remedies(
    tmp_path: Path,
) -> None:
    # The row takes the worse of the delivery and the pointer, and the worse one's remedy first: a
    # missing pointer never softens a render that is gone, and a render that is gone never hides
    # the pointer's way out.
    root = _attached(tmp_path)
    shutil.rmtree(delivery_directory(_id(root)))
    _pointer_set(root, None)
    row = _row(tmp_path, root)
    assert row.status == RED
    assert "autoMemoryDirectory" in row.detail and "render directory" in row.detail
    assert row.remedy == f"{RERUN}, which renders it again; {RERUN}, which writes it"


def test_a_repository_whose_notes_are_not_linked_is_attached_by_its_delivery_alone(
    tmp_path: Path,
) -> None:
    # Delivery does not depend on the memory mode, so a `local-only` repository with a ledger the
    # binding confirms is read for its delivery, and the memory pointer is not asked.
    root = _attached(tmp_path)
    (root / CONFIG_FILE).write_text(
        (root / CONFIG_FILE).read_text(encoding="utf-8").replace('"overlay"', '"local-only"'),
        encoding="utf-8",
    )
    assert _delivered_row(tmp_path, root) == Check(
        "attached",
        OK,
        f"attached; {attach_doctor.DELIVERY_IN_PLACE}; the binding is bound",
        "",
    )


def test_the_attached_row_reads_the_main_checkouts_pointer_from_every_checkout(
    tmp_path: Path,
) -> None:
    # The harness reads `autoMemoryDirectory` from the main checkout's settings file in every
    # worktree, and `attach` writes it and its ledger there alone, so the row reads both there,
    # from the main checkout and from a linked worktree alike, and says nothing of a harness memory
    # path, which nothing places any more.
    from drybag.attach.write import attach
    from tests.attach.test_detach import _bound

    root, store, machine = _bound(tmp_path)
    side = tmp_path / "side"
    _git(root, "worktree", "add", "-q", str(side), "-b", "side")
    attach(root, store=store, machine=machine, runner=Recorder())
    for checkout in (root, side):
        rows = doctor_checks.run_checks(checkout, home=None, machine=machine, env=_env(tmp_path))
        row = _by_name(rows, "attached")
        assert (row.status, row.detail) == (
            OK,
            "attached; the delivery is in place; autoMemoryDirectory points the harness at the "
            "composed store; the binding is bound",
        ), checkout


def _tag_file(overlay: Path, tag: str, relative: str, text: str = "x\n") -> None:
    path = overlay / "tags" / tag / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_two_tags_holding_one_rule_name_is_a_warning_naming_both_and_the_winner(
    tmp_path: Path,
) -> None:
    root = _attached(tmp_path)
    overlay = with_tags(tmp_path / "overlay", "p", ["a", "b"])
    for tag in ("a", "b"):
        _tag_file(overlay, tag, "claude/rules/x.md")
    clause = "the rule x.md is held by the tags a, b: the later, b, wins"
    assert _delivered_row(tmp_path, root) == Check(
        "attached", WARN, _attached_detail(clause), attach_doctor.TAGS_REMEDY
    )


def test_two_tags_setting_one_key_is_a_warning(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    overlay = with_tags(tmp_path / "overlay", "p", ["a", "b"])
    for tag in ("a", "b"):
        _tag_file(overlay, tag, "drybag.toml", '[memory]\nmode = "overlay"\n')
    clause = "the setting memory.mode is held by the tags a, b: the later, b, wins"
    assert _delivered_row(tmp_path, root) == Check(
        "attached", WARN, _attached_detail(clause), attach_doctor.TAGS_REMEDY
    )


def test_a_listed_tag_with_no_directory_is_a_warning(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    with_tags(tmp_path / "overlay", "p", ["a"])
    shutil.rmtree(tmp_path / "overlay" / "tags" / "a")
    row = _delivered_row(tmp_path, root)
    assert row.status == WARN and row.remedy == attach_doctor.TAGS_REMEDY
    assert "the tag a has no directory tags/a; it is skipped" in row.detail


def test_doctor_names_a_project_memory_directory_in_the_tag_namespace(tmp_path: Path) -> None:
    # `tag-` is a tag's link name in the composed store, so the project's own directory of that
    # name is not linked: the warning names it, in the tags finding. So is a machine sub-plate's
    # link shape, and no other `machine-...` name.
    root = _attached(tmp_path)
    memory = tmp_path / "overlay" / PROJECTS / "p" / "memory"
    (memory / "tag-a").mkdir(parents=True)
    (memory / "tag-file").write_text("not a directory\n", encoding="utf-8")
    (memory / "machine-m1-project").mkdir()
    (memory / "machine-notes").mkdir()
    row = _delivered_row(tmp_path, root)
    assert row.status == WARN and row.remedy == attach_doctor.TAGS_REMEDY
    assert attach_doctor.RESERVED_GROUP.format(name="tag-a") in row.detail
    assert attach_doctor.RESERVED_GROUP.format(name="machine-m1-project") in row.detail
    assert "tag-file" not in row.detail and "machine-notes" not in row.detail


def test_a_tag_warning_never_hides_a_red_finding(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    overlay = with_tags(tmp_path / "overlay", "p", ["a", "b"])
    for tag in ("a", "b"):
        _tag_file(overlay, tag, "claude/rules/x.md")
    shutil.rmtree(delivery_directory(_id(root)))
    row = _delivered_row(tmp_path, root)
    assert row.status == RED
    assert attach_doctor.TAGS_REMEDY not in row.remedy
    assert "render directory" in row.detail


# --- the overlay's MCP servers, read from the overlay and the ledger alone ---------------------

A, D = {"command": "a"}, {"command": "d"}


def _mcp_file(overlay: Path, plate: str, servers: Mapping[str, object]) -> None:
    path = overlay / plate / "claude" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def _named_machine(tmp_path: Path, name: str) -> Path:
    """`_machine`, with `[machine] name` set, so the plates' `machines/<name>/` sub-plates apply."""
    path = _machine(tmp_path)
    with path.open("a", encoding="utf-8") as file:
        file.write(f'[machine]\nname = "{name}"\n')
    return path


def _mcp_row(tmp_path: Path, root: Path, machine: Path | None = None) -> Check:
    return _by_name(_checks(tmp_path, root, machine=machine or _machine(tmp_path)), "attached")


def test_doctor_attributes_each_served_name_to_its_plates(tmp_path: Path) -> None:
    # Each name the overlay delivers with the plate whose definition wins and, where another one
    # set its state, that plate too; each name switched off with the plate that said so. A
    # sub-plate is its parent's path and the machine, as the values' provenance says it.
    root = _attached(tmp_path)
    overlay = with_tags(tmp_path / "overlay", "p", ["t1"])
    _mcp_file(overlay, "common", {"alpha": A, "gamma": {"command": "g"}})
    _mcp_file(overlay, "tags/t1/machines/m1", {"alpha": "on", "beta": "off"})
    _mcp_file(overlay, "projects/p", {"delta": D, "gamma": "off"})
    write_mcp_ledger(root, McpLedger(mcp={"alpha": digest(A), "delta": digest(D)}))
    row = _mcp_row(tmp_path, root, _named_machine(tmp_path, "m1"))
    assert row.status == OK, row
    assert (
        "MCP servers the overlay delivers: alpha (defined in common, switched on in tags/t1 on "
        "m1), delta (projects/p)" in row.detail
    )
    assert (
        "MCP servers the overlay switches off: beta (tags/t1 on m1), gamma (projects/p)"
        in row.detail
    )
    assert attach_doctor.MCP_UNSEEN in row.detail


def test_doctor_warns_of_each_name_attach_would_deliver_or_take_back(tmp_path: Path) -> None:
    # As a drifted hook is: a served name not delivered, one under another digest or unsettled,
    # and one the ledger owns that the overlay no longer serves.
    root = _attached(tmp_path)
    _mcp_file(tmp_path / "overlay", "common", {"alpha": A, "beta": A, "delta": D, "eps": A})
    owned = {"alpha": None, "beta": digest(D), "eps": digest(A), "gone": digest(A)}
    write_mcp_ledger(root, McpLedger(mcp=owned))
    row = _mcp_row(tmp_path, root)
    assert (row.status, row.remedy) == (WARN, RERUN), row
    names = "alpha, beta, delta, gone"
    pending = attach_doctor.MCP_PENDING.format(ledger=MCP_LEDGER_NAME, names=names)
    assert pending in row.detail


def test_doctor_says_why_attach_would_change_nothing_mcp(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    path = tmp_path / "overlay" / "common" / "claude" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<<<<<<< HEAD", encoding="utf-8")
    (common_directory(root) / MCP_LEDGER_FILE).write_text('{"format": 2}', encoding="utf-8")
    row = _mcp_row(tmp_path, root)
    assert row.status == WARN and row.remedy.startswith("make each MCP file named readable"), row
    assert UNUSABLE.format(path=quoted(str(path))) in row.detail
    assert BAD_LEDGER.format(name=MCP_LEDGER_NAME) in row.detail


def test_a_lone_surrogate_in_an_mcp_definition_leaves_the_row_unred(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    _mcp_file(tmp_path / "overlay", "common", {"m1": {"command": "a", "args": ["\ud800"]}})
    assert _mcp_row(tmp_path, root).status != RED


def _names_claude(argv: list[str]) -> bool:
    """Whether any word of `argv` is a `claude` executable, by name or by path."""
    return any(Path(word).name == "claude" for item in argv for word in item.split())


def _launches(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every process this process starts from here on, by argv, at each layer a launch reaches:
    `subprocess.Popen`, under `subprocess.run` and every runner, and the `os` calls beneath and
    beside it. A `claude` launch is recorded, then refused before it can start."""
    launched: list[list[str]] = []

    def watched(original: Any, at: int, keyword: str = "args") -> Any:
        def launch(*args: Any, **kwargs: Any) -> Any:
            raw = kwargs[keyword] if keyword in kwargs else args[at]
            items = [raw] if isinstance(raw, (str, bytes, os.PathLike)) else list(raw)
            argv = [os.fsdecode(item) for item in items]
            launched.append(argv)
            if _names_claude(argv):
                raise AssertionError(f"a claude launch: {argv}")
            return original(*args, **kwargs)

        return launch

    monkeypatch.setattr(subprocess.Popen, "__init__", watched(subprocess.Popen.__init__, 1))
    monkeypatch.setattr(os, "system", watched(os.system, 0, "command"))
    for name in ("posix_spawn", "posix_spawnp", "execv", "execve", "execvp", "execvpe"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, watched(getattr(os, name), 1, "argv"))
    return launched


def test_doctor_runs_no_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `claude mcp get` and `list` health-check what they name: they spawn a stdio server and run a
    # `headersHelper`. So the finding reads the overlay and the ledger and launches nothing: the
    # report of a checkout whose ledger owns names starts exactly the processes the same report
    # with the finding taken out starts, and no `claude` among them.
    root = _attached(tmp_path)
    machine = _machine(tmp_path)
    _mcp_file(tmp_path / "overlay", "common", {"alpha": A, "beta": "off"})
    write_mcp_ledger(root, McpLedger(mcp={"alpha": None, "gamma": "0" * 64}))
    launched = _launches(monkeypatch)
    with monkeypatch.context() as without_mcp:
        without_mcp.setattr(attach_doctor, "_mcp", lambda _bound, _recorded: [])
        _checks(tmp_path, root, machine=machine)
    without = list(launched)
    assert without, "the patched layers saw no launch at all, so they watch nothing"
    launched.clear()
    row = _by_name(_checks(tmp_path, root, machine=machine), "attached")
    assert not [argv for argv in launched if _names_claude(argv)], launched
    assert launched == without
    assert "alpha" in row.detail, row


# A value only a secret would hold, absent from every row of the report whatever it says.
MARKER = "sk-marker-not-for-output"


def test_an_env_or_headers_value_is_named_by_its_key_never_printed(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    alpha = {"command": "a", "env": {"TOKEN": MARKER}, "headers": {"X": "${X}"}, "args": [MARKER]}
    _mcp_file(tmp_path / "overlay", "common", {"alpha": alpha})
    write_mcp_ledger(root, McpLedger(mcp={"alpha": digest(alpha)}))
    row = _mcp_row(tmp_path, root)
    assert row.status == OK, row
    written = attach_doctor.MCP_WRITTEN.format(name="alpha", keys="env.TOKEN, headers.X")
    assert written in row.detail
    assert MARKER not in repr(_checks(tmp_path, root, machine=_machine(tmp_path)))
