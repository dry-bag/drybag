"""A note counts as the owner's only once promoted, and only at the bytes that were promoted.

The record is a `reviewed` entry in `trust.json`, beside the machine file and outside every tree,
so a note a repository ships, one the harness's writer or an agent wrote, and one the owner edited
after promoting it all arrive the same way: unreviewed, as data, and never as a standing rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.memory.commands import NOT_A_NOTE, NOTHING_NAMED
from stayfixed.memory.hooks import UNREVIEWED_COUNT, register
from stayfixed.memory.notes import walk
from stayfixed.memory.reviewed import REVIEWED, UNREVIEWED, status
from stayfixed.memory.store import Store, resolve
from stayfixed.memory.trust import DELIMITER
from stayfixed.trust.record import RECORD, SANDBOXED, recorded
from tests.cli import cli
from tests.sandboxed import refuse_writes_under
from tests.sessions import session_of

CONFIG = """
[stayfixed]
version = "0.1.0"

[project]
name = "widget"

[memory]
mode = "local-only"
groups = ["developer", "project-volatile"]
"""


def _note(name: str, *, startup: str = "", body: str = "Body.") -> str:
    meta = "metadata:\n  type: project\n" + (f"  startup: {startup}\n" if startup else "")
    return f'---\nname: {name}\ndescription: "{name} description"\n{meta}---\n\n{body}\n'


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    base = root / ".stayfixed" / "local" / "memory"
    for group in ("developer", "project-volatile"):
        (base / group).mkdir(parents=True)
    (base / "developer" / "rule.md").write_text(
        _note("rule", startup="1", body="RULE-BODY"), "utf-8"
    )
    (base / "developer" / "other.md").write_text(
        _note("other", startup="2", body="OTHER-BODY"), "utf-8"
    )
    (root / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    return root


def _store(root: Path, tmp_path: Path) -> Store:
    machine = tmp_path / "absent.toml"
    store = resolve(root, load(root, machine=machine), machine=machine)
    assert store is not None
    return store


def _status_of(root: Path, tmp_path: Path, name: str) -> str:
    store = _store(root, tmp_path)
    notes = {n.name: n for n in walk(store.path, list(store.groups)).notes}
    return status(store.machine, notes[name])


def _bundle(root: Path, tmp_path: Path, bundle: str) -> str:
    code, out, err = cli(root, tmp_path, "memory", "session-context", "--bundle", bundle)
    assert code == 0, err
    return out


def test_a_note_with_no_record_is_unreviewed_and_no_standing_rule_whatever_it_ranks(
    tmp_path: Path,
) -> None:
    # `startup: 1` is the note's own claim, and a claim a note makes about itself is what a clone,
    # the native writer or an agent can write. With no record it reaches the session in the
    # volatile bundle, inside the data region and labelled, and never as a standing rule.
    # Mutation (oracle): `mutations/`'s "the standing rules admit an unreviewed note".
    root = _project(tmp_path)
    assert _status_of(root, tmp_path, "rule") == UNREVIEWED
    assert "RULE-BODY" not in _bundle(root, tmp_path, "standing-rules")
    volatile = _bundle(root, tmp_path, "volatile-notes")
    assert "### rule [unreviewed]" in volatile
    region = volatile[volatile.index(DELIMITER) :]
    assert "RULE-BODY" in region


def test_promote_marks_a_note_reviewed_and_it_enters_the_standing_rules(tmp_path: Path) -> None:
    root = _project(tmp_path)
    code, out, err = cli(root, tmp_path, "memory", "promote", "developer/rule.md", "--json")
    assert code == 0, err
    promoted = json.loads(out)["promoted"]
    assert [entry["path"] for entry in promoted] == ["developer/rule.md"]
    assert len(promoted[0]["digest"]) == 64
    assert _status_of(root, tmp_path, "rule") == REVIEWED
    assert "RULE-BODY" in _bundle(root, tmp_path, "standing-rules")
    assert "RULE-BODY" not in _bundle(root, tmp_path, "volatile-notes")
    # Only the note named: the other is no more reviewed than it was.
    assert _status_of(root, tmp_path, "other") == UNREVIEWED
    # The line says what was recorded, the path and the digest both.
    code, out, _ = cli(root, tmp_path, "memory", "promote", "developer/other.md")
    assert code == 0 and "developer/other.md" in out and len(out.split()[-1]) == 64


def test_an_edit_after_promotion_makes_that_note_unreviewed_and_moves_no_other(
    tmp_path: Path,
) -> None:
    # The record holds the digest of the bytes promoted, so an edit is a new note to review, and
    # the other note's record still holds. Mutation (oracle): `mutations/`'s "a stale digest
    # still reads as reviewed".
    root = _project(tmp_path)
    assert cli(root, tmp_path, "memory", "promote", "--changed")[0] == 0
    assert _status_of(root, tmp_path, "rule") == REVIEWED
    assert _status_of(root, tmp_path, "other") == REVIEWED
    path = root / ".stayfixed" / "local" / "memory" / "developer" / "rule.md"
    path.write_text(_note("rule", startup="1", body="RULE-BODY, edited"), "utf-8")
    assert _status_of(root, tmp_path, "rule") == UNREVIEWED
    assert _status_of(root, tmp_path, "other") == REVIEWED
    standing = _bundle(root, tmp_path, "standing-rules")
    assert "OTHER-BODY" in standing and "RULE-BODY" not in standing


IN_REPO = CONFIG.replace('mode = "local-only"', 'mode = "in-repo"') + (
    '\n[paths]\nmemory = "notes"\n'
)


def test_a_note_promoted_in_the_main_checkout_is_reviewed_in_a_linked_worktree(
    tmp_path: Path,
) -> None:
    # The record matches a note by the digest of its bytes alone, so the same committed note in
    # another worktree of the repository — the desktop app opens every session in one — is the
    # note the owner promoted. Keyed by the note's resolved path, each worktree's copy was a note
    # nobody had promoted, and no standing rule arrived there.
    from tests.gitfixture import git

    root = tmp_path / "project"
    base = root / "notes" / "developer"
    base.mkdir(parents=True)
    (base / "rule.md").write_text(_note("rule", startup="1", body="RULE-BODY"), "utf-8")
    (root / CONFIG_FILE).write_text(IN_REPO, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "notes")
    side = root / ".claude" / "worktrees" / "w1"
    git(root, "worktree", "add", "-q", str(side))
    assert cli(root, tmp_path, "memory", "promote", "--changed")[0] == 0
    assert "RULE-BODY" in _bundle(side, tmp_path, "standing-rules")


def test_a_promoted_note_is_still_reviewed_after_its_store_moves(tmp_path: Path) -> None:
    # The path is only the record's label, never what it matches on: the bytes the
    # owner promoted are the bytes reviewed wherever the store now sits.
    import shutil

    root = _project(tmp_path)
    assert cli(root, tmp_path, "memory", "promote", "developer/rule.md")[0] == 0
    moved = tmp_path / "moved"
    shutil.move(root, moved)
    assert _status_of(moved, tmp_path, "rule") == REVIEWED
    assert "RULE-BODY" in _bundle(moved, tmp_path, "standing-rules")


def test_promote_changed_records_only_the_unreviewed_notes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    assert cli(root, tmp_path, "memory", "promote", "developer/rule.md")[0] == 0
    code, out, _ = cli(root, tmp_path, "memory", "promote", "--changed", "--json")
    assert code == 0
    assert [entry["path"] for entry in json.loads(out)["promoted"]] == ["developer/other.md"]
    code, out, _ = cli(root, tmp_path, "memory", "promote", "--changed", "--json")
    assert (code, json.loads(out)["promoted"]) == (0, [])


@pytest.mark.parametrize(
    "argv,refusal",
    [
        (("developer/absent.md",), NOT_A_NOTE),
        (("../stayfixed.toml",), NOT_A_NOTE),
        ((), NOTHING_NAMED),
        (("developer/rule.md", "--changed"), NOTHING_NAMED),
    ],
    ids=["absent", "outside", "nothing", "both"],
)
def test_promote_refuses_what_is_no_note_of_the_store_and_records_nothing(
    tmp_path: Path, argv: tuple[str, ...], refusal: str
) -> None:
    root = _project(tmp_path)
    code, _, err = cli(root, tmp_path, "memory", "promote", *argv)
    assert code == 2
    assert refusal in err
    assert not (tmp_path / "trust.json").exists()


def test_a_record_write_a_sandbox_refused_says_a_person_must_run_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # From an agent's sandboxed shell the machine directory cannot be written (`EPERM`, as macOS's
    # sandbox answers), so a promote there ends in exit 2 and the record's constant sentence,
    # nothing written, never a traceback. Mutation (`mutations/`'s "the trust record says nothing
    # of the sandbox that refused its write"): exit 1 and the sentence about a directory that
    # cannot be written.
    root = _project(tmp_path)
    refused = refuse_writes_under(monkeypatch, tmp_path / RECORD)
    code, out, err = cli(root, tmp_path, "memory", "promote", "developer/rule.md")
    assert (code, out) == (2, "")
    assert refused == [tmp_path / RECORD]
    assert err == f"stayfixed: refused: {SANDBOXED}\n"
    assert recorded(tmp_path / "absent.toml") == {}
    capsys.readouterr()


def test_a_trust_record_that_cannot_be_read_leaves_every_note_unreviewed(tmp_path: Path) -> None:
    # Closed: a record nothing can read promotes nothing, so no note becomes a standing rule on
    # it, and the session still gets every note as data.
    root = _project(tmp_path)
    assert cli(root, tmp_path, "memory", "promote", "--changed")[0] == 0
    (tmp_path / "trust.json").write_text("{not json", encoding="utf-8")
    assert _status_of(root, tmp_path, "rule") == UNREVIEWED
    assert "RULE-BODY" not in _bundle(root, tmp_path, "standing-rules")


def test_the_count_line_is_said_once_for_a_new_set_and_not_again_for_the_same_set(
    tmp_path: Path,
) -> None:
    # Said at `SessionStart` only when the set of unreviewed notes differs from the last
    # session's, so a session over an unchanged store hears nothing, and a new note is news.
    from stayfixed.hooks.api import HookEvent

    root = _project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    (handler,) = [h for h in register() if h.event == "SessionStart"]
    event = HookEvent("SessionStart", "s1", None, None, {}, root, root, {})

    def said() -> str | None:
        return handler.run(event, session_of(config)).context

    assert said() == UNREVIEWED_COUNT.format(count=2)
    assert said() is None
    (root / ".stayfixed" / "local" / "memory" / "developer" / "third.md").write_text(
        _note("third"), "utf-8"
    )
    assert said() == UNREVIEWED_COUNT.format(count=3)
    assert said() is None


def test_a_symlinked_note_is_neither_delivered_nor_digested_and_is_counted_skipped(
    tmp_path: Path,
) -> None:
    # A repository chooses its memory mode and commits its notes, so a note that is a link is a
    # read the repository aims: at a file outside it, which reached the volatile bundle with no
    # owner action, or at a note the owner promoted in another project, whose digest made it a
    # standing rule here. A note file that is a link is skipped in every store and counted; a
    # group directory that is a link (the composed store's) is still followed. Mutation (oracle):
    # `mutations/`'s "a symlinked note is walked".
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.md").write_text(_note("secret", startup="1", body="OUTSIDE-BODY"), "utf-8")
    other = tmp_path / "other"
    (other / "notes" / "developer").mkdir(parents=True)
    promoted = other / "notes" / "developer" / "clientb.md"
    promoted.write_text(_note("clientb", startup="1", body="CLIENT-B-RULE"), "utf-8")
    (other / CONFIG_FILE).write_text(IN_REPO, encoding="utf-8")
    assert cli(other, tmp_path, "memory", "promote", "--changed")[0] == 0
    root = tmp_path / "project"
    notes = root / "notes" / "developer"
    notes.mkdir(parents=True)
    (root / CONFIG_FILE).write_text(IN_REPO, encoding="utf-8")
    (notes / "a.md").symlink_to(outside / "secret.md")
    (notes / "b.md").symlink_to(promoted)
    assert "CLIENT-B-RULE" not in _bundle(root, tmp_path, "standing-rules")
    volatile = _bundle(root, tmp_path, "volatile-notes")
    assert "OUTSIDE-BODY" not in volatile and "CLIENT-B-RULE" not in volatile
    code, out, err = cli(root, tmp_path, "memory", "inventory", "--json")
    assert code == 0, err
    assert (json.loads(out)["notes"], json.loads(out)["skipped"]) == (0, 2)
    assert cli(root, tmp_path, "memory", "promote", "developer/b.md")[0] == 2


def test_the_data_region_says_the_note_is_unreviewed_and_not_where_it_was_committed(
    tmp_path: Path,
) -> None:
    # The region's lead called every note in it "memory committed to this repository", which an
    # overlay or `local-only` note, or one an agent wrote, is not; what each of them is, is a note
    # nobody promoted.
    root = _project(tmp_path)
    volatile = _bundle(root, tmp_path, "volatile-notes")
    region = volatile[volatile.index(DELIMITER) :]
    assert "committed to this repository" not in region
    assert "not reviewed by the owner" in region
