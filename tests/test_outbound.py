"""`README.md`'s "What stayfixed sends where", held to the code.

The section declares every program stayfixed starts that can reach a network, and every file its
templates write under `.github/`, which GitHub runs. This module holds the section's Program
column to both, in both directions: a *network* launch with no row is an undisclosed
destination, which the plugin directory's security scan rejects, and a row with no launch is a
promise about nothing. What a launch is, and what the walk that finds them cannot see, is
`tests/outbound/walk.py`'s docstring; what each launch may reach is `tests/outbound/policy.py`.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable
from itertools import pairwise
from pathlib import Path

import pytest

from tests.outbound.policy import (
    GIT_CONFIG_KEYS,
    GIT_GLOBAL_OPTIONS,
    GIT_PROGRAM_OPTIONS,
    GIT_REMOTE_OPTIONS,
    LOCAL,
    LOCAL_WHOLE,
    NATIVE_MODULES,
    NETWORK,
    NETWORK_MODULES,
    NO_ROWS,
    OVERRIDES,
    PASS_THROUGH,
    ROOT_LAUNCHERS,
    SCRUBBED_ENVIRONMENT,
    USER_COMMANDS,
    VOUCHED_ELEMENTS,
)
from tests.outbound.walk import (
    ROOT,
    SRC,
    Element,
    Launch,
    Override,
    Unread,
    Walk,
    _module_file,
    imported_modules,
    imports,
    package_files,
)

README = ROOT / "README.md"
TEMPLATES = SRC / "templates"
WALK = Walk(ROOT_LAUNCHERS)
# Vacuity floors, not coverage: well under what the walk finds today, so that churn never trips
# one and a walk that stopped seeing the package does.
LAUNCHES_FLOOR = 50
MODULES_FLOOR = 120
# What ends the options in an argv, after which every element is an operand, read or not.
END_OF_OPTIONS = ("--", "--end-of-options")
# The section, everything between its heading and the next `## ` heading, and a code span.
_SENDS_SECTION = re.compile(
    r"^## What stayfixed sends where\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL
)
_CODE_SPAN = re.compile(r"`([^`]+)`")

Key = tuple[str, str, str]
Argv = tuple[Element, ...]
FORBIDDEN_MODULES = NETWORK_MODULES | NATIVE_MODULES


def _within(module: str, listed: Iterable[str]) -> bool:
    return any(module == entry or module.startswith(f"{entry}.") for entry in listed)


def forbidden_imports(root: Path) -> list[tuple[str, str]]:
    """`(file, module)` for each network or native module a file under `root` imports."""
    return [(file, module) for file, module in imports(root) if _within(module, FORBIDDEN_MODULES)]


def _key(launch: Launch, element: Unread) -> Key:
    return launch.file, launch.function, element.text


def _vouched(launch: Launch, parts: Argv) -> set[Key] | None:
    """The `VOUCHED_ELEMENTS` entries that vouch for every unread element of `parts`, or `None`
    when one is not vouched for, or names a value its function binds again or mutates."""
    keys = {_key(launch, part) for part in parts if isinstance(part, Unread)}
    stable = all(part.stable for part in parts if isinstance(part, Unread))
    return keys if stable and keys <= VOUCHED_ELEMENTS.keys() else None


def _options(argv: Argv) -> Argv:
    """The elements of `argv` before its options end."""
    ends = [at for at, part in enumerate(argv) if part in END_OF_OPTIONS]
    return argv[: ends[0]] if ends else argv


def _command(argv: Argv) -> tuple[Argv, Argv] | None:
    """`argv` split into git's global options and the command the tables match, the global
    options taken out; `None` when one of them sets configuration outside `GIT_CONFIG_KEYS`."""
    if argv[:1] != ("git",):
        return (), argv
    at = 1
    while at < len(argv) and argv[at] in GIT_GLOBAL_OPTIONS:
        option = str(argv[at])
        value = argv[at + 1] if at + 1 < len(argv) else None
        configures = option == "-c" and isinstance(value, str)
        if configures and str(value).partition("=")[0] not in GIT_CONFIG_KEYS:
            return None
        at += 1 + GIT_GLOBAL_OPTIONS[option]
    return argv[1:at], ("git", *argv[at:])


def _row(command: Argv) -> str | None:
    """The README row `command` reaches: the first `NETWORK` prefix it starts with, and, for a
    prefix in `USER_COMMANDS`, only when the element after it is the user's, unread."""
    for prefix, row in NETWORK.items():
        if command[: len(prefix)] != prefix:
            continue
        users = command[len(prefix) : len(prefix) + 1]
        if prefix not in USER_COMMANDS or (users and isinstance(users[0], Unread)):
            return row
    return None


