from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from drybag.overlay.api import requires_of, satisfies
from drybag.overlay.layout import IDENTITY_RECORD
from drybag.overlay.template import template_root
from tests.parserlimits import LONG_NUMBER


def overlay_with(root: Path, requires: object) -> Path:
    """An overlay directory whose identity record declares `requires`; the doctor, attach and setup
    suites plant their overlays with it too."""
    root.mkdir(parents=True, exist_ok=True)
    # `json.dumps` spells a TOML basic string: the same quotes and the same `\\uXXXX` escapes.
    declared = "" if requires is None else f"requires = {json.dumps(requires)}\n"
    (root / IDENTITY_RECORD).write_text(
        f'owner = "ci"\nname = "overlay"\n{declared}layout = 1\n', encoding="utf-8"
    )
    return root


def test_the_shipped_template_declares_a_floor_this_reader_reads() -> None:
    spec = requires_of(template_root())
    assert spec is not None and satisfies(spec, "0.1.0") is not None


def test_an_absent_declaration_and_an_absent_record_both_answer_none(tmp_path: Path) -> None:
    assert requires_of(overlay_with(tmp_path / "a", None)) is None
    assert requires_of(tmp_path / "nowhere") is None
    assert requires_of(overlay_with(tmp_path / "b", " >=0.1.0 ")) == ">=0.1.0"


def test_a_record_past_the_parsers_reach_is_nothing_declared(tmp_path: Path) -> None:
    # Valid TOML nested past what `tomllib` follows raises `RecursionError`, and an integer longer
    # than the interpreter converts a plain `ValueError`, neither of them a `TOMLDecodeError`.
    # Escaping, either ended a function whose docstring promises `None` for anything it cannot
    # read, and the session handler's backstop swallowed every other line of the same result
    # with it.
    root = tmp_path / "overlay"
    root.mkdir()
    for body in ("requires = " + "[" * 20_000 + "]" * 20_000, "requires = " + LONG_NUMBER):
        (root / IDENTITY_RECORD).write_text(body + "\nlayout = 1\n", encoding="utf-8")
        assert requires_of(root) is None, body[:16]


