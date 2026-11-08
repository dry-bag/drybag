"""The two bounds on a repository-chosen name: `printable` withholds it, `quoted` escapes it."""

from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from drybag.printed import CLIPPED_CHARS, UNPRINTABLE, clipped, printable, quoted
from tests.crafted import CRAFTED

# Names the path grammar admits: each prints as itself under both bounds, so ordinary output is
# unchanged by either.
INSIDE = ["docs/a.md", "BR-001.md", ".hidden", "..foo", "a_b/c-d.e"]
# Names outside it, one per way out. `a/`, `a/b/..` and `a/.` are the shapes Python 3.11.0 to
# 3.11.4 read into the grammar when its segments were a possessive repeat. `x\udce9` is how Linux
# hands Python a file name whose bytes are not UTF-8 (a lone surrogate), so it is covered here
# portably, where the filesystem cases that need such a name skip on APFS. `café.md`, `My Note.md`
# and `заметки.md` are ordinary names the grammar still refuses: it is ASCII-only on purpose, and
# those print as the stand-in.
OUTSIDE = [
    "",
    ".",
    "..",
    "a/../b",
    "a//b",
    "a/",
    "a/b/..",
    "a/.",
    "-rf",
    "a\rb",
    "a\u009bb",
    "a\u2028b",
    "a\u202eb",
    "a b",
    "x\udce9",
    "café.md",
    "My Note.md",
    "заметки.md",
    CRAFTED,
]


@pytest.mark.parametrize("name", INSIDE)
def test_a_name_inside_the_grammar_prints_as_itself_under_both_bounds(name: str) -> None:
    assert printable(name) == name
    assert quoted(name) == name


@pytest.mark.parametrize("name", OUTSIDE)
def test_a_name_outside_the_grammar_is_withheld_by_printable(name: str) -> None:
    # Mutation: return the name unchecked from `printable` — every case reddens.
    assert printable(name) == UNPRINTABLE
    assert printable(name, "<elsewhere>") == "<elsewhere>"


@pytest.mark.parametrize("name", OUTSIDE)
def test_a_name_outside_the_grammar_arrives_whole_and_inert_through_quoted(name: str) -> None:
    # The docstring's two claims, stated as properties: the name arrives whole (the literal reads
    # back to it) and cannot start a line or drive a terminal (every character is printable).
    # Mutation: return the name unchecked from `quoted`, or return `UNPRINTABLE` — each reddens.
    shown = quoted(name)
    assert ast.literal_eval(shown) == name
    assert shown.isprintable()


def test_a_name_up_to_the_clip_prints_as_its_bound_prints_it() -> None:
    # At `CLIPPED_CHARS` nothing is cut, so an ordinary name, however long a real one gets,
    # prints exactly as `quoted` prints it.
    name = "a" * CLIPPED_CHARS
    assert clipped(name) == name
    assert clipped(CRAFTED) == quoted(CRAFTED)


@pytest.mark.parametrize("name", ["a" * (CLIPPED_CHARS + 1), "a" * 200_000, CRAFTED * 5_000])
def test_a_name_past_the_clip_prints_its_first_characters_and_its_length(name: str) -> None:
    # `quoted` escapes a name and does not bound its length, and a repository-authored key or
    # label is bounded in length by nothing: one `[states]` key of 200 000 characters printed a
    # stderr line of 200 185 bytes. Past `CLIPPED_CHARS` the name prints as its first
    # characters, through the same bound, and its length — still identifiable, and a line of
    # bounded size. Mutation: never clip in `clipped` — every case reddens.
    shown = clipped(name)
    assert shown == f"{quoted(name[:CLIPPED_CHARS])}…({len(name)} chars)"
    assert len(shown) < 4 * CLIPPED_CHARS + 32
    assert shown.isprintable()


# A name of a million segments, which the grammar read with 124 MiB more of match state when `re`
# kept a record for each segment it might give back, and with none when it keeps none: a
# `drybag.toml` value is bounded in length by nothing. The most the child may grow its peak
# resident size by, a few copies of the two-mebibyte name.
_LONG_NAME_SEGMENTS = 1 << 20
_LONG_NAME_BYTES = 32 << 20
_LONG_NAME_SECONDS = 30


def test_a_long_name_is_judged_in_memory_linear_in_its_length() -> None:
    # In a child that measures its own peak resident size before and after (`ru_maxrss`, bytes on
    # macOS and KiB on Linux), under a timeout. The name is inside the grammar, so `quoted` gives
    # it back whole only if the grammar read it to its end. Mutation (oracle): `mutations/`'s "a
    # path's segments are given back" -> this reddens.
    probe = (
        "import resource, sys\n"
        "from drybag.printed import quoted\n"
        "name = 'a/' * int(sys.argv[1]) + 'a'\n"
        "scale = 1 if sys.platform == 'darwin' else 1024\n"
        "before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "shown = quoted(name)\n"
        "grown = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) * scale\n"
        "print(shown is name, grown)\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, str(_LONG_NAME_SEGMENTS)],
            capture_output=True,
            text=True,
            timeout=_LONG_NAME_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"judging one long name ran past {_LONG_NAME_SECONDS} s")
    answer, grown = done.stdout.split()
    assert answer == "True", done.stderr
    assert int(grown) < _LONG_NAME_BYTES, f"the grammar grew the peak by {int(grown) >> 20} MiB"
