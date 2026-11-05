from __future__ import annotations

import os
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from stayfixed import fsops
from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.config.paths import PathEscape
from stayfixed.config.schema import Config
from stayfixed.errors import Refusal
from stayfixed.scaffold import engine
from stayfixed.scaffold.engine import apply, plan
from stayfixed.scaffold.manifest import (
    MANIFEST_PATH,
    Kind,
    Location,
    Manifest,
    Record,
    digest,
)
from stayfixed.scaffold.model import Action, Plan, Template, Verb
from stayfixed.scaffold.regions import Style, upsert

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
release_branch = "main"
"""


def a_config(tmp_path: Path) -> Config:
    (tmp_path / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    return load(tmp_path, machine=tmp_path / "absent.toml")


def a_template(**overrides: object) -> Template:
    base = Template(
        id="agents-md",
        kind=Kind.TEMPLATE,
        target="AGENTS.md",
        source="project/AGENTS.md",
        render=lambda: "BODY\n",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def a_record(**overrides: object) -> Record:
    values: dict[str, object] = {
        "id": "agents-md",
        "kind": Kind.TEMPLATE,
        "location": Location.REPO,
        "target": "AGENTS.md",
        "template": "project/AGENTS.md",
        "version": "0.1.0",
        "sha256": digest("BODY\n"),
    }
    values.update(overrides)
    return Record(**values)  # type: ignore[arg-type]


# --- whole files -------------------------------------------------------------------------


def test_an_unrecorded_absent_file_is_created(tmp_path: Path) -> None:
    result = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert [(a.verb, a.target, a.payload) for a in result.actions] == [
        (Verb.CREATE, "AGENTS.md", "BODY\n")
    ]


def test_an_unrecorded_present_file_is_never_clobbered(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("someone wrote this\n", encoding="utf-8")
    result = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert [a.verb for a in result.actions] == [Verb.SKIP_MODIFIED]


def test_a_recorded_unchanged_file_yields_no_action(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("BODY\n", encoding="utf-8")
    Manifest({}).with_record(a_record()).write(tmp_path)
    result = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert result.actions == ()
    assert result.unchanged == ("agents-md",)


def test_a_recorded_file_the_tool_wrote_is_updated(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("BODY\n", encoding="utf-8")
    Manifest({}).with_record(a_record()).write(tmp_path)
    result = plan(tmp_path, a_config(tmp_path), [a_template(render=lambda: "NEWER\n")])
    assert [(a.verb, a.payload) for a in result.actions] == [(Verb.UPDATE, "NEWER\n")]


def test_a_hand_edited_file_is_skipped_and_named(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("edited by hand\n", encoding="utf-8")
    Manifest({}).with_record(a_record()).write(tmp_path)
    result = plan(tmp_path, a_config(tmp_path), [a_template(render=lambda: "NEWER\n")])
    assert [(a.verb, a.target) for a in result.actions] == [(Verb.SKIP_MODIFIED, "AGENTS.md")]


def test_a_once_artifact_is_never_updated(tmp_path: Path) -> None:
    # `skip_modified` and not `unchanged`: a file that is present with no record is `skip_modified`
    # for a `template` or a `once` kind, and `unchanged` renders as "up to date" for a file
    # stayfixed deliberately never looks inside again. The user needs "left alone because it is
    # yours", which is the statement that is true.
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    template = a_template(id="claude-md", kind=Kind.ONCE, target="CLAUDE.md")
    result = plan(tmp_path, a_config(tmp_path), [template])
    assert [(a.verb, a.target) for a in result.actions] == [(Verb.SKIP_MODIFIED, "CLAUDE.md")]
    assert result.unchanged == ()
    before = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert apply(tmp_path, result).skipped == ("CLAUDE.md",)
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == before


def test_a_manifest_naming_a_target_outside_the_root_plans_nothing_for_it(tmp_path: Path) -> None:
    # The manifest is committed, so `record.target` is repository-controlled input.
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "outside.md").write_text("BODY\n", encoding="utf-8")
    Manifest({}).with_record(a_record(target="../outside.md")).write(root)
    config = a_config(root)
    result = plan(root, config, [a_template()])
    # Said out loud, not silent. The file is still not touched — that is the property — but a
    # record naming a file stayfixed will not remove is something the report has to carry, or
    # the artifact is created at its new target with the old one left on disk and nothing said.
    assert [a.verb for a in result.actions] == [Verb.SKIP_MODIFIED, Verb.CREATE]
    assert result.actions[0].target == "../outside.md"
    assert (tmp_path / "outside.md").exists()


def test_a_recorded_target_this_template_could_never_produce_is_not_a_relocation(
    tmp_path: Path,
) -> None:
    # Both halves of "is this file ours" come out of the committed manifest: the recorded target
    # and the recorded hash. So without a guard, naming any file in the root and stamping it with
    # the bytes it is committed with is enough to make `plan` emit a REMOVE for it — and a
    # mismatch between the recorded target and the template's is all it takes.
    victim = tmp_path / ".claude"
    victim.mkdir()
    settings = victim / "settings.json"
    before = '{"permissions": {"deny": ["Read(./.env)"]}}\n'
    settings.write_text(before, encoding="utf-8")
    record = a_record(target=".claude/settings.json", sha256=digest(before))
    Manifest({}).with_record(record).write(tmp_path)
    planned = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert [(a.verb, a.target) for a in planned.actions] == [
        (Verb.SKIP_MODIFIED, ".claude/settings.json"),
        (Verb.CREATE, "AGENTS.md"),
    ]
    applied = apply(tmp_path, planned)
    assert settings.read_text(encoding="utf-8") == before
    assert applied.skipped == (".claude/settings.json",)


# --- regions, which live inside somebody else's file -------------------------------------


def test_a_managed_region_is_installed_into_a_file_no_record_covers(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("PROSE\n", encoding="utf-8")
    template = a_template(kind=Kind.MANAGED_REGION, region="harness", render=lambda: "R1")
    first = plan(tmp_path, a_config(tmp_path), [template])
    assert first.actions[0].verb is Verb.REGION_UPDATE
    assert first.actions[0].payload is not None
    assert first.actions[0].payload.startswith("PROSE\n")
    assert "R1" in first.actions[0].payload


def test_a_region_already_current_yields_no_action(tmp_path: Path) -> None:
    text = upsert("PROSE\n", "harness", "R1", Style.MARKDOWN)
    (tmp_path / "AGENTS.md").write_text(text, encoding="utf-8")
    Manifest({}).with_record(a_record(kind=Kind.MANAGED_REGION, sha256=digest("R1"))).write(
        tmp_path
    )
    template = a_template(kind=Kind.MANAGED_REGION, region="harness", render=lambda: "R1")
    assert plan(tmp_path, a_config(tmp_path), [template]).actions == ()


def test_prose_around_a_region_may_change_without_reading_as_a_hand_edit(tmp_path: Path) -> None:
    text = upsert("PROSE\n", "harness", "R1", Style.MARKDOWN) + "a paragraph the user added\n"
    (tmp_path / "AGENTS.md").write_text(text, encoding="utf-8")
    Manifest({}).with_record(a_record(kind=Kind.MANAGED_REGION, sha256=digest("R1"))).write(
        tmp_path
    )
    template = a_template(kind=Kind.MANAGED_REGION, region="harness", render=lambda: "R2")
    assert [a.verb for a in plan(tmp_path, a_config(tmp_path), [template]).actions] == [
        Verb.REGION_UPDATE
    ]


def test_a_hand_edited_region_body_is_skipped(tmp_path: Path) -> None:
    text = upsert("PROSE\n", "harness", "EDITED BY HAND", Style.MARKDOWN)
    (tmp_path / "AGENTS.md").write_text(text, encoding="utf-8")
    Manifest({}).with_record(a_record(kind=Kind.MANAGED_REGION, sha256=digest("R1"))).write(
        tmp_path
    )
    template = a_template(kind=Kind.MANAGED_REGION, region="harness", render=lambda: "R2")
    assert [a.verb for a in plan(tmp_path, a_config(tmp_path), [template]).actions] == [
        Verb.SKIP_MODIFIED
    ]


# --- refusals ------------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["../outside.md", "/etc/stayfixed.md", "docs/../../x.md", ""])
def test_an_escaping_target_is_refused_not_planned(tmp_path: Path, target: str) -> None:
    result = plan(tmp_path, a_config(tmp_path), [a_template(target=target)])
    assert result.actions == ()
    assert [r.artifact_id for r in result.refusals] == ["agents-md"]


def test_one_refused_template_does_not_hide_the_others(tmp_path: Path) -> None:
    result = plan(
        tmp_path,
        a_config(tmp_path),
        [a_template(id="bad", target="../x"), a_template(id="good", target="GOOD.md")],
    )
    assert [a.artifact_id for a in result.actions] == ["good"]
    assert [r.artifact_id for r in result.refusals] == ["bad"]


def test_an_unreadable_file_refuses_only_its_own_artifact(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes(b"\xff\xfe not utf-8 \xff")
    result = plan(
        tmp_path,
        a_config(tmp_path),
        [a_template(), a_template(id="good", target="GOOD.md")],
    )
    assert [a.artifact_id for a in result.actions] == ["good"]
    assert [r.artifact_id for r in result.refusals] == ["agents-md"]


def test_a_file_past_the_read_cap_refuses_only_its_own_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An artifact's file is one a clone commits, so the engine reads it to the read cap, as every
    # reader of a committed file reads one, and a file past it is a refusal for its own artifact,
    # never one read to its end. The cap is lowered so the file is small. Mutation (oracle):
    # `mutations/`'s "the scaffold engine reads an artifact's file with no bound" -> it is read.
    limit = 4 * 1024
    (tmp_path / "AGENTS.md").write_text("BODY\n" + "#" * limit, encoding="utf-8")
    config = a_config(tmp_path)
    monkeypatch.setattr(fsops, "REGULAR_READ_LIMIT", limit)
    result = plan(tmp_path, config, [a_template(), a_template(id="good", target="GOOD.md")])
    assert [a.artifact_id for a in result.actions] == ["good"]
    assert [r.artifact_id for r in result.refusals] == ["agents-md"]
    assert "larger than this reader reads" in result.refusals[0].reason


@pytest.mark.parametrize(
    ("shape", "reason"),
    [
        ("a directory", "AGENTS.md cannot be read (not a regular file)"),
        ("past the cap", "AGENTS.md cannot be read (larger than this reader reads)"),
        ("not UTF-8", "AGENTS.md is not UTF-8 text"),
    ],
    ids=["directory", "too-large", "not-utf8"],
)
def test_an_unreadable_artifact_is_named_relative_to_the_project_with_the_reason_in_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str, reason: str
) -> None:
    # The refusal named the file by its absolute path, twice — once of its own and once inside
    # the raw `OSError` it quoted — where every other refusal names it relative to the project and
    # says the reason in words: `AGENTS.md  (/…/AGENTS.md cannot be read: [Errno 22] not a regular
    # file: '/…/AGENTS.md')`. The path is a configured target a clone may choose. Mutation:
    # `mutations/`'s "the scaffold engine names an unreadable artifact by its absolute path".
    monkeypatch.setattr(fsops, "REGULAR_READ_LIMIT", 4 * 1024)
    agents = tmp_path / "AGENTS.md"
    if shape == "a directory":
        agents.mkdir()
    elif shape == "past the cap":
        agents.write_text("#" * 8 * 1024, encoding="utf-8")
    else:
        agents.write_bytes(b"\xff\xfe not utf-8 \xff")
    result = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert [r.reason for r in result.refusals] == [reason]


def test_a_fifo_at_an_artifacts_place_is_its_refusal_and_never_waited_on(tmp_path: Path) -> None:
    # A FIFO cannot be committed, but a local process can leave one where an artifact goes, and
    # the engine opened it for reading and waited for a writer that never came: `init` and
    # `upgrade` hung. It is read as a regular file only, so the FIFO is this artifact's refusal. In
    # a child under a timeout, so a regression fails this case rather than hanging. Mutation
    # (oracle): `mutations/`'s "the scaffold engine reads an artifact's file with no bound" -> the
    # child waits and this times out.
    a_config(tmp_path)
    os.mkfifo(tmp_path / "AGENTS.md")
    probe = (
        "import sys\n"
        "from pathlib import Path\n"
        "from stayfixed.config.loader import load\n"
        "from stayfixed.scaffold.engine import plan\n"
        "from stayfixed.scaffold.manifest import Kind\n"
        "from stayfixed.scaffold.model import Template\n"
        "root = Path(sys.argv[1])\n"
        "template = Template(id='agents-md', kind=Kind.TEMPLATE, target='AGENTS.md',\n"
        "    source='project/AGENTS.md', render=lambda: 'BODY\\n')\n"
        "config = load(root, machine=root / 'absent.toml')\n"
        "print([r.artifact_id for r in plan(root, config, [template]).refusals])\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the engine waited on a FIFO at an artifact's place")
    assert done.stdout == "['agents-md']\n", done.stderr


def test_a_doubled_region_marker_refuses_only_its_own_artifact(tmp_path: Path) -> None:
    # A bad merge, not an internal bug. The engine answers it with a refusal for this one artifact,
    # and `render_report`'s REFUSED section exists to name exactly these — which it can only do if a
    # plan is returned at all.
    (tmp_path / "AGENTS.md").write_text(
        "PROSE\n"
        "<!-- stayfixed:harness:begin -->\nfirst\n<!-- stayfixed:harness:end -->\n"
        "<!-- stayfixed:harness:begin -->\nsecond\n<!-- stayfixed:harness:end -->\n",
        encoding="utf-8",
    )
    result = plan(
        tmp_path,
        a_config(tmp_path),
        [
            a_template(kind=Kind.MANAGED_REGION, region="harness", render=lambda: "R1"),
            a_template(id="good", target="GOOD.md"),
        ],
    )
    assert [(r.artifact_id, "twice" in r.reason) for r in result.refusals] == [("agents-md", True)]
    assert [(a.artifact_id, a.verb) for a in result.actions] == [("good", Verb.CREATE)]


def test_a_template_naming_no_region_raises_rather_than_becoming_a_refusal(tmp_path: Path) -> None:
    # The boundary of what `plan` converts into a per-artifact refusal. A `MANAGED_REGION`
    # template carrying no region name is a malformed `Template`, so it is a bug in the caller
    # that built it; recording it beside the user's own bad merges would hide it.
    template = a_template(kind=Kind.MANAGED_REGION, region=None, render=lambda: "R1")
    (tmp_path / "AGENTS.md").write_text("PROSE\n", encoding="utf-8")
    with pytest.raises(Refusal, match="names no region"):
        plan(tmp_path, a_config(tmp_path), [template])


def test_a_file_carrying_only_a_region_end_marker_is_refused_and_left_alone(
    tmp_path: Path,
) -> None:
    # A begin line somebody deleted, or a merge that kept one side's end marker. Read as "region
    # absent", the first run appended a fresh block and wrote a second end marker itself, and
    # every run after that refused a file stayfixed had broken — `uninstall` included.
    before = "Prose.\n<!-- stayfixed:harness:end -->\n"
    (tmp_path / "AGENTS.md").write_text(before, encoding="utf-8")
    template = a_template(kind=Kind.MANAGED_REGION, region="harness", render=lambda: "R1")
    first = plan(tmp_path, a_config(tmp_path), [template])
    assert first.actions == ()
    assert [(r.artifact_id, "no beginning" in r.reason) for r in first.refusals] == [
        ("agents-md", True)
    ]
    with pytest.raises(Refusal):
        apply(tmp_path, first)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == before


# --- apply ----------------------------------------------------------------------------------


def test_apply_writes_the_payload_and_records_it(tmp_path: Path) -> None:
    config = a_config(tmp_path)
    result = apply(tmp_path, plan(tmp_path, config, [a_template()]))
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "BODY\n"
    assert result.written == ("AGENTS.md",)
    assert Manifest.read(tmp_path).get("agents-md") is not None


def test_apply_refuses_a_plan_carrying_a_refusal(tmp_path: Path) -> None:
    config = a_config(tmp_path)
    planned = plan(tmp_path, config, [a_template(target="../outside.md")])
    with pytest.raises(Refusal, match="refused"):
        apply(tmp_path, planned)


def test_a_symlink_planted_between_plan_and_apply_is_refused(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    config = a_config(tmp_path)
    (tmp_path / "docs").mkdir()
    planned = plan(tmp_path, config, [a_template(target="docs/AGENTS.md")])
    (tmp_path / "docs").rmdir()
    (tmp_path / "docs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(Refusal):
        apply(tmp_path, planned)
    assert list(outside.iterdir()) == []


def test_apply_refuses_a_dotdot_target_no_symlink_walk_would_catch(tmp_path: Path) -> None:
    # The plan is built by hand because `plan()` would refuse this target and `apply()` would
    # then stop on the refusal instead of on the guard under test. `..` is an ordinary
    # directory entry, so `open_within`'s O_NOFOLLOW walk opens it without objecting: the
    # `contained()` call `apply` makes at write time is the only thing between this action and
    # a write outside the root.
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    action = Action(Verb.CREATE, "agents-md", f"../{outside.name}/AGENTS.md", "BODY\n", "new", None)
    with pytest.raises(PathEscape, match=r"\.\."):
        apply(tmp_path, Plan(actions=(action,)))
    assert list(outside.iterdir()) == []


def test_the_write_refuses_a_symlinked_parent_containment_never_saw(tmp_path: Path) -> None:
    # The writer is called directly, with no `contained()` ahead of it, because that is the
    # shape of the race this layer exists to close: the check has already passed by the time a
    # component becomes a symlink. Nothing at all follows the link — not the content, and not
    # the parent directories, because `_mkdirs_within` creates those through the same
    # O_NOFOLLOW walk instead of handing the string to `Path.mkdir`.
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "docs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(Refusal):
        engine._write(tmp_path, "docs/deep/AGENTS.md", "BODY\n")
    assert list(outside.iterdir()) == []


def test_a_skipped_artifact_is_reported_and_not_written(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("mine\n", encoding="utf-8")
    config = a_config(tmp_path)
    result = apply(tmp_path, plan(tmp_path, config, [a_template()]))
    assert result.skipped == ("AGENTS.md",)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "mine\n"


def test_no_temporary_file_survives_a_write(tmp_path: Path) -> None:
    config = a_config(tmp_path)
    apply(tmp_path, plan(tmp_path, config, [a_template()]))
    assert sorted(p.name for p in tmp_path.iterdir()) == [".stayfixed", "AGENTS.md", CONFIG_FILE]


def test_an_updated_file_keeps_the_mode_it_had(tmp_path: Path) -> None:
    config = a_config(tmp_path)
    apply(tmp_path, plan(tmp_path, config, [a_template()]))
    os.chmod(tmp_path / "AGENTS.md", 0o664)
    apply(tmp_path, plan(tmp_path, config, [a_template(render=lambda: "NEWER\n")]))
    assert stat.S_IMODE((tmp_path / "AGENTS.md").stat().st_mode) == 0o664


def test_a_created_file_is_readable_by_more_than_its_owner(tmp_path: Path) -> None:
    config = a_config(tmp_path)
    apply(tmp_path, plan(tmp_path, config, [a_template()]))
    assert stat.S_IMODE((tmp_path / "AGENTS.md").stat().st_mode) == 0o644


def test_a_committed_symlink_at_dot_stayfixed_refuses_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # git stores symlinks, so a clone materialises this one, and no race is needed: without a
    # containment check the manifest — records and all — is written wherever the link points.
    root = tmp_path / "project"
    root.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    (root / ".stayfixed").symlink_to(victim, target_is_directory=True)
    config = a_config(root)
    with pytest.raises(PathEscape, match="symlink"):
        plan(root, config, [a_template()])
    assert list(victim.iterdir()) == []
    assert not (root / "AGENTS.md").exists()


def test_dot_stayfixed_symlinked_after_the_plan_makes_apply_refuse(tmp_path: Path) -> None:
    # The same escape in the race shape the dry run cannot see: the plan was clean when the
    # user read it. `apply` must refuse with nothing written, inside the root or outside it.
    root = tmp_path / "project"
    root.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    config = a_config(root)
    planned = plan(root, config, [a_template()])
    (root / ".stayfixed").symlink_to(victim, target_is_directory=True)
    with pytest.raises(PathEscape, match="symlink"):
        apply(root, planned)
    assert list(victim.iterdir()) == []
    assert not (root / "AGENTS.md").exists()


def test_a_file_where_a_directory_belongs_refuses_rather_than_raising_oserror(
    tmp_path: Path,
) -> None:
    # No race and no symlink: the user saves a file at `docs` while reading the dry-run report,
    # then confirms. A bare `OSError` here reaches the CLI as a traceback instead of the exit 2
    # a refusal is for.
    config = a_config(tmp_path)
    planned = plan(tmp_path, config, [a_template(id="doc", target="docs/README.md")])
    (tmp_path / "docs").write_text("a file the user just saved\n", encoding="utf-8")
    with pytest.raises(Refusal):
        apply(tmp_path, planned)
    assert (tmp_path / "docs").read_text(encoding="utf-8") == "a file the user just saved\n"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the directory mode under test")
def test_a_directory_that_cannot_be_created_refuses_rather_than_raising_oserror(
    tmp_path: Path,
) -> None:
    # The other half of "no bare OSError": a parent directory stayfixed may read but not write
    # to. `open_within` opens it happily — r-x is enough — so this arrives as EACCES from
    # `os.mkdir` rather than as an `UnsafePath`, and only the broad clause turns it into exit 2.
    (tmp_path / "docs").mkdir()
    os.chmod(tmp_path / "docs", stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(Refusal, match="cannot be written"):
            engine._write(tmp_path, "docs/specs/README.md", "S\n")
    finally:
        os.chmod(tmp_path / "docs", 0o755)
    assert not (tmp_path / "docs" / "specs").exists()


def test_crlf_endings_outside_a_managed_region_survive_plan_and_apply(tmp_path: Path) -> None:
    # `regions.py` promises to return every byte outside its own markers unchanged, and
    # `test_regions.py` proves it by calling `upsert` directly. This measures the same property
    # where a user meets it: a universal-newline read rewrites every ending in the file before
    # `upsert` is ever reached, so the promise is kept or broken here, not there.
    before = b"# Title\r\n\r\nProse the tool must never touch.\r\n"
    (tmp_path / "AGENTS.md").write_bytes(before)
    template = a_template(kind=Kind.MANAGED_REGION, region="harness", render=lambda: "R1")
    apply(tmp_path, plan(tmp_path, a_config(tmp_path), [template]))
    assert (tmp_path / "AGENTS.md").read_bytes() == before + (
        b"<!-- stayfixed:harness:begin -->\r\nR1\r\n<!-- stayfixed:harness:end -->\r\n"
    )


def test_apply_records_the_files_it_wrote_before_a_later_action_refused(tmp_path: Path) -> None:
    # The ledger describes the disk, so it cannot be discarded for actions that already ran. A
    # file stayfixed wrote and did not record reads as somebody else's on every later run:
    # `skip_modified` under a reason that is false, moved only by a `--force` that names it, and
    # invisible to `uninstall`.
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    config = a_config(tmp_path)
    (tmp_path / "docs").mkdir()
    planned = plan(
        tmp_path,
        config,
        [
            a_template(id="first", target="A.md", render=lambda: "A\n"),
            a_template(id="second", target="docs/B.md", render=lambda: "B\n"),
        ],
    )
    (tmp_path / "docs").rmdir()
    (tmp_path / "docs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(Refusal):
        apply(tmp_path, planned)
    assert (tmp_path / "A.md").read_text(encoding="utf-8") == "A\n"
    recorded = Manifest.read(tmp_path)
    assert recorded.get("first") is not None
    assert recorded.get("second") is None


def test_a_plan_carrying_a_refusal_creates_no_manifest_at_all(tmp_path: Path) -> None:
    # The boundary of persisting progress. `apply` refuses a plan carrying a refusal before it
    # reaches the first action, so there is nothing on disk to record and no ledger to create.
    config = a_config(tmp_path)
    planned = plan(tmp_path, config, [a_template(target="../outside.md")])
    with pytest.raises(Refusal, match="refused"):
        apply(tmp_path, planned)
    assert not (tmp_path / MANIFEST_PATH).exists()


# --- the two rules the module docstring is read for ------------------------------------------


def test_the_module_docstring_names_every_input_plan_raises_for() -> None:
    # A consumer reads this docstring to decide what to catch. It named two inputs while the
    # module raises for three: a `MANAGED_REGION` template carrying no region name is a malformed
    # `Template`, and the test above pins that `plan` deliberately does not soften it into a
    # per-artifact refusal.
    prose = " ".join((engine.__doc__ or "").split())
    assert "and a malformed `Template`" in prose


def test_the_containment_docstring_claims_the_property_the_walk_actually_holds() -> None:
    # A component certainly can become a symlink after `contained()` has passed — two tests
    # above plant one for exactly that reason — so "there is no window" described a guarantee
    # nothing provides. What the O_NOFOLLOW walk holds is narrower and is the thing that
    # matters: the link cannot redirect the write.
    prose = " ".join((engine.__doc__ or "").split())
    assert "it cannot redirect the write" in prose
    assert "there is no window in which a component can become a symlink" not in prose


def test_a_record_at_a_case_variant_of_the_target_is_that_file_and_never_a_relocation(
    tmp_path: Path,
) -> None:
    # A record at `agents.md` for an artifact at `AGENTS.md`, as a case-only `[paths]` edit leaves
    # it. Where case folds they are one file, and a relocation "from" `agents.md` removed the
    # artifact's own file (`relocated`) beside an `unchanged` verdict for it, then dropped its
    # record. Asserted on the plan, which is the same string rule on every filesystem.
    # Mutation (oracle): `mutations/`'s "a record at a case variant of the target triggers a
    # relocation" -> the plan holds a `skip_modified` for `agents.md` and this reddens.
    config = a_config(tmp_path)
    (tmp_path / "AGENTS.md").write_text("BODY\n", encoding="utf-8")
    Manifest({}).with_record(a_record(target="agents.md")).write(tmp_path)
    planned = plan(tmp_path, config, [a_template()])
    assert planned.actions == ()
    assert planned.unchanged == ("agents-md",)
