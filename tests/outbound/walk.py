"""The outbound walk: every process stayfixed's package starts, found in the package's syntax.

`tests/test_outbound.py` holds README.md's "What stayfixed sends where" to what this walk finds,
and this docstring is the one description of what it sees and what it cannot.

**What it finds.** A *launch* is a call that starts a process, a launcher named without being
called — handed to `functools.partial`, passed as a callback, bound to another name, used as a
base class — a star import of a launcher module or of a package module, which can re-export
one, or either kind of module named without an attribute after it (`m = subprocess`, `f(os)`,
`m = gitenv`), which hands on every launcher it holds. `getattr` and `hasattr` given a literal
name read the attribute it names, so `getattr(os, "O_NOFOLLOW", 0)` uses `os` rather than
handing it on, and `getattr(subprocess, "run")` names the launcher. The standard library's
launchers are `subprocess`, the `os` process functions (reached through `os`, `posix` or `nt`),
`pty.spawn`, `asyncio`'s subprocess calls and an event loop's.
The package's own start from the roots `tests/outbound/policy.py` names and grow by derivation:
a module-level function — one defined at the top of its module, or under a module-level `if`,
`try` or `with` — that hands its own argv on to a launcher in exactly one call, as the argv's
last part, is a launcher too, read at its callers. Its argv is its `*args`, or a list parameter,
spread or whole, that the function never rebinds or mutates. A function that hands its argv on
in two calls, a method and a nested function are not launchers: their own launches stay
findings until declared. A `Runner`'s `.launch` is a launcher by its attribute alone, whatever
holds the runner — a parameter, an attribute, a subscript, a call's result: no other method in
the package is named `launch`, and one that came to be would be read as a launch too, a finding
to read rather than a launch missed. A name is followed through every import, relative, dotted
or a re-export, to the module that defines it, a package module being one of the files the tree
lists under that exact name, whether or not the disk folds case.

**What it reads.** Each launch's argv, element by element: a string literal, or a module
constant holding a string or a list of strings, is read; anything else is `Unread`, carrying its
source text. A constant is one name the module binds exactly once and never mutates, so a
rebinding, an augmented assignment, an `.append` or a parameter of the same name makes it
`Unread`. A launch whose argv the walk cannot read at all — a shell string, a launcher handed on,
a starred argument before the argv's position — is one `Unread`. Each launch's `env=`,
`executable=` and `**` spread are recorded beside it as an `Override`: the first replaces what
the launch inherits, the second the program it runs, and the third can hand either.
`isinstance` and `issubclass` only compare a class, so a launcher named there is not handed on;
nor is one named as a type in an annotation, though a call there still runs, and is walked, when
the annotation is evaluated.

**What it cannot see.** The walk reads syntax, so a launch whose program, argv, environment or
receiver is decided by data flow it does not follow is beyond it. Each of these is probed to
return nothing:

- dynamic dispatch: `importlib.import_module`, `__import__`, `sys.modules`, and code run from
  data by `exec`, `eval` or `pickle`;
- aliasing: a launcher named as `Annotated` metadata, which code reading the annotation could
  call;
- values computed at run time: an argv element held in a variable is `Unread`, and the walk
  does not follow where its value came from;
- launches and connections the standard library makes on the package's behalf, at import or
  when called: `uuid.getnode()` can run `ifconfig`, `platform.architecture()` runs `file`,
  `xml.sax` fetches an external entity through `urllib.request`, `pydoc.browse` serves HTTP and
  `email.utils.make_msgid` asks DNS through `socket`, none of which the package imports by
  name;
- a process of the running interpreter that `multiprocessing` or `concurrent.futures` starts,
  which runs the package's own code rather than another program.

`ctypes`, `_posixsubprocess` and `_winapi` start a process through no launcher the walk knows,
so the outbound test forbids importing them, beside the network modules, rather than walking
them.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cache, cached_property
from pathlib import Path
from typing import TypeAlias

from stayfixed.runner import Runner

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "stayfixed"


@dataclass(frozen=True)
class Launcher:
    """How a launcher takes its argv. `program` is what it puts first itself; the rest is the
    call's arguments from position `at` on when `spread`, or else the one list at position `at`
    or under `keyword`. A launcher that does not `read` takes a shell string."""

    program: tuple[str, ...] = ()
    at: int = 0
    spread: bool = False
    keyword: str | None = None
    reads: bool = True


@dataclass(frozen=True)
class Unread:
    """An argv element the walk cannot read, by its source text. `spread` when it stands for any
    number of elements; `stable` when every name in it is bound once in its function and never
    mutated, so the text names one value wherever it is handed."""

    text: str
    spread: bool = False
    stable: bool = True


Element: TypeAlias = str | Unread


@dataclass(frozen=True)
class Launch:
    """One launch: where it is — `function` is the dotted name of the function or class it sits
    in — and its argv, as far as the walk reads it."""

    file: str
    line: int
    function: str
    argv: tuple[Element, ...]


@dataclass(frozen=True)
class Override:
    """A launch's `env=`, `executable=` or `**` spread, by its source text (`env=env`, `**kw`),
    and the package function its value is a call to, as `(file, function)`, if it is one."""

    file: str
    line: int
    function: str
    text: str
    calls: tuple[str, str] | None


SUBPROCESS = Launcher(keyword="args")
RUNNER = Launcher(keyword="argv")
# The method a `Runner` launches through, known by its name alone.
RUNNER_METHOD = Runner.launch.__name__
SHELL = Launcher(reads=False)
# Every standard-library function that starts a process and takes an argv the walk can read, by
# `(module, function)`.
STDLIB_LAUNCHERS: dict[tuple[str, str], Launcher] = {
    ("subprocess", "run"): SUBPROCESS,
    ("subprocess", "Popen"): SUBPROCESS,
    ("subprocess", "call"): SUBPROCESS,
    ("subprocess", "check_call"): SUBPROCESS,
    ("subprocess", "check_output"): SUBPROCESS,
    ("pty", "spawn"): Launcher(keyword="argv"),
    ("asyncio", "create_subprocess_exec"): Launcher(spread=True),
    ("asyncio", "create_subprocess_shell"): SHELL,
}
# A call to any other `subprocess` name is a launch too — `getoutput` and `getstatusoutput` take a
# shell string — except these, which start nothing. So is a call to `os.system`, `os.popen`,
# `os.startfile` and the `exec`, `fexec`, `spawn` and `posix_spawn` families, and to an event
# loop's `subprocess_exec` and `subprocess_shell` on whatever loop a call holds. The walk reads
# none of their argvs.
SUBPROCESS_INERT = frozenset(
    {
        "CalledProcessError",
        "CompletedProcess",
        "SubprocessError",
        "TimeoutExpired",
        "list2cmdline",
        "DEVNULL",
        "PIPE",
        "STDOUT",
    }
)
OS_LAUNCH_PREFIXES = ("system", "popen", "startfile", "exec", "fexec", "spawn", "posix_spawn")
LOOP_LAUNCHES = frozenset({"subprocess_exec", "subprocess_shell"})
# `os` takes its process functions from `posix`, or from `nt` on Windows, so a call through either
# is a call through `os`.
OS_MODULES = frozenset({"os", "posix", "nt"})
# The modules whose names are launchers: a star import of one binds names the walk cannot follow.
LAUNCHER_MODULES = OS_MODULES | {module for module, _ in STDLIB_LAUNCHERS}
# The calls that only compare a class, by the name they are called through.
CLASS_CHECKS = frozenset({"isinstance", "issubclass"})
# The calls that read an attribute by a name a string gives, by the name they are called through:
# `getattr(os, "O_NOFOLLOW", 0)` is `os.O_NOFOLLOW`, and `hasattr` only asks whether one exists.
ATTRIBUTE_READS = frozenset({"getattr", "hasattr"})
# The keywords of a launch that replace what it inherits or what it runs; a `**` spread is read as
# an override too, since it can hand either.
OVERRIDING = frozenset({"env", "executable"})
# The `os` functions that change the process's environment without going through `os.environ`.
ENVIRONMENT_CALLS = frozenset({"putenv", "unsetenv"})
# The methods that change a list, a dict or a set in place.
MUTATORS = frozenset(
    {"append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse", "update"}
    | {"setdefault", "popitem", "add", "discard", "__setitem__", "__delitem__", "__iadd__"}
)

Function: TypeAlias = ast.FunctionDef | ast.AsyncFunctionDef
Launchers: TypeAlias = dict[tuple[str, str], Launcher]
Site: TypeAlias = tuple[int, int]


@dataclass(frozen=True)
class Bindings:
    """What the names in the package file `file` are bound to: `functions` maps a bare name to
    the package function it names, as `(file, function)`; `stdlib` maps one imported by name
    from the standard library to `(module, function)`; `modules` maps a name, dotted or not, to
    the module it is. A name can be bound in more than one."""

    file: str
    functions: dict[str, tuple[str, str]]
    stdlib: dict[str, tuple[str, str]]
    modules: dict[str, str]


def package_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@cache
def _tree(file: str) -> ast.Module:
    return ast.parse((ROOT / file).read_text(encoding="utf-8"))


def imported_modules(tree: ast.Module) -> set[str]:
    """Every module `tree` imports, by dotted name: `import a.b` and `from a import b` both name
    `a.b`, because the second can import a submodule and the syntax cannot say which. Relative
    imports are left out: they name the package's own modules, never the standard library's."""
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            named.add(node.module)
            named.update(f"{node.module}.{alias.name}" for alias in node.names)
    return named


def imports(root: Path) -> list[tuple[str, str]]:
    """`(file, module)` for each module a file under `root` imports."""
    return [
        (relative(path), module)
        for path in package_files(root)
        for module in sorted(imported_modules(_tree(relative(path))))
    ]


def module_level(tree: ast.Module) -> list[Function]:
    """The functions defined at module level: at the top of the module, or under a module-level
    `if`, `try` or `with`, which still binds the name in the module. The one predicate both the
    bindings and the derivation use, so a launcher derived is a launcher its callers can name."""
    found: list[Function] = []
    pending: list[ast.stmt] = list(tree.body)
    while pending:
        node = pending.pop(0)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(node)
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith)):
            pending.extend(
                child
                for field in ("body", "orelse", "finalbody", "handlers")
                for child in getattr(node, field, [])
            )
        elif isinstance(node, ast.ExceptHandler):
            pending.extend(node.body)
    return found


def _bound_names(scope: ast.AST) -> tuple[Counter[str], set[str]]:
    """How many times each name is bound anywhere under `scope` — an assignment, a parameter, an
    import, a `def`, a `for` target, a `del` — and the names mutated there: a mutating method
    called on one, or an item of one assigned or deleted."""
    bound: Counter[str] = Counter()
    mutated: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound[node.id] += 1
        elif isinstance(node, ast.arg):
            bound[node.arg] += 1
        elif isinstance(node, ast.alias):
            bound[(node.asname or node.name).split(".")[0]] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound[node.name] += 1
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update({name: 2 for name in node.names})
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound[node.name] += 1
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            mutated.add(_dotted(node.value) or "")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATORS
        ):
            mutated.add(_dotted(node.func.value) or "")
    return bound, mutated


@cache
def _scope_names(scope: ast.AST) -> tuple[Counter[str], set[str]]:
    return _bound_names(scope)


def _stable(name: str, scope: ast.AST) -> bool:
    """Whether `name` is bound at most once under `scope` and never mutated there."""
    bound, mutated = _scope_names(scope)
    return bound[name] <= 1 and name not in mutated


def _strings(node: ast.expr | None) -> list[str] | None:
    """The strings of a tuple or list made only of string literals."""
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    strings = []
    for element in node.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            return None
        strings.append(element.value)
    return strings


def _constants(tree: ast.Module) -> dict[str, str | list[str]]:
    """The module's constants: each name bound exactly once in the whole module, at its top, to
    a string or to a tuple or list of strings, and never mutated — so it holds that value
    wherever the module reads it."""
    bound: dict[str, str | list[str]] = {}
    value: ast.expr | None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            continue
        if not isinstance(target, ast.Name) or not _stable(target.id, tree):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            bound[target.id] = value.value
        elif (strings := _strings(value)) is not None:
            bound[target.id] = strings
    return bound


@cache
def _source_files() -> frozenset[str]:
    """Every `.py` file under `src/`, relative to the root, spelled as the directory lists it."""
    return frozenset(relative(path) for path in package_files(ROOT / "src"))


def _module_file(module: str) -> str | None:
    """The package file that defines `module`, relative to the root, or `None` for any other.

    Looked up among the names the tree lists rather than asked of the disk: a disk that folds case,
    as macOS's does by default, finds `scaffold/manifest.py` for `stayfixed.scaffold.Manifest`, and
    the class `Manifest` imported from `stayfixed.scaffold` read as that module there and as a
    name everywhere else."""
    stem = module.replace(".", "/")
    for candidate in (f"src/{stem}.py", f"src/{stem}/__init__.py"):
        if candidate in _source_files():
            return candidate
    return None


def _holds_launchers(names: Bindings, node: ast.expr) -> bool:
    """Whether `node` names a module that can hold a launcher: a launcher module, or a package
    module, which can define or re-export one."""
    module = _module_of(names, node)
    if module is None:
        return False
    return module in LAUNCHER_MODULES or _module_file(module) is not None


def _imported_from(node: ast.ImportFrom, file: str) -> str:
    """The absolute module a `from … import` in `file` names: a relative one is resolved against
    the package `file` is in, one level up for each dot past the first."""
    if not node.level:
        return node.module or ""
    package = Path(file).relative_to("src").with_suffix("").parts[:-1]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


@cache
def _bindings_of(file: str) -> Bindings:
    return _bindings(_tree(file), file)


def _bindings(tree: ast.Module, file: str) -> Bindings:
    """The file's own module-level functions, and what each of its imports binds, as written: a
    name imported from a package module is bound to that module's name for it, which
    `_resolved` follows."""
    functions = {node.name: (file, node.name) for node in module_level(tree)}
    stdlib: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
                    continue
                # `import os.path` binds `os` as well, and `os.system` is then a call through it.
                parts = alias.name.split(".")
                modules.update(
                    {".".join(parts[:i]): ".".join(parts[:i]) for i in range(1, len(parts) + 1)}
                )
        elif isinstance(node, ast.ImportFrom):
            module = _imported_from(node, file)
            for alias in node.names:
                bound = alias.asname or alias.name
                if _module_file(f"{module}.{alias.name}") is not None:
                    modules[bound] = f"{module}.{alias.name}"
                elif (source := _module_file(module)) is not None:
                    functions[bound] = (source, alias.name)
                else:
                    stdlib[bound] = (module, alias.name)
    return Bindings(file, functions, stdlib, modules)


def _resolved(
    names: Bindings, name: str, seen: frozenset[tuple[str, str]] = frozenset()
) -> Bindings:
    """What `name` is, bound as `name`: a name a package module only imports is what it imports
    there, followed to the module that defines it, so `from stayfixed.docs.trail import
    git_run` is `gitenv`'s `git_run`, which `trail` imports."""
    resolved = Bindings(names.file, {}, {}, {})
    if name in names.stdlib:
        resolved.stdlib[name] = names.stdlib[name]
    if name in names.modules:
        resolved.modules[name] = names.modules[name]
    if (target := names.functions.get(name)) is None:
        return resolved
    onward = Bindings(target[0], {}, {}, {})
    if target[0] != names.file and target not in seen:
        onward = _resolved(_bindings_of(target[0]), target[1], seen | {target})
    hop = target[1]
    if hop in onward.functions:
        resolved.functions[name] = onward.functions[hop]
    if hop in onward.stdlib:
        resolved.stdlib[name] = onward.stdlib[hop]
    if hop in onward.modules:
        resolved.modules[name] = onward.modules[hop]
    if not (onward.functions or onward.stdlib or onward.modules):
        # Defined here, or bound by something other than a `def` or an import.
        resolved.functions[name] = target
    return resolved


