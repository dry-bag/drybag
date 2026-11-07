from __future__ import annotations

import json

import pytest

from stayfixed import jsonobject
from stayfixed.scaffold.entries import (
    EntriesError,
    ParserLimitError,
    mark,
    marker_id,
    settings_object,
    settings_text,
)
from tests.parserlimits import LONG_NUMBER, NESTED, PAST_ENCODING, overflowing


def document(*commands: tuple[str, str]) -> str:
    return json.dumps(
        {
            "hooks": {
                event: [{"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]}]
                for event, cmd in commands
            }
        },
        indent=2,
    )


def test_marker_id_reads_the_id_a_command_claims() -> None:
    assert marker_id("run.sh hook PreToolUse  # stayfixed:bg-cleanup") == "bg-cleanup"
    assert marker_id("run.sh hook PreToolUse") is None


def test_a_marker_that_is_not_at_the_end_is_not_an_id() -> None:
    assert marker_id("run.sh  # stayfixed:bg-cleanup then more text") is None


def test_mark_is_idempotent() -> None:
    once = mark("run.sh", "bg-cleanup")
    assert mark(once, "bg-cleanup") == once


def test_a_malformed_document_refuses() -> None:
    with pytest.raises(EntriesError):
        settings_object("{not json")


def test_a_document_nested_past_the_parsers_reach_refuses_as_one_past_a_limit() -> None:
    # `RecursionError` used to leave the engine past every caller's catch: `attach` ended in an
    # internal error, on a file the repository chose. The refusal is its own kind, because the
    # document is valid JSON a harness may well read.
    # Mutation (oracle): `mutations/`'s "the JSON object reader lets a document nested past the
    # parser raise" -> it raises `RecursionError`.
    nested = '{"hooks": ' + NESTED + "}"
    with pytest.raises(ParserLimitError, match="nested deeper"):
        settings_object(nested)


def test_a_document_past_the_encoder_refuses_as_one_nested_past_the_parser() -> None:
    # On Python 3.14 this parses, and a write-back's `json.dumps` of it raised `RecursionError`
    # past every caller's catch, where 3.11 to 3.13 refuse it at the parse. The reader bounds the
    # depth it follows, so every interpreter refuses it as nested too deep; the bound itself is
    # proven on every interpreter by `test_the_object_reader_refuses_a_value_past_its_depth_bound`.
    with pytest.raises(ParserLimitError, match="nested deeper"):
        settings_object('{"x": ' + PAST_ENCODING + "}")


def test_the_object_reader_refuses_a_value_past_its_depth_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The bound lowered, so a document every parser follows meets it: one level past refuses in
    # the parser's own words, and a document at the bound is read. Mutation (declared): the
    # bound never refuses -> the deeper document is read.
    monkeypatch.setattr(jsonobject, "DEPTH_CAP", 4)
    with pytest.raises(ParserLimitError, match="nested deeper than this reader follows"):
        settings_object('{"x": [[[[]]]]}')
    assert settings_object('{"x": [[[]]]}') == {"x": [[[]]]}


def test_a_real_settings_document_sits_far_inside_the_depth_bound() -> None:
    # The legitimate document the bound must never refuse: hooks -> event -> group -> hooks ->
    # entry is five levels, and the bound is a named cap far above any settings file a harness
    # writes. Under it too, and pinned, because only the oracle's interpreters see this test run
    # the cap: on 3.14 (the one interpreter whose parser follows past it) nested objects stopped
    # encoding at about 21,700 levels of `==` and 28,900 of `json.dumps(indent=2)` (measured on
    # 3.14.7), so a cap raised past 20,000 would let 3.14 read what it cannot write back.
    # Mutations (declared): `mutations/`'s "the JSON object reader's depth bound is raised past what
    # 3.14 encodes" and "the JSON object reader's depth bound is lowered under what a harness
    # writes".
    marked = document(("PreToolUse", mark("a.sh", "bg-cleanup")))
    assert 1_000 <= jsonobject.DEPTH_CAP < 20_000
    assert settings_object(marked) == json.loads(marked)


def test_a_number_past_the_parsers_reach_is_refused() -> None:
    # A number the reader cannot hold could not be written back unchanged, so it refuses. The
    # `ValueError` used to leave the engine past every caller's catch. Mutation (oracle):
    # `mutations/`'s "the JSON object reader lets a number past the parser's reach raise" ->
    # `settings_object` raises `ValueError`.
    marked = json.loads(document(("PreToolUse", mark("a.sh", "bg-cleanup"))))
    long = json.dumps(marked)[:-1] + ', "n": ' + LONG_NUMBER + "}"
    with pytest.raises(ParserLimitError, match="number longer"):
        settings_object(long)


# Valid JSON 3,000 levels deep: inside every supported parser's reach but 3.11's, and past the
# reach of 3.12's encoder whenever it indents. 3.12's C encoder does not handle `indent`, so
# `json.dumps(indent=2)` runs the pure-Python one, which stops near 994 levels.
ENCODER_DEEP = '{"x": ' + "[" * 3_000 + "]" * 3_000 + "}"


def test_a_document_read_and_then_too_deep_to_write_back_is_refused_never_an_internal_error() -> (
    None
):
    # On Python 3.12 the engine read this document and then ended in `RecursionError` writing it
    # back, an internal error; 3.11 refuses it at the parse, and 3.13 and 3.14 read and write it.
    # Every interpreter now either writes it back or refuses it as nested too deep. Real depth, so
    # it reddens on 3.12 in CI; `test_a_write_back_the_encoder_cannot_follow_is_refused_as_nested`
    # forces the same arm on every interpreter, for the oracle.
    try:
        written = settings_text(settings_object(ENCODER_DEEP))
    except ParserLimitError as refused:
        assert "nested deeper than this reader follows" in str(refused)
    else:
        assert json.loads(written) == json.loads(ENCODER_DEEP)


def test_a_write_back_the_encoder_cannot_follow_is_refused_as_nested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The encoder stops where an interpreter's recursion does, which differs by interpreter and
    # by `indent`; forced here, the engine's encode of a parsed document answers it as the reader
    # answers a document nested past the parser. Mutation (declared): the encode made with a bare
    # `json.dumps` again -> `RecursionError` escapes.
    monkeypatch.setattr(jsonobject, "_encode", overflowing)
    marked = document(("PreToolUse", mark("a.sh", "bg-cleanup")))
    with pytest.raises(ParserLimitError, match="nested deeper than this reader follows"):
        settings_text(settings_object(marked))


def test_a_document_at_the_depth_bound_is_written_back_or_refused_on_this_interpreter() -> None:
    # The bound is only as good as what the rest of the interpreter follows: a document exactly at
    # it either round-trips through the engine here or is refused in the reader's words, never an
    # internal error -- on 3.11 to 3.13 the parser refuses it; on 3.14 it is read and encoded,
    # and refused because, indented, it is longer than the regular-file reader reads.
    deep = '{"x": ' + "[" * (jsonobject.DEPTH_CAP - 1) + "]" * (jsonobject.DEPTH_CAP - 1) + "}"
    try:
        written = settings_text(settings_object(deep))
    except ParserLimitError as refused:
        assert jsonobject.NESTED in str(refused) or jsonobject.WRITTEN_PAST in str(refused)
    else:
        assert written.startswith('{\n  "x": [')
