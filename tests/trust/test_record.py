"""The machine's one trust record (`src/stayfixed/trust/record.py`): a versioned document of kinds
and subjects beside the machine file."""

from __future__ import annotations

import errno
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stayfixed import fsops
from stayfixed.config.machine import machine_config_path
from stayfixed.errors import Failure
from stayfixed.jsonobject import LONG_NUMBER, NESTED
from stayfixed.trust.record import (
    LATER_VERSION,
    NO_HOME,
    NOT_A_RECORD,
    RECORD,
    SANDBOXED,
    VERSION,
    SandboxedWrite,
    UnreadableTrust,
    approve_all,
    record_path,
    recorded,
)
from tests import parserlimits

T0 = datetime(2026, 10, 16, 9, 30, tzinfo=UTC)
# One approval as a version-1 record spells it, every field a string.
APPROVAL = {"kind": "memory", "subject": "/s", "digest": "d", "approved_at": ""}


def machine(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def test_a_flat_map_with_no_version_is_refused_and_kept(tmp_path: Path) -> None:
    # A flat map of paths to digests is no version-1 record, so it refuses as any other non-record
    # does; read as empty, the next write would replace it.
    path = tmp_path / RECORD
    document = json.dumps({"/s": "d", "/t": "e"})
    path.write_text(document, encoding="utf-8")
    with pytest.raises(UnreadableTrust) as caught:
        recorded(machine(tmp_path))
    assert str(caught.value) == (
        f"{path} is not a version-1 trust record, and nothing here will overwrite it; repair it "
        "if it holds approvals you want to keep, or delete it to start a new record"
    )
    with pytest.raises(UnreadableTrust):
        approve_all(machine(tmp_path), "reviewed", {"/n": "e"}, now=T0)
    assert path.read_text(encoding="utf-8") == document


@pytest.mark.parametrize(
    ("document", "sentence"),
    [
        pytest.param("{", None, id="not-json"),
        pytest.param(json.dumps({"version": 2, "approvals": []}), LATER_VERSION, id="version-2"),
        pytest.param(json.dumps({"version": True, "approvals": []}), NOT_A_RECORD, id="bool"),
        pytest.param(json.dumps({"version": 0, "approvals": []}), NOT_A_RECORD, id="version-0"),
        pytest.param(json.dumps({"version": -1, "approvals": []}), NOT_A_RECORD, id="negative"),
        pytest.param(json.dumps({"version": "1", "approvals": []}), NOT_A_RECORD, id="text"),
        pytest.param(json.dumps({"approvals": [APPROVAL]}), NOT_A_RECORD, id="no-version"),
        pytest.param(json.dumps({"version": 1}), NOT_A_RECORD, id="no-approvals"),
        pytest.param(
            json.dumps({"version": 1, "approvals": [{"kind": "memory", "subject": "/s"}]}),
            NOT_A_RECORD,
            id="approval-short-a-field",
        ),
        pytest.param(
            json.dumps({"version": 1, "approvals": {}}), NOT_A_RECORD, id="approvals-not-a-list"
        ),
        pytest.param(
            json.dumps({"version": 1, "approvals": [], "note": "hand-added"}),
            NOT_A_RECORD,
            id="stray-key",
        ),
        pytest.param(
            json.dumps({"version": 1, "approvals": [{**APPROVAL, "digest": 1}]}),
            NOT_A_RECORD,
            id="digest-not-a-string",
        ),
        pytest.param(
            json.dumps({"version": 1, "approvals": [APPROVAL, {**APPROVAL, "digest": "e"}]}),
            NOT_A_RECORD,
            id="duplicate-pair",
        ),
        pytest.param(
            json.dumps({"version": 1, "approvals": [sorted(APPROVAL)]}),
            NOT_A_RECORD,
            id="entry-not-an-object",
        ),
    ],
)
def test_an_unreadable_record_refuses_and_is_never_overwritten(
    tmp_path: Path, document: str, sentence: str | None
) -> None:
    # Each arm of the version-1 reader has a case of its own: every other version-1 record in the
    # suite is one `approve_all` wrote, and it can write none of these. Only a version above this
    # one sends its reader to a later stayfixed. Mutations (`mutations/`'s "a trust record of a
    # later version is read as empty" -> version 2 reads as no approval and the write replaces it;
    # "a trust record of any other version is sent to a later stayfixed" -> `bool`, `version-0`,
    # `negative` and `text` say `LATER_VERSION`; "an approval over an unreadable trust record
    # writes the record anyway" -> the write replaces every case; "a trust
    # record's approvals that are not a list read as none" -> `approvals-not-a-list` reads as no
    # approval; "a trust record with a stray key is read" -> `stray-key` reads; "a trust record's
    # digest that is not a string is read" -> `digest-not-a-string` reads as a lapsed approval; "a
    # trust record naming one approval twice keeps the last" -> `duplicate-pair` reads, and the next
    # write persists the survivor; "a trust record's approval that is not an object is read" ->
    # `entry-not-an-object` raises an `AttributeError` instead of refusing).
    path = tmp_path / RECORD
    path.write_text(document, encoding="utf-8")
    with pytest.raises(UnreadableTrust) as caught:
        recorded(machine(tmp_path))
    if sentence is not None:
        assert str(caught.value) == sentence.format(path=path)
    with pytest.raises(UnreadableTrust):
        approve_all(machine(tmp_path), "memory", {"/s": "d"}, now=T0)
    assert path.read_text(encoding="utf-8") == document


# What every refusal of a record that is there and cannot be read ends with, written out rather than
# imported, so the sentence a person reads is held here and not only by the module that says it.
KEPT = (
    "it holds every project's approval on this machine, so nothing here will overwrite it — repair "
    "or delete it"
)


def _json_says(text: str) -> str:
    """What the standard library's parser says of `text`, which the refusal quotes."""
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return str(exc)
    raise AssertionError(f"{text!r} parses")


@pytest.mark.parametrize(
    ("data", "said"),
    [
        pytest.param(b"{", f"is not valid JSON: {_json_says('{')}", id="not-json"),
        pytest.param(b"\xff{}", "is not UTF-8 text", id="not-utf-8"),
    ],
)
def test_a_record_that_does_not_parse_says_why_and_that_it_is_kept(
    tmp_path: Path, data: bytes, said: str
) -> None:
    # The two arms before the version-1 reader, each asserted whole: the refusal names the file and
    # why, and closes with what keeps the record from being overwritten. Mutations (`mutations/`'s
    # "a trust record that is not JSON is refused without saying it is kept" -> `not-json` loses
    # its close; "a trust record that is not UTF-8 is refused without saying why" -> `not-utf-8`
    # names no cause).
    path = tmp_path / RECORD
    path.write_bytes(data)
    with pytest.raises(UnreadableTrust) as caught:
        recorded(machine(tmp_path))
    assert str(caught.value) == f"{path} {said}; {KEPT}"


def test_two_kinds_never_share_a_subject(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the trust record keys an approval by its subject alone"): the
    # second approval replaces the first, and the first kind is gone.
    approve_all(machine(tmp_path), "memory", {"/s": "d"}, now=T0)
    approve_all(machine(tmp_path), "other", {"/s": "e"}, now=T0)
    assert {key: a.digest for key, a in recorded(machine(tmp_path)).items()} == {
        ("memory", "/s"): "d",
        ("other", "/s"): "e",
    }


def test_no_record_at_all_holds_no_approval(tmp_path: Path) -> None:
    # The fresh machine. No mutation of its own: the absent file is the arm every write test
    # passes through first.
    assert recorded(machine(tmp_path)) == {}


def test_the_record_ignores_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The record beside the machine file is under `HOME`, whatever `XDG_CONFIG_HOME` says.
    monkeypatch.setenv("HOME", str(tmp_path / "owner"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert machine_config_path() == tmp_path / "owner" / ".config" / "stayfixed" / "config.toml"
    assert record_path(None) == tmp_path / "owner" / ".config" / "stayfixed" / RECORD
    assert record_path(machine(tmp_path)) == tmp_path / RECORD
    # No home: no record, and nothing to fall back on.
    monkeypatch.setenv("HOME", "")
    assert record_path(None) is None


@pytest.mark.parametrize(
    ("document", "clause"),
    [(parserlimits.NESTED, NESTED), ('{"/p": ' + parserlimits.LONG_NUMBER + "}", LONG_NUMBER)],
    ids=["nested", "long-number"],
)
def test_a_record_past_the_parser_is_refused_and_never_overwritten(
    tmp_path: Path, document: str, clause: str
) -> None:
    # Both documents are valid JSON that `json.loads` meets with no `JSONDecodeError`: nesting
    # past what it follows raises `RecursionError`, and an integer longer than the interpreter
    # converts (4,300 digits by default) a plain `ValueError`. The reader caught only the first
    # kind, so a write ended in an internal error quoting the interpreter, where a record it cannot
    # read is refused in the record's own sentence: it holds every project's approval, and
    # nothing overwrites it. Mutation (oracle): `mutations/`'s "the trust record's reader lets a
    # document past the parser escape" -> the internal error comes back and both cases redden.
    path = tmp_path / RECORD
    path.write_text(document, encoding="utf-8")
    with pytest.raises(UnreadableTrust) as caught:
        approve_all(machine(tmp_path), "memory", {"/s": "d"}, now=T0)
    assert str(caught.value) == f"{path} {clause}; {KEPT}"
    assert path.read_text(encoding="utf-8") == document


def test_a_record_that_cannot_be_read_says_why_in_words(tmp_path: Path) -> None:
    # It named the file and then the error, whose text names the same absolute path again; the
    # reason is said in words, the file named once. Mutation: `mutations/`'s "a trust record that
    # cannot be read is reported with the error's own text".
    if os.geteuid() == 0:
        pytest.skip("root reads everything")
    approve_all(machine(tmp_path), "memory", {"/s": "d"}, now=T0)
    path = tmp_path / RECORD
    path.chmod(0o000)
    try:
        with pytest.raises(UnreadableTrust) as refused:
            recorded(machine(tmp_path))
    finally:
        path.chmod(0o600)
    assert str(refused.value) == (
        f"{path} cannot be read ({os.strerror(errno.EACCES)}); refusing to answer about trust or "
        "to overwrite it"
    )


def test_a_record_with_no_home_is_written_nowhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No home the hook path could read the record from, so none is written anywhere: not under
    # `HOME`, and not as a `trust.json` beside whatever directory the command ran in. Mutations
    # (`mutations/`'s "a trust record with no home is written beside the working directory" -> a
    # `trust.json` appears here; "a trust record with no home is read as a path" -> the read raises
    # an internal error).
    monkeypatch.setenv("HOME", "")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(Failure) as failed:
        approve_all(None, "memory", {"/s": "d"}, now=T0)
    assert str(failed.value) == NO_HOME
    assert list(tmp_path.rglob(RECORD)) == []


def test_a_home_that_cannot_be_written_fails_naming_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No other place is one a hook reads: a failure naming the directory, never an internal error,
    # and not the sandbox's sentence, since a directory's mode is not the sandbox. Mutations
    # (`mutations/`'s "an unwritable trust record directory ends as an internal error" -> an
    # internal error; "a directory's mode is read as the sandbox" -> `SandboxedWrite`).
    if os.geteuid() == 0:
        pytest.skip("root writes everywhere")
    locked = tmp_path / "locked-home"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        monkeypatch.setenv("HOME", str(locked))
        with pytest.raises(Failure) as failed:
            approve_all(None, "memory", {"/s": "d"}, now=T0)
    finally:
        locked.chmod(0o755)
    assert not isinstance(failed.value, SandboxedWrite)
    assert str(failed.value).startswith(f"{locked / '.config' / 'stayfixed'} cannot be written")


@pytest.mark.parametrize(
    ("code", "sandboxed"),
    [
        pytest.param(errno.EPERM, True, id="eperm"),
        pytest.param(errno.EROFS, True, id="erofs"),
        pytest.param(errno.EACCES, False, id="eacces"),
    ],
)
def test_a_write_refused_as_a_sandbox_refuses_one_is_said_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, sandboxed: bool
) -> None:
    # `EPERM`, which macOS's sandbox answers, and `EROFS`, a read-only mount's answer, are read as
    # the sandbox's refusal and said in the record's constant sentence, a refusal; `EACCES`, a
    # directory whose mode refuses the user, keeps the sentence naming the directory, a failure.
    # Nothing is written either way. Mutations (`mutations/`'s "a read-only mount's refusal is not
    # read as the sandbox's" -> `erofs` names the directory; "a directory's mode is read as the
    # sandbox" -> `eacces` says the sandbox's sentence).
    path = machine(tmp_path).parent / RECORD

    def refusing(target: Path, text: str, **kwargs: object) -> None:
        raise OSError(code, os.strerror(code), str(target))

    monkeypatch.setattr(fsops, "write_atomically", refusing)
    with pytest.raises((SandboxedWrite, Failure)) as refused:
        approve_all(machine(tmp_path), "memory", {"/s": "d"}, now=T0)
    if sandboxed:
        assert type(refused.value) is SandboxedWrite
        assert str(refused.value) == SANDBOXED
    else:
        assert type(refused.value) is Failure
        assert str(refused.value) == (
            f"{path.parent} cannot be written ({fsops.said(OSError(code, os.strerror(code)))}), "
            "so the trust record cannot be kept there; it is beside the machine configuration "
            "file --machine names"
        )
    assert not path.exists()


def test_the_sandbox_sentence_says_what_a_person_in_their_own_terminal_meets() -> None:
    # `EPERM` and `EROFS` are what the sandbox answers, and also what a read-only mount or an
    # immutable flag answers a person already in their own terminal, whom the sentence would
    # otherwise send there again. Mutation (`mutations/`'s "the sandbox sentence sends a person in
    # their own terminal there again"): the sentence ends at the sandbox.
    from stayfixed.trust.boundary import OWN_TERMINAL_TOO
    from stayfixed.trust.record import SANDBOXED

    assert SANDBOXED.endswith(OWN_TERMINAL_TOO)


def test_every_subject_of_a_kind_is_approved_in_one_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A kind with several subjects is approved whole or not at all: one replacement of the record,
    # so a write that fails part-way leaves it as it was. Mutation (`mutations/`'s "approving a
    # kind writes the record once per subject"): two writes.
    machine = tmp_path / "config.toml"
    approve_all(machine, "memory", {"/a": "old"}, now=T0)
    writes: list[Path] = []
    real = fsops.write_atomically

    def counting(path: Path, text: str) -> None:
        writes.append(path)
        real(path, text)

    monkeypatch.setattr(fsops, "write_atomically", counting)
    approve_all(machine, "memory", {"/a": "new", "/b": "d"}, now=T0)
    assert writes == [tmp_path / RECORD]
    assert {key: a.digest for key, a in recorded(machine).items()} == {
        ("memory", "/a"): "new",
        ("memory", "/b"): "d",
    }


def test_approving_no_subject_writes_nothing(tmp_path: Path) -> None:
    # A kind with nothing to approve in this checkout leaves the record where it is, absent
    # included. Mutation (`mutations/`'s "approving no subject writes the record"): an empty
    # version-1 record appears.
    machine = tmp_path / "config.toml"
    approve_all(machine, "memory", {}, now=T0)
    assert not (tmp_path / RECORD).exists()


def test_a_symlinked_record_is_written_through_and_stays_a_link(tmp_path: Path) -> None:
    # A dotfiles manager (stow, chezmoi) links `trust.json` to its own copy: an approval lands in
    # that copy and the link stays. Mutation (`mutations/`'s "the trust record is written without
    # resolving it"): the link becomes a regular file and the copy keeps the old approvals.
    leads_to = tmp_path / "dotfiles" / RECORD
    leads_to.parent.mkdir()
    leads_to.write_text(json.dumps({"version": VERSION, "approvals": []}), encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / RECORD).symlink_to(leads_to)
    approve_all(home / "config.toml", "memory", {"/s": "d"}, now=T0)
    assert (home / RECORD).is_symlink()
    written = json.loads(leads_to.read_text(encoding="utf-8"))
    assert [(a["subject"], a["digest"]) for a in written["approvals"]] == [("/s", "d")]


def test_a_record_linked_into_a_directory_that_cannot_be_written_names_that_directory(
    tmp_path: Path,
) -> None:
    # The write goes where the link leads, and the failure named the link's own directory, which
    # could be written, so the person was sent to fix the wrong one. Mutation (oracle):
    # `mutations/`'s "a write-through failure names the link's directory".
    leads_to = tmp_path / "dotfiles" / RECORD
    leads_to.parent.mkdir()
    leads_to.write_text(json.dumps({"version": VERSION, "approvals": []}), encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / RECORD).symlink_to(leads_to)
    leads_to.parent.chmod(0o555)
    try:
        with pytest.raises(Failure) as failed:
            approve_all(home / "config.toml", "memory", {"/s": "d"}, now=T0)
    finally:
        leads_to.parent.chmod(0o755)
    assert str(failed.value).startswith(f"{leads_to.parent} cannot be written (")


def test_a_later_records_refusal_sends_its_reader_to_a_later_stayfixed() -> None:
    # A record a later stayfixed wrote is met after a downgrade, where deleting it would destroy
    # that release's approvals: the remedy is updating stayfixed, never deleting the file. No
    # mutation of its own: the refusal is a constant, asserted whole by the unreadable-record cases
    # above.
    assert LATER_VERSION.endswith("update stayfixed to read it")
    assert "delete" not in LATER_VERSION
