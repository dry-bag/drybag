# stayfixed

A methodology harness for coding agents: a bug ledger that lives in the repository, a
working memory whose index is rendered rather than written, guards that fail closed where
the platform lets them, and an adoption state machine that runs each gate advisory until the
repository has earned it. One plugin for Claude Code and Codex, one Python package with
**no runtime dependencies**.

> **Pre-1.0.** What ships is a core and three delivery areas. The **core** is what stayfixed does
> without its private layer: the methodology's gates, the records they check, and a machine's setup.
> It holds the bug ledger; the documentation and plan lints; the guards over a shell call, a commit
> message and a test run; the scaffolding engine that writes files into a repository;
> `stayfixed init`, which writes a repository's scaffold from the shipped project templates,
> `stayfixed upgrade`, which refreshes it, and `stayfixed uninstall`, which takes it back;
> `stayfixed assess`, which inventories what stands between a repository and enforcement;
> `stayfixed gate`, which judges a change against what its base branch enforces; `stayfixed adopt`,
> which enforces a repository's gates as each one passes; `stayfixed setup`, which configures a
> machine from a preset; and `stayfixed doctor`, which reports on the result. The **delivery** areas
> are the private layer: `memory`, the note store; `overlay`, the private overlay
> — `overlay upgrade`, with `setup --overlay` making it; and `attach`,
> whose `attach` binds a repository to the overlay and whose `detach` takes back what `attach`
> wrote, keeping the overlay's record of the binding ([CONTRIBUTING.md](https://github.com/stayfixed/stayfixed/blob/main/CONTRIBUTING.md#areas) says
> where the line between the two runs). The core is language-neutral, and a stack is a **profile**:
> one stack's test runner, build artifacts and package manager belong to its profile — data, and
> optionally the advice to give after that stack's test runner fails — so a repository in several
> languages gets each stack's advice with no configuration. The first profile, `python`, ships:
> every agent is handed its rules, `stayfixed assess` runs its checks, and the stale-bytecode line
> of the note after a failing pytest run is its own. The hooks file that wires all of it into a
> session ships too, so on Claude Code installing the plugin is enough to make the guards fire and
> the memory bundles arrive ([what each agent enforces](#what-each-agent-enforces)). The first
> skills ship with them, and so does one command meant for a machine rather than for you — `hook`,
> which dispatches one harness event. **Not yet:** the memory MCP server, a hold-the-line baseline,
> the `uvx` form of the gate, and adapters for Cursor or Hermes — each leaves this list in the
> change that ships it. The [Quickstart](#quickstart) shows the three keys that are enough to start
> a project by hand, which `init` reads as your answers — a run that writes the file itself writes
> `[stayfixed] version` and `agents`, and `profile` when the repository carries a shipped
> profile's markers or `--profile` names one, beside `[project] name`, `base_branch` and
> `release_branch`, a `[ci]` table only when it has a released commit to pin or `--no-ci` asks for
> none, a `[memory]` table only when `--memory-mode` answers it, and an `[artifacts]` table only
> when `--local` does. [docs/cli.md](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md) is the reference; the command list below is held
> to the parser by a test, so it is complete for what ships.

## What this is, and what it is not

Two kinds of tool already exist for working with a coding agent. A process layer such as
superpowers tells the agent *how* to work — brainstorm, plan, test first, review. A spec
layer such as spec-kit tells it *what* to build. Neither remembers what went wrong last
time, and neither has a way to introduce rules into a repository that does not yet follow
them.

This project looked through the community plugin marketplace on 2026-09-05 and counted about
2,300 plugins listed that day. That is one project's dated count rather than a survey with a
method — no row in [sources.md](https://github.com/stayfixed/stayfixed/blob/main/docs/methodology/sources.md) backs it, and it says what that
look found, not what exists. What it did not find anywhere else is the three things stayfixed
adds:

- **A bug ledger as a first-class repository artifact** — one file per bug, a generated
  index, a "what this evidence does not establish" line the tooling insists on, and skills
  that teach the agent how to read an entry.
- **Enforcement earned per gate**, in which each gate runs advisory until the repository has
  earned it. `stayfixed assess` says what stands in the way, and `stayfixed adopt promote`
  enforces a gate once it passes, by listing it in `[stayfixed] enforced`.
- **A personal overlay that is a versioned repository of its own**, named by its identity record
  and with its own upgrade manifest, rather than a dotfiles sync. `stayfixed setup --overlay` renders or generates one and `stayfixed attach`
  binds a repository to it: the hooks, skills, agents and allow rules you keep there reach that
  repository's sessions, and so do your rules — `claude/rules/*.md` in `common/`, in each
  tag your project lists (`groups/<tag>/`) and in `projects/<name>/`, a standing rule at every session's start and one with
  `paths:` frontmatter the first time a session reads or edits a file its globs match. It also *declares* the stayfixed it needs, in its identity record;
  `stayfixed doctor` reads it and reports it when the stayfixed running is too old — red when
  this project keeps its notes in that overlay, a warning when it does not — and a session in a
  bound repository says so once at its start.

Two more practices ride along and are named as such: every branch that decides a verdict, a
containment or a data-loss path ships with the mutation that reddens its test, and working memory
is a routing table of hand-written lines, not a summary. The principles behind all of it, with dated sources and an honest note where the
backing is thin, are in [docs/methodology/README.md](https://github.com/stayfixed/stayfixed/blob/main/docs/methodology/README.md).

**This is not a replacement for superpowers.** `stayfixed init` recommends it, and
[context7](https://github.com/upstash/context7), and `stayfixed setup --plugin superpowers
--plugin context7` installs them on Claude Code — both ship in Anthropic's own official
marketplace, so `setup` needs no separate registration step for either. Neither is installed
unless you name it: each runs in every session, and neither is pinned. **Codex has no verified non-interactive marketplace source for either plugin** (checked
against this project's own spike record and each plugin's own published install instructions,
2026-09-18): install `superpowers` and `context7` by hand there if you use Codex, the same way
you would install any other Codex plugin — `setup` reports this as a note rather than guessing a
marketplace name (nothing is vendored on a guess). The `adopt` skill, which `init` offers as
its last step, brainstorms the adoption through superpowers where it is present.

## What each agent enforces

stayfixed reaches an agent in three ways, and they do not hold alike on every agent. The
**session notices** add context and refuse nothing (the background-cleanup hints, the pipe-status hint, the test-hygiene
note, the standing rules, the volatile notes); the **repository gates** — the bug, documentation,
plan, commit and trail checks — run in CI through the reusable workflow; and the **methodology** is
the skills and the `AGENTS.md` region. Each column is an agent under the name `[stayfixed] agents`
lists it by: `claude` is Claude Code and `codex` is Codex.

| Surface | `claude` | `codex` |
|---|---|---|
| session notices | context only | not verified |
| repository gates | CI only | CI only |
| methodology | instructions only | instructions only |

The background-cleanup hints, from the `bg-cleanup` handler that `stayfixed hook PreToolUse` runs
on every shell call, name a command the agent runs in the background that leaves an `&` job behind
with no `trap … EXIT` or trailing `wait` to stop it, or that begins with `sleep`, and the remedy;
they never refuse it. They run in every repository, one with no `stayfixed.toml` or one a session
cannot use included, and the session hears once, when it starts, what it could not use. A repository may switch them off by default in its
`stayfixed.toml`, and the owner's layers override it: the overlay's files, and the machine file
last ([`docs/cli.md`](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md#configuration)
names the key).

The pipe-status hint, from the `pipe-status` handler that runs beside it, names a test run piped into
`tail`, `head` or `grep` in a command whose text keeps no `pipefail` or `PIPESTATUS` (or zsh's spelling of either), where the pipeline's exit status
is the reader's and a red run reads as green, and the remedy; it says so once per session context
and never refuses the command. It reads a flat list of pipelines and nothing else: a command with a substitution or a
heredoc gets no hint. It reads the command alone, so it has no switch and
runs in every repository too.

Where a surface does not reach an agent in the session, the repository gates
still hold in CI, which every agent's changes pass through. What was measured of Codex
(Codex CLI 0.162.0-alpha.17.2) is its side: it runs a plugin's hooks once they are trusted in
`/hooks`, skips untrusted ones without a message and runs them anyway under
`--dangerously-bypass-hook-trust`, and a blocking `PreToolUse` hook's reason reaches the model.
Codex delivers a failed command on `PostToolUse` with no exit code, so the note after a failing
test run does not speak on Codex. Whether a stayfixed hook is trusted on Codex is not measured:
nothing here knows how Codex records hook trust, so the table above is where what holds on Codex
is said, and `stayfixed doctor` has no row for it. Of your overlay, `stayfixed attach` delivers
Codex its rules alone, copied into `.codex/rules/`; its hooks, skills and agents reach Claude Code
through the plugin `attach` renders and are not delivered to Codex.

## Install

**Released as 0.6.1.** The plugin form below takes that release's tag. `uv tool install
stayfixed` names no version, so it installs the newest release on PyPI:

As a Claude Code plugin:

```
/plugin marketplace add stayfixed/stayfixed@v0.6.1
/plugin install stayfixed@stayfixed-marketplace
```

The marketplace in `stayfixed/stayfixed` fetches the plugin from
[`stayfixed/stayfixed-plugin`](https://github.com/stayfixed/stayfixed-plugin) at the release's
tag: a repository holding only what the plugin runs, generated from `stayfixed/stayfixed` at each
release.

As a command-line tool:

```bash
uv tool install stayfixed
```

In CI, a project calls the reusable workflow at a commit SHA;
[docs/cli.md](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md#the-reusable-workflow) shows the caller `stayfixed init` writes.

**Requirements: Python 3.11 or newer, and a POSIX system.** Linux and macOS are supported and
tested; Windows is not. The containment this project is built on uses `openat` with
`O_NOFOLLOW` and `O_DIRECTORY`, which have no Windows equivalent.

## Quickstart

Three keys in a `stayfixed.toml` at the root of a repository start a project; every other key
takes the `recommended` preset's default, and [docs/cli.md](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md#configuration) lists all
of them, annotated.

```toml
[stayfixed]
version = "0.6.1"

[project]
name = "widget"          # one lowercase path segment

[memory]
groups = ["developer"]   # the preset names four; the store below has one
```

`stayfixed init --yes` writes that file for you — the name from `origin`, the base branch, the
agent surfaces this repository carries — along with the documentation skeleton the other
commands expect and, once there is a stayfixed release to pin, a CI workflow.
`stayfixed init --questions` shows each value it would take and where it came from, and a flag
on `--yes` replaces any of them. Read it before it runs; a `stayfixed.toml` you wrote yourself
is read as your answers rather than replaced:

```bash
stayfixed init --yes --dry-run   # both plans, every file named, nothing written
stayfixed init --yes
```

The default memory mode keeps notes under `.stayfixed/local/memory/`, git-ignored, one
directory per group. Write one note and render the index:

```bash
mkdir -p .stayfixed/local/memory/developer
printf -- '---\nname: first-note\ndescription: "When to open this note"\n---\n\nThe note.\n' \
  > .stayfixed/local/memory/developer/first-note.md
stayfixed memory index      # renders .stayfixed/local/memory/MEMORY.md from the notes
stayfixed doctor            # fourteen checks over this installation, one line; --json has the remedies
```

These notes are inside the repository, so they reach a session as data and never as standing
rules; [The threat model, in one paragraph](#the-threat-model-in-one-paragraph) says why.
Add `.stayfixed/local/` to `.gitignore` if it is not there already.

The other commands in [Commands](#commands) expect more of a repository than those three keys
create: `docs check` wants an `AGENTS.md`, `docs trail` a `docs/roadmap.md`, `bugs check` a
ledger entry. `stayfixed init --yes` writes all of those, which is what it is for; in a
repository you would rather grow by hand, add each path as you start using the command that
reads it — [docs/cli.md](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md#configuration) lists every default.

## What it writes, and where

stayfixed writes files. Being specific about which is the point of this section.

| Path | What it is | Written by |
|---|---|---|
| `stayfixed.toml` | Your project's configuration, committed | `stayfixed init`, once — into a file you wrote, only a missing `[stayfixed] version`; you after |
| `docs/memory/` (configurable) | The note store, in `in-repo` and `overlay` mode | `stayfixed memory index` |
| `.stayfixed/local/memory/` | The note store in `local-only` mode — git-ignored | `stayfixed memory index` |
| `<store>/MEMORY.md` | The rendered routing index. **Generated — do not hand-edit** | `stayfixed memory index` |
| `docs/bugs/` and `docs/bug-reports.md` (configurable) | One file per bug, and the generated index over them | `stayfixed init` writes the empty index and `docs/bugs/audits/README.md`; `stayfixed bugs new`, `bugs index` and `bugs renumber` after |
| `docs/roadmap.md` and `docs/roadmap-history.md` (configurable) | The forward track and the closed phases; in the roadmap, `docs trail` owns only the listing between its two markers | `stayfixed init` writes both files; `stayfixed docs trail` rewrites the listing |
| `docs/trail.toml` (beside the roadmap) | Which theme each design or plan document belongs to, and which are not plainly delivered. Read by `docs trail`, never written by it | `stayfixed init`, once; you after |
| `AGENTS.md`, `CLAUDE.md`, `docs/architecture/`, `docs/adr/`, `docs/runbooks/`, `docs/specs/`, `docs/plans/`, `.github/workflows/stayfixed.yml` | The project scaffold: the documents every other command reads, plus the pinned CI caller. Written by `stayfixed init`, recorded in the manifest; `stayfixed upgrade` refreshes what you have not touched, and `stayfixed uninstall` takes it back | `stayfixed init` |
| `docs/stayfixed/rules/<profile>.md` (configurable) and `.claude/rules/stayfixed-<profile>.md` | The stack profile's rules, the one copy a project edits, and a path-scoped pointer at it for Claude Code (only when `[stayfixed] agents` lists `claude`) | `stayfixed init`, when `[stayfixed] profile` is set |
| `.stayfixed/assessment.json` | The inventory `stayfixed assess` last wrote, format 1 — git-ignored | `stayfixed assess`; `stayfixed uninstall` removes it |
| the file `--summary FILE` names | The gate's summary, appended; in CI the platform's job summary | `stayfixed gate --summary FILE` |
| `.stayfixed/manifest.json` | The ledger of every scaffolded artifact | the scaffold engine |
| `.stayfixed/local/artifacts/` | The artifacts `[artifacts] local` keeps out of git, at the path each would have in the repository — git-ignored, never recorded in the manifest | `stayfixed init` and `stayfixed upgrade`, when `[artifacts] local` lists them; `stayfixed uninstall` takes them back |
| `.stayfixed/local/artifacts.json` | The record of the bytes stayfixed last wrote under `.stayfixed/local/artifacts/`, so an unedited copy is refreshed or retired and an edited one is left. Git-ignored and never committed. Deleted, later runs judge a copy at its artifact's own place by what they render, and no longer find a copy left at an earlier place at all | the scaffold engine; `stayfixed uninstall` removes it |
| `~/.config/stayfixed/config.toml` | Machine-level settings: `[personal]`; `[guards]`, where `bg_cleanup = false` switches the background guard off on this machine, whatever a repository's `stayfixed.toml` sets as its default; `[budgets]`, the four budgets that bound what a session loads; `[overlay]`; and `[machine]`. `~` is `HOME`, as the harness reads it ([docs/cli.md](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md#configuration)) | you, or `stayfixed setup` |
| `~/.config/stayfixed/trust.json` | Every approval recorded on this machine, as a versioned record of kinds and subjects, under the same home, the notes you promoted among them (kind `reviewed`); `stayfixed trust list` shows them | `stayfixed memory promote`, which records a note; `stayfixed trust revoke`, which withdraws one |
| `hooks/hooks.json` and `hooks/run-hook.sh` | The zero-config wiring both harnesses read, and the wrapper they execute. **Shipped in the plugin; never written into a project** | nothing — they are part of the plugin |
| `${CLAUDE_PLUGIN_DATA}/stayfixed/` | Once-per-session markers and the hook diagnostics log. Deleted with the plugin | the hook dispatcher |
| `.gitignore`, the `stayfixed:ignore` region | The block that keeps `.stayfixed/local/` and `.stayfixed/assessment.json` out of git, recorded in the manifest. `attach` and `detach` never touch `.gitignore` | `stayfixed init` |
| `.stayfixed/local/attach.json` | What `attach` added to this repository, in the main checkout whichever worktree it ran from, so `detach` can take exactly that back — hidden from git by the block `attach` writes in the repository's `info/exclude` | `stayfixed attach` |
| `<overlay>/common/stayfixed.toml` | Preferences, session budgets, personal values and guard switches for every checkout on a machine that records this overlay, above the repository's `stayfixed.toml` and below the machine file. Read the way a session reads `stayfixed.toml`: what this stayfixed cannot use is ignored with a note, and a gate's input or a fact about the repository is never taken from it | you |
| `<overlay>/projects/<name>/stayfixed.toml` | The same keys for one project, above the common file: read only for a checkout this machine binds to `<name>`, never for one whose own `stayfixed.toml` merely names it | you |
| `<overlay>/projects/<name>/project.toml` | The remote this project was first attached with, and when; it binds nothing | `stayfixed attach`, while it records no remote |
| `.git/stayfixed/binding` (in the git common directory every worktree shares) | The checkout's binding id: 32 random hexadecimal characters that never leave this machine and are printed only as their first eight. No clone carries it | `stayfixed attach`, once |
| `~/.local/share/stayfixed/bindings/<id>.toml` | What this machine binds that id to: the project name, the `origin` at attach time and the checkout. Where the binding is decided, never from a name the repository supplies. `~` is `HOME`; no `XDG_*` variable is read | `stayfixed attach` |
| `~/.local/share/stayfixed/delivery/<id>/` | The overlay's hooks, skills and agents rendered as a plugin, `overlay-<id>` in a marketplace `stayfixed-delivery-<id>`, both named by the binding id, and, when the overlay holds a rule with `paths:`, the `PostToolUse` entry that delivers it, run through whatever launched the stayfixed that ran `attach`: the plugin's hook wrapper, or an installed package's interpreter. A session runs the plugin from here in place, so each attach rewrites it, and `stayfixed detach` removes it | `stayfixed attach` |
| `~/.local/share/stayfixed/stores/<id>/` | The composed memory store the harness and stayfixed's own bundles read, named by the binding id: a link to each of the overlay's note groups for this project and one to its `MEMORY.md`, which `autoMemoryDirectory` in the main checkout's `.claude/settings.local.json` names. Each attach makes its links the overlay's current set and leaves a note the harness wrote there; `stayfixed detach` takes the links and the key, and the directory where nothing else is left | `stayfixed attach`, in `overlay` mode |
| `AGENTS.md`, `CLAUDE.md`, `stayfixed.toml` and any other regular file of `<overlay>/projects/<name>/checkout/` (never a `.env*` file or `settings.local.json`) | The files you keep outside the repository, in the root of a new linked worktree of a bound checkout, only where the worktree has nothing at the name. The main checkout is not touched, and `stayfixed detach` leaves them | the `SessionStart` hook |
| `~/.local/share/stayfixed/sessions/` | One empty file per session and file a path-scoped rule was said for, both names hashed, so the rule is said once per file in a session. Nothing removes them | the hook dispatcher |
| `~/.local/share/stayfixed/unreviewed/` | One file per note store, named by a hash of the store's path, holding a digest of the set of its unreviewed notes the last session was told about, so the count line is said only when that set changes. Nothing removes them | the hook dispatcher |

Every write into a repository goes through a path walk that refuses a symlink at any component
and refuses to leave the project root, and replaces files atomically, keeping the mode of the
file it replaced. Nothing is written by `--check`, `bugs check`, `plan check` or `memory
refs`, and the scaffold engine's `plan` phase performs no writes at all.

## What stayfixed sends where

stayfixed makes no network request of its own and sends no telemetry: none of its modules imports
one of Python's network modules. The table has two kinds of row. Most are programs stayfixed
starts, each only when a command its row's **Run by** names runs, and as your user; stayfixed
installs none of them. The last three are files stayfixed writes that GitHub runs; stayfixed runs
none of them. stayfixed's skills and its agent start nothing themselves: what your coding agent
runs on their advice — through `stayfixed test attribute --command`, a `[gates.custom]` command or
its own shell — is a command it chose, and reaches what that command reaches. The
`uv sync --locked && uv run --locked pytest …` the `attribute-failure` skill suggests, for one,
can reach the package index in each of the three trees `test attribute` runs it in.

`tests/test_outbound.py` walks the Python package and holds the **Program** column, in both
directions, to the package's launches that can reach a network and the files its templates write
under `.github/`. The walk reads syntax, so a launch decided by data flow it does not follow —
dynamic dispatch, aliasing, a value computed at run time, a connection the standard library makes
on the package's behalf — is beyond it; the docstring of
[`tests/outbound/walk.py`](https://github.com/stayfixed/stayfixed/blob/main/tests/outbound/walk.py) says what it sees and names each such case.
The **Run by**, **Talks to** and **When** columns are kept by hand. The hook wrapper,
`hooks/run-hook.sh`, is not Python and is not walked: it starts `python3` and `git`, the last
to find the project root, and reaches no network.

| Program | Run by | Talks to | When |
|---|---|---|---|
| `git fetch` | `stayfixed bugs new` | the project's `origin` (note 1) | unless `--no-fetch` |
| `git ls-remote` | `stayfixed init`, `stayfixed upgrade`, `stayfixed doctor`, `stayfixed gate` | `https://github.com/stayfixed/stayfixed`, for its release tags | note 2 |
| `gh` | `stayfixed setup --overlay create:<owner>/<name>` | GitHub's API, as the account `gh` acts for, and the clones it makes over git (note 3) | note 3 |
| `git clone` | `stayfixed setup --overlay create:<owner>/<name>` | `git@github.com:<owner>/<name>.git`, the overlay just created | when `gh repo create --clone` reported success and left nothing at the destination |
| `claude plugin` | `stayfixed setup --plugin NAME` (`--preset NAME`; `recommended` when omitted), `stayfixed attach`, `stayfixed detach`, and `stayfixed uninstall` on an attached repository, which runs `detach` | for `setup`, the marketplace the preset names for Claude Code, and the named plugins' sources; for `attach` and `detach`, nothing past this machine (note 4) | `setup` when `--plugin` names a plugin, the preset's agents include `claude` and it names a marketplace for it; `attach` on every run; `detach` where the main checkout's `.claude/settings.local.json` names the plugin or its marketplace and no other checkout of the repository is attached |
| `codex plugin` | `stayfixed setup --plugin NAME` (`--preset NAME`; `recommended` when omitted) | the marketplace the preset names for Codex (note 4) | when `--plugin` names a plugin, the preset's agents include `codex` and it names a marketplace for it |
| `pre-commit install` | `stayfixed setup --overlay` | nothing as it installs; GitHub and Go's servers on the first commit after it (note 5) | when it renders an overlay at a path, records an existing one, or with `create:` |
| `sh -c` | `stayfixed test attribute --command CMD` | wherever `CMD` reaches; stayfixed does not choose | every run: `CMD` in the working tree, then in extracts of `HEAD` and of the merge base |
| the commands `[gates.custom]` names | `stayfixed assess`, `stayfixed gate`, `stayfixed adopt promote` | wherever those commands reach; stayfixed does not choose | when `[gates.custom]` names one, unless `--builtin` is passed |
| the test command after `stayfixed prove --` | `stayfixed prove -- COMMAND`; `stayfixed bugs regressions`, with each fixed bug entry's `regression` as `COMMAND`, run from the project root | wherever `COMMAND` reaches; stayfixed does not choose: `uv run` may sync the project's environment from its index, `go test` may download the modules `go.mod` names, and `npx` installs a runner no `node_modules` holds, from the registry the project's `.npmrc` names, without asking, since under `prove` its standard input is no terminal; each as outside `prove` | every run, in the directory `prove` is typed in or the one its launcher is told to run `COMMAND` in, once a runner adapter recognises `COMMAND`, or with `--junit` |
| `.github/workflows/stayfixed.yml` | your CI, from the workflow `stayfixed init` writes in `reusable` mode | GitHub, through stayfixed's reusable workflow (note 6) | on the events the workflow names |
| `.github/workflows/scan.yml` | the overlay's CI on GitHub (note 7) | GitHub, through `gitleaks/gitleaks-action` (note 7) | on every push, pull request and manual run, unless the repository is marked a template |
| `.github/dependabot.yml` | GitHub's Dependabot, from the file the same commands write into the overlay | GitHub: it looks up new releases of the scan workflow's two pinned actions and opens one grouped pull request in the overlay to move them | monthly, once the file is on GitHub |

1. **`git fetch`** asks the project's own `origin` for identifiers filed on branches this checkout
   has not fetched, with `--no-recurse-submodules`, so a submodule's remote is not asked. stayfixed
   passes git only `PATH`, `HOME`, `LANG`, `LC_ALL` and `SYSTEMROOT` from your environment, and
   what it drops changes how the fetch connects. ssh finds no agent through
   `SSH_AUTH_SOCK`, though it still uses its key files under `~/.ssh` and any `IdentityFile` or
   `IdentityAgent` your `~/.ssh/config` names, and `GIT_SSH_COMMAND` is not used. Without
   `HTTPS_PROXY`, `ALL_PROXY` and `NO_PROXY`, in either case, a fetch over HTTPS goes direct unless
   your git configuration sets `http.proxy` or the remote's `remote.<name>.proxy`. Without
   `XDG_CONFIG_HOME` and `GIT_CONFIG_GLOBAL`, git reads your global configuration from
   `~/.gitconfig` and `~/.config/git/config` alone: a global configuration either variable points
   elsewhere, and the credential helpers it names, are not read, while the helpers the configuration
   git does read names are used.
2. **`git ls-remote`** runs in `init` and `upgrade` in `reusable` mode, to pin the CI workflow they
   write to a release's commit; in `doctor` when `[ci] ref` is recorded; and in `gate` when a
   change moves `[ci] ref` to the commit `--workflow-sha` names.
3. **`gh`**: `setup --overlay create:` looks up the template, creates the private overlay from it
   with its clone, and asks whether it exists when that clone left nothing. It is asked nothing
   until `setup` has looked at `<home>/<name>`: a file there, or a directory that is not an
   overlay, is refused before any `gh` call, and the overlay an earlier run made there is left
   alone with none. `gh repo create --clone` makes its clone with git, over git's own transport, from github.com or the host
   `GH_HOST` names. stayfixed passes `gh` your environment, so a `GH_TOKEN` or `GITHUB_TOKEN` there
   is the account it acts as, over the one `gh` is signed in to, and `GH_HOST` can point it at a
   GitHub Enterprise host — while the clone `create:` falls back to is always `git@github.com:`.
4. **`claude plugin`** registers the marketplace the preset names for Claude Code
   (`anthropics/claude-plugins-official` in `recommended`), reads its list of plugins, and
   downloads each plugin `--plugin` named from the source its entry there names, which can be
   another repository. For `attach`, it registers the directory `attach` renders the overlay's
   hooks, skills and agents into, `~/.local/share/stayfixed/delivery/<id>/`, as a marketplace and
   installs the one plugin in it, whose source is a directory inside it, so neither names a source
   past this machine; `detach` uninstalls that plugin and removes that marketplace. **`codex plugin`** registers the marketplace the preset names for Codex and
   adds the named plugins from it; `recommended` names none, so it does not run. Once
   installed, a plugin runs in every session of its harness and reaches what it reaches.
5. **`pre-commit install`** reaches nothing as it installs. On the first commit after it,
   pre-commit clones `https://github.com/gitleaks/gitleaks` at the commit the overlay's
   `.pre-commit-config.yaml` pins, gitleaks 8.30.1, whose hook is written in Go: pre-commit builds
   it, fetching Go modules through Go's module proxy and checking them against Go's checksum
   database, `sum.golang.org`, and may first download a Go toolchain from Go's own download
   service where none is installed. Go honours `GOPROXY` and `GOSUMDB` from your environment,
   which pre-commit passes on, so those can send each request elsewhere; it honours your
   `GOTOOLCHAIN` only when Go was already installed, since pre-commit sets it to `local` for a Go
   it downloaded.
6. **`stayfixed.yml`** calls stayfixed's reusable workflow at the commit it pins, which checks out
   your repository and stayfixed, may download a Python, on a pull request that moves `[ci] ref`
   lists stayfixed's release tags, and, once the configuration and built-in gates pass, runs the
   commands `[gates.custom]` names (that row above).
7. **`scan.yml`** is written by `stayfixed setup --overlay <path>` and `stayfixed overlay
   upgrade`; an overlay made with `create:` gets it from the template repository. It checks out the overlay's whole history and runs
   `gitleaks/gitleaks-action` at the commit it pins, v3.0.0. The action looks up the repository's
   owner through GitHub's API and, for an organisation, stops unless a `GITLEAKS_LICENSE` secret is
   set; in this release it checks only that the secret is present, its call to validate the
   licence being commented out, so it contacts no licensing server. It downloads gitleaks
   8.30.1 from `https://github.com/zricethezav/gitleaks/releases/download/…`, stores its report as
   an artifact of the run and, on a pull request, lists the pull request's commits and, when it
   finds a leak, its review comments, all through GitHub's API with the job's read-only token. It
   also tries to post a review comment on the leak, which that token does not allow, so the
   attempt fails as a warning.

Two kinds of git read the table counts as local can reach a network, and they are the two that
stayfixed's own reads meet. In a partial clone (`git clone --filter=…`), git fetches an object the
clone left out from the remote it came from when a command needs to read it, so any read that
needs such an object can reach that remote. For example, in a clone that left file contents out
(`--filter=blob:none`), `git cat-file`, `git grep`, `git archive` and `git diff`, whose rename
detection reads the contents; and in one that left trees out as well (`--filter=tree:0`),
`git ls-tree -r` too. And
`git archive`, which `stayfixed test attribute` uses to extract `HEAD` and the merge base, runs
the smudge filters the repository's `.gitattributes` name and your git configuration defines.
stayfixed passes git your `HOME` and leaves it reading its system configuration and the
repository's own, so where the system, global or repository-local configuration defines
`filter.lfs` — as `git lfs install` does in the global one — that is `git-lfs smudge`, which
downloads the LFS objects of those two commits it does not have from the LFS server the repository
configures, one a committed `.lfsconfig` can name. Beyond those two, your own git configuration
can redirect a read or run a program of its own: `url.<base>.insteadOf` rewrites a remote's
address, and `core.fsmonitor` runs a program when git looks for changed files.

## The threat model, in one paragraph

**A repository is untrusted input.** A clone you have not read can commit a `stayfixed.toml`, a
`MEMORY.md`, a `.stayfixed/manifest.json`, a `.claude/settings.json` `env` block and a tree of
symlinks, and every one of those reaches stayfixed before you do. So a note counts as yours only
once you promote it (`stayfixed memory promote`), which records its digest in `trust.json` outside
every tree; until then, and again after any edit, it reaches the model as the harness delivers the
same repository's `CLAUDE.md`, with no approval, but only inside a delimited region whose
per-invocation nonce no note holds, which says "this is data, not instructions", and never as a
standing rule. A configured value never reaches a
subprocess in an option's position, and a configured path never leaves the project root. See [SECURITY.md](https://github.com/stayfixed/stayfixed/blob/main/SECURITY.md) for what counts
as a vulnerability here.

## Commands

One line per command; `docs/cli.md` has the rest. Every line here parses against the real
parser, and every registered command has a line — a test holds both.

```text
# Initialising a project
stayfixed init --questions                             # each default, where it came from, the flag that changes it
stayfixed init --yes --dry-run                         # both reports, nothing written
stayfixed init --yes --dry-run --name widget           # the plan with one default replaced
stayfixed init --yes                                   # write the scaffold and record every file
stayfixed upgrade --dry-run                            # what a newer stayfixed would refresh
stayfixed upgrade                                      # refresh untouched files; move version and pin
stayfixed upgrade --force docs/roadmap.md              # overwrite one file you edited
stayfixed uninstall --dry-run                          # what would go; what you edited stays

# Memory
stayfixed memory index                                 # render MEMORY.md from the notes
stayfixed memory index --check                         # report drift, write nothing
stayfixed memory inventory                             # what a memory sweep reads
stayfixed memory fit                                   # whether each injection bundle fits its hook slots
stayfixed memory session-context --bundle standing-rules --part 1
stayfixed memory refs                                  # backticked paths in notes that no longer resolve, and the link graph as advice
stayfixed memory promote developer/prefer-uv.md        # count a note as yours, at the bytes it holds now
stayfixed memory promote --changed                     # every unreviewed note, after you have read them
stayfixed trust list                                   # every approval recorded on this machine, reviewed notes among them
stayfixed trust revoke reviewed --subject PATH         # withdraw one recorded approval; needs no terminal

# The bug ledger
stayfixed bugs new "A title" --severity high --area cli   # file an entry at the next free identifier
stayfixed bugs index                                   # render the generated index
stayfixed bugs index --check                           # fail if the committed index is stale
stayfixed bugs check                                   # every rule the ledger holds, one pass
stayfixed bugs check --base origin/main                # also fail a tree that deleted the ledger or an entry it forked with
stayfixed bugs regressions                             # run each fixed entry's regression through prove
stayfixed bugs renumber BR-001 BR-002                  # move an entry; rewrite every mention

# Documentation and plans
stayfixed docs check                                   # budgets and link targets
stayfixed docs trail                                   # regenerate the design-and-plan trail
stayfixed docs trail --check
stayfixed plan check                                   # lint the plans a change touches
stayfixed plan check --base origin/main docs/plans/example.md

# Guards
stayfixed commit check --range origin/main..HEAD       # attribution lines in commit messages
stayfixed commit strip .git/COMMIT_EDITMSG             # take the attribution block out of a message file
stayfixed test hygiene                                 # the faults that make a red run unattributable
stayfixed test attribute --command "uv sync --locked && uv run --locked pytest tests/x.py::t"   # the change, or the environment: three runs, one verdict

# The private overlay
stayfixed overlay upgrade --root ../stayfixed-private --dry-run  # what a release would refresh

# Binding a repository to the overlay
stayfixed attach --check                               # the binding and the permission diff, writing nothing
stayfixed attach                                       # merge the allow rules, install the overlay's plugin, point the harness at the notes; prints the binding and what will run
stayfixed detach                                       # remove what attach added; the binding record stays

# Machine setup
stayfixed setup --preset recommended                   # the machine configuration and deny rules; no plugin unless --plugin names one
stayfixed setup --preset recommended --overlay ../stayfixed-private   # record an existing overlay, or render one there if nothing is; no network call
stayfixed setup --preset recommended --overlay create:you/stayfixed-private  # create one on GitHub from your <owner>/stayfixed-overlay-template if you published one, else stayfixed's
stayfixed setup --git-hooks                            # install the commit-message hook into this repository
stayfixed setup --git-hooks --uninstall                # remove it; restore the hook it chained to
stayfixed setup --approval-boundary                    # print the deny rule and sandbox settings that keep an agent out of the trust record; writes nothing

# Assessing a repository
stayfixed assess                                       # every gate and probe; the whole inventory in .stayfixed/assessment.json
stayfixed assess --builtin                             # the same, running none of the repository's own gate commands
stayfixed gate                                         # judge stayfixed.toml against the base, then run every configured gate
stayfixed gate --only docs --only config               # a few of them; config is the configuration check
stayfixed adopt promote docs                           # enforce one gate, if it passes now
stayfixed adopt promote                                # enforce every gate that passes now; name the rest
stayfixed adopt promote --builtin                      # the same, running none of the repository's own gate commands

# Proving a fix
stayfixed prove -- uv run --locked pytest tests/test_x.py   # run it here; proved, failed, not proven or refused, from the runner's own report

# Diagnosing an installation
stayfixed doctor                                       # fourteen checks over this installation, one line
stayfixed doctor --json                                # every check with its status, detail and remedy

# Internal
stayfixed hook SessionStart                            # dispatch one harness hook event (internal)
```

Commands that read a project take `--root` (default: the current directory) and `--machine` (read
a machine configuration file other than the default); `memory` commands and `attach` take
`--store` as well. The commands that take neither, and the ones that mean something else by
either, are listed in [Shared flags](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md#shared-flags). `--json` is accepted anywhere before `--` and
prints one machine-readable object instead of one line; the words after `--` are the command's own. The commands that report a list of
findings — `bugs check`, `docs check`, `memory refs`, `plan check` — all spell it `findings`,
whatever their summary line calls them; every other command's keys are its own and are listed
with it in [docs/cli.md](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md).

Exit codes are the same everywhere: **0** success, **1** findings, **2** a refusal or an
internal error. A caller must never read 2 as permission. One command is deliberately
outside that rule: `stayfixed hook` degrades open with **0** on an internal error, on every event,
because a bug in stayfixed must not cost you a tool call, and on `UserPromptSubmit` an exit 2 would
erase what you typed. [docs/cli.md](https://github.com/stayfixed/stayfixed/blob/main/docs/cli.md) states it.

## Memory, in one page

A note is a Markdown file with frontmatter, under a group directory in the store:

```markdown
---
name: prefer-uv
description: This project uses uv, never pip
index: adding a dependency → use uv add
metadata:
  type: project
  startup: 1
---

Run `uv add`, not `pip install`. The lockfile is committed and CI runs `uv sync --locked`.
```

- **`index:`** is the routing line — the trigger and the answer, not a summary. Where it is
  missing, `memory index` renders the note's `metadata.index` or its description in its place and
  writes nothing into the note.
- **`metadata.startup`** flags the note as a standing rule, injected in full at session start
  and ranked by that number, once you have promoted it; until then it arrives with the volatile
  notes, labelled unreviewed and as data.
- **`metadata.as_of`** dates a volatile note; one past `volatile_ttl_days` is injected with a
  visible warning rather than dropped.
- **`group:`** files a note under a sub-heading inside its section.

`MEMORY.md` is rendered from the notes and is not a file you edit — curation lives in each
note's `index:` line. A second writer appending entries to `MEMORY.md` is expected, and
`memory index` harvests those back into the notes before it re-renders.

`memory.mode` decides where the store is. `harness`, the default where no layer sets it, leaves
memory to the coding agent's own and stayfixed resolves no store and injects no bundle.
`local-only` (`.stayfixed/local/memory`, git-ignored) and `in-repo` (committed) both put the notes
**inside the repository**; `overlay` (the composed store, a directory of links under
`~/.local/share/stayfixed/stores/` into a machine-level overlay shared across your projects) puts
them outside it. In every mode a note is yours only once promoted: `stayfixed memory promote`
records the digest of its bytes in `trust.json`, which no tree carries, so a note a clone shipped,
one an agent or the harness wrote, and one edited since you promoted it all arrive unreviewed —
inside the delimited region, labelled, and never as a standing rule. A session hears one line,
"N notes are unreviewed", when that set has changed since the last session.

## The bug ledger, in one paragraph

An entry is one file, `docs/bugs/BR-001.md` by default, with flat frontmatter — `id`,
`status` from `open | partial | fixed | rejected | void`, `severity` from `high | medium |
low`, `area`, `related` — and a body whose `**What this evidence does not establish:**` line
must be filled in for the severities the project names. `bugs index` renders the index as a
pure function of the entries and refuses to overwrite one it did not generate; `bugs check`
finds identifiers in the code with no entry behind them, entries whose evidence line is still
the template's, and citations that do not resolve. The identifier prefix is one configuration
key. The `close-bug` skill walks the closing of an entry through these commands.

## Skills and agents

`skills/` ships two ported skills (`close-bug`, `memory-sweep`), seven authored ones
(`adopt`, `file-bug`, `sweep-defect-class`, `review-plan-three-lenses`, `attribute-failure`,
`run-correctness-audit`, `retro-to-guard`), and thin wrappers for the commands the CLI
registers; `agents/` ships a read-only `code-navigator`. Every skill is written in action
language — never a harness tool's name — with the per-harness mapping in
[skills/README.md](skills/README.md), and every `stayfixed …` invocation in a skill is
parsed against the real parser by a test. A wrapper written ahead of its command is listed in
that test until the command ships; none is today.

## Contributing

See [CONTRIBUTING.md](https://github.com/stayfixed/stayfixed/blob/main/CONTRIBUTING.md) — it states the three rules a change here has to satisfy,
which are not obvious from the code. Security reports go through
[SECURITY.md](https://github.com/stayfixed/stayfixed/blob/main/SECURITY.md), never a public issue.

## License

MIT. See [LICENSE](LICENSE).
