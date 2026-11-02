# Restructure, lane 5 — note sync in the product (`sync`): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking. **The wave is the dispatch
> unit, not the task:** one implementer per lettered wave (A–E), each task inside it keeping its own
> failing test, verification and commit. One pull request into `next` for the whole lane, one final
> review, one scoped re-review (see "Execution contract"). No per-wave review.

**Goal:** a machine whose machine file says `[sync] enabled = true` commits the overlay's notes,
takes in the other machines' notes and pushes its own, unattended, from Claude Code's
`SessionStart`, `Stop` and `SessionEnd` hooks; a machine that does not say so runs nothing new.

**Architecture:** a new delivery-side area `src/stayfixed/sync/`. Its `hooks.py` decides on each of
the three events whether a job is due and spawns it detached; the job (`job.py`) takes a per-machine
lock and runs seven bounded steps against the overlay recorded in the machine file: guard, pre-render
the indexes, commit memory through a temporary index, fetch, integrate a memory-only upstream by
replay, resolve index-only conflicts by union, push the checked range after a secret scan. Its state
lives in the data directory (`~/.local/share/stayfixed/sync/`) and `doctor` reports it. The git rules
that decide what may move are `rules.py`; the bounded process runner is `git.py`; the scanner lookup
and scans are `scan.py`. The area has no `api.py` and no command: nothing outside it imports it, and
the switch is a key of the machine file.

