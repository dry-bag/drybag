"""The readings the boundary rules share, each held on its own: an import named in every spelling,
the imports that run and the ones that can, and a name resolved by Python's scoping."""

from __future__ import annotations

import ast
import sys

import pytest

from tests.boundaries import astscan


def test_an_import_names_its_module_in_every_spelling_and_a_relative_one_resolved() -> None:
    # A `from` statement names its own module first and then one name per alias, and a relative
    # one is resolved from the importing module's package: one dot is that package, and each
    # further dot strips one component. Mutation (declared): `mutations/`'s "the boundary rule
    # ignores a relative import again" -> the relative modules read as written.
    text = (
        "import os.path, json as j\n"
        "from drybag.memory import worktree\n"
        "from ..hooks.sink import DIRECTORY\n"
        "from . import commands\n"
        "from .checks import OK\n"
    )
    assert astscan.imported_modules(ast.parse(text), ("drybag", "doctor")) == [
        (1, "os.path"),
        (1, "json"),
        (2, "drybag.memory"),
        (2, "drybag.memory.worktree"),
        (3, "drybag.hooks.sink"),
        (3, "drybag.hooks.sink.DIRECTORY"),
        (4, "drybag.doctor"),
        (4, "drybag.doctor.commands"),
        (5, "drybag.doctor.checks"),
        (5, "drybag.doctor.checks.OK"),
    ]


def test_the_imports_that_run_exclude_type_checking_and_on_request_function_bodies() -> None:
    # One reading for two questions, which were two near copies of it: what runs when a module
    # is imported (the doctor rule, the package graph) and what can run at all (the module graph).
    # Neither counts what `if TYPE_CHECKING:` guards, in either spelling; both count its `else`, a
    # class body, a `try`, a `with` and an `if` of any other test. Mutations (declared):
    # `mutations/`'s "the module graph stops reading imports inside a function" -> the module
    # graph's cases redden; "the import reading takes a function body for one that runs on import"
    # -> the first assertion here reddens.
    text = (
        "import a\n"
        "class K:\n    import b\n"
        "try:\n    import c\nexcept ImportError:\n    import d\n"
        "with x:\n    import e\n"
        "if flag:\n    import f\n"
        "if TYPE_CHECKING:\n    import g\nelse:\n    import h\n"
        "if typing.TYPE_CHECKING:\n    import i\n"
        "def fn():\n    import j\n"
        "    if TYPE_CHECKING:\n        import k\n"
        "async def coroutine():\n    import l\n"
        "lam = lambda: m\n"
    )
    tree = ast.parse(text)

    def names(found: list[ast.Import | ast.ImportFrom]) -> list[str]:
        return [alias.name for node in found for alias in node.names]

    assert names(astscan.imports([tree], inside_functions=False)) == list("abcdefh")
    assert names(astscan.imports([tree], inside_functions=True)) == list("abcdefhjl")


def _resolved(source: str) -> list[tuple[str, str, bool]]:
    """Each name `source` reads, with the function it is read in and whether it resolves to a
    binding of the file's own (`astscan.shadowed`) rather than to the builtin."""
    return [
        (function, node.id, astscan.shadowed(node.id, chain))
        for node, function, chain in astscan.walk(ast.parse(source))
        if isinstance(node, ast.Name) and type(node.ctx) is ast.Load
    ]


