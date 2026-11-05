"""Every rule `bugs check` reports, one fixture each.

stayfixed:ledger:fixtures — the identifiers below are sample data, not claims about a ledger.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from stayfixed import committed
from stayfixed.config.loader import load
from stayfixed.config.schema import Config
from stayfixed.errors import Failure, Refusal
from stayfixed.findings import LISTED_LIMIT
from stayfixed.gitenv import NO_ANSWER, git_run
from stayfixed.ledger import check
from stayfixed.ledger.check import register_gate, uninitialised
from stayfixed.ledger.entries import load_entries
from stayfixed.ledger.index import render_index
from stayfixed.ledger.register import EVIDENCE_LABEL, EVIDENCE_PLACEHOLDER, bug_register
from stayfixed.ledger.write import renumber
from tests.gitfixture import answer_shallow_check, criss_cross, dated, git, needs_git
from tests.ledger.kills import Killed, killed_at

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"
"""


def project(tmp_path: Path, extra: str = "") -> tuple[Path, Config]:
    root = tmp_path / "widget"
    root.mkdir()
    (root / "stayfixed.toml").write_text(CONFIG + extra, encoding="utf-8")
    for name in ("src", "tests", "scripts", "docs"):
        (root / name).mkdir()
    return root, load(root, machine=tmp_path / "m.toml")


def entry(number: int, *, severity: str = "low", body: str = "body\n", related: str = "") -> str:
    return (
        f"---\nid: BR-{number:03d}\ntitle: a title\nstatus: open\nseverity: {severity}\n"
        f"area: an area\nfound: 2026-01-01\nsource:\nfixed_in:\nrelated: {related}\n---\n\n{body}"
    )


def ledger(root: Path, config: Config, entries: dict[str, str]) -> None:
    bugs = root / "docs" / "bugs"
    bugs.mkdir(parents=True, exist_ok=True)
    for name, text in entries.items():
        (bugs / f"{name}.md").write_text(text, encoding="utf-8")
    register = bug_register(config)
    (root / "docs" / "bug-reports.md").write_text(
        render_index(load_entries(root, register), register), encoding="utf-8"
    )


def rules(root: Path, config: Config) -> list[str]:
    return [problem.rule for problem in register_gate(root, config, bug_register(config))]