**Tech Stack:** Python ≥ 3.11 standard library; git ≥ 2.43 at run time (the job's own floor);
gitleaks as the build `pre-commit install-hooks` makes for the overlay's pinned hook; pytest with
real git repositories under `tmp_path`; the mutation oracle (`sync/` routes to `mutations/core.toml`).

**Spec:** the restructure's umbrella plan, lane 5, restated here because it is not public:

> The overlay's note sync moves into a platform area `sync`: `SessionStart`, `Stop` and `SessionEnd`
> triggers, a detached job, the 120 s throttle and back-off, commit and push of memory paths only
> (`common/memory`, `groups/*/memory`, `projects/*/memory`; regular files only), the secret scan
> before a push, which fails closed with a remedy when the scan is unavailable. It reuses the
> product's process, write and memory-layout code. Its git floor (2.43) is its own: on an older git
> it does nothing and `doctor` says why. The switch is per machine: `[sync] enabled = true` in the
> machine file (machine-only class). `setup --overlay` sets it when it creates or renders a new
> overlay; recording an existing one leaves it alone. Claude Code sessions only; Codex sessions do
> not trigger it. The SessionStart push notice stays as it is. README rows for the job's `git fetch`
> and `git push`. No cloud mode. Budget `src` ≤ 2.5k lines.

The behaviour ported is an existing, field-tested job that ran outside this repository; the
implementer's brief carries where its source and its tests are. This plan names what changes against
it (see "Decisions"); everything else is ported as it behaves, with its tests.

**Scope:** restructure lane 5; one pull request into `next`. Consumes lane 0 (#158, merged into `next`:
the `hints` area, `roots` in the core, three sides in `src/stayfixed/areas.py`, one name per line). Out of scope: the overlay's own hook
yielding to the switch (another lane, in the overlay), `setup --restore --sync` (lane 6, which calls
the writer Task 1 extends), a cloud mode, `[sync] paths`, Codex triggers.

## Premise

Measured on `dev` at `d00b726` and on #158's diff, by reading the tree; re-read after merging `next`
at `ae716db`. Each wave re-measures its part and stops on a mismatch.

- `src/stayfixed/areas.py` lists `DELIVERY_AREAS`, `PACK_PACKAGES` and `CORE_AREAS` one name per
  line, and `sync` is on no side: Task 1 adds the line `"sync",` to `DELIVERY_AREAS`.
  `tests/boundaries/test_delivery.py` refuses any unpinned import between delivery and the pack, or
  from the core into either, so `sync` imports only the core and delivery areas (`memory`).

- `src/stayfixed/processes.py` has no `run`: it ends process groups (`kill_group`, `exited`, `end`);
  the two callers `Popen(..., start_new_session=True)` themselves. `runner.Runner.launch` and
  `gitenv.git_run` cannot carry an index file, stdin bytes, an ssh agent or a kill of the group, so
  the job keeps a runner of its own built on `Popen` and `processes.kill_group`.
- `gitenv.scrubbed_env()` keeps only `PATH`, `HOME`, `LANG`, `LC_ALL`, `SYSTEMROOT`: a push over ssh
  would lose `SSH_AUTH_SOCK`. The job's runner inherits the environment minus git's repository
  variables, as the ported job does.
- `src/stayfixed/config/paths.py`: `data_directory()` is `$HOME/.local/share/stayfixed`; `src/stayfixed/config/machine.py`:
  `machine_config_path()`; `src/stayfixed/config/overlay.py`: `overlay_root(machine) -> Path | None` reads
  `[overlay] root`; `src/stayfixed/config/reading.py`: `read_machine_toml(path)`.
- `src/stayfixed/config/classes.py` `CLASSES` has one machine-only row (`"personal.*"`); `src/stayfixed/config/loader.py` derives
  `MACHINE_ONLY_SECTIONS` from it and refuses such a section in a repository's `stayfixed.toml`.
  `tests/config/test_classes.py` pins `TABLE_ROWS` and `MACHINE_FILE_KEYS`.
- `src/stayfixed/setup/machine.py` `write_machine(path, *, personal, overlay_root, machine)` merges owned tables
  key by key and carries foreign ones through; `src/stayfixed/setup/run.py` `_apply_overlay` knows `record`,
  `render` and `create`, then writes `[overlay] root` in a second `write_machine` call.
- `src/stayfixed/memory/store.py`: `COMMON`, `PROJECTS`, `STORE_DIR`, `composed_directory`, `resolved`;
  `src/stayfixed/memory/index.py`: `reconcile`, `render_index`, `write_index`, `check_index`, all needing a `Store`
  and a `Config`. In overlay mode the store resolves through a bound checkout's composed store and
  `--store` is ignored, so an index can only be rendered from a checkout bound to the project.
- `src/stayfixed/hooks/api.py` `EVENTS` lacks `Stop` and `SessionEnd`; `hooks/hooks.json` has 10 entries over four
  events; `scripts/smoke_hooks.py` pins `EXPECTED_ENTRIES = 10`, `EXPECTED_ROWS = 11`, and
  `smoke.yml` greps `10 entries, 11 row(s), 0 failure(s)`.
- `doctor`'s row count 14 is spelled in `README.md` (twice), `docs/cli.md`, `skills/doctor/SKILL.md`,
  `smoke.yml`, `tests/test_documents.py`, `tests/test_install_path.py`, `tests/doctor/test_command.py`
  and `tests/doctor/test_checks.py` (`REPORT`); `tests/boundaries/test_discovery.py` lists every
  area `doctor.py`.
- `tests/test_outbound.py` holds README's "What stayfixed sends where" to every launch the walk
  finds from `tests/outbound/policy.py`'s `ROOT_LAUNCHERS`; `("git", "push")` is in no table, and a
  `Popen` outside `gitenv._ask` and the runner is unclassified until declared.
- The overlay template ships `.pre-commit-config.yaml` pinning gitleaks by commit sha;
  `src/stayfixed/overlay/create.py` `finish` runs `pre-commit install`, which builds nothing.
- `src/stayfixed/memory/reviewed.py`: a note ranked `startup` that this machine has not reviewed is data, not a
  rule. That is why the ported job's `integrated` record is not ported (D6).
- `ci.yml` renders an overlay with `setup --overlay` in a scratch `HOME` and runs no hook there;
  `smoke_hooks.py` uses a scratch `HOME` with no machine file.

## Decisions

- **D1 — memory only, as a code constant.** The pathspec is three `glob` pathspecs,
  `common/memory/**`, `groups/*/memory/**`, `projects/*/memory/**`, derived from `src/stayfixed/memory/store.py`'s
  constants (a `GROUPS = "groups"` constant goes there beside `PROJECTS` unless `next` already has
  one). A path moves only as a regular, non-executable `.md` file with no dot component from the
  scope's name down, and only as text. Nothing configures it.
- **D2 — the scanner is the overlay's pinned pre-commit build.** The lookup reads the pin from
  `.pre-commit-config.yaml` and pre-commit's database row for that repository and revision, and takes
  `golangenv-<language_version>`, else `golangenv-default`, else `golangenv-system` (the same source
  at the same revision either way). It does not model pre-commit's choice between the last two, and
  never downloads or builds. No build: `scan_unavailable`, nothing committed or pushed, the remedy
  `run \`pre-commit install-hooks\` in <overlay>`. Rules and ignores come from `HEAD`; a
  `.gitleaksignore` or `.gitleaks.toml` at the overlay's root that differs from the committed one
  stops the scan with a remedy.
- **D3 — state in the data directory.** `~/.local/share/stayfixed/sync/`: `state.json` (the ported
  JSON shape, plus `overlay`, minus `integrated`), `job.lock`, `sleeper.lock`, `pending`,
  `checkouts.json` and one `scratch/` directory the job removes whole at its start and end (a fixed
  name: CONTRIBUTING's removal rule). A state recorded for another overlay path is not used: the job
  starts afresh and its detail says so.
- **D4 — the pre-render runs in process, from checkouts this machine's sessions opened.** The index
  can only be rendered from a bound checkout. The `SessionStart` handler records the session's
  project root in `checkouts.json` (at most `CHECKOUTS_KEPT = 64`, newest first); the job pre-renders
  through `memory.api.rerender_overlay_index` for each recorded checkout, still bound into this
  overlay, whose project's memory is dirty, and for every one when a common or group note is dirty.
  A project with no recorded checkout keeps its `MEMORY.md` out of the commit, named in the detail,
  as the ported job does for a project it cannot render. (Priced alternatives: reading the
  `dir` of a machine-layer project table, a file only some overlays have, about the same size; or no
  pre-render, about −80 `src`, at the cost of committed indexes nobody renders and harvests made on
  every machine.)
- **D5 — a group note re-renders every recorded project**, like a common one: which projects carry
  a tag is another lane's reader, and rendering too many indexes costs time, not correctness.
- **D6 — not ported:** the cloud mode and its take of non-memory upstream ranges; the delivery check
  that ran a script from the overlay's working tree (the job runs no overlay file); the subprocess
  pre-render and its program lookup; the `integrated` arrivals list and its `startup` flag, which no
  product code reads (`src/stayfixed/memory/reviewed.py` already keeps an unreviewed startup note out of the rules);
  the ported job's own state directory and atomic writer.
- **D7 — the job starts isolated.** `job_argv` is
  `[sys.executable, "-I", "-c", BOOT, <directory holding the imported stayfixed package>, ...]`:
  `-I` drops the working directory (the overlay), `PYTHONPATH` and the user site from `sys.path`, and
  `BOOT` puts back only the package's own parent. The job reads the switch and the overlay root from
  the machine file itself; its argv carries only `--sleep-until`.
- **D8 — no command and no `api.py`.** On is `setup --overlay` (new overlay) or a hand edit; off is a
  hand edit; `doctor` reports. Lane 6 switches it on through `write_machine(..., sync=...)`.

Every control here, with its adversary and anchor:

| Control | Stops | Anchor, and why the adversary cannot move it |
|---|---|---|
| memory-only pathspec, modes, `.md`, no dot components; the range rule (each commit and the merge-base bound) | executable or hidden content arriving from the remote (another machine, a session elsewhere) or written by a memory writer here | git's own recorded paths and modes of the checked sha (`fetch.fsckObjects`), and the constants in this package, which no repository byte reaches |
| `GIT_ATTR_SOURCE=HEAD`, `GIT_NO_REPLACE_OBJECTS=1`, git's repository variables dropped | a `.gitattributes` filter or a replace ref left in the working tree; a job spawned from inside a git hook | the committed tree and the job's own environment |
| the secret scan before commit and before push | an honest mistake: a token pasted into a note or a commit message | the pinned build and `HEAD`'s rules; an agent with a shell can push by hand anyway, so this is a check against mistakes, fail-closed by the umbrella's decision |
| the repository refused a `[sync]` section (machine-only class) | a hostile clone switching a machine's sync | the machine file in the owner's home, which the job alone reads |
| `-I` spawn (D7) | a `json.py` or `stayfixed/` at the overlay's root | the interpreter's isolated mode |

## Execution contract

The umbrella's contract binds this lane; the controller copies the relevant part into each brief.

1. **Final review:** one, on the pull request. Seats: correctness; "what can be deleted / who does
   this refuse"; security (the job commits and pushes: what reaches the remote, what runs, what
   the working tree and real index see). One scoped re-review, then stop. Reviewers report findings
   with no replacement text; only correctness and requirement gaps go back; Minors become follow-ups.
2. **Lifecycle matrix:** the table below, checked at pre-flight like a task.
3. **Parallelism:** waves run in order in one worktree; read-only seats may run beside an
   implementer; one oracle at a time (its lock is per machine).
4. **Templates:** a fix brief folds sibling instances into one rule or deletes them, and carries a
   net `src` budget.
5. **Verification:** focused runs while iterating, one full suite before each push; paste what a
   command printed; a plan's predicted mutation outcome is a hypothesis. The oracle locally only with
   a pattern: `uv run python scripts/mutation_oracle.py sync/`.

Implementer briefs also carry: the reference job's source and tests (private paths, in the brief);
report a mismatch between plan and tree instead of guessing; no line numbers from this plan; write
nothing under the repository but this lane's change; a private scratch subdirectory per agent; never
kill by a name pattern; never run the job, a hook or `setup` against the real `HOME` or overlay.

**Size and budget.** Five dispatches. `src` ≤ 2,500 lines net, budgeted per wave: A 380, B 650,
C 850, D 470, E 150. A wave that passes its budget stops and reports before it commits; the budget is
never met by deleting a test that holds behaviour or by packing code denser. Docstrings at the
surrounding code's density: the design's reasons live once, in `docs/cli.md`'s section and in this
plan, not in every function. Tests about +5–7k. Each report prints
`git diff --shortstat <base> HEAD -- src tests mutations docs`.

## Global constraints

- Standard library only. Writes into the overlay's working tree go through git (`checkout-index`
  from a temporary index) or `fsops`; state writes through `fsops.write_atomically`.
