"""`stayfixed upgrade` and `stayfixed uninstall` through the real parser: flags, exit codes, and
what prints.
"""

from __future__ import annotations

import io
import json
import os
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

import stayfixed
from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.jsonobject import LONG_NUMBER, NESTED
from stayfixed.scaffold import MANIFEST_PATH, Kind, Location, Manifest, Record, digest
from tests import parserlimits
from tests.gitfixture import needs_git
from tests.pathfaults import ROOT_SEARCHES_EVERYTHING, unsearchable
from tests.project.repos import forge_record, initialised, tree
from tests.snapshot import assert_snapshot_unchanged, snapshot

FORGED = "docs/\x1b[31mforged.md"
# The commands every shared case runs through, and the invocations that print a report.
COMMANDS = ["upgrade", "uninstall"]
REPORTS = [("upgrade", "--dry-run"), ("uninstall", "--dry-run"), ("uninstall",)]
UNMATCHED = "note: 1 --force path(s) named no file this run had to judge"


def _run(root: Path, tmp_path: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    """The command's `--json` object. A refusal goes to stderr in text mode (`cli._report`), so
    a test that read stdout alone would pass on an empty string."""
    parser = build_parser(discover_registrars())
    flags = ["--root", str(root), "--machine", str(tmp_path / "absent.toml"), "--json"]
    with redirect_stdout(io.StringIO()) as out:
        code = run([*argv, *flags], parser=parser)
    data: dict[str, Any] = json.loads(out.getvalue())
    return code, data


@needs_git
@pytest.mark.parametrize("command", COMMANDS)
def test_an_uninitialised_repository_exits_two_and_names_what_to_run(
    tmp_path: Path, command: str
) -> None:
    root = tmp_path / "bare"
    root.mkdir()
    code, data = _run(root, tmp_path, command)
    assert code == 2 and "manifest.json is not there" in data["summary"]


@needs_git
def test_a_current_footprint_says_so_and_exits_zero(tmp_path: Path) -> None:
    root = initialised(tmp_path)
    code, data = _run(root, tmp_path, "upgrade", "--dry-run")
    assert code == 0, data["summary"]
    assert data["summary"].splitlines()[0] == "would upgrade:"
    assert "0 to create, 0 to update, 0 to remove" in data["summary"]
    assert {
        "dry_run",
        "moved",
        "scaffold",
        "writes",
        "skipped",
        "orphans",
    } <= set(data)


# Two manifests that are valid JSON past this interpreter's parser, and what the refusal says of
# each: nested deeper than it follows, and an integer longer than it converts (4,300 digits by
# default).
PAST_THE_PARSER = {
    "nested": (parserlimits.NESTED, NESTED),
    "long-number": ('{"format": ' + parserlimits.LONG_NUMBER + "}", LONG_NUMBER),
}


@needs_git
@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("case", sorted(PAST_THE_PARSER))
def test_a_manifest_past_the_parser_is_refused_in_its_own_words(
    tmp_path: Path, case: str, command: str
) -> None:
    # The reader caught both documents and quoted the exception: "is unreadable: Exceeds the limit
    # (4300 digits) for integer string conversion ... use sys.set_int_max_str_digits() to increase
    # the limit", which tells the owner of a committed ledger to change their interpreter, and
    # for the nested one the parser's report of its own stack. The refusal now says what the file
    # holds, in the sentence shape the reader's other refusals have, and quotes no interpreter.
    # Mutation (oracle): `mutations/`'s "the manifest reader quotes the parser's exception for a
    # document past its reach" -> every case reddens.

    root = initialised(tmp_path)
    document, clause = PAST_THE_PARSER[case]
    (root / MANIFEST_PATH).write_text(document, encoding="utf-8")
    code, data = _run(root, tmp_path, command, "--dry-run")
    assert code == 2
    assert data["summary"] == f"refused: {MANIFEST_PATH} {clause}"


@needs_git
@ROOT_SEARCHES_EVERYTHING
@pytest.mark.parametrize(
    "argv", [("init", "--yes"), ("upgrade",), ("uninstall",)], ids=["init", "upgrade", "uninstall"]
)
@pytest.mark.parametrize("link", [".stayfixed", MANIFEST_PATH.as_posix()])
def test_a_committed_link_into_a_directory_nobody_may_search_is_refused_in_words(
    tmp_path: Path, link: str, argv: tuple[str, ...]
) -> None:
    # A clone commits a link as text and needs no mode: an absolute target under a directory its
    # user cannot search makes every path through the link a fault to ask about. The manifest was
    # asked for with a bare existence check, which met that fault, and all three commands ended in
    # `internal error: PermissionError` with the manifest's absolute path. The manifest is asked
    # through `contained` now, as reading it always was, so the link is refused by name.
    # Mutation (oracle): `mutations/`'s "init, upgrade and uninstall ask for the manifest past
    # contained" -> every case ends in an internal error again.
    root = initialised(tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir()
    if link == ".stayfixed":
        shutil.rmtree(root / link)
    else:
        (root / link).unlink()
    (root / link).symlink_to(locked / "x")
    with unsearchable(locked):
        code, data = _run(root, tmp_path, *argv)
    assert code == 2
    assert (
        data["summary"] == f"refused: {str(MANIFEST_PATH)!r} passes through a symlink at {link!r}"
    )


@needs_git
@ROOT_SEARCHES_EVERYTHING
def test_uninstall_refuses_a_local_directory_linked_where_nobody_may_search_by_name(
    tmp_path: Path,
) -> None:
    # The same fault one directory down: whether `attach`'s ledger is there was asked of the path
    # whole, through the link. Mutation (oracle): `mutations/`'s "uninstall asks for attach's
    # ledger past contained".
    root = initialised(tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir()
    shutil.rmtree(root / ".stayfixed" / "local", ignore_errors=True)
    (root / ".stayfixed" / "local").symlink_to(locked / "x")
    with unsearchable(locked):
        code, data = _run(root, tmp_path, "uninstall")
    assert code == 2
    assert data["summary"] == (
        "refused: '.stayfixed/local/attach.json' passes through a symlink at '.stayfixed/local'"
    )


@needs_git
@ROOT_SEARCHES_EVERYTHING
@pytest.mark.parametrize("left", [".stayfixed/assessment.json", ".stayfixed/local/artifacts.json"])
def test_uninstall_removes_a_ledger_file_linked_where_nobody_may_search_as_a_link(
    tmp_path: Path, left: str
) -> None:
    # A file of stayfixed's own ledger that is a link is removed as one. Whether it was a directory
    # to leave was asked first, through the link, which met the fault past it: an internal error
    # after every other file had gone. Mutation (oracle): `mutations/`'s "uninstall follows a link
    # where its ledger belongs to ask whether it is a directory".
    root = initialised(tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir()
    (root / left).parent.mkdir(parents=True, exist_ok=True)
    (root / left).unlink(missing_ok=True)
    (root / left).symlink_to(locked / "x")
    with unsearchable(locked):
        code, data = _run(root, tmp_path, "uninstall")
    assert code == 0, data["summary"]
    assert not os.path.lexists(root / left)


@needs_git
@pytest.mark.parametrize("argv", REPORTS)
def test_a_recorded_target_outside_the_path_grammar_prints_as_its_artifact_id(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    # `_relocation` answers a forged target with `skip_modified` at that target, and the run goes
    # on: exit 0, the file at the forged path untouched, and nothing of the target printed.
    root = initialised(tmp_path)
    # A committed manifest can carry any `target`. The engine reports a left-behind file at
    # the recorded target, and a report prints targets; only one the path grammar accepts
    # may print.
    forge_record(root, "roadmap", target=FORGED)
    code, data = _run(root, tmp_path, *argv)
    printed = json.dumps(data)
    assert code == 0, data["summary"]
    assert "\\u001b" not in printed and "forged" not in printed
    assert "<roadmap>" in data["summary"]


@needs_git
@pytest.mark.parametrize("command", COMMANDS)
def test_a_force_path_outside_the_root_is_refused_by_rule(tmp_path: Path, command: str) -> None:
    root = initialised(tmp_path)
    code, data = _run(root, tmp_path, command, "--dry-run", "--force", "../elsewhere.md")
    assert code == 2
    assert "elsewhere" not in data["summary"]


@needs_git
def test_a_force_path_that_names_nothing_is_counted(tmp_path: Path) -> None:
    # The roadmap is edited first, so the exact path names an action the run judges and the
    # case-shifted one does not. On an untouched footprint every forced path would be counted,
    # whether or not the comparison worked. Mutation (advisory): count every forced path ->
    # the exact path gains a note and the first assertion reddens.
    root = initialised(tmp_path)
    roadmap = root / "docs" / "roadmap.md"
    roadmap.write_text(roadmap.read_text(encoding="utf-8") + "\nours\n", encoding="utf-8")
    code, data = _run(root, tmp_path, "upgrade", "--dry-run", "--force", "docs/roadmap.md")
    assert code == 0 and UNMATCHED not in data["summary"]
    code, data = _run(root, tmp_path, "upgrade", "--dry-run", "--force", "docs/Roadmap.md")
    assert code == 0
    assert UNMATCHED in data["summary"]


@needs_git
@pytest.mark.parametrize("command", COMMANDS)
def test_a_region_record_this_build_does_not_produce_is_an_orphan_and_its_host_file_stays(
    tmp_path: Path, command: str
) -> None:
    # A retired record is judged against a whole-file stub, which names no region, so a record
    # saying its artifact lived inside a host file (a region, or keyed entries) is never retired
    # that way: forced, the stub would delete the host file and everything a person wrote in it.
    # It is counted as an orphan, by the one rule both commands apply. The kind is read off the
    # committed manifest, and it can only turn a removal into an orphan. Mutation (oracle):
    # `mutations/`'s "a region record this build does not produce is retired as a whole file" -> the
    # forced run removes the host file, and the first assertion reddens for both commands.
    root = initialised(tmp_path)
    target = "docs/stayfixed/rules/python.md"
    host = root / target
    host.parent.mkdir(parents=True, exist_ok=True)
    host.write_text("Our own rules.\n", encoding="utf-8")
    # The digest a region record carries is its body's, never the host file's.
    record = Record(
        id="profile-rules",
        kind=Kind.MANAGED_REGION,
        location=Location.REPO,
        target=target,
        template="profile/python/rules.md",
        version=stayfixed.__version__,
        sha256=digest("a region body"),
    )
    Manifest.read(root).with_record(record).write(root)
    code, data = _run(root, tmp_path, command, "--force", target)
    assert host.is_file() and host.read_text(encoding="utf-8") == "Our own rules.\n"
    assert code == 0 and data["orphans"] == 1, data["summary"]


@needs_git
def test_uninstall_lists_what_it_leaves_and_exits_zero(tmp_path: Path) -> None:
    root = initialised(tmp_path)
    (root / "docs" / "roadmap.md").write_text("ours\n", encoding="utf-8")
    code, data = _run(root, tmp_path, "uninstall")
    assert code == 0, data["summary"]
    assert data["left"] == ["docs/roadmap.md"]
    assert {"dry_run", "scaffold", "once", "left", "orphans", "note", "kept_locally"} <= set(data)
    assert data["summary"].splitlines()[0] == "uninstalled:"
    assert data["kept_config"] is False  # `init` wrote this one, and it goes


@needs_git
@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "real"])
def test_a_file_a_later_pass_deletes_is_never_reported_left_in_place(
    tmp_path: Path, dry_run: bool
) -> None:
    # stayfixed's region taken out of `AGENTS.md` by hand: the footprint pass lists the file
    # `skip_modified`, and the write-once pass then removes the untouched skeleton. The file was
    # counted as "left in place, yours now" after it was deleted. Mutation (advisory): drop the
    # `not in gone` filter -> `left` names `AGENTS.md` and the first assertion reddens.
    root = initialised(tmp_path)
    agents = root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    begin, end = "<!-- stayfixed:harness:begin -->", "<!-- stayfixed:harness:end -->\n"
    agents.write_text(text[: text.index(begin)] + text[text.index(end) + len(end) :])
    code, data = _run(root, tmp_path, "uninstall", *(("--dry-run",) if dry_run else ()))
    assert code == 0, data["summary"]
    assert data["left"] == [] and "left in place" not in data["summary"]
    assert "skip_modified  AGENTS.md  (retired and hand-edited)" in data["scaffold"]
    assert agents.exists() is dry_run


# One removal from each pass: the footprint's body, the write-once pass, the ignore pass, and
# `stayfixed.toml` itself, which goes last of all.
FAILING = ["docs/roadmap.md", "CLAUDE.md", ".gitignore", "stayfixed.toml"]


@needs_git
@pytest.mark.parametrize("failing", FAILING)
def test_a_removal_that_fails_part_way_exits_2_keeps_what_was_done_and_a_rerun_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """Exit 2 is not "nothing was written", and it is never a dead end. Wherever a removal fails,
    what ran stays applied and recorded, `stayfixed.toml` and the manifest are still there, and
    the next run finishes to the state an uninterrupted run leaves. The failure is the one the
    engine translates: an `OSError` from the removal, which `_remove` turns into a refusal.

    Mutation (declared): `stayfixed.toml` removed in the write-once pass again -> a failure on
    `CLAUDE.md` or `.gitignore` leaves no configuration, the next run keeps what the manifest
    still records and drops the manifest, and the last assertion reddens.
    """
    import stayfixed.scaffold.engine as engine
    from stayfixed import fsops

    root = initialised(tmp_path)
    real = fsops.remove_within

    def fails(where: Path, target: str) -> None:
        if target == failing:
            raise PermissionError(13, "Permission denied")
        real(where, target)

    monkeypatch.setattr(engine, "remove_within", fails)
    code, data = _run(root, tmp_path, "uninstall")
    assert code == 2, data
    assert (root / failing).is_file()
    # Read now and asserted last, so the converged end state is what a wrong order reddens.
    resumable = (root / "stayfixed.toml").is_file() and (
        root / ".stayfixed" / "manifest.json"
    ).is_file()
    monkeypatch.setattr(engine, "remove_within", real)
    code, data = _run(root, tmp_path, "uninstall")
    assert code == 0, data
    # Every directory the first run emptied goes too: each pass prunes above what it removed in a
    # `finally`, so the pass that stopped still emptied the directories of the files it took.
    # Mutation (oracle): `mutations/`'s "a pass that stops part-way leaves the directories it
    # emptied" -> the `docs/roadmap.md` case keeps `docs/`.
    assert tree(root) == {"README.md"}, sorted(tree(root))
    assert resumable


@needs_git
@pytest.mark.parametrize(
    ("command", "refusing"),
    [("upgrade", "scaffold"), ("uninstall", "scaffold"), ("uninstall", "once")],
    ids=["upgrade-footprint", "uninstall-footprint", "uninstall-once"],
)
def test_a_plan_that_refuses_exits_one_heads_the_report_refused_and_changes_nothing(
    tmp_path: Path, command: str, refusing: str
) -> None:
    """Each half of each report's `refused`, which decides both whether anything is written and
    the heading and exit code the command prints. The footprint pass refuses a region whose
    begin marker is gone; the write-once pass refuses a `CLAUDE.md` that became a symlink.

    Mutations (oracle): `mutations/`'s "upgrade's refusal reads no plan", "uninstall's refusal reads
    only the write-once plan" and "uninstall's refusal reads only the footprint plan" -> the run
    goes on to `apply`, whose own backstop refuses the refused plan: exit 2 with the engine's
    message and no report, and in the `uninstall-once` case only after the footprint pass has
    removed its files. The matching case reddens.
    """
    root = initialised(tmp_path)
    if refusing == "scaffold":
        agents = root / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8").replace("<!-- stayfixed:harness:begin -->\n", ""),
            encoding="utf-8",
        )
    else:
        (tmp_path / "elsewhere.md").write_text("theirs\n", encoding="utf-8")
        (root / "CLAUDE.md").unlink()
        (root / "CLAUDE.md").symlink_to(tmp_path / "elsewhere.md")
    before = snapshot(root)
    code, data = _run(root, tmp_path, command)
    assert code == 1, data["summary"]
    verb = "written" if command == "upgrade" else "removed"
    assert data["summary"].startswith(f"refused, and nothing was {verb}:")
    assert "REFUSED" in data[refusing]
    assert_snapshot_unchanged(root, before)
