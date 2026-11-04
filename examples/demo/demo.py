"""A demonstration of stayfixed, run against a small repository it builds in a scratch directory.

    python3 -I examples/demo/demo.py STAYFIXED [--require-claude] [--keep]

`STAYFIXED` is the `stayfixed` program under test. Each act runs it as a user would and passes
only on the product's own answer: its exit code and the fields of the one JSON object its
`--json` prints on standard output. Nothing this script prints is ever read back, so an act
cannot pass on the script's word.

Every command runs with `HOME` inside the scratch directory, `GIT_CONFIG_NOSYSTEM=1`, fixed
author and committer names, emails and dates, and a `bin/` directory first on `PATH` that holds a
link named `stayfixed` to `STAYFIXED`, so a configured `["stayfixed", ...]` runs the program under
test. Nothing reaches the network: `pytest`, `git` and `python3` come from the caller's `PATH`.

Exit 0 when no act failed, 1 when one did, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

# The whole run's wall time is printed beside this goal, in seconds; it is a goal and not a bound.
GOAL_SECONDS = 60
# How long one command may run before its act fails: a named cap, so a hung command ends the act
# instead of the demo. Ten times what the slowest act's commands take on a laptop.
COMMAND_TIMEOUT_SECONDS = 300

# The fixed identity and date every commit in the fixture carries, so two runs build the same
# history.
IDENTITY = "Demo Author"
EMAIL = "demo@example.com"
DATE = "2026-01-01T00:00:00+00:00"

# The fixture repository, by its path inside it. `conftest.py` at the root is what makes pytest
# put the root on the import path, so the tests import `total` without an install.
FIXTURE = {
    ".gitignore": "__pycache__/\n.pytest_cache/\n",
    "conftest.py": "# Here so that pytest puts this directory on the import path.\n",
    "total.py": ('def total(items):\n    """The sum of every item."""\n    return sum(items)\n'),
    "tests/test_total.py": (
        "from total import total\n"
        "\n"
        "\n"
        "def test_total_adds_every_item():\n"
        "    assert total([1, 2, 3]) == 6\n"
        "\n"
        "\n"
        "def test_total_of_nothing_is_zero():\n"
        "    assert total([]) == 0\n"
    ),
}


class ActFailed(Exception):
    """An act's command did not answer as the act expects; the message says what differed."""


class Skipped(Exception):
    """An act could not run here; the message says why."""


@dataclass(frozen=True)
class Field:
    """One field of a `--json` object an act asserts.

    `path` is dotted into the object; a segment `rows[name=x]` takes the one element of the list
    `rows` whose `name` is `x`. `how` says what the value must be: `is` equal to `expected`,
    `holds` a list holding it, `lacks` a list without it, `names` a string containing it.
    """

    path: str
    expected: object
    how: str = "is"

    def describe(self) -> str:
        return f"{self.path} {self.how} {json.dumps(self.expected)}"


@dataclass(frozen=True)
class Ran:
    code: int
    stdout: str
    stderr: str


_MISSING = object()
_SELECTOR = re.compile(r"^(?P<key>[^\[]+)\[(?P<field>[^=\]]+)=(?P<value>[^\]]*)\]$")


def _lookup(document: object, path: str) -> object:
    """The value at `path` in `document`, or `_MISSING`."""
    value = document
    for segment in path.split("."):
        selector = _SELECTOR.match(segment)
        key = selector.group("key") if selector else segment
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
        if selector:
            if not isinstance(value, list):
                return _MISSING
            rows = [
                row
                for row in value
                if isinstance(row, dict)
                and row.get(selector.group("field")) == selector.group("value")
            ]
            if len(rows) != 1:
                return _MISSING
            value = rows[0]
    return value


