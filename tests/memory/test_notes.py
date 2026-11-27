from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from drybag.memory import notes
from drybag.memory.notes import (
    NAME_NOT_UTF_8,
    NoteError,
    NoteType,
    Provenance,
    read_note,
    render_note,
    walk,
    with_index,
    write_note,
)

FULL = """---
name: pick-a-fork
description: "At a fork, ask"
index: "A design fork → ask or decide"
group: Tests
group_order: 2
metadata:
  type: feedback
  startup: 2
  node_type: memory
  originSessionId: abc-123
---

Body line one.

Body line two.
"""

MINIMAL = """---
name: bare
description: just a description
---

Body.
"""

# Shapes the real corpus contains and a naive renderer destroys: an apostrophe that looks like
# a quote, an embedded double quote, a negative and a malformed `group_order`, and the native
# writer's own stamps.
AWKWARD = """---
name: awkward
description: 'tis a note, isn't it
index: "a → b"
group_order: -1
metadata:
  type: project
  modified: '2026-09-01T10:00:00Z'
  node_type: memory
---

Body with a "quoted" word.
"""

MALFORMED_ORDER = AWKWARD.replace("group_order: -1", "group_order: 2b")


def write(tmp_path: Path, text: str, name: str = "n.md") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_every_declared_field_is_read(tmp_path: Path) -> None:
    note = read_note(write(tmp_path, FULL))
    assert note.name == "pick-a-fork"
    assert note.description == "At a fork, ask"
    assert note.index == "A design fork → ask or decide"
    assert note.group == "Tests"
    assert note.group_order == 2
    assert note.type is NoteType.FEEDBACK
    assert note.startup == 2
    assert note.body.startswith("Body line one.")


def test_an_absent_index_is_curated_by_default(tmp_path: Path) -> None:
    note = read_note(write(tmp_path, MINIMAL))
    assert note.index is None
    assert note.index_provenance is Provenance.CURATED


@pytest.mark.parametrize("text", [FULL, MINIMAL, AWKWARD, MALFORMED_ORDER])
def test_an_unmodified_note_round_trips_byte_for_byte(tmp_path: Path, text: str) -> None:
    # The strictest assertion in this module, and the reason the renderer keeps the original
    # lines rather than re-emitting parsed values: seventy notes whose quoting changed on the
    # first `memory index` is a diff nobody reviews and a ping-pong with the native writer.
    assert render_note(read_note(write(tmp_path, text))) == text


def test_an_apostrophe_is_not_read_as_a_quote(tmp_path: Path) -> None:
    assert read_note(write(tmp_path, AWKWARD)).description == "'tis a note, isn't it"


def test_a_malformed_group_order_is_kept_in_the_file(tmp_path: Path) -> None:
    # It parses to None — the renderer must still not delete the line it could not read.
    note = read_note(write(tmp_path, MALFORMED_ORDER))
    assert note.group_order is None
    assert "group_order: 2b" in render_note(note)


def test_an_absent_declared_key_is_never_invented_on_render(tmp_path: Path) -> None:
    # `read_note` defaults `description` to "" and `name` to the file stem so the fields are
    # always usable — but a read-time default is not a value this run decided to write. A
    # note without one of these keys must not gain a line it never had, in either direction.
    no_description = (
        "---\nname: reminder\ngroup: Tasks\nmetadata:\n  type: user\n---\n\nSome text.\n"
    )
    no_name = (
        "---\ndescription: a reminder\ngroup: Tasks\nmetadata:\n  type: user\n---\n\nSome text.\n"
    )
    assert render_note(read_note(write(tmp_path, no_description, "a.md"))) == no_description
    assert render_note(read_note(write(tmp_path, no_name, "b.md"))) == no_name


def test_the_native_writers_own_keys_survive_a_round_trip(tmp_path: Path) -> None:
    rendered = render_note(read_note(write(tmp_path, AWKWARD)))
    assert "modified: '2026-09-01T10:00:00Z'" in rendered
    assert "node_type: memory" in rendered


