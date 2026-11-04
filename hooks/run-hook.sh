#!/bin/sh
# stayfixed hook wrapper: runs the launcher beside it under the `python3` on PATH, else uv's
# interpreter, with `-I`.
# Any fault, the launcher's non-zero exit included, is exit 0 with one line on stderr, so a session
# never dies of stayfixed's own fault. `/bin/sh` is SIP-protected on macOS, so `DYLD_*` variables
# never reach the interpreter below; keep the shebang a system shell.
skip() { echo "stayfixed: $1; continuing open" >&2; exit 0; }
# No usable python3 is stayfixed off, and stderr on a `0` reaches nobody, so the one entry that
# dispatches `SessionStart` says so as the JSON Claude Code shows the person (`systemMessage`) and
# adds to the model's context (`additionalContext`). A `PATH` directory may be named anything, so
# the path goes out narrowed to bytes a JSON string takes unescaped.
off() {
  if test "$call" = "hook SessionStart"; then
    why="there is no python3 on PATH"
    if test -n "$1"; then
      why="$(printf %s "$1" | LC_ALL=C command -p tr -c 'A-Za-z0-9/._+ ~_-' '?')"
      why="$why is not Python 3.11 or newer"
    fi
    line="stayfixed's hooks are off in this session: $why. Install Python 3.11 or newer on PATH."
    printf '{"systemMessage": "%s", "hookSpecificOutput": ' "$line"
    printf '{"hookEventName": "SessionStart", "additionalContext": "%s"}}\n' "$line"
  fi
  skip "$2"
}
call="$1 $2"

case $0 in */*) here=${0%/*} ;; *) here=. ;; esac
launcher="$(CDPATH= cd -- "${here:-/}/.." && pwd)/scripts/stayfixed"
test -f "$launcher" && test -r "$launcher" || skip "no readable launcher at $launcher"

# An inherited GIT_DIR or GIT_WORK_TREE would make every git answer about another repository.
unset GIT_DIR GIT_WORK_TREE
# Every entry but `hook` reads its `--root` default, the directory it runs in, as the project, and
# a version manager's `python3` answers for the directory it runs in, so both are asked from there.
root=${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}
test -z "$root" || CDPATH= cd -- "$root" 2>/dev/null || skip "cannot enter the project root $root"

usable() { test -n "$1" && "$1" -I -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; }
python=$(command -v python3) || python=
if ! usable "$python"; then
  # The program every hook starts comes from `PATH`, which is the person's and the harness's, and
  # from uv asked in `/` with `--no-config`: uv reads `.python-version`, `pyproject.toml` and
  # `uv.toml` from its working directory and its parents, and runs the `.venv/bin/python` it finds
  # there, none of which in `/` is a repository's, so a repository's bytes choose nothing here.
  # `python3` is asked from the project root, as above, because a version manager's shim answers
  # for the directory it runs in. The `cd /` runs in the substitution's subshell, so the launcher
  # still runs in the project root.
  bad=$python
  python=
  if command -v uv >/dev/null 2>&1; then
    python=$(cd / && uv python find --no-config --no-python-downloads '>=3.11' 2>/dev/null)
  fi
  usable "$python" || {
    test -n "$bad" || off "" "no python3 on PATH"
    off "$bad" "$bad is not python 3.11 or newer"
  }
fi
"$python" -I "$launcher" "$@" || skip "stayfixed exited $?"
