"""The Python profile's red-run hint: which commands run pytest, which bytecode is stale, and the
line it adds to the notice after a failed pytest run."""

from __future__ import annotations

import importlib.util
import os
import py_compile
import struct
import sys
import threading
from collections.abc import Mapping
from pathlib import Path

import pytest

from stayfixed import fsops
from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.config.schema import Config
from stayfixed.hints.hygiene import simple_commands
from stayfixed.profiles.python import hygiene as python_hygiene
from stayfixed.profiles.python.hygiene import HINT
from stayfixed.roots import contained_roots
from tests.profiles.python.bytecode import compile_module, make_stale

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
profile = ""
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
release_branch = "main"

[ledger]
code_roots = ["src", "tests"]
"""


def repo(tmp_path: Path) -> Path:
    # No git repository: the walk reads files and nothing else, and the dirty count that needs
    # git belongs to the red-run note (`tests/hints/test_hygiene.py`).
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    return root


def config(root: Path) -> Config:
    return load(root, machine=root.parent / "absent.toml")


def reported(root: Path) -> Mapping[str, int] | None:
    """The hint's report over the roots the guard hands it: `ledger.code_roots`, contained."""
    return HINT.report(contained_roots(root, config(root)))


def counted(root: Path) -> Mapping[str, int]:
    """The hint's counts for a walk that finished; a test that wants `None` asks `report`."""
    report = reported(root)
    assert report is not None
    return report


def stale(root: Path) -> int:
    return counted(root)["stale"]


def runs_pytest(command: str) -> bool:
    """The question the handler asks: does the hint recognise any simple command of `command`."""
    return any(HINT.recognises(argv) for argv in simple_commands(command))


def test_stale_bytecode_is_counted(tmp_path: Path) -> None:
    """A `.pyc` is stale when the source mtime recorded in its header (bytes 8-12) no longer
    matches the source's — the condition CPython itself checks. Compile, then move the source
    forward."""
    # Oracle: `mutations/`'s "stale bytecode is never counted".
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    compile_module(module)
    make_stale(module)
    assert stale(root) == 1


UNTOLD = (
    "the configured code roots hold more than {entries} directory entries or {files} .pyc files, "
    "so the walk for .pyc files stopped there and could not tell whether the interpreter imported "
    "a build older than its source. If the failure could be a stale build, delete the "
    "`__pycache__` directories under those roots and re-run before attributing anything."
)
READ_FILES = python_hygiene.BYTECODE_READ_FILES
ENTRIES = fsops.WALK_ENTRIES


def a_stale_tree_of_eight_entries(tmp_path: Path) -> Path:
    """`src` holding eight directory entries: one stale `.pyc` in its `__pycache__`, the source
    beside it, and five files that are no bytecode at all."""
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    compile_module(module)
    make_stale(module)
    for index in range(5):
        (root / "src" / f"data{index}.txt").write_text("", encoding="utf-8")
    return root


def test_a_walk_cut_short_by_its_cap_could_not_tell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The walk had no bound of its own: about 0.37 s per 100k directory entries, stopped only by
    # the harness's hook timeout, and a hook that times out never banks its once-key, so every
    # later red run in the context paid the whole walk again. Bounded, a walk that reached its
    # cap has not seen the tree, so its count is no answer either way: the report carries no
    # `stale` and says it could not tell, and the note claims neither stale bytecode nor its
    # absence. The cap counts every entry visited and not only `.pyc` files: here one `.pyc`
    # among eight entries is over a cap of seven. Oracle: `mutations/`'s "the stale-bytecode walk
    # ignores its cap".
    root = a_stale_tree_of_eight_entries(tmp_path)
    monkeypatch.setattr(fsops, "WALK_ENTRIES", 8)
    assert reported(root) == {"stale": 1, "roots": 1}
    monkeypatch.setattr(fsops, "WALK_ENTRIES", 7)
    counts = reported(root)
    assert counts is None
    # Reddened by dropping `note`'s undetermined branch, which leaves the note silent; measured.
    assert HINT.note(counts) == UNTOLD.format(entries=7, files=READ_FILES)


