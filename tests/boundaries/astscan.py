"""What a module's syntax tree says about its imports and its names, read as Python reads them.

The boundary rules beside this module judge the package's source without running it, and this is
what they share: the module an import statement names, which import statements run when their
module is imported and which can run at all, and, for a name read anywhere in a file, whether
Python resolves it to a binding of the file's own or to the builtin of that name. Each rule's
policy, what it reads for and what it pins, stays in the rule's own file.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Sequence

# The nodes that open a scope of their own, by Python's rules: a function, a lambda, a class body
# and a comprehension.
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
SCOPES = (*FUNCTIONS, ast.ClassDef, *COMPREHENSIONS)
# The scopes Python looks a name up in at run time, in the namespace and then in the builtins.
RUN_TIME_SCOPES = (ast.Module, ast.ClassDef)

# The scopes a name is read in, the module first, each with what `scope_bindings` says of it.
Chain = Sequence[tuple[ast.AST, tuple[set[str], set[str], set[str]]]]


def imported_modules(tree: ast.AST, package: tuple[str, ...]) -> list[tuple[int, str]]:
    """Every module name this file imports, as an absolute dotted name, with its line.

    Three spellings, and the third is the one the surface rule shipped without seeing.
    `from drybag.memory.api import X` and `import drybag.memory.api` are the obvious one;
    `from drybag.memory import worktree` is the one a rule that looked only at `node.module`
    would miss, and it reaches a private module just as squarely.

    **The third is the relative import**, and it used to be dropped on the floor: the condition
    read `and not node.level`, so `from ..hooks.sink import DIRECTORY` inside `doctor/checks.py`
    walked straight past. There are no relative imports under `src/drybag/` today, but only by
    house style: ruff's `TID` rules are not selected, so nothing bans one, and the first
    contributor to write an idiomatic one would have reopened the boundary with the rule still
    green.

    Resolved rather than refused, so a rule answers the question it is named for in whatever
    spelling, instead of imposing a second rule the project has not made. `package` is the
    importing module's package, `("drybag", "doctor")` for `doctor/checks.py`; `level` counts
    the leading dots: one means that package, and each further dot strips one component off it.
    A `from` statement yields its own module first and then one name per alias.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                # A relative import that climbs above `drybag` is a module Python could not
                # import at all; it must fail here rather than resolve to something shorter.
                assert base, f"line {node.lineno}: a relative import above the package root"
                prefix = ".".join((*base, *(node.module.split(".") if node.module else ())))
            else:
                assert node.module is not None
                prefix = node.module
            found.append((node.lineno, prefix))
            found += [(node.lineno, f"{prefix}.{alias.name}") for alias in node.names]
    return found


