"""How one version orders against another: the reader `upgrade` and `doctor` share, so the two
cannot disagree about which way a recorded version lies."""

from __future__ import annotations

import pytest

from stayfixed.semver import RELEASE, later


def test_a_component_past_nine_digits_is_no_version_and_never_an_exception() -> None:
    # `int()` refuses a string past 4300 digits, so an unbounded component turned a recorded version
    # into a `ValueError` out of `later`, which `upgrade` and `doctor` call on a version a
    # repository wrote. The value is asserted rather than the crash, because the crash is the thing
    # being removed. Mutation (declared): `mutations/`'s "the version grammar stops bounding its
    # components".
    long = "1" * 5000
    assert later(f"{long}.0.0", "0.1.0") is None
    assert later("0.1.0", f"{long}.0.0") is None
    # Ten digits, the first length past the bound rather than the first past `int()`, with nine
    # beside it so the refusal is the bound's and not the pattern's.
    assert later("1234567890.0.0", "0.1.0") is None
    assert RELEASE.match("1234567890.0.0") is None
    assert later("123456789.0.0", "0.1.0") is True
    assert RELEASE.match("123456789.0.0") is not None


def test_a_version_in_digits_that_are_not_ascii_is_no_version() -> None:
    # `\d` matches every Unicode decimal digit and `int()` converts them, so `1.0.0` spelled in
    # Eastern Arabic-Indic numerals ordered as a release and passed `RELEASE`, which is what
    # `upgrade` checks before it prints a recorded version back. Spelled as escapes so this file
    # stays ASCII. Mutation (declared): `mutations/`'s "the version grammar stops bounding its
    # components".
    eastern = "\u0661.\u0660.\u0660"
    assert later(eastern, "0.1.0") is None
    assert later("0.1.0", eastern) is None
    assert RELEASE.match(eastern) is None


def test_later_reads_each_version_s_leading_triple_and_answers_none_without_one() -> None:
    # A suffix does not hide a newer release, and a shape with no leading `X.Y.Z` is unknown
    # rather than older: `upgrade` moved `1.0.0-rc1` and `v1.0.0` down to the running `0.1.0`
    # while this answered through `satisfies`, which needs an exact floor.
    assert later("1.0.0-rc1", "0.1.0") is True
    assert later("0.10.0", "0.9.9") is True
    assert later("0.1.0", "0.1.0") is False
    assert later("0.0.9", "0.1.0") is False
    for unreadable in ("v1.0.0", "", "one"):
        assert later(unreadable, "0.1.0") is None, unreadable


@pytest.mark.parametrize(
    ("version", "than", "answer"),
    [
        # A release is later than its own pre-release, whichever side each is on and however the
        # pre-release is spelled; read by the triple alone both of the first two were `False`, and
        # a pre-release build moved a project recording the release down to itself.
        ("1.0.0", "1.0.0rc1", True),
        ("0.2.0", "0.2.0.dev0", True),
        ("1.0.0", "1.0.0-rc.1", True),
        ("1.0.0", "1.0.0a1.dev2", True),
        ("1.0.0rc1", "1.0.0", False),
        ("0.2.0.dev0", "0.2.0", False),
        ("1.0.0rc1", "1.0.0rc1", False),
        # Two pre-releases, or a suffix that is not one, are not ordered: `.post1` is later than
        # the bare version, so reading every suffix as a pre-release would move it backward.
        ("1.0.0rc1", "1.0.0rc2", None),
        ("1.0.0.dev0", "1.0.0rc1", None),
        ("1.0.0.post1", "1.0.0", None),
        ("1.0.0", "1.0.0.post1", None),
        ("1.0.0+local", "1.0.0", None),
        # A suffix that begins as a pre-release and goes on past one is not a pre-release.
        ("1.0.0", "1.0.0rc1.post2", None),
        # The triple still decides whenever it differs, whatever follows it.
        ("1.0.1rc1", "1.0.0", True),
        ("0.9.9", "1.0.0rc1", False),
    ],
)
def test_equal_triples_order_a_release_after_its_pre_release_and_nothing_else(
    version: str, than: str, answer: bool | None
) -> None:
    # Mutation (oracle): `mutations/`'s "a release reads as older than its own pre-release" -> the
    # rows whose answer is `True` with a bare `version` redden.
    # Measured by hand: `_PRE_RELEASE` without its closing `\Z` -> `1.0.0rc1.post2` reads as a
    # pre-release and its row answers `True`.
    assert later(version, than) is answer
