"""`stayfixed detach` removes exactly what `attach` added, and nothing else.

The ledger is the authority on what was ours. Guessing it back from the content of a settings
file is the heuristic the ledger exists to replace, and a detach built on a guess removes a rule
the owner wrote by hand — which is worse than removing none.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from stayfixed import fsops, jsonobject
from stayfixed.attach.write import Attached, Detached, attach, detach
from stayfixed.config.layout import ATTACH_LEDGER as LEDGER
from stayfixed.errors import Failure, Refusal
from stayfixed.printed import quoted
from stayfixed.project.init import init
from stayfixed.project.uninstall import uninstall
from stayfixed.scaffold import MANIFEST_PATH
from stayfixed.scaffold.regions import Style, extract
from tests.attach.test_binding import CONFIG, _machine
from tests.attach.test_write import SETTINGS
from tests.gitfixture import git
from tests.parserlimits import LONG_NUMBER, NESTED, PAST_ENCODING, overflowing_indent
from tests.runners import Recorder, claude_code, git_that_cannot_run
from tests.snapshot import (
    assert_snapshot_changed,
    assert_snapshot_unchanged,
    snapshot,
    tree_entries,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

RULE = "Bash(uv run pytest:*)"
ENTRY = {"type": "command", "command": "echo hello"}


def _grant(overlay: Path, *, allow: tuple[str, ...] = (), hooks: bool = False) -> None:
    claude = overlay / "common" / "claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "permissions.json").write_text(
        json.dumps({"permissions": {"allow": list(allow), "deny": []}}), encoding="utf-8"
    )
    (claude / "hooks.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [ENTRY]}]} if hooks else {}}),
        encoding="utf-8",
    )
    (overlay / "common" / "codex").mkdir(parents=True, exist_ok=True)
    (overlay / "common" / "codex" / "common.rules").write_text("# rule\n", encoding="utf-8")


def _bound(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A committed repository in overlay mode, and the overlay that already records it."""
    root = tmp_path / "project"
    root.mkdir(parents=True)
    overlay = tmp_path / "overlay"
    (overlay / "common" / "memory").mkdir(parents=True)
    (overlay / "common" / "memory" / "shared.md").write_text("x", encoding="utf-8")
    own = overlay / "projects" / "p" / "memory"
    own.mkdir(parents=True)
    (own.parent / "project.toml").write_text(
        'remote = "git@example.com:o/p.git"\n', encoding="utf-8"
    )
    (overlay / "common" / "claude").mkdir(parents=True)
    (overlay / "common" / "codex").mkdir(parents=True)
    (root / "stayfixed.toml").write_text(CONFIG.format(name="p"), encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", "git@example.com:o/p.git")
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "init")
    return root, own, _machine(tmp_path, overlay=overlay)


def _attach(root: Path, store: Path, machine: Path) -> Attached:
    return attach(root, store=store, machine=machine, runner=Recorder())


def _detach(root: Path, runner: Recorder | None = None) -> Detached:
    return detach(root, runner=runner or Recorder())


def test_detach_removes_exactly_what_attach_added(tmp_path: Path) -> None:
    # The round trip is the assertion: snapshot every file under the root, attach with
    # `confirmed=True`, detach, and compare against the snapshot. A detach that removes a rule
    # the owner wrote by hand is worse than one that removes none.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    before = snapshot(root)
    _attach(root, store, machine)
    assert_snapshot_changed(root, before)
    _detach(root)
    assert_snapshot_unchanged(root, before)


def _render_of(root: Path) -> tuple[str, Path]:
    """The binding id of `root`'s repository and the render directory it names."""
    from stayfixed import binding
    from stayfixed.binding import delivery_directory

    id = binding.read_id(root)
    assert id is not None
    return id, delivery_directory(id)


def _installed(root: Path, store: Path, machine: Path) -> None:
    """An attach whose two `claude plugin` calls wrote what Claude Code writes into the main
    checkout's settings file: the `enabledPlugins` and `extraKnownMarketplaces` entries that name
    the binding id."""
    from stayfixed.attach.write import attach

    runner = Recorder(on_call=claude_code(root))
    attach(root, store=store, machine=machine, runner=runner)


def test_detach_withdraws_the_rendered_plugin_and_keeps_the_binding(tmp_path: Path) -> None:
    # The plugin runs from its render directory in place, so the directory goes and Claude Code is
    # told to forget the plugin and its marketplace, each once, from the main checkout whose
    # settings file holds the plugin's entries. The id, this machine's record of it and the
    # overlay's record stay: a later attach binds the same checkout again.
    from stayfixed import binding

    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _installed(root, store, machine)
    id, delivery = _render_of(root)
    assert (delivery / ".claude-plugin" / "marketplace.json").is_file()
    record = store.parent / "project.toml"
    kept = record.read_bytes()
    runner = Recorder(on_call=claude_code(root))
    _detach(root, runner)
    assert not delivery.exists()
    assert list(zip(runner.calls, runner.cwds, strict=True)) == [
        (
            [
                "claude",
                "plugin",
                "uninstall",
                f"overlay-{id}@stayfixed-delivery-{id}",
                "--scope",
                "local",
            ],
            root.resolve(),
        ),
        (["claude", "plugin", "marketplace", "remove", f"stayfixed-delivery-{id}"], root.resolve()),
    ]
    assert not (root / SETTINGS).exists()
    assert binding.read_id(root) == id
    found = binding.bound_project(root)
    assert found is not None and found.project == "p"
    assert record.read_bytes() == kept


def test_detach_with_the_render_directory_gone_still_asks_claude_code_to_forget_the_plugin(
    tmp_path: Path,
) -> None:
    # Each call is decided by what the main checkout's settings file names, never by the render
    # directory, which a data-directory cleanup can take away: a detach that skipped the calls for
    # want of it withdrew the exclude block and left `enabledPlugins` naming the whole id in a file
    # `git status` then offered for commit.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _installed(root, store, machine)
    _, delivery = _render_of(root)
    shutil.rmtree(delivery)
    runner = Recorder(on_call=claude_code(root))
    _detach(root, runner)
    assert [argv[2] for argv in runner.calls] == ["uninstall", "marketplace"]
    assert not (root / SETTINGS).exists() and not _exclude_block(root)
    assert git(root, "status", "--porcelain", "-uall").strip() == ""


def test_a_round_trip_through_claude_codes_calls_leaves_the_checkout_as_it_was(
    tmp_path: Path,
) -> None:
    # Claude Code's two calls leave `enabledPlugins` and `extraKnownMarketplaces` behind, emptied,
    # in the settings file `attach` made. Kept, that file was the one trace `git status` showed
    # once the exclude block went, in a checkout no global exclude hides it in. Mutation (oracle):
    # `mutations/`'s "detach keeps the settings file Claude Code's calls emptied".
    root, store, machine = _bound(tmp_path)
    before = snapshot(root)
    _installed(root, store, machine)
    assert_snapshot_changed(root, before)
    _detach(root, Recorder(on_call=claude_code(root)))
    assert_snapshot_unchanged(root, before)
    assert git(root, "status", "--porcelain", "-uall").strip() == ""


