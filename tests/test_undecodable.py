"""A file a person or a repository owns that is not UTF-8 is its area's answer, never a crash.

stayfixed reads every such file as UTF-8, and `read_text` raises `UnicodeDecodeError` for one
that is not: a `ValueError`, so an `except OSError` beside it caught nothing and the command
ended in `internal error: UnicodeDecodeError` (exit 2) instead of the failure the same file
gets when it cannot be read or parsed. Each case below plants the bytes `\\xff\\xfe` at one
reader's file and asks for what that reader already answers a broken file with: a `Failure`
(or, for the `.gitignore` `attach` must write, a `Refusal`), or, where a reader treats an
unreadable file as absent, the same absent answer.

Mutation (by hand, per case): take `UnicodeDecodeError` out of the reader's `except` -> that
case reddens on the decode error itself. Three of these readers are declared: the two a
command's first read meets, `stayfixed.toml` and the machine file, and the trust record's, as
`mutations/`'s "a stayfixed.toml that is not UTF-8 crashes every command that loads it", "a
machine file that is not UTF-8 crashes every command that loads the configuration" and "a trust
record that is not UTF-8 crashes instead of refusing loudly".
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from stayfixed import fsops
from stayfixed.attach import binding, permissions, write
from stayfixed.attach.binding import Binding
from stayfixed.config.loader import CONFIG_FILE, load, read_document
from stayfixed.config.overlay import overlay_root
from stayfixed.config.plates import plates
from stayfixed.config.reading import ConfigError, MachineConfigError
from stayfixed.errors import Failure
from stayfixed.memory import index, store
from stayfixed.overlay import identity
from stayfixed.overlay.api import COMMON_CODEX
from stayfixed.overlay.layout import IDENTITY_RECORD
from stayfixed.printed import quoted
from stayfixed.project.init import _existing
from stayfixed.setup.machine import read_machine
from stayfixed.setup.run import _read_document
from stayfixed.trust.record import UnreadableTrust, recorded
from tests.cli import cli
from tests.gitfixture import git, needs_git
from tests.project.repos import DOCUMENT, repository
from tests.scriptload import release

# The repository's release script, whose version check is one more reader below.
script = release()

UNDECODABLE = b"\xff\xfe[overlay]\n"


def _plant(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(UNDECODABLE)
    return path


def _config(root: Path) -> Path:
    return _plant(root / CONFIG_FILE)


# (id, what to plant under `tmp_path`, the call, the exception the reader answers with)
RAISING: list[tuple[str, Callable[[Path], Callable[[], object]], type[Exception]]] = [
    (
        "stayfixed.toml, as every command loads it",
        lambda t: (_config(t), lambda: load(t, machine=t / "absent.toml"))[1],
        ConfigError,
    ),
    (
        "stayfixed.toml, as the editors read it",
        lambda t: (_config(t), lambda: read_document(t))[1],
        ConfigError,
    ),
    ("stayfixed.toml, as init adopts it", lambda t: (_config(t), lambda: _existing(t))[1], Failure),
    (
        "the machine file, under the loader",
        lambda t: (
            (t / CONFIG_FILE).write_text(DOCUMENT, encoding="utf-8"),
            lambda: load(t, machine=_plant(t / "machine.toml")),
        )[1],
        MachineConfigError,
    ),
    (
        "the machine file, for its overlay root",
        lambda t: lambda: overlay_root(_plant(t / "machine.toml")),
        MachineConfigError,
    ),
    (
        "the machine file, under setup",
        lambda t: lambda: read_machine(_plant(t / "m.toml")),
        MachineConfigError,
    ),
    (
        "the trust record",
        lambda t: (_plant(t / "trust.json"), lambda: recorded(t / "machine.toml"))[1],
        UnreadableTrust,
    ),
    (
        "the overlay's project record",
        lambda t: (
            _plant(binding._record(t, "widget")),
            lambda: binding._recorded(t, "widget"),
        )[1],
        Failure,
    ),
    (
        "a harness settings file attach merges into",
        lambda t: lambda: permissions._read(_plant(t / "settings.local.json")),
        Failure,
    ),
    (
        "the attach ledger",
        lambda t: (_plant(t / "attach.json"), lambda: write.read_ledger(t / "attach.json"))[1],
        Failure,
    ),
    (
        "an overlay rule attach copies for Codex",
        lambda t: (
            _plant(t / "overlay" / COMMON_CODEX / "rules.md"),
            lambda: write._codex_rule_texts(
                Binding(
                    "widget",
                    t / "overlay",
                    t / "store",
                    None,
                    None,
                    "",
                    plates=plates(t / "overlay", "widget")[0],
                )
            ),
        )[1],
        Failure,
    ),
    (
        "a harness settings file setup merges into",
        lambda t: lambda: _read_document(_plant(t / "settings.json")),
        Failure,
    ),
    (
        "pyproject.toml, for the release check",
        lambda t: (_plant(t / script.PYPROJECT), lambda: script._pyproject(t))[1],
        script.MalformedSource,
    ),
    (
        "a version source, for the release check",
        lambda t: (
            _plant(t / script.PYPROJECT),
            lambda: script._read(t, script.PYPROJECT),
        )[1],
        script.MalformedSource,
    ),
    (
        "the marketplace manifest, for the release check",
        lambda t: (
            (t / script.PYPROJECT).write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8"),
            _plant(t / script.MARKETPLACE),
            lambda: script.check(t),
        )[2],
        script.MalformedSource,
    ),
]


@pytest.mark.parametrize(
    ("planted", "expected"), [(p, e) for _, p, e in RAISING], ids=[i for i, _, _ in RAISING]
)
def test_an_undecodable_file_is_its_readers_own_failure(
    tmp_path: Path, planted: Callable[[Path], Callable[[], object]], expected: type[Exception]
) -> None:
    call = planted(tmp_path)
    with pytest.raises(expected, match="not UTF-8 text"):
        call()


# (id, what to plant, the call, what the reader answers for a file it cannot read)
ABSENT: list[tuple[str, Callable[[Path], Callable[[], object]], object]] = [
    (
        "the memory index a second writer appended to",
        lambda t: lambda: index._outside(_plant(t / "MEMORY.md")),
        [],
    ),
    (
        "the attach record's keys",
        lambda t: lambda: write._record_table(_plant(t / "project.toml")),
        None,
    ),
]


@pytest.mark.parametrize(
    ("planted", "answer"), [(p, a) for _, p, a in ABSENT], ids=[i for i, _, _ in ABSENT]
)
def test_an_undecodable_file_a_reader_treats_as_absent_is_absent(
    tmp_path: Path, planted: Callable[[Path], Callable[[], object]], answer: object
) -> None:
    assert planted(tmp_path)() == answer


def test_an_undecodable_overlay_identity_record_is_no_record(tmp_path: Path) -> None:
    _plant(tmp_path / IDENTITY_RECORD)
    assert identity.overlay_fault(tmp_path) == identity.NOT_A_RECORD.format(
        root=quoted(str(tmp_path))
    )


@needs_git
def test_an_undecodable_worktree_back_pointer_is_no_registered_worktree(tmp_path: Path) -> None:
    # `.git/worktrees/<name>/gitdir` is git's own file, read to find the checkout that owns the
    # store; one that cannot be decoded answers "not a registered worktree", as one that cannot
    # be read does.
    main = repository(tmp_path)
    git(main, "commit", "-q", "--allow-empty", "-m", "first")
    linked = tmp_path / "linked"
    git(main, "worktree", "add", "-q", str(linked))
    private = Path(git(linked, "rev-parse", "--path-format=absolute", "--git-dir").strip())
    assert store._registered_worktree(linked) is not None
    (private / "gitdir").write_bytes(b"\xff\xfe\n")
    assert store._registered_worktree(linked) is None


@needs_git
@pytest.mark.parametrize(
    ("argv", "planted"),
    [
        (("init", "--yes", "--dry-run"), "machine"),
        (("init", "--yes", "--dry-run"), CONFIG_FILE),
        (("docs", "check"), CONFIG_FILE),
    ],
    ids=["init-machine", "init-stayfixed-toml", "docs-check-stayfixed-toml"],
)
def test_a_command_meeting_an_undecodable_file_fails_and_does_not_crash(
    tmp_path: Path, argv: tuple[str, ...], planted: str
) -> None:
    # Through the real parser: the exit code and the frame's own word for it are what a person
    # and a relaying agent read, and `internal error` told them the fault was stayfixed's.
    root = repository(tmp_path)
    machine = _plant(tmp_path / "machine.toml") if planted == "machine" else None
    if planted == CONFIG_FILE:
        _config(root)
    code, _, stderr = cli(root, tmp_path, *argv, machine=machine)
    assert code == 1
    assert "failed:" in stderr and "not UTF-8 text" in stderr and "internal error" not in stderr


@needs_git
def test_the_questions_read_an_undecodable_machine_file_as_recording_no_overlay(
    tmp_path: Path,
) -> None:
    # The machine file changes one title of the questions and nothing else, so a broken one
    # reads as recording no overlay, however it is broken.
    root = repository(tmp_path)
    code, _, stderr = cli(
        root, tmp_path, "init", "--questions", machine=_plant(tmp_path / "m.toml")
    )
    assert code == 0
    assert "internal error" not in stderr


# The neighbour the same probe found: `stayfixed.toml` and the machine file are the first thing
# most commands read, and one that cannot be read at all — a directory at the path, or a
# permission bit — also ended in `internal error`. Mutation (by hand, per case): the `except
# OSError` taken out of that reader -> the case reddens on the `OSError` itself.
def test_a_stayfixed_toml_that_is_a_directory_cannot_be_read_and_says_so(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILE).mkdir()
    with pytest.raises(ConfigError, match=r"cannot be read \(not a regular file\)"):
        load(tmp_path, machine=tmp_path / "absent.toml")
    with pytest.raises(ConfigError, match=r"cannot be read \(not a regular file\)"):
        read_document(tmp_path)


def test_a_stayfixed_toml_past_the_read_cap_cannot_be_read_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `stayfixed.toml` is committed and is the first thing most commands and every hook read, so it
    # is read to the read cap by the bounded reader every committed file is read with, and one past
    # it is a file that cannot be read rather than one read to its end. The cap is lowered so the
    # file is small. Mutation (oracle): `mutations/`'s "stayfixed.toml is read with no bound" -> the
    # document is read.
    limit = 4 * 1024
    (tmp_path / CONFIG_FILE).write_text("#" * (limit + 1), encoding="utf-8")
    monkeypatch.setattr(fsops, "REGULAR_READ_LIMIT", limit)
    with pytest.raises(ConfigError) as refused:
        read_document(tmp_path)
    assert str(refused.value) == f"{CONFIG_FILE} cannot be read (larger than this reader reads)"


@pytest.mark.parametrize("which", ["machine", "overlay-root", "setup", CONFIG_FILE])
def test_a_file_without_read_permission_cannot_be_read_and_says_so(
    tmp_path: Path, which: str
) -> None:
    # `overlay-root` is the machine file again, through the one reader of its `[overlay] root`
    # key. Its `PermissionError` escaped as itself, past the `Failure` every caller of the overlay
    # root catches — the memory hooks among them. `setup` is the same file through the reader
    # `stayfixed setup` merges into: without the arm, setup ended in an internal error quoting the
    # operating system's message. Mutation (oracle): `mutations/`'s "the overlay root's reader lets
    # a machine file it cannot read raise past its callers".
    if os.geteuid() == 0:
        pytest.skip("root reads everything")
    (tmp_path / CONFIG_FILE).write_text(DOCUMENT, encoding="utf-8")
    machine = tmp_path / "machine.toml"
    machine.write_text("[personal]\n", encoding="utf-8")
    locked = tmp_path / CONFIG_FILE if which == CONFIG_FILE else machine
    locked.chmod(0)
    try:
        if which == "machine":
            with pytest.raises(MachineConfigError, match=r"cannot be read \(Permission denied\)"):
                load(tmp_path, machine=machine)
        elif which == "overlay-root":
            with pytest.raises(MachineConfigError, match=r"cannot be read \(Permission denied\)"):
                overlay_root(machine)
        elif which == "setup":
            with pytest.raises(MachineConfigError, match=r"cannot be read \(Permission denied\)"):
                read_machine(machine)
        else:
            with pytest.raises(Failure, match=r"cannot be read \(Permission denied\)"):
                _existing(tmp_path)
    finally:
        locked.chmod(0o644)


def test_a_machine_file_setup_cannot_parse_is_the_loaders_failure(tmp_path: Path) -> None:
    # The same reader's other broken shape: `read_machine` parsed with no answer for a file that
    # is not TOML either, so `stayfixed setup` crashed on the stray bracket the loader names by
    # position. Mutation (by hand): the `TOMLDecodeError` arm removed -> this reddens on it.
    machine = tmp_path / "machine.toml"
    machine.write_text("[overlay\n", encoding="utf-8")
    with pytest.raises(MachineConfigError, match=r"is not valid TOML \(at line 1"):
        read_machine(machine)