- No commit, test, comment or plan text names the reference job's repository, its paths, the owner's
  repositories or the private design. `tests/test_neutral.py`: no bare 8–10-hex commit id, and a
  pull request is cited as `#158`, with no word before the hash.
- Commits `feat(sync): …`, `feat(setup): …`, `test(sync): …`; one towncrier fragment
  `changelog.d/+note-sync.feature.md`.
- Every subprocess is a classified launch in `tests/outbound/policy.py`; every timeout a named cap
  with its reason (`CONTRIBUTING.md`, "Named caps").
- The job never: force-pushes; stashes; rebases; pulls; writes a non-memory path of the working tree
  or the real index; commits, integrates or pushes a path outside D1.

## Lifecycle matrix

| Change | What happens | Held by |
|---|---|---|
| `setup --overlay` renders or creates an overlay | the machine file gains `[sync] enabled = true`; every other key and table kept | Task 1 |
| `setup --overlay` records an existing overlay | `[sync]` untouched: absent stays absent, `false` stays `false` | Task 1 |
| on by hand (`enabled = true`) | the next `SessionStart` spawns a job | Task 8 |
| `[sync]` in a repository's `stayfixed.toml` | refused by the loader (machine-only); never switches anything | Task 1 |
| a machine file that does not parse, or a non-bool value | off; no raise reaches the session | Tasks 1, 8 |
| off by hand (`false` or removed) | the hooks spawn nothing; a sleeper already waiting wakes, reads the switch, exits with no job; the state file stays; `doctor` says off | Tasks 7, 8, 9 |
| the overlay moves (`[overlay] root` names another checkout) | the next job ignores the state recorded for the old path and says so; holds and pending alignment start empty | Tasks 2, 7 |
| no overlay recorded, or not a git repository | the hooks spawn nothing | Task 8 |
| a job killed between moving `main` and aligning the index | the next job aligns first (`pending_align`) | Task 5 |
| a job killed while writing the state | the old state or the new one, never half | Task 2 |
| a failed push: offline, refused credentials, rejected, timed out | the outcome is recorded; a later trigger retries (throttled, never forced) | Task 7 |
| a secret in the outgoing range | nothing pushed; the outcome names the commit and the remedy | Task 7 |
| no scanner build | nothing committed or pushed; `scan_unavailable` with the remedy; already-committed upstream still integrates | Tasks 4, 5, 7, 9 |
| a held integration (upstream changes outside memory) | upstream hold with the review command; no push; `doctor` names it; taken by hand, the next job clears it | Tasks 6, 9 |
| a held local range (local commits outside memory) | local hold naming the commits; not pushed; `doctor` names it | Tasks 7, 9 |
| git older than 2.43 | the job records `skipped` with the reason and changes nothing; `doctor` says why | Tasks 3, 9 |
| CI | no machine file sets the key; the smoke feeds `Stop` and `SessionEnd` and nothing spawns | Task 8 |
| a Codex session | no trigger: its manifest has no hooks; `docs/cli.md` says so | Task 9 |
| the plugin removed | no trigger; `~/.local/share/stayfixed/sync/` stays, named in `docs/cli.md` | Task 9 |

## Review focus

1. **`Stop` fires on every turn of every session.** With sync off, the `Stop` and `SessionEnd`
   handlers read the machine file and return: no git call, no spawn. Task 8's
   `test_with_sync_off_stop_runs_no_git_and_spawns_nothing`.
2. **A `Stop` result that blocks the turn.** The handler returns an empty `HookResult` on every
   path, and what `stayfixed hook Stop` prints carries no `decision`. Task 8's
   `test_stop_and_session_end_print_nothing_that_blocks`.
