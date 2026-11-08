from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from drybag.cli import build_parser, discover_registrars, run
from drybag.errors import Refusal
from drybag.overlay.api import render
from drybag.overlay.layout import IDENTITY_RECORD
from drybag.overlay.template import template_root
from drybag.overlay.upgrade import upgrade
from drybag.scaffold import MANIFEST_PATH, Verb, digest
from tests.runners import Recorder


def _an_overlay(tmp_path: Path) -> Path:
    return render(tmp_path / "ov", runner=Recorder()).root


def _restamp(root: Path, artifact_id: str) -> None:
    """Record the artifact's *current* bytes, the state a release leaves behind when the
    template has moved on and the instance has not."""
    path = root / MANIFEST_PATH
    document = json.loads(path.read_text(encoding="utf-8"))
    body = (root / artifact_id).read_text(encoding="utf-8")
    document["artifacts"][artifact_id]["sha256"] = digest(body)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def test_an_untouched_skeleton_file_is_refreshed(tmp_path: Path) -> None:
    # `overlay upgrade` refreshes untouched skeleton files after a release by the same rule a
    # project's files follow, which is the scaffold engine's hash comparison; this asserts the
    # overlay really goes through it rather than reimplementing it.
    root = _an_overlay(tmp_path)
    (root / "README.md").write_text("stale", encoding="utf-8")
    _restamp(root, "README.md")  # record the hash of the stale text, as a release would
    verbs = {a.artifact_id: a.verb for a in upgrade(root, dry_run=True).plan.actions}
    assert verbs["README.md"] is Verb.UPDATE


def test_a_hand_edited_file_is_skipped_and_named(tmp_path: Path) -> None:
    # The same rule's other half. An overlay is where the owner's own rules live, so a silent
    # overwrite here destroys the only copy of something.
    root = _an_overlay(tmp_path)
    (root / "common" / "codex" / "common.rules").write_text("my own rules\n", encoding="utf-8")
    verbs = {a.artifact_id: a.verb for a in upgrade(root, dry_run=True).plan.actions}
    assert verbs["common/codex/common.rules"] is Verb.SKIP_MODIFIED


def _a_release_that_raises_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, floor: str
) -> None:
    """Stand in for a later release: the shipped tree, its identity record's `requires` raised."""
    shipped = tmp_path / "a-later-release"
    shutil.copytree(template_root(), shipped)
    record = shipped / IDENTITY_RECORD
    text = record.read_text(encoding="utf-8")
    assert 'requires = ">=0.1.0"' in text, "the stand-in has no floor to raise"
    record.write_text(text.replace('">=0.1.0"', f'"{floor}"'), encoding="utf-8")
    monkeypatch.setattr("drybag.overlay.template.template_root", lambda: shipped)


def test_an_overlay_set_up_at_a_path_takes_a_raised_floor_with_nothing_for_its_owner_to_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The identity record is the one carrier of `requires`, the floor `doctor` and a session's
    # first lines read, so `overlay upgrade` has to be able to raise it. It also held `owner` and
    # `name`, which the render's note told the owner to write in: once they had, the record no
    # longer held the bytes the ledger recorded, and every later upgrade skipped it as hand-edited,
    # so the floor never rose again. Nothing in it is the owner's to write now, and nothing asks.
    #
    # Mutation: `mutations/`'s "setup writes into the identity record it rendered" -> the record
    # is skipped as hand-edited and this reddens.
    from drybag.overlay.requires import requires_of
    from drybag.setup.api import setup

    destination = tmp_path / "ov"
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=Recorder(),
        overlay=str(destination),
    )
    assert IDENTITY_RECORD not in " ".join(report.notes), report.notes
    record = tomllib.loads((destination / IDENTITY_RECORD).read_text(encoding="utf-8"))
    assert set(record) == {"requires", "layout"}, record
    _a_release_that_raises_the_floor(tmp_path, monkeypatch, ">=9.9.9")
    upgraded = upgrade(destination, dry_run=False).plan
    verbs = {a.artifact_id: (a.verb, a.reason) for a in upgraded.actions}
    assert verbs[IDENTITY_RECORD] == (Verb.UPDATE, "refreshed"), verbs
    assert requires_of(destination) == ">=9.9.9"


def test_a_record_written_by_hand_as_the_upgrading_note_says_is_the_one_the_template_ships(
    tmp_path: Path,
) -> None:
    # An overlay made before the record shipped is migrated by hand: the release note says to add
    # `drybag-overlay.toml` holding `requires = ">=0.1.0"` and `layout = 1`. Written so, it is
    # the shipped record byte for byte, so `overlay upgrade` reads it as up to date. While the
    # record also held an owner and a name, a record written as the note said never matched the
    # template, and was skipped as a file drybag did not write. A ledger records only what
    # drybag wrote, so such a record is still not refreshed once a later release changes it
    # (`docs/cli.md`, `overlay upgrade`).
    root = _an_overlay(tmp_path)
    manifest = root / MANIFEST_PATH
    document = json.loads(manifest.read_text(encoding="utf-8"))
    del document["artifacts"][IDENTITY_RECORD]
    manifest.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (root / IDENTITY_RECORD).write_text('requires = ">=0.1.0"\nlayout = 1\n', encoding="utf-8")
    planned = upgrade(root, dry_run=True).plan
    assert IDENTITY_RECORD in planned.unchanged, planned.actions


