"""What `stayfixed attach` writes, the refusals it owes before it writes anything, and the screen
it proceeds with.

What the overlay grants — allow rules, hook entries, skills and agents — is the owner's, written by
the owner and the owner's agents, so `attach` shows it on one screen beside the binding and asks
for no confirmation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from stayfixed import fsops, jsonobject
from stayfixed.attach.api import ledger
from stayfixed.attach.binding import OVERLAY_DAMAGED
from stayfixed.attach.check import check
from stayfixed.attach.exclude import NOT_IGNORED, TRACKED
from stayfixed.attach.permissions import settings_document
from stayfixed.attach.write import (
    GROUP_ESCAPES,
    GROUP_UNASKED,
    NO_MAIN_CHECKOUT,
    NO_ORIGIN_NOTE,
    NOT_INSTALLED,
    Attached,
    attach,
)
from stayfixed.binding import LEDGER_FILE, common_directory
from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.errors import Failure, Refusal
from stayfixed.memory.api import PROJECT_RECORD, link_sources
from stayfixed.overlay.api import COMMON_CLAUDE, COMMON_CODEX
from stayfixed.printed import quoted
from stayfixed.runner import Completed
from stayfixed.scaffold import EntriesError, Style, drop, extract
from tests.attach.test_binding import CONFIG, DEFAULT_MEMORY, _machine, _project_and_store
from tests.cli import cli
from tests.gitfixture import git as _git
from tests.gitfixture import run_git
from tests.parserlimits import LONG_NUMBER, NESTED
from tests.pathfaults import ROOT_SEARCHES_EVERYTHING, unsearchable
from tests.runners import Recorder

# The walk-based snapshot guard, owned at the top level rather than duplicated here and in
# tests/test_install_path.py: it used to exist twice, verbatim including its docstring, and the
# two copies drifted apart on the one thing that mattered — how much of `.git` to trust.
from tests.snapshot import assert_snapshot_unchanged, snapshot

# The fixture the binding tests already build, reused rather than copied: one spelling of the
# overlay layout keeps the two modules from drifting apart about what `--store` names.
from tests.tagged import with_tags

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _never_the_developers_own_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """A case that drives `attach` through the command line reaches the CLI's own
    `subprocess_runner()`, which resolves `claude` on `PATH`; no case may run the developer's."""
    runner = Recorder()
    monkeypatch.setattr("stayfixed.runner.subprocess_runner", lambda **_: runner)


def ledger_file(root: Path) -> Path:
    """The attach ledger of `root`'s repository: in the git common directory, beside the id."""
    return common_directory(root) / LEDGER_FILE


SETTINGS = ".claude/settings.local.json"
# The settings key that points the harness at the composed store, which every overlay-mode attach
# writes beside whatever else the case is about.
POINTER = "autoMemoryDirectory"
RULE = "Bash(uv run pytest:*)"
ENTRY = {"type": "command", "command": "echo hello"}


def _overlay_repository(overlay: Path) -> None:
    """The overlay as what it actually is — a git repository."""
    _git(overlay, "init", "-q", "-b", "main")


def _overlay_grants(
    store: Path,
    *,
    allow: tuple[str, ...] = (),
    hooks: Mapping[str, object] | None = None,
    codex: str | None = None,
) -> Path:
    overlay = store.parents[2]
    (overlay / COMMON_CLAUDE / "permissions.json").write_text(
        json.dumps({"permissions": {"allow": list(allow), "deny": []}}), encoding="utf-8"
    )
    (overlay / COMMON_CLAUDE / "hooks.json").write_text(
        json.dumps({"hooks": dict(hooks or {})}), encoding="utf-8"
    )
    if codex is not None:
        (overlay / COMMON_CODEX / "common.rules").write_text(codex, encoding="utf-8")
    return overlay


def _attachable(
    tmp_path: Path,
    *,
    recorded: str | None = None,
    origin: str = "git@example.com:o/p.git",
    allow: tuple[str, ...] = (),
    hooks: Mapping[str, object] | None = None,
    codex: str | None = None,
) -> tuple[Path, Path, Path]:
    root, store = _project_and_store(tmp_path, recorded=recorded, origin=origin)
    _overlay_grants(store, allow=allow, hooks=hooks, codex=codex)
    return root, store, _machine(tmp_path, overlay=store.parents[2])


def _check_ignore(root: Path, relative: str) -> bool:
    # `run_git` and not `git`: `check-ignore` answers 1 for "nothing matched", which is an
    # answer and not a failure — the same distinction `stayfixed.gitenv.git_run` makes.
    return run_git(root, "check-ignore", "-q", "--", relative).returncode == 0


def test_a_record_of_another_remote_attaches_with_a_note_and_is_left_alone(
    tmp_path: Path,
) -> None:
    # A record of another remote refused the attach unless `--trust-remote`, which then rewrote
    # the record. The record binds nothing now: the binding is the id in the git common directory
    # and this machine's record of it, so the run binds, says both remotes, and leaves the
    # overlay's record as the owner wrote it -- another machine may have written it.
    from stayfixed import binding

    recorded, origin = "git@example.com:o/real.git", "https://example.com/fork/p"
    root, store, machine = _attachable(tmp_path, recorded=recorded, origin=origin)
    record = store.parent / "project.toml"
    before = record.read_bytes()
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    assert attached.binding_recorded
    assert any(quoted(origin) in note and quoted(recorded) in note for note in attached.notes)
    assert record.read_bytes() == before
    found = binding.bound_project(root)
    assert found is not None and found.project == "p" and found.origin == origin


def test_the_same_repository_under_another_url_form_attaches_with_no_note(
    tmp_path: Path,
) -> None:
    # One repository is one remote whatever transport names it: a clone made over https of a
    # repository the overlay recorded over ssh hears nothing about its remote.
    root, store, machine = _attachable(
        tmp_path,
        recorded="git@example.com:o/p.git",
        origin="https://example.com/o/p",
    )
    record = store.parent / "project.toml"
    before = record.read_bytes()
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    assert not any("`origin`" in note for note in attached.notes)
    assert record.read_bytes() == before


def test_an_attach_of_an_overlay_that_grants_nothing_binds_and_writes_only_the_memory_pointer(
    tmp_path: Path,
) -> None:
    # An overlay with no allow rules and no hooks, the state of a freshly created one: the run
    # binds and writes nothing into the settings file but the pointer at the composed store.
    root, store, machine = _attachable(tmp_path)
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    assert attached.binding_recorded
    assert attached.settings_written
    assert list(json.loads((root / SETTINGS).read_text(encoding="utf-8"))) == [POINTER]
    assert ledger_file(root).is_file()


def test_the_screen_names_what_a_render_adds_and_removes_against_the_last_one(
    tmp_path: Path,
) -> None:
    # The executable diff is taken against the render directory the last run left, which is what
    # a session runs: a skill the overlay dropped is said removed, an agent it gained added, and
    # a hook entry that stayed is in neither list.
    hooks = {"SessionStart": [{"hooks": [ENTRY]}]}
    root, store, machine = _attachable(tmp_path, allow=(RULE,), hooks=hooks)
    claude = store.parents[2] / COMMON_CLAUDE
    (claude / "skills" / "old").mkdir(parents=True)
    (claude / "skills" / "old" / "SKILL.md").write_text("old\n", encoding="utf-8")
    first = attach(root, store=store, machine=machine, runner=Recorder())
    assert first.added.hooks == (("SessionStart", ENTRY["command"]),)
    assert (first.added.skills, first.allow_added) == (("old",), (RULE,))
    shutil.rmtree(claude / "skills" / "old")
    (claude / "agents").mkdir()
    (claude / "agents" / "reviewer.md").write_text("r\n", encoding="utf-8")
    second = attach(root, store=store, machine=machine, runner=Recorder())
    assert (second.added.hooks, second.removed.hooks) == ((), ())
    assert (second.added.agents, second.removed.skills) == (("reviewer.md",), ("old",))
    assert (second.added.skills, second.removed.agents, second.allow_added) == ((), (), ())


def test_a_skill_the_overlay_dropped_after_a_failed_install_is_never_rendered_again(
    tmp_path: Path,
) -> None:
    # A failed install records no render, so a render that took out only the parts the ledger
    # named left a skill the overlay dropped in the directory Claude Code runs, for good, while
    # `doctor`'s digest said the delivery was in place. Each render is the overlay as it is now,
    # whole, whatever any ledger recorded.
    from stayfixed.runner import Completed

    root, store, machine = _attachable(tmp_path)
    claude = store.parents[2] / COMMON_CLAUDE
    (claude / "skills" / "old").mkdir(parents=True)
    (claude / "skills" / "old" / "SKILL.md").write_text("old\n", encoding="utf-8")
    broken = Recorder(answers={"claude plugin install": Completed(1, "", "")})
    with pytest.raises(Failure):
        attach(root, store=store, machine=machine, runner=broken)
    assert (_delivered_hooks(root).parents[1] / "skills" / "old" / "SKILL.md").is_file()
    shutil.rmtree(claude / "skills" / "old")
    attach(root, store=store, machine=machine, runner=Recorder())
    assert not (_delivered_hooks(root).parents[1] / "skills").exists()


def _delivered_hooks(root: Path) -> Path:
    """The hook file of the plugin rendered for `root`'s binding id."""
    from stayfixed import binding

    id = binding.read_id(root)
    assert id is not None
    delivery = Path(os.environ["HOME"]) / ".local" / "share" / "stayfixed" / "delivery" / id
    return delivery / "plugin" / "hooks" / "hooks.json"


def _claude_calls(runner: Recorder) -> list[tuple[list[str], Path]]:
    calls = zip(runner.calls, runner.cwds, strict=True)
    return [(argv, cwd) for argv, cwd in calls if argv[0] == "claude"]


def test_every_attach_installs_the_rendered_plugin_from_the_main_checkout(
    tmp_path: Path,
) -> None:
    # Run from a linked worktree, so the working directory the two calls name is the main
    # checkout's for a reason and not because it is where the command was typed: Claude Code reads
    # the main checkout's `settings.local.json` from every worktree. Both calls are idempotent
    # (Claude Code 2.1.301 answers 0 for a marketplace it knows and a plugin it has), so every
    # attach runs them: one keyed on the checkout's ledger never reinstalled what a copy's detach,
    # or a lost id, had taken away.
    from stayfixed import binding

    root, store, machine = _attachable(tmp_path, hooks={"SessionStart": [{"hooks": [ENTRY]}]})
    _committed(root)
    side = tmp_path / "side"
    _git(root, "worktree", "add", "-q", str(side), "-b", "side")
    first = Recorder()
    attach(side, store=store, machine=machine, runner=first)
    id = binding.read_id(root)
    assert id is not None
    delivery = Path(os.environ["HOME"]) / ".local" / "share" / "stayfixed" / "delivery" / id
    assert _claude_calls(first) == [
        (
            ["claude", "plugin", "marketplace", "add", str(delivery), "--scope", "local"],
            root.resolve(),
        ),
        (
            [
                "claude",
                "plugin",
                "install",
                f"overlay-{id}@stayfixed-delivery-{id}",
                "--scope",
                "local",
            ],
            root.resolve(),
        ),
    ]
    assert (delivery / ".claude-plugin" / "marketplace.json").is_file()
    second = Recorder()
    attach(side, store=store, machine=machine, runner=second)
    assert _claude_calls(second) == _claude_calls(first)


def test_attach_from_a_bare_repositorys_worktree_cannot_tell_its_main_checkout_and_installs_nothing(
    tmp_path: Path,
) -> None:
    # A bare repository has no main checkout: its git common directory's parent is whatever
    # directory the repository sits in, which is no checkout at all, and the plugin is installed
    # from the main checkout. So the run refuses with "cannot tell" before anything is written or
    # installed, rather than installing into a directory that is not a checkout.
    root, store, machine = _attachable(tmp_path)
    _committed(root)
    bare = tmp_path / "bare.git"
    _git(tmp_path, "clone", "-q", "--bare", str(root), str(bare))
    side = tmp_path / "side"
    _git(bare, "worktree", "add", "-q", str(side), "main")
    before = snapshot(tmp_path)
    runner = Recorder()
    with pytest.raises(Refusal) as refused:
        attach(side, store=store, machine=machine, runner=runner)
    assert str(refused.value) == NO_MAIN_CHECKOUT
    assert runner.calls == []
    assert_snapshot_unchanged(tmp_path, before)


def test_attach_from_a_worktree_asks_the_main_checkouts_gitignore_about_what_it_places(
    tmp_path: Path,
) -> None:
    # Claude Code writes the plugin's entry, which names the binding id, into the main checkout's
    # settings file whichever worktree `attach` runs from, so that file is asked about in the main
    # checkout, where `attach` places everything. Here the worktree's branch ignores the settings
    # file and the main checkout's re-includes it: asked of the worktree alone, every check passed
    # and the plugin was installed into a file `git status` offered the main checkout for commit.
    root, store, machine = _attachable(tmp_path)
    (root / ".gitignore").write_text(f"{SETTINGS}\n", encoding="utf-8")
    _committed(root)
    side = tmp_path / "side"
    _git(root, "worktree", "add", "-q", str(side), "-b", "side")
    (root / ".gitignore").write_text(f"!{SETTINGS}\n", encoding="utf-8")
    _git(root, "commit", "-qam", "re-include the settings file")
    runner = Recorder()
    with pytest.raises(Refusal) as refused:
        attach(
            side,
            store=store,
            machine=machine,
            runner=runner,
        )
    assert str(refused.value) == NOT_IGNORED.format(paths=quoted(SETTINGS))
    assert runner.calls == []
    assert not (root / SETTINGS).exists() and not (side / SETTINGS).exists()


def test_attach_from_a_worktree_refuses_a_settings_file_the_main_checkout_tracks(
    tmp_path: Path,
) -> None:
    # The tracked half of the same rule, asked of the main checkout's own index: its branch commits
    # the settings file the install would write the binding id into, the worktree's does not.
    root, store, machine = _attachable(tmp_path)
    _committed(root)
    side = tmp_path / "side"
    _git(root, "worktree", "add", "-q", str(side), "-b", "side")
    (root / ".claude").mkdir()
    (root / SETTINGS).write_text("{}\n", encoding="utf-8")
    _git(root, "add", SETTINGS)
    _git(root, "commit", "-qm", "commit the settings file")
    runner = Recorder()
    with pytest.raises(Refusal) as refused:
        attach(
            side,
            store=store,
            machine=machine,
            runner=runner,
        )
    assert str(refused.value) == TRACKED.format(paths=quoted(SETTINGS))
    assert runner.calls == []
    assert (root / SETTINGS).read_text(encoding="utf-8") == "{}\n"


