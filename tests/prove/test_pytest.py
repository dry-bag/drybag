"""The pytest adapter: what it recognises, how it plans a run, what it refuses, and what a real
pytest run under it proves.

The plan tests run no runner: `plan` is a pure function of its arguments and of the files it reads,
so each builds the files a virtual environment holds (a `bin/python` linked to the interpreter
running the suite, a `pytest` script) and reads the plan. A few run a stand-in for pytest through
`prove`, a script that writes a green report where it is told to. The tests marked `runners` run
the real pytest of the project's own environment in a scratch project
(`tests/prove/real_runners.py`), each through `prove` with the adapters this stayfixed ships.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from stayfixed.hints.api import read_launch
from stayfixed.profiles.python.adapters import (
    ADAPTERS,
    DISCOVERY,
    FORGING,
    NAME,
    REPORT_NAME,
    PytestAdapter,
    optimises,
)
from stayfixed.profiles.runners import (
    ENTRY_NOT_FOUND,
    REFUSED_OPTION,
    Plan,
    Refused,
    ReportKind,
    ReportSource,
    Unresolved,
)
from stayfixed.prove.counts import Counts
from stayfixed.prove.run import (
    ASSIGNED_FORGING,
    FAILING,
    NO_REPORT,
    NONE_RAN,
    Receipt,
    Verdict,
    line,
    prove,
)
from tests.gitfixture import git
from tests.prove.projects import pytest_project
from tests.prove.real_runners import needs_runner, runner_directory
from tests.prove.test_run import standard_input

PROVED, FAILED, NOT_PROVEN, REFUSED = (
    Verdict.PROVED,
    Verdict.FAILED,
    Verdict.NOT_PROVEN,
    Verdict.REFUSED,
)


def executable(path: Path, text: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def interpreter(path: Path) -> Path:
    """A `python` at `path` the way a virtual environment holds one: a link to the interpreter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(sys.executable)
    return path


def environment(root: Path) -> Path:
    """A virtual environment's `bin`: its `python`, and a `pytest` script naming it."""
    bin_ = root / "bin"
    python = interpreter(bin_ / "python")
    executable(bin_ / "pytest", f"#!{python}\nimport sys\n")
    return bin_


# A stand-in for pytest, or for a launcher in front of it: it records the words it was run with in
# `argv.json` in the directory it runs in, writes a green JUnit report where `--junitxml=` says,
# and exits 0.
_STAND_IN = (
    "import json, sys\n"
    "json.dump(sys.argv[1:], open('argv.json', 'w'))\n"
    "for word in sys.argv:\n"
    "    if word.startswith('--junitxml='):\n"
    "        report = open(word.split('=', 1)[1], 'w')\n"
    "        report.write('<testsuite><testcase name=\"a\"/></testsuite>')\n"
)


def stand_in(path: Path) -> Path:
    return executable(path, f"#!{sys.executable}\n{_STAND_IN}")


def planned(
    command: Sequence[str],
    cwd: Path,
    *,
    path: str = "",
    launch: Sequence[str] = (),
) -> Plan | Refused | Unresolved:
    return PytestAdapter().plan(
        launch, command, cwd=cwd, scratch=cwd / "scratch", environ={"PATH": path}
    )


def argv_of(command: Sequence[str], cwd: Path, **given: object) -> tuple[str, ...]:
    got = planned(command, cwd, **given)  # type: ignore[arg-type]
    assert isinstance(got, Plan), got
    return got.argv


def ours(cwd: Path) -> tuple[str, ...]:
    """The report options the adapter adds, last, for a run planned in `cwd`."""
    return (f"--junitxml={cwd / 'scratch' / REPORT_NAME}", "-o", "junit_family=xunit2")