def _lookup(module: str, name: str) -> Bindings:
    """What `module.name` is, bound as `name`, followed as `_resolved` follows it."""
    if _module_file(f"{module}.{name}") is not None:
        return Bindings("", {}, {}, {name: f"{module}.{name}"})
    if (source := _module_file(module)) is None:
        return Bindings("", {}, {name: (module, name)}, {})
    return _resolved(Bindings("", {name: (source, name)}, {}, {}), name)


def _stdlib_launcher(module: str, function: str) -> Launcher | None:
    """What a call of the standard library's `module.function` starts, if anything."""
    module = "os" if module in OS_MODULES else module
    if (module, function) in STDLIB_LAUNCHERS:
        return STDLIB_LAUNCHERS[module, function]
    if module == "subprocess" and function not in SUBPROCESS_INERT:
        return SHELL
    if module == "os" and function.startswith(OS_LAUNCH_PREFIXES):
        return SHELL
    return None


def _dotted(node: ast.expr) -> str | None:
    """`a.b.c` for an expression spelled as names and attributes, the way an import binds it."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (owner := _dotted(node.value)) is not None:
        return f"{owner}.{node.attr}"
    return None


def _module_of(names: Bindings, owner: ast.expr) -> str | None:
    """The module `owner` names, by an import of its own or one a package module re-exports."""
    dotted = _dotted(owner) or ""
    if dotted in names.modules:
        return names.modules[dotted]
    return _resolved(names, dotted).modules.get(dotted) if dotted in names.functions else None


def _function_of(expr: ast.expr, names: Bindings) -> tuple[str, str] | None:
    """The package function `expr` names, as `(file, function)`, if it names one."""
    if isinstance(expr, ast.Name):
        return _resolved(names, expr.id).functions.get(expr.id)
    if isinstance(expr, ast.Attribute) and (module := _module_of(names, expr.value)):
        return _lookup(module, expr.attr).functions.get(expr.attr)
    return None


def _bound_launcher(names: Bindings, name: str, launchers: Launchers) -> Launcher | None:
    # A name bound both ways — a `def run` beside `from subprocess import run` — is taken for the
    # launch: which binding wins depends on order, and the walk does not follow order.
    names = _resolved(names, name)
    named = names.stdlib.get(name)
    launcher = _stdlib_launcher(*named) if named else None
    package = names.functions.get(name)
    return launcher or (launchers.get(package) if package else None)


def _launcher(expr: ast.expr, names: Bindings, launchers: Launchers) -> Launcher | None:
    """The launcher the expression `expr` names, called or not, or `None` when it names none."""
    if isinstance(expr, ast.Name):
        return _bound_launcher(names, expr.id, launchers)
    if not isinstance(expr, ast.Attribute):
        return None
    if (module := _module_of(names, expr.value)) is not None:
        return _bound_launcher(_lookup(module, expr.attr), expr.attr, launchers)
    if expr.attr in LOOP_LAUNCHES:
        return SHELL
    if expr.attr == RUNNER_METHOD:
        return RUNNER
    return None


def _given(call: ast.Call, launcher: Launcher) -> ast.expr | None:
    """The one argv argument `call` hands a launcher that takes its argv whole."""
    if len(call.args) > launcher.at:
        return call.args[launcher.at]
    return next((k.value for k in call.keywords if k.arg and k.arg == launcher.keyword), None)


@dataclass(frozen=True)
class _Source:
    tree: ast.Module
    file: str
    names: Bindings
    constants: dict[str, str | list[str]]
    module_level: frozenset[int]


def _source(file: str, text: str | None = None) -> _Source:
    """The package file `file` read for the walk, or `text` read as that file."""
    if text is None:
        return _package_source(file)
    tree = ast.parse(text)
    level = frozenset(map(id, module_level(tree)))
    return _Source(tree, file, _bindings(tree, file), _constants(tree), level)


@cache
def _package_source(file: str) -> _Source:
    tree = _tree(file)
    level = frozenset(map(id, module_level(tree)))
    return _Source(tree, file, _bindings_of(file), _constants(tree), level)


def _names_stable(expr: ast.expr, scope: ast.AST) -> bool:
    return all(_stable(node.id, scope) for node in ast.walk(expr) if isinstance(node, ast.Name))


def _read(
    node: ast.expr, whole: bool, constants: dict[str, str | list[str]], scope: ast.AST
) -> list[Element]:
    """What the walk reads of one argument node: a string, a constant's strings, or an
    `Unread` — of any length when the node is spread, or when it is the whole argv."""
    spread = node.value if isinstance(node, ast.Starred) else node if whole else None
    if spread is None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.Name) and isinstance(constants.get(node.id), str):
            return [str(constants[node.id])]
        return [Unread(ast.unparse(node), stable=_names_stable(node, scope))]
    named = constants.get(spread.id) if isinstance(spread, ast.Name) else None
    if isinstance(named, list):
        return list(named)
    return [Unread(ast.unparse(node), spread=True, stable=_names_stable(node, scope))]


def _argv_nodes(call: ast.Call, launcher: Launcher) -> tuple[list[ast.expr], bool] | None:
    """The argument nodes `call` hands `launcher` as its argv, past the launcher's own
    `program`, and whether they are one expression that is the whole argv; `None` when the walk
    reads no argv there — a shell string, no argv found, or a starred argument before the argv's
    position, which moves it by a length the walk does not know."""
    if not launcher.reads or any(isinstance(a, ast.Starred) for a in call.args[: launcher.at]):
        return None
    if launcher.spread:
        return list(call.args[launcher.at :]), False
    given = _given(call, launcher)
    if given is None:
        return None
    if isinstance(given, (ast.List, ast.Tuple)):
        return list(given.elts), False
    return [given], True


def _argv(
    call: ast.Call, launcher: Launcher, constants: dict[str, str | list[str]], scope: ast.AST
) -> tuple[Element, ...]:
    """What the walk reads of the argv `call` hands `launcher`, with `scope` the outermost
    function the call sits in, or the module."""
    if (handed := _argv_nodes(call, launcher)) is None:
        return (Unread(ast.unparse(call.args[0] if call.args else call)),)
    nodes, whole = handed
    parts: list[Element] = list(launcher.program)
    for node in nodes:
        parts.extend(_read(node, whole, constants, scope))
    return tuple(parts)


def _handed_on(call: ast.Call, launcher: Launcher, function: Function | None) -> str | None:
    """The parameter of `function` that `call` hands `launcher` as its argv's last part — its
    `*args`, or a list parameter, spread or whole — or `None` when it hands none."""
    handed = _argv_nodes(call, launcher)
    if function is None or handed is None or not handed[0]:
        return None
    nodes, whole = handed
    tail = nodes[-1] if whole else nodes[-1].value if isinstance(nodes[-1], ast.Starred) else None
    arguments = function.args
    names = [a.arg for a in (*arguments.posonlyargs, *arguments.args)]
    if arguments.vararg is not None:
        names.append(arguments.vararg.arg)
    return tail.id if isinstance(tail, ast.Name) and tail.id in names else None


def _derived(
    call: ast.Call, launcher: Launcher, function: Function, source: _Source
) -> Launcher | None:
    """The launcher `function` is when `call` hands `launcher` the function's own argv, which
    the function never rebinds or mutates, with nothing before it the walk cannot read: its
    callers' arguments are then read at each caller, after what this call puts first."""
    parameter = _handed_on(call, launcher, function)
    if parameter is None or not _stable(parameter, function):
        return None
    head = _argv(call, launcher, source.constants, function)[:-1]
    if not all(isinstance(part, str) for part in head):
        return None
    program = tuple(str(part) for part in head)
    arguments = function.args
    positional = [a.arg for a in (*arguments.posonlyargs, *arguments.args)]
    if arguments.vararg is not None and parameter == arguments.vararg.arg:
        return Launcher(program, at=len(positional), spread=True)
    return Launcher(program, at=positional.index(parameter), keyword=parameter)


