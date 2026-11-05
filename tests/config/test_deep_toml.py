"""Every reader of a TOML document somebody else wrote, handed one past a limit of the parser.

`tomllib` reads nested arrays by recursion, so `a = [[[…]]]` a few thousand levels deep raises
`RecursionError`, not `TOMLDecodeError`; and an integer literal longer than the interpreter
converts raises a plain `ValueError`, which is not a `TOMLDecodeError` either. Uncaught, each is an
internal error, the class stayfixed keeps for its own defects; in a gate run it ended every gate,
and in `stayfixed.toml` it replaced "does not load" with a traceback's name. So each reader answers
both as it answers a document that does not parse, and each case below holds one reader to its own
answer.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from stayfixed.attach import binding, write
from stayfixed.config.loader import loads
from stayfixed.config.overlay import overlay_root
from stayfixed.config.owned import UnparsedDocument, rewrite
from stayfixed.config.plates import PROJECTS, RECORD
from stayfixed.config.reading import TOO_DEEP, TOO_LONG, ConfigError, MachineConfigError
from stayfixed.docs.trail import read_trail
from stayfixed.errors import Failure
from stayfixed.project import init
from stayfixed.setup.machine import read_machine
from tests.parserlimits import LONG_NUMBER
from tests.scriptload import release

# The repository's release script, whose version check is one more reader below.
script = release()

# Past the interpreter's default recursion limit of 1000 with room to spare, on 3.11 to 3.13.
DEPTH = 2000
DEEP = "a = " + "[" * DEPTH + "]" * DEPTH + "\n"
# Valid TOML whose one integer is longer than the interpreter converts.
LONG = "a = " + LONG_NUMBER + "\n"
FINE = '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n'


def _file(tmp_path: Path, relative: str, text: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _record(tmp_path: Path, text: str) -> Path:
    """The overlay's record of the project `widget`, holding `text`."""
    return _file(tmp_path, f"overlay/{PROJECTS}/widget/{RECORD}", text)


def test_the_parser_still_recurses_at_this_depth_and_refuses_this_number() -> None:
    # The premise of every case below: on a `tomllib` that stopped recursing, or one that
    # converted any integer, each would pass for a reason that is not the guard.
    import tomllib

    with pytest.raises(RecursionError):
        tomllib.loads(DEEP)
    with pytest.raises(ValueError) as refused:
        tomllib.loads(LONG)
    assert not isinstance(refused.value, tomllib.TOMLDecodeError)


Case = Callable[[Path, str], object]

READERS = [
    pytest.param(lambda t, d: loads(d, t, machine=t / "absent.toml"), ConfigError, id="loads"),
    pytest.param(
        lambda t, d: loads(FINE, t, machine=_file(t, "machine.toml", d)),
        MachineConfigError,
        id="personal",
    ),
    pytest.param(
        lambda t, d: rewrite(d, {("stayfixed", "version"): "0.2.0"}),
        UnparsedDocument,
        id="owned-rewrite",
    ),
    pytest.param(
        lambda t, d: read_trail(_file(t, "docs/trail.toml", d), "docs/trail.toml"),
        Failure,
        id="trail",
    ),
    pytest.param(
        lambda t, d: binding._recorded(_record(t, d).parents[2], "widget"), Failure, id="binding"
    ),
    pytest.param(
        lambda t, d: overlay_root(_file(t, "machine.toml", d)),
        MachineConfigError,
        id="overlay-root",
    ),
    pytest.param(
        lambda t, d: script._read(_file(t, "pyproject.toml", d).parent, script.PYPROJECT),
        script.MalformedSource,
        id="versions-read",
    ),
    pytest.param(
        lambda t, d: script._pyproject(_file(t, "pyproject.toml", d).parent),
        script.MalformedSource,
        id="versions-pyproject",
    ),
    pytest.param(
        lambda t, d: init._existing(_file(t, "stayfixed.toml", d).parent), Failure, id="init"
    ),
    pytest.param(
        lambda t, d: read_machine(_file(t, "machine.toml", d)), MachineConfigError, id="machine"
    ),
]

