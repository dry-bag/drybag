"""The one TOML serialiser, and the one rule it holds: a value is escaped or it is refused."""

from __future__ import annotations

import datetime
import tomllib

import pytest

from drybag.errors import Refusal
from drybag.tomlout import dumps


def test_a_value_with_a_quote_and_a_newline_round_trips() -> None:
    # This module exists because the value it was written for is a git remote URL — repository-
    # authored bytes, which are untrusted input like everything else a repository carries.
    # Unescaped, a crafted URL closes its own string and writes further keys into a record that
    # decides what `attach` trusts.
    hostile = 'git@h:o/p.git"\nremote = "git@evil:o/p.git'
    parsed = tomllib.loads(dumps({"project": {"remote": hostile}}))
    assert parsed["project"] == {"remote": hostile}


def test_every_scalar_type_the_callers_use_round_trips() -> None:
    tables: dict[str, dict[str, object]] = {
        "project": {"remote": "u", "first_attach": "2026-09-17"},
        "machine": {"cli_on_path": True, "plugins": ["a", "b"]},
    }
    assert tomllib.loads(dumps(tables)) == tables


def test_an_unrepresentable_value_refuses_rather_than_being_mangled() -> None:
    # Silently dropping or str()-ing an unexpected type is how a capability record acquires a
    # value nobody wrote. There are two callers and both know their own types.
    with pytest.raises(Refusal):
        dumps({"project": {"when": object()}})


def test_a_key_that_is_not_a_bare_key_refuses_rather_than_being_quoted() -> None:
    # The same rule one level up. A key this cannot emit bare is a caller passing something it
    # did not mean to; quoting it would make `[project]` hold a name nobody chose to write.
    with pytest.raises(Refusal):
        dumps({"project": {"re mote": "u"}})
    with pytest.raises(Refusal):
        dumps({"pro ject": {"remote": "u"}})


def test_every_value_a_toml_document_can_hold_round_trips() -> None:
    # The contract widened when a third input arrived: `setup` rewrites the machine
    # configuration, a file `README.md` documents the owner as writing by hand, so what reaches
    # this serialiser is no longer only a caller's own dict. Refusing a float or a sub-table
    # merely because no caller of ours produces one wedged `drybag setup` permanently — the
    # file is read back at the top of every run. A nested dict becomes a sub-table header; a
    # dict inside a list becomes an inline table, the one spelling that survives being nested.
    #
    # Mutation: drop any one arm of `_scalar` (the float, the date/time) or the `children`
    # branch of `_emit`, and this reddens on that value. No entry in `mutations/`: value
    # coverage in a serialiser is not a guard something downstream reads as permission.
    document: dict[str, dict[str, object]] = {
        "personal": {
            "reply_language": "ru",
            "scale": 1.5,
            "when": datetime.date(2026, 9, 18),
            "at": datetime.datetime(2026, 9, 18, 10, 30),
            "editor": {"name": "nvim", "options": {"deep": True}},
        },
        "trust": {"rows": [{"host": "example.com"}, {"host": "other"}]},
    }
    assert tomllib.loads(dumps(document)) == document


def test_a_table_nested_inside_an_array_of_tables_round_trips_too() -> None:
    # The first attempt at the widening stopped one level short: an inline table's own values
    # went through `_value`, which refuses a dict, so `[[trust.rows]]` with a sub-table under it
    # parsed fine and could never be written back — the same permanent wedge `setup` had for a
    # float, one level further in, and in a file the owner is invited to hand-edit. "Every value
    # `tomllib` can parse" has to mean at any depth or it means very little.
    #
    # Mutation: `_inline` calls `_value` instead of `_element` for its values and this reddens
    # with the refusal. No entry in `mutations/`, for the reason the test above gives.
    document: dict[str, dict[str, object]] = {
        "trust": {"rows": [{"host": "a", "opts": {"deep": True, "tags": ["x"]}}]},
        "personal": {"editor": {"options": {"deep": {"deeper": 1}}}},
    }
    assert tomllib.loads(dumps(document)) == document


def test_a_control_character_survives_the_round_trip() -> None:
    # A tab and a carriage return are legal in a TOML basic string only as escapes, and a raw
    # one is a parse error rather than a mangled value — which is the failure this would be if
    # the escaping table stopped at the quote and the backslash.
    value = "a\tb\rc\x00d\\e"
    assert tomllib.loads(dumps({"project": {"remote": value}}))["project"]["remote"] == value


