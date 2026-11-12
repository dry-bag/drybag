"""The background-cleanup judge: hints about a cleanup a reap can skip, and never a refusal.

The harness can reap a backgrounded call's parent shell without killing its process group, so a
cleanup written as a later line of the same command may never run, and the `&` jobs it was meant
to stop survive, re-parented to PID 1. This module does not work around the harness; it names the
command SHAPE in which the leak is written::

    for i in $(seq 1 14); do (while :; do :; done) & done
    LOADPIDS=$(jobs -p)
    ...
    kill $LOADPIDS 2>/dev/null

`trap 'kill ...' EXIT INT TERM` runs where a trailing line does not, because the shell fires it
however it leaves. The agent in the session writes the command and can spell around any reading
here, so every reading is a hint naming the remedy, never a refusal.

Four readings of that one shape:

1. `LEAK_HINT`: a call with `run_in_background: true` that backgrounds a job with a bare `&` and
   cleans up nowhere -- no `trap` naming `EXIT` and no trailing `wait`. The `&` is read as a
   TOKEN from `bashscan.tokenize`, never from raw text, where `&&` and `2>&1` look alike, and
   from a command whose heredoc BODIES are gone (`_scan`). A lone `cmd &` counts: the harness
   already backgrounds the whole command, so the inner `&` adds only a child nothing reaps.
2. `SLEEP_HINT`: a backgrounded call whose FIRST simple command is `sleep`. The call returns at
   once, so the sleep buys nothing; `pytest ...; sleep 1` is not that misunderstanding.
3. `RESTORE_HINT`: a last line that restores a backup outside a trap, on ANY call: a foreground
   call that outlives its timeout is backgrounded by the harness, which no flag says at
   `PreToolUse` time. Because it reads every call, it fires only on a ROUND TRIP -- an earlier
   `cp`/`mv` whose two paths the last command swaps back.
4. `EXIT_ECHO_HINT`: a backgrounded chain ending in `; echo …`, whose completion notification
   reports the echo's exit code. It cannot fire with 3: both are a last command.

DEGRADES TOWARD SILENCE: an unparseable command, a trap read too generously and a `&` past the
recursion bound get no hint. The known false hint is a BITWISE `&` in an arithmetic expansion
(`echo $((3 & 1))`): suppressing `&` inside a run opened by `((` would also silence
`((sleep 1; sleep 2) & echo x)`, a real leak.

Not covered:

- by the `&` and `sleep` readings, a command the harness backgrounds ITSELF after the
  foreground timeout, with no `run_in_background` in the payload;
- `trap - EXIT`, which REMOVES a trap, reads as a trap;
- a `&` inside a `$(...)` substitution, or in a body fed to a language interpreter
  (`python3 - <<'PY'`);
- a `-c` string that another option in the same cluster displaces (`bash -cO extglob '...'`);
- a backup copied INTO A DIRECTORY (`cp ci.yml bak/`, `cp -t bak ci.yml`, `cp a b bak`);
- a restore line carrying a redirect (`cp a.bak a 2>/dev/null`), whose pieces read as operands;
- a command longer than `bashscan.MAX_COMMAND_CHARS`, which is not read at all.
"""

from __future__ import annotations

import re
import shlex
from itertools import dropwhile
from pathlib import Path
from typing import NamedTuple

from drybag.hints import bashscan

# The backgrounding operator, as an operator PIECE: `bashscan.tokenize` emits `&&`, `>&`, `&>`
# and `&>>` as compound tokens, so none of them can be mistaken for it.
_BACKGROUND_OPERATOR = "&"

# Pieces that, standing immediately before an `&`, make it part of a LONGER operator: `|&` (pipe
# both streams), `;&` and `;;&` (case fall-through), which `bashscan` decomposes to single
# characters. Without this, `cmd |& grep x` would read as backgrounding.
_COMMAND_ENDING_PIECES = frozenset({"|", ";"})

# `trap ACTION SIGNAL...`, both words matched as EXACT TOKENS, so `echo 'trap ... EXIT'` (one
# quoted token) is a mention, not a trap. Only `EXIT` is required; other signals are extra tokens.
_TRAP = "trap"
_EXIT_SIGNAL = "EXIT"

# `--` ends option parsing, so tokens after it are operands: `printf '%s\n' -- trap EXIT` is no
# trap and excuses no leak.
_OPTION_TERMINATOR = "--"