DEGRADERS = [
    pytest.param(lambda t, d: write._record_table(_record(t, d)), None, id="record-table"),
]


@pytest.mark.parametrize(("read", "raised"), READERS)
def test_a_reader_answers_a_document_nested_past_the_parser_as_one_that_does_not_parse(
    tmp_path: Path, read: Case, raised: type[Exception]
) -> None:
    # Mutation (declared, one per reader): the reader's `RecursionError` dropped from its catch
    # -> it escapes and this case reddens with the wrong exception.
    with pytest.raises(raised):
        read(tmp_path, DEEP)


@pytest.mark.parametrize(("read", "raised"), READERS)
def test_a_reader_answers_a_number_past_the_parser_as_a_document_that_does_not_parse(
    tmp_path: Path, read: Case, raised: type[Exception]
) -> None:
    # The reader's own type, which a plain `ValueError` is not. Mutations (declared): `ValueError`
    # dropped from `UNPARSEABLE` -> it escapes every reader at once; and each reader's catch
    # narrowed to `TOMLDecodeError`, the per-reader entries, reddens its own case here too.
    with pytest.raises(raised):
        read(tmp_path, LONG)


@pytest.mark.parametrize(("read", "answer"), DEGRADERS)
def test_a_reader_that_degrades_on_a_broken_record_degrades_on_a_deep_one(
    tmp_path: Path, read: Case, answer: object
) -> None:
    # Two readers answer "nothing recorded" for a record they cannot parse; a deep one is such a
    # record. Mutation (declared, one per reader): `RecursionError` dropped from either catch ->
    # it escapes.
    assert read(tmp_path, DEEP) == answer


@pytest.mark.parametrize(("read", "answer"), DEGRADERS)
def test_a_reader_that_degrades_on_a_broken_record_degrades_on_a_long_number(
    tmp_path: Path, read: Case, answer: object
) -> None:
    # A record holding a number past the parser is such a record too: before, `doctor`'s
    # `attached`, `bundles` and `store-debris` rows each went red "could not run". Mutation
    # (declared): `ValueError` dropped from `UNPARSEABLE` -> it escapes.
    assert read(tmp_path, LONG) == answer


def test_the_refusal_names_the_file_and_says_why_without_a_position() -> None:
    # The position `tomllib` reports is the actionable half of a parse failure; a document
    # nested past the parser has none, and the message says what it has instead.
    with pytest.raises(ConfigError) as refused:
        loads(DEEP, Path("/nowhere"), machine=Path("/nowhere/absent.toml"))
    assert str(refused.value).endswith(f"stayfixed.toml' is not valid TOML {TOO_DEEP}")


def test_a_number_past_the_parser_is_refused_in_stayfixeds_words_not_the_interpreters() -> None:
    # The interpreter's message tells the reader to raise a process-wide limit
    # (`sys.set_int_max_str_digits`), which is no remedy for a file somebody else wrote, and it
    # carries no position. Mutation (declared): `toml_position` answering a plain `ValueError`
    # as it answers a `TOMLDecodeError` -> the suffix is `NO_POSITION`.
    with pytest.raises(ConfigError) as refused:
        loads(LONG, Path("/nowhere"), machine=Path("/nowhere/absent.toml"))
    assert str(refused.value).endswith(f"stayfixed.toml' is not valid TOML {TOO_LONG}")


def test_an_integer_of_exactly_the_conversion_limit_still_parses() -> None:
    # The legitimate edge of the readers' widened catch: 4,300 digits is what the interpreter still
    # converts, so such a document parses, and only one past it is a document that does not. No
    # mutation: it pins the interpreter's limit the widened catch relies on, not a line here.
    import tomllib

    assert tomllib.loads("a = " + "9" * 4_300 + "\n") == {"a": int("9" * 4_300)}