# --- What is recognised ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        ["pytest"],
        ["py.test", "-q"],
        [".venv/bin/pytest", "tests"],
        ["python", "-m", "pytest"],
        ["python3.13", "-mpytest", "-q"],
        [".venv/bin/python", "-W", "error", "-Xdev", "-B", "-m", "pytest"],
        ["poetry", "run", "pytest", "-q"],
        ["poetry", "run", "--", "python", "-m", "pytest"],
        ["poetry", "run", "py.test"],
        # What `prove` hands an adapter of `uv run --locked pytest`, the launcher read past.
        list(
            read_launch(("uv", "run", "--locked", "pytest", "-q"), ADAPTERS[0].recognises).command
        ),
        list(read_launch(("uv", "run", "python", "-m", "pytest"), ADAPTERS[0].recognises).command),
        list(read_launch(("uv", "run", "-m", "pytest"), ADAPTERS[0].recognises).command),
    ],
)
def test_python_m_pytest_poetry_run_and_uv_run_are_recognised(command: list[str]) -> None:
    # Mutation (declared): `poetry run` not read through -> the three `poetry` shapes are not.
    assert PytestAdapter().recognises(command)


@pytest.mark.parametrize(
    "command",
    [
        # The interpreter runs `script.py` and hands it `-m pytest`; `-c` runs its own text.
        ["python", "script.py", "-m", "pytest"],
        ["python", "-c", "pass", "-m", "pytest"],
        ["python", "-m", "pytest_cov"],
        ["python"],
        ["grep", "-m", "pytest", "notes.txt"],
        ["poetry", "install"],
        ["poetry", "run", "black"],
        ["poetry", "run"],
        ["pytest-watch"],
        [],
    ],
)
def test_a_command_that_runs_no_pytest_is_not_recognised(command: list[str]) -> None:
    # Mutation (declared): the interpreter's words before `-m` read as its options whatever they
    # are -> `python script.py -m pytest` is planned as a pytest run, which runs no `script.py`.
    assert not PytestAdapter().recognises(command)


def test_the_adapters_this_stack_ships() -> None:
    assert [adapter.name for adapter in ADAPTERS] == [NAME] == ["pytest"]
    assert PytestAdapter().forging == FORGING == {"PYTHONOPTIMIZE": optimises}


@pytest.mark.parametrize(
    ("value", "optimised"),
    [
        ("1", True),
        ("2", True),
        ("abc", True),
        ("-1", True),
        ("0 ", True),
        ("0_0", True),
        (" ", True),
        ("", False),
        ("0", False),
        # Another spelling of zero is read as optimising, the safe side.
        ("00", True),
    ],
)
def test_pythonoptimize_optimises_unless_empty_or_zero(value: str, optimised: bool) -> None:
    # Mutations (declared): `0` read as optimising -> it is refused; the empty value read as one
    # -> it is refused.
    assert optimises(value) is optimised


# --- How a run is planned -------------------------------------------------------------------


def test_the_plan_runs_the_command_as_typed_with_a_report_of_its_own(tmp_path: Path) -> None:
    # The console script runs, by the path it is found on, never the interpreter its first line
    # names: what runs is what the command selects, and the receipt names its realpath.
    bin_ = environment(tmp_path / "venv")
    got = planned(["pytest", "-q", "tests"], tmp_path, path=str(bin_))
    report = tmp_path / "scratch" / REPORT_NAME
    assert got == Plan(
        argv=(
            str(bin_ / "pytest"),
            "-q",
            "tests",
            f"--junitxml={report}",
            "-o",
            "junit_family=xunit2",
        ),
        kind=ReportKind.JUNIT,
        source=ReportSource.FILE,
        report=report,
        discovery=(
            "conftest.py",
            "**/conftest.py",
            "test_*.py",
            "**/test_*.py",
            "*_test.py",
            "**/*_test.py",
        ),
    )
    assert got.discovery == DISCOVERY


@pytest.mark.parametrize(
    "words",
    [
        ("-m", "pytest", "-q"),
        ("-mpytest", "-q"),
        ("-W", "error", "-Xdev", "-B", "-m", "pytest", "-q"),
    ],
    ids=["spaced", "fused", "options"],
)
def test_python_m_pytest_is_planned_as_typed(tmp_path: Path, words: tuple[str, ...]) -> None:
    # The typed words and the report's options, and nothing else: no `-c` text in place of `-m`,
    # no `-P`, nothing that moves the run directory on the import path, so the run imports the
    # same copy of the project the command does.
    bin_ = environment(tmp_path / "venv")
    got = argv_of(["python", *words], tmp_path, path=str(bin_))
    assert got == (str(bin_ / "python"), *words, *ours(tmp_path))


