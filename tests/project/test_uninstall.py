"""`stayfixed uninstall`: what stayfixed wrote goes, what a person wrote stays and is named."""

from __future__ import annotations

import contextlib
import errno
import json
import os
import re
from dataclasses import replace
from pathlib import Path

import pytest

import stayfixed
from stayfixed.attach.api import detach
from stayfixed.config.loader import CONFIG_FILE
from stayfixed.errors import Refusal
from stayfixed.project.commands import DETACHED, DETACHED_DRY
from stayfixed.project.footprint import LOCAL_ROOT_ONLY, ROOT_ONLY
from stayfixed.project.init import init
from stayfixed.project.templates import (
    CONFIG_ARTIFACT,
    IGNORE_ARTIFACT,
    ONE_FILE,
    OWN_NAME,
)
from stayfixed.project.uninstall import (
    DELETED_CONFIG,
    KEPT_AFTER,
    KEPT_LOCALLY,
    NO_CONFIG,
    NOTHING,
    ORDER_NOTE,
    UninstallReport,
    uninstall,
)
from stayfixed.project.upgrade import upgrade
from stayfixed.scaffold import (
    LOCAL_DIGESTS,
    MANIFEST_PATH,
    Kind,
    LocalDigests,
    Location,
    Manifest,
    Record,
    Verb,
    digest,
)
from tests.attach.test_detach import RULE, _attach, _bound, _grant, _render_of
from tests.cli import cli
from tests.gitfixture import needs_git, run_git
from tests.project.repos import BEFORE, DOCUMENT, initialised, repository, tree
from tests.runners import Recorder
from tests.snapshot import assert_snapshot_unchanged, snapshot

LOCAL_ROADMAP = f'''[stayfixed]
version = "{stayfixed.__version__}"

[project]
name = "widget"

[artifacts]
local = ["roadmap"]
'''


def _uninstall(
    root: Path, tmp_path: Path, *, dry_run: bool = False, force: tuple[str, ...] = ()
) -> UninstallReport:
    return uninstall(
        root, machine=tmp_path / "absent.toml", dry_run=dry_run, force=force, runner=Recorder()
    )


@needs_git
def test_an_untouched_footprint_leaves_only_what_was_there_before(tmp_path: Path) -> None:
    root = initialised(tmp_path)
    report = _uninstall(root, tmp_path)
    assert tree(root) == {"README.md"}
    assert (root / "README.md").read_text(encoding="utf-8") == BEFORE
    # The report is what ran: the skeleton judged after its region left, and removed, where the
    # plan made before the first pass called it edited. Mutation (advisory): return the plans
    # made before any write -> `AGENTS.md` is reported left in place, and this reddens.
    assert [a.verb for a in report.once.actions if a.artifact_id == "agents-skeleton"] == [
        Verb.REMOVE
    ]
    assert not [
        a for a in (*report.footprint.actions, *report.once.actions) if a.verb is Verb.SKIP_MODIFIED
    ]


@needs_git
def test_an_edited_file_stays_and_is_listed_and_force_takes_it(tmp_path: Path) -> None:
    root = initialised(tmp_path)
    roadmap = root / "docs" / "roadmap.md"
    roadmap.write_text(roadmap.read_text(encoding="utf-8") + "\nours\n", encoding="utf-8")
    report = _uninstall(root, tmp_path)
    left = {a.target for a in report.footprint.actions if a.verb is Verb.SKIP_MODIFIED}
    assert left == {"docs/roadmap.md"}
    assert roadmap.is_file() and not (root / MANIFEST_PATH).exists()


@needs_git
def test_force_removes_the_edited_file_it_names(tmp_path: Path) -> None:
    root = initialised(tmp_path)
    roadmap = root / "docs" / "roadmap.md"
    roadmap.write_text("ours\n", encoding="utf-8")
    _uninstall(root, tmp_path, force=("docs/roadmap.md",))
    assert not roadmap.exists()


@needs_git
def test_text_a_person_added_around_the_region_keeps_agents_md(tmp_path: Path) -> None:
    root = initialised(tmp_path)
    agents = root / "AGENTS.md"
    agents.write_text("Our preface.\n" + agents.read_text(encoding="utf-8"), encoding="utf-8")
    _uninstall(root, tmp_path)
    text = agents.read_text(encoding="utf-8")
    assert text.startswith("Our preface.\n") and "stayfixed:harness" not in text


@needs_git
def test_forcing_agents_md_takes_the_region_out_and_keeps_the_skeleton_s_prose(
    tmp_path: Path,
) -> None:
    # `AGENTS.md` is two artifacts: stayfixed's region, and the skeleton a person writes into.
    # Forcing the path is the only way to take an edited region out, and it must not reach the
    # write-once pass, where it would delete the skeleton and every line written into it.
    root = initialised(tmp_path)
    agents = root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    edited = text.replace(
        "<!-- stayfixed:harness:begin -->\n", "<!-- stayfixed:harness:begin -->\nOur line.\n"
    )
    agents.write_text("Our preface.\n" + edited, encoding="utf-8")
    _uninstall(root, tmp_path, force=("AGENTS.md",))
    kept = agents.read_text(encoding="utf-8")
    assert kept.startswith("Our preface.\n") and "stayfixed:harness" not in kept


@needs_git
@pytest.mark.parametrize("forced", [False, True], ids=["plain", "region-forced"])
def test_a_person_s_lines_in_gitignore_stay_when_the_ignore_region_goes(
    tmp_path: Path, forced: bool
) -> None:
    # A region's host file is somebody's: what leaves is the region, never the file around it,
    # and forcing overrides the hand-edit verdict and not the payload. With the region edited
    # the plain run leaves it, markers and all, and the forced run takes the region alone.
    # Mutation (advisory): `_removal_payload` answers `None` for a managed region -> the host
    # file is deleted with the person's lines in it, and the first assertion reddens.
    root = initialised(tmp_path)
    ignore = root / ".gitignore"
    ours = "# ours\nbuild/\n"
    text = ignore.read_text(encoding="utf-8")
    edited = text.replace(".stayfixed/assessment.json", ".stayfixed/assessment.json\nextra/")
    ignore.write_text(ours + edited, encoding="utf-8")
    _uninstall(root, tmp_path, force=(".gitignore",) if forced else ())
    kept = ignore.read_text(encoding="utf-8")
    assert kept.startswith(ours)
    assert ("stayfixed:ignore" in kept) is not forced


@needs_git
def test_a_dry_run_writes_nothing_and_says_the_skeleton_is_judged_after_its_region(
    tmp_path: Path,
) -> None:
    # Mutation (oracle, advisory): set the note on the real run too -> the last assertion
    # reddens.
    root = initialised(tmp_path)
    before = snapshot(root)
    report = _uninstall(root, tmp_path, dry_run=True)
    assert_snapshot_unchanged(root, before)
    assert report.note == ORDER_NOTE
    real = _uninstall(root, tmp_path)
    assert real.note == "" and not (root / "AGENTS.md").exists()


