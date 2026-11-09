"""Every regular expression the package holds or builds from its own text, in a shape every
supported Python reads alike.

A possessive repeat (`*+`, `++`) is how a pattern here reads a long run without the record `re`
keeps for each pass of a repeated group, and Python 3.11.0 to 3.11.4 misread some of them: after a
pass of a possessive group fails, the match goes on from wherever the pass's last repeat, choice or
lookahead left off rather than from where the pass began (fixed in 3.11.5, gh-100061 and
gh-106052). So `docs/` read as a path, and `{hooks: x}` held no key. CONTRIBUTING.md ("Tests")
states the shape that reads alike everywhere; this holds every pattern to it, and the
`checks (ubuntu-latest, 3.11.4)` leg runs the readers' own tests where the bug lives.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import itertools
import pkgutil
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import drybag

# `re`'s own parser, private and the same from 3.11 to 3.14. It gives the shape the engine runs:
# a prefix every alternative shares is taken out ahead of the choice (`cd|cxb` is `c(?:d|xb)`),
# which puts a choice inside the pass, so the source text alone would misjudge it.
_PARSER: Any = importlib.import_module("re._parser")
_OP: Any = importlib.import_module("re._constants")
_ONE_CHARACTER = {_OP.LITERAL, _OP.NOT_LITERAL, _OP.IN, _OP.ANY}
_REPEATS = {_OP.MAX_REPEAT, _OP.MIN_REPEAT, _OP.POSSESSIVE_REPEAT}


def _one_character(item: tuple[Any, Any]) -> bool:
    return item[0] in _ONE_CHARACTER


def _repeat_of_one(item: tuple[Any, Any]) -> bool:
    if item[0] not in _REPEATS:
        return False
    body = list(item[1][2])
    return len(body) == 1 and _one_character(body[0])


def _reads_alike(alternative: list[tuple[Any, Any]]) -> bool:
    """Whether a pass can fail only before anything in it but single characters and anchors: a
    repeat of one character alone that needs at most one, or characters and anchors followed by
    repeats of one character that may match nothing, which cannot fail.

    The lone repeat's bound is the ignore-case count: 3.11.4 counts an item it matches ignoring
    case through a class one character at a time, moving the pass's position as it goes, so a
    repeat that needs two and finds one fails one past where the pass began. A class is such an
    item, and so is a letter with a second case fold, `s` or `i` (U+017F, U+0131), which the
    compiler turns into one; the bound ignores the item, so it holds both. One that needs at most
    one fails only on finding none, before anything moved.
    """
    if len(alternative) == 1 and _repeat_of_one(alternative[0]):
        return bool(alternative[0][1][0] <= 1)
    rest = alternative
    while rest and (_one_character(rest[0]) or rest[0][0] is _OP.AT):
        rest = rest[1:]
    return all(_repeat_of_one(item) and item[1][0] == 0 for item in rest)


def _passes(body: list[tuple[Any, Any]]) -> list[list[tuple[Any, Any]]]:
    """The alternatives a pass of a repeated `body` may take, through one group or one choice."""
    if len(body) == 1 and body[0][0] is _OP.SUBPATTERN:
        return _passes(list(body[0][1][3]))
    if len(body) == 1 and body[0][0] is _OP.BRANCH:
        return [list(alternative) for alternative in body[0][1][1]]
    return [body]


def offences(items: Any) -> list[str]:
    """What in a parsed pattern is read otherwise by Python 3.11.0 to 3.11.4, or is an atomic
    group, which keeps the record a possessive repeat exists to drop."""
    found: list[str] = []
    for op, value in items:
        if op is _OP.ATOMIC_GROUP:
            found.append("an atomic group")
            found += offences(value)
        elif op in _REPEATS:
            body = list(value[2])
            if (
                op is _OP.POSSESSIVE_REPEAT
                and not _repeat_of_one((op, value))
                and not all(_reads_alike(alternative) for alternative in _passes(body))
            ):
                found.append("a possessive repeat of a group that can fail past its first run")
            found += offences(body)
        elif op is _OP.SUBPATTERN:
            found += offences(value[3])
        elif op is _OP.BRANCH:
            for alternative in value[1]:
                found += offences(alternative)
        elif op in (_OP.ASSERT, _OP.ASSERT_NOT):
            found += offences(value[1])
        elif op is _OP.GROUPREF_EXISTS:
            found += offences(value[1])
            if value[2] is not None:
                found += offences(value[2])
    return found


def _offences_of(pattern: re.Pattern[str]) -> list[str]:
    return offences(_PARSER.parse(pattern.pattern, pattern.flags))


# The checker's own table, each shape with what it must say, from what Python 3.11.4 was measured
# to misread against 3.14: a pass that fails at or after a repeat, a lookahead or a choice it has
# entered, and the choice the parser builds out of a shared prefix. The shapes it admits are the
# ones this package uses.
SHAPES = {
    r"(?:ab++)*+": False,
    r"(?:ab+)*+c": False,
    r"(?:ab?c)*+": False,
    r"(?:a(?!x)b)*+": False,
    r"(?:a(?=b)b)*+": False,
    r"(?:a(?:b|\Z))*+": False,
    r"(?:cd|cxb)*+c": False,
    r"(?:\.[a-z]++)++": False,
    r"(?>a+)": False,
    r"(?:x(?>a))*": False,
    # A lone class that needs two, matched ignoring case: 3.11.4 counts it one character at a
    # time, and a pass that read one and failed leaves the next pass one past its start, so `-a1`
    # leaves `1` to the tail where 3.14 leaves `a1`. A letter with a second case fold is read
    # through such a class: `-s1` leaves `1` where 3.14 leaves `s1`.
    r"(?i)(?:[a-z]{2,}|-)*+": False,
    r"(?i)(?:s{2,}|-)*+": False,
    r"[ab]*+": True,
    r"\s++": True,
    r"(?:''[^']*+)*+": True,
    r"(?:[^\"\\]++|\\.)*+": True,
    r"(?:[,\s]|\band\b|\bor\b)*+": True,
    r"(?:\.[a-z][a-z]*+)++": True,
    r"(?:[!&]\S*+\s*+|#[^\n]*+\s*+)++": True,
    r"(?:ab+)*": True,
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_shape_check_tells_what_python_3_11_4_misreads(shape: str) -> None:
    # The check below is only as good as this table: each row that should be refused fails it if
    # the check stops looking at that part of a pass, and each that should pass fails it if the
    # check refuses more than it must. The rows are its oracle. Mutation (oracle): `mutations/`'s
    # "a lone repeat of one character may need two again" -> reddens the ignore-case row.
    assert (not _offences_of(re.compile(shape))) is SHAPES[shape]


def _compiled() -> dict[str, re.Pattern[str]]:
    """Every pattern a module of the package holds at its top level, under the first name it was
    met by: one imported by another module is the same object, judged once."""
    patterns: dict[str, re.Pattern[str]] = {}
    for module in _modules():
        for name, value in vars(module).items():
            if (
                isinstance(value, re.Pattern)
                and isinstance(value.pattern, str)
                and all(value is not seen for seen in patterns.values())
            ):
                patterns[f"{module.__name__}.{name}"] = value
    return patterns


def _modules() -> list[ModuleType]:
    return [
        importlib.import_module(module.name)
        for module in pkgutil.walk_packages(drybag.__path__, "drybag.")
        if not module.name.endswith(".__main__")
    ]


# The functions of `re` that take a pattern first, each with the place its flags stand in when
# they are passed in order.
_FLAGS_AT = {
    "compile": 1,
    "match": 2,
    "search": 2,
    "fullmatch": 2,
    "findall": 2,
    "finditer": 2,
    "split": 3,
    "sub": 4,
    "subn": 4,
}
# What `re.escape` gives back is literal characters, so a pattern built around it is judged with
# none, one and two in its place: every shape a run of literals takes, outside a choice a
# possessive group repeats. There the parser takes a prefix every alternative shares out ahead of
# the choice, so an escaped value that begins as a sibling alternative does puts a choice inside
# the pass that no stand-in shows (`(?:{lead}ab|cd)*+` with `lead` `c`), and the place is named
# instead: `_MARK` stands in once more, to find where the value lands.
_ESCAPED = ("", "x", "xy")
_MARK = "\ue000"
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
# What opens a scope of its own: a function, a lambda, a class body and a comprehension.
_SCOPES = (*_FUNCTIONS, ast.ClassDef, *_COMPREHENSIONS)


class _Unspelled(Exception):
    """A pattern, or its flags, that the source alone does not spell."""


class _Compiled(Exception):
    """A pattern handed over already compiled: a module's own, which the object walk judges."""