3. **A planted module at the overlay's root.** The spawned job runs from the overlay; a `json.py` or
   a `stayfixed/` there is never imported. Task 7's `test_the_job_imports_nothing_from_the_overlay`.
4. **Two sessions ending at once.** Two `SessionEnd` triggers: one job, the other marks pending and
   the job runs a second round. Task 7's `test_busy_lock_marks_pending_and_the_job_loops`.
5. **A tag's note with no recorded checkout.** It is still committed and pushed; only the indexes are
   left out and named. Task 5's `test_a_group_note_travels_without_any_recorded_checkout`.

## Launch graph

Drawn last, over the imports each task's Interfaces block names.

```
A (switch, state) ──┐
                    ├─► C (commit, align, integrate) ─► D (push, run loop, triggers) ─► E (doctor, docs)
B (git, rules, scan)┘
```

A and B import nothing from each other but write one worktree, so they run in order (A, then B).

| Wave | Tasks | Plan lines | `src` budget | Why one dispatch |
|---|---|---|---|---|
| A | 1–2 | ~110 | 380 | the switch and the state file are the job's two inputs from the machine |
| B | 3–4 | ~120 | 650 | the scan runs through the runner and the rules Task 3 writes |
| C | 5–6 | ~150 | 850 | every move of `main` goes through one compare-and-swap and one alignment; integrate re-commits through commit's code |
| D | 7–8 | ~130 | 470 | the hook spawns the job's own argv and shares its lock and pending marker |
| E | 9 | ~80 | 150 | every surface that counts or lists: doctor, docs, README, outbound |

---

## Wave A — Tasks 1–2

### Task 1: The switch, and `setup --overlay` setting it

**Files:**
- Create: `src/stayfixed/sync/__init__.py`, `src/stayfixed/sync/switch.py`
- Modify: `src/stayfixed/areas.py`, `src/stayfixed/config/classes.py`, `src/stayfixed/setup/machine.py`, `src/stayfixed/setup/run.py`
- Test: `tests/sync/__init__.py`, `tests/sync/test_switch.py`, `tests/boundaries/test_delivery.py`, `tests/config/test_classes.py`, `tests/setup/test_setup.py`

**Interfaces:**
- Produces: `sync.switch.enabled(machine: Path | None = None) -> bool` (the default machine file when
  `None`; `False` for an absent file, an absent or non-bool key, or a file that does not parse);
  `SECTION = "sync"`, `KEY = "enabled"`; `write_machine(path, *, personal, overlay_root, machine,
  sync: Mapping[str, object] = {})`, `sync` an owned table merged key by key.

- [ ] **Step 1: failing tests.**
  - `test_enabled_only_for_a_true_bool`: absent file, `[sync]` absent, `enabled = "yes"`,
    `enabled = 1`, `enabled = false` → `False`; `enabled = true` → `True`.
  - `test_a_machine_file_that_does_not_parse_is_off`: invalid TOML → `False`, no raise.
  - `test_a_repository_cannot_set_sync`: a `stayfixed.toml` with `[sync] enabled = true` is refused
    by the loader with the machine-only message.
  - `test_setup_rendering_an_overlay_switches_sync_on` and `..._creating_...`: the machine file holds
    `[sync] enabled = true` after `setup --overlay` renders (and, with the `gh` runner double,
    creates); `[personal]`, `[machine]`, `[overlay]` and a foreign table survive.
  - `test_setup_recording_an_overlay_leaves_sync_alone`: absent stays absent; `false` stays `false`.
  - `tests/config/test_classes.py`: `TABLE_ROWS` gains `"sync.*"`, `MACHINE_FILE_KEYS` gains
    `"sync.enabled"`.
- [ ] **Step 2:** run `uv run pytest tests/sync/test_switch.py tests/setup/test_setup.py tests/config/test_classes.py -q`; the new tests fail.
- [ ] **Step 3:** add `"sync.*": KeyClass.MACHINE_ONLY` to `CLASSES`; `switch.py` reads through
  `read_machine_toml` and `machine_config_path`; `write_machine` gains the `sync` owned table;
  `_apply_overlay` (or its caller) passes `sync={"enabled": True}` for `render` and `create` only, in
  the write that records `[overlay] root`. The package's `__init__.py` holds the area's docstring.
  `DELIVERY_AREAS` gains the line `"sync",`; its mutation entry "sync drops out of every side"
  (the line deleted) is declared by Task 8, once `hooks.py` makes the area discovered.
- [ ] **Step 4:** the focused run passes; then `uv run pytest tests/config tests/setup -q`.
- [ ] **Step 5: mutations** (`mutations/core.toml` or the group `GROUP_OF` routes to; the oracle with
  pattern `sync/` and `setup/`): "a string 'true' switches sync on" (`is True` → truthy test);
  "recording an existing overlay switches sync on" (the kind test dropped).
- [ ] **Step 6:** commit `feat(sync): a per-machine switch, set when setup makes a new overlay`.

### Task 2: The job's state, lock, pending marker and pacing

**Files:**
- Create: `src/stayfixed/sync/state.py`
- Test: `tests/sync/test_state.py`

**Interfaces:**
- Consumes: `config.paths.data_directory()`, `fsops.write_atomically`.
- Produces: `OUTCOMES` (the 15 outcome names of the ported job); frozen dataclasses
  `Outcome(state, at, detail, paths, commits)`, `Holds(upstream_paths, upstream_since, local_commits,
  local_since)` with `.any`, `PendingAlign(from_sha, to_sha, paths)`, `SyncState(overlay, outcome,
  holds, last_fetch_ok, fetched_sha, last_job_at, pending_align, head)`; `EMPTY_HOLDS`;
  `StateUnreadable(Exception)`; `state_directory() -> Path` (`data_directory() / "sync"`);
  `read_state(d: Path) -> SyncState | None`; `write_state(d: Path, s: SyncState) -> None` (mode 0600);
  `Lock.try_acquire(path) -> Lock | None` (an exclusive non-blocking `flock`, close-on-exec, context
  manager, `release()`); `mark_pending(d)`, `take_pending(d) -> bool`; `throttled(last_job_at, now)
  -> bool`; `backed_off(state, head, now, *, upstream=None) -> bool`; `iso(moment) -> str`,
  `parse_time(text) -> datetime`; `THROTTLE_SECONDS = 120`, `BACK_OFF_MINUTES = 15`; file names
  `STATE_FILE`, `LOCK_FILE`, `SLEEPER_LOCK_FILE`, `PENDING_FILE`, `CHECKOUTS_FILE`, `SCRATCH`.

