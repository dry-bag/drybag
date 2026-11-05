"""The `bugs` group through the real frame: one line out, three exit codes, `--json`.

stayfixed:ledger:fixtures — the identifiers below are sample data, not claims about a ledger.
"""

from __future__ import annotations

import errno
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.findings import Finding
from stayfixed.printed import UNPRINTABLE
from tests.cli import cli
from tests.crafted import CRAFTED, assert_never_raw
from tests.gitfixture import git, needs_git

# What the platform calls a permission refusal, as `OSError.strerror` words it.
DENIED = os.strerror(errno.EACCES)

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
"""


def invoke(argv: list[str]) -> int:
    return run(argv, parser=build_parser(discover_registrars()))


def project(tmp_path: Path) -> tuple[Path, list[str]]:
    root = tmp_path / "widget"
    root.mkdir()
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    for name in ("src", "docs", "docs/bugs"):
        (root / name).mkdir()
    return root, ["--root", str(root), "--machine", str(tmp_path / "m.toml")]


def test_new_files_an_entry_and_prints_its_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, common = project(tmp_path)
    argv = ["bugs", "new", "a title", "--severity", "low", "--area", "an area", "--no-fetch"]
    assert invoke([*argv, *common]) == 0
    out = capsys.readouterr().out
    assert out == "filed docs/bugs/BR-001.md\n"
    assert (root / "docs" / "bug-reports.md").is_file()


def test_new_json_carries_the_identifier_and_the_fetch_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, common = project(tmp_path)
    argv = ["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", "--json"]
    assert invoke([*argv, *common]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "BR-001"
    assert data["path"] == "docs/bugs/BR-001.md"
    assert data["warning"] is None


def test_new_with_a_bad_severity_is_refused_by_argparse(tmp_path: Path) -> None:
    _root, common = project(tmp_path)
    with pytest.raises(SystemExit):
        invoke(["bugs", "new", "t", "--severity", "huge", "--area", "a", *common])


def test_check_is_inert_on_a_project_with_no_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, common = project(tmp_path)
    (root / "docs" / "bugs").rmdir()
    assert invoke(["bugs", "check", *common]) == 0
    assert "nothing to check" in capsys.readouterr().out


def test_check_reports_a_citation_when_there_is_no_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The gate reports it, so the command its remedy names must report it too, and not
    # answer "nothing to check".
    root, common = project(tmp_path)
    (root / "docs" / "bugs").rmdir()
    (root / "src" / "a.py").write_text("# see docs/bugs/BR-404.md\n", encoding="utf-8")
    assert invoke(["bugs", "check", *common]) == 1
    assert capsys.readouterr().out.startswith(
        "FAIL: 2 ledger problem(s): src/a.py:1 [dangling-mention], src/a.py:1 [dangling-citation]"
    )


@needs_git
def test_check_with_a_base_answers_for_a_ledger_the_base_carries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The gate's command is `bugs check --base <base>`, so the command its remedy names reports
    # the deleted ledger as the gate does; without `--base` the tree alone is judged and is
    # inert. Mutation (oracle): `mutations/`'s "bugs check drops its --base" -> exit 0, nothing to
    # check.
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD").strip()
    git(root, "rm", "-rq", "docs/bugs", "docs/bug-reports.md")
    capsys.readouterr()
    assert invoke(["bugs", "check", *common]) == 0
    assert "nothing to check" in capsys.readouterr().out
    assert invoke(["bugs", "check", "--base", base, *common]) == 1
    assert capsys.readouterr().out == "FAIL: 1 ledger problem(s): docs/bugs [ledger-removed]\n"


def based(tmp_path: Path, under: str, paths: str = "") -> tuple[Path, list[str]]:
    """A repository whose `main` holds a project under `under` with BR-001 and BR-002, checked
    out on a branch `change`; the project and the arguments that name `main` as the base."""
    repository = tmp_path / "repository"
    root = repository / under
    root.mkdir(parents=True)
    (root / "stayfixed.toml").write_text(CONFIG + paths, encoding="utf-8")
    common = ["--root", str(root), "--machine", str(tmp_path / "m.toml")]
    for title in ("a", "b"):
        invoke(["bugs", "new", title, "--severity", "low", "--area", "a", "--no-fetch", *common])
    git(repository, "init", "-q", "-b", "main")
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", "base")
    git(repository, "checkout", "-q", "-b", "change")
    return root, ["bugs", "check", "--base", "main", *common]


# Each takes the project at `app` and answers the root to pass and where the project now is.
def _moved_behind_a_link(root: Path) -> tuple[Path, Path]:
    os.rename(root, root.parent / "elsewhere")
    os.symlink("elsewhere", root)
    return root, root.parent / "elsewhere"


def _linked_back_to_the_top(root: Path) -> tuple[Path, Path]:
    for name in ("stayfixed.toml", "docs"):
        os.rename(root / name, root.parent / name)
    root.rmdir()
    os.symlink(".", root)
    return root, root.parent


def _reached_from_outside(root: Path) -> tuple[Path, Path]:
    outside = root.parent.parent / "outside"
    os.symlink(root, outside)
    return outside, root


@needs_git
@pytest.mark.parametrize(
    "link",
    [_moved_behind_a_link, _linked_back_to_the_top, _reached_from_outside],
    ids=["moved-behind-a-link", "linked-back-to-the-top", "reached-from-outside"],
)
def test_a_root_reached_through_a_link_is_refused_against_its_base(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], link: Callable[[Path], tuple[Path, Path]]
) -> None:
    # CI names the root; the change can make a component of it a link. Resolved, the root is
    # wherever the link points, where the base keeps no stayfixed.toml, so the change read as the
    # bootstrap and deleted BR-002 with exit 0. Mutations (oracle): `mutations/`'s "bugs check
    # --base judges a root reached through a symlink at the link's target" -> moved-behind-a-link
    # and linked-back-to-the-top pass; "a project root reached through a symlink reads the base
    # at a path it never had" -> the same; "the ancestor that resolves to the top is looked for
    # from the nearest end" -> linked-back-to-the-top passes; "a root no ancestor of which
    # resolves to the top is read as if one did" -> reached-from-outside is an internal error.
    root, argv = based(tmp_path, "app")
    spelled, moved = link(root)
    (moved / "docs" / "bugs" / "BR-002.md").unlink()
    git(tmp_path / "repository", "add", "-A")
    git(tmp_path / "repository", "commit", "-q", "-m", "change")
    capsys.readouterr()
    argv[argv.index("--root") + 1] = str(spelled)
    assert invoke(argv) == 2
    assert capsys.readouterr().err.startswith(
        "stayfixed: refused: the project root is reached through a symlink"
    )


@needs_git
def test_a_ledger_the_base_placed_below_a_directory_named_like_pathspec_magic_is_read_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The base's stayfixed.toml is read at the project's path from the repository's top, taken
    # literally: read at the top, relative to the project, or as the pathspec `:/` ("from the
    # top"), it is missing, the change is the bootstrap, and moving the ledger by `[paths]` while
    # deleting BR-002 passed. Mutations (oracle): `mutations/`'s "a project in a subdirectory
    # reads the base's copy at the repository's top", "the base's copy is listed relative to the
    # project root rather than the repository's top" and "a project under a directory named like
    # pathspec magic reads no copy on the base" -> no entry-removed.
    root, argv = based(tmp_path, ":", paths='\n[paths]\nbugs = "records/bugs"\n')
    text = (root / "stayfixed.toml").read_text(encoding="utf-8")
    (root / "stayfixed.toml").write_text(text.replace("records/bugs", "kept"), encoding="utf-8")
    (root / "kept").mkdir()
    os.rename(root / "records" / "bugs" / "BR-001.md", root / "kept" / "BR-001.md")
    (root / "records" / "bugs" / "BR-002.md").unlink()
    capsys.readouterr()
    assert invoke(argv) == 1
    assert "kept/BR-002.md [entry-removed]" in capsys.readouterr().out


@needs_git
@pytest.mark.parametrize(
    ("dot_git", "said"),
    [
        (None, "the project root is not inside a git repository"),
        ("gitdir: gone\n", "git gave no answer about the repository the project root is in"),
    ],
    ids=["no-repository", "git-directory-gone"],
)
def test_a_root_git_answers_nothing_for_fails_against_its_base(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], dot_git: str | None, said: str
) -> None:
    # git refuses a worktree whose git directory is gone as it refuses a directory in no
    # repository, so which one it was is read off the disk, and neither is judged as if git had
    # answered. Mutations (oracle): `mutations/`'s "a root outside any repository is judged as if
    # git had answered" -> both are a refusal naming a symlink; "a repository git will not answer
    # for is called no repository" -> git-directory-gone sends the owner looking for a repository.
    root, common = project(tmp_path)
    if dot_git is not None:
        (root / ".git").write_text(dot_git, encoding="utf-8")
    assert invoke(["bugs", "check", "--base", "main", *common]) == 1
    assert capsys.readouterr().err.startswith(f"stayfixed: failed: {said}")


def test_check_reports_problems_on_one_line_and_lists_them_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    (root / "src" / "a.py").write_text("# BR-404\n# BR-405\n", encoding="utf-8")
    assert invoke(["bugs", "check", *common]) == 1
    line = capsys.readouterr().out
    assert line.startswith(
        "FAIL: 2 ledger problem(s): src/a.py:1 [dangling-mention], src/a.py:2 [dangling-mention]"
    )
    # One line out, as every command's human output is: the details that would have made it
    # many are in `--json`.
    assert line.count("\n") == 1
    assert invoke(["bugs", "check", "--json", *common]) == 1
    data = json.loads(capsys.readouterr().out)
    # `findings` and not `problems`: one name across every command that returns a list of
    # `Finding`. Mutation: spell the key `problems` in `run_bugs_check` — this reddens.
    assert [p["rule"] for p in data["findings"]] == ["dangling-mention", "dangling-mention"]
    assert "BR-404" in data["findings"][0]["detail"]


def test_check_never_prints_a_crafted_entry_file_name_raw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The entry's file name is the repository's, and `bugs check` runs in CI: a name holding a
    # line break and `::error::` forged a workflow command on the runner, and an escape sequence
    # reached the terminal. The name still reaches `--json`, which escapes it. Mutation: print
    # `self.path` in `Finding.labelled` — this reddens.
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    entry = next((root / "docs" / "bugs").glob("BR-*.md"))
    crafted = f"BR-001-{CRAFTED}.md"
    entry.rename(entry.with_name(crafted))
    assert invoke(["bugs", "check", *common]) == 1
    captured = capsys.readouterr()
    assert f"{UNPRINTABLE} [id-mismatch]" in captured.out
    assert_never_raw(captured.out, captured.err)
    assert captured.out.count("\n") == 1
    assert invoke(["bugs", "check", "--json", *common]) == 1
    paths = [p["path"] for p in json.loads(capsys.readouterr().out)["findings"]]
    assert f"docs/bugs/{crafted}" in paths


@pytest.mark.parametrize(
    ("body", "refusal"),
    [
        (b"no frontmatter\n", "no `---` frontmatter block"),
        (b"---\nbogus: x\n---\n", "unknown frontmatter key `bogus`"),
        (b"caf\xe9\n", "is not valid UTF-8"),
    ],
    ids=["no-frontmatter", "unknown-key", "not-utf8"],
)
def test_index_names_a_crafted_entry_it_cannot_read_escaped_never_raw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], body: bytes, refusal: str
) -> None:
    # `bugs index` refuses an entry it cannot read or parse and names the file, whose name the
    # repository chose; one case per kind of refusal, since each is its own f-string. The name
    # arrives escaped and whole. Mutation: return the path unquoted from `entries._where`, or
    # format `where` raw in the UTF-8 or unknown-key refusal — each reddens a case.
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    name = f"BR-002-{CRAFTED}.md"
    (root / "docs" / "bugs" / name).write_bytes(body)
    assert invoke(["bugs", "index", *common]) == 1
    captured = capsys.readouterr()
    assert refusal in captured.err
    assert_never_raw(captured.out, captured.err)
    assert repr(f"docs/bugs/{name}") in captured.err


def test_check_passes_a_clean_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    assert invoke(["bugs", "check", *common]) == 0
    assert capsys.readouterr().out == (
        "OK: bug ledger entries, index freshness, and identifier references\n"
    )


def test_index_check_reports_staleness_and_index_repairs_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    (root / "docs" / "bug-reports.md").write_text("", encoding="utf-8")
    assert invoke(["bugs", "index", "--check", *common]) == 1
    assert "is stale; run: stayfixed bugs index" in capsys.readouterr().out
    assert invoke(["bugs", "index", *common]) == 0
    assert capsys.readouterr().out == "rewrote docs/bug-reports.md (1 entries)\n"
    assert invoke(["bugs", "index", "--check", *common]) == 0


def test_index_refuses_over_foreign_content_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, common = project(tmp_path)
    (root / "docs" / "bug-reports.md").write_text(
        "# Bug reports\n\n## BR-009 — hand-written\n", encoding="utf-8"
    )
    assert invoke(["bugs", "index", *common]) == 2
    assert "refused" in capsys.readouterr().err


def test_renumber_reports_its_endpoints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    assert invoke(["bugs", "renumber", "BR-001", "BR-009", *common]) == 0
    assert capsys.readouterr().out == (
        "BR-001 -> BR-009; a void pointer remains at docs/bugs/BR-001.md\n"
    )


def test_a_renumber_run_again_after_it_finished_says_so_and_rewrites_no_later_mention(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Once a move has finished, a mention of the old number is legitimate — the void pointer is
    # there so that it resolves — and a re-run from shell history swept it onto the new number,
    # exit 0: "BR-009 was renumbered to BR-009". The index is the move's last write, so a fresh
    # one says the move finished, and the re-run changes nothing and says so. Mutation:
    # `mutations/`'s "a renumber that finished sweeps again when run again".
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    assert invoke(["bugs", "renumber", "BR-001", "BR-009", *common]) == 0
    history = root / "docs" / "history.md"
    history.write_text("BR-001 was renumbered to BR-009 to resolve a collision.\n", "utf-8")
    capsys.readouterr()
    assert invoke(["bugs", "renumber", "BR-001", "BR-009", "--json", *common]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"] == "BR-001 was already moved to BR-009; nothing to do"
    assert data["moved"] is False
    assert history.read_text(encoding="utf-8") == (
        "BR-001 was renumbered to BR-009 to resolve a collision.\n"
    )


# Each write of its own a move can fail at: the sealed directory, and the file its message names.
UNWRITABLE = {
    "target": ("docs/bugs", "docs/bugs/BR-009.md"),
    "pointer": ("docs/bugs", "docs/bugs/BR-001.md"),
    "index": ("docs", "docs/bug-reports.md"),
}


@pytest.mark.parametrize(("sealed", "named"), UNWRITABLE.values(), ids=UNWRITABLE.keys())
def test_a_renumber_whose_own_write_fails_names_the_re_run_that_finishes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sealed: str, named: str
) -> None:
    # A failure at the index, the move's last write, leaves both endpoints and the sweep on disk;
    # it ended in `internal error: PermissionError`, exit 2, which said nothing of the re-run that
    # now finishes the move. Each of the move's own writes fails as the move's failure, exit 1,
    # naming that re-run and the file by its root-relative path. `pointer` is the move killed
    # after its first write, re-run with the old file unwritable. Mutations: `mutations/`'s "a
    # renumber's failed target write escapes as an internal error", and the same of its pointer
    # and its index.
    if os.geteuid() == 0:
        pytest.skip("root writes everywhere")
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    if sealed == "docs/bugs" and named.endswith("BR-001.md"):
        moved = (root / "docs" / "bugs" / "BR-001.md").read_text(encoding="utf-8")
        target = root / "docs" / "bugs" / "BR-009.md"
        target.write_text(moved.replace("id: BR-001", "id: BR-009", 1), encoding="utf-8")
    directory = root / sealed
    directory.chmod(0o555)
    try:
        assert invoke(["bugs", "renumber", "BR-001", "BR-009", *common]) == 1
    finally:
        directory.chmod(0o755)
    err = capsys.readouterr().err
    assert err == (
        f"stayfixed: failed: the move is not finished: {named} could not be written "
        f"({DENIED}); once it can be, run `stayfixed bugs renumber BR-001 BR-009` again to "
        "finish it\n"
    )
    assert invoke(["bugs", "renumber", "BR-001", "BR-009", *common]) == 0
    assert invoke(["bugs", "check", *common]) == 0


def test_a_filing_whose_index_write_fails_names_the_entry_it_filed_and_bugs_index(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The entry is written before the index, so a failure there left a filed entry behind an
    # `internal error`, exit 2, that said nothing of it; an operator who ran `bugs new` again
    # filed the same bug twice. It is a failure, exit 1, naming the entry it filed and the
    # command that brings the index up to date, which files nothing: after it, one entry and a
    # clean check. Mutation: `mutations/`'s "a filing whose index write fails escapes as an
    # internal error".
    if os.geteuid() == 0:
        pytest.skip("root writes everywhere")
    root, common = project(tmp_path)
    argv = ["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common]
    assert invoke(argv) == 0
    capsys.readouterr()
    docs = root / "docs"
    docs.chmod(0o555)
    try:
        assert invoke(argv) == 1
    finally:
        docs.chmod(0o755)
    assert capsys.readouterr().err == (
        "stayfixed: failed: filed docs/bugs/BR-002.md, but docs/bug-reports.md could not be "
        f"written ({DENIED}); once it can be, run `stayfixed bugs index`, not this command "
        "again, which would file it a second time\n"
    )
    assert invoke(["bugs", "index", *common]) == 0
    assert sorted(p.name for p in (docs / "bugs").iterdir()) == ["BR-001.md", "BR-002.md"]
    assert invoke(["bugs", "check", *common]) == 0


@needs_git
def test_a_filing_whose_index_write_fails_keeps_the_allocators_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The allocator warns when it could not ask what other branches hold, since the number it
    # chose may then be taken there, and a filing that stops at the index is the one whose number
    # the operator acts on next. The failure named the entry and the index and dropped the
    # warning. The checkout here has no `origin`, so the fetch fails. Mutation: `mutations/`'s "a
    # filing whose index write fails drops the allocator's warning".
    if os.geteuid() == 0:
        pytest.skip("root writes everywhere")
    root, common = project(tmp_path)
    git(root, "init", "-q")
    docs = root / "docs"
    docs.chmod(0o555)
    try:
        assert invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", *common]) == 1
    finally:
        docs.chmod(0o755)
    err = capsys.readouterr().err
    assert err.startswith("stayfixed: failed: filed docs/bugs/BR-001.md, but ")
    assert err.endswith(
        "which would file it a second time; git fetch origin failed; identifiers may collide "
        "with branches this checkout has not fetched\n"
    )


def test_an_index_that_cannot_be_written_is_a_failure_naming_the_rerun(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same write, from `bugs index` itself: `internal error`, exit 2, where it is the
    # command's failure, exit 1, with the reason in words. Mutation: `mutations/`'s "an index
    # write that fails escapes as an internal error".
    if os.geteuid() == 0:
        pytest.skip("root writes everywhere")
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    (root / "docs" / "bug-reports.md").unlink()
    capsys.readouterr()
    (root / "docs").chmod(0o555)
    try:
        assert invoke(["bugs", "index", *common]) == 1
    finally:
        (root / "docs").chmod(0o755)
    assert capsys.readouterr().err == (
        f"stayfixed: failed: docs/bug-reports.md could not be written ({DENIED}); once it can "
        "be, run `stayfixed bugs index` again\n"
    )


def test_a_missing_configuration_is_a_failure_not_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = str(tmp_path / "m.toml")
    assert invoke(["bugs", "check", "--root", str(tmp_path), "--machine", machine]) == 1
    assert "failed" in capsys.readouterr().err


def test_index_writes_nothing_when_it_is_already_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `new` has just regenerated it, so the bare `index` has nothing to do and says so on its
    # own line rather than rewriting a file whose bytes would not change.
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    before = (root / "docs" / "bug-reports.md").stat().st_mtime_ns
    assert invoke(["bugs", "index", *common]) == 0
    assert capsys.readouterr().out == "docs/bug-reports.md is current (1 entries)\n"
    assert (root / "docs" / "bug-reports.md").stat().st_mtime_ns == before


@pytest.mark.parametrize(
    ("directory", "named"),
    [("sealed", "src/sealed/a.py"), (CRAFTED, UNPRINTABLE), ("a:b", UNPRINTABLE)],
    ids=["plain", "crafted", "colon"],
)
def test_renumber_fails_naming_a_file_the_sweep_could_not_rewrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], directory: str, named: str
) -> None:
    # Exit 1, not 0: once the void pointer exists a stale mention in that file looks
    # intentional to `bugs check` forever, so the move is reported as incomplete. The file is
    # named, and a name the tree chose outside the path grammar is withheld on the line and kept
    # in `--json`. Mutation: list the unswept names unbounded in `run_bugs_renumber` — the
    # crafted case reddens. The name on the line is the file the sweep reported, not a prefix of
    # its message: rebuilt by splitting `"path: reason"` at the first colon, `src/a:b/a.py`
    # printed as `src/a`, a directory the operator would look in for nothing. Mutation: split the
    # message again in `run_bugs_renumber` — the colon case reddens.
    if os.geteuid() == 0:
        pytest.skip("root writes everywhere")
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    sealed = root / "src" / directory
    sealed.mkdir()
    (sealed / "a.py").write_text("# BR-001\n", encoding="utf-8")
    sealed.chmod(0o555)
    try:
        assert invoke(["bugs", "renumber", "BR-001", "BR-009", "--json", *common]) == 1
    finally:
        sealed.chmod(0o755)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    line = data["summary"]
    assert line.startswith("FAIL: BR-001 moved to BR-009, but 1 file(s) still reference BR-001")
    assert f"({named})" in line and "docs/bugs/BR-001.md" in line
    assert_never_raw(line, captured.err)
    assert "\n" not in line
    # One object per file, the path whole whatever it holds: a `"path: reason"` string cannot be
    # split back, since a path may itself hold `": "`. Mutation: carry `"path: reason"` strings
    # under `unswept` in `run_bugs_renumber` — every case reddens.
    assert data["unswept"] == [
        {"path": f"src/{directory}/a.py", "reason": f"could not be written ({DENIED})"}
    ]
    assert "unswept_files" not in data


def test_renumber_names_a_file_it_could_not_read_without_this_machine_s_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The reason carried `str(OSError)`, which names the file by its absolute path: the
    # machine's own directory layout in `--json`, the leak `memory index` stopped for the same
    # reason. The reason is the error's own words; the path is the field beside it, relative to
    # the root. Mutation: record `str(error)` in `scan.scannable` — this reddens.
    if os.geteuid() == 0:
        pytest.skip("root reads everything")
    root, common = project(tmp_path)
    invoke(["bugs", "new", "t", "--severity", "low", "--area", "a", "--no-fetch", *common])
    capsys.readouterr()
    locked = root / "src" / "a: b" / "locked.py"
    locked.parent.mkdir(parents=True)
    locked.write_text("# BR-001\n", encoding="utf-8")
    locked.chmod(0)
    try:
        assert invoke(["bugs", "renumber", "BR-001", "BR-009", "--json", *common]) == 1
    finally:
        locked.chmod(0o644)
    out = capsys.readouterr().out
    data = json.loads(out)
    reason = f"could not be read to check for BR-001 ({DENIED})"
    assert data["unswept"] == [{"path": "src/a: b/locked.py", "reason": reason}]
    assert tmp_path.name not in out


def test_check_answers_with_the_bugs_gate_s_own_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `bugs check` and the `bugs` gate are one function, so the command cannot pass a ledger the
    # gate run fails, or the reverse: a finding only `bugs_gate` returns is the command's answer.
    _root, common = project(tmp_path)
    argv = ["bugs", "new", "a title", "--severity", "low", "--area", "an area", "--no-fetch"]
    assert invoke([*argv, *common]) == 0
    assert invoke(["bugs", "check", *common]) == 0
    planted = [Finding("planted", "", None, "")]
    monkeypatch.setattr("stayfixed.ledger.check.bugs_gate", lambda *args, **kwargs: planted)
    assert invoke(["bugs", "check", *common]) == 1


@pytest.mark.parametrize(
    "argv",
    [["bugs", "check"], ["plan", "check", "{plan}"]],
    ids=["bugs-check", "plan-check"],
)
def test_a_boundary_level_that_names_no_severity_is_a_refusal_in_every_command_that_reads_it(
    tmp_path: Path, argv: list[str]
) -> None:
    # `bug_register` is reached from `plan check` as well as the `bugs`
    # group, so the refusal is a `Refusal`, which each prints as a normal `refused:` line with
    # exit 2, and never a `ValueError`, which each would print as an internal error.
    root, _ = project(tmp_path)
    document = CONFIG + '\n[ledger]\nevidence_boundary_required_for = ["critical"]\n'
    (root / "stayfixed.toml").write_text(document, encoding="utf-8")
    (root / "docs" / "plans").mkdir()
    (root / "docs" / "plans" / "p.md").write_text("# A plan\n", encoding="utf-8")
    plan = str(root / "docs" / "plans" / "p.md")
    argv = [arg.format(plan=plan) for arg in argv]
    code, out, err = cli(root, tmp_path, *argv, machine=tmp_path / "m.toml")
    assert (code, out) == (2, ""), (out, err)
    assert err.startswith("stayfixed: refused: [ledger] evidence_boundary_required_for names 1")
    assert "critical" not in err
