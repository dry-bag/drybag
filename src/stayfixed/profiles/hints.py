"""What a stack's profile says after that stack's test runner failed.

The core knows a red run and a dirty tree and nothing about any stack; a profile that has more to
say ships it as `HINT` in a `hygiene.py` beside its data. The test command that failed chooses
which hints speak, through `RedRunHint.recognises`, and `[stayfixed] profile` plays no part: a
repository in several languages runs several stacks' suites, and the stack whose runner failed is
the one whose advice applies.

`note` receives counts and nothing else, or `None` for a walk that could not tell: both callers,
the hook's notice and `stayfixed test hygiene`, ask a hint through `answer`, which reads its report
through `counts`. That keeps a key
only when it is a count name (`COUNT_NAME`: lower-case letters, digits and underscores, at most
32 characters) and its value only when it is a plain integer, and drops the rest before anything
reaches `note` or `--json`.
A key is text a hint chose, and one built from the tree it walked would otherwise carry that
tree's names out; the grammar admits no `/`, `.`, space or upper case, so no path, file name or
command text a repository authored can pass as a count's name. So the trust rule
(`CONTRIBUTING.md`, "Repository bytes are data") holds for every hint that renders from its
argument alone, which is the contract below; a hint that kept a string from `report` on itself
for `note` to print would break the contract, and nothing but review catches that.

The listing is `stayfixed.profiles.stack_directories`, through `importlib.resources` over this
package and never over a repository path, so only a hint stayfixed itself ships is ever imported.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from stayfixed.profiles import stack_directories, stack_module

HINT_FILE = "hygiene.py"
# What a count may be called: a lower-case word of letters, digits and underscores, which is a
# fixed name in a hint's code and never something read off the tree. The length is a named cap
# (CONTRIBUTING.md#named-caps): 32 characters is room for any count's name and too little for a
# sentence, and no shipped file changes with it (the Python profile's names are `stale` and
# `roots`).
COUNT_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
# How large a count may be, exclusive: a named cap too. A count is a number of files or roots,
# which no tree comes near, so past the signed 64-bit range an integer is a defect in the hint
# rather than a count, and an unbounded one makes `json.dumps` raise past 4300 digits. No shipped
# file changes with it.
COUNT_LIMIT = 2**63


class RedRunHint(Protocol):
    """A stack's advice after its test runner failed. A profile ships one as `HINT` in its
    `hygiene.py`; the profile's name is its directory's, never a second attribute."""

    def recognises(self, argv: Sequence[str]) -> bool:
        """Whether this simple command runs this stack's tests.

        `argv` is one simple command with exactly this removed from its front, as often as it
        recurs: a shell assignment (`FOO=1`), `env`, and `uv … run` with every word up to the
        first a runner adapter recognises (`uv run --locked pytest` and `uv run -m pytest`
        arrive as `pytest`), the program named by its path or its bare name (`/usr/bin/env`
        too); behind `uv run`, an `env`, another launcher or a uv option's value before that word
        goes with it. Everything else arrives as written: any other launcher (`poetry run`,
        `npx`, `sudo`, `time`), a `uv` command in which no adapter recognises a word (it arrives
        whole, as `uv …`), and the `(` that opens a subshell or the `{` that opens a group, which
        stays the first word.
        """
        ...

    def report(self, roots: Sequence[Path]) -> Mapping[str, int] | None:
        """The one walk: counts of what could have falsified the run, under `roots`, each under a
        name `COUNT_NAME` matches; `counts` drops anything else. `roots` is `ledger.code_roots`
        contained (`stayfixed.roots.contained_roots`), which the caller computes and hands
        over, so a stack's code never imports it. `None` when the walk stopped at a
        bound before it had seen the tree, so no count it reached is an answer either way: not a
        key among the counts, since every key a hint returns is a count name it chose.
        `stayfixed test hygiene` refuses on `None` rather than read the tree as judged."""
        ...

    def note(self, counts: Mapping[str, int] | None) -> str | None:
        """One line for `counts`, or `None` when nothing in them is worth saying. Given `None`,
        the report's, the line says the hint could not tell."""
        ...


def hint_modules() -> tuple[str, ...]:
    """The stacks that carry a `hygiene.py`, by name."""
    return stack_directories(HINT_FILE)


class NotText(TypeError):
    """A hint's note was neither text nor `None`, which its protocol does not allow."""


def shipped_hints() -> tuple[tuple[str, RedRunHint | None], ...]:
    """Every profile `hint_modules` lists, in its order, with its `HINT`, or `None` for one whose
    `hygiene.py` does not import or defines no `HINT`.

    Never raises for one profile's module: importing a module runs its code, so any exception can
    come out of it, and each caller decides what an absent hint costs.
    """
    return tuple((name, _hint(name)) for name in hint_modules())


def _hint(name: str) -> RedRunHint | None:
    try:
        hint: RedRunHint = stack_module(name, HINT_FILE.removesuffix(".py")).HINT
    except Exception:
        return None
    return hint


def answer(hint: RedRunHint, roots: Sequence[Path]) -> tuple[dict[str, int] | None, str | None]:
    """`hint`'s counts under `roots` (`counts`), `None` when it could not tell, and its note on
    them: non-empty text, or `None` when it has nothing to say.

    Raises `NotText` for a note that is neither text nor `None`, and lets whatever `report` or
    `note` raises through.
    """
    report = counts(hint, roots)
    note = hint.note(report)
    if note is not None and not isinstance(note, str):
        raise NotText
    return report, note or None


def counts(hint: RedRunHint, roots: Sequence[Path]) -> dict[str, int] | None:
    """`hint`'s report under `roots` as a fresh mapping of count names to plain integers, or
    `None` when the report is: the hint could not tell.

    A key is kept only when it is a `str` matching `COUNT_NAME`, and a value only when it is an
    `int` from 0 up to `COUNT_LIMIT`. Exactly those types, and no subclass: a subclass keeps its
    own `__str__` and `__format__`, so it can print as text the check never saw, and `bool` is one
    (`red_exit` refuses it for the same reason). What `report` raises reaches the caller.
    """
    report = hint.report(roots)
    if report is None:
        return None
    return {
        key: value
        for key, value in report.items()
        if type(key) is str
        and COUNT_NAME.fullmatch(key)
        and type(value) is int
        and 0 <= value < COUNT_LIMIT
    }
