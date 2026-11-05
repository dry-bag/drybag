"""`stayfixed setup --restore`: the overlay's projects file, the tools, and the attach loop.

Every case builds an overlay and its checkouts under `tmp_path`, hands `restore` (or the command)
a `Recorder` for `claude`, and a `home` and a `machine` file of its own: nothing here reads the
developer's own `~`, overlay or harness. The projects are neutral names (`alpha`, `beta`, `gamma`).
"""

from __future__ import annotations

import io
import json
import shutil
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from stayfixed import binding, fsops
from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.errors import Refusal
from stayfixed.overlay.api import COMMON_CLAUDE, COMMON_CODEX
from stayfixed.overlay.layout import IDENTITY_RECORD
from stayfixed.runner import Completed
from stayfixed.setup.restore import (
    PLUGINS_FILE,
    PROJECTS_FILE,
    Listed,
    Outcome,
    RestoreReport,
    listed_plugins,
    listed_projects,
    missing_tools,
    restore,
)
from stayfixed.setup.run import _MARKETPLACE_ADD, _PLUGIN_INSTALL
from tests.attach.test_binding import CONFIG
from tests.attach.test_write import ledger_file
from tests.gitfixture import git
from tests.runners import Recorder
from tests.snapshot import assert_snapshot_unchanged, snapshot

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _overlay(tmp_path: Path) -> Path:
    """An overlay as `overlay_fault` reads one, with the common layer `attach` reads."""
    overlay = tmp_path / "overlay"
    (overlay / COMMON_CLAUDE).mkdir(parents=True)
    (overlay / COMMON_CODEX).mkdir(parents=True)
    (overlay / "common" / "memory").mkdir(parents=True)
    (overlay / IDENTITY_RECORD).write_text('requires = ">=0.1.0"\nlayout = 1\n', encoding="utf-8")
    (overlay / COMMON_CLAUDE / "permissions.json").write_text(
        json.dumps({"permissions": {"allow": [], "deny": []}}), encoding="utf-8"
    )
    (overlay / COMMON_CLAUDE / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
    return overlay


def _checkout(tmp_path: Path, directory: str, *, claims: str | None = None) -> Path:
    """A git checkout under `tmp_path/checkouts/<directory>` whose tracked `stayfixed.toml` names
    the project `claims` (the directory's own name by default)."""
    root = tmp_path / "checkouts" / directory
    root.mkdir(parents=True)
    (root / "stayfixed.toml").write_text(CONFIG.format(name=claims or directory), encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", f"git@example.com:o/{directory}.git")
    return root


def _list(overlay: Path, tables: dict[str, str]) -> None:
    """The overlay's projects file, one `[projects.<key>]` table per entry, whose body is `tables`'
    value verbatim, and the project directory attach writes its record under."""
    lines = []
    for key, body in tables.items():
        lines += [f'[projects."{key}"]', body]
    target = overlay / PROJECTS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _listing(overlay: Path, tmp_path: Path, **dirs: Path) -> tuple[Listed, ...]:
    _list(overlay, {name: f'dir = "{path}"' for name, path in dirs.items()})
    return listed_projects(overlay, home=tmp_path / "home")


def _machine(tmp_path: Path, overlay: Path) -> Path:
    path = tmp_path / "machine.toml"
    path.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    return path


def _restore(
    tmp_path: Path,
    overlay: Path,
    listed: tuple[Listed, ...],
    *,
    runner: Recorder | None = None,
    yes: bool = False,
) -> RestoreReport:
    return restore(
        overlay,
        listed,
        home=tmp_path / "home",
        machine=_machine(tmp_path, overlay),
        runner=runner or Recorder(),
        yes=yes,
    )


def _states(report: RestoreReport) -> dict[str, str]:
    return {outcome.name: outcome.state for outcome in report.projects}


def _restoring(tmp_path: Path, overlay: Path, *extra: str) -> list[str]:
    """`setup --restore --overlay <overlay>`, with a home and a machine file of the case's own."""
    home, machine = str(tmp_path / "home"), str(tmp_path / "config.toml")
    return [
        "setup",
        "--restore",
        "--overlay",
        str(overlay),
        "--home",
        home,
        "--machine",
        machine,
        *extra,
    ]


def invoke(argv: list[str]) -> tuple[int, str, str]:
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
        code = run(argv, parser=build_parser(discover_registrars()))
    return code, out.getvalue(), err.getvalue()


def test_a_listed_checkout_that_exists_is_attached(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha))
    assert _states(report) == {"alpha": "attached"}
    # The overlay's record of the binding, which attach writes under the project the key names.
    assert fsops.is_file(overlay / "projects" / "alpha" / "project.toml")
    assert fsops.is_file(ledger_file(alpha))


def test_a_listed_dir_that_is_not_there_is_reported_and_skipped(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    gone = tmp_path / "checkouts" / "alpha"
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=gone))
    assert report.projects == (Outcome("alpha", gone, "absent", "not there", 0),)
    assert not fsops.exists(gone)


