from __future__ import annotations

import ast
import importlib
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from stayfixed import gitenv
from stayfixed.gitenv import NO_ANSWER, git_run
from tests.gitfixture import SESSION_CONFIG, plant_path, stand_in_git

SRC = Path(__file__).resolve().parents[1] / "src"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@needs_git
def test_a_successful_query_returns_zero_and_its_output(tmp_path: Path) -> None:
    code, out = git_run(tmp_path, "init", "-q")
    assert (code, out) == (0, "")
    code, out = git_run(tmp_path, "rev-parse", "--is-inside-work-tree")
    assert (code, out.strip()) == (0, "true")


@needs_git
def test_a_non_zero_exit_is_returned_not_collapsed(tmp_path: Path) -> None:
    # `check-ignore` answers 1 for "nothing matched"; a runner that read every non-zero as
    # "nothing found" could not carry that answer. Mutation: return `(-1, "")` on any
    # non-zero — this reddens.
    git_run(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("x\n", encoding="utf-8")
    code, _ = git_run(tmp_path, "check-ignore", "--no-index", "--stdin", stdin="y\n")
    assert code == 1


def test_a_git_that_cannot_run_is_minus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # no git here
    assert git_run(tmp_path, "rev-parse") == (-1, "")


def _stub(directory: Path, body: str, name: str = "git") -> Path:
    """An executable `<directory>/<name>` that runs `body` under `/bin/sh`."""
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / name
    stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


@needs_git
def test_the_environment_is_scrubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # An inherited GIT_DIR would make every answer be about a different repository.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    git_run(elsewhere, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    code, _ = git_run(tmp_path, "rev-parse", "--is-inside-work-tree")
    assert code != 0


@needs_git
def test_the_product_s_git_reads_the_home_the_suite_gives_each_test(tmp_path: Path) -> None:
    # `scrubbed_env` keeps `HOME` for real users, so under test the product's `git` would read
    # the developer's global excludes; `tests/conftest.py` gives each test an empty one. This
    # writes an excludes file there and sees the product's `check-ignore` honour it, so the
    # `HOME` it reads is the sealed one and not the developer's. Mutation (advisory): drop the
    # conftest's `setenv("HOME", ...)` -> the first assertion reddens, before anything could be
    # written into the developer's real home.
    home = Path.home()
    assert home.is_relative_to(tmp_path.parent), home
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text("CLAUDE.md\n", encoding="utf-8")
    git_run(tmp_path, "init", "-q")
    code, out = git_run(tmp_path, "check-ignore", "--stdin", "-z", stdin="CLAUDE.md\0other.md")
    assert (code, out) == (0, "CLAUDE.md\0")


@needs_git
def test_the_product_s_git_runs_no_automatic_maintenance_under_test(tmp_path: Path) -> None:
    # The product's `fetch` starts maintenance as a fixture's `commit` does, and from git 2.55 it
    # outlives the command, holding `objects/maintenance.lock` while a test may already be
    # removing or walking the repository. `scrubbed_env` drops the `GIT_CONFIG_COUNT` the
    # fixture's `git` is sealed with, so the suite reaches the product's through the `HOME` it
    # keeps: asked by the product's own `git_run`, both keys answer as `tests/gitfixture.py` sets
    # them. Mutation (declared): the conftest writes an empty `.gitconfig` -> neither key is set.
    git_run(tmp_path, "init", "-q")
    assert git_run(tmp_path, "config", "--get", "maintenance.auto") == (0, "false\n")
    assert git_run(tmp_path, "config", "--get", "gc.auto") == (0, "0\n")


# A byte no UTF-8 locale decodes, and the string this process spells it as: `os.fsdecode` is
# how `os.listdir`, `Path.iterdir` and `sys.argv` hand the same name to Python, so it is the
# one spelling a git answer can be compared with, and the one that opens the file it names.
LATIN1_NAME = b"caf\xe9.md"
DECODED_NAME = os.fsdecode(LATIN1_NAME)


@needs_git
def test_a_path_the_locale_cannot_decode_is_answered_and_not_raised(tmp_path: Path) -> None:
    # `text=True` decoded strictly, so one non-UTF-8 name in `ls-files -z` either left every
    # caller as `internal error: UnicodeDecodeError` or, read as "no answer", hid every other
    # name in the same listing: a committed `.env` beside it went unreported, a sibling checkout
    # of the project passed `setup`'s common-directory check. The answer is the name itself,
    # spelled as the filesystem spells it — lossless, not a placeholder, which is what lets a
    # caller that matches it against a path it walked or sent still match. The name is planted
    # with `update-index --cacheinfo`, which takes the raw bytes on every platform, so this runs
    # where no such file can be created (APFS refuses one). Mutations (declared): the decode made
    # strict again -> it raises; the answer read as no answer again -> `(-1, "")`; both redden.
    git_run(tmp_path, "init", "-q")
    plant_path(tmp_path, LATIN1_NAME)
    code, out = git_run(tmp_path, "ls-files", "-z")
    assert (code, out) == (0, f"{DECODED_NAME}\0")
    assert os.fsencode(out.rstrip("\0")) == LATIN1_NAME


@needs_git
def test_a_name_sent_on_stdin_reaches_git_as_the_bytes_it_names(tmp_path: Path) -> None:
    # The other direction of the same seam: a name read off a Linux disk carries the surrogate
    # escapes above, and a strict encode of `stdin` failed before git was ever asked — the docs
    # trail's ignore filter then read "nothing is ignored" and listed a local-only document in
    # the committed roadmap. `check-ignore --no-index` echoes what it was sent, so an ignored
    # name coming back equal to itself proves both halves: the bytes git matched were the
    # name's own, and the answer decodes back to what the caller holds. Mutation (declared):
    # encode `stdin` strictly again -> the question cannot be asked and this reddens.
    git_run(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("caf*\n", encoding="utf-8")
    code, out = git_run(tmp_path, "check-ignore", "--no-index", "--stdin", "-z", stdin=DECODED_NAME)
    assert (code, out) == (0, f"{DECODED_NAME}\0")


@needs_git
def test_git_s_own_diagnostics_are_never_decoded_into_a_failure(tmp_path: Path) -> None:
    # Text mode decoded stderr with the same codec, and nothing reads it: a git whose error
    # text quoted one non-UTF-8 byte turned an ordinary non-zero exit — an answer every caller
    # has an arm for — into a traceback, or into `-1` with git's own exit code lost. Now it is
    # never decoded. `update-index` on a missing path names it on stderr, raw. Mutation
    # (declared): decode git's stderr again -> this reddens.
    git_run(tmp_path, "init", "-q")
    code, out = git_run(tmp_path, "update-index", "--add", "--", DECODED_NAME)
    assert code not in (0, -1)
    assert out == ""


@needs_git
def test_a_stdin_this_process_cannot_encode_is_minus_one(tmp_path: Path) -> None:
    # A lone surrogate outside the escape range has no bytes under any codec, so git cannot be
    # asked the question at all: `(-1, "")`, the runner's own "git could not be given its
    # input", which every stdin caller already answers conservatively. Reachable in
    # practice under a non-UTF-8 locale, where a note's text holds characters that locale has
    # no byte for. Mutation (declared): drop `UnicodeEncodeError` from the `except` -> this
    # reddens. `needs_git`, because where no `git` can be launched the `OSError` answers
    # `(-1, "")` first and the case passes whatever the `except` holds — measured, with that
    # mutation applied and no `git` on `PATH`: 1 passed.
    assert git_run(tmp_path, "check-ignore", "--stdin", stdin="\ud800") == (-1, "")


# A carriage return, which a name may carry on every POSIX filesystem, APFS included. Every `-z`
# query prints it raw.
CR_NAME = "plan\rx.md"


@needs_git
def test_a_carriage_return_in_a_name_comes_back_as_itself(tmp_path: Path) -> None:
    # Text mode translated line endings in git's answer, so `ls-files -z` handed back
    # `plan\nx.md`, a name nothing on disk carries: the answer was lossless for every byte but
    # this one. Planted in the index, so the case does not depend on the disk. Mutation
    # (declared): decode through a text-mode wrapper again -> this reddens.
    git_run(tmp_path, "init", "-q")
    plant_path(tmp_path, CR_NAME.encode())
    assert git_run(tmp_path, "ls-files", "-z") == (0, f"{CR_NAME}\0")


@needs_git
def test_a_carriage_return_asked_on_stdin_is_matched_and_answered_as_itself(
    tmp_path: Path,
) -> None:
    # The same byte through the other direction and back: `check-ignore --no-index` echoes the
    # ignored name, and the echo came back with its `\r` turned into `\n`, so the docs trail read
    # a gitignored plan so named as not ignored and wrote it into the committed roadmap.
    # Mutation (declared, the entry above) reddens this too.
    git_run(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("plan*\n", encoding="utf-8")
    code, out = git_run(tmp_path, "check-ignore", "--no-index", "--stdin", "-z", stdin=CR_NAME)
    assert (code, out) == (0, f"{CR_NAME}\0")


# A name that is valid UTF-8 and not ASCII: the filesystem spells it `café.md` on every
# platform where its encoding is UTF-8, which macOS's always is, whatever the locale says.
CAFE = "caf\u00e9.md"


def _a_latin_1_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """What `LC_ALL=en_US.ISO8859-1` changes in this process, simulated at the one place Python
    reads it, so the case holds on a runner that has no such locale installed."""
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "latin-1")


@needs_git
def test_git_s_answer_and_the_filesystem_spell_a_name_alike_whatever_the_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `git_run` decoded with the locale's codec while `os.fsdecode`, `Path.iterdir` and argv use
    # the filesystem's, and on macOS the two differ under any non-UTF-8 locale: git's
    # `caf\xc3\xa9.md` came back as mojibake, never equal to the `café.md` the disk and argv
    # hold. Paths are compared with git's answers everywhere, so every such comparison missed.
    # The pipe uses the filesystem's codec now, and both directions agree. Mutation
    # (declared): decode with the locale's codec again -> this reddens.
    _a_latin_1_locale(monkeypatch)
    git_run(tmp_path, "init", "-q")
    plant_path(tmp_path, os.fsencode(CAFE))
    assert git_run(tmp_path, "ls-files", "-z") == (0, f"{CAFE}\0")


@needs_git
def test_a_name_asked_on_stdin_matches_the_rule_that_names_it_whatever_the_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other direction: a name read off the disk, sent on `stdin` in the locale's codec,
    # reached git as bytes that were not the name's, so `.gitignore`'s `café.md` never matched
    # it and a gitignored document read as not ignored — the docs trail then listed it in the
    # committed roadmap. Mutation (declared, the entry above) reddens this too.
    _a_latin_1_locale(monkeypatch)
    git_run(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(f"{CAFE}\n", encoding="utf-8")
    code, out = git_run(tmp_path, "check-ignore", "--no-index", "--stdin", "-z", stdin=CAFE)
    assert (code, out) == (0, f"{CAFE}\0")


def _a_git_that_sleeps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """A stand-in `git` the product runs that answers nothing, exit 0, after `seconds`."""
    stand_in_git(monkeypatch, _stub(tmp_path / "bin", f"exec sleep {seconds}"))


def test_a_git_past_its_time_limit_is_minus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The third cause `-1` still carries, and the one the callers' safeguards are kept for: a
    # `git` that hangs is no answer, whatever it would have said. The stand-in `git` sleeps
    # past a bound far below it. The suite's floor is removed, back to the product's zero, or
    # the bound this test is about would be lifted past the sleep.
    monkeypatch.delenv(gitenv.FLOOR_VARIABLE)
    _a_git_that_sleeps(tmp_path, monkeypatch, 5)
    assert git_run(tmp_path, "rev-parse", timeout=0.2) == (-1, "")


def test_the_suite_floor_outlasts_a_bound_its_caller_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `tests/conftest.py` lifts every `git_run` bound to its floor, so a loaded machine cannot
    # run a caller's two- or five-second bound out and turn a test red for the load. A `git` that
    # answers after half a second, under a bound a fifth of that, still answers here. Mutation
    # (oracle): `mutations/`'s "the git runner ignores the floor a test runner sets" — the variable
    # is never read, the call runs out, and this reddens.
    _a_git_that_sleeps(tmp_path, monkeypatch, 0.5)
    assert git_run(tmp_path, "rev-parse", timeout=0.1) == (0, "")


def test_the_product_ships_with_no_floor_under_its_bounds() -> None:
    # Read in a fresh interpreter with the suite's variable gone, as an import of the product
    # leaves it, because the suite has raised the floor this process sees. A floor above zero in
    # the product would widen every bound a caller chose, the session-start sync's two seconds
    # among them, whose handler shares a ten-second entry. Mutation (oracle): `mutations/`'s "the
    # product ships a floor under every git bound" -> this reddens.
    env = {key: value for key, value in os.environ.items() if key != gitenv.FLOOR_VARIABLE}
    shipped = subprocess.run(
        [sys.executable, "-P", "-c", "from stayfixed import gitenv; print(gitenv.bound_floor())"],
        capture_output=True,
        text=True,
        check=False,
        env={**env, "PYTHONPATH": str(SRC)},
    )
    assert shipped.returncode == 0, shipped.stderr
    assert float(shipped.stdout) == 0, shipped.stdout


def test_the_floor_variable_never_shortens_a_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The variable can only raise: a value below the caller's bound leaves that bound as it
    # was. A `git` that answers after 0.3 s, under a caller's minute and a floor of 0.05,
    # answers; the minute is there so no load on the machine can decide the case. Mutation
    # (oracle): `mutations/`'s "the floor replaces the caller's bound instead of raising it" -> this
    # reddens.
    monkeypatch.setenv(gitenv.FLOOR_VARIABLE, "0.05")
    _a_git_that_sleeps(tmp_path, monkeypatch, 0.3)
    assert git_run(tmp_path, "rev-parse", timeout=60) == (0, "")


@pytest.mark.parametrize("value", ["", "sixty", "nan", "-inf", "-5", "0"])
def test_a_floor_variable_that_is_no_positive_number_raises_nothing(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # Not a number, or not above zero: no floor at all, as if the variable were unset. `nan`
    # compares false with everything, so a check spelled `asked <= 0` would let it through as
    # the floor, and `max` would then answer by argument order. Mutation (oracle): `mutations/`'s "a
    # floor variable that is not a number is honoured" -> the `nan` row reddens.
    monkeypatch.setenv(gitenv.FLOOR_VARIABLE, value)
    assert gitenv.bound_floor() == 0


@pytest.mark.parametrize("value", ["1e300", "inf"])
def test_the_floor_variable_is_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # Uncapped, a floor of `1e300` or `inf` would reach `subprocess.run` as a timeout it cannot
    # represent, which raises `OverflowError` — not one of the three things `git_run` reads as no
    # answer — out of every caller. Capped, the call is simply given ten minutes. Mutation
    # (oracle): `mutations/`'s "the floor variable is honoured without its ceiling" -> both rows
    # redden.
    monkeypatch.setenv(gitenv.FLOOR_VARIABLE, value)
    assert gitenv.bound_floor() == gitenv.FLOOR_CEILING_SECONDS
    _a_git_that_sleeps(tmp_path, monkeypatch, 0)
    assert git_run(tmp_path, "rev-parse") == (0, "")


def _seen_by_git(root: Path) -> dict[str, str]:
    """The environment a `git` started by `git_call` hands a shell alias of its own."""
    called = gitenv.git_call(root, "-c", "alias.e=!env", "e", timeout=60)
    assert called.code == 0, called
    return dict(line.split("=", 1) for line in called.out.splitlines() if "=" in line)


@needs_git
def test_git_call_hands_git_only_the_kept_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Whatever the session that fired carries, a per-project `GIT_CONFIG_GLOBAL` with a `pushurl`
    # above all, reaches no git stayfixed starts; the agent and the proxy a push needs still do.
    # Mutation (oracle): `mutations/`'s "a session's global git configuration reaches git" -> this
    # reddens.
    for name in (SESSION_CONFIG, "GIT_DIR", "PRE_COMMIT_HOME", "GIT_SSH_COMMAND"):
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv("SSH_AUTH_SOCK", "/agent.sock")
    monkeypatch.setenv("https_proxy", "http://proxy.invalid:3128")

    seen = _seen_by_git(tmp_path)

    for name in (SESSION_CONFIG, "GIT_DIR", "PRE_COMMIT_HOME", "GIT_SSH_COMMAND"):
        assert name not in seen, name
    assert seen["SSH_AUTH_SOCK"] == "/agent.sock"
    assert seen["https_proxy"] == "http://proxy.invalid:3128"
    assert seen["GIT_TERMINAL_PROMPT"] == "0"


@needs_git
@pytest.mark.parametrize("entry", ["", "."])
def test_a_relative_path_entry_never_reaches_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    # Every git runs in a repository a clone chose the contents of, so an empty or `.` entry of
    # `PATH` (a dotfile slip) would find a `git` planted at its root, and git an `ssh` there the
    # same way. Mutation (oracle): `mutations/`'s "a relative PATH entry reaches git" -> this
    # reddens.
    _stub(tmp_path, "echo planted")
    monkeypatch.setenv("PATH", f"{entry}{os.pathsep}{os.environ['PATH']}")

    assert gitenv.git_call(tmp_path, "version", timeout=60).out.startswith("git version")
    shown = _seen_by_git(tmp_path)["PATH"]
    assert all(os.path.isabs(part) for part in shown.split(os.pathsep)), shown


def test_git_call_honours_the_floor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The suite's floor lifts `git_call`'s bounds as it lifts `git_run`'s, so the note sync's tests
    # pass no bound of their own. A `git` that answers after half a second, under a bound a fifth
    # of that, still answers. Mutation (oracle): `mutations/`'s "git_call ignores the floor" ->
    # this reddens.
    _a_git_that_sleeps(tmp_path, monkeypatch, 0.5)
    called = gitenv.git_call(tmp_path, "rev-parse", timeout=0.1)
    assert (called.code, called.timed_out) == (0, False)


# Every named bound a product `git` runs under. The suite's floor lifts each one past git's
# latency, so a bound shrunk below it — `QUERY_TIMEOUT_SECONDS = 0.001` — passed every test
# that runs through it, and only an owner's machine would have met a `git` never given the time.
GIT_RUN_BOUNDS = (
    "stayfixed.gitenv.GIT_TIMEOUT_SECONDS",
    "stayfixed.gitenv.QUERY_TIMEOUT_SECONDS",
    "stayfixed.overlay.sync.SYNC_TIMEOUT_SECONDS",
    "stayfixed.guards.commit.LOG_TIMEOUT_SECONDS",
    "stayfixed.hints.hygiene.STATUS_TIMEOUT_SECONDS",
)


@pytest.mark.parametrize("bound", GIT_RUN_BOUNDS)
def test_a_named_git_bound_leaves_git_a_second_to_answer(bound: str) -> None:
    # A second is far above what a local `rev-parse` takes and far below every bound shipped,
    # so the row fails on a bound shrunk by accident and on nothing a person would tune.
    # Mutations (oracle): `mutations/`'s "the bound on a query that grows is shrunk below git's
    # latency" and "the overlay sync's bound is shrunk below git's latency" -> their rows redden.
    module, name = bound.rsplit(".", 1)
    assert getattr(importlib.import_module(module), name) >= 1


def test_a_query_that_grows_with_the_repository_is_given_at_least_the_default_bound() -> None:
    # `QUERY_TIMEOUT_SECONDS` is the wider bound for a `log --all` or a listing of every tracked
    # file; narrower than the default for a five-second `rev-parse`, it is not wider at all.
    # Mutation (oracle): `mutations/`'s "the default git bound outgrows the one for a query that
    # grows" -> this reddens.
    assert gitenv.QUERY_TIMEOUT_SECONDS >= gitenv.GIT_TIMEOUT_SECONDS


def _default_of(
    function: ast.FunctionDef | ast.AsyncFunctionDef, parameter: str
) -> ast.expr | None:
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    defaulted = positional[len(positional) - len(arguments.defaults) :]
    defaults = {a.arg: d for a, d in zip(defaulted, arguments.defaults, strict=True)}
    for a, d in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if d is not None:
            defaults[a.arg] = d
    return defaults.get(parameter)


def _spelled(expression: ast.expr | None) -> str | None:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return expression.attr
    return None


# The two runners a bound is handed to, `git_run` and `git_call`.
GIT_LAUNCHES = frozenset({"git_run", "git_call"})


def test_every_bound_a_git_run_call_passes_is_one_the_table_pins() -> None:
    # The table above is only as good as its list: a call given a bound of its own that no row
    # names — a new constant, or a literal below a second — would slip past it as the two above
    # did past the suite. So every `timeout=` a `git_run` or `git_call` under `src/` is given is
    # read: a literal must be at least a second, a name must be a row, and a parameter passed
    # through must default to one. And every row must be reached, so none outlives its constant.
    # Mutation (oracle): `mutations/`'s "the status query's bound is a literal below git's latency"
    # -> this reddens.
    pinned = {bound.rsplit(".", 1)[1] for bound in GIT_RUN_BOUNDS}
    reached = {"GIT_TIMEOUT_SECONDS"}  # `git_run`'s own default, for a call that passes none
    unpinned = []
    for path in sorted((SRC / "stayfixed").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        enclosing = {
            id(node): function
            for function in ast.walk(tree)
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(function)
        }
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and _spelled(call.func) in GIT_LAUNCHES):
                continue
            given = next((k.value for k in call.keywords if k.arg == "timeout"), None)
            where = f"{path.relative_to(SRC)}:{call.lineno}"
            if given is None:
                continue
            if isinstance(given, ast.Constant):
                if not (isinstance(given.value, int | float) and given.value >= 1):
                    unpinned.append(where)
                continue
            name = _spelled(given)
            function = enclosing.get(id(call))
            if name not in pinned and function is not None and isinstance(given, ast.Name):
                name = _spelled(_default_of(function, given.id))
            if name in pinned:
                reached.add(name)
            else:
                unpinned.append(where)
    assert unpinned == []
    assert reached == pinned


def test_no_answer_names_each_cause_git_run_folds_into_minus_one() -> None:
    # Callers word `-1` with this clause; a clause naming one cause misdiagnoses the others.
    # Output is no longer one of them — it is decoded losslessly — and a clause that still
    # named it would send an owner looking for a filename that is not the fault. Mutation
    # (advisory): put "not UTF-8" back into `NO_ANSWER` — this reddens.
    assert "could not be run" in NO_ANSWER
    assert "time limit" in NO_ANSWER
    assert "input" in NO_ANSWER
    assert "UTF-8" not in NO_ANSWER