@dataclass(frozen=True)
class _Scope:
    namespace: Mapping[str, object]
    function: ast.AST | None
    # Every scope the call sits in, outermost first: the function among them, the functions it is
    # nested in, and the class bodies and comprehensions on either side.
    chain: tuple[ast.AST, ...] = ()
    escaped: tuple[str, ...] = _ESCAPED


def _of_re(node: ast.expr, name: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == name
        and isinstance(node.value, ast.Name)
        and node.value.id == "re"
    )


def _binds(scope: ast.AST, name: str) -> bool:
    """Whether `name` is bound anywhere in `scope`: stored, a parameter, imported, an `except … as`,
    a `def` or a `class`. What a scope nested in it binds counts too, which can only make a place
    one the scan names rather than reads."""
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load) and node.id == name:
            return True
        if isinstance(node, ast.arg) and node.arg == name:
            return True
        if isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name:
            return True
        if isinstance(node, (ast.ExceptHandler, ast.ClassDef, *_FUNCTIONS[:2])) and (
            node.name == name
        ):
            return True
    return False


def _named(name: str, scope: _Scope) -> list[str]:
    """What `name` spells where a pattern reads it: the value of the one plain assignment the
    function makes to it, or, when the function binds it nowhere, the module's string.

    Python reads a class body's or a comprehension's own name before the function's or the
    module's, and a function's free name from the functions it is nested in before the module, so
    a name either binds is one the source alone does not spell here."""
    at = scope.chain.index(scope.function) if scope.function is not None else -1
    if any(_binds(node, name) for node in scope.chain[at + 1 :]):
        raise _Unspelled(name)
    if scope.function is not None:
        inside = list(ast.walk(scope.function))
        stores = [n for n in inside if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]
        assigned = [n for n in stores if n.id == name]
        plain = [
            n.value
            for n in inside
            if isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == name
        ]
        bound = [
            n
            for n in inside
            if (isinstance(n, ast.arg) and n.arg == name)
            or (isinstance(n, ast.alias) and (n.asname or n.name.split(".")[0]) == name)
            or (isinstance(n, ast.ExceptHandler) and n.name == name)
        ]
        if len(assigned) == 1 and len(plain) == 1 and not bound:
            return _spellings(plain[0], scope)
        if assigned or bound:
            raise _Unspelled(name)
    enclosing = scope.chain[: max(at, 0)]
    if any(isinstance(node, _FUNCTIONS) and _binds(node, name) for node in enclosing):
        raise _Unspelled(name)
    value = scope.namespace.get(name)
    if isinstance(value, str):
        return [value]
    if isinstance(value, int) and not isinstance(value, bool):
        return [str(value)]  # a bound in an f-string, `{0,{_SPAN}}`
    if isinstance(value, re.Pattern):
        raise _Compiled(name)
    raise _Unspelled(name)