def test_a_checkout_whose_project_is_not_its_table_key_is_refused_and_the_rest_attach(
    tmp_path: Path,
) -> None:
    # A clone's tracked `stayfixed.toml` can claim another of the owner's projects. The store comes
    # from the key in the owner's file, so attach refuses the clone rather than giving it beta's
    # notes. Mutation: `mutations/`'s "restore attaches without the store its table key names".
    overlay = _overlay(tmp_path)
    claiming = _checkout(tmp_path, "alpha", claims="beta")
    gamma = _checkout(tmp_path, "gamma")
    before = snapshot(claiming)
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=claiming, gamma=gamma))
    assert _states(report) == {"alpha": "refused", "gamma": "attached"}
    assert_snapshot_unchanged(claiming, before)
    assert not fsops.exists(ledger_file(claiming))
    assert binding.bound_project(claiming) is None
    assert not fsops.exists(overlay / "projects" / "beta")


def test_a_table_key_that_is_no_project_name_is_refused_and_the_rest_attach(
    tmp_path: Path,
) -> None:
    overlay = _overlay(tmp_path)
    odd = _checkout(tmp_path, "alpha")
    gamma = _checkout(tmp_path, "gamma")
    before = snapshot(odd)
    listed = _listing(overlay, tmp_path, **{"../x": odd, "a b": odd, "gamma": gamma})
    report = _restore(tmp_path, overlay, listed)
    assert _states(report) == {"../x": "refused", "a b": "refused", "gamma": "attached"}
    assert_snapshot_unchanged(odd, before)
    # Nothing was written where `projects/../x` leads, nor beside the overlay.
    assert not fsops.exists(overlay / "x")
    assert not fsops.exists(overlay / "projects" / "a b")
    assert not fsops.exists(tmp_path / "x")


