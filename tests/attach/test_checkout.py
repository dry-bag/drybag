"""The owner-held files a new linked worktree gets (`attach.checkout`).

Each case builds a repository with a commit, binds it to project `p` the way `attach` does
(`binding.record`) and records an overlay whose `projects/p/checkout/` holds the owner's files in
the machine file under the test's own `HOME`. A case that expects nothing placed also shows, in the
same world, that the bound linked worktree is placed, so "nothing" is never "not bound".
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from drybag import binding
from drybag.attach.checkout import PLACED, READ_AGENTS, WITHHELD, place, said
from drybag.attach.hooks import register
from drybag.errors import Refusal
from drybag.hooks.api import HookEvent
from tests.gitfixture import git, needs_git
from tests.sessions import NO_CONFIG

pytestmark = needs_git

REGULAR = {"AGENTS.md": 0o755, "CLAUDE.md": 0o600, "drybag.toml": 0o644}
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
    machine = Path(os.environ["HOME"]) / ".config" / "drybag" / "config.toml"
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


def _world(
    tmp_path: Path, *, hide: tuple[str, ...] = (*REGULAR, *NOT_PLACED), gitignore: str | None = None
) -> tuple[Path, Path]:
    """A bound main checkout and a new linked worktree of it, with the overlay recorded. The
    owner's `info/exclude` hides `hide`, by default every name in the overlay's `checkout/` that a
    file could be, so only the rules of the handler itself keep one out; and a branch commits
    `gitignore` where it is given."""
    _overlay(tmp_path)
    main = _repository(tmp_path / "main")
    (main / ".git" / "info").mkdir(exist_ok=True)
    (main / ".git" / "info" / "exclude").write_text(
        "".join(f"/{name}\n" for name in hide), encoding="utf-8"
    )
    if gitignore is not None:
        (main / ".gitignore").write_text(gitignore, encoding="utf-8")
        git(main, "add", "-A")
        git(main, "commit", "-qm", "the branch's ignore rules")
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
    # A name with anything at it is neither placed nor reported; the exclusive create under it is
    # `fsops`'s and held by `tests/test_fsops.py`.
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
    assert placed == ["CLAUDE.md", "drybag.toml"]
    if kind == "file":
        assert target.read_text(encoding="utf-8") == "the worktree's own\n"
    elif kind == "directory":
        assert target.is_dir() and not os.listdir(target)
    else:
        assert target.is_symlink() and os.readlink(target) == str(outside)
        assert not outside.exists()


def test_the_main_checkout_gets_nothing(tmp_path: Path) -> None:
    # Mutation (oracle): `mutations/`'s "owner-held files are placed in the main checkout" -> the
    # main checkout is given the files and this reddens.
    main, linked = _world(tmp_path)
    assert place(main, machine=None) == ([], [])
    assert _names(main) == {"README.md"}
    assert place(linked, machine=None)[0] == sorted(REGULAR)


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


def test_the_handler_asks_git_once_before_it_knows_a_worktree_is_not_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # It runs on every `SessionStart` of every repository: the one `rev-parse` that finds the linked
    # worktree names the common directory the binding id is read from, so a worktree this machine
    # does not bind, and a bound one whose project holds no `checkout/`, each cost one launch.
    _, linked = _world(tmp_path)
    stranger = tmp_path / "stranger"
    clone = _repository(tmp_path / "clone")
    git(clone, "worktree", "add", "-q", str(stranger))
    shutil.rmtree(tmp_path / "overlay" / "projects" / "p" / "checkout")
    launched: list[str] = []
    real = subprocess.Popen

    def spy(argv, *args, **kwargs):  # type: ignore[no-untyped-def]
        launched.append(str(argv[0]))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    for tree in (stranger, linked):
        launched.clear()
        assert place(tree, machine=None) == ([], [])
        assert launched == ["git"]


def test_the_second_session_says_nothing(tmp_path: Path) -> None:
    _, linked = _world(tmp_path)
    (handler,) = (h for h in register() if h.name == "owner-files")
    event = _event(linked)
    assert handler.run(event, NO_CONFIG).context is not None
    assert place(linked, machine=None) == ([], [])
    assert handler.run(event, NO_CONFIG).context is None


def test_the_context_names_what_it_withheld_and_reads_agents_md_only_when_it_placed_it(
    tmp_path: Path,
) -> None:
    # Mutation (oracle): `mutations/`'s "owner-held files point at an AGENTS.md they did not place"
    # -> `CLAUDE.md` placed alone points the session at the branch's own `AGENTS.md`.
    _, linked = _world(tmp_path, hide=("CLAUDE.md",))
    placed, withheld = place(linked, machine=None)
    assert (placed, withheld) == (["CLAUDE.md"], ["AGENTS.md", "drybag.toml"])
    assert said(placed, withheld) == (
        f"{PLACED.format(names='CLAUDE.md')} {WITHHELD.format(names='AGENTS.md, drybag.toml')}"
    )
    assert said(["AGENTS.md", "CLAUDE.md"], []) == (
        f"{PLACED.format(names='AGENTS.md, CLAUDE.md')} {READ_AGENTS}"
    )
    # Nothing placed and nothing withheld, nothing said.
    assert said([], []) == ""


def test_a_name_a_branch_gitignore_un_ignores_is_withheld_not_placed(tmp_path: Path) -> None:
    # The owner's `info/exclude` hides all three names, and the branch's `.gitignore` re-includes
    # two: a `!` line outranks the exclude file, so placed they would show in `git status` and go
    # out with the next `git add -A`. Asked before anything is created, so they are named and not
    # written; the control fails closed, since a branch can only make fewer files be placed.
    # Mutation (oracle): `mutations/`'s "owner-held files are placed before git is asked whether
    # they are ignored".
    _, linked = _world(tmp_path, gitignore="!/AGENTS.md\n!/CLAUDE.md\n")
    placed, withheld = place(linked, machine=None)
    assert (placed, withheld) == (["drybag.toml"], ["AGENTS.md", "CLAUDE.md"])
    assert _names(linked) == {"README.md", ".gitignore", "drybag.toml"}
    assert git(linked, "status", "--porcelain") == ""


def test_a_branchs_gitignore_never_makes_a_name_be_placed(tmp_path: Path) -> None:
    # The branch hides `AGENTS.md`, the owner hides nothing, and the branch's next commit takes the
    # line out: `?? AGENTS.md`, and `git add -A` stages the owner's private file. Only the owner's
    # own files open the gate, so a branch can only make fewer files be placed. Mutation (oracle):
    # `mutations/`'s "a branch's .gitignore opens the owner-files gate".
    _, linked = _world(tmp_path, hide=(), gitignore="/AGENTS.md\n")
    placed, withheld = place(linked, machine=None)
    assert placed == [] and withheld == sorted(REGULAR)
    assert _names(linked) == {"README.md", ".gitignore"}


def test_where_git_cannot_say_what_it_ignores_nothing_is_placed_or_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, linked = _world(tmp_path)

    def unanswered(root: Path, relatives: object) -> tuple[str, ...]:
        raise Refusal("git did not answer")

    monkeypatch.setattr("drybag.attach.checkout.unignored", unanswered)
    assert place(linked, machine=None) == ([], [])
    assert _names(linked) == {"README.md"}


def test_the_handler_needs_no_configuration_and_a_machine_without_an_overlay_places_nothing(
    tmp_path: Path,
) -> None:
    # The worktree has no `drybag.toml` until this places one, so the handler is asked with no
    # configuration at all; and a machine file recording no overlay leaves the worktree as it is.
    _, linked = _world(tmp_path)
    machine = Path(os.environ["HOME"]) / ".config" / "drybag" / "config.toml"
    machine.write_text("[overlay]\n", encoding="utf-8")
    (handler,) = (h for h in register() if h.name == "owner-files")
    assert handler.run(_event(linked), NO_CONFIG).context is None
    assert _names(linked) == {"README.md"}


def _event(root: Path) -> HookEvent:
    return HookEvent("SessionStart", "s1", None, None, {}, root, root, {"source": "startup"})
