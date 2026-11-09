"""The guards on the one fixture `git`, and on there going on being only one of it.

Twenty-three modules each carried a copy, and the copies were protected by five different
subsets of the same precaution. Collapsing them is only half the repair: the other half is that
the twenty-fourth copy cannot be written without a test going red, which is what the walk at
the bottom of this file is for.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from tests.gitfixture import ENV_KEEP, env, git, needs_git, run_git

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# What points `git` at a repository other than the one it was handed. `drybag.runner` names
# the same seven as the set it drops, and its docstring says why each is there; this list is
# that one, and a variable added there belongs here too.
REDIRECTING = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
)

# The one `git` in the suite that this module does not run, named rather than skipped silently — for
# `tests/boundaries/test_api_surface.py`'s stated reason, that an exemption nobody can see is how
# the violation a guard exists to catch gets merged green. `tracked_files` asks the *real*
# repository which files it tracks, reads the answer as bytes because `-z` separates with NUL, and
# is the neutrality gate's own enumeration rather than a fixture being built.
HAND_ROLLED_EXEMPT = frozenset({("test_neutral.py", "tracked_files")})

# The shared fixture and the module you are reading, which are the two that may name the
# variables the rest of the suite must not spell for itself.
_THE_FIXTURE_AND_ITS_GUARD = frozenset({"gitfixture.py", "test_gitfixture.py"})


@needs_git
def test_a_fixture_repository_is_built_where_it_was_asked_although_git_dir_names_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The defect the sealed environment exists to close, and the reason it matters more here
    # than in `drybag.gitenv`: these calls are `init`, `add` and `commit`, so an inherited
    # `GIT_DIR` does not make a fixture read the wrong repository, it makes it *write* to one.
    # Under `pytest -p xdist` or a shell that exports `GIT_DIR`, that repository is whichever
    # one the developer is sitting in.
    #
    # Mutation (declared): `env()` returns `dict(os.environ)` -> `git init` reinitialises the
    # victim, the commit lands there, and both assertions below fail.
    victim = tmp_path / "victim"
    victim.mkdir()
    git(victim, "init", "-q", "-b", "main")
    monkeypatch.setenv("GIT_DIR", str(victim / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(victim))

    project = tmp_path / "project"
    project.mkdir()
    git(project, "init", "-q", "-b", "main")
    (project / "a.txt").write_text("a\n", encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "chore: seed")

    # The specific sentence and not "something went wrong": the commit is in the repository
    # that was named, under the forced identity, and the victim never got one.
    assert git(project, "log", "-1", "--format=%s").strip() == "chore: seed"
    assert git(project, "log", "-1", "--format=%ae").strip() == "t@example.com"
    assert run_git(victim, "rev-parse", "HEAD").returncode != 0


def test_the_sealed_environment_carries_nothing_that_could_redirect_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mutation (declared): the same one — `dict(os.environ)` carries all seven through.
    for name in REDIRECTING:
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    # Asserted present in the ambient environment before they are asserted absent from the
    # sealed one: a `REDIRECTING` that had been emptied, or a `monkeypatch` that stopped
    # setting anything, would satisfy the subtraction below having compared nothing.
    assert set(REDIRECTING) <= set(os.environ)

    sealed = env(tmp_path)
    assert set(REDIRECTING) & set(sealed) == set()
    # And the keep-list is an allowlist rather than a denylist, which is why adding an eighth
    # redirecting variable to git needs no edit here: nothing survives that is not named.
    assert set(sealed) - set(ENV_KEEP) == {
        "HOME",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_TERMINAL_PROMPT",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_CONFIG_KEY_1",
        "GIT_CONFIG_VALUE_1",
    }
    assert sealed["HOME"] == str(tmp_path)


@needs_git
def test_a_fixture_git_reads_no_configuration_file_the_machine_supplies(tmp_path: Path) -> None:
    # What "sealed" has to mean for a test whose answer depends on git's defaults: outside any
    # repository, the fixture's `git` reads no file at all. Apple's git reads a gitconfig inside
    # Xcode that `GIT_CONFIG_SYSTEM` does not replace, and it sets `init.defaultBranch = main`,
    # so an `init` without `-b` made `main` on a Mac and `master` on every CI runner, and a test
    # passed on the one and failed on the other. A Linux `/etc/gitconfig` that sets
    # `safe.directory = *`, as GitHub's Ubuntu image does, is the same shape.
    #
    # Mutation: `GIT_CONFIG_NOSYSTEM` dropped from `env()` -> red here with Apple's git, which
    # lists the Xcode file; with any other git it has no extra file to read, so the declared
    # entry for that line is the key set above, which reddens everywhere.
    #
    # What it does read is the environment's own: the two keys that turn automatic maintenance
    # off, from `GIT_CONFIG_COUNT`, which git lists as the command line's and never as a file's.
    listed = run_git(tmp_path, "config", "--list", "--show-origin")
    assert listed.stdout.splitlines() == [
        "command line:\tmaintenance.auto=false",
        "command line:\tgc.auto=0",
    ], listed.stdout


@needs_git
def test_a_fixture_commit_leaves_no_maintenance_running_behind_it(tmp_path: Path) -> None:
    # The flake this closes: from git 2.55 the maintenance a `commit` starts detaches and keeps
    # `objects/maintenance.lock` after the commit returns, so `shutil.rmtree(root / ".git")`
    # straight after `smoke_repo` listed the lock and then found it gone — `FileNotFoundError`
    # on the Python 3.12 leg of CI. Read from git's own trace, which names every program it
    # starts: a fixture commit starts no maintenance, and no `gc --auto` either.
    #
    # The same commit with automatic maintenance turned back on is the control, held in the
    # foreground so it leaves nothing running: it shows the trace names the spawn when there is
    # one, so the first assertion cannot pass because tracing stopped reaching the file.
    #
    # Mutation (declared): `env()` sets `GIT_CONFIG_COUNT` to "0" -> git reads none of the keys,
    # and the commit starts `git maintenance run --auto --detach` again.
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")

    def started(trace: Path, *config: str) -> list[str]:
        git(root, *config, "commit", "-q", "--allow-empty", "-m", "c", GIT_TRACE=str(trace))
        lines = trace.read_text(encoding="utf-8").splitlines()
        return [line for line in lines if "run_command:" in line]

    sealed = started(tmp_path / "sealed.trace")
    assert not [line for line in sealed if "maintenance" in line or " gc " in line], sealed
    in_the_foreground = ("-c", "maintenance.auto=true", "-c", "maintenance.autoDetach=false")
    control = started(tmp_path / "control.trace", *in_the_foreground)
    assert [line for line in control if "maintenance run --auto" in line], control


def _git_runs(tree: ast.AST) -> list[int]:
    """Every `…run(["git", …], …)` in this module, by line."""
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        first = node.args[0]
        if name != "run" or not isinstance(first, ast.List) or not first.elts:
            continue
        head = first.elts[0]
        if isinstance(head, ast.Constant) and head.value == "git":
            found.append(node.lineno)
    return found


def _enclosing(tree: ast.AST, line: int) -> str:
    """The innermost `def` a line sits in, so an exemption names a function and not a number."""
    best = ("<module>", -1)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.lineno <= line <= (node.end_lineno or node.lineno)
            and node.lineno > best[1]
        ):
            best = (node.name, node.lineno)
    return best[0]


def test_no_test_module_runs_a_git_of_its_own() -> None:
    # The durable half of the collapse. Twenty-three named helpers and six further inline call
    # sites each built the environment by hand, and nothing held any of them to any other — so
    # `os.devnull` had drifted to the literal `"/dev/null"` on twelve lines, four sites never
    # set `GIT_TERMINAL_PROMPT`, and three ran `git init` with no environment at all. A
    # twenty-fourth copy would have arrived the same way: unremarked.
    #
    # Mutation (declared): the walk is narrowed to `gitfixture.py`, which this module excludes
    # -> `modules` comes back empty and the floor below reddens, because a guard that stopped
    # walking reports no offences for the same reason a clean tree does.
    modules = sorted(p for p in TESTS.rglob("*.py") if p.name != "gitfixture.py")
    assert len(modules) >= 90, len(modules)
    offences: list[str] = []
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line in _git_runs(tree):
            where = (path.name, _enclosing(tree, line))
            if where not in HAND_ROLLED_EXEMPT:
                offences.append(f"{path.relative_to(ROOT)}:{line} runs git without gitfixture")
    assert not offences, "\n".join(offences)


def test_no_test_module_builds_a_git_environment_of_its_own() -> None:
    # The other spelling of the same defect, and the one that catches a hand-built environment
    # handed to something that is not `subprocess.run` — the two `env=` dictionaries that were
    # passed to a launcher rather than to git. String constants out of the AST rather than a
    # substring search, so the prose in `tests/snapshot.py` that *describes* the precaution is
    # not mistaken for a second copy of it. This module is excluded beside `gitfixture.py` and
    # for the same reason: the assertion above spells every forced name out, so that
    # dropping one from `gitfixture.env` reddens rather than passing quietly.
    #
    # No separate mutation: the walk is the one above's, and narrowing it reddens there first.
    modules = sorted(p for p in TESTS.rglob("*.py") if p.name not in _THE_FIXTURE_AND_ITS_GUARD)
    assert len(modules) >= 90, len(modules)
    named = {
        str(path.relative_to(ROOT))
        for path in modules
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and node.value in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM")
    }
    assert named == set(), named
