"""The ledger of what stayfixed last wrote under `.stayfixed/local/artifacts/`, and the engine rules
that read it: an unedited copy follows a changed template, a copy whose id left `[artifacts]
local` is retired, and a ledger a clone wrote reaches nothing but bytes it already names."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from stayfixed.scaffold import engine
from stayfixed.scaffold.engine import apply, plan
from stayfixed.scaffold.local import LOCAL_DIGESTS, MAX_BYTES, MAX_ENTRIES, LocalDigests
from stayfixed.scaffold.manifest import Manifest, digest
from stayfixed.scaffold.model import Verb
from tests.scaffold.test_engine import a_config, a_record, a_template

LOCAL = ".stayfixed/local/artifacts/AGENTS.md"
OTHER = ".stayfixed/local/artifacts/other.md"


def _written(tmp_path: Path, render: str = "BODY\n") -> None:
    """`agents-md` written kept out of git, rendering `render`."""
    config = a_config(tmp_path, local=("agents-md",))
    apply(tmp_path, plan(tmp_path, config, [a_template(render=lambda: render)]))


def _ledger(tmp_path: Path, artifacts: object, **extra: object) -> None:
    path = tmp_path / LOCAL_DIGESTS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": 1, "artifacts": artifacts, **extra}), encoding="utf-8")


def test_a_write_kept_out_of_git_is_recorded_in_the_ledger_and_never_in_the_manifest(
    tmp_path: Path,
) -> None:
    _written(tmp_path)
    assert LocalDigests.read(tmp_path).entries == {("agents-md", LOCAL): digest("BODY\n")}
    assert Manifest.read(tmp_path).records == {}


def test_a_footprint_with_nothing_kept_out_of_git_writes_no_ledger(tmp_path: Path) -> None:
    apply(tmp_path, plan(tmp_path, a_config(tmp_path), [a_template()]))
    assert not (tmp_path / ".stayfixed" / "local").exists()


def test_an_unedited_copy_follows_a_changed_template(tmp_path: Path) -> None:
    # With the render as the only oracle, every unedited copy read as somebody's after a release
    # changed its template: `skip_modified`, and `uninstall` refused over it. The ledger says
    # these are the bytes stayfixed wrote. Mutation (oracle): `mutations/`'s "an unedited artifact
    # kept out of git is skipped as not stayfixed's once its template changes" -> the verb is
    # `skip_modified`.
    _written(tmp_path)
    config = a_config(tmp_path, local=("agents-md",))
    planned = plan(tmp_path, config, [a_template(render=lambda: "BODY 2\n")])
    assert [(a.verb, a.reason) for a in planned.actions] == [(Verb.UPDATE, "refreshed")]
    apply(tmp_path, planned)
    assert (tmp_path / LOCAL).read_text(encoding="utf-8") == "BODY 2\n"
    assert LocalDigests.read(tmp_path).entries == {("agents-md", LOCAL): digest("BODY 2\n")}


def test_an_edited_copy_is_named_as_changed_and_with_no_ledger_as_unrecorded(
    tmp_path: Path,
) -> None:
    # Neither reason calls the file edited unless the ledger shows stayfixed wrote other bytes
    # there. With the ledger gone the file is judged by the render alone, as before it existed.
    _written(tmp_path)
    (tmp_path / LOCAL).write_text("BODY\nours\n", encoding="utf-8")
    config = a_config(tmp_path, local=("agents-md",))
    changed = plan(tmp_path, config, [a_template()])
    assert [(a.verb, a.reason) for a in changed.actions] == [
        (Verb.SKIP_MODIFIED, engine.CHANGED_LOCALLY)
    ]
    (tmp_path / LOCAL_DIGESTS).unlink()
    (tmp_path / LOCAL).write_text("BODY\n", encoding="utf-8")
    assert plan(tmp_path, config, [a_template()]).unchanged == ("agents-md",)
    unrecorded = plan(tmp_path, config, [a_template(render=lambda: "BODY 2\n")])
    assert [(a.verb, a.reason) for a in unrecorded.actions] == [
        (Verb.SKIP_MODIFIED, engine.NOT_OURS_LOCALLY)
    ]


def test_a_copy_whose_id_left_the_list_is_retired_while_its_bytes_are_stayfixeds(
    tmp_path: Path,
) -> None:
    # Nothing ever judged it again: `upgrade` created the committed file and left the copy, and
    # `uninstall` refused over it for good with a `--force` no action could reach. Mutation
    # (oracle): `mutations/`'s "a copy left kept out of git when its id left [artifacts] local is
    # never judged" -> the plan holds the create alone.
    _written(tmp_path)
    config = a_config(tmp_path)
    planned = plan(tmp_path, config, [a_template(render=lambda: "BODY 2\n")])
    assert [(a.verb, a.target, a.reason) for a in planned.actions] == [
        (Verb.REMOVE, LOCAL, "relocated"),
        (Verb.CREATE, "AGENTS.md", "new"),
    ]
    apply(tmp_path, planned)
    assert not (tmp_path / LOCAL).exists() and (tmp_path / "AGENTS.md").is_file()
    assert LocalDigests.read(tmp_path).entries == {}


def test_a_changed_copy_whose_id_left_the_list_is_named(tmp_path: Path) -> None:
    _written(tmp_path)
    (tmp_path / LOCAL).write_text("BODY\nours\n", encoding="utf-8")
    config = a_config(tmp_path)
    planned = plan(tmp_path, config, [a_template()])
    assert [(a.verb, a.target, a.reason) for a in planned.actions] == [
        (Verb.SKIP_MODIFIED, LOCAL, engine.LEFT_LOCALLY),
        (Verb.CREATE, "AGENTS.md", "new"),
    ]


def test_an_unreadable_copy_left_kept_out_of_git_is_named_where_it_is(tmp_path: Path) -> None:
    # The reason names the copy it is about, which is not the artifact's committed target the plan
    # creates beside it. Mutation: `mutations/`'s "a left copy that cannot be read is named by the
    # artifact's target".
    _written(tmp_path)
    (tmp_path / LOCAL).unlink()
    (tmp_path / LOCAL).mkdir()
    planned = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert [(a.verb, a.target, a.reason) for a in planned.actions] == [
        (Verb.SKIP_MODIFIED, LOCAL, f"{LOCAL} cannot be read (not a regular file)"),
        (Verb.CREATE, "AGENTS.md", "new"),
    ]


def test_a_ledger_entry_away_from_the_artifact_s_own_place_vouches_only_by_its_digest(
    tmp_path: Path,
) -> None:
    # A clone can force-add the ledger. An entry naming another file under the directory reaches
    # it only while the file's bytes digest to exactly what the entry states, bytes its writer
    # already names; the render vouches only at the artifact's own place, so a file there that
    # happens to hold this build's bytes is left and named, and so is one with other bytes.
    # Mutation (oracle): `mutations/`'s "a left copy away from its own place goes on the render
    # alone" -> the file holding the render is removed and the first assertion reddens.
    other = tmp_path / OTHER
    other.parent.mkdir(parents=True)
    other.write_text("BODY\n", encoding="utf-8")
    _ledger(tmp_path, {"agents-md": {OTHER: digest("something else\n")}})
    planned = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert [(a.verb, a.target) for a in planned.actions] == [
        (Verb.SKIP_MODIFIED, OTHER),
        (Verb.CREATE, "AGENTS.md"),
    ]
    apply(tmp_path, planned)
    assert other.is_file()
    _ledger(tmp_path, {"agents-md": {OTHER: digest("BODY\n")}})
    planned = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert [(a.verb, a.target, a.reason) for a in planned.actions] == [
        (Verb.REMOVE, OTHER, "relocated")
    ]


@pytest.mark.parametrize(
    ("artifacts", "extra"),
    [
        # Outside `LOCAL_ARTIFACTS`: a committed file, attach's ledger, a parent segment.
        ({"agents-md": {"AGENTS.md": "0" * 64}}, {}),
        ({"agents-md": {".stayfixed/local/attach.json": "0" * 64}}, {}),
        ({"agents-md": {".stayfixed/local/artifacts/../x": "0" * 64}}, {}),
        # Not this module's shape.
        ({"agents-md": {LOCAL: "zz"}}, {}),
        ({"Agents\x1b[31m": {LOCAL: "0" * 64}}, {}),
        ({"agents-md": [LOCAL, "0" * 64]}, {}),
        ({"agents-md": {LOCAL: 7}}, {}),
        ([], {}),
        ({"agents-md": {LOCAL: "0" * 64}}, {"format": 2}),
    ],
)
def test_a_ledger_that_is_not_exactly_this_shape_is_absent(
    tmp_path: Path, artifacts: object, extra: dict[str, object]
) -> None:
    # A fault anywhere makes the whole ledger absent, which only sends the engine back to the
    # render rule. Mutation (oracle): `mutations/`'s "a ledger entry may name a file outside the
    # artifacts directory" -> the first two cases read as entries.
    _ledger(tmp_path, artifacts, **extra)
    assert LocalDigests.read(tmp_path).entries == {}


def test_an_oversized_unparsable_or_redirected_ledger_is_absent(tmp_path: Path) -> None:
    path = tmp_path / LOCAL_DIGESTS
    path.parent.mkdir(parents=True)
    entry = {"agents-md": {LOCAL: "0" * 64}}
    body = json.dumps({"format": 1, "artifacts": entry})
    path.write_text(body + " " * MAX_BYTES, encoding="utf-8")
    assert LocalDigests.read(tmp_path).entries == {}
    path.write_text("{" * 100_000, encoding="utf-8")
    assert LocalDigests.read(tmp_path).entries == {}
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(body, encoding="utf-8")
    path.unlink()
    path.symlink_to(elsewhere)
    assert LocalDigests.read(tmp_path).entries == {}
    path.unlink()
    os.mkfifo(path)
    assert LocalDigests.read(tmp_path).entries == {}
    path.unlink()
    path.write_text(body, encoding="utf-8")
    assert LocalDigests.read(tmp_path).entries == {("agents-md", LOCAL): "0" * 64}


@pytest.mark.parametrize("edited", [False, True], ids=["committed-untouched", "committed-edited"])
def test_removing_a_left_copy_keeps_the_record_of_the_committed_file(
    tmp_path: Path, edited: bool
) -> None:
    # The left copy's removal carries the artifact's id, and `apply` dropped the manifest record
    # by id alone: the committed file's live record went with the copy, `upgrade` then reported
    # the file unchanged for ever without recording it, and `uninstall` left it unlisted.
    # Mutation (oracle): `mutations/`'s "removing a file drops the record of whatever file its
    # artifact now names" -> the record is gone and the last assertion reddens.
    _written(tmp_path)
    committed = "BODY\nours\n" if edited else "BODY\n"
    (tmp_path / "AGENTS.md").write_text(committed, encoding="utf-8")
    Manifest({}).with_record(a_record()).write(tmp_path)
    planned = plan(tmp_path, a_config(tmp_path), [a_template()])
    assert (Verb.REMOVE, LOCAL) in {(a.verb, a.target) for a in planned.actions}
    apply(tmp_path, planned)
    assert not (tmp_path / LOCAL).exists()
    assert Manifest.read(tmp_path).get("agents-md") == a_record()


def test_a_left_copy_at_a_file_another_template_of_the_plan_targets_is_that_template_s(
    tmp_path: Path,
) -> None:
    # A stale entry, or `[paths]` values swapped, can put an artifact's left copy on the file
    # another artifact of the same plan now targets. That template judges its own file; judged
    # twice, the left copy's removal deleted it from under an `unchanged` verdict. Mutation
    # (oracle): `mutations/`'s "a left copy at a file another template of the plan targets is judged
    # twice" -> the plan removes the file and this reddens.
    _written(tmp_path)
    _ledger(
        tmp_path,
        {"agents-md": {LOCAL: digest("BODY\n")}, "roadmap": {LOCAL: digest("BODY\n")}},
    )
    config = a_config(tmp_path, local=("agents-md", "roadmap"))
    roadmap = a_template(id="roadmap", target="docs/roadmap.md", render=lambda: "R\n")
    planned = plan(tmp_path, config, [a_template(), roadmap])
    assert [(a.verb, a.target) for a in planned.actions] == [
        (Verb.CREATE, ".stayfixed/local/artifacts/docs/roadmap.md")
    ]
    apply(tmp_path, planned)
    assert (tmp_path / LOCAL).read_text(encoding="utf-8") == "BODY\n"


class _AgentsMdOwnsItsFile:
    """The one answer the engine asks of the ownership relation, stubbed: `AGENTS.md` is
    `agents-md`'s. The real relation is the project area's (`project.templates.Owners`), which
    `scaffold` does not import, and neither does its test."""

    def foreign(self, artifact_id: str, place: str) -> frozenset[str]:
        return frozenset({"agents-md"} - {artifact_id}) if place == "AGENTS.md" else frozenset()


def test_an_entry_under_one_id_never_names_another_artifact_s_place_kept_out_of_git(
    tmp_path: Path,
) -> None:
    # `AGENTS.md` is a place `owners` gives `agents-md`, so `LOCAL_ARTIFACTS/AGENTS.md` is that
    # artifact's copy, judged under its own id. A forged entry under `roadmap` naming it with its
    # unedited digest removed it when no template of the plan targeted it. Mutation (oracle):
    # `mutations/`'s "a ledger entry under one id reaches another artifact's copy kept out of git"
    # -> the plan holds a `REMOVE` of that copy.
    _written(tmp_path)
    _ledger(tmp_path, {"roadmap": {LOCAL: digest("BODY\n")}})
    roadmap = a_template(id="roadmap", target="docs/roadmap.md", render=lambda: "R\n")
    planned = plan(tmp_path, a_config(tmp_path), [roadmap], owners=_AgentsMdOwnsItsFile())
    assert LOCAL not in {a.target for a in planned.actions}
    apply(tmp_path, planned)
    assert (tmp_path / LOCAL).read_text(encoding="utf-8") == "BODY\n"


VARIANT = ".stayfixed/local/artifacts/agents.md"


def _variant(tmp_path: Path) -> None:
    """`VARIANT` holding the same bytes as `LOCAL`. On a filesystem that folds case it is `LOCAL`
    itself and this rewrites it unchanged; on one that does not, it is a second file, so the
    rule below is held by the same assertions on Linux as on macOS."""
    (tmp_path / VARIANT).write_text("BODY\n", encoding="utf-8")


def test_a_case_variant_of_an_artifact_s_own_place_is_that_place_and_never_a_left_copy(
    tmp_path: Path,
) -> None:
    # An entry for `agents-md` at `.../agents.md` while it lives at `.../AGENTS.md`: on the
    # default macOS and Windows filesystems one file, so judging the variant as a copy left
    # behind removed the artifact's own current copy, relocated onto itself. Mutation
    # (advisory): compare the copy with the artifact's own place exactly in `left_copies` -> in
    # `plan` the folded same-plan skip still withholds it (the artifact is in its own plan), so
    # only with that skip made exact too does the plan hold a `REMOVE` at the variant; the fold
    # in `left_copies` is what keeps `uninstall`'s prediction the same answer.
    _written(tmp_path)
    _variant(tmp_path)
    _ledger(tmp_path, {"agents-md": {LOCAL: digest("BODY\n"), VARIANT: digest("BODY\n")}})
    config = a_config(tmp_path, local=("agents-md",))
    planned = plan(tmp_path, config, [a_template()])
    assert VARIANT not in {a.target for a in planned.actions}
    apply(tmp_path, planned)
    assert (tmp_path / LOCAL).read_text(encoding="utf-8") == "BODY\n"
    assert (tmp_path / VARIANT).read_text(encoding="utf-8") == "BODY\n"


def test_a_left_copy_at_a_case_variant_of_a_file_the_plan_targets_is_that_template_s(
    tmp_path: Path,
) -> None:
    # The same-plan skip, compared the way the disk compares: an entry under `roadmap` at
    # `.../agents.md` names `agents-md`'s `.../AGENTS.md` where case folds, and with no
    # `owners` given the plan's own targets are the only guard. Mutation (oracle): `mutations/`'s "a
    # left copy at a case variant of a file the plan targets is judged twice" -> the plan removes
    # the variant, which on macOS is `agents-md`'s copy, and this reddens.
    _written(tmp_path)
    _variant(tmp_path)
    _ledger(
        tmp_path, {"agents-md": {LOCAL: digest("BODY\n")}, "roadmap": {VARIANT: digest("BODY\n")}}
    )
    config = a_config(tmp_path, local=("agents-md", "roadmap"))
    roadmap = a_template(id="roadmap", target="docs/roadmap.md", render=lambda: "R\n")
    planned = plan(tmp_path, config, [a_template(), roadmap])
    assert VARIANT not in {a.target for a in planned.actions}
    apply(tmp_path, planned)
    assert (tmp_path / LOCAL).read_text(encoding="utf-8") == "BODY\n"
    assert (tmp_path / VARIANT).read_text(encoding="utf-8") == "BODY\n"


def test_a_ledger_past_its_entry_bound_is_absent(tmp_path: Path) -> None:
    files = {f".stayfixed/local/artifacts/f{n}.md": "0" * 64 for n in range(MAX_ENTRIES + 1)}
    _ledger(tmp_path, {"agents-md": files})
    assert LocalDigests.read(tmp_path).entries == {}
    _ledger(tmp_path, {"agents-md": dict(list(files.items())[:MAX_ENTRIES])})
    assert len(LocalDigests.read(tmp_path).entries) == MAX_ENTRIES


def test_an_entry_whose_copy_a_person_deleted_is_dropped_by_the_next_apply(tmp_path: Path) -> None:
    # A left copy is kept in the ledger until it is gone. Gone by hand, nothing plans an action
    # at it, so `apply` drops what no longer names a file. Mutation (advisory): drop the
    # `on_disk` pass -> the stale entry stays and this reddens.
    _written(tmp_path)
    (tmp_path / LOCAL).unlink()
    apply(tmp_path, plan(tmp_path, a_config(tmp_path), [a_template()]))
    assert LocalDigests.read(tmp_path).entries == {}
    assert not (tmp_path / LOCAL_DIGESTS).exists()