# Shells whose `-c <string>` argument is itself a shell command line, and whose heredoc body
# is a program rather than data.
_SHELL_INTERPRETERS = frozenset(
    {"ash", "bash", "csh", "dash", "fish", "ksh", "mksh", "rbash", "sh", "tcsh", "zsh"}
)

# A single-dash short-option cluster containing `c`: `-c`, `-lc`, `-ic`, anchored at both ends so
# `--check` and `-I{}` never match. The leading class EXCLUDES `c`, so the literal can match at one
# position only and a token like `-ccc...c0` is read in linear time, not quadratic;
# `test_the_shell_c_flag_matches_exactly_what_the_backtracking_pattern_did` holds the language.
_SHELL_C_FLAG = re.compile(r"\A-[A-Zabd-z]*c[A-Za-z]*\Z")

# A named cap (CONTRIBUTING.md#named-caps) on descent into a command hidden inside a string, and no
# shipped file changes with it. Real nesting rarely goes past one level. Exceeding it stops looking,
# which says nothing: a shell inside a shell inside a shell is a shape nobody reaches by accident.
_MAX_RECURSION_DEPTH = 3

LEAK_HINT = (
    "This command backgrounds a job with `&` and expresses its cleanup as a later line of "
    "the same command. That is not cleanup: the harness can reap the parent shell before the "
    "line is reached, and an `&`-backgrounded child survives the reap, re-parents to PID 1, "
    "and runs until something finds it, long after the session that started it has ended.\n"
    "Do one of these instead:\n"
    "- Put the cleanup in a trap, which runs however the shell exits: "
    "`trap 'kill ${=PIDS}' EXIT INT TERM`. Note `${=PIDS}` and not `$PIDS` -- zsh does not "
    "word-split an unquoted parameter, so `kill $PIDS` passes the whole list as ONE argument "
    "and silently fails.\n"
    "- Or do not background the helper at all. This call already carries "
    "`run_in_background: true`, so the harness is backgrounding the whole command for you; an "
    "inner `&` only adds a child that nothing can reap.\n"
    "- Best of all, size the run to finish in the foreground: parallelise the suite "
    "rather than wait on it."
)

SLEEP_HINT = (
    "This command is backgrounded (`run_in_background: true`) and begins with `sleep`. A "
    "backgrounded call returns immediately -- the harness does not wait for it -- so the sleep "
    "buys nothing and the check after it runs at once, in the background, unread.\n"
    "To wait for a condition, use the Monitor tool with an until-loop, or run the check in the "
    "foreground without the sleep."
)

# `{trap}` carries its own quoting, so the template must NOT wrap it in quotes: the tokens lost
# theirs, and `cp a.bak "a; touch x"` would come back as a different command. `shlex.quote` per
# token, then once more for the line, makes it one word for `trap`. A restore meant to expand
# (`cp $BAK $ORIG`) comes back quoted and inert: over-quoted advice is visibly wrong, not run.
RESTORE_HINT = (
    "This command restores a backup on its last line (`{restore}`). That line runs only if the "
    "shell survives to reach it: a foreground call that outlives the 120 s timeout is "
    "backgrounded by the harness and may be reaped before it, leaving the tree mutated. Put the "
    "restore in a trap, which runs however the shell exits: `trap {trap} EXIT INT TERM` as the "
    "FIRST line."
)

_RESTORE_COMMANDS = frozenset({"cp", "mv"})

# `cp`/`mv` options that name the destination instead of leaving it as the last operand.
_TARGET_DIRECTORY_OPTIONS = frozenset({"-t", "--target-directory"})

# A backgrounded call's completion notification reports the LAST command's exit code, so
# `check --run > out.log; echo "exit=$?"` notifies 0 after `check` failed. Keyed on the background
# flag: a foreground call's status is read from the tool result itself.
EXIT_ECHO_HINT = (
    "This backgrounded command ends in `; {tail}`, so its completion notification will report "
    "that command's exit code, not the code of `{masked}`. Either make `{masked}` the last "
    "command of the chain, or read its status from the output it wrote -- never from the "
    "notification."
)
_ECHO_COMMANDS = frozenset({"echo", "printf"})
# Words that can stand before the last `;` without naming a command anyone typed: in
# `for f in a b; do cat $f; done; echo done` the masked segment is the keyword `done` alone.
_STATEMENT_KEYWORDS = frozenset({"done", "fi", "esac", "then", "else", "elif", "do", "}", ")"})
# Every operator that ends a simple command, AFTER `operator_pieces` has split welded runs.
_CHAIN_OPERATORS = frozenset({";", "&&", "||", "|", "&"})