def test_a_settings_file_holding_anything_besides_the_emptied_maps_stays(tmp_path: Path) -> None:
    # A key of the owner's own, written beside the plugin's entries while attached, keeps the
    # file: only what Claude Code's calls leave goes. Mutation (oracle): `mutations/`'s "detach
    # removes a settings file whatever it holds".
    root, store, machine = _bound(tmp_path)
    _installed(root, store, machine)
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    document["model"] = "opus"
    (root / SETTINGS).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    _detach(root, Recorder(on_call=claude_code(root)))
    kept = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert kept == {"enabledPlugins": {}, "extraKnownMarketplaces": {}, "model": "opus"}


def test_a_ledger_naming_another_directory_deletes_nothing_outside_the_delivery_directory(
    tmp_path: Path,
) -> None:
    # The render directory is derived from the id, never read from the ledger, which a clone can
    # commit: a ledger whose `store` and `render` name a directory elsewhere leaves it standing.
    # Mutation: `mutations/`'s "detach deletes the directory the ledger names".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _attach(root, store, machine)
    _, delivery = _render_of(root)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "keep.txt").write_text("mine\n", encoding="utf-8")
    raw = json.loads((root / LEDGER).read_text(encoding="utf-8"))
    raw["store"] = str(outside)
    raw["render"] = {"digest": "0" * 64, "parts": ["keep.txt"]}
    (root / LEDGER).write_text(json.dumps(raw), encoding="utf-8")
    _detach(root)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "mine\n"
    assert not delivery.exists()


def _exclude_block(root: Path) -> bool:
    """Whether the repository's exclude file still holds `attach`'s block."""
    exclude = root / ".git" / "info" / "exclude"
    return exclude.is_file() and "# stayfixed:attach:begin" in exclude.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("ignoring", "left", "again"),
    [
        pytest.param(
            ("marketplace remove",), ["extraKnownMarketplaces"], ["marketplace"], id="remove"
        ),
        pytest.param(
            ("uninstall", "marketplace remove"),
            ["enabledPlugins", "extraKnownMarketplaces"],
            ["uninstall", "marketplace"],
            id="both",
        ),
    ],
)
def test_a_settings_file_still_naming_the_plugin_keeps_the_delivery_hidden_and_detach_runs_again(
    tmp_path: Path, ignoring: tuple[str, ...], left: list[str], again: list[str]
) -> None:
    # The plugin's entries in `settings.local.json` name the whole binding id, and only Claude Code
    # takes them out. So while the file still names the id once the calls ran, whatever they
    # exited with, everything that keeps the file hidden or lets `detach` run again stays: the
    # exclude block, the ledger and the render. The failure names the entry left by its key and
    # never the id. A second detach makes only the call the file still asks for.
    # Mutation: `mutations/`'s "detach goes past a settings file that still names the plugin".
    from stayfixed.attach.write import STILL_NAMED

    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _installed(root, store, machine)
    id, delivery = _render_of(root)
    assert _exclude_block(root)
    with pytest.raises(Failure) as failed:
        _detach(root, Recorder(on_call=claude_code(root, ignoring=ignoring)))
    assert str(failed.value) == STILL_NAMED.format(keys=", ".join(f"`{key}`" for key in left))
    assert id not in str(failed.value)
    assert _exclude_block(root) and (root / LEDGER).is_file() and delivery.is_dir()
    second = Recorder(on_call=claude_code(root))
    _detach(root, second)
    assert [argv[2] for argv in second.calls] == again
    assert not _exclude_block(root) and not (root / LEDGER).exists() and not delivery.exists()


def test_a_detach_that_cannot_read_the_id_keeps_a_settings_file_naming_a_delivery_hidden(
    tmp_path: Path,
) -> None:
    # With the id file gone, `detach` cannot name the plugin, and the settings file still names the
    # old id under both keys: withdrawn, the block left that file for `git add -A` to commit. Any
    # `stayfixed-delivery-` name there keeps the block, the ledger and the render, and fails.
    # Mutation: `mutations/`'s "detach asks the settings file about this binding id's delivery
    # alone".
    from stayfixed.attach.write import STILL_NAMED

    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _installed(root, store, machine)
    _, delivery = _render_of(root)
    (root / ".git" / "stayfixed" / "binding").unlink()
    runner = Recorder(on_call=claude_code(root))
    with pytest.raises(Failure) as failed:
        _detach(root, runner)
    assert str(failed.value) == STILL_NAMED.format(
        keys="`enabledPlugins`, `extraKnownMarketplaces`"
    )
    assert runner.calls == []
    assert _exclude_block(root) and (root / LEDGER).is_file() and delivery.is_dir()


def test_detach_after_an_attach_whose_marketplace_add_failed_runs_no_call_and_finishes(
    tmp_path: Path,
) -> None:
    # A `claude` that is not on `PATH` failed the first call, so Claude Code wrote nothing and the
    # attach exited 1. The settings file names no plugin, so `detach` asks Claude Code to forget
    # nothing and withdraws: it used to run `marketplace remove` regardless, fail on it, and promise
    # that running it again would finish, which it never did.
    from stayfixed.attach.write import attach
    from stayfixed.runner import Completed

    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    absent = Recorder(answers={"claude": Completed(127, "", "")})
    with pytest.raises(Failure):
        attach(root, store=store, machine=machine, runner=absent)
    _, delivery = _render_of(root)
    runner = Recorder(answers={"claude": Completed(127, "", "")})
    _detach(root, runner)
    assert runner.calls == []
    assert not _exclude_block(root) and not (root / LEDGER).exists() and not delivery.exists()


def test_detach_in_a_bare_repositorys_worktree_withdraws_this_checkouts_own_parts(
    tmp_path: Path,
) -> None:
    # git names no main checkout in a bare repository, so `attach` refuses there and installed
    # nothing; a ledger an earlier release wrote in such a worktree is withdrawn rather than refused
    # in attach's words, which left the checkout neither detachable nor uninstallable.
    from tests.attach.test_write import _attachable, _committed

    root, store, _ = _attachable(tmp_path, allow=(RULE,))
    _committed(root)
    bare = tmp_path / "bare.git"
    git(tmp_path, "clone", "-q", "--bare", str(root), str(bare))
    side = tmp_path / "side"
    git(bare, "worktree", "add", "-q", str(side), "main")
    (side / ".stayfixed" / "local").mkdir(parents=True)
    ledgered = {"format": 1, "store": str(store), "allow": [RULE], "entries": {}, "rules": []}
    ledgered |= {"settings_keys": [], "directories": [".stayfixed/local", ".stayfixed"]}
    (side / LEDGER).write_text(json.dumps(ledgered), encoding="utf-8")
    (side / ".claude").mkdir()
    (side / SETTINGS).write_text(json.dumps({"permissions": {"allow": [RULE]}}), encoding="utf-8")
    runner = Recorder()
    removed = _detach(side, runner)
    assert removed.allow_removed == (RULE,)
    assert runner.calls == [] and not (side / LEDGER).exists() and not (side / SETTINGS).exists()