def test_a_listed_dir_that_is_no_checkout_is_reported_and_the_rest_attach(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    plain = tmp_path / "checkouts" / "alpha"
    plain.mkdir(parents=True)
    a_file = tmp_path / "checkouts" / "beta"
    a_file.write_text("not a directory\n", encoding="utf-8")
    gamma = _checkout(tmp_path, "gamma")
    report = _restore(
        tmp_path, overlay, _listing(overlay, tmp_path, alpha=plain, beta=a_file, gamma=gamma)
    )
    states = _states(report)
    assert states["gamma"] == "attached"
    assert states["alpha"] == states["beta"] == "failed"
    assert all(o.detail for o in report.projects if o.name != "gamma")
    assert not fsops.exists(plain / ".stayfixed")


def test_a_relative_dir_is_refused_before_any_attach(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    _list(overlay, {"alpha": 'dir = "checkouts/alpha"'})
    code, _, err = invoke(_restoring(tmp_path, overlay))
    assert code == 2
    assert "projects.alpha" in err and "relative" in err and "machine setup ran" in err


@pytest.mark.parametrize(
    "body",
    ["", "dir = 3", 'dir = ""', 'dir = "a\\u0000b"', 'dir = ["/x"]'],
    ids=["missing", "number", "empty", "nul", "list"],
)
def test_a_dir_that_is_no_path_is_refused_naming_the_table(tmp_path: Path, body: str) -> None:
    overlay = _overlay(tmp_path)
    _list(overlay, {"alpha": body})
    with pytest.raises(Refusal) as refused:
        listed_projects(overlay, home=tmp_path / "home")
    assert "projects.alpha" in str(refused.value)


@pytest.mark.parametrize(
    "text",
    ["projects = 3\n", "[projects]\nalpha = 3\n", "projects = [\n", "\xff"],
    ids=["not-a-table", "table-of-numbers", "not-toml", "not-utf-8"],
)
def test_a_projects_file_that_cannot_be_read_is_refused(tmp_path: Path, text: str) -> None:
    overlay = _overlay(tmp_path)
    target = overlay / PROJECTS_FILE
    target.parent.mkdir(parents=True)
    target.write_bytes(text.encode("latin-1"))
    with pytest.raises(Refusal):
        listed_projects(overlay, home=tmp_path / "home")


def test_a_dir_led_by_a_tilde_is_read_under_the_home(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    _list(overlay, {"alpha": 'dir = "~/Dev/alpha"'})
    assert listed_projects(overlay, home=tmp_path / "home") == (
        Listed("alpha", tmp_path / "home" / "Dev" / "alpha"),
    )


def test_no_projects_file_lists_nothing(tmp_path: Path) -> None:
    assert listed_projects(_overlay(tmp_path), home=tmp_path / "home") == ()


def test_keys_the_product_does_not_read_are_ignored(tmp_path: Path) -> None:
    # An overlay's own scripts read `branch`, `sync`, `exclude` and `links`; stayfixed reads `dir`.
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    body = f'dir = "{alpha}"\nbranch = "next"\nsync = true\nexclude = ["x"]\nlinks = {{ a = 1 }}'
    _list(overlay, {"alpha": body})
    listed = listed_projects(overlay, home=tmp_path / "home")
    assert listed == (Listed("alpha", alpha),)
    assert _states(_restore(tmp_path, overlay, listed)) == {"alpha": "attached"}


def test_restore_twice_changes_nothing_the_second_time(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    listed = _listing(overlay, tmp_path, alpha=alpha)
    first = _restore(tmp_path, overlay, listed)
    after = snapshot(alpha)
    # Non-vacuous: the first run did write into the checkout.
    assert ".claude/settings.local.json" in after
    second = _restore(tmp_path, overlay, listed)
    assert _states(first) == _states(second) == {"alpha": "attached"}
    assert "already recorded" in second.projects[0].detail
    assert_snapshot_unchanged(alpha, after)


def test_one_failed_attach_leaves_the_others_and_exits_1(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha, gamma = _checkout(tmp_path, "alpha"), _checkout(tmp_path, "gamma")
    # `Recorder` answers by argv, and the failing project's delivery install has the same argv
    # shape as the others' bar the binding id in the plugin's name; `on_call` runs before the
    # answer is chosen, so it switches the install's answer on the directory the call is made in.
    runner = Recorder()

    def fail_in_alpha(argv: list[str], cwd: Path) -> None:
        if cwd.name == "alpha":
            runner.answers["claude plugin install"] = Completed(1, "", "boom\n")
        else:
            runner.answers.pop("claude plugin install", None)

    runner.on_call = fail_in_alpha
    listed = _listing(overlay, tmp_path, alpha=alpha, gamma=gamma)
    report = _restore(tmp_path, overlay, listed, runner=runner)
    assert _states(report) == {"alpha": "failed", "gamma": "attached"}
    # A re-run completes what the failure left.
    runner.on_call = None
    assert _states(_restore(tmp_path, overlay, listed)) == {
        "alpha": "attached",
        "gamma": "attached",
    }


def test_a_failed_project_makes_the_command_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overlay = _overlay(tmp_path)
    claiming = _checkout(tmp_path, "alpha", claims="beta")
    _list(overlay, {"alpha": f'dir = "{claiming}"'})
    monkeypatch.setattr("stayfixed.setup.commands.subprocess_runner", lambda: Recorder())
    code, out, _ = invoke(_restoring(tmp_path, overlay, "--json"))
    assert code == 1
    rows = json.loads(out)["projects"]
    assert [(r["name"], r["dir"], r["state"]) for r in rows] == [
        ("alpha", str(claiming), "refused")
    ]
    assert rows[0]["detail"]


def test_a_project_whose_record_lists_a_tag_is_attached(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    (overlay / "groups" / "t" / "memory").mkdir(parents=True)
    (overlay / "projects" / "alpha").mkdir(parents=True)
    (overlay / "projects" / "alpha" / "project.toml").write_text('tags = ["t"]\n', "utf-8")
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha))
    assert _states(report) == {"alpha": "attached"}


def test_a_checkout_with_no_config_is_attached_under_its_table_key(tmp_path: Path) -> None:
    # Its `origin` names `zzz`, which is not the key: the key names the project.
    overlay = _overlay(tmp_path)
    zzz = _checkout(tmp_path, "zzz")
    (zzz / "stayfixed.toml").unlink()
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha2=zzz))
    assert _states(report) == {"alpha2": "attached"}
    assert not fsops.exists(overlay / "projects" / "zzz")


def _recording(tmp_path: Path, root: Path, *extra: str) -> tuple[int, str, str]:
    """`setup --restore` with no `--overlay`, on a machine file that records `root`."""
    machine = tmp_path / "config.toml"
    machine.write_text(f'[overlay]\nroot = "{root}"\n', encoding="utf-8")
    home = str(tmp_path / "home")
    return invoke(["setup", "--restore", "--home", home, "--machine", str(machine), *extra])


def test_a_recorded_overlay_that_is_gone_is_refused_naming_it(tmp_path: Path) -> None:
    code, _, err = _recording(tmp_path, tmp_path / "gone")
    assert code == 2
    assert str(tmp_path / "gone") in err and "machine setup ran" in err


def test_a_restore_from_the_recorded_overlay_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overlay = _overlay(tmp_path)
    monkeypatch.setattr("stayfixed.setup.commands.subprocess_runner", lambda: Recorder())
    code, out, _ = _recording(tmp_path, overlay)
    assert code == 0
    assert str(overlay) in out and "no overlay recorded" not in out


@pytest.mark.parametrize("sync", [True, False], ids=["sync", "no-sync"])
def test_sync_switches_note_sync_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sync: bool
) -> None:
    from stayfixed.sync.switch import enabled

    overlay = _overlay(tmp_path)
    monkeypatch.setattr("stayfixed.setup.commands.subprocess_runner", lambda: Recorder())
    code, out, _ = invoke(_restoring(tmp_path, overlay, "--json", *(["--sync"] if sync else [])))
    assert code == 0
    assert json.loads(out)["sync"] is sync
    assert enabled(tmp_path / "config.toml") is sync


def test_restore_without_an_overlay_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    home, machine = tmp_path / "home", tmp_path / "config.toml"
    code, _, err = invoke(["setup", "--restore", "--home", str(home), "--machine", str(machine)])
    assert code == 2
    assert "--overlay PATH" in err
    assert not machine.exists() and not home.exists()


@pytest.mark.parametrize("beside", ["--git-hooks", "--approval-boundary"])
def test_restore_is_refused_beside_git_hooks_and_approval_boundary(
    tmp_path: Path, beside: str
) -> None:
    home, machine = tmp_path / "home", tmp_path / "config.toml"
    code, _, err = invoke(
        ["setup", "--restore", beside, "--home", str(home), "--machine", str(machine)]
    )
    assert code == 2
    assert "--restore" in err
    assert not machine.exists() and not home.exists()


def test_missing_tools_names_what_path_lacks() -> None:
    none = missing_tools(lambda name: None)
    assert none == ("git", "claude or codex", "python3 or uv")
    only = {"git", "codex", "uv"}
    assert missing_tools(lambda name: "/x" if name in only else None) == ()
    assert missing_tools(lambda name: "/x" if name != "git" else None) == ("git",)


def test_restore_prints_the_missing_tools_first_and_still_attaches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    _list(overlay, {"alpha": f'dir = "{alpha}"'})
    monkeypatch.setattr("stayfixed.setup.restore.missing_tools", lambda: ("codex",))
    monkeypatch.setattr("stayfixed.setup.commands.subprocess_runner", lambda: Recorder())
    code, out, _ = invoke(_restoring(tmp_path, overlay))
    assert code == 0
    assert out.splitlines()[0].startswith("missing tools: codex")
    assert fsops.is_file(ledger_file(alpha))


# --- the plugins the overlay's machine settings enable ---------------------------------------
#
# Restore runs setup's own verbs (`_MARKETPLACE_ADD` and `_PLUGIN_INSTALL`) on every run and asks
# Claude Code no listing: what it answers is what the person sees, as with `setup --plugin`.


def _machine_settings(overlay: Path, document: object) -> None:
    target = overlay / PLUGINS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document), encoding="utf-8")


