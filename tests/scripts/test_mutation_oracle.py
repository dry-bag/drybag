"""The oracle's own guards, which nothing exercised.

`scripts/mutation_oracle.py` is the mechanism this project's strongest test convention rests
on — "every new assertion ships with the mutation that reddens it" — and it had no tests of its
own, so the two states it could not tell apart were invisible by construction: a mutation whose
named tests do not exist read as *caught*, and a `git status` that could not answer read as a
*clean tree*. Both are proved here, against a real pytest run and a real repository.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from tests import gitfixture
from tests.declarations import (
    ANCHOR,
    SCRIPT,
    cited_names,
    declared,
    empty_anchors,
    needs_declarations,
    unread_citations,
    unread_names,
)
from tests.gitfixture import git as _git
from tests.gitfixture import needs_git
from tests.scriptload import load

REPOSITORY = Path(__file__).resolve().parents[2]


def oracle(root: Path | None = None) -> ModuleType:
    """A fresh copy of the script, loaded by path through `tests.scriptload.load`.

    `root` redirects the module's `ROOT`, which is where it runs pytest and asks `git` about
    the tree, and `DECLARATIONS`, the `mutations/` directory beneath it. Every test below points
    it at a throwaway directory, so nothing here mutates a file in this checkout or reads its git
    state.
    """
    module = load(SCRIPT, "mutation_oracle_under_test")
    if root is not None:
        # Through `__dict__`, not an attribute assignment: `ModuleType` types reads as
        # `Any` and writes as an error, and this one is deliberate.
        module.__dict__["ROOT"] = root
        # And the declarations under it, here rather than in each fixture: a fixture that forgot
        # would set `ROOT` alone, and `declared()` would read this checkout's real set against a
        # throwaway tree.
        module.__dict__["DECLARATIONS"] = root / "mutations"
        # And `TEMPDIR` beside it, for every test in this module rather than for the ones that
        # remember. `main` sweeps `TEMPDIR` for leaked scratch checkouts and deletes what it
        # finds, so with the real temporary directory in place each test that calls `main`
        # swept the developer's own — measured with a canary planted there, which the suite
        # removed — and would have destroyed a concurrently running oracle's checkout. The
        # scratch checkout and the bytecode cache are created under it too.
        #
        # A SIBLING of `root` and never `root` itself: the scratch checkout has to land outside
        # the repository it is a checkout of, which is the property
        # `test_the_working_tree_is_never_written_and_pytest_runs_in_the_scratch_checkout`
        # asserts — pointing it at `root` put the worktree inside the tree under test and
        # reddened that test, correctly.
        scratch = root.parent / f"{root.name}-oracle-tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        module.__dict__["TEMPDIR"] = scratch
    return module


def a_mutation(module: ModuleType, subject: Path, reddens: tuple[str, ...]) -> object:
    return module.Mutation(
        name="probe",
        file=subject,
        before="GUARD = True",
        after="GUARD = False",
        reddens=reddens,
    )


# --- the clean-tree run, which is what tells a proof from a typo -----------------------------
#
# `_check` mutates, runs the named tests, and reads "they did not pass" as "the mutation was
# caught". Without a clean-tree run first it cannot tell a red test from an absent one: a
# mistyped id makes pytest exit 4, 4 is not 0, and the oracle printed `caught` for a guard it
# had never tested. Measured before the fix, against this tree: `_check` returned `None`.


def test_a_test_id_that_does_not_exist_is_a_finding_not_a_catch(tmp_path: Path) -> None:
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    finding = module._check(
        a_mutation(module, subject, ("test_nothing.py::test_this_name_does_not_exist",)), tmp_path
    )
    assert finding is not None
    assert "did not pass on a clean tree" in finding
    # Untouched: the run stopped before the write, so a bad entry cannot even risk the restore.
    assert subject.read_text(encoding="utf-8") == "GUARD = True\n"


def test_a_run_where_every_named_test_skipped_proves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same hole wearing a different face, and one an environment produces rather than a
    # typo: this suite has nine environmental skips (no `git`, running as root, no interpreter
    # below the floor). A run of zero executed tests exits 0, so an exit code alone reads it as
    # a clean pass and banks the skip as a proof. Substituted at `_run`, the subprocess
    # boundary, because a skip that is reliably a skip on every CI leg is not something a test
    # can arrange honestly.
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    monkeypatch.setattr(
        module, "_run", lambda _targets, _cwd, **_kw: module.Outcome(code=0, executed=0)
    )
    finding = module._check(
        a_mutation(module, subject, ("test_x.py::test_skipped_here",)), tmp_path
    )
    assert finding is not None
    assert "0 test(s) ran" in finding


def test_a_real_guard_with_a_real_test_is_still_reported_caught(tmp_path: Path) -> None:
    # The refusals above prove the oracle can say no; this proves the no is not simply always.
    # A guard, a test that depends on it, and a mutation that breaks it, end to end through a
    # real pytest run in a throwaway tree.
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    (tmp_path / "test_subject.py").write_text(
        "import subject\n\n\ndef test_the_guard_holds() -> None:\n    assert subject.GUARD\n",
        encoding="utf-8",
    )
    caught = module._check(
        a_mutation(module, subject, ("test_subject.py::test_the_guard_holds",)), tmp_path
    )
    assert caught is None  # `None` is this function's word for "the mutation was caught"
    assert subject.read_text(encoding="utf-8") == "GUARD = True\n"


def test_a_mutation_that_breaks_collection_is_a_finding_and_not_a_catch(tmp_path: Path) -> None:
    """The clean run's own argument, applied to the mutated run.

    `_check` gates the clean run on `Outcome.passed` — `code == 0 and executed > 0` — with a
    long paragraph about why an exit code alone cannot tell a green assertion from an absent
    one. It then judged the *mutated* run by `mutated.code` alone, computing `mutated.executed`
    and throwing it away. A mutation that makes the module unimportable exits 2 from a
    collection error, 2 is not 0, and that read as `caught`.

    Measured before the fix, with this exact fixture::

        caught   probe
        all 1 mutations were caught

    exit 0 — for an entry whose named test never ran. The module's own sentence is "an oracle
    whose own failures look exactly like its successes is worse than no oracle", and this is
    the half of it that was left open in a file of 368 entries.

    Mutation (declared): the `mutated.executed == 0` test is removed -> this reddens.
    """
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    (tmp_path / "test_subject.py").write_text(
        "import subject\n\n\ndef test_the_guard_holds() -> None:\n    assert subject.GUARD\n",
        encoding="utf-8",
    )
    breaks_the_import = module.Mutation(
        name="probe",
        file=subject,
        before="GUARD = True",
        after="import a_module_that_does_not_exist\nGUARD = True",
        reddens=("test_subject.py::test_the_guard_holds",),
    )
    finding = module._check(breaks_the_import, tmp_path)
    assert finding is not None, "a collection error read as the guard being caught"
    assert "from running at all" in finding, finding
    # Both counts in the message, so a reader can tell this from a guard that legitimately
    # stops a parametrised case being generated.
    assert "1 test(s) ran on the clean tree, 0 with the mutation applied" in finding, finding
    assert subject.read_text(encoding="utf-8") == "GUARD = True\n"


@pytest.mark.parametrize(
    ("after", "crash"),
    [("    return NOT_IMPORTED", "NameError"), ("    return None.real", None)],
    ids=["name-error", "attribute-error"],
)
def test_a_mutation_that_raises_name_error_is_a_finding(
    tmp_path: Path, after: str, crash: str | None
) -> None:
    # Function-level imports turn an `after` that breaks a name into a test that ran and went
    # red, so `executed == 0` above cannot see it, and it read as caught: the test never reached
    # its assertion about the guard. An `AttributeError` stays a catch, which is the bound.
    # Mutation (declared): the crash check skipped -> the name-error case reads as caught.
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("def guard() -> bool:\n    return True\n", encoding="utf-8")
    (tmp_path / "test_subject.py").write_text(
        "import subject\n\n\ndef test_the_guard_holds() -> None:\n    assert subject.guard()\n",
        encoding="utf-8",
    )
    entry = module.Mutation(
        "probe", subject, "    return True", after, ("test_subject.py::test_the_guard_holds",)
    )
    finding = module._check(entry, tmp_path)
    assert finding is None if crash is None else f"crashed with {crash}" in str(finding), finding


def test_the_loader_aims_every_deletion_this_module_drives_at_its_own_scratch(
    tmp_path: Path,
) -> None:
    """The guard on the harness, because this module drives a function that deletes trees.

    `main` sweeps `TEMPDIR` for leaked scratch checkouts and removes what it finds. With the
    real temporary directory in place, every test here that calls `main` swept the developer's
    own — measured by planting a `drybag-oracle-canary` directory in it and running this
    module, which removed it — and a concurrently running oracle would have lost its checkout
    mid-run. A suite that can delete a developer's files is a defect whatever it is testing.

    A sibling of `root` and never `root` itself, because a scratch checkout of a repository
    must not land inside it.

    Mutation (declared): the `TEMPDIR` redirect is dropped from `oracle()` -> this reddens.
    """
    root = tmp_path / "repo"
    root.mkdir()
    module = oracle(root=root)
    aimed = Path(module.TEMPDIR)
    assert aimed != Path(tempfile.gettempdir()), aimed
    assert tmp_path in aimed.parents, aimed
    assert root not in aimed.parents and aimed != root, aimed
    # And the checkout really is made under it, rather than the name merely being set.
    assert Path(module.__dict__["ROOT"]) == root


@needs_git
def test_a_leaked_scratch_checkout_is_swept_where_git_worktree_prune_will_not_take_it(
    tmp_path: Path,
) -> None:
    """The leak, and the reason `prune` was never going to clear it.

    `scratch_checkout`'s docstring promised that an interrupted run "leaves nothing behind but
    a prunable entry, which the next `git worktree prune` clears". Both halves were false: the
    `mkdtemp` tree is still on disk, and `prune` only drops entries whose directory is *gone*.
    One such registration was live in the development repository at review time — 6.5 MB, and
    `git worktree prune --dry-run -v` printed nothing about it — pinning a commit against
    `git gc`.

    This builds a real repository, registers a leak under the real prefix, and asserts that
    `prune` declines it and the sweep takes it.

    Mutation (declared): the sweep's `worktree remove` is dropped -> the entry survives and
    this reddens.
    """

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return gitfixture.run_git(repository, *args)

    repository = tmp_path / "repo"
    repository.mkdir()
    git("init", "-q", "-b", "main")
    (repository / "a.txt").write_text("a\n", encoding="utf-8")
    git("add", "-A")
    git("-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "chore: one")

    module = oracle(root=repository)
    leaked = tmp_path / f"{module.SCRATCH_PREFIX}leaked-by-a-kill"
    tree = leaked / "tree"
    git("worktree", "add", "--detach", "--quiet", str(tree), "HEAD")
    assert tree.is_dir()
    # The premise, measured rather than assumed: prune leaves it exactly where it is.
    git("worktree", "prune")
    assert str(tree) in git("worktree", "list").stdout, "prune took it, so there is no leak"

    # `tempdir=tmp_path` explicitly, so this test states the containment it depends on rather
    # than inheriting it from the loader.
    dropped = module.sweep_stale_scratch(tempdir=tmp_path)
    assert str(leaked) in dropped, dropped
    assert str(tree) not in git("worktree", "list").stdout, git("worktree", "list").stdout
    assert not leaked.exists(), sorted(tmp_path.iterdir())

    # The orphaned-directory half, in the same scratch: a directory under the prefix that no
    # `git worktree` entry points at is swept too, because `_run`'s cache leaks the same way.
    orphan = tmp_path / f"{module.SCRATCH_PREFIX}cache-left-by-a-kill"
    orphan.mkdir()
    dropped = module.sweep_stale_scratch(tempdir=tmp_path)
    assert str(orphan) in dropped, dropped
    assert not orphan.exists()


def test_a_red_test_that_prints_an_undecodable_byte_is_still_reported_caught(
    tmp_path: Path,
) -> None:
    # Found by running this oracle over the entry for `project.detect`'s base-branch check: the
    # mutated test failed, as it should, and pytest's diff of the two strings wrote the
    # branch's latin-1 byte to its stdout raw. `_run` captured that stdout with `text=True`
    # and a strict decode, so the oracle itself died with `UnicodeDecodeError` on a mutation it
    # had caught, and every entry after it went unproven. Nothing reads the captured output —
    # the verdict is the exit code and the junit report — so it is no longer decoded at all.
    # Mutation (declared): put `text=True` back on `_run`'s pytest call -> this reddens.
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    (tmp_path / "test_subject.py").write_text(
        "import subject\n\n\ndef test_the_guard_holds() -> None:\n"
        '    assert ("main" if subject.GUARD else "caf\\udce9") == "main"\n',
        encoding="utf-8",
    )
    caught = module._check(
        a_mutation(module, subject, ("test_subject.py::test_the_guard_holds",)), tmp_path
    )
    assert caught is None


def test_a_collection_that_prints_an_undecodable_byte_still_warms_the_cache(
    tmp_path: Path,
) -> None:
    # The test above's defect, in the other pytest this module launches. `warm_cache` captured
    # its collection's output with `text=True` and a strict decode and forgives only a timeout,
    # so a conftest or a test module that wrote a byte no codec reads while being collected
    # raised `UnicodeDecodeError` out of the oracle before its first entry. Nothing reads that
    # output either — what the collection is for is the bytecode it leaves behind, which is
    # what the second assertion holds, so a collection that never ran cannot pass here.
    # Mutation (declared): put `text=True` back on `warm_cache`'s collection -> this reddens.
    module = oracle(root=tmp_path)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "conftest.py").write_text(
        'import os\n\n\ndef pytest_collection_finish(session):\n    os.write(1, b"caf\\xe9\\n")\n',
        encoding="utf-8",
    )
    (tree / "test_one.py").write_text("def test_one() -> None:\n    pass\n", encoding="utf-8")
    cache = module.warm_cache(tree)
    assert list(cache.rglob("conftest*.pyc")), sorted(cache.rglob("*"))


def test_a_mutation_nothing_notices_is_reported_as_surviving(tmp_path: Path) -> None:
    # And the finding the oracle exists to produce: the named test passes on a clean tree and
    # passes again with the guard broken. Without the clean-tree run this and the typo above
    # were told apart by nothing at all.
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    (tmp_path / "test_subject.py").write_text(
        "import subject\n\n\ndef test_the_guard_holds() -> None:\n"
        "    assert subject.GUARD in (True, False)\n",
        encoding="utf-8",
    )
    finding = module._check(
        a_mutation(module, subject, ("test_subject.py::test_the_guard_holds",)), tmp_path
    )
    assert finding is not None
    assert finding.startswith("survived")


# --- the dirty-tree guard, which must not stand down when `git` cannot answer ----------------
#
# The guard exists because this script writes source files and restores them from memory; its
# own comment says "refuse rather than risk it". It read any non-zero `git` exit as a clean
# tree — and `git status` exits 128 outside a repository, which is exactly what a tree that is
# not a checkout is and what a broken `git` produces.


@needs_git
def test_a_tree_git_cannot_answer_about_is_refused_not_assumed_clean(tmp_path: Path) -> None:
    module = oracle(root=tmp_path)  # not a repository: `git status` exits 128 here
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    refusal = module._uncommitted({subject})
    assert refusal is not None
    assert "could not answer" in refusal


@needs_git
def test_a_committed_tree_is_not_refused_and_a_dirty_one_still_is(tmp_path: Path) -> None:
    # The other side of the same guard. A refusal that fired on everything would be no guard
    # either — it would make the oracle unrunnable rather than fail-closed — and the original
    # behaviour it replaces has to survive intact.
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "init")
    assert module._uncommitted({subject}) is None
    subject.write_text("GUARD = False\n", encoding="utf-8")
    refusal = module._uncommitted({subject})
    assert refusal is not None
    assert "uncommitted changes" in refusal


def test_a_git_that_cannot_be_launched_is_refused_not_assumed_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A `git` that is absent rather than unhappy raises out of `subprocess.run` instead of
    # returning non-zero, so the exit-code arm above never sees it. Uncaught it is a traceback;
    # read as "clean" it is the same fail-open. Neither.
    module = oracle(root=tmp_path)

    def _absent(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("git")

    monkeypatch.setattr(module.subprocess, "run", _absent)
    refusal = module._uncommitted({tmp_path / "subject.py"})
    assert refusal is not None
    assert "could not be run" in refusal


# --- the scratch checkout, which is why the working tree is never written --------------------


def _repo_with_guard(root: Path) -> None:
    """A committed repository with one guard and one test that imports it.

    The test records the path it ran from into `ORACLE_PROBE`, which is how the outer test
    learns whether pytest was collected from the scratch checkout or from this repository.
    """
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "pkg" / "guard.py").write_text("GUARD = True\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_guard.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "from pkg.guard import GUARD\n"
        "\n"
        "\n"
        "def test_the_guard_holds() -> None:\n"
        "    Path(os.environ['ORACLE_PROBE']).write_text(__file__, encoding='utf-8')\n"
        "    assert GUARD\n",
        encoding="utf-8",
    )
    (root / "mutations").mkdir()
    (root / "mutations" / "repository.toml").write_text(
        "[[mutation]]\n"
        'name = "the guard is disarmed"\n'
        'file = "src/pkg/guard.py"\n'
        'before = "GUARD = True"\n'
        'after = "GUARD = False"\n'
        'reddens = ["tests/test_guard.py::test_the_guard_holds"]\n',
        encoding="utf-8",
    )
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "init")


@needs_git
def test_the_working_tree_is_never_written_and_pytest_runs_in_the_scratch_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The oracle proves HEAD and never the working tree. It used to rewrite `mutation.file` in
    # place and restore it from a string held in memory, so two runs at once interleaved writes
    # over one file. It now applies every mutation to a detached worktree of HEAD. Proved from
    # both sides: every byte of the repository is identical before and after, and the fixture
    # test reports that it was collected from somewhere that is not this repository.
    #
    # Mutation (declared): `_run`'s `cwd=cwd` back to `cwd=ROOT` -> pytest is collected from
    # the repository, the probe path lands under `tmp_path`, and the second assertion reddens.
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    module = oracle(root=root)
    probe = tmp_path / "probe.txt"
    monkeypatch.setenv("ORACLE_PROBE", str(probe))
    before = {path: path.read_bytes() for path in root.rglob("*.py")}
    assert before  # a walk-based assertion states its walk is non-empty: `{} == {}` passes
    assert module.main([]) == 0
    assert {path: path.read_bytes() for path in root.rglob("*.py")} == before
    ran_from = Path(probe.read_text(encoding="utf-8")).resolve()
    assert root.resolve() not in ran_from.parents, ran_from


@needs_git
def test_the_scratch_copy_wins_over_a_main_checkout_already_on_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The editable install of the real repository puts its `src/` on `sys.path` through
    # site-packages, so a scratch checkout whose `src/` is not put *first* runs the named tests
    # against the unmutated main modules and reports every mutation as surviving. Modelled by
    # putting the repository's own `src` on PYTHONPATH before the run: only a prepend of the
    # scratch `src` makes the mutated copy the one imported.
    #
    # Mutation (declared): drop the PYTHONPATH prepend in `_run` -> the mutation survives,
    # `main` returns 1, and the assertion reddens.
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    module = oracle(root=root)
    monkeypatch.setenv("ORACLE_PROBE", str(tmp_path / "probe.txt"))
    monkeypatch.setenv("PYTHONPATH", str(root / "src"))
    assert module.main([]) == 0


def _recommit(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        (root / relative).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "change")


@needs_git
def test_a_warm_bytecode_cache_never_stands_in_for_a_mutated_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The hazard the per-run empty cache used to answer, made certain rather than a matter of
    # timing. `warm_cache` compiles `guard.py` from HEAD before the entry runs, and the entry's
    # `after` is exactly as long as its `before`, so the mutated file differs from HEAD's in
    # content only: a `.pyc` is trusted on mtime-in-whole-seconds and size, and with the
    # mutated write left on HEAD's mtime the import system runs HEAD's bytecode, the guard
    # holds, and the entry reads as surviving. `_check`'s stamp is what tells them apart.
    #
    # Mutation (declared): the stamp pinned at 0, so the mutated write keeps HEAD's mtime ->
    # the entry survives, `main` returns 1, and this reddens.
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    _recommit(
        root,
        {
            "mutations/repository.toml": "[[mutation]]\n"
            'name = "the guard is disarmed, byte for byte as long"\n'
            'file = "src/pkg/guard.py"\n'
            'before = "GUARD = True"\n'
            'after = "GUARD = None"\n'
            'reddens = ["tests/test_guard.py::test_the_guard_holds"]\n',
        },
    )
    module = oracle(root=root)
    monkeypatch.setenv("ORACLE_PROBE", str(tmp_path / "probe.txt"))
    assert module.main([]) == 0


def test_a_mutated_file_that_does_not_keep_its_stamp_is_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The stamp is read back rather than assumed. A filesystem whose timestamps are coarser
    # than a second would round two stamps into one and bring the stale-bytecode hazard back
    # without a sound, so an mtime that did not take is a finding, not a run. Modelled by an
    # `os.utime` that does nothing, which is what such a filesystem looks like from here.
    #
    # Mutation (declared): the read-back is disabled -> the entry runs against a mutated file
    # carrying the clock's mtime, is caught, and the finding this asserts never appears.
    module = oracle(root=tmp_path)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    (tmp_path / "test_subject.py").write_text(
        "import subject\n\n\ndef test_the_guard_holds() -> None:\n    assert subject.GUARD\n",
        encoding="utf-8",
    )
    # HEAD's mtime far in the past, so the clock's own mtime on the mutated write cannot land
    # on HEAD's plus the stamp by coincidence — a clean run takes about a second, which is
    # exactly the first stamp.
    os.utime(subject, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(module.os, "utime", lambda *_args, **_kwargs: None)
    finding = module._check(
        a_mutation(module, subject, ("test_subject.py::test_the_guard_holds",)), tmp_path
    )
    assert finding is not None
    assert "did not keep the mtime it was given" in finding, finding
    assert subject.read_text(encoding="utf-8") == "GUARD = True\n"


@needs_git
def test_every_job_proves_its_entries_in_a_scratch_checkout_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two jobs sharing one checkout would interleave their mutations over one file and each
    # would run against the other's — the hazard the scratch checkout removes, moved inside the
    # oracle. Every pytest run appends the checkout it ran from; each run sleeps, so each job
    # is still busy with its first entry when the other takes the second, and two jobs must
    # show up as two checkouts, neither of them the repository.
    #
    # Mutation (declared): one checkout made however many jobs there are -> the jobs take
    # turns with it, one checkout is recorded, and the count reddens.
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    entry = (
        "[[mutation]]\n"
        'name = "{name}"\n'
        'file = "src/pkg/guard.py"\n'
        'before = "GUARD = True"\n'
        'after = "{after}"\n'
        'reddens = ["tests/test_guard.py::test_the_guard_holds"]\n'
    )
    _recommit(
        root,
        {
            "tests/test_guard.py": "import os\n"
            "import time\n"
            "from pathlib import Path\n"
            "\n"
            "from pkg.guard import GUARD\n"
            "\n"
            "\n"
            "def test_the_guard_holds() -> None:\n"
            "    with Path(os.environ['ORACLE_PROBE']).open('a', encoding='utf-8') as probe:\n"
            "        probe.write(__file__ + '\\n')\n"
            "    time.sleep(1)\n"
            "    assert GUARD\n",
            "mutations/repository.toml": entry.format(name="disarmed", after="GUARD = False")
            + "\n"
            + entry.format(name="emptied", after="GUARD = 0"),
        },
    )
    module = oracle(root=root)
    probe = tmp_path / "probe.txt"
    monkeypatch.setenv("ORACLE_PROBE", str(probe))
    assert module.main(["--jobs", "2"]) == 0
    ran_from = {Path(line).parents[1] for line in probe.read_text(encoding="utf-8").splitlines()}
    assert len(ran_from) == 2, ran_from
    assert all(root.resolve() not in tree.resolve().parents for tree in ran_from), ran_from


def test_every_run_keeps_its_temporary_files_to_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Several jobs run pytest at once, and pytest's default `--basetemp` is one directory per
    # user that every one of them prunes on exit; a neighbour's `tmp_path` is protected only by
    # a lock created just after it. On a four-job run one clean run of 1,138 failed with a test
    # that passes alone every time and only writes under `tmp_path`. Each run now gets a base
    # of its own, under this module's scratch, which is what the probe checks.
    #
    # Mutation (declared): the `--basetemp` argument dropped -> the test's `tmp_path` lands in
    # pytest's shared default and the containment assertion reddens.
    module = oracle(root=tmp_path)
    probe = tmp_path / "probe.txt"
    monkeypatch.setenv("ORACLE_PROBE", str(probe))
    (tmp_path / "test_where.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def test_where(tmp_path: Path) -> None:\n"
        "    Path(os.environ['ORACLE_PROBE']).write_text(str(tmp_path), encoding='utf-8')\n",
        encoding="utf-8",
    )
    assert module._run(("test_where.py::test_where",), tmp_path).passed
    where = Path(probe.read_text(encoding="utf-8")).resolve()
    assert Path(module.TEMPDIR).resolve() in where.parents, where


# How long a fixture pytest below holds its run open before it gives up and finishes. Never a
# verdict: the stop tests judge by whether the held run *finished* — it writes a marker when it
# does — and a stopped run never does, however long the stop took to arrive. Only a mutated run,
# whose stop does nothing, waits this out, so it is also what one of those costs the oracle.
HELD_RUN_SECONDS = 30
# A pytest that writes `ORACLE_HOLDING`, holds its run open until the release file named by
# `ORACLE_RELEASE` appears or `HELD_RUN_SECONDS` pass, and then writes `ORACLE_FINISHED`. On the
# first run only when `ORACLE_PROBE` is set: the terminate test's mutated run then waits once,
# not twice.
HELD = (
    "import os\n"
    "import time\n"
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def hold() -> None:\n"
    "    probe = os.environ.get('ORACLE_PROBE')\n"
    "    if probe is not None:\n"
    "        if Path(probe).exists():\n"
    "            return\n"
    "        Path(probe).write_text('ran', encoding='utf-8')\n"
    "    Path(os.environ['ORACLE_HOLDING']).write_text('holding', encoding='utf-8')\n"
    f"    deadline = time.monotonic() + {HELD_RUN_SECONDS}\n"
    "    while not Path(os.environ['ORACLE_RELEASE']).exists() and time.monotonic() < deadline:\n"
    "        time.sleep(0.05)\n"
    "    Path(os.environ['ORACLE_FINISHED']).write_text('finished', encoding='utf-8')\n"
)


def _held_run_markers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """The marker a held run writes once it holds, the release file it waits for, and the
    marker it writes once it finishes."""
    holding, release, finished = (tmp_path / name for name in ("holding", "release", "finished"))
    monkeypatch.setenv("ORACLE_HOLDING", str(holding))
    monkeypatch.setenv("ORACLE_RELEASE", str(release))
    monkeypatch.setenv("ORACLE_FINISHED", str(finished))
    return holding, release, finished


def _wait_until_holding(holding: Path) -> None:
    """Until the held run is inside its test, past pytest's own start. A precondition, not a
    verdict: a stop sent before then ends a run that had not reached the test at all, and proves
    nothing about one that had. The caller asserts the marker, so a run that never holds is
    reported as such, whatever the time it took."""
    deadline = time.monotonic() + 120
    while not holding.exists() and time.monotonic() < deadline:
        time.sleep(0.05)


def test_a_stop_ends_the_pytest_in_flight_and_starts_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A job's pytest runs in a worker thread, where no signal reaches it. Without `_stop_runs`
    # a terminate waited for every in-flight entry to finish both of its runs before the
    # checkouts could be removed — long enough for a process manager's grace period to end in
    # a `SIGKILL` that leaks them all. The sequential oracle never had this: `subprocess.run`
    # killed its child as the `SystemExit` passed through it.
    #
    # Judged by what the held run did, never by a clock: it writes its marker only if it ran to
    # its end, and a stopped run cannot. This used to be a ten-second join, which load can spend.
    #
    # Mutations (declared): the terminate dropped -> the held run waits out `HELD_RUN_SECONDS`,
    # finishes, and the marker assertion reddens; the refusal dropped -> the second `_run`
    # starts pytest, and `pytest.raises` reddens.
    module = oracle(root=tmp_path)
    holding, release, finished = _held_run_markers(tmp_path, monkeypatch)
    (tmp_path / "test_held.py").write_text(
        HELD + "\n\ndef test_held() -> None:\n    hold()\n\n\n"
        "def test_quick() -> None:\n    pass\n",
        encoding="utf-8",
    )
    waiting = threading.Thread(
        target=module._run, args=(("test_held.py::test_held",), tmp_path), daemon=True
    )
    waiting.start()
    try:
        _wait_until_holding(holding)
        assert holding.exists() and module._live, "the held run never started"
        module._stop_runs()
        # Bounded, as a precondition and not the verdict: the held run releases itself after
        # `HELD_RUN_SECONDS`, which bounds the pytest child and not `_run`, so a regression that
        # left `_run` blocked would otherwise hang the suite rather than fail this test.
        waiting.join(timeout=HELD_RUN_SECONDS + 60)
        assert not waiting.is_alive(), "the held run outlived its own release"
        assert not finished.exists(), "a stop let the pytest in flight run to its end"
        with pytest.raises(module.Stopped):
            module._run(("test_held.py::test_quick",), tmp_path)
    finally:
        release.write_text("", encoding="utf-8")


@needs_git
def test_a_terminate_mid_run_ends_the_pytest_in_flight_and_leaves_no_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The stop wiring end to end, which the test above does not reach: that one calls
    # `_stop_runs` itself, so `_prove`'s own arm could stop calling it and nothing would notice.
    # A real `SIGTERM`, sent once a job's pytest is running, becomes `SystemExit` in the main
    # thread; the arm must end that pytest — it holds its run open — and the checkouts must be
    # gone when `main` returns. A terminate that waited for the entry instead is the one a
    # process manager's grace period ends in a `SIGKILL`, leaking every checkout.
    #
    # Judged by what the held run did, never by a clock: it writes its marker only if it ran to
    # its end. This used to assert that `main` returned within twenty seconds, and at a load
    # average of 13 to 17 a clean run took 23.6.
    #
    # Mutation (declared): the arm stops calling `_stop_runs` -> the job waits out the held run,
    # which finishes, and the marker assertion reddens. The fixture holds its first run only, so
    # that mutated run costs one `HELD_RUN_SECONDS` rather than the clean run's and the mutated
    # run's both.
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    _recommit(
        root,
        {
            "tests/test_guard.py": HELD + "\n\nfrom pkg.guard import GUARD\n"
            "\n"
            "\n"
            "def test_the_guard_holds() -> None:\n"
            "    hold()\n"
            "    assert GUARD\n",
        },
    )
    module = oracle(root=root)
    monkeypatch.setenv("ORACLE_PROBE", str(tmp_path / "probe.txt"))
    holding, release, finished = _held_run_markers(tmp_path, monkeypatch)

    def terminate_once_pytest_runs() -> None:
        _wait_until_holding(holding)
        # Only while a run is live, which is only inside `scratch_checkout`, where the handler
        # that turns the signal into `SystemExit` is installed; outside it this would end the
        # test process.
        if module._live:
            os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=terminate_once_pytest_runs, daemon=True).start()
    try:
        with pytest.raises(SystemExit):
            module.main([])
    finally:
        release.write_text("", encoding="utf-8")
    assert holding.exists(), "the held run never started"
    assert not finished.exists(), "the terminate waited for the pytest in flight to finish"
    assert not module._live
    left = [
        path for path in Path(module.TEMPDIR).glob(f"{module.SCRATCH_PREFIX}*") if path.is_dir()
    ]
    assert left == [], left


@needs_git
def test_a_scratch_checkout_that_cannot_be_created_is_a_refusal_not_an_in_place_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No fallback to the old in-place behaviour: an oracle that silently mutated the working tree
    # because `git worktree add` failed would reintroduce the exact hazard the scratch checkout
    # removes. `subprocess.run` is wrapped so that only the worktree call fails; `git status` and
    # pytest are real.
    #
    # No mutation entry of its own: the in-place fallback is a code path this module no
    # longer has, so there is no line to substitute. Measured by hand instead — making
    # `scratch_checkout` yield `ROOT` on failure reddens the first assertion below with
    # `assert 0 == 1`, because the fallback run mutates the fixture repository in place, the
    # entry is caught there, and `main` returns 0. The later two assertions are not reached:
    # the first `assert` ends the test, which is why this says "the first" and not "both".
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    module = oracle(root=root)
    monkeypatch.setenv("ORACLE_PROBE", str(tmp_path / "probe.txt"))
    real_run = module.subprocess.run

    def _no_worktree(argv: list[str], *args: object, **kwargs: object) -> object:
        if "worktree" in argv:
            return subprocess.CompletedProcess(argv, 128, "", "fatal: no worktree today")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", _no_worktree)
    assert module.main([]) == 1
    assert "worktree" in capsys.readouterr().err
    assert (root / "src" / "pkg" / "guard.py").read_text(encoding="utf-8") == "GUARD = True\n"


@needs_git
def test_an_uncommitted_reddens_test_file_is_refused_like_an_uncommitted_source_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The dirty-tree guard's second arm, which the scratch checkout is what makes it necessary:
    # a HEAD checkout cannot see an uncommitted edit to a *test* any more than to a source, so
    # an entry whose `reddens` file is dirty would be proved against the committed test while
    # its author reads the result as being about the one on screen. `main` therefore sweeps the
    # `reddens` files as well as the mutated ones. Only the test file is dirty here.
    #
    # Mutation (declared): drop the `reddens` files from the set `main` sweeps -> the run is
    # not refused, `main` returns 0, and the first assertion reddens.
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    module = oracle(root=root)
    (root / "tests" / "test_guard.py").write_text(
        "def test_the_guard_holds() -> None:\n    pass\n", encoding="utf-8"
    )
    assert module.main([]) == 1
    assert "uncommitted changes" in capsys.readouterr().err


# --- one oracle at a time -----------------------------------------------------------------


def _a_reaped_pid() -> int:
    """A process id that has certainly exited: one this test started and waited for.

    Pid reuse between the `wait()` and the assertion is theoretically possible and fails in the
    safe direction — the lock would read as live, `main` would refuse, and the test would go red
    saying so rather than passing while measuring nothing.
    """
    finished = subprocess.Popen([sys.executable, "-c", ""])
    finished.wait()
    return finished.pid


@needs_git
def test_a_second_oracle_refuses_rather_than_sweeping_the_first_ones_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `sweep_stale_scratch` assumes a single writer: without the lock, a second run started
    # beside a first removes its checkout and turns every later mutation into a false FINDING.
    #
    # The assertion is the *checkout surviving*, not the exit code: a refusal that still swept
    # would exit 1 too, and exit 1 is what this oracle returns for a finding as well.
    #
    # Mutation (declared): `O_EXCL` drops out of the open -> the second run takes the lock, the
    # sweep runs, the planted checkout is gone and both assertions redden.
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    module = oracle(root=root)
    monkeypatch.setenv("ORACLE_PROBE", str(tmp_path / "probe.txt"))
    scratch = Path(module.TEMPDIR)
    lock = scratch / module.LOCK_NAME
    # This process is alive by construction, which is the whole of what the lock reads.
    lock.write_text(f"{os.getpid()} a run that is still going", encoding="utf-8")
    standing = scratch / f"{module.SCRATCH_PREFIX}first-run"
    standing.mkdir()

    assert module.main([]) == 1
    assert standing.is_dir(), "the second run swept the first run's scratch checkout"
    error = capsys.readouterr().err
    assert "another mutation oracle is running" in error
    # And it says which file to remove, because the other half of a lock is the way out of one.
    assert str(lock) in error


@needs_git
def test_a_lock_left_by_a_dead_process_is_taken_over_rather_than_obeyed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other direction, and it has to hold or the cure is worse than the disease: a `SIGKILL`
    # runs no `finally`, so a lock outliving its writer is the ordinary aftermath of an
    # interrupted run — and one that refused for ever would need a person with a shell before
    # the oracle could be run again.
    #
    # Mutation (declared): `_holder` reports every lock as held -> this run refuses instead of
    # taking the stale lock over, `main` returns 1 and the first assertion reddens.
    root = tmp_path / "repo"
    root.mkdir()
    _repo_with_guard(root)
    module = oracle(root=root)
    monkeypatch.setenv("ORACLE_PROBE", str(tmp_path / "probe.txt"))
    lock = Path(module.TEMPDIR) / module.LOCK_NAME
    lock.write_text(f"{_a_reaped_pid()} a run that is gone", encoding="utf-8")

    assert module.main([]) == 0
    # And the run that took it over released it, so the next one does not inherit a stale lock
    # from a process that exited cleanly.
    assert not lock.exists()


def test_the_housekeeping_sweep_leaves_the_lock_alone(tmp_path: Path) -> None:
    # The lock lives beside the scratch checkouts and shares their prefix, so the sweep's glob
    # finds it; what spares it is the `is_dir()` arm. That is an invariant between two functions
    # and nothing stated it — a sweep that took the lock with it would let the next run in while
    # the first was still working, which is the hazard with one more step in it.
    #
    # **`root` is a throwaway and not this checkout, and the first version of this test got that
    # wrong.** `sweep_stale_scratch` has two halves: the `tempdir` glob, which `tempdir=` aims
    # wherever a caller says, and a walk over `git worktree list` run in `ROOT`, which `tempdir=`
    # does not scope at all. With `ROOT` left at the real repository, the second half removed
    # every registered `drybag-oracle-*/tree` — including the live checkout of the oracle
    # running this very test. It passed locally, where no oracle was running, and CI reported
    # `0 test(s) ran` on the clean tree: this test destroyed the run that was executing it, which
    # is precisely the hazard the lock it is testing exists to prevent. The loader above states
    # the rule — every test here points `ROOT` at a throwaway directory — and a sweep is the one
    # function in this module where breaking it is not merely untidy.
    #
    # A plain directory and not a repository: `_git` runs with `check=False`, so the worktree
    # half finds nothing and the `tempdir` half — the half this test is about — is what runs.
    #
    # Mutation (declared): the `is_dir()` arm drops out of the sweep -> the lock is reported
    # dropped and the last two assertions redden.
    root = tmp_path / "elsewhere"
    root.mkdir()
    module = oracle(root=root)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    lock = scratch / module.LOCK_NAME
    lock.write_text("1 a live run", encoding="utf-8")
    leaked = scratch / f"{module.SCRATCH_PREFIX}leaked"
    leaked.mkdir()

    dropped = module.sweep_stale_scratch(tempdir=scratch)
    # The walk states it found something before anything is asserted about what it spared: a
    # sweep that stopped sweeping spares the lock too, and would pass the two lines below.
    assert str(leaked) in dropped, dropped
    assert str(lock) not in dropped, dropped
    assert lock.is_file()


# --- the declaration itself, checked before any run -------------------------------------------
#
# `static_findings` is what the oracle's `main` asks first and what the suite asks of the real
# declaration: every entry anchored exactly once, every `reddens` id a test, no mutation declared
# twice. It needs no pytest run but one collection, for the parametrized ids.


def test_a_before_line_must_occur_exactly_once(tmp_path: Path) -> None:
    # Mutation (declared): the duplicate arm stops firing -> the second assertion reddens.
    module = oracle(root=tmp_path)
    assert module.anchor_finding("GUARD = True\n", "GUARD = True") is None
    duplicated = module.anchor_finding("GUARD = True\nGUARD = True\n", "GUARD = True")
    assert duplicated is not None and "2 times" in duplicated, duplicated
    drifted = module.anchor_finding("GUARD = False\n", "GUARD = True")
    assert drifted is not None and "drifted apart" in drifted, drifted


def test_a_reddens_id_must_name_a_test_its_file_defines(tmp_path: Path) -> None:
    # Mutations (declared): the name lookup accepts any name -> `test_member` is found for
    # `test_renamed`, and a class's first method for `test_gone`, so both stop being reported;
    # the collected-id lookup dropped -> `test_param[absent]` stops being reported.
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_probe.py").write_text(
        "import pytest\n\n\ndef test_kept():\n    pass\n\n\n"
        "class TestGroup:\n    def test_member(self):\n        pass\n\n\n"
        '@pytest.mark.parametrize("x", [1], ids=["one"])\ndef test_param(x):\n    pass\n',
        encoding="utf-8",
    )
    module = oracle(root=tmp_path)
    ids = (
        "tests/test_probe.py::test_kept",
        "tests/test_probe.py::TestGroup::test_member",
        "tests/test_probe.py::test_param[one]",
        "tests/test_probe.py::test_renamed",
        "tests/test_probe.py::TestGroup::test_gone",
        "tests/test_probe.py::test_param[absent]",
        "tests/test_absent.py::test_kept",
        "tests/test_probe.py",
    )
    assert module.undefined_tests(ids, tmp_path) == [
        "tests/test_probe.py::test_renamed",
        "tests/test_probe.py::TestGroup::test_gone",
        "tests/test_probe.py::test_param[absent]",
        "tests/test_absent.py::test_kept",
        "tests/test_probe.py",
    ]


def test_a_mutation_declared_twice_is_a_finding(tmp_path: Path) -> None:
    # Mutation (declared): the repeat rule dropped -> the list below comes out empty.
    subject = tmp_path / "guard.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    module = oracle(root=tmp_path)
    first = a_mutation(module, subject, ())
    second = module.Mutation(
        name="again", file=subject, before="GUARD = True", after="GUARD = False", reddens=()
    )
    assert module.static_findings([first, second]) == ["again: repeats the mutation of 'probe'"]


def test_an_entry_anchored_on_a_rewritten_action_pin_is_a_finding(tmp_path: Path) -> None:
    # Dependabot rewrites every action pin under `.github/workflows/` (`.github/dependabot.yml`),
    # so an entry whose `before` quotes one stops occurring at the next bump and turns that pull
    # request's every leg red, whatever the bump changed. The same pin quoted in a file Dependabot
    # does not read, or a `before` naming the action without its revision, is no finding.
    # Mutation (declared): the pin rule dropped -> the list below comes out empty.
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    pinned = "      - uses: actions/checkout@" + "a" * 40 + " # v7\n"
    (workflows / "ci.yml").write_text(pinned + "        with:\n", encoding="utf-8")
    elsewhere = tmp_path / "scan.yml"
    elsewhere.write_text(pinned, encoding="utf-8")
    module = oracle(root=tmp_path)

    def entry(name: str, file: Path, before: str) -> object:
        return module.Mutation(name=name, file=file, before=before, after="", reddens=())

    assert module.static_findings(
        [
            entry("quotes the pin", workflows / "ci.yml", pinned),
            entry("names the action", workflows / "ci.yml", "        with:\n"),
            entry("outside the workflows", elsewhere, pinned),
        ]
    ) == [
        "quotes the pin: its `before` quotes an action pin Dependabot rewrites; anchor it on the "
        "step's other lines"
    ]


@needs_declarations
def test_every_declared_entry_is_sound_before_any_run() -> None:
    """`static_findings` over the real `mutations/` finds nothing.

    No entry names this case, and none may: every mutation removes its own `before` line, so
    this case would redden under all of them and prove nothing about any. Its guard is the
    helpers above, whose entries are declared; it was watched red by duplicating one entry's
    `before` line in its file and by renaming one `reddens` test.
    """
    module = oracle()
    declared = module.declared()
    # The walk first: an empty declaration would make the list below come out empty for a
    # reason that is not about drift.
    assert len(declared) > 400, len(declared)
    assert module.static_findings(declared) == []


def test_an_entry_name_declared_twice_is_a_finding(tmp_path: Path) -> None:
    # A comment cites an entry by its name alone, so a second entry under one name makes every
    # citation of it ambiguous. Mutation (declared): the name rule dropped -> the list below comes
    # out empty.
    subject = tmp_path / "guard.py"
    subject.write_text("GUARD = True\nOTHER = True\n", encoding="utf-8")
    module = oracle(root=tmp_path)
    first = a_mutation(module, subject, ())
    second = module.Mutation(
        name="probe", file=subject, before="OTHER = True", after="OTHER = False", reddens=()
    )
    assert module.static_findings([first, second]) == [
        "probe: another entry is declared under this name"
    ]


def test_an_entry_with_no_reddens_is_refused(tmp_path: Path) -> None:
    # pytest handed no ids runs the whole suite, and any red test anywhere then read as a catch.
    # Mutation (declared): the empty check removed -> `declared()` returns the entry.
    (tmp_path / "mutations").mkdir()
    (tmp_path / "mutations" / "core.toml").write_text(
        '[[mutation]]\nname = "proves nothing"\nfile = "a.py"\nbefore = "a"\nafter = "b"\n'
        "reddens = []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="proves nothing"):
        oracle(root=tmp_path).declared()


def test_a_hung_entry_is_a_finding_not_a_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A mutation that removes a bound hung its pytest until CI cancelled the job. A machine too
    # loaded to start pytest in 2 s times out too, which is the outcome asserted.
    # Mutation (declared): the timeout dropped from `communicate` -> both runs wait out the sleep.
    module = oracle(root=tmp_path)
    monkeypatch.setattr(module, "ENTRY_TIMEOUT_SECONDS", 2)
    subject = tmp_path / "subject.py"
    subject.write_text("GUARD = True\n", encoding="utf-8")
    (tmp_path / "test_subject.py").write_text(
        "import time\n\nimport subject\n\n\ndef test_the_guard_holds() -> None:\n"
        "    time.sleep(5)\n    assert subject.GUARD\n",
        encoding="utf-8",
    )
    finding = module._check(
        a_mutation(module, subject, ("test_subject.py::test_the_guard_holds",)), tmp_path
    )
    assert finding is not None and "timed out after 2 s" in finding, finding
    assert not module._live


# --- citations: a comment names an entry, and the name must reach one ----------------------------
#
# CONTRIBUTING makes the entry's quoted name the one way a comment anywhere in the tree cites it,
# so that a regroup of `mutations/` leaves every comment true. That holds only while every cited
# name is declared: a renamed entry otherwise leaves its citations pointing at nothing, and the
# release runbook was found pointing at such a name with the whole suite green.


def test_a_citation_is_read_across_comment_lines_and_through_a_list() -> None:
    # Mutations (declared): `_WRAP` matches nothing -> the wrapped name keeps its `#` and this
    # reddens; `_FURTHER` is never tried -> the second name of the list is lost and this reddens;
    # `_GAP` reads whitespace alone -> the name after a line-ending anchor is lost.
    text = (
        f'# as {ANCHOR} "the first\n'
        '#   wrapped one" and "the second", and also\n'
        f'   {ANCHOR} "a third" in a document, beside "a quote that is no citation".\n'
        f"# and, wrapped after the set, {ANCHOR}\n"
        '# "a fourth".\n'
    )
    assert cited_names(text) == ["the first wrapped one", "the second", "a third", "a fourth"]


def test_a_citation_reads_every_name_of_an_arrow_list_and_no_quote_past_its_lines() -> None:
    # The tree's commonest citation says what each mutation does: `"a" -> x; "b" -> y`. Only the
    # first name was read, so a later one could be renamed away with every test green, and one
    # was: a comment went on citing an entry a refactor had removed. What an arrow says ends at
    # the citation's own lines, so a quote in the code under a comment, or past a blank line in a
    # document, is never read as a name. Mutations (declared): `mutations/`'s "the citation parser
    # loses the names an arrow list carries after the first" -> only the first name of each list
    # is read; "the citation parser reads an arrow past the citation's own lines" -> `"remote"`
    # and `"x"` are read as names.
    text = (
        f'    # Mutations: {ANCHOR} "the first" -> the `a`\n'
        '    # case; "the second" -> `b`, and "the third" -> `c`, "the fourth"\n'
        '    # and "the fifth" -> the rest.\n'
        f'    # And {ANCHOR} "a sixth" -> the case\n'
        '    run_git(root, "remote", "add")\n'
        f'{ANCHOR} "a seventh" -> nothing more\n\nsaid, "x" here.\n'
    )
    assert cited_names(text) == [
        "the first",
        "the second",
        "the third",
        "the fourth",
        "the fifth",
        "a sixth",
        "a seventh",
    ]


@needs_git
@pytest.mark.skipif(not (REPOSITORY / ".git").exists(), reason="no git checkout to ask")
def test_every_cited_entry_name_is_declared() -> None:
    """Every citation of an entry in a tracked file outside `docs/plans/` names a declared entry.

    `docs/plans/` is left out because the delivered plans are a record (CONTRIBUTING.md, "Plans"):
    each cites the entries as they were named when it was written. Mutation (declared): an entry a
    comment cites is renamed -> its citations name nothing and this reddens.
    """
    names = {" ".join(mutation.name.split()) for mutation in declared()}
    cited: list[tuple[str, str]] = []
    for path in _git(REPOSITORY, "ls-files", "-z").split("\0"):
        source = REPOSITORY / path
        if not path or path.startswith("docs/plans/") or not source.is_file():
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        cited.extend((path, name) for name in cited_names(text))
    # A walk-based assertion states its walk is non-empty: a parser that read nothing passes.
    assert len(cited) > 100, len(cited)
    assert [(path, name) for path, name in cited if name not in names] == []


def test_a_citation_spelled_another_way_is_told_apart_from_the_one_the_reader_reads() -> None:
    # A citation through a comma rather than `'s` read as one to a person and as nothing to
    # `cited_names`, and four of the tree's 138 named no entry: three shortened with an ellipsis,
    # one renamed away; a quote straight after a lead, singular or plural, names no set. Mutations
    # (declared): `mutations/`'s "the citation spelling rule lets a comma or a colon through" -> no
    # line is told; "the citation spelling rule reads no further than the set's own line" -> the
    # third is not; "the citation spelling rule misses a quote straight after a plural lead" -> the
    # last is not.
    set_name = ANCHOR.removesuffix("'s")
    quote = '"'  # so that no line of this file is the shape the rule refuses
    text = (
        f'# Mutation: {set_name}, "one".\n'
        f'# Mutation ({set_name}: "two").\n'
        f"# Mutations: {set_name},\n"
        '#   "three".\n'
        f'# Mutation: {ANCHOR} "four"; {set_name} holds the rest.\n'
        f"# Mutation (oracle): {quote}five{quote}, and (by hand) the lead alone.\n"
        f"# Mutations (oracle): {quote}six{quote} and {quote}seven{quote}.\n"
    )
    assert unread_citations(text) == [1, 2, 3, 6, 7]


def test_a_quoted_entry_name_the_citation_reader_does_not_read_is_told() -> None:
    # The reader read the first name of each of these and stopped, or read none, so a later name
    # could be renamed away with every test green; 292 quoted names in 71 files were read by
    # nothing. Every quote of a declared name must be one the reader reads. Mutations (declared):
    # `mutations/`'s "a quoted entry name the citation reader skips is never told" -> every case
    # but the read one reddens; "a quoted entry name that wraps is never told" -> the wrapped one
    # is not told; "the citation walk reads an entry's own name line as a citation" -> the
    # declaration is told too.
    names = {"a", "b", "c", "a wrapped one"}
    plants = {
        "a quote after an arrow": f'# {ANCHOR} "a" -> "x"; "b" -> y.\n',
        "prose between names": f'# {ANCHOR} "a" for the first, and "b" for the rest.\n',
        "a bulleted list": f'# {ANCHOR}\n# - "a"\n# - "b"\n',
        "an arrow joined by a bare and": f'# {ANCHOR} "a" -> drops x and "b" -> drops y.\n',
        "a name in parentheses": f'# {ANCHOR} "a" -> x; and dropping it ("b", "c") passes.\n',
        "no anchor": '# held by "a" and "a wrapped\n# one".\n',
        "read": f'# {ANCHOR} "a" -> x; "b" -> y, and "a wrapped\n# one" or "c".\n',
        "a declaration": 'name = "a"\n# but "b" is cited.\n',
    }
    assert {case: unread_names(text, names) for case, text in plants.items()} == {
        "a quote after an arrow": [(1, "b")],
        "prose between names": [(1, "b")],
        "a bulleted list": [(2, "a"), (3, "b")],
        "an arrow joined by a bare and": [(1, "b")],
        "a name in parentheses": [(1, "b"), (1, "c")],
        "no anchor": [(1, "a"), (1, "a wrapped one")],
        "read": [],
        "a declaration": [(2, "b")],
    }


def test_an_anchor_that_reads_no_name_is_told() -> None:
    # A list set out under the anchor, or prose after it, reads no name at all, so the anchor
    # vouches for nothing. Mutation (declared): `mutations/`'s "an anchor that reads no name is
    # never told" -> this reddens.
    text = f'# {ANCHOR}\n# - "a"\n# {ANCHOR} "b".\n# and {ANCHOR} the rest, in prose.\n'
    assert empty_anchors(text) == [1, 4]


@needs_git
@pytest.mark.skipif(not (REPOSITORY / ".git").exists(), reason="no git checkout to ask")
def test_every_citation_is_spelled_the_way_the_citation_reader_reads() -> None:
    # The walk `test_every_cited_entry_name_is_declared` makes, asking the other question: a
    # citation it cannot read is one whose name nothing checks. That is a citation spelled another
    # way, a quote of a declared name the reader does not read, and an anchor that reads no name.
    names = {" ".join(mutation.name.split()) for mutation in declared()}
    unread: list[tuple[str, int]] = []
    unread_quotes: list[tuple[str, int, str]] = []
    empty: list[tuple[str, int]] = []
    walked = 0
    for path in _git(REPOSITORY, "ls-files", "-z").split("\0"):
        source = REPOSITORY / path
        if not path or path.startswith("docs/plans/") or not source.is_file():
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        walked += 1
        unread.extend((path, line) for line in unread_citations(text))
        unread_quotes.extend((path, line, name) for line, name in unread_names(text, names))
        empty.extend((path, line) for line in empty_anchors(text))
    assert walked > 300, walked  # a walk-based assertion states its walk is non-empty
    assert unread == []
    assert unread_quotes == []
    assert empty == []


# --- the declarations directory, one file per group ------------------------------------------
#
# `mutations/` holds the set as one file per group of the tree, because a single file outgrew the
# plugin directory's per-file limit. Two properties keep the split honest: the oracle reads every
# file, and every entry sits in the file its `file` routes to. No size cap holds a group file: the
# plugin's tree (`scripts/plugin_tree.py`) no longer holds `mutations/`, so neither of the limits
# the groups were sized for reaches them (CONTRIBUTING.md, "Tests").


@needs_declarations
def test_the_oracle_reads_every_group_file() -> None:
    # Mutation (declared): `declared()` reads only the first group file (`[:1]` on the sorted
    # glob) -> the count comes out at the first file's entries and the second assertion reddens.
    module = oracle()
    files = module.group_files()
    expected = sum(len(tomllib.loads(f.read_text("utf-8"))["mutation"]) for f in files)
    assert {f.stem for f in files} == {group for _, group in module.GROUP_OF}
    assert len(module.declared()) == expected


@needs_declarations
def test_every_entry_lives_in_its_group_file() -> None:
    # Mutation (declared): `GROUP_OF` loses its `src/drybag/doctor/` row -> every `doctor`
    # entry routes to the package's catch-all group instead, and the first of them, still in the
    # file its old row named, reddens this.
    module = oracle()
    files = module.group_files()
    assert files  # a walk-based assertion states its walk is non-empty
    for path in files:
        for entry in tomllib.loads(path.read_text("utf-8"))["mutation"]:
            assert module.group_for(entry["file"]) == path.stem, (path.name, entry["name"])


def test_a_row_routes_its_files_wherever_it_stands_in_the_table() -> None:
    # `GROUP_OF` once took the first prefix that matched, so a row appended after
    # `src/drybag/` was dead without a sound: its files went on routing to `core`. Mutation
    # (declared): `group_for` takes the first match again -> the appended row routes nothing and
    # this reddens.
    module = oracle()
    module.__dict__["GROUP_OF"] = (*module.GROUP_OF, ("src/drybag/newarea/", "newarea"))
    assert module.group_for("src/drybag/newarea/x.py") == "newarea"
    assert module.group_for("src/drybag/fsops.py") == "core"
    assert module.group_for("README.md") == "repository"
    assert module.group_for(".github/workflows/ci.yml") == "tooling"


def test_no_prefix_is_routed_twice() -> None:
    # Longest-prefix matching makes the order meaningless only while each prefix has one row: a
    # repeated prefix would route to whichever `max` met first. Mutation: none of the code's; the
    # subject is the table, watched red by appending a second `("src/drybag/", "records")` row.
    prefixes = [prefix for prefix, _ in oracle().GROUP_OF]
    assert len(prefixes) == len(set(prefixes)), prefixes