def judge(command: str, *, background: bool) -> str | None:
    """The whole contract, as a pure function of the command text and the background flag: the
    hint for one Bash call, or `None`. It never raises on a string input."""
    if len(command) > bashscan.MAX_COMMAND_CHARS:
        return None
    if background:
        tokens = bashscan.tokenize(command)
        if tokens is not None and _begins_with_sleep(tokens):
            return SLEEP_HINT
        backgrounds, cleaned = _scan(command, depth=0)
        if backgrounds and not cleaned:
            return LEAK_HINT
    hints = [
        hint
        for hint in (_restore_hint(command), _exit_echo_hint(command) if background else None)
        if hint
    ]
    return "\n\n".join(hints) or None


def _begins_with_sleep(tokens: list[str]) -> bool:
    """The first simple command's program is `sleep`, however it is spelled: `/bin/sleep 30`,
    `FOO=1 sleep 30`, `env sleep 30` and `( sleep 30 )` all count.

    `dropwhile`, not a filter: only a LEADING `(` opens the same command. `X=$(sleep 5) pytest -q`
    segments to `['X=$', '(', 'sleep', '5', ')', ...]`, and its first word is the assignment's.

    Missed: `time sleep 30`, `uv run sleep 30`, and any prefix `command_words` does not resolve.
    """
    commands = bashscan.segments(tokens)
    if not commands:
        return False
    segment = list(dropwhile(lambda t: t == "(", commands[0]))
    words = bashscan.command_words(segment)
    return bool(words) and Path(words[0]).name == "sleep"


def _restore_hint(command: str) -> str | None:
    """A trailing restore with no trap, foreground or not."""
    tokens = bashscan.tokenize(command)
    if tokens is None or _installs_an_exit_trap(tokens):
        return None
    restore = _restores_at_the_end(tokens)
    if not restore:
        return None
    return RESTORE_HINT.format(restore=restore, trap=shlex.quote(restore))


def _exit_echo_hint(command: str) -> str | None:
    """Advice for a backgrounded chain whose last command is an echo after a `;`."""

    tokens = bashscan.tokenize(command)
    if tokens is None:
        return None
    masked = _echo_after_a_semicolon(tokens)
    if masked is None:
        return None
    return EXIT_ECHO_HINT.format(masked=masked[0], tail=masked[1])


def _echo_after_a_semicolon(tokens: list[str]) -> tuple[str, str] | None:
    """``(masked, tail)`` -- the command whose exit code a trailing `; echo …` hides and that
    echo, both as shell text -- or None.

    Only a `;` masks: after `&&` a failing command skips the echo, and after `||` the code is
    already lost to `||`. Newlines arrive as `;`, so a chain's trailing separators (an editor's
    final newline) are dropped before the breaks are counted.

    Silent where the masked segment is no command: a statement's terminator (`done`, `fi`) or a
    second echo, about which advice would name something the reader never wrote.
    """

    pieces: list[str] = []
    for token in tokens:
        pieces.extend(bashscan.operator_pieces(token))
    while pieces and pieces[-1] in _CHAIN_OPERATORS:
        pieces.pop()
    breaks = [index for index, piece in enumerate(pieces) if piece in _CHAIN_OPERATORS]
    if not breaks or pieces[breaks[-1]] != ";":
        return None
    tail = pieces[breaks[-1] + 1 :]
    words = bashscan.command_words(tail)
    if not words or Path(words[0]).name not in _ECHO_COMMANDS:
        return None
    start = breaks[-2] + 1 if len(breaks) > 1 else 0
    masked = _command_head(pieces[start : breaks[-1]])
    head = bashscan.command_words(masked)
    if not head:
        return None
    program = Path(head[0]).name
    if program in _STATEMENT_KEYWORDS or program in _ECHO_COMMANDS:
        return None
    return " ".join(masked), _as_shell_text(tail)