def test_only_a_changed_key_is_rewritten(tmp_path: Path) -> None:
    note = with_index(read_note(write(tmp_path, MINIMAL)), "trigger → answer", Provenance.NATIVE)
    rendered = render_note(note)
    assert "index_provenance: native" in rendered
    assert "description: just a description" in rendered  # untouched, unquoted, as it was
    # The new value is asserted by reading it back, not by its quoting: what the renderer owes
    # is a value that parses to what was set, and a style assertion would pin an accident.
    write(note.path.parent, rendered, note.path.name)
    assert read_note(note.path).index == "trigger → answer"


def test_write_note_persists_what_render_produced(tmp_path: Path) -> None:
    note = with_index(read_note(write(tmp_path, MINIMAL)), "t → a", Provenance.NATIVE)
    write_note(note)
    again = read_note(note.path)
    assert again.index == "t → a"
    assert again.index_provenance is Provenance.NATIVE


def test_a_provisional_line_is_never_written_with_its_provenance(tmp_path: Path) -> None:
    # A provisional line is the index's rendering (`index.reconcile`), so no note says it holds
    # one: a reader would otherwise take it for a line the note carries.
    note = with_index(read_note(write(tmp_path, MINIMAL)), "t → a", Provenance.PROVISIONAL)
    assert "index_provenance" not in render_note(note)


@pytest.mark.parametrize(
    "value,expected", [("2", 2), ("0", 0), ("false", None), ("no", None), ("off", None)]
)
def test_startup_reads_a_rank_or_a_refusal(
    tmp_path: Path, value: str, expected: int | None
) -> None:
    text = MINIMAL.replace("---\n\nBody.", f"metadata:\n  startup: {value}\n---\n\nBody.")
    assert read_note(write(tmp_path, text)).startup == expected


@pytest.mark.parametrize("value", ["yes", "true", "", "1 # first", "soon"])
def test_a_startup_that_is_not_an_integer_is_no_rank(tmp_path: Path, value: str) -> None:
    # A rank makes a note a standing rule, so a value this reader cannot read as one fails toward
    # no rank: `startup: yes` used to rank last and so stood as a rule. Mutation (declared):
    # `mutations/`'s "a startup that is not an integer still ranks a note".
    text = MINIMAL.replace("---\n\nBody.", f"metadata:\n  startup: {value}\n---\n\nBody.")
    assert read_note(write(tmp_path, text)).startup is None


def test_as_of_is_a_date_or_none(tmp_path: Path) -> None:
    text = MINIMAL.replace("---\n\nBody.", "metadata:\n  as_of: 2026-09-01\n---\n\nBody.")
    assert read_note(write(tmp_path, text)).as_of == date(2026, 9, 1)
    assert read_note(write(tmp_path, MINIMAL, "b.md")).as_of is None


def test_a_malformed_as_of_is_none_not_an_error(tmp_path: Path) -> None:
    text = MINIMAL.replace("---\n\nBody.", "metadata:\n  as_of: soon\n---\n\nBody.")
    assert read_note(write(tmp_path, text)).as_of is None


def test_the_group_is_the_folder_never_the_frontmatter_key(tmp_path: Path) -> None:
    # `group` is a sub-heading inside a section; the section is the folder the note sits in.
    note = read_note(write(tmp_path, FULL, "developer/n.md"))
    assert note.group_name == "developer"
    assert note.group == "Tests"


def test_a_note_without_frontmatter_refuses(tmp_path: Path) -> None:
    with pytest.raises(NoteError, match="frontmatter"):
        read_note(write(tmp_path, "no frontmatter here\n"))


def test_an_unclosed_frontmatter_refuses(tmp_path: Path) -> None:
    with pytest.raises(NoteError, match="never closed"):
        read_note(write(tmp_path, "---\nname: a\n\nBody.\n"))


def test_a_nested_list_refuses_rather_than_being_dropped(tmp_path: Path) -> None:
    text = "---\nname: a\ndescription: b\ntags:\n  - one\n  - two\n---\n\nBody.\n"
    with pytest.raises(NoteError, match="line 4"):
        read_note(write(tmp_path, text))


def test_a_duplicated_key_refuses(tmp_path: Path) -> None:
    text = "---\nname: a\nname: b\ndescription: c\n---\n\nBody.\n"
    with pytest.raises(NoteError, match="duplicate"):
        read_note(write(tmp_path, text))


