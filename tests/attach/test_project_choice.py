"""Which overlay project `attach` binds a repository with no `stayfixed.toml` to.

A public clone the owner cannot commit to carries no `[project] name`, so the project comes, in
this order, from `--project`, from this machine's binding record, from the one overlay project
whose `project.toml` records this checkout's `origin`, and from the last segment of `origin`'s
path. Each step is a convenience and not a gate: the anchor is `origin`, which whoever cloned set,
and the screen names the project and the origin for the owner who ran the command to read.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from stayfixed import binding
from stayfixed.attach.binding import BY_FILE, BY_FLAG, BY_OVERLAY, BY_RECORD, BY_REMOTE
from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.doctor.api import NO_CONFIG_SKIP, OK, SKIP, Check, run_checks
from stayfixed.memory.api import PROJECT_RECORD, PROJECTS
from stayfixed.overlay.api import COMMON_CLAUDE, COMMON_CODEX, COMMON_MEMORY
from tests.attach.test_binding import _machine, _project_and_store
from tests.attach.test_write import SETTINGS
from tests.doctor.test_checks import _env
from tests.gitfixture import git
from tests.runners import Recorder, claude_code
from tests.snapshot import assert_snapshot_unchanged, snapshot

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _claude_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No case reaches the developer's real `claude`: the CLI's `subprocess_runner()` is a
    recorder that writes what Claude Code's local-scope plugin calls write."""
    runner = Recorder(on_call=claude_code(tmp_path / "project"))
    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda **_: runner)


def invoke(argv: list[str]) -> int:
    return run(argv, parser=build_parser(discover_registrars()))


