from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from stayfixed.prose import (
    blank_fences,
    path_references,
    resolves_within,
)


def test_a_backticked_path_with_a_slash_is_a_reference_and_a_bare_filename_is_prose() -> None:
    assert list(path_references("see `src/widget/boot.py` and `config.py`")) == [
        "src/widget/boot.py"
    ]


def test_a_location_suffix_is_not_part_of_the_name() -> None:
    # A line, a line and a column, and a symbol path of any depth: `::` joins a symbol path in
    # Rust and C++ as it does a test node's, so `::TestA::test_x` and `::parser::parse` are one
    # suffix. Before, a column or a second `::` made the span no reference at all. Oracle:
    # `mutations/`'s "a column stops being part of a location suffix", "a symbol path stops
    # being read past its first `::`".
    line = (
        "`src/a.py:12` `tests/test_a.py::test_x` `src/b.c:3:14` "
        "`tests/test_a.py::TestA::test_x` `src/lib.rs::parser::parse`"
    )
    assert list(path_references(line)) == [
        "src/a.py",
        "tests/test_a.py",
        "src/b.c",
        "tests/test_a.py",
        "src/lib.rs",
    ]


# Backticked spans whose symbol path has an empty part or a colon outside a `::`: none claims a
# path, and the next backtick may open one. Python 3.11.0 to 3.11.4 read the first as a claim when
# the parts were a possessive repeat, which they end where a failed part stopped.
BROKEN_SYMBOLS = {
    "an empty last part": ("`src/a.py::x::` here", []),
    "three colons": ("`src/a.py::x:::y` here", []),
    "a colon alone": ("`src/a.py::x:y` here", []),
    "an empty first part": ("`src/a.py:::x` here", []),
    "a claim at its closing backtick": ("`src/a.py::x::`src/b.py` here", ["src/b.py"]),
}


@pytest.mark.parametrize("case", sorted(BROKEN_SYMBOLS))
def test_a_symbol_path_with_an_empty_part_or_a_lone_colon_claims_no_path(case: str) -> None:
    # Mutations (oracle): `mutations/`'s "a symbol path with an empty last part is read" -> `an
    # empty last part`; "a symbol path with three colons is read" -> `three colons`; "a symbol path
    # with a lone colon is read" -> `a colon alone`; "a broken symbol path's closing backtick
    # opens no claim" -> `a claim at its closing backtick`.
    line, claims = BROKEN_SYMBOLS[case]
    assert list(path_references(line)) == claims


# A symbol path of a million parts, read with 154 MiB more of match state when `re` kept a record
# for each part it might give back, and with none when it keeps none. The most the child may grow
# its peak resident size by: a few copies of the three-mebibyte line, a fifth of that record.
_LONG_SYMBOL_PARTS = 1 << 20
_LONG_SYMBOL_BYTES = 32 << 20


def test_a_long_symbol_path_is_read_in_memory_linear_in_its_length() -> None:
    # In a child that measures its own peak resident size before and after the read (`ru_maxrss`,
    # bytes on macOS and KiB on Linux), under a timeout. The claim after the long one says the
    # line was read past it. Mutation (oracle): `mutations/`'s "a symbol path's parts are given
    # back" -> this reddens.
    probe = (
        "import resource, sys\n"
        "from stayfixed.prose import path_references\n"
        "line = '`src/a.py' + '::x' * int(sys.argv[1]) + '` `docs/b.md`'\n"
        "scale = 1 if sys.platform == 'darwin' else 1024\n"
        "before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "found = list(path_references(line))\n"
        "grown = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) * scale\n"
        "print(found == ['src/a.py', 'docs/b.md'], grown)\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, str(_LONG_SYMBOL_PARTS)],
            capture_output=True,
            text=True,
            timeout=_LONG_TEXT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"reading one long symbol path ran past {_LONG_TEXT_SECONDS} s")
    answer, grown = done.stdout.split()
    assert answer == "True", done.stderr
    assert int(grown) < _LONG_SYMBOL_BYTES, f"the reader grew its peak by {int(grown) >> 20} MiB"


