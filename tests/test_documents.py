"""The public documents are held to a contract, the way the skills are (tests/skills).

`README.md` and `docs/methodology/` are read by people who have not read the code, which is
why nothing in them may be wrong in a way a test could have caught: a relative link that
does not resolve, a command row the parser does not accept, a command with no row, a
citation with no source, a source nothing cites, a principle with no statement of how well
it is backed. None of these is a matter of taste, so none is left to review.

The three parser lines are the same three `tests/skills/test_skills.py` has, on purpose:
two modules asking the real parser the same question is two claims, and collapsing them would
make one of the two documents provable only through the other. This used to forbid a cross-module
import on the grounds that the test tree was not importable, which was false in both halves:
`tests/__init__.py` is tracked, nine modules import across it, and `CONTRIBUTING.md` carries no
such rule. `tests/snapshot.py` is where a helper two modules share
belongs.
"""

from __future__ import annotations

import argparse
import inspect
import io
import posixpath
import re
import shlex
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from stayfixed import __version__
from stayfixed.cli import build_parser, discover_registrars, split_json_flag
from tests.cli import subparsers
from tests.scriptload import plugin_tree, publish_plugin
from tests.test_neutral import tracked_files

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
METHODOLOGY = ROOT / "docs" / "methodology"
PRINCIPLES = METHODOLOGY / "principles.md"
SOURCES = METHODOLOGY / "sources.md"
# The freshness window `docs/methodology/README.md` states: a source published more than this
# many months before it was read must say `older` in its notes column. A working rule of the
# methodology, not a project budget, so it is a constant here and a sentence there.
FRESH_MONTHS = 2
# The three answers a principle may give to "how well is this backed", defined in
# docs/methodology/README.md. A fourth value is a wording change to that file first.
BACKING_LABELS = ("sourced", "measured", "thin")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
# `| S<n> | title | 2026-08 | 2026-09 | https://… | cited for | notes |` — seven cells. The
# published cell is a month or the word `living` for a maintained page that carries no date.
_SOURCE_ROW = re.compile(
    r"^\| (S\d+) \| ([^|]+) \| (\d{4}-\d{2}|living) \| (\d{4}-\d{2}) \| "
    r"(https?://\S+) \| ([^|]+) \| ([^|]*)\|$",
    re.MULTILINE,
)
_CITATION = re.compile(r"\[(S\d+)\]")
_SECTION = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
# The label, then a full stop, then whatever prose follows: `**Backing:** sourced. The mechanism…`.
# Capturing the bare word let `sourced for the budget` pass as `sourced` while the README says
# the label is chosen by the weakest link, so the stop is part of the grammar.
_BACKING = re.compile(r"^\*\*Backing:\*\* (\w+)\.", re.MULTILINE)


def prose(path: Path) -> str:
    return _FENCE.sub("", path.read_text(encoding="utf-8"))


def links_in(path: Path) -> list[str]:
    """Relative link targets in a document's prose; URLs, anchors and mail links are not
    the tree's to resolve."""
    return [
        target.split("#", 1)[0]
        for target in _LINK.findall(prose(path))
        if not target.startswith(("http://", "https://", "#", "mailto:"))
        and target.split("#", 1)[0]
    ]


def public_documents() -> list[Path]:
    return [README, ROOT / "docs" / "plans" / "README.md", *sorted(METHODOLOGY.glob("*.md"))]


def sources() -> dict[str, tuple[str, str, str, str, str, str]]:
    text = SOURCES.read_text(encoding="utf-8")
    return {row[0]: row[1:] for row in _SOURCE_ROW.findall(text)}


def principle_sections() -> list[tuple[str, str, str]]:
    """`(number, title, body)` per `## n. title` section of principles.md."""
    text = PRINCIPLES.read_text(encoding="utf-8")
    matches = list(_SECTION.finditer(text))
    return [
        (
            m.group(1),
            m.group(2),
            text[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)],
        )
        for i, m in enumerate(matches)
    ]


def _months(stamp: str) -> int:
    year, month = stamp.split("-")
    return int(year) * 12 + int(month)


# Vacuity floors, not coverage: the table has 32 rows and the principles 10 sections today,
# and these numbers say only "not empty enough to be a mistake". Pinning the exact counts
# would make every added source a test edit; the cited/citing tests below hold the content.
SOURCES_FLOOR = 20
PRINCIPLES_FLOOR = 8


TESTS = ROOT / "tests"


def test_no_module_claims_the_test_tree_cannot_share_a_helper() -> None:
    """The sentence that authorised the duplication this module exists to end.

    Three modules said, in as many words, that a helper was copied rather than imported
    because the test tree was not importable as a package and CONTRIBUTING forbade a
    cross-module import. Both halves are false: `tests/__init__.py` is tracked, `CONTRIBUTING.md`
    carries no such rule, and `tests/overlay/test_upgrade.py` imported the very class one of those
    comments said it could not (it and `tests/overlay/test_create.py` now import
    `tests.runners.Recorder`). What it cost, measured at the time: the hardened-`git` helper
    defined in 26 modules, six of them already drifted, while `tests/snapshot.py` published it.

    In a tree whose whole discipline is that a comment is evidence, a false comment that
    *authorises* a practice is worse than the practice. So the claim is a finding, and the
    import that disproves it is asserted to still exist.
    """
    # Mutation: put the sentence back into `tests/test_documents.py` -> reddens naming it.
    assert (TESTS / "__init__.py").is_file(), "tests/ stopped being a package"
    modules = sorted(TESTS.rglob("test_*.py"))
    # The walk's floor before anything is asserted about it: a glob that matched nothing would
    # make both lists empty and the claim check vacuously true.
    assert len(modules) >= 40, len(modules)
    texts = {module: module.read_text(encoding="utf-8") for module in modules}
    importers = sorted(m.name for m, text in texts.items() if "\nfrom tests." in text)
    # And the disproof is live rather than remembered: eight or more modules really do import
    # across the package today (nine when this was written).
    assert len(importers) >= 8, importers
    # Assembled rather than written out, because this module is inside the walk and a literal
    # needle would match the line that holds it — the guard would then report itself for ever.
    needle = "is not a " + "package"
    claims = sorted(str(m.relative_to(TESTS)) for m, text in texts.items() if needle in text)
    assert claims == [], claims


def test_the_methodology_walks_are_not_empty() -> None:
    # The vacuity guard for every parametrised test below: an empty methodology directory
    # or an empty sources table passes them all vacuously. Named apart from the gate guards in
    # `tests/test_neutral.py` so `-k` can pick one.
    assert PRINCIPLES in public_documents()
    assert len(sources()) >= SOURCES_FLOOR
    assert len(principle_sections()) >= PRINCIPLES_FLOOR


