"""Bash-command scanning shared by the session hints.

This module reports what the TEXT of a command says, and a caller judges that text. It never runs
anything, and it never hands a caller LESS text than a shell would execute: every place below
that discards text discards only text a shell would not run.

`prepare` reduces a command in a fixed order, and each step says where it is defined why its place
in the order matters:

1. `strip_comments`: a `#` opens a comment only at the start of a word, which `shlex`'s
   `commenters` gets wrong (it reads `echo a#b && cat secrets/.env` as `echo a`).
2. `scan_heredocs`: QUOTING decides whether a body stays in the text. An unquoted body is
   expanded by the shell and kept; a quoted one is inert data and removed, which is what lets a
   test write a fixture whose content mentions a protected name. THE COMMAND THE HEREDOC FEEDS
   decides whether the body is a program: every heredoc is reported with its header line, so a
   caller judges a body fed to `bash` or an interpreter as a command whatever its quoting.
3. `_strip_line_continuations`: a backslash-newline joins two lines, as bash joins it.
4. `_newlines_to_separators`: a newline separates commands as `;` does, while `shlex` would drop
   it as whitespace and an argv0-keyed caller would judge a multi-line command by its first line.

`segments` and `pipelines` split the tokens at separators, after `operator_pieces` decomposes a
run of fused punctuation (`);`, `;>`) into the operators bash reads it as.

Tokenizing is built on `shlex.shlex` directly: `punctuation_chars` is a constructor argument, not
a parameter of `shlex.split`, and it surfaces redirects and separators as their own tokens.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from drybag.hints.runners import is_launcher, names_a_test_run, past_run

# A named cap (CONTRIBUTING.md#named-caps), and no shipped file changes with it. It bounds every
# hint's read of a command: above it no hint reads the command at all. 64 KiB is far past any
# command a person or a model types and far below where tokenizing costs seconds.
MAX_COMMAND_CHARS = 65_536
_SEPARATORS = frozenset({";", "&&", "||", "|", "&"})
# `shlex`'s `punctuation_chars` mode emits a run of these as ONE token, so a separator welded to a
# neighbour (`);`, `;>`) is no member of `_SEPARATORS`; `operator_pieces` decomposes the run.
_PUNCTUATION_CHARS = frozenset("();<>|&")
# The characters that END a command. A run without one of these (`((`, `))`, `>>`, `<<`,
# `<<<`, `<>`) cannot be hiding a separator, so it is handed back untouched.
_SEPARATOR_CHARS = frozenset(";&|")
# Operators that survive decomposition WHOLE, longest first: redirects carrying a separator
# character (`&>`, `>&`, `>|`), whose split would invent a command break and hide a write target,
# and redirects that can share a run with one (`>>;`). `;;`, `;&`, `;;&` and `|&` are absent:
# every piece of them ends a command, so single characters yield the right breaks.
_COMPOUND_OPERATORS = ("&>>", "<<<", "&>", ">&", "<&", ">|", ">>", "<<", "<>")
# Every redirect operator as `operator_pieces` hands it back. Public because `&>` and `&>>` begin
# with neither `>` nor `<`, so a first-character test cannot find where a command's words stop.
REDIRECT_OPERATORS = frozenset(_COMPOUND_OPERATORS) | {">", "<"}
# `<<'TAG'`, `<<"TAG"` and `<<\TAG` suppress expansion of the body; a bare `<<TAG` does not. One
# alternation, because a backreference to an optional quote group would accept a mismatched pair.
_HEREDOC = re.compile(
    # `(?<!<)` and `(?!<)` keep a here-string's `<`s from opening a heredoc, and `(?!\S)` keeps
    # `$((1<<2))` from one; `cat<<'EOF'` and `2<<EOF` are heredocs, as bash reads them.
    r"(?<!<)<<-?(?!<)\s*"
    r"(?:(?P<quote>['\"])(?P<quoted_tag>\w+)(?P=quote)|(?P<backslash>\\)?(?P<tag>\w+))"
    r"(?!\S)"
)
# A `#` opens a comment only at the start of a word; these are the characters that end the
# previous word for that purpose (whitespace is handled separately).
_WORD_BOUNDARY = frozenset({";", "&", "|", "(", ")", "<", ">"})
# `FOO=1 BAR=2 pytest`: a shell assignment token, not the command. `.match` anchors at index 0,
# and the value is irrelevant, so nothing anchors the end.
_ASSIGNMENT = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")
# `env pytest`: a bare wrapper token, not the command. `env` and `uv run` (`hints/runners.py`) are
# the only launchers read through; `poetry run`, `npx`, `sudo` and `time` are not.
_SINGLE_WRAPPERS = frozenset({"env"})


class Heredoc(NamedTuple):
    """One heredoc redirect found in a command.

    `header` is the source line carrying the `<<TAG` redirect -- the command the body is
    standard input to. `quoted` is True for `<<'TAG'`/`<<"TAG"`/`<<\\TAG`, whose body the
    shell does not expand; `body` is the body's raw text either way, so a caller that wants
    to judge it as a program has it regardless of quoting.
    """

    tag: str
    quoted: bool
    body: str
    header: str


def strip_comments(command: str) -> str:
    """``command`` with its shell comments removed, as a shell would read them.

    A comment opens only at the start of a word and runs to the end of its LINE; quotes are
    tracked across lines, so a `#` inside a multi-line quoted string stays in it.

    Runs BEFORE heredoc recognition, so `echo hi # <<'EOF'` carries no redirect that would swallow
    the following lines, and BEFORE `_newlines_to_separators`, so `ls # note` cannot swallow the
    commands after it.
    """

    kept: list[str] = []
    quote = ""
    escaped = False
    commented = False
    previous = ""  # the last character a shell would still be reading a word from
    for character in command:
        if commented:
            if character != "\n":
                continue
            commented, previous = False, character
        elif escaped:
            escaped = False
        elif quote == "'":
            quote = "" if character == "'" else quote  # single quotes escape nothing
        elif quote:
            if character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
        elif character == "\\":
            escaped = True
        elif character in "'\"":
            quote = character
        elif character == "#" and _starts_a_word(previous):
            commented, previous = True, character
            continue
        kept.append(character)
        previous = character
    return "".join(kept)


def _starts_a_word(previous: str) -> bool:
    """Whether a `#` following ``previous`` opens a comment rather than sitting in a word."""

    return previous == "" or previous.isspace() or previous in _WORD_BOUNDARY


def _quoted_spans(line: str, quote: str) -> tuple[list[bool], str]:
    """``(per-character "inside a quote" flags, quote state at the end of the line)``.

    `strip_comments`' quote model. ``quote`` is passed in and handed back so a caller carries the
    state across lines. Both quote delimiters are flagged as inside.
    """

    flags: list[bool] = []
    escaped = False
    for character in line:
        inside = bool(quote)
        if escaped:
            escaped = False
        elif quote == "'":
            if character == "'":
                quote = ""
        elif quote:
            if character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
        elif character == "\\":
            escaped = True
        elif character in "'\"":
            quote = character
            inside = True
        flags.append(inside)
    return flags, quote


def scan_heredocs(text: str, *, keep_unquoted_bodies: bool = True) -> tuple[str, list[Heredoc]]:
    """``(text with quoted heredoc bodies removed, every heredoc found)``.

    Expects comment-stripped text; `prepare` is the entry point that guarantees it. An unterminated
    quoted heredoc strips to the end of the command; an unterminated unquoted one keeps every line.

    ``keep_unquoted_bodies=False`` removes unquoted bodies too, for a caller asking a GRAMMAR
    question (`bgcleanup._scan`): a body is standard input, never syntax of the enclosing shell,
    so a `&` or an apostrophe in it is data. Every heredoc is still reported either way.

    Several redirects on one line (`cmd <<A <<B`) are consumed in order, as bash reads them.

    A `<<TAG` inside a quoted string is not a redirect (`_quoted_spans`): taking it for one would
    delete every following line. Quote state carries from line to line but not through a body,
    where an apostrophe opens nothing. When the quotes do not balance over the parsed lines, the
    scan is redone quote-blind, because a wrong "inside a string" verdict hides a real heredoc;
    bash will not run an unbalanced command, so every command it runs gets the quote-aware answer.

    Lines are split on `\\n` alone, not `str.splitlines`, which also breaks on characters a shell
    does not, and an invented break would invent a command.
    """

    lines = text.split("\n")
    out, found, unbalanced = _scan_lines(
        lines, quote_aware=True, keep_unquoted_bodies=keep_unquoted_bodies
    )
    if unbalanced:
        out, found, _ = _scan_lines(
            lines, quote_aware=False, keep_unquoted_bodies=keep_unquoted_bodies
        )
    return "\n".join(out), found


def _scan_lines(
    lines: list[str], *, quote_aware: bool, keep_unquoted_bodies: bool
) -> tuple[list[str], list[Heredoc], str]:
    """One heredoc pass over ``lines``: the kept lines, the heredocs found, and the quote state
    left open at the end, which `scan_heredocs` reads as "this pass cannot be trusted"."""

    out: list[str] = []
    found: list[Heredoc] = []
    index = 0
    quote = ""
    while index < len(lines):
        line = lines[index]
        out.append(line)
        index += 1
        if quote_aware:
            inside, quote = _quoted_spans(line, quote)
        else:
            inside = [False] * len(line)
        for match in _HEREDOC.finditer(line):
            if inside[match.start()]:
                continue  # `<<TAG` inside a string is text the shell never reads as a redirect
            quoted = bool(match.group("quote") or match.group("backslash"))
            tag = match.group("quoted_tag") or match.group("tag")
            body: list[str] = []
            while index < len(lines) and lines[index].strip() != tag:
                body.append(lines[index])
                index += 1
            index += 1  # drop the closing tag line too; harmless if absent
            found.append(Heredoc(tag=tag, quoted=quoted, body="\n".join(body), header=line))
            if not quoted and keep_unquoted_bodies:
                out.extend(body)
    return out, found, quote


def _newlines_to_separators(text: str) -> str:
    """``text`` with every unquoted, unescaped newline rewritten to `;`.

    A newline inside quotes is part of the word, and a backslash-newline separates nothing; both
    are left as they are. Runs LAST, because the comment and heredoc passes are line-based.

    The separator is SPACE-PADDED: a bare `;` after a line ending in `;` would weld into `;;`,
    which is no separator. `operator_pieces` decomposes such a run too; the padding keeps this
    independent of that table being right.
    """

    out: list[str] = []
    quote = ""
    escaped = False
    for character in text:
        if escaped:
            escaped = False
        elif quote == "'":
            quote = "" if character == "'" else quote  # single quotes escape nothing
        elif quote:
            if character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
        elif character == "\\":
            escaped = True
        elif character in "'\"":
            quote = character
        elif character == "\n":
            out.append(" ; ")
            continue
        out.append(character)
    return "".join(out)


def _strip_line_continuations(text: str) -> str:
    """``text`` with every bash line continuation -- an unescaped `\\` immediately followed
    by a newline -- removed, outside single quotes.

    Bash joins `\\<newline>` into nothing outside quotes and inside double quotes, so
    `cat secrets/\\<newline>.env` reads `secrets/.env`; inside single quotes the pair stays two
    literal characters, and stripping it there would invent a path bash never reads.

    Its place in `prepare` is load-bearing:

    - AFTER `strip_comments`: a backslash at the end of a comment continues nothing, and joining
      first would hide the next line's command inside the comment.
    - AFTER `scan_heredocs`: a quoted body is already gone, and an apostrophe in a body is no
      quote. A continuation inside an unquoted body fed to a shell is not joined, because
      `Heredoc.body` is captured before this runs.
    - BEFORE `_newlines_to_separators`, so no continuation outside single quotes reaches it.

    The escaping model is `_newlines_to_separators`' own, so the two never disagree about which
    side of a quote a character is on. A trailing backslash with nothing after it is kept.
    """

    out: list[str] = []
    quote = ""
    escaped = False
    for character in text:
        if escaped:
            escaped = False
            if character == "\n":
                continue  # `\` + newline elided together: bash's line continuation
            out.append("\\")
            out.append(character)
        elif quote == "'":
            out.append(character)
            if character == "'":
                quote = ""
        elif quote:
            if character == "\\":
                escaped = True
            else:
                if character == quote:
                    quote = ""
                out.append(character)
        elif character == "\\":
            escaped = True
        else:
            if character in "'\"":
                quote = character
            out.append(character)
    if escaped:
        out.append("\\")  # a dangling backslash at the very end: nothing follows to elide
    return "".join(out)


def prepare(command: str, *, keep_unquoted_bodies: bool = True) -> tuple[str, list[Heredoc]]:
    """``command`` reduced to the text a scanner should read, plus its heredocs.

    The single entry point for the four passes the module docstring lists, in their order, so no
    caller can apply one and forget another. ``keep_unquoted_bodies`` is `scan_heredocs`'.
    """

    text, heredocs = scan_heredocs(
        strip_comments(command), keep_unquoted_bodies=keep_unquoted_bodies
    )
    text = _strip_line_continuations(text)
    return _newlines_to_separators(text), heredocs


def tokenize(command: str, *, keep_unquoted_bodies: bool = True) -> list[str] | None:
    """Shell tokens with redirects/separators preserved; ``None`` when unparseable.

    ``keep_unquoted_bodies=False`` tokenizes the command with every heredoc body gone, which
    is what a caller asking a grammar question wants; see `scan_heredocs`.
    """
    lexer = shlex.shlex(
        prepare(command, keep_unquoted_bodies=keep_unquoted_bodies)[0],
        posix=True,
        punctuation_chars=True,
    )
    lexer.whitespace_split = True
    lexer.commenters = ""  # `strip_comments` has handled them, correctly; see its docstring
    tokens: list[str] = []
    try:
        for token in lexer:
            tokens.append(token)
    except ValueError:
        return None
    return tokens


def operator_pieces(token: str) -> list[str]:
    """``token`` as the operators bash reads it as; anything else comes back untouched.

    A token is decomposed only when it is no known separator, carries a `;`, `&` or `|`, and is
    punctuation from end to end, so a word such as `notes#1.md` or `-I{}` is never taken apart.
    The run is matched greedily against `_COMPOUND_OPERATORS`: `);` becomes `)` + `;`, while
    `&>` stays whole.

    A quoted argument that is all punctuation and holds a separator character (`echo ';;'`) is
    decomposed too, because tokens carry no memory of their quoting.
    """

    if token in _SEPARATORS or not token:
        return [token]
    if not _SEPARATOR_CHARS & set(token):
        return [token]
    if not set(token) <= _PUNCTUATION_CHARS:
        return [token]
    pieces: list[str] = []
    index = 0
    while index < len(token):
        for operator in _COMPOUND_OPERATORS:
            if token.startswith(operator, index):
                pieces.append(operator)
                index += len(operator)
                break
        else:
            pieces.append(token[index])
            index += 1
    return pieces


def segments(tokens: list[str]) -> list[list[str]]:
    """Split a token stream into simple commands at shell separators.

    A fused run of punctuation is decomposed first (`operator_pieces`), and its non-separator
    pieces stay in place: `;>` puts the `>` at the FRONT of the segment it opens, so a caller that
    looks for a redirect before a path finds the write target of `echo hi;>scripts/guard.py`.
    """

    return [command for pipeline in pipelines(tokens) for command in pipeline]


def pipelines(tokens: list[str]) -> list[list[list[str]]]:
    """Each pipeline of a token stream as its simple commands: the commands a `|` joins. `;`,
    `&&`, `||` and `&` end one, and a fused run of punctuation is decomposed first
    (`operator_pieces`); `segments` is these pipelines' commands, flattened. A `;` straight after
    a `|` does not end the pipeline: `prepare` rewrites a line break to `;`, and a line break
    after `|` continues the pipeline in bash and zsh (a literal `|;` is a syntax error, so no
    valid command differs).

    THE BOUND IS DOCUMENTED: `|&` reaches this as the pieces `|` and `&`, and the `&` ends the
    pipeline, so the two commands it joins are read as two pipelines.
    """

    result: list[list[list[str]]] = []
    pipeline: list[list[str]] = []
    current: list[str] = []
    after_pipe = False
    for token in tokens:
        for piece in operator_pieces(token):
            if piece not in _SEPARATORS:
                current.append(piece)
                after_pipe = False
                continue
            if piece == ";" and after_pipe:
                continue
            after_pipe = piece == "|"
            if current:
                pipeline.append(current)
                current = []
            if piece != "|" and pipeline:
                result.append(pipeline)
                pipeline = []
    if current:
        pipeline.append(current)
    if pipeline:
        result.append(pipeline)
    return result


def _launched(segment: Sequence[str], index: int) -> int | None:
    """Where the command that the `uv` at `index` launches starts: the first word after `run`
    the runner table reads as a test run; `None` where no `run` follows or no such word does."""
    start = past_run(segment, index + 1)
    if start is None:
        return None
    for at in range(start, len(segment)):
        if names_a_test_run(segment, at):
            return at
    return None


def command_words(segment: list[str], *, test_runs: bool = False) -> list[str]:
    """This segment's own command and arguments, with any leading environment-assignment
    tokens and the wrapper prefixes -- `_SINGLE_WRAPPERS`, and, given `test_runs`, `uv run`
    with every word up to the first the runner table reads as a test run -- stripped off the
    front, repeatedly, so `env FOO=1 pytest` and `FOO=1 uv run --locked pytest` both resolve to
    `pytest` as the real command, not to the assignment or the launcher.

    THE BOUND IS DOCUMENTED, not accidental: a `uv` command in which the table reads no test
    run, or one with no `run`, is left whole and its program is `uv`, and no other launcher
    is read through. Behind `uv run` every word before the first the table reads as a test run
    is the launcher's, so a runner named as a uv option's value or as another
    program's argument (`uv run --with pytest echo`, `uv run grep -m pytest x`) is read as the
    command, and a warn-only caller delivers its note to a run of no test.
    """

    index = 0
    while index < len(segment):
        token = segment[index]
        if _ASSIGNMENT.match(token):
            index += 1
            continue
        name = Path(token).name
        if test_runs and is_launcher(name):
            launched = _launched(segment, index)
            if launched is None:
                break
            index = launched
            continue
        if name in _SINGLE_WRAPPERS:
            index += 1
            continue
        break
    return segment[index:]