def test_check_is_inert_before_a_ledger_exists(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    assert uninitialised(root, bug_register(config))
    assert register_gate(root, config, bug_register(config)) == []


def test_with_no_ledger_every_citation_of_an_entry_file_dangles(tmp_path: Path) -> None:
    # "No ledger yet" is read off the tree, and a pull request writes the tree: deleting the
    # ledger and its index must not switch an enforced gate off while code still cites entry
    # files. A project that registers the gate before its first entry cites none, and the case
    # above holds that it stays green. Mutation (declared): the uninitialised arm answers `[]`
    # again -> nothing is reported.
    root, config = project(tmp_path)
    (root / "src" / "a.py").write_text("# see docs/bugs/BR-001.md\n", encoding="utf-8")
    (root / "docs" / "roadmap.md").write_text("see [x](bugs/BR-404.md)\n", encoding="utf-8")
    assert uninitialised(root, bug_register(config))
    found = register_gate(root, config, bug_register(config))
    # The code's citation names the identifier too, so it is a mention as well, as it is once a
    # ledger exists; the roadmap is outside the trees swept for mentions.
    assert [(p.rule, p.path, p.line) for p in found] == [
        ("dangling-mention", "src/a.py", 1),
        ("dangling-citation", "src/a.py", 1),
        ("dangling-citation", "docs/roadmap.md", 1),
    ]


def test_with_no_ledger_a_bare_mention_dangles_too(tmp_path: Path) -> None:
    # A bare identifier is the ordinary way code refers to a bug, so with the ledger deleted a
    # `# workaround for BR-001` is as dangling as a citation of its file: reported only for
    # citations, deleting the ledger and its index switched an enforced gate off for every
    # mention. Mutation (oracle): `mutations/`'s "with no ledger a bare mention is not a finding" ->
    # nothing is reported.
    root, config = project(tmp_path)
    (root / "src" / "a.py").write_text("# workaround for BR-001\n", encoding="utf-8")
    assert [
        (p.rule, p.path, p.line) for p in register_gate(root, config, bug_register(config))
    ] == [("dangling-mention", "src/a.py", 1)]


def _based(tmp_path: Path, on_base: str) -> tuple[Path, Config, str]:
    """A project whose one commit carries `on_base` of the ledger (`both`, `directory`, `index`
    or `none`), with the tree then emptied of it; the commit's id is the base."""
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    if on_base in ("both", "directory"):
        ledger(root, config, {"BR-001": entry(1)})
    if on_base == "directory":
        (root / "docs" / "bug-reports.md").unlink()
    if on_base == "index":
        (root / "docs" / "bug-reports.md").write_text(
            render_index([], bug_register(config)), encoding="utf-8"
        )
    (root / "README.md").write_text("widget\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD").strip()
    shutil.rmtree(root / "docs" / "bugs", ignore_errors=True)
    (root / "docs" / "bug-reports.md").unlink(missing_ok=True)
    return root, config, base


@needs_git
@pytest.mark.parametrize("on_base", ["both", "directory", "index"])
def test_a_tree_that_deleted_the_base_s_ledger_is_one_ledger_removed_finding(
    tmp_path: Path, on_base: str
) -> None:
    # "No ledger" is read off the tree, which the change wrote, so the base is asked whether it
    # had one: deleting the ledger, the index and every mention together passed, with nothing
    # left in the tree to dangle. Mutation (oracle): `mutations/`'s "the uninitialised arm ignores
    # the base's ledger" -> nothing is reported.
    root, config, base = _based(tmp_path, on_base)
    assert uninitialised(root, bug_register(config))
    assert [(p.rule, p.path) for p in register_gate(root, config, bug_register(config), base)] == [
        ("ledger-removed", "docs/bugs")
    ]
    # Without a base the tree alone is judged, as `bugs check` without `--base` judges it.
    assert register_gate(root, config, bug_register(config)) == []
    # And a mention still dangles beside it: both are the change's to answer for.
    (root / "src" / "a.py").write_text("# workaround for BR-001\n", encoding="utf-8")
    assert [p.rule for p in register_gate(root, config, bug_register(config), base)] == [
        "ledger-removed",
        "dangling-mention",
    ]


@needs_git
def test_a_base_with_no_ledger_leaves_a_project_before_its_first_entry_green(
    tmp_path: Path,
) -> None:
    # The gate can be enforced before the first entry: no ledger on the base and no reference
    # in the tree is nothing to report.
    root, config, base = _based(tmp_path, "none")
    assert register_gate(root, config, bug_register(config), base) == []


def _committed_ledger(tmp_path: Path, names: tuple[str, ...]) -> tuple[Path, Config, str]:
    """A project whose one commit carries the entries `names` and their index, with a mention
    of each in `src/a.py`; the commit's id is the base, and the tree is left as committed."""
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    ledger(root, config, {name: entry(int(name[3:])) for name in names})
    (root / "src" / "a.py").write_text(
        "".join(f"# workaround for {name}\n" for name in names), encoding="utf-8"
    )
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root, config, git(root, "rev-parse", "HEAD").strip()


def _drop(root: Path, config: Config, *names: str) -> None:
    """Delete the entries `names`, keep the directory with a placeholder, and regenerate the
    index, which is what a change that empties the ledger commits."""
    for name in names:
        (root / "docs" / "bugs" / f"{name}.md").unlink()
    (root / "docs" / "bugs" / ".gitkeep").write_text("", encoding="utf-8")
    register = bug_register(config)
    (root / "docs" / "bug-reports.md").write_text(
        render_index(load_entries(root, register), register), encoding="utf-8"
    )


@needs_git
@pytest.mark.parametrize(
    "mentions",
    ["", "# stayfixed:ledger:fixtures\n# workaround for BR-001\n"],
    ids=["mentions-removed", "fixtures-marker"],
)
def test_an_entry_the_base_carries_and_the_tree_lacks_is_entry_removed(
    tmp_path: Path, mentions: str
) -> None:
    # Ledger entries are append-only. Deleting every entry and the mentions of them, keeping the
    # directory with a placeholder and regenerating the empty index, left a ledger that was not
    # "uninitialised", and the base was asked nothing: an enforced `bugs` gate passed. The
    # mentions do not decide it either way, so a file that marks itself as holding sample
    # identifiers exempts nothing. Mutation (declared): the entries the base carries not
    # compared with the tree's -> nothing is reported.
    root, config, base = _committed_ledger(tmp_path, ("BR-001",))
    _drop(root, config, "BR-001")
    (root / "src" / "a.py").write_text(mentions, encoding="utf-8")
    assert not uninitialised(root, bug_register(config))
    assert [(p.rule, p.path) for p in register_gate(root, config, bug_register(config), base)] == [
        ("entry-removed", "docs/bugs/BR-001.md")
    ]
    # Without a base the tree alone is judged, and it is a consistent, empty ledger.
    assert register_gate(root, config, bug_register(config)) == []


@needs_git
def test_one_entry_removed_of_several_is_named_and_the_rest_are_not(tmp_path: Path) -> None:
    root, config, base = _committed_ledger(tmp_path, ("BR-001", "BR-002"))
    _drop(root, config, "BR-002")
    (root / "src" / "a.py").write_text("# workaround for BR-001\n", encoding="utf-8")
    assert [(p.rule, p.path) for p in register_gate(root, config, bug_register(config), base)] == [
        ("entry-removed", "docs/bugs/BR-002.md")
    ]


@needs_git
def test_a_ledger_whose_directory_went_and_index_stayed_names_each_removed_entry(
    tmp_path: Path,
) -> None:
    # The other arm a deleted ledger takes: the generated index is still there and says the
    # entries are missing, and against a base each one the base carried is named too.
    root, config, base = _committed_ledger(tmp_path, ("BR-001",))
    shutil.rmtree(root / "docs" / "bugs")
    (root / "src" / "a.py").write_text("", encoding="utf-8")
    assert [(p.rule, p.path) for p in register_gate(root, config, bug_register(config), base)] == [
        ("entries-missing", "docs/bug-reports.md"),
        ("entry-removed", "docs/bugs/BR-001.md"),
    ]


@needs_git
def test_renumbering_an_entry_removes_nothing(tmp_path: Path) -> None:
    # `bugs renumber` is how an entry moves, and it leaves a `void` entry at the old number, so
    # an identifier once allocated keeps resolving: against the base it moved on, nothing is
    # reported.
    root, config, base = _committed_ledger(tmp_path, ("BR-001",))
    renumber(root, config, bug_register(config), "BR-001", "BR-002", today="2026-01-02")
    assert (root / "docs" / "bugs" / "BR-001.md").is_file()
    assert register_gate(root, config, bug_register(config), base) == []


MOVED = '\n[paths]\nbugs = "ledger"\nbug_index = "ledger-index.md"\n'


def _moved(root: Path, tmp_path: Path, kept: tuple[str, ...]) -> Config:
    """Move the committed ledger to `ledger/` and `ledger-index.md` by `[paths]`, keeping the
    entries `kept` and deleting the rest, and the mentions with them; the tree's new config."""
    (root / "stayfixed.toml").write_text(CONFIG + MOVED, encoding="utf-8")
    config = load(root, machine=tmp_path / "m.toml")
    (root / "ledger").mkdir()
    for path in sorted((root / "docs" / "bugs").iterdir()):
        if path.stem in kept:
            path.rename(root / "ledger" / path.name)
    shutil.rmtree(root / "docs" / "bugs")
    (root / "docs" / "bug-reports.md").unlink()
    register = bug_register(config)
    (root / "ledger-index.md").write_text(
        render_index(load_entries(root, register), register), encoding="utf-8"
    )
    (root / "src" / "a.py").write_text(
        "".join(f"# workaround for {name}\n" for name in kept), encoding="utf-8"
    )
    return config


@needs_git
def test_a_ledger_moved_by_paths_is_read_on_the_base_where_the_base_kept_it(
    tmp_path: Path,
) -> None:
    # The base's entries were listed at the tree's `[paths]`, so a change that moved the ledger
    # found none there on the base, and deleting an entry in the same change passed `bugs check
    # --base` — and the `gate` command, whenever the base enforces nothing and so refuses no
    # `[paths]` change. The base's ledger is read where the base's own `stayfixed.toml` kept it.
    # Mutation: `mutations/`'s "the base's entries are listed at the tree's paths again".
    root, _, base = _committed_ledger(tmp_path, ("BR-001", "BR-002", "BR-003"))
    config = _moved(root, tmp_path, ("BR-001", "BR-003"))
    assert [(p.rule, p.path) for p in check.bugs_gate(root, config, base)] == [
        ("entry-removed", "ledger/BR-002.md")
    ]


@needs_git
def test_a_ledger_moved_whole_by_paths_removes_nothing(tmp_path: Path) -> None:
    # The legitimate move this must not refuse: every entry carried to the new paths.
    root, _, base = _committed_ledger(tmp_path, ("BR-001", "BR-002"))
    config = _moved(root, tmp_path, ("BR-001", "BR-002"))
    assert check.bugs_gate(root, config, base) == []


@needs_git
@pytest.mark.parametrize(
    ("copy", "raised", "said"),
    [
        (b"[nonsense]\n", Failure, "does not load"),
        (b"# \xff\n", Failure, "is not UTF-8 text"),
        (b"[paths]\nbugs = '../out'\n", Refusal, "loading its stayfixed.toml against this tree"),
        (b"[ledger]\nid_prefix = 'br'\n", Refusal, "places its ledger by an identifier prefix"),
    ],
    ids=["does-not-load", "not-utf8", "refused", "prefix-refused"],
)
def test_a_base_copy_that_will_not_load_fails_the_check_and_never_reads_as_no_ledger(
    tmp_path: Path, copy: bytes, raised: type[Exception], said: str
) -> None:
    # Where the base kept its ledger is the question, so a copy that cannot answer it is no
    # answer, and never the tree's paths in its place: that would pass again the change
    # `test_a_ledger_moved_by_paths_is_read_on_the_base_where_the_base_kept_it` makes. A copy
    # that is not UTF-8 is never parsed, as the loader never parses the tree's. A load that met
    # a refusal and a prefix the identifiers refuse are told apart in the words. Mutations:
    # `mutations/`'s "a base copy that does not load is read at the tree's paths", "a base copy
    # that is not UTF-8 is parsed", "a base copy whose load meets a refusal is read at the
    # tree's paths" and "a base copy whose prefix is refused is said to have met a refusal on
    # load".
    root, config, _ = _committed_ledger(tmp_path, ("BR-001",))
    (root / "stayfixed.toml").write_bytes(CONFIG.encode() + copy)
    git(root, "commit", "-qam", "a copy the loader refuses")
    base = git(root, "rev-parse", "HEAD").strip()
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    with pytest.raises(raised, match=said):
        check.bugs_gate(root, config, base)


@needs_git
def test_a_base_whose_boundary_level_names_no_severity_does_not_stop_the_change_that_corrects_it(
    tmp_path: Path,
) -> None:
    # Locating the base's ledger needs its paths and its identifiers, and nothing of how it
    # judges an entry: built whole, the base's register refused the boundary level 0.2.0 loaded,
    # so the change correcting it was refused (exit 2) by the very check it repairs. Mutation:
    # `mutations/`'s "the base's ledger is located by a register that judges entries".
    root, config, _ = _committed_ledger(tmp_path, ("BR-001",))
    typo = CONFIG + '\n[ledger]\nevidence_boundary_required_for = ["critical"]\n'
    (root / "stayfixed.toml").write_text(typo, encoding="utf-8")
    git(root, "commit", "-qam", "a level that names no severity")
    base = git(root, "rev-parse", "HEAD").strip()
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    assert check.bugs_gate(root, config, base) == []


@needs_git
def test_a_ledger_deleted_with_its_paths_moved_is_named_where_the_base_kept_it(
    tmp_path: Path,
) -> None:
    # The finding's remedy is "restore it from the base", so it names the paths the base held:
    # named at the change's new paths, it sent the owner to restore what no commit ever had.
    # Mutation: `mutations/`'s "a removed ledger is named at the tree's paths".
    root, _, base = _committed_ledger(tmp_path, ("BR-001",))
    (root / "stayfixed.toml").write_text(CONFIG + MOVED, encoding="utf-8")
    config = load(root, machine=tmp_path / "m.toml")
    shutil.rmtree(root / "docs" / "bugs")
    (root / "docs" / "bug-reports.md").unlink()
    (root / "src" / "a.py").write_text("", encoding="utf-8")
    [found] = check.bugs_gate(root, config, base)
    assert (found.rule, found.path) == ("ledger-removed", "docs/bugs")
    assert "(docs/bugs or docs/bug-reports.md)" in found.detail


@needs_git
def test_a_listing_of_the_base_s_configuration_git_refuses_is_a_failure_never_the_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A listing that failed listed nothing, which is what a fork with no `stayfixed.toml` lists:
    # read that way, the base would be compared at the tree's paths, which is the bootstrap's
    # answer and not this one. The failure names the file it could not read, not the ledger's
    # paths. Mutations: `mutations/`'s "git failing to read the base is read as the base having no
    # stayfixed.toml" and "an unread fork configuration is named by the ledger's paths".
    root, _, base = _committed_ledger(tmp_path, ("BR-001", "BR-002"))
    config = _moved(root, tmp_path, ("BR-001",))
    real = git_run

    def refused(where: Path, *args: str, **kwargs: Any) -> tuple[int, str]:
        if "ls-tree" in args and args[-1] == "stayfixed.toml":
            return 128, ""
        return real(where, *args, **kwargs)

    monkeypatch.setattr(committed, "git_run", refused)
    with pytest.raises(Failure, match="proved nothing") as raised:
        check.bugs_gate(root, config, base)
    assert "hold of stayfixed.toml is unknown" in str(raised.value)


@needs_git
def test_a_listing_git_refuses_at_a_fork_names_the_paths_that_fork_kept_the_ledger_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # After a `[paths]` move the failing listing asked about the base's paths, not the tree's,
    # and the message names what it asked about. Mutation: `mutations/`'s "an unread fork
    # listing is named by the tree's paths".
    root, _, base = _committed_ledger(tmp_path, ("BR-001",))
    config = _moved(root, tmp_path, ("BR-001",))
    real = git_run

    def refused(where: Path, *args: str, **kwargs: Any) -> tuple[int, str]:
        if args[:2] == ("ls-tree", "-r"):
            return 128, ""
        return real(where, *args, **kwargs)

    monkeypatch.setattr(check, "git_run", refused)
    with pytest.raises(Failure) as raised:
        check.bugs_gate(root, config, base)
    assert "hold of docs/bugs and docs/bug-reports.md is unknown" in str(raised.value)


@needs_git
def test_the_base_a_caller_names_is_printed_as_data_in_every_base_refusal(tmp_path: Path) -> None:
    # `--base` is the caller's, and a ref holding an escape sequence reached the terminal raw.
    # It is printed through `printed.quoted`, as every name in a refusal is. Mutation:
    # `mutations/`'s "an unread base is named raw".
    root, config, _ = _committed_ledger(tmp_path, ("BR-001",))
    with pytest.raises(Failure) as raised:
        check.bugs_gate(root, config, "nowhere\x1b[31m")
    assert "\x1b" not in str(raised.value)
    assert "'nowhere\\x1b[31m'" in str(raised.value)


@needs_git
def test_a_base_prefix_the_ledger_refuses_is_clipped_where_it_is_named(tmp_path: Path) -> None:
    # The base's prefix is the base's own text, of any length: named in full, five thousand
    # characters of it reached the line. It is clipped as every repository-chosen name in a
    # refusal is. Mutation: `mutations/`'s "a base prefix the ledger refuses is named whole".
    root, config, _ = _committed_ledger(tmp_path, ("BR-001",))
    long = "B" * 5000
    (root / "stayfixed.toml").write_text(
        CONFIG + f'\n[ledger]\nid_prefix = "{long}"\n', encoding="utf-8"
    )
    git(root, "commit", "-qam", "a prefix the ledger refuses")
    base = git(root, "rev-parse", "HEAD").strip()
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    with pytest.raises(Refusal) as raised:
        check.bugs_gate(root, config, base)
    assert "…(5000 chars)" in str(raised.value)
    assert long not in str(raised.value)


@needs_git
def test_a_changed_id_prefix_answers_for_every_entry_under_the_old_one(tmp_path: Path) -> None:
    # The base's identifiers are the base's prefix: a change that renames the prefix leaves
    # every old entry unloaded under the new one, and each is named.
    root, _, base = _committed_ledger(tmp_path, ("BR-001",))
    (root / "stayfixed.toml").write_text(
        CONFIG + '\n[ledger]\nid_prefix = "XX"\n', encoding="utf-8"
    )
    config = load(root, machine=tmp_path / "m.toml")
    (root / "docs" / "bugs" / "BR-001.md").unlink()
    (root / "src" / "a.py").write_text("", encoding="utf-8")
    register = bug_register(config)
    (root / "docs" / "bug-reports.md").write_text(render_index([], register), encoding="utf-8")
    assert [(p.rule, p.path) for p in check.bugs_gate(root, config, base)] == [
        ("entry-removed", "docs/bugs/BR-001.md")
    ]


@needs_git
def test_the_base_s_copy_reads_no_machine_file_but_the_one_the_command_was_given(
    tmp_path: Path,
) -> None:
    # A gate is handed `(root, config, base)`, not the machine file's path, so a second load
    # that read the machine file again read the default one: a command given `--machine` read
    # a file nobody named, and failed on its contents. Mutation: `mutations/`'s "the base's copy
    # reads the default machine file".
    root, config, base = _committed_ledger(tmp_path, ("BR-001",))
    default = Path.home() / ".config" / "stayfixed" / "config.toml"
    default.parent.mkdir(parents=True)
    default.write_text("[[[ not toml\n", encoding="utf-8")
    assert check.bugs_gate(root, config, base) == []


@needs_git
def test_a_base_with_no_stayfixed_toml_is_read_at_the_tree_s_paths(tmp_path: Path) -> None:
    # The change that adds `stayfixed.toml` is the bootstrap, where the tree decides: its entries
    # are compared at the tree's own paths.
    root, config, _ = _committed_ledger(tmp_path, ("BR-001", "BR-002"))
    git(root, "rm", "-q", "--cached", "stayfixed.toml")
    git(root, "commit", "-qm", "no configuration yet")
    base = git(root, "rev-parse", "HEAD").strip()
    _drop(root, config, "BR-002")
    (root / "src" / "a.py").write_text("# workaround for BR-001\n", encoding="utf-8")
    assert [(p.rule, p.path) for p in check.bugs_gate(root, config, base)] == [
        ("entry-removed", "docs/bugs/BR-002.md")
    ]


@needs_git
def test_an_entry_renamed_only_in_case_is_entry_removed_where_the_filesystem_folds_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `BR-001.md` renamed to `br-001.md` is no entry: the ledger loads `BR-*.md` by exact name,
    # so the identifier lost its file. Asked by name, a filesystem that folds case (macOS's and
    # Windows's default) answered that `BR-001.md` was still there, and the change passed where
    # the reusable workflow's Linux runner refused it. The rename below folds on such a
    # filesystem; the lookup is made to fold here too, so the case holds on every runner.
    # Mutation (declared): the name looked up with `os.path.lexists` again -> nothing reported.
    root, config, base = _committed_ledger(tmp_path, ("BR-001",))
    bugs = root / "docs" / "bugs"
    (bugs / "BR-001.md").rename(bugs / "br-001.md")
    (root / "docs" / "bug-reports.md").write_text(
        render_index([], bug_register(config)), encoding="utf-8"
    )
    (root / "src" / "a.py").write_text("", encoding="utf-8")
    real = os.path.lexists

    def folding(path: str | os.PathLike[str]) -> bool:
        where = Path(path)
        if real(where) or not where.parent.is_dir():
            return real(where)
        return any(name.lower() == where.name.lower() for name in os.listdir(where.parent))

    monkeypatch.setattr(os.path, "lexists", folding)
    assert os.path.lexists(bugs / "BR-001.md")
    assert [(p.rule, p.path) for p in register_gate(root, config, bug_register(config), base)] == [
        ("entry-removed", "docs/bugs/BR-001.md")
    ]


@needs_git
def test_deleting_what_is_not_an_entry_under_the_ledger_directory_removes_no_entry(
    tmp_path: Path,
) -> None:
    # The ledger directory can hold notes beside the entries: a README, an audit under a
    # subdirectory, a file that looks like an entry and is not one. Only a `<PREFIX>-nnn.md`
    # directly under the directory is an entry, so deleting the rest is no `entry-removed`.
    # Mutation (declared): the identifier filter on the base's names dropped -> each `.md` the
    # base carried under the directory reads as a deleted entry.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    ledger(root, config, {"BR-001": entry(1)})
    bugs = root / "docs" / "bugs"
    (bugs / "audits").mkdir()
    for name in ("audits/a.md", "audits/BR-005.md", "README.md", "BR-002.txt", "notes.md"):
        (bugs / name).write_text("notes\n", encoding="utf-8")
    (root / "src" / "a.py").write_text("# workaround for BR-001\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD").strip()
    shutil.rmtree(bugs / "audits")
    for name in ("README.md", "BR-002.txt", "notes.md"):
        (bugs / name).unlink()
    assert register_gate(root, config, bug_register(config), base) == []


def _forked(
    tmp_path: Path, at_fork: tuple[str, ...], filed_since: tuple[str, ...]
) -> tuple[Path, Config, str]:
    """A project whose `main` carries the entries `at_fork`, a branch `change` forked there, and
    `main` then filing `filed_since`; the tree is `change` as forked, and the base is `main`."""
    root, config, _ = _committed_ledger(tmp_path, at_fork)
    git(root, "checkout", "-q", "-b", "change")
    git(root, "checkout", "-q", "main")
    ledger(root, config, {name: entry(int(name[3:])) for name in filed_since})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "file entries on the base")
    base = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "change")
    return root, config, base