def _spellings(node: ast.expr, scope: _Scope) -> list[str]:
    """Every text `node` may spell as a pattern, read from the source alone: string literals,
    f-strings, `+`, `str.format`, `re.escape` and names bound to those."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        texts = [""]
        for part in node.values:
            texts = [text + more for text in texts for more in _spellings(part, scope)]
        return texts
    if isinstance(node, ast.FormattedValue) and node.conversion == -1 and node.format_spec is None:
        return _spellings(node.value, scope)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [a + b for a in _spellings(node.left, scope) for b in _spellings(node.right, scope)]
    if isinstance(node, ast.Name):
        return _named(node.id, scope)
    if isinstance(node, ast.Call) and _of_re(node.func, "escape"):
        return list(scope.escaped)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and not any(isinstance(arg, ast.Starred) for arg in node.args)
    ):
        templates = _spellings(node.func.value, scope)
        given = [_spellings(arg, scope) for arg in node.args]
        named: dict[str, list[str]] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise _Unspelled(ast.unparse(node))
            named[keyword.arg] = _spellings(keyword.value, scope)
        return [
            template.format(*args, **dict(zip(named, values, strict=True)))
            for template in templates
            for args in itertools.product(*given)
            for values in itertools.product(*named.values())
        ]
    raise _Unspelled(ast.unparse(node))


def _flags(node: ast.expr, scope: _Scope) -> int:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flags(node.left, scope) | _flags(node.right, scope)
    value: object = None
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        value = getattr(re, node.attr, None) if node.value.id == "re" else None
    elif isinstance(node, ast.Name) and scope.function is None:
        value = scope.namespace.get(node.id)
    elif isinstance(node, ast.Constant):
        value = node.value
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    raise _Unspelled(ast.unparse(node))


def _given(call: ast.Call, scope: _Scope) -> list[tuple[str, int]]:
    """Every pattern and its flags that a call of `re` may be given."""
    assert isinstance(call.func, ast.Attribute)
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        raise _Unspelled(ast.unparse(call))
    pattern = call.args[0] if call.args else None
    at = _FLAGS_AT[call.func.attr]
    flags = call.args[at] if len(call.args) > at else None
    for keyword in call.keywords:
        if keyword.arg is None:
            raise _Unspelled(ast.unparse(call))
        if keyword.arg == "pattern":
            pattern = keyword.value
        elif keyword.arg == "flags":
            flags = keyword.value
    if pattern is None:
        raise _Unspelled(ast.unparse(call))
    bits = 0 if flags is None else _flags(flags, scope)
    return [(text, bits) for text in _spellings(pattern, scope)]


def _calls(
    node: ast.AST, chain: tuple[ast.AST, ...]
) -> Iterator[tuple[ast.Call, tuple[ast.AST, ...]]]:
    """Every call under `node`, each with the scopes it is made in, outermost first."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call):
            yield child, chain
        yield from _calls(child, (*chain, child) if isinstance(child, _SCOPES) else chain)