@pytest.mark.parametrize("failing", ["claude plugin marketplace add", "claude plugin install"])
def test_an_install_that_did_not_succeed_exits_one_by_its_code_and_a_rerun_completes(
    tmp_path: Path, failing: str
) -> None:
    # What Claude Code prints names the plugin, and the plugin's name carries the whole binding
    # id, so the failure says the exit code and nothing it printed. The run exits 1 rather than
    # reporting an attach that delivers nothing, records no render, and keeps the exclude block, so
    # the next attach installs again with everything still hidden.
    from stayfixed import binding

    root, store, machine = _attachable(tmp_path)
    broken = Recorder(answers={failing: Completed(1, "", "overlay-secret")})
    with pytest.raises(Failure) as failed:
        attach(root, store=store, machine=machine, runner=broken)
    id = binding.read_id(root)
    assert id is not None
    verb = failing.removeprefix("claude plugin ")
    assert str(failed.value) == NOT_INSTALLED.format(verb=verb, code=1)
    assert id not in str(failed.value) and "overlay-secret" not in str(failed.value)
    assert ledger(root).render is None
    assert "# stayfixed:attach:begin" in (root / ".git" / "info" / "exclude").read_text("utf-8")
    again = Recorder()
    attach(root, store=store, machine=machine, runner=again)
    assert [argv[2] for argv, _ in _claude_calls(again)] == ["marketplace", "install"]
    assert ledger(root).render is not None


def test_after_attach_the_local_settings_file_holds_the_allow_rules_and_no_hook_entry(
    tmp_path: Path,
) -> None:
    # Claude Code rewrites `settings.local.json` whole and keeps no marker in it, so every hook
    # entry goes into the rendered plugin and the file keeps only the allow rules the ledger names.
    hooks = {"SessionStart": [{"hooks": [ENTRY]}]}
    root, store, machine = _attachable(tmp_path, allow=(RULE,), hooks=hooks)
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert document.pop(POINTER) and document == {"permissions": {"allow": [RULE]}}
    assert ledger(root).entries == {}


def test_an_attach_withdraws_the_hook_entries_its_earlier_ledger_records_and_no_other(
    tmp_path: Path,
) -> None:
    # A checkout attached by an earlier release holds the entries that release merged, named by
    # its ledger. `attach` takes back exactly those, found through the ledger and never by the
    # marker alone: an entry claiming the marker that no ledger records is left where it is, as is
    # the owner's own, and a group left with one of them is split rather than dropped.
    root, store, machine = _attachable(tmp_path)
    (root / ".claude").mkdir()
    recorded = {"type": "command", "command": "old.sh  # stayfixed:overlay-SessionStart-1"}
    unrecorded = {"type": "command", "command": "other.sh  # stayfixed:overlay-SessionStart-2"}
    mine = {"type": "command", "command": "mine.sh"}
    (root / SETTINGS).write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [mine, recorded, unrecorded]}]}}),
        encoding="utf-8",
    )
    ledger_file(root).parent.mkdir(parents=True)
    ledger_file(root).write_text(
        json.dumps(
            {
                "format": 1,
                "store": str(store),
                "entries": {"overlay-SessionStart-1": "SessionStart"},
            }
        ),
        encoding="utf-8",
    )
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    assert attached.settings_written
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert document.pop(POINTER)
    assert document == {"hooks": {"SessionStart": [{"hooks": [mine, unrecorded]}]}}
    assert ledger(root).entries == {}


def test_attach_delivers_whatever_the_memory_mode(tmp_path: Path) -> None:
    # Delivery does not depend on where a repository keeps its notes, so a `local-only` one is
    # attached: its hooks are rendered and installed.
    root, store, machine = _attachable(tmp_path, hooks={"SessionStart": [{"hooks": [ENTRY]}]})
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace('mode = "overlay"', 'mode = "local-only"'),
        encoding="utf-8",
    )
    runner = Recorder()
    attach(root, store=store, machine=machine, runner=runner)
    assert [argv[2] for argv, _ in _claude_calls(runner)] == ["marketplace", "install"]
    assert ledger_file(root).is_file()


def test_attach_points_the_harness_at_the_composed_store_in_the_main_checkout(
    tmp_path: Path,
) -> None:
    # One settings key reaches every worktree: `autoMemoryDirectory` in the main checkout's
    # excluded settings file, absolute, naming the store under this machine's data directory whose
    # group links resolve into the overlay. The ledger records the key, so `detach` takes it back.
    from stayfixed import binding
    from stayfixed.memory.store import composed_directory as store_directory

    root, store, machine = _attachable(tmp_path)
    attach(root, store=store, machine=machine, runner=Recorder())
    id = binding.read_id(root)
    assert id is not None
    composed = store_directory(id)
    assert (root / SETTINGS).is_file()
    settings = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert settings["autoMemoryDirectory"] == str(composed)
    assert (composed / "developer").resolve() == (store.parents[2] / "common/memory").resolve()
    assert ledger(root).settings_keys == ("autoMemoryDirectory",)


def test_a_reattach_out_of_overlay_mode_withdraws_the_pointer_and_the_composed_store(
    tmp_path: Path,
) -> None:
    # Left in place, the harness kept reading the overlay's notes through the composed store, and
    # its writer kept writing into it, while stayfixed delivered the repository's own notes or
    # nothing; no row said so. A re-attach in another mode takes the ledgered key and the store
    # back as `detach` does. Mutation (oracle): `mutations/`'s "a re-attach out of overlay mode
    # keeps the pointer".
    from stayfixed import binding
    from stayfixed.memory.store import composed_directory as store_directory

    root, store, machine = _attachable(tmp_path)
    attach(root, store=store, machine=machine, runner=Recorder())
    id = binding.read_id(root)
    assert id is not None and store_directory(id).is_dir()
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace('mode = "overlay"', 'mode = "in-repo"')
    )
    attach(root, store=None, machine=machine, runner=Recorder())
    settings = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert POINTER not in settings
    assert not store_directory(id).exists()
    assert ledger(root).settings_keys == ()


def test_the_first_attach_reads_the_mode_the_overlays_project_file_sets(tmp_path: Path) -> None:
    # The overlay's project layer is read for a bound checkout, and the first attach read the
    # configuration before it bound the checkout: `[memory] mode = "overlay"` set there alone
    # composed nothing and wrote no pointer until a second attach. The mode is resolved after the
    # binding is recorded.
    from stayfixed import binding
    from stayfixed.memory.store import composed_directory as store_directory

    root, store, machine = _attachable(tmp_path)
    config = root / CONFIG_FILE
    config.write_text(config.read_text(encoding="utf-8").replace('mode = "overlay"\n', ""))
    (store.parent / "stayfixed.toml").write_text('[memory]\nmode = "overlay"\n', encoding="utf-8")
    attach(root, store=None, machine=machine, runner=Recorder())
    id = binding.read_id(root)
    assert id is not None
    written = (root / SETTINGS).is_file()
    settings = json.loads((root / SETTINGS).read_text(encoding="utf-8")) if written else {}
    assert settings.get(POINTER) == str(store_directory(id))
    assert ledger(root).settings_keys == (POINTER,)


def test_the_composed_store_is_the_recorded_projects_and_moves_only_when_attach_rebinds(
    tmp_path: Path,
) -> None:
    # The project a composed store is built for is the one this machine's binding record names,
    # never the repository's `[project] name` read on its own: a checkout bound to `p` whose
    # `stayfixed.toml` now names `q` keeps `p`'s store until `attach` records the new binding, and
    # then gets `q`'s.
    from stayfixed import binding
    from stayfixed.memory.store import composed_directory as store_directory

    root, store, machine = _attachable(tmp_path)
    attach(root, store=store, machine=machine, runner=Recorder())
    id = binding.read_id(root)
    assert id is not None
    composed = store_directory(id)
    overlay = store.parents[2]
    (store / "project-stable").mkdir(exist_ok=True)
    root, other = _project_and_store(tmp_path, recorded=None, origin="git@x:o/p.git", name="q")
    (other / "project-stable").mkdir(exist_ok=True)
    assert (composed / "MEMORY.md").readlink() == overlay / "projects/p/memory/MEMORY.md"
    attach(root, store=other, machine=machine, runner=Recorder())
    found = binding.bound_project(root)
    assert found is not None and found.project == "q"
    assert (composed / "MEMORY.md").readlink() == overlay / "projects/q/memory/MEMORY.md"
    assert (composed / "project-stable").resolve() == (other / "project-stable").resolve()


def test_attach_needs_no_store_argument(tmp_path: Path) -> None:
    # The store is derived: this project's share of the overlay the machine records.
    from stayfixed import binding

    root, _, machine = _attachable(tmp_path)
    code, out, err = cli(root, tmp_path, "attach", machine=machine)
    assert code == 0, out + err
    found = binding.bound_project(root)
    assert found is not None and found.project == "p"


def test_a_mode_other_than_overlay_writes_no_memory_pointer(tmp_path: Path) -> None:
    # Only the overlay's notes are composed; a repository that keeps its own store gets no key.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    config = root / CONFIG_FILE
    config.write_text(
        config.read_text(encoding="utf-8").replace('mode = "overlay"', 'mode = "local-only"'),
        encoding="utf-8",
    )
    attach(root, store=store, machine=machine, runner=Recorder())
    assert "autoMemoryDirectory" not in json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert ledger(root).settings_keys == ()


def test_a_second_attach_that_changes_nothing_leaves_the_settings_file_alone(
    tmp_path: Path,
) -> None:
    # The guard for the clause above: `owned_ids` widened the early return, and a widening that
    # went too far would reformat a file the owner owns on every run and report itself as a
    # write. A second attach of an overlay that grants nothing touches nothing: the pointer the
    # first one wrote is already there.
    root, store, machine = _attachable(tmp_path)
    attach(root, store=store, machine=machine, runner=Recorder())
    before = (root / SETTINGS).read_bytes()
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    assert not attached.settings_written
    assert (root / SETTINGS).read_bytes() == before


def test_a_first_attach_records_the_remote_and_the_date(tmp_path: Path) -> None:
    # projects/<name>/project.toml holds the bound remote URL and the first-attach date.
    import datetime
    import tomllib

    root, store, machine = _attachable(tmp_path)
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    record = tomllib.loads((store.parent / "project.toml").read_text(encoding="utf-8"))
    assert record["remote"] == "git@example.com:o/p.git"
    assert datetime.date.fromisoformat(str(record["first_attach"]))


def test_a_record_that_already_binds_this_repository_is_left_alone(tmp_path: Path) -> None:
    # The record is the owner's consent, and its date is when they gave it. Rewriting it on
    # every attach turns a fact into a timestamp of the last run — so a repository the overlay
    # already records correctly is not written at all.
    import tomllib

    root, store, machine = _attachable(tmp_path)
    runner = Recorder()
    attach(
        root,
        store=store,
        machine=machine,
        runner=runner,
    )
    record = store.parent / "project.toml"
    first = tomllib.loads(record.read_text(encoding="utf-8"))["first_attach"]
    record.write_text(
        record.read_text(encoding="utf-8").replace(str(first), "2000-01-01"), encoding="utf-8"
    )
    attach(
        root,
        store=store,
        machine=machine,
        runner=runner,
    )
    assert tomllib.loads(record.read_text(encoding="utf-8"))["first_attach"] == "2000-01-01"


def test_the_merged_rules_are_recorded_where_they_can_be_removed_again(tmp_path: Path) -> None:
    # The ledger lives in the git common directory, because the committed manifest would publish a
    # digest of the owner's personal allow rules to collaborators.
    hooks = {"SessionStart": [{"hooks": [ENTRY]}]}
    root, store, machine = _attachable(tmp_path, allow=(RULE,), hooks=hooks)
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    recorded = ledger(root)
    assert recorded.allow == (RULE,)
    assert recorded.entries == {}
    assert recorded.render is not None
    assert ledger_file(root).is_file()


def test_attach_writes_nothing_into_gitignore_and_leaves_git_status_empty(tmp_path: Path) -> None:
    # The ledger was kept out of git by a `stayfixed:ignore` region `attach` wrote into
    # `.gitignore`, a tracked file, so every first attach left a change every collaborator would
    # get. The ledger is in the git common directory now and the rest is hidden through the
    # exclude block, and `.gitignore` is not written at all.
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _committed(root)
    before = (root / ".gitignore").read_bytes()
    _attach_quietly(root, store, machine)
    # Non-vacuous: the run placed the settings file, which git would show.
    assert ledger_file(root).is_file() and (root / SETTINGS).is_file()
    assert _git(root, "status", "--porcelain=v1", "-z", "-uall") == ""
    assert (root / ".gitignore").read_bytes() == before


def test_a_gitignore_that_re_includes_the_settings_file_refuses_before_it_is_written(
    tmp_path: Path,
) -> None:
    # A pull request adding `!.claude/settings.local.json` to the tracked `.gitignore`: a
    # `.gitignore` outranks the exclude file, so the block's line hides nothing and the settings
    # file, which names what only this machine may know, would show in `git status` and go out
    # with the next `git add -A`. git is asked about every placed path once the block stands, and
    # the run stops there, naming the path, with the settings file not written.
    #
    # Mutation: `mutations/`'s "the ignore check skips the settings file".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    (root / ".gitignore").write_text(f"!{SETTINGS}\n", encoding="utf-8")
    _committed(root)
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert str(refused.value) == NOT_IGNORED.format(paths=quoted(SETTINGS))
    assert not (root / SETTINGS).exists()
    assert not ledger_file(root).exists()
    assert not (root / ".codex" / "rules").exists()


def test_a_tracked_local_settings_file_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # No exclude line hides a tracked file, so a repository that tracks its
    # `.claude/settings.local.json` would carry whatever `attach` merged into it to every clone.
    # Refused before the first write, by `--check` as by the run.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    (root / SETTINGS).write_text("{}\n", encoding="utf-8")
    _committed(root)
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert str(refused.value) == TRACKED.format(paths=quoted(SETTINGS))
    assert_snapshot_unchanged(root, before)
    with pytest.raises(Refusal) as previewed:
        check(root, store=store, machine=machine)
    assert str(previewed.value) == TRACKED.format(paths=quoted(SETTINGS))