@needs_git
def test_an_attached_repository_is_detached_and_then_uninstalled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `uninstall` used to refuse an attached repository and send the person to `detach` first;
    # the one remedy it named is now a step it takes. A real `init` scaffold and a real attach
    # that merged a rule and a hook entry: the dry run says it would detach first and writes
    # nothing, and the real run withdraws what attach placed, its ledger included, and then takes
    # the scaffold back. The plugin commands go to a recorder, never to a real `claude`.
    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda: Recorder())
    root, store, machine = _bound(tmp_path)
    init(root, machine=machine, yes=True, dry_run=False)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "scaffold")
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _attach(root, store, machine)
    before = snapshot(root)
    code, printed, _ = cli(root, tmp_path, "uninstall", "--dry-run", machine=machine)
    assert code == 0, printed
    assert f"note: {DETACHED_DRY}\n" in printed
    assert_snapshot_unchanged(root, before)
    code, printed, _ = cli(root, tmp_path, "uninstall", machine=machine)
    assert code == 0, printed
    assert f"note: {DETACHED}\n" in printed
    assert not (root / MANIFEST_PATH).exists()
    assert not (root / ".stayfixed" / "local" / "attach.json").exists()
    # The `stayfixed.toml` the repository had before `init` is its own, and is kept.
    assert tree(root) == {"stayfixed.toml"}


@needs_git
@pytest.mark.parametrize("dry_run", [False, True], ids=["real", "dry-run"])
def test_a_refused_uninstall_of_an_attached_repository_says_nothing_of_detaching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    # A plan that refuses returns the report before `detach` runs, and the report still said the
    # repository was detached, so the person read "uninstall ran `stayfixed detach` first" above a
    # REFUSED section while the overlay's plugin and rules were all still in place; a dry run
    # that refuses said it would detach, which the real run would not either. The footprint pass
    # refuses a region whose begin marker is gone. Mutation (oracle): `mutations/`'s "a refused
    # uninstall reports the repository detached" -> the DETACHED line prints and this reddens.
    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda: Recorder())
    root, store, machine = _bound(tmp_path)
    init(root, machine=machine, yes=True, dry_run=False)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "scaffold")
    _attach(root, store, machine)
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace("<!-- stayfixed:harness:begin -->\n", ""),
        encoding="utf-8",
    )
    before = snapshot(root)
    flags = ("--dry-run",) if dry_run else ()
    code, printed, _ = cli(root, tmp_path, "uninstall", *flags, machine=machine)
    assert code == 1, printed
    verb = "would be" if dry_run else "was"
    assert printed.startswith(f"refused, and nothing {verb} removed:"), printed
    assert DETACHED not in printed and DETACHED_DRY not in printed, printed
    assert_snapshot_unchanged(root, before)
    assert (root / ".stayfixed" / "local" / "attach.json").is_file()
    assert _render_of(root)[1].exists()


@needs_git
def test_a_linked_worktree_of_an_attached_repository_detaches_the_main_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `attach` keeps its ledger in the main checkout whichever worktree it ran from, so a worktree
    # holds none, and `uninstall` there used to take the worktree's scaffold and leave the main
    # checkout's delivery recorded by nothing the next commit would explain. It reads the main
    # checkout's ledger and detaches that.
    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda: Recorder())
    root, store, machine = _bound(tmp_path)
    init(root, machine=machine, yes=True, dry_run=False)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "scaffold")
    side = tmp_path / "side"
    run_git(root, "worktree", "add", "-q", str(side))
    _attach(root, store, machine)
    ledger = root / ".stayfixed" / "local" / "attach.json"
    assert ledger.is_file()
    code, printed, _ = cli(side, tmp_path, "uninstall", machine=machine)
    assert code == 0, printed
    assert f"note: {DETACHED}\n" in printed
    assert not ledger.exists() and not (side / MANIFEST_PATH).exists()


@needs_git
@pytest.mark.parametrize("dry_run", [False, True], ids=["real", "dry-run"])
def test_an_attached_repository_without_its_stayfixed_toml_is_detached_before_its_ledger_goes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    # A `stayfixed.toml` the project wrote before `init` is recorded nowhere, so once it is gone
    # only the scaffold's ledger goes. On an attached repository `attach`'s ledger, the one record
    # of what it placed, is under `.stayfixed/local/` too, and the `.stayfixed/` the ledger's
    # removal prunes would take the attachment's record while its plugin and rules stayed. The
    # real run detaches first; the dry run writes nothing, the attachment included, and says it
    # would detach. Mutations (oracle): `mutations/`'s "uninstall without stayfixed.toml leaves the
    # repository attached" -> `real`; "an uninstall dry run without stayfixed.toml detaches" ->
    # `dry-run`.
    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda: Recorder())
    root, store, machine = _bound(tmp_path)
    init(root, machine=machine, yes=True, dry_run=False)
    assert CONFIG_ARTIFACT not in Manifest.read(root).records
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _attach(root, store, machine)
    (root / CONFIG_FILE).unlink()
    ledger = root / ".stayfixed" / "local" / "attach.json"
    render = _render_of(root)[1]
    before = snapshot(root)
    flags = ("--dry-run",) if dry_run else ()
    code, printed, _ = cli(root, tmp_path, "uninstall", *flags, machine=machine)
    assert code == 0, printed
    if dry_run:
        assert f"note: {DETACHED_DRY}\n" in printed
        assert_snapshot_unchanged(root, before)
        assert ledger.is_file() and render.is_dir()
        return
    assert f"note: {DETACHED}\n" in printed
    assert not ledger.exists() and not render.exists()
    assert not (root / MANIFEST_PATH).exists()