@needs_git
def test_a_branch_forked_before_the_base_filed_an_entry_deleted_nothing(tmp_path: Path) -> None:
    # The base gained BR-002 after this branch forked, and the branch touched nothing: listed at
    # the base's tip, BR-002 read as an entry this change deleted, and the finding told a
    # contributor whose branch predates a colleague's `bugs new` to restore it. The ledger is
    # compared with the commit the change forked from, where `plan` compares too. Mutation
    # (declared): the entries listed at the base's tip -> `entry-removed` for BR-002.
    root, config, base = _forked(tmp_path, ("BR-001",), ("BR-002",))
    assert not (root / "docs" / "bugs" / "BR-002.md").exists()
    assert register_gate(root, config, bug_register(config), base) == []


@needs_git
def test_a_branch_forked_before_the_base_had_a_ledger_deleted_none(tmp_path: Path) -> None:
    # The same line for the whole ledger: a branch forked before the first entry has no ledger
    # in its tree, and that is not a deletion. Mutation (declared, as above): the base's tip
    # listed -> `ledger-removed`.
    root, config, base = _based(tmp_path, "none")
    git(root, "checkout", "-q", "-b", "change")
    git(root, "checkout", "-q", "main")
    ledger(root, config, {"BR-001": entry(1)})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the first entry")
    base = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "change")
    assert uninitialised(root, bug_register(config))
    assert register_gate(root, config, bug_register(config), base) == []


