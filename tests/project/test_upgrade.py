"""`stayfixed upgrade`: moved keys, a re-planned footprint, and what it will not touch."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

import stayfixed
from stayfixed.config.loader import CONFIG_FILE
from stayfixed.config.owned import OwnedKeyError
from stayfixed.errors import Refusal
from stayfixed.project import footprint, templates
from stayfixed.project.upgrade import (
    NEWER,
    NOT_INITIALISED,
    UNORDERED,
    UNREADABLE_VERSION,
    UpgradeReport,
    upgrade,
)
from stayfixed.scaffold import Manifest, Record, Verb, digest
from stayfixed.scaffold.manifest import Kind, Location
from tests.gitfixture import needs_git
from tests.project.repos import initialised
from tests.runners import Recorder
from tests.snapshot import assert_snapshot_unchanged, snapshot


def _upgrade(
    root: Path,
    tmp_path: Path,
    *,
    dry_run: bool = False,
    force: tuple[str, ...] = (),
) -> UpgradeReport:
    return upgrade(
        root, machine=tmp_path / "absent.toml", runner=Recorder(), dry_run=dry_run, force=force
    )


@pytest.fixture
def newer(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Become a later stayfixed — a new version, one shipped template's bytes changed — when
    called, which is after the fixture has run the current one."""

    def become() -> None:
        monkeypatch.setattr(stayfixed, "__version__", "9.9.9")
        original = templates.read

        def read(name: str) -> str:
            text = original(name)
            extra = "\nA line the next release adds.\n"
            return text + extra if name == "documentation.md" else text

        monkeypatch.setattr(templates, "read", read)

    return become


@needs_git
def test_a_profile_kept_out_of_git_refuses_upgrade_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # `footprint.refuse_local_profile` at the second entry point that writes a footprint: a
    # `stayfixed.toml` edited by hand after `init` meets it here. `uninstall` does not apply it, so
    # the same file can still be taken back (`test_uninstall.py` holds that half). Mutation
    # (oracle): `mutations/`'s "a profile artifact kept out of git is written, and every pointer to
    # it dangles" drops the condition both share.
    root = initialised(tmp_path)
    (root / CONFIG_FILE).write_text(
        f'[stayfixed]\nversion = "{stayfixed.__version__}"\nprofile = "python"\n'
        'agents = ["claude"]\n\n'
        '[project]\nname = "widget"\n\n[artifacts]\nlocal = ["claude-rules"]\n',
        encoding="utf-8",
    )
    before = snapshot(root)
    with pytest.raises(Refusal, match="profile's artifacts"):
        _upgrade(root, tmp_path)
    assert_snapshot_unchanged(root, before)


@needs_git
def test_stayfixed_toml_kept_out_of_git_refuses_upgrade_before_any_write(tmp_path: Path) -> None:
    # `footprint.refuse_local_root_only` where a hand edit after `init` meets it.
    root = initialised(tmp_path)
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8") + '\n[artifacts]\nlocal = ["config"]\n',
        encoding="utf-8",
    )
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _upgrade(root, tmp_path)
    assert_snapshot_unchanged(root, before)
    assert str(refused.value) == footprint.LOCAL_ROOT_ONLY.format(names="config")


@needs_git
def test_a_committed_path_into_stayfixeds_own_directory_refuses_upgrade_before_any_write(
    tmp_path: Path,
) -> None:
    # The attach ledger case, end to end. `agents-md` is a region inserted into whatever file
    # `[paths] agents_md` names, so a pulled commit naming `.stayfixed/local/attach.json` had this
    # command report `region_update .stayfixed/local/attach.json (refreshed)` and rewrite the
    # ledger, in a directory git cannot give back. The loader refuses the value now, naming the
    # key. Mutation (oracle): `mutations/`'s "a [paths] value may name stayfixed's own directory".
    root = initialised(tmp_path)
    ledger = root / ".stayfixed" / "local" / "attach.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"entries": []}\n', encoding="utf-8")
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8")
        + '\n[paths]\nagents_md = ".stayfixed/local/attach.json"\n',
        encoding="utf-8",
    )
    before = snapshot(root)
    with pytest.raises(Refusal, match=r"paths\.agents_md names stayfixed's own directory"):
        _upgrade(root, tmp_path)
    assert_snapshot_unchanged(root, before)
    assert ledger.read_text(encoding="utf-8") == '{"entries": []}\n'