def _forge_a_ledger(root: Path) -> None:
    """A ledger a clone commits, naming the owner's untracked rule file, an allow rule and a
    settings key, and the owner's own copies of all three."""
    ledger = {
        "store": "",
        "allow": ["Bash(npm test)"],
        "entries": {},
        "rules": [".codex/rules/team.rules"],
        "settings_keys": ["autoMemoryDirectory"],
        "directories": [],
    }
    (root / ".stayfixed" / "local").mkdir(parents=True, exist_ok=True)
    (root / ".stayfixed" / "local" / "attach.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / ".codex" / "rules").mkdir(parents=True, exist_ok=True)
    (root / ".codex" / "rules" / "team.rules").write_text("# the owner's\n", encoding="utf-8")
    (root / ".claude").mkdir(exist_ok=True)
    settings = {"permissions": {"allow": ["Bash(npm test)"]}, "autoMemoryDirectory": "/notes"}
    (root / ".claude" / "settings.local.json").write_text(json.dumps(settings), encoding="utf-8")


@needs_git
def test_a_ledger_a_clone_committed_detaches_nothing(tmp_path: Path) -> None:
    # Whether a repository is attached is the binding id's to say, in the git common directory,
    # which no commit reaches, and never the ledger's, which a clone can commit with `git add -f`.
    # Read off the ledger, `uninstall` in a never-attached clone ran `detach`, which deleted the
    # owner's untracked rule file and took their allow rule and `autoMemoryDirectory` out of their
    # settings. The committed ledger is a file under `.stayfixed/local/` the run would not remove,
    # so the run refuses with nothing touched. Mutation (oracle): `mutations/`'s "uninstall takes a
    # committed ledger for an attachment" -> the owner's files go and this reddens.
    root = initialised(tmp_path)
    _forge_a_ledger(root)
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _uninstall(root, tmp_path)
    assert str(refused.value) == KEPT_LOCALLY.format(count=1)
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_ledger_committed_after_a_detach_detaches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `detach` keeps the binding id, so a checkout attached once and detached since still carries
    # one: read as "attached", the id let a ledger a pull request committed later have `uninstall`
    # run `detach` over the owner's untracked rule file and settings again. Attached is the
    # render `attach` writes and `detach` removes, outside the work tree.
    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda: Recorder())
    root, store, machine = _bound(tmp_path)
    init(root, machine=machine, yes=True, dry_run=False)
    _attach(root, store, machine)
    detach(root, runner=Recorder())
    _forge_a_ledger(root)
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        uninstall(root, machine=machine, dry_run=False, force=(), runner=Recorder())
    assert str(refused.value) == KEPT_LOCALLY.format(count=1)
    assert_snapshot_unchanged(root, before)


@needs_git
@pytest.mark.parametrize("stopped", ["detach", "attach"])
def test_a_ledger_left_without_its_render_is_finished_by_detach_and_then_uninstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped: str
) -> None:
    # A `detach` that stopped after its render went, or an `attach` that stopped after its ledger
    # and before its render, leaves a ledger with no render. Attachment is the render, so that
    # ledger is a file this run would not remove, as a forged one is, and the documents said a
    # second `uninstall` finishes, where it refuses. What they say now: `stayfixed detach`
    # finishes from the ledger, and `uninstall` then runs to its end.
    import stayfixed.attach.write as write
    from stayfixed.attach import exclude

    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda: Recorder())
    root, store, machine = _bound(tmp_path)
    init(root, machine=machine, yes=True, dry_run=False)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "scaffold")
    _grant(store.parents[2], allow=(RULE,), hooks=True)

    def full_disk(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    if stopped == "attach":
        monkeypatch.setattr(write, "write_render", full_disk)
        with pytest.raises(OSError):
            _attach(root, store, machine)
    else:
        _attach(root, store, machine)
        monkeypatch.setattr(exclude, "write", full_disk)
        with pytest.raises(OSError):
            uninstall(root, machine=machine, dry_run=False, force=(), runner=Recorder())
    monkeypatch.undo()
    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda: Recorder())
    ledger = root / ".stayfixed" / "local" / "attach.json"
    assert ledger.is_file() and not _render_of(root)[1].exists()
    with pytest.raises(Refusal) as refused:
        uninstall(root, machine=machine, dry_run=False, force=(), runner=Recorder())
    assert str(refused.value) == KEPT_LOCALLY.format(count=1)
    block = root / ".git" / "info" / "exclude"
    assert "stayfixed attach" in block.read_text("utf-8")
    detach(root, runner=Recorder())
    assert not ledger.exists() and "stayfixed attach" not in block.read_text("utf-8")
    uninstall(root, machine=machine, dry_run=False, force=(), runner=Recorder())
    assert not (root / MANIFEST_PATH).exists()


@needs_git
def test_notes_kept_out_of_git_refuse_the_run_that_would_expose_them(tmp_path: Path) -> None:
    # The local-only store is the preset's default, and the ignore region this run removes is
    # all that keeps it out of git. The count is reported by the dry run and refuses the real
    # one before anything is written; neither names a note. The snapshot is compared whatever the
    # refusal says, so a run that starts removing and refuses later fails on the writes.
    root = initialised(tmp_path)
    note = root / ".stayfixed" / "local" / "memory" / "developer" / "private-note.md"
    note.parent.mkdir(parents=True)
    note.write_text("a private note\n", encoding="utf-8")
    before = snapshot(root)
    assert _uninstall(root, tmp_path, dry_run=True).kept_locally == 1
    with pytest.raises(Refusal) as refused:
        _uninstall(root, tmp_path)
    assert_snapshot_unchanged(root, before)
    assert str(refused.value) == KEPT_LOCALLY.format(count=1)
    assert "private-note" not in str(refused.value)


@needs_git
def test_an_artifact_kept_out_of_git_goes_with_the_rest(tmp_path: Path) -> None:
    root = initialised(tmp_path, document=LOCAL_ROADMAP)
    assert (root / ".stayfixed" / "local" / "artifacts" / "docs" / "roadmap.md").is_file()
    _uninstall(root, tmp_path)
    assert not (root / ".stayfixed").exists()


@needs_git
def test_an_edited_artifact_kept_out_of_git_refuses_until_it_is_forced(tmp_path: Path) -> None:
    root = initialised(tmp_path, document=LOCAL_ROADMAP)
    local = root / ".stayfixed" / "local" / "artifacts" / "docs" / "roadmap.md"
    local.write_text("private plans\n", encoding="utf-8")
    dry = _uninstall(root, tmp_path, dry_run=True)
    assert [a.verb for a in dry.footprint.actions if a.artifact_id == "roadmap"] == [
        Verb.SKIP_MODIFIED
    ]
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _uninstall(root, tmp_path)
    assert_snapshot_unchanged(root, before)
    assert str(refused.value) == KEPT_LOCALLY.format(count=1)
    _uninstall(root, tmp_path, force=(".stayfixed/local/artifacts/docs/roadmap.md",))
    assert not (root / ".stayfixed").exists()


LOCAL_AGENTS = ".stayfixed/local/artifacts/AGENTS.md"
AGENTS_PLACEMENTS = {
    "committed": (),
    "region-local": ("agents-md",),
    "skeleton-local": ("agents-skeleton",),
    "both-local": ("agents-md", "agents-skeleton"),
}


def _agents_local(local: tuple[str, ...]) -> str:
    return LOCAL_ROADMAP.replace('local = ["roadmap"]', f"local = {json.dumps(list(local))}")


def _ignored(root: Path, path: Path) -> bool:
    # The sealed environment: a global excludes file cannot make a leaked file read as ignored.
    relative = path.relative_to(root).as_posix()
    return run_git(root, "check-ignore", "-q", "--", relative).returncode == 0


