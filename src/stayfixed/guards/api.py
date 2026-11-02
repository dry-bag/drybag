"""The import surface: everything a consumer may import from this area.

A module and not the package's `__init__`, for the same measured reason `stayfixed.memory.api`
gives: `stayfixed.hooks.registry` imports `stayfixed.guards.hooks`, which imports the package
first, so a re-export list in `__init__.py` would pull this whole area into every `discover()`
call and reddens `tests/boundaries/test_discovery.py`. Keeping the surface one level down costs a
consumer six characters and keeps discovery cheap.

The list is what consumers outside this area actually reach for: the git hook, one shared rule,
one gate and the command reader:

- `setup` offers and undoes the git hook (`install`, `uninstall`, `HOOK_NAME`), and `Installed`
  and `Removed` come with the two verbs, because a return type absent from this list is a value
  `setup` can hold and cannot declare; so does `Found`, what `uninstall` found, which its report
  says.
- `setup`'s own tests read the marker that makes a hook stayfixed's (`HOOK_MARKER`). Where the
  hooks live is not this area's to publish: `hooks_dir`, which `attach`, `doctor` and those tests
  ask rather than assume `.git/hooks`, and `git_path`, through which `attach` and `detach` resolve
  `info/exclude`, are `stayfixed.gitenv`'s, a leaf every area reaches without importing another.
- `ledger.scan`, `memory.refs` and `assess`'s probes all ask which roots a configuration's paths
  may reach (`contained_roots`), and two spellings of that would be two answers. A profile's
  red-run hint walks the same roots, handed to it by this area's guard rather than imported.
  `assess`'s `code-roots` probe names the entries those walks leave out, each with its reason
  (`dropped_roots`), read from the same loop, so the entries named and the entries walked cannot
  disagree.
- `assess` runs the `commit` gate (`commit_gate`), `(root, config, base) -> list[Finding]`;
  `commit check` reads the same range through the same `check_range`.
- `prove` reads a test command past its assignments, `env` and `uv run …` the way every red-run
  hint does (`read_launch`, the walk `command_words` returns the last part of, and `Launch`, what
  it returns), so the runner it asks an adapter about is the one they would name; a second
  reading of that launch would be a second answer. It runs the command, so it needs every part:
  the assignments before the launcher, for the run's environment and its forging check, and the
  launcher's words apart from them, for the adapter. It judges the command in the directory the
  launcher runs it in (`run_directory`, `uv run --directory` and `UV_WORKING_DIR`), read from the
  launcher's words.

An area that needs something absent from this list grows it deliberately, in a commit that says
which area and why.

**What is not here.** The commit rules (`offending_lines`, `check_range`, `strip_message` and
their records), the hygiene surface, the rest of the scanner a guard is built on, the failure
attribution and the background-cleanup judge stay in the modules that define them, each
reachable there: no other area imports them, and a name published for a consumer that does not
exist is a claim nothing checks. `assess` needs one name from this area, `commit_gate`, and it is
above.
"""

from stayfixed.guards.bashscan import Launch, read_launch
from stayfixed.guards.commit import commit_gate
from stayfixed.guards.githooks import (
    HOOK_MARKER,
    HOOK_NAME,
    Found,
    Installed,
    Removed,
    install,
    uninstall,
)
from stayfixed.guards.roots import contained_roots, dropped_roots
from stayfixed.guards.uvrun import run_directory

__all__ = [
    "HOOK_MARKER",
    "HOOK_NAME",
    "Found",
    "Installed",
    "Launch",
    "Removed",
    "commit_gate",
    "contained_roots",
    "dropped_roots",
    "install",
    "read_launch",
    "run_directory",
    "uninstall",
]