@needs_git
def test_a_deletion_is_named_on_a_stale_branch_and_on_a_merge_commit(tmp_path: Path) -> None:
    # What the fork point may not do is let a deletion through. On a branch behind its base the
    # entry it deleted is named, and the one the base filed since is not. In CI the tree is a
    # merge commit whose base parent can be behind the base the run resolved (the base moved
    # between the event and the job): the commit both share is that parent, which carried the
    # entry, so the deletion is named there too.
    root, config, base = _forked(tmp_path, ("BR-001",), ("BR-002",))
    _drop(root, config, "BR-001")
    (root / "src" / "a.py").write_text("", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "empty the ledger")
    expected = [("entry-removed", "docs/bugs/BR-001.md")]
    assert [
        (p.rule, p.path) for p in register_gate(root, config, bug_register(config), base)
    ] == expected
    git(root, "checkout", "-q", "--detach", "main~1")
    git(root, "merge", "-q", "--no-ff", "--no-edit", "change")
    assert git(root, "rev-parse", "HEAD^2").strip() == git(root, "rev-parse", "change").strip()
    assert [
        (p.rule, p.path) for p in register_gate(root, config, bug_register(config), base)
    ] == expected


@needs_git
def test_a_deletion_is_named_whichever_of_several_merge_bases_git_would_pick(
    tmp_path: Path,
) -> None:
    # A criss-cross: `main` files BR-002 and then merges a colleague's side branch, forked
    # before BR-002 and committed after it; the change merges the filing commit and the side
    # branch itself. HEAD and the base then have two merge bases, and `git merge-base` answers
    # the newer-dated one, the side branch's, which predates the entry: listed there alone,
    # deleting BR-002 passed, and merging the change deletes it from `main`. Every merge base is
    # listed and their entries are united; entries are append-only, so the union refuses no
    # branch that deleted nothing. Mutations (declared): `--all` dropped, or only the first
    # merge base kept -> nothing reported.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    ledger(root, config, {"BR-001": entry(1)})
    git(root, "add", "-A")
    dated(root, 1, "commit", "-q", "-m", "the first entry")
    shape = criss_cross(root, lambda: ledger(root, config, {"BR-002": entry(2)}))
    git(root, "checkout", "-q", "-b", "change")
    # A branch that merged both and deleted nothing is not refused.
    assert register_gate(root, config, bug_register(config), shape.base) == []
    _drop(root, config, "BR-002")
    git(root, "add", "-A")
    dated(root, 6, "commit", "-q", "-m", "delete BR-002")
    assert [
        (p.rule, p.path) for p in register_gate(root, config, bug_register(config), shape.base)
    ] == [("entry-removed", "docs/bugs/BR-002.md")]


