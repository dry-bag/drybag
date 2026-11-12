from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from drybag import binding
from drybag.cli import build_parser, discover_registrars, run
from drybag.config.paths import data_directory
from drybag.findings import LISTED_LIMIT
from drybag.printed import UNPRINTABLE
from tests.crafted import CRAFTED, assert_never_raw
from tests.gitfixture import git

CONFIG = """
[drybag]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"

[memory]
mode = "local-only"
groups = ["developer", "project-volatile"]
index_extra = []
"""

NOTE = (
    '---\nname: {name}\ndescription: "{name} description"\n'
    'index: "t → {name}"\n{meta}---\n\n{body}\n'
)


def invoke(argv: list[str]) -> int:
    return run(argv, parser=build_parser(discover_registrars()))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    base = root / ".drybag" / "local" / "memory"
    for group in ("developer", "project-volatile"):
        (base / group).mkdir(parents=True)
    # The *short* note is the one whose name sorts first. Different body lengths alone were not
    # enough and the comment that used to sit here said otherwise: with "a" long and "v" short,
    # `-words` order and `name` order are the same order, so name-only, no-sort and
    # drop-the-tiebreak every one of them reproduced it and none of them could be caught. Now
    # the two disagree, and `test_the_inventory_sorts_by_word_count_then_by_name` adds the
    # equal-length pair that is the only thing the tiebreak decides.
    (base / "developer" / "a.md").write_text(
        NOTE.format(
            name="a",
            meta="metadata:\n  type: project\n  startup: 1\n",
            body="Body.",
        ),
        encoding="utf-8",
    )
    (base / "project-volatile" / "v.md").write_text(
        NOTE.format(
            name="v",
            meta="metadata:\n  type: project\n  as_of: 2026-09-01\n",
            body="Body. Body. Body. Body. Body.",
        ),
        encoding="utf-8",
    )
    (root / "drybag.toml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "machine.toml").write_text("", encoding="utf-8")
    return root


def common(project: Path) -> list[str]:
    return ["--root", str(project), "--machine", str(project.parent / "machine.toml")]


def test_the_memory_group_and_its_commands_are_discovered() -> None:
    help_text = build_parser(discover_registrars()).format_help()
    assert "memory" in help_text


def test_index_check_reports_drift_with_exit_one(project: Path) -> None:
    # Three invocations on purpose: red, write, green. One would pass either way.
    assert invoke(["memory", "index", "--check", *common(project)]) == 1
    assert invoke(["memory", "index", *common(project)]) == 0
    assert invoke(["memory", "index", "--check", *common(project)]) == 0


def test_an_unknown_bundle_is_refused(project: Path) -> None:
    assert invoke(["memory", "session-context", "--bundle", "nonsense", *common(project)]) == 2


def test_a_store_whose_notes_live_in_the_repository_delivers_them_as_data_and_no_standing_rule(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # With nothing promoted: the volatile note arrives inside the region that marks it as data,
    # and the note ranked `startup: 1` is not a standing rule.
    from drybag.memory.trust import DELIMITER

    assert (
        invoke(["memory", "session-context", "--bundle", "standing-rules", *common(project)]) == 0
    )
    assert capsys.readouterr().out.strip() == ""
    assert (
        invoke(["memory", "session-context", "--bundle", "volatile-notes", *common(project)]) == 0
    )
    out = capsys.readouterr().out
    assert DELIMITER in out
    assert out.index(DELIMITER) < out.index("Body. Body.")
    assert not (project.parent / "trust.json").exists()


def test_an_unreached_part_prints_nothing_and_succeeds(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["memory", "session-context", "--bundle", "volatile-notes", "--part", "3"]
    assert invoke([*argv, *common(project)]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_inventory_reports_what_a_sweep_acts_on(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert invoke(["memory", "inventory", "--json", *common(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["notes"] == 2
    # Nothing promoted: "a" ranks `startup: 1` and is no standing rule until it is.
    assert (payload["standing"], payload["unreviewed"]) == (0, 2)
    assert invoke(["memory", "promote", "--changed", *common(project)]) == 0
    capsys.readouterr()
    assert invoke(["memory", "inventory", "--json", *common(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert (payload["standing"], payload["unreviewed"]) == (1, 0)
    assert all(entry["reviewed"] for entry in payload["entries"])
    # "v" carries five words to "a"'s one, so word count decides this and the alphabet does not.
    assert [entry["name"] for entry in payload["entries"]] == ["v", "a"]


def test_the_inventory_sorts_by_word_count_then_by_name(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `-words` first and `name` only to break a tie, which takes four notes to state: two of
    # different lengths whose lengths and names disagree, and two of the *same* length reached
    # in an order the alphabet does not give. `walk` reads groups in configured order and each
    # group's files in name order, so "z" (developer) arrives before "b" (project-volatile) —
    # a stable sort that dropped the tiebreak would leave them that way round.
    base = project / ".drybag" / "local" / "memory"
    (base / "developer" / "z.md").write_text(
        NOTE.format(name="z", meta="", body="Body. Body. Body."), encoding="utf-8"
    )
    (base / "project-volatile" / "b.md").write_text(
        NOTE.format(name="b", meta="", body="Body. Body. Body."), encoding="utf-8"
    )
    assert invoke(["memory", "inventory", "--json", *common(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [entry["name"] for entry in payload["entries"]] == ["v", "b", "z", "a"]


def test_a_project_with_no_store_fails_with_a_reason(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    (root / "drybag.toml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "machine.toml").write_text("", encoding="utf-8")
    assert (
        invoke(
            ["memory", "index", "--root", str(root), "--machine", str(tmp_path / "machine.toml")]
        )
        == 1
    )


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

OVERLAY_CONFIG = """
[drybag]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"

[memory]
mode = "overlay"
groups = ["developer"]
index_extra = []
"""

REMOTE = "git@example.com:acme/widget.git"
BARE_NOTE = "---\nname: n\ndescription: n description\nmetadata:\n  type: project\n---\n\nBody.\n"


def _composed(root: Path) -> Path:
    """The composed store of `root`'s binding id: the overlay-mode store `attach` builds."""
    from drybag.memory.store import composed_directory

    id = binding.read_id(root)
    assert id is not None
    return composed_directory(id)


@pytest.fixture
def overlay_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", REMOTE)
    overlay = tmp_path / "overlay"
    (overlay / "common" / "memory").mkdir(parents=True)
    (overlay / "common" / "memory" / "n.md").write_text(BARE_NOTE, encoding="utf-8")
    (overlay / "projects" / "widget" / "memory").mkdir(parents=True)
    (overlay / "projects" / "widget" / "project.toml").write_text(
        f'remote = "{REMOTE}"\n', encoding="utf-8"
    )
    binding.record(root, "widget", REMOTE)
    memory = _composed(root)
    memory.mkdir(parents=True)
    (memory / "developer").symlink_to(overlay / "common" / "memory", target_is_directory=True)
    (root / "drybag.toml").write_text(OVERLAY_CONFIG, encoding="utf-8")
    (tmp_path / "machine.toml").write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    return root


@needs_git
def test_indexing_writes_through_the_symlinked_index_every_reader_sources(
    overlay_project: Path,
) -> None:
    # `write_atomically` ends in `os.replace`, which replaces the *link*, not its target. Every
    # reader — the harvest, the worktree tree, the trust question — routes through
    # `index.index_source`; the one writer did not. One `os.replace` strands the overlay's
    # shared copy on every other machine, turns the index into a real file inside the
    # repository, and so flips `in_repository` to True and closes the gate on it for good.
    overlay = overlay_project.parent / "overlay"
    shared = overlay / "projects" / "widget" / "memory" / "MEMORY.md"
    shared.write_text("# shared index\n", encoding="utf-8")
    link = _composed(overlay_project) / "MEMORY.md"
    link.symlink_to(shared)

    assert invoke(["memory", "index", *common(overlay_project)]) == 0

    assert link.is_symlink(), "the link every reader sources was replaced by a real file"
    assert "# Memory Index" in shared.read_text(encoding="utf-8"), "the overlay copy went stale"


def test_index_check_answers_about_the_file_the_index_actually_is(project: Path) -> None:
    # `check_index` read `store.path / MEMORY.md` through `is_file()`, which follows the link,
    # while `index_source` — the rule every reader applies — refuses a symlinked index outright
    # outside overlay mode. So `--check` compared the render against a file no reader sources:
    # exit 0, "index is current", and every reader refusing it. CI green, model empty-handed.
    assert invoke(["memory", "index", *common(project)]) == 0
    index = project / ".drybag" / "local" / "memory" / "MEMORY.md"
    elsewhere = project.parent / "elsewhere.md"
    elsewhere.write_text(index.read_text(encoding="utf-8"), encoding="utf-8")
    index.unlink()
    index.symlink_to(elsewhere)
    # The refusal is the same one the writer makes, so `--check` reports it the same way.
    assert invoke(["memory", "index", "--check", *common(project)]) == 2
    assert invoke(["memory", "index", *common(project)]) == 2
    assert index.is_symlink(), "the refused link was clobbered instead"


@needs_git
def test_the_machines_own_index_is_still_harvested_into_the_machines_notes(
    overlay_project: Path,
) -> None:
    # The rule is one trust domain, not "never harvest in overlay mode". A symlinked index into
    # this project's own overlay share is a legitimate member of the composed store `attach`
    # creates, and the curation a session wrote there is exactly what the harvest exists to
    # keep. A fix that refused this would delete the feature instead of gating it.
    share = overlay_project.parent / "overlay" / "projects" / "widget" / "memory"
    curated = "n trigger \u2192 the answer, written by a session on this machine"
    (share / "MEMORY.md").write_text(f"- [{curated}](developer/n.md)\n", encoding="utf-8")
    (_composed(overlay_project) / "MEMORY.md").symlink_to(share / "MEMORY.md")
    note = overlay_project.parent / "overlay" / "common" / "memory" / "n.md"

    assert invoke(["memory", "index", *common(overlay_project)]) == 0

    written = note.read_text(encoding="utf-8")
    assert curated in written
    assert "index_provenance: native" in written


@needs_git
def test_memory_index_bootstraps_a_dangling_attach_link(
    overlay_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `attach` creates the index symlink before any content exists behind it — that ordering is
    # the whole point of a link over a copy. `index_source` correctly answers "nothing to read"
    # for a dangling link, but `_destination` used to read that same `None` as "refused", the
    # answer meant for a link resolving *outside* the permitted roots, and raised `Refusal`
    # (exit 2). The very first `memory index` an overlay project ever runs hits exactly this
    # shape — unlike the test above, which pre-creates the shared file and so never exercised
    # it. `--check` afterwards proves the write and the read agree about which file this is.
    share = overlay_project.parent / "overlay" / "projects" / "widget" / "memory" / "MEMORY.md"
    link = _composed(overlay_project) / "MEMORY.md"
    link.symlink_to(share)
    assert not share.exists()

    assert invoke(["memory", "index", *common(overlay_project)]) == 0

    assert link.is_symlink(), "the bootstrap write replaced the link instead of writing through it"
    assert share.is_file()
    assert "# Memory Index" in share.read_text(encoding="utf-8")
    capsys.readouterr()
    assert invoke(["memory", "index", "--check", *common(overlay_project)]) == 0


@needs_git
def test_a_refused_note_or_pointer_is_named_without_its_crafted_bytes(
    overlay_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The refusal names what it held back, and the name is the repository's: a
    # `memory.index_extra` entry, which `_extra` checks for line breaks and link syntax but not
    # for an escape sequence. It reached the terminal raw. `--json` still names it. Mutation: drop
    # `printable` from `_printed`, or join the list raw in `_publish` — each reddens.
    config = overlay_project / "drybag.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "index_extra = []", 'index_extra = ["docs/x\\u001b[2J.md"]'
        ),
        encoding="utf-8",
    )
    share = overlay_project.parent / "overlay" / "projects" / "widget" / "memory" / "MEMORY.md"
    share.write_text("# shared index\n", encoding="utf-8")
    (_composed(overlay_project) / "MEMORY.md").symlink_to(share)

    assert invoke(["memory", "index", *common(overlay_project)]) == 0
    captured = capsys.readouterr()
    assert f"{UNPRINTABLE} took no pointer" in captured.out
    assert_never_raw(captured.out, captured.err)
    assert invoke(["memory", "index", "--check", "--json", *common(overlay_project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["refused_extra"] == ["docs/x\x1b[2J.md"]


LONG_INDEX_NOTE = '---\nname: big\ndescription: big description\nindex: "{line}"\n---\n\nBody.\n'


def test_a_note_the_store_cannot_parse_is_counted_and_fails_the_check(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `unreadable` reached `Result.data` and neither summary nor the exit code, so CI stayed
    # green while a note the store holds was invisible to routing, the standing rules and
    # volatile injection — and nothing a person runs by hand said a word about it.
    notes = project / ".drybag" / "local" / "memory" / "developer"
    (notes / "broken.md").write_text("no frontmatter at all\n", encoding="utf-8")
    assert invoke(["memory", "index", *common(project)]) == 0
    assert "broken.md" in capsys.readouterr().out
    assert invoke(["memory", "index", "--check", *common(project)]) == 1
    assert "broken.md" in capsys.readouterr().out


def test_an_unparseable_note_with_a_crafted_name_is_counted_and_never_printed_raw(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The file name is whatever the store holds, and in-repo mode that is a committed file: a
    # line break and `::error::` forged a workflow command in CI, an escape sequence reached the
    # terminal. `--json` still carries the path. Mutation: drop `printable` from `_printed` —
    # this reddens; print the absolute path instead of the store-relative one — the last
    # assertion reddens.
    notes = project / ".drybag" / "local" / "memory" / "developer"
    crafted = f"{CRAFTED}.md"
    (notes / crafted).write_text("no frontmatter at all\n", encoding="utf-8")
    assert invoke(["memory", "index", "--check", *common(project)]) == 1
    captured = capsys.readouterr()
    assert (
        f"1 file(s) in the store cannot be read as a note, so they reach neither the index "
        f"nor any injection bundle: {UNPRINTABLE}" in captured.out
    )
    assert_never_raw(captured.out, captured.err)
    assert invoke(["memory", "index", "--check", "--json", *common(project)]) == 1
    assert json.loads(capsys.readouterr().out)["unreadable"][0]["path"].endswith(crafted)
    # A name inside the grammar is still named, so the ordinary case keeps its pointer.
    (notes / crafted).rename(notes / "broken.md")
    assert invoke(["memory", "index", "--check", *common(project)]) == 1
    assert "developer/broken.md" in capsys.readouterr().out


@pytest.mark.parametrize("check", [True, False], ids=["check", "write"])
def test_an_unreadable_note_is_named_store_relative_on_the_line_and_in_json_alike(
    project: Path, capsys: pytest.CaptureFixture[str], check: bool
) -> None:
    # The line named the note inside the store and `--json`'s `unreadable` named it by its
    # absolute path, so one command gave two answers about one file, and the second carried the
    # machine's own directory layout. Both are store-relative now, as the index line names them.
    # Mutation: build `IndexCheck.unreadable` from the absolute path in `check_index` — this
    # reddens.
    notes = project / ".drybag" / "local" / "memory" / "developer"
    (notes / "broken.md").write_text("no frontmatter at all\n", encoding="utf-8")
    argv = ["memory", "index", *(["--check"] if check else []), "--json", *common(project)]
    assert invoke(argv) == (1 if check else 0)
    data = json.loads(capsys.readouterr().out)
    assert [entry["path"] for entry in data["unreadable"]] == ["developer/broken.md"]
    assert "developer/broken.md" in data["summary"]


def test_index_check_json_gives_each_unreadable_reason(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--json` named the files that cannot be read as notes and dropped why, so a person had to
    # open each one to learn what the reader refused. Each reason is store-relative, as the path
    # is: the machine's own directory layout is in neither.
    notes = project / ".drybag" / "local" / "memory" / "developer"
    (notes / "bare.md").write_text("no frontmatter at all\n", encoding="utf-8")
    (notes / "open.md").write_text("---\nname: open\n", encoding="utf-8")
    assert invoke(["memory", "index", "--check", "--json", *common(project)]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["unreadable"] == [
        {"path": "developer/bare.md", "reason": "no frontmatter; a note opens with '---'"},
        {"path": "developer/open.md", "reason": "frontmatter is never closed"},
    ]


def test_many_unreadable_notes_are_counted_and_named_at_most_to_the_listed_limit(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `_printed` joined every name it was handed, while every other summary line takes
    # `findings.listed`'s one cap: a store of a few hundred notes that stopped parsing at once —
    # a frontmatter change applied by hand — printed every one of them. The line counts them all
    # and names `LISTED_LIMIT`; `--json` names every one. The refused-harvest, refused-publish and
    # refused-pointer lines go through the same `_printed`. Mutation: join uncapped in
    # `_printed` — this reddens.
    store = project / ".drybag" / "local" / "memory"
    broken = [f"developer/broken-{number:02d}.md" for number in range(LISTED_LIMIT + 3)]
    for name in broken:
        (store / name).write_text("no frontmatter at all\n", encoding="utf-8")
    assert invoke(["memory", "index", "--check", "--json", *common(project)]) == 1
    data = json.loads(capsys.readouterr().out)
    line = data["summary"]
    assert f"{len(broken)} file(s) in the store cannot be read as a note" in line
    assert [name for name in broken if name in line] == broken[:LISTED_LIMIT]
    assert f"{broken[LISTED_LIMIT - 1]}, and 3 more" in line
    assert [entry["path"] for entry in data["unreadable"]] == broken


def test_the_check_summary_never_says_current_while_the_exit_code_says_otherwise(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The summary branched on `drifted` alone and the exit code on `drifted or over_budget`,
    # so one run printed "index is current: N words, M lines" and exited 1 in the same breath.
    config = project / "drybag.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\n[budgets]\nmemory_index_words = 1\n",
        encoding="utf-8",
    )
    assert invoke(["memory", "index", *common(project)]) == 0
    capsys.readouterr()
    assert invoke(["memory", "index", "--check", *common(project)]) == 1
    out = capsys.readouterr().out
    assert "index is current" not in out
    assert "budget" in out


def test_an_index_past_a_harness_cap_is_surfaced_rather_than_computed_and_dropped(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `over_caps` names the limits at which the harness truncates `MEMORY.md`. The write path
    # computed it and then dropped it entirely — absent from the data, absent from the
    # summary, exit 0 — so an index the harness will cut looked exactly like a healthy one.
    notes = project / ".drybag" / "local" / "memory" / "developer"
    (notes / "big.md").write_text(LONG_INDEX_NOTE.format(line="x" * 30000), encoding="utf-8")
    assert invoke(["memory", "index", "--json", *common(project)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["over_caps"] == ["memory_index_bytes"]
    assert invoke(["memory", "index", "--check", *common(project)]) == 1
    out = capsys.readouterr().out
    assert "memory_index_bytes" in out
    assert "index is current" not in out


def test_the_standing_total_counts_what_the_standing_bundle_actually_injects(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The standing bundle excludes a volatile-group note even when it carries `startup` — a
    # perishable fact is not a standing rule — while `totals` counted every note with one. The
    # sweep skill's headline number therefore disagreed with what reaches the model, and a
    # number that means something other than its name is worse than no number at all. Every note
    # is promoted first, so the count is held to the selection the bundle makes of the owner's
    # notes.
    volatile = project / ".drybag" / "local" / "memory" / "project-volatile"
    (volatile / "loud.md").write_text(
        NOTE.format(name="loud", meta="metadata:\n  type: project\n  startup: 1\n", body="Loud."),
        encoding="utf-8",
    )
    assert invoke(["memory", "promote", "--changed", *common(project)]) == 0
    capsys.readouterr()
    assert invoke(["memory", "inventory", "--json", *common(project)]) == 0
    counted = json.loads(capsys.readouterr().out)["standing"]
    argv = ["memory", "session-context", "--bundle", "standing-rules", *common(project)]
    assert invoke(argv) == 0
    injected = capsys.readouterr().out.count("### ")
    assert counted == injected == 1


# --- repository text never reaches stdout unwrapped -------------------------------------


def test_a_missing_store_directory_is_said_in_the_resolvers_own_words(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A store with no directory is the commonest reason there is nothing to walk. The reason is
    # drybag's text and prints; the store's path is the repository's and stays inside the data
    # region, which `cli._report` prints on stdout under `--json` as well, so the invariant
    # `refusal_reason`'s docstring states holds only where the detail arrives inside it.
    # Mutations (declared): `mutations/`'s "a missing store directory is reported with no reason
    # of its own", and "a store refusal prints its repository-authored detail before the data
    # region", which reddens the split below.
    from drybag.memory.api import DELIMITER

    shutil.rmtree(project / ".drybag" / "local" / "memory")
    assert invoke(["memory", "inventory", *common(project)]) == 1
    lead, opened, region = capsys.readouterr().err.partition(DELIMITER)
    assert "the memory store's directory does not exist" in lead
    # The path is kept, because a person needs it, and it is never printed ahead of the marker
    # that says it is data.
    assert opened and ".drybag" in region
    assert ".drybag" not in lead
    assert invoke(["--json", "memory", "inventory", *common(project)]) == 1
    assert json.loads(capsys.readouterr().out)["summary"].count(DELIMITER) == 2


SECOND_NOTE = (
    "---\nname: second\ndescription: second description\nmetadata:\n  type: project\n---\n\nB.\n"
)


@needs_git
def test_overlay_mode_reads_the_composed_store_whatever_store_is_named(
    overlay_project: Path,
) -> None:
    # In overlay mode the store is the composed one the binding names. `--store` was read there
    # too, so a directory a repository chose, committing links into the overlay, stood in for it:
    # its index lines were harvested into overlay notes and its notes' lines published into the
    # overlay's index. Mutation (oracle): `mutations/`'s "overlay mode reads a named store".
    from drybag.config.loader import load
    from drybag.memory.store import resolved

    chosen = overlay_project / "chosen"
    (chosen / "developer").mkdir(parents=True)
    machine = overlay_project.parent / "machine.toml"
    store, why = resolved(
        overlay_project,
        load(overlay_project, machine=machine),
        override=str(chosen),
        machine=machine,
    )
    assert why is None and store is not None
    assert store.path == _composed(overlay_project)


def _binding_project(tmp_path: Path, cause: str) -> tuple[Path, Path]:
    """An attached-shaped overlay project whose binding fails for exactly one of its causes: this
    machine binds nothing to the checkout, even with the overlay recording its very remote, or the
    overlay the machine records is not there."""
    root = tmp_path / "project"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", REMOTE)
    overlay = tmp_path / "overlay"
    (overlay / "common" / "memory").mkdir(parents=True)
    (overlay / "projects" / "widget" / "memory").mkdir(parents=True)
    (overlay / "projects" / "widget" / "project.toml").write_text(
        f'remote = "{REMOTE}"\n', encoding="utf-8"
    )
    (root / "docs" / "memory").mkdir(parents=True)
    (root / "docs" / "memory" / "developer").symlink_to(overlay / "common" / "memory")
    (root / "drybag.toml").write_text(OVERLAY_CONFIG, encoding="utf-8")
    machine = tmp_path / "machine.toml"
    # A machine record naming a directory that is not there: the overlay moved, or this machine
    # never cloned it. Its own cause, and not "no record of this project".
    recorded = tmp_path / "moved-away" if cause == "overlay-gone" else overlay
    machine.write_text(f'[overlay]\nroot = "{recorded}"\n', encoding="utf-8")
    return root, machine


# Each cause's own words, which only its own refusal may carry.
BINDING_CAUSES = {
    "no-record": "records no binding of this checkout",
    "overlay-gone": "is not a directory on this machine",
}


@needs_git
@pytest.mark.parametrize("cause", sorted(BINDING_CAUSES))
def test_a_binding_refusal_names_its_own_cause_and_the_way_out_that_fits_it(
    tmp_path: Path, cause: str
) -> None:
    # `store._bound` answered one `False` for several causes, and the refusal said "run
    # `drybag attach`" for all of them. Each cause says itself, in drybag's own words before
    # the region that holds the repository's.
    from drybag.memory.trust import DELIMITER
    from tests.cli import cli

    root, machine = _binding_project(tmp_path, cause)
    code, out, err = cli(root, tmp_path, "memory", "index", machine=machine)
    assert code == 1
    said = out + err
    lead = said.split(DELIMITER, 1)[0]
    assert BINDING_CAUSES[cause] in lead
    for other, words in BINDING_CAUSES.items():
        if other != cause:
            assert words not in said, other
    assert "--trust-remote" not in said
    if cause == "overlay-gone":
        # A recorded overlay that is not there is answered by recording where it is now, which
        # `setup --overlay` does; `attach --store <new place>` refuses a store outside the
        # recorded overlay, so it is not the first thing to run.
        assert "setup" in lead and "--overlay" in lead
        # The root is the owner's own machine configuration, not the repository's: it prints as
        # drybag's own words, quoted, and never inside the region that marks repository text.
        # Mutation: `mutations/`'s "the recorded overlay root is printed as repository text".
        assert "moved-away" in lead
        assert DELIMITER not in said


def _bound_without_file(tmp_path: Path, *, layer: str = '[memory]\nmode = "overlay"\n') -> Path:
    """`overlay_project` with no `drybag.toml`: this machine binds the checkout to `widget`, and
    the overlay's project layer (`layer`) is all that says the memory is the overlay's."""
    root = tmp_path / "project"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", REMOTE)
    overlay = tmp_path / "overlay"
    (overlay / "common" / "memory").mkdir(parents=True)
    (overlay / "common" / "memory" / "n.md").write_text(BARE_NOTE, encoding="utf-8")
    home = overlay / "projects" / "widget"
    (home / "memory").mkdir(parents=True)
    (home / "project.toml").write_text(f'remote = "{REMOTE}"\n', encoding="utf-8")
    (home / "drybag.toml").write_text(layer, encoding="utf-8")
    (home / "memory" / "MEMORY.md").write_text("# shared index\n", encoding="utf-8")
    binding.record(root, "widget", REMOTE)
    composed = _composed(root)
    composed.mkdir(parents=True)
    (composed / "developer").symlink_to(overlay / "common" / "memory", target_is_directory=True)
    (composed / "MEMORY.md").symlink_to(home / "memory" / "MEMORY.md")
    (tmp_path / "machine.toml").write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    return root


@needs_git
def test_memory_index_renders_in_a_bound_checkout_with_no_file(tmp_path: Path) -> None:
    # Every memory command refused such a checkout as having no configuration, though `attach`
    # had bound it and its overlay's layers say where the memory is. Mutation: `mutations/`'s
    # "bound_config answers for an unbound checkout" is the other side of this seam.
    root = _bound_without_file(tmp_path)
    assert invoke(["memory", "index", *common(root)]) == 0
    shared = tmp_path / "overlay" / "projects" / "widget" / "memory" / "MEMORY.md"
    assert "# Memory Index" in shared.read_text(encoding="utf-8")


@needs_git
def test_an_unbound_checkout_with_no_file_is_still_told_to_init(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same checkout and overlay, but nothing on this machine binds it: a clone gains no
    # configuration from the overlay it never attached to, so every command that needs a store
    # still refuses, naming the file it lacks.
    root = _bound_without_file(tmp_path)
    id = binding.read_id(root)
    assert id is not None
    (data_directory() / binding.BINDINGS / f"{id}.toml").unlink()
    for argv in (
        ["index"],
        ["index", "--check"],
        ["inventory"],
        ["promote", "--changed"],
    ):
        assert invoke(["memory", *argv, *common(root)]) == 1, argv
        assert "does not exist; write one" in capsys.readouterr().err, argv


@needs_git
def test_the_unreviewed_count_is_said_in_a_bound_checkout_with_no_file(tmp_path: Path) -> None:
    # The `SessionStart` handler reads the configuration the memory commands read: with no file it
    # said nothing of a store the machine binds and the owner has notes in.
    from drybag.config.machine import machine_config_path
    from drybag.config.session import session_config
    from drybag.hooks.api import HookEvent
    from drybag.memory.hooks import UNREVIEWED_COUNT, register

    root = _bound_without_file(tmp_path)
    # A hook reads the machine file at its place under `HOME` (the suite's scratch one).
    where = machine_config_path()
    assert where is not None
    where.parent.mkdir(parents=True)
    where.write_text((tmp_path / "machine.toml").read_text(encoding="utf-8"), encoding="utf-8")
    (handler,) = [h for h in register() if h.name == "unreviewed-notes"]
    event = HookEvent("SessionStart", "s1", None, None, {}, root, root, {})
    assert handler.run(event, session_config(root)).context == UNREVIEWED_COUNT.format(count=1)