- [ ] **Step 1: failing tests**, ported from the reference's state tests minus `integrated` and the
  XDG directory, plus: `test_state_lives_in_the_data_directory` (`state_directory() ==
  home/".local/share/stayfixed/sync"`); `test_a_state_round_trips_and_carries_its_overlay`;
  `test_a_corrupt_state_is_unreadable_not_absent` (bad JSON, deep nesting, a wrong type, an unknown
  outcome); `test_a_lock_held_elsewhere_is_busy_and_released_on_close`; `test_pending_taken_once`;
  `test_throttle_and_back_off_treat_a_future_time_as_long_past`; `test_back_off_needs_a_hold_the_same_head_and_the_same_upstream`.
- [ ] **Step 2:** `uv run pytest tests/sync/test_state.py -q` fails on the missing module.
- [ ] **Step 3:** implement; JSON keys as the ported job writes them, plus `overlay`, minus
  `integrated` and `pending_align.integrated`.
- [ ] **Step 4:** the focused run passes.
- [ ] **Step 5: mutations:** the reference's rows for the throttle, the back-off's three comparisons,
  the future-time rule, "an unreadable state reads as absent", and the lock's non-blocking flag.
- [ ] **Step 6:** commit `feat(sync): the job's state, lock and pacing`.

---

## Wave B — Tasks 3–4

### Task 3: The runner, the rules of what may move, and the guard

**Files:**
- Create: `src/stayfixed/sync/git.py`, `src/stayfixed/sync/rules.py`
- Modify: `src/stayfixed/memory/store.py` (a `GROUPS` constant, if `next` has none)
- Test: `tests/sync/conftest.py`, `tests/sync/test_git.py`, `tests/sync/test_rules.py`

**Interfaces:**
- Consumes: `processes.kill_group`; `memory.store` `COMMON`, `PROJECTS`, `STORE_DIR`, `GROUPS`.
- Produces, `git.py`: `Ran(code, out, err, timed_out)`; `run(argv, *, cwd, timeout, env=None,
  index_file=None, stdin: bytes | None = None, unset_prefixes=()) -> Ran` (own session, the group
  killed on timeout, output decoded with `surrogateescape`, git's repository variables dropped);
  `git(repo, *args, timeout, env=None, index_file=None, stdin=None) -> Ran`; `GitError`,
  `GitTimeout(GitError)`; `job_env(repo, *, timeout) -> dict[str, str]`; `MIN_GIT = (2, 43)`;
  `version_ok(text) -> bool`; `Guard(ok, reason)`; `guard(repo, *, timeout, env=None) -> Guard`.
- Produces, `rules.py`: `MEMORY_PATHSPEC`, `NOT_MEMORY_PATHSPEC`, `MEMORY_SPECS` (pathspec, literal
  directory) — three each; `INDEX_NAME`; `MemoryPath(scope: str, name: str | None, below:
  tuple[str, ...])` with `scope` one of `"common"`, `"group"`, `"project"`, `.root`, `.is_index`
  (a project's `MEMORY.md` only), `.is_note`; `memory_path(path) -> MemoryPath | None`;
  `is_memory_path`; `index_of(project) -> str`; `RawEntry`; `entry_offends(entry) -> bool`;
  `dirty_memory(repo, *, timeout, env) -> list[str]`; `commit_entries(repo, rev_range, ...)`;
  `offending_paths(repo, *revisions, index_file=None, ...)`; `range_is_memory_only(repo, base, tip,
  ...) -> tuple[bool, list[str]]`.

- [ ] **Step 1: the test world.** `tests/sync/conftest.py`: a `world` fixture with a bare remote
  (`main`) and two clones under `tmp_path`, git configuration sealed by `tests.gitfixture.env`
  (identity, no global or system config); helpers to write, commit, rename, push a note from the
  other clone, build a crafted tree (a link, a gitlink, an executable, `..` as a project name), and
  merge with a resolution. No test reads the developer's git configuration.
- [ ] **Step 2: failing tests**, ported from the reference's git-layer tests, each extended to the
  group scope where it judges paths: `test_memory_path_agrees_with_git` (git's own pathspec match
  over a tree holding common, group and project notes, and decoys: a note under a project's
  `checkout/memory` directory, and one two directories below `groups`); renames listing both sides; a
  pathless commit and a clean merge never memory-only; the tree bound catching what commits hide;
  link, gitlink, executable, dot component, non-`.md`, binary refused; `000000` only for a deletion;
  the guard's reasons (old git, not a repository, each in-progress marker, unmerged paths, detached
  `HEAD`, another branch, another upstream); `test_git_version_floor`; `job_env` (an ssh program
  gets `BatchMode`, a wrapper is used as is, a timed-out `config` is a timeout); the runner killing
  the group of a child that outlives its timeout, and dropping `GIT_DIR` and friends.
- [ ] **Step 3:** run them; they fail.
- [ ] **Step 4:** implement. The layout constants come from `memory.store`; `rules.py` holds no
  second spelling of `common/memory` or `projects`.
- [ ] **Step 5:** `uv run pytest tests/sync -q` passes.
- [ ] **Step 6: mutations:** the reference's "what may move" rows (its rule numbers 1–5, 30–32,
  40–48), with the group scope added to the `glob` and `*` rows; one entry "a group's notes are not
  memory" (`groups` dropped from the pathspec).
- [ ] **Step 7:** commit `feat(sync): the rules of what may move, and the guard`.

### Task 4: The scanner and the three scans

**Files:**
- Create: `src/stayfixed/sync/scan.py`
- Test: `tests/sync/test_scan.py`