@needs_git
def test_a_shallow_clone_is_a_failure_never_an_older_fork_point(tmp_path: Path) -> None:
    # In a shallow clone the commits HEAD forked from can be cut off, and the merge base git can
    # see is then older than the real one, from before the entry the change deleted: a deletion
    # passed. A shallow clone is a question with no answer, `Failure` like a base git cannot
    # list, whose remedy is the full history. Mutation (declared, on `gitenv`): the shallow
    # answer ignored -> the clone below, whose tip is its own merge base, answers `[]`.
    root, config, _ = _committed_ledger(tmp_path, ("BR-001",))
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", root.as_uri(), str(shallow))
    assert git(shallow, "rev-parse", "--is-shallow-repository").strip() == "true"
    with pytest.raises(Failure) as caught:
        register_gate(shallow, config, bug_register(config), "refs/remotes/origin/main")
    assert "shallow" in str(caught.value)


@needs_git
@pytest.mark.parametrize(
    ("answer", "cause"),
    [(-1, NO_ANSWER), (128, "git exited 128")],
    ids=["no-answer", "refused"],
)
def test_a_shallow_check_git_does_not_answer_is_a_failure_never_a_full_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: int, cause: str
) -> None:
    # Whether the clone is shallow is a question too: read as "not shallow" when git gave no
    # answer or refused, a shallow clone went on to the merge base it could see, an older one
    # than the real fork point, which is the case the shallow check exists to close. Mutation
    # (declared, on `gitenv`): the shallow check's failure ignored -> the listing below goes
    # ahead and answers `[]`.
    root, config, base = _committed_ledger(tmp_path, ("BR-001",))
    answer_shallow_check(monkeypatch, answer)
    with pytest.raises(Failure) as caught:
        register_gate(root, config, bug_register(config), base)
    assert f"({cause})" in str(caught.value)
    assert "proved nothing" in str(caught.value)