def test_detach_keeps_the_allow_rule_claude_code_added_to_a_rewritten_settings_file(
    tmp_path: Path,
) -> None:
    # Claude Code rewrites `settings.local.json` whole, its keys in another order, and adds the
    # allow rule a "don't ask again" answer grants. `detach` takes out the rule its ledger names
    # and leaves Claude Code's.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _attach(root, store, machine)
    rewritten = {
        "enabledPlugins": {"superpowers@claude-plugins-official": True},
        "permissions": {"allow": ["Bash(git tag *)", RULE]},
    }
    (root / SETTINGS).write_text(json.dumps(rewritten, indent=4), encoding="utf-8")
    removed = _detach(root)
    assert removed.allow_removed == (RULE,)
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert document["permissions"]["allow"] == ["Bash(git tag *)"]


def test_uninstall_after_a_real_detach_takes_the_footprint_back(tmp_path: Path) -> None:
    # The lifecycle's "uninstalled after a detach": what a detach leaves behind decides whether
    # `stayfixed uninstall` reads the repository as attached, and so whether it detaches again
    # before it takes the scaffold back. An `init`
    # footprint, a real attach that merged a rule and a hook entry, a detach, and the tree is the
    # one `init` left; `uninstall` then runs and takes the footprint back, and a second one finds
    # nothing to take. Mutation: `mutations/`'s "detach leaves its ledger behind".
    root, store, machine = _bound(tmp_path)
    init(root, machine=machine, yes=True, dry_run=False)
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "footprint")
    initialised = snapshot(root)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _attach(root, store, machine)
    assert_snapshot_changed(root, initialised)
    _detach(root)
    assert_snapshot_unchanged(root, initialised)
    uninstall(root, machine=machine, dry_run=False, force=(), runner=Recorder())
    assert not (root / MANIFEST_PATH).exists() and not (root / LEDGER).exists()
    with pytest.raises(Refusal):
        uninstall(root, machine=machine, dry_run=False, force=(), runner=Recorder())


def test_detach_leaves_a_rule_the_ledger_does_not_claim(tmp_path: Path) -> None:
    # Write an allow rule into settings.local.json by hand before attaching, attach, detach,
    # and assert that rule survives. The ledger is the authority on what was ours; content
    # heuristics are exactly what it exists to replace.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    (root / ".claude").mkdir(exist_ok=True)
    (root / SETTINGS).write_text(
        json.dumps({"permissions": {"allow": ["Bash(rm:*)"]}}), encoding="utf-8"
    )
    _attach(root, store, machine)
    _detach(root)
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert document["permissions"]["allow"] == ["Bash(rm:*)"]


def test_detach_leaves_a_hook_entry_that_was_never_marked(tmp_path: Path) -> None:
    # The same rule for the other half of the file. `scaffold.apply_entries` splits a group
    # rather than replacing it, so a developer's own entry beside stayfixed's survives — and
    # this is the command whose mistake would delete it.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], hooks=True)
    (root / ".claude").mkdir(exist_ok=True)
    (root / SETTINGS).write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": "mine.sh"}]}]}}),
        encoding="utf-8",
    )
    _attach(root, store, machine)
    _detach(root)
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    commands = [e["command"] for g in document["hooks"]["SessionStart"] for e in g["hooks"]]
    assert commands == ["mine.sh"]


def test_detach_without_a_ledger_says_so_and_changes_nothing(tmp_path: Path) -> None:
    # A repository attached by an older version, or by hand. Guessing which rules were ours
    # from their content is the heuristic this ledger exists to avoid, so the answer is a
    # `Failure` naming the missing ledger, not a best effort.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _attach(root, store, machine)
    (root / LEDGER).unlink()
    before = snapshot(root)
    # As in `test_a_mismatched_remote_refuses_and_writes_nothing`: `snapshot` is a walk and an
    # empty one satisfies the comparison below on its own.
    assert before
    with pytest.raises(Failure) as failed:
        _detach(root)
    assert LEDGER in str(failed.value)
    assert_snapshot_unchanged(root, before)


@pytest.mark.parametrize("run_in", ["main", "worktree"])
def test_a_second_detach_exits_one_and_writes_nothing(tmp_path: Path, run_in: str) -> None:
    # Run twice: the first takes the main checkout's ledger, whichever checkout it ran in, so the
    # second has nothing to reverse and fails (exit 1) naming the missing ledger, with every
    # checkout exactly as the first left it.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    side = tmp_path / "side"
    git(root, "worktree", "add", "-q", str(side), "-b", "side")
    _attach(root, store, machine)
    target = root if run_in == "main" else side
    _detach(target)
    before = tree_entries(root, side)
    assert str(root / "stayfixed.toml") in before
    with pytest.raises(Failure) as failed:
        _detach(target)
    assert LEDGER in str(failed.value)
    assert tree_entries(root, side) == before


def test_detach_withdraws_the_memory_pointer_and_the_composed_store(tmp_path: Path) -> None:
    # The key names a directory derived from the id; both go, the overlay the links point into
    # stays, and a settings file that held nothing else goes with them.
    from stayfixed import binding
    from stayfixed.attach.write import attach
    from stayfixed.memory.store import composed_directory as store_directory

    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    attach(root, store=store, machine=machine, runner=Recorder())
    id = binding.read_id(root)
    assert id is not None
    composed = store_directory(id)
    assert (root / SETTINGS).is_file()
    assert "autoMemoryDirectory" in json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert composed.is_dir()
    _detach(root)
    assert not (root / SETTINGS).exists()
    assert not composed.exists()
    assert (store.parents[2] / "common" / "memory").is_dir()


def test_detach_from_a_worktree_takes_the_pointer_out_of_the_main_checkouts_file(
    tmp_path: Path,
) -> None:
    # `attach` writes the pointer and its ledger into the main checkout from any worktree, since
    # Claude Code reads that settings file from every one: a detach from the worktree takes the key
    # out of the main checkout's file and leaves the rest of that file as it was.
    from stayfixed.attach.write import attach

    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    side = tmp_path / "side"
    git(root, "worktree", "add", "-q", str(side), "-b", "side")
    (root / ".claude").mkdir()
    (root / SETTINGS).write_text('{"theme": "dark"}\n', encoding="utf-8")
    attach(side, store=store, machine=machine, runner=Recorder())
    assert "autoMemoryDirectory" in json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    _detach(side)
    assert json.loads((root / SETTINGS).read_text(encoding="utf-8")) == {"theme": "dark"}


def test_detach_leaves_the_binding_record_in_place(tmp_path: Path) -> None:
    # `projects/<name>/project.toml` is a record of the owner's consent, not a piece of local
    # state. Re-attaching later must not re-ask for it, and a detach that deleted it would
    # turn every re-attach into a first attach.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    _detach(root)
    assert (store.parent / "project.toml").is_file()
    assert (store.parents[2] / "common" / "memory" / "shared.md").is_file()


