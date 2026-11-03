"""What the `attached` row in `stayfixed doctor` answers, now that `attach` contributes it.

Every case runs the whole report through `run_checks`, so the row is asked the way a user's
`stayfixed doctor` asks it: discovered in this area's `doctor.py`, with the note store resolved by
the lazy value its `register()` creates and the overlay root by the report's `Context`. The
fixtures are the doctor area's own (`tests/doctor/test_checks.py`), shared rather than respelled.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from stayfixed import binding
from stayfixed.attach import doctor as attach_doctor
from stayfixed.attach.api import LOCAL_SETTINGS
from stayfixed.attach.check import check as attach_check
from stayfixed.attach.render import MARKETPLACE_FILE, read_parts
from stayfixed.attach.render import write as render_write
from stayfixed.binding import delivery_directory
from stayfixed.config.layout import ATTACH_LEDGER as LEDGER
from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.doctor import checks as doctor_checks
from stayfixed.doctor.api import OK, RED, SKIP, WARN, Check
from stayfixed.errors import Refusal
from stayfixed.memory.api import PROJECT_RECORD, PROJECTS
from stayfixed.overlay.api import COMMON_CLAUDE
from stayfixed.printed import quoted
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
from tests.parserlimits import LONG_NUMBER, NESTED
from tests.runners import Recorder

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _past_a_name(tmp_path: Path, path: Path) -> None:
    """Make `path` a symbolic link to a name longer than a file name may be on Linux and macOS.

    A clone can commit the link, and nothing on the machine has to be wrong for it. Asked about
    through it, `stat` raises `ENAMETOOLONG` on every supported Python; `Path.is_file()` raises it
    on 3.11 to 3.13 and answers `False` from 3.14.
    """
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.is_symlink() or path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(tmp_path / ("x" * 300))


# The row as `stayfixed doctor --json` prints it for a project that was never attached, pasted here
# and never derived from the code under test. The overlay case is the bytes captured before the row
# moved into this area; the `local-only` one changed when delivery stopped depending on the memory
# mode, since `attach` delivers to such a repository too, and "there is no overlay to bind to" was
# no longer true of it.
UNATTACHED = {
    "overlay": Check(
        "attached",
        "warn",
        "memory.mode is overlay and .stayfixed/local/attach.json does not exist, so nothing "
        "records an attach",
        "run `stayfixed attach --check`",
    ),
    "local-only": Check(
        "attached", "ok", f"{LEDGER} does not exist, so nothing records an attach", ""
    ),
}


@pytest.mark.parametrize("mode", sorted(UNATTACHED))
def test_an_unattached_project_reports_attached_as_it_did(tmp_path: Path, mode: str) -> None:
    # A checkout with a `stayfixed.toml` and a git repository and nothing `attach` wrote: the
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
    (tmp_path / "overlay" / PROJECTS / "p" / PROJECT_RECORD).write_text(
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
    # configured for an overlay before anyone has run `stayfixed attach` in this checkout, which
    # is the ordinary state of a fresh clone. The remedy is the command that ends it.
    root = _attached(tmp_path)
    (root / LEDGER).unlink()
    check = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert check.status == "warn"
    assert LEDGER in check.detail
    assert "stayfixed attach" in check.remedy


def test_an_empty_home_is_told_it_is_home_that_names_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The render and the composed store are under the home's data directory, and an empty `HOME`
    # names no home. The row says so, as a warning and never "this check could not run". Asked of
    # the row directly, which is how a person runs `doctor`. Mutation (oracle): `mutations/`'s
    # "the attached row dies on a home it cannot name".
    from stayfixed.attach.doctor import _attached as attached_row
    from stayfixed.attach.doctor import _Ledger
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
    from stayfixed.memory.api import composed_directory

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
    from stayfixed.memory.api import composed_directory

    root = _attached(tmp_path)
    link = composed_directory(_id(root)) / "developer"
    link.unlink()
    link.symlink_to(tmp_path / "moved-away" / "common" / "memory", target_is_directory=True)
    row = _row(tmp_path, root)
    assert (row.status, row.detail) == (
        WARN,
        f"attached; the delivery is in place; {attach_doctor.STORE_DANGLES}; the binding is bound",
    )
    assert "stayfixed attach" in row.remedy


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
    # `.stayfixed/local/attach.json` is a path a clone can commit, and `_attached` took its
    # existence as "this checkout was attached". The binding this machine keeps is the trusted
    # side, so the row asks it: a ledger with no binding id behind it in the git common directory
    # is a warning that names the file, and the remedy says what to do in each of the two cases.
    #
    # Mutation (declared): `if state == UNBOUND or id is None:` -> `if False:` -> the row falls
    # through to the harness-shape branch and this reddens on the sentence.
    root = _attached(tmp_path)
    kept = root / ".git" / "stayfixed" / "binding"
    assert kept.is_file(), "the fixture must have recorded a binding for this to be a probe"
    kept.unlink()
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert row.status == WARN
    assert "records no binding of this checkout to this project" in row.detail
    assert "a clone can commit that file" in row.detail
    assert "stayfixed attach" in row.remedy and "remove the ledger" in row.remedy


def test_a_ledger_naming_a_store_the_overlay_does_not_permit_is_a_warning(tmp_path: Path) -> None:
    # `_attached` asked the overlay only for its *state*, and `read_binding` answers with a
    # `Refusal` — not a state — when the store the ledger names is not this project's share of
    # the recorded overlay. That refusal used to collapse into the same `None` as "no overlay
    # recorded", the row skipped both new arms, and a repository that committed
    # `.stayfixed/local/attach.json` with any store it liked was reported `attached: ok` to a
    # model. This is the likeliest hostile shape of the three: an attacker cannot know
    # the victim's overlay root, so the store they commit is one the overlay does not permit.
    #
    # `warn` and not `skip`: this is a fact about the repository, and `skip` never reaches the
    # exit code.
    #
    # Mutation (declared): `except Refusal: return UNRESOLVED` -> `return UNASKABLE` -> the row
    # becomes a skip about this machine and this reddens on the status and the sentence.
    root = _attached(tmp_path)
    recorded = json.loads((root / LEDGER).read_text(encoding="utf-8"))
    recorded["store"] = str(tmp_path / "somewhere-else" / "memory")
    (root / LEDGER).write_text(json.dumps(recorded), encoding="utf-8")
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert row.status == WARN
    assert "is not this project's directory inside the overlay" in row.detail
    assert "not evidence of an attach" in row.detail
    assert "attached;" not in row.detail, "a ledger the overlay does not confirm is not an attach"
    assert "stayfixed attach" in row.remedy and "remove the ledger" in row.remedy


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
    assert "stayfixed setup --overlay" in row.remedy


def test_a_ledger_on_a_machine_whose_file_does_not_load_skips_in_words_of_its_own(
    tmp_path: Path,
) -> None:
    # Whether a machine whose file nobody could read records an overlay is not known, which is
    # neither of the two arms beside it: read as no overlay, the row told the owner to run
    # `stayfixed setup --overlay`; read as an overlay that could not be asked, it blamed `git`. The
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
    (overlay / PROJECTS / "p" / PROJECT_RECORD).write_text("remote = [", encoding="utf-8")
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert row.status == WARN
    assert f"{PROJECT_RECORD} is not valid TOML" in row.detail and "attached;" in row.detail
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


def test_a_ledger_that_cannot_be_read_is_this_repositorys_doing_and_never_blamed_on_git(
    tmp_path: Path,
) -> None:
    # `_binding_answer` had three answers and needed four. A ledger that is there and will not
    # parse was joining "no overlay" and "no git" under `unaskable`, so the row said "no `git`,
    # or a record this process could not read" and the remedy said "run `stayfixed doctor` again
    # where `git` runs" — about a file in the checkout the reader is standing in. `skip` never
    # reaches the exit code either, so a clone's committed, malformed ledger was silent, which
    # is the split `_uncorroborated`'s own docstring exists to make.
    #
    # Mutation (declared): the unreadable ledger answers `UNASKABLE` again -> the row is `skip`,
    # blames `git`, and every assertion below reddens.
    root = _attached(tmp_path)
    (root / LEDGER).write_text("this is not json", encoding="utf-8")
    row = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")

    assert row.status == WARN
    assert f"{LEDGER} is here and cannot be read as a ledger" in row.detail
    assert "`git`" not in row.detail and "`git`" not in row.remedy
    assert LEDGER in row.remedy


# Ledger fields a clone can commit in shapes `attach` never writes, each of which used to raise out
# of the ledger's reader with something other than its refusal, or to be read as something it is
# not: a `store` holding a NUL, which `Path.resolve` meets as `ValueError`, and one holding a lone
# surrogate, which it meets as `UnicodeEncodeError`; a `store` or an entry's event that is not text,
# which the reader passed through `str()`, so `5` read as the store `5`; and a list field holding a
# number, which the reader's iteration meets as `TypeError`.
HOSTILE_FIELDS = {
    "store-nul": ("store", "/overlay/projects/widget/memory\u0000"),
    "store-unencodable": ("store", "/overlay/projects/widget/memory\ud800"),
    "store-not-text": ("store", 5),
    "entry-event-not-text": ("entries", {"x": 5}),
    "allow-not-a-list": ("allow", 5),
    "rules-not-a-list": ("rules", 5),
    "settings-keys-not-a-list": ("settings_keys", 5),
    "directories-not-a-list": ("directories", 5),
    # A list of the right shape naming a file `attach` could not have written: the reader refuses
    # it, and both of `doctor`'s callers of the reader must read that refusal as a ledger that
    # cannot be read rather than let it reach the report's guard.
    "rules-naming-a-workflow": ("rules", [".github/workflows/ci.yml"]),
}

# Deeper than `str()` follows a nested list, and no deeper than Python 3.14's parser does, so the
# parser reads the ledger and `str()` is what overflows: measured on 3.14.7, the parser's reach ends
# between 50,000 and 60,000 levels and `str()`'s between 30,000 and 40,000. Below 3.14 the parser
# refuses this depth itself, which the `nested` case holds.
PAST_STR = 45_000
# The two fields the reader passed through `str()`, each nested `PAST_STR` deep.
PAST_STR_FIELDS = {"store-past-str": "store", "entry-past-str": "entries"}

# The `attached` row beside a ledger that cannot be read, pasted rather than read back from the
# code under test.
UNREADABLE_LEDGER_ATTACHED = Check(
    "attached",
    "warn",
    f"{LEDGER} is here and cannot be read as a ledger, so nothing in it can be corroborated "
    f"and this checkout's attach state is unknown — a clone can commit {LEDGER}, so on its own "
    f"it is not evidence of an attach",
    f"remove {LEDGER}, then run `stayfixed attach --check`",
)


# A ledger `ledger()` cannot read, by its whole bytes.
UNREADABLE_LEDGERS = {
    "not-json": "this is not json",
    "rules-not-a-list": json.dumps({"rules": 5}),
    "nested": '{"entries": ' + NESTED + "}",
    "long-number": '{"entries": {"forged-1": ' + LONG_NUMBER + "}}",
}


def _unreadable_own_ledger(root: Path, shape: str) -> None:
    """Replace the owner's ledger in `root` with `shape`, one `ledger()` cannot read: a field from
    `HOSTILE_FIELDS`, a field from `PAST_STR_FIELDS`, or whole bytes from `UNREADABLE_LEDGERS`."""
    recorded = json.loads((root / LEDGER).read_text(encoding="utf-8"))
    if shape in HOSTILE_FIELDS:
        key, value = HOSTILE_FIELDS[shape]
        recorded[key] = value
        text = json.dumps(recorded)
    elif shape in PAST_STR_FIELDS:
        if PAST_STR_FIELDS[shape] == "store":
            recorded["store"] = "@deep@"
        else:
            # A key an earlier release's `attach` recorded, because the reader only ever converted
            # the event under a key that round-trips through the marker.
            recorded["entries"] = {"overlay-PreToolUse-1": "@deep@"}
        text = json.dumps(recorded).replace('"@deep@"', "[" * PAST_STR + "]" * PAST_STR)
    else:
        text = UNREADABLE_LEDGERS[shape]
    (root / LEDGER).write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    "shape",
    [
        *sorted(HOSTILE_FIELDS),
        "not-json",
        "nested",
        "long-number",
        *(
            pytest.param(
                shape,
                marks=pytest.mark.skipif(
                    sys.version_info < (3, 14), reason="below 3.14 the parser stops first"
                ),
            )
            for shape in sorted(PAST_STR_FIELDS)
        ),
    ],
)
def test_a_committed_ledger_of_a_shape_attach_never_writes_reads_as_unreadable(
    tmp_path: Path, shape: str
) -> None:
    # `.gitignore` does not untrack a file a clone committed, so the ledger's path holds whatever a
    # repository likes. Each of these shapes reached `_guarded` as an exception the area did not
    # catch, from both rows that read the ledger: red, "this check could not run", exit 1, and the
    # remedy "report this", on a file a clone chose and an installation with nothing wrong with it.
    # Not JSON, it raised out of `ledger()`; nested past what `json.loads` follows, it raised
    # `RecursionError`; holding a number longer than the interpreter converts, a plain `ValueError`;
    # and on Python 3.14, whose parser follows deeper than `str()` does, a value the reader passed
    # through `str()` overflowed it. The row now reads the ledger as one that cannot be read,
    # warns, and says so. The vacuity guard is
    # `test_an_attached_checkout_the_overlay_confirms_is_still_green_and_says_the_binding`: the
    # same fixture with its ledger readable is green.
    #
    # Mutations (oracle): `mutations/`'s "the attach ledger's reader
    # takes a store holding a NUL" -> `store-nul` is red again; "the attach ledger's reader takes a
    # store no path can spell" -> `store-unencodable` is; "the attach ledger's reader reads a store
    # that is not text" and "the attach ledger's reader reads an entry's event that is not text" ->
    # the `-not-text` cases read the ledger as one it could read; "the attach ledger's reader
    # iterates a field that is not a list" -> the list cases are red again; "the JSON object reader
    # lets a document nested past the parser raise" -> `nested` is; "the JSON object reader lets a
    # number past the parser's reach raise" -> `long-number` is. The `-past-str` cases skip on the
    # oracle's 3.13 and were measured by hand on 3.14.7 against the two `-not-text` entries: the
    # `store` case red again in both rows, the `entries` case read as a ledger that could be read.
    root = _attached(tmp_path)
    _unreadable_own_ledger(root, shape)
    rows = _checks(tmp_path, root, machine=_machine(tmp_path))
    assert [(row.name, row.detail) for row in rows if row.status == "red"] == []
    assert _by_name(rows, "attached") == UNREADABLE_LEDGER_ATTACHED


def test_one_report_reads_the_ledger_once_and_the_configuration_not_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `attached` reads the ledger more than once, and the row needs the binding behind it. The
    # ledger had three readers that asked three ways — one of them the
    # `is_file()` that a link to an over-long name defeats — and parsed the file twice, and the
    # binding was read through `read_binding` without the report's `Config`, so `stayfixed.toml`
    # and the machine file were loaded a second time. Measured by hand: `_Ledger.state` asking
    # `_ledger_state` every time -> three ledger reads; `read_binding` without `config=` -> one
    # load.
    from stayfixed.attach import binding, write

    reads: list[Path] = []
    loads: list[Path] = []
    real_ledger = write.ledger

    def counted_ledger(root: Path) -> object:
        reads.append(root)
        return real_ledger(root)

    def counted_load(root: Path, *, machine: Path | None) -> object:
        # `load` is the loader's own, which `binding` imports by name; only `read_binding` calls it
        # through that module.
        loads.append(root)
        return load(root, machine=machine)

    monkeypatch.setattr(write, "ledger", counted_ledger)
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
    from stayfixed.config.overlay import overlay_root

    asked: list[Path | None] = []

    def counted(machine: Path | None) -> Path | None:
        asked.append(machine)
        return overlay_root(machine)

    # The name the report's `Context` calls the machine file's reader by, in `doctor.model`.
    monkeypatch.setattr("stayfixed.doctor.model.recorded_overlay_root", counted)
    root = _attached(tmp_path)
    rows = _checks(tmp_path, root, machine=_machine(tmp_path))
    # Non-vacuous: both areas read the root, and found the overlay there.
    assert _by_name(rows, "attached").detail.startswith("attached;")
    assert _by_name(rows, "pre-commit").status != SKIP
    assert asked == [_machine(tmp_path)]


# --- the ledger's path, the binding record and the overlay's shape -----------------------------


# Where a clone can put a symbolic link to a name longer than a file name may be, so that `stat`
# cannot answer about the ledger on any supported Python: the ledger itself, and the directory that
# holds it.
UNCHECKABLE_LEDGERS = {"the-ledger": LEDGER, "its-directory": str(Path(LEDGER).parent)}


@pytest.mark.parametrize("shape", sorted(UNCHECKABLE_LEDGERS))
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
    _past_a_name(tmp_path, root / UNCHECKABLE_LEDGERS[shape])
    rows = _checks(tmp_path, root, machine=_machine(tmp_path))
    assert _by_name(rows, "attached") == UNREADABLE_LEDGER_ATTACHED


# Committed shapes at the ledger's path that name no file to read, which the row reads as no
# ledger, as it always has: nothing there records an attach.
NAMES_NO_LEDGER = ("a-dangling-link", "a-link-loop", "a-directory")


@pytest.mark.parametrize("shape", NAMES_NO_LEDGER)
def test_a_ledger_path_that_names_no_file_is_no_ledger_as_before(
    tmp_path: Path, shape: str
) -> None:
    # The vacuity guard for the case above: asking with `stat` must not turn every path that holds
    # no ledger into one that cannot be read. Mutations (oracle): `mutations/`'s "the regular-file
    # probe is blind to a path that names no file" -> the dangling link and the loop say the
    # ledger cannot be read; "the regular-file probe reads a path that is no regular file" -> the
    # directory does.
    root = _attached(tmp_path)
    path = root / LEDGER
    path.unlink()
    if shape == "a-dangling-link":
        path.symlink_to(tmp_path / "nothing-here")
    elif shape == "a-link-loop":
        path.symlink_to(path)
    else:
        path.mkdir()
    check = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "attached")
    assert check == UNATTACHED["overlay"]


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
        f"{LEDGER} records an attach, but {broken} is not a directory, so the overlay this "
        f"machine records is damaged and holds none of this checkout's notes or grants",
        f"repair the overlay so that {broken} is a directory again (or clone the overlay afresh), "
        f"then run `stayfixed doctor` again",
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
    record_path = tmp_path / "overlay" / PROJECTS / "p" / PROJECT_RECORD
    text = UNPARSEABLE_RECORD if record == "unterminated" else f"x = {LONG_NUMBER}\n"
    record_path.write_text(text, encoding="utf-8")
    machine = _machine(tmp_path)
    rows = _checks(tmp_path, root, machine=machine)
    attached = _by_name(rows, "attached")
    assert attached.status == WARN and f"/{PROJECT_RECORD} is not valid TOML" in attached.detail
    for name in ("bundles", "memory"):
        assert "could not run" not in _by_name(rows, name).detail
    store = tmp_path / "overlay" / PROJECTS / "p" / "memory"
    (tmp_path / "home").mkdir(exist_ok=True)
    with pytest.raises(Refusal, match=f"/{PROJECT_RECORD}.* is not valid TOML"):
        attach_check(root, store=store, machine=machine)


# --- the delivery ------------------------------------------------------------------------------
#
# What the binding delivers, read where `attach` left it: the render under the machine's data
# directory and the paths it placed in the checkout. Each state is asserted by its constant in
# `stayfixed.attach.doctor`, formatted as the row formats it.

# The remedy every delivery state but the named ones carries.
RERUN = "run `stayfixed attach`"


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
    assert "stayfixed setup --overlay <path>" in row.remedy


def test_a_placed_path_the_repository_tracks_is_red(tmp_path: Path) -> None:
    # A tracked file is one every collaborator gets, and no exclude line hides it.
    root = _attached(tmp_path)
    _git(root, "add", "-f", LEDGER)
    clause = attach_doctor.PLACED_TRACKED.format(paths=LEDGER)
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


def test_a_tracked_file_naming_the_delivery_is_red_and_never_prints_the_id(tmp_path: Path) -> None:
    # The delivery's name carries the binding id, the one name a clone would need to run this
    # machine's delivery; a tracked file holding it is a leak on its way out. Asked for the whole
    # name: this repository's own sources spell the prefix.
    root = _attached(tmp_path)
    name = f"stayfixed-delivery-{_id(root)}"
    (root / "notes.md").write_text(f"enabled: overlay-x@{name}\n", encoding="utf-8")
    (root / "prefix.md").write_text("stayfixed-delivery-<id>\n", encoding="utf-8")
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
    from stayfixed.attach import exclude

    def unanswered(root: Path, relatives: object) -> tuple[str, ...]:
        raise Refusal(exclude.UNANSWERED)

    root = _attached(tmp_path)
    monkeypatch.setattr(exclude, "tracked", unanswered)
    row = _delivered_row(tmp_path, root)
    assert (row.status, row.detail) == (WARN, _attached_detail(attach_doctor.PLACED_UNASKED))


def _ledger_field(root: Path, **fields: object) -> None:
    recorded = json.loads((root / LEDGER).read_text(encoding="utf-8"))
    (root / LEDGER).write_text(json.dumps({**recorded, **fields}), encoding="utf-8")


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
        "run `stayfixed attach --check`, which says why",
    )


def test_a_launcher_the_path_scoped_rules_run_through_that_is_gone_warns(tmp_path: Path) -> None:
    # The path-scoped rules' entry runs `hook PostToolUse` through the launcher that ran `attach`,
    # by its absolute path; the render keeps it, so a stayfixed moved or uninstalled since leaves
    # those rules undelivered. The digest is taken with the launcher the render holds, so the
    # report reads no drift for a launcher of its own.
    root = _attached(tmp_path)
    overlay = tmp_path / "overlay"
    rules = overlay / COMMON_CLAUDE / "rules"
    rules.mkdir()
    (rules / "scoped.md").write_text("---\npaths: src/**\n---\nA rule.\n", encoding="utf-8")
    gone = tmp_path / "gone" / "run-hook.sh"
    command = f'"{gone}" hook PostToolUse'
    rendered = render_write(_id(root), read_parts(overlay, "p", command=command))
    _ledger_field(root, render={"digest": rendered.digest})
    assert _delivered_row(tmp_path, root) == Check(
        "attached",
        WARN,
        _attached_detail(attach_doctor.LAUNCHER_GONE.format(path=quoted(str(gone)))),
        f"{RERUN} from the stayfixed you run now, which renders the entry through it",
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
    from stayfixed.attach.write import attach
    from tests.attach.test_detach import _bound

    root, store, machine = _bound(tmp_path)
    side = tmp_path / "side"
    _git(root, "worktree", "add", "-q", str(side), "-b", "side")
    attach(root, store=store, machine=machine, runner=Recorder())
    for checkout in (root, side):
        rows = doctor_checks.run_checks(
            checkout, home=None, machine=machine, runner=Recorder(), env=_env(tmp_path)
        )
        row = _by_name(rows, "attached")
        assert (row.status, row.detail) == (
            OK,
            "attached; the delivery is in place; autoMemoryDirectory points the harness at the "
            "composed store; the binding is bound",
        ), checkout


def _tagged(tmp_path: Path, *tags: str) -> Path:
    """The overlay's record of project `p` listing `tags`, each with a `groups/<tag>/` directory;
    the overlay's root."""
    overlay = tmp_path / "overlay"
    record = overlay / PROJECTS / "p" / PROJECT_RECORD
    listed = ", ".join(f'"{tag}"' for tag in tags)
    record.write_text(record.read_text(encoding="utf-8") + f"tags = [{listed}]\n", "utf-8")
    for tag in tags:
        (overlay / "groups" / tag).mkdir(parents=True)
    return overlay