def _scoped(
    node: ast.AST,
    scope: tuple[str, ...] = (),
    functions: tuple[Function, ...] = (),
    annotation: bool = False,
) -> Iterator[tuple[ast.AST, str, tuple[Function, ...], bool]]:
    """Every node under `node`, with the dotted name of the function or class it sits in, the
    functions it sits in, outermost first, and whether it sits in an annotation: there
    `subprocess.Popen[bytes]` names a type, though a call's arguments are still values when the
    annotation is evaluated."""
    for field, value in ast.iter_fields(node):
        arguments = isinstance(node, ast.Call) and field in ("args", "keywords")
        inside = (annotation and not arguments) or field in ("annotation", "returns")
        for child in value if isinstance(value, list) else [value]:
            if not isinstance(child, ast.AST):
                continue
            yield child, ".".join(scope) or "<module>", functions, inside
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from _scoped(child, (*scope, child.name), (*functions, child), inside)
            elif isinstance(child, ast.ClassDef):
                yield from _scoped(child, (*scope, child.name), functions, inside)
            else:
                yield from _scoped(child, scope, functions, inside)


@dataclass(frozen=True)
class _Call:
    """A call in a source, where it sits, and the launcher it calls through, if any."""

    node: ast.Call
    scope: str
    functions: tuple[Function, ...]


