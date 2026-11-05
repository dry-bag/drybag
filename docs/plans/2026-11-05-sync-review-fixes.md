# Note sync, the review fixes for #162: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking. **The wave is the dispatch
> unit, not the task:** one implementer per lettered wave (A–F), each task inside it keeping its own
> failing test, verification and commit. Waves run in order in one worktree. One pull request into
> `next` for the whole plan; one final review and one scoped re-review, both run by the
> controller's second reviewer session (see "Execution contract"). No per-wave review.

**Goal:** the note sync that #162 landed does what its docs say with less code: no note name or
session environment lets a secret or the notes go somewhere they should not, git does the commits
and the moves of `main` that the job now builds by hand, a rewrite the owner made is held rather
than undone, `doctor` says when the sync is not running and what a standing failure needs, Codex
sessions start nothing, and the generated `MEMORY.md` indexes stop travelling: each machine renders
its own.

**Architecture:** no new area. Two core modules grow by what the sync's own runner did:
`src/stayfixed/processes.py` gains a bounded launch that ends the process group, and
`src/stayfixed/gitenv.py` one environment for every git stayfixed starts, with the suite's floor.
`src/stayfixed/sync/` loses its runner, its scanner lookup, its pre-render, its index unions, its
hand-built index commit and its alignment of the real index. The memory area gains one handler that
renders a bound overlay checkout's index at `SessionStart` and `SessionEnd`.

**Tech Stack:** Python ≥ 3.11 standard library; git ≥ 2.43 (unchanged); gitleaks from `PATH`;
pytest with real git repositories under `tmp_path`; the mutation oracle (`sync/` and the core files
route to `mutations/core.toml`).

**Scope:** the findings of an independent review of #162 that hold, verified against `next`; one
pull request into `next`. Out of scope: the overlay itself (untracking the indexes it commits, its
ignore file, its own delivery check and its own sync hook change on the overlay's side, by its
owner); a cloud mode; collapsing the outcome vocabulary; the overlay's CI scan.

**Premise:** measured on `next` at `53fdd72` by reading the tree and by scratch experiments under
an isolated `HOME` (never the real one). Each wave re-measures its part and stops on a mismatch.

- Size. The `.py` files of `src/stayfixed/sync/` are 3,126 lines against the sync plan's budget of
  2,500 (`docs/plans/2026-11-02-restructure-sync.md`, "Size and budget"); that plan's `## Findings`
  is empty, so the overrun was neither stopped nor recorded. `tests/sync/` is 6,676 lines;
  `mutations/core.toml` holds 132 entries whose `file` is under `src/stayfixed/sync/`.
- The indexes. `src/stayfixed/sync/render.py` (117 lines) pre-renders each project's index through
  `memory.index.rerender_overlay_index` (`src/stayfixed/memory/index.py:556-587`) from checkouts
  recorded in `checkouts.json` by `trigger.trigger` (`src/stayfixed/sync/trigger.py:174-175`);
  `job.union_index`, `_resolve_by_union`, `_unite_worktree` (`src/stayfixed/sync/job.py:641-684,
  794-819`) unite two renderings; `resolved_index` is a settled outcome
  (`src/stayfixed/sync/state.py:33-41`). `rules.MemoryPath.is_index` marks a project's
  `MEMORY.md`, which the pathspec includes (`src/stayfixed/sync/rules.py:34-44, 65-68`). The only
  other renderer that runs unasked is `attach`'s `render_missing_index`
  (`src/stayfixed/memory/composed.py:136-152`). Hook areas are dispatched in area-name order
  (`src/stayfixed/hooks/registry.py`, docstring), so `memory` runs before `sync`.
- The environment. `sync.git.run` copies `os.environ` less 15 repository variables and the askpass
  pair (`src/stayfixed/sync/git.py:37-45, 89-97`): `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`,
  `GIT_EXEC_PATH`, `GIT_PROXY_COMMAND`, `PRE_COMMIT_HOME` and `XDG_CACHE_HOME` reach the job.
  `runner._ENV_DROP` drops another list (`src/stayfixed/runner.py:58-68`), `gitenv.GIT_ENV_KEEP`
  keeps five names (`src/stayfixed/gitenv.py:47`), and only `git_run` honours
  `gitenv.FLOOR_VARIABLE` (`src/stayfixed/gitenv.py:84, 99-113, 251-278`), so `tests/sync` passes
  `SLOW` as a bound about 104 times. `job_env` re-derives git's ssh command
  (`src/stayfixed/sync/git.py:178-216`).