@needs_git
def test_a_current_footprint_upgrades_to_nothing(tmp_path: Path) -> None:
    root = initialised(tmp_path)
    before = snapshot(root)
    report = _upgrade(root, tmp_path)
    assert report.moved == ()
    assert [a.verb for a in report.footprint.actions] == []
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_newer_stayfixed_refreshes_what_is_untouched_and_skips_what_was_edited(
    tmp_path: Path, newer: Callable[[], None]
) -> None:
    root = initialised(tmp_path)
    running = stayfixed.__version__
    newer()
    roadmap = root / "docs" / "roadmap.md"
    roadmap.write_text(roadmap.read_text(encoding="utf-8") + "\nOur own line.\n", encoding="utf-8")
    document_before = (root / CONFIG_FILE).read_text(encoding="utf-8")

    report = _upgrade(root, tmp_path)

    # Keyed by artifact id, not by path: a document path under `tests/` is one of the strings
    # the neutrality gate refuses in test code.
    verbs = {a.artifact_id: (a.verb, a.reason) for a in report.footprint.actions}
    assert verbs["documentation-policy"] == (Verb.UPDATE, "refreshed")
    assert verbs["roadmap"] == (Verb.SKIP_MODIFIED, "hand-edited")
    assert "Our own line." in roadmap.read_text(encoding="utf-8")
    assert "A line the next release adds." in (
        root / "docs" / "architecture" / "documentation.md"
    ).read_text(encoding="utf-8")
    # Every byte but the version is the byte it was.
    assert (root / CONFIG_FILE).read_text(encoding="utf-8") == document_before.replace(
        f'version = "{running}"', 'version = "9.9.9"'
    )
    assert [(m.key, m.after) for m in report.moved] == [(("stayfixed", "version"), "9.9.9")]


@needs_git
def test_force_overwrites_exactly_the_edit_it_names(
    tmp_path: Path, newer: Callable[[], None]
) -> None:
    root = initialised(tmp_path)
    newer()
    for name in ("roadmap.md", "roadmap-history.md"):
        path = root / "docs" / name
        path.write_text(path.read_text(encoding="utf-8") + "\nours\n", encoding="utf-8")
    _upgrade(root, tmp_path, force=("docs/roadmap.md",))
    assert "ours" not in (root / "docs" / "roadmap.md").read_text(encoding="utf-8")
    assert "ours" in (root / "docs" / "roadmap-history.md").read_text(encoding="utf-8")


@needs_git
def test_a_second_upgrade_to_the_same_release_writes_nothing(
    tmp_path: Path, newer: Callable[[], None]
) -> None:
    # The lifecycle's "re-run, nothing changed": the first run to a release refreshes a document
    # and moves the version, and the second finds every artifact as the first left it, so it
    # plans nothing and the tree is the same byte for byte. Mutation: `mutations/`'s "an artifact
    # whose bytes are already the template's is planned again".
    root = initialised(tmp_path)
    newer()
    first = _upgrade(root, tmp_path)
    assert first.moved and Verb.UPDATE in {action.verb for action in first.footprint.actions}
    before = snapshot(root)
    second = _upgrade(root, tmp_path)
    assert_snapshot_unchanged(root, before)
    assert second.moved == () and second.footprint.actions == ()
    assert second.footprint.unchanged


@needs_git
def test_a_dry_run_writes_nothing_and_reports_everything(
    tmp_path: Path, newer: Callable[[], None]
) -> None:
    root = initialised(tmp_path)
    newer()
    before = snapshot(root)
    report = _upgrade(root, tmp_path, dry_run=True)
    assert report.dry_run and report.moved and report.footprint.actions
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_version_in_a_shape_the_editor_cannot_rewrite_is_refused_even_when_it_would_be_held(
    tmp_path: Path,
) -> None:
    """A tool-owned key written in a shape the editor cannot prove it rewrote is refused before
    any write. Asking whether the loaded version differs from the running one instead would
    write the footprint around a key no later run can move either. The roadmap is deleted first,
    so a run that went on would visibly write.
    """
    root = initialised(tmp_path)
    config = root / CONFIG_FILE
    text = config.read_text(encoding="utf-8")
    recorded = f'version = "{stayfixed.__version__}"'
    assert text.count(recorded) == 1
    config.write_text(text.replace(recorded, 'version = """0.0.1"""'), encoding="utf-8")
    (root / "docs" / "roadmap.md").unlink()
    before = snapshot(root)
    with pytest.raises(OwnedKeyError, match=re.escape("[stayfixed] version is written in a shape")):
        _upgrade(root, tmp_path)
    assert_snapshot_unchanged(root, before)


