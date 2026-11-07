"""What `stayfixed.scaffold` publishes, which is the whole of the engine's contract for a caller."""

from __future__ import annotations

from stayfixed import scaffold
from stayfixed.errors import Refusal
from stayfixed.scaffold import EntriesError, ManifestError, ParserLimitError, RegionError

EXPORTED = [
    "FORMAT",
    "MANIFEST_PATH",
    "Action",
    "Applied",
    "EntriesError",
    "Kind",
    "Location",
    "ManifestError",
    "ParserLimitError",
    "Plan",
    "Record",
    "Refused",
    "RegionError",
    "Style",
    "Template",
    "Verb",
    "apply",
    "digest",
    "drop",
    "extract",
    "mark",
    "marker_id",
    "plan",
    "render_report",
    "settings_object",
    "settings_text",
    "upsert",
]


def test_the_three_refusals_a_consumer_catches_by_name_are_exported() -> None:
    # `Manifest.read` raises `ManifestError`, `drop` raises `RegionError`, and `settings_object`
    # raises `EntriesError`. The package docstring makes importing a private
    # module of it from another area a review finding, so while these three were absent from the
    # list a consumer had to choose between that finding and catching `Refusal` whole — which
    # also swallows the malformed-`Template` bug the engine raises on purpose.
    for name in ("ManifestError", "RegionError", "EntriesError"):
        assert name in scaffold.__all__
    assert issubclass(ManifestError, Refusal)
    assert issubclass(RegionError, Refusal)
    assert issubclass(EntriesError, Refusal)


def test_a_document_past_a_limit_of_the_parser_is_an_entries_refusal_of_its_own_kind() -> None:
    # `settings_object` raises `ParserLimitError` for valid JSON past a limit of the parser.
    # `doctor` tells it from a malformed document by name, and every caller that catches
    # `EntriesError` still catches it.
    assert "ParserLimitError" in scaffold.__all__
    assert issubclass(ParserLimitError, EntriesError)


def test_the_published_list_is_exactly_this_and_every_name_resolves() -> None:
    # Five downstream areas consume this surface, so the list may grow and may not shrink or
    # rename. Spelled out rather than counted, so a swap cannot pass for a no-op.
    assert scaffold.__all__ == EXPORTED
    assert [name for name in EXPORTED if not hasattr(scaffold, name)] == []
