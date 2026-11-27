"""The binding id in a repository's git common directory, and the machine's record of what it binds.

The id is the anchor: repository bytes cannot write `.git/`, and a clone never carries it, so a
checkout is bound only where this machine wrote an id into its common directory and a record
under its own data directory. Nothing here reads `drybag.toml`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from drybag import binding
from drybag.config.paths import data_directory
from drybag.errors import Failure
from drybag.gitenv import GitUnavailable
from drybag.printed import quoted
from tests.gitfixture import git, needs_git
from tests.runners import git_that_cannot_run

pytestmark = needs_git

ORIGIN = "git@example.com:acme/widget.git"
CONFIG = '[drybag]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n'


def _repository(root: Path, *, commit: bool = False) -> Path:
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / "drybag.toml").write_text(CONFIG, encoding="utf-8")
    if commit:
        git(root, "add", "-A")
        git(root, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "init")
    return root


def test_two_worktrees_of_one_repository_read_the_same_id_from_its_common_directory(
    tmp_path: Path,
) -> None:
    # `git rev-parse --git-path drybag/binding` resolves per worktree, so an id kept there would
    # leave every linked worktree unbound; the common directory is one place for all of them.
    main = _repository(tmp_path / "main", commit=True)
    linked = tmp_path / "linked"
    git(main, "worktree", "add", "-q", str(linked))
    made = binding.ensure_id(main)
    assert binding.common_directory(linked) == binding.common_directory(main)
    assert binding.read_id(linked) == made
    assert (main / ".git" / "drybag" / "binding").is_file()
    assert not list((main / ".git" / "worktrees").rglob("binding"))
    # A second ask reads the id rather than drawing another.
    assert binding.ensure_id(linked) == made


def test_a_fresh_clone_at_the_same_path_has_no_id_and_no_binding(tmp_path: Path) -> None:
    # The record of the earlier clone stays on the machine, keyed by an id the new clone never
    # holds, so the path alone binds nothing.
    upstream = _repository(tmp_path / "upstream", commit=True)
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(upstream), str(work))
    binding.record(work, "widget", ORIGIN)
    assert binding.bound_project(work) is not None
    shutil.rmtree(work)
    git(tmp_path, "clone", "-q", str(upstream), str(work))
    assert binding.read_id(work) is None
    assert binding.bound_project(work) is None


def test_a_checkout_with_no_id_is_unbound_even_when_its_name_is_a_bound_projects(
    tmp_path: Path,
) -> None:
    # A hostile clone commits `[project] name` equal to one of the owner's projects. The project
    # comes from the machine's record for this checkout's id, never from the repository's name.
    #
    # Mutation (oracle): `mutations/`'s "bound_project falls back to the repository's project name".
    owner = _repository(tmp_path / "owner")
    clone = _repository(tmp_path / "clone")
    recorded = binding.record(owner, "widget", ORIGIN)
    assert binding.bound_project(owner) == recorded
    assert recorded.project == "widget"
    assert binding.bound_project(clone) is None


def test_a_record_on_one_machine_leaves_another_machines_record_for_the_project_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two machines attaching one overlay project: each keeps its own id and its own record, and
    # neither turns the other's checkout unbound.
    first, second = tmp_path / "first-home", tmp_path / "second-home"
    first.mkdir()
    second.mkdir()
    here = _repository(tmp_path / "here")
    there = _repository(tmp_path / "there")
    monkeypatch.setenv("HOME", str(first))
    binding.record(here, "widget", ORIGIN)
    kept = {path: path.read_bytes() for path in data_directory().rglob("*.toml")}
    assert kept
    monkeypatch.setenv("HOME", str(second))
    binding.record(there, "widget", "https://example.com/acme/widget")
    assert binding.read_id(here) != binding.read_id(there)
    monkeypatch.setenv("HOME", str(first))
    assert {path: path.read_bytes() for path in data_directory().rglob("*.toml")} == kept
    id = binding.read_id(here)
    assert id is not None
    assert binding.bound_project(here) == binding.Bound("widget", ORIGIN, id)


@pytest.mark.parametrize(
    ("text", "read"),
    [
        pytest.param("0123456789abcdef0123456789abcdef", True, id="32-hex"),
        pytest.param("0123456789abcdef0123456789abcde", False, id="31-hex"),
        pytest.param("0123456789abcdef0123456789abcdef0", False, id="33-hex"),
        pytest.param("0123456789ABCDEF0123456789ABCDEF", False, id="upper-case"),
        pytest.param("0123456789abcdef0123456789abcdef\n", False, id="trailing-newline"),
    ],
)
def test_an_id_is_read_only_when_it_is_exactly_32_lowercase_hex_characters(
    tmp_path: Path, text: str, read: bool
) -> None:
    # Mutation (oracle): `mutations/`'s "read_id accepts a 31-character id".
    root = _repository(tmp_path / "root")
    stored = root / ".git" / "drybag" / "binding"
    stored.parent.mkdir()
    stored.write_text(text, encoding="utf-8")
    assert binding.read_id(root) == (text if read else None)


def test_a_fresh_id_is_32_lowercase_hex_characters_and_only_its_start_is_printed(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path / "root")
    made = binding.ensure_id(root)
    assert len(made) == 32 and set(made) <= set("0123456789abcdef")
    assert binding.short(made) == made[:8]


def test_the_data_directory_is_under_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "elsewhere"))
    assert data_directory() == tmp_path / ".local" / "share" / "drybag"


def test_a_directory_git_cannot_place_is_cannot_tell_and_never_an_id(tmp_path: Path) -> None:
    with pytest.raises(Failure, match="cannot tell"):
        binding.common_directory(tmp_path)


def test_attach_outside_a_repository_says_so(tmp_path: Path) -> None:
    # `git worktree list` exits 128 there, which was blamed on this machine's `git`.
    with pytest.raises(Failure) as failed:
        binding.main_checkout_or_none(tmp_path)
    assert str(failed.value) == binding.NOT_A_REPOSITORY.format(quoted(str(tmp_path)))
    git(tmp_path, "init", "-q", "--bare", "bare.git")
    assert binding.main_checkout_or_none(tmp_path / "bare.git") is None


def test_no_repository_is_no_id_and_a_git_that_cannot_run_is_never_no_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A directory git places in no repository holds no id, which is an answer; a `git` that
    # cannot be asked is a fault on this machine, and reading it as "no id" would tell the owner
    # to attach about their own `git`.
    assert binding.read_id(tmp_path) is None
    root = _repository(tmp_path / "root")
    binding.ensure_id(root)
    git_that_cannot_run(monkeypatch)
    with pytest.raises(GitUnavailable):
        binding.read_id(root)
