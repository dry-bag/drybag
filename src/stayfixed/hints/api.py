"""The import surface: everything a consumer may import from this area.

A module and not the package's `__init__`, for the reason every area's surface is one: area
discovery imports a package before the submodule it wants, and the package stays empty of imports.

The list is what consumers outside this area actually reach for: the command reader and the
dirty count:

- `prove` reads a test command past its assignments, `env` and `uv run …` the way every red-run
  hint does (`read_launch`, the walk `command_words` returns the last part of, and `Launch`, what
  it returns), so the runner it asks an adapter about is the one they would name; a second
  reading of that launch would be a second answer. It runs the command, so it needs every part:
  the assignments before the launcher, for the run's environment and its forging check, and the
  launcher's words apart from them, for the adapter. It judges the command in the directory the
  launcher runs it in (`run_directory`, `uv run --directory` and `UV_WORKING_DIR`), read from the
  launcher's words.
- `guards`' `stayfixed test hygiene` counts the uncommitted changes the red-run note counts
  (`dirty_count`), so the command and the note cannot disagree about whether a tree is dirty.

An area that needs something absent from this list grows it deliberately, in a commit that says
which area and why.

**What is not here.** The red-run note's own reading (`red_exit`, `simple_commands`, `notice`,
`context_for`), the rest of the scanner the hints are built on and the background-cleanup judge
stay in the modules that define them, each reachable there: no other area imports them, and a
name published for a consumer that does not exist is a claim nothing checks.
"""

from stayfixed.hints.bashscan import Launch, read_launch
from stayfixed.hints.hygiene import dirty_count
from stayfixed.hints.uvrun import run_directory

__all__ = [
    "Launch",
    "dirty_count",
    "read_launch",
    "run_directory",
]