def test_the_root_table_is_written_before_any_header() -> None:
    # `projects/<name>/project.toml` holds `remote` at the top level, and the machine's binding
    # record its keys, because their readers read them there — one file, one place, or the writer
    # and the reader disagree about the record that decides whether a store resolves at all.
    text = dumps({"": {"remote": "u"}, "notes": {"kept": True}})
    assert text.splitlines()[0] == 'remote = "u"'
    assert tomllib.loads(text) == {"remote": "u", "notes": {"kept": True}}


def test_an_integer_round_trips() -> None:
    # The ledger format number and anything `setup` counts; `bool` is checked before `int`
    # because `isinstance(True, int)` is True and `1` is not `true`.
    assert tomllib.loads(dumps({"machine": {"format": 1}})) == {"machine": {"format": 1}}


def test_a_value_where_a_table_belongs_refuses() -> None:
    with pytest.raises(Refusal):
        dumps({"project": "not a table"})  # type: ignore[dict-item]


def test_the_root_table_is_hoisted_when_it_is_not_given_first() -> None:
    # `_emit` writes no header for the root, so a root that followed `[n]` bound its keys to
    # `[n]`: `{"n": {"k": True}, "": {"r": "u"}}` parsed back as `{"n": {"k": True, "r": "u"}}`.
    # That is the misplacement this module exists to prevent, reached by ordering rather than
    # by escaping. Both callers happened to put the root first; the serialiser no longer
    # depends on it. Mutation: the `sorted(...)` in `dumps` back to `tables.items()` → reddens.
    parsed = tomllib.loads(dumps({"n": {"k": True}, "": {"r": "u"}}))
    assert parsed == {"n": {"k": True}, "r": "u"}


def test_a_time_with_an_offset_and_a_sub_minute_offset_are_refused_rather_than_written() -> None:
    # Two shapes `isoformat` spells that `tomllib` cannot read back: TOML's local time has no
    # offset form, and an offset is `±HH:MM` with no seconds. Written, either wedges `setup`'s
    # rewrite-on-every-run file for ever — the contract says refuse, and it did not. Mutation:
    # either `raise` in `_scalar`'s datetime arm removed → the matching call below writes text
    # that `tomllib.loads` rejects instead of raising `Refusal`.
    with pytest.raises(Refusal):
        dumps({"t": {"k": datetime.time(10, 30, tzinfo=datetime.UTC)}})
    odd = datetime.timezone(datetime.timedelta(minutes=30, seconds=7))
    with pytest.raises(Refusal):
        dumps({"t": {"k": datetime.datetime(2026, 9, 19, 10, 30, tzinfo=odd)}})
    # The shapes beside them still round-trip, so the refusal is narrow.
    fine = {
        "t": {
            "naive": datetime.time(10, 30),
            "aware": datetime.datetime(2026, 9, 19, 10, 30, tzinfo=datetime.UTC),
            "half": datetime.datetime(
                2026,
                9,
                19,
                10,
                30,
                tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)),
            ),
        }
    }
    assert tomllib.loads(dumps(fine)) == fine


def test_an_integer_past_the_conversion_limit_round_trips_in_hexadecimal() -> None:
    # `tomllib` converts a hex, octal or binary literal of any length, and `str()` of the result
    # past 4,300 digits raises `ValueError`: `setup`'s rewrite of the owner's machine file and
    # `init`'s re-render of an adopted `drybag.toml` ended in an internal error on one such
    # line. Written as the hexadecimal TOML reads back, which no digit limit bounds. Mutation
    # (declared): the integer spelled with `str` alone again -> `ValueError`.
    large = int("f" * 5_000, 16)
    assert tomllib.loads(dumps({"t": {"n": large}})) == {"t": {"n": large}}
    # A decimal one: the usual spelling, unchanged.
    assert dumps({"t": {"n": 600}}) == "[t]\nn = 600\n"


def test_a_negative_integer_no_toml_spelling_holds_is_refused() -> None:
    # A negative integer past the decimal limit has no TOML spelling (a hex literal has no sign),
    # and no TOML document could have held it: a caller's bug, refused rather than written.
    with pytest.raises(Refusal, match=r"t\.n holds an integer"):
        dumps({"t": {"n": -int("f" * 5_000, 16)}})