def _runs_a_program(part: str, subcommand: str) -> bool:
    """Whether `part`, before the options end of `git <subcommand>`, is one of the subcommand's
    `GIT_PROGRAM_OPTIONS` as git parses it: a long one by a prefix of its name, and a short one
    anywhere in a cluster of short options."""
    name = part.partition("=")[0]
    for option in GIT_PROGRAM_OPTIONS.get(subcommand, ()):
        if option.startswith("--"):
            if len(name) > len("--") and option.startswith(name):
                return True
        elif part[:1] == "-" and part[1:2] != "-" and option[1:] in part[1:]:
            return True
    return False


def _local(command: Argv, options: Argv) -> bool:
    if command[0] == "git":
        subcommand = command[1] if len(command) > 1 and isinstance(command[1], str) else ""
        if any(
            isinstance(part, str)
            and (part.startswith(GIT_REMOTE_OPTIONS) or _runs_a_program(part, subcommand))
            for part in options
        ):
            return False
    return any(command[: len(prefix)] == prefix for prefix in LOCAL) or command in LOCAL_WHOLE


def classify(launch: Launch) -> tuple[frozenset[str] | None, set[Key]]:
    """The README rows `launch` can reach — none for a local one — or `None` when it is
    unclassified; and the declarations that answer rests on.

    A launch whose first unread element is declared in `PASS_THROUGH` reaches the rows declared
    there, whatever else the walk read of it. Otherwise its argv decides: git's global options
    must be read or vouched for in `VOUCHED_ELEMENTS`, since one of them can change what the
    subcommand after them does; a network launch is its row whatever follows; and a launch is
    local only when every element before its options end is read or vouched for, because an
    unread one can be an option such as `--remote`. A declaration covers an element only while
    the element is `stable`.
    """
    unread = [part for part in launch.argv if isinstance(part, Unread)]
    if unread and unread[0].stable and (key := _key(launch, unread[0])) in PASS_THROUGH:
        return PASS_THROUGH[key], {key}
    split = _command(launch.argv)
    if split is None:
        return None, set()
    global_options, command = split
    options = _options(launch.argv)
    if (row := _row(command)) is not None:
        relied = _vouched(launch, global_options)
        return (None, set()) if relied is None else (frozenset({row}), relied)
    relied = _vouched(launch, options)
    if relied is not None and _local(command, options):
        return NO_ROWS, relied
    return None, set()


def unclassified(launches: list[Launch]) -> list[Launch]:
    """The launches that reach neither a row nor only this machine, and are not declared."""
    return [launch for launch in launches if classify(launch)[0] is None]


def _override_key(override: Override) -> Key | None:
    """The `OVERRIDES` key `override` needs, or `None` for an `env=` that calls
    `SCRUBBED_ENVIRONMENT`, which needs none."""
    if override.text.startswith("env=") and override.calls == SCRUBBED_ENVIRONMENT:
        return None
    return override.file, override.function, override.text


def undeclared_overrides(overrides: list[Override]) -> list[Override]:
    """The overrides neither scrubbed nor declared in `OVERRIDES`."""
    return [o for o in overrides if (key := _override_key(o)) and key not in OVERRIDES]


def github_files() -> set[str]:
    """Every file stayfixed's templates write under a `.github/` directory, by the path it is
    written at: a file there is one GitHub acts on.

    A template under a `.github/` folder is found by its path. One written into `.github/` from a
    template outside one is found only when its destination is named here, because the path it is
    written at is computed at run time, which this does not follow: none is today, and one is a row
    this misses until it is added.
    """
    return {
        "/".join(parts[parts.index(".github") :])
        for path in TEMPLATES.rglob("*")
        if path.is_file() and ".github" in (parts := path.relative_to(TEMPLATES).parts)
    }


def outbound_programs(launches: list[Launch]) -> set[str]:
    """The README rows `launches` can reach, and every file the templates write under
    `.github/`."""
    rows = set().union(*(classify(launch)[0] or NO_ROWS for launch in launches))
    return rows | github_files()


def readme_outbound_rows() -> set[str]:
    """The first code span of each row's Program cell in README's network section."""
    match = _SENDS_SECTION.search(README.read_text(encoding="utf-8"))
    assert match, "README.md has no ## What stayfixed sends where section"
    keys = []
    for line in match.group(1).splitlines():
        if not line.startswith("| ") or line.startswith("| Program |"):
            continue
        cells = line.strip("|").split(" | ")
        span = _CODE_SPAN.search(cells[0])
        assert len(cells) == 4 and span is not None, line
        keys.append(span.group(1))
    # One row per key: a second row for a program would be two declarations that can disagree.
    assert len(keys) == len(set(keys)), keys
    return set(keys)


def _plugin_installs() -> list[tuple[str, ...]]:
    """Every argv `_install_plugins` builds, from the lambdas it builds them with."""
    from stayfixed.setup.run import _MARKETPLACE_ADD, _PLUGIN_INSTALL

    builders: list[tuple[Callable[[str], list[str]], str]] = [
        *((build, "owner/marketplace") for build in _MARKETPLACE_ADD.values()),
        *((build, "plugin@marketplace") for build in _PLUGIN_INSTALL.values()),
    ]
    return [tuple(build(value)) for build, value in builders]