def test_bytecode_past_the_read_cap_could_not_tell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The entry cap bounds the listing, and the listing is the cheap half: each `.pyc` it lists
    # is then opened and read and its source stat'ed, about fifty times a listed entry's cost,
    # and any number of `.pyc` files share one source (the name before the first dot). 200,000
    # of them under one `m.py` took 18 s on this walk with the entry cap alone, past the hook's
    # 10 s timeout. So the reads have a cap of their own, and reaching it is the same "could not
    # tell". Here three stale `.pyc` files share one source, well under the entry cap. Oracle:
    # `mutations/`'s "the stale-bytecode walk reads past its read cap".
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    compiled = compile_module(module)
    make_stale(module)
    for tag in ("one", "two"):
        (compiled.parent / f"mod.{tag}.pyc").write_bytes(compiled.read_bytes())
    monkeypatch.setattr(python_hygiene, "BYTECODE_READ_FILES", 3)
    assert reported(root) == {"stale": 3, "roots": 1}
    monkeypatch.setattr(python_hygiene, "BYTECODE_READ_FILES", 2)
    counts = reported(root)
    assert counts is None
    assert HINT.note(counts) == UNTOLD.format(entries=ENTRIES, files=2)


def test_the_entry_cap_is_one_total_across_the_code_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `src` holds three entries (the source, its `__pycache__`, the stale `.pyc`) and `tests`
    # three more. A cap of four is above either root and below their sum, so a walk that counts
    # per root would answer, and with every listed code root multiplying the cap no bound is
    # left on the hook's time. Oracle: `mutations/`'s "the stale-bytecode walk counts its cap
    # afresh for each code root".
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    compile_module(module)
    make_stale(module)
    (root / "tests").mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (root / "tests" / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(fsops, "WALK_ENTRIES", 6)
    assert reported(root) == {"stale": 1, "roots": 2}
    monkeypatch.setattr(fsops, "WALK_ENTRIES", 4)
    assert reported(root) is None


def test_bytecode_under_a_hidden_directory_is_judged(tmp_path: Path) -> None:
    # The walk enters hidden directories, as the `rglob` it replaced did: a package under `.ci`
    # or `.tools` is imported like any other. Oracle: `mutations/`'s "the stale-bytecode walk
    # skips hidden directories".
    root = repo(tmp_path)
    module = root / "src" / ".tools" / "helper.py"
    module.parent.mkdir()
    module.write_text("z = 1\n", encoding="utf-8")
    compile_module(module)
    make_stale(module)
    assert stale(root) == 1


def test_a_directory_that_cannot_be_listed_is_passed_over(tmp_path: Path) -> None:
    # A directory the walk cannot list is passed over, as `rglob` passed over it, and the rest
    # of the tree is still judged: raising would turn a permission bit on one directory into a
    # failed hint, and the whole tree's note into a refusal. Oracle: `mutations/`'s
    # "an unlistable directory fails the stale-bytecode walk".
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    compile_module(module)
    make_stale(module)
    locked = root / "src" / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("this user lists a directory whose mode is 0; the fault cannot be staged")
        assert stale(root) == 1
    finally:
        locked.chmod(0o700)


def test_a_pyc_outside_a_pycache_is_not_judged(tmp_path: Path) -> None:
    # The interpreter imports bytecode for `src/mod.py` from `src/__pycache__` alone. A `.pyc`
    # in any other directory is read against the source in that directory's parent, which is
    # not its source: here a stale header in `src/legacy/` would be charged to `src/mod.py`.
    # Oracle: `mutations/`'s "the stale-bytecode walk judges a .pyc outside __pycache__".
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    compiled = compile_module(module)
    make_stale(module)
    legacy = root / "src" / "legacy"
    legacy.mkdir()
    compiled.rename(legacy / compiled.name)
    assert (legacy / compiled.name).is_file()
    assert stale(root) == 0


def test_a_normally_compiled_pyc_is_not_stale(tmp_path: Path) -> None:
    """The everyday case, and what a naive `pyc mtime > source mtime` gets backwards."""
    # Oracle: `mutations/`'s "fresh bytecode is counted as stale".
    root = repo(tmp_path)
    # The `.pyc` must actually exist, or `stale == 0` passes by finding nothing to judge.
    assert compile_module(root / "src" / "mod.py").is_file()
    assert stale(root) == 0


def test_a_hash_based_pyc_is_not_judged(tmp_path: Path) -> None:
    """PEP 552 bytes 8-12 are the source mtime only while bit 0 of the flags word at bytes 4-8
    is clear. In a hash-based `.pyc` they are the first half of the source's hash, and comparing
    that fragment to an mtime reports every such file as stale forever — the FALSE-ALARM
    direction, which this module's whole design note says it avoids. It is not an exotic shape:
    `py_compile` switches to it on its own under `SOURCE_DATE_EPOCH`, and `compileall
    --invalidation-mode checked-hash` produces a tree of them.
    """
    # Oracle: `mutations/`'s "a hash-based .pyc is read as if it carried an mtime".
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    cache = module.parent / "__pycache__" / f"{module.stem}.{sys.implementation.cache_tag}.pyc"
    py_compile.compile(
        str(module),
        cfile=str(cache),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH,
    )
    # The file must exist, or `stale == 0` passes by finding nothing to judge — the same
    # vacuity `compile_module` was written to close.
    assert cache.is_file()
    assert stale(root) == 0


def test_a_source_mtime_past_2106_is_compared_the_way_cpython_compares_it(tmp_path: Path) -> None:
    """PEP 552's timestamp field is a uint32, so CPython masks the source mtime to 32 bits
    before writing it. Comparing the unmasked `int(st_mtime)` against that field reports a
    perfectly current `.pyc` as stale forever — the false-alarm direction again, reachable by
    a clock that ran forward, an archive unpacked with a bad timestamp, or the year 2106.

    Reddened by dropping `& _PYC_MTIME_MASK` from `_stale_bytecode`'s comparison; measured,
    and it reddened this test alone.

    Not in `mutations/`: the skip below is environmental — a filesystem that cannot store
    a post-2106 mtime clamps it — and a declared mutation whose named test can SKIP reports
    "caught" while proving nothing.
    """
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    beyond = 2**32 + 5
    os.utime(module, (beyond, beyond))
    if int(module.stat().st_mtime) != beyond:
        pytest.skip("this filesystem clamps a post-2106 mtime; the fault cannot be staged")
    # Compiled AFTER the mtime is set, so the header holds CPython's own masked value (5) and
    # the bytecode is genuinely current.
    assert compile_module(module).is_file()
    assert stale(root) == 0


def test_a_repeated_or_nested_code_root_is_walked_once(tmp_path: Path) -> None:
    """Every consumer of `contained_roots` walks each entry and adds up what it
    finds, so a repeated or nested entry double-counts. Measured before the pruning: with
    `code_roots = ["src", "src", "src/pkg"]` the one stale `.pyc` under `src/pkg` was reported
    three times and the one under `src` twice — `stale == 5` for two stale files, in a notice
    whose only job is to be believed about a number.

    Oracle: `mutations/`'s "a code root listed twice is walked twice". Measured both ways —
    deleting BOTH pruning lines gives `stale == 5`, and the declared single-line mutation (the
    `if any(_covers(...))` guard alone) still gives `stale == 3`, because the descendant
    rebuild below it happens to collapse the exact repeat while leaving the nested root. Each
    reddened this test alone.

    The `.pyc` count is asserted beside the root list deliberately: a de-duplicated list that
    nothing counted would be a shape claim, and the doubled COUNT is the defect.
    """
    root = repo(tmp_path)
    package = root / "src" / "pkg"
    package.mkdir()
    inner = package / "deep.py"
    inner.write_text("y = 1\n", encoding="utf-8")
    for module in (root / "src" / "mod.py", inner):
        compile_module(module)
    make_stale(root / "src" / "mod.py", inner)
    (root / CONFIG_FILE).write_text(
        CONFIG.replace('code_roots = ["src", "tests"]', 'code_roots = ["src", "src", "src/pkg"]'),
        encoding="utf-8",
    )
    assert contained_roots(root, config(root)) == [root / "src"]
    assert stale(root) == 2


def test_a_pyc_from_another_interpreter_is_not_judged(tmp_path: Path) -> None:
    """The sibling of the hash-based case, in the same false-alarm direction. A `__pycache__`
    accumulates one `.pyc` per interpreter tag and nothing removes the old ones, so a
    `mod.cpython-311.pyc` from an earlier run sits there forever recording the source mtime as
    of THAT run — while the bytecode this interpreter will actually import, compiled here and
    fresh, matches. Reading past the magic word counted the leftover and the notice then fired
    on every red run of a healthy tree. Measured before the magic check: `stale == 1`.
    """
    # Oracle: `mutations/`'s "a .pyc from another interpreter is read as this one's".
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    # The CURRENT tag's bytecode, fresh — so a non-zero count can only come from the leftover.
    assert compile_module(module).is_file()
    foreign = module.parent / "__pycache__" / f"{module.stem}.cpython-311.pyc"
    # Hand-assembled rather than compiled: only one interpreter is installed in this test run,
    # so the one header shape that matters here cannot be produced by asking `py_compile` for
    # it. A magic this interpreter never writes, a timestamp-based flags word, and a recorded
    # mtime deliberately unequal to the source's — the exact shape a stale leftover has.
    #
    # DERIVED from the running magic rather than written as some released version's literal,
    # and that is not laziness: CI runs this suite on every interpreter in `ci.yml`'s matrix, so
    # any literal naming one of them is the RUNNING interpreter's magic on that leg and the test
    # would then assert the opposite of what it means. The `!=` below is what the derivation has to
    # buy, so it is asserted rather than assumed.
    foreign_magic = bytes([importlib.util.MAGIC_NUMBER[0] ^ 0xFF]) + importlib.util.MAGIC_NUMBER[1:]
    assert len(foreign_magic) == 4
    assert foreign_magic != importlib.util.MAGIC_NUMBER
    foreign.write_bytes(
        foreign_magic
        + struct.pack("<I", 0)
        + struct.pack("<I", int(module.stat().st_mtime) - 10_000)
        + struct.pack("<I", 4)
    )
    assert stale(root) == 0


def test_a_pyc_that_is_a_symlink_is_not_followed(tmp_path: Path) -> None:
    """Bytecode is the interpreter's own output, a regular file. A `.pyc` that is a symlink was
    put there by whoever wrote the tree, and following it reads what it names: a file outside
    every code root, or `/dev/stdin`, which waits on a terminal for good. The link here names
    real bytecode outside the tree, stale against its source, so following it counts one more.

    Only the bytecode must be a regular file. A source that is a symlink is still compared,
    because the interpreter follows it too, and its stale bytecode is counted.
    """
    # Oracle: `mutations/`'s "a symlinked .pyc is followed" and "a source that is a symlink is not
    # compared".
    root = repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    module = root / "src" / "mod.py"
    compile_module(module)
    real = outside / "real.py"
    real.write_text("w = 1\n", encoding="utf-8")
    aliased = root / "src" / "aliased.py"
    aliased.symlink_to(real)
    compile_module(aliased)
    linked = root / "src" / "linked.py"
    linked.write_text("z = 1\n", encoding="utf-8")
    cache = compile_module(linked)
    target = outside / cache.name
    cache.rename(target)
    cache.symlink_to(target)
    make_stale(module, real, linked)
    assert stale(root) == 2


def test_a_symlinked_directory_under_a_code_root_is_never_entered(tmp_path: Path) -> None:
    # The walk enters no symlinked directory below a root, a `__pycache__` included, as
    # `rglob` entered none on 3.11 to 3.13: a link a tree commits can name a directory outside
    # every code root, or an ancestor, which walks the same entries again until the cap. Both
    # links here name stale bytecode outside the tree, so a walk that followed either counts it.
    # Oracle: `mutations/`'s "the stale-bytecode walk follows a symlinked directory".
    root = repo(tmp_path)
    outside = tmp_path / "outside"
    (outside / "pkg").mkdir(parents=True)
    module = outside / "pkg" / "mod.py"
    module.write_text("x = 1\n", encoding="utf-8")
    cache = compile_module(module)
    make_stale(module)
    (root / "src" / "pkg").symlink_to(outside / "pkg")
    (root / "src" / "other").mkdir()
    (root / "src" / "other" / "mod.py").symlink_to(module)
    (root / "src" / "other" / "__pycache__").symlink_to(cache.parent)
    assert stale(root) == 0


needs_mkfifo = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes")

# How long a walk over two files may take before the test calls it blocked. A correct walk takes
# milliseconds, so only a walk starved of the CPU for this long could pass it by accident; the
# number decides only how long a regression takes to fail.
PATIENCE_SECONDS = 10


def a_tree_with_a_piped_pyc(tmp_path: Path) -> tuple[Path, Path]:
    """A tree with one real stale `.pyc` and, beside it, a `.pyc` that is a named pipe whose
    source is stale too: counted, the pipe would make two."""
    root = repo(tmp_path)
    module = root / "src" / "mod.py"
    compile_module(module)
    piped = root / "src" / "piped.py"
    piped.write_text("p = 1\n", encoding="utf-8")
    pipe = module.parent / "__pycache__" / f"piped.{sys.implementation.cache_tag}.pyc"
    os.mkfifo(pipe)
    make_stale(module, piped)
    return root, pipe


@needs_mkfifo
def test_a_pyc_that_is_a_named_pipe_never_blocks_the_walk(tmp_path: Path) -> None:
    """Opening a named pipe for reading waits for a writer, so a `.pyc` that is one, like a
    committed symlink to `/dev/stdin`, hung the red-run walk for good. The walk opens
    without waiting.

    The walk runs in a thread so that a regression fails instead of hanging: when it is still
    running after `PATIENCE_SECONDS`, it is waiting on the pipe, and opening the write end
    without blocking, which succeeds once a reader waits, releases it.
    """
    # Oracle: `mutations/`'s "a .pyc that is a named pipe is opened waiting for a writer".
    root, pipe = a_tree_with_a_piped_pyc(tmp_path)
    counted: list[int] = []
    walker = threading.Thread(target=lambda: counted.append(stale(root)), daemon=True)
    walker.start()
    walker.join(PATIENCE_SECONDS)
    blocked = walker.is_alive()
    if blocked:
        os.close(os.open(pipe, os.O_WRONLY | os.O_NONBLOCK))
        walker.join()
    assert not blocked
    assert counted == [1]


@needs_mkfifo
def test_a_pyc_that_is_a_named_pipe_is_never_read(tmp_path: Path) -> None:
    """A pipe whose writer has already written a whole stale header reads like a `.pyc`, and
    without waiting: only the check that the opened file is a regular one keeps it out of the
    count. The test holds both ends itself (`O_RDWR`), so the header sits in the pipe."""
    # Oracle: `mutations/`'s "a .pyc that is not a regular file is read".
    root, pipe = a_tree_with_a_piped_pyc(tmp_path)
    writer = os.open(pipe, os.O_RDWR)
    try:
        os.write(writer, importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, 0, 0))
        assert stale(root) == 1
    finally:
        os.close(writer)