@needs_git
def test_a_base_that_shares_no_history_with_the_tree_is_a_failure(tmp_path: Path) -> None:
    # A base with no commit in common with HEAD leaves nothing to compare the ledger with, and
    # "the base carried nothing" would pass whatever the change deleted: a `Failure`, which a
    # gate run reports as could not run. Mutation (declared): a merge base git cannot answer
    # read as a base with no ledger -> `[]`.
    root, config, _ = _committed_ledger(tmp_path, ("BR-001",))
    git(root, "checkout", "-q", "--orphan", "unrelated")
    git(root, "commit", "-q", "-m", "no shared history")
    other = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "-f", "main")
    with pytest.raises(Failure) as caught:
        register_gate(root, config, bug_register(config), other)
    assert "proved nothing" in str(caught.value)


@needs_git
def test_a_base_git_cannot_list_never_reads_as_a_base_with_no_ledger(tmp_path: Path) -> None:
    # A base this clone does not have is a question with no answer, and "the base had no
    # ledger" would pass exactly the change the question exists to catch: a `Failure`, which a
    # gate run reports as could not run. Mutation (oracle): `mutations/`'s "a fork point that is
    # not known reads as a base with no ledger" -> `register_gate` returns `[]`.
    root, config, _base = _based(tmp_path, "both")
    with pytest.raises(Failure) as caught:
        register_gate(root, config, bug_register(config), "refs/remotes/origin/main")
    assert "proved nothing" in str(caught.value)
    # Shaped like an option, it is refused before git sees it, as `plan check` refuses it.
    with pytest.raises(Refusal):
        register_gate(root, config, bug_register(config), "--output=x")


@needs_git
def test_a_listing_git_refuses_at_a_merge_base_is_a_failure_never_an_empty_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fork points are known and the listing at one of them is not: an empty listing would
    # read as a base with no ledger, and pass the deletion below. Mutation (declared): the
    # listing's failure arm dropped -> `[]`.
    root, config, base = _committed_ledger(tmp_path, ("BR-001",))
    _drop(root, config, "BR-001")
    real = git_run

    def refused(where: Path, *args: str, **kwargs: Any) -> tuple[int, str]:
        return (128, "") if args[0] == "ls-tree" else real(where, *args, **kwargs)

    monkeypatch.setattr(check, "git_run", refused)
    with pytest.raises(Failure, match="git exited 128") as caught:
        register_gate(root, config, bug_register(config), base)
    assert "proved nothing" in str(caught.value)


def test_a_generated_index_with_no_entries_directory_is_a_deleted_ledger(tmp_path: Path) -> None:
    # Mutation: drop the `is_generated_index` conjunct from `uninitialised` — this reddens.
    root, config = project(tmp_path)
    (root / "docs" / "bug-reports.md").write_text(
        render_index([], bug_register(config)), encoding="utf-8"
    )
    assert not uninitialised(root, bug_register(config))
    assert rules(root, config) == ["entries-missing"]


def test_check_accepts_a_clean_ledger(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1)})
    assert register_gate(root, config, bug_register(config)) == []


def test_a_conflict_marker_is_reported_before_the_entry_is_parsed(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1)})
    (root / "docs" / "bugs" / "BR-001.md").write_text(
        "<<<<<<< ours\n" + entry(1) + "=======\n>>>>>>> theirs\n", encoding="utf-8"
    )
    found = register_gate(root, config, bug_register(config))
    assert [p.rule for p in found] == ["conflict-marker", "stale-index"]
    assert found[0].path == "docs/bugs/BR-001.md"


def test_an_id_that_disagrees_with_its_filename_is_reported(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-002": entry(1)})
    assert "id-mismatch" in rules(root, config)


def test_a_body_that_restates_status_or_severity_is_reported(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1, body="- **Status:** open\n")})
    assert rules(root, config) == ["state-in-body"]


def test_two_files_claiming_one_identifier_are_reported_once(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1), "BR-002": entry(1)})
    found = [
        p for p in register_gate(root, config, bug_register(config)) if p.rule == "duplicate-id"
    ]
    assert len(found) == 1 and "BR-002.md" in found[0].detail


def test_a_related_identifier_with_no_entry_is_reported(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1, related="[BR-009]")})
    assert rules(root, config) == ["dangling-related"]


def test_high_severity_needs_a_filled_evidence_boundary(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1, severity="high")})
    assert rules(root, config) == ["evidence-boundary"]


def test_the_untouched_scaffold_placeholder_does_not_satisfy_the_rule(tmp_path: Path) -> None:
    # A placeholder that satisfies its own check is the failure mode the rule exists to
    # prevent. Mutation: drop the negative lookahead — this reddens.
    root, config = project(tmp_path)
    ledger(
        root,
        config,
        {
            "BR-001": entry(
                1,
                severity="high",
                body=f"{EVIDENCE_LABEL} {EVIDENCE_PLACEHOLDER} —\nname what.\n",
            )
        },
    )
    assert rules(root, config) == ["evidence-boundary"]


def test_a_filled_evidence_boundary_passes(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(
        root,
        config,
        {
            "BR-001": entry(
                1,
                severity="high",
                body=f"{EVIDENCE_LABEL} whether the read path is reached at all.\n",
            )
        },
    )
    assert register_gate(root, config, bug_register(config)) == []


def test_an_empty_boundary_line_is_not_rescued_by_later_body_text(tmp_path: Path) -> None:
    # `[^\S\n]*` and not `\s*`: the latter crosses newlines under MULTILINE. Mutation: replace
    # it with `\s*` — this reddens.
    root, config = project(tmp_path)
    ledger(
        root,
        config,
        {"BR-001": entry(1, severity="high", body=f"{EVIDENCE_LABEL}\n\nlater prose\n")},
    )
    assert rules(root, config) == ["evidence-boundary"]


def test_the_severities_that_need_a_boundary_come_from_configuration(tmp_path: Path) -> None:
    root, config = project(
        tmp_path, '\n[ledger]\nevidence_boundary_required_for = ["high", "medium"]\n'
    )
    ledger(root, config, {"BR-001": entry(1, severity="medium")})
    assert rules(root, config) == ["evidence-boundary"]


def test_foreign_index_content_is_reported_and_staleness_is_not_named_beside_it(
    tmp_path: Path,
) -> None:
    # Regenerating is what deletes the content, so the stale row must not recommend it.
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1)})
    index = root / "docs" / "bug-reports.md"
    index.write_text(
        index.read_text(encoding="utf-8") + "\nAn operator's note.\n", encoding="utf-8"
    )
    (root / "docs" / "bugs" / "BR-002.md").write_text(entry(2), encoding="utf-8")
    assert rules(root, config) == ["foreign-index-content"]


