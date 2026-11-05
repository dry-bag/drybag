"""One traversal for three readers, and the two readers that use it.

stayfixed:ledger:fixtures — the identifiers below are sample data, not claims about a ledger.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from stayfixed import fsops
from stayfixed.config.loader import load
from stayfixed.config.schema import Config
from stayfixed.gitenv import git_run
from stayfixed.ledger.register import bug_register
from stayfixed.ledger.scan import (
    FIXTURE_MARKER,
    FIXTURE_MARKER_WINDOW,
    citation_roots,
    citations,
    code_mentions,
    entry_citations,
    mention_roots,
    scannable,
)
from tests.gitfixture import git, plant_path

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"
"""

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def project(tmp_path: Path, extra: str = "") -> tuple[Path, Config]:
    root = tmp_path / "widget"
    root.mkdir()
    (root / "stayfixed.toml").write_text(CONFIG + extra, encoding="utf-8")
    for name in ("src", "tests", "scripts", "docs"):
        (root / name).mkdir()
    return root, load(root, machine=tmp_path / "m.toml")


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_mention_roots_are_the_top_level_plus_the_contained_code_roots(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    assert mention_roots(root, config) == (".", "src", "tests", "scripts")


def test_citation_roots_add_the_first_component_of_every_document_path(tmp_path: Path) -> None:
    # The defaults put every document under `docs/`; a citation names a path, so the reader
    # that reports a dangling one may read documents, while the bare-mention reader may not
    # (plan documents spell invented identifiers as worked examples).
    root, config = project(tmp_path)
    assert citation_roots(root, config) == (".", "src", "tests", "scripts", "docs")


def test_a_code_root_outside_the_project_is_skipped_not_scanned(tmp_path: Path) -> None:
    root, config = project(tmp_path, '\n[ledger]\ncode_roots = ["src", "../elsewhere"]\n')
    (tmp_path / "elsewhere").mkdir()
    assert mention_roots(root, config) == (".", "src")


def test_the_top_level_files_are_scanned(tmp_path: Path) -> None:
    # `pyproject.toml` and `.gitignore` each carried a live identifier once, invisible to a scan
    # that only knew directories.
    root, config = project(tmp_path)
    write(root, "pyproject.toml", "# see BR-404\n")
    assert list(code_mentions(root, config, bug_register(config))) == ["BR-404"]


@pytest.mark.parametrize(
    "location",
    [
        "node_modules/pkg/index.js",
        "src/build/generated.py",
        "tests/dist/bundle.js",
        "scripts/__pycache__/x.py",
    ],
)
def test_the_walk_enters_no_vendored_or_generated_directory(tmp_path: Path, location: str) -> None:
    root, config = project(tmp_path)
    write(root, location, "// see BR-404\n")
    assert code_mentions(root, config, bug_register(config)) == {}


def test_a_directory_name_is_excluded_only_inside_the_repository(tmp_path: Path) -> None:
    # A repository kept under a directory called `build` is an ordinary thing.
    root = tmp_path / "build"
    root.mkdir()
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    (root / "src").mkdir()
    config = load(root, machine=tmp_path / "m.toml")
    write(root, "src/a.py", "# BR-404\n")
    assert list(code_mentions(root, config, bug_register(config))) == ["BR-404"]


def test_a_binary_suffix_and_a_symlink_are_skipped_whole(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    (root / "src" / "img.png").write_bytes(b"BR-404")
    outside = tmp_path / "outside.py"
    outside.write_text("# BR-405\n", encoding="utf-8")
    os.symlink(outside, root / "src" / "linked.py")
    assert code_mentions(root, config, bug_register(config)) == {}


def test_a_fixture_holder_is_excluded_from_the_scan(tmp_path: Path) -> None:
    # The marker replaces the source's hard-coded exclusion list. Mutation: make
    # `is_fixture_holder` return False — this reddens.
    root, config = project(tmp_path)
    write(root, "tests/test_x.py", f'"""{FIXTURE_MARKER} — sample data"""\nENTRY = "BR-404"\n')
    write(root, "tests/test_y.py", "ENTRY = 'BR-405'\n")
    assert list(code_mentions(root, config, bug_register(config))) == ["BR-405"]


def test_the_marker_is_read_only_from_the_head_of_a_file(tmp_path: Path) -> None:
    # A marker buried past the window is prose about the marker, not the marker.
    root, config = project(tmp_path)
    write(
        root,
        "tests/test_x.py",
        "x = 1\n" * (FIXTURE_MARKER_WINDOW // 6 + 1) + f"# {FIXTURE_MARKER}\nENTRY = 'BR-404'\n",
    )
    assert list(code_mentions(root, config, bug_register(config))) == ["BR-404"]


def test_an_undecodable_file_is_not_text_and_an_unreadable_one_carries_its_error(
    tmp_path: Path,
) -> None:
    root, _config = project(tmp_path)
    (root / "src" / "latin.py").write_bytes(b"# \xff BR-404\n")
    write(root, "src/ok.py", "# BR-405\n")
    items = {item.relative.as_posix(): item for item in scannable(root, ("src",))}
    assert items["src/latin.py"].text is None and items["src/latin.py"].error is None
    assert items["src/ok.py"].text == "# BR-405\n"
    if os.geteuid() == 0:
        pytest.skip("root reads everything")
    (root / "src" / "ok.py").chmod(0)
    try:
        items = {item.relative.as_posix(): item for item in scannable(root, ("src",))}
        assert items["src/ok.py"].text is None and items["src/ok.py"].error
    finally:
        (root / "src" / "ok.py").chmod(0o644)


def test_a_file_past_the_read_cap_is_one_the_scan_could_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A scanned file is one a clone commits, so it is read to the read cap, as every reader of a
    # committed file reads one, and a file past it carries the reader's error rather than being
    # read to its end. The cap is lowered so the file is small. Mutation (oracle): `mutations/`'s
    # "the reference scan reads a file with no bound" -> the file is read as text.
    root, _config = project(tmp_path)
    limit = 4 * 1024
    write(root, "src/long.py", "# BR-404\n" + "#" * limit + "\n")
    monkeypatch.setattr(fsops, "REGULAR_READ_LIMIT", limit)
    items = {item.relative.as_posix(): item for item in scannable(root, ("src",))}
    assert items["src/long.py"].text is None
    assert items["src/long.py"].error == "larger than this reader reads"


def test_a_binary_past_the_read_cap_is_skipped_as_a_binary_is_and_text_past_it_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Past the cap the file is not read to its end, so whether it is text is decided from what
    # was read: bytes that are not UTF-8 make it a binary, skipped in silence as one under the cap
    # is, and a model or a database in the tree no longer reads as a file the scan could not read,
    # which no re-run clears. Text past the cap keeps the reader's error, and so does text whose
    # last character in the window that decides is cut in two by it. The cap is lowered so the
    # files are small. Mutations (declared): a file past the cap is an error whatever it holds ->
    # the binary reddens; the window is decoded as if it were the whole file -> the cut text
    # reddens.
    from stayfixed.ledger.scan import TEXT_WINDOW

    root, _config = project(tmp_path)
    limit = 4 * 1024
    (root / "src" / "model.onnx").write_bytes(b"\xff\xfe BR-404\n" + bytes(limit))
    write(root, "src/cut.md", "BR-404 " + "\u00e9" * TEXT_WINDOW)
    # Seven bytes, then two per character: the window's last byte is the first half of one.
    assert len(b"BR-404 ") % 2 == 1 and TEXT_WINDOW % 2 == 0
    monkeypatch.setattr(fsops, "REGULAR_READ_LIMIT", limit)
    items = {item.relative.as_posix(): item for item in scannable(root, ("src",))}
    assert (items["src/model.onnx"].text, items["src/model.onnx"].error) == (None, None)
    assert items["src/cut.md"].text is None
    assert items["src/cut.md"].error == "larger than this reader reads"


@needs_git
def test_git_enumerates_the_candidates_and_an_ignored_file_is_not_one(tmp_path: Path) -> None:
    # The question is "what is in the commit under review"; a walk answers a different one.
    # Mutation: make `_committed_files` return None — this reddens.
    root, config = project(tmp_path)
    git(root, "init", "-q")
    write(root, ".gitignore", "src/generated/\n")
    write(root, "src/generated/out.py", "# BR-404\n")
    write(root, "src/a.py", "# BR-405\n")
    assert list(code_mentions(root, config, bug_register(config))) == ["BR-405"]


@needs_git
def test_a_listing_git_gave_no_answer_for_falls_back_to_the_walk_and_not_to_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `git_run`'s `(-1, "")` — git could not be run or ran past its bound — read as an empty
    # listing scanned no file at all and reported every reference as absent: the guard that
    # says OK because it looked at nothing, which this module's walk fallback exists to
    # prevent. Only the listing is diverted, so the top-level probe still answers and the case
    # reaches the listing's own arm. Mutation (declared): answer the failed listing with the
    # empty string again — the scan finds nothing and this reddens.
    from stayfixed.ledger import scan as module

    root, config = project(tmp_path)
    git(root, "init", "-q")
    write(root, "src/a.py", "# BR-405\n")
    real = git_run

    def unanswered(where: Path, *args: str, **kwargs: Any) -> tuple[int, str]:
        return (-1, "") if args[0] == "ls-files" else real(where, *args, **kwargs)

    monkeypatch.setattr(module, "git_run", unanswered)
    assert list(code_mentions(root, config, bug_register(config))) == ["BR-405"]


@needs_git
def test_a_listed_name_that_is_not_utf_8_hides_no_other_file(tmp_path: Path) -> None:
    # `ls-files -z` prints a tracked name raw; decoded losslessly it is one more name in the
    # listing, and the files beside it are still scanned. The planted name has no file on this
    # disk (APFS refuses one), so this also holds that a listed name the scan cannot open costs
    # that name and not the scan.
    root, config = project(tmp_path)
    git(root, "init", "-q")
    write(root, "src/a.py", "# BR-405\n")
    plant_path(root, b"src/caf\xe9.py")
    assert list(code_mentions(root, config, bug_register(config))) == ["BR-405"]


@needs_git
def test_a_root_that_is_not_the_top_of_a_checkout_falls_back_to_the_walk(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    root, config = project(tmp_path)
    write(root, "src/a.py", "# BR-404\n")
    assert list(code_mentions(root, config, bug_register(config))) == ["BR-404"]


def test_a_citation_of_an_entry_file_is_resolved_two_ways(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    write(root, "src/a.py", "# see docs/bugs/BR-404.md\n")
    write(root, "docs/roadmap.md", "see [x](bugs/BR-405.md)\n")
    write(root, "docs/deeper/note.md", "see [x](../bugs/BR-406.md)\n")
    # resolves to docs/deeper/bugs/: not a citation
    write(root, "docs/deeper/other.md", "see [x](bugs/BR-407.md)\n")
    found = entry_citations(root, config, bug_register(config))
    assert set(found) == {"BR-404", "BR-405", "BR-406"}
    assert found["BR-404"] == [(PurePosixPath("src/a.py"), 1)]


def test_an_absolute_path_that_merely_contains_the_entry_path_is_not_a_citation(
    tmp_path: Path,
) -> None:
    root, config = project(tmp_path)
    write(root, "src/a.py", "# /tmp/x/docs/bugs/BR-404.md\n")
    assert entry_citations(root, config, bug_register(config)) == {}


# Files the citation scan read in time quadratic in their length, each with what it must find: a
# run of `../` before a citation of its own, whose every split between the pattern's two repeats
# was tried, 0.7 s over 8,000; and a file of citations, each of whose lines was counted from the
# file's start, 36 s over 160,000. Each is sized so that the old reading takes over a minute and a
# half and the scan a second or less.
LONG_CITERS = {
    "a run of parent steps": ((" " + "../" * (1 << 17) + " docs/bugs/BR-001.md\n", 1), [1, 1, 1]),
    "many citations": (("see docs/bugs/BR-001.md\n", 1 << 18), [1 << 18, 1, 1 << 18]),
}
# The child's bound: a fifth of the old reading's time over either file on a laptop, and forty
# times the scan's there, start-up included.
_LONG_CITER_SECONDS = 20


@pytest.mark.parametrize("shape", sorted(LONG_CITERS))
def test_a_long_file_s_citations_are_read_in_time_linear_in_its_length(
    tmp_path: Path, shape: str
) -> None:
    # In a child under a timeout, so a regression fails this case rather than holding a worker.
    # The answer is how many lines cite the entry, and the first and the last of them. Mutations
    # (oracle): `mutations/`'s "a citation is read for at every split of a run of parent steps" ->
    # `a run of parent steps`; "a citation's line is counted from the file's start" -> `many
    # citations`.
    root, _ = project(tmp_path)
    (unit, count), expected = LONG_CITERS[shape]
    write(root, "src/a.py", unit * count)
    probe = (
        "import sys\n"
        "from pathlib import Path\n"
        "from stayfixed.config.loader import load\n"
        "from stayfixed.ledger.register import bug_register\n"
        "from stayfixed.ledger.scan import entry_citations\n"
        "root, machine = map(Path, sys.argv[1:])\n"
        "config = load(root, machine=machine)\n"
        "found = entry_citations(root, config, bug_register(config))\n"
        "lines = [line for _, line in found['BR-001']]\n"
        "print([len(lines), lines[0], lines[-1]])\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, str(root), str(tmp_path / "m.toml")],
            capture_output=True,
            text=True,
            timeout=_LONG_CITER_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the citation scan ran past {_LONG_CITER_SECONDS} s on one file")
    assert done.stdout == f"{expected}\n", done.stderr


# A citation behind a million segments, which the pattern read with 140 MiB more of match state when
# `re` kept a record for each segment it might give back, and with none when it keeps none. The
# most the child may grow its peak resident size by: a few copies of the two-mebibyte line.
_LONG_CITATION_SEGMENTS = 1 << 20
_LONG_CITATION_BYTES = 32 << 20


def test_a_citation_behind_many_segments_is_read_in_memory_linear_in_its_length(
    tmp_path: Path,
) -> None:
    # The child measures its own peak resident size before and after (`ru_maxrss`, bytes on macOS
    # and KiB on Linux), under a timeout. Mutation (oracle): `mutations/`'s "a citation's segments
    # are read by a pattern that gives them back" -> this reddens.
    root, _ = project(tmp_path)
    probe = (
        "import resource, sys\n"
        "from pathlib import Path\n"
        "from stayfixed.config.loader import load\n"
        "from stayfixed.ledger.register import bug_register\n"
        "from stayfixed.ledger.scan import citations\n"
        "root, machine, count = sys.argv[1:]\n"
        "register = bug_register(load(Path(root), machine=Path(machine)))\n"
        "text = ' ' + 'a/' * int(count) + 'docs/bugs/BR-001.md'\n"
        "scale = 1 if sys.platform == 'darwin' else 1024\n"
        "before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "found = [identifier for _, _, identifier in citations(text, register)]\n"
        "grown = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) * scale\n"
        "print(found == ['BR-001'], grown)\n"
    )
    arguments = [str(root), str(tmp_path / "m.toml"), str(_LONG_CITATION_SEGMENTS)]
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, *arguments],
            capture_output=True,
            text=True,
            timeout=_LONG_CITER_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"reading one long citation ran past {_LONG_CITER_SECONDS} s")
    answer, grown = done.stdout.split()
    assert answer == "True", done.stderr
    assert int(grown) < _LONG_CITATION_BYTES, f"the scan grew its peak by {int(grown) >> 20} MiB"


def test_the_index_and_the_entries_are_not_read_as_citers(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    write(root, "docs/bug-reports.md", "| [BR-404](bugs/BR-404.md) |\n")
    write(root, "docs/bugs/BR-001.md", "see [BR-404](BR-404.md)\n")
    assert entry_citations(root, config, bug_register(config)) == {}


def test_the_citation_reader_follows_the_configured_ledger_directory(tmp_path: Path) -> None:
    _root, config = project(tmp_path, '\n[paths]\nbugs = "docs/defects"\n')
    assert list(citations("docs/defects/BR-001.md", bug_register(config)))
    assert not list(citations("docs/bugs/BR-001.md", bug_register(config)))