@needs_git
@pytest.mark.parametrize("forced", [False, True], ids=["plain", "region-forced"])
@pytest.mark.parametrize("placement", sorted(AGENTS_PLACEMENTS))
def test_a_person_s_line_in_agents_md_survives_every_placement_and_stays_ignored(
    tmp_path: Path, placement: str, forced: bool
) -> None:
    """`AGENTS.md`'s region and its skeleton can each be kept out of git, so the file a person
    writes in may be the committed one, the local one, or both, and `--force` may name the
    region's file. In every combination the person's line survives, and whatever is left under
    `.stayfixed/local/` when the run ends, finished or refused, is still ignored by git.

    Mutations (declared): the force filter compares `Template.target` instead of the engine's
    effective path -> `both-local` with `region-forced` deletes the file; the check after the
    write-once pass dropped -> `both-local` takes the ignore block out over the remainder.
    """
    local = AGENTS_PLACEMENTS[placement]
    root = initialised(tmp_path, document=_agents_local(local))
    region = LOCAL_AGENTS if "agents-md" in local else "AGENTS.md"
    written = [path for path in ("AGENTS.md", LOCAL_AGENTS) if (root / path).is_file()]
    for path in written:
        with (root / path).open("a", encoding="utf-8") as stream:
            stream.write("\nA LINE OF OURS\n")
    with contextlib.suppress(Refusal):
        _uninstall(root, tmp_path, force=(region,) if forced else ())
    for path in written:
        assert "A LINE OF OURS" in (root / path).read_text(encoding="utf-8"), path
    kept = root / ".stayfixed" / "local"
    left = [p for p in kept.rglob("*") if p.is_file()] if kept.is_dir() else []
    assert all(_ignored(root, p) for p in left), left


@needs_git
def test_an_untouched_agents_md_kept_out_of_git_goes_whole(tmp_path: Path) -> None:
    # Region and skeleton share `.stayfixed/local/artifacts/AGENTS.md`. What the region's removal
    # leaves is exactly the skeleton `init` wrote, so the prediction before any write counts the
    # file as going, and it goes. Mutation (advisory): the prediction never credits a remainder
    # -> the run refuses before any write, and this reddens at the call.
    root = initialised(tmp_path, document=_agents_local(("agents-md", "agents-skeleton")))
    assert (root / LOCAL_AGENTS).is_file()
    _uninstall(root, tmp_path)
    # `stayfixed.toml` was written by the test before `init` adopted it, so it is the person's.
    assert tree(root) == {"README.md", "stayfixed.toml"}


@needs_git
def test_a_shared_agents_md_kept_out_of_git_goes_whole_after_its_templates_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The prediction before any write asks the engine's rule of what the region's removal leaves,
    # and that rule reads the ledger: the skeleton `init` wrote is stayfixed's though this build
    # renders another. Judged by the render alone, the run refused before any write over a file
    # nobody touched. Mutation (oracle): `mutations/`'s "the ledger never vouches for bytes
    # stayfixed wrote kept out of git" -> the refusal is raised.
    from stayfixed.project import templates

    root = initialised(tmp_path, document=_agents_local(("agents-md", "agents-skeleton")))
    original = templates.read
    monkeypatch.setattr(templates, "read", lambda name: original(name) + "\nA later line.\n")
    _uninstall(root, tmp_path)
    assert tree(root) == {"README.md", "stayfixed.toml"}


@needs_git
@pytest.mark.parametrize("edit", ["skeleton", "region"])
def test_a_shared_agents_md_kept_out_of_git_that_will_stay_refuses_before_any_write(
    tmp_path: Path, edit: str
) -> None:
    """Region and skeleton both kept out of git share one file. With a person's line in the
    skeleton, the file stays whatever is forced: the region's force never reaches the skeleton.
    With the region edited, it stays unforced. Either way the run knows before it writes, and
    refuses with the remedy that works: move it out. A first draft counted every action at that
    path as a deletion, started removing, and refused part-way telling the person to force a
    path that is never forced there, which refused the same way on every run.

    Mutation (declared): every action at that path counted as going, the first draft's rule ->
    the dry run's count comes back 0, and this reddens there; the real run would remove the
    footprint before refusing.
    """
    root = initialised(tmp_path, document=_agents_local(("agents-md", "agents-skeleton")))
    local = root / LOCAL_AGENTS
    text = local.read_text(encoding="utf-8")
    if edit == "skeleton":
        local.write_text(text + "\nA LINE OF OURS\n", encoding="utf-8")
    else:
        local.write_text(
            text.replace(
                "<!-- stayfixed:harness:begin -->\n", "<!-- stayfixed:harness:begin -->\nX\n"
            ),
            encoding="utf-8",
        )
    before = snapshot(root)
    assert _uninstall(root, tmp_path, dry_run=True).kept_locally == 1
    for force in ((), (LOCAL_AGENTS,)) if edit == "skeleton" else ((),):
        with pytest.raises(Refusal) as refused:
            _uninstall(root, tmp_path, force=force)
        assert_snapshot_unchanged(root, before)
        assert str(refused.value) == KEPT_LOCALLY.format(count=1)