def _calls(source: _Source) -> list[_Call]:
    return [
        _Call(node, scope, functions)
        for node, scope, functions, _ in _scoped(source.tree)
        if isinstance(node, ast.Call)
    ]


def _handing_on(
    sources: list[tuple[_Source, list[_Call]]], launchers: Launchers
) -> dict[tuple[str, str], list[tuple[_Source, _Call, Launcher]]]:
    """Each function's calls that hand its own argv on to a launcher, by `(file, function)`: a
    module-level function's, and a root's."""
    found: dict[tuple[str, str], list[tuple[_Source, _Call, Launcher]]] = {}
    for source, calls in sources:
        for call in calls:
            if not call.functions:
                continue
            function = call.functions[-1]
            key = (source.file, call.scope)
            if id(function) not in source.module_level and key not in launchers:
                continue
            launcher = _launcher(call.node.func, source.names, launchers)
            if launcher is not None and _handed_on(call.node, launcher, function) is not None:
                found.setdefault(key, []).append((source, call, launcher))
    return found


def _derive(
    sources: list[_Source], roots: Launchers
) -> tuple[Launchers, frozenset[tuple[str, Site]]]:
    """The roots and every launcher derived from them in `sources`, and the call in each that
    hands its argv on, by `(file, (line, column))`, which is read at its callers instead.

    A launcher stands for its one handing on of its argv. A function found handing it on in more
    than one call is blocked and the derivation starts again without it, so it is no launcher
    and each of its launches stays a finding; blocked only grows, so this ends. A root's first
    handing on is exempt and any other is a finding.
    """
    indexed = [(source, _calls(source)) for source in sources]
    blocked: set[tuple[str, str]] = set()
    while True:
        launchers = dict(roots)
        while True:
            handing = _handing_on(indexed, launchers)
            added = {
                key: launcher
                for key, [(source, call, outer), *_] in handing.items()
                if key not in launchers and key not in blocked
                if (launcher := _derived(call.node, outer, call.functions[-1], source))
            }
            if not added:
                break
            launchers.update(added)
        twice = {key for key, found in handing.items() if len(found) > 1} - roots.keys()
        if not twice & launchers.keys():
            exempt = frozenset(
                (source.file, (call.node.lineno, call.node.col_offset))
                for key, [(source, call, _), *_] in handing.items()
                if key in launchers
            )
            return launchers, exempt
        blocked |= twice