**Interfaces:**
- Consumes: `git.run`, `git.GitTimeout`.
- Produces: `CheckResult(ok, check_id, detail, timed_out, finding_commit)`; `gitleaks_pin(overlay)
  -> tuple[str, str, str | None] | None`; `gitleaks_binary(home, overlay, env=None) -> Path | None`;
  `scan_index(repo, index_file, binary, timeout, env=None, scratch=None) -> CheckResult`;
  `scan_range(repo, base, tip, binary, ...)`; `scan_commits(repo, commits: list[tuple[str, str]],
  binary, ...)`; `NO_SCANNER` (the `scan_unavailable` detail, with the remedy of D2).

- [ ] **Step 1: failing tests**, ported from the reference's check tests minus the delivery check and
  the go-installed rule; the scanner is a stand-in script answering with the real build's interface
  (a JSON report naming rule, file and commit; exit 1 with an empty report for a failed scan), and
  pre-commit's database a SQLite file the fixture writes under a scratch `XDG_CACHE_HOME`:
  `test_the_pin_is_read_from_the_overlays_config`; `test_no_row_for_the_pinned_rev_is_no_scanner`;
  `test_an_explicit_version_has_no_substitute`; `test_default_then_system`;
  `test_a_build_linking_out_of_its_row_is_not_it`; `test_a_finding_names_rule_file_and_commit_never_the_secret`;
  `test_a_failed_scan_is_not_a_finding`; `test_rules_and_ignores_come_from_head`;
  `test_an_uncommitted_gitleaksignore_at_the_root_stops_the_scan`; `test_gitleaks_variables_are_dropped`;
  `test_metadata_scan_names_the_commit`.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement; the build's default rules are the `gitleaks.toml` of the source checkout
  beside the build, as the reference reads them.
- [ ] **Step 4:** `uv run pytest tests/sync/test_scan.py -q` passes.
- [ ] **Step 5: mutations:** the reference's scan rows (the report, not the exit code, decides a
  finding; the pin's revision; rules from `HEAD`; the root ignore file; `GITLEAKS_` dropped).
- [ ] **Step 6:** commit `feat(sync): the secret scan, from the overlay's pinned build`.

---

## Wave C — Tasks 5–6

### Task 5: The pre-render, the commit through a temporary index, and the alignment

**Files:**
- Create: `src/stayfixed/sync/render.py`, `src/stayfixed/sync/job.py`
- Modify: `src/stayfixed/memory/index.py`, `src/stayfixed/memory/api.py`
- Test: `tests/sync/test_render.py`, `tests/sync/test_commit.py`, `tests/memory/test_index.py`

**Interfaces:**
- Consumes: Task 2's state, Task 3's `git`/`rules`, Task 4's scans.
- Produces, `memory`: `rerender_overlay_index(root: Path, *, machine: Path | None) -> Rerendered`,
  `Rerendered(project: str | None, overlay_store: Path | None, reason: str | None)`: resolves the
  checkout's `Config` and store as `memory index` does, renders and writes the index, checks it,
  renders once more on drift; a checkout not bound in overlay mode has a `reason`. Exported from
  `src/stayfixed/memory/api.py`.
- Produces, `render.py`: `remember_checkout(root: Path, d: Path) -> None` (newest first, at most
  `CHECKOUTS_KEPT = 64`, through `fsops`); `prerender(overlay: Path, dirty: list[str], d: Path, *,
  also: Iterable[str] = ()) -> dict[str, str]` (project → why its index was not rendered).
- Produces, `job.py`: `Limits(fetch=30, push=30, prerender=30, checks=60, job=180, local=30)`;
  `JobContext(overlay, state_dir, home, host, now, limits, deadline, remarks, notices, pending,
  fetched_sha, last_fetch_ok, resolved, refused, holds)` with `limit(step)` and `env`;
  `JobTimeout`, `JobStopped`; `commit_memory(ctx, *, also=()) -> Outcome | None`;
  `align(ctx, pending) -> Outcome | None`; `align_first(ctx) -> Outcome | None`;
  `_move_main(ctx, pending) -> bool` (record, then compare-and-swap); `_outcome(...)`; `_scratch(ctx)`
  (the fixed `scratch/` directory).

- [ ] **Step 1: failing tests**, ported from the reference's commit tests, minus the subprocess
  pre-render, plus:
  - `test_rerender_writes_the_overlays_index_from_a_bound_checkout` and
    `test_an_unbound_checkout_has_a_reason` (in `tests/memory/test_index.py`, with an attached
    fixture checkout);
  - `test_a_recorded_checkout_list_keeps_the_newest_64`;
  - `test_a_dirty_common_or_group_note_renders_every_recorded_project`;
  - `test_a_project_with_no_recorded_checkout_keeps_its_index_out_and_says_so`;
  - `test_a_group_note_travels_without_any_recorded_checkout` (Review focus 5);
  - from the reference: only the pathspec is staged; links (at the path or above it), nested
    repositories, executables, dot paths, non-`.md` and binary files are left out and named while
    the plain notes beside them commit; the commit's message and scopes (`groups/<tag>` among them);
    signing honoured and a signing failure `signing_failed`; `raced` when `main` moved; an unmerged
    note from a `stash pop` never committed; the real index's memory entries aligned and retried on
    `index.lock`; `index_stale` with the command; a job killed after the swap finished by
    `align_first`; a record whose swap never happened dropped without touching the index;
    `test_no_scanner_commits_nothing_and_says_how_to_build_one`; a `.gitattributes` filter left in
    the working tree changes nothing committed.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement. `commit_memory` builds the commit in `scratch/index`, runs the index
  scan before `write-tree`, and moves `main` only by `_move_main`. Removals in the working tree go
  through `fsops.remove_within(overlay, path)`.
- [ ] **Step 4:** `uv run pytest tests/sync tests/memory/test_index.py -q` passes.
- [ ] **Step 5: mutations:** the reference's commit and alignment rows (stage only the pathspec; the
  compare-and-swap; record before the swap; the alignment never skipped; the unmerged re-check;
  signing never silently off), and "a group note does not re-render the recorded projects".