def test_a_file_on_path_that_cannot_be_executed_is_passed_over(tmp_path: Path) -> None:
    # As the run's own lookup passes it over. Mutation (declared): any file taken -> the first.
    (tmp_path / "first").mkdir()
    (tmp_path / "first" / "python").write_text("", encoding="utf-8")
    bin_ = environment(tmp_path / "venv")
    path = os.pathsep.join([str(tmp_path / "first"), str(bin_)])
    assert argv_of(["python", "-m", "pytest"], tmp_path, path=path)[0] == str(bin_ / "python")


def test_a_command_it_does_not_recognise_has_no_plan(tmp_path: Path) -> None:
    # The core asks `plan` only of a command `recognises` took; asked anyway, nothing resolves.
    assert planned(["make", "test"], tmp_path) == Unresolved(ENTRY_NOT_FOUND)


def test_a_path_is_read_from_the_directory_the_command_is_typed_in(tmp_path: Path) -> None:
    # A relative `PATH` entry and a relative program are where the command runs, and the plan's
    # program is absolute, as the core requires.
    environment(tmp_path / ".venv")
    assert argv_of([".venv/bin/pytest"], tmp_path)[0] == str(tmp_path / ".venv" / "bin" / "pytest")
    assert argv_of(["python", "-m", "pytest"], tmp_path, path=".venv/bin")[0] == str(
        tmp_path / ".venv" / "bin" / "python"
    )


def test_the_report_options_go_before_a_separator(tmp_path: Path) -> None:
    # pytest reads every word after `--` as a path to collect, its options included.
    # Mutation (declared): the report's options added after `--` -> they follow it.
    bin_ = environment(tmp_path / "venv")
    got = argv_of(["pytest", "-q", "--", "tests"], tmp_path, path=str(bin_))
    assert got[1:] == ("-q", *ours(tmp_path), "--", "tests")


@pytest.mark.parametrize(
    ("launch", "command"),
    [
        (("uv", "run", "--locked"), ("pytest", "-q")),
        (("uv", "run"), ("python3", "-m", "pytest", "-q")),
        (("uv", "run", "-m"), ("pytest", "-q")),
        (("uv", "run", "--project", "../other", "--env-file", ".env"), ("pytest", "-q")),
        ((), ("poetry", "run", "pytest", "-q")),
        ((), ("poetry", "run", "--", "py.test", "-q")),
        (("uv", "run"), ("poetry", "run", "pytest", "-q")),
    ],
)
def test_a_launcher_is_kept_in_front_as_typed(
    tmp_path: Path, launch: tuple[str, ...], command: tuple[str, ...]
) -> None:
    # Under `uv run` or `poetry run` the run is the launcher, which chooses the interpreter, with
    # every word after it as typed: the program is the launcher's realpath, which the bound
    # concedes. Mutation (declared): `poetry run` not read through -> the `poetry` cases are no
    # plan.
    tools = tmp_path / "tools"
    launcher = executable(tools / ("uv" if launch else "poetry"))
    got = argv_of(command, tmp_path, path=str(tools), launch=launch)
    assert got == (str(launcher), *launch[1:], *command[1 if not launch else 0 :], *ours(tmp_path))


@pytest.mark.parametrize(
    ("command", "launch", "detail"),
    [
        (["pytest"], (), "no pytest on PATH"),
        (["python", "-m", "pytest"], (), "no python on PATH"),
        (["poetry", "run", "pytest"], (), "no poetry on PATH"),
        (["pytest"], ("uv", "run"), "no uv on PATH"),
        ([".venv/bin/pytest"], (), "no executable file at .venv/bin/pytest"),
    ],
)
def test_an_entry_point_not_on_path_does_not_resolve(
    tmp_path: Path, command: list[str], launch: tuple[str, ...], detail: str
) -> None:
    # The detail says what was looked for, and how: a word holding a `/` is never looked up on
    # `PATH` (`programs.not_found`). Mutation: none -- the detail is wording.
    assert planned(command, tmp_path, path=str(tmp_path / "empty"), launch=launch) == Unresolved(
        ENTRY_NOT_FOUND, detail
    )