def _shown(argv: Argv) -> tuple[str | None, ...]:
    return tuple(None if isinstance(part, Unread) else part for part in argv)


def test_no_module_imports_a_network_or_native_module() -> None:
    # `urllib.parse` and `http.HTTPStatus` reach nothing, so the match is on modules, not roots.
    # The entries in `mutations/` that name this test are its declared mutations. By hand:
    # src/stayfixed/runner.py imports `ctypes` -> this reddens; the match moves to the root ->
    # the `urllib.parse` that src/stayfixed/docs/hygiene.py imports reads as `urllib.request`. A
    # walk-based assertion states its walk is non-empty: `package_files` globs only the top of
    # the package -> the floor reddens.
    assert len(package_files(SRC)) >= MODULES_FLOOR
    assert forbidden_imports(SRC) == []


def test_a_module_is_the_file_the_tree_lists_under_its_exact_name() -> None:
    # On a disk that folds case, as macOS's does by default, asking the disk found
    # `scaffold/manifest.py` for `stayfixed.scaffold.Manifest`, so the class `Manifest` that
    # `overlay/create.py` imports from `stayfixed.scaffold` was read as a module there and as a name
    # on Linux: the walk read one tree two ways. No declared entry: the oracle's CI job runs on a
    # case-sensitive disk, where asking the disk again answers the same and the mutation survives.
    # By hand on macOS: `_module_file` asks `(ROOT / candidate).is_file()` again -> the first
    # assertion reddens.
    assert _module_file("stayfixed.scaffold.Manifest") is None
    assert _module_file("stayfixed.scaffold.manifest") == "src/stayfixed/scaffold/manifest.py"


def test_both_import_forms_name_the_module_they_reach() -> None:
    # The tree imports no forbidden module either way, so the walk above cannot tell the two
    # forms apart on its own. Mutation: `import a.b` names only `a` -> the first reddens.
    # Mutation: `from a import b` stops naming `a.b` -> the second reddens.
    assert "urllib.request" in imported_modules(ast.parse("import urllib.request"))
    assert "urllib.request" in imported_modules(ast.parse("from urllib import request"))


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        ("asyncio.streams", True),
        ("logging.config", True),
        ("_socket", True),
        ("ctypes.util", True),
        ("_posixsubprocess", True),
        ("urllib.parse", False),
        ("logging", False),
    ],
)
def test_a_listed_module_is_forbidden_with_its_submodules(module: str, forbidden: bool) -> None:
    # The entries in `mutations/` that name this test are its declared mutations. By hand: the
    # match moves to the root -> `urllib.parse` reads as `urllib.request`'s.
    assert _within(module, FORBIDDEN_MODULES) is forbidden