def test_the_two_permission_files_are_asked_about_even_when_unchanged(tmp_path: Path) -> None:
    # Exactly two files are exceptions to the hash rule, and `overlay upgrade` diffs and asks
    # about them regardless of hash — they are the two files that can grant capability, and a
    # hash match is not consent for those. The scaffold engine every area shares has no verb for
    # it, so the decision list lives beside the plan rather than inside it.
    root = _an_overlay(tmp_path)
    decisions = upgrade(root, dry_run=True).decisions
    assert set(decisions) == {"common/claude/permissions.json", "common/claude/hooks.json"}


def test_an_upgrade_of_a_fresh_overlay_plans_nothing(tmp_path: Path) -> None:
    # The overlay this release renders is what this release would upgrade it to, so the first
    # upgrade after a render has nothing to do; the case below relies on that.
    assert upgrade(_an_overlay(tmp_path), dry_run=True).plan.actions == ()


def test_a_dry_run_writes_nothing_where_a_real_run_would(tmp_path: Path) -> None:
    # Non-vacuous on purpose: on a freshly created overlay the plan carries no action, so a dry
    # run and a real run both write nothing and `if not dry_run:` could be deleted unnoticed.
    # A stale, re-stamped file gives the plan an UPDATE; the dry run must leave the stale bytes
    # and the real run must replace them. Mutation: `if not dry_run:` → `if True:` reddens the
    # first assertion; `apply(...)` removed reddens the second.
    root = _an_overlay(tmp_path)
    (root / "README.md").write_text("stale", encoding="utf-8")
    _restamp(root, "README.md")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert upgrade(root, dry_run=True).plan.actions
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    upgrade(root, dry_run=False)
    assert (root / "README.md").read_text(encoding="utf-8") != "stale"


def test_a_directory_that_is_not_an_overlay_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # `--root` defaults to `.` and was checked nowhere: in a directory
    # holding a `README.md` and a `src/main.py`, `drybag overlay upgrade --root .` created
    # the whole overlay — both plugin manifests, `hooks/hooks.json`, `common/**`, `.gitignore`
    # and `.github/workflows/scan.yml` — reported them as work done and exited 0. (Fourteen
    # files when the defect was found; the count has moved since, which is why it is not
    # restated here.) Writing a workflow file into a repository the owner may then
    # commit is the concrete harm.
    #
    # Mutation (`mutations/`'s "overlay upgrade stops asking whether --root is an overlay"):
    # the `require_overlay` call is removed → the overlay's files appear and this reddens on
    # both the refusal and the tree.
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "README.md").write_text("# a project, not an overlay\n", encoding="utf-8")
    (project / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    before = sorted(p.relative_to(project) for p in project.rglob("*"))
    assert before, "the fixture writes nothing, so the comparison below would prove nothing"
    with pytest.raises(Refusal, match="must name an overlay"):
        upgrade(project, dry_run=False)
    assert sorted(p.relative_to(project) for p in project.rglob("*")) == before


def test_the_cli_exits_two_rather_than_zero_on_a_directory_that_is_not_an_overlay(
    tmp_path: Path,
) -> None:
    # The same finding through the command surface, which is where it was reproduced: the run
    # that created the overlay's files reported them as work done and exited 0, so nothing
    # about the outcome said anything had gone wrong.
    (tmp_path / "README.md").write_text("# not an overlay\n", encoding="utf-8")
    parser = build_parser(discover_registrars())
    assert run(["overlay", "upgrade", "--root", str(tmp_path)], parser=parser) == 2
    assert [p.name for p in tmp_path.iterdir()] == ["README.md"]


# --- a file an earlier release shipped and this one does not --------------------------------

# The bytes 0.1.0 and 0.1.1 shipped at `common/memory/README.md`, whole: the bytes drybag wrote
# there, which `overlay upgrade` once removed the file by.
SHIPPED_MEMORY_README = (
    "# Cross-project notes\n"
    "\n"
    "Notes that are true across your projects: how you like to work, what you have learned "
    "about a\n"
    "tool you use everywhere, standing preferences that are not rules.\n"
    "\n"
    "This directory is the store a bound repository links to as its `developer` group, alongside\n"
    "that project's own notes under `projects/<name>/memory/`. The routing index a session "
    "reads is\n"
    "rendered from both; it is generated, so write the notes and let the index follow.\n"
    "\n"
    "A note about one project goes under `projects/<name>/memory/` instead. Keeping the two apart\n"
    "is what stops one client's work reaching another client's session.\n"
)
MEMORY_README = "common/memory/README.md"


def test_upgrade_plans_nothing_for_a_formerly_retired_file(tmp_path: Path) -> None:
    # `overlay upgrade` plans the shipped template files only: a file an earlier release shipped
    # and this one does not is the owner's to delete, even holding the bytes drybag wrote.
    root = _an_overlay(tmp_path)
    (root / MANIFEST_PATH).unlink()
    path = root / MEMORY_README
    path.write_text(SHIPPED_MEMORY_README, encoding="utf-8")
    planned = upgrade(root, dry_run=True).plan
    assert MEMORY_README not in {a.target for a in planned.actions}
    upgrade(root, dry_run=False)
    assert path.read_text(encoding="utf-8") == SHIPPED_MEMORY_README
