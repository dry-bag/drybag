"""What the `bundles` and `memory` rows in `stayfixed doctor` answer, now that `memory`
contributes them.

Every case runs the whole report through `run_checks`, so the rows are asked the way a user's
`stayfixed doctor` asks them: discovered in this area's `doctor.py`, with the note store resolved
by the lazy value its `register()` creates. The fixtures are the doctor area's own
(`tests/doctor/test_checks.py`), shared rather than respelled.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import stayfixed.memory.answers as answers_module
from stayfixed import fsops
from stayfixed.config.loader import load
from stayfixed.doctor.api import OK, RED, SKIP, WARN, Check
from stayfixed.errors import Refusal
from stayfixed.memory.doctor import NEARLY_FULL
from stayfixed.overlay.api import COMMON_MEMORY
from tests.cli import cli
from tests.doctor.test_checks import (
    _attached,
    _by_name,
    _checks,
    _initialised,
    _machine,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

# A local-only project whose one group leaves the store, with the store's directory in place so
# the resolver reaches the group rather than stopping at a missing directory.
OUTSIDE = """
[stayfixed]
version = "{version}"

[project]
name = "p"

[memory]
mode = "local-only"
groups = ["../outside"]
"""


@pytest.mark.parametrize("how", ["group-outside-the-store", "resolver-raises"])
def test_a_store_that_refuses_skips_the_store_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    # A `stayfixed.toml` is repository-authored, so a `memory.groups` that makes the store refuse
    # is the repository's to write. The two rows that read the store skip on it, as they did
    # when the core resolved the store for them; neither may turn red, because red gates the exit
    # code and a check that "could not run" is not something the repository did wrong.
    #
    # Two cases. Asked about a group that leaves the store, the resolver hands the store over
    # without that group, so the rows read what is left and stay green. The second case is the
    # resolver raising `Refusal` instead, which is what the lazy value's `except` exists for and
    # what no `memory.groups` reaches today, so it is stood in for by replacing the resolver where
    # the lazy value calls it, in `memory.answers`.
    #
    # Mutation (oracle): `mutations/`'s "the delivery rows let a refusing store escape" -> the
    # `Refusal` reaches the guard and both rows are red with `this check could not run: Refusal`.
    root = _initialised(tmp_path, template=OUTSIDE)
    (root / ".stayfixed" / "local" / "memory").mkdir(parents=True)
    if how == "resolver-raises":

        def refuses(*args: object, **kwargs: object) -> None:
            raise Refusal("the store refused")

        monkeypatch.setattr(answers_module, "resolve", refuses)
    rows = {row.name: row for row in _checks(tmp_path, root)}
    assert rows["bundles"].status == (SKIP if how == "resolver-raises" else OK), rows["bundles"]
    assert rows["memory"].status == OK, rows["memory"]
    if how == "resolver-raises":
        assert "the store does not resolve" in rows["memory"].detail
    assert not any(row.status == RED for row in rows.values()), [
        (row.name, row.detail) for row in rows.values() if row.status == RED
    ]


def _note(body: str, *, name: str, startup: int) -> str:
    return (
        f"---\nname: {name}\ndescription: a standing rule\nmetadata:\n"
        f"  type: rule\n  startup: {startup}\n---\n\n{body}"
    )


def _promoted(tmp_path: Path, root: Path) -> None:
    """The owner's `memory promote --changed`: a note is a standing rule only once promoted."""
    code, _, err = cli(root, tmp_path, "memory", "promote", "--changed", machine=_machine(tmp_path))
    assert code == 0, err