- [ ] **Step 6:** commit `feat(sync): commit notes through a temporary index`.

### Task 6: Fetch, integrate by replay, and the index union

**Files:**
- Modify: `src/stayfixed/sync/job.py`
- Test: `tests/sync/test_integrate.py`

**Interfaces:**
- Consumes: Task 5's `_move_main`, `align`, `commit_memory`, `_scratch`, `JobContext`.
- Produces: `FETCHED_REF = "refs/stayfixed/fetched"`; `fetch(ctx) -> tuple[str | None, Outcome |
  None]`; `union_index(local: bytes, upstream: bytes) -> bytes`; `replay(ctx, onto, commits) ->
  tuple[str | None, list[str]]`; `integrate(ctx, upstream) -> Outcome | None`; `REVIEW` (the review
  command a hold names); `_remote_failure(ctx, result, what, limit) -> Outcome`.

- [ ] **Step 1: failing tests**, ported from the reference's integration tests minus the cloud take:
  a fast-forward; local memory commits replayed onto the checked sha with their author, message,
  encoding header and signature setting; an empty commit of the owner's kept; `fetch.fsckObjects`
  refusing a tree with `..` or `.git`; the fetched sha read once from the job's own ref (the owner's
  fetch meanwhile changes nothing); an upstream range touching anything outside memory held with
  `REVIEW`, nothing integrated or pushed; a hold's `since` kept while it stands and cleared once the
  range is memory-only; a local merge commit `conflict`; a non-index conflict `conflict` with `main`
  unmoved; an index-only conflict resolved by union and re-rendered; a dirty incoming note
  `waiting_clean_tree`; a dirty `MEMORY.md` united in the working tree, never blocking; an upstream
  tree git will not read held; incoming notes written only where the working tree still has the old
  version; `test_an_upstream_group_note_is_integrated`; `test_no_rebase_ever_runs`; offline,
  refused credentials and timeout classified.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `uv run pytest tests/sync -q` passes.
- [ ] **Step 5: mutations:** the reference's integration rows (replay, never rebase; the job's own
  fetched ref; `fsckObjects`; hold on a range outside memory; union keeps local-only bullets; write
  only over the old version).
- [ ] **Step 6:** commit `feat(sync): take memory-only upstream changes by replay`.

---

## Wave D — Tasks 7–8

### Task 7: Push, the job's end, the run loop and its entry point

**Files:**
- Modify: `src/stayfixed/sync/job.py`
- Test: `tests/sync/test_push.py`, `tests/sync/test_run.py`

**Interfaces:**
- Consumes: Tasks 2–6; `sync.switch.enabled`; `config.overlay.overlay_root`.
- Produces: `push(ctx, upstream) -> Outcome | None`; `run_job(ctx) -> SyncState | None` (lock; one
  round; at most two more while a trigger is pending; a sleeper scheduled for a trigger still pending
  at the cap); `BOOT` and `job_argv(*, wake: datetime | None) -> list[str]` (D7);
  `spawn(overlay: Path, *, wake: datetime | None = None) -> None` (detached: own session, standard
  streams on `/dev/null`, `close_fds`, `cwd=overlay`); `main(argv: list[str] | None = None) -> int`
  (`[--sleep-until ISO]`; reads the switch and the overlay root; exits 0 whatever happens).

- [ ] **Step 1: failing tests**, ported from the reference's push and loop tests minus `--cloud`, plus:
  - `test_the_job_imports_nothing_from_the_overlay` (Review focus 3): a `json.py` and a `stayfixed/`
    package that write a marker file, planted at the overlay's root; `spawn` a real job; the marker
    never appears and the state is written;
  - `test_a_sleeper_woken_after_sync_was_switched_off_runs_no_job`;
  - `test_a_state_for_another_overlay_is_not_used` (the overlay moved);
  - `test_busy_lock_marks_pending_and_the_job_loops` (Review focus 4);
  - from the reference: the memory-only range pushed as the checked sha, never `main`, never forced;
    a local commit outside memory held, naming it; both holds recorded at once; an upstream hold
    skips the push; `rejected` retried on the next trigger; `secret_found` with the sha and the
    rewrite remedy; a secret only in a commit's author, message or path names never pushed; a failed
    range scan `hook_failed`, not `secret_found`; `scan_unavailable` still integrates upstream;
    the end rule (a stop, else the latest notice, refusals the earliest; each said once; the detail
    cut fairly); a hung remote `timeout` with the lock released; the whole job's limit; every git
    call non-interactive; a replace ref cannot disguise a commit; an unreadable state replaced and
    said.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement; `main` reads `enabled()` and `overlay_root(None)` first and returns 0 with
  no job when either says no; the scratch directory is removed whole at the start and end of
  `_one_job`.
- [ ] **Step 4:** `uv run pytest tests/sync -q` passes.
- [ ] **Step 5: mutations:** the reference's push and loop rows (push the checked sha; never force;
  scan before push; the report decides a secret; the pending loop; the sleeper's own lock), and
  "the job runs with the overlay on its path" (`-I` dropped from `job_argv`).
- [ ] **Step 6:** commit `feat(sync): push the checked range, and run the job detached`.

### Task 8: The triggers, and `Stop` and `SessionEnd` in the hook surfaces

**Files:**
- Create: `src/stayfixed/sync/hooks.py`
- Modify: `src/stayfixed/hooks/api.py`, `hooks/hooks.json`, `scripts/smoke_hooks.py`, `.github/workflows/smoke.yml`, `tests/test_check_workflow.py`, `tests/hooks/test_hooks_json.py`
- Test: `tests/sync/test_hooks.py`, `tests/scripts/test_smoke_scripts.py`

**Interfaces:**
- Consumes: `hooks.api` `Handler`, `HookEvent`, `HookResult`; Task 2's pacing; Task 3's
  `MEMORY_PATHSPEC`; Task 5's `remember_checkout`; Task 7's `spawn`.