- The scanner. `scan.gitleaks_pin` reads `.pre-commit-config.yaml` line by line and
  `gitleaks_binary` reads pre-commit's sqlite database (`src/stayfixed/sync/scan.py:79-173`), whose
  location comes from the session's `PRE_COMMIT_HOME` or `XDG_CACHE_HOME`. Measured: `which
  gitleaks` finds a Homebrew gitleaks 8.30.1; the desktop app's own process has the minimal
  `/usr/bin:/bin:/usr/sbin:/sbin`, but the Claude Code process it starts, which starts the hooks,
  carries the login `PATH` with the Homebrew directory.
- The scans. With no committed `.gitleaks.toml` every scan runs on the default rules, whose global
  path allowlist skips names a note writer chooses (`src/stayfixed/sync/scan.py:234-244`).
  Measured with the real gitleaks 8.30.1 on one commit of four notes holding a GitHub token: a
  `gitleaks git` scan reported one, the note whose name holds no allowlisted part; a config of
  `[extend] useDefault = true` reported the same one; `gitleaks dir` over the four blobs written
  as files `1` to `4` in a scratch directory reported all four. The commit-time scan stops every
  note for one finding (`src/stayfixed/sync/job.py:430-438`), and the push's `secret_found` detail
  carries its remedy last (`src/stayfixed/sync/job.py:971-973`).
- The commit and the moves. `commit_memory` builds the commit in a temporary index and moves `main`
  by a recorded compare-and-swap; `align`, `align_first`, `_finish_worktree`, `_index_needs_align`,
  `_blocked` and `PendingAlign` re-implement git's index and working-tree update
  (`src/stayfixed/sync/job.py:236-246, 255-571, 748-772`; `src/stayfixed/sync/state.py:108-114`).
  Measured in scratch repositories: `git add -N` then `git commit --only` with
  `GIT_LITERAL_PATHSPECS=1` and `--pathspec-from-file` commits only the listed notes and leaves the
  owner's staged work staged; `git read-tree -m -u H T` writes incoming notes, keeps the owner's
  staging and untracked files, and refuses with exit 128 and nothing written a dirty clashing note,
  an untracked file where a note lands, a link standing in place of a directory above an incoming
  note (the link stays), and an index with unmerged entries. **But `git commit --only` of a path
  with unmerged entries left by a conflicted `stash pop` exits 0 and commits its conflict markers**:
  git does not guard that case, so the unmerged re-check before the commit stays.
  With `-c core.hooksPath=/dev/null` a `commit --only` ran none of five planted hooks; without it
  the job's own `update-ref` and `push` run `reference-transaction` and `pre-push`
  (`src/stayfixed/sync/job.py:314-319, 1013-1016`).
- A local rewrite. `_dropped` (`src/stayfixed/sync/job.py:782-791`) catches only commits upstream
  lost; after the owner's `git reset --hard <sha>~1` of a pushed note, with or without a new commit,
  `integrate` replays or fast-forwards the purged note back.
- Codex. The handlers read only the switch (`src/stayfixed/sync/hooks.py:23-31`); Codex reads the
  same `hooks/hooks.json` (`docs/cli.md`, "Hooks") and sets `PLUGIN_ROOT`, which Claude Code does
  not (`src/stayfixed/harnesses.py:172-179`).
- `doctor`. It prints the detail's first line and promises a retry for every non-settled outcome
  (`src/stayfixed/sync/doctor.py:116-121`); `skipped` is settled, so "on feature, not main" and
  "main tracks nothing" read green, and `setup --overlay <path>` renders an overlay with no remote
  and switches sync on (`src/stayfixed/overlay/create.py:139-180`,
  `src/stayfixed/setup/run.py:671-674`).
- The switch. `sync.switch.enabled()` reads the machine file on every turn
  (`src/stayfixed/sync/switch.py:22-33`) while the handler is handed the session's resolved
  configuration; the core carries a machine key through `Owner` (`src/stayfixed/config/owner.py:57`),
  as `hints` reads its guard (`src/stayfixed/hints/hooks.py:63`).

## Decisions

- **D1 — the indexes are local** (the owner's decision). A project's `MEMORY.md` is not memory to
  the sync: the pathspec carries `:(top,exclude,glob)projects/*/memory/MEMORY.md`, `memory_path`
  answers `None` for it, so the job never stages or writes one, and a range that changes one is
  outside memory (a hold, or a local hold for the owner's own commit). Each machine renders its own
  through the memory area's new `index-render` handler, on `SessionStart` and on `SessionEnd`, for a
  session whose checkout is bound in overlay mode, through the session's own configuration (no
  second resolution). `SessionEnd` harvests the lines a session appended outside the
  `stayfixed:index` region into notes on the machine that wrote them, before the sync's own
  `SessionEnd` handler starts the job (area order), so those notes travel in that job. `SessionStart`
  renders what the jobs integrated since; whether Claude Code reads `MEMORY.md` before or after its
  `SessionStart` hooks finish is unmeasured, and the `SessionEnd` render makes the next session's
  index current either way for everything integrated before the previous session ended. Priced at
  about +30 `src`; `rerender_overlay_index` (32 lines) goes.
- **D2 — one environment for every git.** `gitenv.scrubbed_env()` is the policy: the five
  `GIT_ENV_KEEP` names plus `SSH_AUTH_SOCK` (the push's and an ssh clone's agent) and the proxy
  variables curl reads (`http_proxy`, `https_proxy`, `HTTPS_PROXY`, `all_proxy`, `ALL_PROXY`,
  `no_proxy`, `NO_PROXY`), `PATH` with its relative entries dropped, `GIT_TERMINAL_PROMPT=0`.
  `gitenv.git_call` starts git with it through `processes.run_bounded`, at no less than the floor;
  `Runner.launch` gives an argv whose program is `git` the same environment. The sync adds only its
  own settings: `GIT_ATTR_SOURCE=HEAD`, `GIT_NO_REPLACE_OBJECTS=1`, `LC_ALL=C` (its few message
  matches read English whatever the locale), `core.askPass` empty and `core.hooksPath=/dev/null`.
  No ssh options: a child with no terminal, no stdin, no askpass and a group kill at its step's
  bound cannot wait for a person.
- **D3 — the scanner is the gitleaks on `PATH`** (the policy's `PATH`), looked up once per job. No
  machine-file key: no case was found that `PATH` cannot serve. Missing, it is `scan_unavailable`
  with the remedy to install gitleaks on the `PATH` the sessions run with.
- **D4 — every scan reads content only.** The items (bytes, each with a label) are written as files
  named `1`, `2`, … in the job's scratch directory and scanned by `gitleaks dir .` run there, with
  `--config` naming `HEAD`'s `.gitleaks.toml` or, when none is committed, a file holding
  `[extend] useDefault = true`. No path of the overlay reaches gitleaks, so no path allowlist and no
  `.gitleaksignore` fingerprint applies; a committed rule set's content allowlists still do. The
  commit's items are the working-tree bytes of each note to be committed; the push's are every new
  blob of the range, read raw by one `git cat-file --batch`, and each commit's metadata.
- **D5 — git commits and moves `main`.** The commit is `git add -N` for new notes, `git diff --raw
  --numstat HEAD` to judge them, and `git commit --only` of the notes that pass. Integration writes
  the working tree and the index first (`git read-tree -m -u <head> <tip>`), then moves `main` by
  `update-ref` compare-and-swap. The temporary index of the commit, the pending-align record, the
  alignment of the real index, the two-way merge and its dirty-clash check go; the unmerged re-check
  before the commit stays (Premise), and the scratch readability check of an upstream tree stays.
- **D6 — a local rewrite is held.** The mirror of the upstream rewrite hold: commits of
  `HEAD..upstream` that the `HEAD` the last job recorded had and `HEAD` no longer has are held,
  never replayed or fast-forwarded back.
- **D7 — Codex starts nothing:** the handlers return at once when `CODEX.detects(os.environ, None)`,
  the environment half of Codex's detection, never the payload half.
- **D8 — `doctor` reports `skipped` as a warning** and, for a standing outcome, says that a rerun
  meets it again until the owner acts; a standing outcome's detail opens with its remedy.
- **D9 — the switch is read through `Owner`:** `Owner.sync.enabled`, from the machine file's
  `[sync]`, as `[guards]` is read; `src/stayfixed/sync/switch.py` goes.

### Crash ordering, on git's terms (for the pull request's body)

- **Killed inside `git commit --only`.** git writes the commit, moves `main`, and only then renames
  its `index.lock` over the real index. Killed between the last two, git leaves `index.lock`, and
  every later index-writing git, the owner's and the job's alike, refuses with git's own message
  until it is removed: the state any `git commit` of the owner's leaves when killed. The job never
  removes the lock (it cannot tell a stale lock from a live one); its outcome is `raced` with git's
  words, which `doctor` shows.
- **Killed between `git commit --only` and the push.** The commit is whole: `main` and the real
  index agree. The next job finds no dirty note for those paths, fetches, replays the commit onto an
  upstream that moved, and pushes the scanned range. Killed between `git add -N` and the commit,
  the real index holds intent-to-add entries for new notes, which no `git commit` of the owner's
  carries; the next job adds them again (a no-op) and commits them.
- **Killed between `read-tree -m -u` and `update-ref`.** `main` is still at `head`; the index and
  the working tree hold the incoming notes, which `git status` shows as staged memory changes whose
  content is upstream's. An owner's commit in that window carries them, losing nothing. The next job
  commits them as its own memory commit, fetches, and its replay of that commit onto upstream finds
  the tree upstream already has and drops it (the existing "already upstream" rule); `read-tree`
  is then a no-op and `update-ref` moves `main` to upstream. Nothing is recorded, and nothing needs
  to be.
- **The other order is not used.** With `update-ref` first, a kill before `read-tree` leaves `main`
  at the tip and the index and working tree at the old notes: `git status` shows the incoming notes
  reverted, the owner's next commit would carry the revert, and so would the job's next commit,
  unless a record told it to finish first. That record (and its false positives once the owner
  stages over it) is what this plan deletes.
- **A compare-and-swap that fails** after `read-tree` (the owner committed meanwhile) is the second
  state above with the owner's commit on top of `head`: `raced` now, and the next job converges as
  above, or holds locally if the owner's commit is not memory alone.

### Controls kept or added, with adversary and anchor

| Control | Stops | Anchor, and why the adversary cannot move it |
|---|---|---|
| memory-only rule (pathspec with the index excluded, `is_note`, modes, binary; the tree bound) | executable, hidden or generated content arriving from the remote or written by a memory writer here | git's record of the paths and modes of the judged sha, or of `HEAD` against the working tree for the commit (`git diff --raw`), and the constants in `sync.rules`, which no repository byte reaches |
| `fetch.fsckObjects` | a tree with a `..` or `.git` name | the job's own `-c`, which upstream cannot move |
| upstream rewrite hold (kept); local rewrite hold (added, D6) | upstream dropping commits this overlay has; the owner's reset or rebase of pushed notes being replayed back by the next job | `fetched_sha` and `head` in the owner's state file, and git's ancestry; upstream writes neither file |
| the compare-and-swap of `main` in integration, and `read-tree -m -u`'s refusals | the owner's concurrent git; an uncommitted edit, an untracked file or a link where an incoming note lands | the ref, read once; git's two-tree rules against the index and the working tree, which refuse before writing |
| the unmerged re-check before the commit | a conflicted `stash pop` during the job, whose markers `commit --only` would commit (Premise) | the real index's unmerged entries, asked right before the commit |
| one environment for every git (D2) | whatever environment the session that fired carries: a per-project `GIT_CONFIG_GLOBAL` with `pushurl` or `insteadOf`, a `PRE_COMMIT_HOME`, a `GIT_SSH_COMMAND`, an inherited `GIT_DIR` | an allowlist in `src/stayfixed/gitenv.py`; destination and scanner then come from the configuration under `HOME`, the overlay's own configuration and `PATH`. What sets `PATH` chooses `git` itself as readily, so `PATH` is the anchor every git of the product already has |
| `PATH` without relative entries (moved to the policy) | a `git`, `ssh` or `gitleaks` planted where a git runs, on a `PATH` with a `.` | the absolute entries of the inherited `PATH`; a convenience that refuses nobody |
| the content-only scan before the commit and before the push (D4) | an honest mistake: a token pasted into a note, under any name, or into a message | the bytes git commits and pushes, scanned under neutral names, with `HEAD`'s rules or gitleaks' own defaults; an agent with a shell can push by hand anyway |
| no scanner, nothing committed or pushed | a machine without gitleaks pushing unscanned | the policy's `PATH` lookup, fail-closed |
| `GIT_ATTR_SOURCE=HEAD`, `GIT_NO_REPLACE_OBJECTS=1` | a working-tree filter or a replace ref | the committed tree and the job's own environment; the scans no longer depend on attributes, since they read raw bytes |
| `core.hooksPath=/dev/null` (added) | not an adversary: an overlay's hook framework building or prompting inside an unattended, bounded job | the job's own `-c`, which no configuration file overrides; whoever writes `.git` runs code anyway, so this is predictability, not containment |
| Codex starts nothing (added, D7) | a requirement, not a boundary | Codex's own `PLUGIN_ROOT` in the hook's environment; a repository that sets it in a Claude Code session switches its own triggers off, never on |
| the switch, machine-only (kept, now through `Owner`) | a hostile clone switching a machine's sync | the machine file in the owner's home |
| the lock; the `-I` spawn (kept) | concurrent jobs; a planted module at the overlay's root | the kernel's `flock`; the interpreter's isolated mode |
| the guard (kept, now visible, D8) | acting on an overlay mid-operation, on another branch or tracking nothing | git's own state |

## Execution contract

1. **Final review:** one, on the pull request, run by the controller's second reviewer session:
   correctness; "what can be deleted / who does this refuse"; security (what reaches the remote,
   what runs, what the working tree and real index see). One scoped re-review of the fix commits,
   then stop. Only Critical and Important findings open a round; Minors become follow-ups.
2. **Lifecycle matrix:** the table below, checked at pre-flight like a task.
3. **Parallelism:** waves in order in one worktree; read-only seats may run beside an implementer;
   one oracle at a time.
4. **Seams the tests patch.** Tests patch `job.git`, `job._swap`, `job._before_swap`, `job.align`,
   `job.union_index`, `job.prerender`, `scan.gitleaks_binary`, `subprocess.Popen` and others. A task
   that moves or deletes one retargets each patch to the new seam and proves the retargeted test
   still reddens, through its mutation entry or by hand, before it commits: a patch of a name nobody
   calls any more turns a test green without testing anything.
5. **Verification:** focused runs while iterating; one full suite before each push, also on Python
   3.13; paste what a command printed; a predicted mutation outcome is a hypothesis until the oracle
   prints it. The oracle locally only with a pattern (`sync/`, `gitenv`, `processes`, `runner`,
   `memory/hooks`, `config/owner`).
6. **Briefs** carry: no line numbers from this plan (the Premise's are for the reviewer); report a
   mismatch between plan and tree instead of guessing; write nothing under the repository but this
   plan's change; a private scratch directory per agent; never kill by a name pattern; never run the
   job, a hook, `doctor` or `setup` against the real `HOME` or any real overlay.

**Budget.** The net of `src` plus `tests` is negative across the plan and in every wave but E.
Expected net per wave (`src` / `tests` / mutation entries / docs): A −200 / −390 / −10 / −15;
B −55 / −30 / −3 / −5; C −200 / −300 / −9 / −10; D −190 / −300 / −7 / −15; E −10 / +50 / +5 / +10;
F −40 / −215 / 0 / +5. Total ≈ −695 `src` (the sync area to about 2,350 lines), ≈ −1,185 tests,
≈ −24 entries, ≈ −30 docs. A wave whose `src` net comes out more than 50 lines above its estimate
stops and reports before it commits; the estimate is never met by deleting a test that holds
behaviour or by packing code denser. Each report prints
`git diff --shortstat <wave base> HEAD -- src tests mutations docs`.

## Global constraints

- English only. No AI attribution in commits, the pull request or any file.
- No vendor-prefixed branch name; the branch is `restructure/sync-review-fixes`.
- `tests/test_neutral.py`: no bare 8–10-hex commit id (seven characters, as above) and no "PR"
  followed by a space and a hash; a pull request is cited as `#162`.
- No private paths, private ids or overlay names in tracked text; the overlay is "the overlay".
- Standard library only. Writes through git or `fsops`; state through `fsops.write_atomically`.
- Every subprocess is a classified launch in `tests/outbound/policy.py`; every timeout a named cap.
- The job never force-pushes, stashes, rebases, pulls, writes or stages a path outside D1's notes,
  or runs a hook.
- Commits `fix(sync): …`, `refactor(sync): …`, `refactor(gitenv): …`, `feat(memory): …`,
  `test(sync): …`; changelog fragments as each task names.

## Lifecycle matrix

| Change | What the user sees | Held by |
|---|---|---|
| a project's `MEMORY.md` | never committed, pulled or pushed by the job; each overlay-mode session renders its own at start and end; a line an agent appended is harvested into a note on that machine at `SessionEnd` and that note travels | Tasks 1, 2 |
| an overlay that still tracks its indexes | the job leaves them alone; a local render makes them differ from `HEAD`, which starts no job; an upstream commit that changes or untracks one is held like any change outside memory, with the review command, until taken by hand once (the overlay's own untracking commit) | Task 2 |
| a state file whose outcome is `resolved_index` or `index_stale`, or that carries `pending_align` | the first is unreadable, replaced by the next job and said in its detail; the key is ignored | Tasks 2, 7 |
| a session whose environment sets `GIT_CONFIG_GLOBAL`, `url.*.insteadOf`, `pushurl`, `GIT_SSH_COMMAND`, `PRE_COMMIT_HOME` | none of them reaches the job's git or its scanner; `core.sshCommand` under `HOME` or in the overlay still applies; ssh agent and proxy variables still reach it | Tasks 3, 4, 5 |
| an unreachable host over ssh | `timeout` after the step's 30 s, where it was `offline` after 10 | Task 4 |
| the overlay's git hooks | the job runs none (`core.hooksPath=/dev/null`); the owner's credential helper, `core.sshCommand`, `gpg.program` and `core.fsmonitor` still run, as for the owner's own git; `docs/cli.md` says both | Task 4 |
| `setup --overlay create:` clones | unchanged; its `git` gets the same environment as every other | Task 3 |
| a machine with gitleaks only as pre-commit's build | `scan_unavailable` until gitleaks is on `PATH`, with that remedy; an `upgrading` changelog entry says so | Task 5 |
| a committed or working-tree `.gitleaksignore` | not honoured by the job's scans (fingerprints name paths it no longer shows); a working-tree one no longer stops the scan; a committed `.gitleaks.toml` still applies | Task 6 |
| a note whose name an allowlist names (`gitleaks.toml-tips.md`, a `node_modules` component) | scanned like any other | Task 6 |
| a secret in one note | that note is left out and named with its remedy; the other notes commit | Task 7 |
| the owner's staged non-memory work, untracked files | kept, now by git | Tasks 7, 8 |
| an incoming note dirty here, or a link above it | `waiting_clean_tree` with git's words; nothing written | Task 8 |
| a job killed mid-commit or mid-move | the states in "Crash ordering"; the next job converges with no record | Tasks 7, 8 |
| the owner resets or rebases away pushed notes | a hold naming the commits, nothing integrated or pushed; `doctor` gives the force-push and the rebase; cleared once either is done | Task 9 |
| a Codex session | starts nothing | Task 10 |
| sync off, on, a hand edit, a non-bool value | as before, read from the session's resolved configuration | Task 10 |
| the overlay on another branch, detached, or tracking nothing (a rendered overlay before its remote) | `doctor` warns with the reason and its remedy | Task 11 |
| a standing failure | `doctor` says a rerun meets it until the owner acts, and shows the remedy line | Tasks 6, 11 |
| git older than 2.43 | each trigger's job records `skipped`; `docs/cli.md` says so | Task 14 |
| the plugin removed | unchanged: the triggers go, the state directory stays (`checkouts.json` no longer written) | Task 2 |

## Review focus

1. **A secret under an allowlisted name.** Task 6's
   `test_a_note_name_never_exempts_it_from_the_scan` with the stand-in, and
   `test_the_real_gitleaks_finds_a_token_under_allowlisted_names`, skipped where no gitleaks is on
   `PATH`.
2. **The session's environment.** Task 4's `test_a_sessions_global_config_cannot_redirect_the_push`.
3. **The order of the move.** Task 8's `test_a_kill_between_the_write_and_the_move_converges` and the
   mutation "main moves before the working tree is written".
4. **Conflict markers.** Task 7's `test_a_stash_pop_conflicting_while_the_job_runs_is_never_committed`
   and the mutation "the unmerged entries are not asked again before the commit".
5. **A purge undone.** Task 9's `test_a_local_purge_is_held_not_undone`.
6. **The local render.** Task 1's `test_session_end_harvests_an_appended_line_before_the_sync_runs`.

## Launch graph

Drawn last, over the imports each task's Interfaces block names.

```
A (indexes local) ─► B (core environment) ─► C (scanner, scans) ─► D (git commits and moves) ─┐
                                                                                             ├─► F (cleanup, tests, docs)
                                              E (rewrite hold, Codex, switch, doctor) ◄──────┘
```

E runs after D (its hold sits in `integrate`, which D rewrites) and before F. No two waves run at
once: they write one worktree.

| Wave | Tasks | Why one dispatch | `src` / `tests` |
|---|---|---|---|
| A | 1–2 | the local render must exist before the job stops rendering | −200 / −390 |
| B | 3–4 | the sync's runner goes onto the launch the core gains | −55 / −30 |
| C | 5–6 | the scans run the scanner the lookup finds | −200 / −300 |
| D | 7–8 | every move of `main` and the index is git's after both | −190 / −300 |
| E | 9–11 | three small correctness fixes on files D leaves final | −10 / +50 |
| F | 12–14 | what is left once the code above is final | −40 / −215 |

---

## Wave A — the indexes stay on their machine (Tasks 1–2)

### Task 1: render a bound overlay checkout's index at session start and end

**Files:**
- Modify: `src/stayfixed/memory/hooks.py`, `src/stayfixed/memory/index.py`, `src/stayfixed/memory/api.py`, `docs/cli.md`
- Test: `tests/memory/test_index.py`, `tests/memory/test_surface.py`, `tests/boundaries/test_discovery.py`

**Interfaces:**
- Produces: a handler `index-render` registered on `SessionStart` and `SessionEnd` in
  `memory.hooks.register()`. It renders when `session.config` is not `None` and the store it
  resolves (`memory.store.resolved`, with the session's config) is in overlay mode; it runs
  `reconcile(write=True)`, `write_index`, and once more on drift, as `memory index` does; it returns
  an empty `HookResult` on every path and lets a failure cost itself alone (dispatch's per-handler
  catch). Every import inside the body.
- Consumes: `memory.index` `reconcile`, `render_index`, `write_index`, `check_index`.
- Removes (Task 2 deletes its caller): nothing yet; `rerender_overlay_index` stays until Task 2.

- [ ] **Step 1: failing tests.**
  - `test_session_start_renders_a_bound_overlay_checkouts_index`: an attached fixture checkout in
    overlay mode, a note added to its project's memory in the overlay; `stayfixed hook SessionStart`
    through the CLI in a scratch `HOME`; the overlay's `MEMORY.md` lists the note.
  - `test_session_end_harvests_an_appended_line_before_the_sync_runs`: a line appended outside the
    region; `hook SessionEnd` with sync on and the job's `spawn` patched to read `git status` of the
    overlay at the moment it is called; the harvested note is already dirty there.
  - `test_a_repository_mode_checkout_is_not_rendered` and
    `test_an_unbound_checkout_is_not_rendered`: the file is unchanged.
  - `test_discovery`: `memory.hooks` still imports nothing heavy at discovery.
- [ ] **Step 2:** `uv run pytest tests/memory -q` fails on the missing handler.
- [ ] **Step 3:** implement; `docs/cli.md`'s "Hooks" handler list and the memory section name it,
  and say which event harvests (D1).
- [ ] **Step 4:** `uv run pytest tests/memory tests/hooks tests/boundaries -q` passes.
- [ ] **Step 5: mutations** (added): "the session end renders no index" (the `SessionEnd`
  registration dropped); "a repository-mode checkout's index is rendered by a hook" (the mode test
  dropped).
- [ ] **Step 6:** commit `feat(memory): render a bound overlay checkout's index at session start and end`.

Expected net: `src` +30, tests +60.

### Task 2: the sync stops committing, pulling and uniting indexes

**Files:**
- Modify: `src/stayfixed/sync/rules.py`, `src/stayfixed/sync/job.py`, `src/stayfixed/sync/trigger.py`, `src/stayfixed/sync/state.py`, `src/stayfixed/sync/doctor.py`, `src/stayfixed/memory/index.py`, `src/stayfixed/memory/api.py`, `docs/cli.md`, `README.md`, `tests/outbound/policy.py`, `mutations/core.toml`
- Delete: `src/stayfixed/sync/render.py`, `tests/sync/test_render.py`
- Create: `changelog.d/+sync-indexes-local.upgrading.md`
- Test: `tests/sync/conftest.py`, `tests/sync/test_rules.py`, `tests/sync/test_commit.py`, `tests/sync/test_integrate.py`, `tests/sync/test_push.py`, `tests/sync/test_hooks.py`, `tests/sync/test_state.py`, `tests/memory/test_index.py`, `tests/memory/test_surface.py`

**Interfaces:**
- `rules.MEMORY_PATHSPEC` ends with the exclusion `:(top,exclude,glob)projects/*/memory/MEMORY.md`
  (built from `memory.index.INDEX_NAME`, `PROJECTS`, `STORE_DIR`); each spec of `MEMORY_SPECS` that
  a call uses alone (`git add -A -- <spec>`) is given with it. `memory_path` answers `None` for a
  project's index; `MemoryPath.is_index` and `index_of` go. `unsafe_parent` moves from `render.py`
  into `rules.py`, unchanged.
- `job`: `commit_memory(ctx)` (no `also`), no pre-render, no left-out indexes; `replay` returns
  `None` and the conflicting paths on any conflict; `_blocked` returns the blocked paths only.
  Deleted: `union_index`, `_resolve_by_union`, `_entry` (if no other caller), `_unite_worktree`,
  `_read`, `_projects`, `JobContext.resolved`.
- `state`: `OUTCOMES` loses `resolved_index`; `SETTLED = ("ok", "skipped")`; `CHECKOUTS_FILE` goes.
- `trigger.trigger` records no checkout. `memory.index.rerender_overlay_index` and `Rerendered` go,
  with their export.

- [ ] **Step 1: failing tests.**
  - `test_a_projects_index_is_not_memory` (rules: `memory_path`, the pathspec against git's own
    match, `entry_offends` on an added, a changed and a deleted index).
  - `test_a_dirty_index_is_never_committed` (commit: a rendered index beside a note; the commit
    holds the note only, the index stays dirty).
  - `test_an_upstream_index_change_is_held_like_a_path_outside_memory` (integrate: `REVIEW` named,
    nothing integrated or pushed).
  - `test_a_note_conflict_is_a_conflict_with_main_unmoved` stays; the index-union tests
    (`test_two_index_conflicts_are_resolved_by_union_and_re_rendered` and its kin) go.
  - `test_session_start_records_no_checkout` (hooks: no `checkouts.json` after `SessionStart`).
  - `test_a_resolved_index_state_is_unreadable_and_replaced` (state).
  - The `overlays` fixture: no bound checkouts, no render, no `remember_checkout`.
- [ ] **Step 2:** `uv run pytest tests/sync -q`: the new tests fail.
- [ ] **Step 3:** implement the deletions; `docs/cli.md` "Note sync": the pre-render step,
  `checkouts.json`, the unions and `resolved_index` go; "What moves" says a project's `MEMORY.md`
  never moves and why; "Holds" says an upstream index change is held; the `SessionStart` paragraph
  of "Hooks" drops the checkout record. README's `[sync]` row is unchanged. The fragment
  (`upgrading`): the indexes are rendered on each machine and no longer synced; an overlay that
  commits them should untrack them, and the job holds an upstream change to one until it does.
- [ ] **Step 4:** `uv run pytest tests/sync tests/memory tests/test_outbound.py tests/test_documents.py -q` passes.
- [ ] **Step 5: mutations.** Removed: "a group note does not re-render the recorded projects", "the
  union drops the local-only bullets", "a dirty index waits like a note", "the union overwrites a
  line appended while it was built", "a united index is not settled" and every other entry whose
  `file` is `src/stayfixed/sync/render.py` or whose `before` names a deleted function. Added: "an
  index is memory again" (the exclusion dropped from `MEMORY_PATHSPEC`), "an index name parses as a
  note" (the `None` for an index dropped from `memory_path`). Run the oracle with pattern `sync/`.
- [ ] **Step 6:** commit `refactor(sync): leave each machine's MEMORY.md indexes to that machine`.