def test_a_bundle_that_does_not_fit_its_slots_is_reported(tmp_path: Path) -> None:
    # A bundle whose notes do not fit its slots is the condition that needs a human — raising N
    # edits a shipped file — so doctor reports it. Four standing notes of a whole slot each,
    # against the three `standing-rules` entries `hooks/hooks.json` declares.
    #
    # Promoted, since an unreviewed note is no standing rule, so the standing bundle would be
    # empty and this assertion would pass for having measured nothing.
    root = _attached(tmp_path)
    store = tmp_path / "overlay" / COMMON_MEMORY
    for index in range(4):
        (store / f"note-{index}.md").write_text(
            _note("word " * 2_000, name=f"note-{index}", startup=index + 1), encoding="utf-8"
        )
    _promoted(tmp_path, root)
    check = _by_name(
        _checks(tmp_path, root, machine=_machine(tmp_path)),
        "bundles",
    )
    assert check.status == "red"
    assert "standing-rules" in check.detail


def test_a_bundle_that_fits_is_not_reported(tmp_path: Path) -> None:
    # The vacuity guard for the test above: one short standing rule fits its slots and is
    # nowhere near the platform cap, which is the ordinary installation, and the row stays green.
    root = _attached(tmp_path)
    store = tmp_path / "overlay" / COMMON_MEMORY
    (store / "short.md").write_text(_note("a short rule", name="short", startup=1), "utf-8")
    _promoted(tmp_path, root)
    check = _by_name(
        _checks(tmp_path, root, machine=_machine(tmp_path)),
        "bundles",
    )
    assert check.status == "ok"


def test_a_bundle_whose_largest_part_is_at_the_platform_cap_is_a_warning(tmp_path: Path) -> None:
    # `NEARLY_FULL` appeared in no test at all: the constant, the fraction and the whole `full`
    # arm were dead. It is the warning *before* the red row above — one more sentence in one
    # note and the bundle needs a slot that does not exist, and raising a slot count edits
    # `hooks/hooks.json`, which is a shipped file and a change somebody has to make deliberately.
    #
    # One standing note sized into the band between the threshold and the cap, so this is
    # neither the `over` arm (which would be red) nor the green one. Both are asserted, because
    # "warn" alone would also be produced by a `full` list built from the wrong predicate.
    root = _attached(tmp_path)
    store = tmp_path / "overlay" / COMMON_MEMORY
    cap = load(root, machine=_machine(tmp_path)).native_caps.hook_output_chars
    body = "word " * ((int(cap * NEARLY_FULL) + 600) // 5)
    (store / "big.md").write_text(_note(body, name="big", startup=1), encoding="utf-8")
    _promoted(tmp_path, root)
    check = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "bundles")
    assert check.status == "warn", check.detail
    assert "standing-rules" in check.detail
    assert "at the platform cap" in check.detail


# A project whose `stayfixed.toml` sets no `[memory] mode`: memory is the harness's own.
HARNESS = """
[stayfixed]
version = "{version}"

[project]
name = "p"
"""


def _memory_row(tmp_path: Path, root: Path) -> Check:
    rows = {row.name: row for row in _checks(tmp_path, root)}
    assert "memory" in rows, sorted(rows)
    return rows["memory"]


def test_on_a_default_install_the_memory_row_is_ok_and_names_the_harness(tmp_path: Path) -> None:
    # No layer sets a mode, so memory is the coding agent's own and there is no store: the
    # ordinary state of a fresh install, which is no finding.
    root = _initialised(tmp_path, template=HARNESS)
    row = _memory_row(tmp_path, root)
    assert row.status == OK, row
    assert "mode harness, which no layer sets" in row.detail
    assert "no autoMemoryDirectory is set" in row.detail


def test_a_committed_settings_file_setting_the_pointer_is_named_as_information(
    tmp_path: Path,
) -> None:
    # A repository can point the harness's memory elsewhere through its committed settings file;
    # stayfixed cannot stop that and does not try, so the row names the file, as information, and
    # never the value, which the repository wrote.
    root = _initialised(tmp_path, template=HARNESS)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(
        '{"autoMemoryDirectory": "/somewhere/else\\u001b[2J"}', encoding="utf-8"
    )
    row = _memory_row(tmp_path, root)
    assert row.status == OK, row
    assert "autoMemoryDirectory is set by .claude/settings.json" in row.detail
    assert "somewhere" not in row.detail