def test_a_file_any_stack_stores_is_a_path_claim() -> None:
    # The drift that built this module was one reader accepting `.ts`/`.tsx` and the other not;
    # a closed list of extensions is the same drift between this grammar and every stack it does
    # not list. Before, a plan citing `src/lib.rs` or `cmd/main.go:12` was never checked. An
    # extension is any word that starts with a letter, a dotfile's included. Oracle:
    # `mutations/`'s "the reference grammar closes its extension list again".
    line = (
        "`web/app.tsx` `cfg/a.toml` `src/lib.rs` `cmd/main.go:12` `app/Foo.java` "
        "`include/a.hpp` `types/a.d.ts` `secrets/.env`"
    )
    assert list(path_references(line)) == [
        "web/app.tsx",
        "cfg/a.toml",
        "src/lib.rs",
        "cmd/main.go",
        "app/Foo.java",
        "include/a.hpp",
        "types/a.d.ts",
        "secrets/.env",
    ]


def test_a_span_whose_first_component_is_a_host_is_prose() -> None:
    # Go names a dependency `gopkg.in/yaml.v3`, and a repository or a page is often written
    # with no scheme: a first path component ending in a host's label is not a directory of this
    # repository, so the span is prose. A leading dot is a hidden directory, and a `.d` suffix a
    # directory of fragments (this repository's own `changelog.d/`): both stay paths. Oracle:
    # `mutations/`'s "a host-shaped first component is read as a directory", "a `.d` directory
    # reads as a host", "a hidden directory reads as a host".
    hosts = "`gopkg.in/yaml.v3` `github.com/owner/repo.git` `docs.example.org/3/x.html`"
    assert list(path_references(hosts)) == []
    paths = "`.github/workflows/x.yml` `./src/a.py` `changelog.d/x.fix.md` `conf.d/a.conf`"
    assert list(path_references(paths)) == [
        ".github/workflows/x.yml",
        "./src/a.py",
        "changelog.d/x.fix.md",
        "conf.d/a.conf",
    ]


def test_a_version_number_is_not_an_extension() -> None:
    # `releases/0.1.9596` names a version, not a file: an extension starts with a letter, so a
    # numbered directory is prose. Oracle: `mutations/`'s "an extension may start with a digit".
    assert list(path_references("`releases/0.1.9596` `docs/p0/0.0.1` `man/stayfixed.1`")) == []


def test_a_shell_command_or_a_url_is_never_a_reference() -> None:
    assert list(path_references("`python3 scripts/x.py --root .` `https://example.com/a.py`")) == []


def test_fences_are_blanked_not_deleted_so_line_numbers_hold() -> None:
    text = "a\n```\n`x/y.py`\n```\nb\n~~~\n`p/q.py`\n~~~\nc\n"
    blanked = blank_fences(text)
    assert blanked.count("\n") == text.count("\n")
    assert "x/y.py" not in blanked and "p/q.py" not in blanked
    assert blanked.splitlines()[-1] == "c"


# How a fence is read, each line a case the old pattern decided and the line reader must decide
# alike: an opening run with no closer of its length falls back one mark at a time, down to
# three; a closer is the same run alone, blanks around it allowed; a run of the other mark, or a
# longer one, closes nothing.
FENCE_READINGS = {
    "a run closed at its own length": ("````\na\n```\nb\n````\n", "\n\n\n\n\n"),
    "a run closed one mark shorter": ("````\na\n```\nb\n", "\n\n\nb\n"),
    "a closer between blanks": ("```py\na\n \t```\t \nb\n", "\n\n\nb\n"),
    "a longer run closes nothing": ("```\na\n````\nb\n", "```\na\n````\nb\n"),
    "the other mark closes nothing": ("~~~\na\n```\nb\n", "~~~\na\n```\nb\n"),
}