def _attribute_read(
    call: ast.Call, reads: frozenset[str] = ATTRIBUTE_READS
) -> ast.Attribute | None:
    """The attribute `call` reads when it is one of `reads` given a literal name, as the
    `owner.name` it reads; `None` for any other call."""
    if not (isinstance(call.func, ast.Name) and call.func.id in reads):
        return None
    named = call.args[1] if call.args[1:] else None
    if not (isinstance(named, ast.Constant) and isinstance(named.value, str)):
        return None
    return ast.Attribute(value=call.args[0], attr=named.value, ctx=ast.Load())


def _owners(tree: ast.Module) -> set[int]:
    """The nodes a module named there is used through rather than handed on: the owner of an
    attribute, and the first argument of an attribute read by a literal name."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            ids.add(id(node.value))
        elif isinstance(node, ast.Call) and (read := _attribute_read(node)) is not None:
            ids.add(id(read.value))
    return ids


def _not_handed_on(tree: ast.Module) -> set[int]:
    """The nodes a launcher named there is not handed on from: what a call calls, which the
    call itself is read for, and a class `isinstance` or `issubclass` only compares."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        ids.add(id(node.func))
        if isinstance(node.func, ast.Name) and node.func.id in CLASS_CHECKS and node.args[1:]:
            compared = node.args[1]
            ids.update(map(id, compared.elts if isinstance(compared, ast.Tuple) else [compared]))
    return ids