@pytest.mark.parametrize("path", public_documents(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_resolves(path: Path) -> None:
    # Mutation: point one README link at `docs/methodolgy/` — that file's case reddens naming
    # the target.
    missing = [target for target in links_in(path) if not (path.parent / target).exists()]
    assert missing == [], missing


def test_every_source_row_parses_and_the_table_has_no_other_rows() -> None:
    # A row that does not match the grammar is invisible to every test below, which is how a
    # citation to it would look dangling and a fix would be to "loosen the regex". So the
    # table's row count is measured two ways and they must agree: every `| S` line is a row.
    text = SOURCES.read_text(encoding="utf-8")
    declared = [line for line in text.splitlines() if line.startswith("| S")]
    assert len(declared) == len(sources()), "a source row does not match the grammar"


def test_every_citation_resolves_and_every_source_is_cited() -> None:
    # Mutations: cite `[S99]` in a principle → the first assertion reddens; add a source row
    # that no `[S98]` cites → the second reddens. Both directions, because an uncited source is a
    # source someone meant to use and forgot, which is a claim left without its evidence.
    cited = set(_CITATION.findall(PRINCIPLES.read_text(encoding="utf-8")))
    cited |= set(_CITATION.findall((METHODOLOGY / "README.md").read_text(encoding="utf-8")))
    known = set(sources())
    assert cited - known == set(), sorted(cited - known)
    assert known - cited == set(), sorted(known - cited)


def test_a_source_older_than_the_window_says_so() -> None:
    # Mutation: delete the word `older` from one dated-2025 row's notes → reddens naming it.
    # A `living` page is fresh by definition of the `read` column, so the arithmetic skips it.
    late = [
        source_id
        for source_id, (_, published, read, _, _, notes) in sources().items()
        if published != "living"
        and _months(read) - _months(published) > FRESH_MONTHS
        and "older" not in notes
    ]
    assert late == [], late


def test_a_fresh_source_is_not_labelled_older() -> None:
    # The other direction: the label means something only if it is absent where it does not
    # apply. Mutation: write `older` into a `living` row's notes → reddens.
    wrong = [
        source_id
        for source_id, (_, published, read, _, _, notes) in sources().items()
        if "older" in notes
        and (published == "living" or _months(read) - _months(published) <= FRESH_MONTHS)
    ]
    assert wrong == [], wrong


def test_every_principle_states_its_backing_and_cites_a_source() -> None:
    # Mutation: remove one `**Backing:**` line → that section is named. A `thin` principle
    # must still cite something or say why nothing exists; the citation rule here is that
    # every section carries at least one `[S<n>]`, and `thin` ones say in prose what the
    # citation does not establish — the README defines the labels.
    sections = principle_sections()
    unlabelled = [n for n, _, body in sections if not _BACKING.search(body)]
    assert unlabelled == [], unlabelled
    bad_label = [
        (n, m.group(1))
        for n, _, body in sections
        if (m := _BACKING.search(body)) and m.group(1) not in BACKING_LABELS
    ]
    assert bad_label == [], bad_label
    uncited = [n for n, _, body in sections if not _CITATION.search(body)]
    assert uncited == [], uncited


# `docs/methodology/README.md` states the thin count in prose and in words — `Three of the ten
# are thin` — because it is prose a person reads, not a table. The count is read off that
# sentence rather than written here, so an honest relabelling is one edit in the document it
# describes and none in this file; the test holds only that the two agree.
_THIN_CLAIM = re.compile(r"(\w+) of the (\w+) are thin", re.IGNORECASE)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}


def test_the_stated_thin_count_matches_the_labels() -> None:
    # A prose count in a tree that tests everything else it could: a fourth `thin` label, or a
    # third one relabelled, falsifies the sentence silently. Mutation: relabel one `sourced`
    # principle `thin` → reddens on the count.
    text = (METHODOLOGY / "README.md").read_text(encoding="utf-8")
    claim = _THIN_CLAIM.search(text)
    assert claim is not None, "docs/methodology/README.md no longer says how many are thin"
    stated_thin = _NUMBER_WORDS[claim.group(1).lower()]
    stated_total = _NUMBER_WORDS[claim.group(2).lower()]
    labels = [m.group(1) for _, _, body in principle_sections() if (m := _BACKING.search(body))]
    assert labels.count("thin") == stated_thin, labels
    # The other half of the sentence: `of the ten` is a count of principles, not of labels.
    assert len(principle_sections()) == stated_total


def test_principles_are_numbered_consecutively_from_one() -> None:
    # Cheap, and it is what makes `[principle 4]` in the README mean the same thing next
    # month. Mutation: renumber section 3 as 5 → reddens.
    numbers = [int(n) for n, _, _ in principle_sections()]
    assert numbers == list(range(1, len(numbers) + 1))


_COMMANDS_BLOCK = re.compile(r"^## Commands\n.*?^```text\n(.*?)^```", re.MULTILINE | re.DOTALL)


def readme_invocations() -> list[str]:
    """Every `stayfixed …` line in the README's Commands block, comments stripped."""
    match = _COMMANDS_BLOCK.search(README.read_text(encoding="utf-8"))
    assert match is not None, "README has no `## Commands` section with a ```text block"
    lines = (line.split("#", 1)[0].strip() for line in match.group(1).splitlines())
    return [line for line in lines if line.startswith("stayfixed ")]


def registered_commands() -> set[str]:
    """`group command` for every subcommand the real parser registers; a group with no
    subcommands (`hook <event>`) counts as its bare name."""
    groups = subparsers(build_parser(discover_registrars()))
    assert groups is not None
    found: set[str] = set()
    for group, sub in groups.choices.items():
        nested = subparsers(sub)
        if nested is None:
            found.add(group)
        else:
            found.update(f"{group} {command}" for command in nested.choices)
    return found


# A vacuity floor, not a count of the commands this CLI ships: the parser registered twenty
# when this test was written, and the number is here so that a walk which found nothing — or
# half of them — cannot satisfy the subset check above it. A change that ships a command raises
# the parser's count and leaves this alone.
REGISTERED_COMMANDS_FLOOR = 20


def test_the_parser_registers_what_this_test_expects_to_walk() -> None:
    # The mutation guard for the two tests below, and a pin on the walk's own mechanism:
    # `_SubParsersAction` is a private name, so the day argparse renames it this reddens
    # instead of `registered_commands()` returning an empty set that satisfies `<=`.
    found = registered_commands()
    assert {"memory index", "bugs check", "docs check", "plan check", "hook"} <= found
    assert len(found) >= REGISTERED_COMMANDS_FLOOR


# Where a tracked file names a command: in backticks, on a line that runs it through `uv run`,
# and on a line of a fenced block in a document. A mention wrapped onto the next line carries
# the comment marker or the string-concatenation quotes that continue it, which `_WRAP` reads
# as the space they stand for.
_MENTION = re.compile(r"`stayfixed\s([^`]{1,300})`")
_RUN = re.compile(r"\buv run stayfixed\s+([^\n`\"']*)")
_FENCED_LINE = re.compile(r"^\s*(?:\$ )?stayfixed\s+([^\n]*)", re.MULTILINE)
_WRAP = re.compile(r'"?\s*\n\s*(?:#\s*|f?")?')
_COMMAND_NAME = re.compile(r"[a-z][a-z0-9-]*")
# What the walk does not read, and why: a plan, the changelog and its fragments are the record of
# what a command was called when they were written, and a mutation entry plants an old spelling
# on purpose, in an `after` value no mention walk can tell from prose.
_NAMES_AS_THEY_WERE = ("docs/plans/", "changelog.d/", "mutations/", "CHANGELOG.md")
_NAMING_SUFFIXES = (".md", ".yml", ".yaml", ".toml", ".py")
# A vacuity floor, not a count: the walk read 877 mentions when it was written, and a regex
# that matched nothing would satisfy the check below it.
NAMED_COMMANDS_FLOOR = 500


def named_commands(relative: str, text: str) -> list[str]:
    """The text after `stayfixed` in each place `text` names a command."""
    found = [_WRAP.sub(" ", body) for body in _MENTION.findall(text)]
    found += _RUN.findall(text)
    if relative.endswith(".md"):
        for block in _FENCE.findall(text):
            found += _FENCED_LINE.findall(block)
    return found


def unregistered(named: list[str]) -> list[str]:
    """Each of `named` whose group, or whose command under a group, the parser does not register.

    Names only, never a parse: a synopsis carries placeholders (`<group>`, `…`, `{name}`), and a
    token that is not a command's name is not asked about.
    """
    groups = subparsers(build_parser(discover_registrars()))
    assert groups is not None
    wrong: list[str] = []
    for body in named:
        words = body.split()
        if not words or not _COMMAND_NAME.fullmatch(words[0]):
            continue
        if words[0] not in groups.choices:
            wrong.append(body)
            continue
        nested = subparsers(groups.choices[words[0]])
        if (
            nested is not None
            and len(words) > 1
            and _COMMAND_NAME.fullmatch(words[1])
            and words[1] not in nested.choices
        ):
            wrong.append(body)
    return wrong


def test_the_command_name_walk_discriminates() -> None:
    # The guard for the walk below, which asserts an absence: a walk that read no mention, or
    # asked nothing of one, would pass it. Spelled through `tick` and `run` so this file names no
    # command the walk would then find in it.
    tick, run = "`", "uv run"
    old = [
        f"run {tick}stayfixed release check{tick} first",
        f"{tick}stayfixed adopt begin{tick} and {tick}stayfixed test audit-entrypoints{tick}",
        f"# {tick}stayfixed overlay\n# publish{tick}",
        f"        run: {run} stayfixed release check --tag x",
    ]
    for text in old:
        assert unregistered(named_commands("x.py", text)), text
    assert unregistered(named_commands("x.md", "```bash\nstayfixed release check\n```\n"))
    fine = [
        f"{tick}stayfixed adopt promote{tick}, {tick}stayfixed hook <event>{tick}",
        f"{tick}stayfixed <group>{tick}, {tick}stayfixed …{tick}, {tick}stayfixed {{name}}{tick}",
        f'"{tick}stayfixed memory "\n    "index --check{tick}"',
        f"{tick}stayfixed --version{tick}, {run} stayfixed init --yes",
    ]
    for text in fine:
        named = named_commands("x.py", text)
        assert named and not unregistered(named), text


def test_every_command_a_tracked_file_names_is_one_the_parser_registers() -> None:
    # The release commands left the CLI for `scripts/release.py`, `adopt begin` and `test
    # audit-entrypoints` left it outright, and the tests that held the new spellings checked that
    # each was present, never that an old one was gone: five old spellings planted across the
    # contributor documents, the README, `docs/cli.md` and `release.yml` left them green. And a
    # source comment had named `overlay publish` since that command became `publish-template`.
    # Mutation (declared): `mutations/`'s "a source comment names the overlay command by its old
    # name".
    named: dict[str, list[str]] = {}
    count = 0
    for path in tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(_NAMES_AS_THEY_WERE) or not relative.endswith(_NAMING_SUFFIXES):
            continue
        found = named_commands(relative, path.read_text(encoding="utf-8"))
        count += len(found)
        if wrong := unregistered(found):
            named[relative] = wrong
    assert count >= NAMED_COMMANDS_FLOOR, count
    assert named == {}


def test_every_registered_command_has_a_readme_row() -> None:
    # Mutation: delete the `stayfixed docs trail` line from the README → reddens naming it.
    # This is the test that makes the README a shared file every command owes a line to.
    named = {" ".join(line.split()[1:3]) for line in readme_invocations()}
    named |= {line.split()[1] for line in readme_invocations()}
    missing = sorted(command for command in registered_commands() if command not in named)
    assert missing == [], missing


def test_every_readme_row_parses() -> None:
    # Mutation: change the `bugs new` row's `--severity high` to `--severity critical` →
    # reddens naming the line. Not `--sev high`, which parses: argparse accepts any
    # unambiguous prefix of a long option, so an abbreviated flag is the one mistake in a
    # row this test cannot catch.
    parser = build_parser(discover_registrars())
    failed: list[str] = []
    for line in readme_invocations():
        argv, _ = split_json_flag(shlex.split(line)[1:])
        with redirect_stderr(io.StringIO()):
            try:
                parser.parse_args(argv)
            except SystemExit:
                failed.append(line)
    assert failed == [], failed


# `--json`'s one cross-command promise, in the README's Exit-codes paragraph. The sentence
# named four commands while five emit the key — `memory refs` was missing — so a reader
# scripting against it would have treated a `findings` list as "this command does not report
# findings". Bound to the real parser's functions rather than to a second hand-written list.
_FINDINGS_SENTENCE = re.compile(
    r"The commands that report a list of\s+findings — (.+?) —\s+all spell it `findings`", re.DOTALL
)


def command_parsers() -> dict[str, argparse.ArgumentParser]:
    """`group command` -> the parser of every command the real parser registers; a group with no
    subcommands (`hook <event>`) is its own command, under its bare name."""
    groups = subparsers(build_parser(discover_registrars()))
    assert groups is not None
    found: dict[str, argparse.ArgumentParser] = {}
    for group, sub in groups.choices.items():
        nested = subparsers(sub)
        if nested is None:
            found[group] = sub
        else:
            found.update((f"{group} {command}", leaf) for command, leaf in nested.choices.items())
    return found


def command_functions() -> dict[str, object]:
    """`group command` -> the `run_*` callable the real parser dispatches to."""
    found: dict[str, object] = {}
    for name, leaf in command_parsers().items():
        func = leaf.get_default("func")
        if func is not None:
            found[name] = func
    return found


def test_the_readme_names_every_command_whose_json_carries_findings() -> None:
    # Mutation: drop `memory refs` from the README sentence -> reddens naming it.
    # The floor first: a walk that resolved no functions would make the comparison below
    # vacuously true, and a regex that stopped matching would look the same. Four emit the key
    # today: `bugs check`, `docs check`, `memory refs` and `plan check`.
    functions = command_functions()
    assert len(functions) >= REGISTERED_COMMANDS_FLOOR, sorted(functions)
    emitting = {
        name
        for name, func in functions.items()
        if '"findings":' in inspect.getsource(func)  # type: ignore[arg-type]
    }
    assert len(emitting) >= 4, sorted(emitting)
    match = _FINDINGS_SENTENCE.search(README.read_text(encoding="utf-8"))
    assert match is not None, "README's --json paragraph no longer names the findings commands"
    named = set(re.findall(r"`([^`]+)`", match.group(1)))
    assert named == emitting, (sorted(named), sorted(emitting))


RELEASING = ROOT / "RELEASING.md"
# `README.md`'s `## Install` section: everything between its heading and the next `## ` heading.
_INSTALL_SECTION = re.compile(r"^## Install\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL)


def test_the_readme_installs_the_release_the_tree_carries() -> None:
    """The Install section is what a new adopter copies, so it names this release and no other.

    Before 0.1.0 the section described the untagged install forms and a marked region the release
    commit replaced; `RELEASING.md` step 5 now bumps the two places the section names the
    version, and this holds them to the version `scripts/release.py check` holds everywhere else,
    which it cannot see in a README example. An untagged `git+` install or a promise about "the
    first release" would put a second install command beside the released one.

    Mutation (declared): the PyPI form becomes an untagged `git+` install -> this reddens.
    """
    match = _INSTALL_SECTION.search(README.read_text(encoding="utf-8"))
    assert match, "README.md has no ## Install section"
    section = match.group(1)
    version = __version__
    assert f"**Released as {version}.**" in section, section[:300]
    assert f"/plugin marketplace add stayfixed/stayfixed@v{version}" in section, section[:300]
    assert "uv tool install stayfixed\n" in section, section[:300]
    for stale in (
        "uv tool install git+",
        "Nothing is released yet",
        "first release",
        "release-install",
    ):
        assert stale not in section, stale
    assert "set both to the new version" in RELEASING.read_text(encoding="utf-8")


# A `gh` version `RELEASING.md` names as the floor: "`gh` 2.101.0 or later", "a `gh` older than
# 2.101.0", either wrapped across a line.
_GH_FLOOR_NAMED = re.compile(r"`gh`(?:\s+older\s+than)?\s+(\d+(?:\.\d+)+)")


def test_every_gh_floor_releasing_names_is_the_one_the_publisher_refuses_below() -> None:
    """Step 7 names the oldest `gh` the publisher accepts three times, and `GH_FLOOR` is the one
    the publisher enforces; a floor raised in the script and not in the document sends the owner
    to install a `gh` the publisher then refuses.

    Mutation (oracle): `mutations/`'s "RELEASING names an older gh floor than the publisher"
    -> reddens naming it. The set is held non-empty first, so a pattern that found none would
    hold the document to nothing: `mutations/`'s "the gh floor test reads no version from
    RELEASING" -> reddens.
    """
    floor = ".".join(str(part) for part in publish_plugin().GH_FLOOR)
    named = _GH_FLOOR_NAMED.findall(RELEASING.read_text(encoding="utf-8"))
    assert named, "RELEASING.md names no gh floor"
    assert set(named) == {floor}, (named, floor)


# The floor as the publisher's own docstring states it: "a release at least 2.101.0".
_GH_FLOOR_IN_DOCSTRING = re.compile(r"a release at least\s+(\d+(?:\.\d+)+)")


def test_the_publisher_s_docstring_names_the_gh_floor_it_refuses_below() -> None:
    """The publisher's module docstring, which `RELEASING.md` calls its reference, states the
    floor in prose beside `GH_FLOOR`; a floor raised in the constant alone leaves that reference
    naming a `gh` the publisher refuses.

    Mutation (oracle): `mutations/`'s "the publisher's docstring names an older gh floor than it
    refuses below" -> reddens naming it. Held to exactly one mention, so a pattern that found
    none holds nothing: the docstring rewritten without the phrase reddens too.
    """
    module = publish_plugin()
    floor = ".".join(str(part) for part in module.GH_FLOOR)
    named = _GH_FLOOR_IN_DOCSTRING.findall(module.__doc__ or "")
    assert named == [floor], (named, floor)


# `README.md`'s `## What each agent enforces` section: everything to the next `## ` heading.
_REACH_SECTION = re.compile(
    r"^## What each agent enforces\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL
)
# A cell's words where no tier is claimed for a surface under an agent.
NOT_REACHED = "not verified"


def _reach_table() -> str:
    """The README's table as the harness registry states it: a row per surface, a column per
    harness under the name `[stayfixed] agents` lists it by, and each cell its tier."""
    from stayfixed.harnesses import HARNESSES, Surface

    head = "| Surface | " + " | ".join(f"`{harness.name}`" for harness in HARNESSES) + " |"
    rule = "|---" * (len(HARNESSES) + 1) + "|"
    rows = [
        f"| {surface} | "
        + " | ".join(
            NOT_REACHED if (tier := harness.reach[surface].tier) is None else str(tier)
            for harness in HARNESSES
        )
        + " |"
        for surface in Surface
    ]
    return "\n".join([head, rule, *rows]) + "\n"


def test_the_readme_states_each_agents_reach_as_the_registry_does() -> None:
    # The table is rendered here from the registry and the README is held equal to it, so the
    # README stays a plain file a reader can open and the claim it makes about each agent cannot
    # drift from the one `doctor` reports. An empty table equals nothing rendered, so a section
    # that lost its table reddens too. Mutation (declared, on `harnesses`): Codex's session
    # notices stated as held in CI -> this reddens.
    match = _REACH_SECTION.search(README.read_text(encoding="utf-8"))
    assert match, "README.md has no ## What each agent enforces section"
    lines = match.group(1).splitlines(keepends=True)
    table = "".join(line for line in lines if line.startswith("|"))
    assert table == _reach_table(), table


# A fenced `toml` block, and inside one the `[stayfixed]` table's `version =` line: the table
# runs to the next table header or the end of the block, so a `version` key in another table
# is not taken for it.
_TOML_FENCE = re.compile(r"^```toml\n(.*?)^```", re.MULTILINE | re.DOTALL)
_STAYFIXED_TABLE = re.compile(r"^\[stayfixed\]\n((?:(?!\[).*\n)*)", re.MULTILINE)
_VERSION_KEY = re.compile(r'^version = "([^"]*)"', re.MULTILINE)


@pytest.mark.parametrize("document", [README, ROOT / "docs" / "cli.md"], ids=lambda path: path.name)
def test_the_example_configurations_carry_the_running_version(document: Path) -> None:
    """`doctor` warns whenever `[stayfixed] version` is not `__version__`, so an example that
    kept the last release's number is a copy-paste that makes a brand-new project warn.

    `scripts/release.py check` reads seven sources and none of them is an example in a document, so
    `RELEASING.md` step 3 once named these two blocks as held by nothing but the person cutting
    the release. This holds them, the way the Install section is held above.

    Mutation (declared, one per document): the example's `version` becomes `0.0.1-<version>`
    -> this reddens for that document.
    """
    versions = [
        key.group(1)
        for fence in _TOML_FENCE.finditer(document.read_text(encoding="utf-8"))
        for table in _STAYFIXED_TABLE.finditer(fence.group(1))
        for key in _VERSION_KEY.finditer(table.group(1))
    ]
    # A floor as well as the equality: a document whose example lost its `[stayfixed]` table
    # would otherwise compare an empty list and pass.
    assert versions, f"{document.name} has no example `[stayfixed]` table with a version"
    assert versions == [__version__] * len(versions), (document.name, versions)


def test_the_readme_points_at_the_methodology_and_the_reference() -> None:
    # The two documents a reader is sent to; a README that lost either link would still pass
    # the link walk (it checks the links that exist). Mutation: remove the methodology link.
    text = prose(README)
    assert "docs/methodology/README.md" in text
    assert "docs/cli.md" in text


# The paths `scripts/plugin_tree.py` renders into the plugin repository, read from its
# `PLUGIN_PATHS`. The subject here is the README's links, not that list: what the list holds is
# spelled out and pinned by `tests/scripts/test_plugin_tree.py`, so a fourth copy here would only
# be one more place to forget when the plugin gains a path.
PLUGIN_PATHS: tuple[str, ...] = plugin_tree().PLUGIN_PATHS
# A link to a file of this repository as `main` holds it, which moves only at a release.
_THIS_REPOSITORY_MAIN = re.compile(r"^https://github\.com/stayfixed/stayfixed/blob/main/([^#]+)")


def test_the_readme_links_only_inside_the_plugin_or_absolutely() -> None:
    """The README is published three times — here, on PyPI as the long description, and at the
    root of the plugin repository, which holds only the plugin's paths. A relative link to
    `docs/cli.md` resolves here and in nothing else, so a link to a file outside the plugin is
    absolute, to this repository's `main`. One inside it stays relative: it resolves here and in
    the plugin repository, though not on PyPI.

    `test_every_relative_link_resolves` holds that a relative link names a file here; this holds
    that the file is one the plugin repository has too, and that every absolute link to `main`
    names a tracked file, which the link walk skips as a URL.

    Mutations (declared): the reference link made relative again, `](docs/cli.md)` -> `outside`
    reddens; the same link spelled through a plugin path, `](src/stayfixed/../../docs/cli.md)`,
    which only the normalisation tells from one inside it -> `outside` reddens; the outbound
    walk's link naming a file that is not there -> `missing` reddens.
    """
    relative = links_in(README)
    # Floors: a README whose links all vanished, or a regex that stopped matching, would make
    # both walks vacuously true. `skills/README.md` and `LICENSE` stay relative today.
    assert len(relative) >= 2, relative
    # Normalised first: `src/stayfixed/../../docs/cli.md` starts with a plugin path and names a
    # file outside every one of them.
    normal = [posixpath.normpath(target) for target in relative]
    outside = [
        target
        for target in normal
        if not any(target == path or target.startswith(path + "/") for path in PLUGIN_PATHS)
    ]
    assert outside == [], outside
    absolute = [
        match.group(1)
        for target in _LINK.findall(prose(README))
        if (match := _THIS_REPOSITORY_MAIN.match(target))
    ]
    assert absolute, "README.md links nothing of this repository's main"
    tracked = set(tracked_files())
    missing = [path for path in absolute if ROOT / path not in tracked]
    assert missing == [], missing


CLI_REFERENCE = ROOT / "docs" / "cli.md"
# The `## Shared flags` section of `docs/cli.md`. Everything between its heading and the next `## `
# heading, so a table moved out of it stops being checked loudly rather than quietly.
_SHARED_FLAGS_SECTION = re.compile(r"^## Shared flags\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL)
_TABLE_ROW = re.compile(r"^\| (?!Flag |Command and flag |---)(.+?) \| (.+?) \|$", re.MULTILINE)


def test_the_shared_flag_tables_are_the_constants_and_not_a_second_spelling() -> None:
    # No shared-flag sentence is spelled by hand, and that section of `docs/cli.md` spelled all nine
    # of them a second time in a document nothing checked — re-creating, one file over, exactly the
    # drift one constant per flag exists to remove. Held row by row to `stayfixed.command`'s
    # constants, the same way the README's Commands block is held to the real parser above.
    #
    # Mutation: change the `--machine` row's cell in `docs/cli.md` → reddens naming the row.
    from stayfixed.command import (
        ATTACH_CHECK_HELP,
        CHECK_HELP,
        DRY_RUN_HELP,
        HOME_HELP,
        MACHINE_HELP,
        OVERLAY_ROOT_HELP,
        ROOT_HELP,
        SETUP_MACHINE_HELP,
        SETUP_ROOT_HELP,
        STORE_HELP,
    )

    expected = {
        "`--root`": ROOT_HELP,
        "`--machine`": MACHINE_HELP,
        "`--store`": STORE_HELP,
        "`--dry-run`": DRY_RUN_HELP,
        "`--home`": HOME_HELP,
        "`--check`": CHECK_HELP,
        "`stayfixed overlay upgrade --root`": OVERLAY_ROOT_HELP,
        "`stayfixed setup --root`": SETUP_ROOT_HELP,
        "`stayfixed setup --machine`": SETUP_MACHINE_HELP,
        "`stayfixed attach --check`": ATTACH_CHECK_HELP,
    }
    section = _SHARED_FLAGS_SECTION.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md has no `## Shared flags` section"
    rows = dict(_TABLE_ROW.findall(section.group(1)))
    # The walk's own floor, before anything is compared: a regex that matched nothing would
    # make every comparison below vacuously true, and a section that lost a table would look
    # exactly like one that never had it.
    assert len(rows) == len(expected), rows
    assert rows == expected, {
        flag: (rows.get(flag), sentence)
        for flag, sentence in expected.items()
        if rows.get(flag) != sentence
    }


# The Shared flags sentence naming the commands that take neither `--root` nor `--machine`, up to
# the reason it gives, so the list it holds is the one the sentence states and nothing around it.
_TAKES_NEITHER = re.compile(
    r"Neither flag is taken by (.+?),\s+because none of them reads a project", re.DOTALL
)
_PROJECT_FLAGS = frozenset({"--root", "--machine"})


def test_shared_flags_names_every_command_that_takes_neither_root_nor_machine() -> None:
    # The rule is stated once, in Shared flags, and the README and the `memory` bullet link to it:
    # it was spelled by hand in both, in two wordings, and nothing held either to the parser. Held
    # here to the same walk as the command table: the commands named as taking neither flag are
    # exactly those whose parser declares neither, every other `overlay` command takes `--root`
    # alone, and every command besides takes both.
    #
    # Mutation (declared): a command dropped from the takes-neither sentence -> this reddens.
    section = _SHARED_FLAGS_SECTION.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md has no `## Shared flags` section"
    match = _TAKES_NEITHER.search(section.group(1))
    assert match is not None, "Shared flags no longer names the commands that take neither flag"
    named = {" ".join(name.split()) for name in re.findall(r"`stayfixed ([^`]+)`", match.group(1))}
    options = {
        name: {flag for action in leaf._actions for flag in action.option_strings}
        for name, leaf in command_parsers().items()
    }
    # The walk's floor, for the reason the command-table test gives: a walk that found nothing
    # would make every comparison below vacuously true.
    assert len(options) >= 20, sorted(options)
    neither = {name for name, flags in options.items() if not flags & _PROJECT_FLAGS}
    assert named == neither, (sorted(named), sorted(neither))
    overlay = {name for name in options if name.startswith("overlay ")} - neither
    assert overlay, "no `overlay` command takes `--root`"
    assert {name for name in overlay if options[name] & _PROJECT_FLAGS != {"--root"}} == set()
    rest = set(options) - neither - overlay
    assert {name for name in rest if not options[name] >= _PROJECT_FLAGS} == set()


_REUSABLE_WORKFLOW_SECTION = re.compile(
    r"^## The reusable workflow\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL
)
# The repository settings the reusable workflow's verdict binds under. The caller file is
# pull-request content, so without them the gates still run and report but a pull request can
# edit its own caller; a section that lost one would read as if the verdict held without it.
SETTINGS = (
    "CODEOWNERS covering `/.github/`",
    "Dismiss stale pull request approvals when new commits are pushed",
    "the `check / gates` status check required",
    "expected source set to GitHub Actions",
    "branches required to be up to date before merging, or a merge queue",
    "a `v*` tag ruleset on the stayfixed repository",
)


def test_the_reusable_workflow_names_every_setting_the_verdict_binds_under() -> None:
    # No oracle entry: this holds a document, not a guard. Checked by hand when it was
    # written: the "Dismiss stale" bullet deleted from the section reddens this case naming it.
    section = _REUSABLE_WORKFLOW_SECTION.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md has no `## The reusable workflow` section"
    # Whitespace folded, so a setting wrapped across two lines is still found as one phrase.
    text = " ".join(section.group(1).split())
    assert [setting for setting in SETTINGS if setting not in text] == []


# The configuration block in `docs/cli.md` is introduced as the grammar, and the loader
# *refuses* an unknown section — so a section the block leaves out reads to a reader as a key
# that is invalid. Three of the nine were missing (`[artifacts]`, `[ci]`, `[commit_messages]`),
# which is the drift a binding prevents. `## Configuration` down to the next `## ` heading.
# The FIRST fenced `toml` block under `## Configuration` — the `stayfixed.toml` one. The section
# carries a second block, the machine file, whose `[personal]` and `[overlay]` are not sections
# of this grammar at all; scoping to the first block is what keeps the two apart.
_CONFIGURATION_BLOCK = re.compile(
    r"^## Configuration\n.*?^```toml\n(.*?)^```", re.MULTILINE | re.DOTALL
)
_TOML_HEADER = re.compile(r"^\[([a-z_]+)\]", re.MULTILINE)


def test_the_configuration_block_shows_every_section_the_loader_accepts() -> None:
    # Mutation: drop the `[ci]` header from `docs/cli.md`'s block -> reddens naming it.
    from stayfixed.config.loader import SECTIONS

    section = _CONFIGURATION_BLOCK.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md's `## Configuration` has no ```toml block"
    # The walk's floor before anything is compared: a regex that matched no headers would make
    # the set comparison below vacuously a subset in one direction and empty in the other.
    shown = _TOML_HEADER.findall(section.group(1))
    assert len(shown) >= len(SECTIONS), shown
    assert set(shown) == set(SECTIONS), (sorted(set(shown)), sorted(SECTIONS))


def test_the_configuration_block_lists_the_built_in_gates_in_their_one_order() -> None:
    # The reference is prose and cannot import the tuple, so its one spelling of the built-in
    # gates is pinned here. Mutation: reorder `builtin` in `docs/cli.md`'s block and this
    # reddens.
    from stayfixed.config.schema import BUILTIN_GATES

    section = _CONFIGURATION_BLOCK.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md's `## Configuration` has no ```toml block"
    listed = ", ".join(f'"{name}"' for name in BUILTIN_GATES)
    assert f"\nbuiltin = [{listed}]" in section.group(1)


# `plan check`'s rule count, stated in the reference and emitted by `docs/plans.py`. The
# sentence said "Four rules" and then listed five, in one breath, for as long as the fifth rule
# has existed. `base-unresolvable` is the refusal, not one of the rules the sentence counts.
_PLAN_RULES_SENTENCE = re.compile(r"\. (\w+) rules,\s+each\s+from\s+a\s+retrospective:")
_PLAN_FINDING_CODE = re.compile(r'Finding\("([a-z-]+)"')
PLAN_REFUSAL_CODE = "base-unresolvable"


def test_the_plan_rule_count_is_the_number_of_rules_plan_check_emits() -> None:
    # Mutation: change `Five rules` back to `Four rules` in `docs/cli.md` -> reddens naming
    # both numbers.
    source = (ROOT / "src" / "stayfixed" / "docs" / "plans.py").read_text(encoding="utf-8")
    codes = {c for c in _PLAN_FINDING_CODE.findall(source)} - {PLAN_REFUSAL_CODE}
    # The floor first: a regex that stopped matching would compare zero against a number word.
    assert len(codes) >= 5, sorted(codes)
    match = _PLAN_RULES_SENTENCE.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert match is not None, "docs/cli.md's `plan check` section no longer counts its rules"
    assert _NUMBER_WORDS.get(match.group(1).lower()) == len(codes), (match.group(1), sorted(codes))


# The `doctor` check table: fifteen rows, each spelling a check name, and the one
# code-restating table in this document the branch that built this binding mechanism did not
# bind. `tests/doctor/test_checks.py` pins each name as a literal exactly once *inside* the module
# that registers it — `checks.py` or an area's `doctor.py` — so the document's copy is a *second*
# spelling of each of the fifteen — one that
# guard cannot see, and a renamed check would leave this page green and wrong. That the unbound
# ones drift is not a hypothesis: `len(OVERLAY_FILES)` was sixteen while four comments one
# directory over still said fourteen.
_DOCTOR_SECTION = re.compile(
    r"^## `stayfixed doctor[^\n]*\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL
)
# `| `name` | what it answers | what it reads |` — the first cell only, backticked.
_CHECK_ROW = re.compile(r"^\| `([a-z-]+)` \| [^|]+ \| [^|]+ \|$", re.MULTILINE)


def test_the_doctor_table_is_the_registry_and_not_a_second_spelling() -> None:
    # Mutation: rename one check in `docs/cli.md`'s table -> reddens naming the row. In order
    # and not as a set, because the table's order is the report's order and the document says
    # so: the core's checks, then each area's contribution in area-name order.
    from stayfixed.doctor.checks import CHECKS
    from stayfixed.doctor.registry import contributions

    section = _DOCTOR_SECTION.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md has no `stayfixed doctor` section"
    rows = _CHECK_ROW.findall(section.group(1))
    # The walk's floor before anything is compared, for the reason the Shared flags test gives:
    # a regex that matched nothing would make the comparison below vacuously true, and a
    # section that lost its table would look exactly like one that never had it.
    expected = [name for name, _ in CHECKS]
    expected += [name for contribution in contributions(CHECKS) for name, _ in contribution.checks]
    assert len(rows) == len(expected), rows
    assert rows == expected, [
        (row, name) for row, name in zip(rows, expected, strict=True) if row != name
    ]


# Every shipped document that counts `doctor`'s rows, and the spelling each counts them in: the
# README's two command summaries, the reference's opening line, the skill's first step and the smoke
# workflow's assertion over an installed plugin's report.
_DOCTOR_COUNTS = {
    "README.md": re.compile(r"^stayfixed doctor +# (\w+) checks over this installation", re.M),
    "docs/cli.md": re.compile(r"^(\w+) checks over one installation", re.M),
    "skills/doctor/SKILL.md": re.compile(r"read the report: (\w+) checks"),
    ".github/workflows/smoke.yml": re.compile(r"assert len\(rows\) == (\d+), len\(rows\)"),
}


def test_every_document_counts_the_rows_the_report_has() -> None:
    # The count was written in five places and held in none: a row added to the report left four
    # documents and the smoke workflow saying the old number. Mutation (`mutations/`'s "the
    # reference counts one doctor row more than the report has"): `docs/cli.md` says sixteen.
    from stayfixed.doctor.checks import CHECKS
    from stayfixed.doctor.registry import contributions

    expected = len(CHECKS) + sum(len(c.checks) for c in contributions(CHECKS))
    for name, pattern in _DOCTOR_COUNTS.items():
        found = pattern.findall((ROOT / name).read_text(encoding="utf-8"))
        assert found, f"{name} no longer counts the doctor rows where this test reads"
        counted = [
            int(word) if word.isdigit() else _NUMBER_WORDS.get(word.lower()) for word in found
        ]
        assert counted == [expected] * len(found), (name, found, expected)


# The reference's sentence on the report's order counts the core's rows and the private layer's
# apart, a second count beside the total the test above holds: it said "the installation's own
# thirteen first" over a `CHECKS` of twelve, and the total, eighteen, still came out right.
_ROW_ORDER = re.compile(
    r"the installation's own (\w+) first, then the (\w+) about the\s+private layer"
)


def test_the_reference_counts_the_cores_rows_and_the_private_layers_apart() -> None:
    # Mutation (`mutations/`'s "the reference miscounts the installation's own doctor rows"):
    # reddens naming the word.
    from stayfixed.doctor.checks import CHECKS
    from stayfixed.doctor.registry import contributions

    section = _DOCTOR_SECTION.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md has no `stayfixed doctor` section"
    found = _ROW_ORDER.findall(section.group(1))
    assert len(found) == 1, found
    core, layer = found[0]
    contributed = sum(len(contribution.checks) for contribution in contributions(CHECKS))
    counted = (_NUMBER_WORDS.get(core.lower()), _NUMBER_WORDS.get(layer.lower()))
    assert counted == (len(CHECKS), contributed), (found[0], len(CHECKS), contributed)


# Every sentence in `docs/cli.md` that says how many noted key names `doctor` prints before it
# counts the rest: the `not-initialised` row, the paragraph under the table, and the exception in
# "What is printed".
_NAMES_SHOWN_SENTENCES = (
    re.compile(r"naming at most (\w+) of their keys and counting the rest"),
    re.compile(r"at most (\w+) names, one outside the path grammar withheld"),
)


def test_every_sentence_that_counts_the_names_doctor_shows_is_the_cap() -> None:
    # The cap was stated in words in the reference and held by nothing, while a comment beside it
    # said no shipped file stated it. Mutation (`mutations/`'s "doctor shows four noted names"):
    # the cap is four and the reference still says three.
    from stayfixed.doctor.checks import NAMES_SHOWN

    text = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    found = [word for pattern in _NAMES_SHOWN_SENTENCES for word in pattern.findall(text)]
    assert len(found) == 3, found
    assert [_NUMBER_WORDS[word] for word in found] == [NAMES_SHOWN] * 3


# The five verdict sentences are `VERDICTS` in `stayfixed.guards.attribute` and are reproduced by
# hand in `docs/cli.md`'s table; every test that had them read the expectation back out of
# `VERDICTS`, which is shape 9 of the `sweep-defect-class` skill's own reference — both sides move
# together under any reword. This is the same rule the Shared flags tables are held to, one section
# over.
_ATTRIBUTE_SECTION = re.compile(
    r"^## `stayfixed test attribute[^\n]*\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL
)
# `| fails | passes | — | `sentence` |`: the three code columns, then the sentence in backticks.
_VERDICT_ROW = re.compile(r"^\| (?:fails|passes) \| [^|]+ \| [^|]+ \| `(.+?)` \|$", re.MULTILINE)


def test_the_verdict_table_is_the_shipped_sentences_and_not_a_second_spelling() -> None:
    # Mutation: reword one sentence in `docs/cli.md`'s table — reddens naming the row.
    from stayfixed.guards.attribute import VERDICTS

    section = _ATTRIBUTE_SECTION.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md has no `stayfixed test attribute` section"
    rows = _VERDICT_ROW.findall(section.group(1))
    # The walk's floor before anything is compared, for the reason the Shared flags test gives:
    # a regex that matched nothing would make the comparison below vacuously true, and a
    # section that lost its table would look exactly like one that never had it.
    assert len(rows) == len(VERDICTS), rows
    assert tuple(rows) == VERDICTS, [
        (row, sentence) for row, sentence in zip(rows, VERDICTS, strict=True) if row != sentence
    ]


def _anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lower-cased, every character but a letter, a digit, a
    space, `-` and `_` dropped, and each space a hyphen."""
    kept = "".join(c for c in heading.lower() if c.isalnum() or c in " -_")
    return kept.replace(" ", "-")


def test_the_cli_reference_contents_lists_every_section_in_order() -> None:
    # Every `## ` heading after the Contents, in order, each linked by GitHub's anchor: a command
    # section added without its Contents line, or a heading renamed under a stale link, is
    # a reference a reader cannot navigate. The floor is today's count of sections after the
    # Contents, 39, so a walk that found nothing, or half, cannot pass.
    # Mutation (declared): drop the `memory fit` Contents line -> the lists differ.
    text = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    _, _, after = text.partition("## Contents\n")
    contents, _, rest = after.partition("\n## ")
    listed = re.findall(r"^- \[(.+)\]\(#([^)]+)\)$", contents, re.MULTILINE)
    headings = re.findall(r"^## (.+)$", "## " + rest, re.MULTILINE)
    assert len(headings) >= 39, len(headings)
    assert listed == [(heading, _anchor(heading)) for heading in headings]


# The `prove` section of `docs/cli.md`: its heading to the next `## ` heading.
_PROVE_SECTION = re.compile(r"^## `stayfixed prove .*?\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL)


def _prove_section() -> str:
    section = _PROVE_SECTION.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md has no `stayfixed prove` section"
    return section.group(1)


def test_the_prove_section_states_the_bound_word_for_word() -> None:
    # One source for the bound, which the section quotes as it is. Mutation (declared): the
    # bound's text changed in `run.py` -> the section no longer holds it.
    from stayfixed.prove.run import BOUND

    assert f"**What `proved` means.** {BOUND}\n" in _prove_section()


def test_the_json_keys_the_prove_section_lists_are_the_receipt_s_fields() -> None:
    # The section lists `--json`'s keys in order, each with what it holds in parentheses.
    # Mutation (declared): a field added to the receipt -> the section lists one key fewer.
    import dataclasses

    from stayfixed.prove.run import Receipt

    section = _prove_section()
    start = section.index("`--json` carries `verdict`") + len("`--json` carries ")
    end = section.index("`untracked_more`.", start) + len("`untracked_more`")
    listed = re.findall(r"`([a-z_]+)`", re.sub(r"\([^()]*\)", "", section[start:end]))
    assert listed == [field.name for field in dataclasses.fields(Receipt)]


# `| what holds | `verdict` | exit | reason(s) |`: a row of the prove section's verdict table.
_CASCADE_ROW = re.compile(r"^\| [^|]+ \| `([a-z ]+)` \| (\d) \|([^|]*)\|$", re.MULTILINE)


def test_the_prove_verdict_table_is_the_cascade_row_for_row() -> None:
    # The table says it is `CASCADE`, the first row that holds winning: each row its verdict, its
    # exit code and, where the cascade names one, its reason; a row whose reason is the step's
    # that stopped the run lists some. Mutation (declared): `mutations/`'s "the cascade's
    # green-but-exited row is no longer the table's" -> that row's verdict differs.
    from stayfixed.prove.run import CASCADE, EXIT

    rows = _CASCADE_ROW.findall(_prove_section())
    # The walk's floor, for the reason the Shared flags test gives.
    assert len(rows) == len(CASCADE), rows
    for (verdict, code, reasons), (expected, reason, _) in zip(rows, CASCADE, strict=True):
        assert (verdict, int(code)) == (expected, EXIT[expected]), (verdict, code)
        if reason is None:
            assert reasons.strip(), verdict
        else:
            assert reasons.strip() == (f"`{reason}`" if reason else ""), (verdict, reasons)


def test_every_reason_constant_is_documented() -> None:
    # Every reason a receipt can carry, the run's, the readers' and each shipped adapter's, is
    # named in the section as its code span. Mutation (declared): a reason's text renamed -> the
    # section no longer names it.
    import sys

    from stayfixed.profiles.adapters import shipped_adapters
    from stayfixed.prove.run import WORDS

    core = {reason for reason in WORDS if reason}
    adapters: set[str] = set()
    for adapter in shipped_adapters():
        adapters |= set(sys.modules[type(adapter).__module__].REASONS)
    # The receipt's line words an adapter's reason by the verdict it stopped the run with, and the
    # core's by `WORDS`: a reason of both would be worded as the core's.
    assert core.isdisjoint(adapters), sorted(core & adapters)
    reasons = core | adapters
    section = _prove_section()
    # The walk's floor: the core's reasons alone, so a discovery that found no adapter cannot
    # pass with nothing of theirs held.
    assert adapters and len(reasons) > len(core), sorted(reasons)
    assert [reason for reason in sorted(reasons) if f"`{reason}`" not in section] == []


# The "Note sync" section names what the sync keeps and every outcome it records, in words that
# were written beside the code and are held to it here: a fifth file in the state directory, a new
# outcome or a different throttle would leave the section true of a sync that is gone.
_NOTE_SYNC_SECTION = re.compile(r"^## Note sync\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL)


def test_the_note_sync_section_names_what_the_sync_keeps_and_records() -> None:
    # Mutation (declared): a sixth outcome in `state.OUTCOMES`, or `CHECKOUTS_FILE` renamed ->
    # reddens naming the word the section lacks.
    from stayfixed.sync import state

    section = _NOTE_SYNC_SECTION.search(CLI_REFERENCE.read_text(encoding="utf-8"))
    assert section is not None, "docs/cli.md has no `Note sync` section"
    text = section.group(1)
    kept = (
        state.STATE_FILE,
        state.LOCK_FILE,
        state.SLEEPER_LOCK_FILE,
        state.PENDING_FILE,
        state.CHECKOUTS_FILE,
        f"{state.SCRATCH}/",
    )
    absent = [f"`{word}`" for word in (*kept, *state.OUTCOMES) if f"`{word}`" not in text]
    assert absent == [], absent
    assert f"within {state.THROTTLE_SECONDS} seconds" in text
    assert f"{state.BACK_OFF_MINUTES} minutes" in text