# Each shape a launch can take, as a package file holding it, and what the walk must read of its
# argv (`None`: an element it cannot read). The tree holds none of most of them, so the walk over
# the tree alone cannot show they are seen.
TOP, NESTED = "src/stayfixed/probe.py", "src/stayfixed/docs/probe.py"
GIT_RUN = "from stayfixed.gitenv import git_run\n"
LAUNCH_SHAPES: dict[str, tuple[str, str, tuple[str | None, ...]]] = {
    "getoutput": (TOP, "import subprocess\nsubprocess.getoutput('curl x')", (None,)),
    "getstatusoutput": (TOP, "import subprocess as sp\nsp.getstatusoutput('curl x')", (None,)),
    "imported-by-name": (TOP, "from subprocess import getoutput\ngetoutput('curl x')", (None,)),
    "keyword-args": (TOP, "import subprocess\nsubprocess.run(args=['curl', 'x'])", ("curl", "x")),
    "runner": (TOP, "runner.launch(argv, root)", (None,)),
    "runner-call": (TOP, "subprocess_runner().launch(['curl', 'x'], r)", ("curl", "x")),
    "runner-misnamed": (TOP, "go.launch(argv, root)", (None,)),
    "runner-subscripted": (TOP, "RUNNERS['x'].launch(argv, root)", (None,)),
    "runner-keyword": (TOP, "self.go.launch(argv=['curl', 'x'], cwd=r)", ("curl", "x")),
    "relative": (TOP, "from .gitenv import git_run\ngit_run(r, 'fetch')", ("git", "fetch")),
    "relative-up": (NESTED, "from ..gitenv import git_run as g\ng(r, 'fetch')", ("git", "fetch")),
    "relative-module": (TOP, "from . import gitenv\ngitenv.git_run(r, 'fetch')", ("git", "fetch")),
    "dotted-module": (
        TOP,
        "import stayfixed.gitenv\nstayfixed.gitenv.git_run(r, 'fetch')",
        ("git", "fetch"),
    ),
    "re-export": (
        TOP,
        "from stayfixed.docs.trail import git_run as g\ng(r, 'push', 'origin', 'HEAD')",
        ("git", "push", "origin", "HEAD"),
    ),
    "re-export-module": (
        TOP,
        "from stayfixed.docs import trail\ntrail.git_run(r, 'push')",
        ("git", "push"),
    ),
    "derived": (
        TOP,
        "from stayfixed.gitenv import git_answer\ngit_answer(r, 'push')",
        ("git", "push"),
    ),
    "derived-here": (
        TOP,
        f"{GIT_RUN}def ask(r, *args):\n    return git_run(r, '-c', 'x=y', *args)\nask(r, 'push')",
        ("git", "-c", "x=y", "push"),
    ),
    "derived-list": (
        TOP,
        "def gh(go, argv, cwd):\n    return go.launch(['gh', *argv], cwd)\ngh(r, ['api'], c)",
        ("gh", "api"),
    ),
    "derived-under-try": (
        TOP,
        f"{GIT_RUN}try:\n    import x\nexcept ImportError:\n    def ask(r, *a):\n"
        "        return git_run(r, *a)\nask(r, 'push')",
        ("git", "push"),
    ),
    "parameter-rebound": (
        TOP,
        "import subprocess\ndef f(argv):\n    argv = ['curl', 'x']\n    subprocess.run(argv)\n"
        "f(['git', 'status'])",
        (None,),
    ),
    "star-before-the-argv": (TOP, f"{GIT_RUN}git_run(*xs, 'status')", (None,)),
    "constant-rebound": (
        TOP,
        f"{GIT_RUN}ARGS = ('status',)\nARGS = ('push', 'origin')\ngit_run(r, *ARGS)",
        ("git", None),
    ),
    "constant-augmented": (
        TOP,
        f"{GIT_RUN}ARGS = ['status']\nARGS += ['x']\ngit_run(r, *ARGS)",
        ("git", None),
    ),
    "constant-mutated": (
        TOP,
        f"{GIT_RUN}ARGS = ['status']\nARGS.insert(0, 'push')\ngit_run(r, *ARGS)",
        ("git", None),
    ),
    "constant-shadowed": (
        TOP,
        f"{GIT_RUN}ARGS = ('status',)\ndef f():\n    ARGS = ('push',)\n    git_run(r, *ARGS)",
        ("git", None),
    ),
    "asyncio-exec": (
        TOP,
        "import asyncio\nasyncio.create_subprocess_exec('curl', 'x')",
        ("curl", "x"),
    ),
    "asyncio-shell": (TOP, "import asyncio\nasyncio.create_subprocess_shell('curl x')", (None,)),
    "loop": (TOP, "loop.subprocess_exec(factory, 'curl', 'x')", (None,)),
    "pty": (TOP, "import pty\npty.spawn(['curl', 'x'])", ("curl", "x")),
    "os-exec": (TOP, "import os\nos.execvp('curl', ['curl', 'x'])", (None,)),
    "os-system": (TOP, "from os import system\nsystem('curl x')", (None,)),
    "os-fexec": (TOP, "import os\nos.fexecve(fd, ['curl', 'x'], env)", (None,)),
    "posix": (TOP, "import posix\nposix.system('curl x')", (None,)),
    "nt": (TOP, "from nt import system\nsystem('curl x')", (None,)),
    "submodule-import": (TOP, "import os.path\nos.system('curl x')", (None,)),
    "shadowed-by-def": (
        TOP,
        "from subprocess import run\ndef run(): ...\nrun(['curl', 'x'])",
        ("curl", "x"),
    ),
    "alias": (TOP, "import subprocess\nlaunch = subprocess.run", (None,)),
    "partial": (TOP, "import functools, subprocess\nfunctools.partial(subprocess.run, x)", (None,)),
    "dunder-call": (TOP, "import subprocess\nsubprocess.run.__call__(['curl', 'x'])", (None,)),
    "in-annotation": (
        TOP,
        "import subprocess\ndef f(x: subprocess.run(['curl', 'x'])): pass",
        ("curl", "x"),
    ),
    "in-annotation-argument": (
        TOP,
        "import subprocess\ndef f(x: g(subprocess.run)): pass",
        (None,),
    ),
    "callback": (TOP, f"{GIT_RUN}retry(git_run, r)", (None,)),
    "module-alias": (TOP, "import subprocess\nm = subprocess\nm.run(['curl', 'x'])", (None,)),
    "module-handed-on": (TOP, "import os\nretry(os, r)", (None,)),
    "module-in-a-class": (TOP, "import subprocess\nclass C:\n    sp = subprocess", (None,)),
    "getattr-literal": (
        TOP,
        "import subprocess\ngetattr(subprocess, 'run')(['curl', 'x'])",
        (None,),
    ),
    "getattr-computed": (TOP, "import subprocess\ngetattr(subprocess, name)", (None,)),
    "package-module-alias": (
        TOP,
        "from stayfixed import gitenv\nm = gitenv\nm.git_run(r, 'push')",
        (None,),
    ),
    "package-module-handed-on": (TOP, "from . import gitenv\nretry(gitenv, r)", (None,)),
    "runner-handed-on": (TOP, "retry(self._runner.launch, argv)", (None,)),
    "star-subprocess": (TOP, "from subprocess import *\ngetoutput('curl x')", (None,)),
    "star-os": (TOP, "from os import *\nsystem('curl x')", (None,)),
    "star-posix": (TOP, "from posix import *\nsystem('curl x')", (None,)),
    "star-launcher": (TOP, "from stayfixed.gitenv import *\ngit_run(r, 'fetch')", (None,)),
    "star-re-export": (
        TOP,
        "from stayfixed.guards.attribute import *\ngit_run(r, 'push')",
        (None,),
    ),
    "method-forwarder": (
        TOP,
        f"{GIT_RUN}class G:\n    def ask(self, *args):\n        return git_run(r, *args)",
        ("git", None),
    ),
}


