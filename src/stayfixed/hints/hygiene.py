"""Name what could have falsified a red test run, before the diff is blamed.

Uncommitted work in the tree produces a red run that no baseline A/B can attribute, because both
halves of the A/B run inside it: the measurement describes a tree nobody is merging. It has cost
real time, twice in one branch's retro. It belongs to no stack and is named here; a fault that
is one stack's own, such as Python's stale bytecode, is named by that stack's profile
(`stayfixed.profiles.hints`).

Warn-only by construction: the tool has already run, and the verdict this guards is the
human's next sentence, not the command. Once per context, which the dispatcher's `once_key`
owns (see `hooks.py`, and `stayfixed.hooks.dispatch`, which decides and banks the one delivery, for
what that currently means).

Which hints speak is decided by the command that failed, never by configuration: the command is
split into simple commands with the shared scanner's tokens and segments, each unwrapped as
`RedRunHint.recognises` describes, and every shipped hint is asked whether it recognises one of
them. When none does, nothing is said, the dirty-tree line included: the core cannot tell a
failed test run from a failed `grep`, and the one delivery per context belongs to the first
failed test run. A command the scanner cannot read is recognised by nobody
(`simple_commands`).

Which harness field says a run was red is read from the documentation, not guessed: the Claude
Code hooks reference gives the Bash `tool_response` as `stdout`, `stderr`, `interrupted` and
`isImage` with no exit code, and a non-zero exit arriving on `PostToolUseFailure` as
`error: "Exit code N\\n…"`. `red_exit` reads both that shape and a `tool_response.exit_code`,
so the notice is keyed on whichever the harness sends rather than on a field one lacks.

Nothing a repository authored leaves this module. The notice carries the fixed sentences below,
counts this module computed, and lines a shipped hint rendered from its own counts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stayfixed.gitenv import answer_lines, git_run
from stayfixed.guards.api import contained_roots
from stayfixed.hints import bashscan
from stayfixed.profiles.adapters import shipped_adapters
from stayfixed.profiles.hints import answer, shipped_hints

if TYPE_CHECKING:
    from stayfixed.config.schema import Config
    from stayfixed.profiles.hints import RedRunHint

# Anchored TWICE, redundantly: the `\A` here and the `.match` at the call site each pin the read
# to index 0, so removing either one alone is a no-op -- measured, in both directions -- and only
# removing BOTH unanchors it. Do not read one of them as dead weight: unanchored, a number is
# read out of arbitrary captured stderr, and a line of test output that merely quotes an exit
# code is then taken for the run's own. The documented shape puts `Exit code N` at the very
# START of `error`, which is what the pair is protecting. The digits are bounded, and a longer run
# of them is no exit code: `int()` raises past 4,300 digits, and an exit code has at most three.
_EXIT_CODE_ERROR = re.compile(r"\AExit code (\d{1,9})(?!\d)")
# A named cap (CONTRIBUTING.md#named-caps) of its own, and no shipped file changes with it. Not
# `gitenv.GIT_TIMEOUT_SECONDS`: that constant covers "local, argument-free, read-only" queries, and
# `git status --porcelain` walks the worktree. A timeout here is `None`, "could not answer", which
# `test hygiene` turns into a refusal.
STATUS_TIMEOUT_SECONDS = 20

LEAD = "Before calling this red a flake, pre-existing, or caused by the branch:"
DIRTY = (
    "{count} uncommitted change(s) in the tree -- this run measured a tree nobody is merging. "
    "A stashed-baseline A/B cannot see this: both halves run in it."
)


def simple_commands(command: str) -> list[list[str]]:
    """Each simple command of `command`, unwrapped to its own program and arguments.

    `[]` for a command the scanner cannot read (`bashscan.tokenize` returns `None`): no hint is
    asked about text that is not a command line, so such a run gets no note. That under-reports
    a real failed run whose command the scanner cannot read, the safe direction for a warn-only
    note, where guessing from a substring would put one stack's advice on another's run.
    """
    tokens = bashscan.tokenize(command)
    if tokens is None:
        return []
    adapters = shipped_adapters()
    found: list[list[str]] = []
    for segment in bashscan.segments(tokens):
        words = bashscan.command_words(segment, lambda w: any(a.recognises(w) for a in adapters))
        if words:
            found.append(words)
    return found


def red_exit(raw: Mapping[str, Any]) -> int | None:
    """The non-zero exit code this payload reports, in either shape, or `None`.

    `isinstance(code, bool)` is excluded on purpose: `True` is an `int` equal to 1 in Python,
    so a harness that put a boolean in `exit_code` would otherwise be read as "exited 1".
    """
    response = raw.get("tool_response")
    if isinstance(response, dict):
        code = response.get("exit_code")
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            return code
    error = raw.get("error")
    if isinstance(error, str):
        match = _EXIT_CODE_ERROR.match(error)
        if match and int(match.group(1)) != 0:
            return int(match.group(1))
    return None


def dirty_count(root: Path) -> int | None:
    """Uncommitted changes, or `None` when git could not answer. Never `0` for the latter:
    the two mean opposite things to a person deciding whether to trust a red run.

    Through `gitenv.git_run`: `root` is the project root the dispatcher resolved or `--root`
    resolved, not a repository value, and `--` closes the argument list so no pathspec can be
    smuggled in. `status --porcelain` prints a name raw under `core.quotePath=false`, in
    whatever bytes the disk holds it, and `git_run` reads those losslessly; counted by the
    lines git wrote (`answer_lines`), a name holding a line separator is still one entry.
    """
    code, out = git_run(root, "status", "--porcelain", "--", timeout=STATUS_TIMEOUT_SECONDS)
    if code != 0:
        return None
    return sum(1 for line in answer_lines(out) if line.strip())


def notice(dirty: int | None, notes: Sequence[str]) -> str | None:
    """The dirty-tree sentence when the tree is dirty, then each hint's line, under `LEAD`; or
    `None` for silence."""
    lines: list[str] = []
    if dirty:
        lines.append(DIRTY.format(count=dirty))
    lines.extend(notes)
    if not lines:
        return None
    return LEAD + "\n- " + "\n- ".join(lines)


# A hint that fails costs its own line and nothing else: one whose module did not load is `None`
# and skipped, and the two guards below catch everything else, broad on purpose, because an
# exception out of one stack's hint would reach the dispatcher, which records
# it and drops the handler's whole context -- the dirty-tree line and every other stack's line
# with it. They are also silent, and that is a cost rather than a design: a handler has no sink
# to record into, and `stayfixed test hygiene`, which exposes the rest, never calls `recognises`,
# so a broken one is visible nowhere. Recording it in the hook's diagnostics would take a sink the
# handler can reach, a change to the handler contract and not to this module.
def _recognises(hint: RedRunHint, commands: Sequence[Sequence[str]]) -> bool:
    try:
        return any(hint.recognises(argv) for argv in commands)
    except Exception:
        return False


def _note(hint: RedRunHint, root: Path, config: Config) -> str | None:
    try:
        return answer(hint, contained_roots(root, config))[1]
    except Exception:
        return None


def context_for(command: str, root: Path, config: Config) -> str | None:
    """The notice after `command` failed: `None` unless some shipped hint recognises one of its
    simple commands, and then the dirty-tree line and the line of each hint that recognised it,
    in the order `shipped_hints` gives."""
    commands = simple_commands(command)
    if not commands:
        return None
    hints = shipped_hints()
    speaking = [hint for _, hint in hints if hint is not None and _recognises(hint, commands)]
    if not speaking:
        return None
    notes: list[str] = []
    for hint in speaking:
        note = _note(hint, root, config)
        if note:
            notes.append(note)
    return notice(dirty_count(root), notes)