def test_a_tracked_codex_rule_copy_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    # Every placed path is held to one rule, and the settings file was its only member: a
    # repository tracking `.codex/rules/common.rules` had it overwritten by the overlay's rule,
    # since `check-ignore --no-index` answers "ignored" for a tracked path the block names.
    #
    # Mutation: `mutations/`'s "attach writes over a tracked placed path".
    root, store, machine = _attachable(tmp_path, codex="# the overlay's rule\n")
    (root / ".codex" / "rules").mkdir(parents=True)
    (root / ".codex" / "rules" / "common.rules").write_text("# the project's\n", "utf-8")
    _committed(root)
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert str(refused.value) == TRACKED.format(paths=quoted(".codex/rules/common.rules"))
    assert_snapshot_unchanged(root, before)


def _case_blind(directory: Path) -> bool:
    probe = directory / "case-probe"
    probe.write_text("", encoding="utf-8")
    try:
        return (directory / "CASE-PROBE").exists()
    finally:
        probe.unlink()


def test_a_tracked_settings_file_spelled_in_another_case_is_refused_and_left_as_it_was(
    tmp_path: Path,
) -> None:
    # On a filesystem that ignores case, `.claude/Settings.Local.json` in the index is the file
    # `.claude/settings.local.json` opens, so a case-sensitive question let `attach` write into a
    # tracked file. The index is asked under any case of each placed path's spelling.
    if not _case_blind(tmp_path):
        pytest.skip("the temporary filesystem tells case apart")
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    tracked = root / ".claude" / "Settings.Local.json"
    tracked.write_text("{}\n", encoding="utf-8")
    _committed(root)
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert str(refused.value) == TRACKED.format(paths=quoted(SETTINGS))
    assert tracked.read_bytes() == b"{}\n"


def test_a_tracked_settings_file_under_a_directory_spelled_in_another_case_is_refused(
    tmp_path: Path,
) -> None:
    # The directory's spelling folds too: `.CLAUDE/settings.local.json` in the index is what
    # `.claude/settings.local.json` opens on a filesystem that ignores case, and a question about
    # the directory as spelled listed nothing to compare with.
    if not _case_blind(tmp_path):
        pytest.skip("the temporary filesystem tells case apart")
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".CLAUDE").mkdir()
    tracked = root / ".CLAUDE" / "settings.local.json"
    tracked.write_text("{}\n", encoding="utf-8")
    _committed(root)
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert str(refused.value) == TRACKED.format(paths=quoted(SETTINGS))
    assert tracked.read_bytes() == b"{}\n"


def test_a_tracked_settings_file_in_another_case_deleted_from_the_work_tree_is_refused(
    tmp_path: Path,
) -> None:
    # With `core.ignorecase` git takes a newly written `settings.local.json` for the tracked
    # `Settings.Local.json` whose file was deleted, and shows it as a modified tracked file. Nothing
    # is there to compare identities with, so git's own view of case is asked.
    if not _case_blind(tmp_path):
        pytest.skip("the temporary filesystem tells case apart")
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    (root / ".claude" / "Settings.Local.json").write_text("{}\n", encoding="utf-8")
    _committed(root)
    (root / ".claude" / "Settings.Local.json").unlink()
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert str(refused.value) == TRACKED.format(paths=quoted(SETTINGS))
    assert not (root / SETTINGS).exists()


def _folds_long_s(directory: Path) -> bool:
    probe = directory / "\u017fprobe"
    probe.write_text("", encoding="utf-8")
    try:
        return (directory / "sprobe").exists()
    finally:
        probe.unlink()


def test_a_tracked_settings_file_a_filesystem_folds_to_the_placed_name_is_refused(
    tmp_path: Path,
) -> None:
    # APFS folds `\u017f` (LATIN SMALL LETTER LONG S) to `s`, so a tracked
    # `.claude/\u017fettings.local.json` is the file `.claude/settings.local.json` opens; git's
    # `icase` pathspec and `str.lower` fold ASCII alone, and `attach` wrote the allow rules, and
    # Claude Code the binding id, into a tracked file. Asked of the filesystem, by identity, and
    # never by emulating its folding.
    if not _folds_long_s(tmp_path):
        pytest.skip("the temporary filesystem does not fold a long s to an s")
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    tracked = root / ".claude" / "\u017fettings.local.json"
    tracked.write_text("{}\n", encoding="utf-8")
    _committed(root)
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert str(refused.value) == TRACKED.format(paths=quoted(SETTINGS))
    assert tracked.read_bytes() == b"{}\n"


def test_a_placed_path_that_is_the_same_file_as_a_tracked_one_is_refused(tmp_path: Path) -> None:
    # The identity half of the rule on any filesystem: a hard link is what a folded name is, one
    # file under two names, and a write through the untracked one lands in the tracked one.
    # Mutation: `mutations/`'s "attach asks git alone whether a placed path is tracked".
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    tracked = root / ".claude" / "settings.json"
    tracked.write_text("{}\n", encoding="utf-8")
    _committed(root)
    os.link(tracked, root / SETTINGS)
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert str(refused.value) == TRACKED.format(paths=quoted(SETTINGS))
    assert tracked.read_bytes() == b"{}\n"


CONFLICTED = '<<<<<<< HEAD\nfirst_attach = "2026-10-01"\n=======\nfirst_attach = "2026-10-02"\n'


def test_an_overlay_project_record_that_cannot_be_read_stops_attach_but_not_the_session(
    tmp_path: Path,
) -> None:
    # The overlay's `projects/<name>/project.toml` keeps the first remote and date for the owner to
    # read, and the tags it lists: the binding is the id and this machine's record of it. Two
    # machines that first-attach one project each write it, and the overlay's merge leaves conflict
    # markers. A write run cannot tell which tags that lists and refuses, never writing over it;
    # the session's binding check is not silenced by it.
    from stayfixed.attach.binding import binding_for

    root, store, machine = _attachable(tmp_path)
    attach(root, store=store, machine=machine, runner=Recorder())
    record = store.parent / PROJECT_RECORD
    record.write_text(CONFLICTED, encoding="utf-8")
    with pytest.raises(Refusal, match="is not valid TOML"):
        attach(root, store=store, machine=machine, runner=Recorder())
    assert record.read_text(encoding="utf-8") == CONFLICTED
    found = binding_for(root, load(root, machine=machine), machine=machine)
    assert found.state == "bound"


@pytest.mark.parametrize("blocked", ["bindings", "delivery"])
def test_a_write_under_the_data_directory_that_fails_names_the_binding_by_its_short_form(
    tmp_path: Path, blocked: str
) -> None:
    # The binding record and the render are named by the whole id, and an `OSError` writing either
    # escaped to the command line's "internal error", whose text is the absolute path ending in the
    # id, relayed by the attach skill into the transcript. Said here with the directory and the id's
    # first eight characters. A file where the directory goes is one way to get there.
    from stayfixed import binding

    root, store, machine = _attachable(tmp_path)
    data = Path(os.environ["HOME"]) / ".local" / "share" / "stayfixed"
    data.mkdir(parents=True)
    (data / blocked).write_text("in the way\n", encoding="utf-8")
    with pytest.raises(Failure) as failed:
        attach(root, store=store, machine=machine, runner=Recorder())
    id = binding.read_id(root)
    assert id is not None
    assert id not in str(failed.value) and binding.short(id) in str(failed.value)


def _with_groups(root: Path, listed: str) -> None:
    text = (root / "stayfixed.toml").read_text(encoding="utf-8")
    (root / "stayfixed.toml").write_text(
        text.replace('groups = ["developer", "project-stable"]', f"groups = {listed}"),
        encoding="utf-8",
    )


def test_a_memory_group_that_leaves_the_projects_share_is_refused_not_created(
    tmp_path: Path,
) -> None:
    # `memory.groups` is repository-authored (principle 5) and reaches no guard of its own —
    # `config/paths.py` says so in as many words, and leaves the containment to the module that
    # consumes the field. The entry decides a directory created inside the OVERLAY, which is the
    # one tree `attach` trusts, so a `..` in it is refused rather than created, and refused rather
    # than crashing out as a raw `OSError`.
    #
    # **And refused before the first write**, which is the half this case was missing. The
    # containment was called from `_prepare_store`, which runs after the ignore region, the
    # `.codex/rules/` copies, the settings merge, the ledger *and* the overlay's binding record
    # — so a clone committing the entry below got five artifacts written and exit 2, and
    # `doctor._attached` then reported the repository attached and the binding **bound**,
    # because the record had been written too. The overlay is left out of the snapshot on
    # purpose: the binding record lives there, and asserting on the repository is what the
    # separate assertion below the snapshot is for.
    #
    # Mutation: `mutations/`'s "the memory.groups containment is asked at write time only".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    _with_groups(root, '["../../escape"]')
    before = snapshot(root)
    # `snapshot` is a walk, and an empty one satisfies the comparison below on its own.
    assert before
    with pytest.raises(Refusal) as refusal:
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )
    # Non-vacuous: this refusal and not another `attach` can raise before it. The identity is what
    # keeps the hoisted call proven. (`GROUP_ESCAPES` names `memory.groups`, which is what a
    # reader needs from it; asserting that here would be an assertion about a literal that no
    # behaviour change can redden.)
    assert str(refusal.value) == GROUP_ESCAPES
    # The entry itself is repository-authored, so it is not quoted back.
    assert "../../escape" not in str(refusal.value)
    assert not (store.parents[2].parent / "escape").exists()
    assert_snapshot_unchanged(root, before)
    # The one write that is not under the root, and the one that made `doctor` say `bound`.
    assert not (store.parent / PROJECT_RECORD).exists()


@ROOT_SEARCHES_EVERYTHING
def test_a_memory_group_whose_place_in_the_share_cannot_be_asked_about_is_refused_for_that(
    tmp_path: Path,
) -> None:
    # A real group directory in the overlay that nobody may search: no link is on the way and the
    # entry stays inside the share, so `GROUP_ESCAPES` named a cause it did not have. Refused all
    # the same, before the first write, since no path is contained until every ancestor is asked.
    # Mutation (oracle): `mutations/`'s "attach words a group it cannot ask about as an escape".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    (store / "project-stable").mkdir()
    before = snapshot(root)
    assert before
    with unsearchable(store / "project-stable"), pytest.raises(Refusal) as refusal:
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )
    assert str(refusal.value) == GROUP_UNASKED.format(fault="Permission denied")
    assert_snapshot_unchanged(root, before)


@ROOT_SEARCHES_EVERYTHING
def test_a_codex_directory_linked_where_nobody_may_search_is_refused_by_name_by_check_and_run(
    tmp_path: Path,
) -> None:
    # A clone commits `.codex` as a link under a directory its user cannot search. Whether
    # `.codex/rules` was there to be recorded as made by this run was asked through the link,
    # which met the fault: `--check` and the run ended in an internal error that printed the path,
    # above the containment refusal that names the link. Mutation (oracle): `mutations/`'s "attach
    # asks whether a directory it would create is there through a link it cannot follow".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    locked = tmp_path / "locked"
    locked.mkdir()
    shutil.rmtree(root / ".codex", ignore_errors=True)
    (root / ".codex").symlink_to(locked / "x")
    before = snapshot(root)
    refused = "'.codex/rules/common.rules' passes through a symlink at '.codex'"
    with unsearchable(locked):
        with pytest.raises(Refusal) as checked:
            check(root, store=store, machine=machine)
        with pytest.raises(Refusal) as run:
            attach(
                root,
                store=store,
                machine=machine,
                runner=Recorder(),
            )
    assert str(checked.value) == str(run.value) == refused
    assert_snapshot_unchanged(root, before)


def test_the_memory_group_refusal_is_reached_on_a_run_that_would_have_written(
    tmp_path: Path,
) -> None:
    # The vacuity guard for the snapshot above, and the same one the no-origin refusal and the
    # ledger refusal carry: a refusal that writes nothing proves nothing if the run had nothing to
    # write. The identical fixture with a group name that stays inside this project's share
    # attaches, and leaves behind every artifact the case above has to prevent.
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    _with_groups(root, '["developer", "project-stable"]')
    before = snapshot(root)
    assert before
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    after = snapshot(root)
    added = set(after) - set(before)
    assert attached.settings_written and attached.binding_recorded
    assert {SETTINGS, ".codex/rules/common.rules"} <= added and ledger_file(root).is_file()
    assert before.get(".git/info/exclude") != after.get(".git/info/exclude")
    assert (store.parent / PROJECT_RECORD).is_file()
    assert (store / "project-stable").is_dir()


def test_a_second_attach_adds_nothing_twice(tmp_path: Path) -> None:
    # `attach` is idempotent and reversible by `detach`. A permission list that grows by one copy of
    # every rule per attach is the shape this catches.
    hooks = {"SessionStart": [{"hooks": [ENTRY]}]}
    root, store, machine = _attachable(tmp_path, allow=(RULE,), hooks=hooks)
    runner = Recorder()
    attach(
        root,
        store=store,
        machine=machine,
        runner=runner,
    )
    attach(
        root,
        store=store,
        machine=machine,
        runner=runner,
    )
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert document.pop(POINTER) and document == {"permissions": {"allow": [RULE]}}
    assert ledger(root).allow == (RULE,)


def test_a_second_attach_still_claims_what_the_first_one_added(tmp_path: Path) -> None:
    # The idempotence above is what makes this possible to get wrong: on the second run the
    # rule is already present, so the *diff* is empty — and a ledger written from the diff
    # alone would forget it, leaving `detach` nothing to remove.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    runner = Recorder()
    attach(
        root,
        store=store,
        machine=machine,
        runner=runner,
    )
    attach(
        root,
        store=store,
        machine=machine,
        runner=runner,
    )
    assert ledger(root).allow == (RULE,)


def test_codex_rules_land_under_the_directory_codex_reads(tmp_path: Path) -> None:
    # `attach` places Codex rules under .codex/rules/. Kept separate from the Claude settings merge
    # because the two harnesses fail differently and a shared path would hide which.
    root, store, machine = _attachable(tmp_path, codex="# standing rule\n")
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    landed = root / ".codex" / "rules" / "common.rules"
    assert landed.read_text(encoding="utf-8") == "# standing rule\n"
    assert ".codex/rules/common.rules" in attached.rules_written
    assert ledger(root).rules == (".codex/rules/common.rules",)