@pytest.mark.parametrize(("file", "source", "argv"), LAUNCH_SHAPES.values(), ids=LAUNCH_SHAPES)
def test_a_launch_of_any_shape_is_found(
    file: str, source: str, argv: tuple[str | None, ...]
) -> None:
    # One case per shape, so that each is proved seen on its own. The entries in `mutations/`
    # that name this test redden the cases they list. By hand, each reddening its cases:
    # `getoutput` joins `SUBPROCESS_INERT` (getoutput, imported-by-name); `_dotted` reads only a
    # bare name (dotted-module);
    # `asyncio`, `pty`, the event loop and `os` each leave the launcher tables (their cases);
    # `fexec` leaves `OS_LAUNCH_PREFIXES` (os-fexec); `_derive` derives nothing (the derived
    # cases); `LAUNCHER_MODULES` loses `subprocess` and `os` (star-subprocess, star-os).
    assert [_shown(launch.argv) for launch in WALK.launches_in(source, file)] == [argv]


# A function that hands its argv on in more than one call is no launcher: each of its launches
# stays a finding, where deriving it from one would let the other pass unread.
HANDED_ON_TWICE: dict[str, tuple[str, list[tuple[str | None, ...]]]] = {
    "two-launchers": (
        f"{GIT_RUN}import subprocess\ndef f(*args):\n    subprocess.run(['curl', *args])\n"
        "    git_run(r, *args)\nf('status')",
        [("curl", None), ("git", None)],
    ),
    "fetch-then-merge-base": (
        f"{GIT_RUN}def fork(root, *refs):\n    git_run(root, 'fetch', 'origin', *refs)\n"
        "    return git_run(root, 'merge-base', *refs)[1]\nfork(r, 'a', 'b')",
        [("git", "fetch", "origin", None), ("git", "merge-base", None)],
    ),
    "a-second-configured": (
        f"{GIT_RUN}def f(r, *args):\n    git_run(r, *args)\n    git_run(r, '-c', cfg, *args)\n"
        "f(r, 'status')",
        [("git", None), ("git", "-c", None, None)],
    ),
    "one-per-branch": (
        f"{GIT_RUN}import sys\nif sys.platform == 'win32':\n    def ask(r, *a):\n"
        "        return git_run(r, *a)\nelse:\n    def ask(r, *a):\n"
        "        return git_run(r, '-c', cfg, *a)\nask(r, 'push')",
        [("git", None), ("git", "-c", None, None)],
    ),
}


@pytest.mark.parametrize(("source", "argvs"), HANDED_ON_TWICE.values(), ids=HANDED_ON_TWICE)
def test_a_function_that_hands_its_argv_on_twice_is_no_launcher(
    source: str, argvs: list[tuple[str | None, ...]]
) -> None:
    # The entry in `mutations/` that names this test derives such a function from its first
    # handing on again, which exempts that one and reads the function's callers through it.
    assert [_shown(launch.argv) for launch in WALK.launches_in(source, TOP)] == argvs


def test_what_only_names_a_launcher_is_not_a_launch() -> None:
    # `probe.run(context)`, `gate.run(root, config, base)` and `handler.run(view, session)` are the
    # package's own in-process `.run`s, and a runner launches through `.launch`, so a `.run` handed
    # a list is not a runner's either. Mutation: every `.run` is a launch -> all four are found.
    # Nor is a name that only mentions a launcher's module: an annotation, a constant, an
    # exception. Mutation: the reference check runs inside annotations -> `Popen[bytes]` is found.
    # Nor a class `isinstance` or `issubclass` compares. Mutation: `CLASS_CHECKS` is emptied ->
    # the last two lines' `Popen`s are found. Nor a launcher module `getattr` or `hasattr` reads a
    # literal attribute of that is no launcher, or `hasattr` only asks about. The entry in
    # `mutations/` that names this test reads such a module as handed on again.
    source = "probe.run(context)\ngate.run(root, config, base)\nhandler.run(view, session)\n"
    source += "step.run([view], config)\n"
    source += "import subprocess\nraise subprocess.TimeoutExpired(args, 1)\n"
    source += "def f(p: subprocess.Popen[bytes]) -> None:\n    stdin = subprocess.DEVNULL\n"
    source += "from os import path\nimport os.path\nos.path.join(a, b)\n"
    source += "isinstance(p, subprocess.Popen)\nissubclass(t, (int, subprocess.Popen))\n"
    source += "getattr(os, 'O_NOFOLLOW', 0)\nhasattr(os, 'waitid')\nhasattr(subprocess, 'run')"
    assert WALK.launches_in(source, "src/stayfixed/assess/probe.py") == []