def test_only_contained_code_roots_are_scanned(tmp_path: Path) -> None:
    # `config.paths` leaves `ledger.code_roots` to its consumer; an escaping entry is
    # skipped rather than followed, and a missing one is skipped rather than raised on.
    # `outside` is CREATED, which is what makes the containment check load-bearing here: with
    # `contained()` removed, `root/../outside` is a real directory and would be walked, so the
    # assertion below fails. Without the directory the entry would be dropped by `is_dir()`
    # alone and the containment call could be deleted with the test still green.
    # Oracle: `mutations/`'s "an escaping code root is followed".
    root = repo(tmp_path)
    (root.parent / "outside").mkdir()
    (root / CONFIG_FILE).write_text(
        CONFIG.replace(
            'code_roots = ["src", "tests"]', 'code_roots = ["src", "../outside", "nope"]'
        ),
        encoding="utf-8",
    )
    assert contained_roots(root, config(root)) == [root / "src"]
    assert counted(root)["roots"] == 1


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        ".venv/bin/python -m pytest tests/x.py",
        "python3 -mpytest",
        "PYTHONPATH=src pytest",
        'PYTHONPATH="$WT/src" "$MAIN/.venv/bin/python" -m pytest',
        "FOO=1 BAR=2 pytest",
        "env pytest -q",
        "uv run pytest -q",
        "uv run --locked pytest -q",
        "uv run --python 3.11 pytest",
        "uv --quiet run -m pytest",
        "uv run --frobnicate pytest",
        "make lint && pytest",
        "py.test -q",
        "python -W error -m pytest",
        "poetry run pytest",
        "poetry run -- python3 -m pytest",
    ],
)
def test_a_real_pytest_invocation_is_recognised(command: str) -> None:
    # One reading with `prove`'s pytest adapter (`hygiene.pytest_command`). Oracle: `mutations/`'s
    # "the pytest command reads py.test as no pytest" and "the pytest command reads no `poetry
    # run`" redden the `py.test` and `poetry` shapes.
    assert runs_pytest(command)


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        'echo "run pytest later" > n.md',
        "grep -m pytest notes.txt",
        "cargo test",
        # The interpreter runs `script.py`, which is handed `-m pytest` as its own arguments.
        "python script.py -m pytest",
        "poetry install",
    ],
)
def test_a_mention_or_an_unrecognised_launcher_is_not_a_run(command: str) -> None:
    # Reddened by mutating `recognises` to answer
    # `_PYTEST in " ".join(argv)`, the substring test it exists to replace; measured.
    assert not runs_pytest(command)