def test_detach_removes_a_rule_file_the_overlay_has_since_deleted(tmp_path: Path) -> None:
    # `attach` stays idempotent and reversible by `detach`, and the ledger is the only record
    # of what was placed. A rule file deleted from the overlay between two attaches is not
    # written by the second one and so drops out of a ledger built from that run alone — while
    # the copy the first attach made is still in `.codex/rules/`, where Codex reads it as a
    # standing instruction. Without the union, `detach` leaves it there for good.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    landed = root / ".codex" / "rules" / "common.rules"
    assert landed.is_file()
    (store.parents[2] / "common" / "codex" / "common.rules").unlink()
    _attach(root, store, machine)
    assert landed.is_file(), "the copy the first attach made is still here"
    _detach(root)
    assert not landed.exists()


def _rewrite_ledger(root: Path, **fields: object) -> None:
    """The ledger a clone committed: `attach`'s own, with fields replaced.

    Built from a real one rather than by hand so that the case differs from a working detach in
    exactly the field under test. `.gitignore` does not untrack a file a clone committed, which
    is what makes this a state a fresh checkout can be in rather than a contrivance.
    """
    document = json.loads((root / LEDGER).read_text(encoding="utf-8"))
    document.update(fields)
    (root / LEDGER).write_text(json.dumps(document), encoding="utf-8")


def test_a_ledger_naming_a_file_attach_could_not_have_written_removes_nothing(
    tmp_path: Path,
) -> None:
    # The ledger is a record, not an authority. `fsops.remove_within` contains the removal to
    # the root — and `.github/workflows/`, `.pre-commit-config.yaml` and every source file are
    # inside it, so containment is not the guard that matters. The guard is that `attach` only
    # ever writes `.codex/rules/<file>`, so anything else in `rules` is a repository asking for
    # a deletion no attach could have earned.
    #
    # Mutation: `mutations/`'s "detach deletes whatever file the ledger names" — make
    # `_rule_is_writable` answer True unconditionally and the workflow file goes.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    workflow = root / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("on: push\n", encoding="utf-8")
    _rewrite_ledger(root, rules=[".github/workflows/ci.yml", ".codex/rules/common.rules"])
    before = snapshot(root)
    # `snapshot` is a walk, and an empty one satisfies the comparison below on its own.
    assert before
    with pytest.raises(Refusal):
        _detach(root)
    assert_snapshot_unchanged(root, before)
    assert workflow.is_file()


def test_a_ledger_nested_past_the_parsers_reach_removes_nothing(tmp_path: Path) -> None:
    # A committed ledger nested deeper than `json.loads` follows ended `detach` in an internal
    # error. It is a ledger that cannot be read, so the run fails before it withdraws anything.
    # Mutation (oracle): `mutations/`'s "the JSON object reader lets a document nested past the
    # parser raise" -> `RecursionError`.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    (root / LEDGER).write_text('{"entries": ' + NESTED + "}", encoding="utf-8")
    before = snapshot(root)
    assert before
    with pytest.raises(Failure, match="nested deeper"):
        _detach(root)
    assert_snapshot_unchanged(root, before)


def test_a_ledger_holding_a_number_past_the_parsers_reach_removes_nothing(tmp_path: Path) -> None:
    # A committed ledger holding an integer literal longer than the interpreter converts ended
    # `detach` in an internal error, `ValueError`. It is a ledger that cannot be read, so the run
    # fails before it withdraws anything. Mutation (oracle): `mutations/`'s "the JSON object
    # reader lets a number past the parser's reach raise" -> `ValueError`.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    (root / LEDGER).write_text('{"entries": {"x": ' + LONG_NUMBER + "}}", encoding="utf-8")
    before = snapshot(root)
    assert before
    with pytest.raises(Failure, match="number longer"):
        _detach(root)
    assert_snapshot_unchanged(root, before)


@pytest.mark.parametrize("bound", ["real-depth", "cap-forced"])
def test_a_local_settings_file_past_the_encoder_is_refused_and_removes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str
) -> None:
    # On Python 3.14 the parser follows about 57,800 levels and `json.dumps` overflows near
    # 50,000, so a `settings.local.json` nested between the two parsed and then ended `detach` in
    # `internal error: RecursionError … while encoding a JSON object`, where 3.11 to 3.13 refuse
    # it as nested deeper than the reader follows. The reader now bounds the depth it follows, so
    # every interpreter refuses it in those words. `real-depth` is that file, and exercises the
    # bound only where the parser reaches it (3.14); `cap-forced` lowers the bound so the same
    # refusal is reached on every interpreter. Mutation (declared): the depth bound never refuses
    # -> `cap-forced` detaches.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    if bound == "cap-forced":
        monkeypatch.setattr(jsonobject, "DEPTH_CAP", 4)
        deep = "[" * 5 + "]" * 5
    else:
        deep = PAST_ENCODING
    (root / SETTINGS).parent.mkdir(exist_ok=True)
    (root / SETTINGS).write_text('{"x": ' + deep + "}", encoding="utf-8")
    before = snapshot(root)
    assert before
    with pytest.raises((Failure, Refusal), match="nested deeper than this reader follows"):
        _detach(root)
    assert_snapshot_unchanged(root, before)


def test_a_ledger_claiming_the_permissions_key_never_drops_the_owners_deny_rules(
    tmp_path: Path,
) -> None:
    # The measured widening, and the reason this refusal is not a nicety. `_withdraw_settings`
    # assigns `raw["permissions"] = permissions` and *then* pops every string in
    # `settings_keys`, so a committed `settings_keys = ["permissions"]` took the owner's whole
    # permissions block out — deny rules included. A repository cannot be allowed to remove a
    # deny rule by committing a JSON file, whatever it calls that file.
    #
    # Mutation: the same entry as above, on the `settings_keys` half — let `_checked` accept a
    # key other than `autoMemoryDirectory` and the deny rule below is gone.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    (root / ".claude").mkdir(exist_ok=True)
    (root / SETTINGS).write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(curl:*)"]}}),
        encoding="utf-8",
    )
    _rewrite_ledger(root, settings_keys=["permissions"])
    with pytest.raises(Refusal):
        _detach(root)
    document = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert document["permissions"]["deny"] == ["Bash(curl:*)"]
    assert document["permissions"]["allow"] == ["Bash(ls:*)"]


def test_the_two_values_attach_really_writes_are_still_acted_on(tmp_path: Path) -> None:
    # The vacuity guard for both refusals above: a validator that refused everything would pass
    # them and break the command. A ledger holding exactly what `attach` wrote — one
    # `.codex/rules/` file and the one pointer key — detaches, and both are withdrawn.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    from stayfixed.attach.api import ledger as read_ledger

    recorded = read_ledger(root)
    assert recorded.rules == (".codex/rules/common.rules",)
    assert recorded.settings_keys == ("autoMemoryDirectory",)
    _detach(root)
    assert not (root / ".codex" / "rules" / "common.rules").exists()
    assert not (root / SETTINGS).exists()