def test_every_launch_is_classified() -> None:
    # The entries in `mutations/` that name this test are its declared mutations. By hand:
    # `VOUCHED_ELEMENTS` loses `gitenv`'s `base` -> `merge-base` hands an unread element before
    # its options end.
    launches = WALK.launches(SRC)
    # A walk-based assertion states its walk is non-empty: a launcher the walk stopped
    # recognising would take its launches out of every check here and leave them all green.
    # Mutation: `package_files` globs only the top of the package -> the floor reddens.
    assert len(launches) >= LAUNCHES_FLOOR, len(launches)
    assert unclassified(launches) == []


def test_the_declarations_name_exactly_what_the_classification_rests_on() -> None:
    # Equality, both ways: an entry whose launch moved or went would go on exempting a value
    # nothing hands, ready for the next launch that hands it. The entry in `mutations/` that
    # names this test adds such an entry. By hand: the `_custom.run` entry's function is renamed
    # -> it names nothing, and the launch it named is undeclared.
    relied = set().union(*(classify(launch)[1] for launch in WALK.launches(SRC)))
    assert relied == PASS_THROUGH.keys() | VOUCHED_ELEMENTS.keys()


@pytest.mark.parametrize(
    "extra",
    [
        "            runner.launch(list(EXTRA), home)\n",
        "            argv = ['curl', 'x']\n            runner.launch(argv, home)\n",
    ],
    ids=["another-expression", "the-same-expression-rebound"],
)
def test_a_declaration_covers_only_the_launch_it_names(extra: str) -> None:
    # A declaration is about one value handed to one launch, so a second launch in a declared
    # function is unclassified, whether it hands another expression or the declared one after
    # binding it again. The entries in `mutations/` that name this test key a declaration on its
    # function alone again, and stop holding a declared element to one binding.
    installs = "src/stayfixed/setup/run.py"
    source = (ROOT / installs).read_text(encoding="utf-8")
    done = "            done = runner.launch(argv, home)\n"
    launches = WALK.launches_in(source.replace(done, done + extra), installs)
    assert [launch.line for launch in unclassified(launches)] != []


def test_every_table_entry_names_a_live_launch() -> None:
    # A classification no launch uses is a promise about nothing, as a dead declaration is. The
    # plugin installs' argvs are built by lambdas, so they are counted from the lambdas. The entry
    # in `mutations/` that names this test puts a dead row in `NETWORK`. By hand, each reddening
    # its assertion: `("git", "show")` joins `LOCAL`; `("git", "stash")` joins `LOCAL_WHOLE`;
    # `--bare` joins `GIT_GLOBAL_OPTIONS`; `core.sshCommand` joins `GIT_CONFIG_KEYS`.
    commands: list[Argv] = [
        split[1]
        for launch in WALK.launches(SRC)
        if classify(launch)[0] is not None and (split := _command(launch.argv)) is not None
    ]
    commands += _plugin_installs()
    launched = [launch.argv for launch in WALK.launches(SRC)]

    def live(prefix: tuple[str, ...]) -> bool:
        return any(command[: len(prefix)] == prefix for command in commands)

    assert [prefix for prefix in NETWORK if not live(prefix)] == []
    assert [prefix for prefix in LOCAL if not live(prefix)] == []
    assert [whole for whole in LOCAL_WHOLE if whole not in commands] == []
    assert [o for o in GIT_GLOBAL_OPTIONS if not any(o in argv for argv in launched)] == []
    settings = {
        str(value).partition("=")[0]
        for argv in launched
        for option, value in pairwise(argv)
        if option == "-c"
    }
    assert sorted(GIT_CONFIG_KEYS - settings) == []