# --- What is refused ------------------------------------------------------------------------


REFUSALS = [
    (("--setup-plan",), "--setup-plan"),
    (("--setup-only",), "--setup-only"),
    (("--setup-plan=x",), "--setup-plan"),
    # The undashed aliases pytest registers, which run as the dashed forms do.
    (("--setupplan",), "--setupplan"),
    (("--setuponly",), "--setuponly"),
    # `--trace` under a standard input that ends reports a failing test as passed, exit 0.
    (("--trace",), "--trace"),
]


@pytest.mark.parametrize(
    ("argv", "named"), REFUSALS, ids=[" ".join(argv).replace(" ", "_") for argv, _ in REFUSALS]
)
def test_each_option_that_reports_unrun_tests_as_passed_is_refused(
    tmp_path: Path, argv: tuple[str, ...], named: str
) -> None:
    # Refused before anything is resolved: no `PATH` holds a pytest here. Mutation (declared):
    # `--setup-plan` left off the list -> its case is planned, and `--setup-plan` reports a failing
    # test as passed.
    assert planned(["pytest", *argv], tmp_path) == Refused(REFUSED_OPTION, named)


# The interpreter's own options that turn `assert` off: a failing test then passes, and the run
# exits 0 with a green report.
OPTIMIZING = [
    (("python", "-O", "-m", "pytest"), "-O"),
    (("python3", "-OO", "-m", "pytest", "-q"), "-OO"),
    (("python", "-bO", "-mpytest"), "-bO"),
    (("python", "-W", "error", "-BO", "-m", "pytest"), "-BO"),
    (("poetry", "run", "python", "-O", "-m", "pytest"), "-O"),
]


@pytest.mark.parametrize(
    ("command", "named"), OPTIMIZING, ids=["_".join(command) for command, _ in OPTIMIZING]
)
def test_an_interpreter_option_that_turns_asserts_off_is_refused(
    tmp_path: Path, command: tuple[str, ...], named: str
) -> None:
    # Refused before anything is resolved. Mutation (declared): the interpreter's options not
    # read -> each is planned, and `python -O -m pytest` reports a failing test as passed.
    assert planned(command, tmp_path) == Refused(REFUSED_OPTION, named)


@pytest.mark.parametrize(
    "options",
    [("-W", "-O"), ("-WO",), ("-X", "O"), ("-XO",), ("-B", "-W", "ignore")],
    ids=["W_-O", "-WO", "X_O", "-XO", "B_W_ignore"],
)
def test_a_warning_filter_or_x_option_is_no_optimization(
    tmp_path: Path, options: tuple[str, ...]
) -> None:
    # `-W` and `-X` take a value, fused or as the next word, and an `O` in it is no flag.
    bin_ = environment(tmp_path / "venv")
    got = planned(["python", *options, "-m", "pytest"], tmp_path, path=str(bin_))
    assert isinstance(got, Plan)


def test_launched_under_uv_an_optimizing_option_is_refused(tmp_path: Path) -> None:
    got = planned(["python", "-O", "-m", "pytest"], tmp_path, launch=("uv", "run"))
    assert got == Refused(REFUSED_OPTION, "-O")


FREE = [
    # The report options the command spells itself: the adapter's own come last and win.
    ("--junitxml=reports/junit.xml",),
    ("--junit-xml", "x"),
    ("-o", "junit_family=xunit1"),
    ("-o", "junit_suite_name=x"),
    ("-o", "addopts="),
    ("--override-ini=addopts=--co",),
    # What writes no report, or runs no test, ends `not proven` or `failed` by itself.
    ("-p", "no:junitxml"),
    ("--collect-only",),
    ("--co",),
    ("--collectonly",),
    ("@args.txt",),
    ("-c", "ci.ini"),
    ("-p", "no:cacheprovider"),
    ("-k", "junit_x"),
    # After `--` a word is a path to collect.
    ("--", "--setup-plan"),
    ("--", "--trace"),
]