@needs_git
@pytest.mark.parametrize("recorded", ["99.0.0", "99.0.0-rc1"])
def test_a_project_recording_a_newer_stayfixed_is_refused(tmp_path: Path, recorded: str) -> None:
    # An older plugin would repin an older release and put older bytes over newer ones. A
    # pre-release suffix does not hide the newer release: the leading `X.Y.Z` decides.
    root = initialised(tmp_path)
    path = root / CONFIG_FILE
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f'version = "{stayfixed.__version__}"', f'version = "{recorded}"'
        ),
        encoding="utf-8",
    )
    before = snapshot(root)
    with pytest.raises(Refusal, match=re.escape(NEWER.format(running=stayfixed.__version__))):
        _upgrade(root, tmp_path)
    assert_snapshot_unchanged(root, before)


def _recording(root: Path, version: str) -> None:
    path = root / CONFIG_FILE
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f'version = "{stayfixed.__version__}"', f'version = "{version}"'
        ),
        encoding="utf-8",
    )


@needs_git
def test_a_pre_release_build_never_moves_a_project_recording_the_release_down_to_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read by the leading `X.Y.Z` alone, `1.0.0` and `1.0.0rc1` were one version, so this build
    # rewrote a released `1.0.0` down to `1.0.0rc1` and re-pinned the workflow to it. Mutation
    # (oracle): `mutations/`'s "a release reads as older than its own pre-release" -> the run moves
    # the version and the refusal is never raised.
    root = initialised(tmp_path)
    _recording(root, "1.0.0")
    monkeypatch.setattr(stayfixed, "__version__", "1.0.0rc1")
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _upgrade(root, tmp_path)
    assert str(refused.value) == NEWER.format(running="1.0.0rc1")
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_release_moves_a_project_recording_its_own_pre_release_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = initialised(tmp_path)
    _recording(root, "1.0.0.dev0")
    monkeypatch.setattr(stayfixed, "__version__", "1.0.0")
    report = _upgrade(root, tmp_path)
    assert [(m.key, m.before, m.after) for m in report.moved] == [
        (("stayfixed", "version"), "(not a version)", "1.0.0")
    ]
    assert 'version = "1.0.0"\n' in (root / CONFIG_FILE).read_text(encoding="utf-8")


@needs_git
def test_two_pre_releases_of_one_version_are_refused_as_unordered_and_never_quoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `later` does not order two pre-releases, so which way a move would go is unknown. The
    # refusal names the running version, stayfixed's own, and never the recorded string.
    # Mutation (oracle): `mutations/`'s "upgrade moves a version it cannot order" -> the run moves
    # it.
    root = initialised(tmp_path)
    _recording(root, "1.0.0rc1-PROJECT")
    monkeypatch.setattr(stayfixed, "__version__", "1.0.0rc2")
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _upgrade(root, tmp_path)
    assert str(refused.value) == UNORDERED.format(running="1.0.0rc2")
    assert "PROJECT" not in str(refused.value)
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_recorded_version_with_no_leading_triple_is_refused_and_never_quoted(
    tmp_path: Path,
) -> None:
    # `v99.0.0` has no leading `X.Y.Z`, so which way a move would go is unknown; moving it to the
    # running version could be moving it backward. Mutation (oracle): `mutations/`'s "upgrade moves
    # a recorded version it cannot read".
    root = initialised(tmp_path)
    path = root / CONFIG_FILE
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f'version = "{stayfixed.__version__}"', 'version = "v99.0.0"'
        ),
        encoding="utf-8",
    )
    before = snapshot(root)
    with pytest.raises(Refusal, match=re.escape(UNREADABLE_VERSION)) as refused:
        _upgrade(root, tmp_path)
    assert "v99" not in str(refused.value)
    assert_snapshot_unchanged(root, before)


@needs_git
def test_an_uninitialised_repository_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "bare"
    root.mkdir()
    with pytest.raises(Refusal, match=re.escape(NOT_INITIALISED)):
        _upgrade(root, tmp_path)