def _in_a_repeated_choice(items: Any, repeated: bool = False, chosen: bool = False) -> bool:
    """Whether a parsed pattern holds `_MARK` in an alternative of a choice that a possessive
    repeat holds, at any depth."""
    for op, value in items:
        if op is _OP.LITERAL and value == ord(_MARK) and chosen:
            return True
        inner: list[tuple[Any, bool, bool]] = []
        if op is _OP.BRANCH:
            inner = [(alternative, repeated, chosen or repeated) for alternative in value[1]]
        elif op in _REPEATS:
            inner = [(value[2], repeated or op is _OP.POSSESSIVE_REPEAT, chosen)]
        elif op is _OP.SUBPATTERN:
            inner = [(value[3], repeated, chosen)]
        elif op in (_OP.ASSERT, _OP.ASSERT_NOT):
            inner = [(value[1], repeated, chosen)]
        elif op is _OP.ATOMIC_GROUP:
            inner = [(value, repeated, chosen)]
        elif op is _OP.GROUPREF_EXISTS:
            inner = [(body, repeated, chosen) for body in value[1:] if body is not None]
        if any(_in_a_repeated_choice(*args) for args in inner):
            return True
    return False


def _built(
    source: str, namespace: Mapping[str, object], module: str
) -> tuple[dict[str, list[tuple[str, int]]], list[str]]:
    """The patterns a module's calls of `re` are given, read from its source, by
    `module.function:line`; and, by `module.function`, once per call, where the source does not
    spell one."""
    spelled: dict[str, list[tuple[str, int]]] = {}
    unspelled: list[str] = []
    tree = ast.parse(source)
    # The scan reads `re` by that name only, so `re` bound to another, or its functions taken out
    # of it, is a place it cannot read.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "re":
            unspelled.append(f"{module}.<from re import>")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "re" and alias.asname not in (None, "re"):
                    unspelled.append(f"{module}.<import re as {alias.asname}>")
    for call, chain in _calls(tree, ()):
        if not any(_of_re(call.func, name) for name in _FLAGS_AT):
            continue
        function = next((node for node in reversed(chain) if isinstance(node, _FUNCTIONS)), None)
        where = f"{module}.{getattr(function, 'name', '<lambda>') if function else '<module>'}"
        scope = _Scope(namespace, function, chain)
        try:
            given = _given(call, scope)
            marked = _given(call, dataclasses.replace(scope, escaped=(_MARK,)))
        except _Compiled:
            continue
        except _Unspelled:
            unspelled.append(where)
            continue
        if any(
            _compiles(text, flags) and _in_a_repeated_choice(_PARSER.parse(text, flags))
            for text, flags in marked
        ):
            unspelled.append(where)
            continue
        valid = [(text, flags) for text, flags in given if _compiles(text, flags)]
        if valid:
            spelled[f"{where}:{call.lineno}"] = valid
        else:
            unspelled.append(where)
    return spelled, unspelled


