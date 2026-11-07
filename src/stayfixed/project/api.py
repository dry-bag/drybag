"""The import surface: everything a consumer may import from this area.

A module and not the package's `__init__`, for the reason `stayfixed.docs.api`,
`stayfixed.ledger.api` and `stayfixed.memory.api` all give: area discovery imports a package
before it imports the submodule it wants, so a re-export list in `__init__.py` would pull this
whole area into every `discover()` call.

Two names, each with the consumer that reaches for it:

- `PROJECT_FILES`, for `scripts/check_artifacts.py`. It asks the built wheel whether the shipped
  template files are actually in it, and before this list existed the only other way to ask was
  to spell those paths a second time in the script — which is the drift a published constant
  exists to stop.
- `project_templates`, for `tests/project/test_fixture.py`, which plans the footprint over a copy
  of the smoke fixture and asserts that the planning has nothing left to create. Not that the
  fixture is what these templates render: the fixture's bug index, roadmap and trail are its own,
  and come back `skip_modified` with bytes that differ from the templates. That module's docstring
  states the measurement. It returns `scaffold.Template`s, which a consumer declares through
  `stayfixed.scaffold`.

`read` is **not** here: it is this area's own, reached by `stayfixed.project.templates` and by
nothing outside it. An area that needs it grows this list deliberately, in a commit that says
which area and why.
"""

from stayfixed.project.layout import PROJECT_FILES
from stayfixed.project.templates import project_templates

__all__ = [
    "PROJECT_FILES",
    "project_templates",
]
