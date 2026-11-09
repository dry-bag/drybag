# Command reference

Every command, what it reads, what it writes, and what each exit code means. `drybag --help`
gives you the one-line version; this is the rest.

Three things hold everywhere:

- **`--json` is accepted anywhere** and prints one machine-readable object instead of
  one line. It is not declared per command — the frame strips it from `argv` before parsing. A command whose result is a list of findings carries it under **`findings`**, named after what the
  values are and spelled the same way by every command, whatever its summary line calls them.
  Two commands do: `docs check` and `plan check`. Every other
  command's keys are its own and are listed with it below — `doctor`'s `checks`, `docs trail`'s
  `undeclared`, and the two of `docs trail`'s keys that are
  not lists at all, `written` and `stale`. `--json` escapes every non-ASCII character as
  `\uXXXX`, and a name git or the disk gave in bytes that are not UTF-8 appears as one lone
  surrogate escape per byte (`\udcXX`), which a strict JSON reader may refuse.
- **Exit codes**: `0` success, `1` findings, `2` a refusal or an internal error. A caller that
  treats `1` as "proceed anyway" must still never treat `2` that way — a refusal is a boundary,
  not a low-confidence result. Every command that reads `drybag.toml` refuses one that is a
  symbolic link, whatever it points at, before reading anything through it: a link to
  `/dev/zero` would otherwise be read until memory ran out. The refusal exits `2`, except in three
  commands that read the file the way a session does: `drybag hook` runs on with no project
  configuration and warns once when the session starts (see [its section](#drybag-hook-event)),
  `drybag memory session-context` prints nothing, and `drybag doctor` reports it as a
  `drybag.toml` that does not load, a red row, exit `1`.
- **Every `memory` command takes the same three options**, described once here rather than seven
  times below. `--root` and `--machine` are not memory's alone: [Shared flags](#shared-flags) says
  which commands take them, and in which sense.

| Option | Meaning |
|---|---|
| `--root PATH` | The project root. Default: the current directory. |
| `--store PATH` | Resolve the note store at this path instead of where the configuration says. An override of *where the notes are*, not of the rules about them: the same containment checks apply. In overlay mode it is not read: the store is the composed store the binding names, so no directory a repository chose stands in for it. |
| `--machine PATH` | Read this machine configuration file instead of `~/.config/drybag/config.toml`. Mostly for tests and for running against a second machine profile; it also decides which `trust.json` is consulted. |
## Contents

- [`drybag memory index`](#drybag-memory-index)
- [`drybag memory session-context --bundle <name> [--part N]`](#drybag-memory-session-context---bundle-name---part-n)
- [`drybag memory inventory`](#drybag-memory-inventory)
- [`drybag memory promote NOTE… | --changed`](#drybag-memory-promote-note----changed)
- [`drybag hook <event>`](#drybag-hook-event)
- [Hooks](#hooks)
- [Note sync](#note-sync)
- [`drybag commit check --range RANGE`](#drybag-commit-check---range-range)
- [`drybag commit strip FILE`](#drybag-commit-strip-file)
- [`drybag docs check [--budgets] [--links]`](#drybag-docs-check---budgets---links)
- [`drybag docs trail [--check]`](#drybag-docs-trail---check)
- [`drybag plan check [--base REF] [PATH …]`](#drybag-plan-check---base-ref-path-)
- [`drybag overlay upgrade [--root PATH] [--dry-run]`](#drybag-overlay-upgrade---root-path---dry-run)
- [`drybag attach [--store PATH] [--project NAME] [--check] [--root PATH] [--machine PATH]`](#drybag-attach---store-path---project-name---check---root-path---machine-path)
- [`drybag detach [--root PATH] [--machine PATH]`](#drybag-detach---root-path---machine-path)
- [`drybag setup [--preset NAME] [--plugin NAME …] [--home PATH] [--machine PATH] [--overlay VALUE]`](#drybag-setup---preset-name---plugin-name----home-path---machine-path---overlay-value)
- [`drybag setup --git-hooks [--uninstall] [--root PATH]`](#drybag-setup---git-hooks---uninstall---root-path)
- [`drybag setup --approval-boundary [--home PATH] [--machine PATH]`](#drybag-setup---approval-boundary---home-path---machine-path)
- [`drybag doctor [--json] [--root PATH] [--home PATH] [--machine PATH]`](#drybag-doctor---json---root-path---home-path---machine-path)
- [Shared flags](#shared-flags)
- [Terms](#terms)
- [Configuration](#configuration)

---

## `drybag memory index`

Render `MEMORY.md` from the notes. The index is a rendering: the only note it writes is one that a line outside its markers in
`MEMORY.md` names, a line the native writer appended or an earlier release rendered, which is
harvested into it.

```bash
drybag memory index            # write
drybag memory index --check    # report drift, write nothing
```

**Reads** every `*.md` under each configured group, and the current `MEMORY.md`.

**Writes** each note it harvests a line into (step 2), and `MEMORY.md` — in overlay mode, the file
the symlink points at, not the link. Under `--check`, nothing.

What it does, in order:

1. **Takes the note's own short line.** A note with no top-level `index:` that carries one under
   `metadata:` (`metadata.index`, more than whitespace) is rendered with it, and the note is not
   written: an edit to `metadata.index` reaches the next render.
2. **Harvests.** A second writer — you, another session — may have appended
   `- [trigger → answer](group/note.md)` lines to `MEMORY.md`. For a note with neither key, those
   are read back into its `index:` frontmatter, marked `index_provenance: native`, so nothing a
   session wrote is lost by regenerating. Only lines outside the region the render writes are
   read (step 4), so a line between its markers is not read back; an index an earlier release
   rendered under other markers is outside it, so its lines are harvested too. Each note is
   written once, since it then has `index:`, and is unreviewed until promoted again
   ([`memory promote`](#drybag-memory-promote-note----changed)).
3. **Renders what is missing.** A note with none of these is rendered with its `description`, and
   is not written. A line an earlier release wrote into a note as `index_provenance: provisional`
   is read as no line, so the note's line follows its description again.
4. **Renders.** One section per configured group, a note's `group:` value as a sub-heading
   inside it, ordered by `startup` rank first, then by `group_order`, then by name — so a
   note ranked for the session leads its section whatever its position within a sub-heading.
   The harness's own memory writer keeps its notes as topic files at the top of the store,
   outside every group, each named by one `- [title](file.md)` line in `MEMORY.md`: every such
   line whose file the store still holds is kept, verbatim and once, and the topic files are never
   written. The render sits between two marker lines, `<!-- drybag:index -->` and
   `<!-- drybag:index:end -->`; the native writer's pointer lines stand after it, where that
   writer appends, and a `MEMORY.md` with no markers is read whole as lines outside the region. In
   a composed store's own `MEMORY.md` under `~/.local/share/drybag/stores/`, a note you have not
   promoted at the bytes it holds now
   ([`memory promote`](#drybag-memory-promote-note----changed)) has its line end in
   `[unreviewed]`, as the bundles label it; the label follows this machine's record, so it is never
   written into an index a repository commits or the overlay shares.

`--json`'s `provisional` lists the notes rendered by step 1 or step 3, the ones whose line a
curated `index:` would replace.

`--check` exits `1` when the index has drifted, when it is over its word budget, when it is past
the harness's line or byte caps, or when a file in the store cannot be parsed as a note — one
whose name is not UTF-8 on disk included, since the index names every note by its file's name.
Such a file is named by its path inside the store, on the line and in `--json`'s `unreadable`
alike. Every list of names on the line names up to eight and says
how many more there are; `--json` carries every one.
The same findings are printed on the write path too — they just do not fail it, because `--check`
is the mode that fails a build.

Exits `2` if `MEMORY.md` is a symlink this store may not follow (the target rule: outside
overlay mode a symlinked index is refused outright; in overlay mode only a link into *this*
project's own share of the recorded overlay is honoured).

**A session renders it in overlay mode.** In a checkout with a `drybag.toml` whose memory is in
overlay mode and that this machine binds, the `index-render` hook handler runs this command's write
on `SessionStart` and on `SessionEnd`, and renders once more when a line arrived while it rendered:
the note sync moves no `MEMORY.md`, so each machine renders its own from the notes it holds. Either render
harvests (step 2) what stands outside the markers. The `SessionEnd` one takes the lines the session
appended, on the machine that wrote them, and it runs before the [note sync](#note-sync)'s own
`SessionEnd` handler starts its job, so the notes it wrote travel in that job; the `SessionStart`
one also lists what the jobs brought in since. It says nothing; a
failure is one line on stderr and costs no other handler.

**A checkout with no `drybag.toml` that this machine binds** reads the memory a repository with
the file reads: every `memory` command, the bundles and `doctor`'s note-store rows use the preset's
configuration under the overlay's layers (`common/`, the project's tags, `projects/<name>/`), for
the project this machine's binding record names, which is how a public clone you cannot commit to
gets its notes. A checkout nothing on this machine binds is still refused (`1`), naming the
`drybag.toml` it lacks, and the bundles print nothing for it. A `drybag.toml` is read first when
there is one.

**One store in overlay mode.** There the store is the composed store `drybag attach` builds,
`~/.local/share/drybag/stores/<id>/`, named by the checkout's binding id and holding one link per
group into the overlay, and `--store` is not read. In every other mode `--store` is resolved at the
path it names, under the same rules as the configured store. The groups include the notes of each tag
the project lists, as `tag-<tag>` (`groups/<tag>/memory/` in the overlay), which every `memory`
command, the index and the bundles read after the common notes and in the order the project lists
its tags, whether or not `memory.groups` names them. A note's review is
recorded by its path, so renaming a tag, which moves its notes' path in the store, makes them
unreviewed once.

**When there is no store, the refusal says why** (exit `1`). An overlay root the machine
configuration records that is not a directory on this machine — the overlay moved, or was never
cloned here — is said first, with the root named in drybag's own sentence (it is your
machine configuration's, not the repository's) and `drybag setup --preset NAME
--overlay PATH` as the way out, since `attach` refuses a store outside the recorded root. A
checkout this machine does not bind to the project — no binding id in its git common directory, or
none this machine records for that project — is said in drybag's own words before the region
that carries the repository's, with `drybag attach` as the way out. The checkout's `origin`
plays no part in it.

## `drybag memory session-context --bundle <name> [--part N]`

Render one injection bundle. This is what a `SessionStart` hook entry invokes; you will rarely
run it by hand except to see what a session actually receives.

| Bundle | What it is |
|---|---|
| `standing-rules` | Every note flagged `startup` that you promoted at the bytes it holds now ([`memory promote`](#drybag-memory-promote-note----changed)), in full, ranked; an unreviewed note is never a standing rule, whatever it says about itself. Never truncated — only flagged when the set outgrows its budget, because a standing rule that does not arrive is a standing rule that gets broken. |
| `volatile-notes` | Dated, perishable notes, and every unreviewed note flagged `startup`, in full; over budget, descriptions only. An unreviewed note arrives labelled `[unreviewed]` inside a delimited region that says it is data, opened and closed with a nonce the note does not hold. |

Each bundle is emitted across numbered parts, because the harness caps each hook entry's output
independently. `--part N` selects one; a part past the end prints nothing and exits `0`. A part
that is a single block too large for one slot is withheld — the command prints a short notice
saying so instead, because the harness would otherwise truncate it and a truncated region loses
the marker that says where repository content ends. `drybag doctor`'s `bundles` row reports it.

Output is deliberately **raw**, not JSON: the margin that keeps a bundle inside the platform cap
is additive only because there is no envelope and no escaping. Do not pass `--json` from a hook
entry.

Where no layer sets `[memory] mode`, memory is the coding agent's own (`harness`), there is no
store, and this command prints nothing. So it does before the store's directory exists — a
`local-only` repository before its first note — and in an overlay checkout this machine has not
bound, whose binding `doctor` reports. In an overlay checkout this machine binds whose composed
store is gone, `--bundle standing-rules` (part 1) prints one line saying so, the store named by its
short binding id, with `drybag attach` as the way back, and every other entry prints nothing. A configured
group whose directory the store does not hold is an empty group, here and in every `memory`
command: it contributes no notes, and the store is still read, the native writer's files at its
top included. An unreviewed note — one a repository commits, one
an agent or the harness's writer wrote, one edited since you promoted it — reaches a session with no
approval, as the harness delivers the same repository's `CLAUDE.md`, only in `volatile-notes` and
only as data, in every mode; a `trust.json` that cannot be read leaves every note unreviewed. It
reads the configuration as the session does
([Configuration](#configuration)), and a machine file that does not load is read as recording no
overlay, so the notes not kept in an overlay still arrive; the session's own warning names that
file.

**Writes** nothing: the bundle goes to standard output and nowhere else.

## `drybag memory inventory`

What a memory sweep reads: every note with its word count, type, `startup` rank, date, whether
it is stale, whether its index line is curated, harvested or provisional, and whether it is
`reviewed`. Plus totals, among them `unreviewed` and `standing`, the promoted notes the
`standing-rules` bundle carries, and `skipped`, the note files that are symbolic links. A note
file that is a link is read by no `memory` command and reaches no bundle, in every mode, and the
line counts it: a repository would choose what is read through it, a file outside it or a note
promoted elsewhere. A group directory that is a link, as each of the composed store's is, is
followed.

**Reads** the store's notes and the machine's trust record.

**Writes** nothing.

## `drybag memory promote NOTE… | --changed`

Count notes as yours, at the bytes they hold now. Each `NOTE` is a note's path in the store,
`<group>/<file>.md` as `memory index` links it, or a path to the note's file; `--changed` takes
every note that is not reviewed. One or the other: both, or neither, exits `2` and records nothing,
as does a name that is no note of the store.

```bash
drybag memory promote developer/prefer-uv.md
drybag memory promote --changed    # after reading what changed
```

A note is reviewed while the sha256 of its current bytes is a `reviewed` approval in `trust.json`.
The digest alone decides, and the approval keeps the note's resolved path only as a label: the same bytes are reviewed in every worktree, after the store moves and
under another name, and an edit — yours, an agent's, the harness's writer's — makes the note
unreviewed again and moves no other note. The record is this machine's, so another machine
promotes for itself. Only a reviewed note is a standing rule
([`session-context`](#drybag-memory-session-context---bundle-name---part-n)). The record lies
outside every tree, so repository bytes cannot write it; an agent whose shell can run this command
can, and against it the record is a label, not a gate (what the record holds against is below). An
approval holds for its bytes wherever they reappear: an edit takes the note out of review, but the
same bytes written again anywhere, a revert or a copy, are reviewed again. No command withdraws
an approval; withdrawing one is a hand edit of `trust.json` that removes its entry.
[`drybag setup --restore --yes`](#drybag-setup---preset-name---plugin-name----home-path---machine-path---overlay-value)
records the notes of the overlay's share for each project it attaches.

Prints each note's path in the store and the digest recorded, one per line. `--json` keys:
`promoted`, one object per note with its `path` and `digest`.

**The record** is the machine's one record of approvals, of every kind. It is versioned: a JSON
object holding `version` (`1`) and `approvals`, each with its `kind`, `subject`, `digest` and
`approved_at`. Every write replaces the whole file in one atomic step, and no lock is taken: two
commands writing at once each replace it whole, the last one wins, and neither leaves it torn.

**What an approval holds against.** Repository bytes: drybag never writes `trust.json` from
what a repository holds, and a clone, a pull or a pull request does not reach it, since it lies
under `HOME` and outside every repository. A repository whose hooks your harness runs — a committed
`.claude/settings.json` hook in a folder you trusted — is code running as you, and can write any
file you can, this one included. Not the session's own agent: an agent whose shell can write any
file you can may write the record as well, and drybag neither stops nor checks that. That
boundary is the harness's sandbox, which is yours to set; `drybag setup --approval-boundary`
prints what to set under Claude Code. Even a sandbox that keeps the record out of reach leaves an
agent a way to instruct the next session: Claude Code's documentation does not list a project's
`CLAUDE.md` or `AGENTS.md` among the paths its sandbox keeps from the agent's own writes, and Claude
Code loads the first as instructions and can load the second, through an import or its project
instructions setting (read in the documentation, not measured). [SECURITY.md](../SECURITY.md)
lists an agent with an unsandboxed shell as out of scope.

Exits `2` if `trust.json` exists and is not a record this drybag reads — not JSON, not UTF-8, a
later version, no `version`, a `version` that is neither `1` nor later (`0`, `"1"`, `true`), or a
version-1 record that is not whole: a key besides `version` and `approvals`, an approval that is not
an object of four text fields, or one approval named twice. Nothing will overwrite a file it
could not read: one that does not parse may hold every project's approval, so repair or delete it;
repair any other that holds approvals you want to keep, or delete it to start a new record; for a record of a later version, which a later
drybag wrote and is met after a downgrade, update drybag instead, since deleting it would
destroy that release's approvals.

Exits `2` for a write refused as an agent's sandbox refuses one, as **Writes** below says.

**Reads** the store's notes and the machine's trust record.

**Writes** `~/.config/drybag/trust.json` (or the file beside `--machine`), only when a note was
promoted, through a link a dotfiles manager put there: the file the link leads to gets the record,
and the link stays. A write refused as an agent's sandbox refuses one (`EPERM` on macOS and
`EROFS` on Linux and WSL2, as Claude Code's sandboxing reference gives them) exits `2`, records
nothing, and says that a person must run the command in their own terminal, outside the agent's
sandbox, and that met in their own terminal it is the directory itself refusing writes, as a
read-only mount or an immutable flag does. A directory you may not write for its mode exits `1`,
naming it.

## `drybag hook <event>`

Internal. Reads a hook payload on stdin, dispatches it to every handler registered for that
event, and writes the harness's expected output.

Not something to run by hand. Its exit-code policy differs from every other command: an internal
error degrades open (`0`) on every event, with the error on stderr — a bug in drybag must not
cost you a tool call, and on `UserPromptSubmit` an exit `2` would erase what you typed.

On `PreToolUse` for a `Bash` call two handlers hint and neither refuses: `bg-cleanup` names a
backgrounded command that leaves a job behind, and `pipe-status` names a test run piped into `tail`,
`head` or `grep` whose text names no `pipefail` or `PIPESTATUS` and is a flat list of pipelines, where
the run's exit status is lost. Each reads the command alone, so each speaks in a repository with no `drybag.toml`; `pipe-status` has no
switch and speaks once per context.

**A session never dies of its configuration.** The guards run in every repository, whatever
`drybag.toml` holds: none at all, one that does not load, and a broken machine file included;
only their switches are read, the repository's `[guards]` as a default the overlay's files and the
machine file override. A configuration is never the reason a call is refused.
The project's file is read the way [Configuration](#configuration) says a
session reads it: an unknown section or key is ignored and a value that cannot be used is put back
to the preset's, so the rest of the file still applies. The handlers about the project — the
unreviewed-notes count, the overlay status, the red-run note — say nothing when there is no project
configuration to use, which is so when there is no file, and when the file is a symbolic link
(never read, whatever it points at), is not UTF-8, cannot be read or is not TOML, or holds a key
nothing can stand in for: a required key with no default (`[drybag] version`, `[project]
name`) that is missing or cannot be used, or whose section is not a table, or a key whose preset
value does not hold in this repository either, such as a `[paths]` default under a committed
symlink. Nor is a file longer than 256 KiB read at all, nor one read key by key past more settings
it cannot use than its length allows — 64 for a file of up to 16 KiB, fewer for a longer one, 4 at
256 KiB: each costs the session a whole rebuild of the configuration, which costs what the file is
long, so a long file of unusable keys would keep a hook past its timeout, which lets the call
through with its guards silent. Such a file is dropped whole, and the guards run on the
preset and the owner's layer.

What the session could not use is said once, on `SessionStart`, in one warning about each file, to
the person (`systemMessage`) and at the head of the model's context (`additionalContext`), both
counted inside the hook's output cap: that `drybag.toml` does not load, that one of its keys
cannot be used and nothing can stand in for it (naming the key), that it is longer than a session
reads, that it holds more settings this drybag cannot use than a file its length is read past,
that it loaded with some
settings ignored or put back to the preset's (counting them, and saying when a newer drybag
wrote it), or that the machine file, named by the path that was read, could not be used whole.
Each points at `drybag doctor`, and none carries the loader's own message, which carries the
repository's text; a command such as `drybag docs check` still refuses the file and prints that
message in full. Every other event
prints no warning, and records once per session, in the diagnostics log below, that the session
runs without some of its configuration (`config-fallback`).

**The overlay's rules.** In a checkout this machine binds to an overlay project
([`attach`](#drybag-attach---store-path---project-name---check---root-path---machine-path)), `SessionStart`
carries the overlay's standing rules — every `*.md` file in `claude/rules/` of `common/`, of each
tag the project lists (`groups/<tag>/`) and of `projects/<name>/` whose frontmatter has no `paths:`
key, in that order and each in name order, a later plate's file replacing the earlier plate's file of
its name —
under one fixed lead line, on every event the matcher covers, since a compacted or cleared context
has lost them. A rule with `paths:` is path-scoped: the plugin `attach` renders carries a
`PostToolUse` entry for it, matching `Read|Edit|Write`, that runs `hook PostToolUse` through
whatever launched the drybag that ran `attach`, by absolute paths in double quotes: from the
core plugin, its own `hooks/run-hook.sh` (below), so `-I` and exit `0` on any fault hold as for the
plugin's own entries; from an installed package, which has no plugin root, the interpreter it ran
under, as `<python> -I -m drybag`. That answer carries every such rule whose globs match the file the tool named, relative to the checkout's root (`*` and `?` within
one path segment, `**` across segments, `{a,b}` for alternatives), the first time a session touches
that file, and nothing after. The project is the one the machine's binding record names, never the
repository's `drybag.toml`, so an unbound checkout hears no rule, whatever its `memory.mode`; a
rule that cannot be read silences the rules of that hook, and `attach` refuses it. A rule's body
reaches the model as the overlay holds it; the one path printed is the touched file's, withheld
outside the path grammar.

**The owner-held files.** In a new linked worktree of a checkout this machine binds to an overlay
project, `SessionStart` places the regular files directly inside the overlay's
`projects/<name>/checkout/` (`owner-files`, the first handler there) that the worktree does not
have: an `AGENTS.md`, a `CLAUDE.md`, a `drybag.toml` the repository does not track. Never a
`.env*` file (in any letter case), `settings.local.json` or `.DS_Store`, and never a subdirectory or
a link in `checkout/`. A file keeps its source's permission bits and is created only where nothing
is at the name: a file the branch tracks is already there, and a file, directory or link at the name
is left alone and never written through. It answers from the machine's binding record, never from
the repository's `drybag.toml`, which the worktree may not have until this places it, and it
places nothing in the main checkout, in a submodule, in an unbound checkout or on a machine that
records no overlay. It runs on every `SessionStart` there, so a placed file you delete by hand comes
back with the next session. **A file is placed only where your own excludes hide its name**, the
checkout's `.git/info/exclude` or your global excludes file, and no `!` line re-includes it, asked
before any is created. A `.gitignore` does not stand in for them, since a branch's next commit can
take its line out, so a branch only ever makes fewer files be placed. Any other name is not placed
but named to the session, which is told to add it to the checkout's `.git/info/exclude`, unless the
branch's `.gitignore` un-ignores it on purpose (a `!` line outranks the exclude file), in which case
it stays out. Where git cannot say what it ignores, nothing is placed and nothing is said. It says nothing when it placed and withheld
nothing; otherwise it names the files placed, asks the session to read `AGENTS.md` when that file
itself is among them, and names the files withheld. It asks git only `rev-parse`, `config` and
`check-ignore --no-index`, none of which runs a repository's `core.fsmonitor`: one `rev-parse`
finds the linked worktree and the common directory the binding id is read from, so a checkout it
does not serve costs that one launch, and the rest are asked only when a name is free.

**Writes** inside `drybag/` under the data root the harness names — `CLAUDE_PLUGIN_DATA`, or
Codex's `PLUGIN_DATA` — and nowhere else of its own: `.probe`, written each time it dispatches to
learn whether the root can be written at all; under `markers/`, one empty file per `once_key`
handler that delivered, and one for a `config-fallback` record, filed under a directory per
session, both names hashed to a fixed width,
with all but the newest fifty session directories removed; and `diagnostics.jsonl`, one JSON line
per diagnostic record, rotated to `diagnostics.1.jsonl` once it would pass 256 KiB. With no data
root, or a relative one, nothing is written there and a `once_key` handler is asked on every
invocation. These handlers write outside it. `index-render`, on `SessionStart` and `SessionEnd`
in a checkout bound in overlay mode, writes what `drybag memory index` writes there: the
overlay's `MEMORY.md` for the project and each note it harvests a line into. `owner-files`, the files above, creates one file in the
root of the new linked worktree for each name it places, and nothing else there; nothing removes
them. `overlay-path-rules`, the path-scoped rules above,
writes one empty file per session and file it said a rule for, under
`$HOME/.local/share/drybag/sessions/`, both names hashed to a fixed width; none for a payload
with no session id, and nothing removes them. And `unreviewed-notes`, which on `SessionStart` says
"N unreviewed note(s)" when the set of the store's unreviewed notes differs from the one last
said, writes one file per store under `$HOME/.local/share/drybag/unreviewed/`, named by a hash
of the store's path and holding a digest of that set; nothing removes them. And the note sync's three handlers, on a machine whose machine file switches
the sync on and nowhere else, write `pending` under `$HOME/.local/share/drybag/sync/` and start the
job that writes the rest ([Note sync](#note-sync) names every path). No handler links a memory store into a worktree:
the harness reads the composed store from every worktree through the main checkout's
`autoMemoryDirectory` (`drybag attach`).

## Hooks

The two harnesses do not run `drybag` directly. Every entry in `hooks/hooks.json` invokes
`hooks/run-hook.sh`, which hands its argv to `drybag` untouched:

```
run-hook.sh <drybag args…>
```

`hooks/hooks.json` files its entries under six events: `SessionStart`, `PreToolUse`,
`PostToolUse`, `PostToolUseFailure`, `Stop` and `SessionEnd`, each tool event matched on `Bash`.
`PostToolUseFailure` is where Claude Code delivers a `Bash` call that exited non-zero, and it
carries the red-run note (below); Codex reads the same file and ignores that key (measured on
Codex CLI 0.162.0-alpha.17.2). `SessionStart` and `SessionEnd` carry `index-render`, which
renders a bound overlay checkout's `MEMORY.md`
([`memory index`](#drybag-memory-index)). `Stop` and `SessionEnd` carry the note sync's handlers
([Note sync](#note-sync)) and print nothing that blocks, since a `decision` on `Stop` would keep the
turn from ending. A `drybag hook` entry with nothing to say answers `{}`, on every event; a context
on `Stop` or `SessionEnd` is refused, and no shipped handler gives one there. An event Codex
delivers from that file runs the same handlers behind the same
per-machine switch, and that has not been measured on Codex. `drybag hook` dispatches eight
events, those six and `UserPromptSubmit` and `UserPromptExpansion`, which no shipped entry uses.

**The red-run note.** The environment fault that makes a red test run unattributable:
uncommitted changes in the tree. The note counts them across the whole repository — a dirty tree
anywhere makes a red run unattributable — and says nothing when the tree is clean.

The `PostToolUseFailure` `Bash` hook delivers the note once per context after a red test run:
Claude Code delivers a command that exited non-zero on that event, with `error` beginning `Exit code
N`, and an `error` that begins otherwise, or with a run of more than nine digits, which no exit code
has, gets no note. The same handler is registered on `PostToolUse` too, where no measured harness
delivers an exit code: Codex delivers a failed command there with none, so the note does not speak,
and the registration is a placeholder for parity with Codex. The two share one once-per-context key,
so a context gets at most one note, whichever event carries it. The note is given by the command
that failed rather than by configuration: it speaks when a simple command of the red run starts
with a test runner's command in the hints' runner table (`pytest`, `python -m pytest`, `cargo test`,
`go test`, `npm test` and the other common runners), read by the program's file name and never by
its options. A runner is recognised behind environment assignments, an `env` prefix and `uv run`,
its bound included: the command starts at the first word the table reads as a test run, so a
runner named before the real command (`uv run --with pytest echo`, `uv run grep -m pytest x`) gets
the note, and one named through an alias or another launcher (`poetry run pytest`) does not. A red
command the table does not name gets no note.

The wrapper exists because a Python process cannot speak for its own absence: a missing script
exits `2` by CPython accident, and so does a launcher run under an interpreter below drybag's
floor, and on `PreToolUse` Claude Code reads a `2` as a refusal of the call. So the wrapper does
three things before drybag runs: it unsets an inherited `GIT_DIR` and `GIT_WORK_TREE`, which
would make every `git` answer about another repository, and changes into the project root
(`CLAUDE_PROJECT_DIR`, else `git`'s toplevel) so every command's `--root` default is correct; it
takes its interpreter from `PATH` resolved in `/`, which a repository cannot move because it writes
no file there; and it maps exit codes. The `python3` found from `/` is asked, by running code, to be
3.11 or newer and to print the binary it really is, which then runs drybag from the project
root. Where that `python3` is missing or older, it takes the interpreter `uv python find '>=3.11'`
names, also asked from `/`. Asked from the project root, an empty or relative `PATH` element would
run a `python3` the repository commits, a pyenv, asdf or mise shim would run what the project's own
pin names, and uv reads `.python-version`, `pyproject.toml` and `uv.toml` from its working
directory and its parents and runs the `.venv/bin/python` it finds there to ask its version
(measured with uv 0.12.19).

No handler refuses a call, so drybag's non-zero exit is always a fault. `0` passes through
untouched. Every non-zero exit, and every fault the wrapper finds before `drybag` runs — no
`python3` of 3.11 or newer on `PATH` and no uv that names one, no readable `scripts/drybag`
beside the wrapper, a project root it cannot enter — ends in exit `0` with one line on stderr that names the fault and ends
`continuing open`: **a session never dies of drybag's own fault.** `drybag hook` exits `0` on
an internal error of its own for the same reason, so no shipped entry ever blocks a call. Claude
Code discards stderr on a `0`, so `drybag doctor`'s `wrapper` row runs the wrapper and goes red
on such a line. Without a usable interpreter neither `doctor` nor any hook can run, so the one entry
that dispatches `SessionStart` (`hook SessionStart`) also prints, on stdout, the hook answer Claude
Code shows the person (`systemMessage`) and adds to the model's context (`additionalContext`):
that drybag's hooks are off in this session, because there is no `python3` on `PATH` or the one
there (its path, each byte but an ASCII letter, a digit, a space and `/._+~-` printed as `?`) is not
Python 3.11 or newer, and to install Python 3.11 or newer on `PATH`. Every other entry, the six
memory entries on the same event included, stays silent on stdout.
A hook that runs past its ten-second `timeout`, or that cannot start at all — the wrapper missing or
not executable — never reaches the mapping, and Claude Code then carries the tool call out.

**Which `python3` and which `git` run is `PATH`'s to choose**, in a hook as at a terminal: a nix,
MacPorts or mise `git`, and a `python3` in a virtual environment, both answer. A trusted folder's
committed `env` block can set `PATH`, and it runs code in your shells by design; that boundary is
the harness's ([SECURITY.md](../SECURITY.md)).

**The interpreter starts isolated.** `-I` keeps what the interpreter imports before drybag's
first line to the standard library: the wrapper runs both the version probe and the launcher with
it, so no `PYTHON*` variable is read (`PYTHONPATH`, `PYTHONHOME`, `PYTHONUSERBASE`), there is no
user site, and neither the working directory nor the script's own directory is on `sys.path`. The
launcher puts the plugin's own `src` there itself, and drybag still sees the whole environment:
`-I` changes how the interpreter starts, not what `os.environ` holds. What the dynamic loader
injects is out of any wrapper's reach — `LD_PRELOAD` on Linux acts on the wrapper's own shell before
its first line. On macOS the wrapper's `/bin/sh` is SIP-protected and drops `DYLD_*` before
anything below it starts, which is why its shebang must stay a protected shell.

**The one row this does not cover.** A `run-hook.sh` whose executable bit has been cleared is
never executed by the harness at all, so no code of ours runs and the hooks are silent. The
wrapper cannot defend its own mode, so `drybag doctor` is what catches it: the `wrapper` row
goes **red** on a cleared bit, and under a root the environment named hands you the `chmod +x`. Run it after anything that rewrites the
plugin directory.

**What a session hears about the overlay it is bound to: `overlay-status`.** Beside the two that
deliver the overlay's rules (above), the `attach` area registers one `SessionStart` handler, with a
`once_key`, so it speaks **at most** once
per session: the marker is banked only when the handler had something to say, so a session that
hears a line hears it once, and a repository with nothing to report is asked again on every
`startup`, `resume`, `clear`, `compact` and `fork` the matcher above covers — and it says
nothing at all unless `[memory] mode` is `overlay`, which for a checkout this machine binds and that has
no `drybag.toml` is the mode the overlay's layers set. Eight lines, each fixed and carrying at most a
count but the one that names two remotes, joined by newlines in this order: **no overlay recorded** on this machine, or one that
**could not be asked** about, which is a machine configuration file that will not parse; this
repository **not attached** to that overlay, or, for a bound one, its **`origin` moved** from
the remote its binding was recorded with — the one line that names repository bytes, both remotes,
each escaped where it is not a plain path; the `requires` of the overlay's identity record
(`drybag-overlay.toml`) in **a form this drybag cannot read**, or naming **a floor this drybag
does not meet**, a pre-release of the floor's version included; and — only when none of those fired — the overlay's branch having **no
upstream**, and the counts of its **unpushed commits and uncommitted changes**. A bound,
up-to-date repository on a satisfied drybag hears nothing. But for the moved-`origin` line, not
one byte a repository wrote reaches any of those lines: `project.name`, `memory.groups` and
`paths.memory` are read and none is quoted back, because the field these lines land in is
`additionalContext` — model input with no delimiter.

**What it costs, and on which repository.** The binding's own `origin` query runs on every
invocation, at git's five-second cap. The last two lines cost two more `git` calls at two seconds
each, and they are reached **only when nothing above them found anything wrong** — a finding
short-circuits them. So the repository that pays all three, nine seconds against the entry's own
ten-second budget, is the bound, up-to-date one that then
hears nothing; and because the `once_key` marker is banked only on a line actually delivered,
that is also the repository asked again on every event the matcher covers. A repository with a
finding pays five seconds, hears its line, and is not asked again.

Which is why those last two `git` calls are gated on the event's own `source`: on a **compact** —
the running conversation continuing, under the session id the marker is filed under — they are
skipped, so a healthy repository costs five seconds there and not nine. `startup`, `resume`,
`fork`, `clear` and a payload carrying no `source` all pay: a resume is a new launch, often days
later, over an overlay the conversation may have left dirty, and an invocation drybag cannot
place in a context is treated as a new one rather than as one already answered. The cost is that
an overlay which becomes unpushed *during* a session that started clean is not reported at that
session's compactions, only at its next resume or startup; `drybag doctor` answers on demand. And the overlay is never a plugin drybag
executes anything from: it carries no plugin manifest and no
`hooks/hooks.json`, and hook entries the owner keeps in the `claude/hooks.json` of *common/*, of a tag and of
`projects/<name>/` reach a session only through the plugin `attach` renders from
them, named by this machine's binding id.

## Note sync

A machine whose machine file says `[sync] enabled = true` commits the overlay's notes, takes in the
other machines' and pushes its own, unattended, from Claude Code's session hooks; a machine whose
file does not say so runs nothing. The sync has no command and no `drybag.toml` key.

**The switch.** `[sync] enabled = true` in [the machine file](#configuration), the bool `true` and
nothing else: a string, a number, a table that is not one or a file that does not load reads as
off. `[sync]` is machine-only, so a repository's `drybag.toml` that holds it is refused and
switches nothing. `drybag setup --overlay` writes it for an overlay it renders or creates and
leaves it alone for one it records; turn it off by changing it to `false` or removing it. A value
that is not a bool is said as the machine file's other unusable values are, and reads as off. The
handlers read it from the configuration the session resolved when it started, so a change reaches
the next session; the job reads the file again each time it wakes. Off, the three handlers return:
no `git` call and no process, on every turn of every session. `doctor`'s `sync` row says which it
is.

**The triggers.** One handler on each of `SessionStart` (not after a compaction, which is the same
session going on), `Stop` and `SessionEnd`, named `note-sync-start`, `note-sync-stop` and
`note-sync-end`. `SessionStart` always starts a job, to fetch. `Stop` and `SessionEnd` ask one
`git status` of the overlay's memory paths and start a job only when a memory path is changed or
untracked, when commits wait to be pushed, when the last outcome is not `ok` or `skipped`, or when
a hold stands. While a
hold stands, or a failure a rerun usually meets again (`conflict`, `auth_failed`, `hook_failed`,
`scan_unavailable`, `signing_failed`, `secret_found`, `waiting_clean_tree`), and neither `HEAD`,
the fetched `origin/main` nor the dirty notes, by name and content, changed since the last job,
`Stop` waits 15 minutes from the last job: the same job would meet the same end. `SessionEnd`
waits only under a hold, since a `hook_failed` can also be a step a rerun clears and no later turn
of the session would retry it.
A trigger within 120 seconds of the last job is marked pending and a sleeper waits out the
throttle (a second sleeper exits at once, so a burst of turns is one run); one while a job runs is
only marked pending, and that job runs again, at most twice, for the triggers that arrived while
it ran. `SessionEnd` is
never throttled, since no later turn would pick it up; how long a `SessionEnd` hook may run is the
harness's to set, whatever `timeout` its entry asks for.

The job is a detached process in its own session, its standard streams on `/dev/null`, started
as `python -I -c BOOT <package directory> [--sleep-until ISO]` from the overlay. `-I` keeps the
overlay's root, `PYTHONPATH` and the user site off `sys.path`, so a `json.py` or a `drybag/` the
overlay holds is never imported. It reads the switch and the overlay root from the machine file itself, and a sleeper reads
the switch again when it wakes. It exits `0` whatever happens and records the outcome.

**The job, in order.** Each step is bounded in time, and the whole job in 180 seconds.

1. **Guard.** `git` 2.43 or newer, a repository, no merge, rebase, cherry-pick or revert in
   progress, no unmerged paths, `HEAD` on `main`, and `main` tracking `origin/main`. Anything else
   is the outcome `skipped`, with the reason, and nothing changes. Work in progress outside memory
   is no reason: the job never touches it.
2. **Commit.** `git commit --only` of exactly the changed notes, with no hook. A new note is added
   intent-to-add first (`git add -N`), so each is judged by what git would record from the working
   tree. One that may not move (below), or that a link or a file stands above, is left out and named;
   one the secret scan finds something in is left out and named with its remedy (`secret_found`)
   while the others commit; and the intent-to-add entry of a note left out is removed again. git
   moves `main` and updates the real index for those notes alone, so your staged work stays staged
   and your next `git commit` carries no old note back. A signature is made when `commit.gpgsign` is
   set, and never switched off.
3. **Fetch.** `git fetch origin main` into `refs/drybag/fetched`, with `fetch.fsckObjects`.
4. **Integrate.** When everything `HEAD..` the fetched sha brings is memory, and every local commit
   is a plain commit of memory alone, the local commits are replayed onto it one by one; a commit
   that conflicts is `conflict`, `main` unmoved. Then git writes the incoming notes and the real
   index (`git read-tree -m -u`), keeping your staged work and your untracked files, and only then
   does `main` move to the result, by a compare-and-swap. A note changed here and not committed yet,
   an untracked file where a note lands, or a link where git needs a directory makes git refuse
   before it writes anything (`waiting_clean_tree`, with git's words). Anything else is a hold, and
   `HEAD` stays as it is.
5. **Push.** The checked sha, `<sha>:refs/heads/main`, never forced and with no tag, after the
   secret scan of the range and only when every commit in it is memory.

**What moves.** Three globs only: `common/memory/**`, `groups/*/memory/**` and
`projects/*/memory/**`, less each project's own `MEMORY.md` (`projects/*/memory/MEMORY.md`), which
never moves: it is a rendering of the notes beside it and of what this machine's sessions appended,
so each machine renders its own ([`memory index`](#drybag-memory-index), on `SessionStart` and
`SessionEnd`) and the notes travel instead. A path moves as a regular, non-executable `.md` file with no dot component
from the scope's name down, and only as text; a link, an executable, a dot-file, a file that is not
Markdown, a nested repository or a file git calls binary is left out of the commit and named. A path outside those globs is
never committed, integrated, written or pushed. Nothing configures the list.

**When an overlay stops tracking its generated indexes.** An overlay that still commits its
`MEMORY.md` indexes should stop, with one commit that untracks and ignores them. Nothing is needed beforehand on a
machine: the pull deletes each index the commit untracks, and the next session renders it again. A
clone with local changes to an index refuses that pull; copy the index aside, run
`git checkout -- <index>`, pull, and put the copy back, where it is now ignored. Until the commit is
taken on a machine, the
job holds it like any upstream change outside memory, and `doctor` gives the review command.

**What it never does.** Force-push, stash, rebase, pull, push a tag, rebuild a commit of yours that
is not memory alone, write a non-memory path of the working tree or of the real index, run a script
from the overlay's working tree, run a git hook of the overlay's (`core.hooksPath=/dev/null`), or
ask for a password (`GIT_TERMINAL_PROMPT=0`, no askpass variable kept, `core.askPass` empty, no
standard input, and its whole process group ended at the step's bound). What your own git
configuration names still runs, as it does for your own git: a credential helper,
`core.sshCommand`, `gpg.program` and `core.fsmonitor`. Its `git` gets the one environment every git
drybag starts is given: `PATH` without its relative entries, `HOME`, `LANG`, `LC_ALL`,
`SYSTEMROOT`, `SSH_AUTH_SOCK` and the proxy variables (`http_proxy`, `https_proxy`, `HTTPS_PROXY`,
`all_proxy`, `ALL_PROXY`, `no_proxy`, `NO_PROXY`), and nothing else of the session's, so a
`GIT_CONFIG_GLOBAL`, `GIT_SSH_COMMAND` or `GIT_DIR` it sets reaches no git of the job. Over that go
the job's own settings: attributes read from `HEAD` (`GIT_ATTR_SOURCE=HEAD`), replace refs ignored
(`GIT_NO_REPLACE_OBJECTS=1`) and `LC_ALL=C`.

**The secret scan.** The `gitleaks` on `PATH`: the `PATH` every git of the job gets, its relative
entries dropped, looked up once per job. pre-commit's build is not read, nor any other a session's
environment names, and the job never downloads or builds one. It scans a patch of the bytes, under
neutral names: before the commit, the working-tree bytes of each note to be committed; before the push,
every blob the range adds or changes and each commit's metadata (the commit object whole, every
header and the message, and its path names), read raw by one `git cat-file --batch`, so no
attribute, filter or `textconv` stands between git's bytes and the scan. Each is committed as a
file named `1`, `2`, ... to a repository in the job's `scratch/`, which no global or system git file
configures, and scanned there by `gitleaks git`: gitleaks' file sources, `dir` and `stdin`, skip a
file by its opening bytes, so a note opening `MZ` or `%PDF-` would pass unread, and a patch has no such
filter. What git calls binary shows no patch, and the memory-only rule refuses it. No name of a note
reaches gitleaks. The rules are the `.gitleaks.toml` `HEAD` commits, else gitleaks' own defaults
(`[extend] useDefault = true`); a `.gitleaks.toml` in the working tree is never read. So a path
pattern cannot name a note: one like `gitleaks.toml-tips.md` or under a `node_modules` directory is
scanned like any other, and the defaults' path allowlist exempts nothing. A `.gitleaksignore`,
committed or not, is not read either. A committed rule set still applies whole: its content
allowlists, and a path pattern that matches the numbered names, so `paths = [".*"]` exempts
everything. And `gitleaks:allow` on a line exempts that line, as it does anywhere. With no `gitleaks` there, nothing is committed or
pushed (`scan_unavailable`) and the remedy is to install gitleaks on the `PATH` the sessions run
with; what is already committed upstream still integrates. A finding before the commit leaves that
note out (`secret_found`, its detail opening with `remove the secret from <path>; the next job
commits it`), and the notes beside it commit. A finding stops the push
(`secret_found`): its detail opens with the rewrite from the oldest commit found, then names each
finding's rule, commit and path.

**Writes.** In the data directory, `$HOME/.local/share/drybag/sync/`: `state.json` (the last
outcome, the holds, the fetched sha, the sha `main` and upstream last agreed on and a digest of the dirty notes, written in one step), `job.lock` and `sleeper.lock` (held
while a job runs and while a sleeper waits), `pending` (a trigger that arrived while a job ran),
and `scratch/`, which the job removes whole at its start and its end. In the overlay: the objects
and the commit of step 2, which `git commit --only` writes with `main` and the real index's entries
of the notes it commits; an intent-to-add entry for each new note (`git add -N`, removed again by
`git update-index --force-remove` for one left out); the replayed commits of step 4; the real index's
stat data (`git update-index --refresh`), then the notes it brings in, written, removed (with the
directories a removal empties) and entered in the real index by `git read-tree -m -u`; `refs/heads/main`, moved by `update-ref` against the sha it read; and
`refs/drybag/fetched`. On the remote, `main`, by step 5. Besides `scratch/` and what git removes
for step 4, it removes `pending` when it takes it, and nothing else. When the plugin is removed, the
triggers go and this directory stays.

**Outcomes** (`state.json`, and `doctor`): `ok`; `skipped` (the guard's reasons, each ending with
its remedy: `git switch main`, finish or abort the operation, or give the overlay a remote with
`git remote add origin <url>`, a commit and `git push -u origin main`, as an overlay `setup --overlay`
rendered needs); `conflict` (a local
commit conflicts with upstream, and `main` was not moved); `raced` (another git holds `index.lock`, which the job never removes, or `main` moved while it integrated); `rejected`
(`origin/main` moved before the push; the next trigger fetches and retries); `offline`,
`auth_failed` and `timeout` (the remote or a step); `hook_failed` (a step failed, or paths were
left out of a commit); `scan_unavailable`; `signing_failed`; `secret_found`; `waiting_clean_tree`
(git refused to write an incoming note: one changed here, an untracked file or a link in its way).
A failure is retried by a later trigger, throttled and
never forced; one only you can clear waits out the back-off above, and `doctor` says a rerun
meets it again until you act on what the first line of its detail says.

**Holds.** A hold is a range the sync refuses to move until you act, and a later outcome never
clears it; while one stands nothing is integrated or pushed, and the next job clears it once you
have acted. *Upstream*, for one of four reasons. `HEAD..origin/main` changes something outside
memory: read all of it and take it at the sha that was held, `git log -p --no-renames HEAD..<sha>`,
then `git rebase <sha>`. A change to a project's `MEMORY.md` is such a change: an overlay that
still commits its indexes is held on the first upstream commit that changes or untracks one, until
you take that commit (the overlay's own untracking commit, once on each machine). Its tree is one
git will not check out: `git diff --stat HEAD <sha>`, and
repair upstream. Or upstream was rewritten: the sha the last job recorded as upstream's, fetched or
pushed, is not in the new one, and commits it dropped are still in `HEAD`; they are named, and
never replayed or pushed back. Read them with `git log -p <sha>..HEAD`, then take the rewrite with
`git rebase -i <sha>`, dropping them, or undo it with `git rebase <sha>` and a push. A first fetch,
with nothing recorded, is no rewrite. Or you rewrote notes already pushed, by a reset or a rebase:
commits of the sha `main` and `origin/main` last agreed on (`agreed`, which a job writes only when
it verified them equal on `main`, after a push or finding them so), which `main` no longer has and
`origin/main` still has, are named and held, so `main` stays as you made it and nothing is
fast-forwarded or replayed back. A job that stops early, offline or mid-rebase, does not move that
record.
Keep the rewrite with `git push --force-with-lease=refs/heads/main:<sha> origin main` by hand, or
undo it with `git rebase <sha>`. *Local*: your own commits that are not memory alone (a change
outside memory, a merge, an empty commit) keep their shas: they are neither rebuilt nor pushed, and
upstream is not integrated past them; integrate and push them by hand when reviewed. `doctor` names
each.

**A job killed.** git does the writes, so a kill leaves a state the next job converges from, with
no record kept. Inside `git commit --only`, between the move of `main` and the rename of the real
index into place, git leaves `index.lock`; every later index-writing git refuses until it is
removed, as after any killed `git commit`. The job never removes it (it cannot tell a stale lock
from a live one): its outcome is `raced`, with git's words, and `doctor` names a lock older than a
whole job. The job's own step bound does not get there: a timed-out step's group is sent SIGTERM,
on which git removes its lock, and SIGKILL a moment later, so a signature waiting on a person ends
`signing_failed` with no lock left. Only a signer that ignores SIGTERM reaches the lock above. After the commit and before the push, the commit is whole, and the next job replays it
onto an upstream that moved and pushes the scanned range. Between `git read-tree -m -u` and the
move of `main`, the incoming notes are staged on the old `main`; your own commit in that window
carries them, losing nothing, and the next job commits them, finds upstream already has the tree,
and moves `main` to it.

**The floor.** The job needs `git` 2.43 (`merge-tree --write-tree --merge-base`, and
`GIT_ATTR_SOURCE`, which an older git ignores without a word). On an older one every trigger's job
records `skipped` with the reason and changes nothing, and `doctor` says why.

**`doctor`.** The `sync` row is read off this machine's records and runs no job. In the order it
asks: off (a skip, naming the file and the key), no overlay recorded, `git` below the floor, no
`gitleaks` on `PATH`, a hold, a record it cannot read, and the last outcome. Only `ok` is green: a
`skipped` job is a sync that is not running, and every other outcome warns with its remedy; a
failure a rerun meets again says so until you act. After a `raced` job, a stale `index.lock` is
named wherever git keeps it, a linked worktree's included.

**Claude Code and Codex.** The triggers are the entries of `hooks/hooks.json` ([Hooks](#hooks)),
which Codex reads too. A hook process whose environment carries Codex's `PLUGIN_ROOT` starts
nothing: Codex sets it and Claude Code does not, measured as `src/drybag/harnesses.py` cites. A
repository that sets it in a Claude Code session turns that session's triggers off, never on.
There is no cloud mode.

## `drybag commit check --range RANGE`

Every message in `RANGE` (a `git log` revision range, e.g. `main..HEAD`), for lines in its
trailing attribution block that are an AI/tool attribution trailer or footer: a `-by:` trailer
whose address is at a vendor's domain or whose name is a product, a `Generated with <tool>`
footer, or a line that is only `AI-generated`. The block is the message's last paragraph plus
every paragraph above it that is attribution to the last line — the canonical harness block is
two paragraphs — and it ends at the first paragraph holding any body line. Body prose is never
judged. A trailer's display name is judged whole: one that is a product's name and nothing else
(`Cursor`, `Devin`, `ChatGPT`) is a violation whatever its address, and a person's name that holds
a product word (`Cursor Smith`, `Claude Lemaire`) is not, by its name.
The rules apply only where `[commit_messages] attribution_check = true`; the preset leaves it
`false`, and then no message is ever a violation, but the range must still be readable, because
the report says how many messages it read. Exits `1` naming up to eight offences as `sha line N [label]` and counting the rest —
never the text, which is the repository's; `--json`'s `violations` carries every one — and `2`
when git cannot read the range or the range looks like an option.

**Writes** nothing.

Exit `1` has two meanings here and a gate should know both: messages were read and some carry a
trailer (`FAIL: …`), and *no `drybag.toml` was found under `--root`*, which the configuration
loader reports as a failure — `drybag: failed: …/drybag.toml does not exist` — and not as a
refusal. A workflow that must tell them apart reads the first word of the output, or checks the
file is there before it runs the gate.

## `drybag commit strip FILE`

Rewrite a commit-message file in place with the attribution lines of its trailing attribution
block removed — never a line of the body. Exits `0` whether or not anything was stripped, and
prints one line saying which: `stripped N attribution line(s) from FILE`, `nothing to strip`, or
`kept N attribution line(s): …` with the reason below. A message that is *only* attribution is
left alone and reads `nothing to strip`, because emptying it aborts the commit with a confusing
error and CI explains better. It strips nothing where your own Claude Code settings,
`~/.claude/settings.json`, set `attribution.commit` to text: what a commit carries is then your
choice in the harness, and when a line would have gone the run says it kept it and why; a message
with nothing to strip still says `nothing to strip`, which the hook keeps off the terminal. It is
all or nothing: with text there, every attribution line the strip would take is kept, not only
the one the setting names. Set empty, or to whitespace alone, it says your commits carry nothing,
so a trailer that arrives anyway is stripped as it is with the setting unset. The file is read as
a regular file only: one that is not there, is not a regular file (a FIFO, which would hold every
commit), cannot be read or is not one JSON object sets nothing. A repository's own
`.claude/settings.json` is not read for it, since a clone could then turn the hook off. Refuses a symlink, and fails (`1`) on a file it cannot read, a
file that is not UTF-8 included.

Git's own trailing comment block is kept, and so is everything below the scissors line that
`commit.verbose = true` puts the staged diff under — the message is what lies above both.

This is what the chained `prepare-commit-msg` hook runs, so the trailer is gone before the
commit exists; `git commit --no-verify` skips `commit-msg` but not that hook. Installing the
hook is `drybag setup --git-hooks`, and removing it — restoring whatever it chained to — is
`drybag setup --git-hooks --uninstall`; both are documented below.
`drybag.guards.api.install` is the same call for a caller embedding drybag.

**Reads** `FILE` and `~/.claude/settings.json` under your home, and nothing a repository holds.

**Writes** `FILE`.

## `drybag docs check [--budgets] [--links]`

Two checks, both enforced, and no flag runs both (exit `1`, `FAIL:`):
the always-loaded document at `[paths] agents_md` exists, is within `agents_md_lines` and
`agents_md_words`, and has a `## Current status` section within `status_lines`; the roadmap at
`[paths] roadmap`, up to the line `## Design and plan trail`, is within `roadmap_prose_lines`
and `roadmap_prose_words` (a roadmap with no marker is budgeted whole; an absent one is not a
finding); every relative local link in the agents file resolves to a file — read from that
document's own directory, and only when it lands inside the project root, since a link that
walks out through `..` would be settled against the machine rather than the repository (an
absolute link is not read at all, nor is an anchor, a URL or a `mailto:`). Budgets are the
effective ones — the preset's, or the value `[budgets]` sets in its place.

**Writes** nothing.

## `drybag docs trail [--check]`

Rewrite the listing between `## Design and plan trail` and `<!-- end design and plan trail -->`
in the roadmap: every `*.md` under `[paths] specs` and `[paths] plans` that git tracks and does
not ignore, grouped by the first `[[theme]]` in `trail.toml` (beside the roadmap) whose
`pattern` is found in its filename, `Unfiled` otherwise, each annotated with its `[states]` entry or
`delivered`. `--check` exits `1` when the listing is stale and writes nothing. Two guards make
the listing unable to lie by silence: a state naming a document that no longer exists fails
(`1`) before anything is written, counting every such key and naming up to eight, with a note
that a re-run after updating those names the rest (a key longer than 120 characters is named by
its first 120 and its length); and a document that enters the listing
without a declared state is written as `delivered` and then reported (`1`), counted and named
up to eight on the line and every one in `--json`'s `undeclared` — a design is written before
the thing is built. A listing that named no document before, such as a new project's first,
reports none of them, so the first design and plan need their states declared before the first
run. That second guard fires on the writing path only: a row enters the listing through
`docs trail`, whose exit `1` the operator sees, and `--check` has no earlier listing to compare
against, so a defaulted `delivered` that was committed over that report is invisible to CI.
A theme's `pattern` is a small part of regular-expression syntax, meaning what it means to a
regular expression: literal text, `.` for any one character, `.*` for any run of them, `|`
between alternatives, `^` and `$` at an alternative's start and end, and `\` before a
punctuation character to take it literally — `.*`, `widget` and `gadget|gizmo` are all
patterns. It is matched without backtracking, so no pattern can make a run take longer than
the name's length times its own, and a pattern holds at most 256 characters and a `trail.toml`
at most 32 themes, since every name is tried against every theme until one matches. Any other
syntax — a group, a class, `+`, `?` or `{n}` — is refused rather than read otherwise.
A `trail.toml` outside its contract fails (`1`): a non-string label, a pattern outside that
syntax or longer than 256 characters (the refusal names the theme by its `label`, a label
longer than 120 characters by its first 120 and its length), more than 32 themes, a file that is not valid UTF-8, or a `label` or `[states]` value that is not a single
line or that carries either marker — both are written into the listing verbatim, so one could
otherwise split the block and push repository prose into the roadmap. A listed document's name
is held to the same rule, and to one more: a name that is not a single line, carries either
marker, or is not UTF-8 on disk fails (`1`) naming the file, escaped, with nothing written —
rename it. A carriage return ends a line here as a newline does. Inside a git work tree,
a question git gives no answer to — which documents it ignores or tracks, when it cannot be run,
runs past its time limit or refuses the checkout — fails (`1`) with nothing written, rather than
listing every document on disk; outside one, every document is listed.

Nothing writes the roadmap or `trail.toml` for you, and without them the command has nothing to
check. Write the roadmap (`[paths] roadmap`, `docs/roadmap.md` by default) by hand, with a line
`## Design and plan trail` and, below it, a line `<!-- end design and plan trail -->`, between
which `docs trail` writes the listing,
and `trail.toml` beside it, one theme to start with and a state for each document not plainly
delivered:

```toml
[[theme]]
label = "Everything"
pattern = ".*"

[states]
```

**Writes** `[paths] roadmap`.

## `drybag plan check [--base REF] [PATH …]`

With `PATH` arguments, lint exactly those plans; without, the plans under `[paths] plans` that
merging the change could alter on `REF`, `REF` defaulting to
`refs/remotes/origin/<project.base_branch>`, the fully qualified name, so a tag called `origin/<branch>` cannot stand in for it. Those are the plans
whose copy in `HEAD` differs from `REF`'s and from that of any commit `git merge-base --all REF
HEAD` names: a copy equal to every merge base's leaves the merge taking `REF`'s, and one equal to
`REF`'s leaves it as it is. Every merge base, not the one `REF...HEAD` diffs against, which can
already hold an old plan the change puts back. Five rules, each from a retrospective: every
backticked path resolves unless the line says `(create)` or `(delete)`, or the plan declares it
on a `Create:`, `Test:` or `Delete:` line; no step is phrased as already knowing its answer
(`confirm that nothing …`, `verify no …`, `check that it does not …`); a `**Scope:**` line
with content is present; a plan claiming `Fixes BR-nnn` (no other prefix is judged) carries a `**Premise:**` line with
content; and a mutation's outcome stated as fact in the present tense (`-> the test reddens`,
`watch it go red`, `reddens 8 assertions`) is a finding unless its own sentence marks it an
expectation. Without `PATH`, the first rule reads only the lines the change wrote — those that
differ from every merge base's copy and from `REF`'s — so a change editing a delivered plan, an
`Interfaces:` block say, is held to its own lines and never to paths the tree has moved since the
plan was written; a new plan is all such lines. Naming a plan as `PATH` settles every reference in
it.
Fenced code is fixture text, and so is a path claim that lands outside the project root —
an absolute one, one that walks out through `..`, or one that runs through a committed symlink
pointing out of the tree — which is never settled against the filesystem, because that answer
would be about the machine rather than about the repository. A symlink that stays inside the
tree is followed. A
base that does not resolve, one that shares no commit with `HEAD`, any base in a shallow clone,
where the commits `HEAD` forked from can be cut off and an older commit stand in for them, and
any base in a clone git refuses to say is shallow or not, are this command's `base-unresolvable`
finding (`1`), never an OK: fetch the whole history (`fetch-depth: 0`). A git that could not be
run or ran past its time limit, on any of these questions, fails (`1`) with that cause in
words. A `REF`
shaped like an option is refused (`2`) before git sees it. Uncommitted plans
are not in the diff; the line counts them and `--json` names them, and naming one as `PATH`
lints it.

**Writes** nothing.

---

## `drybag overlay upgrade [--root PATH] [--dry-run]`

**`--root` must name an overlay, and that is checked before anything is planned.** It defaults
to `.`, and pointed at a directory that is not one this command used to create the overlay's
files there — `.gitignore` and `.github/workflows/scan.yml` among them — report them as work done
and exit `0`. An overlay is a tree whose identity record, `drybag-overlay.toml` at its root,
parses as TOML and holds `layout = 1`; the record also holds `requires`, the floor `drybag
doctor` and a session's first lines read, and nothing else. Anything else is refused (`2`) with
nothing written, and the refusal names the file and its two keys: an overlay made before the
record shipped carries plugin manifests instead, and no code migrates it, so its owner adds the
record by hand.

Brings an overlay up to date with the template a newer drybag ships. It is the project rule
and not a second copy of it: a skeleton file you have not touched is refreshed, one you have
edited is skipped and named, and the oracle is the digest `.drybag/manifest.json` recorded when
the file was written. An overlay is where your own rules live, so a silent overwrite here would
destroy the only copy of something. An overlay `setup --overlay create:` generated has no
`.drybag/manifest.json` (the template repository carries none), and an identity record you
added by hand has no entry in one, so neither is recorded as drybag's: a file there that differs
from this release's is skipped as `exists and drybag did not write it`.

**Two files are always listed, however their hashes compare.**
`common/claude/permissions.json` and `common/claude/hooks.json` are the two an overlay carries
that can grant a capability — a permission rule, a command that runs on an event — and a hash
that matches is not your consent to either. They are listed under `ASK FIRST` beneath the report,
and under `decisions` in `--json`. Without `--dry-run` that list is printed *after* the refresh,
not before it: nothing waits for an answer, and the reason it can be a notice rather than a gate
is that the shipped template grants nothing — its permissions file is deny-only and its hooks
file is empty, both held by a test. `--dry-run` first is how you read them before anything moves.

`--dry-run` prints the same report and writes nothing; the report you approve is produced by the
code path that then runs, which is what makes the dry run worth reading.

**Writes**, without `--dry-run`, every artifact the report lists as `create` or `update`, plus
`.drybag/manifest.json`. A file an earlier release shipped and this one does not, such as
`common/memory/README.md` or `hooks/hooks.json`, is not planned at all: delete it by hand. Exits
`0`; `1` when the report carries a REFUSED section, because nothing would be written while one of
those stands; `2` when `--root` is not an overlay, when the manifest itself cannot be trusted, or
when a write is refused by the containment walk.

---

## `drybag attach [--store PATH] [--project NAME] [--check] [--root PATH] [--machine PATH]`

Binds this repository to your private overlay, renders the hooks, skills and agents you keep there
into a local plugin and installs it, and, in overlay mode, points the harness at the composed store
of its notes. After it, a session in this
repository runs your overlay's hooks, skills and agents and reads your cross-project notes and this
project's own notes, and the allow rules you keep in the overlay are merged into
`.claude/settings.local.json`.

**`--store` is optional, and names one directory and nothing else:**
`<overlay>/projects/<project name>/memory`, where `<project name>` is the `[project] name` in this
repository's `drybag.toml`, or the project chosen below where it has none; without it that directory is derived from the overlay the machine
records, and passing it changes nothing. The overlay root itself is **not** taken from that path —
it comes from the `[overlay] root` your machine configuration records, which `drybag setup`
writes. A `--store` anywhere else is refused (`2`), including a directory elsewhere under the same
overlay. A `[project] name` no directory can carry there — the name of a file the overlay keeps
under `projects/`, which on a filesystem that ignores case includes `readme.md`, or a name longer
than the filesystem allows — is refused (`2`) before anything is written, by `--check` as well, and
the refusal names the shape of the path and never the name. So is a name whose directory there fits
under the longest path the system allows while a path `attach` makes inside it does not — the
`project.toml` that keeps the first attach's remote and date, the notes index `MEMORY.md`, or the
directory of one of `memory.groups` — because nothing could read that record back or link the notes
to that path; a long `memory.groups` entry reaches it as a long name does, and the refusal names
neither. Both hold where the overlay has no directory for the project yet, `projects/` included. An
overlay whose root, or whose `projects/`, is there and is not a directory is refused (`2`) as
damaged, by `--check` as well, with that path named and the overlay's repair as the way out; no name
is blamed for it, and `drybag doctor`'s `attached` row warns about the same path rather than
offering to remove the ledger.

**A repository with no `drybag.toml` attaches too**, so a public clone you cannot commit to can
be bound to your overlay. Its project — the directory under the overlay's `projects/` it is bound
to — is chosen, by `attach` and `--check` alike, in this order:

1. `--project NAME`, held to the rule `[project] name` is held to, which the parser refuses (`2`)
   without echoing the value;
2. the project this machine's binding records for the checkout, so a re-attach needs no flag;
3. the one overlay project whose `projects/<name>/project.toml` records this checkout's `origin`,
   compared as the binding's `origin` note compares remotes (below: the three spellings of one
   repository are one), which is how a second machine finds the project the first one attached;
   two or more such projects are refused (`2`), naming them, with `--project` to choose;
4. otherwise the last segment of `origin`'s path, `.git` taken off and lower-cased
   (`https://example.com/Owner/Widget-Kit.git` is `widget-kit`), refused (`2`) where that is not a
   project name.

With no `origin` and neither of the first two, it is refused (`2`). Every refusal names `--project`
as the way out. The attach screen's binding line names the project and the origin, which is what
you read: matching by remote is a convenience, and a clone whose `origin` claims one of your
repositories is bound to that project. The configuration it acts on is the preset's, under your
overlay's `common/drybag.toml`, its `projects/<name>/drybag.toml` once the binding is recorded
(a first attach reads it after recording, as for a repository with the file), and the machine
file, as a session resolves its preferences; so `memory.mode` is the preset's,
`harness`, unless an overlay file sets `overlay`. Where the repository has a `drybag.toml`, its
`[project] name` names the project and nothing above applies; `--project` beside it is refused
(`2`).

**The notes are composed only in overlay mode; the rest is delivered whatever the mode.** A
`drybag.toml` whose `memory.mode` is not `overlay` keeps its notes elsewhere, so for it `attach`
builds no composed store, writes no `autoMemoryDirectory` and makes no note directories in the
overlay, and does not ask the `memory.groups` containment below; where an earlier attach composed
them, it takes the recorded key and the composed store back, as `detach` does. It binds, merges the
allow rules, places the Codex rule files and renders and installs the plugin all the same. The mode
is the one the configuration resolves once the binding is recorded, so a `[memory] mode` the
overlay's project file sets applies from the first attach.

**One place per repository: the main checkout.** Claude Code reads the main checkout's
`.claude/settings.local.json` from every worktree, and writes a worktree's own answers into it, so
`attach` run from any worktree acts on the main checkout: it reads that checkout's `drybag.toml`
and writes its settings file and its `.codex/rules/` copies; its ledger is in the git common
directory. Nothing is placed in a
linked worktree, and a worktree created later needs no step of its own.

**`--check` writes nothing.** It opens with the project it would bind and where the name came from —
`project NAME (named by --project)`, `(this machine's binding record)`, `(the overlay's record of the
remote)`, `(the remote's name)` or, for a checkout that has one, `(its drybag.toml)` — the name
escaped as every name the repository chose is; `--json` carries them as `project` and
`project_source`. It then reports the binding state — `unbound` or `bound` — with the
`origin` note the run would print (below), the permission diff
(which allow rules would be added, how many of the overlay's rules this
repository already has, and, when there are any, how many the ledger names that the overlay no
longer grants and the run would take back), and the Codex standing-rule files it would place under `.codex/rules/`.
Read it before the real run: everything under **Writes** below that carries content from the
overlay is named here first. It asks what the real run asks before its first write, through the
run's own code, so where the run fails or refuses there, in any case the two lists below give before
the first write, `--check` ends with the same code and the same line; otherwise it exits `0`.

`rules_to_write` in the `--json` output lists those standing-rule files.

**What the overlay grants is shown, not gated.** The overlay is yours, written by you and your
agents, and its hooks run scripts from the overlay checkout in place, so `attach` asks for no
confirmation of what it grants; it says it on one screen and proceeds. Below its line come the
binding — the first eight characters of the binding id, the project it is recorded under and this
checkout's `origin`, the project and the remote escaped as every name the repository chose is —
then each hook entry (by its event and command), skill (by its directory) and
agent (by its file) the render adds or removes against the render the last run left in
`$HOME/.local/share/drybag/delivery/<id>/`, which is what a session runs, and then each allow
rule this run merges or takes back. A hook's command and an allow rule that do not fit a plain name are printed
escaped, and cut to their first 120 characters and their length. `--json` carries the same lists
as `hooks_added`, `hooks_removed`, `skills_added`, `skills_removed`, `agents_added`,
`agents_removed`, `allow_added`, `allow_withdrawn` and `rules_left`, and no remote and no project of their own. A re-attach that
binds the checkout to another project than this machine's record named — a `[project] name`
renamed in a pulled commit moves every worktree's binding — says so on one line naming both.
`--check`'s line names no project.

**The overlay's hooks, skills and agents are delivered as a plugin.** Every run renders them into
`$HOME/.local/share/drybag/delivery/<id>/`, named by the binding id below: a marketplace
`drybag-delivery-<id>` holding one plugin, `overlay-<id>`, whose `hooks/hooks.json` is the union
of the `claude/hooks.json` of `common/`, of each tag the project lists in list order, and of
`projects/<name>/` — each event's entry groups in that order, as the overlay wrote them — and whose
skills and agents, each an entry directly in `skills/` or `agents/` of the same directories, are
copied whole from the later plate that holds one of the name, no file of an earlier plate's entry
beside it, each copy keeping its source's permission bits, so a skill's script stays executable. A session runs the plugin from that
directory in place, so a later `attach` re-renders it there and an edit reaches the next session
with no reinstall. Each render is written whole into a new directory beside it and swapped into
place, so a file the overlay no longer holds is gone, whatever an earlier run recorded; the ledger
keeps the render's digest alone, never the id. Every run installs it with `claude plugin marketplace
add <that directory> --scope local` and `claude plugin install overlay-<id>@drybag-delivery-<id>
--scope local`, run from the main checkout, whose `.claude/settings.local.json` Claude Code reads
from every worktree and writes the plugin's entries into; both calls succeed for a marketplace and a
plugin Claude Code already has, so what Claude Code holds is asked of Claude Code each time rather
than of the ledger. A linked worktree of a bare repository has no main checkout, so `attach` refuses
it (`2`) before anything is written, saying it cannot tell which checkout is the main one. A call
that does not succeed fails the run (`1`), naming the call and its exit code and never what it
printed, since that names the plugin; the ledger records no render, the exclude block stays, and the
next `attach` installs it again. Claude Code records a local-scope marketplace for the whole
machine, so the names carry the whole id, which a clone never sees; the plugin's entry is the reason
`.claude/settings.local.json` is placed and hidden on every run (below). No hook entry goes into
`.claude/settings.local.json` any more, since Claude Code rewrites that file whole: the entries an
earlier release's `attach` merged there are taken back, the ones its ledger records under the event
it records and never one by its marker alone, and the new ledger records none.

**The binding is an id this machine keeps, not a remote.** `attach` draws a random binding id
(32 hexadecimal characters) the first time, writes it into the repository's git common directory,
`drybag/binding` there (the directory `git rev-parse --git-common-dir` names, which every
worktree of the repository shares), and records on this machine what it is bound to — the project
name, the `origin` at the time and the checkout — in `$HOME/.local/share/drybag/bindings/<id>.toml`.
A checkout is bound where both are there and the record names its `[project] name`; nothing a
repository commits can write either, and a clone never carries the id, so a clone that names itself
after one of your projects is not bound to it. The id never leaves the machine: it is printed only
as its first eight characters, on the run's line and as `binding` in `--json`. A checkout with no
`origin`, or one whose `origin` is not the remote its binding (or, on a first attach, the
overlay's record) names, attaches all the same, and the line says so, naming both remotes: one
repository is one remote whichever of git's three spellings names it — `git@host:owner/repo`,
`ssh://git@host/owner/repo` and `https://host/owner/repo`, each with or without `.git`, the host
in any case and, on github.com alone, the path too — so a clone made over https of a repository
recorded over ssh hears nothing. The overlay's `projects/<name>/project.toml` keeps the remote it
was first written with and the first attach's date, and is written only while it records no
remote, and then only with the keys it lacks, put above everything the owner wrote there, which
stays byte for byte; an `origin` git prints in bytes that are not UTF-8 is recorded as none. An `origin`'s
userinfo — a token in `https://user:token@host/…` — is taken out before it is printed, on the
screen or in the note naming both remotes, and before it is recorded; an ssh URL keeps its user
(`ssh://git@host/…`) and loses only a password.

**Reads** the overlay's `common/claude/permissions.json`, `common/claude/hooks.json` and the files
under `common/claude/skills/` and `common/claude/agents/` (dot-named ones left out), the same
`claude/` files of each tag the project lists in `projects/<name>/project.toml` (`groups/<tag>/`,
in list order), this project's `projects/<name>/claude/` equivalents, the `codex/` rules of
`common/`, of each tag and of `projects/<name>/`, a later plate winning a name over an earlier one
(the order is `common`, the tags, the project), and this repository's existing
`.claude/settings.local.json`; for a
repository with no `drybag.toml` whose project neither `--project` nor this machine's binding
names, every `projects/<name>/project.toml` in the overlay.
`.claude/settings.json` — the committed one — is read for **nothing**: it is repository-controlled,
and the repository never grants a capability.

**Writes** a block between `# drybag:attach:begin` and `# drybag:attach:end` in the
repository's own exclude file (the one `git rev-parse --git-path info/exclude` names, which every
worktree shares), written first,
`.claude/settings.local.json`, `.codex/rules/`, the ledger `drybag/attach.json` and the
binding id `drybag/binding` (when there is none yet) in the git common directory, this machine's
binding record `$HOME/.local/share/drybag/bindings/<id>.toml`, the render
`$HOME/.local/share/drybag/delivery/<id>/` (written whole into a directory beside it, then
swapped into place, the render before removed whole) and, through the two `claude plugin` calls,
Claude Code's own records of the marketplace and the plugin and the main checkout's
`.claude/settings.local.json`; where the notes are composed, the composed store
`$HOME/.local/share/drybag/stores/<id>/` (a link per group of the overlay's for this project,
`tag-<tag>` to `groups/<tag>/memory/` for each tag the project lists where that is a directory, and
one to its `MEMORY.md`; a directory of the project's `memory/` whose name starts with `tag-` is not
linked, the prefix being the tags'; each run makes its links exactly the overlay's current set, so
untagging takes the link and a rename of a tag moves it, and leaves any file there that is not a
link, such as a note the harness wrote), the key `autoMemoryDirectory`
naming that directory, absolute, in the main checkout's `.claude/settings.local.json`, which Claude
Code reads from every worktree, and — in the overlay — `projects/<name>/project.toml` while it
records no remote, this project's note directories,
`projects/<name>/memory/MEMORY.md` when the store has none yet (rendered as `drybag memory
index` renders it, so the store's index link never dangles and `memory index --check` passes right after
a first attach in an overlay this release rendered, and in an older one once its owner has deleted
by hand the `common/memory/README.md` 0.1.x shipped, which the note reader reads as a note).
It runs no program in the overlay: its commit-time secret scan is `setup --overlay`'s, which makes
or records the overlay, and where that scan is missing `doctor`'s `pre-commit` row says it is not
installed. The ledger is the only record
of which allow rules are drybag's, because an allow rule cannot carry a marker the way a hook
entry can; `detach` reads it and nothing else. **A re-attach takes back an allow rule the overlay
no longer grants**, where the ledger names it and the settings file still holds it: a rule dropped
from `common/`, from `projects/<name>/` or from a tag you took off the project leaves with the
next run, each said as `allow rule withdrawn`, and a rule you added by hand, which the ledger does not name, stays.
The ledger sits in the git common directory beside the binding id, where a branch cannot write it, so
nothing a branch commits names what a re-attach or `detach` takes back. **A re-attach removes no `.codex/rules/` copy**: a
file dropped from a plate, or a tag taken off the project, may since have been committed or edited
by the team, so the run leaves it and says `Codex rule copy no longer in the overlay: <path>`
(`rules_left` in `--json`). The ledger records the sha256 of the bytes `attach` wrote to each copy,
and goes on recording a dropped one only while its file is untracked and holds those bytes, so
`detach` can still take a file Codex reads as a standing instruction; any other is forgotten, and
the file is yours. **`.gitignore` is never written**: it is tracked, so
any line there would be a change every collaborator gets. A `drybag:ignore` region an earlier
release wrote there stays until you remove it.

**`projects/<name>/checkout/` holds the owner-held files**, which `attach` neither reads nor
writes: [`owner-files`](#hooks) places them in each new linked worktree.

**What it places, it hides from git, unless git hides it already.** Each
`.codex/rules/` file and `.claude/settings.local.json`,
which holds the plugin's entry and so the binding id, are this machine's own, so each one is listed in
the exclude-file block, one anchored line per path, unless your own excludes already hide it: the
repository's exclude file or your global excludes file (`core.excludesFile`), read on their own. A
`.gitignore` in the checkout does not stand in for the block, because the repository authors it and
a pull can change it: a path only a `.gitignore` hides gets a line, and a path your own excludes
hide gets none, whatever a `.gitignore` also says. A path the repository tracks — in any ASCII case,
as git itself matches it, or as the same file as one the repository tracks in that directory — is
refused before the first write, since no exclude line hides a tracked file. **Once the block is
written, git is asked whether
each of those paths is ignored** (`git check-ignore --no-index`, every ignore file read), and a path
it would still show — one a `.gitignore` re-includes with a `!` line, which outranks the exclude
file — refuses the run before that path, or anything after the block, is written. The binding id and
the ledger are placed in the git common directory, which git never tracks, so neither is listed nor asked about.
Every one of those paths is the main checkout's, so the two questions are asked of the main
checkout's own index and `.gitignore` whichever worktree `attach` runs from.
A `.claude` linked in from elsewhere is refused before the first write, since what lands there names
the binding id and git cannot be asked whether it is ignored. A checkout that already hides all of them in its
own exclude file or a global excludes file gets no block, and `git status` after an attach shows
nothing new. When the exclude file did not exist, when the directory it goes in did not exist either
(a repository made without git's templates has no `info/`, and the write creates it), or when its
last line had no line ending, the block says so in a comment line of its own, which is what lets
`detach`, from whichever checkout runs it last, give the file back byte for byte. The file is read
as bytes, so bytes in it that are not UTF-8 are kept exactly and refuse nothing. The file is read,
changed and replaced without a lock, so two runs at once in checkouts of one repository — two
`attach` runs, or an `attach` and a `detach`, in the main checkout and a worktree say — can each
read it before the other writes, and the later write then undoes what the earlier one did to it. Run
one `attach` or `detach` at a time. Running `attach` again in the checkout whose lines went puts
them back.

**The harness reads its memory from the composed store.** Where the notes are composed, the
`autoMemoryDirectory` key points the harness at `$HOME/.local/share/drybag/stores/<id>/`, outside
every checkout, whose links reach the overlay's notes and nothing of the repository's, so it waits
for no approval. The key is recorded in the ledger before it is written, so `detach` takes it back;
the path names the whole binding id and is printed only with the id cut to its short form. A repository that keeps its own notes gets
no key. `drybag memory` reads the same store in overlay mode, so the bundles a session starts
with and the harness read one directory. Nothing is placed under `paths.memory` or under
`~/.claude/projects/`: the link tree and the harness memory link an earlier release made there are
yours to remove by hand.

Exits `0` on success. A failure or refusal below that the run meets before its first write ends
`--check` with the run's code and line.

A real run exits `1` on a failure, something it reads that cannot be read or a `git` that cannot
answer, in the order the run meets them:

- `drybag.toml` is missing, cannot be read, is not UTF-8 or valid TOML, or holds a key or value
  the loader refuses; or the machine configuration cannot be read, is not UTF-8 or is not valid
  TOML.
- `git` cannot read the `origin` remote, or `git` cannot name the repository's common directory.
  The overlay's record of this project (`projects/<name>/project.toml`) binds nothing and is never
  written over; one that cannot be read, is not UTF-8 or is not valid TOML is a refusal below.
- The overlay's `permissions.json` or `hooks.json`, or `.claude/settings.local.json`, cannot be
  read or is not UTF-8; or a file under the overlay's `skills/` or `agents/` cannot be read, is
  not a regular file, is not UTF-8 or is longer than 64 MiB, or a directory there cannot be
  listed.
- An existing ledger (`drybag/attach.json` in the git common directory) cannot be read. One that
  is not valid JSON or not a JSON object records nothing: `attach` carries on and writes a new one.
- A Codex rule file in the overlay cannot be read or is not UTF-8, or the overlay's `common/codex/`
  or `projects/<name>/codex/` directory holding it cannot be listed.
- `git worktree list`, which names the main checkout, fails.

For `drybag.toml`, the overlay's record of this project, its `permissions.json` and
`hooks.json`, `.claude/settings.local.json` and the ledger, a file that "cannot be read" includes
one that is not a regular file once a link to it is followed, such as a link to `/dev/zero` or to
a FIFO, which is never waited on, and one longer than 64 MiB, which is as far as each of these is
read. The machine configuration and the overlay's Codex rule files are read whole, and one that is
not a regular file is passed over as absent.

Every failure in that list happens before anything is written. One way to exit `1` comes later,
and leaves behind what was written before it: a store that still does not resolve once the
composed store is built.

It exits `2` on a refusal, in the order the run meets them:

- A `[paths]` value that leaves the project or passes through a symlink.
- No overlay root recorded in the machine configuration, or a `--store` that is not this project's
  own directory inside it.
- The overlay's `permissions.json` or `hooks.json`, or `.claude/settings.local.json`, that is not
  JSON or not a JSON object, or whose `permissions` or `hooks` has a shape the merge cannot read:
  anything but an object, a list of strings, a list of entry groups or a list of entries each with
  a command where one goes, `null` included. An absent key is no rules and no entries. The
  `hooks` of `.claude/settings.local.json` is read only where an earlier attach's ledger records
  entries to take back out of it. `--check` reads each with the run's own readers, so it refuses
  exactly these documents.
- A `.claude/settings.local.json` that drybag's indented write-back would make longer than the
  64 MiB it reads, whether or not this run would rewrite it: a short document many levels deep
  grows by its depth on every line, and `would be longer than this reader reads once written
  back` keeps a run from leaving a file its next read refuses. `--check` refuses it too.
- A `memory.groups` entry that leaves this project's share of the overlay.
- The overlay's record of this project, where it is there and cannot be read, is not UTF-8 or is
  not valid TOML (a merge's conflict markers, when two machines first attached the project), or
  its `tags` is not a list: the record could not say which tags it lists, and a run
  that read that as none would take back what they delivered. The refusal names the file, and
  `--check` refuses it too. A session reads it as no tags and says so. A record that is absent,
  as before a first attach, is no refusal.
- A `git check-ignore` that cannot answer.
- A path it places — a `.codex/rules/` copy, or `.claude/settings.local.json` — that the repository tracks, in any ASCII case, as git itself
  matches it, or as the same file as one it tracks in that directory (where the filesystem folds
  names, a tracked `.CLAUDE/Settings.Local.json`, or on macOS `.claude/ſettings.local.json`, is
  the file `attach` would write), since no exclude line hides a tracked file and what `attach`
  writes there would reach every clone with the next commit; or a `git ls-files` that cannot say.
  The refusal names each such path. `--check` refuses it too.
- A `.claude` that is a symlink, or a `.codex` that is one on a run that writes into it; a
  `git rev-parse --git-path info/exclude` that names no exclude file; an exclude file that cannot
  be read or holds a `drybag:attach` block opened or closed twice (the refusal names the file),
  or, when the block needs a line, that is a symlink or sits in a directory you cannot write.

Every refusal in that list happens before anything is written, so a refused attach leaves both the
repository and the overlay as they were. What is left can only happen once writing has begun:

- An exclude file that cannot be written after all, which is refused, naming it. It is the first
  write, so this refusal leaves nothing behind either.
- A path it places that git would still show once the block is written — one a `.gitignore`
  re-includes with a `!` line, which outranks the exclude file — or a `git check-ignore` that
  cannot answer at that point. It is refused, naming each such path, with only the exclude block
  written; take the line out of the `.gitignore` and run `attach` again, which reuses the block.
- A directory in this project's share of the overlay that became a symlink between the moment it
  was checked and the moment it was written, which is refused.
- Any other write that fails, a rule copy, the settings file, the ledger, the binding id, the
  machine's binding record, the overlay's record or a link of the composed store, which ends as
  `internal error` with the error the system gave.

---

## `drybag detach [--root PATH] [--machine PATH]`

Removes exactly what `attach` added, and leaves the binding alone: the binding id, this machine's
record of it and the overlay's `projects/<name>/project.toml` stay, so a later `attach` binds the
same checkout again.

It reads the ledger, `drybag/attach.json` in the git common directory, and acts on that and on
nothing else. A repository with no ledger fails (`1`) naming the missing file rather than guessing
which allow rules were drybag's from their content — that guess is the reason the ledger
exists, and getting it wrong removes a rule you wrote by hand. A branch cannot write the git
common directory, and a ledger left in the working tree by an earlier release is not read. A
ledger that is not valid JSON records nothing: `detach` fails (`1`), says so and removes nothing.
It removes a `.codex/rules/` copy only from a single file under that directory, a settings key only
if it is `autoMemoryDirectory`, and a directory only from the closed list `attach` can create;
anything else a ledger names (a hand edit, say) is skipped. A ledger claiming
`settings_keys = ["permissions"]` would otherwise have deleted your whole `permissions` block, deny
rules included.

**Run it from any checkout of the repository.** `attach` writes its settings file and
`.codex/rules/` copies into the main checkout whichever worktree it ran from, and its ledger into
the one git common directory, so `detach` acts on the main checkout too.

**Writes**: it takes the recorded allow rules and the `autoMemoryDirectory` key back out of the
main checkout's `.claude/settings.local.json`, and leaves the file unwritten when neither is in it,
removes each `.codex/rules/` copy whose bytes are
still the ones the ledger's sha256 records (any other copy is left and named, `Codex rule copy left:
<path>`, `rules_left` in `--json`), withdraws the overlay's rendered plugin — `claude plugin uninstall overlay-<id>@drybag-delivery-<id> --scope
local` where the main checkout's `.claude/settings.local.json` names that plugin under
`enabledPlugins`, and `claude plugin marketplace remove drybag-delivery-<id>` where it names that
marketplace under `extraKnownMarketplaces`, each run from the main checkout, then the render
directory `$HOME/.local/share/drybag/delivery/<id>/` removed whole where it is there, a link
there unlinked, then every link in the composed store `$HOME/.local/share/drybag/stores/<id>/`
and the directory where nothing else is left (a file there that is not a link is a note the harness
wrote: it stays, and so does the directory, which the line says and `--json` reports as
`store_kept: true`) — removes the `drybag:attach` block in the repository's exclude file, and deletes
the ledger, `drybag/attach.json` in the git common directory. The render directory and the composed store are derived
from the binding id and never read from the ledger, so a ledger naming another directory removes nothing
outside it. The plugin goes before the exclude block, so Claude Code takes the plugin's entries,
which name the id, out of `.claude/settings.local.json` while that file is still hidden. Each call
is decided by what that file names, never by the ledger or the render directory, and the file is
read again once they ran: while a name under either key names a `drybag-delivery-` marketplace,
whatever the calls exited with and whether or not the binding id can be read, `detach` fails (`1`)
naming the key and never the id; the exclude block, the ledger and
the render directory are kept, so the file stays hidden, and running `detach` again finishes the
withdrawal. The calls leave `enabledPlugins` and `extraKnownMarketplaces` behind, emptied; a file
holding those and nothing else is removed, and one holding anything more stays as it is. In a
linked worktree of a bare repository git names no main checkout, `attach` installed
nothing there, and `detach` withdraws that checkout's own parts with no `claude plugin` call. A
render directory that cannot be removed fails (`1`) the same way, with the ledger kept. An allow
rule Claude Code added to `.claude/settings.local.json` — the one a "don't ask again" answer writes
— is not on the ledger and stays, whatever order Claude Code rewrote the file's keys in. A file left
holding nothing is removed rather than left empty — for the exclude file, only when `attach` created
it, which the block records, so an exclude file you had, empty or not, stays, and the `info/`
directory it sat in goes with it only when `attach` created that too and it is empty; the line
ending `attach` added to your exclude file's last line before its block is taken back too, when
nothing follows the block. The exclude file is read and written as bytes, so bytes in it that are
not UTF-8 are kept as they are. An exclude file that is a symlink is left alone, because `attach`
never writes through one.

Last, each directory the ledger records `attach` as having created — of `.codex/rules/`,
`.codex/` and `.claude/`, in that order — is removed when it is
empty, and left standing otherwise. A link tree under `paths.memory` or a harness memory link under
`~/.claude/projects/` an earlier release made is not touched: remove those by hand.

**The files `owner-files` placed stay.** A file the `owner-files` handler put in a linked worktree
is not on the ledger, and `detach` leaves it, as it leaves any file in a worktree you may have edited.

**`.gitignore` is never touched.** `attach` writes nothing there, so `detach` takes nothing out:
a `drybag:ignore` region an earlier release wrote stays until you remove it.

**Directories come back too.** `attach` records which of `.drybag/local/`, `.drybag/`,
`.codex/rules/`, `.codex/` and `.claude/` this repository did not have before it ran, and `detach`
removes exactly those once everything inside them is gone. The removal is `rmdir`: a directory
still holding anything — your own `.codex/rules/` file, your `.claude/settings.json` — survives,
and so does its parent. The round trip is byte-for-byte in the main checkout.

**It does not touch `projects/<name>/project.toml`.** That record is the overlay's note of the
remote and the date this project was first attached, kept for you to read, and binds nothing; it is
the overlay's, not this checkout's, so a detach leaves it as it is.

Exits `0` on success. It exits `1` on a failure, in the order the run meets them:

- `git` cannot list this repository's worktrees, which names the main checkout.
- The ledger, `drybag/attach.json` in the git common directory, is not there, cannot be read,
  is not UTF-8, is not valid JSON or is not a JSON object.
- `.claude/settings.local.json` cannot be read or is not UTF-8.

"Cannot be read" means here what it means for `attach`: a link to a device or a FIFO, or a file
longer than 64 MiB, which neither command reads past. A settings file an earlier release's
`attach` wrote back past that size has to be cut down by hand before `detach` can run.

It exits `2` on a refusal, in the order the run meets them:

- A ledger naming files, settings keys or directories `attach` could not have written.
- A `.claude/settings.local.json` that is not JSON or not a JSON object, or whose `hooks` has a
  shape the withdrawal cannot read, or whose indented write-back would pass 64 MiB.
- A `git rev-parse --git-path info/exclude` that names no exclude file, an exclude file that cannot
  be read, a `drybag:attach` block in it opened or closed twice, or one to take out of a file in
  a directory you cannot write (the refusal names the file).
- A path the withdrawal writes or removes reached through a directory that became a symlink after
  the attach: `.claude` when the settings file is to be rewritten, `.codex` or `.codex/rules` for
  a recorded rule copy. The refusal names the path and
  the symlink. A rule copy that is itself a link is not one of these: it is unlinked, and what it
  points at stays.
- A `.claude/settings.local.json` whose `permissions` is not an object, or whose
  `permissions.allow` is not a list of strings.

Every one of those is answered before the first withdrawal, so a refused `detach` has removed
nothing. What is left can only happen once withdrawing has begun, and leaves the ledger in place
with part of the attach already undone:

- An exclude file whose write fails for any other reason, which is refused, naming it, once the
  settings and the rule copies are withdrawn.
- Any other write or removal that fails, which ends as `internal error` with the error the system
  gave.

---

## `drybag setup [--preset NAME] [--plugin NAME …] [--home PATH] [--machine PATH] [--overlay VALUE]`

Configures this machine from a preset, `recommended` unless `--preset` names another: the
machine configuration file's `[personal]` and `[machine]` tables, the deny rules and personal
values in `<home>/.claude/settings.json`, and each plugin `--plugin` names, one install per plugin
per configured harness. Without `--plugin` no plugin is installed and no plugin command runs. That file is read as Claude Code reads it, past a leading byte-order mark,
which a rewrite keeps. The deny rules are merged in beside the owner's own, and none is removed.
`recommended` denies the env files by name: `.env`, `.env.local`, `.env.*.local`, `.env.dev`,
`.env.development`, `.env.prod`, `.env.production`, `.env.stage`, `.env.staging` and `.env.test`,
each as `Read(**/<name>)`, so the templates a project commits (`.env.example`, `.env.dist` and the
rest) stay readable. An env file under another name stays readable too. `--home` and `--machine` default to the home directory and to
`~/.config/drybag/config.toml` — the file every reader reads, and not whatever
`XDG_CONFIG_HOME` or `DRYBAG_CONFIG` names, because a machine file half the installation
cannot find is not a machine file. Both flags exist so this command can be pointed at a
scratch destination instead of your real one, the same way every other command here takes
`--root`. A scratch destination is **not a dry run**: the same files are written, at the paths
these two flags name, and nothing is suppressed. They apply to `--preset` alone — `--git-hooks`
writes inside a repository and ignores both. The settings file is written through the home's own
symlinks, so a `~/.claude` or a `~/.claude/settings.json` that a dotfiles manager links into
another tree gets the file the link leads to, and the link stays. The machine configuration file
is written through a link at it the same way.

`setup` is not the only command that writes outside a repository, and two others say so in their
own sections: `drybag memory promote` records an approval in `~/.config/drybag/trust.json`,
and `drybag attach` keeps its binding record, render and composed store under
`~/.local/share/drybag/`. It is the only
one that writes the machine configuration file and `<home>/.claude/settings.json`. `--root` names
the repository `--git-hooks` installs into (below); machine setup reads no repository, so it refuses
`--root` (`2`) with nothing written, where it used to take the flag and read nothing of it.

`setup` is the only writer of the machine configuration file, and its readers do not change to
suit it: `[personal]`, `[guards]`, the session `[budgets]` and `[sync]` are `config.owner`'s,
which every command's load and every session read; `[overlay] root` is `config.overlay`'s; and each resolves
the file `--machine` names or the default one. A second run merges rather than
replaces, key by key: a personal value already recorded — by an earlier `setup` or by your own
hand — is never overwritten by the preset's own default, and an overlay root a previous run
recorded survives a run that only changes something else. A table `setup` knows nothing about is
carried through untouched, and so is a key at the top level; **comments are not** — the file is
parsed and rewritten, and there is no standard-library parser that keeps them.

The `[personal]` values are copied into `pluginConfigs` in `<home>/.claude/settings.json`, where
Claude Code reads this plugin's own options, only where it holds no value for them: a value
already there — one you set in Claude Code's plugin-config screen, or one an earlier `setup`
copied — is kept on every run. So a personal value you change in the machine file after the first
run does not reach `pluginConfigs`; change it there too, or delete it there and run `setup` again.

**From an agent's sandboxed shell** `setup` cannot write the machine directory or the user
settings: with Claude Code's sandbox on, an agent's shell writes nothing outside the working
directory and the temporary directory. It says so in one sentence (below, under the exits), naming a
person outside the agent's sandbox as the one to run it, and never ends in a traceback.

**Plugins are installed only when named**, with `--plugin NAME` once per plugin: a plugin name is
lowercase ASCII letters, digits and `-`, led by a letter or a digit, and the parser refuses any
other, naming that rule. A third-party plugin runs in every session of its harness, hooks
included, and none is pinned, so none is installed unasked. A named plugin is installed per harness drybag serves (`claude` and `codex`),
from the preset's own per-harness marketplace table (`[plugins.<harness>]`). For each harness the preset declares a
marketplace for, `setup` registers it (`claude plugin marketplace add <source>`; idempotent — an already-registered
source is a no-op reported as such) and then installs each plugin bare (`claude plugin install
<name>@<marketplace>`; no `--scope` or `-y` — the spike record's own measured output reports
`(scope: user)` as the *default*, and `-y` only ever appears there on `uninstall`). Codex adds
rather than installs (`codex plugin add <name>@<marketplace>`) where the preset declares a
marketplace for it. A harness with no declared marketplace for a plugin is not attempted —
nothing here is vendored on a guessed marketplace name — and a missing binary or a
failed call is a reported note, never a failure.

**The overlay is touched only when `--overlay` names an answer.** It is the one entry for an
overlay, in three forms, below; naming one is the request, and no flag stands in front of it. Each
is validated **before the first write** — before the machine file, the settings merge and the
plugin installs, and for `create:` before `gh repo create` runs on anybody's account — and the
place it names is judged by one rule. Nothing there, or an empty directory that is no link, is a
place to render or clone into. A tree that carries the identity record `drybag-overlay.toml`,
parsing as TOML and holding `layout = 1`, is an overlay; the refusal of a tree without it names the
file and its keys. Anything else is refused (`2`): a file, a link at a `create:` destination, a
directory holding something that is not an overlay, and, in one sentence for both forms, a
directory you cannot search, or one holding no overlay that you cannot both list and write. Where
the overlay lives is yours to choose and `setup` refuses no place for it; `drybag doctor`'s
`overlay-requires` row warns when another repository's work tree holds it, since that repository
can put files into it. Each path is judged and recorded resolved, so the record does not follow a
link someone retargets later, and a run that records a root other than the one the machine file
held says so in a note naming the root it replaced, and how to record that one again. A leading
`~` is the home `HOME` names, as in the machine file's `[overlay] root`; where `HOME` is empty or
relative, such a path is refused (`2`) rather than read against `/` or the directory the command
ran from. Every overlay a form makes or records gets the commit-time secret scan with `pre-commit
install`; a missing `pre-commit` is a note. What `gh`, `git` and `pre-commit` print is quoted in
these notes as it came, except that one holding anything but a plain path is escaped, and one
longer than 120 characters is cut to its first 120 and its length.

**Record: `--overlay <path>` naming an overlay** records its root and writes nothing in its tree;
its `pre-commit` git hook is installed, so a second machine records its clone with the scan armed.

**Render: `--overlay <path>` naming nothing**, or an empty directory, renders the shipped template
there, with no network call. The directory it is made in has to be one you can write: a path whose
parent is missing or not writable is refused before the first write. So a mistyped path is not
refused: it is rendered at and recorded, with the note above when it replaces a recorded root. The
render writes the identity record after every other file, so a render cut short is never taken for
an overlay. It is made a git repository with `git init` and `git symbolic-ref HEAD refs/heads/main`
(not `git init -b main`, which a `git` older than 2.28 refuses), on `main` with no remote, and the
note says how to give it one; a `git` that cannot run, or runs and fails, is a note and not a
failure, since the tree is there.

**`create:`: `--overlay create:<owner>/<name>`** asks GitHub for a private repository generated
from a template — a template and not a fork, since a fork's visibility is bound to the upstream
network and cannot be made private — and clones it to `<home>/<name>`. What is there already is
judged first, before the first write and before `gh` is asked anything: nothing, or an empty
directory, which this run clones into; the overlay an earlier run made, which is left alone and
nothing is generated; or anything else, refused (`2`) by the rule above, since the clone would meet
it only after `gh repo create` had made a repository nothing then records. It then asks `gh repo
view <owner>/drybag-overlay-template --json isTemplate` once: a template there is generated
from, and a repository of that name that is not one, or `gh`'s explicit answer that there is none,
means you have published none, and the template is `github.com/dry-bag/drybag-overlay-template`,
the publisher's public copy, named with its host: `gh` looks an unqualified name up on `GH_HOST`,
so on a GitHub Enterprise host `dry-bag/…` would be whoever owns that name there. Any other
failure of that question — an expired token, a network error, a `gh` that is not installed or
hung, an answer that is not the JSON asked for — stops the command with `gh`'s own message and
creates nothing (`1`). Once `gh repo create` has run, the repository may exist on GitHub whatever
`gh` answered, and a second `create:` would fail on the name it holds, so every refusal from then
on says so and gives the remedy that works: once `<home>/<name>` holds a clone of it, record it
with `drybag setup --overlay <home>/<name>`. When `gh repo create` itself fails, the command
stops there with its exit code and stderr; when it reports success and the clone leaves nothing at
`<home>/<name>`, `gh repo view` is asked whether the repository exists, and the clone is retried
once, after a ten-second wait when it does — a wait carried on reasoning rather than a measurement,
since the one trial run against it did not reproduce the race. A clone is written in the order git
takes, so, unlike a render, a clone cut short can carry the identity record without every other
file. A generated overlay has no `.drybag/manifest.json`, so `drybag overlay upgrade`
refreshes none of its files once they differ from a release's (`overlay upgrade`, above).

**Writes** `<home>` itself when it is not there yet; `--machine`'s file, with the directories above
it, once for the preset and again for the overlay root `--overlay` records, and, for an overlay it
renders or creates, `[sync] enabled = true` beside it, which switches the [note sync](#note-sync) on
(recording an existing overlay leaves `[sync]` as it is);
`<home>/.claude/settings.json`, where its links lead; and, through the plugin
commands it runs for each plugin `--plugin` names, on each harness with a declared marketplace (`claude plugin marketplace add` and
`claude plugin install`, `codex plugin marketplace add` and `codex plugin add`), the marketplace
registrations and installed plugins those commands write into each harness's own configuration;
with `--restore`, the same `claude plugin marketplace add` and `claude plugin install` for what the
overlay's `machine/claude/settings.json` lists, with `--sync`, `[sync] enabled = true` in the machine
file, and, with `--yes`, the trust record's `reviewed` approvals (`trust.json`, beside the machine
file) for the notes of the overlay's share for each attached project.
`--overlay <path>` naming an overlay writes nothing in its tree: it is recorded, and its
`pre-commit` git hook is installed through `pre-commit install`. Naming nothing or an
empty directory, it writes the directory with every file of the template plus `.drybag/manifest.json`, the
repository `git init` makes there, and, through `pre-commit install`, its `pre-commit` git hook.
`--overlay create:<owner>/<name>` writes, through `gh repo create <owner>/<name> --private
--template <template> --clone`, a new private repository on GitHub under `<owner>` and its clone
at `<home>/<name>` — or, when that clone leaves nothing there, a clone from the retried `git clone`
— then its `pre-commit` git hook. Run again over the overlay it made, it generates nothing.
`--restore` writes, beyond the above, for each checkout it attaches what
[`drybag attach`](#drybag-attach---store-path---project-name---check---root-path---machine-path)
writes, listed in its **Writes**, and nothing else; into a checkout it reports `absent` or
`refused` it writes nothing, and a `failed` one keeps what the failed attach had written, which a
re-run finishes.

**Exits** `0` on success, and `2` on each of these refusals:

- `--uninstall`, which is taken only with `--git-hooks` (below), before anything is written;
- `--restore` with no overlay recorded and none named, before anything is written; after machine
  setup ran, an overlay to restore from that is not one or a projects file it cannot read (see
  `--restore` below), before any attach; `--restore` beside `--git-hooks` or
  `--approval-boundary`; and `--yes` or `--sync` without `--restore`;
- `--root`, which names the repository `--git-hooks` installs into, before anything is written;
- a refused `--overlay`: a path that names nothing under a directory that is missing or that you
  cannot create it in, a path holding something that is not an overlay, a `create:` destination
  that holds something and is not the overlay an earlier run made, a directory at either that you
  cannot search, or that holds no overlay and that you cannot both list and write, a path beginning
  with `~` while `HOME` names no home, or a path that is not UTF-8 text and so cannot be recorded in
  the machine file;
- a `--home` that cannot take what this run writes under it, naming the directory you cannot write
  into, asked only where a write lands: the one the settings file is made in (its directory when
  it is there, the nearest directory above it while it is not); and for `create:`, the one the
  clone is made in while it is not there yet. A `<home>`
  you cannot write into is not refused for that alone: with a writable `.claude` already in it, and
  no overlay to create, nothing this check asks about is made in it;
- a settings file's directory that cannot be read, which the settings write opens;
- a `<home>` that could not be created;
- any other path this command cannot ask about before its first write, named with why: `<home>`
  or an `--overlay` directory below a directory nobody may search, and a symbolic-link loop at
  `~/.claude`, `--home` or `--overlay`, on every Python;
- a write refused as an agent's sandbox refuses one, met by the machine file or the user settings
  file (`EPERM` on macOS and `EROFS` on Linux and WSL2, as Claude Code's sandboxing reference gives
  them), or by the question asked of the settings directory before the first write (a directory
  whose mode lets you write it, which the system still says you may not): one sentence, saying
  `setup` stopped, that a person must run it in their own terminal, outside the agent's sandbox,
  and that met in their own terminal it is the directory itself refusing writes, as a read-only
  mount or an immutable flag does. A run it stops part-way is finished by the next.

The machine file's directory is not asked about before the first write: a write there that fails
ends the run `1`, or `2` in the sentence above where the sandbox refused it. So does the user
settings file, which is read when it is merged, after the machine file is written: one that cannot
be read or is not one JSON object the parser reaches ends the run `1`, naming it, and once it is
repaired the next run finishes what this one began.

These questions are asked in one fixed order, and the first refusal ends the run: what `--overlay`
names, whether an existing path is an overlay and what a `create:` destination holds; the preset;
and where a write under `--home` lands. Every one of those refusals happens before the first write,
**with one exception**: for
`--overlay create:<owner>/<name>`, "not an overlay" is a check on the tree that arrived, so it runs
after the repository has been created on GitHub and cloned — along with the machine file, the
settings merge and the plugin installs. That refusal, like every one after `gh repo create`, says
the repository may now exist, and how to record it, because nothing else would. Everything else `create:` can be refused for — a
malformed spec, a name that is not one path segment, a destination that holds something else, a
`<home>` you cannot write into, or one the machine file could not record — still happens before
`gh` is run at all.

A plugin that fails to install or a harness that is absent is a note in the report, not a
nonzero exit (`--restore` exits `1` when an attach was refused or failed, below). What the failing plugin command printed is quoted as the overlay's notes quote it
(escaped, and cut to its first 120 characters and its length).

**`--restore`** brings a machine back from the private overlay its machine file records, or the one
`--overlay` names, in these steps, each reported and none undone by the next:

1. machine setup, as above (`--preset`, `--plugin` and `--overlay` are taken as they are without
   it);
2. the plugins the overlay's machine settings enable: `<overlay>/machine/claude/settings.json` is
   the overlay's copy of Claude Code's user settings, and restore reads two keys of it and writes
   nothing from it. Each `extraKnownMarketplaces.<name>.source` that is exactly `{"source":
   "github", "repo": R}` or `{"source": "git", "url": U}`, string values, is added with `claude plugin
   marketplace add R` or `… U`; a source of another kind, or holding any other key (a `git`
   source's `ref`, a `github` source's `path` or `sparsePaths`), is a note naming the marketplace
   and what restore does not carry, and is not added. Each `enabledPlugins` key whose value is `true`
   is installed as written with `claude plugin install <id>`. These are `setup --plugin`'s own argv,
   and a non-zero exit, a missing `claude` included, is a note quoting what it said, never a
   refusal. A second restore runs them again, and whatever Claude Code answers for a marketplace
   already registered or a plugin already installed is what you see. The ids installed count among
   machine setup's `plugin(s) installed` and `--json`'s `plugins_installed`, and each note is
   printed among its notes, in its summary line and in `--json`'s `notes`;
3. attach, for every project `<overlay>/machine/projects.toml` lists whose `dir` is there. A `dir`
   that is not there is reported `absent` and skipped; a checkout with no `drybag.toml` is
   attached under the project its table key names, as `attach --project` would; a checkout `attach`
   refuses (one whose `drybag.toml` names another project than its table key) is `refused`, and one whose attach
   fails (a plain directory, or a failure part-way) is `failed`, each with attach's own message, and the rest go
   on. The exit code is `1` when a project was refused or failed, and `0` otherwise, `absent`
   included. A run twice attaches nothing new, and a project removed from the file stays attached
   until `drybag detach` there.

4. with `--yes` only, the overlay's notes recorded as reviewed on this machine: after each project
   it attached, every note of the overlay's share for its table key (`common/memory`, each listed
   tag's `groups/<tag>/memory`, and each group under `projects/<name>/memory/`) not already
   reviewed at its current bytes is recorded in the trust record beside the machine file, notes
   written on another machine that nobody reviewed included. Only overlay paths are walked,
   whatever the checkout's memory mode, a group directory that is a link is followed, and a note
   is reviewed wherever the same bytes are read. Without `--yes` nothing is recorded as reviewed, whatever the overlay holds. A project whose notes cannot be recorded (an unreadable
   trust record, which is never overwritten) is reported `failed`, attached all the same. A second
   run with `--yes` records nothing new; an approval it recorded is withdrawn by a hand edit of
   `trust.json`. `--yes` without `--restore` is refused (`2`),
   naming `--restore`, before anything is written;
5. with `--sync` only, `[sync] enabled = true` in the machine file, which switches the
   [note sync](#note-sync) on; `--sync` without `--restore` is refused like `--yes`.

Last, it checks the tools and prints what is missing on the first line of its output, above machine
setup's summary, and refuses nothing: `git`, one of `claude` and `codex`, and a `python3` or a `uv`
for the hooks. A missing `git` makes each attach fail in attach's own words.

**The input, `<overlay>/machine/projects.toml`**, is the owner's, one `[projects.<name>]` table per
project: `<name>` is the overlay project the checkout belongs to (the directory under the overlay's
`projects/`), and `dir` is where its main checkout lives, absolute or led by `~/`, which is read
under `--home`. Every other key is ignored by drybag; an overlay's own scripts may read them.
`dir` missing, not a string or relative, a file that cannot be read or is not TOML, and a
`projects` that is not a table, are refused (`2`) naming the table, after machine setup ran and
before any attach. No
file lists nothing. The store `attach` is handed is the one the table key names, and `attach`
refuses a store that is not the checkout's own project's, so a clone that claims another of your
projects in its tracked `drybag.toml` is refused rather than given that project's notes, rules
and delivery.

With `--restore`, the overlay restored from is the one `--overlay` recorded, rendered or created,
else the one the machine file records. With no `--overlay` and no overlay recorded, `--restore` is
refused (`2`) naming `--overlay PATH`, before anything is written; once machine setup ran, an
overlay to restore from that is not one (a recorded overlay that is gone) is refused (`2`) naming
it and saying machine setup ran. It is refused beside `--git-hooks` and `--approval-boundary`. The
summary's overlay clause and `--json`'s `overlay` name the overlay restored from. `--json` adds
`sync`, whether `--sync` was given, `missing` and `projects`, each project's `name`, `dir`, `state`
(`attached`, `absent`, `refused` or `failed`), `detail`, the last attach's own words, and
`promoted`, the notes `--yes` recorded.

What stays an overlay's own script and is not done here: cloning the checkouts, owner-held files,
excludes, links, commit hooks and the merge of the overlay's settings.

---

## `drybag setup --git-hooks [--uninstall] [--root PATH]`

Installs the commit-message hook into this repository's own hooks directory — `git rev-parse
--git-path hooks`, never `core.hooksPath`, which is global state this command has no business owning
and which a repository-wide install would compete with husky or `pre-commit` elsewhere on the
machine.

A foreign hook of the same name is kept as `prepare-commit-msg.local` and the installed hook
`exec`s it last, so nothing that was already running there stops running; `--uninstall` puts it
back under its original name, byte for byte. The report names exactly what moved — a `.local`
file nobody was told about is indistinguishable from a lost one.

**Refuses (`2`) a foreign hook whose bytes name `prepare-commit-msg.local`.** Kept under that name,
it is the file the installed hook `exec`s last, so a chain line naming it — `exec "$(git rev-parse
--git-common-dir)/hooks/prepare-commit-msg.local" "$@"`, or the same name off `"${0%/*}"` or
`"$(dirname "$0")"` — would `exec` itself, and `git commit` would run until it was killed. The
refusal names the hook and where it would be kept, and nothing is written: remove its chain line, or
move the hook aside. A re-install reads the `.local` beside drybag's hook for the same name and
refuses too, saying what is already on disk: drybag's hook runs that `.local` last, so every
commit runs until it is killed. It names the same remedy and leaves both files as they are. The
check is for the name, not for how a chain is spelled: `exec "$0.local" "$@"` names
`prepare-commit-msg.local.local` once the hook is kept, runs nothing twice, and is installed; a
`--git-common-dir` chain under a `core.hooksPath` that is not that directory is refused though it
would not loop, and the same remedy covers it. It is a liveness check, not a security control: a
chain that builds the name at run time (`"${0%.local}.local"`, `$(basename …)`, a variable) is not
seen, and neither is a `.local` edited to name itself after the install, which loops as any hook
that `exec`s itself does. Nor is the name in another case: the bytes are compared as they are, so
`Prepare-Commit-Msg.local`, which a case-insensitive volume (macOS's default) opens as the same
file, is not refused there, because on a case-sensitive volume it names another file and refusing it
would refuse a chain that cannot loop. A hook past the 64 MiB read cap is not read, so it is not
judged either: it is kept and chained, as below.

**Refuses (`2`) together with `--preset`, `--overlay`, `--plugin` or `--restore`.** Each asks machine setup to
do something, which this form does not do, so it names `--git-hooks` and writes nothing, where
`--overlay` used to be dropped and the hook installed. `--home` and `--machine` say
only where machine setup would write, and are ignored.

**Refuses (`2`) `--uninstall` without `--git-hooks`.** It removes the hook this form installs and
means nothing to machine setup, so `drybag setup --uninstall` names `--git-hooks` and writes
nothing, where it used to drop the flag and run the machine setup.

**Writes** the hook file in `--root`'s hooks directory, and the `.local` file beside it only when a
foreign hook was there to preserve, by renaming that hook. Under `--uninstall` it removes the hook
file only when it is drybag's, and renames the `.local` file beside it, when there is one, back
to `prepare-commit-msg`. Its line says which it met: `removed <hook>` with whether a foreign hook
was restored, `there is no drybag hook at <hook>; nothing was removed`, or `left <hook> as it
was: it is not drybag's hook; nothing was removed`; `--json` carries it as `found` (`removed`,
`absent` or `foreign`) beside `path` and `restored`. A FIFO or a directory at the path is foreign to
`--uninstall`, which leaves it, and the install refuses it (`2`). A hook whose mode forbids reading
is neither drybag's nor foreign: either form refuses (`2`) naming it and the reason, and leaves
it. A regular file past the 64 MiB read cap is foreign, since drybag's own hook is a couple of
kilobytes: it is kept and chained, and `--uninstall` leaves it. Exits `0`; `2` when `--preset`,
`--overlay`, `--plugin` or `--restore` is also given, `--uninstall` is given without `--git-hooks`, the hook
cannot be read, or a hook names `prepare-commit-msg.local`.

---

## `drybag setup --approval-boundary [--home PATH] [--machine PATH]`

Prints what keeps an agent's shell out of the trust record's directory under Claude Code, for you
to set, and sets none of it: an approval holds against an agent only while the harness's sandbox
holds ([`drybag memory promote`](#drybag-memory-promote-note----changed) says why), and
drybag neither enforces nor checks that boundary. The line names:

- the deny rule `Edit(//<the trust record's directory>/**)` for `permissions.deny` in
  `<home>/.claude/settings.json`. The directory is that of
  `~/.config/drybag/trust.json`, or of the file beside `--machine`, which is the machine
  configuration file's own, so the rule covers that file too; where a symbolic link makes the
  directory as named and the directory it leads to differ, a rule is named for each, since the
  harness compares a write against the resolved path and a tool call may carry the path as named.
  Measured on Claude Code 2.1.296, an `Edit` rule in that spelling stops both the sandboxed shell
  and the file tools; one leading slash anchors the path at the working directory and stops
  nothing outside it, and a `Write` rule stops neither;
- `sandbox.enabled = true` in the same file, since the rule holds against the file tools on its
  own and against the shell only while the sandbox confines it;
- and, since a project's `.claude/settings.json` or `.claude/settings.local.json` turns a user's
  sandbox off, `sandbox.enabled = true`, `sandbox.failIfUnavailable = true` and
  `sandbox.allowUnsandboxedCommands = false` in the managed settings file only an administrator
  writes (Claude Code's sandboxing reference's recipe for enforcing the sandbox),
  `/Library/Application Support/ClaudeCode/managed-settings.json` on macOS and
  `/etc/claude-code/managed-settings.json` on Linux.

`--home` and `--machine` name the two files as `setup` would write them, and each is
printed absolute: a rule over a relative `--machine`'s directory would carry one leading slash and
deny edits under the working directory of every project. `--json` keys: `deny_rules`, `settings`
and `managed`.

**Reads** nothing but the directory the trust record lies in, to resolve it.

**Writes** nothing.

**Exits** `0`; `2` beside `--preset`, `--overlay`, `--plugin`, `--restore`, `--git-hooks` or
`--uninstall`, which name a write this run does not make; `1` for a `HOME` that is empty with no `--home` or no
`--machine`.

---

## `drybag doctor [--json] [--root PATH] [--home PATH] [--machine PATH]`

Fourteen checks over one installation. It **reports and never repairs**: every finding
carries the command that would fix it, and not one of them is run for you. Nothing is written.

The rows come in a fixed order: the installation's own eight first, then the six about the
private layer — the binding's (`attached`), memory's (`bundles`, `memory`), the
private overlay's (`pre-commit`, `overlay-requires`) and its note sync's (`sync`). Match a row by its `name`, never by its
position.

**Several subprocesses are run and every one of them only asks.** drybag's own
`hooks/run-hook.sh` with `--version`, and the `git` queries the other rows need — where the overlay keeps its hooks, what this checkout's `origin` is, which the
binding's row asks, the repository's common directory, where the binding id and the ledger are
kept, which the binding's row (twice: for the ledger and for the id), the note store's rows and
the `preferences` row's read of the overlay's project file each ask for themselves, which
checkout is the main one (`git worktree list`), whose settings file the binding's row reads, whether this checkout is a registered worktree (its
common and its own git directory), which the `memory` row asks to read the main checkout's settings
file a linked worktree reads too, whether a path `attach` placed is tracked (`git ls-files`) or ignored (`git check-ignore`) and whether a
tracked file names the delivery (`git grep`), which the binding's row asks of a bound checkout, and the
binding's common directory once more, which the binding's row asks to read the overlay's tag layers.
Sixteen of those are measured on a green attached installation whose machine file switches the
note sync on, as `setup --overlay` does for an overlay it makes — the wrapper probe and fifteen
`git` questions, the `sync` row's `git version` among them — and not one of them leaves this
machine. The `git` questions are `gitenv`'s five seconds each, and the wrapper probe is this
area's own thirty seconds. The `sync` row's `git version`, of the overlay's `git`, is bounded at
five seconds like them, and asked only where the note sync is on; after a `raced` job it asks
one `git rev-parse --git-path` more.

The summary line carries the counts and the names of whichever status most needs reading, capped
the way every summary in this CLI is. The rows are in `--json`, under `checks`, one object per
check with `name`, `status`, `detail` and `remedy`, so every remedy is there.

`status` is one of `ok`, `warn`, `red`, `skip`.

| Check | What it answers | What it reads |
|---|---|---|
| `not-initialised` | whether there is a `drybag.toml` here, and how much of it a session can use: with none, a warning that the session guards and `doctor` work without one and memory stays the coding agent's own, and that a `drybag.toml` adds the rest, except in a checkout this machine binds, where it is ok and says the configuration comes from the overlay's layers; with one that loaded with settings ignored or put back to the preset's, a warning naming at most three of their keys and counting the rest, never their values; red only for one a session drops whole, in the words of the session's warning | `drybag.toml` |
| `versions` | whether the project's `[drybag] version` is the drybag running; with no project configuration, which drybag runs | `drybag.toml`, the package |
| `wrapper` | whether the wrapper can actually reach drybag on this machine: red when it writes a fault to stderr or cannot be run; under a root the environment named, which it never runs, red when the wrapper is not executable and a skip otherwise; a stale `hooks/hooks.json`, an edited wrapper that still runs or a changed `scripts/drybag` is not reported | one `run-hook.sh --version`, and only under the plugin root this drybag is part of; under a named root, `hooks/run-hook.sh`'s mode |
| `budgets` | every budget set above the preset, named raised, and every one set below it, named lowered | `drybag.toml`, the machine file, the preset |
| `preferences` | each personal value, guard switch, preference and session budget a session resolves, with the layer its value came from — the preset, the repository, the overlay's common file (`overlay common`), its file for the project this checkout is bound to (`overlay project`) or the machine file — and the value only where it is a boolean, a number or one of drybag's own words; then, as information that never changes the row's status, every note reading the overlay's layers gave — no overlay recorded, a file not there or not loading, a key it cannot use or may not set; red when the machine file does not load, in the words every command refuses it in, which name the file and where the parser stopped; a warning naming the file when a key in it could not be used | `drybag.toml`, the preset, the overlay's two `drybag.toml` files, the machine file |
| `cli-path` | whether `drybag` resolves on `PATH` | `PATH` |
| `diagnostics` | how many reasons the hook sink recorded — a count, never a line of the file | `${CLAUDE_PLUGIN_DATA}/drybag/diagnostics.jsonl` |
| `ignored-env` | as information, never a status: `DRYBAG_CONFIG` set, or `XDG_CONFIG_HOME` set to anything but the `.config` of the home every command reads under (`HOME`, or the password database's where `HOME` is unset), and not honoured by any command; and a `HOME` that is not the home the password database records for this user, since drybag follows `HOME` | the environment, the password database |
| `attached` | the overlay binding, what it delivers, and, where `memory.mode` is `overlay`, the `autoMemoryDirectory` pointer at the composed store, read alike from every checkout (the states are below the table) | the ledger `drybag/attach.json` in the git common directory, the main checkout's `.claude/settings.local.json`, `~/.local/share/drybag/delivery/<id>/`, `~/.local/share/drybag/stores/<id>/`, the overlay's executable parts, `git` on the paths `attach` placed |
| `bundles` | a bundle that does not fit its slots, and one whose part reaches the cap | the note store |
| `memory` | the memory a session gets: the active `memory.mode` and the layer that set it (or that none does, and memory is the coding agent's own), the store, which settings file sets the harness's `autoMemoryDirectory` — the checkout's `.claude/settings.local.json`, the main checkout's, the committed `.claude/settings.json` or `~/.claude/settings.json`, the first that holds it, named as information and never with its value, since a committed file may point the harness elsewhere — and the store's unreviewed notes as a count; a warning only for files in the note store that are not notes, counted (at most 500,000 entries) | the resolution `preferences` reads, the note store, the machine's trust record, those settings files |
| `pre-commit` | whether the overlay's commit-time secret scan is installed on this machine | the overlay |
| `overlay-requires` | whether the overlay this machine records requires a drybag the running one satisfies — red when this project keeps its notes in that overlay, a warning when it does not — and, where that finds nothing, a warning when another repository's work tree holds the overlay root (a `.git` in a directory above it), naming that directory, since that repository can put files into the overlay | the overlay's `drybag-overlay.toml`, `drybag.toml`, the directories above the overlay root |
| `sync` | whether the [note sync](#note-sync) can run here and what its last job left: a skip while the machine file does not say `[sync] enabled = true`, naming the file and the key; a warning when it is on and the machine records no overlay (or one that is not a directory), when `git` is older than 2.43 (the job does nothing), when no `gitleaks` is on `PATH` (nothing is then committed or pushed; `setup --overlay` switches the sync on without installing one, and the job fails closed), when a hold stands (the paths or commits, and the review command, which names the recorded sha only when it is a whole one), when the record of the job cannot be read, or when the last outcome is anything but `ok`, with the outcome and the first line of its detail: for `skipped` the guard's reason and its remedy (the job acts once it is resolved, and the next session event runs it), for a failure a rerun meets again (`conflict`, `auth_failed`, `hook_failed`, `scan_unavailable`, `signing_failed`, `secret_found`, `waiting_clean_tree`) that it does until you act on what the line says, for any other that a later session event retries, and for `raced` beside an `index.lock` older than a whole job runs (the path `git rev-parse --git-path index.lock` gives, so a linked worktree's too), that lock and to remove it if no git is running; green for `ok`, with the time of the last job. A record made for another overlay reads as never run | the machine file, `git version`, `PATH`, `~/.local/share/drybag/sync/state.json` |

**How `attached` reads the delivery.** With no ledger, a repository whose `memory.mode` is not
`overlay` is simply not attached, and the row is green. Once this machine's binding confirms the
ledger, the row reads what `attach` left: the render under `~/.local/share/drybag/delivery/<id>/`,
named only by the binding id's first eight characters, and the paths `attach` placed in the main
checkout, beside the ledger every checkout reads. Every state is read, and the first red one answers,
else the first warning; the row's detail says the delivery's state beside the pointer's, its status
is the worse of the two, and the worse one's remedy comes first. The overlay's digest is computed with the launcher the render holds, so a report
run through another launcher than `attach` was reads no drift for that alone, and the digest refuses
nothing.

| State | What the row finds | Status | Remedy |
|---|---|---|---|
| in place | everything below holds | `ok` | — |
| overlay gone | the overlay root this machine records is not there, so the delivered hooks that run its scripts have nothing to run | `red` | move the overlay back, or record where it is now, then `attach` |
| placed path tracked | the index tracks a path `attach` placed for this machine alone | `red` | `git rm --cached`, then `attach` |
| placed path shown | git would not ignore a path `attach` placed: a tracked `.gitignore` re-includes it with `!` | `red` | take that line out, then `attach` |
| delivery named in a tracked file | a tracked file holds `drybag-delivery-<id>`, the delivery's name and with it the binding id, which never leaves this machine; asked for the whole name, never the prefix | `red` | take the name out before it is pushed |
| render gone | the render directory is gone, so nothing of the overlay loads and nothing else says so | `red` | `attach`, which renders it again |
| marketplace gone | the render has no `.claude-plugin/marketplace.json`, so its plugin does not load | `red` | `attach`, which renders it again |
| placed paths unasked | git could not say whether the placed paths are tracked or ignored, or whether a tracked file names the delivery | `warn` | `doctor` again where `git ls-files`, `git check-ignore` and `git grep` work |
| not installed | the ledger records no install of the plugin | `warn` | `attach`, which installs it |
| launcher gone | the launcher the path-scoped rules' entry runs through is not there | `warn` | `attach` from the drybag you run now |
| drift | the overlay's hooks, skills or agents changed since the last render | `warn` | `attach`, which renders the overlay as it is now |
| overlay unreadable | the overlay's executable parts could not be read | `warn` | `attach --check`, which says why |
| `origin` moved | this checkout's `origin` is not the one the binding was recorded with | `warn` | `attach`, which records the new one |
| tags unresolved | two of the project's `tags` hold one rule, skill, agent, Codex rule file or setting a tag may set (the later tag wins), a listed tag is not a usable name, is not a string, or has no `groups/<tag>/` directory (each said once, however often it is listed), or a directory of the project's `memory/` starts with `tag-` (the composed store links none); said after the other warnings, and a record that cannot be read answers with its own fault | `warn` | in the overlay, fix each tag, record or directory a note names; for a name two tags hold, rename one of them or reorder `tags` in the project's `project.toml` |

**How `attached` reads the memory pointer.** Where `memory.mode` is `overlay`, the row reads
`autoMemoryDirectory` in the main checkout's `.claude/settings.local.json`, which Claude Code reads
from every worktree, and compares it with the composed store `~/.local/share/drybag/stores/<id>/`
of this checkout's binding id, the one value `attach` writes there. The value is never printed.
Which `autoMemoryDirectory` is in effect where a committed `.claude/settings.json` sets one too is
the harness's to decide, and this row does not read that file.

| State | What the main checkout's settings file holds | Status | Remedy |
|---|---|---|---|
| in place | `autoMemoryDirectory` naming the composed store, which is there | `ok` | — |
| store gone | `autoMemoryDirectory` naming the composed store, which is gone, so the harness reads no memory | `red` | `attach`, which builds it again |
| link dangles | `autoMemoryDirectory` naming the composed store, one of whose links names a place that is not there (the overlay moved, and no `attach` followed), so the harness reads none of the notes behind it | `warn` | `attach`, which links it again |
| elsewhere | `autoMemoryDirectory` naming anything else | `red` | remove the key from that file, then `attach` |
| missing | no `autoMemoryDirectory` | `warn` | `attach`, which writes it |
| unreadable | a file that cannot be read as one JSON object | `warn` | make it one JSON object, then `attach` |

**Eight of the fourteen have a `skip` arm — eighteen arms between them, every one on a state of
this machine or this repository.** A `skip` is **not** a finding and never reaches the exit code, so
read the detail — each one says which measurement it is missing. No row skips for want of a build
that can answer it: `codex-hooks`, the one that did, left the report, and what holds on Codex is the
README's reach table.

The eight that skip on a state are `wrapper`, when there is no plugin root this process can
vouch for; `attached`, when this machine records no overlay to check the ledger
against, or the overlay could not be asked at all; `pre-commit` and `overlay-requires`, when
no overlay root is recorded on this machine **or** when the root it records is not a directory
— two different arms with two different sentences, because a machine that recorded an overlay
and then moved it is not a machine that recorded none; `attached`, `pre-commit` and
`overlay-requires` again, each in a sentence of its own, when the machine file does not load, so
whether it records an overlay is not known, which is neither of those; `overlay-requires` again
when the overlay declares no drybag requirement and no other repository's work tree holds it;
`bundles`, when the note store does not resolve; `diagnostics`, when no harness data root is set in the environment, which is every
`drybag doctor` run from a terminal rather than from a hook; and `sync`, when the machine file
does not switch the note sync on.
And three rows read the project configuration and skip, in one sentence, when there is none to
read — no `drybag.toml`, or one a session drops whole: `budgets`, `attached` and `bundles`. `memory` reads the resolution a session reads and answers without one. A checkout this
machine binds whose main checkout has no `drybag.toml` is the one exception for `attached` and
for the note store `memory` reads: both are judged on the configuration `attach` acted on there,
the preset's under the overlay's layers for the project the binding record names.

**A `skip` does not mean there is nothing to do.** Six of the eighteen arms carry a remedy:
the plugin-root skip, `wrapper`'s named-root skip, `attached`'s no-overlay and
could-not-be-asked arms, and the moved-overlay arm of `pre-commit` and of `overlay-requires`. The dividing line is not "always"
versus "on a state" — every other arm skips on a state and carries nothing: `bundles`,
`diagnostics` and `sync`, the *no overlay recorded* arms of the two overlay
rows, `overlay-requires`' no-requirement arm, and the
three with no project configuration, whose remedy is
`not-initialised`'s, and the three on a machine file that does not load, whose remedy is
`preferences`', red on the same file. Nor
is it whether another row names a command that changes the state: `pre-commit`'s arm carries
nothing though `attached` names `drybag setup --overlay` there. It is whether the skip is
itself worth acting on. Those six report something wrong that no other
row will tell you: a plugin root nothing can find, a root that will be read and never executed,
a recorded attach the overlay could not confirm, an overlay root recorded and not there. Of the
other twelve, nine report a measurement that is simply unavailable — no store, no overlay,
no overlay requirement, no harness data root, a note sync that is off or no project
configuration — and no command in that row's gift changes it, and three report a machine
file another row is red about, with the command that clears it.

**The one to read first is the plugin root**, because it is the quietest and the worst. When
this process can find no plugin root at all, `wrapper` skips — no red, and every hook entry on
this machine silent. It carries a remedy: run `drybag doctor` from the plugin's own launcher,
so its root answers for itself, or set `CLAUDE_PLUGIN_ROOT` to where the plugin is installed,
which lets `wrapper` read the wrapper's executable bit even though it still will not run it.

**Nothing configured is not broken.** `doctor` reads the configuration the way a session does
([`drybag hook <event>`](#drybag-hook-event)), so every row is asked whatever `--root`
holds. With no `drybag.toml`, `not-initialised` **warns**, the three rows above that read the
project configuration skip, and no row is red for it: a default install, where the guards and
this report already work, exits `0`. In a checkout this machine binds, `not-initialised` is **ok**
instead and says the configuration comes from the overlay's layers, with no remedy, since no file is
what that checkout lacks. A `drybag.toml` that loads with settings ignored or put
back to the preset's warns, naming at most three of their keys and counting the rest. Only one a session drops whole is **red**: a
symbolic link, whatever it points at, a file that is not UTF-8, cannot be read or is not TOML, or
one holding a key nothing can stand in for; the row says which in the session's own words and
names `drybag docs check`, which prints the loader's own message.

**What is printed, and what is not. There is one exception, and it is bounded.** Counts,
statuses, file paths this project chose and drybag's own vocabulary print freely; a
repository-authored string does not. `[drybag] version`, a note's filename, every
field of the hook sink's diagnostics log and the reason the store would not resolve are all read
and none is quoted back — `drybag doctor
--json` is relayed to a model verbatim by the `doctor` skill, so a byte a repository wrote reaching
this report is a byte reaching the model outside `trust.wrap`. The exception is the name of a
`drybag.toml` key that `not-initialised` says was ignored or put back to the preset's, which is
what the owner needs to find it: at most three names, one outside the path grammar withheld and
one inside it clipped at 120 characters, then a count of the rest, so the row stays short however
many keys the file holds and however long their names are.

`diagnostics` follows the same ruling, and is why that row counts rather than quotes. Its three
fields are drybag's own vocabulary *for a log drybag wrote*, and the log is found through
`${CLAUDE_PLUGIN_DATA}` — the same environment class a committed `env` block reaches — so this
command never establishes that. The row reports how many records are logged and how many sessions were
seen, and the remedy names the file by its variable; you open it yourself. A record is a hook
failure, an answer the output cap cut, or a session that ran without some of its configuration
(`config-fallback`), and the count does not tell them apart: which one a line is lies in its
`error` field, the very field this row does not trust.

**A plugin root the environment named is read and never run.** `wrapper` launches
`hooks/run-hook.sh` only under the root this drybag derived from its own module path. With a
wheel installation there is no such root — which is what `uv tool install` gives, and what
`cli-path`'s own remedy suggests — and `CLAUDE_PLUGIN_ROOT` or `PLUGIN_ROOT` may then name one:
that root's wrapper is still read by `wrapper`, for its executable bit, red without it and
otherwise a `skip` saying why. A report that ran a script the inspected repository could commit, and then
called the result green, would be worse than one that says it could not vouch for it.

**Writes** nothing. Exits `0`, or `1` when any check is red.

---

## Shared flags

Six flags mean the same thing wherever they appear, and each has exactly one sentence. Both
tables below are held to `drybag.command`'s own constants, row by row, by
`tests/test_documents.py` — so a sentence cannot be spelled by hand here any more than it can be
in a parser, which is the whole point of the rule.

| Flag | What it means |
|---|---|
| `--root` | project root (default: current directory) |
| `--machine` | machine configuration file to read |
| `--store` | resolve the memory store at this path |
| `--dry-run` | report what would change and write nothing |
| `--home` | the home directory to read and write under (default: the real one) |
| `--check` | report drift instead of writing, and fail if there is any |

`--check` is the CI half of `--dry-run`: both read and write nothing, and `--check` fails when
anything differs. `drybag docs trail` and `drybag memory index` both
take it with that meaning.

Three commands mean something else by a shared name, `setup` by two. Each of the four is a
**named exception** — a decision that the flag means something else, not a sentence that drifted —
and each has its own constant beside the six above:

| Command and flag | What it means there |
|---|---|
| `drybag overlay upgrade --root` | the overlay root (default: current directory) |
| `drybag setup --root` | the repository --git-hooks installs into (default: .) |
| `drybag setup --machine` | the machine configuration file to write (default: ~/.config/drybag/config.toml, the file every reader reads) |
| `drybag attach --check` | report the binding and the diff, and write nothing |

`attach --check` reports the way the three `--check`s above do and exits differently on purpose: never on a
non-empty diff. A diff carrying allow rules is the ordinary state of a first attach, which
`attach` shows and proceeds with. A `--check` that failed on it would make reading the diff first a
failure.

Every command that reads a project's configuration takes `--root` and `--machine`, with the
meanings in the first table, whether or not its heading spells them.
Neither flag is taken by `drybag commit strip` and `drybag hook`,
because none of them reads a project's configuration: the first reads the message file it is
handed and your own `~/.claude/settings.json`, and `hook` finds the project from the harness's own
event.
`overlay upgrade` takes `--root` alone, in the sense the second table gives it, and reads no
`drybag.toml`; `setup` takes both, in its own senses. `tests/test_documents.py` holds both
lists to the real parser.

---

## Terms

**Scaffold** means the scaffold engine, which plans and writes the overlay's files and reports
every action in the same verbs, `drybag overlay upgrade`'s included.

---

## Configuration

`drybag.toml` in the project root, committed. Every value is repository-controlled, which is
why so few of them are trusted with anything.

```toml
[drybag]
version = "0.7.1"        # required; there is no default
preset = "recommended"

[project]
name = "widget"          # one lowercase path segment
base_branch = "main"

[paths]                  # each inside the root, out of .git and .drybag, 1024 characters at most
agents_md = "AGENTS.md"
specs = "docs/specs"
plans = "docs/plans"
roadmap = "docs/roadmap.md"
memory = "docs/memory"

[memory]
mode = "harness"         # harness | overlay | in-repo | local-only — default: harness
groups = ["developer", "project-stable", "project-volatile", "specs"]
index_extra = []         # extra pointers rendered into MEMORY.md

[budgets]                # the base branch raises or lowers any budget, the machine file a session's
agents_md_lines = 300
agents_md_words = 3000
status_lines = 50
roadmap_prose_lines = 350
roadmap_prose_words = 3500
memory_index_words = 1200
startup_rules_words = 1600
volatile_notes_words = 2500
volatile_ttl_days = 30

[commit_messages]
attribution_check = false # whether `commit check` enforces the attribution block

[guards]
bg_cleanup = true        # false switches the bg-cleanup session guard off by default here;
                         # the overlay's files and the machine file override it
```

**Eight sections, and the list is closed**: a section this block does not show is refused when
the file loads (`unknown section(s)`), so the grammar above is the whole of it.
`[commit_messages] attribution_check` is read by `commit check`. `[guards]` is the guards' default
for a session in this repository, which the overlay's files and the machine file override (below);
no command reads it.

**Commands refuse; a session reads what it can.** Every command that loads `drybag.toml`, but
`doctor` and `memory session-context`, refuses it whole over an unknown section or key, a value it
cannot use or a `[paths]` value that leaves the root, naming the key and never the value. Those
two read it the way a session does: an unknown section or key is ignored, a value that cannot be
used is put back to the preset's, one key at a time, and each says so in a note naming the key, so a file a newer drybag wrote keeps every setting
this one understands. A repository's `[personal]` is the machine owner's to set and is ignored
the same way, with a note. A session drops the project configuration whole
only for a file it cannot read as TOML — a symbolic link, one that is not UTF-8, one it cannot
read, or one that is not TOML — and for a key nothing can stand in for: a key that has no default
(`[drybag] version`, `[project] name`) and is missing or cannot be used, or whose section is not
a table, or a key whose preset value does not hold in this repository either, such as a `[paths]`
default under a committed symbolic link. It then names that key rather than calling a key the file holds missing, and runs
the guards on the preset and the machine owner's layer ([`drybag hook
<event>`](#drybag-hook-event)).

Every value above is what a key you leave out takes, from the `recommended` preset — with two
exceptions. `[drybag] version` and `[project] name` have no default at all and are yours to
write: a file without `version` does not load at all (`[drybag] is missing required key(s):
version`). Everything else from `[project] base_branch` down is the preset's default exactly as written. `[project]
base_branch` is a branch name git accepts, from letters, digits, `.`, `_`, `-` and `/` (the
grammar `--base-branch` follows); anything else does not load, and the refusal names the key and
never the value.

**Which command reads which path.** `agents_md` and `roadmap` are the two documents `docs check`
budgets, and the roadmap is also what `docs trail` writes into; `specs` and `plans` are the two
trees `docs trail` lists, and `plans` is where `plan check` looks for the plans a diff touched.
`memory` is the note store.

**`[budgets]`.** The first five are the documentation budgets `docs check` enforces:
`agents_md_lines`, `agents_md_words` and `status_lines` over the always-loaded document and its
`## Current status` section, `roadmap_prose_lines` and `roadmap_prose_words` over the roadmap
above its trail marker. The last four bound the memory store. The base branch and the machine
owner raise or lower a budget — the base branch's `drybag.toml` any of the nine, the machine
file a session's four — and the value set is the value in force.

`~/.config/drybag/config.toml` is yours, not the project's:

```toml
[personal]
preset = "recommended"   # the preset `setup` applies

[overlay]
root = "~/drybag-overlay"   # only read in overlay mode

[guards]
bg_cleanup = true        # false switches the bg-cleanup session guard off on this machine,
                         # whatever a repository's drybag.toml sets

[budgets]                # the session's budgets only, which win over a project's
memory_index_words = 1200
startup_rules_words = 1600
volatile_notes_words = 2500
volatile_ttl_days = 30
```

`[guards]` here is the last word on a session guard, and it is yours: a repository's
`drybag.toml` sets the default, the overlay's files move it, and this file wins over both.
`[budgets]` here holds only the four budgets that bound
what a session loads; the five a gate judges a pull request by (`agents_md_lines`,
`agents_md_words`, `status_lines`, `roadmap_prose_lines`, `roadmap_prose_words`) are the
repository's alone: one written here is ignored, with a note. Every key you leave out is the
preset's. A command that loads `drybag.toml` reads this file's `[personal]`, `[guards]` and
`[budgets]` too, as a session reads them, so `memory index` and `memory inventory`
measure the session budgets a session runs on. What you write here is honoured, and what this
drybag cannot use is said and never refused: a key in those three tables it does not know, a
value it cannot use or a table that is not one costs that key or table alone — an unknown key is
ignored, an unusable value is put back to the preset's — and a command says so on stderr, once
however many documents it loads, naming the file and the key, while a session says so once, when
it starts. So a key a later release's
`setup` writes stops no older command on the machine. Only a file that does not load at all is
refused by a command, as `[overlay] root`'s reader refuses it, before the command reads anything
else, and leaves a session on the preset's personal values and guards, with one warning naming
this file when the session starts and `drybag doctor`'s `preferences` row red.
With no `drybag.toml` in the repository a session still reads this file: `bg_cleanup = false`
turns the guard off there too.

Between the repository's file and this one, a session reads the overlay's two, under the overlay
`[overlay] root` names: `<overlay>/common/drybag.toml` for every checkout, and
`<overlay>/projects/<name>/drybag.toml` for a checkout this machine binds to `<name>` — by the
binding id `drybag attach` records, never by the repository's own `[project] name`, so a clone
that names one of your projects gets the common file alone. Each may set a `[personal]` value, a
`[guards]` switch, a preference (`[memory] mode`, `groups` and `index_extra`) and a session
budget; the project file wins over the common one, and this file over
both. They are read the way a session reads `drybag.toml`: an unknown name is ignored, and a
value this drybag cannot use is left out so the layer beneath applies; a gate's input or a fact
about the repository written there is never taken from it. A missing file, an overlay this file
does not record, or this file not loading sets nothing. A session, `doctor`, `memory
session-context`, `attach`, `attach --check`, `detach` and the other `memory` commands read them
all through the same resolution, so what decides the store `attach` builds is what a session asks
for; every other command reads the repository's file and this one, and `doctor`'s `preferences`
row names the layer each value came from.

To state a language preference, write a personal standing rule, a note with `metadata.startup`
in your overlay's `common/memory/`.

`drybag setup` writes one more table, `[machine]`, into the same file — `version`, the
drybag that ran, and `installed`, the date it ran. It is `setup`'s record of what it did, not
a setting: it is written, never hand-edited, and a file that has never had one loads fine.
`--overlay` writes `[sync] enabled = true` beside `[overlay] root` when it renders or creates an
overlay, and nothing under `[sync]` when it records an existing one; the key is yours to change
by hand, and a repository's `drybag.toml` cannot set it ([Note sync](#note-sync)).

**This file's location is not selectable by a repository.** The path is
`~/.config/drybag/config.toml`, and neither `DRYBAG_CONFIG` nor `XDG_CONFIG_HOME` changes
it: a committed `.claude/settings.json` `env` block would otherwise choose your overlay root
and your trust record. Pass `--machine <path>` to read a different file — a path you typed
rather than one an environment chose, and honoured by every reader of it.

**`~` here is `HOME`**, as the harness and every other program read it, so a devcontainer, a
home-manager setup or a scratch `HOME` keeps drybag and the harness under one home; a `~` in
`[overlay] root` means that home too. An environment that sets `HOME` already runs code as you.
An empty or relative `HOME` names no home, so `setup`, `attach` and `detach` stop there and
`doctor` says so; `doctor`'s `ignored-env` row says, as information, when `HOME` is not the home
the password database records.

Only `[overlay]` and the trust record used to be held to that rule while `[personal]` followed
the environment, so one command could read the two halves of this file from two different files.