def type_checking(test: ast.expr) -> bool:
    """Whether an `if` tests `TYPE_CHECKING` itself, bare or as `typing.TYPE_CHECKING`."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
    )


def imports(
    nodes: Iterable[ast.AST], *, inside_functions: bool
) -> list[ast.Import | ast.ImportFrom]:
    """Every import statement under `nodes` that can run: the whole tree, less what the body of an
    `if TYPE_CHECKING:` holds, which never runs, and, unless `inside_functions`, less what a
    function body holds, which runs only when the function is called. The rest runs when its
    module is imported: a class body, a `try`, a `with`, the `else` of `if TYPE_CHECKING:` and an
    `if` of any other test."""
    found: list[ast.Import | ast.ImportFrom] = []
    for node in nodes:
        if not inside_functions and isinstance(node, FUNCTIONS):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
        elif isinstance(node, ast.If) and type_checking(node.test):
            found += imports(node.orelse, inside_functions=inside_functions)
        else:
            found += imports(ast.iter_child_nodes(node), inside_functions=inside_functions)
    return found


def scope_parts(node: ast.AST) -> tuple[list[ast.AST], list[ast.AST]]:
    """A scope node's children split by where Python evaluates them: in the enclosing scope (a
    function's decorators, type parameters, defaults and annotations, a class's decorators, type
    parameters and bases, a comprehension's first iterable) and in the scope the node opens (the
    body, a comprehension's targets and the rest). Type parameters are read through `getattr`,
    since the 3.11 syntax tree has none."""
    if isinstance(node, FUNCTIONS):
        args = node.args
        every = [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
        outer: list[ast.AST] = [*args.defaults, *(d for d in args.kw_defaults if d is not None)]
        outer += [a.annotation for a in every if a is not None and a.annotation is not None]
        if isinstance(node, ast.Lambda):
            return outer, [node.body]
        outer += [*node.decorator_list, *getattr(node, "type_params", [])]
        outer += [node.returns] if node.returns else []
        return outer, list(node.body)
    if isinstance(node, ast.ClassDef):
        outer = [*node.decorator_list, *getattr(node, "type_params", [])]
        return [*outer, *node.bases, *node.keywords], list(node.body)
    if isinstance(node, COMPREHENSIONS):
        first, *rest = node.generators
        results = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        return [first.iter], [first.target, *first.ifs, *rest, *results]
    return [], list(ast.iter_child_nodes(node))


def bound_name(node: ast.AST) -> str | None:
    """The name `node` binds, an import aside: a name stored or deleted, a `def` or `class` name,
    or an `except … as` or `match` capture."""
    if isinstance(node, ast.Name) and type(node.ctx) is not ast.Load:
        return node.id
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
        return node.name
    if isinstance(node, ast.MatchMapping):
        return node.rest
    return None


def scope_bindings(node: ast.AST) -> tuple[set[str], set[str], set[str]]:
    """The names that hide a builtin throughout the scope `node` opens, and those it declares
    `global` and `nonlocal`.

    A function's names are fixed when it is compiled, so every name it binds hides there: its
    parameters, each `bound_name` in its own body, an import from any module but `builtins`, and
    a walrus target in a comprehension inside it, which Python binds in the function. A
    comprehension hides only its own iteration variables. A module or a class body is looked up at
    run time, where a binding may not have run, may have been deleted, or may be the builtin
    itself (`exec = exec`), so only an import hides there. What a nested scope binds is that
    scope's own."""
    bound: set[str] = set()
    imported: set[str] = set()
    if isinstance(node, FUNCTIONS):
        args = node.args
        every = [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
        bound |= {a.arg for a in every if a is not None}
    declared_global: set[str] = set()
    declared_nonlocal: set[str] = set()
    # Each part with whether it sits in a comprehension nested in this scope, where only a walrus
    # binds a name of this scope's.
    pending = [(part, False) for part in scope_parts(node)[1]]
    while pending:
        child, nested = pending.pop()
        if isinstance(child, ast.NamedExpr):
            if not isinstance(node, COMPREHENSIONS):
                bound.add(child.target.id)
            pending.append((child.value, nested))
            continue
        name = None if nested else bound_name(child)
        if name is not None:
            bound.add(name)
        elif isinstance(child, ast.Global):
            declared_global |= set(child.names)
        elif isinstance(child, ast.Nonlocal):
            declared_nonlocal |= set(child.names)
        elif isinstance(child, ast.Import):
            imported |= {
                alias.asname or alias.name.split(".")[0]
                for alias in child.names
                if alias.name != "builtins"
            }
        elif isinstance(child, ast.ImportFrom) and child.module != "builtins":
            imported |= {alias.asname or alias.name for alias in child.names}
        if isinstance(child, SCOPES):
            outer, inner = scope_parts(child)
            pending += [(part, nested) for part in outer]
            if isinstance(child, COMPREHENSIONS):
                pending += [(part, True) for part in inner]
        else:
            pending += [(part, nested) for part in ast.iter_child_nodes(child)]
    hiding = imported if isinstance(node, RUN_TIME_SCOPES) else bound | imported
    return hiding - declared_global - declared_nonlocal, declared_global, declared_nonlocal


def walk(tree: ast.Module) -> Iterator[tuple[ast.AST, str, Chain]]:
    """Every node of `tree` below the module, in source order, each with the name of the innermost
    `def` around it (`<module>` outside one) and the chain of scopes a name read there resolves
    through, the module first. A part of a scope node that Python evaluates around it (a default,
    a decorator, a base) is read in the enclosing scope (`scope_parts`). A string standing alone as
    a statement, a docstring among them, is prose and is passed over whole."""

    def visit(node: ast.AST, function: str, chain: Chain) -> Iterator[tuple[ast.AST, str, Chain]]:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return
        yield node, function, chain
        if isinstance(node, SCOPES):
            outer, inner = scope_parts(node)
            name = (
                node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            )
            for part in outer:
                yield from visit(part, function, chain)
            within = [*chain, (node, scope_bindings(node))]
            for part in inner:
                yield from visit(part, name, within)
        else:
            for part in ast.iter_child_nodes(node):
                yield from visit(part, function, chain)

    module: Chain = [(tree, scope_bindings(tree))]
    for part in ast.iter_child_nodes(tree):
        yield from visit(part, "<module>", module)


def shadowed(name: str, chain: Chain) -> bool:
    """Whether `name`, read in the innermost scope of `chain` (the module first), resolves to a
    binding of the file's rather than to the builtin: Python's own lookup, the innermost scope
    outward, past every enclosing class body, which a nested scope does not see, and through a
    `global` straight to the module, where only an import hides (`scope_bindings`)."""
    for depth, (node, (bound, declared_global, _)) in enumerate(reversed(chain)):
        if depth and isinstance(node, ast.ClassDef):
            continue
        if name in declared_global:
            return name in chain[0][1][0]
        if name in bound:
            return True
    return False


def binds_at_run_time(name: str, chain: Chain, *, walrus: bool) -> bool:
    """Whether a binding of `name` made in the innermost scope of `chain` lands in a module or a
    class body, which Python looks up at run time: made there, made in a function under `global`,
    or a walrus target in a comprehension, which binds in the nearest scope around it that is not
    a comprehension."""
    depth = len(chain) - 1
    while walrus and isinstance(chain[depth][0], COMPREHENSIONS):
        depth -= 1
    node, (_, declared_global, _) = chain[depth]
    return isinstance(node, RUN_TIME_SCOPES) or name in declared_global