@pytest.mark.parametrize("argv", FREE, ids=["_".join(argv) or "none" for argv in FREE])
def test_every_other_option_is_planned_as_typed(tmp_path: Path, argv: tuple[str, ...]) -> None:
    bin_ = environment(tmp_path / "venv")
    got = argv_of(["pytest", *argv], tmp_path, path=str(bin_))
    if "--" in argv:
        cut = argv.index("--")
        assert got == (str(bin_ / "pytest"), *argv[:cut], *ours(tmp_path), *argv[cut:])
    else:
        assert got == (str(bin_ / "pytest"), *argv, *ours(tmp_path))


def _proved_here(argv: Sequence[str], cwd: Path, environ: Mapping[str, str]) -> Receipt:
    return prove(argv, cwd=cwd, environ=environ, timeout=600)


def test_a_refused_option_is_named_on_the_receipt(tmp_path: Path) -> None:
    # Through `prove` and the adapters this stayfixed ships. Mutation (declared, `core`): the
    # adapter's detail left off the receipt -> `detail` is empty.
    got = _proved_here(["pytest", "--setup-plan"], tmp_path, {"PATH": ""})
    assert (got.verdict, got.reason, got.detail, got.runner) == (
        REFUSED,
        REFUSED_OPTION,
        "--setup-plan",
        NAME,
    )
    assert line(got) == (
        "refused: the runner's adapter refuses this command (refused-option): '--setup-plan'; "
        "runner pytest"
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["PYTHONOPTIMIZE=1", "pytest"],
        ["env", "PYTHONOPTIMIZE=1", "uv", "run", "-m", "pytest"],
    ],
)
def test_an_assigned_pythonoptimize_is_refused(tmp_path: Path, argv: list[str]) -> None:
    got = _proved_here(argv, tmp_path, {"PATH": ""})
    assert (got.verdict, got.reason, got.detail) == (REFUSED, ASSIGNED_FORGING, "PYTHONOPTIMIZE")


@pytest.mark.parametrize("value", ["0", ""])
def test_an_assigned_pythonoptimize_that_optimises_nothing_runs(tmp_path: Path, value: str) -> None:
    # Level 0 runs every `assert`: the run goes ahead, here to a `pytest` on no `PATH` entry.
    got = _proved_here([f"PYTHONOPTIMIZE={value}", "pytest"], tmp_path, {"PATH": ""})
    assert (got.verdict, got.reason) == (NOT_PROVEN, ENTRY_NOT_FOUND)


@pytest.mark.parametrize(
    "argv", [["pytest", "-q"], ["PYTEST_ADDOPTS=-x", "pytest", "-q"]], ids=["bare", "assigned"]
)
def test_the_pytest_on_the_path_the_command_assigns_is_the_one_that_runs(
    tmp_path: Path, argv: list[str]
) -> None:
    # As a shell finds it: a `PATH` the command assigns is searched, never the caller's alone, and
    # `PYTEST_ADDOPTS` is the project's to set. Mutations (declared, `core`): the command's
    # assignments left out of the run's environment, or the plan made in stayfixed's own -> the
    # `pytest` that runs is another one.
    pytest_ = stand_in(tmp_path / "tools" / "pytest")
    elsewhere = stand_in(tmp_path / "elsewhere" / "pytest")
    got = _proved_here([f"PATH={pytest_.parent}", *argv], tmp_path, {"PATH": str(elsewhere.parent)})
    assert (got.verdict, got.runner, got.program) == (PROVED, NAME, os.path.realpath(pytest_))


def test_uv_run_m_pytest_runs_as_typed(tmp_path: Path) -> None:
    # Read as the launcher `uv run -m` in front of `pytest`, and run as it was typed.
    uv = stand_in(tmp_path / "tools" / "uv")
    got = _proved_here(["uv", "run", "-m", "pytest", "-q"], tmp_path, {"PATH": str(uv.parent)})
    assert (got.verdict, got.runner, got.program) == (PROVED, NAME, os.path.realpath(uv))
    words = json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))
    assert words[:4] == ["run", "-m", "pytest", "-q"]
    assert words[4].startswith("--junitxml=")
    assert words[5:] == ["-o", "junit_family=xunit2"]


# --- Real pytest runs -----------------------------------------------------------------------


