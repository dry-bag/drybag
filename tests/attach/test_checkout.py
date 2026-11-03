"""The owner-held files a new linked worktree gets (`attach.checkout`).

Each case builds a repository with a commit, binds it to project `p` the way `attach` does
(`binding.record`) and records an overlay whose `projects/p/checkout/` holds the owner's files in
the machine file under the test's own `HOME`. A case that expects nothing placed also shows, in the
same world, that the bound linked worktree is placed, so "nothing" is never "not bound".
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from stayfixed import binding
from stayfixed.attach.checkout import PLACED, READ_AGENTS, UNIGNORED, place, said
from stayfixed.attach.hooks import register
from stayfixed.hooks.api import HookEvent
from tests.gitfixture import git, needs_git
from tests.sessions import NO_CONFIG

pytestmark = needs_git

REGULAR = {"AGENTS.md": 0o755, "CLAUDE.md": 0o600, "stayfixed.toml": 0o644}
NOT_PLACED = (".env", ".env.local", ".ENV", "settings.local.json", ".DS_Store")


def _overlay(tmp_path: Path) -> Path:
    """An overlay whose `projects/p/checkout/` holds the three files that are placed and every kind
    of file that is not, recorded in the machine file under `HOME`."""
    overlay = tmp_path / "overlay"
    source = overlay / "projects" / "p" / "checkout"
    source.mkdir(parents=True)
    for name, mode in REGULAR.items():
        (source / name).write_text(f"owner's {name}\n", encoding="utf-8")
        (source / name).chmod(mode)
    for name in NOT_PLACED:
        (source / name).write_text("not for a worktree\n", encoding="utf-8")
    (source / "link.md").symlink_to(source / "AGENTS.md")
    (source / "notes").mkdir()
    (source / "notes" / "inner.md").write_text("inside a directory\n", encoding="utf-8")
    machine = Path(os.environ["HOME"]) / ".config" / "stayfixed" / "config.toml"
    machine.parent.mkdir(parents=True, exist_ok=True)
    machine.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    return overlay


def _repository(root: Path) -> Path:
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root


def _world(tmp_path: Path) -> tuple[Path, Path]:
    """A bound main checkout and a new linked worktree of it, with the overlay recorded."""
    _overlay(tmp_path)
    main = _repository(tmp_path / "main")
    binding.record(main, "p", None)
    linked = tmp_path / "linked"
    git(main, "worktree", "add", "-q", str(linked))
    return main, linked


def _names(directory: Path) -> set[str]:
    return {entry for entry in os.listdir(directory) if entry != ".git"}


def test_a_new_linked_worktree_gets_the_regular_files_and_nothing_else(tmp_path: Path) -> None:
    # Mutation (oracle): `mutations/`'s "owner-held files copy .env files" -> `.env` and
    # `.env.local` land in the worktree and this reddens.
    _, linked = _world(tmp_path)
    placed, _ = place(linked, machine=None)
    assert placed == sorted(REGULAR)
    assert _names(linked) == {"README.md", *REGULAR}
    source = tmp_path / "overlay" / "projects" / "p" / "checkout"
    for name, mode in REGULAR.items():
        assert (linked / name).read_bytes() == (source / name).read_bytes()
        assert stat.S_IMODE((linked / name).stat().st_mode) == mode


@pytest.mark.parametrize("kind", ["file", "directory", "dangling link"])
def test_a_present_name_is_never_overwritten(tmp_path: Path, kind: str) -> None:
    # Mutation (oracle): `mutations/`'s "owner-held files overwrite a present name" -> the file is
    # written over, and the directory and the link refuse with an error.
    _, linked = _world(tmp_path)
    target = linked / "AGENTS.md"
    outside = tmp_path / "outside.md"
    if kind == "file":
        target.write_text("the worktree's own\n", encoding="utf-8")
    elif kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(outside)
    placed, _ = place(linked, machine=None)
    assert placed == ["CLAUDE.md", "stayfixed.toml"]
    if kind == "file":
        assert target.read_text(encoding="utf-8") == "the worktree's own\n"
    elif kind == "directory":
        assert target.is_dir() and not os.listdir(target)
    else:
        assert target.is_symlink() and os.readlink(target) == str(outside)
        assert not outside.exists()


def test_a_tracked_name_is_left_to_the_branch(tmp_path: Path) -> None:
    # The worktree already has `AGENTS.md` from the branch, so the exclusive create finds the name
    # taken: nothing is placed over it and nothing is said of it.
    _overlay(tmp_path)
    main = _repository(tmp_path / "main")
    (main / "AGENTS.md").write_text("the branch's\n", encoding="utf-8")
    git(main, "add", "-A")
    git(main, "commit", "-qm", "track AGENTS.md")
    binding.record(main, "p", None)
    linked = tmp_path / "linked"
    git(main, "worktree", "add", "-q", str(linked))
    placed, _ = place(linked, machine=None)
    assert placed == ["CLAUDE.md", "stayfixed.toml"]
    assert (linked / "AGENTS.md").read_text(encoding="utf-8") == "the branch's\n"


def test_the_main_checkout_gets_nothing(tmp_path: Path) -> None:
    # Mutation (oracle): `mutations/`'s "owner-held files are placed in the main checkout" -> the
    # main checkout is given the files and this reddens.
    main, linked = _world(tmp_path)
    assert place(main, machine=None) == ([], [])
    assert _names(main) == {"README.md"}
    assert place(linked, machine=None)[0] == sorted(REGULAR)


def test_a_worktree_of_a_bare_repository_gets_nothing(tmp_path: Path) -> None:
    _overlay(tmp_path)
    source = _repository(tmp_path / "source")
    bare = tmp_path / "bare.git"
    git(tmp_path, "clone", "-q", "--bare", str(source), str(bare))
    linked = tmp_path / "linked"
    git(bare, "worktree", "add", "-q", str(linked), "main")
    binding.record(linked, "p", None)
    assert binding.bound_project(linked) is not None
    assert place(linked, machine=None) == ([], [])
    assert _names(linked) == {"README.md"}


def test_a_submodule_gets_nothing(tmp_path: Path) -> None:
    _overlay(tmp_path)
    inner = _repository(tmp_path / "inner")
    outer = _repository(tmp_path / "outer")
    git(outer, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "sub")
    submodule = outer / "sub"
    binding.record(submodule, "p", None)
    assert binding.bound_project(submodule) is not None
    assert place(submodule, machine=None) == ([], [])
    assert _names(submodule) == {"README.md"}


def test_an_unbound_worktree_gets_nothing(tmp_path: Path) -> None:
    # Same `origin` as the bound project, no binding id: a clone of the owner's repository, which
    # carries neither the id nor this machine's record of it.
    _, linked = _world(tmp_path)
    origin = "git@example.com:acme/widget.git"
    clone = _repository(tmp_path / "clone")
    git(clone, "remote", "add", "origin", origin)
    stranger = tmp_path / "stranger"
    git(clone, "worktree", "add", "-q", str(stranger))
    assert binding.read_id(stranger) is None
    assert place(stranger, machine=None) == ([], [])
    assert _names(stranger) == {"README.md"}
    assert place(linked, machine=None)[0] == sorted(REGULAR)


def test_the_second_session_says_nothing(tmp_path: Path) -> None:
    _, linked = _world(tmp_path)
    (handler,) = (h for h in register() if h.name == "owner-files")
    event = _event(linked)
    assert handler.run(event, NO_CONFIG).context is not None
    assert place(linked, machine=None) == ([], [])
    assert handler.run(event, NO_CONFIG).context is None


def test_the_context_names_unignored_files_and_asks_to_read_agents_md(tmp_path: Path) -> None:
    _, linked = _world(tmp_path)
    exclude = Path(git(linked, "rev-parse", "--git-path", "info/exclude").strip())
    exclude = exclude if exclude.is_absolute() else linked / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("/CLAUDE.md\n", encoding="utf-8")
    placed, visible = place(linked, machine=None)
    assert (placed, visible) == (sorted(REGULAR), ["AGENTS.md", "stayfixed.toml"])
    assert said(placed, visible) == (
        f"{PLACED.format(names='AGENTS.md, CLAUDE.md, stayfixed.toml')} {READ_AGENTS} "
        f"{UNIGNORED.format(names='AGENTS.md, stayfixed.toml')}"
    )
    # Nothing placed, nothing said; and no instruction to read when neither document is among them.
    assert said([], []) == ""
    assert said(["stayfixed.toml"], []) == PLACED.format(names="stayfixed.toml")


def test_the_handler_needs_no_configuration_and_a_machine_without_an_overlay_places_nothing(
    tmp_path: Path,
) -> None:
    # The worktree has no `stayfixed.toml` until this places one, so the handler is asked with no
    # configuration at all; and a machine file recording no overlay leaves the worktree as it is.
    _, linked = _world(tmp_path)
    machine = Path(os.environ["HOME"]) / ".config" / "stayfixed" / "config.toml"
    machine.write_text("[overlay]\n", encoding="utf-8")
    (handler,) = (h for h in register() if h.name == "owner-files")
    assert handler.run(_event(linked), NO_CONFIG).context is None
    assert _names(linked) == {"README.md"}


def _event(root: Path) -> HookEvent:
    return HookEvent("SessionStart", "s1", None, None, {}, root, root, {"source": "startup"})