@pytest.mark.parametrize(
    "source",
    [
        "git_run(root, 'remote', 'update')",
        "git_run(root, 'remote', *more)",
        "git_run(root, 'archive', '--remote=git@example.com:x', 'HEAD')",
        "git_run(root, 'archive', '--format=tar', '-o', 'x.tar', '--remote', 'example', 'HEAD')",
        "git_run(root, 'worktree', 'add', '../elsewhere')",
        "git_run(root, 'config', 'core.sshCommand', 'curl x')",
        "git_run(root, 'grep', '-Ocurl', 'x')",
        "git_run(root, 'grep', '--open-files-in=echo', 'x')",
        "git_run(root, 'grep', '--textc', 'x')",
        "git_run(root, 'grep', '-lOecho', 'x')",
        "git_run(root, 'cat-file', '--filters', 'HEAD:x')",
        "git_run(root, 'diff', '--ext-diff', 'HEAD')",
        "git_run(root, 'archive', *opts)",
        "git_run(root, 'ls-files', *opts, '--', *paths)",
        "git_run(root, 'log', revisions)",
        "git_run(root, '-c', setting, 'status')",
        "git_run(root, '-c', 'core.sshCommand=ssh -o ProxyCommand=x', 'fetch')",
        "git_run(root, '--config-env=core.fsmonitor=VARIABLE', 'status')",
    ],
    ids=[
        "remote-update",
        "remote-spread",
        "archive-remote",
        "archive-remote-late",
        "worktree-add",
        "config-write",
        "grep-pager",
        "grep-pager-abbreviated",
        "grep-textconv-abbreviated",
        "grep-pager-bundled",
        "cat-file-filters",
        "diff-external",
        "spread-options",
        "spread-before-paths",
        "unread-operand",
        "unread-configuration",
        "configuration-not-listed",
        "global-option-not-listed",
    ],
)
def test_a_local_subcommand_in_a_form_that_reaches_a_remote_is_unclassified(source: str) -> None:
    # `LOCAL` is as narrow as each subcommand's other forms need, and a launch is local only
    # when nothing before its options end is unread and no option there runs a program. The
    # entries in `mutations/` that name this test redden the cases they list. By hand:
    # `("git", "remote")` back in `LOCAL` -> remote-update passes; `("git", "worktree")` for
    # `("git", "worktree", "list")` -> worktree-add; `("git", "config")` for its read form ->
    # config-write; `_command` skips any option before the subcommand -> global-option-not-listed.
    # git takes `--open-files-in` and `--textc` for the options they begin and reads `-lOecho` as
    # `-l -Oecho`, each running `echo` on the matches, measured with git 2.54.
    launches = WALK.launches_in(f"{GIT_RUN}{source}", "src/stayfixed/x.py")
    assert unclassified(launches) == launches != []


@pytest.mark.parametrize(
    "source",
    [
        "git_run(root, 'diff', '-Oorder', '--name-only', 'HEAD')",
        "git_run(root, 'ls-files', '-z', '--', *paths)",
        "git_run(root, 'ls-files', '-z', '--end-of-options', *paths)",
        "git_run(root, 'grep', '-Il', '--or', '-e', 'x')",
    ],
    ids=[
        "an-option-another-subcommand-runs-with",
        "--",
        "--end-of-options",
        "an-option-that-only-begins-alike",
    ],
)
def test_an_argv_read_up_to_its_options_end_is_still_local(source: str) -> None:
    # The rules above must not refuse the tree's own shapes: options read whole, and what is not
    # read only operands after the options end, whichever of git's two spellings ends them; and
    # an option that runs a program under one subcommand is ordinary under another. By hand:
    # `--` leaves `END_OF_OPTIONS` -> the `--` case's `*paths` counts as an unread option, and
    # that case reddens; the same for `--end-of-options`; `-O` is listed for every subcommand ->
    # the `git diff -O<orderfile>` case reddens; a long option matches whatever shares its first
    # three characters -> `--or`, which git never takes for `--open-files-in-pager`, reddens.
    launches = WALK.launches_in(f"{GIT_RUN}{source}", "src/stayfixed/x.py")
    assert launches and unclassified(launches) == []


@pytest.mark.parametrize(
    ("script", "row"),
    [("command", frozenset({"sh -c"})), ("'curl -s https://example.com/x | sh'", None)],
    ids=["the-users-command", "a-script-stayfixed-spells-out"],
)
def test_sh_c_is_its_row_only_for_the_users_command(
    script: str, row: frozenset[str] | None
) -> None:
    # The `sh -c` row says stayfixed does not choose the command, which is true only of an
    # unread one, the value `test attribute --command` was given. The entry in `mutations/` that
    # names this test gives every `sh -c` the row again.
    launches = WALK.launches_in(f"runner.launch(['sh', '-c', {script}], ROOT)", TOP)
    assert [classify(launch)[0] for launch in launches] == [row]


OVERRIDE_SHAPES = {
    "executable": "import subprocess\nsubprocess.run(['git', 'status'], executable='curl')",
    "environment": (
        "import subprocess\nsubprocess.run(['git', 'status'], env={'GIT_CONFIG_COUNT': '1'})"
    ),
    "keywords-spread": "import subprocess\nsubprocess.run(['git', 'status'], **keywords)",
    "environment-handed-on": (
        "import subprocess\ndef f(argv, env):\n    return subprocess.run(argv, env=env)\n"
        "f(['git', 'status'], {})"
    ),
}