Expected net: `src` −230, tests −450, entries −12.

---

## Wave B — one environment and one bounded launch for every git (Tasks 3–4)

### Task 3: the core's launch and environment

**Files:**
- Modify: `src/stayfixed/processes.py`, `src/stayfixed/gitenv.py`, `src/stayfixed/runner.py`, `tests/outbound/policy.py`, `mutations/core.toml`
- Create: `tests/test_processes.py`
- Test: `tests/test_git_run.py`, `tests/test_runner.py`

**Interfaces:**
- `processes.Ran(code: int, out: bytes, err: bytes, timed_out: bool)`;
  `processes.run_bounded(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float,
  stdin: bytes | None = None) -> Ran`: its own session, stdin closed or the bytes, the whole group
  killed on a timeout and its pipes abandoned past `KILL_WAIT_SECONDS`, a launch `OSError` as code
  127. No floor: a caller that wants one asks `gitenv`.
- `gitenv.GIT_ENV_KEEP` gains `SSH_AUTH_SOCK` and the proxy variables of D2; `scrubbed_env()`
  drops `PATH`'s relative entries and sets `GIT_TERMINAL_PROMPT=0`.
- `gitenv.Called(code: int, out: str, err: str, timed_out: bool)`; `gitenv.git_call(root: Path,
  *args: str, timeout: float, env: Mapping[str, str] | None = None, stdin: bytes | None = None) ->
  Called`: `git <args>` in `root` with `scrubbed_env() | env`, at `max(timeout, bound_floor())`,
  decoded with `pipe_encoding()` and `surrogateescape`.