def test_a_name_resolves_by_pythons_scoping_to_the_files_binding_or_the_builtin() -> None:
    # The scoping the string rule reads a builtin by, held here on its own. A function's binding
    # hides a name in that function and the scopes it encloses, never beyond; a class body is not
    # seen by its methods, an import there included; `global` reads the module, where only an
    # import hides, as a module or a class body is looked up at run time; a comprehension's
    # variable hides in the comprehension alone, though not in its first iterable, which is read
    # around it, while a walrus in it binds in the function around it; a parameter's annotation
    # and default are read around the function; an `except` clause's name binds, and `import a.b`
    # binds `a`; a `nonlocal` name is the enclosing function's, so where that took it `from
    # builtins` it is still the builtin. Mutations (declared): `mutations/`'s "a module or a class
    # body hides a builtin by any binding again", "a walrus in a comprehension binds in the
    # comprehension", "import builtins under a text runner's name hides the builtin", "a nested
    # scope sees an enclosing class body", "a comprehension's first iterable is read inside it",
    # "an except clause's name binds nothing", "import a.b binds the dotted name rather than its
    # first part" and "a nonlocal name hides a builtin the enclosing function took from builtins"
    # -> a row here changes.
    source = (
        "import json as exec\n"
        "import builtins as eval\n"
        "compile = 1\n"
        "def f(breakpoint):\n"
        "    def inner():\n        return breakpoint\n"
        "    return breakpoint\n"
        "def g():\n    return breakpoint\n"
        "class K:\n    print = 1\n    def m(self):\n        return print\n"
        "def h():\n    global exec\n    return exec\n"
        "def w():\n    _ = [(id := c) for c in ()]\n    return id\n"
        "_ = [len for len in ()]\n"
        "def a(x: input = vars):\n    return input, vars\n"
        "class L:\n    import json as hex\n    def m(self):\n        return hex\n"
        "_ = [hash for hash in hash]\n"
        "def e():\n    try:\n        pass\n    except OSError as abs:\n        pass\n"
        "    return abs\n"
        "def i():\n    import open.mode\n    return open\n"
        "def j():\n    from builtins import open\n    def k():\n        nonlocal open\n"
        "        open = print\n        return open\n    return k\n"
        "exec, eval, compile\n"
    )
    assert _resolved(source) == [
        ("inner", "breakpoint", True),
        ("f", "breakpoint", True),
        ("g", "breakpoint", False),
        ("m", "print", False),
        ("h", "exec", True),
        ("w", "c", True),
        ("w", "id", True),
        ("<module>", "len", True),
        ("<module>", "vars", False),
        ("<module>", "input", False),
        ("a", "input", False),
        ("a", "vars", False),
        ("m", "hex", False),
        ("<module>", "hash", False),
        ("<module>", "hash", True),
        ("e", "OSError", False),
        ("e", "abs", True),
        ("i", "open", True),
        ("k", "print", False),
        ("k", "open", False),
        ("j", "k", True),
        ("<module>", "exec", True),
        ("<module>", "eval", False),
        ("<module>", "compile", False),
    ]


def test_a_binding_lands_where_python_looks_it_up_at_run_time_or_in_its_function() -> None:
    # A binding made in a module or a class body, or in a function under `global`, lands where
    # Python looks the name up at run time; a walrus in a comprehension lands in the scope around
    # the comprehension. Mutations (declared): `mutations/`'s "a function's store of a text runner
    # under global is no row" and "a walrus target is taken to land in its comprehension" -> a row
    # here changes.
    source = (
        "exec = 1\n"
        "class K:\n    eval = 1\n"
        "def f():\n    global compile\n    compile = 1\n    breakpoint = 1\n"
        "_ = [(input := c) for c in ()]\n"
        "def g():\n    _ = [(vars := c) for c in ()]\n"
    )
    tree = ast.parse(source)
    walrus = {id(node.target) for node in ast.walk(tree) if isinstance(node, ast.NamedExpr)}
    landed = [
        (function, name, astscan.binds_at_run_time(name, chain, walrus=id(node) in walrus))
        for node, function, chain in astscan.walk(tree)
        if (name := astscan.bound_name(node)) is not None and name != "_" and name != "c"
    ]
    assert landed == [
        ("<module>", "exec", True),
        ("<module>", "K", True),
        ("<module>", "eval", True),
        ("<module>", "f", True),
        ("f", "compile", True),
        ("f", "breakpoint", False),
        ("<module>", "input", True),
        ("<module>", "g", True),
        ("g", "vars", False),
    ]


@pytest.mark.skipif(sys.version_info < (3, 12), reason="type parameters are 3.12's syntax")
def test_type_parameters_are_read_around_their_def_or_class() -> None:
    # A type parameter's bound is evaluated where the `def` or `class` stands, not inside it. The
    # syntax is 3.12's, so this case is parsed from text and skipped on 3.11. Mutations
    # (declared): `mutations/`'s "a function's type parameters are not read" and "a class's type
    # parameters are not read" -> its bound is not read at all.
    source = "def f[T: exec]():\n    pass\nclass C[T: eval]:\n    pass\n"
    assert [(function, name) for function, name, _ in _resolved(source)] == [
        ("<module>", "exec"),
        ("<module>", "eval"),
    ]