def real(cwd: Path, *argv: str, **variables: str) -> Receipt:
    """`argv` proved in `cwd` with the project's own pytest first on `PATH`. Its entry-point
    plugins are not loaded, so the suite's own (coverage, workers) never join the run."""
    environ = {
        **os.environ,
        "PATH": os.pathsep.join([str(runner_directory("pytest")), os.environ.get("PATH", "")]),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        **variables,
    }
    return _proved_here(argv, cwd, environ)


@needs_runner("pytest")
def test_python_m_pytest_is_proved(tmp_path: Path) -> None:
    got = real(pytest_project(tmp_path / "p", passing=2), "python", "-m", "pytest", "-q")
    assert (got.verdict, got.reason, got.counts, got.exit_code) == (PROVED, "", Counts(2, 0, 0), 0)


@needs_runner("pytest")
def test_python_m_pytest_counts_a_failing_test(tmp_path: Path) -> None:
    got = real(pytest_project(tmp_path / "p", passing=1, failing=1), "python", "-m", "pytest")
    assert (got.verdict, got.reason, got.counts) == (FAILED, FAILING, Counts(1, 1, 0))


# A project whose tests import its own package from the directory the command runs in, which
# `python -m pytest` puts on the import path and the console script does not.
_OWN_PACKAGE = {
    "mypkg/__init__.py": "X = 1\n",
    "tests/test_own.py": "import mypkg\n\ndef test_own():\n    assert mypkg.X == 1\n",
}


@needs_runner("pytest")
def test_python_m_pytest_imports_the_project_s_own_package_from_the_run_directory(
    tmp_path: Path,
) -> None:
    # Run as typed, `python -m pytest` puts the run directory first on the import path and the
    # project's own package imports, and `pytest -q` stays the console script's run, which never
    # had it. No test file at the root, which pytest would put on the import path itself.
    project = tmp_path / "p"
    for name, text in {"pytest.ini": "[pytest]\n", **_OWN_PACKAGE}.items():
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        (project / name).write_text(text, encoding="utf-8")
    got = real(project, "python", "-m", "pytest", "-q")
    assert (got.verdict, got.reason, got.counts, got.exit_code) == (PROVED, "", Counts(1, 0, 0), 0)
    assert real(project, "pytest", "-q").verdict == FAILED


@needs_runner("pytest")
@pytest.mark.parametrize(("asserted", "verdict"), [(99, PROVED), (2, FAILED)])
def test_python_m_pytest_tests_the_copy_of_the_project_the_command_tests(
    tmp_path: Path, asserted: int, verdict: Verdict
) -> None:
    # The project is installed as well (here a directory on `PYTHONPATH` holding `VERSION = 2`) and
    # the tree holds `VERSION = 99`: `python -m pytest` imports the tree's, and so does the run
    # `prove` makes, whose verdict is the command's own exit code read. Mutation (declared): the
    # interpreter's words replaced by a bootstrap that moves the run directory after the installed
    # copy -> the case asserting 2 is `proved`, the one asserting 99 `failed`.
    project = tmp_path / "p"
    files = {
        "pytest.ini": "[pytest]\n",
        "mypkg/__init__.py": "VERSION = 99\n",
        "tests/test_version.py": (
            f"import mypkg\n\ndef test_v():\n    assert mypkg.VERSION == {asserted}\n"
        ),
    }
    for name, text in files.items():
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        (project / name).write_text(text, encoding="utf-8")
    installed = tmp_path / "site" / "mypkg" / "__init__.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("VERSION = 2\n", encoding="utf-8")
    got = real(project, "python", "-m", "pytest", "-q", PYTHONPATH=str(installed.parent.parent))
    assert got.verdict == verdict
    environ = {**os.environ, "PYTHONPATH": str(installed.parent.parent)}
    environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    typed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=project,
        env=environ,
        capture_output=True,
        check=False,
    )
    assert (typed.returncode == 0) == (verdict == PROVED)