def _enabling(*ids: str, marketplaces: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "enabledPlugins": {i: True for i in ids},
        "extraKnownMarketplaces": marketplaces or {},
    }


def _plugin_calls(runner: Recorder) -> list[list[str]]:
    return [c for c in runner.calls if c[:2] == ["claude", "plugin"] and "--scope" not in c]


def test_every_listed_marketplace_and_plugin_is_run_through_setups_argv(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    marketplaces: dict[str, object] = {
        "hub": {"source": {"source": "github", "repo": "o/hub"}},
        "lab": {"source": {"source": "git", "url": "https://example.com/lab.git"}},
    }
    _machine_settings(overlay, _enabling("a@hub", "b@lab", marketplaces=marketplaces))
    runner = Recorder()
    report = _restore(tmp_path, overlay, (), runner=runner)
    add: Callable[[str], list[str]] = _MARKETPLACE_ADD["claude"]
    install: Callable[[str], list[str]] = _PLUGIN_INSTALL["claude"]
    assert _plugin_calls(runner) == [
        add("o/hub"),
        add("https://example.com/lab.git"),
        install("a@hub"),
        install("b@lab"),
    ]
    assert report.plugins == ("a@hub", "b@lab") and report.notes == ()


@pytest.mark.parametrize(
    ("source", "named"),
    [
        ({"source": "git", "url": "https://example.com/p.git", "ref": "v2"}, "`ref`"),
        ({"source": "github", "repo": "o/p", "path": "sub"}, "`path`"),
        ({"source": "github", "repo": "o/p", "sparsePaths": ["a"]}, "`sparsePaths`"),
        ({"source": "github", "repo": "o/p", "ref": "v2"}, "`ref`"),
        ({"source": "directory", "path": "/x"}, "github"),
        ({"source": "directory", "": "/x"}, "github"),
        ({"source": "github"}, "github"),
        ({"source": "git", "url": 3}, "github"),
        ("o/p", "github"),
    ],
    ids=[
        "git-ref",
        "github-path",
        "github-sparse",
        "github-ref",
        "directory",
        "blank-key",
        "no-repo",
        "url-number",
        "string",
    ],
)
def test_a_marketplace_source_restore_does_not_carry_is_a_note_and_not_added(
    tmp_path: Path, source: object, named: str
) -> None:
    overlay = _overlay(tmp_path)
    _machine_settings(overlay, _enabling(marketplaces={"third": {"source": source}}))
    runner = Recorder()
    report = _restore(tmp_path, overlay, (), runner=runner)
    assert not _plugin_calls(runner)
    assert len(report.notes) == 1 and "third" in report.notes[0] and named in report.notes[0]


def test_an_id_claude_code_refuses_is_a_note(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    _machine_settings(overlay, _enabling("no-marketplace"))
    runner = Recorder(answers={"claude plugin install": Completed(1, "", "no such plugin\n")})
    report = _restore(tmp_path, overlay, (), runner=runner)
    install: Callable[[str], list[str]] = _PLUGIN_INSTALL["claude"]
    assert _plugin_calls(runner) == [install("no-marketplace")]
    assert report.plugins == ()
    assert report.notes == (
        "claude: 'claude plugin install no-marketplace' did not succeed ('no such plugin')",
    )


def test_a_marketplace_claude_code_does_not_register_is_a_note(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    hub: dict[str, object] = {"hub": {"source": {"source": "github", "repo": "o/hub"}}}
    _machine_settings(overlay, _enabling(marketplaces=hub))
    runner = Recorder(answers={"claude plugin marketplace": Completed(1, "", "not found\n")})
    report = _restore(tmp_path, overlay, (), runner=runner)
    assert report.notes == ("claude: could not register marketplace o/hub ('not found')",)


def test_a_failed_install_is_a_note_and_the_projects_still_attach(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    _machine_settings(overlay, _enabling("need@hub"))
    install = "claude plugin install need@hub"
    runner = Recorder(answers={install: Completed(1, "", "no such plugin\n")})
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha), runner=runner)
    assert report.plugins == ()
    assert len(report.notes) == 1 and install in report.notes[0]
    assert _states(report) == {"alpha": "attached"}


@pytest.mark.parametrize("json_flag", [[], ["--json"]], ids=["text", "json"])
def test_a_failed_install_is_printed_by_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_flag: list[str]
) -> None:
    overlay = _overlay(tmp_path)
    _machine_settings(overlay, _enabling("need@hub"))
    install = "claude plugin install need@hub"
    runner = Recorder(answers={install: Completed(1, "", "no such plugin\n")})
    monkeypatch.setattr("stayfixed.setup.commands.subprocess_runner", lambda: runner)
    code, out, _ = invoke(_restoring(tmp_path, overlay, *json_flag))
    assert code == 0
    said = json.loads(out)["notes"] if json_flag else [out]
    assert any(install in note for note in said)


def test_an_overlay_with_no_machine_settings_lists_no_plugins(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    assert listed_plugins(overlay) == ((), (), ())
    runner = Recorder()
    report = _restore(tmp_path, overlay, (), runner=runner)
    assert report.plugins == () and report.notes == () and not runner.calls


@pytest.mark.parametrize(
    "text",
    ["[", '"x"', '{"enabledPlugins": []}', '{"extraKnownMarketplaces": 3}'],
    ids=["not-json", "not-object", "plugins-list", "marketplaces-number"],
)
def test_machine_settings_of_another_shape_list_nothing_and_say_so(
    tmp_path: Path, text: str
) -> None:
    overlay = _overlay(tmp_path)
    target = overlay / PLUGINS_FILE
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")
    marketplaces, ids, notes = listed_plugins(overlay)
    assert marketplaces == () and ids == () and len(notes) == 1


def test_every_enabled_plugin_id_is_listed_as_written(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    enabled = {"a@m": True, "b@m": False, "no-marketplace": True, "d@m": "yes", "e@m@n": True}
    _machine_settings(overlay, {"enabledPlugins": enabled})
    assert listed_plugins(overlay)[1] == ("a@m", "no-marketplace", "e@m@n")


# --- `--yes`: the overlay's notes, recorded as reviewed -----------------------------------------


def _note(name: str) -> str:
    return (
        f"---\nname: {name}\ndescription: {name} description\nmetadata:\n  type: rule\n"
        f"  startup: 1\n---\n\nBody of {name}.\n"
    )


def _notes(overlay: Path, project: str, *names: str) -> None:
    """Notes in the project's own `project-stable` group, which the attach fixture's
    `stayfixed.toml` lists among `memory.groups`."""
    group = overlay / "projects" / project / "memory" / "project-stable"
    group.mkdir(parents=True, exist_ok=True)
    for name in names:
        (group / f"{name}.md").write_text(_note(name), encoding="utf-8")


def _reviewed(machine: Path) -> list[str]:
    """The notes the machine's trust record holds as reviewed."""
    from stayfixed.trust.api import recorded

    return sorted(subject for kind, subject in recorded(machine) if kind == "reviewed")


def test_without_yes_no_note_is_recorded_as_reviewed(tmp_path: Path) -> None:
    # Mutation: `mutations/`'s "restore records notes as reviewed without --yes".
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    _notes(overlay, "alpha", "one", "two")
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha), yes=False)
    assert _states(report) == {"alpha": "attached"}
    assert [o.promoted for o in report.projects] == [0]
    assert _reviewed(_machine(tmp_path, overlay)) == []


def test_yes_records_every_unreviewed_note_of_each_attached_project(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha, beta = _checkout(tmp_path, "alpha"), _checkout(tmp_path, "beta")
    claiming = _checkout(tmp_path, "gamma", claims="alpha")
    _notes(overlay, "alpha", "one", "two")
    _notes(overlay, "beta", "three")
    _notes(overlay, "gamma", "four")
    listed = _listing(overlay, tmp_path, alpha=alpha, beta=beta, gamma=claiming)
    report = _restore(tmp_path, overlay, listed, yes=True)
    assert _states(report) == {"alpha": "attached", "beta": "attached", "gamma": "refused"}
    assert {o.name: o.promoted for o in report.projects} == {"alpha": 2, "beta": 1, "gamma": 0}
    recorded = _reviewed(_machine(tmp_path, overlay))
    # Three notes, and none of the refused checkout's.
    assert sorted(Path(subject).name for subject in recorded) == ["one.md", "three.md", "two.md"]


def test_yes_records_the_overlays_notes_for_the_key_and_never_the_checkouts(
    tmp_path: Path,
) -> None:
    # An in-repo checkout commits a note ranked `startup: 1`; `--yes` records the overlay's share
    # for the table key and reads nothing the checkout holds.
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    config = (alpha / "stayfixed.toml").read_text(encoding="utf-8")
    in_repo = config.replace('mode = "overlay"', 'mode = "in-repo"') + '[paths]\nmemory = "n"\n'
    (alpha / "stayfixed.toml").write_text(in_repo, encoding="utf-8")
    committed = alpha / "n" / "project-stable" / "planted.md"
    committed.parent.mkdir(parents=True)
    committed.write_text(_note("planted"), encoding="utf-8")
    _notes(overlay, "alpha", "one")
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha), yes=True)
    assert [(o.state, o.promoted) for o in report.projects] == [("attached", 1)]
    assert [Path(s).name for s in _reviewed(_machine(tmp_path, overlay))] == ["one.md"]