def _compiles(text: str, flags: int) -> bool:
    try:
        re.compile(text, flags)
    except re.error:
        return False
    return True


def _built_by_package() -> tuple[dict[str, list[tuple[str, int]]], list[str]]:
    spelled: dict[str, list[tuple[str, int]]] = {}
    handed: list[str] = []
    for module in _modules():
        assert module.__file__ is not None
        found, missed = _built(
            Path(module.__file__).read_text(encoding="utf-8"), vars(module), module.__name__
        )
        spelled |= found
        handed += missed
    return spelled, handed


def _offences_in(spelled: Mapping[str, list[tuple[str, int]]]) -> dict[str, list[str]]:
    return {
        where: said
        for where, given in spelled.items()
        for text, flags in given
        if (said := offences(_PARSER.parse(text, flags)))
    }


# Where the package compiles text the source does not spell, one row per call, each with where
# that text comes from. The test below fails on any place not named here, on a second call in a
# place named once, and on a row whose call is gone.
_HANDED = (
    (
        "drybag.attach.rules._glob",
        "a rule's `paths:` glob, from the owner's overlay, translated into `[^/]*`, `[^/]`, `.*` "
        "and choices, with every other character through `re.escape`: no possessive repeat",
    ),
)


def test_no_pattern_repeats_a_group_in_a_shape_python_3_11_4_misreads() -> None:
    # Every pattern object a module holds at its top level, and every pattern a call of `re` is
    # given anywhere in the package's source -- inside a function, from module constants,
    # f-strings and `str.format`, with `re.escape`'s literals judged as none, one and two
    # characters outside a choice a possessive group repeats. Outside it: text a function is
    # handed at run time, and `re.escape` inside such a choice, which are `_HANDED`'s calls only,
    # and the patterns the standard library builds itself (a glob's).
    # Mutations (oracle):
    # `mutations/`'s "the path grammar repeats its segments possessively", "a symbol path's parts
    # are a possessive repeat", "a footer's words are a possessive repeat", "a model's words open
    # on their possessive run" -> each reddens this.
    patterns = _compiled()
    assert len(patterns) > 50  # a walk-based assertion states its walk is non-empty
    spelled, unspelled = _built_by_package()
    assert len(spelled) > 50
    found = {name: said for name, pattern in patterns.items() if (said := _offences_of(pattern))}
    assert found | _offences_in(spelled) == {}
    assert Counter(unspelled) == Counter(place for place, _ in _HANDED)