def _tag_file(overlay: Path, tag: str, relative: str, text: str = "x\n") -> None:
    path = overlay / "groups" / tag / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_two_tags_holding_one_rule_name_is_a_warning_naming_both_and_the_winner(
    tmp_path: Path,
) -> None:
    root = _attached(tmp_path)
    overlay = _tagged(tmp_path, "a", "b")
    for tag in ("a", "b"):
        _tag_file(overlay, tag, "claude/rules/x.md")
    clause = "the rule x.md is held by the tags a, b: the later, b, wins"
    assert _delivered_row(tmp_path, root) == Check(
        "attached", WARN, _attached_detail(clause), attach_doctor.TAGS_REMEDY
    )


def test_two_tags_setting_one_key_is_a_warning(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    overlay = _tagged(tmp_path, "a", "b")
    for tag in ("a", "b"):
        _tag_file(overlay, tag, "stayfixed.toml", '[memory]\nmode = "overlay"\n')
    clause = "the setting memory.mode is held by the tags a, b: the later, b, wins"
    assert _delivered_row(tmp_path, root) == Check(
        "attached", WARN, _attached_detail(clause), attach_doctor.TAGS_REMEDY
    )


def test_a_listed_tag_with_no_directory_is_a_warning(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    _tagged(tmp_path, "a")
    shutil.rmtree(tmp_path / "overlay" / "groups" / "a")
    row = _delivered_row(tmp_path, root)
    assert row.status == WARN and row.remedy == attach_doctor.TAGS_REMEDY
    assert "the tag a has no directory groups/a; it is skipped" in row.detail


def test_doctor_names_a_project_memory_directory_in_the_tag_namespace(tmp_path: Path) -> None:
    # `tag-` is a tag's link name in the composed store, so the project's own directory of that
    # name is not linked: the warning names it, in the tags finding.
    root = _attached(tmp_path)
    memory = tmp_path / "overlay" / PROJECTS / "p" / "memory"
    (memory / "tag-a").mkdir(parents=True)
    (memory / "tag-file").write_text("not a directory\n", encoding="utf-8")
    row = _delivered_row(tmp_path, root)
    assert row.status == WARN and row.remedy == attach_doctor.TAGS_REMEDY
    assert attach_doctor.RESERVED_GROUP.format(name="tag-a") in row.detail
    assert "tag-file" not in row.detail


def test_a_tag_warning_never_hides_a_red_finding(tmp_path: Path) -> None:
    root = _attached(tmp_path)
    overlay = _tagged(tmp_path, "a", "b")
    for tag in ("a", "b"):
        _tag_file(overlay, tag, "claude/rules/x.md")
    shutil.rmtree(delivery_directory(_id(root)))
    row = _delivered_row(tmp_path, root)
    assert row.status == RED
    assert attach_doctor.TAGS_REMEDY not in row.remedy
    assert "render directory" in row.detail
