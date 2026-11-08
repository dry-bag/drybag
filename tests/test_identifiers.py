from __future__ import annotations

from stayfixed.identifiers import BUG_FIXES


def test_a_fixes_claim_takes_three_digits_or_more() -> None:
    # Two digits is a different shape, and a lint that accepts it asks a plan for a premise over a
    # number that was never an identifier. Oracle: `mutations/`'s "a Fixes claim accepts fewer than
    # three digits".
    assert BUG_FIXES.search("Fixes BR-042.") is not None
    assert BUG_FIXES.search("Fixes BR-2345") is not None
    assert BUG_FIXES.search("Fixes BR-42.") is None


def test_a_fixes_claim_is_bounded_by_word_edges_and_names_the_fixed_prefix() -> None:
    assert BUG_FIXES.search("Prefixes BR-042") is None
    assert BUG_FIXES.search("Fixes BR-0421x") is None
    assert BUG_FIXES.search("Fixes DF-042") is None