def test_yes_records_the_overlays_notes_for_a_checkout_with_no_config(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    (alpha / "stayfixed.toml").unlink()
    _notes(overlay, "alpha", "one")
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha), yes=True)
    assert [(o.state, o.promoted) for o in report.projects] == [("attached", 1)]
    assert [Path(s).name for s in _reviewed(_machine(tmp_path, overlay))] == ["one.md"]


def test_a_project_whose_notes_cannot_be_recorded_is_failed_and_the_rest_go_on(
    tmp_path: Path,
) -> None:
    overlay = _overlay(tmp_path)
    alpha, beta = _checkout(tmp_path, "alpha"), _checkout(tmp_path, "beta")
    _notes(overlay, "alpha", "one")
    _notes(overlay, "beta", "two")
    # A record that is there and cannot be read: promote refuses it rather than replace it.
    (tmp_path / "trust.json").write_text("not json", encoding="utf-8")
    report = _restore(
        tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha, beta=beta), yes=True
    )
    assert _states(report) == {"alpha": "failed", "beta": "failed"}
    assert (tmp_path / "trust.json").read_text(encoding="utf-8") == "not json"


def test_yes_through_the_command_records_the_notes_and_the_json_counts_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    _notes(overlay, "alpha", "one", "two")
    _list(overlay, {"alpha": f'dir = "{alpha}"'})
    monkeypatch.setattr("stayfixed.setup.commands.subprocess_runner", lambda: Recorder())
    code, out, _ = invoke(_restoring(tmp_path, overlay, "--yes", "--json"))
    assert code == 0
    assert [row["promoted"] for row in json.loads(out)["projects"]] == [2]
    assert len(_reviewed(tmp_path / "config.toml")) == 2


@pytest.mark.parametrize("flag", ["--yes", "--sync"])
@pytest.mark.parametrize("beside", [[], ["--git-hooks"], ["--approval-boundary"]])
def test_yes_and_sync_are_refused_without_restore(
    tmp_path: Path, flag: str, beside: list[str]
) -> None:
    home, machine = tmp_path / "home", tmp_path / "config.toml"
    code, _, err = invoke(["setup", flag, *beside, "--home", str(home), "--machine", str(machine)])
    assert code == 2
    assert flag in err and "--restore" in err
    assert not machine.exists() and not home.exists()
