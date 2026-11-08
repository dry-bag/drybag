"""Code, tests and documents cite what a reader here can open, and nothing else.

The design these modules were built against lives in a private repository. A `§9.1` or a
`(D7)` in a docstring therefore points a reader at a page they cannot open: it looks like a
reference and carries none of the content. Seventy-four files under `src/` did it before this
gate, eighty-two under `tests/`, and the mutation register, the scripts, the workflows,
`docs/cli.md`, the preset and the hook wrapper besides. The rule is to say what the section
says, in a few words, or to cite an anchor that exists in this repository — `docs/cli.md#…`,
`CONTRIBUTING.md`, or a principle of `docs/methodology/principles.md` by its number.

**Every tracked file is walked, and the exemptions are named.** `docs/plans/` is a historical
record of work argued from the design, and it keeps the ids it argued with; `CONTRIBUTING.md`
says its references cannot be followed from here. This file plants citations on purpose. A
list of trees to walk would be a list of trees to forget, and the class did arrive in one that
an earlier list left out.

**A file is read whole, not line by line.** Words are matched across any run of whitespace, so
a phrase a re-wrap split over two lines — "the Global" at the end of one, "Constraints" at the
start of the next — is the same phrase to the gate as to a reader.

The arms are deliberately wider than "a parenthesised id". The ids were written bare as often
as in brackets — `D7: a cap, not a config key`, `DP3 makes it trusted by construction`, `C5's
exit 2` — and an arm that saw only one spelling would have let most of the class back in. What
the width costs is a rewrite: an ordinary numbered use — `P95`, `the P1 bug`, `item 1 of the
tuple` in code — is refused too, and says it another way.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from tests.test_neutral import ROOT, tracked_files

# What is never walked. Everything else git tracks is. The listing icon is the repository's one
# binary (`tests/test_neutral.py`'s `UNDECODABLE`): an image cites nothing, and is named here
# rather than skipped as undecodable, so no other file can leave the walk that way.
EXEMPT = (".claude-plugin/icon.png", "docs/plans", "tests/test_public_anchors.py")

# Where the plans' bookkeeping arms do not apply: a document may talk about a task or a round in
# its own sense, and a fixture is a document a test reads, whatever tree it sits in.
DOCUMENT_SUFFIX = ".md"
FIXTURES = "tests/fixtures"

# Each arm is named so a hit says what it is. Every arm is matched against the whole text, so
# a space in a phrase is written `\s+`.
CITATIONS = (
    ("design section", re.compile(r"§\s*\d+(?:\.\d+)*")),
    # The two-letter prefixes are unambiguous; the one-letter ones are held to the numbers the
    # design and its plans used. `C0` and `C1` stay legal before "control", because those are
    # the Unicode names of the control classes `tomlout` and the probes escape.
    (
        "decision id",
        re.compile(r"\b(?:DC|DP|OD|RD)\d+\b|\b[DP]\d{1,2}\b|\bC[1-9]\b(?!\s+control)"),
    ),
    # Whatever prefix a later plan invents, it arrives in brackets at the end of a sentence.
    ("bracketed id", re.compile(r"\([A-Z]{1,2}\d{1,2}(?:,\s*[A-Z]{1,2}\d{1,2})*\)")),
    # The design's measurement log, cited as `Findings → S6`.
    ("design finding", re.compile(r"Findings\s*→")),
    # A plan's own headings, which a module quoted as if the reader had the plan open: "Premise 2
    # of the lane's plan", "by the Global Constraints' own list", in either case, and the list of
    # inputs a plan asks its tasks to exercise, which eight test comments cited by its number.
    (
        "plan section",
        re.compile(r"\bPremise\s+\d+|(?i:\bglobal\s+constraint)|(?i:\breview\s+focus)"),
    ),
    # The plans' word for a unit of work. A module, a test and a document all name the area, the
    # module or the command they mean instead: "the foundation lane" told a reader nothing that
    # `stayfixed.hooks.dispatch` does not tell them better. A letter and not a word character is the
    # boundary, because `\b` counts `_` as a word character and a snake_case test name walked past
    # it. The pattern spells the word `l[a]nes` so that the two entries that quote this line,
    # `mutations/`'s "the public-anchor gate stops seeing the plans' unit of work" and "the
    # public-anchor gate lets a snake_case name carry the plans' unit of work", are not refused for
    # quoting it; the bookkeeping arm below spells its word the same way.
    ("plan unit", re.compile(r"(?i:(?<![^\W\d_])l[a]nes?(?![^\W\d_]))")),
    # A plan's name for a package of work, which names no module, command or file here: two module
    # docstrings and one function docstring used `hooks-core` as if it named a part of the tree,
    # the first two as the owner of the entries `hooks/hooks.json` holds. Only that name is
    # refused, hyphenated, because the plans' other package names are commands and ordinary words
    # (`setup`, `attach`, `upgrade`, onboarding) that a refusal would take from correct sentences.
    # It is spelled `hooks-c[o]re` so the entry in `mutations/` that quotes this line is not
    # refused for quoting it.
    ("plan package", re.compile(r"(?i:\bhooks-c[o]re\b)")),
)

# The plans' own bookkeeping, which means nothing once the code has shipped: the wave a line
# landed in, the task that wrote it, the review round that changed it and the finding or item by
# its number in that round, and a spike's or a review's `S<n>`. Code says what it does and why;
# when it did it is git's. The public source list's `[S27]` is bracketed and stays legal.
CODE_ONLY = (
    (
        "plan vocabulary",
        re.compile(
            r"(?i:(?<![^\W\d_])w[a]ve(?![^\W\d_]))|\bTask\s+\d+|(?i:\bfix\s+round)|(?i:\bround\s+\d+)"
            r"|(?i:\bitem\s+\d+)|(?i:\bfinding\s+\d+)"
        ),
    ),
    ("spike id", re.compile(r"(?<!\[)\bS\d{1,2}\b(?!\])")),
)

# A line's comment leader: Python, TOML, YAML and shell all spell it `#`.
COMMENT_LEADER = re.compile(r"(?m)^([ \t]*)(#+)")

# What a contributor who trips the gate reads first.
REMEDY = (
    "Shipped text cites the private design or the plans' bookkeeping. State the rule in a few "
    "words, or cite docs/cli.md#…, CONTRIBUTING.md or a principle of "
    "docs/methodology/principles.md by its number."
)


def is_document(relative: str) -> bool:
    return relative.endswith(DOCUMENT_SUFFIX) or relative.startswith(FIXTURES + "/")


def arms_for(relative: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """The arms the file at `relative` is held to: the code-only ones too unless a document."""
    return CITATIONS if is_document(relative) else CITATIONS + CODE_ONLY


def citations(
    text: str, arms: Iterable[tuple[str, re.Pattern[str]]] = CITATIONS
) -> list[tuple[int, str, str]]:
    """Every citation in the text, as `(line number, arm name, matched text)`, one per span.

    Two arms that take the same span — `(D7)` is a bracketed id and a decision id — report it
    once, under the arm that starts first and then under the arm listed first.
    """
    # A comment's leading `#` becomes spaces of the same width, so a phrase wrapped across two
    # comment lines is one phrase and every offset, and so every line number, stays where it was.
    text = COMMENT_LEADER.sub(lambda m: m.group(1) + " " * len(m.group(2)), text)
    matches = sorted(
        (match.start(), order, match.end(), name, match.group())
        for order, (name, pattern) in enumerate(arms)
        for match in pattern.finditer(text)
    )
    found: list[tuple[int, str, str]] = []
    covered = -1
    for start, _, end, name, matched in matches:
        if start < covered:
            continue
        covered = end
        found.append((text.count("\n", 0, start) + 1, name, " ".join(matched.split())))
    return found


def is_exempt(relative: str) -> bool:
    return any(relative == exempt or relative.startswith(exempt + "/") for exempt in EXEMPT)


def gated_files() -> list[Path]:
    """Every tracked file but the exemptions."""
    return [path for path in tracked_files() if not is_exempt(path.relative_to(ROOT).as_posix())]


def scan(root: Path, paths: Iterable[Path]) -> list[str]:
    """Every citation in the files, as `path:line: arm 'text'`, the path relative to `root`."""
    hits: list[str] = []
    # No `UnicodeDecodeError` handler: the repository's one binary is exempt by name (`EXEMPT`),
    # and a walk that skipped what it could not read would go green by reading nothing.
    for path in paths:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        hits.extend(
            f"{relative}:{n}: {arm} {found!r}"
            for n, arm, found in citations(text, arms_for(relative))
        )
    return hits


def test_the_citation_gate_discriminates() -> None:
    # Break any arm — widen it into silence, or drop a spelling — and one of these goes the
    # wrong way. The negatives are the neighbours the arms must not take: the public source
    # list's `[S27]`, a principle by number, a Unicode control class, a version, a digest name.
    for planted in (
        "the store's own §9.1 checks",
        "§ 5.3",
        "(D7)",
        "D7: a cap, not a config key",
        "DC3 says the registry stamps it",
        "DP3 makes the overlay trusted",
        "OD5 as a table",
        "RD2 keeps the record",
        "the argument P10 makes",
        "C5's exit 2",
        "(R5, D15)",
        "(R5, E3)",
        "(E3)",
        "Findings → S6 did not reproduce",
        "the dispatcher banks it (Premise 2)",
        "repository-authored by the Global Constraints' own list",
        "the global constraints make `gh` a seam",
        "The Global\nConstraints list it",
        "under Premise\n12",
        "Review Focus 4, the upgrade half",
        "the review\nfocus of the plan",
        "the foundation lane",
        "Lanes that scaffold",
        "def test_what_every_downstream_lane_reaches_for",
        "`hooks-core` owns the entries that invoke them",
        "the Hooks-Core package",
    ):
        assert citations(planted), planted
    for clean in (
        "sourced [S3] [S7], and that is the",
        "principle 5 says a repository is untrusted input",
        "see docs/cli.md#stayfixed-init",
        "Every other C0 control and DEL",
        "the C1 control range",
        "Python 3.11, 3.12 and 3.13",
        "a sha256 digest, MD5 never",
        "exit code 2 (a refusal)",
        "a global constant",
        "a review of the focus ring",
        "a plane of glass",
        "planes and lanemarks",
        "the core's `hooks` area answers through it",
        "the `hooks` area's sink",
    ):
        assert citations(clean) == [], clean


def test_a_citation_reports_its_whole_text_once_on_its_own_line() -> None:
    # One span, one hit, and the number whole: `(D7)` used to report twice and `Task 12` as
    # `Task 1`, and a phrase split over two lines is reported on the line it starts on.
    assert citations("(D7)") == [(1, "bracketed id", "(D7)")]
    assert citations("(DC4, D15)") == [(1, "bracketed id", "(DC4, D15)")]
    assert citations("x\ny §9.12 z") == [(2, "design section", "§9.12")]
    arms = arms_for("src/stayfixed/x.py")
    assert citations("a\nTask 12, and Finding 14", arms) == [
        (2, "plan vocabulary", "Task 12"),
        (2, "plan vocabulary", "Finding 14"),
    ]
    assert citations("one\nthe Global\n  Constraints list") == [
        (2, "plan section", "Global Constraint")
    ]


def test_the_plan_vocabulary_gate_discriminates() -> None:
    # The code-only arms: each planted line is refused in code and passes in a document, which is
    # the whole difference `arms_for` makes. One spelling per line, so no spelling covers for
    # another. The negatives are the words these modules use in their own sense — a background
    # task, a round trip, what a check finds, a public source by its bracketed id.
    code = arms_for("src/stayfixed/x.py")
    for planted in (
        "the wave-3 memory engine",
        "landed in wave 4",
        "this\nwave exists to remove it",
        "Wave A2's writing commands",
        "tests/test_neutral_wave2.py",
        "Task 12 wrote this guard",
        "Fix round 2 moved the check",
        "the second fix round",
        "Review round 1.",
        "the reviewer's item 5",
        "finding 14 said",
        "S8 row 2 measured it",
        "was S3 of the install-path review",
    ):
        assert citations(planted, code), planted
        assert citations(planted) == [], planted
    for clean in (
        "a task the hook runs in the background",
        "one round trip to git",
        "fix the round-trip",
        "one finding per line",
        "a microwave 3 times",
        "the waveform",
        "sourced [S12], at the source's own date",
        "SHA256 and S3TC",
    ):
        assert citations(clean, code) == [], clean


def test_the_arms_follow_where_a_file_lives() -> None:
    # Code is held to the bookkeeping arms and a document is not: a `.md` file anywhere, and a
    # fixture whatever its suffix, because a fixture is a document a test reads.
    for code in (
        "src/stayfixed/runner.py",
        "tests/test_cli.py",
        "scripts/x.py",
        "mutations/x.toml",
        ".github/workflows/ci.yml",
        "hooks/run-hook.sh",
    ):
        assert citations("the wave-4 engine", arms_for(code)), code
    for document in (
        "docs/cli.md",
        "README.md",
        "RELEASING.md",
        "skills/README.md",
        "tests/fixtures/smoke-project/docs/plans/README.md",
        "tests/fixtures/hostile-project/stayfixed.toml",
    ):
        assert citations("the wave-4 engine", arms_for(document)) == [], document


def test_the_scan_reports_what_it_read_by_path_and_line(tmp_path: Path) -> None:
    # The loop the gate below runs, on planted files. Reading nothing, or reading and keeping
    # nothing, leaves the gate green over any tree; this is where either shows.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n# the Global\n# Constraints\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("# the wave-4 engine\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("the wave-4 engine, and §3\n", encoding="utf-8")
    paths = sorted(tmp_path.rglob("*.*"))
    assert scan(tmp_path, paths) == [
        "c.md:1: design section '§3'",
        "src/a.py:2: plan section 'Global Constraint'",
        "src/b.py:1: plan vocabulary 'wave'",
    ]


def test_the_citation_walk_reads_every_tracked_file_but_the_exemptions() -> None:
    # The non-vacuity guard for the walk below: one named file from every tree, and each
    # exemption shown to be real — a plan is tracked and not walked, and so is this file.
    names = {path.relative_to(ROOT).as_posix() for path in gated_files()}
    for wanted in (
        "README.md",
        "CONTRIBUTING.md",
        "RELEASING.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "pyproject.toml",
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
        ".github/workflows/ci.yml",
        "src/stayfixed/cli.py",
        "src/stayfixed/presets/recommended.toml",
        "docs/cli.md",
        "docs/methodology/principles.md",
        "skills/README.md",
        "hooks/run-hook.sh",
        "tests/test_cli.py",
        "tests/fixtures/hostile-project/stayfixed.toml",
        "scripts/mutation_oracle.py",
    ):
        assert wanted in names, wanted
    # The mutation declarations by their directory, not by a group file's name: `GROUP_OF` names
    # the groups.
    assert any(name.startswith("mutations/") for name in names), "no declaration file is walked"
    plans = [p for p in tracked_files() if p.relative_to(ROOT).as_posix().startswith("docs/plans/")]
    assert plans
    assert not names.intersection(p.relative_to(ROOT).as_posix() for p in plans)
    assert "tests/test_public_anchors.py" not in names


def test_no_tracked_file_cites_the_private_design() -> None:
    # One test over the whole walk rather than one per file, so a regression reads as a list of
    # `path:line` a contributor can work through instead of a wall of parametrised cases.
    hits = scan(ROOT, gated_files())
    assert hits == [], "\n".join([REMEDY, *hits])