def _clone(tmp_path: Path, *, origin: str | None) -> tuple[Path, Path, Path]:
    """A committed repository with no `stayfixed.toml`, the overlay the machine records, and the
    machine file. Returns `(root, overlay, machine)`."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("a public clone\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    if origin is not None:
        git(root, "remote", "add", "origin", origin)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    overlay = tmp_path / "overlay"
    for relative in (COMMON_CLAUDE, COMMON_CODEX, COMMON_MEMORY):
        (overlay / relative).mkdir(parents=True)
    return root, overlay, _machine(tmp_path, overlay=overlay)


def _recorded(overlay: Path, name: str, remote: str) -> Path:
    """An overlay project whose binding record names `remote`; its directory."""
    home = overlay / PROJECTS / name
    home.mkdir(parents=True)
    (home / PROJECT_RECORD).write_text(f'remote = "{remote}"\n', encoding="utf-8")
    return home


def _flags(root: Path, machine: Path) -> list[str]:
    return ["--root", str(root), "--machine", str(machine)]


def _bound_to(root: Path) -> str | None:
    found = binding.bound_project(root)
    return None if found is None else found.project


def test_project_names_the_project_of_a_repository_with_no_stayfixed_toml(tmp_path: Path) -> None:
    # The first way, and the one every refusal below names: the owner says which project. It wins
    # over the remote's own name, `widget` here. Mutation: `mutations/`'s "attach ignores
    # --project".
    origin = "git@example.com:o/widget.git"
    root, _, machine = _clone(tmp_path, origin=origin)
    assert invoke(["attach", "--project", "mine", *_flags(root, machine)]) == 0
    assert _bound_to(root) == "mine"


def test_a_later_attach_takes_the_project_this_machines_binding_records(tmp_path: Path) -> None:
    # The second way: once bound, a routine re-attach needs no `--project`, and does not drift to
    # the remote's name, even where the overlay no longer records this remote for the project, so
    # the overlay alone would name `widget`. Mutation: `mutations/`'s "attach forgets this
    # machine's binding".
    root, overlay, machine = _clone(tmp_path, origin="git@example.com:o/widget.git")
    assert invoke(["attach", "--project", "mine", *_flags(root, machine)]) == 0
    (overlay / PROJECTS / "mine" / PROJECT_RECORD).unlink()
    assert invoke(["attach", *_flags(root, machine)]) == 0
    assert _bound_to(root) == "mine"


def test_the_one_overlay_project_recording_this_origin_is_the_project(tmp_path: Path) -> None:
    # The third way, the one a second machine meets: the overlay's record names the remote in
    # another spelling, which is the same repository as the binding note compares them. Mutation:
    # `mutations/`'s "attach finds no overlay project by its remote".
    root, overlay, machine = _clone(tmp_path, origin="https://github.com/o/widget")
    _recorded(overlay, "alpha", "git@github.com:O/Widget.git")
    _recorded(overlay, "beta", "git@github.com:o/other.git")
    assert invoke(["attach", *_flags(root, machine)]) == 0
    assert _bound_to(root) == "alpha"


def test_two_overlay_projects_recording_this_origin_are_refused_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Two of the owner's projects claim this repository, so which one is meant is the owner's to
    # say. Mutation: `mutations/`'s "attach takes the first of several projects recording its
    # remote".
    root, overlay, machine = _clone(tmp_path, origin="git@example.com:o/widget.git")
    _recorded(overlay, "alpha", "git@example.com:o/widget.git")
    _recorded(overlay, "beta", "https://example.com/o/widget.git")
    before = snapshot(root)
    assert invoke(["attach", *_flags(root, machine)]) == 2
    assert "--project" in capsys.readouterr().err
    assert invoke(["attach", "--check", *_flags(root, machine)]) == 2
    assert_snapshot_unchanged(root, before)
    assert binding.read_id(root) is None


def test_with_nothing_recorded_the_project_is_the_last_segment_of_origin_lower_cased(
    tmp_path: Path,
) -> None:
    # The fourth way, a first attach anywhere: the repository's own name, `.git` taken off and
    # lower-cased, which the overlay's record then keeps beside this remote for the next machine.
    # Mutation: `mutations/`'s "attach derives the project's name with its case".
    origin = "https://example.com/Owner/Widget-Kit.git"
    root, overlay, machine = _clone(tmp_path, origin=origin)
    assert invoke(["attach", *_flags(root, machine)]) == 0
    assert _bound_to(root) == "widget-kit"
    record = overlay / PROJECTS / "widget-kit" / PROJECT_RECORD
    assert origin in record.read_text(encoding="utf-8")


def test_a_derived_name_that_is_no_project_name_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The derived name becomes a directory under the overlay's `projects/`, so it is held to the
    # rule `[project] name` is. Mutation: `mutations/`'s "attach takes a derived name the name
    # rule refuses".
    root, _, machine = _clone(tmp_path, origin="git@example.com:o/_tools.git")
    assert invoke(["attach", *_flags(root, machine)]) == 2
    assert "--project" in capsys.readouterr().err
    assert binding.read_id(root) is None


def test_no_origin_and_no_binding_is_refused_naming_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Nothing names the project at all. Mutation: `mutations/`'s "attach takes the directory's
    # name where nothing names the project".
    root, _, machine = _clone(tmp_path, origin=None)
    assert invoke(["attach", *_flags(root, machine)]) == 2
    assert "--project" in capsys.readouterr().err
    assert invoke(["attach", "--check", *_flags(root, machine)]) == 2
    assert binding.read_id(root) is None


def test_project_beside_a_stayfixed_toml_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The file names the project, and a second name beside it would bind the checkout to a
    # project the file does not name. Mutation: `mutations/`'s "attach takes --project beside a
    # stayfixed.toml".
    root, store = _project_and_store(tmp_path, recorded=None, origin="git@example.com:o/p.git")
    machine = _machine(tmp_path, overlay=store.parents[2])
    before = snapshot(root)
    assert invoke(["attach", "--project", "q", *_flags(root, machine)]) == 2
    assert "stayfixed.toml" in capsys.readouterr().err
    assert invoke(["attach", "--check", "--project", "q", *_flags(root, machine)]) == 2
    assert_snapshot_unchanged(root, before)
    assert binding.read_id(root) is None


def test_a_project_no_directory_name_can_be_is_refused_before_anything_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--project` becomes a directory under the overlay's `projects/`, so `../common` is the value
    # the rule exists for; the refusal states the rule and never echoes the value.
    root, _, machine = _clone(tmp_path, origin="git@example.com:o/widget.git")
    with pytest.raises(SystemExit) as raised:
        invoke(["attach", "--project", "../common", *_flags(root, machine)])
    assert raised.value.code == 2
    assert "../common" not in capsys.readouterr().err
    assert binding.read_id(root) is None


def test_without_an_overlay_layer_the_mode_is_the_presets_and_no_pointer_is_written(
    tmp_path: Path,
) -> None:
    # The preset's `memory.mode` is `harness`: the plugin is delivered, and no note store is
    # composed or pointed at.
    root, _, machine = _clone(tmp_path, origin="git@example.com:o/widget.git")
    assert invoke(["attach", *_flags(root, machine)]) == 0
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert "autoMemoryDirectory" not in document
    assert document["enabledPlugins"]


def _doctor(tmp_path: Path, root: Path, machine: Path) -> dict[str, Check]:
    rows = run_checks(root, home=None, machine=machine, runner=Recorder(), env=_env(tmp_path))
    return {row.name: row for row in rows}


def test_doctor_judges_a_checkout_attached_with_no_stayfixed_toml_on_what_attach_used(
    tmp_path: Path,
) -> None:
    # The rows about what `attach` delivered read the configuration `attach` acted on, for the
    # project this machine's binding names: skipped for want of a file, they said nothing of a
    # delivery and a composed store that are both in place. Mutation: `mutations/`'s "doctor
    # judges a bound checkout with no stayfixed.toml on no configuration".
    root, overlay, machine = _clone(tmp_path, origin="git@example.com:o/widget.git")
    (overlay / PROJECTS / "widget").mkdir(parents=True)
    (overlay / PROJECTS / "widget" / "stayfixed.toml").write_text(
        '[memory]\nmode = "overlay"\n', encoding="utf-8"
    )
    assert invoke(["attach", *_flags(root, machine)]) == 0
    rows = _doctor(tmp_path, root, machine)
    assert (rows["attached"].status, rows["attached"].detail) == (
        OK,
        "attached; the delivery is in place; autoMemoryDirectory points the harness at the "
        "composed store; the binding is bound",
    )
    assert "store the composed store under the data directory" in rows["memory"].detail


def test_doctor_reads_an_unbound_checkout_with_no_stayfixed_toml_as_it_did(tmp_path: Path) -> None:
    # Nothing on this machine binds the checkout, so there is no project to build a configuration
    # for: the rows skip and answer as they did before `attach` could bind such a checkout.
    # Mutation: `mutations/`'s "bound_config answers for an unbound checkout".
    root, _, machine = _clone(tmp_path, origin="git@example.com:o/widget.git")
    rows = _doctor(tmp_path, root, machine)
    assert (rows["attached"].status, rows["attached"].detail) == (SKIP, NO_CONFIG_SKIP)
    assert "no store: memory is the harness's own" in rows["memory"].detail


def test_doctor_reads_a_worktree_whose_main_checkout_has_a_stayfixed_toml_as_it_did(
    tmp_path: Path,
) -> None:
    # A linked worktree without the file whose main checkout has one and is attached: the file
    # names the project, so there is no configuration of `attach`'s to build, and the row skips as
    # before `attach` could bind a checkout with no file. Mutation: `mutations/`'s "doctor builds a
    # configuration where the main checkout has a stayfixed.toml".
    from tests.attach.test_detach import _bound as _attached_with_file

    root, store, machine = _attached_with_file(tmp_path)
    assert invoke(["attach", "--store", str(store), *_flags(root, machine)]) == 0
    side = tmp_path / "side"
    git(root, "worktree", "add", "-q", str(side), "-b", "side")
    (side / "stayfixed.toml").unlink()
    rows = _doctor(tmp_path, side, machine)
    assert (rows["attached"].status, rows["attached"].detail) == (SKIP, NO_CONFIG_SKIP)


def _checked(
    capsys: pytest.CaptureFixture[str], root: Path, machine: Path, *extra: str
) -> tuple[str, dict[str, object]]:
    """`attach --check` as its line and as `--json`, on the same checkout; nothing is written."""
    before = snapshot(root)
    assert invoke(["attach", "--check", *extra, *_flags(root, machine)]) == 0
    line = capsys.readouterr().out.splitlines()[0]
    assert invoke(["attach", "--check", *extra, *_flags(root, machine), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert_snapshot_unchanged(root, before)
    return line, data


def test_check_names_the_project_a_flag_named_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The owner reads which project a clone would be bound to before it is: with `--project` the
    # name is theirs, and the line says it was. Mutation: `mutations/`'s "attach ignores
    # --project".
    root, _, machine = _clone(tmp_path, origin="git@example.com:o/widget.git")
    line, data = _checked(capsys, root, machine, "--project", "mine")
    assert line.startswith(f"project mine ({BY_FLAG}); ")
    assert (data["project"], data["project_source"]) == ("mine", BY_FLAG) and BY_FLAG == (
        "named by --project"
    )


def test_check_names_the_project_this_machines_binding_records_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, overlay, machine = _clone(tmp_path, origin="git@example.com:o/widget.git")
    assert invoke(["attach", "--project", "mine", *_flags(root, machine)]) == 0
    capsys.readouterr()
    (overlay / PROJECTS / "mine" / PROJECT_RECORD).unlink()
    line, data = _checked(capsys, root, machine)
    assert line.startswith(f"project mine ({BY_RECORD}); ")
    assert (data["project"], data["project_source"]) == ("mine", BY_RECORD)
    assert BY_RECORD == "this machine's binding record"


def test_check_names_the_project_the_overlay_records_for_the_remote_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, overlay, machine = _clone(tmp_path, origin="https://github.com/o/widget")
    _recorded(overlay, "alpha", "git@github.com:O/Widget.git")
    line, data = _checked(capsys, root, machine)
    assert line.startswith(f"project alpha ({BY_OVERLAY}); ")
    assert (data["project"], data["project_source"]) == ("alpha", BY_OVERLAY)
    assert BY_OVERLAY == "the overlay's record of the remote"


def test_check_names_the_project_the_remotes_name_gave_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, machine = _clone(tmp_path, origin="https://example.com/Owner/Widget-Kit.git")
    line, data = _checked(capsys, root, machine)
    assert line.startswith(f"project widget-kit ({BY_REMOTE}); ")
    assert (data["project"], data["project_source"]) == ("widget-kit", BY_REMOTE)
    assert BY_REMOTE == "the remote's name"


def test_check_names_the_project_a_stayfixed_toml_names_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, store = _project_and_store(tmp_path, recorded=None, origin="git@example.com:o/p.git")
    machine = _machine(tmp_path, overlay=store.parents[2])
    line, data = _checked(capsys, root, machine)
    assert line.startswith(f"project p ({BY_FILE}); ")
    assert (data["project"], data["project_source"]) == ("p", BY_FILE)
    assert BY_FILE == "its stayfixed.toml"


def test_check_json_keeps_its_existing_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The project and its source are added beside the report's fields, never in place of one.
    root, _, machine = _clone(tmp_path, origin="https://example.com/Owner/Widget-Kit.git")
    _, data = _checked(capsys, root, machine)
    assert {"state", "added_allow", "already_present", "rules_to_write"} <= set(data)
    assert data["state"] == "unbound"