@needs_git
def test_the_disk_after_the_write_once_pass_keeps_the_ignore_block_when_the_prediction_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The count before any write is a prediction; the disk after the write-once pass is the
    fact. Made to miss (it credits the remainder the skeleton pass then keeps), the run must
    still stop before the ignore block goes, with the file ignored and the manifest in place.

    The run has written by then, so what must be unchanged is what `KEPT_AFTER` says it left:
    the ignore block, `stayfixed.toml`, and the manifest's record of the block, which the next run
    finishes from. Mutation (oracle): `mutations/`'s "the ignore block goes while files are still
    under .stayfixed/local/" -> the ignore block goes over the remainder, no refusal is raised, and
    the file stops being ignored.
    """
    import stayfixed.project.uninstall as module

    monkeypatch.setattr(module, "ours_locally", lambda template, text, target, digests: True)
    root = initialised(tmp_path, document=_agents_local(("agents-md", "agents-skeleton")))
    local = root / LOCAL_AGENTS
    local.write_text(local.read_text(encoding="utf-8") + "\nA LINE OF OURS\n", encoding="utf-8")
    kept = (".gitignore", CONFIG_FILE)
    before = {name: (root / name).read_bytes() for name in kept}
    record = Manifest.read(root).get(IGNORE_ARTIFACT)
    assert record is not None
    with pytest.raises(Refusal) as refused:
        _uninstall(root, tmp_path)
    assert str(refused.value) == KEPT_AFTER.format(count=1)
    assert {name: (root / name).read_bytes() for name in kept} == before
    assert Manifest.read(root).get(IGNORE_ARTIFACT) == record
    assert "A LINE OF OURS" in local.read_text(encoding="utf-8")
    assert _ignored(root, local)


@needs_git
def test_a_dry_run_that_refuses_still_counts_what_is_kept_out_of_git(tmp_path: Path) -> None:
    # A plan with a refusal is still a report, and the refusal the real run would meet after the
    # finding is fixed is part of it. Mutation (advisory): report 0 whenever a plan refuses ->
    # the count comes back 0, and this reddens.
    root = initialised(tmp_path)
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace("<!-- stayfixed:harness:begin -->\n", ""),
        encoding="utf-8",
    )
    note = root / ".stayfixed" / "local" / "memory" / "developer" / "private-note.md"
    note.parent.mkdir(parents=True)
    note.write_text("a private note\n", encoding="utf-8")
    report = _uninstall(root, tmp_path, dry_run=True)
    assert [r.artifact_id for r in report.footprint.refusals] == ["agents-md"]
    assert report.kept_locally == 1


@needs_git
def test_a_remainder_kept_out_of_git_is_counted_before_anything_is_written(tmp_path: Path) -> None:
    """The region kept out of git, with a line of a person's outside it: taking the region out
    leaves the line, so the file stays, and the ignore block must stay over it. A first draft
    counted every `REMOVE` as a deletion and took the ignore block out.

    Mutation (declared): `unlinks` answers every `REMOVE` -> the run gets past the first check
    and refuses later, with the other message, and this reddens.
    """
    root = initialised(tmp_path, document=_agents_local(("agents-md",)))
    with (root / LOCAL_AGENTS).open("a", encoding="utf-8") as stream:
        stream.write("\nA LINE OF OURS\n")
    before = snapshot(root)
    assert _uninstall(root, tmp_path, dry_run=True).kept_locally == 1
    with pytest.raises(Refusal, match=re.escape(KEPT_LOCALLY.format(count=1))):
        _uninstall(root, tmp_path)
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_stayfixed_toml_deleted_by_hand_is_refused_until_it_is_restored(tmp_path: Path) -> None:
    # The manifest still records `stayfixed.toml`, and this command's own removal drops that
    # record with the file, so short of a run killed inside `apply` before the manifest write,
    # something else took it: here, a person deleted it. Going on dropped the manifest and left
    # every recorded file untracked for good; now the run refuses before any write, dry run
    # included, and restoring the file is a remedy that reaches the end. Mutation (oracle):
    # `mutations/`'s "uninstall drops the manifest when a person deleted stayfixed.toml" -> the run
    # removes the ledger instead of refusing, and the first assertion reddens.
    root = initialised(tmp_path)
    config = root / CONFIG_FILE
    text = config.read_text(encoding="utf-8")
    config.unlink()
    before = snapshot(root)
    for dry_run in (True, False):
        with pytest.raises(Refusal) as refused:
            _uninstall(root, tmp_path, dry_run=dry_run)
        assert str(refused.value) == DELETED_CONFIG
    assert_snapshot_unchanged(root, before)
    config.write_text(text, encoding="utf-8")
    _uninstall(root, tmp_path)
    assert tree(root) == {"README.md"}


@needs_git
def test_a_missing_stayfixed_toml_nothing_records_leaves_the_recorded_files_and_converges(
    tmp_path: Path,
) -> None:
    # The state a run leaves when it stopped after removing `stayfixed.toml` and before the
    # manifest: `apply` dropped the `config` record with the file. Nothing can be judged without
    # the configuration, so the files stay, their count is reported, and the ledger goes: `init`
    # no longer refuses the repository, and nor does this. Mutation (advisory): the ledger kept on
    # this path -> the second run finds the manifest and does not refuse with `NOTHING`, and the
    # last assertion reddens; the refusal above made unconditional -> the first call refuses.
    root = initialised(tmp_path)
    (root / CONFIG_FILE).unlink()
    Manifest.read(root).without(frozenset({"config"})).write(root)
    count = len(Manifest.read(root).records)
    report = _uninstall(root, tmp_path)
    assert report.note == NO_CONFIG.format(count=count)
    assert not (root / MANIFEST_PATH).exists() and (root / "AGENTS.md").is_file()
    with pytest.raises(Refusal, match=re.escape(NOTHING)):
        _uninstall(root, tmp_path)


@needs_git
def test_a_committed_path_and_record_reach_only_bytes_the_same_commit_states(
    tmp_path: Path,
) -> None:
    # Where the anchor ends. Artifact ids and the targets this build could write are the build's;
    # the `[paths]` value a target comes from and the digest a record carries are committed. A
    # commit pointing `roadmap` at README.md and recording README.md's exact bytes has uninstall
    # remove it, as its own diff could have. A byte of the file that commit does not state stops
    # it. Mutation (oracle): the engine's retired-digest comparison always matches -> the edited
    # README.md is removed and this reddens.
    for name, edit in (("stated", ""), ("edited", "a local line\n")):
        root = initialised(tmp_path / name)
        config = root / CONFIG_FILE
        config.write_text(
            config.read_text(encoding="utf-8") + '\n[paths]\nroadmap = "README.md"\n',
            encoding="utf-8",
        )
        manifest = Manifest.read(root)
        record = manifest.get("roadmap")
        assert record is not None
        forged = replace(record, target="README.md", sha256=digest(BEFORE))
        manifest.with_record(forged).write(root)
        readme = root / "README.md"
        readme.write_text(BEFORE + edit, encoding="utf-8")
        _uninstall(root, tmp_path / name)
        assert readme.exists() is bool(edit)


@needs_git
def test_a_symlinked_stayfixed_directory_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # A clone can commit `.stayfixed` as a symlink to a directory holding a manifest of its own.
    # The manifest is read through `contained()`, which refuses a path through a symlink, so the
    # run stops before any write, in the repository or where the link points.
    root = initialised(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    (root / ".stayfixed").rename(elsewhere)
    (root / ".stayfixed").symlink_to(elsewhere, target_is_directory=True)
    before, outside = snapshot(root), snapshot(elsewhere)
    with pytest.raises(Refusal, match="symlink"):
        _uninstall(root, tmp_path)
    assert_snapshot_unchanged(root, before)
    assert_snapshot_unchanged(elsewhere, outside)


@needs_git
def test_a_force_path_in_another_case_forces_nothing(tmp_path: Path) -> None:
    # A path is compared exactly. On a filesystem that folds case `agents.md` opens the same file
    # as `AGENTS.md`, and it still forces neither the region nor the skeleton.
    root = initialised(tmp_path)
    agents = root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    edited = text.replace(
        "<!-- stayfixed:harness:begin -->\n", "<!-- stayfixed:harness:begin -->\nOur line.\n"
    )
    agents.write_text(edited, encoding="utf-8")
    _uninstall(root, tmp_path, force=("agents.md",))
    assert agents.read_text(encoding="utf-8") == edited


@needs_git
def test_a_repository_stayfixed_never_initialised_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "bare"
    root.mkdir()
    with pytest.raises(Refusal, match=re.escape(NOTHING)):
        _uninstall(root, tmp_path)


@needs_git
def test_a_case_variant_of_a_harness_directory_is_never_pruned(tmp_path: Path) -> None:
    """`[paths] roadmap = ".Claude/roadmap.md"`: where case folds, as on the default macOS and
    Windows filesystems, `.Claude/` is `.claude/`, and pruning above the removed roadmap took an
    empty `.claude/` with it, so a later `init` no longer detected the harness. The marker
    directories are compared case-folded, so `.Claude/` stays on every filesystem (on Linux it
    is an empty directory of its own, left like any directory a harness might read).

    Mutation (oracle): `mutations/`'s "a case variant of a harness's own directory is pruned" -> the
    directory is removed and the assertion reddens.
    """
    document = (
        f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n[project]\nname = "widget"\n\n'
        '[paths]\nroadmap = ".Claude/roadmap.md"\n'
    )
    root = initialised(tmp_path, document=document)
    assert (root / ".Claude" / "roadmap.md").is_file()
    _uninstall(root, tmp_path)
    assert (root / ".Claude").is_dir()
    assert not any((root / ".Claude").iterdir())


@needs_git
def test_a_harness_directory_a_person_made_stays_when_its_rule_goes(tmp_path: Path) -> None:
    # Mutation (oracle, advisory): drop the `marker_dirs` skip in `_prune` -> `.claude/` is
    # removed with the rule inside it, and the first assertion reddens.
    root = initialised(tmp_path)
    (root / ".claude").mkdir()
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "[stayfixed]\n", '[stayfixed]\nprofile = "python"\n', 1
        ),
        encoding="utf-8",
    )
    upgrade(root, machine=tmp_path / "absent.toml", runner=Recorder(), dry_run=False, force=())
    rules = root / ".claude" / "rules"
    assert any(rules.iterdir())
    _uninstall(root, tmp_path)
    assert (root / ".claude").is_dir() and not rules.exists()


@needs_git
def test_an_empty_directory_a_committed_path_names_stays_when_nothing_was_removed_from_it(
    tmp_path: Path,
) -> None:
    # A `[paths]` value is committed, and the run used to prune every directory above every
    # place this configuration puts an artifact: `roadmap = "some/dir/x.md"` had it remove an
    # empty `some/dir/` a person made, though nothing of stayfixed's was ever in it. Only a
    # directory above a file this run removed goes now. The roadmap's own directory still goes,
    # because its file did. Mutation (oracle): `mutations/`'s "uninstall prunes above every place
    # the configuration names" -> `some/dir` is removed and the first assertion reddens.
    root = initialised(tmp_path)
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8") + '\n[paths]\nroadmap = "some/dir/x.md"\n',
        encoding="utf-8",
    )
    (root / "some" / "dir").mkdir(parents=True)
    _uninstall(root, tmp_path)
    assert (root / "some" / "dir").is_dir()
    assert not (root / "docs" / "architecture").exists()


@needs_git
def test_a_relocation_with_no_old_file_prunes_no_directory_a_person_made(tmp_path: Path) -> None:
    # A forged record at `some/dir/x.md`, the committed `[paths]` value naming it, and the
    # artifact kept out of git: the engine plans a relocation's `REMOVE` of the absent old file,
    # which unlinks nothing, and `_apply` counted it removed because the path was absent, so the
    # empty `some/dir/` and `some/` a person made went. Mutation (oracle): `mutations/`'s "a removal
    # that unlinked nothing prunes above its path" -> both directories are removed.
    root = initialised(tmp_path, document=LOCAL_ROADMAP)
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8") + '\n[paths]\nroadmap = "some/dir/x.md"\n',
        encoding="utf-8",
    )
    manifest = Manifest.read(root)
    manifest.with_record(
        Record(
            "roadmap",
            Kind.TEMPLATE,
            Location.REPO,
            "some/dir/x.md",
            "project/roadmap.md",
            stayfixed.__version__,
            digest("x"),
        )
    ).write(root)
    (root / "some" / "dir").mkdir(parents=True)
    report = _uninstall(root, tmp_path)
    assert (Verb.REMOVE, "some/dir/x.md") in {(a.verb, a.target) for a in report.footprint.actions}
    assert (root / "some" / "dir").is_dir()


@pytest.mark.parametrize("target", [MANIFEST_PATH.as_posix(), LOCAL_DIGESTS])
def test_a_ledger_file_that_cannot_be_removed_is_refused_with_the_reason_in_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    # The refusal named the file by its root-relative path and then quoted the error's own text,
    # `[Errno 13] Permission denied: 'manifest.json'`; it says the reason in words, as every other
    # refusal does. Mutations: `mutations/`'s "a ledger file that cannot be removed is reported
    # with the error's own text", and the same of the local ledger.
    from stayfixed.project import uninstall as module

    def refused(within: Path, relative: str) -> None:
        if relative == target:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), Path(relative).name)

    (tmp_path / target).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / target).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(module, "remove_within", refused)
    manifest = target == MANIFEST_PATH.as_posix()
    remove = module._remove_ledger if manifest else module._remove_local_artifacts
    with pytest.raises(Refusal) as failed:
        remove(tmp_path)
    assert str(failed.value) == f"{target} cannot be removed ({os.strerror(errno.EACCES)})"


@needs_git
def test_a_directory_where_the_assessment_belongs_is_left_and_the_ledger_still_goes(
    tmp_path: Path,
) -> None:
    # A clone can commit a directory at `.stayfixed/assessment.json`. Unlinking it fails, and a
    # refusal there, after `stayfixed.toml` went, would leave every later run refusing before the
    # manifest. It is left behind with `.stayfixed/` around it, and the run finishes.
    # Mutation (advisory): drop the directory check in `_remove_ledger` -> the run refuses with
    # "cannot be removed" and the manifest stays, and this reddens at the call.
    root = initialised(tmp_path)
    committed = root / ".stayfixed" / "assessment.json"
    committed.mkdir()
    (committed / "theirs.md").write_text("theirs\n", encoding="utf-8")
    _uninstall(root, tmp_path)
    assert (committed / "theirs.md").is_file()
    assert tree(root) == {
        "README.md",
        ".stayfixed",
        ".stayfixed/assessment.json",
        ".stayfixed/assessment.json/theirs.md",
    }


@needs_git
@pytest.mark.parametrize("value", ["CLAUDE.md", "claude.md"], ids=["exact", "case-variant"])
@pytest.mark.parametrize("command", ["upgrade", "uninstall"])
def test_a_paths_value_naming_another_artifact_s_file_refuses_before_any_write(
    tmp_path: Path, command: str, value: str
) -> None:
    """The review's repro. `CLAUDE.md` is kept out of git, a clone force-adds a ledger entry under
    `roadmap` naming that copy with the digest of its unedited bytes, and commits one line,
    `[paths] roadmap = "CLAUDE.md"`. Both commands' own checks held each pass on its own, so
    `upgrade` removed the copy as the roadmap's relocated one and created `CLAUDE.md` in its
    place, and the ledger rule took `CLAUDE.md` as a place `roadmap` could write too. No two
    artifacts but the `AGENTS.md` skeleton and its region may resolve to one file: refused before
    any write, naming the two ids and the key, never the value.

    `claude.md` is the same file on the default macOS and Windows filesystems, so it is refused
    on every filesystem too.

    Mutation (oracle): `mutations/`'s "an artifact may target a file another artifact is built to
    write" -> no refusal is raised, and `upgrade` creates `CLAUDE.md` over the roadmap. Mutation
    (oracle): `mutations/`'s "places are compared case-sensitively for ownership" -> the
    `case-variant` cases raise nothing.
    """
    root = initialised(
        tmp_path,
        document=f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n[project]\nname = "widget"\n'
        '\n[artifacts]\nlocal = ["claude-md"]\n',
    )
    copy = ".stayfixed/local/artifacts/CLAUDE.md"
    sha = digest((root / copy).read_text(encoding="utf-8"))
    LocalDigests().with_entry("roadmap", copy, sha).write(root)
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "[artifacts]\n", f'[paths]\nroadmap = "{value}"\n\n[artifacts]\n'
        ),
        encoding="utf-8",
    )
    before = snapshot(root)
    run = (
        (
            lambda: upgrade(
                root, machine=tmp_path / "absent.toml", runner=Recorder(), dry_run=False, force=()
            )
        )
        if command == "upgrade"
        else (lambda: _uninstall(root, tmp_path))
    )
    with pytest.raises(Refusal) as refused:
        run()
    assert str(refused.value) == ONE_FILE.format(
        first="claude-md",
        first_key=OWN_NAME,
        second="roadmap",
        second_key="paths.roadmap",
    )
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_profile_artifact_listed_local_after_init_is_still_taken_back(tmp_path: Path) -> None:
    """`init` and `upgrade` refuse a profile artifact in `[artifacts] local`, because every
    pointer to it names the committed path. `uninstall` must not: a `stayfixed.toml` that lists
    one, written before that rule or by hand since, would otherwise be a configuration nothing
    can take back. The committed copy goes as a relocation, and what is left is the adopted
    `stayfixed.toml`, the README from before, and `.claude/`, a harness's own directory that
    `uninstall` never removes.

    Mutation (oracle): `mutations/`'s "uninstall refuses a profile artifact kept out of git, so a
    configuration written before that rule can never be taken back" -> the run raises the
    profile refusal and this reddens at the call.
    """
    document = (
        f'[stayfixed]\nversion = "{stayfixed.__version__}"\nprofile = "python"\n'
        'agents = ["claude"]\n\n[project]\nname = "widget"\n'
    )
    root = initialised(tmp_path, document=document)
    rule = ".claude/rules/stayfixed-python.md"
    assert (root / rule).is_file()
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8") + '\n[artifacts]\nlocal = ["claude-rules"]\n',
        encoding="utf-8",
    )
    report = _uninstall(root, tmp_path)
    assert (Verb.REMOVE, rule, "relocated") in {
        (a.verb, a.target, a.reason) for a in report.footprint.actions
    }
    assert tree(root) == {".claude", "README.md", CONFIG_FILE}
    assert report.orphans == 0 and report.kept_locally == 0


@needs_git
@pytest.mark.parametrize("local", ["config", "gitignore"])
def test_stayfixed_toml_or_the_ignore_block_kept_out_of_git_refuses_before_any_write(
    tmp_path: Path, local: str
) -> None:
    """Both go after the check of what is left under `.stayfixed/local/`, so kept out of git
    they would be counted as removed before any write and found still there after it: the run
    removed the footprint and refused part-way, and every later run refused the same way. Neither
    works out of git anyway, so the configuration is refused before anything is planned.

    Mutation (declared): the refusal dropped -> `config` refuses part-way with the other
    message, after the footprint went, and the snapshot comparison reddens.
    """
    document = LOCAL_ROADMAP.replace('local = ["roadmap"]', "local = []")
    root = initialised(tmp_path, document=document)
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace("local = []", f'local = ["{local}"]'),
        encoding="utf-8",
    )
    # What an earlier stayfixed wrote under that configuration.
    copy = (
        root
        / ".stayfixed"
        / "local"
        / "artifacts"
        / (CONFIG_FILE if local == "config" else ".gitignore")
    )
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(config.read_text(encoding="utf-8") if local == "config" else "x\n")
    before = snapshot(root)
    for force in ((), (copy.relative_to(root).as_posix(),)):
        with pytest.raises(Refusal) as refused:
            _uninstall(root, tmp_path, force=force)
        assert_snapshot_unchanged(root, before)
        assert str(refused.value) == LOCAL_ROOT_ONLY.format(names=local)


def test_the_root_only_artifacts_are_the_two_uninstall_removes_after_its_check() -> None:
    # `ROOT_ONLY` must name the configuration's record and the ignore region, the two artifacts
    # `uninstall` holds back past its check of `.stayfixed/local/`, so naming any other reddens
    # here. Both ids are spelled once and pinned to what the templates build in
    # `tests/project/test_templates.py`.
    assert set(ROOT_ONLY) == {CONFIG_ARTIFACT, IGNORE_ARTIFACT}


LOCAL_COPY = ".stayfixed/local/artifacts/docs/roadmap.md"


@needs_git
@pytest.mark.parametrize("upgraded", [False, True], ids=["direct", "after-upgrade"])
def test_a_copy_left_when_its_id_left_the_local_list_goes_with_the_rest(
    tmp_path: Path, upgraded: bool
) -> None:
    """`roadmap` kept out of git, then taken out of `[artifacts] local`. The copy under
    `.stayfixed/local/artifacts/` was recorded nowhere, so nothing judged it again: `uninstall`
    refused over it for good and suggested a `--force` no action could reach. The ledger records
    it, so it goes whether or not an `upgrade` ran in between.

    Mutation (oracle): `mutations/`'s "uninstall never judges an artifact only the ledger records"
    -> the direct case refuses with `KEPT_LOCALLY`.
    """
    root = initialised(tmp_path, document=LOCAL_ROADMAP)
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace('local = ["roadmap"]', "local = []"),
        encoding="utf-8",
    )
    if upgraded:
        upgrade(root, machine=tmp_path / "absent.toml", runner=Recorder(), dry_run=False, force=())
    _uninstall(root, tmp_path)
    assert tree(root) == {"README.md", "stayfixed.toml"}


@needs_git
def test_a_changed_copy_left_by_the_local_list_is_named_and_force_is_a_remedy_that_works(
    tmp_path: Path,
) -> None:
    # The refusal names `--force` for a file the report lists, and for this one it now reaches.
    root = initialised(tmp_path, document=LOCAL_ROADMAP)
    (root / LOCAL_COPY).write_text("private plans\n", encoding="utf-8")
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace('local = ["roadmap"]', "local = []"),
        encoding="utf-8",
    )
    dry = _uninstall(root, tmp_path, dry_run=True)
    assert (Verb.SKIP_MODIFIED, LOCAL_COPY) in {(a.verb, a.target) for a in dry.footprint.actions}
    assert dry.kept_locally == 1
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _uninstall(root, tmp_path)
    assert str(refused.value) == KEPT_LOCALLY.format(count=1)
    assert_snapshot_unchanged(root, before)
    _uninstall(root, tmp_path, force=(LOCAL_COPY,))
    assert tree(root) == {"README.md", "stayfixed.toml"}


@needs_git
def test_an_unedited_copy_kept_out_of_git_goes_after_its_template_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Judged by this build's render alone, a copy nobody touched was "edited" to `uninstall`
    # after any release that changed its template, and the run refused before any write.
    from stayfixed.project import templates

    root = initialised(tmp_path, document=LOCAL_ROADMAP)
    original = templates.read
    monkeypatch.setattr(
        templates, "read", lambda name: original(name) + ("\nnew\n" if name == "roadmap.md" else "")
    )
    _uninstall(root, tmp_path)
    assert tree(root) == {"README.md", "stayfixed.toml"}


@needs_git
def test_the_ledger_of_what_was_kept_out_of_git_is_ignored_and_goes_last(tmp_path: Path) -> None:
    # It lives under `.stayfixed/local/`, which the footprint's ignore block keeps out of git, and
    # it is stayfixed's own: never counted as a file left behind, removed before the ignore block.
    root = initialised(tmp_path, document=LOCAL_ROADMAP)
    ledger = ".stayfixed/local/artifacts.json"
    assert (root / ledger).is_file() and _ignored(root, root / ledger)
    assert _uninstall(root, tmp_path, dry_run=True).kept_locally == 0
    _uninstall(root, tmp_path)
    assert not (root / ".stayfixed").exists()


@needs_git
def test_forcing_a_region_copy_left_by_the_local_list_never_reaches_the_skeleton_beside_it(
    tmp_path: Path,
) -> None:
    """`agents-md` taken out of `[artifacts] local` while the skeleton stays in it: the region's
    copy is judged by the footprint pass at the skeleton's own file. A `--force` for that copy
    must not reach the write-once pass, where it would delete the skeleton and the line a person
    wrote into it. The file keeps that line, so the run refuses before any write, and says so
    in the dry run's count.

    Mutation (oracle): `mutations/`'s "a force meant for a region's left copy reaches the skeleton
    kept out of git" -> the dry run plans the skeleton `remove (retired, forced)`, and the first
    assertion reddens.
    """
    root = initialised(tmp_path, document=_agents_local(("agents-md", "agents-skeleton")))
    local = root / LOCAL_AGENTS
    text = local.read_text(encoding="utf-8").replace(
        "<!-- stayfixed:harness:begin -->\n", "<!-- stayfixed:harness:begin -->\nX\n"
    )
    local.write_text(text + "\nA LINE OF OURS\n", encoding="utf-8")
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'local = ["agents-md", "agents-skeleton"]', 'local = ["agents-skeleton"]'
        ),
        encoding="utf-8",
    )
    dry = _uninstall(root, tmp_path, dry_run=True, force=(LOCAL_AGENTS,))
    assert [a.verb for a in dry.once.actions if a.artifact_id == "agents-skeleton"] == [
        Verb.SKIP_MODIFIED
    ]
    assert dry.kept_locally == 1
    before = snapshot(root)
    with pytest.raises(Refusal, match=re.escape(KEPT_LOCALLY.format(count=1))):
        _uninstall(root, tmp_path, force=(LOCAL_AGENTS,))
    assert_snapshot_unchanged(root, before)


@needs_git
@pytest.mark.parametrize("edited", [False, True], ids=["unedited", "edited"])
def test_a_copy_left_when_its_path_moved_is_judged_and_force_reaches_it(
    tmp_path: Path, edited: bool
) -> None:
    """`roadmap` kept out of git, then its `[paths]` value moved while it stayed there. The ledger
    entry was overwritten with the new place, no action named the old copy, and `uninstall`
    refused over it with a `--force` that did nothing. Now the old copy is judged at the place the
    ledger records: unedited it goes on `upgrade`, and edited it is named, keeps its entry, and
    `--force` with its path takes it.

    Mutation (oracle): `mutations/`'s "a left copy is judged only where [artifacts] local no longer
    lists its id" -> the unedited case keeps the old copy, and the uninstall refuses.
    """
    root = initialised(tmp_path, document=LOCAL_ROADMAP)
    if edited:
        (root / LOCAL_COPY).write_text("private plans\n", encoding="utf-8")
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8") + '\n[paths]\nroadmap = "docs/r.md"\n',
        encoding="utf-8",
    )
    report = upgrade(
        root, machine=tmp_path / "absent.toml", runner=Recorder(), dry_run=False, force=()
    )
    verbs = {(a.verb, a.target) for a in report.footprint.actions}
    assert ((Verb.SKIP_MODIFIED if edited else Verb.REMOVE), LOCAL_COPY) in verbs
    assert (root / ".stayfixed" / "local" / "artifacts" / "docs" / "r.md").is_file()
    if edited:
        with pytest.raises(Refusal, match=re.escape(KEPT_LOCALLY.format(count=1))):
            _uninstall(root, tmp_path)
        assert (root / LOCAL_COPY).read_text(encoding="utf-8") == "private plans\n"
    _uninstall(root, tmp_path, force=(LOCAL_COPY,) if edited else ())
    assert tree(root) == {"README.md", "stayfixed.toml"}


@needs_git
@pytest.mark.parametrize(
    ("malformed", "refusal"),
    [
        ('\n[ledger]\nid_prefix = "br"\n', "[ledger] id_prefix 'br' must match"),
        (
            '\n[ledger]\nevidence_boundary_required_for = ["critical"]\n',
            "[ledger] evidence_boundary_required_for names 1 value(s) that are not a severity",
        ),
    ],
    ids=["id-prefix", "boundary-level"],
)
def test_a_ledger_value_the_register_refuses_stops_init_and_upgrade_and_never_uninstall(
    tmp_path: Path, malformed: str, refusal: str
) -> None:
    # `uninstall` is the way out of a configuration stayfixed cannot work with. A `[ledger]` value
    # the bug ledger's register refuses — an `id_prefix` outside the grammar, a boundary level that
    # names no severity — is refused where the bug index is rendered, so `init` and `upgrade` stop
    # on it; taking the footprint out renders nothing and must not ask for the register. Mutation
    # (oracle): `mutations/`'s "the footprint builds the bug ledger's register before anything
    # renders" -> `uninstall` refuses too, and each case reddens on its own.
    fresh = repository(tmp_path, directory="fresh")
    (fresh / CONFIG_FILE).write_text(DOCUMENT + malformed, encoding="utf-8")
    code, out, err = cli(fresh, tmp_path, "init", "--yes")
    assert code == 2 and refusal in err, (out, err)
    assert tree(fresh) == {"README.md", CONFIG_FILE}
    root = initialised(tmp_path, document=DOCUMENT)
    config = root / CONFIG_FILE
    config.write_text(config.read_text(encoding="utf-8") + malformed, encoding="utf-8")
    code, out, err = cli(root, tmp_path, "upgrade")
    assert code == 2 and refusal in err, (out, err)
    code, out, err = cli(root, tmp_path, "uninstall")
    assert code == 0, err
    assert tree(root) == {"README.md", CONFIG_FILE}
