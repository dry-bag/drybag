"""The import surface: everything a consumer may import from this area.

A module and not the package's `__init__`, for the reason `stayfixed.guards.api` and
`stayfixed.memory.api` both give: area discovery imports a package before it imports the
submodule it wants, so a re-export list in `__init__.py` would pull this whole area — and with
it the configuration layer — into every `discover()` call. `tests/ledger/test_surface.py`
asserts the `__init__` imports nothing at all.

**Outside this area, `stayfixed.project.templates`
(with its tests) imports `render_index` and `bug_register` to write a new project's first index,
and `BUG_RUNBOOK` and `BUG_AUDITS`, joined by `ledger_path`, to write the runbook and audits
README where that index links them; and `stayfixed.docs.plans`
imports `bug_register` for the bug ledger's identifiers — nothing else on this list**, measured
over `src/`, `scripts/` and `tests/`. So every other name below is here on an argument rather
than on a caller, and the argument is written beside it.

What is left is the two artifacts this area leaves on a project's disk, which outlive any area
that reads them:

- the entry file's grammar — `parse_entry`, `load_entries` and the `Entry` they yield, with
  `LedgerError` for a file that will not parse. A `raise` is not a signature, so
  `tests/test_surfaces.py` does not derive `LedgerError`; it is here for the reason that check's
  own comment gives about a class reachable only by writing it down.
- the generated index — `render_index`, which writes it from `Entry`s, and
  `is_generated_index`, which recognises one already on disk rather than overwriting a file a
  person wrote. A tool that touches `docs/bug-reports.md` and cannot ask that question is the
  bug this pair exists to prevent.

Both are read and written against a register: `Register`, with the `Schema` and the `Section`s it
carries, and `bug_register`, which builds the bug ledger's from a project's configuration and links
its runbook and audits directory by the two names `init` writes them under.
`parse_entry`, `load_entries` and `render_index` each take one, so `tests/test_surfaces.py`
derives the three types from their signatures.

`Entry` is also what keeps this surface above `tests/test_surfaces.py`'s own floor, which
refuses a surface exporting no function or record at all.

**What is not here.** The rule vocabulary and the refusal messages `bugs check` reports
(`register_gate` and its constants) stay in `stayfixed.ledger.check`, and the verbs that file or
move an entry (`file_entry`, `next_identifier`, `renumber`) stay in `stayfixed.ledger.write` with
their return types: no area outside this one files or moves an entry without the command, and a type
no published signature names is a value nobody can be handed. An area that needs one grows this
list, in a commit that says which area and why.

Of the six names of the two artifacts, only `render_index` has an importer. Whether this area
publishes at all is a structural decision and the owner's; the list stays above the floor
`tests/test_surfaces.py` holds every surface to.

The identifier grammar and the finding shape are **not** here: they are leaves
(`stayfixed.identifiers`, `stayfixed.findings`), and the surface test pins every export to this
area's own modules, so re-exporting a leaf would redden it. An area that reads the bug ledger's
identifiers takes them from its register, `bug_register(config).ids`, as the `Fixes` claim does: the
prefix is read one way, the way the ledger reads it.
"""

from stayfixed.ledger.entries import Entry, LedgerError, load_entries, parse_entry
from stayfixed.ledger.index import is_generated_index, render_index
from stayfixed.ledger.register import (
    BUG_AUDITS,
    BUG_RUNBOOK,
    Register,
    Schema,
    Section,
    bug_register,
    ledger_path,
)

__all__ = [
    "BUG_AUDITS",
    "BUG_RUNBOOK",
    "Entry",
    "LedgerError",
    "Register",
    "Schema",
    "Section",
    "bug_register",
    "is_generated_index",
    "ledger_path",
    "load_entries",
    "parse_entry",
    "render_index",
]