@ROOT_SEARCHES_EVERYTHING
@pytest.mark.parametrize("mode", [0o000, 0o444], ids=["unlistable", "unsearchable"])
@pytest.mark.parametrize("where", ["common", "project"])
def test_an_unlistable_codex_directory_fails_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str, mode: int
) -> None:
    # An overlay `codex/` directory this user cannot list ended `attach --check` and `attach` in
    # `internal error: PermissionError`, while an unreadable rule file inside it is a failure that
    # names the file. One fault class, one classification: both are the overlay holding something
    # this user cannot read. At 0o444 the listing succeeds and asking whether an entry is a file
    # does not, so the guard covers both. The project's directory carries `project.name`, so its
    # path prints through `printed.quoted`. Mutation (oracle): `mutations/`'s "an overlay codex
    # directory that cannot be listed is an internal error".
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    overlay = store.parents[2]
    directory = overlay / COMMON_CODEX if where == "common" else store.parent / "codex"
    directory.mkdir(exist_ok=True)
    (directory / "project.rules").write_text("# a project rule\n", encoding="utf-8")
    flags = ("--store", str(store))
    before = snapshot(root)
    directory.chmod(mode)
    try:
        checked = cli(root, tmp_path, "attach", "--check", *flags, machine=machine)
        attached = cli(root, tmp_path, "attach", *flags, machine=machine)
    finally:
        directory.chmod(0o755)
    line = (
        f"stayfixed: failed: {quoted(str(directory))} cannot be listed (Permission denied), "
        "so nothing was written\n"
    )
    assert (checked[0], checked[2]) == (attached[0], attached[2]) == (1, line)
    assert "internal error" not in checked[2] + attached[2]
    # A guard and not the fix's proof: the listing happens while the run is planned, so nothing
    # was written before this change either.
    assert_snapshot_unchanged(root, before)


@pytest.mark.parametrize("fault", ["not-utf8", "unreadable"])
@pytest.mark.parametrize("where", ["common", "project"])
def test_an_overlay_rule_file_that_cannot_be_read_fails_naming_it_as_its_directory_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str, fault: str
) -> None:
    # The sibling of the unlistable `codex/` directory above, one fault class: a rule file inside
    # it this user cannot read, or that is not UTF-8. Its directory is printed through
    # `printed.quoted` and the file was printed raw, though the project's path carries
    # `project.name`, which the repository chooses. Mutation (oracle): `mutations/`'s "an overlay
    # rule file that cannot be read is printed raw" -> the path loses its quotes.
    if fault == "unreadable" and os.geteuid() == 0:
        pytest.skip("root reads every file")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    overlay = store.parents[2]
    directory = overlay / COMMON_CODEX if where == "common" else store.parent / "codex"
    directory.mkdir(exist_ok=True)
    rule = directory / "z.rules"
    if fault == "not-utf8":
        rule.write_bytes(b"\xff\xfe not text\n")
    else:
        rule.write_text("# a rule\n", encoding="utf-8")
        rule.chmod(0o000)
    flags = ("--store", str(store))
    before = snapshot(root)
    try:
        checked = cli(root, tmp_path, "attach", "--check", *flags, machine=machine)
        attached = cli(root, tmp_path, "attach", *flags, machine=machine)
    finally:
        rule.chmod(0o644)
    why = "is not UTF-8 text" if fault == "not-utf8" else "cannot be read (Permission denied)"
    line = f"stayfixed: failed: {quoted(str(rule))} {why}, so nothing was written\n"
    assert (checked[0], checked[2]) == (attached[0], attached[2]) == (1, line)
    assert_snapshot_unchanged(root, before)


def test_a_rule_the_overlay_never_granted_is_left_alone(tmp_path: Path) -> None:
    # `doctor` lists every rule with its provenance, so one no overlay granted is visible. attach's
    # own contribution to that is narrower and stricter: it does not touch one.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    (root / SETTINGS).write_text(
        json.dumps({"permissions": {"allow": ["Bash(rm:*)"]}}), encoding="utf-8"
    )
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    allow = json.loads((root / SETTINGS).read_text(encoding="utf-8"))["permissions"]["allow"]
    assert allow == ["Bash(rm:*)", RULE]
    assert ledger(root).allow == (RULE,)


def test_attach_runs_no_program_in_the_overlay(tmp_path: Path) -> None:
    # `pre-commit install` is `setup --overlay`'s, which makes the overlay: `attach` binds a
    # repository to it and launches nothing in it, even where its secret scan is not installed.
    # `doctor`'s `pre-commit` row is what tells the second machine.
    root, store, machine = _attachable(tmp_path)
    _overlay_repository(store.parents[2])
    (store.parents[2] / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    runner = Recorder()
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=runner,
    )
    assert [argv for argv in runner.calls if argv[0] == "pre-commit"] == []
    assert not any("pre-commit" in note for note in attached.notes)


def test_a_record_with_no_remote_is_given_one_and_keeps_its_first_attach_date(
    tmp_path: Path,
) -> None:
    # The one path that rewrites an existing record, and the reason the date is read back rather
    # than re-stamped: `first_attach` is when the project was first attached, not the last run.
    import tomllib

    root, store, machine = _attachable(tmp_path)
    (store.parent / "project.toml").write_text('first_attach = "2020-02-02"\n', encoding="utf-8")
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    record = tomllib.loads((store.parent / "project.toml").read_text(encoding="utf-8"))
    assert record["remote"] == "git@example.com:o/p.git"
    assert record["first_attach"] == "2020-02-02"


def test_attach_keeps_every_key_and_byte_of_the_record_it_did_not_write(tmp_path: Path) -> None:
    # The owner lists `tags` in the record by hand, with comments around them; the record is the
    # owner's, and `attach` adds the two keys it owns above everything and rewrites nothing else.
    # Mutation (`mutations/`'s "attach rewrites the whole project record"): the file is written
    # from the parsed keys, and the comment, the tag list and the table are gone.
    import datetime
    import tomllib

    root, store, machine = _attachable(tmp_path)
    original = '# who is on what\ntags = ["a"]\n\n[notes]\nowner = "me"  # kept\n'
    (store.parent / PROJECT_RECORD).write_text(original, encoding="utf-8")
    attach(root, store=store, machine=machine, runner=Recorder())
    text = (store.parent / PROJECT_RECORD).read_text(encoding="utf-8")
    today = datetime.date.today().isoformat()
    assert text == f'remote = "git@example.com:o/p.git"\nfirst_attach = "{today}"\n' + original
    assert tomllib.loads(text)["tags"] == ["a"]


def test_attach_keeps_the_line_endings_of_the_record_it_did_not_write(tmp_path: Path) -> None:
    root, store, machine = _attachable(tmp_path)
    original = b'tags = ["a"]\r\n'
    (store.parent / PROJECT_RECORD).write_bytes(original)
    attach(root, store=store, machine=machine, runner=Recorder())
    assert (store.parent / PROJECT_RECORD).read_bytes().endswith(original)


def test_attach_writes_no_key_the_record_holds_unusable(tmp_path: Path) -> None:
    # A second `remote` beside an empty one would make the file invalid TOML, and a file the
    # owner wrote stays theirs: only `first_attach`, which is absent, goes in.
    import datetime
    import tomllib

    root, store, machine = _attachable(tmp_path)
    (store.parent / PROJECT_RECORD).write_text('remote = ""\n', encoding="utf-8")
    attach(root, store=store, machine=machine, runner=Recorder())
    text = (store.parent / PROJECT_RECORD).read_text(encoding="utf-8")
    today = datetime.date.today().isoformat()
    assert text == f'first_attach = "{today}"\nremote = ""\n'
    assert tomllib.loads(text)["remote"] == ""


def test_a_record_that_holds_both_keys_is_not_written(tmp_path: Path) -> None:
    root, store, machine = _attachable(tmp_path)
    original = 'first_attach = "2020-02-02"\nremote = "git@example.com:o/p.git"\ntags = []\n'
    (store.parent / PROJECT_RECORD).write_text(original, encoding="utf-8")
    attach(root, store=store, machine=machine, runner=Recorder())
    assert (store.parent / PROJECT_RECORD).read_text(encoding="utf-8") == original


def test_a_repository_with_no_origin_remote_attaches_and_records_none(tmp_path: Path) -> None:
    # A checkout with no `origin` was refused, above every write. The binding is the id now, so it
    # attaches like any other, says so, and the records carry no remote.
    import tomllib

    from stayfixed import binding

    hooks = {"SessionStart": [{"hooks": [ENTRY]}]}
    root, store, machine = _attachable(
        tmp_path, allow=(RULE,), hooks=hooks, codex="# a standing rule\n"
    )
    run_git(root, "remote", "remove", "origin")
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    assert attached.settings_written and attached.binding_recorded
    assert NO_ORIGIN_NOTE in attached.notes
    record = tomllib.loads((store.parent / "project.toml").read_text(encoding="utf-8"))
    assert "remote" not in record
    found = binding.bound_project(root)
    assert found is not None and found.origin is None


def test_a_settings_file_the_merge_cannot_read_is_refused_and_never_filtered(
    tmp_path: Path,
) -> None:
    # `scaffold.entries`' rule, one file over: what a filter drops here is somebody's own
    # setting, and nothing would say it went.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    (root / SETTINGS).write_text(json.dumps({"permissions": {"allow": "all"}}), encoding="utf-8")
    with pytest.raises(Refusal):
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )


def test_an_overlay_hooks_file_with_an_unreadable_shape_is_refused(tmp_path: Path) -> None:
    # The same rule on the other side. An overlay entry this cannot key is one the owner put
    # there on purpose, and installing the rest of the file while dropping it silently is how
    # a hook goes missing with nothing to say so.
    root, store, machine = _attachable(tmp_path)
    (store.parents[2] / COMMON_CLAUDE / "hooks.json").write_text(
        json.dumps({"hooks": {"SessionStart": "not a list"}}), encoding="utf-8"
    )
    with pytest.raises(Refusal):
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )


def test_a_ledger_that_is_not_json_is_a_failure_and_not_an_empty_one(tmp_path: Path) -> None:
    # An empty ledger reads as "attach added nothing", which makes `detach` a no-op on a
    # repository that has stayfixed's rules in it — the quiet half of the failure this file is
    # the only witness to.
    root, store, machine = _attachable(tmp_path)
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    ledger_file(root).write_text("{", encoding="utf-8")
    with pytest.raises(Failure):
        ledger(root)


# `NESTED`, which no reader caught, in two files a clone can commit.


def test_a_ledger_nested_past_the_parsers_reach_is_a_failure_and_never_an_internal_error(
    tmp_path: Path,
) -> None:
    # The ledger is the unreadable ledger it is, and the attach that reads it back answers so
    # rather than ending in an internal error. Mutation (oracle): `mutations/`'s "the JSON object
    # reader lets a document nested past the parser raise" -> both raise `RecursionError`.
    root, store, machine = _attachable(tmp_path)
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    ledger_file(root).write_text('{"entries": ' + NESTED + "}", encoding="utf-8")
    with pytest.raises(Failure, match="nested deeper"):
        ledger(root)
    with pytest.raises(Failure, match="nested deeper"):
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )


def test_a_settings_file_nested_past_the_parsers_reach_is_refused(tmp_path: Path) -> None:
    # The settings file `attach` merges into, read first by `permissions.settings_document`.
    # Mutation (oracle): `mutations/`'s "the JSON object reader lets a document nested past the
    # parser raise" -> both raise `RecursionError`.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    (root / SETTINGS).write_text('{"hooks": ' + NESTED + "}", encoding="utf-8")
    with pytest.raises(EntriesError, match="nested deeper"):
        settings_document((root / SETTINGS).read_text(encoding="utf-8"))
    with pytest.raises(Refusal, match="nested deeper"):
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )


# `LONG_NUMBER`, which no reader caught, in two files a clone can commit.


def test_a_ledger_holding_a_number_past_the_parsers_reach_is_a_failure_and_never_an_internal_error(
    tmp_path: Path,
) -> None:
    # Mutation (oracle): `mutations/`'s "the JSON object reader lets a number past the parser's
    # reach raise" -> both raise `ValueError`.
    root, store, machine = _attachable(tmp_path)
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    ledger_file(root).write_text('{"entries": {"x": ' + LONG_NUMBER + "}}", encoding="utf-8")
    with pytest.raises(Failure, match="number longer"):
        ledger(root)
    with pytest.raises(Failure, match="number longer"):
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )


def test_a_settings_file_holding_a_number_past_the_parsers_reach_is_refused(tmp_path: Path) -> None:
    # Mutation (oracle): `mutations/`'s "the JSON object reader lets a number past the parser's
    # reach raise" -> both raise `ValueError`.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / ".claude").mkdir()
    (root / SETTINGS).write_text('{"hooks": {}, "n": ' + LONG_NUMBER + "}", encoding="utf-8")
    with pytest.raises(EntriesError, match="number longer"):
        settings_document((root / SETTINGS).read_text(encoding="utf-8"))
    with pytest.raises(Refusal, match="number longer"):
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )


def _committed_ledger(root: Path, store: Path, **fields: object) -> None:
    """A ledger in the git common directory that no `attach` of this run wrote, as an earlier run
    or a hand edit could leave one."""
    document: dict[str, object] = {
        "format": 1,
        "store": str(store),
        "allow": [],
        "entries": {},
        "rules": [],
        "settings_keys": [],
    }
    document.update(fields)
    ledger_file(root).parent.mkdir(parents=True, exist_ok=True)
    ledger_file(root).write_text(json.dumps(document), encoding="utf-8")


def test_a_ledger_no_attach_could_have_written_is_refused_before_the_first_write(
    tmp_path: Path,
) -> None:
    # The same shape as `test_a_repository_with_no_origin_remote_has_nothing_to_record`, one
    # door over, and introduced by the commit that wrote that rule down. `ledger()` refuses a
    # ledger naming files or settings keys `attach` could not have written, and `_write_ledger`
    # used to be the thing that asked for it — from the fourth write of the run. So a clone
    # committing such a ledger got `attach` to write the `stayfixed:ignore` region, copy
    # `.codex/rules/*` and merge `.claude/settings.local.json`, and only then exit 2 — with the
    # committed ledger still on disk, which `doctor._attached` keys on. `attach --check`, which
    # used to report clean beforehand, now reads the ledger with the run's reader and refuses too.
    #
    # Nothing the repository gains here differs from a successful attach, so this is not a trust
    # boundary being crossed. What it is, is `docs/cli.md` asserting that every cause of exit 2
    # happens before the first write while one of them did not.
    #
    # Mutation: `mutations/`'s "the ledger is read after attach has already written".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    _committed_ledger(root, store, rules=[".github/workflows/ci.yml"])
    before = snapshot(root)
    # `snapshot` is a walk, and an empty one satisfies the comparison below on its own.
    assert before
    with pytest.raises(Refusal):
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )
    assert_snapshot_unchanged(root, before)