- `runner._SubprocessRunner.launch`: an argv whose program is `git` runs with `scrubbed_env()`
  (`_ENV_FORCE` still laid over it); every other program keeps the inherited environment less
  `_ENV_DROP`.

- [ ] **Step 1: failing tests.**
  - `tests/test_processes.py`: `test_a_timeout_ends_the_whole_group` (a child that starts a
    sleeping grandchild holding the pipes; both gone, `timed_out`), `test_a_program_that_is_not_there_is_127`,
    `test_stdin_is_the_bytes_or_closed` (moved from `tests/sync/test_git.py`, which loses them).
  - `tests/test_git_run.py`: `test_git_call_hands_git_only_the_kept_variables` (through
    `git -c alias.e=!env e`: `GIT_CONFIG_GLOBAL`, `GIT_DIR`, `PRE_COMMIT_HOME`, `GIT_SSH_COMMAND`
    set in the process are absent; `SSH_AUTH_SOCK` and `https_proxy` present);
    `test_a_relative_path_entry_never_reaches_git`; `test_git_call_honours_the_floor` (floor set, a
    small bound, a slow shim git finishes); its bound-table row for `git_call`.
  - `tests/test_runner.py`: `test_the_runner_gives_git_the_one_environment` and
    `test_other_programs_keep_the_inherited_environment`.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement; `tests/outbound/policy.py` classifies `run_bounded` and `git_call`.