@needs_git
def test_a_record_naming_a_file_this_build_never_writes_is_counted_and_left(
    tmp_path: Path,
) -> None:
    # The manifest is committed, so a record is repository-authored. One claiming README.md
    # under an id this build does not produce, stamped with README.md's own bytes, must not make
    # `upgrade` touch it: which ids exist, and where each could be, are this build's. No
    # one-line mutation breaches this, because no code turns an unknown record into a template;
    # this case is the guard.
    root = initialised(tmp_path)
    readme = root / "README.md"
    readme.write_text("# ours\n", encoding="utf-8")
    manifest = Manifest.read(root)
    manifest.with_record(
        Record(
            "readme",
            Kind.TEMPLATE,
            Location.REPO,
            "README.md",
            "project/x",
            "0.0.0",
            digest("# ours\n"),
        )
    ).write(root)
    report = _upgrade(root, tmp_path)
    assert readme.read_text(encoding="utf-8") == "# ours\n"
    assert report.orphans == 1


@needs_git
def test_dropping_the_profile_retires_its_renditions_while_their_bytes_are_stayfixeds(
    tmp_path: Path,
) -> None:
    root = initialised(tmp_path)
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "[stayfixed]\n", '[stayfixed]\nprofile = "python"\n', 1
        ),
        encoding="utf-8",
    )
    _upgrade(root, tmp_path)
    assert (root / "docs" / "stayfixed" / "rules" / "python.md").is_file()
    config.write_text(
        config.read_text(encoding="utf-8").replace('profile = "python"\n', ""), encoding="utf-8"
    )
    report = _upgrade(root, tmp_path)
    removed = {a.artifact_id for a in report.footprint.actions if a.verb is Verb.REMOVE}
    assert removed == {"profile-rules", "claude-rules"}
    assert not (root / "docs" / "stayfixed" / "rules" / "python.md").exists()
    assert report.orphans == 0


@needs_git
def test_an_edited_artifact_kept_out_of_git_is_left_and_named(tmp_path: Path) -> None:
    # A local artifact has no record, and its directory is git-ignored: an edit overwritten there
    # is gone for good. So it is judged against this build's bytes, and anything else is left.
    root = initialised(
        tmp_path,
        document=f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n'
        '[project]\nname = "widget"\n\n'
        '[artifacts]\nlocal = ["roadmap"]\n',
    )
    local = root / ".stayfixed" / "local" / "artifacts" / "docs" / "roadmap.md"
    local.write_text(local.read_text(encoding="utf-8") + "\nprivate plans\n", encoding="utf-8")
    report = _upgrade(root, tmp_path)
    verbs = {a.artifact_id: a.verb for a in report.footprint.actions}
    assert verbs["roadmap"] is Verb.SKIP_MODIFIED
    assert "private plans" in local.read_text(encoding="utf-8")


@needs_git
def test_an_unedited_artifact_kept_out_of_git_follows_a_template_the_release_changed(
    tmp_path: Path, newer: Callable[[], None]
) -> None:
    # The ledger under `.stayfixed/local/` records what stayfixed wrote there, so a copy nobody
    # touched is refreshed like a committed one. With the render as its only oracle it was
    # `skip_modified` after every release that changed its template, and `uninstall` refused
    # over it, calling it edited.
    root = initialised(
        tmp_path,
        document=f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n[project]\nname = "widget"\n'
        '\n[artifacts]\nlocal = ["documentation-policy"]\n',
    )
    newer()
    report = _upgrade(root, tmp_path)
    verbs = {a.artifact_id: (a.verb, a.reason) for a in report.footprint.actions}
    assert verbs["documentation-policy"] == (Verb.UPDATE, "refreshed")
    local = root / ".stayfixed" / "local" / "artifacts" / "docs" / "architecture"
    assert "A line the next release adds." in (local / "documentation.md").read_text(
        encoding="utf-8"
    )


@needs_git
def test_a_ledger_entry_under_one_id_never_removes_another_artifact_s_copy_kept_out_of_git(
    tmp_path: Path,
) -> None:
    """The cross-id forgery. `CLAUDE.md` is kept out of git, and a clone force-adds a ledger
    whose only entry sits under `roadmap`, naming that copy with the digest of its unedited, and
    so predictable, bytes. `upgrade` plans only the footprint pass, so no template of its plan
    claimed the file, and it removed it as `roadmap`'s relocated copy: nothing in the diff, and
    no later run wrote it again. Another artifact's place kept out of git is never a left copy.

    Mutation (oracle): `mutations/`'s "a ledger entry under one id reaches another artifact's copy
    kept out of git" -> the dry run's plan already holds the removal of `CLAUDE.md`'s copy, and this
    reddens.
    """
    root = initialised(
        tmp_path,
        document=f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n[project]\nname = "widget"\n'
        '\n[artifacts]\nlocal = ["claude-md"]\n',
    )
    copy = ".stayfixed/local/artifacts/CLAUDE.md"
    assert (root / copy).is_file()
    sha = digest((root / copy).read_text(encoding="utf-8"))
    (root / ".stayfixed" / "local" / "artifacts.json").write_text(
        json.dumps({"format": 1, "artifacts": {"roadmap": {copy: sha}}}), encoding="utf-8"
    )
    before = snapshot(root)
    for dry_run in (True, False):
        report = _upgrade(root, tmp_path, dry_run=dry_run)
        assert copy not in {a.target for a in report.footprint.actions}
        assert_snapshot_unchanged(root, before)