def test_a_doubly_signed_group_order_is_kept_but_never_raises(tmp_path: Path) -> None:
    # "--5".lstrip("-").isdigit() is True but int("--5") still raises: the guard that used to
    # gate this value let the ValueError through past read_note, and walk (which only catches
    # NoteError) crashed on it instead of quarantining the file — exactly the failure walk's
    # own docstring says a store cannot afford.
    text = AWKWARD.replace("group_order: -1", "group_order: --5")
    note = read_note(write(tmp_path, text, "developer/awkward.md"))
    assert note.group_order is None
    assert "group_order: --5" in render_note(note)
    found = walk(tmp_path, ["developer"])
    assert [n.name for n in found.notes] == ["awkward"]
    assert found.unreadable == []


def test_walk_reads_markdown_and_skips_the_rest(tmp_path: Path) -> None:
    (tmp_path / "developer").mkdir()
    write(tmp_path, MINIMAL, "developer/a.md")
    write(tmp_path, MINIMAL, "developer/.hidden.md")
    write(tmp_path, MINIMAL, "developer/_draft.md")
    (tmp_path / "developer" / "notes.txt").write_text("x", encoding="utf-8")
    found = walk(tmp_path, ["developer"])
    assert [note.path.name for note in found.notes] == ["a.md"]
    assert found.unreadable == []


def test_walk_quarantines_a_file_that_will_not_parse(tmp_path: Path) -> None:
    # The shipped preset ships `specs` in the default group list, and a store is a place
    # humans put things: one superseded document with no frontmatter must not cost the rest.
    (tmp_path / "specs").mkdir()
    write(tmp_path, MINIMAL, "specs/a.md")
    write(tmp_path, "a design document, no frontmatter\n", "specs/design.md")
    found = walk(tmp_path, ["specs"])
    assert [note.name for note in found.notes] == ["bare"]
    assert [path.name for path, _ in found.unreadable] == ["design.md"]


def test_a_note_that_is_not_utf8_is_quarantined_rather_than_an_internal_error(
    tmp_path: Path,
) -> None:
    # `UnicodeDecodeError` is not an `OSError`, and without its own arm one latin-1 byte in a
    # note left this walk as `internal error: UnicodeDecodeError` and exit 2 — a repository's
    # malformed input reading as this tool being broken. It is a note this reader cannot read,
    # exactly like the `OSError` beside it. Mutation: drop that arm from `read_note` — this
    # reddens with the exception escaping the walk.
    (tmp_path / "specs").mkdir()
    write(tmp_path, MINIMAL, "specs/a.md")
    (tmp_path / "specs" / "latin.md").write_bytes(
        b"---\nname: latin\ndescription: d\n---\n\ncaf\xe9\n"
    )
    found = walk(tmp_path, ["specs"])
    assert [note.name for note in found.notes] == ["bare"]
    assert [path.name for path, _ in found.unreadable] == ["latin.md"]
    assert "not valid UTF-8" in found.unreadable[0][1]


def test_a_note_whose_name_is_not_utf_8_is_quarantined_by_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `MEMORY.md` names every note by its file's name, and a name the disk holds in bytes that
    # are not UTF-8 raised `UnicodeEncodeError` when the index was written: `memory index` ended
    # as an internal error (reproduced in a Linux container). The note is quarantined like one
    # that will not parse, with the reason and the remedy. APFS refuses such a name, so the
    # predicate is made to refuse an ordinary one here; the case below plants the real bytes
    # where the disk holds them. Mutation (declared): drop the check from `walk` -> this reddens.
    (tmp_path / "specs").mkdir()
    write(tmp_path, MINIMAL, "specs/a.md")
    write(tmp_path, MINIMAL.replace("bare", "other"), "specs/b.md")
    monkeypatch.setattr(notes, "utf_8_name", lambda name: name != "b.md")
    found = walk(tmp_path, ["specs"])
    assert [note.name for note in found.notes] == ["bare"]
    assert [path.name for path, _ in found.unreadable] == ["b.md"]
    assert NAME_NOT_UTF_8 in found.unreadable[0][1]