def _star_launches(node: ast.ImportFrom, file: str) -> bool:
    """Whether `from <module> import *` can bind launchers the walk cannot then name: from a
    launcher module, or from any package module, which can re-export one."""
    module = _imported_from(node, file)
    return any(alias.name == "*" for alias in node.names) and (
        module in LAUNCHER_MODULES or _module_file(module) is not None
    )


def _walk(
    source: _Source, launchers: Launchers, exempt: frozenset[tuple[str, Site]]
) -> tuple[list[Launch], list[Override]]:
    """Every launch in `source` and every override a launch call makes. A launch is each call
    that starts a process, except a launcher's one handing on of its argv, which is read at its
    callers; and each place a launcher is handed on unread — named without being called, read by
    `getattr`, star-imported, or reachable through a launcher module named without an attribute
    after it — which the walk cannot follow. Overrides are read on every launch call, the handing
    on included, since what it inherits every caller inherits."""
    not_handed_on = _not_handed_on(source.tree)
    owners = _owners(source.tree)
    launches: list[Launch] = []
    overrides: list[Override] = []
    for node, scope, functions, in_annotation in _scoped(source.tree):
        if isinstance(node, ast.Call):
            # `getattr` hands on what it reads; `hasattr` only asks.
            read = _attribute_read(node, frozenset({"getattr"}))
            if read is not None and _launcher(read, source.names, launchers) is not None:
                unread = (Unread(ast.unparse(node)),)
                launches.append(Launch(source.file, node.lineno, scope, unread))
            if (launcher := _launcher(node.func, source.names, launchers)) is None:
                continue
            overrides.extend(
                Override(source.file, node.lineno, scope, ast.unparse(keyword), called)
                for keyword in node.keywords
                if keyword.arg is None or keyword.arg in OVERRIDING
                for called in [
                    _function_of(keyword.value.func, source.names)
                    if isinstance(keyword.value, ast.Call)
                    else None
                ]
            )
            if (source.file, (node.lineno, node.col_offset)) in exempt:
                continue
            outermost = functions[0] if functions else source.tree
            argv = _argv(node, launcher, source.constants, outermost)
            launches.append(Launch(source.file, node.lineno, scope, argv))
        elif isinstance(node, (ast.Name, ast.Attribute)):
            if not isinstance(node.ctx, ast.Load) or in_annotation:
                continue
            handed = id(node) not in not_handed_on and _launcher(node, source.names, launchers)
            module = id(node) not in owners and _holds_launchers(source.names, node)
            if handed or module:
                unread = (Unread(ast.unparse(node)),)
                launches.append(Launch(source.file, node.lineno, scope, unread))
        elif isinstance(node, ast.ImportFrom) and _star_launches(node, source.file):
            unread = (Unread(ast.unparse(node)),)
            launches.append(Launch(source.file, node.lineno, scope, unread))
    return launches, overrides