# Text planted where the walk has to look, each with what the scan must make of it: a shape refused
# or admitted, or a place named as handed text it cannot judge.
PLANTED = {
    "a literal inside a function": (
        'def f(text):\n    return re.match(r"(?:ab+)*+", text)\n',
        "refused",
    ),
    "a method's literal": (
        'class C:\n    def f(self, text):\n        return re.search(r"(?:ab+)*+", text)\n',
        "refused",
    ),
    "an f-string around re.escape": (
        'def f(prefix):\n    return re.compile(rf"(?:{re.escape(prefix)}b+)*+")\n',
        "refused",
    ),
    "a name the function binds once": (
        'def f(prefix):\n    lead = re.escape(prefix)\n    return re.compile(rf"(?:{lead}b+)*+")\n',
        "refused",
    ),
    "a module template's format": (
        'TEMPLATE = "(?:{key}b+)*+"\n\n\n'
        "def f(key):\n    return re.compile(TEMPLATE.format(key=re.escape(key)))\n",
        "refused",
    ),
    "flags that make it read alike": (
        'def f(text):\n    return re.fullmatch(r"(?:a +)*+", text, re.VERBOSE)\n',
        "admitted",
    ),
    "flags by keyword": (
        'def f(text):\n    return re.sub(r"(?:a +)*+", "", text, flags=re.X | re.I)\n',
        "admitted",
    ),
    "the same text without them": (
        'def f(text):\n    return re.fullmatch(r"(?:a +)*+", text)\n',
        "refused",
    ),
    "text handed to the function": (
        "def f(pattern):\n    return re.compile(pattern)\n",
        "unspelled planted.f",
    ),
    "a name the function binds twice": (
        'def f(text):\n    found = "a"\n    found = text\n    return re.compile(found)\n',
        "unspelled planted.f",
    ),
    "re under another name": (
        'import re as regex\n\n\ndef f(text):\n    return regex.match(r"(?:ab+)*+", text)\n',
        "unspelled planted.<import re as regex>",
    ),
    "a function taken out of re": (
        'from re import match\n\n\ndef f(text):\n    return match(r"(?:ab+)*+", text)\n',
        "unspelled planted.<from re import>",
    ),
    "two calls of handed text in one function": (
        "def f(pattern, other):\n    re.compile(pattern)\n    return re.compile(other)\n",
        "unspelled planted.f, planted.f",
    ),
    "re.escape in a choice a possessive group repeats": (
        'def f(lead, text):\n    return re.match(rf"(?:{re.escape(lead)}ab|cd)*+", text)\n',
        "unspelled planted.f",
    ),
    "re.escape in a choice a greedy group repeats": (
        'def f(lead, text):\n    return re.match(rf"(?:{re.escape(lead)}ab|cd)*", text)\n',
        "admitted",
    ),
    "a name a closure reads from its function": (
        'lead = "x"\n\n\ndef f(text):\n    lead = "(?:ab+)*+"\n\n'
        "    def g():\n        return re.match(lead, text)\n\n    return g\n",
        "unspelled planted.g",
    ),
    "a name a class body binds": (
        'PATTERN = "x"\n\n\nclass C:\n    PATTERN = "(?:ab+)*+"\n    FOUND = re.compile(PATTERN)\n',
        "unspelled planted.<module>",
    ),
}


@pytest.mark.parametrize("case", sorted(PLANTED))
def test_the_scan_reads_a_pattern_wherever_the_source_spells_it(case: str) -> None:
    # Mutations (oracle): `mutations/`'s "the pattern scan stops at a function's body", "the
    # pattern scan stops reading a name its function assigns once", "the pattern scan reads
    # every call's flags as none", "the pattern scan reads re.escape as nothing", "the pattern
    # scan passes over text it cannot spell", "the pattern scan misses re under another name",
    # "the pattern scan misses a function taken out of re" -> each reddens a row here.
    source, expected = PLANTED[case]
    # The module's constants, as importing it would bind them.
    namespace = {
        statement.targets[0].id: ast.literal_eval(statement.value)
        for statement in ast.parse(source).body
        if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name)
    }
    spelled, unspelled = _built(source, namespace, "planted")
    if unspelled:
        read = "unspelled " + ", ".join(sorted(unspelled))
    else:
        read = "refused" if _offences_in(spelled) else "admitted" if spelled else "unseen"
    assert read == expected
