"""`stayfixed setup --restore`: the overlay's projects file, the tools, and the attach loop.

Every case builds an overlay and its checkouts under `tmp_path`, hands `restore` (or the command)
a `Recorder` for `claude`, and a `home` and a `machine` file of its own: nothing here reads the
developer's own `~`, overlay or harness. The projects are neutral names (`alpha`, `beta`, `gamma`).
"""

from __future__ import annotations

import io
import json
import shutil
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
    PROJECTS_FILE,
    Listed,
    Outcome,
    RestoreReport,
    listed_projects,
    missing_tools,
    restore,
)
from tests.attach.test_binding import CONFIG
from tests.gitfixture import git
from tests.runners import Recorder
from tests.snapshot import assert_snapshot_unchanged, snapshot

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

ATTACH_LEDGER = ".stayfixed/local/attach.json"


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


@pytest.fixture(autouse=True)
def _a_harness_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`claude` is on `PATH` for every case, so none depends on the machine running it; the
    runner is a `Recorder`, which launches nothing."""
    real = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name, *a, **k: "/bin/claude" if name == "claude" else real(name)
    )


def test_a_listed_checkout_that_exists_is_attached(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha = _checkout(tmp_path, "alpha")
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha))
    assert _states(report) == {"alpha": "attached"}
    # The overlay's record of the binding, which attach writes under the project the key names.
    assert fsops.is_file(overlay / "projects" / "alpha" / "project.toml")
    assert fsops.is_file(alpha / ATTACH_LEDGER)


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
    assert not fsops.exists(claiming / ATTACH_LEDGER)
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
    assert states["alpha"] in ("refused", "failed") and states["beta"] in ("refused", "failed")
    assert all(o.detail for o in report.projects if o.name != "gamma")
    assert not fsops.exists(plain / ".stayfixed")


def test_a_relative_dir_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    _list(overlay, {"alpha": 'dir = "checkouts/alpha"'})
    home, machine = tmp_path / "home", tmp_path / "config.toml"
    code, _, err = invoke(_restoring(tmp_path, overlay))
    assert code == 2
    assert "projects.alpha" in err and "relative" in err
    assert not machine.exists() and not home.exists()


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
    assert ATTACH_LEDGER in after
    second = _restore(tmp_path, overlay, listed)
    assert _states(first) == _states(second) == {"alpha": "attached"}
    assert "already recorded" in second.projects[0].detail
    assert_snapshot_unchanged(alpha, after)


def test_restore_never_detaches_a_project_no_longer_listed(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    alpha, beta = _checkout(tmp_path, "alpha"), _checkout(tmp_path, "beta")
    _restore(tmp_path, overlay, _listing(overlay, tmp_path, alpha=alpha, beta=beta))
    kept = snapshot(alpha)
    report = _restore(tmp_path, overlay, _listing(overlay, tmp_path, beta=beta))
    assert _states(report) == {"beta": "attached"}
    assert_snapshot_unchanged(alpha, kept)


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
    assert fsops.is_file(alpha / ATTACH_LEDGER)
