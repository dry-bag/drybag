"""No project-identifying string anywhere in the public repository — the whole tree.

Two copies of this gate, each scoped to one area, held the door before it; this whole-tree gate
replaced both, and no scoped copy is to be added beside it. Source under `src/`, `tests/` and
`scripts/` is held to the full table: a module has no reason to spell a default path. Every other
tracked text file is held to the public table, which exempts exactly the preset's own default
`[paths]` values, because a document that could not say where the note store lives by default would
be useless. The denylist is digests; the two docstrings this replaces say why, and their reasoning
is kept verbatim in `digest_of`.

**The denylist is stored as digests, not as the tokens themselves, and that is not decoration.**
A gate that lists the strings it is hiding publishes them: this file ships in a public repository,
so a plain-text list would put every identifier this gate forbids into the very tree the rule is
about, one `grep` away. Each entry is a lower-cased token's length and a short `blake2s` digest of
it; the scan hashes every window of each stored length and compares digests.
The behaviour is identical to the substring list it replaces — the same inputs fail — and a
digest is not a secret, it is merely not readable. **Do not "simplify" them back into
literals.** To add a token, run `digest_of("<token>")` and append `(len, digest)`.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

from tests.declarations import declared, relative
from tests.gitfixture import needs_git, run_git

ROOT = Path(__file__).resolve().parents[1]
THIS = Path(__file__).resolve()
FULL_TABLE_TREES = ("src", "tests", "scripts")
# How many tracked files the walk is allowed to skip for being undecodable. One, measured: the
# plugin directory's listing icon, `.claude-plugin/icon.png`, is this repository's only binary.
# A file that changes it is a deliberate edit here and not a case that quietly stopped being
# checked.
UNDECODABLE = 1
# Only for the fallback walk in an unpacked sdist, where `git ls-files` cannot answer.
FALLBACK_EXCLUDED = {
    ".git",
    ".venv",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    ".claude",
    ".superpowers",
}


def _digest(window: bytes) -> str:
    return hashlib.blake2s(window, digest_size=6).hexdigest()


def digest_of(token: str) -> str:
    """The stored form of one denylist token: twelve hex characters, not eight.

    Eight would be a lower-case hex run of exactly the length the `bare commit id` arm below
    matches, and these digests are quoted in the plan, which this gate walks.
    """
    return _digest(token.lower().encode("utf-8"))


# `(length, digest)` per lower-cased substring. Each stands for a path, identifier or name that
# belongs to the repository the guards were extracted from and to no other; none is a word a
# neutral guard needs. The module docstring says why they are digests rather than the strings.
FORBIDDEN = (
    (7, "41d4469bc846"),
    (6, "7f5fd64931a1"),
    (16, "5b958322253b"),
    (10, "3b2506f40a57"),
    (15, "d67aef39d5ec"),
    (22, "084d395e2884"),
    (17, "f88e4d57bd04"),
    (13, "19a6183f34da"),
    (8, "5a6645d31f46"),
    (16, "96f4afbf58ea"),
    (11, "cbab126d3cca"),
    (13, "4ed3b2917da0"),
    (17, "804de1d3098a"),
    (9, "5f65f06d6470"),
    (9, "453c2632b940"),
    (8, "6144c481add3"),
    (8, "54b030106757"),
    (4, "dea22fd6c241"),
    (4, "188937a5982a"),
    (8, "4d1fd41cacbb"),
    # Added 2026-09-19, and the only entry here that stands for a *shape* rather than for one
    # string: the branches of the source repository that the copied plans still reached for
    # share a slashed middle, so one entry covers the three that were standing and the siblings
    # nobody has written yet. Its first character is load-bearing and it is a separator —
    # without it the entry would also match this repository's own public document filenames,
    # which are legitimate. Measured: three occurrences across two documents before this entry
    # went in, none after, and nothing else in the tree carries it.
    (15, "a2de6ee9ce61"),
)
_URL = re.compile(r"https?://\S+")
# The arms that read the text with its URLs blanked out, and it is exactly one. A documentation
# URL can carry a vendor name as a path segment, so `/codex/quick-start` in a link is a path and
# not a branch. The other two arms read the original text, and that distinction is the whole
# point of naming them here rather than blanking once for everybody: a personal address inside a
# `mailto:`, a profile URL or a query parameter is still a personal address, and a commit id in
# a query parameter is still a commit id. Blanking the lot took both of those out of every URL
# in the tree — the same shape of defect as the arm this replacement was written for.
# The denylist scan is never blanked: a forbidden token inside a URL is still that token.
URL_BLIND = frozenset({"vendor branch"})
# Shapes a substring list cannot express: a personal address, a bare commit id, a
# vendor-prefixed branch name at any depth. Each arm is named so a hit says what it is.
SHAPES = (
    # Not `@users.noreply.github.com`: that is GitHub's generic form and must pass.
    ("personal email", re.compile(r"@(?:gmail|yandex|mail|icloud|proton)\.\w+")),
    # At least one digit, so an eight-letter hex word (`deadbeef`) is not an id — and, by the
    # same argument in the other direction, at least one letter, so a plain decimal number is
    # not one either. The second lookahead is this gate's own finding: the first whole-tree
    # walk reddened `uv.lock` fifty-five times on `size = 13936739`, a file size the resolver
    # writes and no edit of ours can neutralise, and the arm would go on firing on every
    # byte count, timestamp and line number in the tree. What it costs is an abbreviated id
    # that happens to be all digits, which is (10/16)**8 of them and which no rule could tell
    # from an ordinary number anyway.
    (
        "bare commit id",
        re.compile(r"(?<![\w/])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{8,10}(?![\w/])"),
    ),
    # One arm for every form of the name, in three parts, and the only one in `URL_BLIND`
    # above. The lookbehind keeps a dotted harness directory out — a public document has to be
    # able to name the one it configures. The optional path prefix lets any depth in, so a
    # remote-qualified name, a `refs/heads/` name, a worktree path and a remote nobody thought
    # to list are one shape rather than a list to keep up with. And requiring a `-` or `_` in
    # the branch segment is what tells a branch name from the slashed prose pair of the two
    # harness names, which this project's own one-line pitch invites: real branch names are
    # dashed by convention.
    (
        "vendor branch",
        re.compile(r"(?<![.\w])(?:[\w.-]+/)*(?:codex|claude|cursor)/[a-z0-9][\w-]*[-_][\w-]*"),
    ),
)


def offending(text: str, forbidden: tuple[tuple[int, str], ...] = FORBIDDEN) -> list[str]:
    """Every denylist digest and every shape name the text hits — and, for a digest, where.

    A hashed denylist cannot be substring-matched, so the text is scanned by window: for each
    stored length, every window of that length in the lower-cased bytes is hashed and the
    digests are intersected with the entries of that length. Every token is ASCII, so a window
    over bytes and a substring of the string agree, and this is exactly the `token in lowered`
    it replaces.

    **A digest hit carries the offset of its first matching window**, because without one this
    gate had no way to diagnose a hit at all. It now holds every tracked file, and a contributor
    who trips an entry used to get `AssertionError: (PosixPath('…'), ['token dea22fd6c241'])` —
    a twelve-hex digest naming neither the offset nor the window, against a table they cannot
    read by construction. Two entries are four characters long, which no one can brute-force by
    eye. The offset leaks nothing the tree did not already contain: the contributor reads the
    characters off their own file, which is the file they wrote. `at <offset>` is a CHARACTER
    offset into `text.lower()` — the scan runs over bytes and the report is converted back,
    because `CONTRIBUTING.md` tells the reader to slice characters at it and this repository's
    house style is em dashes, three bytes each. The entry's own stored length is the window's:
    say both, so the report is actionable without the table being readable.

    The shape arms keep their bare names. A shape is a regex a reader can look up in `SHAPES`
    two screens up, so an offset would be noise; the digests are the half nothing in the
    repository can spell out.
    """
    # **The cost, measured, and why there is no prefilter in front of it.** This is one
    # `blake2s` per window per distinct stored width — twelve of them — so the whole-tree walk
    # is about twelve passes over 4.8 M characters, 13 s of the suite on the machine this was
    # measured on (2026-09-20), and it runs on three interpreters in CI.
    #
    # A two-stage prefilter is the obvious repair, and **the measurement is what rules it out**
    # rather than any argument about what can be built. A first stage needs a cheap key per
    # token; one could be stored — a second, shorter derived column, produced by the same
    # `digest_of` an author already runs to add a token, revealing no more than the six-byte
    # digest beside it. What it would buy is the number below.
    #
    # Measured on the largest file in the tree: the current scan, 0.655 s. `.digest()` bytes
    # instead of `.hexdigest()`, 0.636 s. Hashing only the distinct windows per width, 0.711 s,
    # because 61% of windows at these widths are already distinct. `memoryview` slices, 0.690 s.
    # And a **hypothetical perfect one-byte prefilter**, which no real table could beat: 0.286 s.
    # That is the ceiling on the whole idea — 2.3x, not the twelvefold the pass count suggests —
    # against 13 s of a suite that runs in about 170 s. A second stored column, and a second way
    # for the table to fall out of step with itself, does not buy 7 s.
    #
    # Note also what this is not. The bound on CI is the oracle job, not this gate; the two are
    # unrelated and must not be traded against each other.
    raw = text.lower().encode("utf-8")
    found: list[str] = []
    for width in sorted({width for width, _ in forbidden}):
        wanted = {digest for length, digest in forbidden if length == width}
        # First window and not last, and the ordering is by digest as it was: a scan that
        # reported the final occurrence would send a reader to the wrong line in a file that
        # carries the token twice, which is the ordinary case for a name.
        first: dict[str, int] = {}
        for start in range(len(raw) - width + 1):
            digest = _digest(raw[start : start + width])
            if digest in wanted and digest not in first:
                first[digest] = start
        # Reported as a CHARACTER offset, not as the byte offset the scan works in. The two
        # differ on every line in this repository's house style — an em dash is three bytes —
        # and `CONTRIBUTING.md` tells a contributor to slice the entry's own length *in
        # characters* from that offset. Measured before this line existed: on
        # "the gate — the one that walks the tree — refuses quernstone here" the gate said
        # `at 53` where the token begins at character 49, and following the instruction gave
        # 'nstone her'. The prefix always ends on a character boundary, because every stored
        # token is ASCII and so every matching window begins at an ASCII byte.
        found.extend(
            f"token {digest} at {len(raw[: first[digest]].decode('utf-8', 'ignore'))}"
            for digest in sorted(first)
        )
    lowered = text.lower()
    blanked = _URL.sub(" ", lowered)
    found.extend(
        name for name, shape in SHAPES if shape.search(blanked if name in URL_BLIND else lowered)
    )
    return found


def _preset_paths() -> tuple[tuple[int, str], ...]:
    """The digests of the default `[paths]` values the preset ships.

    One of them is in `FORBIDDEN`, because it was the source repository's path before it was
    stayfixed's default. A public document that could not say where the note store
    lives by default would be useless, so the public-document walk exempts exactly the values
    the plugin itself ships — read off the preset at import time, never written here. Source
    code keeps the full table: a module has no reason to spell a default path.
    """
    from stayfixed.presets import load_preset

    values = load_preset("recommended")["defaults"]["paths"].values()
    return tuple((len(value), digest_of(value)) for value in values)


PUBLIC_FORBIDDEN = tuple(entry for entry in FORBIDDEN if entry not in _preset_paths())
# One of the preset's default `[paths]` values is also a digest-table entry — the one that was the
# source repository's path before it was stayfixed's default. Pinned so the exemption cannot
# quietly grow: a second would mean a token was added to the table for a
# path the plugin itself ships, which is a contradiction to resolve, not to exempt.
PRESET_PATHS_IN_TABLE = 1


# Every top-level directory this repository tracks, measured 2026-09-19 against
# `git ls-files`. The whole-tree gate names one file in most of them and asserts the tree
# itself for all of them, which is the guard the two numeric floors could not be: four of these
# can disappear from the walk with both floors still satisfied.
TRACKED_TREES = (
    ".claude-plugin",
    ".codex-plugin",
    ".github",
    "agents",
    "changelog.d",
    "docs",
    "hooks",
    "scripts",
    "skills",
    "src",
    "tests",
)


def tracked_files() -> list[Path]:
    """Every file git tracks, or every file under the tree minus the fixed exclusions."""
    # `--others --exclude-standard` as well as `--cached`: a fixture being added is untracked
    # until its commit, and a gate that could not see it until the commit after would let the
    # commit that adds it land unwalked.
    done = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=False,
    )
    if done.returncode == 0 and done.stdout:
        names = [n for n in done.stdout.decode("utf-8").split("\0") if n]
        return sorted(ROOT / n for n in names if (ROOT / n).is_file())
    return walked(ROOT)


def walked(root: Path) -> list[Path]:
    """The fallback: every file under `root` minus the fixed exclusions."""
    # Anchored on the FIRST component: `tests/fixtures/hostile-project/.claude/settings.json`
    # is a fixture to walk, not a configuration directory to skip. Coverage's data files are
    # named rather than listed: each sits in the root and is its own first component. Bytecode
    # is the one exclusion at any depth: one pytest run leaves `tests/__pycache__/*.pyc` beside
    # every module, and no fixture is named `__pycache__`.
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and (parts := p.relative_to(root).parts)[0] not in FALLBACK_EXCLUDED
        and "__pycache__" not in parts
        and not (len(parts) == 1 and (p.name == ".coverage" or p.name.startswith(".coverage.")))
    )


def test_the_fallback_walk_skips_coverage_data_in_the_root(tmp_path: Path) -> None:
    # The sdist half of the test below. An unpacked sdist has no `.git`, so no `.gitignore`
    # applies, and the contributor's `pytest -n auto --cov` leaves `.coverage` and one
    # `.coverage.<host>.pid<pid>.X<random>x` per worker in the root: SQLite, undecodable, and
    # counted against `UNDECODABLE` by whichever run a worker finished first. A root-level file
    # is its own first component, so `FALLBACK_EXCLUDED` cannot name one; this is by file name.
    #
    # Mutation (declared): the coverage clause dropped from `walked` -> both files are walked.
    for name in (".coverage", ".coverage.runner_host.pid4242.XaBcDeFx", "README.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert [p.name for p in walked(tmp_path)] == ["README.md"]


def test_the_fallback_walk_skips_bytecode_at_any_depth(tmp_path: Path) -> None:
    # An unpacked sdist after one pytest run: `__pycache__` sits beside every module, not only in
    # the root, and its `.pyc` files are undecodable — the public-anchor gate reads every file it
    # is given and would raise on the first one.
    #
    # Mutation (declared): the any-depth clause dropped from `walked` -> the `.pyc` is walked.
    (tmp_path / "tests" / "__pycache__").mkdir(parents=True)
    (tmp_path / "tests" / "__pycache__" / "test_x.cpython-313.pyc").write_bytes(b"\xa7\r\r\n")
    (tmp_path / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
    assert [p.relative_to(tmp_path).as_posix() for p in walked(tmp_path)] == ["tests/test_x.py"]


@needs_git
@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="no git checkout to ask")
def test_a_coverage_worker_file_is_not_a_file_the_gate_walks(tmp_path: Path) -> None:
    """The suite runs across workers, and under `--cov` each one leaves its own data file in
    the root while the others still run — `.coverage.<host>.pid<pid>.X<random>x`, SQLite and
    undecodable. `tracked_files` reads `--others --exclude-standard`, so a `.gitignore` naming
    only `.coverage` handed seven of them to `test_the_gate_reads_the_whole_tree` mid-run on
    2026-09-26: `UNDECODABLE` 0, counted 7, and which run it reddened was a matter of timing.

    Asked of git's rules without the file, so this module writes nothing into the tree it walks,
    and in `gitfixture`'s sealed environment, so a developer's global excludes cannot answer for
    the repository's own `.gitignore`.
    Mutation: drop `.coverage.*` from `.gitignore` -> reddens here, on every run.
    """
    worker = ".coverage.runner_host.pid4242.XaBcDeFx"
    ignored = run_git(ROOT, "check-ignore", "-q", "--no-index", worker, home=tmp_path)
    assert ignored.returncode == 0, ignored.stderr


# **What the split gives up, stated as a decision rather than left as an accident.** The two gates
# this replaces walked `skills/**/*.md` and `agents/*.md` under the FULL table; the rule is that
# `.py` under the three source trees takes the full table and every other text file takes the public
# one, so under one gate those documents take the public table and may now spell a preset default
# `[paths]` value where they could not before. That is the design and not a slip: a skill is a
# document a person reads, and the argument that a README which could not say where the note store
# lives by default would be useless is the same argument one directory over. The denylist proper is
# unchanged for them — only the exempted preset default moves — and the shape arms are not
# table-scoped at all, so a personal address, a bare commit id and a vendor branch are still refused
# in a skill. Changing it back means changing that rule, not only this function.
def table_for(path: Path) -> tuple[tuple[int, str], ...]:
    relative = path.relative_to(ROOT)
    source_tree = relative.parts[0] in FULL_TABLE_TREES
    if source_tree and (path.suffix == ".py" or relative.parts[0] == "scripts"):
        return FORBIDDEN
    return PUBLIC_FORBIDDEN


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def test_the_gate_reads_the_whole_tree() -> None:
    # The non-vacuity guard for the parametrised walk below. Named files from six different
    # trees, and a floor well under today's count — the one measurement of that count is the
    # sentence further down, taken from this walk rather than restated here. The number that
    # used to stand in this line was 310, which was the mutation declarations' entry count copied
    # into the wrong comment: two comments in one function, disagreeing, about the same quantity.
    files = tracked_files()
    names = {str(p.relative_to(ROOT)) for p in files}
    # No `.github/` name here: that tree is outside `source-include`, and this floor has to
    # hold in the unpacked sdist the fallback walk exists for. `skills/` and `agents/` are
    # inside it, so they are named like the rest.
    for wanted in (
        "README.md",
        "src/stayfixed/cli.py",
        "docs/cli.md",
        "hooks/run-hook.sh",
        "scripts/stayfixed",
        "tests/test_fsops.py",
        "skills/README.md",
        "agents/code-navigator.md",
    ):
        assert wanted in names, wanted
    # The mutation declarations by their directory and not by a group file's name, which is
    # `GROUP_OF`'s to choose and to change.
    assert any(name.startswith("mutations/") for name in names), "no declaration file is walked"
    # **One assertion per tracked top-level tree, because the two floors below cannot hold
    # this.** Measured 2026-09-19: `tracked_files()` made to drop every path whose first
    # component is `.github`, `skills`, `agents` or `changelog.d` — 58 of 347 files, every
    # workflow, every skill document and the whole changelog fragment directory — left this
    # module at 300 passed, 0 failed, down from 358. The 58 parametrised cases below simply
    # stopped existing, and the file count and the character count both stayed over their
    # floors because `docs/` alone is 1.81 M characters. A higher floor does not close that;
    # naming the trees does.
    #
    # Guarded on the tree being there rather than listed with exemptions: `.github/` is outside
    # `source-include` and is absent from the unpacked sdist the fallback walk exists for, and
    # `changelog.d/` is empty for as long as it takes towncrier to consume it at a release. The
    # claim is "a tree that exists on disk is a tree this walk reads", which is true in both
    # places and needs no list of which is which.
    trees = {p.relative_to(ROOT).parts[0] for p in files if len(p.relative_to(ROOT).parts) > 1}
    for tree in TRACKED_TREES:
        if any((ROOT / tree).rglob("*")):
            assert tree in trees, (tree, sorted(trees))
    assert len(files) >= 200, len(files)
    assert THIS in files
    # And that a file was actually READ, and that reading it produced its CONTENT. Every
    # parametrised case below calls `_text` and skips on `None`, so a regression in `_text` — a
    # changed encoding argument, a widened `except` — turns all of them into skips, and a run of
    # 346 skips and no failures is what a green gate looks like from the outside. Counting the
    # files that decoded closes that; counting the characters closes the shape one step along,
    # where `_text` answers `""` for everything, every case scans an empty string and passes,
    # and the file count is still full. **The measurement, once, and this is the only place in
    # this module that states it:** on 2026-09-19, running `tracked_files()` and `_text` from
    # this module, `len(tracked_files())` was 347, of which 346 are read here (this file is the
    # one the walk skips), none was undecodable, and they hold 4,806,797 characters.
    # `UNDECODABLE` and the character floor are numbers somebody moves on purpose, not silences
    # to walk past.
    read = [_text(path) for path in files if path != THIS]
    kept = [text for text in read if text is not None]
    assert len(kept) >= 200, len(kept)
    assert len(read) - len(kept) == UNDECODABLE, (len(read), len(kept))
    assert sum(len(text) for text in kept) >= 2_000_000, sum(len(text) for text in kept)


def test_the_two_tables_are_told_apart_by_the_file_they_are_for() -> None:
    # `table_for` is what decides whether a file may name a default path, so it is worth an
    # assertion of its own rather than only being exercised through the walk. A module and a
    # test module take the full table; the preset that ships those defaults, every document,
    # and a data file under a full-table tree take the public one. `scripts/stayfixed` has no
    # suffix at all and is source, which is why the tree name is a second arm.
    assert table_for(ROOT / "src" / "stayfixed" / "cli.py") == FORBIDDEN
    assert table_for(ROOT / "tests" / "test_fsops.py") == FORBIDDEN
    assert table_for(ROOT / "scripts" / "stayfixed") == FORBIDDEN
    assert (
        table_for(ROOT / "src" / "stayfixed" / "presets" / "recommended.toml") == PUBLIC_FORBIDDEN
    )
    fixture = ROOT / "tests" / "fixtures" / "smoke-project" / "stayfixed.toml"
    assert table_for(fixture) == PUBLIC_FORBIDDEN
    assert table_for(ROOT / "docs" / "cli.md") == PUBLIC_FORBIDDEN
    assert table_for(ROOT / "README.md") == PUBLIC_FORBIDDEN
    # And the two tables really are different tables, or every arm above would be the same
    # claim written seven ways.
    assert PUBLIC_FORBIDDEN != FORBIDDEN


def test_the_denylist_is_stored_as_digests() -> None:
    # The gate that hides a name must not publish it. This reddens if anyone replaces the
    # digests with the tokens, or empties the list on the way past.
    assert len(FORBIDDEN) == 21
    assert all(length >= 4 for length, _ in FORBIDDEN)
    assert all(re.fullmatch(r"[0-9a-f]{12}", digest) for _, digest in FORBIDDEN)


def test_the_digest_function_is_pinned() -> None:
    # `test_the_gate_discriminates` builds its expected value with `digest_of`, so both sides
    # move together and it cannot pin the hash. This does: change the algorithm or the digest
    # size and every stored digest stops matching, which would leave the tree gate green while
    # checking nothing at all. Second line: the scan lower-cases, so the stored form must too.
    assert digest_of("quernstone") == "be440e8c9338"
    assert digest_of("QuernStone") == digest_of("quernstone")


def test_the_gate_discriminates() -> None:
    # The oracle for the gate itself: a token planted in a synthetic string is found, and so
    # is each regex arm; a neutral fixture is not. The planted token is a made-up word passed
    # in as a one-entry denylist, not a real `FORBIDDEN` entry — writing a real one here would
    # undo the hashing this file exists to keep.
    probe = "quernstone"
    planted = ((len(probe), digest_of(probe)),)
    assert offending("see Quernstone/plans", planted) == [f"token {digest_of(probe)} at 4"]
    assert offending("see quernston/plans", planted) == []
    assert offending("Co-authored-by: Someone <someone@gmail.com>") == ["personal email"]
    assert offending("fixed in 1b279648") == ["bare commit id"]
    # Inside a URL, which is where a personal address and a commit id are most often written:
    # a `mailto:`, a profile link, a query parameter. Only the vendor arm is blanked, because
    # only the vendor arm has a legitimate reason to appear in a URL path; blanking for all
    # three took these two out of every link in the tree and nothing said so.
    assert offending("https://example.test/u?mail=someone@gmail.com") == ["personal email"]
    assert offending("https://example.test/r?sha=1b279648") == ["bare commit id"]
    assert offending("cut from codex/inbound-remediation") == ["vendor branch"]
    # Every prefixed form, on one arm rather than on a list of remote names: this is how a
    # commit message, `git branch -a`, a `refs/` ref and a worktree path each write the same
    # branch. `wp/` is this repository's own branch prefix and `myremote` is a remote nobody
    # thought to list, which is the point — two rounds of review found this arm short by
    # exactly the prefixes no one had enumerated.
    branch = ["vendor branch"]
    assert offending("cut from origin/codex/inbound-remediation") == branch
    assert offending("remotes/origin/codex/inbound-remediation") == branch
    assert offending("refs/heads/codex/inbound-remediation") == branch
    assert offending("wp/codex/inbound-remediation") == branch
    assert offending("myremote/codex/inbound-remediation") == branch
    assert offending("../wt/codex/foo-bar") == branch
    assert offending("upstream/claude/some-branch") == branch
    assert offending("merged fork/cursor/spike-one") == branch
    assert offending("cat secrets/.env; person@example.com; 0x1234; deadbeef") == []
    assert offending("Co-authored-by: Someone <someone@users.noreply.github.com>") == []
    # A decimal number is not a commit id, and this is the assertion the whole-tree walk
    # bought: `uv.lock` writes `size = 13936739` fifty-five times, the resolver rewrites it on
    # every lock, and the arm that read it as an id could only ever have been answered by
    # exempting a file from the gate. Eight digits, ten digits, and the same run with one hex
    # letter in it, which is an id again.
    assert offending("size = 13936739") == []
    assert offending("bytes: 1234567890") == []
    assert offending("bytes: 123456789a") == ["bare commit id"]


def test_a_token_hit_names_the_offset_of_its_first_window() -> None:
    # The whole-tree gate's only diagnostic. The digest is unreadable by construction, so
    # without the offset a contributor who trips a four-character entry has nothing to go on
    # but brute-forcing windows of their own file. What is asserted is the offset's VALUE and
    # that it indexes the token — a report that named the last window, or 0, or the hit count,
    # would satisfy "an offset is printed" and send the reader to the wrong place.
    #
    # Mutation (declared, `mutations/`'s "the neutrality gate reports the last matching window
    # instead of the first"): drop the `and digest not in first` guard -> the offset becomes 25 and
    # the first assertion reddens on the value. The planted token is a made-up word passed in as a
    # one-entry denylist, for the reason `test_the_gate_discriminates` gives.
    probe = "quernstone"
    planted = ((len(probe), digest_of(probe)),)
    text = "a quernstone and another quernstone"
    assert offending(text, planted) == [f"token {digest_of(probe)} at 2"]
    assert text[2 : 2 + len(probe)] == probe, "the offset does not index the token it names"
    # And the offset is into the LOWER-CASED text, which for an ASCII token is the same index
    # in the original — the equivalence the window scan itself rests on.
    assert offending(text.upper(), planted) == [f"token {digest_of(probe)} at 2"]
    # **Non-ASCII before the token, which is the one input class where the property this test
    # names can fail and where every fixture above cannot.** The scan runs over bytes, an em
    # dash is three of them, and this repository's house style puts two on an ordinary line.
    # Reported as a byte offset the line below said `at 53` for a token at character 49, so a
    # contributor following `CONTRIBUTING.md` sliced ten characters and read 'nstone her'.
    #
    # Mutation (declared, `mutations/`'s "the neutrality gate reports a byte offset into a file of
    # characters"): the conversion is dropped -> this reddens on 53 != 49.
    housed = "the gate — the one that walks the tree — refuses quernstone here"
    where = housed.index(probe)
    assert offending(housed, planted) == [f"token {digest_of(probe)} at {where}"]
    assert housed[where : where + len(probe)] == probe, "the offset does not index the token"
    # A shape hit keeps its bare name: there is no window to point at, and the arm is readable
    # in `SHAPES`.
    assert offending("fixed in 1b279648") == ["bare commit id"]


def test_the_mutation_declarations_carry_no_source_repository_string() -> None:
    # Every file in `mutations/` is walked whole under the public table by the parametrised test
    # below, like every other tracked document. This is the stricter half the two area-scoped gates
    # each carried for their own entries: a mutation quotes a line of the file it names, so the
    # entry is held to *that file's* table. Scoping it by the named file rather than by a
    # hand-kept list of path prefixes is what one gate can do that two could not — neither
    # copy could see the other's area, and every area added since was nobody's.
    entries = declared()
    assert len(entries) >= 200, len(entries)
    for entry in entries:
        quoted = "\n".join((entry.name, relative(entry.file), entry.before, entry.after))
        assert offending(quoted, table_for(entry.file)) == [], entry.name


def test_the_exemption_is_exactly_the_presets_default_paths() -> None:
    # Reddens if the preset stops shipping a default path (the exemption shrinks and a public
    # document that names it reddens too), or if someone rewrites `PUBLIC_FORBIDDEN` by hand.
    exempt = set(FORBIDDEN) - set(PUBLIC_FORBIDDEN)
    assert len(exempt) == PRESET_PATHS_IN_TABLE
    # `exempt <= set(_preset_paths())` used to stand here and was dropped: `PUBLIC_FORBIDDEN`
    # is *defined* as that difference, so the subset held for any derivation and reddened for
    # none. The size is the claim with teeth — it is the one a hand-written table breaks.
    # The full table's size is pinned by `test_the_denylist_is_stored_as_digests`; the source
    # walk still refuses it, which `test_the_public_table_still_discriminates` shows.


def test_the_public_table_still_discriminates() -> None:
    # A preset path is allowed by the public table and refused by the full one; a planted
    # token is refused by both; the dotted harness directory is not a vendor branch.
    from stayfixed.presets import load_preset

    defaults = load_preset("recommended")["defaults"]["paths"].values()
    exempt_value = next(
        value for value in defaults if (len(value), digest_of(value)) in set(FORBIDDEN)
    )
    assert offending(exempt_value, PUBLIC_FORBIDDEN) == []
    assert offending(exempt_value) != []
    # Over every default, not over `next(iter(...))`: which value that picked depended on TOML
    # key order, and it landed on one in neither table, where the assertion held for any
    # derivation at all. Over the whole set, `PUBLIC_FORBIDDEN = FORBIDDEN` reddens it.
    assert all(offending(value, PUBLIC_FORBIDDEN) == [] for value in defaults)
    probe = "quernstone"
    planted = ((len(probe), digest_of(probe)),)
    assert offending("see quernstone", planted) == [f"token {digest_of(probe)} at 4"]
    assert offending("edit .claude/settings.json and .codex/hooks.json") == []
    assert offending("~/.claude/settings.json") == []
    # The dot in the lookbehind, which the dash requirement does not make redundant: those two
    # files are cleared by having no dash in the segment after the slash, but a *dashed* name
    # directly under a dotted harness directory would read as a branch without it.
    assert offending("the .codex/hook-config.toml file") == []
    assert offending("see https://example.test/codex/plugins/build") == []
    # And the URL blanking, which is likewise the only thing standing between the gate and a
    # documentation URL whose path segment happens to be dashed — the commonest shape there is.
    assert offending("see https://example.test/codex/quick-start") == []
    # A remote name inside a URL path is still a path segment, and a remote name on its own is
    # not a branch.
    assert offending("see https://example.test/origin/codex/plugins/build") == []
    assert offending("push to origin/main and upstream/dev") == []
    # The slashed prose pair. This project's own one-line pitch names the two harnesses that
    # way, so the pair is the natural phrasing in every document this table walks; an arm that
    # forbade it would be a trap laid for the next writer rather than a gate.
    assert offending("the Claude/Codex split") == []
    assert offending("claude/codex parity") == []
    assert offending("a claude/agents directory") == []
    # The positive case — a bare vendor-prefixed branch name — is `test_the_gate_discriminates`'s
    # existing assertion, which this change must leave green; it is not repeated here because
    # this plan is walked by the gate and would trip on its own example.


# This file is the one the walk does not read, and the exclusion is `!= THIS` rather than a name
# so a rename cannot quietly drop a different file. It carries no denylist token — the table is
# digests — but the three shape arms are proven by fixtures that are personal-address-shaped,
# commit-id-shaped and branch-shaped **by construction**, which is the same reason the two gates
# this replaces each skipped themselves. The pre-commit sweep reads the raw diff and so reports
# those fixtures; a shape hit on a line of this module is the gate quoting itself, and the stop
# condition is a `token` hit.
@pytest.mark.parametrize(
    "path",
    [p for p in tracked_files() if p != THIS],
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_no_tracked_file_carries_a_project_identifying_string(path: Path) -> None:
    text = _text(path)
    if text is None:
        pytest.skip("binary")
    assert offending(text, table_for(path)) == [], path