@needs_runner("pytest")
def test_a_failing_assert_is_not_turned_off(tmp_path: Path) -> None:
    # Under `-O` or `PYTHONOPTIMIZE` the interpreter compiles out every `assert` pytest does not
    # rewrite, a helper module's among them: the failing test is reported passed and the run exits
    # 0. The option and the assignment are refused; an inherited `PYTHONOPTIMIZE` is removed from
    # the run's environment. Mutation (declared): `PYTHONOPTIMIZE` left out of the forging set ->
    # the inherited one turns the assert off, `proved`.
    project = pytest_project(
        tmp_path / "p",
        files={
            "checks.py": "def check(a, b):\n    assert a == b\n",
            "test_checks.py": "from checks import check\n\ndef test_check():\n    check(1, 2)\n",
        },
    )
    got = real(project, "python", "-O", "-m", "pytest", "-q")
    assert (got.verdict, got.reason, got.detail) == (REFUSED, REFUSED_OPTION, "-O")
    got = real(project, "PYTHONOPTIMIZE=1", "pytest", "-q")
    assert (got.verdict, got.reason, got.detail) == (REFUSED, ASSIGNED_FORGING, "PYTHONOPTIMIZE")
    got = real(project, "pytest", "-q", PYTHONOPTIMIZE="1")
    assert (got.verdict, got.reason, got.counts) == (FAILED, FAILING, Counts(0, 1, 0))
    assert got.scrubbed == ("PYTHONOPTIMIZE",)
    # Level 0 asserts as no optimisation does: kept, and the failing assert fails.
    got = real(project, "pytest", "-q", PYTHONOPTIMIZE="0")
    assert (got.verdict, got.reason, got.scrubbed) == (FAILED, FAILING, ())


@needs_runner("pytest")
def test_an_inherited_pytest_addopts_is_the_project_s(tmp_path: Path) -> None:
    # It reaches the run, as it reaches the command: here it selects no test, so the run fails.
    project = pytest_project(tmp_path / "p", passing=2)
    got = real(project, "pytest", "-q", PYTEST_ADDOPTS="-k nothing")
    assert (got.verdict, got.reason, got.counts) == (FAILED, NONE_RAN, Counts(0, 0, 0))


@needs_runner("pytest")
@pytest.mark.parametrize(
    ("words", "variables"),
    [
        (("--junitxml=elsewhere.xml", "-o", "junit_family=xunit1"), {}),
        (("-o", "addopts=--junitxml=elsewhere.xml"), {}),
        ((), {"PYTEST_ADDOPTS": "--junitxml=elsewhere.xml"}),
    ],
    ids=["typed", "override-ini", "addopts-variable"],
)
def test_the_adapter_s_report_options_win_over_the_command_s(
    tmp_path: Path, words: tuple[str, ...], variables: dict[str, str]
) -> None:
    # Measured on pytest 9.1.1: the options pytest reads last win, and the adapter's come last.
    project = pytest_project(tmp_path / "p", passing=1, failing=1)
    got = real(project, "pytest", "-q", *words, **variables)
    assert (got.verdict, got.reason, got.counts) == (FAILED, FAILING, Counts(1, 1, 0))
    assert not (project / "elsewhere.xml").exists()


@needs_runner("pytest")
@pytest.mark.parametrize(
    ("words", "verdict", "reason"),
    [
        (("-p", "no:junitxml"), NOT_PROVEN, NO_REPORT),
        (("--collect-only",), FAILED, NONE_RAN),
        (("--co",), FAILED, NONE_RAN),
        (("--collectonly",), FAILED, NONE_RAN),
    ],
    ids=["no-junitxml", "collect-only", "co", "collectonly"],
)
def test_a_run_that_writes_no_report_or_runs_no_test_is_never_proved(
    tmp_path: Path, words: tuple[str, ...], verdict: Verdict, reason: str
) -> None:
    # Free, and needing no refusal: the cascade reads no report as `not proven` and a report of no
    # test as `failed`.
    project = pytest_project(tmp_path / "p", passing=1, failing=1)
    got = real(project, "pytest", "-q", *words)
    assert (got.verdict, got.reason) == (verdict, reason)


@needs_runner("pytest")
def test_an_argument_file_is_read_as_typed(tmp_path: Path) -> None:
    # pytest reads the words of `@args.txt` as its own: here a selection of one test.
    project = pytest_project(
        tmp_path / "p", passing=1, failing=1, files={"args.txt": "-k\ntest_pass_0\n"}
    )
    got = real(project, "pytest", "-q", "@args.txt")
    assert (got.verdict, got.counts) == (PROVED, Counts(1, 0, 0))