- Produces: `register() -> list[Handler]` — one handler per event, `SessionStart`, `Stop`,
  `SessionEnd`; `decide(event: str, source: str | None, overlay: Path, d: Path, now: datetime) ->
  tuple[str, datetime | None]` (`"run"`, `"schedule"` with the wake time, or `"none"`); `EVENTS`
  in `src/stayfixed/hooks/api.py` gains `"Stop"` and `"SessionEnd"`.

- [ ] **Step 1: failing tests**, ported from the reference's hook tests minus the cloud decision:
  the four triggers (dirty or untracked memory, commits ahead of the upstream, a standing outcome or
  hold, every session start but a compaction); the back-off on an unchanged hold, broken by a new
  `HEAD`, a moved upstream or a dirty note; a trigger inside the throttle or during a job scheduled,
  never dropped; `SessionEnd` never throttled; one sleeper at a time. Plus:
  - `test_with_sync_off_stop_runs_no_git_and_spawns_nothing` (Review focus 1; a spy on `git.run` and
    `spawn`);
  - `test_stop_and_session_end_print_nothing_that_blocks` (Review focus 2): `stayfixed hook Stop`
    and `hook SessionEnd` through the CLI, sync on and off; stdout carries no `decision`;
  - `test_session_start_records_the_checkout_when_sync_is_on`;
  - `test_no_overlay_or_not_a_repository_spawns_nothing`;
  - the smoke script: `Stop` and `SessionEnd` samples, `EXPECTED_ENTRIES = 12`,
    `EXPECTED_ROWS = 13`, and `smoke.yml`'s line derived by `tests/test_check_workflow.py`.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement. Every import inside the handler bodies; each handler wraps its work and
  returns `HookResult()` on every path. `hooks.json` gains two entries running `hook Stop` and
  `hook SessionEnd` with `timeout: 10`.
- [ ] **Step 4:** `uv run pytest tests/sync tests/hooks tests/scripts tests/test_check_workflow.py -q`
  passes; paste the time `stayfixed hook Stop` takes with sync off, over ten runs, for the review.
- [ ] **Step 5: mutations:** the reference's trigger rows (each trigger; the back-off's comparisons;
  `SessionEnd` unthrottled; schedule, never drop; compaction no trigger) and "sync off still
  decides" (the switch read dropped from the handler).
- [ ] **Step 6:** commit `feat(sync): start the job from SessionStart, Stop and SessionEnd`.

---

## Wave E — Task 9

### Task 9: `doctor`'s row, the docs, README's network table, the changelog

**Files:**
- Create: `src/stayfixed/sync/doctor.py`, `changelog.d/+note-sync.feature.md`
- Modify: `README.md`, `docs/cli.md`, `CONTRIBUTING.md`, `skills/doctor/SKILL.md`, `.github/workflows/smoke.yml`, `tests/outbound/policy.py`
- Test: `tests/sync/test_doctor.py`, `tests/test_outbound.py`, `tests/boundaries/test_discovery.py`, `tests/doctor/test_checks.py`, `tests/doctor/test_command.py`, `tests/test_documents.py`, `tests/test_install_path.py`

**Interfaces:**
- Consumes: `doctor.api` `Contribution`, `Context`, `Row`, `OK`, `WARN`, `RED`, `SKIP`;
  `switch.enabled`; `state.read_state`; `git.version_ok`; `scan.gitleaks_binary`.
- Produces: `register() -> Contribution` with one check named `sync`.

- [ ] **Step 1: failing tests.** `test_doctor.py`, one per arm: off → `SKIP` naming the machine file
  and the key; on with no overlay recorded → `WARN`; on with git below 2.43 → `WARN` saying the job
  does nothing and why; on with no scanner build → `RED` with D2's remedy; on with a hold → `WARN`
  naming it and the review command; on with a last outcome other than `ok`/`skipped` → `WARN` with
  the outcome and its first line; on and never run → `OK`; on and last `ok` → `OK` with the time. A
  state recorded for another overlay reads as never run. Then the pinned counts: 14 → 15 rows in
  every place the Premise lists, `REPORT` gaining `sync` after `overlay`, `test_discovery`'s list
  gaining `stayfixed.sync.doctor`.
- [ ] **Step 2:** they fail.
- [ ] **Step 3:** implement the row. README: the `git fetch` row names the sync job beside
  `stayfixed bugs new` (one row per program); a new `git push` row ("the sync job", the overlay's
  `origin`, "a job with memory commits to push, on a machine whose machine file switches sync on");
  a note that both run only with `[sync] enabled = true`. `tests/outbound/policy.py`: the sync runner
  a root launcher, `("git", "push")` a network row, the job's local git subcommands and the scanner
  local, the runner's environment and the spawn declared. `docs/cli.md`: a section "Note sync" (what
  the job does, in order; what it never does; the switch and who sets it; the state directory and
  every path the job writes or removes, by the "Enumerated writes" rule; the outcomes; holds and how
  to take one; the floor; Claude Code only, Codex sessions do not trigger it; what is left when the
  plugin goes), the `hook <event>` and "Hooks" sections gaining `Stop` and `SessionEnd`, the doctor
  table its `sync` row, and `setup --overlay`'s **Writes** paragraph the `[sync]` key. CONTRIBUTING:
  the discovered areas list and the delivery side's description gain `sync`. The fragment: one release note.
- [ ] **Step 4:** `uv run pytest tests/sync tests/doctor tests/test_outbound.py tests/test_documents.py tests/boundaries tests/test_install_path.py -q`
  passes; then the full gates, once: `uv run pytest -n auto --cov --cov-fail-under=92`,
  `uv run ruff check . && uv run ruff format --check .`, `uv run mypy`,
  `uv run python scripts/release.py check`, and the oracle on `sync/`.
- [ ] **Step 5: mutations:** "doctor calls a missing scanner green", "doctor calls an old git green".
- [ ] **Step 6:** commit `feat(sync): doctor reports the sync, and the docs say what it sends`.

### After Wave E (controller)

Merge `origin/next` into the branch, re-run the full gates, open the pull request into `next` with
the net size, wait for CI with `gh run watch <run-id> --exit-status`, fix red, then the final review
and one re-review. The controller merges.

## Findings

Filled during execution: each wave's head, its net size and token total, what the review changed.