def test_the_refused_ledger_is_reached_on_a_run_that_would_have_written_three_files(
    tmp_path: Path,
) -> None:
    # The vacuity guard for the case above, and the same one the no-origin refusal's snapshot has: a
    # refusal that writes nothing proves nothing if the run had nothing to write. The identical
    # fixture, with a ledger `attach` really could have written, attaches and leaves all three
    # artifacts the refusal above has to prevent.
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    _committed_ledger(root, store, rules=[".codex/rules/common.rules"])
    before = snapshot(root)
    assert before
    attached = attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    after = snapshot(root)
    assert attached.settings_written
    assert ".codex/rules/common.rules" in set(after) - set(before)
    assert SETTINGS in set(after) - set(before)
    assert before.get(".git/info/exclude") != after.get(".git/info/exclude")
    # And the union the ledger exists for survived the refusal being hoisted out of the writer:
    # `_write_ledger` is handed the ledger the caller read once, above every write.
    assert ledger(root).rules == (".codex/rules/common.rules",)


def test_an_overlay_store_the_walk_cannot_enter_is_refused_at_write_time(tmp_path: Path) -> None:
    # The floor under the containment hoisted above every write, and the proof it is not dead.
    # `config.paths.contained` answers about a *spelling* and about the symlinks it can see when
    # it looks; `fsops.mkdirs_within` asks the filesystem again at the moment of writing, through
    # the `O_NOFOLLOW` walk, which is the only thing that can catch a component that is not a
    # directory — or became a symlink in between. Here the overlay holds a regular file where
    # this project's memory directory belongs, which `contained` passes and the walk refuses.
    #
    # This is the one remaining way this refusal can arrive after a write, and it is a fact
    # about the overlay — the owner's own tree — rather than about a repository-authored entry.
    #
    # Mutation: `mutations/`'s "the write-time containment on the overlay's store directory
    # is swallowed".
    root, store, machine = _attachable(tmp_path)
    shutil.rmtree(store)
    store.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(Refusal) as refusal:
        attach(
            root,
            store=store,
            machine=machine,
            runner=Recorder(),
        )
    assert "memory.groups" in str(refusal.value)


def test_a_worktree_listing_git_gave_no_answer_for_is_a_failure_about_this_machine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `-1` from `git_run` is a `git` that could not be run or ran past its bound: a fault on
    # this machine, and never a listing with no main checkout. A worktree path that is not UTF-8
    # is no longer a cause — the listing is decoded losslessly — so the message does not send the
    # owner looking for one. Mutation (advisory): put the UTF-8 clause back — the last assertion
    # reddens.
    from stayfixed import binding
    from stayfixed.attach import write as module

    monkeypatch.setattr(binding, "git_run", lambda *a, **k: (-1, ""))
    with pytest.raises(Failure, match="check that `git` runs here") as caught:
        module.main_checkout_of(tmp_path)
    assert "UTF-8" not in str(caught.value)


# --- what `attach` leaves for `git status` to show -------------------------------------------

EXCLUDE_REGION = "attach"


def _exclude(root: Path) -> Path:
    return root / ".git" / "info" / "exclude"


def _committed(root: Path) -> None:
    """Commit what the fixture wrote, so `git status` afterwards shows only what `attach` added."""
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "the project as it was")


def _status(root: Path) -> list[str]:
    return _git(root, "status", "--porcelain", "--untracked-files=all").splitlines()


def _placed() -> list[str]:
    """Every path `attach` puts into the project for this fixture: the Codex rule it copies and
    the settings file."""
    return [".codex/rules/common.rules", SETTINGS]


def _attach_quietly(root: Path, store: Path, machine: Path) -> None:
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )


def test_attach_leaves_nothing_for_git_status(tmp_path: Path) -> None:
    # `.codex/rules/` and `.claude/settings.local.json` were both untracked and unignored after an
    # attach, so every `git status` in the project listed the owner's personal rules, and a
    # `git add -A` committed them. They are machine-local by construction,
    # so `attach` hides them in `info/exclude`, which no clone shares, the ledger with them, and
    # writes nothing into `.gitignore`.
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    _committed(root)
    _attach_quietly(root, store, machine)
    for placed in _placed():
        # Non-vacuous: each one is really there, so `check-ignore` answers about a real path.
        assert (root / placed).is_file(), placed
        assert _check_ignore(root, placed), placed
    assert _status(root) == []
    body = extract(_exclude(root).read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    assert body is not None and SETTINGS in body


def test_a_checkout_that_already_hides_everything_is_not_touched(tmp_path: Path) -> None:
    # The legitimate user the exclude block must not disturb: someone who keeps the whole
    # footprint out of git through `info/exclude` already. `attach` asks git which of its paths
    # are ignored before it writes, so neither file changes and `git status` stays empty.
    #
    # Mutation: `mutations/`'s "attach treats an ignored path as not ignored".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    _committed(root)
    exclude = _exclude(root)
    exclude.parent.mkdir(exist_ok=True)
    held = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    lines = [f"/{placed}" for placed in _placed()] + [
        ".stayfixed/local/",
        ".stayfixed/assessment.json",
    ]
    exclude.write_text(held + "\n".join(lines) + "\n", encoding="utf-8")
    before = exclude.read_bytes()
    _attach_quietly(root, store, machine)
    # Non-vacuous: the attach did place its files, so there was something to hide.
    assert (root / SETTINGS).is_file()
    assert not (root / ".gitignore").exists()
    assert exclude.read_bytes() == before
    assert _status(root) == []


def test_a_checkout_whose_global_excludes_file_hides_everything_is_not_touched(
    tmp_path: Path,
) -> None:
    # The other owner-held source: a global excludes file (`core.excludesFile`) that already
    # hides the whole footprint. Its lines count as hidden, so neither ignore file changes.
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    _committed(root)
    owner = tmp_path / "owner-excludes"
    lines = [f"/{placed}" for placed in _placed()] + [
        ".stayfixed/local/",
        ".stayfixed/assessment.json",
    ]
    owner.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _git(root, "config", "core.excludesFile", str(owner))
    exclude = _exclude(root)
    before = exclude.read_bytes() if exclude.is_file() else None
    _attach_quietly(root, store, machine)
    # Non-vacuous: the attach did place its files, so there was something to hide.
    assert (root / SETTINGS).is_file()
    assert not (root / ".gitignore").exists()
    assert (exclude.read_bytes() if exclude.is_file() else None) == before
    assert _status(root) == []


def test_a_global_excludes_file_named_by_a_relative_path_still_stands_in_for_the_block(
    tmp_path: Path,
) -> None:
    # git opens a relative `core.excludesFile` from the top of the work tree. The question about
    # the owner's own excludes is asked over an empty work tree, where that path names no file,
    # so the owner's lines stood in for nothing and every path they hide got a line of its own.
    #
    # Mutation: `mutations/`'s "the owner's relative excludes file is read from the empty work
    # tree".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    _committed(root)
    owner = tmp_path / "owner-excludes"
    lines = [f"/{placed}" for placed in _placed()] + [
        ".stayfixed/local/",
        ".stayfixed/assessment.json",
    ]
    owner.write_text("\n".join(lines) + "\n", encoding="utf-8")
    relative = os.path.relpath(owner, root)
    _git(root, "config", "core.excludesFile", relative)
    # Non-vacuous: the path is relative, and git reads it from the checkout's top.
    assert not Path(relative).is_absolute()
    assert _check_ignore(root, SETTINGS)
    exclude = _exclude(root)
    before = exclude.read_bytes() if exclude.is_file() else None
    _attach_quietly(root, store, machine)
    assert (root / SETTINGS).is_file()
    assert (exclude.read_bytes() if exclude.is_file() else None) == before
    assert _status(root) == []


def test_a_committed_gitignore_does_not_stand_in_for_the_exclude_block(tmp_path: Path) -> None:
    # A committed `.gitignore` is the repository's, and a pull can take a line out of it. Counted
    # as hiding the owner's files, it left them out of the block, and an upstream commit that
    # dropped their lines from `.gitignore` showed the rule copy and the settings file in every
    # `git status` until the next attach. Only the owner's own excludes -- `info/exclude` and the
    # global excludes file -- stand in for the block.
    #
    # Mutation: `mutations/`'s "the owner's exclude question reads the checkout's .gitignore".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    (root / ".gitignore").write_text(".claude/\n.codex/\n", encoding="utf-8")
    _committed(root)
    _attach_quietly(root, store, machine)
    body = extract(_exclude(root).read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    assert body is not None
    for placed in _placed():
        assert f"/{placed}" in body.split("\n"), placed
    # Upstream drops the lines; the owner's files stay hidden.
    (root / ".gitignore").write_text("", encoding="utf-8")
    assert _status(root) == [" M .gitignore"]


def test_a_path_the_owners_global_excludes_hide_gets_no_line_whatever_the_gitignore_says(
    tmp_path: Path,
) -> None:
    # The common dotfiles layout: the owner's global excludes file (`~/.config/git/ignore`, read
    # with no `core.excludesFile` set) hides the settings file, and the repository's committed
    # `.gitignore` names it too. Asked which pattern decides, git names the `.gitignore`, which
    # outranks the owner's file, and that answer gave the settings file a redundant line of its
    # own: the owner's line keeps it hidden whatever a pull does to the `.gitignore`.
    #
    # Mutation: `mutations/`'s "the exclude block ignores what the owner's excludes hide".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    (root / ".gitignore").write_text(f"{SETTINGS}\n", encoding="utf-8")
    _committed(root)
    ignore = Path.home() / ".config" / "git" / "ignore"
    ignore.parent.mkdir(parents=True)
    ignore.write_text(f"{SETTINGS}\n", encoding="utf-8")
    _attach_quietly(root, store, machine)
    body = extract(_exclude(root).read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    # Non-vacuous: the run wrote the settings file, and a block for what nobody else hides.
    assert (root / SETTINGS).is_file()
    assert body is not None and "/.codex/rules/common.rules" in body.split("\n")
    assert f"/{SETTINGS}" not in body.split("\n")
    assert _status(root) == []


def test_a_gitignore_a_sparse_checkout_leaves_out_does_not_stand_in_for_the_block(
    tmp_path: Path,
) -> None:
    # A sparse checkout keeps a `.gitignore` it leaves out of the work tree in the index only,
    # marked skip-worktree, and git reads such a file from the index when it is not on disk. The
    # question about the owner's own excludes is asked against an empty work tree, where no
    # `.gitignore` is on disk: read with the index, it took the repository's line for the
    # owner's again and left the rule copy out of the block.
    #
    # Mutation: `mutations/`'s "the owner's exclude question reads the index".
    root, store, machine = _attachable(tmp_path, codex="# standing rule\n")
    (root / ".gitignore").write_text(".codex/\n", encoding="utf-8")
    _committed(root)
    _git(root, "update-index", "--skip-worktree", ".gitignore")
    (root / ".gitignore").unlink()
    # Non-vacuous: git still reads the left-out file, so the rule copy's directory is ignored.
    assert _check_ignore(root, ".codex/rules/common.rules")
    _attach_quietly(root, store, machine)
    body = extract(_exclude(root).read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    assert body is not None
    assert "/.codex/rules/common.rules" in body.split("\n")


def test_a_path_the_owners_excludes_re_include_is_still_hidden(tmp_path: Path) -> None:
    # `check-ignore -v` reports a path whose last matching pattern is a negation, and exits 0 for
    # it. Read as "hidden", a file the owner's excludes file re-includes got no line and showed
    # in `git status`. No mutation: the question is asked without `-v`, so git applies the
    # negation itself and no line of stayfixed's reads it; the test holds the behaviour.
    root, store, machine = _attachable(tmp_path)
    _committed(root)
    owner = tmp_path / "owner-excludes"
    owner.write_text(f".claude/*\n!{SETTINGS}\n", encoding="utf-8")
    _git(root, "config", "core.excludesFile", str(owner))
    _attach_quietly(root, store, machine)
    body = extract(_exclude(root).read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    assert body is not None and f"/{SETTINGS}" in body.split("\n")
    assert _status(root) == []


def test_the_block_keeps_what_an_earlier_attach_hid_when_the_grant_changes(
    tmp_path: Path,
) -> None:
    # A path an earlier block hides reads as ignored now. Rebuilt from one run's answer alone, the
    # block dropped it: attach with an overlay granting nothing, add a standing rule, attach
    # again, and the block held only the rule copy while `git status` listed the settings file.
    #
    # Mutation: `mutations/`'s "the exclude block forgets what an earlier attach hid".
    root, store, machine = _attachable(tmp_path)
    _committed(root)
    _attach_quietly(root, store, machine)
    first = extract(_exclude(root).read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    # Non-vacuous: the first block names the settings file and not the rule copy.
    assert first is not None and f"/{SETTINGS}" in first
    assert ".codex/rules/common.rules" not in first
    _overlay_grants(store, codex="# a standing rule\n")
    _attach_quietly(root, store, machine)
    second = extract(_exclude(root).read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    assert second is not None and "/.codex/rules/common.rules" in second.split("\n")
    assert _status(root) == []


def test_a_second_attach_leaves_the_exclude_file_as_the_first_wrote_it(tmp_path: Path) -> None:
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    _committed(root)
    _attach_quietly(root, store, machine)
    # Non-vacuous: the first attach did write the block, so "unchanged" is about a block and not
    # about a file that was never there.
    body = extract(_exclude(root).read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    assert body is not None and SETTINGS in body
    assert "/.codex/rules/common.rules" in body.split("\n")
    exclude = _exclude(root).read_bytes()
    _attach_quietly(root, store, machine)
    assert _exclude(root).read_bytes() == exclude


def test_a_symlinked_exclude_file_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    # `info/exclude` is resolved by git, and written by `attach` only after it refuses a
    # symlink there, as `setup --git-hooks` refuses a symlinked hook: a write through the link
    # would land wherever it points. Refused above the first write, like every other refusal.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    exclude = _exclude(root)
    elsewhere = tmp_path / "somebody-elses-file"
    elsewhere.write_text("# not the repository's\n", encoding="utf-8")
    if exclude.exists():
        exclude.unlink()
    exclude.parent.mkdir(exist_ok=True)
    exclude.symlink_to(elsewhere)
    before = snapshot(root)
    assert before
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    assert "symlink" in str(refused.value)
    assert_snapshot_unchanged(root, before)
    assert elsewhere.read_text(encoding="utf-8") == "# not the repository's\n"


def test_the_first_attach_leaves_an_index_behind_its_link(tmp_path: Path) -> None:
    # `attach` linked the store's `MEMORY.md` to the overlay's copy before any copy existed, so
    # every session saw a dangling link and `memory index --check` failed until someone ran
    # `memory index` by hand. The memory area's own renderer writes it in the same run.
    from stayfixed import binding
    from stayfixed.memory.api import composed_directory
    from tests.cli import cli

    root, store, machine = _attachable(tmp_path)
    _attach_quietly(root, store, machine)
    id = binding.read_id(root)
    assert id is not None
    index = composed_directory(id) / "MEMORY.md"
    assert index.is_symlink()
    assert index.is_file(), "the index link dangles"
    code, out, err = cli(root, tmp_path, "memory", "index", "--check", machine=machine)
    assert code == 0, out + err


def test_a_run_that_would_write_through_a_symlinked_claude_directory_still_refuses(
    tmp_path: Path,
) -> None:
    # Every run places the settings file, even one with no rule to merge: Claude Code writes the
    # plugin's `enabledPlugins` entry, which names the binding id, into it. So a `.claude` that is
    # a link is refused before anything is written, since what it holds would land where git
    # cannot be asked whether it is ignored.
    root, store, machine = _attachable(tmp_path)
    (tmp_path / "dotfiles-claude").mkdir()
    (root / ".claude").symlink_to(tmp_path / "dotfiles-claude", target_is_directory=True)
    before = snapshot(root)
    assert before
    with pytest.raises(Refusal) as refused:
        _attach_quietly(root, store, machine)
    # Refused for the reason it has: the containment asked of each placed path names the link.
    # Mutation: `mutations/`'s "the exclude block stops holding placed paths to the project".
    assert "symlink" in str(refused.value)
    assert_snapshot_unchanged(root, before)


# --- a name git would read as more than one exclude line -------------------------------------

# Every character `str.splitlines` breaks a line at besides `\n` and `\r`, and the NUL git's C
# reader stops a line at: git reads an exclude file by `\n` alone, so a name holding one of these
# is one line to git and several to anything that re-reads the block with `splitlines`.
_LINE_BREAKERS = ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\x00")


def _owner_hides_dotenv(root: Path, tmp_path: Path) -> None:
    """The owner's own excludes file hides `.env`; the project's `.env` and a file `b` sit
    untracked beside it, so `git status` shows `b` and never `.env`."""
    owner = tmp_path / "owner-excludes"
    owner.write_text(".env\n", encoding="utf-8")
    _git(root, "config", "core.excludesFile", str(owner))
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / "b").write_text("b\n", encoding="utf-8")


def test_an_earlier_blocks_line_is_kept_whole_whatever_it_holds(tmp_path: Path) -> None:
    # The union reads back the lines an earlier attach wrote. Read by `str.splitlines`, one line
    # holding U+2028 came back as three, and a `!.env` among them un-hid the owner's `.env`. git
    # ends a line at `\n` alone, so the block is read the same way.
    #
    # Mutation: `mutations/`'s "the exclude block is re-read at every line separator".
    root, store, machine = _attachable(tmp_path)
    _committed(root)
    _owner_hides_dotenv(root, tmp_path)
    exclude = _exclude(root)
    exclude.parent.mkdir(exist_ok=True)
    earlier = f"/{DEFAULT_MEMORY}/g\u2028!.env\u2028b"
    exclude.write_text(
        f"# stayfixed:attach:begin\n{earlier}\n# stayfixed:attach:end\n", encoding="utf-8"
    )
    _attach_quietly(root, store, machine)
    body = extract(exclude.read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH)
    # Non-vacuous: this attach did rewrite the block, adding the paths it placed.
    assert body is not None and f"/{SETTINGS}" in body
    assert earlier in body.split("\n")
    status = _status(root)
    assert "?? .env" not in status
    assert "?? b" in status


@pytest.mark.parametrize("breaker", _LINE_BREAKERS, ids=lambda c: f"U+{ord(c):04X}")
def test_a_name_git_would_read_differently_gets_no_exclude_line(breaker: str) -> None:
    # A name holding one of these is left visible, as a name holding a line break already was:
    # no exclude line spells it, and one that tried would be read back as other lines, or, for a
    # NUL, cut short by git into a pattern for a different path.
    from stayfixed.attach.exclude import pattern

    assert pattern(f"notes/z{breaker}*") is None


def test_a_group_with_a_space_or_a_non_ascii_name_is_still_hidden() -> None:
    # The legitimate user the rule above must not refuse: an ordinary name that happens to hold a
    # space or a letter outside ASCII still gets its one anchored, escaped line.
    from stayfixed.attach.exclude import pattern

    assert pattern("notes/my notes") == "/notes/my\\ notes"
    assert pattern("notes/заметки") == "/notes/заметки"


@pytest.mark.parametrize(
    ("name", "line"),
    [
        ("notes/a*b", "/notes/a\\*b"),
        ("notes/a?b", "/notes/a\\?b"),
        ("notes/a[b", "/notes/a\\[b"),
        ("notes/a\\b", "/notes/a\\\\b"),
    ],
    ids=["star", "question", "bracket", "backslash"],
)
def test_each_pattern_character_in_a_group_name_is_escaped(name: str, line: str) -> None:
    # A `memory.groups` entry is the repository's, and git reads `*`, `?`, `[` and `\` in an
    # exclude line as pattern syntax: a group named `*` unescaped would hide every untracked note
    # under `paths.memory`, and `\` would escape whatever follows it. Only the space escape was
    # asserted, so any one of these could leave `_SPECIAL` unnoticed.
    #
    # Mutations: `mutations/`'s "the exclude line leaves a star unescaped", "the exclude line
    # leaves a question mark unescaped", "the exclude line leaves a bracket unescaped" and "the
    # exclude line leaves a backslash unescaped".
    from stayfixed.attach.exclude import pattern

    assert pattern(name) == line


# --- every refusal is made before the first write ---------------------------------------------


def _everything(tmp_path: Path) -> dict[str, dict[str, bytes]]:
    """What an attach could write: the project, the overlay, the home and the machine's trust
    record beside the machine file."""
    trust = tmp_path / "trust.json"
    return {
        "project": snapshot(tmp_path / "project"),
        "overlay": snapshot(tmp_path / "overlay"),
        "home": snapshot(tmp_path / "home"),
        "trust": {"trust.json": trust.read_bytes()} if trust.is_file() else {},
    }


def _attach_it(root: Path, store: Path, machine: Path) -> Attached:
    return attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )


def test_an_overlay_rule_that_is_not_utf8_stops_attach_before_it_writes(tmp_path: Path) -> None:
    # The overlay's rule sources were read and decoded while they were copied, after `.gitignore`
    # and the exclude block were written and after the rules before the bad one were copied: a
    # rule file that was not UTF-8 exited 1 with `.codex/rules/common.rules` on disk, listed in
    # the exclude block so `git status` no longer showed it, and no ledger for `detach` to
    # remove it by. Every source is read while the run is planned now.
    #
    # Mutations: `mutations/`'s "attach copies past an overlay rule that is not UTF-8" -> the
    # refusal is dropped; and "attach reads the overlay's rule sources after its first write" ->
    # it is kept but moved below a write, so the snapshot is what reddens.
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    (store.parents[2] / COMMON_CODEX / "z.rules").write_bytes(b"\xff\xfe not text\n")
    before = _everything(tmp_path)
    assert before["project"] and before["overlay"]
    with pytest.raises(Failure, match="not UTF-8"):
        _attach_it(root, store, machine)
    assert _everything(tmp_path) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a directory it cannot write")
def test_an_exclude_file_that_cannot_be_written_is_refused_by_name_before_the_first_write(
    tmp_path: Path,
) -> None:
    # A `.git/info` attach could not write into ended as `internal error: PermissionError`, after
    # `.gitignore` had its region. The directory is asked whether it can be written while the run
    # is planned, and the refusal names the file.
    #
    # Mutation: `mutations/`'s "attach finds out the exclude file cannot be written by
    # writing it".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    info = root / ".git" / "info"
    info.mkdir(exist_ok=True)
    before = _everything(tmp_path)
    info.chmod(0o555)
    try:
        with pytest.raises(Refusal) as refused:
            _attach_it(root, store, machine)
    finally:
        info.chmod(0o755)
    assert "info/exclude" in str(refused.value)
    # Asked while planning, in its own words: the exclude block is the first write now, so a write
    # that failed would leave the tree as it was too, and only the sentence tells the two apart.
    assert "this user cannot write the directory that holds it" in str(refused.value)
    assert "internal error" not in str(refused.value)
    assert _everything(tmp_path) == before


def test_a_doubled_exclude_block_is_refused_naming_the_exclude_file(tmp_path: Path) -> None:
    # "region 'attach' is opened or closed twice" said which region and never which file, and the
    # file is not one a person opens often: `.git/info/exclude`.
    #
    # Mutation: `mutations/`'s "a doubled exclude block is refused without its file".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    begin = "# stayfixed:attach:begin\n"
    _exclude(root).parent.mkdir(exist_ok=True)
    _exclude(root).write_text(begin + begin + "# stayfixed:attach:end\n", encoding="utf-8")
    before = _everything(tmp_path)
    with pytest.raises(Refusal) as refused:
        _attach_it(root, store, machine)
    assert "info/exclude" in str(refused.value)
    assert _everything(tmp_path) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a directory it cannot write")
def test_an_exclude_file_whose_write_fails_is_a_refusal_naming_it(tmp_path: Path) -> None:
    # The check made while planning cannot rule out a write that fails anyway, and that write used
    # to end as `internal error: PermissionError`. It is a refusal naming the file.
    #
    # Mutation: `mutations/`'s "a failed exclude write is an internal error".
    from stayfixed.attach.exclude import ExcludeWrite, write

    shut = tmp_path / "info"
    shut.mkdir()
    shut.chmod(0o555)
    try:
        with pytest.raises(Refusal) as refused:
            write(ExcludeWrite(shut / "exclude", "/x\n"))
    finally:
        shut.chmod(0o755)
    assert "info/exclude" in str(refused.value)


def test_a_settings_file_an_earlier_attach_wrote_is_hidden_by_the_next_one(
    tmp_path: Path,
) -> None:
    # The upgrade path: a 0.1.x attach merged the overlay's rules into the settings file and
    # recorded them in its ledger, and kept no exclude block. The next attach, with nothing new
    # to merge, writes no settings, and still hides the file: every run places it, since Claude
    # Code writes the plugin's entry there; asked only of this run's writes, the file stayed in
    # `git status`.
    #
    # Mutation: `mutations/`'s "attach leaves the settings file out of what it places".
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _committed(root)
    _attach_quietly(root, store, machine)
    exclude = _exclude(root)
    exclude.write_text(
        drop(exclude.read_text(encoding="utf-8"), EXCLUDE_REGION, Style.HASH), encoding="utf-8"
    )
    assert not _check_ignore(root, SETTINGS)
    _attach_quietly(root, store, machine)
    assert _check_ignore(root, SETTINGS)


def _exclude_files() -> list[bytes | None]:
    """Every exclude file of up to two pattern lines, each ended by `\\n`, `\\r\\n`, a lone `\\r`
    or `\\r\\r\\n`, with the last one also left unended, plus an absent and an empty file."""
    endings = [b"\n", b"\r\n", b"\r", b"\r\r\n"]
    files: list[bytes | None] = [None, b""]
    for first in endings:
        files += [b"/a0" + first, b"/a0"]
        for second in endings:
            files += [b"/a0" + first + b"/a1" + second, b"/a0" + first + b"/a1"]
    return list(dict.fromkeys(files))


def test_the_exclude_block_hides_what_git_hid_and_gives_every_file_back(tmp_path: Path) -> None:
    # Checked against git itself, not against a model of it: for each exclude file, what git hides
    # with the block is what it hid without it plus the placed path, and taking the block out
    # gives the bytes back. git ends a line at `\n` and then drops one `\r` before it, so a file
    # holding `\r\n` whose last line ended `/a1\r` used to get `\r\n` appended, and git read
    # `/a1\r`, a pattern for another name.
    #
    # Mutations: `mutations/`'s "a hash region ends a line after a lone carriage return with
    # the file's own ending", "detach leaves the newline it added after a lone carriage return"
    # and "detach takes back half the CRLF attach added".
    from stayfixed.attach import exclude

    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name in ("a0", "a1", "linked"):
        (repo / name).write_text("x", encoding="utf-8")
    path = repo / ".git" / "info" / "exclude"

    def hidden() -> set[str]:
        return set(run_git(repo, "check-ignore", "--", "a0", "a1", "linked").stdout.split())

    wrong = []
    for held in _exclude_files():
        if held is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(held)
        before = hidden()
        planned = exclude.planned_block(repo, ["linked"])
        assert planned is not None
        exclude.write(planned)
        with_block = hidden()
        withdrawn = exclude.withdrawn_block(repo)
        assert withdrawn is not None
        exclude.write(withdrawn)
        after = path.read_bytes() if path.exists() else None
        if with_block != before | {"linked"} or after != held:
            wrong.append((held, sorted(before), sorted(with_block), after))
    assert wrong == []


# Names a clone can commit that no directory under the overlay's `projects/` can carry: one a file
# there already holds, and one longer than a file name may be on Linux and macOS alike.
UNSHARED = {"a-file-holds-it": "collides", "longer-than-a-file-name": "a" * 300}


@pytest.mark.parametrize("command", ["attach", "check"])
@pytest.mark.parametrize("case", sorted(UNSHARED))
def test_a_project_name_the_overlay_has_no_directory_for_is_refused_before_the_first_write(
    tmp_path: Path, case: str, command: str
) -> None:
    # `attach` records the binding and keeps the notes under `projects/<name>/`, so a name that
    # directory cannot exist for has nowhere to go. Reading the overlay's sources for such a name as
    # absent is what `doctor` needs; here it must not let the run reach its writes, which a record
    # it cannot place would stop half way through. `--check` refuses it too, as the run it
    # previews would. The name is never quoted back: it is the repository's.
    #
    # Mutations (oracle): `mutations/`'s "attach writes for a project name the overlay has no
    # directory for" -> the run's gate, which `--check` takes too, is dropped; "a name longer than
    # the filesystem allows is an overlay that cannot be asked", "a file where the project's
    # directory would be is an overlay that cannot be asked" and "a binding record the project's
    # name rules out cannot be read" -> the record such a name rules out reads as one that cannot
    # be read, which `attach` and `doctor` then report, rather than as no record.
    name = UNSHARED[case]
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    overlay = store.parents[2]
    (root / CONFIG_FILE).write_text(CONFIG.format(name=name), encoding="utf-8")
    if case == "a-file-holds-it":
        (overlay / "projects" / name).write_text("notes\n", encoding="utf-8")
    store = overlay / "projects" / name / "memory"
    before = _everything(tmp_path)
    with pytest.raises(Refusal) as refused:
        if command == "attach":
            _attach_it(root, store, machine)
        else:
            check(root, store=store, machine=machine)
    assert str(refused.value) == (
        f"{overlay}/projects/<this project's name> cannot be a directory on this machine -- a "
        f"file already holds that name, or the name is longer than the filesystem allows -- so "
        f"there is nowhere to record this binding or keep this project's notes; choose another "
        f"`name` under [project] in stayfixed.toml"
    )
    assert _everything(tmp_path) == before
    from stayfixed.attach.binding import binding_for

    assert binding_for(root, load(root, machine=machine), machine=machine).fault is None


@pytest.mark.parametrize("command", ["attach", "check"])
def test_a_claude_path_that_is_a_file_is_refused_before_the_first_write(
    tmp_path: Path, command: str
) -> None:
    # The other side of the overlay's leniency: a path the project's own `.claude` makes impossible
    # is not a settings file that is absent, because `attach` writes `.claude/settings.local.json`
    # and a run that read it as empty would refuse only at that write, after the ones before it.
    #
    # Mutation (oracle): `mutations/`'s "the project's own settings file is read as leniently as an
    # overlay source".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    (root / ".claude").write_text("not a directory\n", encoding="utf-8")
    before = _everything(tmp_path)
    with pytest.raises(Failure, match=r"settings\.local\.json cannot be read"):
        if command == "attach":
            _attach_it(root, store, machine)
        else:
            check(root, store=store, machine=machine)
    assert _everything(tmp_path) == before


@pytest.mark.parametrize("command", ["attach", "check"])
def test_an_overlay_whose_common_claude_is_a_file_stops_attach_before_it_writes(
    tmp_path: Path, command: str
) -> None:
    # The overlay's leniency is for the path a repository's `project.name` spells, and
    # `common/claude/` is spelled by the overlay alone: a file there is the overlay failing to
    # answer, and `attach` stops before it writes, as it does for a source it cannot read. Read
    # as absent, it attached with nothing `common/` grants and said nothing. Mutation (oracle):
    # `mutations/`'s "a common source the overlay cannot hold reads as no source".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# a standing rule\n")
    common = store.parents[2] / COMMON_CLAUDE
    shutil.rmtree(common)
    common.write_text("not a directory\n", encoding="utf-8")
    before = _everything(tmp_path)
    with pytest.raises(Failure, match=r"common/claude/permissions\.json cannot be read"):
        if command == "attach":
            _attach_it(root, store, machine)
        else:
            check(root, store=store, machine=machine)
    assert _everything(tmp_path) == before


@pytest.mark.parametrize("command", ["attach", "check"])
def test_an_overlay_whose_own_project_claude_is_a_file_stops_attach_before_it_writes(
    tmp_path: Path, command: str
) -> None:
    # The leniency a `project.name` earns is for a name no directory under `projects/` can carry.
    # Here the name picks out the owner's own directory and a file sits below it, where `claude/`
    # goes: `project.name` holds no `/`, so that is the overlay's state, and `attach` stops before
    # it writes as it does for a source it cannot read. Read as absent, the second attach found
    # nothing to grant and stripped the owner's entry from their delivery. Mutation (oracle):
    # `mutations/`'s "a fault below the project's own directory reads as no source".
    root, store, machine = _attachable(tmp_path)
    own = store.parent / "claude"
    own.mkdir()
    (own / "hooks.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [ENTRY]}]}}),
        encoding="utf-8",
    )
    _attach_it(root, store, machine)
    delivered = _delivered_hooks(root).read_bytes()
    # Non-vacuous: the owner's entry, out of the project's own hook file, is in their delivery.
    assert json.loads(delivered)["hooks"]["PreToolUse"] == [{"matcher": "Bash", "hooks": [ENTRY]}]
    shutil.rmtree(own)
    own.write_text("not a directory\n", encoding="utf-8")
    before = _everything(tmp_path)
    with pytest.raises(Failure, match=r"/claude/permissions\.json cannot be read"):
        if command == "attach":
            _attach_it(root, store, machine)
        else:
            check(root, store=store, machine=machine)
    assert _delivered_hooks(root).read_bytes() == delivered
    assert _everything(tmp_path) == before


def test_a_project_the_overlay_has_no_directory_for_yet_is_attached_and_given_one(
    tmp_path: Path,
) -> None:
    # The other side of the refusal above: a name the overlay has no directory for *yet* is the
    # ordinary first attach of a new project, and `attach` creates the directory. Mutation
    # (oracle): `mutations/`'s "attach refuses a project the overlay has no directory for yet".
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    shutil.rmtree(store.parent)
    assert check(root, store=store, machine=machine).exit_code == 0
    _attach_it(root, store, machine)
    assert (store.parent / PROJECT_RECORD).is_file()
    assert store.is_dir()


@pytest.mark.parametrize("projects", ["projects-kept", "projects-absent"])
def test_a_source_past_the_longest_path_under_a_project_with_no_directory_is_no_source(
    tmp_path: Path, projects: str
) -> None:
    # A name whose directory, binding record and every path `attach` links inside it fit under
    # the longest path while a source under it does not, in an overlay that has no directory for
    # it yet -- under a `projects/` it keeps, or with no `projects/` at all. Nothing is below a
    # directory that is not there, so `--check` reads each source there as the absent file it is
    # and previews what `common/` grants. Read as a fault of the overlay's, it failed: "cannot be
    # read: File name too long". A record or a linked path past the longest path is refused before
    # any source is read, which is `tests/attach/test_commands.py`'s
    # `test_a_name_whose_record_fits_while_a_path_attach_links_does_not_is_refused_by_check_too`,
    # so those fit here and the permissions file is the source past them. Mutations (oracle):
    # `mutations/`'s "a source the project's name rules out is an overlay that cannot be asked"
    # and "a source past the longest path under a project the overlay has no directory for cannot
    # be asked" -> both cases fail.
    longest = os.pathconf(tmp_path, "PC_PATH_MAX")
    deep = tmp_path
    # Room under the longest path for the fixture's own files, overlay and checkout alike.
    while len(str(deep)) < longest - 250:
        deep = deep / ("d" * min(200, longest - 250 - len(str(deep))))
    hooks = {"PreToolUse": [{"matcher": "Bash", "hooks": [ENTRY]}]}
    root, store, machine = _attachable(deep, allow=(RULE,), hooks=hooks)
    projects_dir = store.parents[1]
    # How far past the project's directory the longest path `attach` links there reaches, off the
    # paths the link tree is built from for the fixture's own name.
    share = store.parent
    linked = link_sources(store.parents[2], load(root, machine=machine))
    reach = max(len(str(path)) for path in linked if share in path.parents) - len(str(share))
    # The project's directory one character shorter than that path needs, its name a file name
    # that may be, its binding record and every linked path under the longest path and its
    # permissions file past it.
    name = "n" * (longest - reach - 1 - len(str(projects_dir)) - 1)
    assert len(name) < 255
    assert len(str(projects_dir / name)) + reach == longest - 1
    assert len(str(projects_dir / name / PROJECT_RECORD)) < longest
    assert len(str(projects_dir / name / "claude" / "permissions.json")) > longest
    (root / CONFIG_FILE).write_text(CONFIG.format(name=name), encoding="utf-8")
    if projects == "projects-absent":
        shutil.rmtree(projects_dir)
    result = check(root, store=projects_dir / name / "memory", machine=machine)
    assert result.exit_code == 0, result.summary
    assert result.data["added_allow"] == [RULE]


# The two shapes of an overlay that is damaged rather than one a project's name rules out: its
# `projects/` a file, and the overlay root itself a file. Each is the owner's own state, and no
# `project.name` could be chosen that a directory would exist for.
DAMAGED = {
    "projects-is-a-file": ("projects", "file"),
    "overlay-root-is-a-file": ("", "file"),
    # A link that names nothing, at `projects/` or the root: `stat` answers it as "no such file",
    # which read as an overlay with no `projects/` yet, so `--check` passed and `attach` blamed a
    # `memory.groups` entry.
    "projects-is-a-dangling-link": ("projects", "dangling"),
    "overlay-root-is-a-dangling-link": ("", "dangling"),
}


def _damage(overlay: Path, shape: str) -> Path:
    """Break `overlay` the way `DAMAGED[shape]` says, and answer the path that broke."""
    where, how = DAMAGED[shape]
    broken = overlay / where if where else overlay
    shutil.rmtree(broken)
    if how == "file":
        broken.write_text("not a directory\n", encoding="utf-8")
    else:
        broken.symlink_to(broken.parent / "nowhere")
    return broken


@pytest.mark.parametrize("command", ["attach", "check"])
@pytest.mark.parametrize("shape", sorted(DAMAGED))
def test_an_overlay_that_is_not_a_directory_where_projects_go_is_refused_as_damaged(
    tmp_path: Path, shape: str, command: str
) -> None:
    # `share.stat()` raised `NotADirectoryError` for both shapes, which `cannot_exist` reads as a
    # name no directory can carry: the refusal blamed the project's name and told the owner to
    # choose another, for a bound project whose overlay is what broke. It names the path that is
    # not a directory, says the overlay is damaged, and never asks for another name; and it is
    # still made before the first write. The name is the repository's and is never printed.
    # Mutations (declared): the damaged-overlay check skipped -> the name is blamed again;
    # `mutations/`'s "the damaged-overlay probe follows a link that names nothing" -> the dangling
    # cases pass `--check`.
    name = "a-distinctive-project-name"
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    overlay = store.parents[2]
    (root / CONFIG_FILE).write_text(CONFIG.format(name=name), encoding="utf-8")
    store = overlay / "projects" / name / "memory"
    store.mkdir(parents=True)
    _attach_it(root, store, machine)
    broken = _damage(overlay, shape)
    before = _everything(tmp_path)
    with pytest.raises(Refusal) as refused:
        if command == "attach":
            _attach_it(root, store, machine)
        else:
            check(root, store=store, machine=machine)
    said = str(refused.value)
    assert said == OVERLAY_DAMAGED.format(path=broken)
    assert "choose another" not in said
    assert name not in said
    assert _everything(tmp_path) == before


def test_a_settings_merge_the_encoder_cannot_write_back_is_refused_before_the_first_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python 3.12's indenting encoder stops near 994 levels, under what its parser reads, so a
    # deep `settings.local.json` was read and then ended `attach` in `RecursionError` while the
    # merge was encoded. Forced here on every interpreter: the merge refuses as the reader refuses
    # a document nested too deep, before anything is written. The overflow is forced only for the
    # merged document, the one holding the overlay's rule, so the earlier write-back probe of the
    # file as it stands encodes it and the merge's own encode is the one met. Mutation (oracle):
    # `mutations/`'s "attach encodes the settings merge with a bare json.dumps" -> `RecursionError`.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    (root / SETTINGS).parent.mkdir(exist_ok=True)
    (root / SETTINGS).write_text('{"theme": "dark"}', encoding="utf-8")
    before = _everything(tmp_path)
    real = json.dumps

    def overflowing_merge(value: object, *args: Any, indent: int | None = None, **kw: Any) -> str:
        if indent is not None and RULE in real(value):
            raise RecursionError
        return real(value, *args, indent=indent, **kw)

    monkeypatch.setattr(jsonobject, "_encode", overflowing_merge)
    monkeypatch.setattr(json, "dumps", overflowing_merge)
    with pytest.raises(Refusal, match="nested deeper than this reader follows"):
        _attach_it(root, store, machine)
    assert _everything(tmp_path) == before


@pytest.mark.parametrize("command", ["attach", "check"])
def test_a_local_settings_file_linked_to_a_device_is_refused_and_never_read(
    tmp_path: Path, command: str
) -> None:
    # `attach` and `--check` read `.claude/settings.local.json` with `read_text`, which follows a
    # link: a committed link to `/dev/zero` read until memory ran out, and one to a FIFO waited for
    # a writer. It is read only when it is a regular file, and anything else is a settings file
    # that cannot be read, before the first write. `/dev/null` tells the guard apart without
    # hanging: read, it is an empty settings file. Mutation (declared): `mutations/`'s "the settings
    # reader reads a file through any link".
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    settings = root / SETTINGS
    settings.parent.mkdir(exist_ok=True)
    if settings.exists():
        settings.unlink()
    settings.symlink_to("/dev/null")
    before = _everything(tmp_path)
    with pytest.raises(Failure) as refused:
        if command == "attach":
            _attach_it(root, store, machine)
        else:
            check(root, store=store, machine=machine)
    # Named as the project names it, never by the machine's absolute path, as the `.gitignore`
    # refusal is. Mutation (oracle): `mutations/`'s "the settings refusal prints the path it
    # opened" -> the message carries the temporary directory.
    assert str(refused.value) == f"{SETTINGS} cannot be read (not a regular file)"
    assert _everything(tmp_path) == before


@pytest.mark.parametrize("command", ["attach", "check"])
def test_a_local_settings_file_that_is_not_utf8_is_named_as_the_project_names_it(
    tmp_path: Path, command: str
) -> None:
    # The refusal's other arm, held to the same rule. Mutation (oracle): `mutations/`'s "the
    # settings refusal of a file that is not UTF-8 prints the path it opened".
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    settings = root / SETTINGS
    settings.parent.mkdir(exist_ok=True)
    settings.write_bytes(b'{"hooks": {}, "x": "\xff"}')
    before = _everything(tmp_path)
    with pytest.raises(Failure) as refused:
        if command == "attach":
            _attach_it(root, store, machine)
        else:
            check(root, store=store, machine=machine)
    assert str(refused.value) == f"{SETTINGS} is not UTF-8 text"
    assert _everything(tmp_path) == before


def test_a_local_settings_file_that_is_a_fifo_is_refused_without_waiting(tmp_path: Path) -> None:
    # A FIFO left where the settings file goes: the read refuses it, never waits. In a child under
    # a timeout, so a regression fails this case rather than hanging.
    root = tmp_path / "project"
    (root / ".claude").mkdir(parents=True)
    os.mkfifo(root / SETTINGS)
    probe = (
        "import sys\n"
        "from pathlib import Path\n"
        "from stayfixed.attach.permissions import local_document\n"
        "from stayfixed.errors import Failure\n"
        "try:\n"
        "    local_document(Path(sys.argv[1]))\n"
        "except Failure:\n"
        "    print('refused')\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, str(root)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the settings read waited on a FIFO")
    assert done.stdout == "refused\n", done.stderr


def _wide(siblings: int) -> str:
    """A settings document ten lists deep holding `siblings` empty lists: about 3 bytes each as
    written, and about 26 once written back indented, which is the growth the cap is about."""
    return '{"a": ' + "[" * 10 + ",".join(["[]"] * siblings) + "]" * 10 + "}"


@pytest.mark.parametrize("command", ["attach", "check"])
def test_a_settings_file_whose_write_back_the_next_read_refuses_is_refused_before_any_write(
    tmp_path: Path, command: str
) -> None:
    # 12 KB, 6,000 lists deep: written back indented it is 72 MB, past the regular-file reader's
    # cap, so `attach` wrote it, the ignore files, the ledger and `MEMORY.md`, then refused its own
    # read of the file, and every `detach` after refused the same way. It is refused while nothing
    # is written, and `--check` refuses it too. On an interpreter whose indenting encoder stops
    # short of that depth the refusal is the one for nesting; elsewhere the one for length.
    # `attach` and `--check` are each refused by two layers, the diff's and the merge's own
    # write-back through `jsonobject.json_text`, so no single mutation reddens either case; the
    # second layer is proven by `mutations/`'s "the JSON writer writes back a text past the read
    # cap", in `tests/attach/test_detach.py`.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    settings = root / SETTINGS
    settings.parent.mkdir(exist_ok=True)
    settings.write_text('{"deep": ' + "[" * 6_000 + "]" * 6_000 + "}", encoding="utf-8")
    before = _everything(tmp_path)
    with pytest.raises(EntriesError) as refused:
        if command == "attach":
            _attach_it(root, store, machine)
        else:
            check(root, store=store, machine=machine)
    assert str(refused.value) in (
        f"{SETTINGS} {jsonobject.WRITTEN_PAST}",
        f"{SETTINGS} {jsonobject.NESTED}",
    )
    assert _everything(tmp_path) == before


@pytest.mark.parametrize("command", ["attach", "check"])
@pytest.mark.parametrize("siblings", [1_000, 100])
def test_a_settings_write_back_past_the_cap_is_refused_and_one_inside_it_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, siblings: int
) -> None:
    # The same rule on every interpreter, with the cap lowered so the document is small: a
    # document whose write-back, with room for the one key the settings fallback adds, would pass
    # the cap is refused before anything is written, by `attach` and `--check` alike, and one
    # inside it is merged as before. Both commands' two layers are the case above's.
    monkeypatch.setattr(fsops, "REGULAR_READ_LIMIT", 16 * 1024)
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    settings = root / SETTINGS
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(_wide(siblings), encoding="utf-8")
    before = _everything(tmp_path)

    def run() -> object:
        if command == "attach":
            return _attach_it(root, store, machine)
        return check(root, store=store, machine=machine)

    if siblings == 100:
        run()
        if command == "attach":
            assert RULE in settings.read_text(encoding="utf-8")
        return
    with pytest.raises(EntriesError) as refused:
        run()
    assert str(refused.value) == f"{SETTINGS} {jsonobject.WRITTEN_PAST}"
    assert _everything(tmp_path) == before


# --- one place per repository: the main checkout -------------------------------------------


def test_attach_places_no_link_tree_and_writes_nothing_under_the_home(tmp_path: Path) -> None:
    # The harness reads the composed store through `autoMemoryDirectory` in the main checkout's
    # settings file, from every worktree, so `attach` places no link under `paths.memory` in any
    # checkout and writes nothing under the home's `.claude/`. Run with a linked worktree
    # standing, since that is where the worktree's own tree went.
    root, store, machine = _attachable(tmp_path)
    _committed(root)
    side = tmp_path / "side"
    _git(root, "worktree", "add", "-q", str(side), "-b", "side")
    attach(root, store=store, machine=machine, runner=Recorder())
    assert json.loads((root / SETTINGS).read_text(encoding="utf-8"))[POINTER]
    assert not (root / DEFAULT_MEMORY).exists()
    assert not (side / DEFAULT_MEMORY).exists()
    assert not (Path(os.environ["HOME"]) / ".claude").exists()


def test_attach_from_a_linked_worktree_writes_the_main_checkout_only(tmp_path: Path) -> None:
    # Claude Code reads the main checkout's `settings.local.json` from every worktree and writes a
    # worktree's own answers there, so `attach` run from a linked worktree writes that file and its
    # ledger in the main checkout and nothing in the worktree: one place per repository.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _committed(root)
    side = tmp_path / "side"
    _git(root, "worktree", "add", "-q", str(side), "-b", "side")
    attach(side, store=store, machine=machine, runner=Recorder())
    assert ledger_file(root).is_file()
    assert RULE in json.loads((root / SETTINGS).read_text(encoding="utf-8"))["permissions"]["allow"]
    assert not (side / SETTINGS).exists()
    assert _status(side) == []


def _tagged(store: Path, *tags: str) -> Path:
    """The overlay of `_attachable`, its project listing `tags`, each with a `groups/<tag>/`
    directory; the overlay's root."""
    return with_tags(store.parents[2], store.parent.name, list(tags), "claude", "codex")


def _tag_grants(overlay: Path, tag: str, *allow: str) -> None:
    (overlay / "groups" / tag / "claude" / "permissions.json").write_text(
        json.dumps({"permissions": {"allow": list(allow)}}), encoding="utf-8"
    )


def test_a_tag_codex_rule_is_placed_and_a_later_plate_wins_its_name(tmp_path: Path) -> None:
    root, store, machine = _attachable(tmp_path, codex="# common\n")
    overlay = _tagged(store, "a", "b")
    (store.parent / "codex").mkdir()
    (store.parent / "codex" / "project.rules").write_text("# project\n", encoding="utf-8")
    for tag in ("a", "b"):
        (overlay / "groups" / tag / "codex" / "common.rules").write_text(
            f"# from {tag}\n", encoding="utf-8"
        )
        (overlay / "groups" / tag / "codex" / f"{tag}.rules").write_text(
            "# tag\n", encoding="utf-8"
        )
    attached = attach(root, store=store, machine=machine, runner=Recorder())
    rules = root / ".codex" / "rules"
    assert (rules / "common.rules").read_text(encoding="utf-8") == "# from b\n"
    assert {path.name for path in rules.iterdir()} == {
        "common.rules",
        "project.rules",
        "a.rules",
        "b.rules",
    }
    assert set(attached.rules_written) == {f".codex/rules/{name}" for name in os.listdir(rules)}


def test_a_tag_allow_rule_is_added(tmp_path: Path) -> None:
    from stayfixed.attach.binding import read_binding
    from stayfixed.attach.permissions import diff_permissions

    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _tag_grants(_tagged(store, "a"), "a", "Bash(x)")
    diff = diff_permissions(root, read_binding(root, store=store, machine=machine))
    assert diff.added_allow == (RULE, "Bash(x)")


def test_an_unreadable_tag_file_stops_attach_with_nothing_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads every file")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    hooks = _tagged(store, "a") / "groups" / "a" / "claude" / "hooks.json"
    hooks.write_text("{}", encoding="utf-8")
    hooks.chmod(0o000)
    flags = ("--store", str(store))
    before = snapshot(root)
    try:
        attached = cli(root, tmp_path, "attach", *flags, machine=machine)
    finally:
        hooks.chmod(0o644)
    assert attached[0] == 1
    assert_snapshot_unchanged(root, before)
    # No render was made either: the delivery directory is as it was, which is to say absent.
    assert not (Path(os.environ["HOME"]) / ".local" / "share" / "stayfixed" / "delivery").exists()


def _untag(store: Path) -> None:
    """The project's record listing no tag any more; the `groups/` directories stay."""
    (store.parent / PROJECT_RECORD).write_text("tags = []\n", encoding="utf-8")


def _allowed(root: Path) -> list[str]:
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    return list(document.get("permissions", {}).get("allow", []))


def test_untagging_takes_back_the_tags_allow_rule(tmp_path: Path) -> None:
    # The ledger recorded `Bash(x)` as attach's own; with the tag gone the overlay no longer grants
    # it, and left in the settings file it would stay until `detach`. Mutation (oracle):
    # `mutations/`'s "re-attach keeps an allow rule the overlay no longer grants".
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _tag_grants(_tagged(store, "a"), "a", "Bash(x)")
    attach(root, store=store, machine=machine, runner=Recorder())
    assert _allowed(root) == [RULE, "Bash(x)"]
    _untag(store)
    attach(root, store=store, machine=machine, runner=Recorder())
    assert _allowed(root) == [RULE]
    assert ledger(root).allow == (RULE,)


def test_a_hand_added_rule_the_ledger_does_not_name_stays(tmp_path: Path) -> None:
    # The ledger is the only witness of which rules are attach's: a rule the owner typed, which the
    # ledger does not name, is theirs.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _tag_grants(_tagged(store, "a"), "a", "Bash(x)")
    attach(root, store=store, machine=machine, runner=Recorder())
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    document["permissions"]["allow"].append("Bash(mine)")
    (root / SETTINGS).write_text(json.dumps(document), encoding="utf-8")
    _untag(store)
    attach(root, store=store, machine=machine, runner=Recorder())
    assert _allowed(root) == [RULE, "Bash(mine)"]
    assert "Bash(mine)" not in ledger(root).allow


def test_a_recorded_rule_removed_by_hand_is_not_an_error(tmp_path: Path) -> None:
    # An owner who deleted a rule from the settings file and then untagged: nothing to take.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _tag_grants(_tagged(store, "a"), "a", "Bash(x)")
    attach(root, store=store, machine=machine, runner=Recorder())
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    document["permissions"]["allow"].remove("Bash(x)")
    (root / SETTINGS).write_text(json.dumps(document), encoding="utf-8")
    by_hand = (root / SETTINGS).read_bytes()
    _untag(store)
    attach(root, store=store, machine=machine, runner=Recorder())
    assert (root / SETTINGS).read_bytes() == by_hand
    # The overlay grants it no longer, so the ledger forgets it with the file already without it;
    # typed back by the owner, it is theirs and a later attach leaves it.
    assert ledger(root).allow == (RULE,)
    document["permissions"]["allow"].append("Bash(x)")
    (root / SETTINGS).write_text(json.dumps(document), encoding="utf-8")
    attach(root, store=store, machine=machine, runner=Recorder())
    assert _allowed(root) == [RULE, "Bash(x)"]


def test_an_unreadable_project_record_stops_attach_with_nothing_written(tmp_path: Path) -> None:
    # A record that cannot be read is no list of tags, and a run that took it so would withdraw the
    # tags' allow rules, notes and render: it refuses, naming the file, before the first write.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _tag_grants(_tagged(store, "a"), "a", "Bash(x)")
    attach(root, store=store, machine=machine, runner=Recorder())
    (store.parent / PROJECT_RECORD).write_text('tags = ["a"\n', encoding="utf-8")
    data = Path(os.environ["HOME"]) / ".local" / "share" / "stayfixed"
    before = (snapshot(root), snapshot(data))
    for run in (
        lambda: attach(root, store=store, machine=machine, runner=Recorder()),
        lambda: check(root, store=store, machine=machine),
    ):
        with pytest.raises(Refusal) as refusal:
            run()
        assert quoted(str(store.parent / PROJECT_RECORD)) in str(refusal.value)
    assert (snapshot(root), snapshot(data)) == before
    assert "Bash(x)" in _allowed(root)


def test_a_tag_entry_that_is_not_a_string_is_a_note_and_attach_goes_on(tmp_path: Path) -> None:
    # `tags = ["a", 1]` keeps `a`: the entry is skipped like an ungrammatical name, and the run has
    # no unreadable record to refuse on.
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _tag_grants(_tagged(store, "a"), "a", "Bash(x)")
    (store.parent / PROJECT_RECORD).write_text('tags = ["a", 1]\n', encoding="utf-8")
    attach(root, store=store, machine=machine, runner=Recorder())
    assert _allowed(root) == [RULE, "Bash(x)"]


def test_a_re_attach_leaves_a_codex_rule_copy_the_overlay_dropped_and_names_it(
    tmp_path: Path,
) -> None:
    # The team commits `.codex/rules/common.rules` after `attach` placed it, then the overlay drops
    # the rule: the next routine `attach` must not delete a file the checkout tracks. It leaves
    # every copy standing, keeps it in the ledger for `detach`, and names it.
    # Mutation: `mutations/`'s "re-attach removes a Codex copy the overlay dropped".
    root, store, machine = _attachable(tmp_path, allow=(RULE,), codex="# standing rule\n")
    _committed(root)
    attach(root, store=store, machine=machine, runner=Recorder())
    copy = ".codex/rules/common.rules"
    _git(root, "add", "-f", copy)
    _git(root, "commit", "-qm", "the team keeps the rule")
    (store.parents[2] / COMMON_CODEX / "common.rules").unlink()
    again = attach(root, store=store, machine=machine, runner=Recorder())
    assert (root / copy).is_file() and _status(root) == []
    assert again.rules_left == (copy,)
    assert ledger(root).rules == (copy,)


def test_check_counts_the_rules_it_would_take_back(tmp_path: Path) -> None:
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    _tag_grants(_tagged(store, "a"), "a", "Bash(x)", "Bash(y)")
    attach(root, store=store, machine=machine, runner=Recorder())
    before = (root / SETTINGS).read_bytes()
    assert "taken back" not in check(root, store=store, machine=machine).summary
    _untag(store)
    summary = check(root, store=store, machine=machine).summary
    assert "2 allow rule(s) would be taken back" in summary
    # A preview writes nothing.
    assert (root / SETTINGS).read_bytes() == before