# Where `[artifacts] local` keeps an artifact.
KEPT = ".stayfixed/local/artifacts"
# The preset's `[paths] architecture`, where `documentation-policy` lives, joined rather than
# spelled whole: `tests/test_neutral.py`'s denylist refused it spelled whole in this file.
POLICY = "/".join(("docs", "architecture"))


@needs_git
@pytest.mark.parametrize(
    ("local", "variant"),
    [
        ("claude-md", f"{KEPT}/claude.md"),
        ("documentation-policy", f"{KEPT}/{POLICY}/Documentation.md"),
    ],
    ids=["claude-md", "documentation-policy"],
)
def test_a_ledger_entry_at_a_case_variant_of_another_artifact_s_copy_reaches_nothing(
    tmp_path: Path, local: str, variant: str
) -> None:
    """The cross-id forgery with the path's case changed, and no `[paths]` edit at all: on the
    default macOS and Windows filesystems `.../claude.md` is the `CLAUDE.md` copy, and an entry
    under `roadmap` naming it with the digest of those unedited bytes had `upgrade` remove it.
    Places are compared case-folded, so it is withheld on every filesystem. The variant is
    written with the copy's own bytes first: where case folds that rewrites the copy unchanged,
    and where it does not it is a second file, so the same assertions hold on Linux.

    Mutation (oracle): `mutations/`'s "places are compared case-sensitively for ownership" -> the
    dry run already plans a removal at the variant, and the `claude-md` case reddens. The
    `documentation-policy` case is held twice: that artifact is in `upgrade`'s own plan, so the
    same-plan skip, compared case-folded too, withholds its variant as well: that guard's entry
    is `mutations/`'s "a left copy at a case variant of a file the plan targets is judged twice".
    """
    root = initialised(
        tmp_path,
        document=f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n[project]\nname = "widget"\n'
        f'\n[artifacts]\nlocal = ["{local}"]\n',
    )
    exact = {
        "claude-md": f"{KEPT}/CLAUDE.md",
        "documentation-policy": f"{KEPT}/{POLICY}/documentation.md",
    }[local]
    text = (root / exact).read_text(encoding="utf-8")
    (root / variant).write_text(text, encoding="utf-8")
    (root / ".stayfixed" / "local" / "artifacts.json").write_text(
        json.dumps({"format": 1, "artifacts": {"roadmap": {variant: digest(text)}}}),
        encoding="utf-8",
    )
    before = snapshot(root)
    for dry_run in (True, False):
        report = _upgrade(root, tmp_path, dry_run=dry_run)
        assert variant not in {a.target for a in report.footprint.actions}
        assert_snapshot_unchanged(root, before)
    assert (root / exact).read_text(encoding="utf-8") == text


@needs_git
def test_forcing_a_left_copy_away_keeps_the_committed_file_recorded(tmp_path: Path) -> None:
    # The review's repro: `roadmap` taken out of `[artifacts] local` with its copy edited, so
    # `upgrade` skips the copy and creates and records `docs/roadmap.md`; forcing the copy away
    # then dropped that record by id, and the committed file was nobody's from then on.
    root = initialised(
        tmp_path,
        document=f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n[project]\nname = "widget"\n'
        '\n[artifacts]\nlocal = ["roadmap"]\n',
    )
    copy = ".stayfixed/local/artifacts/docs/roadmap.md"
    (root / copy).write_text("private plans\n", encoding="utf-8")
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace('local = ["roadmap"]', "local = []"),
        encoding="utf-8",
    )
    _upgrade(root, tmp_path)
    recorded = Manifest.read(root).get("roadmap")
    assert recorded is not None and recorded.target == "docs/roadmap.md"
    _upgrade(root, tmp_path, force=(copy,))
    assert not (root / copy).exists()
    assert Manifest.read(root).get("roadmap") == recorded