@needs_runner("pytest")
def test_pythonpath_src_is_the_projects(tmp_path: Path) -> None:
    project = pytest_project(
        tmp_path / "p",
        files={
            "src/under_test/__init__.py": "VALUE = 1\n",
            "test_import.py": "from under_test import VALUE\n\ndef test_v():\n    assert VALUE\n",
        },
    )
    assert real(project, "PYTHONPATH=src", "pytest", "-q").verdict == PROVED
    assert real(project, "pytest", "-q").verdict == FAILED


@needs_runner("pytest")
def test_pythonwarnings_error_keeps_its_meaning(tmp_path: Path) -> None:
    # Every `PYTHON*` variable but `PYTHONOPTIMIZE` is the project's, as the command's.
    project = pytest_project(
        tmp_path / "p",
        files={"test_warns.py": "import warnings\n\ndef test_w():\n    warnings.warn('w')\n"},
    )
    assert real(project, "pytest", "-q").verdict == PROVED
    got = real(project, "PYTHONWARNINGS=error", "pytest", "-q")
    assert (got.verdict, got.reason, got.counts) == (FAILED, FAILING, Counts(0, 1, 0))


_FORGED = '<testsuite><testcase name="forged"/></testsuite>'


@needs_runner("pytest")
def test_an_atexit_rewrite_is_what_the_bound_concedes(tmp_path: Path) -> None:
    # Code in the runner's load path runs inside it and can write the report it was handed, after
    # pytest wrote it: `proved` here is the runner's own report, which the bound says the tree can
    # shape.
    conftest = (
        "import atexit, os\n\n"
        "def pytest_configure(config):\n"
        "    path = config.option.xmlpath\n"
        "    def forged():\n"
        f"        open(path, 'w').write({_FORGED!r})\n"
        "        os._exit(0)\n"
        "    atexit.register(forged)\n"
    )
    project = pytest_project(tmp_path / "p", failing=1, files={"conftest.py": conftest})
    got = real(project, "pytest", "-q")
    assert (got.verdict, got.counts, got.exit_code) == (PROVED, Counts(1, 0, 0), 0)


# One debugger command, piped into `prove`, that writes a green report where pytest was told to
# write its own, and leaves at once.
_DEBUGGER_FORGE = (
    "!import sys, os; "
    "path = [word.split('=', 1)[1] for word in sys.argv if word.startswith('--junitxml=')][0]; "
    f"open(path, 'w').write({_FORGED!r}); os._exit(0)\n"
)


@needs_runner("pytest")
def test_a_debugger_driven_through_prove_s_standard_input_forges_nothing(tmp_path: Path) -> None:
    # `--pdb` is free: the runner's standard input is `/dev/null`, so the debugger reads its end,
    # quits, and pytest exits 2 with the failure in its report. Had it the caller's, the command
    # piped in would write a green report and exit 0: `proved`.
    project = pytest_project(tmp_path / "p", failing=1)
    with standard_input(_DEBUGGER_FORGE.encode()):
        got = real(project, "pytest", "-q", "-p", "no:cacheprovider", "--pdb")
    assert (got.verdict, got.reason, got.counts, got.exit_code) == (
        FAILED,
        FAILING,
        Counts(0, 1, 0),
        2,
    )


@needs_runner("pytest")
def test_an_untracked_conftest_is_counted_and_named(tmp_path: Path) -> None:
    project = pytest_project(tmp_path / "p", passing=1)
    git(project, "init", "-q")
    git(project, "add", "pytest.ini", "test_scratch.py")
    git(project, "commit", "-q", "-m", "first")
    (project / "conftest.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef extra():\n    return 1\n", encoding="utf-8"
    )
    got = real(project, "pytest", "-q")
    assert (got.verdict, got.counts) == (PROVED, Counts(1, 0, 0))
    assert got.untracked == ("conftest.py",)
    assert "untracked in the discovery set: conftest.py" in line(got)