def _command_head(segment: list[str]) -> list[str]:
    """The command and its arguments, without its redirects.

    The head stops at the first piece in `bashscan.REDIRECT_OPERATORS`, and a lone digit left in
    front of it is popped as a file descriptor (`cmd 2> err.log`). The pop is a guess: tokens
    drop the whitespace that tells `cmd 2> err.log` from `sleep 5 > out.log`, so `sleep 5` comes
    back `sleep`, an accepted imprecision in advice. The raw command text would settle it.
    """

    head: list[str] = []
    for piece in segment:
        if piece in bashscan.REDIRECT_OPERATORS:
            break
        head.append(piece)
    if len(head) > 1 and head[-1].isdigit():
        head.pop()
    return head


def _backgrounds_a_job(tokens: list[str]) -> bool:
    """Whether these tokens background a job with the async operator.

    Tokens, not text: `a && b` and `cmd 2>&1` carry a `&` and background nothing. Each token is
    decomposed (`bashscan.operator_pieces`), because `shlex` fuses punctuation and
    `(sleep 300 &)` arrives as `['(', 'sleep', '300', '&)']`. A `&` straight after `|` or `;`
    belongs to a longer operator (`_COMMAND_ENDING_PIECES`) and is skipped.
    """
    for token in tokens:
        pieces = bashscan.operator_pieces(token)
        for index, piece in enumerate(pieces):
            if piece != _BACKGROUND_OPERATOR:
                continue
            if index and pieces[index - 1] in _COMMAND_ENDING_PIECES:
                continue
            return True
    return False


def _installs_an_exit_trap(tokens: list[str]) -> bool:
    """Whether these tokens install a `trap` naming `EXIT`.

    Per SEGMENT, so `echo trap && echo EXIT` is no trap; positional within it rather than
    argv0-keyed, so `do trap 'x' EXIT` in a loop counts. Reading a trap too generously costs a
    missed hint, the cheap direction.
    """
    for segment in bashscan.segments(tokens):
        seen_trap = False
        for token in segment:
            if token == _OPTION_TERMINATOR:
                break
            if token == _TRAP:
                seen_trap = True
            elif seen_trap and token == _EXIT_SIGNAL:
                return True
    return False


class _Copy(NamedTuple):
    """What a `cp`/`mv` simple command moves, once its options are out of the way."""

    sources: tuple[str, ...]
    destination: str
    into_directory: bool


def _copy_operands(command: list[str]) -> _Copy | None:
    """A `cp`/`mv` command's operands, or None when it has too few to move anything.

    Options first, since `command[-1]` is the destination only without them (`cp -a X X.bak`,
    `mv -t DIR src`). The split is shallow:

    - A token starting with `-` is an option and dropped, `--preserve=all` included; a bare `-`
      is stdin/stdout, an operand. After `--` every token is an operand.
    - `-t DIR` / `--target-directory[=]DIR` name the destination, and every operand is a source.
      The cluster `-tDIR` is dropped whole, so `cp -tDIR a b` reads `b` as the destination.
    - Fewer than two operands and no `-t` (`cp --help`, `cp x`) is no move: None.

    `into_directory`: `-t`, or a third operand, makes the destination a DIRECTORY, holding a path
    this reader does not construct.
    """
    operands: list[str] = []
    destination: str | None = None
    index = 1
    operands_only = False
    while index < len(command):
        token = command[index]
        index += 1
        # `noqa: S105` -- `token` here is a shell word off a command line, never a credential,
        # and `-` is the getopt spelling of stdin/stdout. The rule keys on the variable name.
        if operands_only or not token.startswith("-") or token == "-":  # noqa: S105
            operands.append(token)
        elif token == _OPTION_TERMINATOR:
            operands_only = True
        elif token in _TARGET_DIRECTORY_OPTIONS:
            destination = command[index] if index < len(command) else destination
            index += 1
        elif token.partition("=")[0] in _TARGET_DIRECTORY_OPTIONS and "=" in token:
            destination = token.partition("=")[2]
    if destination is not None:
        return _Copy(tuple(operands), destination, True) if operands else None
    if len(operands) < 2:
        return None
    return _Copy(tuple(operands[:-1]), operands[-1], len(operands) > 2)