def test_a_fifo_at_the_identity_record_is_unreadable_to_its_readers_without_waiting(
    tmp_path: Path,
) -> None:
    # A reader that opened the record with `read_text` would wait on a FIFO for a writer that
    # never comes, and `requires_of` is asked by the SessionStart hook. The record is read
    # through `identity.identity_record`, a regular file only, so a FIFO is nothing declared;
    # `overlay_fault`'s answer for one comes from the `is_file` gate above that read. In a child
    # under a timeout, so a regression fails this case rather than hanging. Mutation (oracle):
    # `mutations/`'s "the identity record is read without asking what it is" -> the child waits
    # and this times out.
    root = overlay_with(tmp_path / "overlay", ">=0.1.0")
    (root / IDENTITY_RECORD).unlink()
    os.mkfifo(root / IDENTITY_RECORD)
    probe = (
        "import sys\n"
        "from pathlib import Path\n"
        "from drybag.overlay.api import requires_of\n"
        "from drybag.overlay.identity import identity_record, overlay_fault\n"
        "root = Path(sys.argv[1])\n"
        "print(identity_record(root), requires_of(root), overlay_fault(root) is not None)\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, str(root)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("a reader of the overlay's identity record waited on a FIFO")
    assert done.stdout == "None None True\n", done.stderr


def test_the_floor_is_compared_as_numbers_not_as_text() -> None:
    # Mutation (comment): compare `running.groups() >= floor.groups()` as strings -> the first
    # line reddens on `>=9.0.0` against `10.0.0`.
    #
    # And the boundary itself, which is the classic off-by-one site: a floor a running version
    # meets exactly is met. Mutation: `mutations/`'s "the declared floor stops being met by
    # the version that equals it".
    assert satisfies(">=9.0.0", "10.0.0") is True
    assert satisfies(">=0.1.0", "0.1.0") is True
    assert satisfies(">=0.1.0", "0.0.9") is False


@pytest.mark.parametrize(
    "version",
    ["1.0.0rc1", "1.0.0.dev0", "1.0.0-rc.1", "1.0.0a1", "1.0.0rc1.post2", "1.0.0.dev3+g1234abc"],
)
def test_a_pre_release_of_the_floor_does_not_meet_it(version: str) -> None:
    # `semver.later` orders a release after its own pre-release, and the floor compared the
    # leading triple alone, so a `1.0.0rc1` build met an overlay's `>=1.0.0` that `later` says
    # it comes before: the session line and the `overlay-requires` row read it as met. A
    # compound suffix carrying a pre-release segment does not meet it either. Mutations:
    # `mutations/`'s "the declared floor is met by a pre-release of it" and "a pre-release
    # segment no longer makes a pre-release".
    assert satisfies(">=1.0.0", version) is False
    assert satisfies(">=0.9.9", version) is True


# What the floor `>=1.0.0` answers, one row a shape: met by a later triple whatever follows it, by
# its own triple unless a pre-release of it follows, never by an earlier one. `satisfies` was a
# chain of `semver.later`, `semver.pre_release` and a tuple comparison, and these are the chain's
# answers, kept by the one comparison that replaced it; a differential over ten million floors and
# versions found no other difference. `1.0.0rcdev` and `1.0.0adev1` are a pre-release word run into
# its `dev`, which a reading of each segment as a word of its own met the floor with. Mutations
# (oracle): `mutations/`'s "the declared floor is met by a pre-release of it", "the declared floor
# stops being met by the version that equals it" and "the declared floor is not met by the version
# equal to it" -> the rows of the floor's own triple. The segments PEP 440 lets run together with no
# separator are read as it reads them: `1.0.0.post1dev2` is `1.0.0.post1.dev2`, which met the floor
# at 0.2.0 and then stopped meeting it under a search for each segment as a word of its own, and
# `1.0.0rc1post2` is a pre-release that search met the floor with. A further release component other
# than zero is a later release, `1.0.0.1rc1` among them. Mutations (oracle): `mutations/`'s
# "segments run together are no suffix PEP 440 allows", "a further release component is read as no
# later release", "a local label is no part of the suffix grammar", "a pre-release segment no longer
# makes a pre-release", "a development release of a post-release reads as a pre-release" and "a
# suffix outside PEP 440 reads as a pre-release". The answers agree with `packaging`'s ordering over
# every combination of segment, spelling and separator, 5,055 versions, checked offline.
FLOOR_ANSWERS = [
    ("1.0.0", True),
    ("1.0.1", True),
    ("1.0.1rc1", True),
    ("2.0.0.dev1", True),
    ("0.9.9", False),
    ("0.9.9.post1", False),
    ("1.0.0rc1", False),
    ("1.0.0-rc.1", False),
    ("1.0.0.dev0", False),
    ("1.0.0rcdev", False),
    ("1.0.0adev1", False),
    ("1.0.0rc1.post2", False),
    ("1.0.0rc1+local", False),
    ("1.0.0.dev3+g1234abc", False),
    ("1.0.0.post1", True),
    ("1.0.0-1", True),
    ("1.0.0+local", True),
    ("1.0.0+local.rc1", True),
    ("1.0.0.post1.dev2", True),
    ("1.0.0.post1dev2", True),
    ("1.0.0post1dev2", True),
    ("1.0.0rc1post2", False),
    ("1.0.0a1r1dev", False),
    ("1.0.0.1rc1", True),
    ("1.0.0.0rc1", False),
    ("1.0.0x", True),
    ("v1.0.0", None),
]


@pytest.mark.parametrize(("version", "met"), FLOOR_ANSWERS)
def test_the_floor_is_met_by_a_later_triple_or_its_own_and_never_a_pre_release_of_it(
    version: str, met: bool | None
) -> None:
    assert satisfies(">=1.0.0", version) is met


def test_a_suffix_later_leaves_unordered_still_meets_the_floor_by_its_triple() -> None:
    # The legitimate user: `.post1` and `+local` builds, which `later` declines to order against
    # the bare version, keep the answer the triple gives, a floor equal to it met. Mutation:
    # `mutations/`'s "the declared floor stops being met by the version that equals it".
    assert satisfies(">=1.0.0", "1.0.0.post1") is True
    assert satisfies(">=1.0.0", "1.0.0+local") is True
    # A local label is no segment of the version's own, whatever it spells, and a development
    # release of a post-release comes after the release. Mutation: `mutations/`'s "a development
    # release of a post-release reads as a pre-release".
    assert satisfies(">=1.0.0", "1.0.0+local.rc1") is True
    assert satisfies(">=1.0.0", "1.0.0.post1.dev2") is True
    assert satisfies(">=1.0.1", "1.0.0.post1") is False


def test_any_other_form_is_unreadable_never_satisfied() -> None:
    for spec in ("~=1.0", ">1.0.0", "==0.1.0", ">=1.0", ">=a.b.c", ""):
        assert satisfies(spec, "0.1.0") is None, spec
    assert satisfies(">=0.1.0", "next") is None


def test_a_component_too_long_to_convert_is_unreadable_and_not_an_exception() -> None:
    """`satisfies` answers for every string, which is what its `None` is worth.

    CPython 3.11 refuses `int()` on a string past 4300 digits, so an unbounded `(\\d+)` in
    either pattern turned an overlay record an owner can mistype into a `ValueError`: red in
    `doctor` as "this check could not run", and in the session handler swallowed by the
    backstop that then dropped `NOT_ATTACHED` and every other line of the same result. The
    value is asserted rather than the crash, because the crash is the thing being removed.

    Mutation: `mutations/`'s "the version grammar stops bounding its components".
    """
    long = "9" * 5000
    assert satisfies(f">={long}.0.0", "0.1.0") is None
    assert satisfies(">=1.0.0", f"{long}.0.0") is None
    # Ten digits, which is the first length past the bound rather than the first past `int()`.
    assert satisfies(">=1234567890.0.0", "0.1.0") is None


def test_only_ascii_digits_are_a_version(tmp_path: Path) -> None:
    """`\\d` matches every Unicode decimal digit and `int()` converts them, so a floor written
    in Eastern Arabic-Indic numerals validated, compared as `>=1.0.0`, and printed back
    verbatim — `requires_of` returns the record's own bytes, and the session line and the
    `doctor` row print the spec they validated. A version is ASCII or it is unreadable.

    The digits are spelled as escapes so this file stays ASCII; the record a repository
    writes carries them as bytes, which is what the last assertion says."""
    eastern = ">=\u0661.\u0660.\u0660"
    assert satisfies(eastern, "0.1.0") is None
    assert satisfies(">=0.1.0", "\u0661.\u0660.\u0660") is None
    # Non-vacuous: the record really does hand this string back, which is why the verdict
    # above is what keeps it out of a line a model reads.
    assert requires_of(overlay_with(tmp_path / "eastern", eastern)) == eastern