@pytest.mark.parametrize("case", sorted(FENCE_READINGS))
def test_a_fence_is_read_as_its_pattern_reads_one(case: str) -> None:
    # Mutations (oracle), one a case: `mutations/`'s "a fence's run is tried at its full length
    # only" -> `a run closed one mark shorter`; "a fence's closer may not stand between blanks" ->
    # `a closer between blanks`; "a run is tried from three marks up" -> `a run closed at its own
    # length`; "a longer run closes a shorter one" -> `a longer run closes nothing`; "a closer of
    # either mark closes" -> `the other mark closes nothing`.
    text, blanked = FENCE_READINGS[case]
    assert blank_fences(text) == blanked


# Texts the fence pattern took in time quadratic in their length, each ending in a block that
# closes, so the answer says the text was read to its end: opening lines no later line closes,
# which the pattern scanned the rest of the text from, 0.31 s at 4,000 of them; and one long run
# whose closer is one mark short, which it scanned the text from at every length down to three,
# 0.13 s at 1,000 marks. The third holds the line reader's own bound rather than the pattern's
# defect: closed pairs, where a reader that searched a run's closers from the first again at every
# opening line passed over N²/2 of them, 1.2 s at 16,000 lines. Each is sized so that the slow
# reading takes over five minutes and the line reader a fraction of a second, and spelled as runs,
# `(unit, count)`, that the child joins: a run passed whole on its command line would pass Linux's
# limit on one argument. Beside the runs, whether the reader blanks them all or gives them back.
LONG_TEXTS = {
    "openers no line closes": ((("```py\n", 1 << 18),), False),
    "a long run": ((("`", 1 << 19), ("\n", 1), ("`", (1 << 19) - 1), ("x", 1)), False),
    "closed pairs": ((("```\n", 1 << 18),), True),
}
# The child's bound: far below the slow reading's time over any of the texts on a laptop, and a
# hundred times the line reader's there, start-up included, so neither load nor a fast machine
# moves a case across it.
_LONG_TEXT_SECONDS = 30


@pytest.mark.parametrize("shape", sorted(LONG_TEXTS))
def test_fences_are_read_in_time_linear_in_the_text(shape: str) -> None:
    # In a child under a timeout, so a regression fails this case rather than holding a worker.
    # Mutations (oracle): `mutations/`'s "fences are found by a lazy match again" -> the first two
    # cases; "a fence's closers are searched from the first again" -> `closed pairs`.
    probe = (
        "import json, sys\n"
        "from stayfixed.prose import blank_fences\n"
        "runs, blanked = json.loads(sys.argv[1])\n"
        "head = ''.join(unit * count for unit, count in runs)\n"
        "kept = '\\n' * head.count('\\n') if blanked else head\n"
        "print(blank_fences(head + '\\n~~~\\nx\\n~~~\\n') == kept + '\\n\\n\\n\\n')\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, json.dumps(LONG_TEXTS[shape])],
            capture_output=True,
            text=True,
            timeout=_LONG_TEXT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"blanking the fences ran past {_LONG_TEXT_SECONDS} s on one text")
    assert done.stdout == "True\n", done.stderr


def test_a_claim_that_lands_outside_the_root_resolves_nowhere(tmp_path: Path) -> None:
    # The grammar is shared and the resolution was not: `Path(root) / "/etc/passwd.md"` discards
    # `root`, and a `..` walks out of it. Both are answered as None so no reader asks the
    # filesystem about them. Mutation: return `landed` unconditionally — this reddens on the
    # first three cases. Lexical, so a symlink never decides containment.
    root = tmp_path / "widget"
    (root / "docs").mkdir(parents=True)
    assert resolves_within(root, "/etc/passwd.md") is None
    assert resolves_within(root, "../../../../secrets/keys.py") is None
    assert resolves_within(root, "docs/../../out.md") is None
    assert resolves_within(root, "src/widget/boot.py") == root / "src" / "widget" / "boot.py"
    # `base` moves where a relative claim is read from; containment stays against the root, so a
    # link out of `docs/` into `src/` is inside the project and still resolves.
    assert resolves_within(root, "../src/a.py", base=root / "docs") == root / "src" / "a.py"
    assert resolves_within(root, "../../src/a.py", base=root / "docs") is None