def _holds(field: Field, value: object) -> bool:
    if field.how == "is":
        # `True == 1` in Python; a JSON `true` is not the number 1, so the types must match too.
        return type(value) is type(field.expected) and value == field.expected
    if field.how == "holds":
        return isinstance(value, list) and field.expected in value
    if field.how == "lacks":
        return isinstance(value, list) and field.expected not in value
    if field.how == "names":
        return (
            isinstance(value, str) and isinstance(field.expected, str) and field.expected in value
        )
    raise ValueError(f"unknown comparison {field.how!r}")


class Demo:
    """The scratch directory, the fixture repository in it and the environment every command
    runs under."""

    def __init__(self, scratch: Path, stayfixed: Path, caller_path: str) -> None:
        self.scratch = scratch
        self.repo = scratch / "repo"
        self.home = scratch / "home"
        self.bin = scratch / "bin"
        self.tmp = scratch / "tmp"
        # The version `stayfixed --version` names, which the fixture's configuration records.
        self.version = ""
        for directory in (self.repo, self.home, self.bin, self.tmp):
            directory.mkdir()
        (self.bin / "stayfixed").symlink_to(stayfixed)
        self.env = {
            "PATH": os.pathsep.join([str(self.bin), caller_path]),
            "HOME": str(self.home),
            "TMPDIR": str(self.tmp),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": IDENTITY,
            "GIT_AUTHOR_EMAIL": EMAIL,
            "GIT_AUTHOR_DATE": DATE,
            "GIT_COMMITTER_NAME": IDENTITY,
            "GIT_COMMITTER_EMAIL": EMAIL,
            "GIT_COMMITTER_DATE": DATE,
            # Claude Code's switch for every request that is not a model call, of which the
            # demo makes none.
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }

    def which(self, program: str) -> str | None:
        return shutil.which(program, path=self.env["PATH"])

    def run(self, argv: Sequence[str], *, cwd: Path | None = None) -> Ran:
        """Run `argv` in the fixture (or `cwd`) under the act environment, never through a
        shell, and capture what it printed. Its standard input is nothing."""
        try:
            # The argv is this script's own, run as typed and never through a shell.
            done = subprocess.run(  # noqa: S603
                list(argv),
                cwd=cwd or self.repo,
                env=self.env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            raise ActFailed(f"{shlex.join(argv)} ran past {COMMAND_TIMEOUT_SECONDS} s") from expired
        except OSError as error:
            raise ActFailed(f"{shlex.join(argv)} could not start: {error}") from error
        return Ran(done.returncode, done.stdout, done.stderr)

    def run_checked(self, argv: Sequence[str], *, cwd: Path | None = None) -> str:
        """A command the act needs to set the scene; any failure fails the act."""
        ran = self.run(argv, cwd=cwd)
        if ran.code != 0:
            raise ActFailed(f"{shlex.join(argv)} exited {ran.code}: {ran.stderr.strip()}")
        return ran.stdout

    def git(self, *args: str) -> str:
        return self.run_checked(["git", *args])

    def write(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def stayfixed(
        self, args: Sequence[str], *, code: int, fields: Sequence[Field]
    ) -> dict[str, object]:
        """Run `stayfixed ARGS` and assert its exit code and every field of its `--json` object.

        Prints the command as typed, the exit code and each field asserted. Returns the object, so
        an act may take a value the product named (a path it wrote) for its next step.
        """
        argv = ["stayfixed", *args]
        print(f"  $ {shlex.join(argv)}")
        ran = self.run(argv)
        problems: list[str] = []
        if ran.code != code:
            problems.append(f"exit: expected {code}, got {ran.code}")
        print(f"  exit {ran.code}")
        try:
            parsed: object = json.loads(ran.stdout)
        except json.JSONDecodeError:
            parsed = None
        document: dict[str, object] = parsed if isinstance(parsed, dict) else {}
        if not isinstance(parsed, dict):
            problems.append("stdout is not one JSON object")
        else:
            for field in fields:
                value = _lookup(document, field.path)
                if value is _MISSING:
                    problems.append(
                        f"{field.path}: expected {field.how} "
                        f"{json.dumps(field.expected)}, got no such field"
                    )
                elif _holds(field, value):
                    print(f"  {field.describe()}")
                else:
                    problems.append(
                        f"{field.path}: expected {field.how} "
                        f"{json.dumps(field.expected)}, got {json.dumps(value)}"
                    )
        if problems:
            tail = ran.stderr.strip().splitlines()[-5:]
            raise ActFailed("\n".join(problems + [f"stderr: {line}" for line in tail]))
        return document


# The project's configuration.
CONFIGURATION = """\
[stayfixed]
version = "{version}"

[project]
name = "demo"
"""
BUG_TITLE = "total drops the last item"
# The argv the ledger entry carries, which `bugs regressions` runs once the entry is fixed.
REGRESSION = ["pytest", "-q", "tests/test_total.py"]
# The change that brings the bug back.
FIXED = "    return sum(items)\n"
BROKEN = "    return sum(items[:-1])\n"


def _close(demo: Demo, relative: str) -> None:
    """Close the entry `bugs new` filed as the close-bug skill says: `fixed`, `fixed_in` quoted
    around its backticks, the regression that reproduces it and a `## Fix` section."""
    path = demo.repo / relative
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ActFailed(f"the entry bugs new named cannot be read: {error}") from error
    closed = text
    for before, after in (
        ("\nstatus: open\n", "\nstatus: fixed\n"),
        ("\nfixed_in:\n", f'\nfixed_in: "`main`"\nregression: {json.dumps(REGRESSION)}\n'),
    ):
        if closed.count(before) != 1:
            raise ActFailed(f"the entry bugs new wrote has no single {before.strip()!r} line")
        closed = closed.replace(before, after)
    closed += (
        "\n## Fix\n\n"
        "`total` sums every item again. `tests/test_total.py` covers it, and is this entry's"
        " regression.\n"
    )
    path.write_text(closed, encoding="utf-8")


def act_regression(demo: Demo) -> None:
    # On `main`: the configuration, and a bug filed, fixed and given its regression.
    demo.write("stayfixed.toml", CONFIGURATION.format(version=demo.version))
    demo.git("add", "stayfixed.toml")
    demo.git("commit", "-q", "-m", "the project's configuration")
    filed = demo.stayfixed(
        [
            "bugs",
            "new",
            BUG_TITLE,
            "--severity",
            "medium",
            "--area",
            "total",
            "--no-fetch",
            "--json",
        ],
        code=0,
        fields=[Field("id", "BR-001"), Field("path", "docs/bugs/BR-001.md")],
    )
    _close(demo, str(filed["path"]))
    demo.stayfixed(["bugs", "index", "--json"], code=0, fields=[])
    demo.stayfixed(["bugs", "check", "--json"], code=0, fields=[Field("findings", [])])
    demo.stayfixed(
        ["bugs", "regressions", "--json"],
        code=0,
        fields=[Field("not_passed", 0), Field("regressions[id=BR-001].verdict", "passed")],
    )
    demo.git("add", "-A")
    demo.git("commit", "-q", "-m", "a fixed bug and its regression")
    # On `change`: the bug comes back, and its regression fails the change.
    demo.git("switch", "-q", "-c", "change")
    source = (demo.repo / "total.py").read_text(encoding="utf-8")
    demo.write("total.py", source.replace(FIXED, BROKEN))
    demo.git("commit", "-q", "-a", "-m", "total drops the last item again")
    demo.stayfixed(
        ["bugs", "regressions", "--json"],
        code=1,
        fields=[Field("not_passed", 1), Field("regressions[id=BR-001].verdict", "failed")],
    )


# The private overlay `attach` binds the fixture to: this project's skill, and another project's
# that must stay out of this one's render. Its layout is the overlay's own: `common/` for every
# project, `projects/<name>/` for one.
OVERLAY_DIRECTORIES = ("common/claude", "common/codex", "common/memory", "projects/demo/memory")
CANARY = "demo-canary"
OTHER_CANARY = "other-canary"
SKILLS = {
    "projects/demo/claude/skills": CANARY,
    "projects/other/claude/skills": OTHER_CANARY,
}
# Where `attach` renders the overlay's plugin, under the home directory: one directory per binding,
# named by the binding id, which `--json` names by its first characters.
DELIVERY = ".local/share/stayfixed/delivery"
MARKETPLACE = ".claude-plugin/marketplace.json"


def _overlay(demo: Demo) -> Path:
    """A scratch overlay, a git repository as a real one is, and the machine file naming it."""
    overlay = demo.scratch / "overlay"
    for relative in OVERLAY_DIRECTORIES:
        (overlay / relative).mkdir(parents=True)
    for relative, name in SKILLS.items():
        skill = overlay / relative / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A skill that shows which project it reached.\n"
            f"---\n\nSay {name}.\n",
            encoding="utf-8",
        )
    demo.run_checked(["git", "init", "-q", "-b", "main"], cwd=overlay)
    machine = demo.scratch / "machine.toml"
    machine.write_text(f"[overlay]\nroot = {json.dumps(str(overlay))}\n", encoding="utf-8")
    return machine


def _clean(demo: Demo) -> None:
    status = demo.git("status", "--porcelain")
    if status:
        raise ActFailed(f"git status --porcelain is not empty:\n{status.rstrip()}")
    print("  git status --porcelain is empty")


def _render(demo: Demo, binding: str) -> Path:
    """The plugin directory of the one render `attach` wrote for `binding`, read off the
    marketplace file it wrote there."""
    delivery = demo.home / DELIVERY
    renders = sorted(delivery.glob(f"{binding}*")) if binding and delivery.is_dir() else []
    if len(renders) != 1:
        raise ActFailed(f"~/{DELIVERY}/ holds {len(renders)} render(s) for binding {binding!r}")
    try:
        marketplace = json.loads((renders[0] / MARKETPLACE).read_text(encoding="utf-8"))
        source = marketplace["plugins"][0]["source"]
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        raise ActFailed(f"the render's {MARKETPLACE} names no plugin: {error!r}") from error
    return renders[0] / str(source)


def act_attach(demo: Demo) -> None:
    if demo.which("claude") is None:
        raise Skipped("claude is not on PATH")
    machine = _overlay(demo)
    _clean(demo)
    attached = demo.stayfixed(
        ["attach", "--machine", os.path.relpath(machine, demo.repo), "--json"],
        code=0,
        fields=[
            Field("skills_added", CANARY, "holds"),
            Field("skills_added", OTHER_CANARY, "lacks"),
        ],
    )
    skills = _render(demo, str(attached.get("binding", ""))) / "skills"
    shown = f"~/{DELIVERY}/{attached['binding']}…/{skills.parent.name}/skills"
    if not (skills / CANARY).is_dir():
        raise ActFailed(f"{shown}/{CANARY}/ is not there")
    print(f"  {shown}/{CANARY}/ is there")
    if (skills / OTHER_CANARY).exists():
        raise ActFailed(f"{shown}/{OTHER_CANARY}/ is there")
    print(f"  {shown}/{OTHER_CANARY}/ is not")
    _clean(demo)


ACTS: tuple[tuple[str, Callable[[Demo], None]], ...] = (
    ("a fixed bug's regression fails the change that brings it back", act_regression),
    ("attach delivers this project's skill and not another project's", act_attach),
)


def build_fixture(demo: Demo) -> None:
    demo.git("init", "-q", "-b", "main")
    for relative, text in FIXTURE.items():
        demo.write(relative, text)
    demo.git("add", "-A")
    demo.git("commit", "-q", "-m", "a total and its tests")


def _first_line(ran: Ran) -> str:
    """The first line a `--version` printed, or what it exited with when it printed none."""
    lines = (ran.stdout.strip() or ran.stderr.strip()).splitlines()
    return lines[0] if ran.code == 0 and lines else f"exited {ran.code}"


def _on_signal(signum: int, _frame: FrameType | None) -> None:
    # A SIGTERM or SIGHUP leaves through `main`'s `finally`, as Ctrl-C does, so the scratch
    # directory is removed on that path too.
    raise SystemExit(128 + signum)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the stayfixed demo against STAYFIXED.")
    parser.add_argument("stayfixed", metavar="STAYFIXED", help="the stayfixed program to run")
    parser.add_argument(
        "--require-claude",
        action="store_true",
        help="fail the run when an act is skipped because claude is not on PATH",
    )
    parser.add_argument("--keep", action="store_true", help="keep the scratch directory")
    options = parser.parse_args(argv)

    program = Path(options.stayfixed)
    if not program.is_file() or not os.access(program, os.X_OK):
        print(f"usage error: {program} is not an executable file", file=sys.stderr)
        return 2
    caller_path = os.environ.get("PATH", os.defpath)
    for needed in ("pytest", "git", "python3"):
        if shutil.which(needed, path=caller_path) is None:
            print(f"usage error: {needed} is not on PATH", file=sys.stderr)
            return 2

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _on_signal)
    started = time.monotonic()
    scratch = Path(tempfile.mkdtemp(prefix="stayfixed-demo-"))
    try:
        return _run(Demo(scratch, Path(os.path.abspath(program)), caller_path), options, started)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    finally:
        if not options.keep:
            shutil.rmtree(scratch, ignore_errors=True)