def test_a_note_named_in_bytes_that_are_not_utf_8_is_quarantined(tmp_path: Path) -> None:
    # The case above with the real bytes, where the disk can hold them (Linux, where CI's oracle
    # runs). Mutation (declared, on `fsops`): the predicate decodes with `surrogateescape` ->
    # the note is read and this reddens.
    (tmp_path / "specs").mkdir()
    write(tmp_path, MINIMAL, "specs/a.md")
    try:
        with open(os.fsencode(tmp_path / "specs") + b"/caf\xe9.md", "w", encoding="utf-8") as f:
            f.write(MINIMAL.replace("bare", "latin"))
    except OSError as exc:  # APFS: `Illegal byte sequence`
        pytest.skip(f"this filesystem cannot hold a name that is not UTF-8 ({exc.strerror})")
    found = walk(tmp_path, ["specs"])
    assert [note.name for note in found.notes] == ["bare"]
    assert [path.name for path, _ in found.unreadable] == [os.fsdecode(b"caf\xe9.md")]


def test_walk_ignores_a_group_directory_that_does_not_exist(tmp_path: Path) -> None:
    assert walk(tmp_path, ["developer", "specs"]).notes == []


def test_a_value_carrying_a_newline_is_refused_rather_than_written(tmp_path: Path) -> None:
    # There is no line-based frontmatter representation of a newline, and this reader's whole
    # premise is that it does not invent one. Written bare — which is what a multi-line value
    # gets, since it holds none of `: # " '` and neither leads nor trails whitespace — the
    # remainder spills past the `index:` line and the note stops parsing on the next read.
    path = tmp_path / "n.md"
    path.write_text(MINIMAL, encoding="utf-8")
    with pytest.raises(NoteError):
        render_note(with_index(read_note(path), "first line\nsecond line", Provenance.NATIVE))


def test_a_first_written_value_is_escaped_into_the_exact_bytes_the_grammar_reads_back(
    tmp_path: Path,
) -> None:
    # The escaping and the unescaping are one matched pair, so a round trip through both is
    # blind to removing both: `_quote` writing `he said "no"` bare and `_unescape` returning
    # its input unchanged reads back as the value that went in, while the file on disk carries
    # a `"` that closes the scalar on its own and a lone `\` the native writer takes as an
    # escape lead-in. This module's premise is bit-compatibility with *that* writer, so the
    # assertion has to be on the bytes, not on what this module makes of them.
    path = tmp_path / "n.md"
    path.write_text(MINIMAL, encoding="utf-8")
    write_note(with_index(read_note(path), r'he said "no" \ then left', Provenance.NATIVE))
    assert r'index: "he said \"no\" \\ then left"' in path.read_text(encoding="utf-8")


def test_an_escaped_value_reads_back_as_the_value_that_was_written(tmp_path: Path) -> None:
    # `_quote` escapes `\` and `"`; a reader that never unescapes them is not its inverse, so
    # a description holding a quote gains a backslash on every key this run writes for the
    # first time — and renders into `MEMORY.md` with the backslash visible.
    path = tmp_path / "n.md"
    path.write_text('---\nname: n\ndescription: he said "no"\n---\n\nBody.\n', encoding="utf-8")
    original = read_note(path)
    assert original.description == 'he said "no"'
    write_note(with_index(original, original.description, Provenance.PROVISIONAL))
    assert read_note(path).index == 'he said "no"'


# Every character `str.splitlines()` breaks on beyond the two the old guard named. `_split`
# finds the frontmatter fence with `splitlines()`, so this is the set that decides where a
# note's frontmatter ends — while `read_text`'s universal newlines and `_ENTRY` had already
# made `\n` and `\r` the two that cannot arrive.
OTHER_LINE_BREAKS = ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")


@pytest.mark.parametrize("char", OTHER_LINE_BREAKS)
def test_a_value_carrying_any_break_splitlines_knows_is_refused(tmp_path: Path, char: str) -> None:
    # A title copied out of a PDF carries U+2028. Written bare — it holds none of `: # " '`
    # and `str.strip()` does not remove an interior one — the remainder lands on a line of its
    # own, and the next read quarantines the note out of the index, the standing rules and
    # volatile injection with both runs exiting 0.
    path = tmp_path / "n.md"
    path.write_text(MINIMAL, encoding="utf-8")
    with pytest.raises(NoteError):
        render_note(with_index(read_note(path), f"first{char}second", Provenance.NATIVE))