def test_a_git_that_cannot_run_is_answered_before_anything_is_withdrawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `detach` cannot refuse the way `attach` does once it has started: by then the settings and
    # the rule files are gone, and refusing strands a half-detached repository. It is not licence
    # to *discover* a precondition late: a `git` that cannot run is a fact about the machine, true
    # before the run began, and the main checkout is asked of it before the first withdrawal.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _attach(root, store, machine)
    before = snapshot(root)
    # `snapshot` is a walk, and an empty one satisfies the comparison below on its own.
    assert before
    git_that_cannot_run(monkeypatch)
    with pytest.raises(Failure):
        _detach(root)
    assert_snapshot_unchanged(root, before)


def test_the_git_failure_is_reached_on_a_run_that_would_have_withdrawn(tmp_path: Path) -> None:
    # The vacuity guard for the snapshot above: a refusal that withdraws nothing proves nothing
    # if the run had nothing to withdraw. The identical fixture, with a `git` that works,
    # withdraws every artifact the case above has to leave standing.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _attach(root, store, machine)
    before = snapshot(root)
    assert before
    removed = _detach(root)
    after = snapshot(root)
    gone = set(before) - set(after)
    assert {SETTINGS, ".codex/rules/common.rules", LEDGER} <= gone
    assert removed.allow_removed == (RULE,)


# --- the directories, which the file snapshot could not see -----------------------------------


def _directories(root: Path) -> set[str]:
    """Every directory under the root but `.git`, as `snapshot` would if it saw directories."""
    found: set[str] = set()
    for path in root.rglob("*"):
        if path.is_dir() and not path.is_symlink() and ".git" not in path.relative_to(root).parts:
            found.add(str(path.relative_to(root)))
    return found


def test_detach_removes_the_directories_the_attach_created(tmp_path: Path) -> None:
    # `docs/cli.md` promised "an attach and a detach leave the tree byte-for-byte as it was" and
    # it was false for directories: `.stayfixed/local/`, `.stayfixed/`, `.codex/rules/` and
    # `.codex/` survived every round trip. `snapshot` filters on `is_file()`, so the round-trip
    # test above passed while four directories accumulated.
    #
    # The set is asserted by value and not by `not any(...)`: a `_withdraw_directories` that
    # removed only the leaves, or only `.stayfixed/`, satisfies "something was removed" and
    # leaves the tree changed. `.claude/` is on the list too — the overlay here grants a rule,
    # so the attach creates it.
    #
    # Mutation: `mutations/`'s "detach leaves behind the directories the attach created".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    before = _directories(root)
    _attach(root, store, machine)
    # The walk the comparison below rests on, asserted non-empty before it is trusted: an
    # `rglob` that finds nothing would satisfy every equality in this case on its own.
    assert _directories(root) > before
    removed = _detach(root)
    assert set(removed.directories_removed) == {
        ".stayfixed/local",
        ".stayfixed",
        ".codex/rules",
        ".codex",
        ".claude",
    }
    assert _directories(root) == before


def _detach_after_attach(root: Path, store: Path, machine: Path) -> Detached:
    _attach(root, store, machine)
    return _detach(root)


def test_detach_keeps_a_directory_that_still_holds_something(tmp_path: Path) -> None:
    # The floor under the ledger: the removal is `rmdir`, so a directory holding anything the
    # attach did not put there survives — and its parent survives with it, because a parent that
    # still holds a child is not empty either. A `shutil.rmtree` here would delete the owner's
    # own `.codex/rules/` file on a detach that promised to remove only what it added.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _attach(root, store, machine)
    mine = root / ".codex" / "rules" / "zz-my-own.md"
    mine.write_text("# mine\n", encoding="utf-8")
    removed = _detach(root)
    assert mine.is_file(), "a detach deleted a rule file the owner wrote by hand"
    assert ".codex/rules" not in removed.directories_removed
    assert ".codex" not in removed.directories_removed
    # And the ones that had nothing of the owner's in them still went.
    assert ".stayfixed" in removed.directories_removed


def test_detach_leaves_a_directory_that_was_there_before_the_attach(tmp_path: Path) -> None:
    # The other half, and the one the ledger answers rather than `rmdir`: an **empty** `.codex/`
    # the owner made themselves is indistinguishable from one this attach created, once the run
    # is over. `_absent_directories` is asked above the first write, so it is not on the ledger
    # and `detach` does not touch it — a detach must not remove a directory it did not create.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    (root / ".codex").mkdir()
    removed = _detach_after_attach(root, store, machine)
    assert (root / ".codex").is_dir(), "a detach removed a directory that predated the attach"
    assert ".codex" not in removed.directories_removed
    # `.codex/rules/` inside it was this attach's, and still goes.
    assert ".codex/rules" in removed.directories_removed
    assert not (root / ".codex" / "rules").exists()


def test_a_ledger_naming_a_directory_no_attach_creates_is_refused(tmp_path: Path) -> None:
    # `.stayfixed/local/attach.json` is a path a clone can commit, and `directories` drives
    # `rmdir`. It is held to the same closed list `rules` and `settings_keys` are held to, so a
    # ledger naming `src` is refused with nothing removed rather than obeyed — even though
    # `rmdir` would have spared a non-empty `src/` anyway. A partial defence reported as a
    # success is the shape this refusal exists to avoid.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _attach(root, store, machine)
    recorded = json.loads((root / LEDGER).read_text(encoding="utf-8"))
    recorded["directories"] = ["src"]
    (root / LEDGER).write_text(json.dumps(recorded), encoding="utf-8")
    (root / "src").mkdir()
    before = snapshot(root)
    assert before
    with pytest.raises(Refusal):
        _detach(root)
    assert (root / "src").is_dir()
    assert_snapshot_unchanged(root, before)


def test_detach_takes_back_the_exclude_block_and_the_empty_directories(tmp_path: Path) -> None:
    # Each is a thing `attach` made that a detach left behind: the block in `info/exclude` and the
    # directories it had to create. Each is a name the run computes, and each goes only when
    # nothing else is in it.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    before = _directories(root)
    _attach(root, store, machine)
    exclude = root / ".git" / "info" / "exclude"
    # Non-vacuous: the block exists before the detach.
    assert extract(exclude.read_text(encoding="utf-8"), "attach", Style.HASH) is not None
    _detach(root)
    assert extract(exclude.read_text(encoding="utf-8"), "attach", Style.HASH) is None
    assert _directories(root) == before


def test_the_memory_pointer_is_hidden_too(tmp_path: Path) -> None:
    # The pointer is written into the settings file every run places and hides in its one block
    # above the first write, since Claude Code writes the plugin's entry there too.
    from stayfixed.attach.write import attach
    from tests.attach.test_write import _check_ignore

    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    attach(root, store=store, machine=machine, runner=Recorder())
    # Non-vacuous: the pointer is all this overlay gives the file, so the file is this run's.
    assert "autoMemoryDirectory" in (root / SETTINGS).read_text(encoding="utf-8")
    assert _check_ignore(root, SETTINGS)
    # The block hides it, and `attach` wrote nothing into the fixture's tracked `.gitignore`.
    status = git(root, "status", "--porcelain", "--untracked-files=all")
    assert SETTINGS not in status


