# The drybag demo

`demo.py` builds a small repository in a scratch directory and runs `drybag` against it in the
acts [below](#the-acts). Each act passes only on what `drybag` itself answered: its exit code and
the fields of the one JSON object its `--json` prints. Nothing the script prints is read back, so
an act cannot pass on the script's own word.

## What it needs

- `git` and `python3` on `PATH`. The script installs nothing and reaches no network.
- `claude` (Claude Code) on `PATH` for the act, which installs the overlay's plugin through it. It
  needs no signed-in account there: `HOME` is a scratch directory. Without `claude` the act is
  skipped, and the skip is printed.
- Python 3.11 or later, standard library only. The script never imports `drybag`: it runs the
  program you give it, as a user would.

It makes no model call.

## Running it

```bash
python3 -I examples/demo/demo.py "$(command -v drybag)"
```

The argument is the `drybag` program under test. From a checkout, `uv sync` and then
`uv run python -I examples/demo/demo.py .venv/bin/drybag`.

- `--keep` leaves the scratch directory in place and prints its path.
- `--require-claude` fails the run when the act is skipped, so a skip is never read as a pass.

Every command runs with `HOME` inside the scratch directory, `GIT_CONFIG_NOSYSTEM=1` and a fixed
author, committer and date, so your own configuration changes nothing it does.
The script exits `0` when no act failed, `1` when one did or when the act was skipped under
`--require-claude`, and `2` when the program is not an executable file, cannot start or exits
non-zero on `--version` (run by its own path, never through `PATH`), or when `git` or `python3` is
not on `PATH`.

## The acts

1. `drybag attach` binds the repository to a scratch overlay and delivers this project's skill,
   `demo-canary`, and not the other project's, `other-canary`; `git status` stays empty.
