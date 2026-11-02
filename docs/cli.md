# Command reference

Every command, what it reads, what it writes, and what each exit code means. `stayfixed --help`
gives you the one-line version; this is the rest.

Three things hold everywhere:

- **`--json` is accepted anywhere before `--`** and prints one machine-readable object instead of
  one line. It is not declared per command — the frame strips it from `argv` before parsing. The
  words after a bare `--` are a command's own and are never read for it: `stayfixed prove --
  COMMAND --json` hands `--json` to `COMMAND` and prints the line. A command
  whose result is a list of findings carries it under **`findings`**, named after what the
  values are and spelled the same way by every command, whatever its summary line calls them.
  Four commands do: `bugs check`, `docs check`, `memory refs` and `plan check`. Every other
  command's keys are its own and are listed with it below — `doctor`'s `checks`, `memory refs`'s
  advisory `notices`, `docs trail`'s `undeclared`, and the two of `docs trail`'s keys that are
  not lists at all, `written` and `stale`. `--json` escapes every non-ASCII character as
  `\uXXXX`, and a name git or the disk gave in bytes that are not UTF-8 appears as one lone
  surrogate escape per byte (`\udcXX`), which a strict JSON reader may refuse.
- **Exit codes**: `0` success, `1` findings, `2` a refusal or an internal error. A caller that
  treats `1` as "proceed anyway" must still never treat `2` that way — a refusal is a boundary,
  not a low-confidence result. Every command that reads `stayfixed.toml` refuses one that is a
  symbolic link, whatever it points at, before reading anything through it: a link to
  `/dev/zero` would otherwise be read until memory ran out. The refusal exits `2`, except in three
  commands that read the file the way a session does: `stayfixed hook` runs on with no project
  configuration and warns once when the session starts (see [its section](#stayfixed-hook-event)),
  `stayfixed memory session-context` prints nothing, and `stayfixed doctor` reports it as a
  `stayfixed.toml` that does not load, a red row, exit `1`.
- **Every `memory` command takes the same three options**, described once here rather than seven
  times below. `--root` and `--machine` are not memory's alone: [Shared flags](#shared-flags) says
  which commands take them, and in which sense.

| Option | Meaning |
|---|---|
| `--root PATH` | The project root. Default: the current directory. |
| `--store PATH` | Resolve the note store at this path instead of where the configuration says. An override of *where the notes are*, not of the rules about them: the same containment checks apply. In overlay mode it is not read: the store is the composed store the binding names, so no directory a repository chose stands in for it. |
| `--machine PATH` | Read this machine configuration file instead of `~/.config/stayfixed/config.toml`. Mostly for tests and for running against a second machine profile; it also decides which `trust.json` is consulted. |
## Contents

- [`stayfixed memory index`](#stayfixed-memory-index)
- [`stayfixed trust list [--root PATH] [--machine PATH]`](#stayfixed-trust-list---root-path---machine-path)
- [`stayfixed trust revoke KIND --subject KEY [--root PATH] [--machine PATH]`](#stayfixed-trust-revoke-kind---subject-key---root-path---machine-path)
- [`stayfixed memory session-context --bundle <name> [--part N]`](#stayfixed-memory-session-context---bundle-name---part-n)
- [`stayfixed memory inventory`](#stayfixed-memory-inventory)
- [`stayfixed memory fit`](#stayfixed-memory-fit)
- [`stayfixed memory promote NOTE… | --changed`](#stayfixed-memory-promote-note----changed)
- [`stayfixed hook <event>`](#stayfixed-hook-event)
- [Hooks](#hooks)
- [`stayfixed commit check --range RANGE`](#stayfixed-commit-check---range-range)
- [`stayfixed commit strip FILE`](#stayfixed-commit-strip-file)
- [`stayfixed test hygiene`](#stayfixed-test-hygiene)
- [`stayfixed test attribute --command CMD [--base REF]`](#stayfixed-test-attribute---command-cmd---base-ref)
- [`stayfixed prove [--timeout SECONDS] [--junit PATH] -- COMMAND …`](#stayfixed-prove---timeout-seconds---junit-path----command-)
- [`stayfixed bugs new TITLE --severity S --area A [--source S] [--related ID …] [--no-fetch]`](#stayfixed-bugs-new-title---severity-s---area-a---source-s---related-id----no-fetch)
- [`stayfixed bugs index [--check]`](#stayfixed-bugs-index---check)
- [`stayfixed bugs check [--base REF]`](#stayfixed-bugs-check---base-ref)
- [`stayfixed bugs regressions`](#stayfixed-bugs-regressions)
- [`stayfixed bugs renumber OLD NEW`](#stayfixed-bugs-renumber-old-new)
- [`stayfixed docs check [--budgets] [--links]`](#stayfixed-docs-check---budgets---links)
- [`stayfixed docs trail [--check]`](#stayfixed-docs-trail---check)
- [`stayfixed plan check [--base REF] [PATH …]`](#stayfixed-plan-check---base-ref-path-)
- [`stayfixed assess [--base REF] [--builtin] [--root PATH] [--machine PATH]`](#stayfixed-assess---base-ref---builtin---root-path---machine-path)
- [`stayfixed gate [--only NAME]… [--base REF | --pr-base=BRANCH --base-input=BRANCH --default-branch=BRANCH] [--path=PATH] [--builtin | --custom] [--workflow-sha SHA] [--annotate] [--summary FILE] [--root PATH] [--machine PATH]`](#stayfixed-gate---only-name---base-ref----pr-basebranch---base-inputbranch---default-branchbranch---pathpath---builtin----custom---workflow-sha-sha---annotate---summary-file---root-path---machine-path)
- [`stayfixed adopt promote [GATE …] [--base REF] [--builtin] [--root PATH] [--machine PATH]`](#stayfixed-adopt-promote-gate----base-ref---builtin---root-path---machine-path)
- [`stayfixed memory refs`](#stayfixed-memory-refs)
- [`stayfixed init --yes [--dry-run] [--name NAME] [--base-branch BRANCH] [--agent NAME …] [--profile NAME] [--memory-mode MODE] [--attribution-check] [--commit-type TYPE …] [--local ID …] [--no-ci] [--root PATH] [--machine PATH]`](#stayfixed-init---yes---dry-run---name-name---base-branch-branch---agent-name----profile-name---memory-mode-mode---attribution-check---commit-type-type----local-id----no-ci---root-path---machine-path)
- [`stayfixed init --questions [--root PATH] [--machine PATH]`](#stayfixed-init---questions---root-path---machine-path)
- [`stayfixed upgrade [--dry-run] [--force PATH]… [--root PATH] [--machine PATH]`](#stayfixed-upgrade---dry-run---force-path---root-path---machine-path)
- [`stayfixed uninstall [--dry-run] [--force PATH]… [--root PATH] [--machine PATH]`](#stayfixed-uninstall---dry-run---force-path---root-path---machine-path)
- [`stayfixed overlay upgrade [--root PATH] [--dry-run]`](#stayfixed-overlay-upgrade---root-path---dry-run)
- [`stayfixed attach [--store PATH] [--project NAME] [--check] [--root PATH] [--machine PATH]`](#stayfixed-attach---store-path---project-name---check---root-path---machine-path)
- [`stayfixed detach [--root PATH] [--machine PATH]`](#stayfixed-detach---root-path---machine-path)
- [`stayfixed setup [--preset NAME] [--plugin NAME …] [--home PATH] [--machine PATH] [--overlay VALUE]`](#stayfixed-setup---preset-name---plugin-name----home-path---machine-path---overlay-value)
- [`stayfixed setup --git-hooks [--uninstall] [--root PATH]`](#stayfixed-setup---git-hooks---uninstall---root-path)
- [`stayfixed setup --approval-boundary [--home PATH] [--machine PATH]`](#stayfixed-setup---approval-boundary---home-path---machine-path)
- [`stayfixed doctor [--json] [--root PATH] [--home PATH] [--machine PATH]`](#stayfixed-doctor---json---root-path---home-path---machine-path)
- [The reusable workflow](#the-reusable-workflow)
- [Shared flags](#shared-flags)
- [Terms](#terms)
- [Configuration](#configuration)

---

## `stayfixed memory index`

Render `MEMORY.md` from the notes. The index is a rendering: no note is written but one whose line
the native writer appended to `MEMORY.md`, which is harvested into it.

```bash
stayfixed memory index            # write
stayfixed memory index --check    # report drift, write nothing
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
   read (step 4), so the render's own lines are never read back into a note. A note written so is unreviewed until promoted again
   ([`memory promote`](#stayfixed-memory-promote-note----changed)).
3. **Renders what is missing.** A note with none of these is rendered with its `description`, and
   is not written. A line an earlier release wrote into a note as `index_provenance: provisional`
   is read as no line, so the note's line follows its description again.
4. **Renders.** One section per configured group, a note's `group:` value as a sub-heading
   inside it, ordered by `startup` rank first, then by `group_order`, then by name — so a
   note ranked for the session leads its section whatever its position within a sub-heading.
   The harness's own memory writer keeps its notes as topic files at the top of the store,
   outside every group, each named by one `- [title](file.md)` line in `MEMORY.md`: every such
   line whose file the store still holds is kept, verbatim and once, and the topic files are never
   written. The render sits between two marker lines, `<!-- stayfixed:index -->` and
   `<!-- stayfixed:index:end -->`; the native writer's pointer lines stand after it, where that
   writer appends, and a `MEMORY.md` with no markers is read whole as lines outside the region. In
   a composed store's own `MEMORY.md` under `~/.local/share/stayfixed/stores/`, a note you have not
   promoted at the bytes it holds now
   ([`memory promote`](#stayfixed-memory-promote-note----changed)) has its line end in
   `[unreviewed]`, as the bundles label it; the label follows this machine's record, so it is never
   written into an index a repository commits or the overlay shares.

`--json`'s `provisional` lists the notes rendered by step 1 or step 3, the ones whose line a
curated `index:` would replace.

`--check` exits `1` when the index has drifted, when it is over its word budget, when it is past
the harness's line or byte caps, or when a file in the store cannot be parsed as a note — one
whose name is not UTF-8 on disk included, since the index names every note by its file's name.
Such a file is named by its path inside the store, on the line and in `--json`'s `unreadable`
alike, as `memory refs` names it. Every list of names on the line names up to eight and says
how many more there are; `--json` carries every one.
The same findings are printed on the write path too — they just do not fail it, because `--check`
is the mode that fails a build.

Exits `2` if `MEMORY.md` is a symlink this store may not follow (the target rule: outside
overlay mode a symlinked index is refused outright; in overlay mode only a link into *this*
project's own share of the recorded overlay is honoured).

**A checkout with no `stayfixed.toml` that this machine binds** reads the memory a repository with
the file reads: every `memory` command, the bundles and `doctor`'s note-store rows use the preset's
configuration under the overlay's layers (`common/`, the project's tags, `projects/<name>/`), for
the project this machine's binding record names, which is how a public clone you cannot commit to
gets its notes. A checkout nothing on this machine binds is still refused (`1`) with `stayfixed
init` as the way out, and the bundles print nothing for it. A `stayfixed.toml` is read first when
there is one.

**One store in overlay mode.** There the store is the composed store `stayfixed attach` builds,
`~/.local/share/stayfixed/stores/<id>/`, named by the checkout's binding id and holding one link per
group into the overlay, and `--store` is not read. In every other mode `--store` is resolved at the
path it names, under the same rules as the configured store. The groups include the notes of each tag
the project lists, as `tag-<tag>` (`groups/<tag>/memory/` in the overlay), which every `memory`
command, the index and the bundles read after the common notes and in the order the project lists
its tags, whether or not `memory.groups` names them. A note's review is
recorded by its path, so renaming a tag, which moves its notes' path in the store, makes them
unreviewed once.

**When there is no store, the refusal says why** (exit `1`). An overlay root the machine
configuration records that is not a directory on this machine — the overlay moved, or was never
cloned here — is said first, with the root named in stayfixed's own sentence (it is your
machine configuration's, not the repository's) and `stayfixed setup --preset NAME
--overlay PATH` as the way out, since `attach` refuses a store outside the recorded root. A
checkout this machine does not bind to the project — no binding id in its git common directory, or
none this machine records for that project — is said in stayfixed's own words before the region
that carries the repository's, with `stayfixed attach` as the way out. The checkout's `origin`
plays no part in it.

## `stayfixed trust list [--root PATH] [--machine PATH]`

Every approval recorded on the machine, one line each with its kind, its subject and when it was
approved. It names each subject — for `reviewed`, the resolved absolute path the note was
promoted at, a label only, since its digest is what is matched — escaped where it leaves the path grammar and, past 120 characters, by its start and
its length; a subject under `HOME` is named from `~/`. `--json` carries every subject whole.

One command records an approval in this release: [`stayfixed memory
promote`](#stayfixed-memory-promote-note----changed), of kind `reviewed`, one per note.

`--json` keys: `approvals`, one object per approval with its `kind`, `subject`, `digest` and
`approved_at`.

**The record** is the machine's one record of approvals, of every kind. It is versioned: a JSON
object holding `version` (`1`) and `approvals`, each with its `kind`, `subject`, `digest` and
`approved_at`. Every write replaces the whole file in one atomic step, and no lock is taken: two
commands writing at once each replace it whole, the last one wins, and neither leaves it torn.

**What an approval holds against.** Repository bytes: stayfixed never writes `trust.json` from
what a repository holds, and a clone, a pull or a pull request does not reach it, since it lies
under `HOME` and outside every repository. A repository whose hooks your harness runs — a committed
`.claude/settings.json` hook in a folder you trusted — is code running as you, and can write any
file you can, this one included. Not the session's own agent: an agent whose shell can write any
file you can may write the record as well, and stayfixed neither stops nor checks that. That
boundary is the harness's sandbox, which is yours to set; `stayfixed setup --approval-boundary`
prints what to set under Claude Code. Even a sandbox that keeps the record out of reach leaves an
agent a way to instruct the next session: Claude Code's documentation does not list a project's
`CLAUDE.md` or `AGENTS.md` among the paths its sandbox keeps from the agent's own writes, and Claude
Code loads the first as instructions and can load the second, through an import or its project
instructions setting (read in the documentation, not measured). [SECURITY.md](../SECURITY.md)
lists an agent with an unsandboxed shell as out of scope.

Exits `2` if `trust.json` exists and is not a record this stayfixed reads — not JSON, not UTF-8, a
later version, no `version`, a `version` that is neither `1` nor later (`0`, `"1"`, `true`), or a
version-1 record that is not whole: a key besides `version` and `approvals`, an approval that is not
an object of four text fields, or one approval named twice. Nothing will overwrite a file it
could not read: one that does not parse may hold every project's approval, so repair or delete it;
repair any other that holds approvals you want to keep, or delete it to start a new record; for a record of a later version, which a later
stayfixed wrote and is met after a downgrade, update stayfixed instead, since deleting it would
destroy that release's approvals.

**Reads** the machine's trust record.

**Writes** nothing.

## `stayfixed trust revoke KIND --subject KEY [--root PATH] [--machine PATH]`

Withdraw the approval of kind `KIND` recorded for `KEY`, as `trust list` spells the two (a subject
under `HOME` from `~/`, or whole as `--json` gives it),
and every other approval of that kind holding the same digest: a digest is what an approval is
matched on, so a note promoted from two worktrees, or a copy of it, is unreviewed once either is
revoked. It needs no terminal: withdrawing is the direction that fails safe. A revoke that matches nothing
exits `1`, writes nothing, and lists what the kind has recorded, each subject named as `trust list`
names it.

`--json` keys: `kind`, and `revoked`, every subject withdrawn; a revoke that matched nothing adds
`recorded`, every subject the kind has recorded, whole.

**Reads** the machine's trust record.

**Writes** `~/.config/stayfixed/trust.json` (or the file beside `--machine`), only when an approval
was withdrawn, through a link a dotfiles manager put there: the file the link leads to gets the
record, and the link stays. A write refused as an agent's sandbox refuses one (`EPERM` on macOS and
`EROFS` on Linux and WSL2, as Claude Code's sandboxing reference gives them) exits `2`, withdraws
nothing, and says that a person must run the command in their own terminal, outside the agent's
sandbox, and that met in their own terminal it is the directory itself refusing writes, as a
read-only mount or an immutable flag does. A directory you may not write for its mode exits `1`,
naming it.

## `stayfixed memory session-context --bundle <name> [--part N]`

Render one injection bundle. This is what a `SessionStart` hook entry invokes; you will rarely
run it by hand except to see what a session actually receives.

| Bundle | What it is |
|---|---|
| `standing-rules` | Every note flagged `startup` that you promoted at the bytes it holds now ([`memory promote`](#stayfixed-memory-promote-note----changed)), in full, ranked; an unreviewed note is never a standing rule, whatever it says about itself. Never truncated — only flagged when the set outgrows its budget, because a standing rule that does not arrive is a standing rule that gets broken. |
| `volatile-notes` | Dated, perishable notes, and every unreviewed note flagged `startup`, in full; over budget, descriptions only. An unreviewed note arrives labelled `[unreviewed]` inside a delimited region that says it is data, opened and closed with a nonce the note does not hold. |

Each bundle is emitted across numbered parts, because the harness caps each hook entry's output
independently. `--part N` selects one; a part past the end prints nothing and exits `0`. A part
that is a single block too large for one slot is withheld — the command prints a short notice
saying so instead, because the harness would otherwise truncate it and a truncated region loses
the marker that says where repository content ends. `stayfixed memory fit` names the block.

Output is deliberately **raw**, not JSON: the margin that keeps a bundle inside the platform cap
is additive only because there is no envelope and no escaping. Do not pass `--json` from a hook
entry.

Where no layer sets `[memory] mode`, memory is the coding agent's own (`harness`), there is no
store, and this command prints nothing. So it does before the store's directory exists — a
`local-only` repository before its first note — and in an overlay checkout this machine has not
bound, whose binding `doctor` reports. In an overlay checkout this machine binds whose composed
store is gone, `--bundle standing-rules` (part 1) prints one line saying so, the store named by its
short binding id, with `stayfixed attach` as the way back, and every other entry prints nothing. A configured
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

## `stayfixed memory inventory`

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

## `stayfixed memory fit`

Whether each bundle fits the numbered hook entries declared for it. Exits `1` when one does not
— either it needs more parts than there are slots, or a single block is larger than one part
and would be truncated by the platform.

**Writes** nothing.

## `stayfixed memory promote NOTE… | --changed`

Count notes as yours, at the bytes they hold now. Each `NOTE` is a note's path in the store,
`<group>/<file>.md` as `memory index` links it, or a path to the note's file; `--changed` takes
every note that is not reviewed. One or the other: both, or neither, exits `2` and records nothing,
as does a name that is no note of the store.

```bash
stayfixed memory promote developer/prefer-uv.md
stayfixed memory promote --changed    # after reading what changed
```

A note is reviewed while the sha256 of its current bytes is a `reviewed` approval in `trust.json`.
The digest alone decides, and the approval keeps the note's resolved path only as the subject
`trust list` prints: the same bytes are reviewed in every worktree, after the store moves and
under another name, and an edit — yours, an agent's, the harness's writer's — makes the note
unreviewed again and moves no other note. The record is this machine's, so another machine
promotes for itself. Only a reviewed note is a standing rule
([`session-context`](#stayfixed-memory-session-context---bundle-name---part-n)). The record lies
outside every tree, so repository bytes cannot write it; an agent whose shell can run this command
can, and against it the record is a label, not a gate ([`trust list`](#stayfixed-trust-list---root-path---machine-path)
says what the record holds against). `trust revoke reviewed --subject PATH` withdraws one.

Prints each note's path in the store and the digest recorded, one per line. `--json` keys:
`promoted`, one object per note with its `path` and `digest`.

Exits `2` if `trust.json` cannot be read, as `trust list` does, and for a write refused as an
agent's sandbox refuses one, as `trust revoke` does.

**Reads** the store's notes and the machine's trust record.

**Writes** `~/.config/stayfixed/trust.json` (or the file beside `--machine`), only when a note was
promoted, as `trust revoke` writes it.

## `stayfixed hook <event>`

Internal. Reads a hook payload on stdin, dispatches it to every handler registered for that
event, and writes the harness's expected output.

Not something to run by hand. Its exit-code policy differs from every other command: an internal
error degrades open (`0`) on every event, with the error on stderr — a bug in stayfixed must not
cost you a tool call, and on `UserPromptSubmit` an exit `2` would erase what you typed.

**A session never dies of its configuration.** The guards run in every repository, whatever
`stayfixed.toml` holds: none at all, one that does not load, and a broken machine file included;
only their switches are read, the repository's `[guards]` as a default the overlay's files and the
machine file override. A configuration is never the reason a call is refused.
The project's file is read the way [Configuration](#configuration) says a
session reads it: an unknown section or key is ignored and a value that cannot be used is put back
to the preset's, so the rest of the file still applies. The handlers about the project — the
unreviewed-notes count, the overlay status, the red-run note — say nothing when there is no project
configuration to use, which is so when there is no file, and when the file is a symbolic link
(never read, whatever it points at), is not UTF-8, cannot be read or is not TOML, or holds a key
nothing can stand in for: a required key with no default (`[stayfixed] version`, `[project]
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
counted inside the hook's output cap: that `stayfixed.toml` does not load, that one of its keys
cannot be used and nothing can stand in for it (naming the key), that it is longer than a session
reads, that it holds more settings this stayfixed cannot use than a file its length is read past,
that it loaded with some
settings ignored or put back to the preset's (counting them, and saying when a newer stayfixed
wrote it), or that the machine file, named by the path that was read, could not be used whole.
Each points at `stayfixed doctor`, and none carries the loader's own message, which carries the
repository's text; a command such as `stayfixed docs check` still refuses the file and prints that
message in full. Every other event
prints no warning, and records once per session, in the diagnostics log below, that the session
runs without some of its configuration (`config-fallback`).

**The overlay's rules.** In a checkout this machine binds to an overlay project
([`attach`](#stayfixed-attach---store-path---project-name---check---root-path---machine-path)), `SessionStart`
carries the overlay's standing rules — every `*.md` file in `claude/rules/` of `common/`, of each
tag the project lists (`groups/<tag>/`) and of `projects/<name>/` whose frontmatter has no `paths:`
key, in that order and each in name order, a later plate's file replacing the earlier plate's file of
its name —
under one fixed lead line, on every event the matcher covers, since a compacted or cleared context
has lost them. A rule with `paths:` is path-scoped: the plugin `attach` renders carries a
`PostToolUse` entry for it, matching `Read|Edit|Write`, that runs `hook PostToolUse` through
whatever launched the stayfixed that ran `attach`, by absolute paths in double quotes: from the
core plugin, its own `hooks/run-hook.sh` (below), so `-I` and exit `0` on any fault hold as for the
plugin's own entries; from an installed package, which has no plugin root, the interpreter it ran
under, as `<python> -I -m stayfixed`. That answer carries every such rule whose globs match the file the tool named, relative to the checkout's root (`*` and `?` within
one path segment, `**` across segments, `{a,b}` for alternatives), the first time a session touches
that file, and nothing after. The project is the one the machine's binding record names, never the
repository's `stayfixed.toml`, so an unbound checkout hears no rule, whatever its `memory.mode`; a
rule that cannot be read silences the rules of that hook, and `attach` refuses it. A rule's body
reaches the model as the overlay holds it; the one path printed is the touched file's, withheld
outside the path grammar.

**Writes** inside `stayfixed/` under the data root the harness names — `CLAUDE_PLUGIN_DATA`, or
Codex's `PLUGIN_DATA` — and nowhere else of its own: `.probe`, written each time it dispatches to
learn whether the root can be written at all; under `markers/`, one empty file per `once_key`
handler that delivered, and one for a `config-fallback` record, filed under a directory per
session, both names hashed to a fixed width,
with all but the newest fifty session directories removed; and `diagnostics.jsonl`, one JSON line
per diagnostic record, rotated to `diagnostics.1.jsonl` once it would pass 256 KiB. With no data
root, or a relative one, nothing is written there and a `once_key` handler is asked on every
invocation. One handler writes outside it: `overlay-path-rules`, the path-scoped rules above,
writes one empty file per session and file it said a rule for, under
`$HOME/.local/share/stayfixed/sessions/`, both names hashed to a fixed width; none for a payload
with no session id, and nothing removes them. And `unreviewed-notes`, which on `SessionStart` says
"N notes are unreviewed" when the set of the store's unreviewed notes differs from the one last
said, writes one file per store under `$HOME/.local/share/stayfixed/unreviewed/`, named by a hash
of the store's path and holding a digest of that set; nothing removes them. No handler links a memory store into a worktree:
the harness reads the composed store from every worktree through the main checkout's
`autoMemoryDirectory` (`stayfixed attach`).

## Hooks

The two harnesses do not run `stayfixed` directly. Every entry in `hooks/hooks.json` invokes
`hooks/run-hook.sh`, which hands its argv to `stayfixed` untouched:

```
run-hook.sh <stayfixed args…>
```

`hooks/hooks.json` files its entries under four events: `SessionStart`, `PreToolUse`,
`PostToolUse` and `PostToolUseFailure`, each tool event matched on `Bash`. The last is where Claude
Code delivers a `Bash` call that exited non-zero, and it carries the red-run note ([`stayfixed test
hygiene`](#stayfixed-test-hygiene)); Codex reads the same file and ignores that key (measured on
Codex CLI 0.162.0-alpha.17.2). `stayfixed hook` dispatches six events, those four and
`UserPromptSubmit` and `UserPromptExpansion`, which no shipped entry uses.

The wrapper exists because a Python process cannot speak for its own absence: a missing script
exits `2` by CPython accident, and so does a launcher run under an interpreter below stayfixed's
floor, and on `PreToolUse` Claude Code reads a `2` as a refusal of the call. So the wrapper does
three things before stayfixed runs: it unsets an inherited `GIT_DIR` and `GIT_WORK_TREE`, which
would make every `git` answer about another repository, and changes into the project root
(`CLAUDE_PROJECT_DIR`, else `git`'s toplevel) so every command's `--root` default is correct; it
then takes the `python3` on `PATH` there, where a pyenv, asdf or mise shim chooses by the project's
own pin, and asks it, by running code, to be 3.11 or newer; and it maps exit codes.

No handler refuses a call, so stayfixed's non-zero exit is always a fault. `0` passes through
untouched. Every non-zero exit, and every fault the wrapper finds before `stayfixed` runs — no
`python3` of 3.11 or newer on `PATH`, no readable `scripts/stayfixed` beside the wrapper, a project
root it cannot enter — ends in exit `0` with one line on stderr that names the fault and ends
`continuing open`: **a session never dies of stayfixed's own fault.** `stayfixed hook` exits `0` on
an internal error of its own for the same reason, so no shipped entry ever blocks a call. Claude
Code discards stderr on a `0`, so `stayfixed doctor`'s `wrapper` row runs the wrapper and goes red
on such a line. Without a usable `python3` neither `doctor` nor any hook can run, so the one entry
that dispatches `SessionStart` (`hook SessionStart`) also prints, on stdout, the hook answer Claude
Code shows the person (`systemMessage`) and adds to the model's context (`additionalContext`):
that stayfixed's hooks are off in this session, because there is no `python3` on `PATH` or the one
there (its path, each byte but an ASCII letter, a digit, a space and `/._+~-` printed as `?`) is not
Python 3.11 or newer, and to install Python 3.11 or newer on `PATH`. Every other entry, the six
memory entries on the same event included, stays silent on stdout.
A hook that runs past its ten-second `timeout`, or that cannot start at all — the wrapper missing or
not executable — never reaches the mapping, and Claude Code then carries the tool call out.

**Which `python3` and which `git` run is `PATH`'s to choose**, in a hook as at a terminal: a nix,
MacPorts or mise `git`, and a `python3` in a virtual environment, both answer. A trusted folder's
committed `env` block can set `PATH`, and it runs code in your shells by design; that boundary is
the harness's ([SECURITY.md](../SECURITY.md)).

**The interpreter starts isolated.** `-I` keeps what the interpreter imports before stayfixed's
first line to the standard library: the wrapper runs both the version probe and the launcher with
it, so no `PYTHON*` variable is read (`PYTHONPATH`, `PYTHONHOME`, `PYTHONUSERBASE`), there is no
user site, and neither the working directory nor the script's own directory is on `sys.path`. The
launcher puts the plugin's own `src` there itself, and stayfixed still sees the whole environment:
`-I` changes how the interpreter starts, not what `os.environ` holds. What the dynamic loader
injects is out of any wrapper's reach — `LD_PRELOAD` on Linux acts on the wrapper's own shell before
its first line. On macOS the wrapper's `/bin/sh` is SIP-protected and drops `DYLD_*` before
anything below it starts, which is why its shebang must stay a protected shell.

**The one row this does not cover.** A `run-hook.sh` whose executable bit has been cleared is
never executed by the harness at all, so no code of ours runs and the hooks are silent. The
wrapper cannot defend its own mode, so `stayfixed doctor` is what catches it: the `wrapper` row
goes **red** on a cleared bit, and under a root the environment named hands you the `chmod +x`. Run it after anything that rewrites the
plugin directory.

**What a session hears about the overlay it is bound to: `overlay-status`.** Beside the two that
deliver the overlay's rules (above), the `attach` area registers one `SessionStart` handler, with a
`once_key`, so it speaks **at most** once
per session: the marker is banked only when the handler had something to say, so a session that
hears a line hears it once, and a repository with nothing to report is asked again on every
`startup`, `resume`, `clear`, `compact` and `fork` the matcher above covers — and it says
nothing at all unless `[memory] mode` is `overlay`. Eight lines, each fixed and carrying at most a
count but the one that names two remotes, joined by newlines in this order: **no overlay recorded** on this machine, or one that
**could not be asked** about, which is a machine configuration file that will not parse; this
repository **not attached** to that overlay, or, for a bound one, its **`origin` moved** from
the remote its binding was recorded with — the one line that names repository bytes, both remotes,
each escaped where it is not a plain path; the `requires` of the overlay's identity record
(`stayfixed-overlay.toml`) in **a form this stayfixed cannot read**, or naming **a floor this stayfixed
does not meet**, a pre-release of the floor's version included; and — only when none of those fired — the overlay's branch having **no
upstream**, and the counts of its **unpushed commits and uncommitted changes**. A bound,
up-to-date repository on a satisfied stayfixed hears nothing. But for the moved-`origin` line, not
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
later, over an overlay the conversation may have left dirty, and an invocation stayfixed cannot
place in a context is treated as a new one rather than as one already answered. The cost is that
an overlay which becomes unpushed *during* a session that started clean is not reported at that
session's compactions, only at its next resume or startup; `stayfixed doctor` answers on demand. And the overlay is never a plugin stayfixed
executes anything from: it carries no plugin manifest and no
`hooks/hooks.json`, and hook entries the owner keeps in the `claude/hooks.json` of *common/*, of a tag and of
`projects/<name>/` reach a session only through the plugin `attach` renders from
them, named by this machine's binding id.

## `stayfixed commit check --range RANGE`

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

**Writes** nothing. `stayfixed gate`'s `commit` gate, which the reusable workflow runs, reads the
range from the base to `HEAD` through this same check.

Exit `1` has two meanings here and a gate should know both: messages were read and some carry a
trailer (`FAIL: …`), and *no `stayfixed.toml` was found under `--root`*, which the configuration
loader reports as a failure — `stayfixed: failed: …/stayfixed.toml does not exist` — and not as a
refusal. A workflow that must tell them apart reads the first word of the output, or checks the
file is there before it runs the gate.

## `stayfixed commit strip FILE`

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
hook is `stayfixed setup --git-hooks`, and removing it — restoring whatever it chained to — is
`stayfixed setup --git-hooks --uninstall`; both are documented below.
`stayfixed.guards.api.install` is the same call for a caller embedding stayfixed.

**Reads** `FILE` and `~/.claude/settings.json` under your home, and nothing a repository holds.

**Writes** `FILE`.

## `stayfixed test hygiene`

The environment faults that make a red test run unattributable: uncommitted changes in the
tree, which belong to no stack, and whatever each stack's profile knows about its own — for
Python, `.pyc` files under `[ledger] code_roots` whose recorded source mtime no longer matches
their source. Counts the uncommitted changes across the whole repository — a dirty tree
anywhere makes a red run unattributable — and asks every profile that ships a `hygiene.py`
(today, Python) for its counts. A profile is listed when its markers sit at the repository
root, and also, whether or not they do, when it has something to report: a Python project in a
subdirectory has no marker at the root and still gets its stale bytecode named. So a repository
in two stacks gets two entries whatever `[stayfixed] profile` names. The summary
names each such finding as `<profile>: <its note>`, and a clean tree reads `tree is clean`
followed by `; the <profile> profile has nothing to report` for each profile listed. When no
`[ledger] code_roots` entry names a directory a walk takes, no profile has looked at anything, so
the summary gives the uncommitted-change count, or `no uncommitted change` in place of
`tree is clean`, followed by `; no [ledger] code_roots entry names a directory here, so no code
root was walked`, with the exit the count decides; `stayfixed assess`'s `code-roots` item counts
the entries left out, and `.stayfixed/assessment.json` names each with its reason. `--json`
carries `dirty` and, under `profiles`, each listed profile's counts by its name
(`{"python": {"stale": 0, "roots": 2}}`). Exits `1` when the tree is dirty or a profile has
something to report, `2` when git cannot report the tree or a shipped profile's hint cannot be
loaded, answers in something other than text or fails; a failure is named by the profile and the
exception's type alone.

A profile's walk is bounded: Python's lists at most 500,000 directory entries under the code
roots in total, every entry and not only the bytecode, and reads at most 20,000 of the `.pyc`
files it lists. Reading a `.pyc` costs tens of times listing an entry, so each half has its own
bound; over 499,990 `.pyc` files sharing one source, the worst tree for both, the walk stopped
in under 3 s on a laptop with a warm cache, a third of the hook's 10-second timeout. A walk that
stops at either bound has not seen the tree and reports no count, stale or clean, even when the
part it saw held no Python: the command exits `2` with ``the python profile's red-run hint
stopped its walk at a bound and could not tell, so this tree cannot be judged; narrow `[ledger]
code_roots` to the directories that hold code``, which `--json` carries as its `summary` beside
`"error": "refused"`. The bounds are fixed; what they walk is not.

The `PostToolUseFailure` `Bash` hook delivers the same note once per context after a red test run:
Claude Code delivers a command that exited non-zero on that event, with `error` beginning `Exit code
N`, and an `error` that begins otherwise, or with a run of more than nine digits, which no exit code
has, gets no note. The same handler is registered on `PostToolUse` too, where no measured harness
delivers an exit code: Codex delivers a failed command there with none, so the note does not speak,
and the registration is a placeholder for parity with Codex. The two share one once-per-context key,
so a context gets at most one note, whichever event carries it. The note is chosen by the command
that failed rather than by configuration: each simple command of the red run is offered to every
shipped profile's hint, and the dirty-tree line and the line of each profile whose runner it
recognises (Python's: `pytest`, or `python -m pytest`) are delivered together. A runner is
recognised behind environment assignments, an `env` prefix and `uv run`, read as `stayfixed prove`
reads it, its bound included: the command starts at the first word a runner adapter recognises, so
a runner named before the real command (`uv run --with pytest echo`, `uv run grep -m pytest x`)
gets the note, and one named through an alias, or by a path no adapter recognises, does not. A red
command no profile recognises gets no note. When Python's walk stopped at its bound, its line says
the walk could not tell whether a stale build was imported, and names neither stale bytecode nor its
absence.

**Writes** nothing.

## `stayfixed test attribute --command CMD [--base REF]`

Run one failing command three times and say what the three exit codes mean. The three trees:

1. **The working tree as it is** — the command runs with `--root` as its directory, exactly
   where you are.
2. **`HEAD`'s committed tree** — extracted with `git archive` into a scratch directory.
3. **The merge-base with the base branch** — extracted the same way. The merge-base, not the
   base's tip: a base branch that advanced after the fork would otherwise carry commits that
   are not "before this change" into the before side.

That merge base has to be one commit. When `git merge-base --all REF HEAD` names several — a
history the change merged into from both sides of a base merge has them — each is as much
"before this change" as the others and a failure can pass on one and fail on another, so the
attribution is undetermined and the command says so, counting them and naming up to eight,
rather than extract the one git would pick alone. Merge the base into the change, which makes
its tip the one merge base, or pass `--base` naming the commit you mean. A shallow clone is
undetermined too, since the commit `HEAD` forked from can be cut off there and an older one stand
in for it, and so is a clone git cannot say is shallow or not. All of it is decided before
anything runs.

`--base` defaults to `refs/remotes/origin/<[project] base_branch>`, named in full so that no tag of
the short spelling stands in for it; pass it to compare against another ref.

**Writes** nothing, and nothing in it runs `git checkout`, `git stash` or `git reset`: the two
committed trees are extracted into a temporary directory that is removed before the command
returns, and your checkout is never moved between commits or restored from one.

**Your command is another matter, and the distinction is the whole safety property.** Run 1
executes it *in the working tree*, so whatever it writes there, it writes — the example above
leaves a lockfile, a virtual environment, `.pytest_cache` and `__pycache__` behind exactly as
running it by hand would. What this command guarantees is that it does not move your checkout
to another commit to get its "before" reading, not that the three runs leave no trace.

**The command is yours, and so is its environment.** `--command` takes the exact failing
command *including the sync it needs to be meaningful* — `uv sync --locked && uv run --locked
pytest tests/x.py::t` for a Python project, the equivalent for another stack. That sync is the
whole of what makes runs 2 and 3 comparable; a command that does not sync compares two drifted
environments and the verdict is worth nothing. It is also what makes this command the same tool
for every language.

The verdict, from runs 2 and 3 first and run 1 only when both passed:

| `HEAD` | merge-base | working tree | Verdict |
|---|---|---|---|
| fails | fails | — | `pre-existing: the failure is on the merge-base too, so it is not this change` |
| fails | passes | — | `this change: HEAD fails and the merge-base passes` |
| passes | fails | — | `this change fixed a pre-existing failure: HEAD passes and the merge-base fails` |
| passes | passes | fails | `environmental: HEAD passes when synced and fails in the working tree as it is` |
| passes | passes | passes | `not reproduced: all three runs passed` |

Five sentences, and the four `HEAD`/merge-base cases are exhaustive: there is no sixth verdict
and no fall-through. A run that **did not execute** — the launcher's wall-clock cap, or a
command it could not start at all — is a failure naming which of the three it was, never a
verdict. That matters more than it sounds: a cold sync in a fresh extraction is the likeliest
thing to hit the cap, and two timed-out runs scored as exit codes would read as "fails on
both", which is the one wrong answer a tool feeding a ledger entry must not give. Narrow the
command to the failing test rather than asking for a wider cap.

`--json` carries `summary` (the line the command would have printed), `runs` (`head_ambient`,
`head_clean`, `base_clean` — the three exit codes in the order they were run), `base` (the ref
asked for), `merge_base` (the commit actually extracted) and `verdict`. Record the last four
where the failure is discussed: a verdict without its inputs cannot be re-run.

Exits `0` with a verdict, `1` when the merge-base cannot be resolved (`is
refs/remotes/origin/main fetched?`), when the attribution is undetermined (several merge bases, or
a shallow clone), when `git archive` fails, or when an archive is missing tracked
files because the archived tree's own `.gitattributes` excluded them, and `2` when `--base` is
shaped like an option, which is refused above the first subprocess rather than handed to `git` as
one.

## `stayfixed prove [--timeout SECONDS] [--junit PATH] -- COMMAND …`

Run a test command where it is typed, count only what its runner reported, and say what that
proves: `proved`, `failed`, `not proven` or `refused`.

```bash
stayfixed prove -- uv run --locked pytest tests/test_x.py
stayfixed prove --timeout 600 -- npx vitest run
stayfixed prove --junit target/surefire-reports/TEST-all.xml -- mvn -q test
```

**What runs.** The command is everything after `--`, run as typed, never through a shell. `prove`
reads no configuration, needs no `stayfixed.toml`, and takes neither `--root` nor `--machine`; a
line with no `--`, or nothing after it, is a usage error (2). It reads the command past its
`NAME=value` assignments, `env` and `uv run`, as the red-run hint reads a command, and the first
runner adapter that recognises what is left plans the run: the argv, and where the runner's report
arrives and in which format. A command no adapter recognises, an `env` given an option among them,
is `not proven` (`not-recognised`); `--junit` (below) counts the report of a runner no adapter
knows.

**The `uv run` bound.** Behind `uv` and the first later word `run` (so `uv tool run pytest` and `uv
pip install run pytest` too), the command starts at the first word an adapter recognises, and every
word before it goes to uv unchecked, whether a uv option's value, another program and its
arguments, or an `env` and its assignments. So `uv run --with pytest python -O -m pytest`, `uv run
python -O -m coverage run -m pytest`, `uv run python -O .venv/bin/pytest`, `uv run pypy3 -O -m
pytest` and `uv run env PYTHONOPTIMIZE=1 pytest` run with `-O` or `PYTHONOPTIMIZE` unchecked and
can read `proved`; `uv run grep -m pytest x` runs with the report options added and reads `not
proven`; and `uv run --with pytest -- pytest -x` hands them to uv, which refuses them (`not
proven`). A `uv run` in which no adapter recognises a word is read whole, as is a runner named
through an alias or by a path no adapter recognises, which `--junit` counts.

The run is the command's own words with only the adapter's report options added (the table
below). Behind a launcher, the command's words are handed to it as typed and the launcher finds
the runner, so `uv run pytest` runs the `pytest` uv's environment holds; the receipt names the
launcher. A runner missing behind `uv run` is uv's to report (uv exits 2, "Failed to spawn"): a
`go test` reads `failed` (`none-ran`), since its report is its output, and the others `not proven`
(`no-report`), never `entry-not-found`. Without a launcher, the program is found as a shell finds
it in the run's environment: a word holding a `/` from the directory the command runs in, a bare
name on its `PATH`, so `PATH=.venv/bin:$PATH pytest` runs the `pytest` it names. The receipt names
the realpath of the program that ran.

The command runs in the directory `prove` is typed in, or in the one its launcher is told to run it
in: each `uv` among the launcher's words moves to the directory its `--directory DIR` or
`--directory=DIR` names, else to `UV_WORKING_DIR`'s (`--project` moves nothing). Only the
launcher's words are read, so neither moves a command read whole, a `--directory` after the first
word an adapter recognises is not read, and a launched program's own `--directory` before it is
read as uv's. That directory is the one judged: the plan is made there, and the project the
receipt answers for, whose tree's state it names, is its git top-level, or the directory itself
outside a repository. A command typed in `packages/web` runs in `packages/web`.

**The environment** is built once, as a shell builds it: yours, then each `NAME=value` the command
spells before its launcher, bare or after an `env`, in order, the last of two for one name
winning; such an assignment never reaches the argv. It is the whole launched process's, the
launcher's included. An assignment after `uv run`, bare or after an `env`, is the launcher's word,
handed to uv as typed: bare (`uv run TYPED=yes pytest`), uv runs it as its program and fails
("Failed to spawn", exit 2), so no test runs; after an `env`, it is set unchecked (the bound
above). Two variables are set apart, each its adapter's forging set, and only for a value that
turns tests off: `PYTHONOPTIMIZE` (pytest) set to anything but empty or `0`, and `UPDATE_SNAPSHOT`
(vitest) set to anything but empty, `none` or `new`, which vitest reads as `--update`. Assigned by
the command before its launcher, such a value is `refused` (`assigned-forging`, naming the
variable); inherited, the variable is removed from the run's environment, which the receipt names
(`scrubbed`). Every other variable and value is yours, read by the runner as outside `prove`:
`PYTEST_ADDOPTS`, `NODE_OPTIONS`, `GOFLAGS`, `GOENV` and the rest. A variable an env file sets past
this reading (`uv run --env-file`, an inherited `UV_ENV_FILE`) is the bound's: it can set
`PYTHONOPTIMIZE` or `UPDATE_SNAPSHOT`, or a nested launcher's directory, where `prove` does not
look.

**Input and output.** The runner's standard input is `/dev/null`, never yours, so nothing piped
into `prove` reaches the run and a test that reads it sees its end. A report the runner writes to a
file is read from a scratch directory outside the project. A report that is the runner's own
standard output (`go test`'s event stream) is copied to yours as it arrives, every byte, and only
the format's own events are counted. Under `--json` the runner's standard output goes to standard
error instead, every byte, so that standard output holds the one JSON object; without `--json` it
is yours, and its standard error is yours either way. Text a command prints is never counted.

**The runners.** Each refuses (`refused-option`, naming the option) only what you could type by
mistake and get a green report for tests that never ran or checked nothing, and says `not proven`
for a run that would never end (`never-ends`) or runs no test suite (`no-test-run`); every other
option is free. An option is read in its documented spellings, alone or as `--option=value`, where
`=false` turns a jest or vitest boolean off (`--update=none` is free, `--update none` refused as
`--update`); node's options and vitest's `--mergeReports` are read with any `=value`, which Node
reads as on and vitest as a directory. Another spelling the runner also reads, a cluster of short
options such as `-cu` among them, is the bound's.

| Runner | Recognised | Added to the command | Refused, or `not proven` | The receipt names |
|---|---|---|---|---|
| `pytest` | `pytest`, `py.test` and `python… -m pytest` (the interpreter's own options alone before `-m`), each also behind `poetry run`, `uv run` or `uv run -m` | `--junitxml=<report> -o junit_family=xunit2`, last among pytest's options and before a `--` where there is one, so they win over the command's own and an `addopts` | refused: `--setup-plan` and `--setup-only` (and `--setupplan`, `--setuponly`), which report the tests they only set up as passed; `--trace`, which reports a failing test as passed once its standard input ends; the interpreter's `-O` in any word of its flags before `-m pytest` (`-OO`, `-bO`), which compiles out every `assert` pytest does not rewrite, unless the `uv run` bound puts it among the launcher's words | the console script, the interpreter or the launcher |
| `jest` | `jest`, bare, after `npx` or `npx --no-install`, or by a path to it (`./node_modules/.bin/jest`, npm's link or pnpm's shim); `node [Node's options] <entry>`, the entry a path into `node_modules/jest` or `jest-cli`, or `node_modules/.bin/jest` | `--json --outputFile=<report>`; the command's own `--json` runs as without it, and its own `--outputFile` leaves jest writing no report (`not proven`) | refused: `-u`/`--updateSnapshot`, and `--collectTests`, which exits 0 reporting a failing test as passed, each also dashed (`--update-snapshot`); `never-ends`: `--watch`, `--watchAll` (`--watch-all`), and Node's `--inspect-brk` and `--inspect-wait`, on the command line or in `NODE_OPTIONS` | the program (`npx`, `node`, or the file the path names) |
| `vitest` | as `jest`, for `vitest` and `node_modules/vitest` | `run` first where the command's first word is none of vitest's subcommands; `--reporter=json --outputFile=<report>`, and `--reporter=default` where the command names no reporter | refused: `-u`/`--update` but `--update=none`, `--no-update` and `--update=new`; `--mergeReports` or `--merge-reports`, which runs nothing and reports an earlier run's blobs; `--dangerouslyIgnoreUnhandledErrors`, which exits 0 past an error vitest fails the run for; and a rewriting `UPDATE_SNAPSHOT` (above); `never-ends`: the `watch` and `dev` subcommands, `-w`/`--watch`, `--inspect-brk`, `--inspect-wait`; `no-test-run`: `bench`, `list`, `init` and `doctor`, whose detail names `vitest run` | as `jest` |
| `node --test` | `node` with `--test` among its options | a junit reporter to `<report>` and the spec reporter to standard output, before the command's own options | refused: `--test-update-snapshots` and `--test-rerun-failures`, which reports the tests a state file says passed before as passed, unrun; on the command line or in `NODE_OPTIONS`, which Node reads it from too; `never-ends`: `--watch`, `--watch-path`, and `--inspect-brk` and `--inspect-wait` there or in `NODE_OPTIONS` | `node` |
| `go test` | `go test …`, the `go` a bare name or a path to one | `-json`, after a leading `-C dir` (which the go command reads only first) and otherwise first | nothing is refused and nothing removed; `-c`, which builds the test binary and runs nothing, is `failed` (`none-ran`), and a `-json=false` of the command's own turns the stream into text (`report-malformed`) | the `go` or the launcher |

A program the command names that is not where it would be found is `not proven`
(`entry-not-found`), its detail saying what was looked for: a word holding a `/` at that path, a
bare name on `PATH`; a bare `jest` or `vitest` on no `PATH` entry names `npx jest` and `prove
--junit`. A file `node` is given that is not the runner's entry writes no report (`not proven`).
`npm test`, `npm run`, `yarn` and `pnpm` are recognised by none; `prove --junit` counts what they
run. A refusal and a `never-ends` in one command: the refusal wins.

Notes by runner, each what the command does outside `prove` too:

- **pytest.** An option that writes no report (`-p no:junitxml`) is `not proven`, and one that
  runs no test (`--collect-only`) is `failed`, by themselves. `--pdb`'s debugger reads the end of
  its standard input and quits, the failure kept in the report.
- **jest, vitest.** `npx` reads `.npmrc` and puts every `node_modules/.bin` above npm's local
  prefix on `PATH`: the directory, or inside an npm workspace the workspace's root, whose jest
  runs before a package's own. Given a runner no `node_modules` holds,
  it installs one **without asking**: the run's standard input is `/dev/null`, and npm asks only
  at a terminal, and otherwise warns and installs. Node's options before an entry are any (`node
  --max-old-space-size=4096 node_modules/jest/bin/jest.js`), and
  `NODE_OPTIONS=--experimental-vm-modules npx jest`, jest's recipe for ES modules, runs as typed.
  A run of no test with jest's standard error a pipe, as in most CI jobs, writes no report, so it
  is `not proven` there and `failed` at a terminal: never `proved`. A vitest subcommand after an
  option (`vitest --globals related a.js`) is a name filter of `run`, as vitest reads it;
  `related` gets `--run` where the command does not set it. vitest's own `--outputFile` beside
  the adapter's leaves no report (`not proven`, `no-report`), and a file-writing reporter of the
  command's own (`vitest --reporter=junit`) shares the adapter's report file, which then does not
  parse (`not proven`, `report-malformed`).
- **node --test.** A testcase Node writes for a whole file that ran no test is not counted unless
  it failed. A `todo` test is skipped, failing or not, as Node counts it. A reporter of your own
  given no destination stops Node before any test runs, so the run is `not proven`; give it one
  (`--test-reporter=spec --test-reporter-destination=stdout`).
- **go test.** The report is the run's standard output, copied to yours whole; a line a test
  prints is an `output` event and never a result. The 64 MiB cap counts the events alone: every
  `output` event read whole is left out of the report counted, an `output` line that does not
  parse is kept, so its refusal stands, and a refusal's line number, the size it names and
  `report_digest` are of that kept stream. `GOFLAGS`, `GOENV` (and the `go env -w` settings its
  file holds), `GOTOOLCHAIN`, `GOROOT`, `GOOS`, `GOARCH` and every flag are yours. A leading `-C
  dir` moves the go command and not the judgement: the receipt's `directory` is the one typed.

The discovery set of each runner, whose untracked files the receipt names (below):

| Runner | Discovery set |
|---|---|
| `pytest` | `conftest.py`, `test_*.py` and `*_test.py`, at any depth |
| `jest`, `vitest`, `node --test` | jest: `*.test.*`, `*.spec.*`, `__tests__/*`; vitest: `*.test.*`, `*.spec.*`; node: `*.test.*`, `*-test.*`, `*_test.*`, `test-*.*`, `test.*`, `test/*` |
| `go test` | `*_test.go` |

**`--junit PATH`** is for a runner no adapter knows: no adapter is consulted, the command runs
as typed (its assignments, `env` and launcher read as above, its program found as above, nothing
refused or removed), and its report is the JUnit file at `PATH`, read from the directory the command
runs in and allowed anywhere, inside the project too; a command read whole moves to no directory,
so `PATH` is read where `prove` is typed whatever its `--directory` or `UV_WORKING_DIR`. Before the run `prove` notes what is at
`PATH` reaches, followed through a link (nothing, or its inode, size and modification time);
after it, the file is counted only when `PATH` reaches a regular file the run created or rewrote,
or a link the run pointed at another file (`latest.xml` at the report it just wrote), and
otherwise the run is `not proven` (`junit-unchanged`, naming the file by its realpath), so a stale
or committed report counts nothing. A link the run newly makes to a stale file is the bound's.
A program the command names that is not there is `not-started`. The verdict is the cascade's.
`verified` says only whether the run was a `--junit` one: every `--junit` receipt carries
`verified: false`, one not started too, and every other `verified: true`, a command no adapter
recognises or one refused among them; the receipt of a `--junit` run, and of a command no adapter
recognises, carries `runner: null`. The line of a `--junit` run says `runner not verified, ran
<program>`.

**What `proved` means.** The code under test, any file in the runner's load path, tracked or not, and the environment the runner reads can shape its report, so `proved` means the runner reported green on this tree, for the tests this command selected.

**The verdict**, the first row that holds winning:

| Row | Verdict | Exit | Reason |
|---|---|---|---|
| the runner's adapter refuses the command, or the command assigns a variable in the adapter's forging set | `refused` | 2 | the adapter's own (`refused-option`), `assigned-forging` |
| no adapter recognises the command, its entry point does not resolve, it asks for a run that never ends or one that runs no test suite, it could not start, it was interrupted or passed its time limit, it wrote no report, the run did not write the `--junit` report, or the report does not read | `not proven` | 1 | `not-recognised`, the adapter's own (`entry-not-found`, `never-ends`, `no-test-run`), `not-started`, `interrupted`, `timed-out`, `no-report`, `junit-unchanged`, a report's own |
| the report holds a failed test | `failed` | 1 | `failing` |
| the report holds no test | `failed` | 1 | `none-ran` |
| every test the report holds was skipped | `failed` | 1 | `all-skipped` |
| the report is green and the command exited non-zero | `not proven` | 1 | `green-but-exited` |
| otherwise | `proved` | 0 | |

A report does not read when it is past 64 MiB (`report-too-large`), a JSON report is not UTF-8
(`report-not-utf8`), it does not parse as its format (`report-malformed`), an
XML report declares a doctype (`report-doctype`), or it names an entity it never declared
(`report-entity`). Where the refusal names something the report holds, an unknown test status, it is
escaped and, past 120 characters, cut to its start and its length.

`--timeout` ends the run's whole process group past that many seconds (default: 3600, which bounds
a suite that hangs and is no suite's budget). So does an interrupt (Ctrl-C) or a `SIGTERM` or
`SIGHUP` to `prove`, at any point of the run (while the tree's state is taken or the run planned,
as much as while the command runs): either way the run is `not proven` (`interrupted` or
`timed-out`), what the command left running in its process group is ended with it, and the
scratch directory is removed.

**The line** says the verdict and its reason in words, the counts (passed, failed, skipped), the
runner and the realpath of the program that ran, each variable of your environment the run did
not get (`removed from the run's environment: PYTHONOPTIMIZE`: one of the adapter's forging set),
and the untracked files in its discovery set, those git does not ignore first and then the ignored
ones; twenty and a count of the rest. The tree's state is taken before the run and after it, and is information for
you, never an input to the verdict. `--json` carries `verdict`, `reason`, `detail` (the variable a
refused assignment named, or a sentence naming the variable after a launcher; the option or word the
runner's adapter refused; what was looked for on `entry-not-found`; the option or subcommand on
`never-ends` and `no-test-run`; the file on `junit-unchanged`; or where a report stopped reading),
`argv` (the command, the value of every `NAME=value` and `--option=value` word replaced by `…`; a
single-dash `-name=value`, Go's spelling, and a value passed as the word after its option are kept
as typed), `directory` (where the command was judged), `runner`, `program`, `verified`
(false on a `--junit` run, and only there), `scrubbed` (those variables' names, sorted), `counts`,
`exit_code`, `report_digest` (the SHA-256 of the report counted: of a test event stream, the lines
kept, never the output printed), `commit`, `dirty_before`, `dirty_after`, `untracked` and
`untracked_more`.

**The network.** `prove` itself reaches none; what runs may. `uv run` may sync the project's
environment from its index first, as it does outside `prove`; `go test` may download the modules
`go.mod` names, from the proxy your go environment names, a `go env -w` setting included; and
`npx` installs a runner no `node_modules` holds, from the registry your `.npmrc` names, without
asking, since its standard input is no terminal.

**Reads** the command's report and git's answers about the tree. **Writes** nothing in the project:
the scratch directory is under the system's temporary directory, is readable by you alone, and is
removed on every path. What the command itself writes, it writes. **Runs** the command, as the
README's [What stayfixed sends where](../README.md#what-stayfixed-sends-where) row says.

## `stayfixed bugs new TITLE --severity S --area A [--source S] [--related ID …] [--no-fetch]`

File a bug: allocate the next free identifier (`1 + max` over every entry in the working tree
and every entry ever added on any ref, after a bounded `git fetch origin` unless `--no-fetch`),
write `<paths.bugs>/<PREFIX>-nnn.md` from the template, and regenerate the index. Every
rejection happens before the first write: a title or source the flat frontmatter subset cannot
hold is quoted for you; a `--related` value that is not an identifier, an index carrying content
this tool did not generate (`2`), and an allocated identifier whose file already exists (`1`,
naming `bugs check`) each leave the tree exactly as it was. A skipped fetch is reported on the
result line, not hidden. An index that cannot be written once the entry is filed exits `1`,
naming the filed entry, the reason and any skipped fetch, and saying to run `bugs index` once it
can be written, not `bugs new` again, which would file it twice.

The entry carries the keys `id`, `title`, `status`, `severity`, `area`, `found`, `source`,
`fixed_in` and `related`. An entry may also carry `regression`, the argv that reproduces the bug:
an inline list of double-quoted items, like `regression: ["pytest", "-k", "total and not slow"]`,
each item read with the two escapes a quoted title takes (`\"` and `\\`), separated by a comma.
Spaces may surround each item and each comma; a tab may not. `regression:`, `regression: []` and
`regression: [ ]` are the empty list. `bugs check` reports any other shape as `unreadable-entry`,
as it does an empty item and an item holding a control character below U+0020, or DEL.
`bugs renumber` leaves a `regression` exactly as written, while its sweep renames a test whose name
carries the old identifier in a scanned file, so it names each entry whose argv still names the old
identifier as one that may need editing by hand. [`bugs regressions`](#stayfixed-bugs-regressions)
runs it once the entry is `fixed`. `bugs new` does not write one yet.

**Writes** the entry file (creating `<paths.bugs>` for the first entry) and `<paths.bug_index>`;
and, unless `--no-fetch`, whatever the `git fetch --quiet --no-recurse-submodules origin` it runs
before allocating writes into the repository — the remote-tracking refs, `FETCH_HEAD` and the
fetched objects — even when a rejection that follows the allocation leaves the working tree as it
was.

## `stayfixed bugs index [--check]`

Render `<paths.bug_index>` from the entry files alone. `--check` exits `1` when the committed
index differs from that rendering and writes nothing. Either form refuses (`2`) while the write
would destroy something: a line the index holds that this tool did not generate (a hand-written
section, an operator's note, or a table row with no entry file behind it — recover it into an
entry file first), or a generated index whose entry directory is gone (restore the files; the
index carries nothing of its own). A row is judged by the entry it links and not by its shape,
so a row whose entry file went missing in a merge — the last record that bug existed — is not
something regenerating may delete. A reworded
header is a stale index, not foreign content. The first paragraph names the generator, and that
paragraph is recognised structurally rather than by an exact string, so an index left by an
older generated format is still read as generated rather than refused as hand-written content.
An index that cannot be written exits `1` with the reason.

**Writes** `<paths.bug_index>`.

## `stayfixed bugs check [--base REF]`

Every rule the ledger holds, in one pass: each entry parses under the flat frontmatter subset
and its `id:` matches its filename; no entry restates `**Status:**`/`**Severity:**` in its
body; every severity in `[ledger] evidence_boundary_required_for` carries a filled `**What this
evidence does not establish:**` line (the template's placeholder does not count); no identifier
is claimed by two files; every `related:` identifier has an entry; the index carries nothing
this tool did not generate, and is current; every `<PREFIX>-nnn` mentioned under the top-level
files and `[ledger] code_roots` has an entry (a `void` entry counts); every citation of an entry
*file* — from those roots and from the directories the `[paths]` values live under — names a
file that exists. Exits `1` with the count and up to eight `path:line [rule]` labels on the
line; `--json` carries every finding with its `detail`, which may quote the repository and is
why it is not on the line. Before a ledger exists — no `[paths] bugs` directory *and* no
generated index — every mention of an identifier and every citation of an entry file dangles, and
with `--base <ref>` a ledger the change forked with (its `[paths] bugs` or `bug_index`) is one
`ledger-removed` finding: with none of them it prints `nothing to check` and exits `0`, so the
check can be required before the first entry, and a change that deletes the ledger answers for the
ledger and for everything that refers to it. Once a ledger exists its entries are append-only:
with `--base`, each `<PREFIX>-nnn.md` the change forked with directly under `[paths] bugs` whose
exact name the tree's directory does not hold is an `entry-removed` finding, whatever still
mentions the identifier and whatever a file's fixtures marker says, so emptying the directory and
regenerating the index deletes the ledger as surely as removing it, and renaming an entry in case
alone deletes it too, on a filesystem that folds case as on one that does not. Other files under
the directory — a `README.md`, a subdirectory's notes — are not entries and may go. An entry
moves with `bugs renumber`, which leaves a `void` entry at the old number and so removes nothing.

What the change forked with is the ledger at every commit `git merge-base --all <ref> HEAD`
names, their entries taken together. An entry the base filed after the branch forked is not one
the branch deleted. A deletion is still named on a branch behind its base, on the merge commit CI
checks out, and on a history with several merge bases, where the one git would pick alone can
predate the entry while a merge deletes it all the same. Entries are append-only, so on a base
that kept its entries, taking them together refuses no branch that deleted nothing. An entry
removed from the base itself, by a direct push, is still named on a criss-crossed branch whose
merge bases include one from before the removal: restore it on the base.

Each of those commits' ledger is read where that commit's own `stayfixed.toml` put it: its
`[paths] bugs`, `bug_index` and `[ledger] id_prefix`, and nothing of how it judges an entry, so a
base carrying an `evidence_boundary_required_for` level the ledger now refuses does not stop the
change that corrects it. The copy is found and loaded as `stayfixed gate` finds and loads the
base's: at the project root's path inside the repository, through the loader, against the tree's
disk. So a root reached through a symlink, or spelled otherwise than git spells it, is refused
(`2`) here as it is there. The entries are compared by file name with the tree's directory. A
change that moves the ledger by `[paths]` answers for every entry it did not carry along, one that
changes `id_prefix` answers for every entry under the old prefix, and a deleted ledger is named at
the paths the base kept it at. A commit with no `stayfixed.toml` at the project's path is read at
the tree's paths, as the change that adds the configuration decides for itself under `stayfixed
gate`. A copy that does not load fails (`1`); one whose load meets a refusal, or whose `id_prefix`
the identifiers refuse, refuses (`2`); neither is read as a base with no ledger. A refusal prints
the base as data, and a refused prefix clipped to its first 120 characters and its length.

`--base` is what the `bugs` gate passes, the base it judges against. A base git cannot list, one
that shares no commit with `HEAD`, any base in a shallow clone, where the commits `HEAD` forked
from can be cut off and the merge base git sees be an older one, and any base in a clone git
cannot say is shallow or not, fail (`1`) rather than read as a base with no ledger; under a gate
that is the gate not running: fetch the whole history (`fetch-depth: 0`). Without `--base` the
tree alone is judged.

A generated index with no directory behind it is a deleted ledger and exits `1`. Git enumerates
the files where the root is the top of a checkout (tracked plus untracked-not-ignored), and a
walk stands in elsewhere. A file whose first 2 KiB carry `stayfixed:ledger:fixtures` holds sample
identifiers and is neither scanned nor swept.

A stale index is sent to `bugs index`, except the one a `bugs renumber OLD NEW` killed before its
last write leaves: when `NEW` holds `OLD`'s text, or `OLD` is the pointer that move titles toward
`NEW`, and the index is exactly the one rendered before the move, the line names `run: stayfixed
bugs renumber OLD NEW`, which finishes it; where several moves explain it, as for two entries that
differ only in `id:`, it names each and says only the one started finishes it. The sweep may already
have rewritten other entries, so each line is compared with the found index's line both as it was
and with `OLD` rewritten to `NEW`: a void pointer an earlier move left toward `OLD`, or a title
naming either, still names the renumber.

**Writes** nothing.

## `stayfixed bugs regressions`

Run the `regression` of every entry whose `status` is `fixed`, in identifier order, each as
[`stayfixed prove`](#stayfixed-prove---timeout-seconds---junit-path----command-) runs a command
and judged as it judges one: from the project root, under the caller's environment, with
`[gates] custom_timeout_seconds` as each run's bound. An entry of any other status is not run,
whatever it carries: a `rejected` one has no fix to regress, a `partial` one is still open and a
`void` one is a renumber's pointer. An argv no runner adapter recognises is `not proven`, and
nothing is started for it.

The line names each run, `<id>: ` and then the receipt's line as `prove` prints it, and ends
`<n> regression(s), <m> not proved`; with nothing to run, it is `nothing to run: no fixed entry
carries a regression`. `--json` carries `regressions`, one `{"id", "path", "verdict", "line"}`
object a run, `path` being the entry file's from the project root, and `not_proved`. The runner's
standard output goes to standard error in both forms, as a custom gate's does, so under `--json`
standard output holds the one object. Exits `0` when every run is `proved` or there is none, and
`1` otherwise, as `prove` does. A Ctrl-C, or a SIGTERM or SIGHUP, during a run ends that run `not
proven`, and nothing after it starts. A ledger that does not parse fails (`1`).

The run catches an honest regression and is no control against a hostile one: the argv is read from
the tree the change wrote, which can rewrite it as easily as the test. Who runs it is decided as for
any custom gate, by the base branch's `run` and the person's yes before a clone's commands run.

**Reads** the ledger's entry files, and what `prove` reads. **Writes** nothing in the project, as
`prove` writes nothing there; what each runner writes, it writes. **Runs** each argv, as the
README's [What stayfixed sends where](../README.md#what-stayfixed-sends-where) row for `prove`
says.

## `stayfixed bugs renumber OLD NEW`

Move an entry to a free identifier: `NEW` gets the entry with its `id:` rewritten, `OLD` becomes
a `void` pointer at the new number, every scanned file that mentions `OLD` is rewritten, and the
index is regenerated. Both endpoints are written first, then the sweep, so an interruption leaves
`OLD` resolving to the pointer rather than to nothing. The sweep knows the endpoints, the index
and the entries by the file, not by how its path is spelt, so a ledger directory committed in
another case than it is configured in, on a filesystem that folds case, is still one directory.

A run that was killed part-way is finished by running the same move again. The re-run recognises
the move's own half-done state: `NEW` holding exactly `OLD`'s text with the `id:` line rewritten,
or `OLD` byte for byte the pointer this move writes to `NEW`, whose title is only held to start
`renumbered to NEW — `, so a `NEW` retitled since is still finished. It makes the writes still
missing and leaves the tree an uninterrupted run would have left, when resumed the same day: a
pointer written by the resume carries the day it is written. A re-run of a move that finished —
the pointer in place and the index fresh — changes nothing and says `OLD was already moved to
NEW; nothing to do`, and `--json`'s `moved` is `false`, so a mention of `OLD` written since stays
as it was written. `bugs check` names this command while an interrupted move left the index stale.

Rejects `OLD` equal to `NEW`, a missing `OLD`, and any other occupied `NEW` (`1`); the last says
how to finish by hand a move whose `NEW` was edited after the kill, which the re-run can no longer
tell from an entry of its own. Raises the index refusals of `bugs index` (`2`) before touching
anything. A file the sweep could not read or write is listed and the command exits `1` naming it,
because once the pointer exists a stale mention in that file looks intentional to `bugs check`
forever. The line counts them and names up to eight; `--json`'s `unswept` carries every one, each
an object with `path` and `reason`. The path is relative to the root, and the reason is the error
in words, naming no absolute path; a refusal of stayfixed's own may repeat the root-relative path.
The moved entry's own body is the operator's to rewrite and is not swept, and neither is any
entry's `regression`, which is left exactly as written. The same sweep renames a test whose name
carries `OLD` in a scanned file, a test file under `[ledger] code_roots` included, but renames no
file, so an argv naming `OLD` may then select nothing, or name a path that is still right. The
line names each entry file whose `regression` still names `OLD`, the moved entry included, as one
that may need editing by hand, up to eight; `--json`'s `lists_naming_old` carries every one,
relative to the root and sorted. They do not change the exit code. A write of the
move's own that fails — `NEW`, the pointer at `OLD` or the index — exits `1` naming the file and
the reason, and says that running the same move again once the file can be written finishes it.

**Writes** the two entry files, every rewritten file, and `<paths.bug_index>`.

## `stayfixed docs check [--budgets] [--links]`

Two checks, both enforced, and no flag runs both (exit `1`, `FAIL:`):
the always-loaded document at `[paths] agents_md` exists, is within `agents_md_lines` and
`agents_md_words`, and has a `## Current status` section within `status_lines`; the roadmap at
`[paths] roadmap`, up to the line `## Design and plan trail`, is within `roadmap_prose_lines`
and `roadmap_prose_words` (a roadmap with no marker is budgeted whole; an absent one is not a
finding); every relative local link in the agents file resolves to a file — read from that
document's own directory, and only when it lands inside the project root, since a link that
walks out through `..` would be settled against the machine rather than the repository (an
absolute link is not read at all, nor is an anchor, a URL or a `mailto:`). Budgets are the
effective ones — the preset's, or the value `[budgets]` sets in its place. The memory
store's link graph is `stayfixed memory refs`'s, as advice.

**Writes** nothing.

## `stayfixed docs trail [--check]`

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

**Writes** `[paths] roadmap`.

## `stayfixed plan check [--base REF] [PATH …]`

With `PATH` arguments, lint exactly those plans; without, the plans under `[paths] plans` that
merging the change could alter on `REF`, `REF` defaulting to
`refs/remotes/origin/<project.base_branch>`, the fully qualified name, as for `stayfixed assess`
and `stayfixed gate`, so a tag called `origin/<branch>` cannot stand in for it. Those are the plans
whose copy in `HEAD` differs from `REF`'s and from that of any commit `git merge-base --all REF
HEAD` names: a copy equal to every merge base's leaves the merge taking `REF`'s, and one equal to
`REF`'s leaves it as it is. Every merge base, not the one `REF...HEAD` diffs against, which can
already hold an old plan the change puts back. Five rules, each from a retrospective: every
backticked path resolves unless the line says `(create)` or `(delete)`, or the plan declares it
on a `Create:`, `Test:` or `Delete:` line; no step is phrased as already knowing its answer
(`confirm that nothing …`, `verify no …`, `check that it does not …`); a `**Scope:**` line
with content is present; a plan claiming `Fixes <PREFIX>-nnn` carries a `**Premise:**` line with
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
words. The `plan` gate that
`stayfixed assess`, `stayfixed gate` and `stayfixed adopt promote` run reads the same cause as a
gate that could not run, as `commit` does, because it says nothing about any plan. A `REF`
shaped like an option is refused (`2`) before git sees it. Uncommitted plans
are not in the diff; the line counts them and `--json` names them, and naming one as `PATH`
lints it.

**Writes** nothing.

## `stayfixed assess [--base REF] [--builtin] [--root PATH] [--machine PATH]`

What stands between this repository, as it is, and enforcement. It reads the tree's own
`stayfixed.toml` — not the base branch's: the question is about this tree, so this command is
not a trust boundary — and runs every configured gate (see [Configuration](#configuration)): the
built-ins `[gates] builtin` keeps, in their fixed order, then each `[gates.custom.<name>]`. A
custom gate's output goes to standard error as it ran and nowhere else, so running `assess` in a
clone runs the commands that clone configured, as running its test suite would. Then it runs the
probes below, which read files and the git index and never run a tool or reach the network.

`--builtin` runs the built-in gates and the probes and no custom gate: for a clone whose
commands you have not agreed to run. The summary names up to eight of the custom gates it left
out and counts the rest, which count toward no total, and the inventory lists every one under
`skipped`.

`REF` is the revision `plan` and `commit` compare against, and the one `bugs` compares the ledger
with where `HEAD` forked from it (whether it carried one when the tree has none, and which entries
the tree lacks), default
`refs/remotes/origin/<project.base_branch>` — the fully qualified name, so a tag cannot stand in
for it. Where that ref does not exist (no `origin`, or not fetched), `plan`, `commit` and `bugs`
could not run, and each counts as failing; a `note:` after the summary says the base is missing
and suggests `--base refs/heads/<project.base_branch>`, as `adopt promote` does.

A gate that could not judge the tree — a base that is not there, an unreadable plan, a range git
cannot read, a custom gate that could not start or ran past `custom_timeout_seconds`, a file it
reads that CI's checkout will not have (below) — is failing: a gate that could not look has not
passed. A gate never reports that as a finding; it is the one outcome every command that runs
gates spells `could not run`, and `--json` carries it as `answered: false` with a fixed `reason`
naming the command that shows why.

**The `docs` and `trail` gates judge tracked files.** That is the contract: CI checks out what git
tracks and nothing else, so a file that is on disk here and that git does not track — never added,
or ignored — is one those gates read here and CI never sees, and there the gate's own finding for
an absent file fails every pull request. So `assess` reports such a gate as could not run, its
`reason` saying it could not judge the tree as CI will, and counts it as one that would fail, and
`stayfixed adopt promote` never enforces it. To keep one of those files out of git, take its gate out
of `[gates] builtin`.

- **The files.** `[paths] agents_md` and every file or directory its links name, for `docs`, and
  `[paths] roadmap` and the `trail.toml` beside it, for `trail`. The roadmap the `docs` gate reads
  for its prose budget is not asked about: an absent roadmap adds no finding, so one CI cannot see
  can only make the verdict here stricter than CI's.
- **Tracked** means in git's index, as `git ls-files` lists it, so a file staged and not yet
  committed counts — CI checks out commits, so commit it with the change that promotes the gate.
- **Symlinks.** A symlink is tracked as the link alone, and a checkout writes the link whether or
  not what it names is there, so each path is walked as the filesystem walks it, one component at
  a time, and every symlink on the way is followed, a symlinked directory's included: every step
  and the file it lands on must be tracked. Where a link leads is judged against the work tree's
  top, since a project below it may link to a tracked file beside it, which every checkout has; a
  link whose target is absolute or climbs out of the repository counts as untracked, since no other
  checkout has what it names, and so does a link that differs on disk from the one git has — one
  retargeted and not staged — since a checkout writes git's, which may lead elsewhere.
- **The items.** An `untracked` item names the files: the first untracked step on a path, a link
  that differs on disk from git's, or a link that leads out of the repository, a directory's
  included, and when that step or link is outside the project, the last link inside it that led
  there. A name that differs from the one git tracks only in case — a link to `Notes.md` where git
  tracks `notes.md` — reads the committed file on a filesystem that folds case, as macOS's does by
  default, and nothing in a Linux checkout, so it goes to a `case-differs` item instead, whose
  remedy is to spell it as `git ls-files` does; where case is kept apart and the two names are two
  files, the one read is simply untracked. Each name is inside the path grammar or withheld.
- **No answer.** Inside a git work tree, a git that gives no answer is never read as tracked: the
  gate could not run the same way, and its item is `could-not-look`. Outside a work tree nothing is
  asked, since there is no index to ask and no checkout for CI to take, and both gates judge the
  files as they are, as `docs trail` lists every document there.
- **`stayfixed gate`** asks nothing about tracking: it runs on the checkout CI took, where such a
  file is simply absent and the gate's own finding says so.

**A gate's row.** `stayfixed assess`, `stayfixed gate` and `stayfixed adopt promote` each give every
gate they ran one `--json` row in one shape: `name`; `enforcing`; `answered`, false when the gate
could not run; `reason`, that fixed text, else empty; `count`, its findings; and `failing`, true
when it has a finding or could not run. A custom gate `stayfixed gate` did not start because the
run had already failed has a row too, `answered` false and `reason` `not run: the run had already
failed`, and `failing` true, since it judged nothing and a gate that did not look has not passed.
A row names no finding: `assess` lists them as items.

| Probe | Reads | Severity | Principle | Reported when |
|---|---|---|---|---|
| `code-roots` | `[ledger] code_roots` | advice | — | an entry no walk takes, each named in config order, quoted when it lies outside the path grammar, with its reason: it names the repository root itself (`.`, `./`), it is no readable path inside the repository free of links, `..` and `.git`, or it names no directory here, unless the preset's default `code_roots` lists it, in any spelling the fold reads alike, and another entry is walked, since then a missing directory loses no walk |
| `todo-markers` | tracked files under `[ledger] code_roots` | advice | 1 | a `TODO`, `FIXME` or `XXX` word; `where` names files |
| `tracked-env` | the git index | warning | — | a tracked file named `.env` or `.env.<x>`, except `.example`, `.sample` and `.template` |
| `memory-history` | the history of `[paths] memory` | warning | 8 | the store has history and `memory.mode` is not `in-repo` |
| `foreign-hooks` | the committed hook settings of each harness `[stayfixed] agents` selects | advice | 5 | any hook entry, one claiming stayfixed's marker included: stayfixed writes none into a committed file |
| `foreign-workflows` | `.github/workflows/*.yml` and `*.yaml` | advice | — | any workflow but stayfixed's own caller |
| `codeowners` | the first of `.github/CODEOWNERS`, `CODEOWNERS` and `docs/CODEOWNERS` | advice | 7 | there is no file, or no line that does not start with `#` holds `.github`: a plain substring, not GitHub's pattern matching, so a line such as `* @owner` still reports; not judged under `[ci] mode = "none"` |
| `commit-types` | the subjects of the last 100 commits, merges excluded | advice | — | a subject whose type is not in `[commit_messages] types`; `where` names commits |
| `profile` | the configured profile's checks | the check's own | — | each failed check, counted once; a profile this stayfixed does not ship is one `profile-not-shipped` warning |

A probe that could not look — a git query that failed or timed out, a settings file stayfixed
cannot read, a path through a symlink — reports a `could-not-look` warning naming where, and
never reads as "nothing found". Two things are deliberately not inventoried: another tool's
design-document directories, because stayfixed names no other tool's convention; and whether a
test exercises what its name says, which only reading one stack's test files could judge.

**Writes** `.stayfixed/assessment.json`, which the `stayfixed:ignore` region keeps out of git,
overwritten on every run that gets that far and never read back: format `2`, with `format`,
`stayfixed` (the version that wrote it), `base`, `enforcing` (the gates
`[stayfixed] enforced` names), `skipped` (the
custom gates `--builtin` left out, else empty), `gates` (a gate's row each, above) and `items`
(per item: `probe`, the gate or probe that found it; `rule`; `principle`, a number in
[the principles](methodology/principles.md) or `null`; `severity`, `warning` or `advice`;
`remedy`; `where`, at most 200 labels; and `count`, how many there were, never capped). A gate's
findings become one item per rule, at `warning`. `--json` prints the same object with `summary`
beside it. When git does not ignore the file where it is written, the summary ends with a note
saying so. A `.stayfixed` that is a symlink or not a directory, or a directory at the inventory's
place, is a refusal and the inventory is not written. Anything else at that place, a symlink
included, is replaced by the file, and what a symlink pointed at is left as it was. Without
`--builtin`, a custom gate writes whatever its command writes, and every gate runs before the
inventory is written, so that refusal comes after the custom gates have run.

The summary prints counts and stayfixed's own words — gate names, probe and rule ids,
severities, remedies — and never a path the repository chose: one table with a row per gate
(`gate`, `enforcing`, `findings`, `would fail`) and one with a row per item (`from`, `rule`,
`severity`, `count`, `remedy`).

Exit codes: `0` when no gate would fail, whatever the probes found, so `0` means every gate
could enforce now; `1` when a gate would fail, enforced or not, or when `stayfixed.toml` is
missing or invalid (`failed:`, as for every command that reads it); `2` on a refusal, a
`stayfixed.toml` that is a symlink among them: it is never followed, as no command follows it.

## `stayfixed gate [--only NAME]… [--base REF | --pr-base=BRANCH --base-input=BRANCH --default-branch=BRANCH] [--path=PATH] [--builtin | --custom] [--workflow-sha SHA] [--annotate] [--summary FILE] [--root PATH] [--machine PATH]`

The gate a pull request faces, runnable on your own checkout. One run:

1. refuses a project root reached through a symbolic link, spelled otherwise than git spells it,
   or given with a `..` component, which after a linked component is not the directory it names;
2. reads the base's `stayfixed.toml` at one exact commit, at the project's own path in the repository;
3. judges this tree's `stayfixed.toml` against it, key by key (below);
4. runs the configuration check and the configured gates under the configuration that judgement
   chose, each enforcing or advisory as it says.

Without `--only` it runs the configuration check and every configured gate: the built-in gates
`[gates] builtin` keeps and the project's own `[gates.custom]`. `--only NAME` runs just the names
given, each once; `config` is the configuration check. A name this run's configuration does not
have is refused, counted and not quoted. Running it in a clone runs that clone's own gate
commands, as [Configuration](#configuration) says.

**`--builtin` and `--custom`.** `--builtin` runs the configuration check and the built-in gates
and executes no command from `stayfixed.toml`; `--custom` runs the project's own gates alone and
judges nothing. Each narrows the bare run, or `--only`'s names, to its kind, and skips a name of
the other kind rather than refuse it. `--builtin` runs the configuration check whatever `--only`
names: it is the run that judges, and a caller that names one gate — a matrix leg, a person
reproducing CI — still judges the change's `stayfixed.toml`, so a loosening fails every such
run. The reusable workflow runs them as two steps, the second only when the first passed. A
custom gate's command is fixed by the base, but the files it executes — a `conftest.py`, a
`Makefile`, a script — are the change under review, so for a custom gate the guarantee is "this
command runs and must exit 0", and nothing about what it runs. An owner who wants those files
pinned puts them under CODEOWNERS. Run bare on your own checkout, everything runs in one
process. Narrowed to nothing — `--custom` on a project with no gate of its own — the run prints
`nothing to run`, appends no summary and exits `0`.

**The platform's base, and `--path`.** [The reusable workflow](#the-reusable-workflow) hands the
run what the platform and the caller file said, raw, and the run checks them itself. The base is
either `--base` or three flags together, never both: `--pr-base` is the pull request's base as
the platform reports it (empty on any other event), `--base-input` the caller's `base:`, and
`--default-branch` the repository's default branch. Each takes one argument as `--name=value`, so
a value that begins with `-` is still that flag's, and each may be empty. The branch is the first
of `--base-input`, `--pr-base` and `--default-branch` that is not empty; a `--base-input` that
disagrees with a non-empty `--pr-base` is refused, naming the pull request's base and never the
input's value, since on a pull request the caller file is the author's; and the base commit is
`refs/remotes/origin/<branch>`, resolved once in `--root`'s repository, which the verdict and every
gate then read. `--path=PATH` is the project root inside `--root`, with either form of the base:
`""`, `.` and `./` are `--root` itself, one leading `./` and one trailing `/` are dropped, and a
`..` component or an absolute path is refused without echoing the value. Any other character is
admitted, a space or a name outside ASCII included. With the platform's base, git is asked once at
`--root` for the top of its checkout, every other `git` the run asks names that checkout's
repository rather than finding one from the project root, so the project is always that directory
of the checkout, and the release tags a moved `ci.ref` is checked against are listed from its top.

**Which custom gates run, and in what order.** A custom gate runs only with the command the
base's `stayfixed.toml` gives it. One the change adds, or re-commands while the base does not
enforce it, is not run: it prints `<name>: advisory, not run until the base has this command`
(or `enforcing`, when the change enforces it), and runs from the first pull request after it
lands on the base. It fails nothing meanwhile, since the base enforces no command it lacks, and
under the bootstrap, where the base has no `stayfixed.toml`, no custom gate runs. The reason is
that the custom gates share one checkout: a gate the change wrote, run before the base's
enforced ones, could rewrite the script they are about to execute. For the same reason the
built-in gates run first, then the custom gates the base enforces, then every other custom gate.
And once the run has failed — a refused key, or an enforcing gate among those that failed or
could not run — no custom gate starts, one the base enforces included: each prints `<name>:
advisory, not run: the run had already failed` (or `enforcing`), and its `--json` row says the
same, `answered` false with that `reason`. A custom gate can run files the change can edit, and
it runs in the process that holds the verdict, on a GitHub-hosted runner with passwordless
`sudo`, which could rewrite that process and turn its failure into a pass. An enforced gate is
no exception: a test runner the base enforces beside a pinned policy runs the change's code, and
started after the policy failed it would run after the verdict was decided. So once the verdict
is a failure no custom gate runs, and a pinned gate named to sort first among the enforced ones
has passed before any other custom gate starts. While the run has not failed (an advisory gate's
findings do not fail it), a custom gate runs as always; one that was not started is judged on the
next run, once the failure is fixed.
Each custom gate runs in a session of its own, and the command's process group is ended when
the command exits, passes or not, as on a timeout or an interrupt, so nothing it started in the
background in that group runs on into the next gate. A descendant that leaves the command's
process group (a new session, or a job-control shell's own group) is not ended, and nor is one
stayfixed may not signal (a sudo or setuid descendant). Enforced gates that themselves run files
the change can edit — two test runners, say — still share that one checkout, and one could
rewrite what the other runs; one leg per gate isolates them (see "One row per gate" under
[the reusable workflow](#the-reusable-workflow)).

**What a pull request may change in `stayfixed.toml`.** Both copies go through the loader and are
compared by what it derives — each key by its dotted name, each budget by its effective value,
each custom gate's `run` on its own — never by byte. A comment, a key written out at its default,
and a reordered `enforced` or `[gates] builtin` list are no change at all. Each changed key gets one verdict:

| Key | Admitted when | Verdict | Otherwise |
|---|---|---|---|
| `stayfixed.enforced` | it lists every gate the base lists | `tightened` when it lists more, else `neutral` | `refused` |
| `gates.builtin` | a gate added, or one removed that the base does not enforce | `tightened` when one was added, else `neutral` | `refused` |
| `gates.custom.<name>.run` | the gate is new, or the base does not enforce it | `tightened` when new, else `neutral` | `refused` |
| `budgets.<name>`, a gate's budget (`agents_md_lines`, `agents_md_words`, `status_lines`, `roadmap_prose_lines`, `roadmap_prose_words`) or a session's (`memory_index_words`, `startup_rules_words`, `volatile_notes_words`, `volatile_ttl_days`) | the effective value is at most the base's | `tightened` | `refused` |
| `ledger.code_roots` and `ledger.evidence_boundary_required_for` | every entry the base lists is still listed | `tightened` when one was added, else `neutral` | as any other key |
| `stayfixed.preset`, `stayfixed.agents`, `project.name`, and every key whose class is a preference (`stayfixed.profile`, `memory.mode`, `memory.groups`, `memory.index_extra`), the machine owner's or the plugin's | always: no gate judges a pull request by them | `neutral` | — |
| `stayfixed.version` and `ci.ref`, judged as one upgrade | the version is exactly the running stayfixed's and not earlier than the base's, and a moved `ci.ref` is the commit `--workflow-sha` names and one of stayfixed's release tags names | `upgrade` | as any other key |
| any other key | — | — | `refused` while the base enforces any gate, `noted` while it enforces none |

A preset switch is judged by what it moves: its own name is `neutral`, a budget it lowers
`tightened`, and anything else it moves falls to "any other key". "Not earlier" is read the way
`stayfixed upgrade` reads it — by the leading `X.Y.Z`, and a release after its own pre-release — and
a pair stayfixed does not order is judged as any other key: refused while the base enforces a gate,
noted while it enforces none. The run uses this tree's configuration unless a key was
refused, and then the base's; it enforces the gates either side enforces. So a pull request that
promotes a gate is held to that gate in its own run.

**How a refused change lands.** While any gate enforces, a pull request cannot make a change the
table refuses, and that includes routine upkeep: a `[paths]` value,
`[artifacts] local`, a `[ledger] code_roots` entry removed, a `[commit_messages] types` entry, a custom
gate's `run`, `[gates] custom_timeout_seconds`, `[project] base_branch`. The owner makes such a
change by pushing it directly to the base branch; every later pull request is judged against it.
If you want that push to need you, and not an agent working with your credentials, protect the
base branch at the repository level so that only you can push to it. Many projects do not need
that, and it is an option, not a requirement.

**What each input rests on.** The verdict holds where the repository has the settings
[the reusable workflow](#the-reusable-workflow) names, and not otherwise.

- *The base's commit.* `--base` takes a full 40-character commit id or a full `refs/…` name, and
  nothing shorter: git resolves a short name through rules in which a tag called `origin/main`
  wins over the remote-tracking branch of that name, and a full name that does not exist falls
  through to a tag of the same spelling, so the name must also exist as itself. In CI the workflow
  passes the platform's base instead, and the run resolves its branch's fully qualified
  remote-tracking ref once, to a commit. Run locally, the default is
  `refs/remotes/origin/<project.base_branch>`, read from this tree's own configuration, which is
  why a local run is advice and never the authority. A clone without an `origin` remote names its
  base with `--base`, such as `--base refs/heads/<project.base_branch>`: a run whose base is not
  in the checkout fails with that suggestion, spelled with the branch the file configures.
- *The base's copy.* It is read at the project root's own path in the repository. A root reached
  through a symbolic link below the repository's top, or spelled otherwise than git spells it, is
  refused: either would look for the copy where the base has none, and a missing copy is the
  bootstrap, where this tree decides. A link above the repository's top — `/tmp` on macOS, a linked
  home directory — belongs to the machine and is admitted.
- *The running stayfixed and `--workflow-sha`.* In CI both are whatever the caller workflow's
  `uses:` line selects. A pull request can edit that line; a required code-owner review of
  `/.github/` is what keeps it out of the pull request's reach.
- *Release tags.* A moved `[ci] ref` is admitted only at a commit one of stayfixed's own `v*` tags
  names, asked of the public repository.
- *The verdict itself* is worth what the process that computed it is worth. It must execute
  nothing the repository wrote: run it with `--builtin`, and start it as
  `python3 -P -s -m stayfixed`, so that no module in the checkout is imported in place of
  stayfixed's own, and no `.pth` file in a user site directory is processed at start-up, even one
  the environment has pointed into the checkout.

Run locally on a branch `stayfixed upgrade` made, a moved `[ci] ref` is refused unless you pass
`--workflow-sha` with the commit the new `uses:` line names; with it, the run answers what CI will.

**Printed.** `config: …` first when the configuration check runs: how many keys changed, how many
were refused and up to eight of their names, or that the base has no `stayfixed.toml` at this
path. Then one line per gate: `<name>: enforcing, N finding(s)`, `<name>: advisory, N finding(s)`, or `could not run`
in place of the count, or `not run: the run had already failed` for a custom gate not started
once the run had failed; and, after the gates that ran, `<name>: advisory, not run until the base
has this command` (or `enforcing`) for each custom gate whose command the base does not have. A run
that fails with a gate failing ends with one `details:` line saying
where the findings are: `stayfixed assess --json` (`stayfixed assess --builtin --json` under
`--builtin`), or the gate's own command. Key names and gate
names print; values from `stayfixed.toml` and a finding's detail never do.

**`--annotate`** also prints GitHub workflow commands, which the platform shows as annotations:
one `error` per refused key, and one per finding or gate that could not run or was not started —
`error` for an enforcing gate, `warning` for an advisory one — and a `warning` per custom gate not
run until the base has its command. The message is `<gate>: <rule>`. `file=` is written
from the repository's root and only for a path of letters, digits, `.`, `_`, `-` and `/`; any
other path is annotated without a location, and a `commit` finding, which names a commit, has
none. At most ten per level; past that one `notice` counts the rest, because the platform shows
ten per level per step and drops the others without a word.

**`--summary FILE`** appends a markdown table — each gate's mode, count and outcome, and each
changed key's verdict — to `FILE`; the workflow names the job summary. **`--json`** carries
`config` (`judged`, `changes` as `{key, verdict}`, `refused`, `enforcing`),
`not_on_base`, the custom gates not run until the base has their command, and `gates`, a gate's
row each as [`stayfixed assess`](#stayfixed-assess---base-ref---builtin---root-path---machine-path)
defines it, `enforcing` as this run enforces it. It lists no finding: `stayfixed assess --json` is
where findings are serialised.

**Reads** `stayfixed.toml`, the base's copy through git, every file a gate reads, and — only when
`--workflow-sha` matches a moved `[ci] ref` — the public repository's tags.

**Writes** nothing but the file `--summary` names; a custom gate writes whatever its command writes.

A pull request that removes `stayfixed.toml` — `stayfixed uninstall` among them — fails the run:
nothing says which gates run, and a run that cannot judge a change does not pass it. Such a
change lands the way a refused key does, by a direct push to the base branch.

A gate that could not run fails the run only when it enforces, whatever stopped it — a refusal
raised inside the gate included, such as a path its own configuration names that turns out to be
a symbolic link. An advisory gate stopped that way prints `could not run` and is a warning
annotation, and the run can still exit `0`; the gate's own command, which the remedy names,
shows the refusal itself.

Exits `0` when no enforcing gate failed or could not run and, when the configuration check ran,
nothing was refused; a custom gate not run until the base has its command changes neither. `1`
when an enforcing gate failed or could not run; when the configuration check refused a key; when
the base is not in the checkout or git could not read its copy, the platform's base branch
included (the message names `fetch-depth: 0`); when the root is not inside a git repository, or git refuses the one it is
in; when this tree has no `stayfixed.toml`; or when either side's `stayfixed.toml` is not UTF-8
text or does not load, the message naming which (a base's copy is fixed on the base branch, and
is never read as the base having none). `2` on a refusal: a `--base` outside its grammar (before
anything runs); some but not all of the platform's three base flags, or them beside `--base`; a
`--base-input` that disagrees with `--pr-base`; none of the three naming a branch, or one `git
check-ref-format --branch` refuses; a `--path` with a `..` component or an absolute one; a root reached through a symbolic link, spelled otherwise than git spells it, or
given with a `..` component; an `--only` name this run's configuration does not have; a
`stayfixed.toml` that is itself a symbolic link; or a `[paths]` value on either side that leaves
the root, passes through a symbolic link, or names `.git` or `.stayfixed`. Both copies are loaded
against this tree's disk, so a change that turns a directory the base names into a symbolic link
refuses the base's own load, in a message that says it is the base's, and a base written for an
older stayfixed that this one no longer loads fails every pull request until the owner fixes it
on the base branch.

## `stayfixed adopt promote [GATE …] [--base REF] [--builtin] [--root PATH] [--machine PATH]`

Runs gates strictly on the tree as it is, and enforces those that pass by adding them to
`[stayfixed] enforced`, the one adoption key: a gate enforces when that list names it, and
nothing else says so. It is the one adoption command. With no `GATE`, it runs every configured
gate that does not enforce yet, enforces each one that passes, names the rest with their finding
counts, and exits 1 if any failed; the line names up to eight gates in each of its two lists and
counts the rest, and `--json` carries every one. With names, they pass together or nothing is
written, and a named gate that already enforces is refused rather than skipped. The list is
written in configured order, and once every configured gate passed it names every one: a gate
the project adds later is advisory until it is promoted in turn, or listed by hand in the pull
request that adds it, which `stayfixed gate` admits as a tightening. A project whose every
configured gate is already listed is refused, as is one that configures no gate. A name, a gate
already enforcing, nothing left to promote, a `stayfixed.toml` the editor cannot rewrite in place
and a manifest it cannot read are each refused before the first gate runs; a refusal from the
editor names `enforced` on one line: as it stands when the check before the gates finds it, and
as the command would write it when the write itself refuses, so following it either leaves the
project as it was or makes the promotion whole.

`--base` is what `plan` and `commit` judge a range against, and what `bugs` compares the ledger
with where `HEAD` forked from it, as for `stayfixed gate`: a 40-hex commit or a `refs/…` name,
`refs/remotes/origin/<project.base_branch>` by default. The reusable workflow judges against `[ci]
gate_branch`, which is that branch unless the file sets it; where the two differ, pass `--base` to
judge as CI will. Run on the base branch itself, that range is empty and those two gates pass
having judged nothing; the pull request that carries a promotion faces every gate it promotes in
its own run. A custom gate runs its command here, as it does under `stayfixed gate`, and only
when that command is the one the base's `stayfixed.toml` gives it: a gate the base does not have,
or has with another command, is not run and not promoted, and is named `(not on the base)` with
a `note:` saying to land it on the base branch first, because `stayfixed gate` would not run it
in the pull request that carries the promotion. A base that cannot be read, or has no
`stayfixed.toml`, has no command, so every custom gate waits.

A `docs` or `trail` gate that reads a file CI's checkout will not have is never promoted, since CI
would fail the gate on every pull request (*The `docs` and `trail` gates judge tracked files*,
under `stayfixed assess`). It could not run, is named `(could not run)`, and a `note:` for it names
up to eight of the files and counts the rest, each inside the path grammar or withheld, and says
to commit them — an ignored one needs
its ignore rule removed, or `git add -f` — and to point a symlink it names at a tracked file in the
repository, or to keep them out of git and take the gate out of `[gates] builtin`. A file git
tracks only under a name that differs in case gets a `note:` of its own, saying to spell it as
`git ls-files` does; one git gave no answer about is named with a `note:` saying so.

`--builtin` runs the built-in gates and no custom gate, as `stayfixed assess --builtin` does: for
a clone whose commands you have not agreed to run, where the base is the clone author's and its
having a command is no brake. A custom gate is promoted only by a run that ran its command, so
each one is not run and not promoted, is named `(not run, as --builtin asked)` with a `note:`
saying that without `--builtin` the command runs them, and, named beside other gates, holds them
back as a gate not on the base does.

`--json` carries, on exit 0 or 1, `gates` (a gate's row for each gate it ran,
as `stayfixed assess` defines it, `enforcing` when this run promoted it), `promoted`, `failing`,
which maps each gate that ran and did not pass to its finding count, `unanswered`, the gates that
could not run, `not_on_base`, the custom gates not run because the base does not have their
command, `skipped`, the custom gates `--builtin` did not run, `untracked`, which maps each gate
not promoted because it reads files CI's checkout will not have to those files, other than the
ones below, and `case_differs`, which maps each gate not promoted because git tracks a file it
reads only under a name that differs in case to those files, as read; a gate whose only such files
differ in case is under `case_differs` alone. When a gate stays
advisory, the summary ends with a line saying where its findings are
(`stayfixed assess --json`, or `stayfixed assess --builtin --json` under `--builtin`, or the
gate's own command), and, when `plan`, `commit` or `bugs`
could not run and the base is not in the checkout, a `note:` saying so and naming `--base` with
the project's base branch, since a gate that could not run for want of the base says nothing
about the tree.

**There is no demotion.** Loosening is an edit to `stayfixed.toml`, and `stayfixed gate` refuses
it to any pull request while anything enforces. It lands only through a push that bypasses
branch protection, which is an owner's act and not a command. Removing or renaming a gate that
`[stayfixed] enforced` lists is such an edit, and the same push must take the name out of that
list, or `stayfixed.toml` no longer loads.

**Writes** `stayfixed.toml`'s `[stayfixed] enforced` through the same editor as
`stayfixed upgrade`, and the manifest's record of it when that record still describes the file —
and nothing when no gate is promoted. A custom gate writes whatever its command writes.

| Exit | Meaning |
|---|---|
| 0 | every gate it ran passed and now enforces |
| 1 | a gate failed, could not run, is a custom gate whose command the base does not have, or is a custom gate `--builtin` did not run: with names, nothing was written; without, the others were enforced; or `stayfixed.toml` is missing or does not load |
| 2 | a name that is not a configured gate, a named gate that already enforces, nothing left to promote (every configured gate listed), a project that configures no gate, a `--base` outside its grammar (from the parser), a manifest that cannot be read, or `stayfixed.toml` refused |

## `stayfixed memory refs`

Every backticked repository path a note names still exists. Notes are read as authoritative and
age silently, so a path to a deleted module sends the next session after it. A candidate is
dropped when the tree explains it: shorthand that resolves under the root, a code root or the
directory a `[paths]` value lives in; an absolute path outside the repository; a placeholder
(`scripts/foo.py`); a path the repository's ignore rules cover — except a path into the store
itself, which those rules cover wholesale and which is settled on disk. Fenced code and bare
filenames are skipped. In an overlay store, a note in a cross-project group that `[[links]]`
into a project-scoped note is an `audience` finding. Exits `1` listing `note:line [rule]`; the
targets are in `--json`. A note that exists and would not parse is counted on the line and
named in `--json`, and is exit `1` too: an unread note is not a clean note. Beside those, the
store's link graph is reported as advice: every `[[wiki-link]]` names a document in the store,
no link is immediately repeated, and no ledger identifier is bracketed. Each miss is a notice,
counted on the line and listed under `notices` in `--json`, and never changes the exit code: the
store is shared by every session on the machine, so a link a sibling session left dangling is a
hint, while a stale path is a finding. Refuses (`2`) when a
configured group could not be resolved — it leaves the store, or is a link the store refuses — counting them on a line that names none, then naming
every group with the resolver's own reason for it, one per line, inside the delimited region that
marks repository-authored text as data — the one list of names not capped at eight, since the
region is data rather than a line, and on the path a model reads the harness keeps at most
`[native_caps] hook_output_chars` of it — because a walk over a subset that reports nothing stale
is worse than no guard. A group whose directory the store does not hold is no such group: it is
empty, and the walk reads what is there. Where no store resolves at all, the exit is `1`, with
the resolver's reason. Write a path that deliberately does not resolve in *italics*.

**Writes** nothing.

---

## `stayfixed init --yes [--dry-run] [--name NAME] [--base-branch BRANCH] [--agent NAME …] [--profile NAME] [--memory-mode MODE] [--attribution-check] [--commit-type TYPE …] [--local ID …] [--no-ci] [--root PATH] [--machine PATH]`

Writes a repository's stayfixed scaffold, once. It is the only command that creates the
documents every other command reads, and the only one that writes `stayfixed.toml`.

**`--yes` is required, and it means "take the defaults `stayfixed init --questions` shows".**
Without it nothing is written, and the refusal (`2`) names `--questions`.

Each answer flag replaces one default and writes one key:
- `--name` writes `[project] name`;
- `--base-branch` writes `[project] base_branch` and `release_branch`; `[ci] gate_branch`,
  left out, is that branch, so the workflow gates the branch pull requests merge into;
- `--agent`, once per harness, writes `[stayfixed] agents`;
- `--profile` writes `[stayfixed] profile`, an empty value meaning none;
- `--memory-mode` writes `[memory] mode`;
- `--attribution-check` writes `[commit_messages] attribution_check = true`, which is off unless
  answered;
- `--commit-type`, once per type, writes `[commit_messages] types`, each lowercase ASCII letters;
- `--local`, once per file, writes `[artifacts] local`.

`--no-ci` answers the CI question (below). The recommended plugins are not `init`'s to install:
`init --questions` asks about them, and the answer is `stayfixed setup`'s.

After the CI line the run prints `picked:`, one line per question in the order
`init --questions` asks them, with the value this run took: the name, the base branch, the memory
mode, the profile, the CI mode, the attribution check (`on` or `off`), the commit types, the
files kept out of git, the agents stayfixed serves among those listed, and `plugins: none`, since
`init` installs none. Taking every default gives the attribution check `off`, the preset's commit
types and no plugin. A value a `stayfixed.toml` you wrote holds outside the plain-path grammar
prints as `<unprintable; see stayfixed.toml>`.

The parser refuses a value outside its grammar or its choices (`2`), and it refuses a name or
a branch by naming the rule, never the value. A branch is a name git accepts as one, written in
letters, digits, `.`, `_`, `-` and `/` and led by a letter or digit: no `..`, `//`, component
starting with `.` or ending in `.lock`, no trailing `/` or `.`, and not `HEAD`. The same
grammar holds `[ci] gate_branch` and a detected base branch. Answer flags reach only a
`stayfixed.toml` this run creates. Over one the repository already has, they are refused
(`2`), because that file is the answer. Passing a default as its flag loads as the same
configuration as not passing it.

When nothing answers, `init` detects:
- the project's name from `origin`'s last path segment, lower-cased and with `.git` stripped,
  else from the checkout's directory name;
- the base branch from `refs/remotes/origin/HEAD`, read as the full ref with exactly
  `refs/remotes/origin/` stripped, when that is a plain branch name, else `main` with a `note:`
  saying so. A repository with a remote and no `origin/HEAD` — one created locally and pushed,
  until `git clone`, `git remote set-head`, or a `git fetch` from git 2.48 on records one, or one
  whose only remote is another name, such as `upstream`, pushed or cloned with `-o upstream` —
  gives `main`, with a `note:` naming `--base-branch`, and `git remote set-head origin --auto`
  where the remote is `origin`: the branch checked out there is typically the feature branch the
  adoption is made on. Where git cannot list the remotes, it gives `main` with a `note:` saying
  so. Only with no remote at all is it the branch checked out, when that is a plain branch name,
  with a `note:` when it is not `main`, else `main`. The workflow gates the same branch, since
  `[ci] gate_branch` left out is the base branch;
- the agent surfaces from which of `.claude/` and `.codex/` the repository carries, both when
  it carries neither;
- `[stayfixed] profile` from the first shipped profile whose markers sit at the root
  (`python`: `pyproject.toml`, `setup.py`, `setup.cfg`, a requirements file, a `Pipfile` or a
  lockfile), written only when one is found.

Both name candidates, the remote's segment and the directory name, are repository-authored.
So one outside `[project] name`'s grammar is refused naming the grammar and the remedy, and
never the value, unless `--name` answers it. With a `stayfixed.toml` you wrote, the file answers
it: one with no `[project] name` fails (`1`) with the loader's own sentence, whatever the
repository suggests.

**A `stayfixed.toml` you wrote is the answer sheet, not an obstacle.** Every key it carries is
read and kept: the name, the paths, the memory mode, the budgets, the gates. The file itself
is not replaced. It is a create-once artifact, so a repository that already has one is
reported `skip_modified` ("create-once, and the file is already there").

The one change is a missing `[stayfixed] version`, the only key stayfixed owns that the loader
requires. This run writes it into the file in place, leaves every other line as it was, and
says so in a `note:` line.

The file is then checked as it will be on disk, that key included, before anything is
written. One the next command could not load fails (`1`) with the loader's own sentence, and
nothing is written: no `[project] name`, a `[stayfixed] state` line (a key stayfixed no longer
has, which the loader refuses as any unknown key), or an `enforced` list naming a gate the project
does not run, or one gate twice.

The paths it declares are where the scaffold lands. A repository with no `stayfixed.toml` gets
one written from the detected values and your answers, headed by a comment naming the three
keys that are stayfixed's to rewrite: `[stayfixed] version` and `enforced`, and `[ci] ref`. A file that cannot be read, is not UTF-8 text or is not valid TOML is a failure
(`1`) naming the file. A repository that already carries `.stayfixed/manifest.json` is refused
(`2`): re-running `init` is `stayfixed upgrade`. `stayfixed uninstall` later keeps a
`stayfixed.toml` you wrote, the version line included. When that file configures
`[gates.custom]`, a `note:` names those gates, up to eight and then a count, and says that
`stayfixed assess`, `stayfixed gate` and `stayfixed adopt promote` run their commands: in a clone,
those are commands the clone wrote, and the dry run you read before `--yes` says so. The
commands themselves never print.

**Two passes, both planned before either is applied.** The three write-once files are one pass
and the rest of the scaffold is the other, because two artifacts cannot target one file in one
pass and both the `AGENTS.md` skeleton and its `harness` region land on `AGENTS.md`. A refusal
in either plan stops the run with nothing written and no manifest, and `--dry-run` is that same
branch rather than a second code path — it reports both plans and writes nothing. On a
repository with no `AGENTS.md` the dry run plans the region as a *create* of a region-only file
and the real run re-plans it as a *region_update* into the skeleton the first pass has just
written; the report carries one fixed sentence saying the bytes inside the markers are the same
either way.

| id | pass | kind | target | what it holds |
|---|---|---|---|---|
| `config` | write-once | once | `stayfixed.toml` | the document this run rendered |
| `agents-skeleton` | write-once | once | `[paths] agents_md` | a skeleton headed with the project's name, stating this project's own budgets |
| `claude-md` | write-once | once | `CLAUDE.md` | a one-line pointer at `[paths] agents_md`, whatever that file is called |
| `documentation-policy` | scaffold | template | `<architecture>/documentation.md` | where each kind of fact belongs |
| `adr-template` | scaffold | template | `<adr>/0000-template.md` | the four-heading decision record |
| `ledger-runbook` | scaffold | template | `<runbooks>/bug-reports.md` | how to file, close and reference an entry |
| `ledger-audits` | scaffold | template | `<bugs>/audits/README.md` | what an audit record is |
| `bug-index` | scaffold | template | `[paths] bug_index` | the generated index, rendered empty |
| `roadmap` | scaffold | template | `[paths] roadmap` | `Now`, `Next`, and the trail block |
| `roadmap-history` | scaffold | template | `[paths] roadmap_history` | an empty history |
| `trail` | scaffold | template | `trail.toml` beside the roadmap | one theme, no declared states |
| `specs-keep`, `plans-keep` | scaffold | template | `<specs>/.gitkeep`, `<plans>/.gitkeep` | nothing, so the trail lists no documents |
| `gitignore` | scaffold | managed region | `.gitignore` | `.stayfixed/local/` and `.stayfixed/assessment.json` |
| `agents-md` | scaffold | managed region | `[paths] agents_md` | which paths this repository's stayfixed uses |
| `ci-workflow` | scaffold | template | `.github/workflows/stayfixed.yml` | the pinned call to the reusable gate |
| `profile-rules` | scaffold | template | `<stayfixed>/rules/<profile>.md` | the profile's rules, the one copy a project edits; only with `[stayfixed] profile` set |
| `claude-rules` | scaffold | template | `.claude/rules/stayfixed-<profile>.md` | a `paths:`-scoped pointer at `profile-rules` for Claude Code; only when `[stayfixed] agents` lists `claude` |

With a profile set, the `agents-md` region also names the profile's rules file and lists the
lines under its *Before the first command* heading, so every harness that reads `AGENTS.md` has
them before its first command. A name in `[stayfixed] agents` that no harness answers to is
counted in a `note:` line and never printed.

**`--local` offers four files.** `documentation-policy`, `adr-template`, `ledger-runbook` and
`roadmap-history` may be kept out of git, under `.stayfixed/local/artifacts/`, and every gate
still passes. The others are not offered:
- `bug-index`, `ledger-audits`, `roadmap` and `trail` are read by a gate at their committed
  paths. The index would read as stale, the ledger directory would be missing, the roadmap
  absent, and a trail kept out of git would be silently ignored.
- `specs-keep` and `plans-keep` have no purpose outside git.
- `config` and `gitignore` work only at the root.
- `CLAUDE.md`, the `AGENTS.md` skeleton and its region, the workflow, and the profile's rules
  and Claude's pointer are read where they are committed.

A `stayfixed.toml` you write may still list any id but `config`, `gitignore` and the profile's
own. `--local` offers only these four.

**The workflow pins what `[ci] ref` says, and nothing else.** The rendered file calls
[the reusable workflow](#the-reusable-workflow) at the ref `stayfixed.toml` carries *after this
run*, and those two are one value by construction — which is the invariant `stayfixed doctor`'s
`ci-ref` row enforces from the other side ("the workflow pins a different ref from `[ci] ref`,
so the gate that runs is not the one recorded"). On a repository this run creates the document
for, the ref is the commit of the stayfixed release running, asked of the public repository's own
`v*` tags and written into `[ci] ref` beside the workflow. On a repository that already had a
`stayfixed.toml`, that document's `[ci] ref` is not rewritten — all `init` may add there is a
missing `[stayfixed] version`, with its `[stayfixed]` header when the file has none — so the workflow
pins the ref **it** records, and `doctor` judges whether that is a released commit, which is its
job.

Seven states cost the artifact rather than the run, each reported under `skipped` with one
sentence: `[ci] mode` is `none`; `[ci] mode` is `uvx`, whose form of the gate has not shipped; the
public repository could not be asked for its tags; no released tag matches the stayfixed running,
which is every repository's state before the first release; the `stayfixed.toml` this repository
already had records no `[ci] ref`, so there is nothing a workflow could pin that anything records;
`[ci] ref` is not a full-length commit sha, which is the only immutable form and the only one
`init` renders — the mutable `v1` alias, from `1.0.0` on, is a file you write by hand, and until
then a `0.x` project pins the commit; and `[ci] gate_branch` is not a plain branch name. `--no-ci`
is the first of those on purpose: it puts `[ci] mode = "none"` into the document this run builds
and asks no remote anything. **On a repository that already has a `stayfixed.toml` the flag governs
this run and nothing more** — that document is a create-once artifact, reported `skip_modified`, so
the file still says whatever it said and the next `init` would ask the remote again. Writing `none`
there is yours to do.

**The two states about the remote are reported only on a run that creates the document.** On the
adoption path the answer is the fifth one whatever the remote said, because it is the whole
reason: a pin this run resolved would be written into a create-once file that is already there,
so nothing would record it. Reporting "run `stayfixed init --yes` again with the network
reachable" there would send you back to a command that cannot help — by the time you read it,
`.stayfixed/manifest.json` exists and `init` refuses to run again at all. `stayfixed upgrade` is
the command that can: `[ci] ref` is one of stayfixed's keys in any `stayfixed.toml`, so it records
a released commit there in place and renders the workflow around it. On a run that created the
document, the unreachable remote's sentence names both remedies: `stayfixed init --yes` with the
network reachable while nothing is written yet, and `stayfixed upgrade` once it is.

**Reads** `stayfixed.toml` when there is one, `.stayfixed/manifest.json`, `git` for the name
and the base branch and for the public repository's tags, which harness directories the root
carries (`.claude/`, `.codex/`), each shipped profile's marker files at the root, every file
an artifact targets, and `git check-ignore` for each existing file a write targets at a place
a `[paths]` value chose.

**Writes**, every one of them through the scaffold engine or `stayfixed.toml`'s key editor, so
that every target goes through the containment walk and none may leave the project root or
pass through a symlink:
- `stayfixed.toml`, or only its missing `[stayfixed] version` when you wrote it;
- `CLAUDE.md`, `[paths] agents_md` and `.gitignore`;
- the documents in the table above (the profile's rules only when a profile is set, and the
  Claude pointer only when a profile is set and `[stayfixed] agents` lists `claude`), each at its
  place in the table, except that a document `[artifacts] local` lists is written under
  `.stayfixed/local/artifacts/` at that place instead;
- `.github/workflows/stayfixed.yml`, where a ref is recorded;
- `.stayfixed/manifest.json`;
- `.stayfixed/local/artifacts.json`, when `[artifacts] local` lists anything.

Exits `0` on success. `1` on a finding: either plan carries refusals — the report's REFUSED section
names each, nothing was written and no manifest exists — or a `stayfixed.toml` that cannot be read,
is not UTF-8 text or is not valid TOML, or the merged document the loader itself refuses (an unknown
section or key, a `[project] name` outside its grammar, a value of the wrong type, a machine
configuration file that does not load), or a `stayfixed.toml` you wrote that, with its version, the
loader would refuse on the next command's load. `2` on a refusal above the plans: no `--yes`, an
answer flag over an existing `stayfixed.toml`, an answer outside its grammar or its choices (from the
parser), a repository already initialised (with `--local`, the refusal also says to list the id
under `[artifacts] local` and run `stayfixed upgrade`), a detected name outside the grammar that no
`--name` answers, a `[stayfixed]` table the key editor cannot add a version to, a `stayfixed.toml`
that is a symlink, which is never followed, a `[paths]` value outside the plain-path grammar, naming
git's control directory or stayfixed's own `.stayfixed/`, or reaching through a component that is a
symlink — all three refused by the loader before a plan exists — two artifacts, of one pass or of
either, that resolve to one file (`roadmap` and `roadmap_history` set to one path, or `roadmap =
"CLAUDE.md"`), which is named with the two artifacts and their `[paths]` keys to separate, since
only the `AGENTS.md` skeleton and its region share a file by design, an `[artifacts] local` list
naming a profile artifact, which every pointer at it reads at its committed path, one naming
`config` or `gitignore`, which only work at the repository root, and a write git would hide, at an
existing file a `[paths]` value chose, which the refusal names, or one inside a repository whose
`git` cannot say whether it is ignored (see `upgrade`'s boundary).

`--json` carries `dry_run`, `adopted`, `once` and `scaffold` (each the plan's own rendered
report), `writes` (both plans' targets), `skipped`, `pin` (the release this run resolved,
`{tag, sha}` or `null`), `asked`, `note`, `ref` — what `[ci] ref` says on disk after the run
and so what the workflow pins, empty when no workflow was planned — `stamped`, whether this
run's plan adds `[stayfixed] version` to a `stayfixed.toml` you wrote — written only by a run that
is neither a dry run nor refused — `unknown_harnesses`, how many names in `[stayfixed] agents` no
harness answers to, and `head_note`, the `note:` line that says `main` replaced an
`origin/HEAD` outside the plain-branch grammar (the branch it named is never printed), that
`main` stands because a remote is there and no `origin/HEAD` is recorded, or because git could
not list the remotes, or that, with no remote, the branch checked out other than `main` became
the base branch; empty otherwise. An answered `--base-branch` replaced nothing, so it leaves
`head_note` empty.
`custom_gates` lists the custom gates a `stayfixed.toml` you wrote configures, by name, and is empty
when this run writes the file.

---

## `stayfixed init --questions [--root PATH] [--machine PATH]`

Prints the values `stayfixed init --yes` would take for the ten things a person may answer, where
each came from, and the flag that replaces it: on `init --yes`, but for the recommended plugins,
which `stayfixed setup` installs on the machine. It writes nothing. The `init` skill asks its
questions from it, taking every default offered first, and a person reads it to see the defaults
before choosing any.

The summary is one line per question, `<key>: <default> (<where it came from>; <flag>)`, then
one line saying how each is answered:

```text
detected:
  project.name: widget (origin remote; --name)
  project.base_branch: main (origin/HEAD; --base-branch)
  memory.mode: harness (default; --memory-mode)
  stayfixed.profile: python (profile markers; --profile)
  ci.mode: reusable (the preset's default; --no-ci)
  commit_messages.attribution_check: off (the preset's default; --attribution-check)
  commit_messages.types: feat, fix, build, chore, ci, docs, perf, refactor, revert, style, test (the preset's default; --commit-type)
  artifacts.local: none (the preset's default; --local)
  stayfixed.agents: claude, codex (default; --agent)
  plugins: none (default; stayfixed setup --plugin)
each is answered by the flag its line names, on `stayfixed init --yes` but the plugins'; `stayfixed init --questions --json` carries them as a JSON Schema, each with what it gives, what it gives up, what it leaves and how to undo it
```

Where a value came from is one of a fixed set of phrases. The name comes from the
`origin remote`'s last path segment or, with no origin, the `directory name`; when that one is
not a lowercase path segment the source is `not derivable`, and the value prints as
`none; asked`, never as what the repository suggested. The base branch comes from `origin/HEAD`
when that names a plain branch under `refs/remotes/origin/`; with no remote at all, from the
`current branch` when that is a plain branch; otherwise, a remote with no `origin/HEAD` and
remotes git could not list included, it is the `default`, `main`. The agents come from the `harness
directories` the root carries; otherwise the `default` is every harness. The profile comes from
`profile markers`, or there are `no profile markers`. The memory mode is the `default`,
`harness`, since the preset chooses none; the CI mode, the attribution check (off), the commit
types and the files kept out of git are `the preset's default`; and the plugins are the `default`,
none, because a third-party plugin runs in every session and is installed only when named. Each
default is exactly what `stayfixed init --yes` writes when that question is not answered. `origin/HEAD` goes stale after the remote's default branch is
renamed, because git does not refresh one it has. That is why its source is printed: you can
catch it.

`--json` carries `questions`: a JSON Schema object (draft 2020-12) with ten `properties`, and
`required` naming all ten in the order the `init` skill asks them; read the order there, since
`--json` prints every object's keys sorted, so the properties arrive by name. Each but the last is
keyed by the
`stayfixed.toml` key its answer writes: `project.name`, `project.base_branch`, `memory.mode`,
`stayfixed.profile`, `ci.mode`, `commit_messages.attribution_check`, `commit_messages.types`,
`artifacts.local` and `stayfixed.agents`; the last, `plugins`, offers the plugins the preset
recommends, which `stayfixed setup --plugin` installs. Each property carries four keys: `default`
(absent for a name that is not derivable), `x-stayfixed-source` (the phrase above),
`x-stayfixed-flag` (the flag that answers it) and `x-stayfixed-tradeoff`, four lines of fixed
text: `get`, what the answer gives; `give_up`, what it costs; `trace`, what it leaves behind; and
`undo`, how to take it back. A choice is a `oneOf` of `const` and `title`, `items.enum` for a list
of choices, or `boolean`. The two free-text properties and each commit type carry `pattern`, the
grammar their flag enforces.

The schema is modelled on MCP elicitation's flat form schema. A client may send it as a
`requestedSchema` once it drops `pattern` and the `x-stayfixed-*` keys, which that subset does not
carry. Harness ask tools take lists of questions and options rather than a schema, so the `init`
skill turns the properties into questions: every default at once first, then the name and the
base branch as one confirmation, the rest one at a time with their four lines, within each
harness's limits. The flags validate the answers; the schema
does not.

It is refused (`2`) before anything beyond the root is read, in three cases:
- the repository already carries `.stayfixed/manifest.json`: re-running `init` is
  `stayfixed upgrade`;
- it carries a `stayfixed.toml`, which answers these questions itself: edit it, then read the plan
  with `stayfixed init --yes --dry-run`;
- any flag is given but `--root`, `--machine` and `--json`.

`--yes` beside it is a usage error from the parser.

**Reads** `git` for the name and the base branch, which harness directories the root carries, each
shipped profile's marker files at the root, and the machine configuration, to learn whether it
records an overlay. A machine file that does not load reads as "not recorded"; `init` reports it
when it loads it.

**Writes** nothing.

Exits `0` with the questions printed; `2` on a refusal.

---

## `stayfixed upgrade [--dry-run] [--force PATH]… [--root PATH] [--machine PATH]`

Refreshes a repository's scaffold after a stayfixed update, keeping every hand edit. It moves
`[stayfixed] version` to the stayfixed running, re-plans every scaffold artifact against
`.stayfixed/manifest.json` by hash, and never re-plans the write-once files: `stayfixed.toml`,
`CLAUDE.md` and the `AGENTS.md` skeleton are yours after `init`.

`--dry-run` reports everything and writes nothing. `--force PATH` overwrites or removes one file the
report named `skip_modified`, as a path relative to `--root` exactly as the report prints it; repeat
it for each file. It reaches a file you edited, one stayfixed never wrote, and a changed or
unrecorded copy under `.stayfixed/local/artifacts/`, but not a file left at an artifact's old place
(`relocated and hand-edited`, or a recorded target the artifact cannot produce): that one is yours
from then on, to keep or delete by hand. A leading `./` is dropped, and an absolute path or one with
a `..` component is refused (`2`) naming the rule. A forced path no planned action names — a typo, a
case difference, or a file with nothing to force — is counted in a `note:` line and forces nothing.

**Four verdicts.** A file whose bytes are still the ones the manifest records is refreshed
(`update`, or `region_update` for a managed region) when this stayfixed renders it differently,
and reported `unchanged` when it does not. One that is missing is created. One you edited is
`skip_modified` and named, and stays as it is until `--force` names it. So is a file stayfixed
never wrote at a path it would write (`exists and stayfixed did not write it`); forced, it is
overwritten and recorded, and later runs judge it like any file stayfixed wrote. An artifact this
configuration no longer produces is removed while its bytes are the ones recorded (`remove`),
and skipped the same way when they are not. One whose file is already gone is listed
`remove … (retired, already gone)`: nothing is removed, and its record is dropped, so it is not
carried into every later run.

**What is rewritten in `stayfixed.toml`, and what is not.** Only the values stayfixed owns:
`[stayfixed] version` and, under `[ci] mode = "reusable"`, a `[ci] ref` that is a commit sha or
empty. Every other byte stays where it was — comments, order, blank lines, your keys. A key written
in a shape the editor does not rewrite in place (a dotted key, an inline table, a multi-line value)
is refused (`2`) naming the key and the line to write by hand, before anything is written. When the
manifest's `config` record still describes the file, it is re-stamped with the new bytes; when you
have edited the file, it is not, so `stayfixed.toml` stays yours.

**Version, `[ci] ref` and the workflow's pin move together or not at all.** Under
`[ci] mode = "reusable"` the workflow pins stayfixed by commit, so `[stayfixed] version`, `[ci] ref`
and the `uses:` line in `.github/workflows/stayfixed.yml` are one value. When no released commit
of the stayfixed running is found — before its tag exists, or with the network unreachable — or
when the workflow would not be rewritten to the new pin, neither key moves: a `note:` line says
`[stayfixed] version` and `[ci] ref` were left as they are and why, and the rest of the scaffold
is still refreshed. A workflow you edited by hand, or one stayfixed never wrote, is reported
`skip_modified` and moves with them only under `--force` with the path the report prints for it.
When the report refuses the workflow, or the `CI:` line says none was rendered (a `[ci]
gate_branch` outside the branch-name grammar, say), no flag moves them: the note says to put
that right and run `stayfixed upgrade` again. The `CI:` line says the workflow pins `[ci] ref` only
when this run created it, refreshed it or found it current; a workflow the report lists
`skip_modified` or refuses was left as it is and may pin anything, and the line says so.

**A `[ci] ref` that is not a commit is yours.** The `v1` alias, documented from `1.0.0` on, or any
other value that is not a full-length sha, is a choice to track a moving stayfixed, so `upgrade`
moves `[stayfixed] version` alone: it never replaces that ref with a sha, and never renders a
workflow over the one you wrote around it. The `CI:` line says no workflow was rendered around the
ref.

**A project recording a newer stayfixed is refused** (`2`), before anything is written: an older
plugin would repin an older release and put older bytes over newer ones. The recorded version is
read by its leading `X.Y.Z` first, so `1.0.0-rc1` is newer than a running `0.9.0`; with the same
`X.Y.Z`, a release is newer than its own pre-release, so a project recording `1.0.0` is refused
by a `1.0.0rc1` build. Update the stayfixed plugin, then run `stayfixed upgrade` with it; never edit
`[stayfixed] version` to get past it. A recorded version with no leading `X.Y.Z`, such as
`v1.0.0`, is refused too, because which way a move would go is unknown; set it to the release
the project was last upgraded with. So is one sharing the running `X.Y.Z` and differing after it
in a way stayfixed does not order — two pre-releases, such as `1.0.0rc1` and `1.0.0rc2`, or a
post-release — and that refusal names the version running: set it to that by hand if it is the
release the project should move to.

**An artifact kept out of git is recorded out of git too.** One listed in `[artifacts] local` lives
under `.stayfixed/local/artifacts/`, and the committed manifest never records it; instead
`.stayfixed/local/artifacts.json`, which the ignore block keeps out of git like the artifacts,
records the bytes stayfixed last wrote there. A file still holding those bytes is refreshed like any
other when this stayfixed renders it differently. One that no longer does is `skip_modified` (`kept
out of git, and changed since stayfixed wrote it`), because nothing brings it back once it is
overwritten, and `--force` with its path takes it; with that record gone, a file that is not exactly
what this build writes is skipped the same way, saying nothing records what stayfixed wrote there.
When an id leaves `[artifacts] local`, or its `[paths]` value moves while it stays there, the
artifact is written at its new place and the copy the record names at the old one is removed while
it holds exactly the bytes recorded for it (`relocated`); otherwise it is `skip_modified`, stays
recorded until it is gone, and `--force` with its path takes it. When an id joins the list, the copy
at its old place is the committed one the manifest records, and it is removed the same way while it
holds exactly the bytes the manifest records (`relocated`); one you edited is left where it is,
yours to keep or delete by hand, and said once, as `relocated and hand-edited`: the manifest stops
recording it, so the next `upgrade` says nothing of it while the tracked copy stays. That is how a
file is kept out of git after `init`: `init --local` is refused once the repository is initialised,
and the refusal says to list the id under `[artifacts] local` and run `stayfixed upgrade`. The
record is read as untrusted, since a clone can commit it anyway: anything but its own exact shape is
read as no record at all, it is never printed, it names nothing outside
`.stayfixed/local/artifacts/`, and it vouches only for a file there whose bytes are exactly the ones
it states.

**Retirement.** An artifact this configuration no longer produces — the profile's rules after
`[stayfixed] profile` changes, its Claude Code pointer after `agents` drops `claude` — is removed
only at a target this build could have written for it, and only while its bytes are the ones
recorded. The workflow is removed only when `[ci] mode` is `"none"`; a mode this build does not
render, such as `uvx`, is not a request to delete the gate. Every other record in the manifest is
counted in a `note:` line and left where it is, and never named, as is a record saying its
artifact lived inside a file (a region) that this build no longer produces: a region comes out
only through the template that names it, never as a whole file, which is `uninstall`'s rule too.

**The boundary.** Which artifacts exist, and where each could be, are this build's. The `[paths]`
value a target is built from and the digest a record carries are committed. For a whole file, a
commit can make `upgrade` rewrite it only while it holds exactly the bytes the same commit records,
`--force` aside: that overwrites a whole file whatever it holds, one nothing records included, but
only at a path given exactly on the command line, which no commit can supply. A managed region is
inserted into whatever file its key names: a commit that points `[paths] agents_md` at another
tracked file gets the region written into that file, and the diff shows both the edit and the
region. No `[paths]` value may name git's control directory or stayfixed's own `.stayfixed/`, where
attach's ledger and the local-only notes live out of git's sight; the loader refuses either, naming
the key. And a committed `[paths]` value cannot put a write or a removal where git would hide it:
the run is refused (`2`) before anything is written, dry run included, when all three of these hold
for a file it would write or remove — the file exists, git ignores it, and it is at a place a
`[paths]` value chose rather than where the preset puts that artifact. The refusal names each such
file, as the report prints paths, and says to point the key at a path git does not ignore or take it
out. A new file, a fixed name (`CLAUDE.md`, `stayfixed.toml`, `.gitignore`, the workflow, a harness's
rule) and a preset's own place are never refused, so a `CLAUDE.md` in your global excludes or a
`stayfixed.toml` in `.git/info/exclude` works as before. A tracked file that matches an ignore
pattern is not ignored, because git shows every change to it; the artifacts `[artifacts] local`
keeps under `.stayfixed/local/artifacts/` are exempt, since keeping them out of git is what that
setting asks for; and outside a git work tree there is no guard, because there is no diff to hide
from. Inside one (a `.git` in the root or a directory above it), a `git` that cannot answer refuses
the run (`2`) before anything is written, dry run included, and the refusal says to run it again
once `git check-ignore` works: one that timed out, is not installed, or failed on the batch. A
repository can cause the first and the last: git reads every `.gitignore` along each
path it is asked about, so a deep enough path under large enough ignore files outlasts its time
bound, and git answers a whole batch with exit 128 when one path in it lies inside a submodule.
Run it on a checkout you trust. There are no hooks to re-trust afterwards: `init` writes no project-level hook
entries, so an upgrade changes none.

**Reads** `stayfixed.toml`, `.stayfixed/manifest.json`, `.stayfixed/local/artifacts.json`, every
file an artifact targets, `git check-ignore` for each existing file a write or removal targets at
a place a `[paths]` value chose, and, under `[ci] mode = "reusable"`, the public repository's
tags.

**Writes** the scaffold through the scaffold engine — every `create`, `update`, `region_update`,
`remove` and `relocated` in the report, and each file `--force` takes — then
`.stayfixed/manifest.json`, the committed record, written even when a write or removal fails
part-way, and `.stayfixed/local/artifacts.json`, the record kept out of git, only when what it
records changed; then `stayfixed.toml`, last (with `.stayfixed/manifest.json` again when its
`config` record is re-stamped), so the version is the commit point: a run interrupted before it
leaves the old version recorded, and the next run re-plans from there. Under `--dry-run`,
nothing.

Exits `0` when it applied the plan or there was nothing to do. `1` on a finding: the plan carries
refusals — the report's REFUSED section names each, and nothing was written — or a `stayfixed.toml`
that does not load, as for every command. `2` on a refusal before any write: the repository is not
initialised, `stayfixed.toml` is missing, it records a newer stayfixed, a version with no leading
`X.Y.Z` or one stayfixed does not order against the running one, a key is written in a shape the
editor refuses, two artifacts resolve to one file (named by artifact and `[paths]` key, as `init`
names it), a profile artifact, `config` or `gitignore` is listed in `[artifacts] local`, git ignores
(or inside a repository cannot say whether it ignores) an existing file the run would write or
remove at a place a `[paths]` value chose, or a `--force` path leaves `--root`. `2` also when a file
cannot be written or removed part-way through; what was already applied stays applied and recorded,
and running the command again re-plans from there.

`--json` carries `dry_run`, `moved` (each `{key, before, after}`; a `before` outside its grammar
prints as `(not a version)` or `(not a commit)`), `held` (the note's sentence, or empty),
`scaffold` (the plan's rendered report), `writes`, `skipped`, `orphans` (a count), `pin`
(`{tag, sha}` or `null`) and `asked`.

---

## `stayfixed uninstall [--dry-run] [--force PATH]… [--root PATH] [--machine PATH]`

Takes back what `init` and `upgrade` wrote. A file whose bytes are still the ones the manifest
records is removed; stayfixed's managed regions come out of files that hold other text, and such a
file goes too only when nothing else was in it; the ledger goes last. A file you edited stays
where it is, is reported `skip_modified` with its reason, and is counted in a `left in place`
line. Every recorded artifact is judged, including one this configuration no longer produces, at
a target this build could have written for it, whatever `[ci] mode` says now: the workflow goes
under `uvx` too. Any other record is counted in a `note:` line and left where it is, and never
named, as is a record saying its artifact lived inside a file (a region) that this build no longer
produces: a region comes out only through the template that names it, never as a whole file.

`--dry-run` reports everything and writes nothing. `--force PATH` removes one file the report named
`skip_modified`, as a path relative to `--root` exactly as the report prints it; repeat it for each
file. It reaches what `upgrade`'s `--force` reaches, and likewise not a file left at an artifact's
old place (`relocated and hand-edited`), which is yours to keep or delete by hand. The path rules
are `upgrade`'s: a leading `./` is dropped, an absolute path or one with a `..` component is refused
(`2`), and a forced path no planned action names is counted in a `note:` line and forces nothing.

**Two passes, the scaffold first.** The scaffold pass removes files and takes the regions out;
a region taken out of a file that keeps other text is reported as
`remove  AGENTS.md  (retired; stayfixed's part only, the file stays)`, and a line without that
tail means the file itself goes. Every command that prints a plan says it the same way.
The write-once pass (`stayfixed.toml`, `CLAUDE.md` and the `AGENTS.md` skeleton) is planned again
after it, so the skeleton is judged once stayfixed's region has left `AGENTS.md`: untouched, it is
byte for byte what `init` wrote and goes. A dry run cannot take the region out first, so it
judges the skeleton with the region still in it and calls it edited; a `note:` line says so.
**Forcing `AGENTS.md` takes stayfixed's region out of it and never the skeleton**: a forced path
the scaffold pass targets never reaches the write-once pass, compared as the engine places each
file, so what you wrote into the skeleton is judged on its own bytes.

**The ignore block goes last, and only over an empty `.stayfixed/local/`.** The `.gitignore` region
is what keeps `.stayfixed/local/` out of git: attach's ledger, the local-only memory notes, and the
artifacts `[artifacts] local` keeps out of git. So it is taken out in a pass of its own, after the
disk shows nothing left under `.stayfixed/local/`. Every directory above a file a pass removed goes
once it is empty, deepest first, and so does every empty directory under
`.stayfixed/local/artifacts/`, stayfixed's own, which no `[paths]` value reaches; no other goes: an
empty directory a `[paths]` value merely names may be yours. Then `stayfixed.toml`, which the
write-once pass holds back for this point; then the ledger: `.stayfixed/assessment.json`,
`.stayfixed/manifest.json`, and `.stayfixed/local/` and `.stayfixed/` once each is empty. A directory
someone committed where a ledger file belongs stays. So does a harness's own directory
(`.claude/`, `.codex/`, or the same name in any other case), even when it is empty, whoever made it:
`init` may have created `.claude/` to hold the rule it wrote there, but nothing records who made an
empty directory, and to `init` its presence means the project uses that harness. So a later `init`
detects that harness and lists it in `[stayfixed] agents` until you remove the directory.

**An attached repository is detached first.** When `attach`'s ledger is in this checkout or in the
main checkout, where `attach` keeps it from every worktree, and the render `attach` writes for the
repository's binding id is in `~/.local/share/stayfixed/delivery/`, outside the work tree where no
commit reaches, the run asks every refusal below, then
runs [`stayfixed detach`](#stayfixed-detach---root-path---machine-path) before its first write,
which withdraws what `attach` placed, the overlay's plugin and the allow rules among it, and takes
the ledger; a `note:` line says so, and a dry run says it would. A run whose plans refuse stops
before `detach`, and neither it nor its dry run says it detached or would. A `detach` that refuses
or stops part-way stops the run there with nothing of its own done, its own sentence and exit code
given.
While the render is still there, running `uninstall` again finishes from what is left. A `detach`
that stopped after removing the render, or an `attach` that stopped after writing its ledger and
before the render, leaves the ledger with no render, which the next `uninstall` refuses as below:
run `stayfixed detach`, which finishes from the ledger, then `uninstall`. The ledger is not counted
among the files `.stayfixed/local/` holds while the repository is attached. A ledger with no
render, which a clone can commit and a pull request can commit after a `detach`, detaches nothing:
it is a file the run would not remove, and refused as one, so run `stayfixed detach` over a ledger
only when your own `attach` wrote it.

**Refused before any write** (`2`): the repository is not initialised; `stayfixed.toml` is missing
while the manifest records it, so restore it; `[artifacts] local` names `config` or `gitignore`, which only work at the repository root, so
take them out of the list; two artifacts resolve to one file, named as `init` names it;
`.stayfixed/local/` holds files this run would not remove, such as notes, or an artifact kept out of
git that changed since stayfixed wrote it, which the refusal counts and never names; git ignores an
existing file the run would remove or rewrite at a place a `[paths]` value chose, which the refusal
names; or a `--force` path leaves `--root`. The count is exact before anything is written, including
what taking a region out of a file kept out of git would leave behind; the record of what stayfixed
wrote there, `.stayfixed/local/artifacts.json`, is stayfixed's own and goes once nothing else is left,
before the ignore block. Every artifact it records is judged, a copy left behind when its id left
`[artifacts] local` or its `[paths]` value moved included, so an unedited one goes. Move the files
out; one the report lists `skip_modified` in a file of its own there can be named with `--force`
instead, but an `AGENTS.md` whose region and skeleton are both kept out of git shares one file, and
forcing it takes only the region, so a line you wrote into that skeleton has to be moved. A dry run
reports the count in a `note:` line instead of refusing, even when its plans also carry refusals, so
its report still lists the edited file.

**Refused part-way** (`2`): a file that cannot be written or removed, or files still under
`.stayfixed/local/` after the write-once pass, which the count before any write should already have
refused; move them out. What was removed stays removed and recorded, and `stayfixed.toml` and the
manifest are still there, because they go last, unless the last pass removed `stayfixed.toml` and
then could not write the manifest, which the next paragraph covers; so running the command again
finishes from what the first run left, to the same end as a run that was never stopped.

**Without `stayfixed.toml`, nothing the manifest records can be judged.** While the manifest still
records the file, the run is refused (`2`) before any write, dry run included: restore
`stayfixed.toml` (from git, for instance) and run it again. This command drops that record as it
removes the file, so the file was taken by something other than this command, or by a run of it that
removed the file and then did not rewrite the manifest, because it was killed in between or the
manifest could not be written; either way the restored file is judged like any other, and the run
then goes on to the end. When nothing records it — a run stopped between removing it and removing
the manifest, or a `stayfixed.toml` the project wrote itself before `init`, which `init` never
records — every recorded file stays, a `note:` line gives their count, and only the ledger goes, so
`init` and this command no longer refuse the repository. No other directory is pruned then, because
nothing says where the configuration put its artifacts. A `stayfixed.toml` you wrote before `init`,
which is there and recorded nowhere, is left as it is, with the keys stayfixed wrote into it; a
`note:` line says so, and `--json` carries `kept_config: true`.

**The boundary.** Which artifacts exist, where each could be and every region's name are this
build's. The `[paths]` value a target is built from and the digest a record carries are committed,
so a commit can make `uninstall` remove a whole file only while it holds exactly the bytes the same
commit records, and a region only where its key names; the diff shows both. No `[paths]` value may
name git's control directory or stayfixed's own `.stayfixed/`, and a symlinked `.stayfixed/` is
refused. An existing file git ignores at a place a `[paths]` value chose is never removed or
rewritten: the run is refused (`2`) before any removal, dry run included, by `upgrade`'s rule,
naming the files, and so is a run inside a repository whose `git` cannot answer, as `upgrade`'s
is. Take
stayfixed's part out of them by hand, or take the `[paths]` key out of `stayfixed.toml`; the run
then leaves those files where they are and lists them. That includes a file stayfixed itself
created at an ignored place a `[paths]` value chose (`roadmap = "build/roadmap.md"`
under an ignored `build/`, say): creating it was allowed because nothing was there, and by the time
`uninstall` runs it exists, so this refusal meets it, and taking the key out is the remedy that
finishes the run. A `CLAUDE.md` or `AGENTS.md` your own excludes ignore is taken back like any
other. Run it on a checkout you trust.

**What stays on the machine.** `uninstall` takes back one repository's scaffold, and what is the
machine's stays: the deny rules `stayfixed setup` added to the user settings file, and every
approval in `~/.config/stayfixed/trust.json`. `stayfixed trust revoke reviewed --subject KEY`, with a
key `stayfixed trust list --json` prints, withdraws one.

**Reads** `stayfixed.toml`, `.stayfixed/manifest.json`, `.stayfixed/local/artifacts.json`, every file
an artifact targets, `git check-ignore` for each existing file a removal targets at a place a
`[paths]` value chose, and what is under `.stayfixed/local/`; and, to tell whether the repository is
attached, `attach`'s ledger in this checkout and in the main checkout, which `git` names, the binding
id in the git common directory, and whether `~/.local/share/stayfixed/delivery/<id>/` is there. On an
attached repository, what `stayfixed detach` reads.

**Writes** only removals, and region removals, through the scaffold engine, and after each pass
the two records of what is left: `.stayfixed/manifest.json`, which every pass rewrites, whether or
not it finished, and `.stayfixed/local/artifacts.json`, the record kept out of git, which a pass
rewrites when it removed something that record names. Each pass also removes every directory
above a file it removed, once that directory is empty. After the write-once pass it removes
`.stayfixed/local/artifacts.json` and then prunes the empty directories it finds by walking
`.stayfixed/local/artifacts/`, deepest first, that directory included; after the last pass, the
ledger: `.stayfixed/assessment.json`, `.stayfixed/manifest.json`, then `.stayfixed/local/` and
`.stayfixed/`, each once it is empty. A harness's own directory is never removed. When
`stayfixed.toml` is gone and nothing records it, only the ledger is removed. On an attached
repository it first writes and removes what `stayfixed detach` does, which that section names,
`attach`'s ledger among them, and runs the same `claude plugin` commands, which write what Claude
Code records about the plugin. Under `--dry-run`, nothing.

Exits `0` when it applied the plans, including when every recorded file was edited and nothing
was removed but the ledger. `1` on a finding: a plan carries refusals — the report's REFUSED
section names each, and nothing was removed — or a `stayfixed.toml` that does not load; and on an
attached repository, a `detach` that fails as `stayfixed detach` does (`1`), part of what `attach`
placed withdrawn and nothing of the scaffold removed, which the next run finishes. `2` on the
refusals above, before any write or part-way; a repository with no `.stayfixed/manifest.json` is
one of them.

`--json` carries `dry_run`, `scaffold` and `once` (each the plan's rendered report), `left` (the
files left in place, each as the reports print it), `orphans` (a count), `note` (the dry run's
order note, or the missing-configuration count, or empty), `kept_locally` (how many files
under `.stayfixed/local/` the run would leave, on a dry run and on a run whose plans refuse; `0` on
a run that removed what it planned) and `kept_config`.

---

## `stayfixed overlay upgrade [--root PATH] [--dry-run]`

**`--root` must name an overlay, and that is checked before anything is planned.** It defaults
to `.`, and pointed at a directory that is not one this command used to create the overlay's
files there — `.gitignore` and `.github/workflows/scan.yml` among them — report them as work done
and exit `0`. An overlay is a tree whose identity record, `stayfixed-overlay.toml` at its root,
parses as TOML and holds `layout = 1`; the record also holds `requires`, the floor `stayfixed
doctor` and a session's first lines read, and nothing else. Anything else is refused (`2`) with
nothing written, and the refusal names the file and its two keys: an overlay made before the
record shipped carries plugin manifests instead, and no code migrates it, so its owner adds the
record by hand.

Brings an overlay up to date with the template a newer stayfixed ships. It is the project rule
and not a second copy of it: a skeleton file you have not touched is refreshed, one you have
edited is skipped and named, and the oracle is the digest `.stayfixed/manifest.json` recorded when
the file was written. An overlay is where your own rules live, so a silent overwrite here would
destroy the only copy of something. An overlay `setup --overlay create:` generated has no
`.stayfixed/manifest.json` (the template repository carries none), and an identity record you
added by hand has no entry in one, so neither is recorded as stayfixed's: a file there that differs
from this release's is skipped as `exists and stayfixed did not write it`.

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
`.stayfixed/manifest.json`. A file an earlier release shipped and this one does not, such as
`common/memory/README.md` or `hooks/hooks.json`, is not planned at all: delete it by hand. Exits
`0`; `1` when the report carries a REFUSED section, because nothing would be written while one of
those stands; `2` when `--root` is not an overlay, when the manifest itself cannot be trusted, or
when a write is refused by the containment walk.

---

## `stayfixed attach [--store PATH] [--project NAME] [--check] [--root PATH] [--machine PATH]`

Binds this repository to your private overlay, renders the hooks, skills and agents you keep there
into a local plugin and installs it, and, in overlay mode, points the harness at the composed store
of its notes. After it, a session in this
repository runs your overlay's hooks, skills and agents and reads your cross-project notes and this
project's own notes, and the allow rules you keep in the overlay are merged into
`.claude/settings.local.json`.

**`--store` is optional, and names one directory and nothing else:**
`<overlay>/projects/<project name>/memory`, where `<project name>` is the `[project] name` in this
repository's `stayfixed.toml`, or the project chosen below where it has none; without it that directory is derived from the overlay the machine
records, and passing it changes nothing. The overlay root itself is **not** taken from that path —
it comes from the `[overlay] root` your machine configuration records, which `stayfixed setup`
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
is blamed for it, and `stayfixed doctor`'s `attached` row warns about the same path rather than
offering to remove the ledger.

**A repository with no `stayfixed.toml` attaches too**, so a public clone you cannot commit to can
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
overlay's `common/stayfixed.toml`, its `projects/<name>/stayfixed.toml` once the binding is recorded
(a first attach reads it after recording, as for a repository with the file), and the machine
file, as a session resolves its preferences; so `memory.mode` is the preset's,
`harness`, unless an overlay file sets `overlay`. Where the repository has a `stayfixed.toml`, its
`[project] name` names the project and nothing above applies; `--project` beside it is refused
(`2`).

**The notes are composed only in overlay mode; the rest is delivered whatever the mode.** A
`stayfixed.toml` whose `memory.mode` is not `overlay` keeps its notes elsewhere, so for it `attach`
builds no composed store, writes no `autoMemoryDirectory` and makes no note directories in the
overlay, and does not ask the `memory.groups` containment below; where an earlier attach composed
them, it takes the recorded key and the composed store back, as `detach` does. It binds, merges the
allow rules, places the Codex rule files and renders and installs the plugin all the same. The mode
is the one the configuration resolves once the binding is recorded, so a `[memory] mode` the
overlay's project file sets applies from the first attach.

**One place per repository: the main checkout.** Claude Code reads the main checkout's
`.claude/settings.local.json` from every worktree, and writes a worktree's own answers into it, so
`attach` run from any worktree acts on the main checkout: it reads that checkout's `stayfixed.toml`
and writes its settings file, its `.codex/rules/` copies and its ledger. Nothing is placed in a
linked worktree, and a worktree created later needs no step of its own.

**`--check` writes nothing.** It reports the binding state — `unbound` or `bound` — with the
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
`$HOME/.local/share/stayfixed/delivery/<id>/`, which is what a session runs, and then each allow
rule this run merges. A hook's command and an allow rule that do not fit a plain name are printed
escaped, and cut to their first 120 characters and their length. `--json` carries the same lists
as `hooks_added`, `hooks_removed`, `skills_added`, `skills_removed`, `agents_added`,
`agents_removed` and `allow_added`, and no remote and no project of their own. A re-attach that
binds the checkout to another project than this machine's record named — a `[project] name`
renamed in a pulled commit moves every worktree's binding — says so on one line naming both.
`--check`'s line names no project.

**The overlay's hooks, skills and agents are delivered as a plugin.** Every run renders them into
`$HOME/.local/share/stayfixed/delivery/<id>/`, named by the binding id below: a marketplace
`stayfixed-delivery-<id>` holding one plugin, `overlay-<id>`, whose `hooks/hooks.json` is the union
of the `claude/hooks.json` of `common/`, of each tag the project lists in list order, and of
`projects/<name>/` — each event's entry groups in that order, as the overlay wrote them — and whose
`skills/` and `agents/` are copied from the same directories, a later plate's copy of a file
winning over an earlier one's and each copy keeping its source's permission bits, so a skill's script stays executable. A session runs the plugin from that
directory in place, so a later `attach` re-renders it there and an edit reaches the next session
with no reinstall. Each render is written whole into a new directory beside it and swapped into
place, so a file the overlay no longer holds is gone, whatever an earlier run recorded; the ledger
keeps the render's digest alone, never the id. Every run installs it with `claude plugin marketplace
add <that directory> --scope local` and `claude plugin install overlay-<id>@stayfixed-delivery-<id>
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
`stayfixed/binding` there (the directory `git rev-parse --git-common-dir` names, which every
worktree of the repository shares), and records on this machine what it is bound to — the project
name, the `origin` at the time and the checkout — in `$HOME/.local/share/stayfixed/bindings/<id>.toml`.
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
repository with no `stayfixed.toml` whose project neither `--project` nor this machine's binding
names, every `projects/<name>/project.toml` in the overlay.
`.claude/settings.json` — the committed one — is read for **nothing**: it is repository-controlled,
and the repository never grants a capability.

**Writes** a block between `# stayfixed:attach:begin` and `# stayfixed:attach:end` in the
repository's own exclude file (the one `git rev-parse --git-path info/exclude` names, which every
worktree shares), written first,
`.claude/settings.local.json`, `.codex/rules/`, the ledger `.stayfixed/local/attach.json`, the
binding id `stayfixed/binding` in the git common directory when there is none yet, this machine's
binding record `$HOME/.local/share/stayfixed/bindings/<id>.toml`, the render
`$HOME/.local/share/stayfixed/delivery/<id>/` (written whole into a directory beside it, then
swapped into place, the render before removed whole) and, through the two `claude plugin` calls,
Claude Code's own records of the marketplace and the plugin and the main checkout's
`.claude/settings.local.json`; where the notes are composed, the composed store
`$HOME/.local/share/stayfixed/stores/<id>/` (a link per group of the overlay's for this project,
`tag-<tag>` to `groups/<tag>/memory/` for each tag the project lists where that is a directory, and
one to its `MEMORY.md`; a directory of the project's `memory/` whose name starts with `tag-` is not
linked, the prefix being the tags'; each run makes its links exactly the overlay's current set, so
untagging takes the link and a rename of a tag moves it, and leaves any file there that is not a
link, such as a note the harness wrote), the key `autoMemoryDirectory`
naming that directory, absolute, in the main checkout's `.claude/settings.local.json`, which Claude
Code reads from every worktree, and — in the overlay — `projects/<name>/project.toml` while it
records no remote, this project's note directories,
`projects/<name>/memory/MEMORY.md` when the store has none yet (rendered as `stayfixed memory
index` renders it, so the store's index link never dangles and `memory index --check` passes right after
a first attach in an overlay this release rendered, and in an older one once its owner has deleted
by hand the `common/memory/README.md` 0.1.x shipped, which the note reader reads as a note).
It runs no program in the overlay: its commit-time secret scan is `setup --overlay`'s, which makes
or records the overlay, and where that scan is missing `doctor`'s `pre-commit` row says it is not
installed. The ledger is the only record
of which allow rules are stayfixed's, because an allow rule cannot carry a marker the way a hook
entry can; `detach` reads it and nothing else. **A re-attach takes back an allow rule the overlay
no longer grants**, where the ledger names it and the settings file still holds it: a rule dropped
from `common/`, from `projects/<name>/` or from a tag you took off the project leaves with the
next run, and a rule you added by hand, which the ledger does not name, stays. **`.gitignore` is never written**: it is tracked, so
any line there would be a change every collaborator gets. A `stayfixed:ignore` region an earlier
release's `attach` wrote there stays until you remove it; `stayfixed init`'s own region is
`init`'s.

**What it places, it hides from git, unless git hides it already.** The ledger, each
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
file — refuses the run before that path, or anything after the block, is written. The binding id is
placed in the git common directory, which git never tracks, so it is neither listed nor asked about.
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
`autoMemoryDirectory` key points the harness at `$HOME/.local/share/stayfixed/stores/<id>/`, outside
every checkout, whose links reach the overlay's notes and nothing of the repository's, so it waits
for no approval. The key is recorded in the ledger before it is written, so `detach` takes it back;
the path names the whole binding id and is printed only with the id cut to its short form. A repository that keeps its own notes gets
no key. `stayfixed memory` reads the same store in overlay mode, so the bundles a session starts
with and the harness read one directory. Nothing is placed under `paths.memory` or under
`~/.claude/projects/`: the link tree and the harness memory link an earlier release made there are
yours to remove by hand.

Exits `0` on success. A failure or refusal below that the run meets before its first write ends
`--check` with the run's code and line.

A real run exits `1` on a failure, something it reads that cannot be read or a `git` that cannot
answer, in the order the run meets them:

- `stayfixed.toml` is missing, cannot be read, is not UTF-8 or valid TOML, or holds a key or value
  the loader refuses; or the machine configuration cannot be read, is not UTF-8 or is not valid
  TOML.
- `git` cannot read the `origin` remote, or `git` cannot name the repository's common directory.
  The overlay's record of this project (`projects/<name>/project.toml`) binds nothing, so one
  that cannot be read, is not UTF-8 or is not valid TOML — a merge's conflict markers, when two
  machines first attached the project — stops nothing: the run says where it stopped reading,
  never writes over it, and `doctor`'s `attached` row warns.
- The overlay's `permissions.json` or `hooks.json`, or `.claude/settings.local.json`, cannot be
  read or is not UTF-8; or a file under the overlay's `skills/` or `agents/` cannot be read, is
  not a regular file, is not UTF-8 or is longer than 64 MiB, or a directory there cannot be
  listed.
- An existing `.stayfixed/local/attach.json` cannot be read, is not UTF-8, is not valid JSON or is
  not a JSON object.
- A Codex rule file in the overlay cannot be read or is not UTF-8, or the overlay's `common/codex/`
  or `projects/<name>/codex/` directory holding it cannot be listed.
- `git worktree list`, which names the main checkout, fails.

For `stayfixed.toml`, the overlay's record of this project, its `permissions.json` and
`hooks.json`, `.claude/settings.local.json` and the ledger, a file that "cannot be read" includes
one that is not a regular file once a link to it is followed, such as a link to `/dev/zero` or to
a FIFO, which is never waited on, and one longer than 64 MiB, which is as far as each of these is
read. The machine configuration and the overlay's Codex rule files are read whole, and one that is
not a regular file is passed over as absent. A ledger that is itself a link is refused (`2`) before
it is read, as a path that passes through a symlink.

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
- A `.claude/settings.local.json` that stayfixed's indented write-back would make longer than the
  64 MiB it reads, whether or not this run would rewrite it: a short document many levels deep
  grows by its depth on every line, and `would be longer than this reader reads once written
  back` keeps a run from leaving a file its next read refuses. `--check` refuses it too.
- A `memory.groups` entry that leaves this project's share of the overlay.
- A `.stayfixed` that is a symlink, or an existing ledger naming files, settings keys or
  directories `attach` could not have written.
- A `git check-ignore` that cannot answer.
- A path it places — the ledger, a `.codex/rules/` copy, or
  `.claude/settings.local.json` — that the repository tracks, in any ASCII case, as git itself
  matches it, or as the same file as one it tracks in that directory (where the filesystem folds
  names, a tracked `.CLAUDE/Settings.Local.json`, or on macOS `.claude/ſettings.local.json`, is
  the file `attach` would write), since no exclude line hides a tracked file and what `attach`
  writes there would reach every clone with the next commit; or a `git ls-files` that cannot say.
  The refusal names each such path. `--check` refuses it too.
- A `.claude` that is a symlink, or a `.codex` that is one on a run that writes into it; a
  `git rev-parse --git-path info/exclude` that names no exclude file; an exclude file that cannot
  be read or holds a `stayfixed:attach` block opened or closed twice (the refusal names the file),
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

## `stayfixed detach [--root PATH] [--machine PATH]`

Removes exactly what `attach` added, and leaves the binding alone: the binding id, this machine's
record of it and the overlay's `projects/<name>/project.toml` stay, so a later `attach` binds the
same checkout again.

It reads `.stayfixed/local/attach.json` and acts on that and on nothing else *that it is willing
to believe*. A repository with no ledger fails (`1`) naming the missing file rather than guessing
which allow rules were stayfixed's from their content — that guess is the reason the ledger
exists, and getting it wrong removes a rule you wrote by hand. And the ledger is not an
authority: `.gitignore` does not untrack a file a clone committed, so this path can arrive in a
fresh checkout with contents nobody on your machine wrote. Every field is held to what `attach`
could have put there — `rules` to a single file under `.codex/rules/`, `settings_keys` to
`autoMemoryDirectory` — and a ledger naming anything else is refused (`2`) with nothing removed,
rather than obeyed. A ledger claiming `settings_keys = ["permissions"]` would otherwise have
deleted your whole `permissions` block, deny rules included.

**Run it from any checkout of the repository.** `attach` writes its ledger, settings file and
`.codex/rules/` copies into the main checkout whichever worktree it ran from, so `detach` acts on
the main checkout too. A ledger an earlier release wrote in a linked worktree is not read.

**Writes**: it takes the recorded allow rules and the `autoMemoryDirectory` key back out of the
main checkout's `.claude/settings.local.json`, drops the hook entries an earlier release's `attach`
merged there —
the ones its ledger records, under the event it records, and never one by its `# stayfixed:…` marker
alone (a group that mixes one of those with your own entry is split, never replaced) — and leaves
the file unwritten when none of those is in it, removes the `.codex/rules/` files it wrote,
withdraws the overlay's rendered plugin — `claude plugin uninstall overlay-<id>@stayfixed-delivery-<id> --scope
local` where the main checkout's `.claude/settings.local.json` names that plugin under
`enabledPlugins`, and `claude plugin marketplace remove stayfixed-delivery-<id>` where it names that
marketplace under `extraKnownMarketplaces`, each run from the main checkout, then the render
directory `$HOME/.local/share/stayfixed/delivery/<id>/` removed whole where it is there, a link
there unlinked, then every link in the composed store `$HOME/.local/share/stayfixed/stores/<id>/`
and the directory where nothing else is left (a file there that is not a link is a note the harness
wrote: it stays, and so does the directory, which the line says and `--json` reports as
`store_kept: true`) — removes the `stayfixed:attach` block in the repository's exclude file, and deletes
the ledger, `.stayfixed/local/attach.json`. The render directory and the composed store are derived
from the binding id and never read from the ledger, so a ledger a clone committed naming another directory removes nothing
outside it. The plugin goes before the exclude block, so Claude Code takes the plugin's entries,
which name the id, out of `.claude/settings.local.json` while that file is still hidden. Each call
is decided by what that file names, never by the ledger or the render directory, and the file is
read again once they ran: while a name under either key names a `stayfixed-delivery-` marketplace,
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

Last, each directory the ledger records `attach` as having created — of `.stayfixed/local/`,
`.stayfixed/`, `.codex/rules/`, `.codex/` and `.claude/`, in that order — is removed when it is
empty, and left standing otherwise. A link tree under `paths.memory` or a harness memory link under
`~/.claude/projects/` an earlier release made is not touched: remove those by hand.

**`.gitignore` is never touched.** `attach` writes nothing there, so `detach` takes nothing out:
a `stayfixed:ignore` region `stayfixed init` wrote is the scaffold's, and one an earlier release's
`attach` wrote stays until you remove it.

**Directories come back too.** `attach` records which of `.stayfixed/local/`, `.stayfixed/`,
`.codex/rules/`, `.codex/` and `.claude/` this repository did not have before it ran, and `detach`
removes exactly those once everything inside them is gone. The removal is `rmdir`: a directory
still holding anything — your own `.codex/rules/` file, your `.claude/settings.json` — survives,
and so does its parent. The round trip is byte-for-byte in the main checkout.

**It does not touch `projects/<name>/project.toml`.** That record is the overlay's note of the
remote and the date this project was first attached, kept for you to read, and binds nothing; it is
the overlay's, not this checkout's, so a detach leaves it as it is.

Exits `0` on success. It exits `1` on a failure, in the order the run meets them:

- `git` cannot list this repository's worktrees, which names the main checkout.
- `.stayfixed/local/attach.json` is not there, cannot be read, is not UTF-8, is not valid JSON or
  is not a JSON object.
- `.claude/settings.local.json` cannot be read or is not UTF-8.

"Cannot be read" means here what it means for `attach`: a link to a device or a FIFO, or a file
longer than 64 MiB, which neither command reads past. A settings file an earlier release's
`attach` wrote back past that size has to be cut down by hand before `detach` can run.

It exits `2` on a refusal, in the order the run meets them:

- A ledger naming files, settings keys or directories `attach` could not have written.
- A `.claude/settings.local.json` that is not JSON or not a JSON object, or whose `hooks` has a
  shape the withdrawal cannot read, or whose indented write-back would pass 64 MiB.
- A `git rev-parse --git-path info/exclude` that names no exclude file, an exclude file that cannot
  be read, a `stayfixed:attach` block in it opened or closed twice, or one to take out of a file in
  a directory you cannot write (the refusal names the file).
- A path the withdrawal writes or removes reached through a directory that became a symlink after
  the attach: `.claude` when the settings file is to be rewritten, `.codex` or `.codex/rules` for
  a recorded rule copy, `.stayfixed` or `.stayfixed/local` for the ledger. The refusal names the path and
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

## `stayfixed setup [--preset NAME] [--plugin NAME …] [--home PATH] [--machine PATH] [--overlay VALUE]`

Configures this machine from a preset, `recommended` unless `--preset` names another: the
machine configuration file's `[personal]` and `[machine]` tables, the deny rules and personal
values in `<home>/.claude/settings.json`, and each plugin `--plugin` names, one install per plugin
per configured harness. Without `--plugin` no plugin is installed and no plugin command runs. That file is read as Claude Code reads it, past a leading byte-order mark,
which a rewrite keeps. The deny rules are merged in beside the owner's own, and none is removed.
`recommended` denies the env files by name: `.env`, `.env.local`, `.env.*.local`, `.env.dev`,
`.env.development`, `.env.prod`, `.env.production`, `.env.stage`, `.env.staging` and `.env.test`,
each as `Read(**/<name>)`, so the templates a project commits (`.env.example`, `.env.dist` and the
rest) stay readable. An env file under another name stays readable too. `--home` and `--machine` default to the home directory and to
`~/.config/stayfixed/config.toml` — the file every reader reads, and not whatever
`XDG_CONFIG_HOME` or `STAYFIXED_CONFIG` names, because a machine file half the installation
cannot find is not a machine file. Both flags exist so this command can be pointed at a
scratch destination instead of your real one, the same way every other command here takes
`--root`. A scratch destination is **not a dry run**: the same files are written, at the paths
these two flags name, and nothing is suppressed. They apply to `--preset` alone — `--git-hooks`
writes inside a repository and ignores both. The settings file is written through the home's own
symlinks, so a `~/.claude` or a `~/.claude/settings.json` that a dotfiles manager links into
another tree gets the file the link leads to, and the link stays. The machine configuration file
is written through a link at it the same way.

`setup` is not the only command that writes outside a repository, and two others say so in their
own sections: `stayfixed trust revoke` withdraws an approval from `~/.config/stayfixed/trust.json`,
and `stayfixed attach` keeps its binding record, render and composed store under
`~/.local/share/stayfixed/`. It is the only
one that writes the machine configuration file and `<home>/.claude/settings.json`. `--root` names
the repository `--git-hooks` installs into (below); machine setup reads no repository, so it refuses
`--root` (`2`) with nothing written, where it used to take the flag and read nothing of it.

`setup` is the only writer of the machine configuration file, and its readers do not change to
suit it: `[personal]`, `[guards]` and the session `[budgets]` are `config.owner`'s, which every
command's load and every session read; `[overlay] root` is `config.overlay`'s; and each resolves
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
included, and none is pinned, so none is installed unasked; the preset's `[plugins] recommended`
lists the ones `stayfixed init --questions` offers (`superpowers` and `context7` in
`recommended`). A named plugin is installed per configured harness, from
`[defaults.stayfixed] agents` (`claude` and `codex` by default) and from the preset's own
per-harness marketplace table (`[plugins.<harness>]`). For each harness the preset declares a
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
place to render or clone into. A tree that carries the identity record `stayfixed-overlay.toml`,
parsing as TOML and holding `layout = 1`, is an overlay; the refusal of a tree without it names the
file and its keys. Anything else is refused (`2`): a file, a link at a `create:` destination, a
directory holding something that is not an overlay, and, in one sentence for both forms, a
directory you cannot search, or one holding no overlay that you cannot both list and write. Where
the overlay lives is yours to choose and `setup` refuses no place for it; `stayfixed doctor`'s
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
view <owner>/stayfixed-overlay-template --json isTemplate` once: a template there is generated
from, and a repository of that name that is not one, or `gh`'s explicit answer that there is none,
means you have published none, and the template is `github.com/stayfixed/stayfixed-overlay-template`,
the publisher's public copy, named with its host: `gh` looks an unqualified name up on `GH_HOST`,
so on a GitHub Enterprise host `stayfixed/…` would be whoever owns that name there. Any other
failure of that question — an expired token, a network error, a `gh` that is not installed or
hung, an answer that is not the JSON asked for — stops the command with `gh`'s own message and
creates nothing (`1`). Once `gh repo create` has run, the repository may exist on GitHub whatever
`gh` answered, and a second `create:` would fail on the name it holds, so every refusal from then
on says so and gives the remedy that works: once `<home>/<name>` holds a clone of it, record it
with `stayfixed setup --overlay <home>/<name>`. When `gh repo create` itself fails, the command
stops there with its exit code and stderr; when it reports success and the clone leaves nothing at
`<home>/<name>`, `gh repo view` is asked whether the repository exists, and the clone is retried
once, after a ten-second wait when it does — a wait carried on reasoning rather than a measurement,
since the one trial run against it did not reproduce the race. A clone checks the identity record
out last as far as git's order goes: git writes a tree in path order, where the record's path sorts
after every file the template ships, but parallel checkout (`checkout.workers`) keeps no order, and
a file of yours whose path sorts after the record comes after it, so a clone cut short can carry
the record. A generated overlay has no `.stayfixed/manifest.json`, so `stayfixed overlay upgrade`
refreshes none of its files once they differ from a release's (`overlay upgrade`, above).

**Writes** `<home>` itself when it is not there yet; `--machine`'s file, with the directories above
it, once for the preset and again for the overlay root `--overlay` records;
`<home>/.claude/settings.json`, where its links lead; and, through the plugin
commands it runs for each plugin `--plugin` names, on each harness with a declared marketplace (`claude plugin marketplace add` and
`claude plugin install`, `codex plugin marketplace add` and `codex plugin add`), the marketplace
registrations and installed plugins those commands write into each harness's own configuration.
`--overlay <path>` naming an overlay writes nothing in its tree: it is recorded, and its
`pre-commit` git hook is installed through `pre-commit install`. Naming nothing or an
empty directory, it writes the directory with every file of the template plus `.stayfixed/manifest.json`, the
repository `git init` makes there, and, through `pre-commit install`, its `pre-commit` git hook.
`--overlay create:<owner>/<name>` writes, through `gh repo create <owner>/<name> --private
--template <template> --clone`, a new private repository on GitHub under `<owner>` and its clone
at `<home>/<name>` — or, when that clone leaves nothing there, a clone from the retried `git clone`
— then its `pre-commit` git hook. Run again over the overlay it made, it generates nothing.

**Exits** `0` on success, and `2` on each of these refusals:

- `--uninstall`, which is taken only with `--git-hooks` (below), before anything is written;
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
nonzero exit. What the failing plugin command printed is quoted as the overlay's notes quote it
(escaped, and cut to its first 120 characters and its length).

---

## `stayfixed setup --git-hooks [--uninstall] [--root PATH]`

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
move the hook aside. A re-install reads the `.local` beside stayfixed's hook for the same name and
refuses too, saying what is already on disk: stayfixed's hook runs that `.local` last, so every
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

**Refuses (`2`) together with `--preset`, `--overlay` or `--plugin`.** Each asks machine setup to
do something, which this form does not do, so it names `--git-hooks` and writes nothing, where
`--overlay` used to be dropped and the hook installed. `--home` and `--machine` say
only where machine setup would write, and are ignored.

**Refuses (`2`) `--uninstall` without `--git-hooks`.** It removes the hook this form installs and
means nothing to machine setup, so `stayfixed setup --uninstall` names `--git-hooks` and writes
nothing, where it used to drop the flag and run the machine setup.

**Writes** the hook file in `--root`'s hooks directory, and the `.local` file beside it only when a
foreign hook was there to preserve, by renaming that hook. Under `--uninstall` it removes the hook
file only when it is stayfixed's, and renames the `.local` file beside it, when there is one, back
to `prepare-commit-msg`. Its line says which it met: `removed <hook>` with whether a foreign hook
was restored, `there is no stayfixed hook at <hook>; nothing was removed`, or `left <hook> as it
was: it is not stayfixed's hook; nothing was removed`; `--json` carries it as `found` (`removed`,
`absent` or `foreign`) beside `path` and `restored`. A FIFO or a directory at the path is foreign to
`--uninstall`, which leaves it, and the install refuses it (`2`). A hook whose mode forbids reading
is neither stayfixed's nor foreign: either form refuses (`2`) naming it and the reason, and leaves
it. A regular file past the 64 MiB read cap is foreign, since stayfixed's own hook is a couple of
kilobytes: it is kept and chained, and `--uninstall` leaves it. Exits `0`; `2` when `--preset`,
`--overlay` or `--plugin` is also given, `--uninstall` is given without `--git-hooks`, the hook
cannot be read, or a hook names `prepare-commit-msg.local`.

---

## `stayfixed setup --approval-boundary [--home PATH] [--machine PATH]`

Prints what keeps an agent's shell out of the trust record's directory under Claude Code, for you
to set, and sets none of it: an approval holds against an agent only while the harness's sandbox
holds ([`stayfixed trust list`](#stayfixed-trust-list---root-path---machine-path) says why), and
stayfixed neither enforces nor checks that boundary. The line names:

- the deny rule `Edit(//<the trust record's directory>/**)` for `permissions.deny` in
  `<home>/.claude/settings.json`. The directory is that of
  `~/.config/stayfixed/trust.json`, or of the file beside `--machine`, which is the machine
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

**Exits** `0`; `2` beside `--preset`, `--overlay`, `--plugin`, `--git-hooks` or `--uninstall`,
which name a write this run does not make; `1` for a `HOME` that is empty with no `--home` or no
`--machine`.

---

## `stayfixed doctor [--json] [--root PATH] [--home PATH] [--machine PATH]`

Fourteen checks over one installation. It **reports and never repairs**: every finding
carries the command that would fix it, and not one of them is run for you. Nothing is written.

The rows come in a fixed order: the installation's own nine first, then the five about the
private layer — the binding's (`attached`), memory's (`bundles`, `memory`) and the
private overlay's (`pre-commit`, `overlay-requires`). Match a row by its `name`, never by its
position.

**Several subprocesses are run and every one of them only asks.** stayfixed's own
`hooks/run-hook.sh` with `--version`; `git ls-remote --exit-code` against the public
repository's tags, to judge `[ci] ref`, only when one is set; and the `git` queries the other
rows need — where the overlay keeps its hooks, what this checkout's `origin` is, which the
binding's row asks, the repository's common directory, where the binding id is kept, which the
binding's row, the note store's rows and the `preferences` row's read of the overlay's project
file each ask for themselves, which checkout is the main one (`git worktree list`), whose ledger
and settings file the binding's row reads, whether this checkout is a registered worktree (its
common and its own git directory), which the `memory` row asks to read the main checkout's settings
file a linked worktree reads too, whether a path `attach` placed is tracked (`git ls-files`) or ignored (`git check-ignore`) and whether a
tracked file names the delivery (`git grep`), which the binding's row asks of a bound checkout, and the
binding's common directory once more, which the binding's row asks to read the overlay's tag layers.
Fourteen of those are measured on a green attached installation — the wrapper probe and thirteen
`git` questions — and not one of them leaves this machine. The `ci-ref` row's `git ls-remote` is one more on a repository that records a
`[ci] ref` at all, and it is the only one that does leave: it goes through the `Runner` seam,
which is what lets the case that pins the fourteen answer it in process instead of launching it.
That one is bounded at **30 seconds**, not at the seam's own five minutes (the bound for
`gh repo create --clone`), so a peer that does not answer cannot turn a one-line diagnostic into a
five-minute block. The `git` questions are `gitenv`'s five seconds each, and the wrapper probe is
this area's own thirty.

**The rendered workflow is read as a regular file, and to a bound.** That path is the
repository's: a clone chooses what sits at `.github/workflows/stayfixed.yml`. Anything there that
is not a regular file — a directory, a symlink to a FIFO, a dangling link — is a warning naming
the path and never the ref's own verdict, and so is a file past 256 KiB, the same bound the
`diagnostics` row reads its log under. Not one byte of the file is printed on any arm, and a byte
that is not UTF-8 is replaced rather than raised: it used to reach the report as a red row saying
the check could not run, which is a red a clone could force.

The summary line carries the counts and the names of whichever status most needs reading, capped
the way every summary in this CLI is. The rows are in `--json`, under `checks`, one object per
check with `name`, `status`, `detail` and `remedy`, so every remedy is there.

`status` is one of `ok`, `warn`, `red`, `skip`.

| Check | What it answers | What it reads |
|---|---|---|
| `not-initialised` | whether there is a `stayfixed.toml` here, and how much of it a session can use: with none, a warning that the session guards and `doctor` work without one and memory stays the coding agent's own, and that `stayfixed init` adds the rest, except in a checkout this machine binds, where it is ok and says the configuration comes from the overlay's layers; with one that loaded with settings ignored or put back to the preset's, a warning naming at most three of their keys and counting the rest, never their values; red only for one a session drops whole, in the words of the session's warning | `stayfixed.toml` |
| `versions` | whether the project's `[stayfixed] version` is the stayfixed running; with no project configuration, which stayfixed runs | `stayfixed.toml`, the package |
| `wrapper` | whether the wrapper can actually reach stayfixed on this machine: red when it writes a fault to stderr or cannot be run; under a root the environment named, which it never runs, red when the wrapper is not executable and a skip otherwise; a stale `hooks/hooks.json`, an edited wrapper that still runs or a changed `scripts/stayfixed` is not reported | one `run-hook.sh --version`, and only under the plugin root this stayfixed is part of; under a named root, `hooks/run-hook.sh`'s mode |
| `budgets` | every budget set above the preset, named raised, and every one set below it, named lowered | `stayfixed.toml`, the machine file, the preset |
| `preferences` | each personal value, guard switch, preference and session budget a session resolves, with the layer its value came from — the preset, the repository, the overlay's common file (`overlay common`), its file for the project this checkout is bound to (`overlay project`) or the machine file — and the value only where it is a boolean, a number or one of stayfixed's own words; then, as information that never changes the row's status, every note reading the overlay's layers gave — no overlay recorded, a file not there or not loading, a key it cannot use or may not set; red when the machine file does not load, in the words every command refuses it in, which name the file and where the parser stopped; a warning naming the file when a key in it could not be used | `stayfixed.toml`, the preset, the overlay's two `stayfixed.toml` files, the machine file |
| `cli-path` | whether `stayfixed` resolves on `PATH` | `PATH` |
| `ci-ref` | whether `[ci] ref` is the commit of a released stayfixed tag (or the `v1` alias: a warning, as mutable, once a `1.x` release creates it, and red until then), and whether the rendered workflow pins the same ref — under `[ci] mode = "reusable"`, a workflow that is not there at all is a warning and never a green row, and so are a path that is there and is not a regular file and a file past the 256 KiB bound on the read | `git ls-remote --exit-code` over the public repository's tags, bounded at 30 seconds; *.github/workflows/stayfixed.yml*, read as a regular file and to a bound |
| `diagnostics` | how many reasons the hook sink recorded — a count, never a line of the file | `${CLAUDE_PLUGIN_DATA}/stayfixed/diagnostics.jsonl` |
| `ignored-env` | as information, never a status: `STAYFIXED_CONFIG` set, or `XDG_CONFIG_HOME` set to anything but the `.config` of the home every command reads under (`HOME`, or the password database's where `HOME` is unset), and not honoured by any command; and a `HOME` that is not the home the password database records for this user, since stayfixed follows `HOME` | the environment, the password database |
| `attached` | the overlay binding, what it delivers, and, where `memory.mode` is `overlay`, the `autoMemoryDirectory` pointer at the composed store, read alike from every checkout (the states are below the table) | the main checkout's `.stayfixed/local/attach.json` and `.claude/settings.local.json`, `~/.local/share/stayfixed/delivery/<id>/`, `~/.local/share/stayfixed/stores/<id>/`, the overlay's executable parts, `git` on the paths `attach` placed |
| `bundles` | a bundle that does not fit its slots, and one whose part reaches the cap | the note store |
| `memory` | the memory a session gets: the active `memory.mode` and the layer that set it (or that none does, and memory is the coding agent's own), the store, which settings file sets the harness's `autoMemoryDirectory` — the checkout's `.claude/settings.local.json`, the main checkout's, the committed `.claude/settings.json` or `~/.claude/settings.json`, the first that holds it, named as information and never with its value, since a committed file may point the harness elsewhere — and the store's unreviewed notes as a count; a warning only for files in the note store that are not notes, counted (at most 500,000 entries) | the resolution `preferences` reads, the note store, the machine's trust record, those settings files |
| `pre-commit` | whether the overlay's commit-time secret scan is installed on this machine | the overlay |
| `overlay-requires` | whether the overlay this machine records requires a stayfixed the running one satisfies — red when this project keeps its notes in that overlay, a warning when it does not — and, where that finds nothing, a warning when another repository's work tree holds the overlay root (a `.git` in a directory above it), naming that directory, since that repository can put files into the overlay | the overlay's `stayfixed-overlay.toml`, `stayfixed.toml`, the directories above the overlay root |

**How `attached` reads the delivery.** With no ledger, a repository whose `memory.mode` is not
`overlay` is simply not attached, and the row is green. Once this machine's binding confirms the
ledger, the row reads what `attach` left: the render under `~/.local/share/stayfixed/delivery/<id>/`,
named only by the binding id's first eight characters, and the paths `attach` placed in the main
checkout, whose ledger every checkout reads. Every state is read, and the first red one answers,
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
| delivery named in a tracked file | a tracked file holds `stayfixed-delivery-<id>`, the delivery's name and with it the binding id, which never leaves this machine; asked for the whole name, never the prefix | `red` | take the name out before it is pushed |
| render gone | the render directory is gone, so nothing of the overlay loads and nothing else says so | `red` | `attach`, which renders it again |
| marketplace gone | the render has no `.claude-plugin/marketplace.json`, so its plugin does not load | `red` | `attach`, which renders it again |
| placed paths unasked | git could not say whether the placed paths are tracked or ignored, or whether a tracked file names the delivery | `warn` | `doctor` again where `git ls-files`, `git check-ignore` and `git grep` work |
| not installed | the ledger records no install of the plugin | `warn` | `attach`, which installs it |
| launcher gone | the launcher the path-scoped rules' entry runs through is not there | `warn` | `attach` from the stayfixed you run now |
| drift | the overlay's hooks, skills or agents changed since the last render | `warn` | `attach`, which renders the overlay as it is now |
| overlay unreadable | the overlay's executable parts could not be read | `warn` | `attach --check`, which says why |
| `origin` moved | this checkout's `origin` is not the one the binding was recorded with | `warn` | `attach`, which records the new one |
| tags unresolved | two of the project's `tags` hold one rule, skill, agent, Codex rule file or setting name (the later tag wins), a listed tag is not a usable name or has no `groups/<tag>/` directory, or a directory of the project's `memory/` starts with `tag-` (the composed store links none); said after the other warnings, and a record that cannot be read answers with its own fault | `warn` | rename one of them in the overlay, or reorder `tags` in the project's `project.toml` |

**How `attached` reads the memory pointer.** Where `memory.mode` is `overlay`, the row reads
`autoMemoryDirectory` in the main checkout's `.claude/settings.local.json`, which Claude Code reads
from every worktree, and compares it with the composed store `~/.local/share/stayfixed/stores/<id>/`
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

**Eight of the fourteen have a `skip` arm — nineteen arms between them, every one on a state of
this machine or this repository.** A `skip` is **not** a finding and never reaches the exit code, so
read the detail — each one says which measurement it is missing. No row skips for want of a build
that can answer it: `codex-hooks`, the one that did, left the report, and what holds on Codex is the
README's reach table.
`init` writes `[ci] ref`, so what `ci-ref`'s skip reports is a state — this repository records
none — and which state is the ordinary one moves with the release history rather than with any
code here: while no released tag matches the stayfixed running there is no commit to pin, so
`init` records nothing and the row skips on a correct installation; once a release exists, a
repository `init` set up carries a ref and the row answers.

The eight that skip on a state are `wrapper`, when there is no plugin root this process can
vouch for; `attached`, when this machine records no overlay to check the ledger
against, or the overlay could not be asked at all; `pre-commit` and `overlay-requires`, when
no overlay root is recorded on this machine **or** when the root it records is not a directory
— two different arms with two different sentences, because a machine that recorded an overlay
and then moved it is not a machine that recorded none; `attached`, `pre-commit` and
`overlay-requires` again, each in a sentence of its own, when the machine file does not load, so
whether it records an overlay is not known, which is neither of those; `overlay-requires` again
when the overlay declares no stayfixed requirement and no other repository's work tree holds it;
`bundles`, when the note store does not resolve; `diagnostics`, when no harness data root is set in the environment, which is every
`stayfixed doctor` run from a terminal rather than from a hook; and `ci-ref`, when no `[ci] ref`
is recorded.
And four rows read the project configuration and skip, in one sentence, when there is none to
read — no `stayfixed.toml`, or one a session drops whole: `budgets`, `ci-ref`, `attached` and
`bundles`. `memory` reads the resolution a session reads and answers without one. A checkout this
machine binds whose main checkout has no `stayfixed.toml` is the one exception for `attached` and
for the note store `memory` reads: both are judged on the configuration `attach` acted on there,
the preset's under the overlay's layers for the project the binding record names.

**A `skip` does not mean there is nothing to do.** Six of the nineteen arms carry a remedy:
the plugin-root skip, `wrapper`'s named-root skip, `attached`'s no-overlay and
could-not-be-asked arms, and the moved-overlay arm of `pre-commit` and of `overlay-requires`. The dividing line is not "always"
versus "on a state" — every other arm skips on a state and carries nothing: `bundles`,
`diagnostics` and `ci-ref`, the *no overlay recorded* arms of the two overlay
rows, `overlay-requires`' no-requirement arm, and the
four with no project configuration, whose remedy is
`not-initialised`'s, and the three on a machine file that does not load, whose remedy is
`preferences`', red on the same file. Nor
is it whether another row names a command that changes the state: `pre-commit`'s arm carries
nothing though `attached` names `stayfixed setup --overlay` there. It is whether the skip is
itself worth acting on. Those six report something wrong that no other
row will tell you: a plugin root nothing can find, a root that will be read and never executed,
a recorded attach the overlay could not confirm, an overlay root recorded and not there. Of the
other thirteen, ten report a measurement that is simply unavailable — no store, no overlay,
no overlay requirement, no harness data root, no `[ci] ref` or no
project configuration — and no command in that row's gift changes it, and three report a machine
file another row is red about, with the command that clears it.

**The one to read first is the plugin root**, because it is the quietest and the worst. When
this process can find no plugin root at all, `wrapper` skips — no red, and every hook entry on
this machine silent. It carries a remedy: run `stayfixed doctor` from the plugin's own launcher,
so its root answers for itself, or set `CLAUDE_PLUGIN_ROOT` to where the plugin is installed,
which lets `wrapper` read the wrapper's executable bit even though it still will not run it.

**Nothing configured is not broken.** `doctor` reads the configuration the way a session does
([`stayfixed hook <event>`](#stayfixed-hook-event)), so every row is asked whatever `--root`
holds. With no `stayfixed.toml`, `not-initialised` **warns**, the four rows above that read the
project configuration skip, and no row is red for it: a default install, where the guards and
this report already work, exits `0`. In a checkout this machine binds, `not-initialised` is **ok**
instead and says the configuration comes from the overlay's layers, with no remedy, since `init` is
not what that checkout lacks. A `stayfixed.toml` that loads with settings ignored or put
back to the preset's warns, naming at most three of their keys and counting the rest. Only one a session drops whole is **red**: a
symbolic link, whatever it points at, a file that is not UTF-8, cannot be read or is not TOML, or
one holding a key nothing can stand in for; the row says which in the session's own words and
names `stayfixed docs check`, which prints the loader's own message.

**What is printed, and what is not. There is one exception, and it is bounded.** Counts,
statuses, file paths this project chose and stayfixed's own vocabulary print freely; a
repository-authored string does not. `[stayfixed] version`, `[ci] ref`, a note's filename, every
field of the hook sink's diagnostics log and the reason the store would not resolve are all read
and none is quoted back — `stayfixed doctor
--json` is relayed to a model verbatim by the `doctor` skill, so a byte a repository wrote reaching
this report is a byte reaching the model outside `trust.wrap`. The exception is the name of a
`stayfixed.toml` key that `not-initialised` says was ignored or put back to the preset's, which is
what the owner needs to find it: at most three names, one outside the path grammar withheld and
one inside it clipped at 120 characters, then a count of the rest, so the row stays short however
many keys the file holds and however long their names are.

`diagnostics` follows the same ruling, and is why that row counts rather than quotes. Its three
fields are stayfixed's own vocabulary *for a log stayfixed wrote*, and the log is found through
`${CLAUDE_PLUGIN_DATA}` — the same environment class a committed `env` block reaches — so this
command never establishes that. The row reports how many records are logged and how many sessions were
seen, and the remedy names the file by its variable; you open it yourself. A record is a hook
failure, an answer the output cap cut, or a session that ran without some of its configuration
(`config-fallback`), and the count does not tell them apart: which one a line is lies in its
`error` field, the very field this row does not trust.

**A plugin root the environment named is read and never run.** `wrapper` launches
`hooks/run-hook.sh` only under the root this stayfixed derived from its own module path. With a
wheel installation there is no such root — which is what `uv tool install` gives, and what
`cli-path`'s own remedy suggests — and `CLAUDE_PLUGIN_ROOT` or `PLUGIN_ROOT` may then name one:
that root's wrapper is still read by `wrapper`, for its executable bit, red without it and
otherwise a `skip` saying why. A report that ran a script the inspected repository could commit, and then
called the result green, would be worse than one that says it could not vouch for it.

**Writes** nothing. Exits `0`, or `1` when any check is red.

---

## The reusable workflow

`.github/workflows/check.yml` is a `workflow_call` workflow a project runs its stayfixed gates
through. `stayfixed init` writes the caller —
[`.github/workflows/stayfixed.yml`](#stayfixed-init---yes---dry-run---name-name---base-branch-branch---agent-name----profile-name---memory-mode-mode---attribution-check---commit-type-type----local-id----no-ci---root-path---machine-path)
— so most projects never type these lines; what follows is what that file contains, and what to
write by hand if you would rather:

```yaml
on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened, edited]
  merge_group:
    branches: [main]
  push:
    branches: [main]

jobs:
  check:
    uses: stayfixed/stayfixed/.github/workflows/check.yml@<40-hex sha>
    with:
      base: main
```

The branch is named four times, and each one is load-bearing. A pull request into any other
branch runs nothing, so it cannot collect a green check against a looser base and then be
retargeted. `edited` re-runs the check when a pull request is retargeted, and on every title
edit too, because a job filtered out with `if:` reports as skipped, which a required check
counts as passing. `base:` is a literal, so a pull request whose base is not this branch is
refused even where the trigger has been widened by hand. `merge_group` makes the check report
for the gate branch's merge queue and no other: a merge group reports no base the workflow reads,
so with the literal `base:` another branch's queue would be judged against the gate branch's
configuration, and it gets no run, as a pull request into that branch gets none. Each
`edited` run is a job, billed by the whole minute like any other. A pull request into another
branch — one stacked on a feature branch, say — gets no run at all, which blocks nothing as long
as the check is required on the gate branch only.

| Input | Default | Meaning |
|---|---|---|
| `base` | `""` | the branch the gates' configuration is read from; empty means the pull request's base, and on any other event the repository's default branch. On a pull request a value that disagrees with the pull request's own base is refused |
| `path` | `"."` | the project root inside the caller's checkout, for a monorepo or a fixture: a relative path with no `..` component, refused otherwise before a gate runs, so it cannot point the gates at another checkout's configuration. Any other character is admitted, a space or a name outside ASCII included: the value is handed to `stayfixed gate` as one argument and no longer reaches the run's outputs. A root any component of which is a symbolic link in the checkout is refused too |
| `python-version` | `"3.13"` | the interpreter stayfixed runs on; 3.11 is the floor |
| `only` | `""` | the checks to run, space-separated: `config` and any configured gate name. Empty runs the configuration check and every configured gate, and the configuration check runs whatever this names |
| `timeout-minutes` | `15` | the job's time limit in minutes, handed to the runner as given |

The caller's job needs `contents: read`. That is the default, so the lines above are enough —
but a caller that sets `permissions:` at workflow level replaces the default rather than adding
to it, and a called workflow cannot grant itself a scope the caller did not have.
`permissions: {}` at the top of the calling file therefore fails this workflow at its first
checkout, with an error that names neither the cause nor the remedy. Give the calling job
`permissions: { contents: read }` if the file sets any permissions at all.

**One job, and what it runs.** The job, `gates`, checks out the caller, checks out stayfixed **at
the commit the `uses:` line pins** — read off the platform's own record of which reusable
workflow is running, never off the caller's inputs, and asserted against `git rev-parse HEAD`
before anything else runs — and runs `stayfixed gate` in two steps, each of which resolves the
base to one commit in the same checkout, which nothing fetches into between them. The first, "The configuration and the built-in gates", judges the configuration and
runs the built-in gates, and executes nothing your repository wrote. The second, "The project's
own gates", runs the commands `[gates.custom]` names, and only if the first passed. Each gate is
advisory or enforcing, with every finding as an annotation, and each step that runs a check
appends its results to the job summary. No resolver and no build backend; the network is the two
checkouts, whatever `setup-python` fetches when the runner has no matching interpreter cached,
and, on a pull request that moves `[ci] ref`, one listing of stayfixed's public release tags.
It is one job because a job is billed by the whole minute: a push costs one runner-minute, not
one per gate. Its check, in the caller `init` writes, is `check / gates`.

**The time limit is the caller's, and running out still fails.** The job is cancelled after
`timeout-minutes`, 15 unless the caller passes another. The caller `init` writes passes none; a
project whose own gates need longer adds one line under its `with:`:

```yaml
    with:
      base: main
      timeout-minutes: 30
```

The value is handed to the runner as given, and the platform's own job limit bounds it: 360 minutes
on the GitHub-hosted runner this job runs on. The caller file is pull-request content, so that line is one a pull request
can edit, and a bound here would stop nobody while refusing a legitimate long caller. What a pull
request cannot do through the input is turn running out into a pass: a job that runs out of time is
cancelled, and a required check that was cancelled has not passed.

**What the input does not bound.** The rest of the caller file is pull-request content as well, and
runs as the pull request wrote it: a matrix around the call runs this job once per leg, each leg
with a limit of its own, and a `uses:` pointed at another workflow runs none of this file, under
whatever limit that workflow sets, up to the runner's own. That is a change to
`.github/`, and under the settings below a code owner reviews it before it merges — not before it
runs, since a pull request's run starts before any review.

**Your own gates run on a bare runner.** The second step has the runner image and the
interpreter `python-version` names, and nothing of your project's: a custom gate that needs
your toolchain installs it in its own command, for example `run = ["sh", "-c", "pip install -e
.[test] && pytest -q"]`, and that installation is billed in the same job. Why it is a step of
its own: a custom gate executes files the pull request can change with the runner's privileges,
which on a GitHub-hosted runner include passwordless `sudo`. In the process that decides the
verdict those files could rewrite it; in a later step, only its own results are left to them.
Within that step the base's enforced gates run first, and once one of them has failed no other
custom gate starts, enforced or not, so the process that holds a failing verdict runs nothing
more that the change can edit.
What it guarantees, and how to pin those files, is in the `stayfixed gate` section.

**One row per gate, if you want one.** Each leg of a matrix in your own caller is its own check
row and its own billed job:

```yaml
jobs:
  check:
    strategy:
      fail-fast: false
      matrix:
        only: [docs, bugs, plan, commit, trail]
    uses: stayfixed/stayfixed/.github/workflows/check.yml@<40-hex sha>
    with:
      base: main
      only: ${{ matrix.only }}
```

The list is yours to keep: a gate it leaves out never runs, and a custom gate added to
`stayfixed.toml` needs a leg of its own. Every leg runs the configuration check as well as the
gate it names, because `only:` sits in a file a pull request can edit: a change that loosens
what the base enforces fails every leg. Require every leg's check, not only one.

A leg is also the one real isolation between custom gates. Within one job they share a
checkout, and the base's enforced gates run before every other custom gate for that reason; but
two enforced gates that each run files the change can edit — a test suite and its
`conftest.py`, a `Makefile` — still run one after the other in that checkout, and the first can
rewrite what the second executes. A leg per such gate gives each a checkout no other gate has
touched.

**Where the configuration comes from.** `stayfixed gate` reads `stayfixed.toml` from the base
commit and judges the tree's copy against it key by key; the `stayfixed gate` section has the
table, what each input rests on, and how an owner lands a change it refuses. What this workflow
adds: the base's **name** is the pull request's base as the platform reports it, held against
the caller's `branches:` filter and its literal `base:`; its **commit** is
`refs/remotes/origin/<base>` in the caller's own checkout, which each gate step resolves once to
a full sha that every gate in it reads, the same commit in both since nothing fetches between
them; its **copy** is read at `path:`; the **stayfixed that runs** is the one the
caller's `uses:` line pins, whose commit the judging step passes as `--workflow-sha`; and the
**verdict** is the exit status of the first step.

On a pull request, the tree is the merge commit the platform built from the base as it was when
the event fired, while the base commit is read when the job checks out. A base that tightened
in between makes the change appear to undo that tightening, and the configuration check refuses
it. That fails closed; re-run the job, or update the branch. On a push to the gate branch the
base is the branch's tip when the job checks out, which is usually the pushed commit itself: that
run judges the configuration against itself, it proves the gates run, and the pull request's run
is the one that decided. If a later push has moved the branch by then, the run judges the pushed
commit against that later tip, and fails closed in the same way when the tip tightened.

**What makes the verdict binding.** The caller workflow is part of every pull request: a pull
request can edit its `uses:` line, its `on:` filter and its `base:`, or add a job of its own
named like the required check. A ruleset that requires a workflow can close that where your
plan offers one. Everywhere else the verdict binds under six settings, and without them the
gates still run and still report but cannot stop a pull request that edits its own caller:
- **CODEOWNERS covering `/.github/`, with review from code owners required**, so a change to
  the caller needs someone other than its author. GitHub reads the rules from the base
  branch's copy; keep the file at `.github/CODEOWNERS`, where its own `/.github/` rule covers it
  (`stayfixed assess` advises, `codeowners`, when no line names `.github`);
- **"Dismiss stale pull request approvals when new commits are pushed"**, or **"Require
  approval of the most recent reviewable push"**, so an approval of an innocuous `.github/` edit
  does not carry over to a later commit that repoints `uses:`;
- **the `check / gates` status check required** (`check` is the caller job `init` writes; a
  caller of your own names its own job), or every leg's check under a matrix;
- **that check's expected source set to GitHub Actions**, not "any source": otherwise anyone
  with write access can post a `success` status of that name through the API, and no file
  changes for a code owner to see;
- **branches required to be up to date before merging, or a merge queue**: a verdict is judged
  against the base as it was when the run started, and a base that tightened since would not be
  seen. The caller subscribes to `merge_group` for the gate branch's queue;
- and one that is stayfixed's, not yours: **a `v*` tag ruleset on the stayfixed repository**,
  because an upgrade is admitted only at a released tag's commit, and a tag that could move
  would move that anchor for every caller.

Whoever may bypass branch protection holds the gate: "Do not allow bypassing the above settings"
decides who that is, and a change the gate refuses lands by the direct push the `stayfixed gate`
section describes.

**Advisory or enforcing, per gate.** A gate is advisory until it enforces: its findings are
warning annotations and the job stays green. An enforcing gate's findings are errors and fail
the job. What enforces is what the base's `[stayfixed] enforced` names, with any gate the change
itself adds there; a gate no list names is advisory, however the project configures it.
`stayfixed adopt promote` moves a gate across. Within a step, every gate runs whatever the one
before it said, so a project fixing its documents does not pay a round trip per finding; the one
exception is a custom gate, which is not started once the run has failed. A custom gate runs
in the second step, and only with the command the base gives it ("Which custom gates run" under
`stayfixed gate`). The job's token is `contents: read` and neither checkout
keeps it, and the judging step's verdict was decided before any command started.

**Pin it by SHA.** A reusable workflow's ref is resolved when the run is created, so `@v1` and
`@dev` are a moving stayfixed running against your repository. `stayfixed init` writes that pin,
and writes it from `[ci] ref` in `stayfixed.toml` so that the file and the configuration cannot
come apart: on a repository it initialises from scratch that value is the commit of the released
stayfixed running, read off the public repository's own `v*` tags rather than off anything the
project says; on one that already had a `stayfixed.toml`, it is the ref that file records.
`stayfixed upgrade` moves it, with `[stayfixed] version`, and the file says so in its own first
lines. **A project with no release to pin gets no workflow at all**: before the first stayfixed
tag there is no commit to name, so `init` reports the workflow skipped with the reason and writes
nothing into `.github/`, and `stayfixed upgrade` renders it once a release matches. `@v1` is the
documented opt-in for a project that would rather track the major, written by hand;
`stayfixed upgrade` then moves `[stayfixed] version` alone and leaves the ref and that file as they
are. The alias exists from `1.0.0` on: a `0.x` minor may break what the one before it did, so
there is no `v0` to track, a `0.x` project pins the commit, and until the first `1.x` release
`stayfixed doctor` reports `v1` red, as a tag the public repository does not carry.
`smoke-release.yml` in this repository runs the `owner/repo/…@ref` form on demand, at `@dev` and
at the latest release's tag, so that the branch and tag forms are known to work — it is not a form
this reference tells you to write.

**What proves it.** `tests/test_check_workflow.py` runs the job's scripts, extracted from this
file, against real clones: a change that loosens what the base enforces, a custom gate that must
not run in the judging step, and `only:`; and holds that each gate step hands over the platform's
values and reads no base from another step. `tests/assess/test_read_base.py` holds what
`stayfixed gate` checks in them, against real clones: a `base:` naming a branch the author pushed,
a tag named like the base, the order the base is chosen in, a `path:` that leaves the checkout,
a root below it, and the refusal of a root reached through a symbolic link, which both gate steps
run first. `.github/workflows/smoke.yml` installs this plugin from the checkout with the real
harness CLI under a temporary configuration directory, feeds every `hooks/hooks.json` entry the
event it is filed under through the *installed* wrapper, runs `doctor` over the result, runs the
clone-to-exfiltration scenario — a hostile clone attempting to reach the model through committed
memory — and calls this workflow against the committed fixture project, so the reference above
is checked by a run and not only by this page.

**Checked out with `fetch-depth: 0`.** The base commit, the merge bases `plan` and `bugs` read
and the range `commit` reads all come out of that checkout; a shallow one can lack them or show
an older commit in their place, and the run says so rather than passing over a history it cannot
see. `persist-credentials: false` on both
checkouts, so nothing a gate reads can reach a token.

---

## Shared flags

Six flags mean the same thing wherever they appear, and each has exactly one sentence. Both
tables below are held to `stayfixed.command`'s own constants, row by row, by
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
anything differs. `stayfixed bugs index`, `stayfixed docs trail` and `stayfixed memory index` all
take it with that meaning.

Three commands mean something else by a shared name, `setup` by two. Each of the four is a
**named exception** — a decision that the flag means something else, not a sentence that drifted —
and each has its own constant beside the six above:

| Command and flag | What it means there |
|---|---|
| `stayfixed overlay upgrade --root` | the overlay root (default: current directory) |
| `stayfixed setup --root` | the repository --git-hooks installs into (default: .) |
| `stayfixed setup --machine` | the machine configuration file to write (default: ~/.config/stayfixed/config.toml, the file every reader reads) |
| `stayfixed attach --check` | report the binding and the diff, and write nothing |

`attach --check` reports the way the three `--check`s above do and exits differently on purpose: never on a
non-empty diff. A diff carrying allow rules is the ordinary state of a first attach, which
`attach` shows and proceeds with. A `--check` that failed on it would make reading the diff first a
failure.

Every command that reads a project's configuration takes `--root` and `--machine`, with the
meanings in the first table, whether or not its heading spells them.
Neither flag is taken by `stayfixed commit strip`, `stayfixed hook` and `stayfixed prove`,
because none of them reads a project's configuration: the first reads the message file it is
handed and your own `~/.claude/settings.json`, `hook` finds the project from the harness's own
event, and `prove` runs its command where it is typed and answers for that directory's repository.
`overlay upgrade` takes `--root` alone, in the sense the second table gives it, and reads no
`stayfixed.toml`; `setup` takes both, in its own senses. `tests/test_documents.py` holds both
lists to the real parser.

---

## Terms

**Scaffold** means three things on this page, and the sentence says which:

- everything `stayfixed init` writes into a repository, which `upgrade` refreshes and `uninstall`
  takes back: the write-once files (`stayfixed.toml`, `CLAUDE.md` and the `AGENTS.md` skeleton) and
  the rest;
- the rest alone, the second of the two passes those commands plan: the report headed `scaffold:`
  and the `scaffold` key of their `--json`, beside the write-once pass's `write-once:` report and
  `once` key (`upgrade` plans this pass alone, so it prints no `write-once:`);
- the scaffold engine, which plans and writes both passes and reports every action in the same
  verbs, `stayfixed overlay upgrade`'s included.

---

## Configuration

`stayfixed.toml` in the project root, committed. Every value is repository-controlled, which is
why so few of them are trusted with anything.

```toml
[stayfixed]
version = "0.6.1"        # required; there is no default
enforced = []            # tool-owned: the gates that enforce, each promoted when it passed
preset = "recommended"
profile = ""
agents = ["claude", "codex"]

[project]
name = "widget"          # one lowercase path segment
base_branch = "main"
release_branch = "main"

[paths]                  # each inside the root, out of .git and .stayfixed, 1024 characters at most
agents_md = "AGENTS.md"
architecture = "docs/architecture"
runbooks = "docs/runbooks"
adr = "docs/adr"
specs = "docs/specs"
plans = "docs/plans"
bugs = "docs/bugs"
bug_index = "docs/bug-reports.md"
roadmap = "docs/roadmap.md"
roadmap_history = "docs/roadmap-history.md"
memory = "docs/memory"
stayfixed = "docs/stayfixed" # stayfixed's own project files: <stayfixed>/rules/<profile>.md

[memory]
mode = "harness"         # harness | overlay | in-repo | local-only — default: harness
groups = ["developer", "project-stable", "project-volatile", "specs"]
index_extra = []         # extra pointers rendered into MEMORY.md

[ledger]
id_prefix = "BR"         # a capital letter, then up to seven more capitals or digits
code_roots = ["src", "tests", "scripts"]
evidence_boundary_required_for = ["high"]

[budgets]                # the base branch raises or lowers a budget; a pull request lowers a gate's
agents_md_lines = 300
agents_md_words = 3000
status_lines = 50
roadmap_prose_lines = 350
roadmap_prose_words = 3500
memory_index_words = 1200
startup_rules_words = 1600
volatile_notes_words = 2500
volatile_ttl_days = 30

[artifacts]
local = []               # scaffold template ids whose artifact is written under
                         # .stayfixed/local/artifacts/ instead of being committed; never
                         # config or gitignore, which only work at the repository root

[ci]
mode = "reusable"        # reusable | uvx | none — how this project means to be gated
ref = ""                 # the commit of the stayfixed release the workflow is pinned to;
                         # `init` writes it; from 1.0.0, `v1` is the mutable opt-in
gate_branch = "main"     # the branch the workflow gates; left out, [project] base_branch

[gates]
builtin = ["docs", "bugs", "plan", "commit", "trail"]  # the built-in gates this project runs
custom_timeout_seconds = 600  # seconds a gate of your own may run: a whole number above 0
                              # and below 2,147,483,648
# [gates.custom.tests]         # zero or more gates of your own, each a table like this
# run = ["pytest", "-q"]       # an argv, never a shell string

[commit_messages]
attribution_check = false # whether `commit check` enforces the attribution block
types = ["feat", "fix", "build", "chore", "ci", "docs", "perf", "refactor", "revert", "style", "test"]

[guards]
bg_cleanup = true        # false switches the bg-cleanup session guard off by default here;
                         # the overlay's files and the machine file override it
```

**Eleven sections, and the list is closed**: a section this block does not show is refused when
the file loads (`unknown section(s)`), so the grammar above is the whole of it. All three
`[ci]` keys are read today: `mode` decides whether `stayfixed init` renders a CI workflow at all
and which form, `gate_branch` is the branch the rendered workflow gates — it runs for pull
requests into it and pushes to it, and passes it as a literal `base:`; left out, it is `[project]
base_branch`, so a file that names `develop` as its base gates `develop`, and `stayfixed upgrade`
re-renders a caller you have not edited for that branch where an earlier release gated `main`;
set `[ci] gate_branch = "main"` to keep the old one — and `ref` is written by `init` and judged by
`doctor`'s `ci-ref` row. `[commit_messages] attribution_check` is read by
`commit check`, `[commit_messages] types` by `stayfixed assess`'s commit-vocabulary probe,
`[artifacts] local` by the scaffold engine, and `[gates]` and `[stayfixed] enforced` by
`stayfixed assess`, `stayfixed gate` and the reusable workflow. `[guards]` is the guards' default
for a session in this repository, which the overlay's files and the machine file override (below);
no command reads it.

**Commands refuse; a session reads what it can.** Every command that loads `stayfixed.toml`, but
`doctor` and `memory session-context`, refuses it whole over an unknown section or key, a value it
cannot use or a `[paths]` value that leaves the root, naming the key and never the value. Those
two read it the way a session does: an unknown section or key is ignored, a value that cannot be
used is put back to the preset's, one key at a time, a custom gate that cannot run is left out,
and each says so in a note naming the key, so a file a newer stayfixed wrote keeps every setting
this one understands. A repository's `[personal]` is the machine owner's to set and is ignored
the same way, with a note. A session drops the project configuration whole
only for a file it cannot read as TOML — a symbolic link, one that is not UTF-8, one it cannot
read, or one that is not TOML — and for a key nothing can stand in for: a key that has no default
(`[stayfixed] version`, `[project] name`) and is missing or cannot be used, or whose section is not
a table, or a key whose preset value does not hold in this repository either, such as a `[paths]`
default under a committed symbolic link. It then names that key rather than calling a key the file holds missing, and runs
the guards on the preset and the machine owner's layer ([`stayfixed hook
<event>`](#stayfixed-hook-event)).

Every value above is what a key you leave out takes, from the `recommended` preset — with three
exceptions. `[stayfixed] version` and `[project] name` have no default at all and are yours to
write: a file without `version` does not load at all (`[stayfixed] is missing required key(s):
version`). `[ci] gate_branch` has no preset default: left out, it is `[project] base_branch`, whose default is `main`. Everything else
from `[project] base_branch` down is the preset's default exactly as written. `[project]
base_branch` and `release_branch` are branch names git accepts, from letters, digits, `.`, `_`,
`-` and `/` (the grammar `--base-branch` and `[ci] gate_branch` follow); anything else does not
load, and the refusal names the key and never the value.

**Gates.** A gate is one check run over a pull request. `[gates] builtin` names which of
stayfixed's own five the project runs, all of them by default, and each
`[gates.custom.<name>]` names one of the project's own: `run` is an argv to run from the
project root, never through a shell, given `custom_timeout_seconds` to finish, and a non-zero
exit is its one finding. Past that limit its process group gets SIGTERM and, once the command
has exited or 5 seconds have passed, SIGKILL, so what it started can end its own children. A custom gate's name is one lowercase path segment, neither a
built-in gate's name nor `config`, which names the configuration check. `stayfixed assess`,
`stayfixed gate` and [the reusable workflow](#the-reusable-workflow) run exactly the configured
gates. A custom gate runs only from a command a person or a workflow runs on purpose, never
from a hook or `doctor`, so running such a command in a clone runs the commands that clone
configured, as running its test suite would. The `docs` and `trail` gates judge tracked files,
so a project that keeps its roadmap or its `AGENTS.md` out of git — ignored, never added, or
written under `[artifacts] local` — drops `trail` or `docs` from `[gates] builtin`: those gates
read the committed place, where in CI the file is not, and `stayfixed assess` reports such a gate
and `stayfixed adopt promote` never enforces it.

**A fixed bug's regression as a gate.** [`stayfixed bugs regressions`](#stayfixed-bugs-regressions)
runs as a custom gate. Where an installed `stayfixed` is on `PATH`, as on a machine stayfixed was
installed on, the gate is

```toml
[gates.custom.regressions]
run = ["stayfixed", "bugs", "regressions"]
```

and each regression's runner must be on `PATH` there too: a project whose runner lives in an
environment of its own writes each `regression` wrapped in the command that provides it, such as
`["uv", "run", "pytest", "tests/test_total.py"]`, which `prove` reads past to the runner. Neither
holds in [the reusable workflow](#the-reusable-workflow). Its step "The project's own gates" has
the runner image and the interpreter `python-version` names and nothing more, so no `stayfixed`,
`uv` or `pytest` is on `PATH`, and the workflow's own stayfixed is reached through `PYTHONPATH`
alone. There the gate's own `run` provides the runner, for example in a scratch virtual environment put first on
`PATH`, which a system interpreter marked externally managed allows where it refuses a bare
`pip install`:

```toml
[gates.custom.regressions]
run = ["sh", "-c", 'v="$(mktemp -d)" && python3 -m venv "$v" && "$v/bin/pip" install -q pytest==9.1.1 && PATH="$v/bin:$PATH" exec python3 -P -m stayfixed bugs regressions']
```

Each `regression` then names the runner itself, `["pytest", "tests/test_total.py"]`, and what its
tests import is added to the install, pinned as pytest is. `-P` keeps the project root off the
module path, as the step's own `python3 -P -s -m stayfixed` does. This `run` reaches stayfixed only
where `PYTHONPATH` names it, so on a machine `stayfixed bugs regressions` is run directly. The
installation, every regression and the gate itself are bounded by the same `custom_timeout_seconds`,
so a project with many slow regressions raises it; a set that runs past it ends as a gate that could
not run, never as a pass. Named in `[stayfixed] enforced`, the gate makes a regression that is not
proved fail the run; otherwise it is advisory, like any other gate.

**Enforcement is per gate.** `[stayfixed] enforced` is the one adoption key: it lists the gates
that enforce, configured gates each named once, and nothing else makes a gate enforce. It is
stayfixed's to write (`stayfixed adopt promote` adds each gate as it passes), and a person may
write it too; the loader refuses a name the project does not run and a name given twice. Left
out, or empty, nothing enforces. A project that has promoted every gate lists every gate, and a
gate it adds later is advisory until the list names it. `[stayfixed] state`, which once stated a
lifecycle beside the list, is gone: the loader refuses it as any key it does not have. A gate
enforces when the base branch's list names it or the change under review adds it there, so a
change that lists a gate is held to it in its own run; every other gate is advisory.
[The reusable workflow](#the-reusable-workflow) says what each means for a run.

**Which command reads which path.** `agents_md` and `roadmap` are the two documents `docs check`
budgets, and the roadmap is also what `docs trail` writes into; `specs` and `plans` are the two
trees `docs trail` lists, and `plans` is where `plan check` looks for the plans a diff touched.
`bugs` is the ledger's entry directory and `bug_index` its generated index — `bugs new`,
`bugs index`, `bugs check` and `bugs renumber` all read both — and `runbooks` supplies the
`<runbooks>/bug-reports.md` link that index's generated header writes. `memory` is the note
store, which `memory refs` walks. `stayfixed` is the directory stayfixed's own project files go
under, so that `uninstall` can account for them and a reader can find them; a stack profile's
rules are the first, at `<stayfixed>/rules/<profile>.md`. The remaining three are read for their
location alone, and so is every one of the others: `bugs check` treats the first component of
every `[paths]` value that has more than one — `docs`, for the defaults — as a directory
documents live in, and therefore as a place a citation of an entry file may be written and must
resolve. Pointing a path key somewhere unusual widens that sweep; it cannot take a document
outside it, because a value that leaves the root is refused before any command runs.

**`[ledger]`.** `id_prefix` is the one definition of what an identifier looks like: `BR-001`,
and `BR-nnn` in every message. It is interpolated into patterns and filenames, so it is held to
a shape — a capital letter followed by up to seven more capitals or digits — and a prefix
outside it is a refusal (`2`), not a finding. The number is three digits or more. `code_roots`
are the trees `bugs check` sweeps for mentions of an identifier, each of which must have an
entry behind it, and the trees `memory refs`, `test hygiene` and the `todo-markers` probe
walk. `src/` and `./src` are read as `src`. An entry that names the repository root itself,
leaves the repository, passes through a link, a `..` or `.git`, or names no directory is walked
by none of them and refused by nothing: `stayfixed assess`'s `code-roots` item counts it, and
`.stayfixed/assessment.json` names it with the reason, except a missing directory the preset's
default lists while another entry is walked, which then loses no walk.
`evidence_boundary_required_for` names the severities whose entries must carry a filled
`**What this evidence does not establish:**` line, the template's placeholder not counting. Widening it is how a project asks the same of `medium`. Each value must be one of the
severities, `high`, `medium` and `low`, spelled as the table below spells it. A value that names
none would require the line of no entry, so it is a refusal (`2`), counted and not quoted, of
every command that reads the ledger — `bugs`, `plan check`, `memory refs`, `init` and `upgrade`
among them — and never of `uninstall`. An empty list is the project asking it of no severity.

**The two ledger vocabularies**, neither of them configurable — they are the entry contract, and
a value outside either is a finding (`1`) naming the file:

| Field | Values |
|---|---|
| `status:` | `open`, `partial`, `fixed`, `rejected`, `void` |
| `severity:` | `high`, `medium`, `low` |

`void` is the one that is not a state of a bug: it records a number that was allocated and never
carried one — what `bugs renumber` leaves behind at the old identifier — and it is the only
status that needs neither `severity:` nor `area:`. `severity` is `bugs new`'s required
`--severity`, and `--area` beside it is free text that becomes the entry's Area column.

**`[budgets]`.** The first five are the documentation budgets `docs check` enforces:
`agents_md_lines`, `agents_md_words` and `status_lines` over the always-loaded document and its
`## Current status` section, `roadmap_prose_lines` and `roadmap_prose_words` over the roadmap
above its trail marker. The last four bound the memory store. The base branch and the machine
owner raise or lower a budget — the base branch's `stayfixed.toml` any of the nine, the machine
file a session's four — and the value set is the value in force. A pull request lowers a gate's
budget only (`stayfixed gate` refuses a raise), and may move a session's,
which no gate reads.

`~/.config/stayfixed/config.toml` is yours, not the project's:

```toml
[personal]
preset = "recommended"   # the preset `setup` applies

[overlay]
root = "~/stayfixed-overlay"   # only read in overlay mode

[guards]
bg_cleanup = true        # false switches the bg-cleanup session guard off on this machine,
                         # whatever a repository's stayfixed.toml sets

[budgets]                # the session's budgets only, which win over a project's
memory_index_words = 1200
startup_rules_words = 1600
volatile_notes_words = 2500
volatile_ttl_days = 30
```

`[guards]` here is the last word on a session guard, and it is yours: a repository's
`stayfixed.toml` sets the default, the overlay's files move it, and this file wins over both.
`[budgets]` here holds only the four budgets that bound
what a session loads; the five a gate judges a pull request by (`agents_md_lines`,
`agents_md_words`, `status_lines`, `roadmap_prose_lines`, `roadmap_prose_words`) are the
repository's alone: one written here is ignored, with a note. Every key you leave out is the
preset's. A command that loads `stayfixed.toml` reads this file's `[personal]`, `[guards]` and
`[budgets]` too, as a session reads them, so `memory fit`, `memory index` and `memory inventory`
measure the session budgets a session runs on. What you write here is honoured, and what this
stayfixed cannot use is said and never refused: a key in those three tables it does not know, a
value it cannot use or a table that is not one costs that key or table alone — an unknown key is
ignored, an unusable value is put back to the preset's — and a command says so on stderr, once
however many documents it loads, naming the file and the key, while a session says so once, when
it starts. So a key a later release's
`setup` writes stops no older command on the machine. Only a file that does not load at all is
refused by a command, as `[overlay] root`'s reader refuses it, before the command reads anything
else, and leaves a session on the preset's personal values and guards, with one warning naming
this file when the session starts and `stayfixed doctor`'s `preferences` row red.
With no `stayfixed.toml` in the repository a session still reads this file: `bg_cleanup = false`
turns the guard off there too.

Between the repository's file and this one, a session reads the overlay's two, under the overlay
`[overlay] root` names: `<overlay>/common/stayfixed.toml` for every checkout, and
`<overlay>/projects/<name>/stayfixed.toml` for a checkout this machine binds to `<name>` — by the
binding id `stayfixed attach` records, never by the repository's own `[project] name`, so a clone
that names one of your projects gets the common file alone. Each may set a `[personal]` value, a
`[guards]` switch, a preference (`[memory] mode`, `groups` and `index_extra`, `[stayfixed]
profile`) and a session budget; the project file wins over the common one, and this file over
both. They are read the way a session reads `stayfixed.toml`: an unknown name is ignored, and a
value this stayfixed cannot use is left out so the layer beneath applies; a gate's input or a fact
about the repository written there is never taken from it. A missing file, an overlay this file
does not record, or this file not loading sets nothing. A session, `doctor`, `memory
session-context`, `attach`, `attach --check`, `detach` and the other `memory` commands read them
all through the same resolution, so what decides the store `attach` builds is what a session asks
for; every other command reads the repository's file and this one, and `doctor`'s `preferences`
row names the layer each value came from.

To state a language preference, write a personal standing rule, a note with `metadata.startup`
in your overlay's `common/memory/`.

`stayfixed setup` writes one more table, `[machine]`, into the same file — `version`, the
stayfixed that ran, and `installed`, the date it ran. It is `setup`'s record of what it did, not
a setting: it is written, never hand-edited, and a file that has never had one loads fine.

**This file's location is not selectable by a repository.** The path is
`~/.config/stayfixed/config.toml`, and neither `STAYFIXED_CONFIG` nor `XDG_CONFIG_HOME` changes
it: a committed `.claude/settings.json` `env` block would otherwise choose your overlay root
and your trust record. Pass `--machine <path>` to read a different file — a path you typed
rather than one an environment chose, and honoured by every reader of it.

**`~` here is `HOME`**, as the harness and every other program read it, so a devcontainer, a
home-manager setup or a scratch `HOME` keeps stayfixed and the harness under one home; a `~` in
`[overlay] root` means that home too. An environment that sets `HOME` already runs code as you.
An empty or relative `HOME` names no home, so `setup`, `attach` and `detach` stop there and
`doctor` says so; `doctor`'s `ignored-env` row says, as information, when `HOME` is not the home
the password database records.

Only `[overlay]` and the trust record used to be held to that rule while `[personal]` followed
the environment, so one command could read the two halves of this file from two different files.