# --- the exclude block is shared by every checkout, and is taken back exactly ----------------


def _exclude_file(root: Path) -> Path:
    return root / ".git" / "info" / "exclude"


def test_an_exclude_file_attach_created_is_removed_by_detach(tmp_path: Path) -> None:
    # A repository whose `info/exclude` does not exist (`git init` with no templates) got one
    # from `attach`, and `detach` left it behind empty, against "a file left holding nothing is
    # removed rather than left empty".
    #
    # Mutation: `mutations/`'s "detach leaves the exclude file attach created".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _exclude_file(root).unlink(missing_ok=True)
    _attach(root, store, machine)
    # Non-vacuous: the attach did create the file for its block.
    assert extract(_exclude_file(root).read_text(encoding="utf-8"), "attach", Style.HASH)
    _detach(root)
    assert not _exclude_file(root).exists()


def test_an_exclude_file_that_was_there_and_empty_stays_there_and_empty(tmp_path: Path) -> None:
    # The other half: an empty file the owner had is the owner's, and survives the round trip.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _exclude_file(root).write_bytes(b"")
    _attach(root, store, machine)
    assert extract(_exclude_file(root).read_text(encoding="utf-8"), "attach", Style.HASH)
    _detach(root)
    assert _exclude_file(root).read_bytes() == b""


@pytest.mark.parametrize("ending", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_an_exclude_file_with_no_final_line_ending_comes_back_without_one(
    tmp_path: Path, ending: str
) -> None:
    # The block starts on a line of its own, so `attach` ends the owner's last line first, and
    # `detach` left that line ending behind. The block records that it added one, and `detach`
    # takes it back when nothing follows the block.
    #
    # Mutation: `mutations/`'s "detach keeps the line ending attach added".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    held = f"# the owner's{ending}/owner-only".encode()
    _exclude_file(root).write_bytes(held)
    _attach(root, store, machine)
    # Non-vacuous: the attach wrote its block after a line it had to end.
    assert (
        _exclude_file(root)
        .read_bytes()
        .startswith(f"# the owner's{ending}/owner-only{ending}".encode())
    )
    # A second attach that rewrites the block carries the record along.
    _grant(store.parents[2], allow=(RULE, "Bash(ls:*)"))
    _attach(root, store, machine)
    _detach(root)
    assert _exclude_file(root).read_bytes() == held


def test_a_line_the_owner_added_after_the_block_keeps_its_line_ending(tmp_path: Path) -> None:
    # The line ending `attach` added sits before the block; with the owner's own line after it,
    # taking it back would join two lines, so it stays.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    _exclude_file(root).write_bytes(b"/owner-only")
    _attach(root, store, machine)
    with _exclude_file(root).open("a", encoding="utf-8") as stream:
        stream.write("/added-later\n")
    _detach(root)
    assert _exclude_file(root).read_bytes() == b"/owner-only\n/added-later\n"


def test_an_exclude_file_that_is_not_utf8_neither_blocks_attach_nor_detach(
    tmp_path: Path,
) -> None:
    # The exclude file is the owner's, and git reads it as bytes. Read as UTF-8 text, a byte
    # outside it -- a comment in Latin-1, say -- refused `attach` and `detach` both. Its bytes are
    # kept exactly, in the attach and in the round trip.
    #
    # Mutation: `mutations/`'s "the exclude file is read as UTF-8 text".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    held = "# propriété de l'équipe\n/owner-only\n".encode("latin-1")
    _exclude_file(root).write_bytes(held)
    _attach(root, store, machine)
    written = _exclude_file(root).read_bytes()
    assert written.startswith(held)
    assert b"# stayfixed:attach:begin" in written
    _detach(root)
    assert _exclude_file(root).read_bytes() == held


def test_the_exclude_file_refusals_print_the_path_through_the_quoting_rule(
    tmp_path: Path,
) -> None:
    # The checkout's directory name usually comes from the clone URL, so the exclude file's path
    # is printed through `printed.quoted`, which escapes a line break or an escape sequence in
    # it, as the store's refusals already print theirs.
    #
    # Mutation: `mutations/`'s "the exclude file's symlink refusal prints its path raw".
    from stayfixed.attach.exclude import planned_block

    root = tmp_path / "clone\n::error::x"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    exclude = _exclude_file(root)
    exclude.unlink(missing_ok=True)
    exclude.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(Refusal) as refused:
        planned_block(root, ["placed"])
    assert "symlink" in str(refused.value)
    assert "\n" not in str(refused.value)


# --- every refusal is made before the first withdrawal ----------------------------------------


def _withdrawable(tmp_path: Path) -> Path:
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,), hooks=True)
    _attach(root, store, machine)
    assert (root / SETTINGS).is_file()
    return root


def test_a_codex_directory_linked_in_after_attach_refuses_before_anything_is_withdrawn(
    tmp_path: Path,
) -> None:
    # A `.codex` that became a symlink after the attach was found by the removal of the first rule
    # copy, after `.claude/settings.local.json` was withdrawn: `internal error: UnsafePath`, with
    # the settings gone, the links and the ledger in place, and every later run failing at the
    # same line. Each recorded rule copy is held to the project while the run is planned now.
    #
    # Mutation: `mutations/`'s "detach finds a linked .codex by removing through it".
    root = _withdrawable(tmp_path)
    elsewhere = tmp_path / "codex-elsewhere"
    shutil.move(root / ".codex", elsewhere)
    (root / ".codex").symlink_to(elsewhere)
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _detach(root)
    assert ".codex" in str(refused.value)
    assert_snapshot_unchanged(root, before)


def test_a_doubled_exclude_block_refuses_detach_naming_the_exclude_file(tmp_path: Path) -> None:
    # The same refusal `attach` makes, and the same missing file name.
    #
    # Mutation: `mutations/`'s "a doubled exclude block is refused without its file".
    root = _withdrawable(tmp_path)
    path = _exclude_file(root)
    begin = "# stayfixed:attach:begin\n"
    path.write_text(path.read_text(encoding="utf-8") + begin, encoding="utf-8")
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _detach(root)
    assert "info/exclude" in str(refused.value)
    assert_snapshot_unchanged(root, before)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a directory it cannot write")
def test_an_exclude_file_detach_cannot_write_is_refused_before_anything_is_withdrawn(
    tmp_path: Path,
) -> None:
    # A `.git/info` this user cannot write: `detach` found out by writing the exclude file, after
    # the settings file, the rule copies and the link tree were withdrawn, and stopped there with
    # the ledger and the block still in place, half detached. It is asked while nothing has been
    # withdrawn now, as `attach` asks it, and refused naming the file. Mutation (oracle):
    # `mutations/`'s "detach finds out the exclude file cannot be written by writing it" -> the
    # settings file and the rule copies go.
    root = _withdrawable(tmp_path)
    info = _exclude_file(root).parent
    # Non-vacuous: there is a block to take out, and a settings file and rule copies before it.
    assert "stayfixed:attach:begin" in _exclude_file(root).read_text(encoding="utf-8")
    assert (root / SETTINGS).is_file()
    assert any((root / ".codex" / "rules").iterdir())
    before = tree_entries(root)
    info.chmod(0o555)
    try:
        with pytest.raises(Refusal) as refused:
            _detach(root)
    finally:
        info.chmod(0o755)
    assert str(refused.value) == (
        f"{quoted(str(_exclude_file(root)))} cannot be written, because this user cannot write "
        "the directory that holds it, so nothing was written"
    )
    assert tree_entries(root) == before