def test_store_debris_is_no_row_of_its_own(tmp_path: Path) -> None:
    root = _initialised(tmp_path)
    (root / ".stayfixed" / "local" / "memory" / "developer").mkdir(parents=True)
    names = [row.name for row in _checks(tmp_path, root)]
    assert "memory" in names and "store-debris" not in names


def test_a_note_store_holding_something_that_is_not_a_note_is_reported(tmp_path: Path) -> None:
    # Counted in the `memory` row. The count is stayfixed's own; the file names are not, so they
    # are counted rather than printed and the remedy names the command that lists them. The
    # store's unreviewed notes are counted beside it, as information.
    root = _initialised(tmp_path)
    store = root / ".stayfixed" / "local" / "memory" / "developer"
    store.mkdir(parents=True)
    (store / "kept.md").write_text("---\nname: kept\ndescription: d\n---\n\nbody\n")
    (store / "scratch.txt").write_text("not a note\n", encoding="utf-8")
    check = _memory_row(tmp_path, root)
    assert check.status == "warn"
    assert "1 file(s) in the note store are not notes" in check.detail
    assert "1 unreviewed note(s)" in check.detail
    assert "mode local-only, set by repository" in check.detail
    assert "scratch.txt" not in check.detail


@pytest.mark.parametrize("entries", [3, 4])
def test_a_note_store_past_the_walk_cap_is_one_the_row_cannot_tell_about(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entries: int
) -> None:
    # An `in-repo` store is a tree the repository commits, and the walk listed every entry in it,
    # so a clone committing millions of files there stalled `doctor`. It stops at the walk cap,
    # lowered here to three, and says it could not tell; a store of exactly three entries is read
    # whole. Mutation (oracle): `mutations/`'s "the note store's walk lists every entry" -> `4`.
    monkeypatch.setattr(fsops, "WALK_ENTRIES", 3)
    root = _initialised(tmp_path)
    store = root / ".stayfixed" / "local" / "memory" / "developer"
    store.mkdir(parents=True)
    for index in range(entries):
        (store / f"n{index}.md").write_text("---\nname: n\ndescription: d\n---\n\nbody\n")
    check = _memory_row(tmp_path, root)
    if entries == 3:
        assert check.status == OK
        assert "the note store holds notes and nothing else" in check.detail
    else:
        assert check.status == WARN
        assert (
            "the walk of the note store stopped after 3 entries, so it cannot say whether the "
            "store holds files that are not notes"
        ) in check.detail
        assert check.remedy == "run `stayfixed memory inventory` to see what the store holds"


def test_the_note_store_rows_read_a_bound_checkouts_configuration(tmp_path: Path) -> None:
    # With no `stayfixed.toml` the store resolves through `Context.attach_config`; the walk that
    # counts its unreviewed notes and the `bundles` row read that configuration too.
    from tests.memory.test_commands import BARE_NOTE, _bound_without_file, _composed

    root = _bound_without_file(tmp_path)
    overlay = tmp_path / "overlay"
    record = overlay / "projects" / "widget" / "project.toml"
    record.write_text(record.read_text(encoding="utf-8") + 'tags = ["a"]\n', encoding="utf-8")
    (overlay / "groups" / "a" / "memory").mkdir(parents=True)
    (overlay / "groups" / "a" / "memory" / "t.md").write_text(BARE_NOTE, encoding="utf-8")
    (_composed(root) / "tag-a").symlink_to(overlay / "groups" / "a" / "memory")
    rows = {row.name: row for row in _checks(tmp_path, root, machine=tmp_path / "machine.toml")}
    assert "2 unreviewed note(s)" in rows["memory"].detail
    assert rows["bundles"].status != SKIP