def test_a_value_that_merely_ends_in_a_line_break_is_refused_too(tmp_path: Path) -> None:
    # `len(value.splitlines()) > 1` is False for `"one line\n"` — `splitlines` yields one
    # element — while the value plainly carries a break, and the quoted form written for it
    # closes the key's line early. The guard asks whether the value *is* its own single line.
    path = tmp_path / "n.md"
    path.write_text(MINIMAL, encoding="utf-8")
    with pytest.raises(NoteError):
        render_note(with_index(read_note(path), "one line\n", Provenance.NATIVE))


def test_an_empty_value_is_one_line_and_is_still_written(tmp_path: Path) -> None:
    # A note without `description:` is ordinary, and `read_note` fills in `""` for it. The
    # one-line guard must not refuse that, or the empty string becomes unwritable.
    path = tmp_path / "n.md"
    path.write_text(MINIMAL, encoding="utf-8")
    assert 'index: ""' in render_note(with_index(read_note(path), "", Provenance.NATIVE))


# --- an unchanged note really does round-trip byte for byte -----------------------------------
#
# `Note.raw`'s comment claimed this and it was true of the frontmatter only: the body was
# renormalised — CRLF to LF, blank lines around it stripped, a trailing newline added — so the
# first `memory index` over a store somebody else's tool wrote produced exactly the unreviewable
# diff this module exists to prevent, for the subset of notes shaped that way.


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("plain", "---\nname: n\ndescription: d\n---\n\nBody.\n"),
        ("crlf", "---\r\nname: n\r\ndescription: d\r\n---\r\n\r\nBody.\r\n"),
        ("no trailing newline", "---\nname: n\ndescription: d\n---\n\nBody."),
        ("two blank lines before the body", "---\nname: n\ndescription: d\n---\n\n\nBody.\n"),
        ("no blank line before the body", "---\nname: n\ndescription: d\n---\nBody.\n"),
        ("blank lines after the body", "---\nname: n\ndescription: d\n---\n\nBody.\n\n\n"),
        ("an empty body", "---\nname: n\ndescription: d\n---\n"),
    ],
)
def test_an_unchanged_note_round_trips_byte_for_byte(tmp_path: Path, label: str, text: str) -> None:
    path = tmp_path / "n.md"
    path.write_text(text, encoding="utf-8", newline="")
    assert render_note(read_note(path)) == text, label


def test_a_rewritten_key_keeps_the_body_and_the_files_own_line_endings(tmp_path: Path) -> None:
    # The half that has to keep working: when `memory` *does* change a line, the change is the
    # only difference — the body is still the body that was there, and a CRLF file stays CRLF
    # rather than becoming a whole-file diff.
    path = tmp_path / "n.md"
    path.write_text(
        "---\r\nname: n\r\ndescription: d\r\n---\r\n\r\nBody, unchanged.\r\n",
        encoding="utf-8",
        newline="",
    )
    written = render_note(with_index(read_note(path), "t → a", Provenance.PROVISIONAL))
    assert "index: t → a\r\n" in written
    assert written.endswith("\r\n\r\nBody, unchanged.\r\n")
    assert "\n\n" not in written.replace("\r\n", "")


def test_a_note_linked_to_a_device_is_quarantined_and_one_through_a_linked_group_is_read(
    tmp_path: Path,
) -> None:
    # `read_note` followed a committed link to whatever it named: `/dev/stdin` hung
    # `memory inventory`, and `/dev/zero` would read until memory ran out. `walk` skips a note
    # file that is a link, and `read_note` itself reads a regular file only; unguarded, the
    # `/dev/null` case read as an empty note and was refused for having no frontmatter, which the
    # reason tells apart. The group directory beside it is a link, as `attach` makes it in overlay
    # mode, and its note is read. Mutation (declared): `read_note` opens with `path.open` again ->
    # the reason is the frontmatter's.
    elsewhere = tmp_path / "overlay" / "developer"
    elsewhere.mkdir(parents=True)
    write(tmp_path / "overlay", MINIMAL, "developer/a.md")
    store = tmp_path / "store"
    store.mkdir()
    (store / "developer").symlink_to(elsewhere, target_is_directory=True)
    (elsewhere / "null.md").symlink_to("/dev/null")
    found = walk(store, ["developer"])
    assert [note.name for note in found.notes] == ["bare"]
    assert [path.name for path in found.skipped] == ["null.md"]
    with pytest.raises(NoteError, match="not a regular file"):
        read_note(elsewhere / "null.md")