def test_detach_writes_nothing_through_an_exclude_file_that_became_a_symlink(
    tmp_path: Path,
) -> None:
    # `attach` never writes through a symlinked exclude file, so a block behind one is not one it
    # put there, and `detach` leaves the link and the file it points at alone rather than reading
    # the block through it and replacing the link with a regular file.
    #
    # Mutation: `mutations/`'s "detach reads the block through a symlinked exclude file".
    root = _withdrawable(tmp_path)
    path = _exclude_file(root)
    elsewhere = tmp_path / "dotfiles-exclude"
    shutil.move(path, elsewhere)
    path.symlink_to(elsewhere)
    held = elsewhere.read_bytes()
    assert b"stayfixed:attach:begin" in held
    detached = _detach(root)
    assert path.is_symlink()
    assert elsewhere.read_bytes() == held
    assert not detached.exclude_block_removed


def test_an_exclude_file_ending_in_a_lone_carriage_return_keeps_its_last_pattern(
    tmp_path: Path,
) -> None:
    # git ends a line at `\n` alone, so an exclude file ending `/zz\r` holds the pattern `/zz` on
    # an unended last line. The block was read as starting a new line after the `\r`, so its first
    # marker was glued onto that line and `zz` showed in `git status` while the repository was
    # attached. The file comes back byte for byte on detach.
    #
    # Mutations: `mutations/`'s "a hash region reads a lone carriage return as a line end",
    # "the exclude block reads a lone carriage return as a line end" and "detach leaves the
    # newline it added after a lone carriage return".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    held = b"/qq\n/zz\r"
    _exclude_file(root).write_bytes(held)
    (root / "zz").write_text("mine\n", encoding="utf-8")
    assert "zz" not in git(root, "status", "--porcelain")
    _attach(root, store, machine)
    assert "zz" not in git(root, "status", "--porcelain")
    _detach(root)
    assert _exclude_file(root).read_bytes() == held


def test_an_info_directory_attach_created_is_removed_by_detach(tmp_path: Path) -> None:
    # A repository made without git's templates has no `.git/info/` at all, and the write of the
    # exclude file created it; `detach` removed the file and left the directory behind. The block
    # records that its directory was created for it, and `detach` takes the directory back when
    # it is empty.
    #
    # Mutation: `mutations/`'s "detach leaves the info directory attach created".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    info = _exclude_file(root).parent
    shutil.rmtree(info)
    _attach(root, store, machine)
    # Non-vacuous: the attach did create the directory for its block.
    assert _exclude_file(root).is_file()
    _detach(root)
    assert not info.exists()


def test_an_info_directory_the_owner_had_survives_detach(tmp_path: Path) -> None:
    # The other half: a directory that was there before the attach, even empty, is not the
    # attach's to take.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2], allow=(RULE,))
    info = _exclude_file(root).parent
    _exclude_file(root).unlink()
    assert info.is_dir() and not any(info.iterdir())
    _attach(root, store, machine)
    _detach(root)
    assert info.is_dir()


@pytest.mark.parametrize(
    "linked",
    [".stayfixed", ".stayfixed/local", ".claude"],
    ids=["stayfixed", "stayfixed-local", "claude"],
)
def test_a_directory_linked_in_after_attach_refuses_before_anything_is_withdrawn(
    tmp_path: Path, linked: str
) -> None:
    # Each removal `detach` makes is a walk that refuses a symlinked component, and the check made
    # before the first withdrawal was not that walk: it asked nothing of the ledger's or the
    # settings file's path. So `.stayfixed` or `.stayfixed/local` moved away and linked back ended
    # as `internal error: UnsafePath` with the settings file already withdrawn. Every removal
    # target is walked first now, and the refusal says which one.
    #
    # Mutations: `mutations/`'s "detach walks to the ledger only when it removes it" and "detach
    # walks to the settings file only when it rewrites it".
    root = _withdrawable(tmp_path)
    elsewhere = tmp_path / ("moved-" + linked.replace("/", "-"))
    shutil.move(root / linked, elsewhere)
    (root / linked).symlink_to(elsewhere, target_is_directory=True)
    before = snapshot(root)
    with pytest.raises(Refusal) as refused:
        _detach(root)
    assert "symlink" in str(refused.value)
    assert "internal error" not in str(refused.value)
    assert_snapshot_unchanged(root, before)


def test_a_rule_copy_that_is_itself_a_symlink_is_withdrawn(tmp_path: Path) -> None:
    # The copy's own name being a link is not a link on the way to it: the removal unlinks the
    # name and follows nothing, as it did before the check above existed, which refused this
    # with a sentence that blamed `.codex`.
    #
    # Mutation: `mutations/`'s "detach refuses a rule copy that is itself a symlink".
    root = _withdrawable(tmp_path)
    rule = root / ".codex" / "rules" / "common.rules"
    mine = tmp_path / "mine.rules"
    shutil.copy(rule, mine)
    rule.unlink()
    rule.symlink_to(mine)
    detached = _detach(root)
    assert ".codex/rules/common.rules" in detached.rules_removed
    assert not rule.is_symlink()
    assert mine.is_file()


def test_a_settings_file_detach_withdraws_nothing_from_is_not_rewritten(tmp_path: Path) -> None:
    # An overlay that grants nothing gives `attach` nothing to write into the settings file, and
    # `detach` then has nothing to take back out of it. Rewritten anyway, the file came back in
    # another layout, a change to somebody's file the round trip promises not to make, and under
    # the plugin's own entry Claude Code keeps there. A file with nothing to withdraw is not
    # written at all.
    #
    # Mutation: `mutations/`'s "detach rewrites a settings file it withdraws nothing from".
    from stayfixed.attach.write import attach

    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    # A repository that keeps its own notes, so the composed store's pointer is not written either.
    config = root / "stayfixed.toml"
    text = config.read_text(encoding="utf-8").replace('mode = "overlay"', 'mode = "local-only"')
    config.write_text(text, encoding="utf-8")
    (root / ".claude").mkdir()
    (root / SETTINGS).write_text('{"theme": "dark"}', encoding="utf-8")
    attach(root, store=store, machine=machine, runner=Recorder())
    _detach(root)
    assert (root / SETTINGS).read_text(encoding="utf-8") == '{"theme": "dark"}'
    assert not (root / LEDGER).exists()