def _restores_at_the_end(tokens: list[str]) -> str | None:
    """The trailing restore command as shell text, or None.

    A restore is a ROUND TRIP: `cp X X.bak` early and `cp X.bak X` last, the same two paths
    swapped back, or a `git restore` / `git checkout --`. Matching the swap keeps an ordinary
    chained copy (`cp src/a build/a; make; cp build/a dist/a`) silent, since it puts nothing back.
    """

    commands = bashscan.segments(tokens)
    if len(commands) < 2:
        return None
    last = commands[-1]
    if last[:2] == ["git", "restore"] or last[:3] == ["git", "checkout", "--"]:
        return _as_shell_text(last)
    if last[0] not in _RESTORE_COMMANDS:
        return None
    restore = _copy_operands(last)
    if restore is None or restore.into_directory:
        return None
    backups: set[tuple[str, str]] = set()
    for command in commands[:-1]:
        if command[0] not in _RESTORE_COMMANDS:
            continue
        backup = _copy_operands(command)
        if backup is None or backup.into_directory:
            continue
        backups.add((backup.sources[0], backup.destination))
    if (restore.destination, restore.sources[0]) in backups:
        return _as_shell_text(last)
    return None


def _as_shell_text(command: list[str]) -> str:
    """A tokenized command back as text a shell reads the same way this file read it: words
    quoted, redirect operators bare, so `>>` stays an append and not an argument.

    A quoted argument that was all punctuation (`echo '>>'`) comes back bare: tokens carry no
    memory of their quoting.
    """
    return " ".join(
        token if token in bashscan.REDIRECT_OPERATORS else shlex.quote(token) for token in command
    )


def _nested_programs(tokens: list[str], heredocs: list[bashscan.Heredoc]) -> list[str]:
    """Command text this command hands to a shell: `-c` strings and shell-fed heredoc bodies.

    A `-c` string is ONE token, and a heredoc body is out of the scanned text, so both are read
    back out as programs. Only SHELL headers qualify for the heredoc half: a body fed to `cat` is
    data, and one fed to `python3` is another language.
    """
    programs: list[str] = []
    for segment in bashscan.segments(tokens):
        shell: str | None = None
        for index, token in enumerate(segment):
            if Path(token).name in _SHELL_INTERPRETERS:
                shell = Path(token).name
            elif shell is not None and _SHELL_C_FLAG.match(token):
                # The NEXT token only: a later argument re-tokenized without its quoting
                # (`"https://h/p?a=1&b=2"`) would yield a bare `&`.
                programs.extend(segment[index + 1 : index + 2])
                shell = None
    for heredoc in heredocs:
        header = bashscan.tokenize(heredoc.header)
        if header is None:
            continue
        if any(
            Path(token).name in _SHELL_INTERPRETERS
            for segment in bashscan.segments(header)
            for token in segment
        ):
            programs.append(heredoc.body)
    return programs


def _scan(command: str, depth: int) -> tuple[bool, bool]:
    """`(backgrounds a job, cleans up)` for `command` and everything nested in it: cleaning up
    is installing an EXIT trap or ending in `wait`.

    Collected over the WHOLE command tree: a cleanup anywhere excuses a `&` anywhere, the
    permissive direction.

    HEREDOC BODIES ARE NOT GRAMMAR, so both reads ask for tokens with every body removed: a `&`
    in a file written through `cat > x <<EOF` is data, and an apostrophe there is no open quote.
    Shell-fed bodies are still judged, through `_nested_programs` and the heredoc list.

    An unparseable command yields `(False, False)`: with the bodies gone, an unbalanced quote is
    a command no shell would run, and a raw-text fallback would misread `&`.
    """
    tokens = bashscan.tokenize(command, keep_unquoted_bodies=False)
    if tokens is None:
        return False, False
    # `prepare` again, for the heredoc list alone, with the same flag so the two reads agree.
    _text, heredocs = bashscan.prepare(command, keep_unquoted_bodies=False)
    backgrounds = _backgrounds_a_job(tokens)
    commands = bashscan.segments(tokens)
    cleaned = _installs_an_exit_trap(tokens) or (bool(commands) and commands[-1][0] == "wait")
    if depth < _MAX_RECURSION_DEPTH:
        for program in _nested_programs(tokens, heredocs):
            nested_backgrounds, nested_cleaned = _scan(program, depth + 1)
            backgrounds = backgrounds or nested_backgrounds
            cleaned = cleaned or nested_cleaned
    return backgrounds, cleaned
