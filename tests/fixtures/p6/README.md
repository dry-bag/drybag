# The no-trace check on an installed release

Whether `drybag attach` delivers the harness into a repository its user cannot commit to and
leaves no trace there: `git status` empty before `attach`, after `attach` and one `SessionStart`,
and after `detach`, and `.git/info/exclude` byte-equal before `attach` and after `detach`. The
oracle is git's own view of the working tree, never a record drybag keeps, so a path placed but
not recorded is seen as well as one recorded.

## The two repositories

**A public clone:** `anthropics/claude-code` at `03b5892ee77de289bcd5dfa39f541525ade74aff`
(2026-10-15T19:21:45Z), fetched at depth 1. It tracks `.claude/commands/*.md`,
`.claude-plugin/marketplace.json` and a `CLAUDE.md`, and no `.claude/settings.json`, `.mcp.json` or
`drybag.toml`, so a session there runs none of its hooks, `env`, `statusLine` or MCP servers.
Read those files, and record their sha256, before any `claude` run in the clone.

**A negation fixture,** built with `git init`: a tracked `.gitignore` holding `.claude/*`, then
`!.claude/settings.json` and `!.claude/rules/`, a tracked `.claude/settings.json` and a tracked
`.claude/rules/*.md`, and an `origin` remote. The negations are what a repository may carry to beat
an exclude line, and a tracked settings file is what `attach` must leave as it was.

## The isolated machine

Every location under one scratch directory, so nothing reaches the machine that runs the check:

```sh
export HOME="$SCRATCH/home"
export CLAUDE_CONFIG_DIR="$HOME/.claude" XDG_CONFIG_HOME="$HOME/.config"
export GIT_CONFIG_GLOBAL="$HOME/.gitconfig" GIT_CONFIG_NOSYSTEM=1
export UV_TOOL_DIR="$HOME/.local/share/uv/tools" UV_TOOL_BIN_DIR="$HOME/.local/bin"
export PATH="$HOME/.local/bin:<claude, git, uv and a Python 3.11 or newer, and nothing else>"
```

A `GIT_CONFIG_GLOBAL` of its own matters: Claude Code may add `**/.claude/settings.local.json` to the
user's global excludes, which hides a settings file left behind. On macOS the system `python3` is
3.9; with no newer one on `PATH` the plugin's hooks continue open and say nothing.

Then, on that machine:

```sh
uv tool install 'drybag==X.Y.Z'
claude plugin marketplace add dry-bag/drybag@vX.Y.Z
claude plugin install drybag@drybag --scope user
drybag setup --overlay "$SCRATCH/overlay"
```

and canaries in the overlay: a rule in `common/claude/rules/`, one in
`projects/<name>/claude/rules/` for each repository, a skill in `common/claude/skills/`, and a
`SessionStart` entry in `common/claude/hooks.json` that echoes a fourth.

## The run, in each repository

1. `git status --porcelain=v1 -z -uall` and `shasum -a 256 .git/info/exclude`.
2. `drybag attach`, then one `SessionStart` (every `SessionStart` entry of the installed plugin's
   `hooks/hooks.json`, fed a `SessionStart` payload naming the repository as `cwd`), then the same
   two readings, and `git check-ignore -v` on each path `attach` placed.
3. `drybag detach`, then the same two readings.

Expected: every status empty; the exclude digest after `attach` differs from the one before; the
digest after `detach` equals the one before; both rule canaries in the `SessionStart` output.

**The control:** a scratch patch, never committed, that makes `attach` write one extra untracked
file. Run again, the status after `attach` names that file.

**The observables, on the bound clone:** `command -v drybag` resolving under the uv tools
directory; the plugin row's `gitCommitSha` in `installed_plugins.json` equal to the commit the
release's marketplace entry pins; an offline `claude -p --debug-file <log>` run, with
`ANTHROPIC_BASE_URL=http://127.0.0.1:9` and an invalid `ANTHROPIC_API_KEY`, whose log holds the
rule and hook canaries and the overlay plugin's skill, and no request that succeeded;
`drybag doctor` with no red row and `attached` ok; no `docs/memory` link tree; and a
`.claude/settings.local.json` holding only the keys `attach` and the plugin install wrote.