def test_a_stale_index_is_reported_with_the_command_that_repairs_it(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1)})
    # Its own body: one byte-identical to BR-001 but for its `id:` is the tree a `renumber` killed
    # after its first write leaves, whose stale index names that renumber.
    own = entry(2, body="its own body\n")
    (root / "docs" / "bugs" / "BR-002.md").write_text(own, encoding="utf-8")
    found = register_gate(root, config, bug_register(config))
    assert [p.rule for p in found] == ["stale-index"]
    assert "stayfixed bugs index" in found[0].detail


@pytest.mark.parametrize(
    "kill", [2, 3, 4], ids=["before-pointer", "before-sibling-sweep", "before-second-sweep"]
)
def test_a_stale_index_a_killed_renumber_left_names_the_renumber_that_finishes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kill: int
) -> None:
    # A renumber killed part-way leaves the index it found, so `check` reported it stale and
    # sent the operator to `bugs index` — the remedy that turned the check green over two live
    # entries for one bug, or over mentions of the old number the sweep never reached. When the
    # stale index is exactly the one the move found, the line names the move that finishes it.
    # Mutation: `mutations/`'s "a stale index a killed renumber left is sent to bugs index".
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1), "BR-002": entry(2, related="[BR-001]")})
    (root / "src" / "a.py").write_text("# see BR-001\n", encoding="utf-8")
    (root / "docs" / "notes.md").write_text("BR-001 is the first one.\n", encoding="utf-8")
    with killed_at(monkeypatch, kill), pytest.raises(Killed):
        renumber(root, config, bug_register(config), "BR-001", "BR-009", today="2026-01-02")
    stale = [
        p.detail
        for p in register_gate(root, config, bug_register(config))
        if p.rule == "stale-index"
    ]
    assert stale == ["is stale; run: stayfixed bugs renumber BR-001 BR-009"]


def test_a_stale_index_more_than_one_renumber_explains_names_each_and_runs_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two entries that differ only in `id:` are what a `bugs new` run twice files, and a renumber
    # of either one, killed after its first write, leaves a tree both moves explain. The line
    # named the first it tried: run as advised, it voided the entry that was never moved and left
    # the other live beside its new number. So where more than one move explains the index, the
    # line names each and says that only the one that was started finishes it. Mutation:
    # `mutations/`'s "a stale index several renumbers explain names the first of them".
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1), "BR-002": entry(2)})
    with killed_at(monkeypatch, 2), pytest.raises(Killed):
        renumber(root, config, bug_register(config), "BR-002", "BR-009", today="2026-01-02")
    stale = [
        p.detail
        for p in register_gate(root, config, bug_register(config))
        if p.rule == "stale-index"
    ]
    assert stale == [
        "is stale; more than one unfinished renumber explains it, and only the one that was "
        "started finishes it: stayfixed bugs renumber BR-001 BR-009, or stayfixed bugs renumber "
        "BR-002 BR-009"
    ]


def _killed_at_the_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """`fsops.write_within` killed on the index write alone, every write before it made."""
    from stayfixed import fsops

    real = fsops.write_within

    def counted(within: Path, target: str, text: str, **kwargs: Any) -> None:
        if target == "docs/bug-reports.md":
            raise Killed(target)
        real(within, target, text, **kwargs)

    monkeypatch.setattr(fsops, "write_within", counted)


# The two trees whose sweep rewrites a row of the index before the index write: a void pointer an
# earlier move left toward the entry, which the sweep retitles toward the new number, and a live
# entry whose title names the moved one. The third is the legitimate user of a row the sweep left
# as it was: a title that named the new number before the move, which the sweep never touched. The
# fourth holds both kinds of row at once, so neither reading of the whole ledger explains it.
SWEPT_ROWS = (
    "a-chained-move",
    "a-title-naming-it",
    "a-title-naming-the-new-number",
    "both-kinds-of-row",
)


@pytest.mark.parametrize("tree", SWEPT_ROWS)
def test_a_renumber_killed_at_its_index_names_itself_when_its_sweep_rewrote_a_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tree: str
) -> None:
    # The sweep runs before the index write, so a row whose title names the old number already
    # names the new one: re-rendering the found index with the moved entry put back alone missed
    # it, and the line named `bugs index`, which turned the check green over a mention of the old
    # number nothing would ever rewrite, since the re-run then read the move as finished. So each
    # line is matched with the found index's as it was or as the sweep writes it; read back over
    # the whole ledger instead, both kinds of row at once still named `bugs index`. Mutations:
    # `mutations/`'s "a stale index a killed renumber left is matched with the sweep left in
    # place" and "a stale index a killed renumber left is matched only with the sweep applied".
    root, config = project(tmp_path)
    register = bug_register(config)

    def titled(number: int, named: str) -> str:
        return entry(number).replace("title: a title", f"title: follow-up to {named}")

    if tree == "a-chained-move":
        ledger(root, config, {"BR-001": entry(1), "BR-002": entry(2)})
        renumber(root, config, register, "BR-001", "BR-007", today="2026-01-02")
    elif tree == "both-kinds-of-row":
        entries = {"BR-001": titled(1, "BR-013"), "BR-002": titled(2, "BR-007")}
        ledger(root, config, {**entries, "BR-007": entry(7)})
    else:
        named = "BR-007" if tree == "a-title-naming-it" else "BR-013"
        ledger(root, config, {"BR-002": titled(2, named), "BR-007": entry(7)})
    (root / "docs" / "roadmap.md").write_text("also BR-007 matters\n", encoding="utf-8")
    with monkeypatch.context() as patched:
        _killed_at_the_index(patched)
        with pytest.raises(Killed):
            renumber(root, config, register, "BR-007", "BR-013", today="2026-01-02")
    stale = [p.detail for p in register_gate(root, config, register) if p.rule == "stale-index"]
    assert stale == ["is stale; run: stayfixed bugs renumber BR-007 BR-013"]
    renumber(root, config, register, "BR-007", "BR-013", today="2026-01-02")
    roadmap = (root / "docs" / "roadmap.md").read_text(encoding="utf-8")
    assert roadmap == "also BR-013 matters\n"
    assert register_gate(root, config, register) == []