def test_an_empty_command_is_not_a_run() -> None:
    # The scanner never hands an empty argv on, but the hint is a published shape a caller may
    # ask directly. Reddened by deleting `if not argv: return False` (`argv[0]` raises);
    # measured.
    assert HINT.recognises([]) is False


# Python's line, as the code before the move rendered it, captured from that code and pasted here,
# never derived from the code under test: a repository in Python must read exactly what it read
# before its advice moved into the profile.
STALE_TWO = (
    "2 .pyc file(s) whose recorded source mtime no longer matches their source, under the "
    "configured code roots -- the interpreter may be importing a build that predates a fix on "
    "disk, which fails DETERMINISTICALLY in the shape of the defect the test pins. Delete the "
    "`__pycache__` directories under those roots, then re-run before attributing anything."
)


def test_the_note_is_a_function_of_the_report() -> None:
    # `note` sees counts and nothing else, so no path, file name or command text a repository
    # authored can reach the line it renders. Pinned against the literal captured from the code
    # before the move. Reddened by changing `STALE`'s wording in
    # `src/stayfixed/profiles/python/hygiene.py`; measured. The second assertion is the silence:
    # a tree with nothing stale gets no Python line at all. Reddened by dropping `note`'s
    # `if not stale: return None`; measured.
    assert HINT.note({"stale": 2, "roots": 1}) == STALE_TWO
    assert HINT.note({"stale": 0, "roots": 3}) is None
