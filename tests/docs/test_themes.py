"""A `trail.toml` theme's `pattern`: a subset of regular-expression syntax, matched the way
`re.search` matches it, and never by backtracking.

The subset is pinned against `re` itself rather than against a description of it: every pattern
up to four tokens over an alphabet holding each construct the language keeps, against every name
up to four characters, gives the same answer both ways. The names carry no newline, which is the
one place `re`'s `.` and `$` differ from "any character" and "the end"; the listing refuses such
a name before it reaches a theme.
"""

from __future__ import annotations

import itertools
import re
import subprocess
import sys
from pathlib import Path

import pytest

from drybag.docs.themes import PATTERN_MAX_CHARS, RULE, TOO_LONG, compile_theme

TOKENS = ("a", "b", ".", ".*", "|", "^", "$", "\\.")
NAMES = ["".join(chars) for n in range(5) for chars in itertools.product("ab.", repeat=n)]


def _patterns() -> list[str]:
    found = []
    for n in range(1, 5):
        for tokens in itertools.product(TOKENS, repeat=n):
            pattern = "".join(tokens)
            try:
                compile_theme(pattern)
            except ValueError:
                continue
            found.append(pattern)
    return found


def test_every_pattern_in_the_language_matches_as_re_search_does() -> None:
    # Mutation (declared): the leftmost fit of a middle piece taken from the start of the name
    # instead of after the piece before it -> `a.*b` finds `b` before `a` and this reddens.
    patterns = _patterns()
    # The walk first: a language that refused everything would agree with `re` vacuously.
    assert len(patterns) > 1000, len(patterns)
    for pattern in patterns:
        compiled, expected = compile_theme(pattern), re.compile(pattern)
        for name in NAMES:
            assert compiled.search(name) == bool(expected.search(name)), (pattern, name)


@pytest.mark.parametrize(
    ("pattern", "name", "here"),
    [("a$", "a\n", False), ("a.b", "a\nb", True), ("a.*b", "a\nb", True)],
)
def test_a_name_with_a_newline_is_compared_without_re_s_newline_rules(
    pattern: str, name: str, here: bool
) -> None:
    # The module claims `re.search`'s meaning on a name of one line, and says what differs on
    # a name holding a newline: `re`'s `$` also matches before a final newline, and its `.`
    # never matches one; here `$` is the very end and `.` any character. No such name reaches
    # a theme (the listing refuses it first, `test_trail`'s marker case), so these pin the
    # stated difference rather than a behaviour anybody meets: a change to either rule has to
    # change the sentence with it.
    assert compile_theme(pattern).search(name) is here
    assert bool(re.search(pattern, name)) is not here


def test_the_patterns_shipped_and_documented_keep_their_meaning() -> None:
    # The template's `.*`, and the two shapes the documentation and the tests have always used.
    assert compile_theme(".*").search("2026-01-01-anything.md")
    assert compile_theme("widget").search("2026-01-01-widget-design.md")
    assert compile_theme("gadget|gizmo").search("2026-01-02-gizmo.md")
    assert not compile_theme("gadget|gizmo").search("2026-01-01-widget-design.md")


@pytest.mark.parametrize(
    "pattern",
    ["(a+)+$", "a+", "a?", "a*", "[ab]", "a{2}", "(a|b)", "a$b", "a^", "\\d", "\\1", "trailing\\"],
)
def test_syntax_outside_the_language_is_refused_by_the_rule_alone(pattern: str) -> None:
    # Refused rather than guessed at: each of these means something else to `re`, and a meaning
    # changed silently would move documents between themes. The message is the rule and never
    # the pattern, which is the repository's own text. Mutation (declared): `(`, `+` and the
    # other refused characters read as literals -> the first cases no longer raise.
    with pytest.raises(ValueError) as refused:
        compile_theme(pattern)
    assert str(refused.value) == RULE


# `re` backtracks on this pair for longer than any test waits: eight `.*` to place over 300
# characters that hold no `b`. The language's matcher places each piece once.
ADVERSARIAL = (
    "import pathlib, sys\n"
    "from drybag.docs.trail import read_trail, theme_of\n"
    "path = pathlib.Path(sys.argv[1]) / 'trail.toml'\n"
    "path.write_text('[[theme]]\\nlabel = \"x\"\\npattern = \"' + '.*a' * 8 + '.*b\"\\n')\n"
    "print(theme_of('a' * 300 + '.md', read_trail(path, 'docs/trail.toml')))\n"
)


def test_a_pattern_re_would_backtrack_on_for_hours_answers_at_once(tmp_path: Path) -> None:
    # A generous bound in a subprocess, not a clock in this one: the matcher answers in
    # milliseconds, and `re.search` on the same pair runs for longer than the bound by orders of
    # magnitude, so no load on a shared runner separates the two outcomes. Through `read_trail`
    # and `theme_of`, as the gate reaches it. Mutation (declared): `read_trail` compiling the
    # pattern with `re` again -> the subprocess is killed at the bound.
    done = subprocess.run(
        [sys.executable, "-c", ADVERSARIAL, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert (done.returncode, done.stdout.strip()) == (0, "Unfiled"), done.stderr


def test_a_pattern_is_compiled_up_to_its_bound_and_refused_past_it() -> None:
    # The length bound is the language's own, so a caller other than `trail.toml`'s reader meets
    # it too; the refusal is a fixed sentence, never the pattern.
    assert compile_theme("a" * PATTERN_MAX_CHARS).search("a" * PATTERN_MAX_CHARS)
    with pytest.raises(ValueError) as refused:
        compile_theme("a" * (PATTERN_MAX_CHARS + 1))
    assert str(refused.value) == TOO_LONG