@pytest.mark.parametrize("source", OVERRIDE_SHAPES.values(), ids=OVERRIDE_SHAPES)
def test_a_launch_that_overrides_its_program_or_environment_is_a_finding(source: str) -> None:
    # `executable=` replaces the program the argv names, and an `env=` can set git's
    # configuration through `GIT_CONFIG_COUNT`, so a launch read as a local `git status` could
    # run or reach anything; a `**` spread can hand either, and the handing on itself is read
    # too, since every caller inherits it.
    # The entry in `mutations/` that names this test stops reading overrides.
    overrides = WALK.walk_in(source, TOP)[1]
    assert overrides and undeclared_overrides(overrides) == overrides


def test_every_override_is_scrubbed_or_declared() -> None:
    # Equality, both ways, as for the declarations: `git_run`'s and `tar`'s `env=scrubbed_env()`
    # need no entry, and the two inherited environments are declared with their reasons. By hand:
    # the runner's entry is renamed -> its `env=env` is undeclared and the entry names nothing.
    overrides = WALK.overrides(SRC)
    assert len(overrides) >= 3
    assert {key for o in overrides if (key := _override_key(o))} == OVERRIDES.keys()


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.environ['GIT_CONFIG_COUNT'] = '1'",
        "from os import environ\nenviron.update(GIT_SSH_COMMAND='curl')",
        "import os\nos.environ |= {'GIT_DIR': 'x'}",
        "import posix\nposix.putenv('GIT_DIR', 'x')",
        "import os\ndel os.environ['PATH']",
    ],
    ids=["item", "update", "augmented", "putenv", "delete"],
)
def test_a_change_to_the_environment_every_launch_inherits_is_found(source: str) -> None:
    # A launch that inherits the environment inherits whatever the package wrote into it, so a
    # write anywhere changes what every runner launch after it reaches. The entry in
    # `mutations/` that names this test stops recognising `os.environ`; by hand, `putenv` leaves
    # `ENVIRONMENT_CALLS` -> the putenv case reddens.
    assert len(WALK.environment_writes_in(source, TOP)) == 1


def test_no_module_changes_the_environment_every_launch_inherits() -> None:
    # Mutation: src/stayfixed/cli.py sets `os.environ["X"] = "1"` -> this reddens.
    assert WALK.environment_writes(SRC) == []


def test_the_plugin_installs_reach_the_rows_their_entries_name() -> None:
    # `PASS_THROUGH` names `_install_plugins`'s rows by hand, because its argvs are built by
    # lambdas the walk does not call. This calls them. Mutation: `_PLUGIN_INSTALL["codex"]`
    # builds a `codex mcp add` -> it reaches no row, and this reddens.
    reached = {_row(argv) for argv in _plugin_installs()}
    declared = [rows for key, rows in PASS_THROUGH.items() if key[1] == "_install_plugins"]
    assert declared and all(rows == reached for rows in declared)
    claude = {_row(argv) for argv in _plugin_installs() if argv[0] == "claude"}
    restored = [rows for key, rows in PASS_THROUGH.items() if key[1] == "install_listed"]
    assert len(restored) == 2 and all(rows == claude for rows in restored)


def test_the_rendered_plugins_install_reaches_the_rows_its_entries_name() -> None:
    # `PASS_THROUGH` names `attach`'s install rows and `detach`'s withdrawal rows by hand, because
    # each argv is a table whose slot is filled at the call. This fills them. Mutation:
    # `PLUGIN_INSTALL_LOCAL` or `PLUGIN_UNINSTALL_LOCAL` spelled as `codex plugin …` -> it reaches
    # another row, and this reddens.
    from stayfixed.attach.render import (
        PLUGIN_INSTALL_LOCAL,
        PLUGIN_MARKETPLACE_ADD_LOCAL,
        PLUGIN_MARKETPLACE_REMOVE,
        PLUGIN_UNINSTALL_LOCAL,
        filled,
    )

    tables = (
        PLUGIN_MARKETPLACE_ADD_LOCAL,
        PLUGIN_INSTALL_LOCAL,
        PLUGIN_UNINSTALL_LOCAL,
        PLUGIN_MARKETPLACE_REMOVE,
    )
    reached = {_row(tuple(filled(table, "x"))) for table in tables}
    named = ("_install", "_withdraw_plugin")
    declared = [rows for key, rows in PASS_THROUGH.items() if key[1] in named]
    assert len(declared) == 4 and all(rows == reached == {"claude plugin"} for rows in declared)


def test_the_readme_declares_every_program_that_reaches_a_network() -> None:
    # Both directions: a launch with no row is an undisclosed destination, which the directory's
    # security scan rejects; a row with no launch is a promise about nothing. Every file the
    # templates write under `.github/` is a row as well, because GitHub runs it. The entries in
    # `mutations/` that name this test are its declared mutations. By hand: the README drops the
    # `.github/dependabot.yml` row -> this reddens.
    assert outbound_programs(WALK.launches(SRC)) == readme_outbound_rows()