- [ ] **Step 4:** `uv run pytest tests/test_processes.py tests/test_git_run.py tests/test_runner.py tests/test_outbound.py -q`, then `uv run pytest -n auto -q` once.
- [ ] **Step 5: mutations.** Retargeted to `src/stayfixed/processes.py`: "a timeout ends the child
  and not its group", "the child shares the caller's session". Retargeted to
  `src/stayfixed/gitenv.py`: "a relative PATH entry reaches the overlay" (renamed "a relative PATH
  entry reaches git"). Added: "a session's global git configuration reaches git"
  (`"GIT_CONFIG_GLOBAL"` added to `GIT_ENV_KEEP`), "the runner hands git the session's environment"
  (the `git` branch dropped), "git_call ignores the floor" (`max(...)` dropped).
- [ ] **Step 6:** commit `refactor(gitenv): one environment for every git stayfixed starts, and a launch that ends its group`.

Expected net: `src` +70, tests +60, entries +3.

### Task 4: the sync's git onto the core, no ssh re-derivation, no hook

**Files:**
- Modify: `src/stayfixed/sync/git.py`, `src/stayfixed/sync/job.py`, `src/stayfixed/sync/scan.py`, `src/stayfixed/sync/rules.py`, `src/stayfixed/sync/trigger.py`, `src/stayfixed/sync/doctor.py`, `docs/cli.md`, `tests/outbound/policy.py`, `mutations/core.toml`
- Test: `tests/sync/conftest.py`, `tests/sync/test_git.py`, `tests/sync/test_rules.py`, `tests/sync/test_hooks.py`, `tests/sync/test_push.py`, `tests/sync/test_run.py`, every `tests/sync` module that passes `SLOW` to a git call

**Interfaces:**
- `sync.git.git(repo, *args, timeout, env=None, index_file=None, stdin=None) -> Ran` delegates to
  `gitenv.git_call` (`index_file` laid over as `GIT_INDEX_FILE`); `Ran` is `gitenv.Called`.
  Deleted: `run`, `REPOSITORY_VARIABLES`, `ASKPASS`, `SSH_OPTIONS`, `_is_ssh`, `_text`, and
  `job_env`'s git call. `JOB_SETTINGS` (a mapping, built once) replaces `job_env`: D2's sync
  settings through `with_config`. `JobContext.env` is that mapping and asks nothing.
- `scan` launches gitleaks through `processes.run_bounded` with `gitenv.scrubbed_env()`;
  `unset_prefixes` goes (no `GITLEAKS_*` is in the allowlist).
- `rules.status(repo, *, timeout, env) -> Status(paths, ahead, head)`: one `git status --porcelain=v2
  --branch -z` over the pathspec; `dirty_memory` and `trigger._tree` both read it (the v1 reader
  and `_BEFORE_PATH`'s second table go). `trigger.STATUS_TIMEOUT = 3.0`, its reason the `Stop`
  entry's ten seconds holding two calls and start-up.

- [ ] **Step 1: failing tests.**
  - `test_a_sessions_global_config_cannot_redirect_the_push` (push: `GIT_CONFIG_GLOBAL` naming a
    file with `remote.origin.pushurl` at a second bare remote, and a variant with
    `url.<other>.pushInsteadOf`; the job ends `ok`, the note is on `origin`, the second remote has
    no `main`).
  - `test_the_jobs_git_runs_no_hook` (run: `reference-transaction` and `pre-push` hooks planted in
    the overlay's `.git/hooks`, each writing a marker; the job ends `ok`; no marker).
  - `test_one_status_feeds_the_trigger_and_the_commit` (rules).
  - The `tests/sync/conftest.py` `HOME` gains a `.gitconfig` with the identity the fixture's `env`
    gave by variable, which the product's git no longer inherits; every `timeout=SLOW` on a git call
    goes (the suite's floor applies); tests about a bound running out remove
    `gitenv.FLOOR_VARIABLE` first.
  - Deleted: `test_job_env_defaults_to_ssh_and_prefers_the_environment`,
    `test_job_env_leaves_a_wrapper_as_is`, the runner tests moved in Task 3,
    `test_the_runner_hands_on_the_environment_less_what_redirects_git`; `test_no_askpass_is_ever_asked_for_a_password`
    is kept against the new environment.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement. `docs/cli.md` "What it never does": it runs no hook; what the owner's
  git configuration names still runs (credential helper, `core.sshCommand`, `gpg.program`,
  `core.fsmonitor`); its git gets the one environment (name it) plus its own settings; the
  `BatchMode` sentence goes.
- [ ] **Step 4:** `uv run pytest tests/sync tests/test_outbound.py -q`, then the full suite once.
- [ ] **Step 5: mutations.** Removed: "a wrapper around ssh is given ssh's options", "an inherited
  repository variable reaches the child", "the job keeps an inherited askpass", "a variable the
  caller asked to drop reaches the child". Respelled `before` (same names): "attributes come from
  the working tree again", "a replace ref can disguise a commit again", "the job keeps the owner's
  core.askPass". Added: "the job's git runs the overlay's hooks" (`core.hooksPath` dropped from
  `JOB_SETTINGS`). The Task 3 entry "a session's global git configuration reaches git" names
  `test_a_sessions_global_config_cannot_redirect_the_push` in its `reddens` too.
- [ ] **Step 6:** commit `refactor(sync): start every git through the core's launch, and no hook`.

Expected net: `src` −125, tests −90, entries −6.

---

## Wave C — the scanner on PATH, and scans by content (Tasks 5–6)

### Task 5: the scanner is the gitleaks on PATH

**Files:**
- Modify: `src/stayfixed/sync/scan.py`, `src/stayfixed/sync/job.py`, `src/stayfixed/sync/doctor.py`, `docs/cli.md`, `README.md`, `mutations/core.toml`
- Create: `changelog.d/+sync-scanner-on-path.upgrading.md`
- Test: `tests/sync/conftest.py`, `tests/sync/test_scan.py`, `tests/sync/test_doctor.py`, `tests/sync/test_commit.py`, `tests/sync/test_push.py`

**Interfaces:**
- `scan.gitleaks() -> Path | None`: `shutil.which("gitleaks", path=scrubbed_env()["PATH"])`.
  `NO_SCANNER`: no gitleaks on `PATH`, so nothing is committed or pushed; the remedy installs it on
  the `PATH` the sessions run with. `JobContext.scanner` is looked up once per job.
- Deleted: `gitleaks_pin`, `_scalar`, the five patterns, `gitleaks_binary`, `GITLEAKS_REPO`,
  `GITLEAKS_HOOK`, `CONFIG`, `DB_TIMEOUT`, `CONFIG_BYTES`, and the default-rules path beside a
  build. With no committed `.gitleaks.toml` the scan's `--config` names a scratch file holding
  `[extend] useDefault = true`.
- `doctor`'s scanner arm calls `scan.gitleaks()`; it no longer asks a home.

- [ ] **Step 1: failing tests.** The stand-in of `tests/sync/conftest.py` is installed as
  `gitleaks` in a `bin` directory under `tmp_path`, first on `PATH`; `build_gitleaks`'s pre-commit
  layout, `pre_commit_store` and `environment_of` go.
  - `test_the_scanner_is_the_gitleaks_on_path`; `test_no_gitleaks_on_path_is_scan_unavailable_with_the_remedy`
    (commit and push); `test_a_pre_commit_database_chooses_no_scanner` (a `PRE_COMMIT_HOME` whose
    row points at a script that exits 0: the stand-in on `PATH` scans, and the secret is found);
    `test_no_committed_rules_scan_on_gitleaks_defaults` (the `--config` file holds `useDefault`).
  - `test_doctor`: the scanner arms find the stand-in on `PATH` and warn with the new remedy.
  - Deleted: the eleven pin, database, row and build tests of `tests/sync/test_scan.py`.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement. `docs/cli.md` "The secret scan" and README's network notes: the
  scanner is the gitleaks on `PATH`; pre-commit's build is not read. The fragment (`upgrading`): a
  machine whose gitleaks is only pre-commit's build syncs nothing until gitleaks is on `PATH`.
- [ ] **Step 4:** `uv run pytest tests/sync tests/test_documents.py -q`.
- [ ] **Step 5: mutations.** Removed: "the scanner's pin is read from the working tree", "a row of
  another rev is the scanner", "an explicit version has a substitute", "system is tried before
  default", "a build linking out of its row is the scanner". Respelled: "doctor calls a missing
  scanner green", "no scanner, and the commit goes on".
- [ ] **Step 6:** commit `refactor(sync): the scanner is the gitleaks on PATH`.

Expected net: `src` −95, tests −170, entries −5.

### Task 6: scan what is committed and pushed by content alone

**Files:**
- Modify: `src/stayfixed/sync/scan.py`, `src/stayfixed/sync/job.py`, `src/stayfixed/sync/rules.py`, `docs/cli.md`, `tests/outbound/policy.py`, `mutations/core.toml`
- Test: `tests/sync/conftest.py`, `tests/sync/test_scan.py`, `tests/sync/test_commit.py`, `tests/sync/test_push.py`

**Interfaces:**
- `scan.Scanned(ok: bool, detail: str, timed_out: bool, found: tuple[str, ...])`;
  `scan.scan(items: Sequence[tuple[str, bytes]], binary: Path, rules: bytes | None, timeout: float,
  scratch: Path) -> Scanned`: D4; `found` are the labels of the files gitleaks reports, and a detail
  names rule and label, never the match. A failed scan (exit 1 with an empty report) is not a
  finding, as before.
- `rules.RawEntry` drops `old_mode` (no reader) and gains `blob: str`, the new side's sha from the
  `--raw` line.
- `job`: the commit-time scan's items are `(path, working-tree bytes)` of each staged non-deleted
  note; the push's are `(f"{sha} {path}", blob)` for each non-deleted entry of
  `commit_entries(upstream..tip)`, read by one `cat-file --batch`, and `(sha, metadata)` per commit;
  the range is listed once and its entries feed the local hold, the items and the metadata. A push
  finding is `secret_found`, its detail opening with the rewrite remedy for the oldest commit
  found, then the findings.
- Deleted: `scan_index`, `scan_range`, `scan_commits`, `_pinned`'s ignore half and the root
  `.gitleaksignore` refusal, `in_repo`, `SCAN_CONFIG`.

- [ ] **Step 1: failing tests.** The stand-in gains `dir` mode (it reads every file in its source
  directory) and, to stand for a path allowlist, skips any file whose name holds `allowlisted`.
  - `test_a_note_name_never_exempts_it_from_the_scan` (a note named `allowlisted.md` holding the
    fixture's secret: commit-time notice and push `secret_found`).
  - `test_the_real_gitleaks_finds_a_token_under_allowlisted_names` (skipped without gitleaks on
    `PATH`): the four names of the Premise, one token each, through `scan.scan`; all four labels
    found.
  - `test_a_scan_reads_no_file_at_the_overlays_root` (a working-tree `.gitleaks.toml` holding
    `allow-all` and a `.gitleaksignore` holding `ignore-all`; the secret is still found, and the
    stand-in's recorded source is the scratch directory).
  - `test_committed_rules_apply` (a committed `.gitleaks.toml` with `allow-all`: nothing found).
  - `test_a_textconv_cannot_hide_a_note` (`.git/info/attributes` gives `*.md` a `diff` driver whose
    `textconv` prints nothing; the secret is found at commit and at push).
  - `test_a_push_finding_opens_with_its_remedy` (the detail's first line is the rewrite command
    naming the commit).
  - `test_the_metadata_scan_names_the_commit` stays, against `scan.scan`.
  - Deleted: the ignore-file tests, the scan-git-configuration tests, the `--log-opts` tests.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement. `docs/cli.md` "The secret scan": what is scanned (the bytes, under
  neutral names), with which rules, what no longer applies (path allowlists, `.gitleaksignore`),
  and that a committed rule set's content allowlists still do.
- [ ] **Step 4:** `uv run pytest tests/sync -q`; the real-gitleaks test passes on a machine that
  has gitleaks (paste its line).
- [ ] **Step 5: mutations.** Removed: "gitleaks reads a log with signature lines", "the scan's git
  colours its patch", "the scan's git colours its diff", "an uncommitted ignore list at the root does
  not stop a scan", "a GITLEAKS_ variable reaches the scan". Retargeted: "a metadata scan runs at
  the overlay's root" (renamed "a scan runs at the overlay's root"), "the metadata scan names no
  commit", "the scan reads the rules from the working tree", "the push's metadata scan reads no
  commit object", "a failed push scan is taken for a finding". Added: "a scanned file is named after
  its note" (the label written as the file name), expected to redden
  `test_a_note_name_never_exempts_it_from_the_scan`.
- [ ] **Step 6:** commit `fix(sync): scan what is committed and pushed by content, so no note name exempts a secret`.

Expected net: `src` −105, tests −130, entries −4.

---

## Wave D — git commits the notes and moves main (Tasks 7–8)

### Task 7: commit with `git commit --only`

**Files:**
- Modify: `src/stayfixed/sync/job.py`, `src/stayfixed/sync/rules.py`, `src/stayfixed/sync/state.py`, `docs/cli.md`, `tests/outbound/policy.py`, `mutations/core.toml`
- Test: `tests/sync/test_commit.py`, `tests/sync/test_state.py`, `tests/sync/test_run.py`

**Interfaces:**
- `commit_memory(ctx) -> Outcome | None`, in order: the status's dirty paths; those that are not
  notes by name, or have a link or a file above them (`unsafe_parent`), refused and named; `git add
  -N` of the untracked rest (`GIT_LITERAL_PATHSPECS=1`, paths on stdin, NUL-separated);
  `offending_paths(repo, "HEAD", paths=...)` (a new `paths` argument) judges what git would record
  from the working tree, and the offenders are refused, an intent-to-add entry of one dropped again
  by `git reset -q`; the content scan (Task 6) of the rest, each note with a finding left out the
  same way and named in a `secret_found` notice whose detail opens with "remove the secret from
  <path>; the next job commits it"; `_unmerged_now`; `git commit --only -F <scratch message>
  --pathspec-from-file=- --pathspec-file-nul` with `GIT_LITERAL_PATHSPECS=1`. A failed commit is
  `signing_failed` when `commit.gpgsign` asks for a signature, `raced` when git names
  `index.lock`, else `hook_failed` with git's words.
- Deleted: the temporary index of the commit, `_staged`, `_reset_paths`, `_before_swap`,
  `_record_pending`, `_move_main`, `align`, `align_first`, `_index_needs_align`, `_settle`,
  `ALIGN_RETRIES`, `ALIGN_PAUSE_SECONDS`, `ALIGN_COMMAND`, `PendingAlign`,
  `SyncState.pending_align` and its JSON key (an old file's key is ignored), the `index_stale`
  outcome. `_commit_tree` and `_signing` stay for the replay.

- [ ] **Step 1: failing tests.**
  - `test_the_owners_staged_work_stays_staged` (a staged non-memory file and a staged hunk outside
    memory survive the commit, `git diff --cached` unchanged outside memory).
  - `test_a_stash_pop_conflicting_while_the_job_runs_is_never_committed` is retargeted: the
    conflicted `stash pop` of the Premise is made between the guard and the commit, at the new seam
    (its old one, `prerender`, is gone with Task 2); outcome `skipped`, no commit, the markers
    still only in the working tree.
  - `test_one_secret_note_waits_and_the_others_commit` (two notes, one holding the secret).
  - `test_a_link_an_executable_or_a_binary_note_is_refused_and_leaves_no_index_entry` (the real
    index has no intent-to-add entry for any of them afterwards).
  - `test_a_kill_after_git_add_n_is_committed_by_the_next_job`.
  - `test_a_locked_index_is_raced_and_the_lock_is_left` (git's index lock file present: outcome
    `raced`, the lock file untouched).
  - `test_signing_asked_for_is_honoured` and `test_signing_that_needs_a_prompt_is_signing_failed`
    stay, now through `git commit`.
  - Deleted: every test of the alignment, the pending record and `index_stale` (in
    `tests/sync/test_commit.py`, from `test_the_real_indexs_memory_entries_are_aligned` to
    `test_the_owners_removal_after_a_stale_commit_is_not_undone`), and their `tests/sync/test_state.py`
    and `tests/sync/test_run.py` counterparts.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement. `docs/cli.md` "The job, in order": the align step goes; the commit
  step says what git does; the Writes paragraph loses the real index's reset, the temporary index
  and the pending record; `index_stale` leaves the outcomes.
- [ ] **Step 4:** `uv run pytest tests/sync -q`, then the full suite on 3.14 and 3.13.
- [ ] **Step 5: mutations.** Removed: "the sync commit is built in the real index", "the pending
  alignment is not recorded before the swap", "the real index is not aligned after a move", "a
  record whose move never happened is aligned", "the swap compares against a HEAD read later".
  Retargeted: "the sync commit stages the whole tree" (to `--only`), "the temporary index keeps
  what is not a note" (renamed "an offending note is committed"), "the unmerged entries are not
  asked again before main moves" (renamed "the unmerged entries are not asked again before the
  commit"), "a link at a pathspec's root fails the whole commit". Added: "a secret in one note keeps
  every note out" (the leave-out dropped, the whole commit stopped instead).
- [ ] **Step 6:** commit `refactor(sync): let git commit the notes, and leave the owner's index to git`.

Expected net: `src` −150, tests −230, entries −4.

### Task 8: integrate by `read-tree -m -u`, then the compare-and-swap

**Files:**
- Modify: `src/stayfixed/sync/job.py`, `docs/cli.md`, `tests/outbound/policy.py`, `mutations/core.toml`
- Test: `tests/sync/test_integrate.py`, `tests/sync/test_push.py`

**Interfaces:**
- `integrate`: after the replay and the scratch readability check, `_unmerged_now`, then `git
  read-tree -m -u <head> <tip>` on the real index; a refusal is `waiting_clean_tree` with git's first
  line (`raced` when it names `index.lock`), nothing written; then `_swap(ctx, tip, head)`; a failed
  swap is `raced` and the next job converges ("Crash ordering").
- Deleted: `_blocked`, `_finish_worktree`, `_worktree_has`, `_blobs`, `_prune_empty`, and the
  integration's use of `PendingAlign`.

- [ ] **Step 1: failing tests.**
  - `test_incoming_notes_are_written_and_the_owners_staging_kept`.
  - `test_a_dirty_incoming_note_waits_and_nothing_is_written`;
    `test_an_untracked_file_where_a_note_lands_waits`;
    `test_a_link_above_an_incoming_note_waits_and_the_link_stays` (replaces
    `test_a_link_above_an_incoming_path_blocks_and_nothing_escapes`).
  - `test_a_kill_between_the_write_and_the_move_converges` (`_swap` patched to raise once; the next
    job ends `ok`, `main` equals upstream, `git status` clean for memory).
  - `test_a_moved_main_after_the_write_is_raced_and_converges`.
  - Deleted: `test_a_kill_after_the_swap_is_finished_by_the_next_job`, the pending-write tests.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement. `docs/cli.md` "Integrate" and "Writes": git writes the incoming notes
  and the index, then `main` moves; a dirty or untracked clash waits.
- [ ] **Step 4:** `uv run pytest tests/sync -q`.
- [ ] **Step 5: mutations.** Removed: "a pending write goes over the owner's edit". Retargeted:
  "main moves without a compare-and-swap", "an incoming note dirty here does not wait" (renamed "a
  refused read-tree is ignored"), "a tip git cannot read is integrated". Added: "main moves before the
  working tree is written" (the swap moved before `read-tree`), expected to redden
  `test_a_kill_between_the_write_and_the_move_converges`.
- [ ] **Step 6:** commit `refactor(sync): let git write the incoming notes before main moves`.

Expected net: `src` −40, tests −70, entries −3.

---

## Wave E — the rewrite hold, Codex, the switch, doctor (Tasks 9–11)

### Task 9: hold a local rewrite instead of undoing it

**Files:**
- Modify: `src/stayfixed/sync/state.py`, `src/stayfixed/sync/job.py`, `src/stayfixed/sync/doctor.py`, `docs/cli.md`, `mutations/core.toml`
- Test: `tests/sync/test_state.py`, `tests/sync/test_integrate.py`, `tests/sync/test_doctor.py`

**Interfaces:**
- `state.LOCAL_REWRITE = "rewritten here"`, accepted by `_parse` as a hold reason;
  `JobContext.last_head` from the previous state's `head`.
- `_dropped` becomes `_lost(ctx, recorded, upstream, local) -> tuple[list[str], list[str]]`: what
  upstream lost that `HEAD` has (as now), and the commits of `HEAD..upstream` that `ctx.last_head`
  had and `HEAD` no longer has, plus those a standing `LOCAL_REWRITE` hold names. A non-empty second
  list is an upstream hold, why `LOCAL_REWRITE`, naming the commits; nothing is integrated or
  pushed. A first job, or a `last_head` git cannot find, judges nothing.
- `LOCAL_REVIEW`: to keep the rewrite, `git push --force-with-lease=refs/heads/main:{sha} origin
  main` by hand; to undo it, `git rebase {sha}`. `doctor`'s `_held` names it.
- **What the owner sees:** the job ends `ok` with a remark naming the commits and both commands;
  `doctor`'s `sync` row warns that main no longer has those commits, which `origin/main` still has,
  with the two commands; `Stop` backs off on the unchanged hold. The hold clears on the first job
  after either command.

- [ ] **Step 1: failing tests.**
  - `test_a_local_rewrite_hold_round_trips` (state).
  - `test_a_local_purge_is_held_not_undone` (the review's repro: a pushed note, `git reset --hard
    <sha>~1`, another note committed; the job leaves `HEAD` as the owner made it, the purged note
    absent, the hold naming the commit).
  - `test_a_bare_reset_is_held_not_fast_forwarded`.
  - `test_the_local_rewrite_hold_stands_until_pushed_or_rebased` (two jobs held; after the
    force-push by hand, cleared; and after `git rebase <sha>`, cleared).
  - `test_a_local_memory_commit_is_replayed_onto_the_checked_sha` stays green.
  - `test_doctor`: the hold's row and its two commands.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement; `docs/cli.md` "Holds" gains the local rewrite.
- [ ] **Step 4:** `uv run pytest tests/sync -q`.
- [ ] **Step 5: mutations** (added): "a local purge is replayed" (the second list ignored); "a
  local-rewrite hold lasts one job" (the standing hold's commits not carried).
- [ ] **Step 6:** commit `fix(sync): hold a rewrite of pushed notes instead of replaying what it removed`.

Expected net: `src` +25, tests +45, entries +2.

### Task 10: the switch through the session, and no trigger under Codex

**Files:**
- Modify: `src/stayfixed/config/owner.py`, `src/stayfixed/sync/hooks.py`, `src/stayfixed/sync/job.py`, `src/stayfixed/sync/doctor.py`, `src/stayfixed/setup/run.py`, `src/stayfixed/setup/machine.py`, `docs/cli.md`, `mutations/core.toml`
- Delete: `src/stayfixed/sync/switch.py`, `tests/sync/test_switch.py`
- Test: `tests/config/test_owner.py`, `tests/sync/test_hooks.py`, `tests/sync/test_run.py`, `tests/sync/test_doctor.py`

**Interfaces:**
- `config.owner.Sync(enabled: bool = False)`; `Owner.sync: Sync`, read from the machine file's
  `[sync]` as `[guards]` is (an unusable value costs that key, with a note, and reads off).
- `sync.hooks._sync` returns at once when `CODEX.detects(os.environ, None)`, then reads
  `session.owner.sync.enabled`; the job's `main` reads `resolve_owner(machine_config_path()).sync`
  once per wake; `doctor` reads it from its context's machine file.

- [ ] **Step 1: failing tests.**
  - `tests/config/test_owner.py`: `test_sync_is_on_only_for_the_bool_true` (absent, `"yes"`, `1`,
    `false` off; `true` on) and `test_a_machine_file_that_does_not_load_leaves_sync_off`.
  - `test_a_codex_hook_process_starts_nothing` (`PLUGIN_ROOT` set: no git, no spawn);
    `test_a_claude_code_hook_process_still_starts_the_job`.
  - `test_the_handler_reads_the_switch_from_the_session` (`read_machine_toml` patched to raise in
    the handler's process: the decision is the session's).
  - `test_with_sync_off_stop_runs_no_git_and_spawns_nothing` stays.
  - Deleted with the module: `tests/sync/test_switch.py` (its repository-refusal case is
    `tests/config/test_classes.py`'s).
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement; `docs/cli.md` "Claude Code and Codex": a hook process whose
  environment carries Codex's `PLUGIN_ROOT` starts nothing (Codex sets it, measured as cited in
  `src/stayfixed/harnesses.py`); a repository that sets it in a Claude Code session turns that
  session's triggers off, never on.
- [ ] **Step 4:** `uv run pytest tests/config tests/sync tests/setup -q`.
- [ ] **Step 5: mutations.** Retargeted to `src/stayfixed/config/owner.py`: "a string 'true'
  switches sync on". Added: "a Codex session starts the job" (the `detects` line dropped). The
  hooks entry "sync off still decides" respelled.
- [ ] **Step 6:** commit `fix(sync): read the switch from the session, and start nothing under Codex`.

Expected net: `src` −20, tests −10, entries +1.

### Task 11: `doctor` says when the sync is not running and what a standing failure needs

**Files:**
- Modify: `src/stayfixed/sync/doctor.py`, `src/stayfixed/sync/git.py`, `src/stayfixed/sync/job.py`, `docs/cli.md`, `mutations/core.toml`
- Test: `tests/sync/test_doctor.py`, `tests/sync/test_git.py`

**Interfaces:**
- `doctor`: OK only for `ok`; `skipped` warns with the reason, its fix "the job acts once this is
  resolved; the next session event runs it"; a `STANDING` outcome's fix "a rerun meets this again
  until you act on what it says"; any other "a later session event retries".
- `git.guard`'s reasons end with their remedy: tracking nothing ("give the overlay a remote: `git
  remote add origin <url>`, then `git push -u origin main`"), another branch or detached ("`git
  switch main`"), an operation in progress ("finish or abort it").
- The upstream hold's words say "changes outside memory, or a commit that lists no path (a merge)"
  where its names include a sha.

- [ ] **Step 1: failing tests.** `test_a_feature_branch_is_a_warning_with_its_remedy`;
  `test_a_rendered_overlay_with_no_remote_warns_until_it_has_one` (`setup --overlay` render in a
  scratch `HOME`, then `doctor`: warn, the remote commands named);
  `test_a_standing_failure_says_a_rerun_meets_it` (secret, conflict, signing);
  `test_a_retried_failure_says_a_later_event_retries` (offline);
  `test_an_upstream_merge_is_named_as_one`.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement; `docs/cli.md`'s doctor table row and "Outcomes" say it.
- [ ] **Step 4:** `uv run pytest tests/sync tests/doctor -q`.
- [ ] **Step 5: mutations** (added): "doctor calls a guard refusal green" (`skipped` back in the OK
  set); "doctor promises a retry for a standing failure" (the class test dropped).
- [ ] **Step 6:** commit `fix(sync): doctor says when the sync is not running, and what a standing failure needs`.

Expected net: `src` −15 (the settled-set and wording), tests +15, entries +2 (the `src` figure
assumes Task 2 left `SETTLED` used only by the trigger).

---

## Wave F — what is left (Tasks 12–14)

### Task 12: the leftovers in the sync's code

**Files:**
- Modify: `src/stayfixed/sync/job.py`, `src/stayfixed/sync/git.py`, `src/stayfixed/sync/rules.py`, `src/stayfixed/sync/scan.py`, `src/stayfixed/sync/trigger.py`, `src/stayfixed/sync/doctor.py`, `mutations/core.toml`
- Test: `tests/sync/test_integrate.py`, `tests/sync/test_push.py`, `tests/sync/test_hooks.py`

**Interfaces and changes:**
- The replay reads a commit's author through `git log -1 --no-show-signature
  --format=%an%x00%ae%x00%ad --date=raw`; its message and `encoding` header still come raw from
  `cat-file commit`; the `_AUTHOR` pattern goes.
- A rejected push is read from `--porcelain`'s ref line (its `!` flag and `[rejected]`), not from
  English words.
- One deadline helper for `ctx.limit`, `git.left` and the guard's budget; `_rev` and `_tree_of` one
  function; `_range`, `_blob`, `ask`, `is_memory_path` folded into their callers where one remains;
  `Guard` keeps `reason` alone (`ok` a property).
- Constants named once: `INDEX_NAME` from `memory.index`, `CONTROL_DIRECTORY` from `fsops`, the
  `utf-8`/`surrogateescape` pairs by `gitenv.pipe_encoding` and `answer_bytes` where they meet
  git's output.
- `trigger.decide` reads `state.json` once per event.

- [ ] **Step 1:** `test_a_rejected_push_is_read_from_the_porcelain_flag` (a pre-receive-free race:
  another clone pushes first; outcome `rejected` with `LC_ALL` set to a locale other than C in the
  test's process). The rest is held by the existing tests, green before and after; each refactor
  lands only with the suite green.
- [ ] **Step 2:** implement, one commit per fold if a fold fails a test.
- [ ] **Step 3:** `uv run pytest tests/sync -q`; the oracle on `sync/`, every entry caught; respell
  each `before` the folds moved.
- [ ] **Step 4:** commit `refactor(sync): name each constant, deadline and git question once`.

Expected net: `src` −40, tests +10.

### Task 13: the duplicate and change-detector tests

**Files:**
- Modify: `mutations/core.toml`
- Test: `tests/sync/test_rules.py`, `tests/sync/test_state.py`, `tests/sync/test_commit.py`, `tests/sync/test_integrate.py`, `tests/sync/test_push.py`, `tests/sync/test_git.py`, `tests/sync/test_hooks.py`, `tests/sync/test_scan.py`, `tests/sync/test_run.py`, `tests/sync/conftest.py`

- [ ] **Step 1:** for each pair the review named and still present after Waves A–D (a test whose
  every assertion a sibling asserts; the three `entry_offends` tables; the round-trip repeats; the
  change-detector pins of constants; `PATHSPEC` and `GITLEAKS_REPO` copies in the fixture), delete
  the weaker one or fold it into a parametrised sibling, and keep the one a mutation entry names.
- [ ] **Step 2:** retarget each `reddens` that named a deleted test (three expected); the oracle on
  `sync/`, every entry still caught.
- [ ] **Step 3:** `uv run pytest tests/sync -q`; coverage at the floor on the full suite.
- [ ] **Step 4:** commit `test(sync): drop the tests a sibling already holds`.

Expected net: tests −225.

### Task 14: the docs' last pass and the changelog

**Files:**
- Modify: `docs/cli.md`, `README.md`, `changelog.d/+note-sync.feature.md`
- Create: `changelog.d/+sync-review-fixes.fix.md`
- Test: `tests/test_documents.py`

- [ ] **Step 1:** re-read `docs/cli.md`'s "Note sync" against the tree, sentence by sentence; the
  floor paragraph says what an old git costs (each trigger's job records `skipped`); every count and
  outcome list matches `state.OUTCOMES`.
- [ ] **Step 2:** the fragment (`fix`): a note name no longer exempts a secret from the scan; the
  session's environment no longer chooses where notes go or which scanner runs; a rewrite of pushed
  notes is held; `doctor` says when the sync is not running; Codex sessions start nothing.
- [ ] **Step 3:** `uv run pytest tests/test_documents.py tests/test_neutral.py tests/test_public_anchors.py -q`;
  then the full gates once: `uv run pytest -n auto --cov --cov-fail-under=92`,
  `uv run ruff check . && uv run ruff format --check .`, `uv run mypy`,
  `uv run python scripts/release.py check`, the oracle on `sync/`, `gitenv`, `processes`, `runner`,
  `memory/hooks`, `config/owner`.
- [ ] **Step 4:** commit `docs(sync): say what the sync does now`.

Expected net: docs +5.

### After Wave F (controller)

Merge `origin/next`, re-run the gates, open the pull request into `next` with the net size and the
"Crash ordering" section in its body, wait for CI, then the final review and one re-review.

## Findings

Filled during execution: each wave's head, its net size against the estimate, what the review
changed.