def test_a_local_settings_file_read_but_too_deep_to_write_back_is_refused_or_withdrawn(
    tmp_path: Path,
) -> None:
    # 3,000 levels: read by every supported parser but 3.11's, and past 3.12's indenting encoder,
    # so `detach` read it there and then ended in `RecursionError` writing it back. Every
    # interpreter now either withdraws what `attach` wrote or refuses before removing anything.
    # Real depth, so it reddens on 3.12 in CI;
    # `test_a_local_settings_write_back_the_encoder_cannot_follow_is_refused_and_removes_nothing`
    # proves the arm on every interpreter, for the oracle.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    (root / SETTINGS).parent.mkdir(exist_ok=True)
    (root / SETTINGS).write_text('{"x": ' + "[" * 3_000 + "]" * 3_000 + "}", encoding="utf-8")
    before = snapshot(root)
    try:
        _detach(root)
    except (Failure, Refusal) as refused:
        assert "nested deeper than this reader follows" in str(refused)
        assert_snapshot_unchanged(root, before)


def test_a_local_settings_write_back_the_encoder_cannot_follow_is_refused_and_removes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Forced on every interpreter: the encode that writes the withdrawn settings back overflowing,
    # as it does on Python 3.12 near 994 levels. No single mutation reddens it, and that is the
    # point: two layers answer the overflow, `json_text` and the guard around `detach`'s copy and
    # comparison, and each is proven alone -- `mutations/`'s "the JSON writer lets an encode past
    # the interpreter's recursion escape" -> by the engine's forced case; "detach copies and
    # compares the settings document unguarded" -> by
    # `test_a_settings_document_too_deep_to_copy_or_compare_is_refused_and_removes_nothing`.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    (root / SETTINGS).parent.mkdir(exist_ok=True)
    (root / SETTINGS).write_text('{"theme": "dark"}', encoding="utf-8")
    before = snapshot(root)
    assert before
    monkeypatch.setattr(jsonobject, "_encode", overflowing_indent)
    monkeypatch.setattr(json, "dumps", overflowing_indent)
    with pytest.raises(Refusal, match="nested deeper than this reader follows"):
        _detach(root)
    assert_snapshot_unchanged(root, before)


def test_a_local_settings_file_linked_to_a_device_stops_detach_before_it_removes_anything(
    tmp_path: Path,
) -> None:
    # `detach` reads `.claude/settings.local.json` to take back what `attach` merged into it, and
    # read a link to a device through: `/dev/null` read as an empty file and the run went on.
    # Only a regular file is read, so it stops before it removes anything. Mutation (declared):
    # `mutations/`'s "the settings reader reads a file through any link".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    settings = root / SETTINGS
    settings.parent.mkdir(exist_ok=True)
    if settings.exists():
        settings.unlink()
    settings.symlink_to("/dev/null")
    before = snapshot(root)
    assert before
    with pytest.raises(Failure, match=r"settings\.local\.json cannot be read"):
        _detach(root)
    assert_snapshot_unchanged(root, before)


def test_a_ledger_linked_to_a_device_stops_detach_and_is_never_read(tmp_path: Path) -> None:
    # `detach` reads the ledger with no check before it, and a clone can commit the ledger: a link
    # there to `/dev/zero` read until memory ran out. Only a regular file is read, and the refusal
    # names the ledger as the project names it, never the machine's path. `/dev/null` tells the
    # guard apart without hanging: read, it is an empty ledger, "not valid JSON". Mutation
    # (declared): `mutations/`'s "the attach ledger is read through any link".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    (root / LEDGER).unlink()
    (root / LEDGER).symlink_to("/dev/null")
    before = snapshot(root)
    with pytest.raises(Failure) as refused:
        _detach(root)
    assert str(refused.value) == f"{LEDGER} cannot be read (not a regular file)"
    assert_snapshot_unchanged(root, before)


def test_a_ledger_that_is_not_utf8_is_named_as_the_project_names_it(tmp_path: Path) -> None:
    # The ledger's other refusal, held to the rule its first one keeps: the project's own name for
    # the file, never the machine's path. Mutation (oracle): `mutations/`'s "the ledger refusal of
    # a file that is not UTF-8 prints the path it opened".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    (root / LEDGER).write_bytes(b'{"entries": {"\xff": "PreToolUse"}}')
    before = snapshot(root)
    with pytest.raises(Failure) as refused:
        _detach(root)
    assert str(refused.value) == f"{LEDGER} is not UTF-8 text"
    assert_snapshot_unchanged(root, before)


class _ComparedTooDeep(dict[str, object]):
    """A parsed settings document whose comparison overflows, as `==` does on Python 3.14 for a
    document a few thousand levels deep under a reduced stack (`ulimit -s 2048`)."""

    def __eq__(self, other: object) -> bool:
        raise RecursionError

    __hash__ = None


@pytest.mark.parametrize("step", ["copy", "compare"])
def test_a_settings_document_too_deep_to_copy_or_compare_is_refused_and_removes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    # `detach` copies the parsed settings document through `json.dumps` and compares what is
    # left with it, and neither step was guarded: on Python 3.14 under a reduced stack a document
    # the parser read raised `RecursionError` at either, an internal error. Forced at each step
    # here; both are the reader's refusal of a document nested too deep. Mutation (declared):
    # `mutations/`'s "detach copies and compares the settings document unguarded".
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    (root / SETTINGS).parent.mkdir(exist_ok=True)
    (root / SETTINGS).write_text('{"theme": "dark"}', encoding="utf-8")
    before = snapshot(root)
    if step == "copy":
        real_dumps = json.dumps

        def dumps(value: object, *args: Any, **kwargs: Any) -> str:
            if not args and not kwargs:
                raise RecursionError
            return real_dumps(value, *args, **kwargs)

        monkeypatch.setattr(json, "dumps", dumps)
    else:
        real_loads = json.loads

        def loads(text: str, **kwargs: Any) -> object:
            loaded = real_loads(text, **kwargs)
            return _ComparedTooDeep(loaded) if isinstance(loaded, dict) else loaded

        monkeypatch.setattr(json, "loads", loads)
    with pytest.raises(Refusal, match="nested deeper than this reader follows"):
        _detach(root)
    assert_snapshot_unchanged(root, before)


def test_a_settings_write_back_past_the_read_cap_is_refused_and_removes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `detach` writes the withdrawn settings back indented, which can make a file the reader's
    # cap admits one it refuses: written, every later read of it refused. `jsonobject.json_text`
    # refuses such a write-back, so `detach` stops before it removes anything. The cap is lowered
    # so the document is small. Mutation (oracle): `mutations/`'s "the JSON writer writes back a
    # text past the read cap" -> `detach` writes it.
    root, store, machine = _bound(tmp_path)
    _grant(store.parents[2])
    _attach(root, store, machine)
    settings = root / SETTINGS
    settings.parent.mkdir(exist_ok=True)
    document = {"theme": "dark", "a": [[[[[[[[[[[] for _ in range(1_000)]]]]]]]]]]}
    settings.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    monkeypatch.setattr(fsops, "REGULAR_READ_LIMIT", 16 * 1024)
    before = snapshot(root)
    with pytest.raises(Refusal, match=jsonobject.WRITTEN_PAST):
        _detach(root)
    assert_snapshot_unchanged(root, before)