def _run(demo: Demo, options: argparse.Namespace, started: float) -> int:
    # By its absolute path and never through `PATH`: a STAYFIXED that cannot start would let the
    # acts' bare `stayfixed` fall through to the next one on `PATH`, and pass on its answers.
    program = os.path.abspath(options.stayfixed)
    try:
        version = demo.run([program, "--version"])
    except ActFailed as failed:
        print(f"usage error: {failed}", file=sys.stderr)
        return 2
    if version.code != 0:
        print(f"usage error: {program} --version exited {version.code}", file=sys.stderr)
        return 2
    demo.version = _first_line(version).split()[-1]
    pytest = demo.which("pytest") or ""
    pytest_version = demo.run(["pytest", "--version"])
    print(f"stayfixed: {os.path.realpath(options.stayfixed)}")
    print(f"stayfixed --version: {_first_line(version)}")
    print(f"pytest: {pytest}")
    print(f"pytest --version: {_first_line(pytest_version)}")
    if options.keep:
        print(f"scratch directory, kept: {demo.scratch}")

    try:
        build_fixture(demo)
    except ActFailed as failed:
        print(f"the fixture repository could not be built: {failed}", file=sys.stderr)
        return 1

    passed = skipped = failed_count = 0
    for number, (shows, act) in enumerate(ACTS, start=1):
        print()
        print(f"act {number}: {shows}")
        try:
            act(demo)
        except Skipped as skip:
            skipped += 1
            print(f"act {number} skipped: {skip}")
        except ActFailed as failure:
            failed_count += 1
            for line in str(failure).splitlines():
                print(f"  {line}")
            print(f"act {number} failed")
        else:
            passed += 1
            print(f"act {number} passed")

    elapsed = time.monotonic() - started
    print()
    if skipped and options.require_claude:
        print("--require-claude: an act was skipped, so the run fails")
    print(
        f"{passed} passed, {skipped} skipped, {failed_count} failed"
        f" in {elapsed:.1f} s (goal: {GOAL_SECONDS} s)"
    )
    return 1 if failed_count or (skipped and options.require_claude) else 0


if __name__ == "__main__":
    sys.exit(main())