def test_a_stale_index_beside_a_finished_renumber_is_sent_to_bugs_index(tmp_path: Path) -> None:
    # The legitimate user: a move that finished, and an entry edited since without the index.
    # Re-running that move would change nothing, so the line still names `bugs index`.
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1), "BR-002": entry(2)})
    renumber(root, config, bug_register(config), "BR-001", "BR-009", today="2026-01-02")
    sibling = root / "docs" / "bugs" / "BR-002.md"
    sibling.write_text(entry(2).replace("title: a title", "title: retitled"), encoding="utf-8")
    stale = [
        p.detail
        for p in register_gate(root, config, bug_register(config))
        if p.rule == "stale-index"
    ]
    assert stale == ["is stale; run: stayfixed bugs index"]


def test_a_mention_with_no_entry_is_reported_at_its_first_location(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1)})
    (root / "src" / "b.py").write_text("# BR-404\n", encoding="utf-8")
    (root / "src" / "a.py").write_text("x = 1\n# BR-404 again\n", encoding="utf-8")
    found = register_gate(root, config, bug_register(config))
    assert [(p.rule, p.path, p.line) for p in found] == [("dangling-mention", "src/a.py", 2)]
    assert "referenced 2 time(s)" in found[0].detail


def test_a_void_entry_keeps_its_number_resolvable(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    void = "---\nid: BR-001\ntitle: renumbered\nstatus: void\nfound: 2026-01-01\n---\n\nvoid\n"
    ledger(root, config, {"BR-001": void})
    (root / "src" / "a.py").write_text("# BR-001\n", encoding="utf-8")
    assert register_gate(root, config, bug_register(config)) == []


def test_a_citation_of_an_unfiled_entry_is_reported_from_a_document(tmp_path: Path) -> None:
    # Wider than the mention scan: it reads documents, because renaming an entry file leaves
    # the stale link in a docs-only commit.
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1)})
    (root / "docs" / "roadmap.md").write_text("see [x](bugs/BR-404.md)\n", encoding="utf-8")
    found = register_gate(root, config, bug_register(config))
    assert [(p.rule, p.path, p.line) for p in found] == [
        ("dangling-citation", "docs/roadmap.md", 1)
    ]


def test_a_worked_example_in_a_document_is_not_a_dangling_mention(tmp_path: Path) -> None:
    # Documents are outside the mention roots on purpose (plan documents spell invented
    # identifiers as worked examples of this very guard).
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1)})
    (root / "docs" / "plan.md").write_text("imagine BR-404 here\n", encoding="utf-8")
    assert register_gate(root, config, bug_register(config)) == []


def test_every_problem_names_a_repo_relative_path(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1, related="[BR-009]")})
    (root / "docs" / "bugs" / "BR-002.md").write_text("no frontmatter\n", encoding="utf-8")
    for problem in register_gate(root, config, bug_register(config)):
        assert not problem.path.startswith("/"), problem
    labels = [p.label for p in register_gate(root, config, bug_register(config))]
    assert "docs/bugs/BR-002.md [unreadable-entry]" in labels


def test_an_entry_that_is_not_utf8_is_reported_rather_than_crashing_the_check(
    tmp_path: Path,
) -> None:
    # The `unreadable-entry` rule exists for exactly this file, and an unguarded read meant it
    # could never fire from the one path that reaches it: the `UnicodeDecodeError` escaped
    # `register_gate()` and `cli.run` turned a fixable repository condition into exit 2.
    root, config = project(tmp_path)
    ledger(root, config, {"BR-001": entry(1)})
    (root / "docs" / "bugs" / "BR-002.md").write_bytes(b"---\nid: BR-002\ntitle: \xff\n---\n")
    found = register_gate(root, config, bug_register(config))
    assert "docs/bugs/BR-002.md [unreadable-entry]" in [p.label for p in found]
    unreadable = next(p for p in found if p.rule == "unreadable-entry")
    assert "is not valid UTF-8" in unreadable.detail


def test_a_duplicate_identifier_names_at_most_the_listed_limit_of_its_files(
    tmp_path: Path,
) -> None:
    # The files claiming one identifier are bounded in number by nothing but the ledger, so the
    # detail names the first `LISTED_LIMIT` and counts the rest. Nothing is lost from `--json`:
    # only one file's name can be its identifier, so every other holder is named by an
    # `id-mismatch` finding of its own. Mutation (oracle): `mutations/`'s "a duplicate identifier
    # names every file that claims it" -> the detail equality reddens.
    root, config = project(tmp_path)
    names = [f"BR-{n:03}" for n in range(1, LISTED_LIMIT + 4)]
    ledger(root, config, dict.fromkeys(names, entry(1)))
    found = register_gate(root, config, bug_register(config))
    duplicate = [p for p in found if p.rule == "duplicate-id"]
    shown = ", ".join(f"docs/bugs/{name}.md" for name in names[:LISTED_LIMIT])
    assert [p.detail for p in duplicate] == [
        f"BR-001 is claimed by more than one file: {shown}, and 3 more"
    ]
    mismatched = {p.path for p in found if p.rule == "id-mismatch"}
    assert mismatched == {f"docs/bugs/{name}.md" for name in names[1:]}


def test_a_duplicate_identifier_names_its_own_file_first_whatever_the_sort(
    tmp_path: Path,
) -> None:
    # The one holder with no `id-mismatch` finding is the file named after the identifier, so
    # the capped detail names it first: otherwise, sorted last past the cap, it was named nowhere
    # in `--json`. Every other holder is named by a finding of its own. Mutation (oracle):
    # `mutations/`'s "a duplicate identifier names its holders in path order" -> this reddens.
    root, config = project(tmp_path)
    names = [f"BR-{n:03}" for n in range(1, LISTED_LIMIT + 4)]
    ledger(root, config, dict.fromkeys(names, entry(len(names))))
    found = register_gate(root, config, bug_register(config))
    shown = ", ".join(f"docs/bugs/{name}.md" for name in [names[-1], *names[: LISTED_LIMIT - 1]])
    assert [p.detail for p in found if p.rule == "duplicate-id"] == [
        f"{names[-1]} is claimed by more than one file: {shown}, and 3 more"
    ]
    mismatched = {p.path for p in found if p.rule == "id-mismatch"}
    assert mismatched == {f"docs/bugs/{name}.md" for name in names[:-1]}
