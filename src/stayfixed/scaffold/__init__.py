"""The scaffold engine: manifest, regions, keyed entries, plan and apply.

Everything a consumer needs is re-exported here, including the primitives other areas reach for
directly: `owned_ids` for the ids an
earlier `attach` recorded in its ledger, `mark` for any caller that builds `Template.entries`,
`drop` / `apply_entries`, and `withdraw_entries` for `attach` and `detach`, which take back
the entries an earlier `attach` recorded and no other. The three refusals a consumer has to
catch by name are here too: a caller that cannot import `ManifestError`, `RegionError` or
`EntriesError` from this list has no way to tell a bad merge from a bug except by catching
`Refusal` whole; `ParserLimitError`, an `EntriesError` too, is the valid JSON past a limit of the
parser that `attach` must tell from a malformed document. Importing a private module of this
package from another area is a review finding; if an area needs something this list does not
carry, the list grows deliberately.
"""

from stayfixed.scaffold.engine import (
    apply,
    plan,
    validate_sources,
)
from stayfixed.scaffold.entries import (
    EntriesError,
    ParserLimitError,
    apply_entries,
    mark,
    marker_id,
    owned,
    owned_ids,
    settings_object,
    settings_text,
    withdraw_entries,
)
from stayfixed.scaffold.manifest import (
    FORMAT,
    MANIFEST_PATH,
    Kind,
    Location,
    Manifest,
    ManifestError,
    Record,
    digest,
)
from stayfixed.scaffold.model import Action, Applied, Plan, Refused, Template, Verb
from stayfixed.scaffold.regions import RegionError, Style, drop, extract, upsert
from stayfixed.scaffold.report import printable, render_report

__all__ = [
    "FORMAT",
    "MANIFEST_PATH",
    "Action",
    "Applied",
    "EntriesError",
    "Kind",
    "Location",
    "Manifest",
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
    "apply_entries",
    "digest",
    "drop",
    "extract",
    "mark",
    "marker_id",
    "owned",
    "owned_ids",
    "plan",
    "printable",
    "render_report",
    "settings_object",
    "settings_text",
    "upsert",
    "validate_sources",
    "withdraw_entries",
]