def _is_environ(expr: ast.expr, names: Bindings) -> bool:
    """Whether `expr` is the process's environment, `os.environ` however it is reached."""
    if isinstance(expr, ast.Name):
        bound = _resolved(names, expr.id).stdlib.get(expr.id)
        return bound is not None and bound[0] in OS_MODULES and bound[1] == "environ"
    return (
        isinstance(expr, ast.Attribute)
        and expr.attr == "environ"
        and _module_of(names, expr.value) in OS_MODULES
    )


def _environment_writes(source: _Source) -> list[tuple[str, int, str]]:
    """`(file, line, source text)` for each change `source` makes to the process's environment —
    an item of `os.environ` set or deleted, a method that changes it, an augmented assignment, or
    `os.putenv` and `os.unsetenv` — which every launch after it inherits."""
    found = []
    for node in ast.walk(source.tree):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            changed = _is_environ(node.value, source.names)
        elif isinstance(node, ast.AugAssign):
            changed = _is_environ(node.target, source.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            in_place = node.func.attr in MUTATORS and _is_environ(node.func.value, source.names)
            module = _module_of(source.names, node.func.value)
            changed = in_place or (module in OS_MODULES and node.func.attr in ENVIRONMENT_CALLS)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            bound = _resolved(source.names, node.func.id).stdlib.get(node.func.id)
            changed = bound is not None and bound[0] in OS_MODULES
            changed = changed and bound is not None and bound[1] in ENVIRONMENT_CALLS
        else:
            continue
        if changed:
            found.append((source.file, getattr(node, "lineno", 0), ast.unparse(node)))
    return found


class Walk:
    """The walk over the package from `roots`, the package launchers it starts from."""

    def __init__(self, roots: Mapping[tuple[str, str], Launcher]) -> None:
        self.roots = dict(roots)
        self._by_root: dict[Path, list[tuple[list[Launch], list[Override]]]] = {}

    @cached_property
    def _derived(self) -> tuple[Launchers, frozenset[tuple[str, Site]]]:
        return _derive([_source(relative(path)) for path in package_files(SRC)], self.roots)

    @property
    def launchers(self) -> Launchers:
        """Every package launcher: the roots, and every one derived from them."""
        return self._derived[0]

    def _walked(self, root: Path) -> list[tuple[list[Launch], list[Override]]]:
        if root not in self._by_root:
            launchers, exempt = self._derived
            self._by_root[root] = [
                _walk(_source(relative(path)), launchers, exempt) for path in package_files(root)
            ]
        return self._by_root[root]

    def launches(self, root: Path = SRC) -> list[Launch]:
        """Every launch in the package files under `root`."""
        return [launch for launches, _ in self._walked(root) for launch in launches]

    def overrides(self, root: Path = SRC) -> list[Override]:
        """Every `env=` and `executable=` a launch call under `root` passes."""
        return [override for _, overrides in self._walked(root) for override in overrides]

    def environment_writes(self, root: Path = SRC) -> list[tuple[str, int, str]]:
        """Every change a package file under `root` makes to the process's environment."""
        return [
            write
            for path in package_files(root)
            for write in _environment_writes(_source(relative(path)))
        ]

    def environment_writes_in(self, text: str, file: str) -> list[tuple[str, int, str]]:
        """Every change `text`, read as a package file `file`, makes to the environment."""
        return _environment_writes(_source(file, text))

    def walk_in(self, text: str, file: str) -> tuple[list[Launch], list[Override]]:
        """Every launch and override in `text`, read as a package file `file` beside the
        package's own."""
        source = _source(file, text)
        launchers, exempt = _derive([source], self.launchers)
        return _walk(source, launchers, exempt)

    def launches_in(self, text: str, file: str) -> list[Launch]:
        """Every launch in `text`, read as a package file `file` beside the package's own."""
        return self.walk_in(text, file)[0]
