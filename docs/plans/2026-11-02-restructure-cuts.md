# Restructure, lane 3 — the cuts: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking. **The lettered wave is the
> dispatch unit, not the task:** one implementer per wave (waves A–D for pull request 1, E–F for pull
> request 2), every task inside a wave keeping its own red check, verification and commit. **One final
> review per pull request, none per wave:** a deletion-only pull request gets one correctness seat and
> at most one scoped re-review (section "Execution contract" below).

**Goal:** delete what nobody uses, in two deletion-only pull requests into the integration branch
`next`, so that the methodology pack keeps only the bug ledger, the plan and doc lints, the commit
checks, a minimal `init` and their skills.
- **Pull request 1 (waves A–D):** the gate ratchet (`assess`, `gate`, `adopt promote`, the reusable
  workflow `check.yml` and its callers' keys), the heavy scaffold (`upgrade`, `uninstall`, the project
  templates beyond a minimal `init`), and dead commands (`memory refs` with the note graph,
  `memory fit`, `trust list`, `trust revoke`, `test hygiene`).
- **Pull request 2 (waves E–F):** `prove`, the `profiles` package and what loses its last importer
  with them; the demo acts and the `Stop`-hook example built on `prove`.

**Architecture:** no wave adds a feature. A `src` line a wave writes is a caller's adaptation to a
removal, with one named exception each pull request (`bugs regressions` gets its own `--timeout` in
pull request 1, and runs through the product's process runner in pull request 2). Every deletion takes
its tests, its mutation entries, its `docs/cli.md`, `README.md`, skill and contributor text, and its
pinned import crossings in the same commit, because the suite holds all of them
(`tests/test_documents.py` parses every command a tracked file names, `tests/skills/` every skill
invocation, `tests/scripts/test_mutation_oracle.py::test_every_declared_entry_is_sound_before_any_run`
every `reddens` id and `before` line, `tests/boundaries/test_delivery.py` every crossing).

**Tech Stack:** Python ≥ 3.11 standard library at runtime; `uv`, pytest (`-n auto`), ruff, mypy, the
mutation oracle (`scripts/mutation_oracle.py`, entries in `mutations/*.toml` routed by `GROUP_OF`),
towncrier fragments in `changelog.d/`, GitHub Actions.

**Spec:** the restructure's umbrella design and plan, kept in a private repository this one cannot
link to. What this lane needs from them is restated here:

> Lane 3 makes two deletion-only pull requests into `next`, in this order.
> 1. Gates, scaffold, dead commands: `assess` (`gate`, `adopt promote`), `check.yml`, `smoke.yml`'s
>    `same-repository-form` job, the reusable-workflow section of `docs/cli.md`, `[stayfixed]
>    enforced`, `[gates.*]` and `[ci]` (`doctor`'s `ci-ref` row with them), `upgrade`, `uninstall`
>    (its pinned crossing goes), the project templates beyond what a minimal `init` needs, the skills
>    that wrap deleted commands (`adopt`, `upgrade`, `uninstall`); `memory refs` with the note graph,
>    `memory fit`, `trust list`, `trust revoke` (the docstrings that name it say instead that a
>    promoted note is withdrawn by editing or deleting it), the `test hygiene` command (the hook's
>    red-run note stays). A minimal `init` writes `stayfixed.toml` and the files the surviving pack
>    commands need (the roadmap's trail markers and `trail.toml`), nothing else. `bugs regressions`
>    reads its timeout from its own option with today's default. Every tracked file naming what goes
>    (`CONTRIBUTING.md`, `RELEASING.md`, `SECURITY.md`, `smoke-release.yml`) is edited in the same
>    pull request.
> 2. `prove` and `profiles`, after the hints area's test-runner table has merged: `prove`, the
>    `profiles` package (`[stayfixed] profile` with it), the red-run note re-pointed at the hints
>    area's runner table, `uvrun` and whatever else loses its last importer, the demo acts built on
>    `prove` and the gates (`examples/demo` keeps the attach act; `examples/stop-hook/` and its test
>    go; `ci.yml`'s `demo` job runs what is left), `bugs regressions` on the product's process runner.
>
> Each pull request deletes its tests, mutation entries, documentation rows and pinned crossings;
> re-anchors every mutation entry on surviving code whose only reddening tests it deletes, by running
> the oracle on it; lists an entry no surviving test reddens for the owner instead of deleting it
> silently; and reports to the controller, never in the pull request body, every caller of a deleted
> command or key outside this repository.

**Scope:** a change belongs to this plan iff it removes something the quote above names, or adapts a
surviving caller, test, document or mutation entry to that removal. Out: anything another lane of the
restructure adds (the hints area and the three-sided partition land first, from the lane this plan
waits on; tags, sync, restore and the runner table are other lanes'); the owner's configuration files
and other repositories (the cutover migrates them); `docs/plans/*` and `CHANGELOG.md`, which are
history and are not edited.

**Premise:** measured on 2026-11-02 at `origin/next`, which then equalled `dev`, before the lane that
moves the session hints into a `hints` area (#158) merged. After that merge, Task 0 re-measures and
amends this plan in place before wave A starts; every number below is a measurement to re-check, not
a claim to build on. A wave re-measures its own part before its first edit and reports a mismatch
instead of guessing.

## Measured deletion set

Lines are `wc -l` of whole files; "trimmed" files lose part of their lines.

| | Pull request 1 | Pull request 2 |
|---|---|---|
| `src`, whole files | `assess/` 2,693; `project/{upgrade,uninstall,rewrite}.py` 833; `memory/{graph,refs}.py` 269; `trust/commands.py` 105; ten files of `templates/project/` 126 | `prove/` 1,558; `profiles/` 2,187 (`.py`) plus `python/profile.toml`, `python/rules.md` |
| `src`, trimmed | `project/{commands,detect,footprint,ignored,init,questions,templates,layout,api}.py` (2,676 today), `config/{schema,loader,classes,layout}.py`, `doctor/checks.py`, `memory/commands.py`, `guards/commands.py`, `ledger/regressions.py`, `scaffold/*` where only the deleted callers used a branch | `ledger/regressions.py`, `harnesses.py`, `scaffold/engine.py`, the red-run note, `uvrun` and anything else left without an importer |
| workflows | `check.yml` 181, `smoke-release.yml` 33, `smoke.yml`'s `same-repository-form` job | `ci.yml`'s `runners` job; its `demo` job shrinks |
| skills, examples | `skills/{adopt,upgrade,uninstall}/` 185; `examples/demo` act 5 loses its gate steps | `examples/stop-hook/` 235; demo acts 1–4 and 7 |
| tests, whole files | `tests/assess/` 5,935; `tests/project/test_{upgrade,uninstall,rewrite,footprint_commands,round_trip,journey,gates}.py` 3,031; `tests/memory/test_{graph,refs}.py` 788; `tests/trust/test_commands.py` 205 | `tests/prove/` 6,073; `tests/profiles/` 1,689; `tests/test_stop_hook_recipe.py` 147; `tests/test_runners_job.py` 133; `tests/fixtures/prove/` (388 KB) |
| tests, trimmed | the rest of `tests/project/` (4,444 today); `tests/test_check_workflow.py` (1,740, of which the `check.yml` cases are about 800); `tests/config/`, `tests/doctor/`, `tests/guards/`, `tests/memory/`, `tests/skills/`, `tests/test_documents.py` | callers' tests of the trimmed modules |
| mutation entries on deleted files | 243 (`assess` 141, `project` 44, `check.yml` 34, `memory` 14, `trust` 5, `templates` 4, `smoke-release.yml` 1), plus those on trimmed lines | 257 (`prove` 136, `profiles` 119, `stop-hook` 2) |
| entries on surviving code whose **every** reddening test is deleted | 51: `committed.py` 9, `scaffold/entries.py` 7, `memory/commands.py` 6, `processes.py` 5, `project/footprint.py` 4, `scaffold/engine.py` 4, `docs/hygiene.py` 2, `docs/trail.py` 2, `memory/store.py` 2, `scaffold/manifest.py` 2, and one each in `config/layout.py`, `guards/roots.py`, `guards/commit.py`, `project/commands.py`, `project/templates.py`, `ledger/check.py`, `docs/plans.py`, `ledger/commands.py` | 13: `ci.yml` 6, `guards/hygiene.py` 3, `guards/roots.py` 2, `fsops.py` 1, `cli.py` 1 |
| entries losing **some** reddening tests | 45 | 11 |
| entries reddened only from trimmed test files (re-check per test id) | 150 (`release.yml` 29, `project/init.py` 23, `smoke.yml` 17, `project/templates.py` 16, …) | 0 |

`docs/cli.md` loses its sections for `trust list`, `trust revoke`, `memory fit`, `test hygiene`,
`assess`, `gate`, `adopt promote`, `memory refs`, `upgrade`, `uninstall` and "The reusable workflow"
(about 1,500 of its lines), and its `init` sections shrink. Tracked text outside `src`, `tests` and
history naming what goes (`grep -cE` of the deleted commands and keys): `docs/cli.md` 217 lines,
`README.md` 39, `CONTRIBUTING.md` 10, `RELEASING.md` 4, `SECURITY.md` 1, `docs/methodology/principles.md`
4, the skills `init` 6, `doctor` 3, `memory-sweep` 3, `sweep-defect-class`, `setup` and
`run-correctness-audit` 1 each, `src/stayfixed/presets/recommended.toml` 4, the fixtures
`smoke-project` 6, `ledger` 1, `hostile-project` 1, and five unreleased fragments in `changelog.d/`.

Expected net, both pull requests together: `src` about −9k, tests about −21k, mutation entries about
−560 (the umbrella's estimate, which these measurements match).

## Execution contract

The controller copies the relevant part into every brief.

1. **Final review.** One per pull request, after wave D (pull request 1) and wave F (pull request 2).
   A deletion-only pull request gets **one correctness seat**: did anything still shipped lose a
   test, a document row, a mutation guard or a caller; does every surviving command still run; is a
   removed control's adversary named in the body. One scoped re-review, then stop. Reviewers report
   findings with no replacement text; only correctness and requirement gaps go back to the
   implementer; Minors become follow-ups in the report.
2. **Lifecycle matrix.** The table below, checked at pre-flight (Task 0) and again by the reviewer.
3. **Parallelism.** One worktree, so the waves run one after another (A, B, C, D, then E, F); the
   reviewer is read-only and may run beside nothing but the controller. One oracle per machine: its
   lock is per machine, and a run that reports another run holds it waits and retries.
4. **Templates.** A fix brief deletes sibling instances or folds them into one rule, never adds a
   guard to each, and carries a net budget: `src` and tests together may not grow in a fix round.
5. **Verification.** Focused runs while iterating; one full suite
   (`uv run pytest -n auto --cov --cov-fail-under=92`), `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run mypy` and `uv run python scripts/release.py check` before
   each push; the oracle locally only with a pattern for the entries a task touched
   (`uv run python scripts/mutation_oracle.py "<pattern>"`), after the commit it is about. Paste what
   a command printed. A predicted mutation outcome is a hypothesis until the oracle prints it.
6. **Net size.** Every review package and report prints
   `git diff --shortstat origin/next HEAD -- src tests mutations docs` and the same per area.

Implementer briefs also carry: report a mismatch between plan and tree instead of guessing; no line
numbers from this plan (they go stale); write nothing under the repository but the wave's change; a
private scratch subdirectory per agent; never kill a process by a name pattern; never run `attach`,
`setup`, `sync`, a hook or a probe against the real `HOME` (tests use `tmp_path` and a scratch
`HOME`); no pytest probe outside `tests/` that imports `tests.conftest`. Reviewer briefs: no nested
agents; no `git checkout`, `restore`, `stash` or `clean`.

**Every pull request body** carries "What this removes and what is lost": for each removed control,
the adversary it named, why it stopped nobody (or why nobody used it), and what no row, check or
command reports any more; plus the net size. It is written from the diff, not from this plan. It
names no repository, path or file outside this one: the callers list goes to the controller.

## Global constraints

- Standard library only at runtime; no new dependency, no new module.
- **Deletion is the unit.** A control's code, tests, `docs/cli.md` and `README.md` rows, contributor
  text, skill text, mutation entries and pinned crossings go in one commit. A test that holds behaviour
  still shipped is never deleted: when a test of a deleted command also holds a surviving reader
  (the loader's integer limit, a surviving workflow, the scaffold engine), the surviving half moves
  to the surviving test file in the same commit.
- **No old spelling stays.** A removed command, flag or key is gone with no alias. The loader keeps
  refusing an unknown key, so a `stayfixed.toml` that still carries `enforced`, `[gates]`, `[ci]` or
  (pull request 2) `profile` is refused with the loader's existing message; the `upgrading` fragment
  says which keys to delete.
- **Mutation entries:** an entry on deleted code goes with it. An entry on surviving code drops the
  `reddens` ids its commit deletes; when none is left, the task names a surviving test that the
  oracle proves reddens (paste the run) or, when none does, keeps nothing and lists the entry's name
  and `before` line for the owner in the wave's report. A comment citing a deleted entry by quoted
  name goes with it (`tests/scripts/test_mutation_oracle.py::test_every_cited_entry_name_is_declared`).
- **Neutrality.** No tracked line carries a bare 8–10-character hexadecimal commit id or the token
  `PR` followed by a space and `#` (`tests/test_neutral.py`); write `#158`. Nothing names a
  repository outside this one.
- **Commits** follow `CONTRIBUTING.md`: `refactor(assess): …`, `refactor(project): …`, `ci: …`,
  `docs: …`. Each pull request carries one `upgrading` fragment in `changelog.d/` naming every
  removed command and key, and deletes the unreleased fragments that describe only removed features.

## Lifecycle matrix

Every command or key this lane deletes, against what a user who relied on it now does. "Refused"
means the loader's or the parser's existing refusal; no new message is written.

| Removed | List | Change | Unlist / undo | Move a path | Fail part-way |
|---|---|---|---|---|---|
| `assess` | `doctor` and `bugs check`/`docs check`/`plan check` report each surviving check | — | — | — | — |
| `gate`, `check.yml` | — | a caller pinned to an old commit keeps running that commit's workflow, which installs that commit's `stayfixed`; a caller pinned to a later commit fails to resolve the file (cutover moves the callers) | delete the caller workflow | — | — |
| `adopt promote`, `[stayfixed] enforced` | — | the key is refused; delete it | — | — | — |
| `[gates.*]`, `[ci]` | — | refused; delete them. `bugs regressions --timeout` replaces `custom_timeout_seconds` | — | — | — |
| `upgrade` | — | a scaffold file is edited by hand | — | — | — |
| `uninstall` | — | — | `init` now writes four files (Task 8); delete them, and `.stayfixed/manifest.json` | — | — |
| `memory refs`, `memory fit` | `doctor`'s memory rows still say whether each bundle fits | — | — | — | — |
| `trust list` | the reviewed-notes record is read by `memory promote --changed`, which lists what is unreviewed | — | — | — | — |
| `trust revoke` | — | — | a promoted note is withdrawn by editing it (its digest changes) or deleting it | — | — |
| `test hygiene` | the `PostToolUse` red-run note says the same after a red run | — | — | — | — |
| `init` (kept, shrunk) | `--dry-run` lists the four files | answers still reach `stayfixed.toml` | delete the four files and the manifest | `[paths] roadmap` still places the roadmap and `trail.toml` beside it | a refused write leaves the manifest unwritten, as today (`tests/project/test_init.py`) |
| `prove` (PR 2) | — | `bugs regressions` reports each regression's exit code | — | — | an interrupted regression ends the run, as today |
| `profiles`, `[stayfixed] profile` (PR 2) | — | refused; delete the key | — | — | — |

Task 0 checks each row against the tree; the reviewer checks the shipped text says the same.

## Review focus

The failures these cuts can cause that no task's own tests show, most likely first, each with the
test that pins it.

1. **A caller outside the parser's view.** `tests/test_documents.py` holds every command a tracked
   file names after `stayfixed `, but not an argv list (`["adopt", "promote", …]` in
   `examples/demo/demo.py`) or a workflow that calls `python3 -m stayfixed gate`. Pinned by each
   task's search step: the deleted subcommand searched as a string token (`"gate"`, `'adopt'`,
   `gate --`), not only as `stayfixed gate`; and by `ci.yml`'s `demo` job, which runs the argv lists.
2. **`doctor`'s row count, spelled in five places.** Removing `ci-ref` makes fourteen thirteen in
   `README.md` (twice), `docs/cli.md`, `skills/doctor/SKILL.md` and `smoke.yml`
   (`assert len(rows) == 14`). Pinned by `tests/test_documents.py`'s count rule and the smoke job;
   Task 6 edits all five.
3. **A surviving guard that loses its only test.** 51 entries in pull request 1 and 13 in pull
   request 2 guard surviving code through tests this lane deletes. Pinned by
   `test_every_declared_entry_is_sound_before_any_run` (a deleted id is a finding) and by the oracle
   run each task pastes for the entries it re-anchors.
4. **A minimal `init` that leaves a pack command red on a fresh repository.** Measured on a scratch
   repository holding only `stayfixed.toml`: `docs trail --check` fails ("docs/roadmap.md does not
   exist"), `bugs index --check` fails ("docs/bug-reports.md is stale"), `docs check` names a missing
   `AGENTS.md`. Pinned by Task 8's
   `test_a_fresh_init_leaves_trail_and_ledger_checks_green`: after `init --yes` on an empty
   repository, `docs trail --check`, `bugs index --check` and `bugs check` exit 0. `docs check`'s
   missing `AGENTS.md` is accepted: the project writes its own, and `docs/cli.md`'s `init` section
   says so.
5. **A loader test that used a deleted key as its sample.** The integer-limit and range cases in
   `tests/config/test_loader.py` use `[gates] custom_timeout_seconds`; they hold the reader, not the
   key. Pinned by Task 6's step that moves them to a surviving integer key and keeps their mutation
   entries' ids valid.

---

## Wave launches

Drawn over what each task consumes; every edge is an import or a shared table, not a shared file.

```
Task 0 (re-measure after #158) ─► A ─► B ─► C ─► D ─► [pull request 1, review, controller merges]
                                                                   │
lane 6's runner table merged into next ───────────────────────────┴─► Task 12 ─► E ─► F ─► [pull request 2]
```

- **Inside B:** the workflow first (Task 4), because `tests/test_check_workflow.py` and the demo run
  `gate`; then the area (Task 5); then the keys (Task 6), whose last readers were in `assess`.
- **B before C:** `assess` imports `project.api` (`rewrite_owned`, `ASSESSMENT`, `CI_WORKFLOW`), so
  `rewrite.py` and `uninstall.py` can go only after `assess` has.
- **A before B:** none by import; A is first because it is small and touches `docs/cli.md` and
  `README.md` sections B does not, so B's diff reads against a settled base.
- **E before F:** `ledger/regressions.py` and the demo import `prove`; `prove/run.py` and the
  red-run note import `profiles`. `bugs regressions` leaves `prove` in E, then `prove` goes, then
  `profiles`.

| Wave | Tasks | Plan lines (approx.) | Pull request |
|---|---|---|---|
| A — dead commands | 1–3 | 80 | 1 |
| B — the gate ratchet | 4–6 | 140 | 1 |
| C — the heavy scaffold | 7–9 | 110 | 1 |
| D — re-anchor, text, open | 10–11 | 40 | 1 |
| E — `prove` | 13–14 (Task 12 is the controller's) | 45 | 2 |
| F — `profiles` | 15–17 | 45 | 2 |

Each implementer also reads the header above the first wave (about 250 lines); every wave stays far
under the ~900-line ceiling.

Expected dispatches: six implementers, two correctness seats, at most two re-reviews.

---

## Task 0: Re-measure after #158 merges (controller)

- [ ] **Step 1:** `git merge origin/next` into this branch once the controller says #158 has merged.
  Expected: a clean merge (this branch carries only this plan).
- [ ] **Step 2:** re-run the measurements: the importers of every deleted module (an `ast` walk over
  `src/`, `scripts/`, `examples/` and `tests/`, matching `stayfixed.<module>` and relative forms),
  the mutation counts in the table above (entries by `file`, and entries whose `reddens` all fall in
  deleted test files), and the pinned crossings in `tests/boundaries/test_delivery.py` that this lane
  removes. Expected from #158 as reviewed: `PACK_TO_DELIVERY` rows `guards/commands.py →
  stayfixed.hints.api {dirty_count}` (Task 3), `project/uninstall.py → stayfixed.attach.api {detach}`
  (Task 7), `prove/run.py → stayfixed.hints.api` (Task 13); `DELIVERY_TO_PACK` rows
  `memory/graph.py → stayfixed.ledger.api {bug_register}` (Task 1) and the three `hints/hygiene.py
  → stayfixed.profiles.*` rows (Task 15); `CORE_TO_PACK` rows `harnesses.py` and
  `scaffold/engine.py → stayfixed.profiles` (Task 16); `PACK_PACKAGES` losing `assess` (Task 5),
  `prove` (Task 13) and `profiles` (Task 16); `DYNAMIC_IMPORTERS`' `profiles/__init__.py` row
  (Task 16).
- [ ] **Step 3:** settle `trust`'s side. `trust/commands.py` is the area's only discovered module, so
  Task 2 leaves `trust` a package that discovery does not find, and the partition test's
  "every listed area names a discovered one" rule then refuses `trust` in `DELIVERY_AREAS`. Task 2
  removes `trust` from `DELIVERY_AREAS` (it becomes core, which `memory` and `setup` may import) and
  re-anchors any entry that used `trust` as its sample area (#158 declares "trust drops out of every
  side") on another delivery area. If #158 placed `trust` differently, amend Task 2 here.
- [ ] **Step 4:** check the lifecycle matrix rows against the tree, amend this plan where the
  numbers or rows moved, commit `docs(plans): restructure cuts re-measured after the hints move`.

**Re-measured after #158 (2026-11-02, `next` at its merge of #158):** the importers, the mutation
counts and the pinned rows above hold as written (2,498 entries; 243 on pull request 1's deleted
files; 51 surviving-code entries lose every reddening test, one of them now on `roots.py`, the core
module `guards/roots.py` moved to). `areas.py` lists one name per line, and
`test_every_area_is_on_exactly_one_side` holds `(DELIVERY_AREAS | CORE_AREAS) - discovered areas`
to the empty set, so Task 2 removes the line `"trust",` from `DELIVERY_AREAS`; the entry "trust
drops out of every side", whose `before` is that line, is renamed "setup drops out of every side"
and re-anchored on the line `"setup",` with the same test.

---

## Wave A — Tasks 1–3: dead commands

### Task 1: `memory refs` with the note graph, and `memory fit`

**Files:**
- Delete: `src/stayfixed/memory/graph.py`, `src/stayfixed/memory/refs.py`,
  `tests/memory/test_graph.py`, `tests/memory/test_refs.py`
- Modify: `src/stayfixed/memory/commands.py` (`run_refs`, `run_doctor_bundles` and their
  `register` rows), `tests/memory/test_commands.py`, `tests/boundaries/test_delivery.py`,
  `mutations/records.toml`, `docs/cli.md` (`stayfixed memory fit`, `stayfixed memory refs`),
  `README.md`, `skills/memory-sweep/` (its `refs` and `fit` mentions)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `stayfixed memory` with `index`, `session-context`, `inventory`, `promote`. `fit()` in
  `memory/bundles.py` stays: `memory/doctor.py`'s rows read it.

- [ ] **Step 1: Red.** Delete the two modules and the two command functions with their `register`
  rows. Run `uv run pytest -n auto tests/memory tests/test_documents.py tests/skills
  tests/boundaries tests/scripts/test_mutation_oracle.py -q`. Expected: failures naming the stale
  documentation rows, the skill invocations, the pinned `memory/graph.py` crossing, and the entries
  whose `file` or `reddens` is gone.
- [ ] **Step 2:** delete `tests/memory/test_graph.py`, `test_refs.py` and the `refs`/`fit` cases of
  `tests/memory/test_commands.py`; the crossing row; the `docs/cli.md` sections and `README.md` rows;
  the skill text (a sweep reads the inventory; it no longer runs `refs`). Mutation entries: delete
  those on deleted code; for the six on surviving `memory/commands.py` and two on `memory/store.py`
  whose only tests are deleted, follow the global rule.
- [ ] **Step 3:** search `examples/`, `scripts/`, `skills/`, `.github/` and `src/` for the strings
  `"refs"` and `"fit"` next to `memory` in an argv list. Expected: no hit.
- [ ] **Step 4: Green.** The Step 1 command passes; then
  `uv run python scripts/mutation_oracle.py "<the re-anchored entries' names>"` after the commit.
- [ ] **Step 5: Commit** `refactor(memory): drop memory refs, the note graph and memory fit`.

### Task 2: `trust list` and `trust revoke`

**Files:**
- Delete: `src/stayfixed/trust/commands.py`, `tests/trust/test_commands.py`
- Modify: `src/stayfixed/trust/__init__.py` and `api.py` docstrings, `src/stayfixed/memory/reviewed.py`
  (its docstring names `trust list` and `trust revoke`), `src/stayfixed/areas.py` and
  `tests/boundaries/test_delivery.py` per Task 0 Step 3, `CONTRIBUTING.md` ("Areas"), `docs/cli.md`,
  `README.md`, `mutations/core.toml`

**Interfaces:**
- Consumes: Task 0's ruling on `trust`'s side.
- Produces: `stayfixed.trust.api` unchanged for `memory/reviewed.py` and `setup`; no `trust`
  command group.

- [ ] **Step 1: Red.** Delete the module; run `uv run pytest -n auto tests/trust tests/memory
  tests/boundaries tests/test_documents.py tests/test_cli.py -q`. Expected: the documentation rows
  for `trust list`/`revoke` and the partition test's unlisted-or-unknown area.
- [ ] **Step 2:** the docstrings: `memory/reviewed.py` says "`memory promote` writes the entry, and
  a promoted note is withdrawn by editing it, which changes its digest, or by deleting it"; nothing
  else names `trust list` or `trust revoke`. The `docs/cli.md` sections go, and so do `README.md`'s
  rows. `CONTRIBUTING.md`'s list of areas drops `trust` and its "`stayfixed trust` commands over it".
- [ ] **Step 3: Green** as Step 1, and the oracle on the five entries' replacements, if any.
- [ ] **Step 4: Commit** `refactor(trust): drop trust list and trust revoke`.

### Task 3: the `test hygiene` command

**Files:**
- Modify: `src/stayfixed/guards/commands.py` (`run_test_hygiene` and its `register` rows; the `test`
  group keeps `attribute`), `tests/guards/test_commands.py`, `tests/boundaries/test_delivery.py`
  (the `guards/commands.py → stayfixed.hints.api` row), `mutations/guards.toml`, `docs/cli.md`
  (`stayfixed test hygiene`), `README.md`, any skill that names it

**Interfaces:**
- Consumes: nothing.
- Produces: `stayfixed test attribute` unchanged. The red-run note in `hints` is untouched.

- [ ] **Step 1: Red.** Delete the function and its rows; run `uv run pytest -n auto tests/guards
  tests/hints tests/boundaries tests/test_documents.py tests/skills -q`.
- [ ] **Step 2:** delete the cases, the crossing row, the section and the rows. If
  `guards/commands.py` keeps a `profiles` import only for `test hygiene`, it goes too, and with it
  any `CORE_TO_PACK`/`PACK` row #158 pinned for it.
- [ ] **Step 3: Green**, oracle on what was re-anchored.
- [ ] **Step 4: Commit** `refactor(guards): drop the test hygiene command; the red-run note stays`.

---

## Wave B — Tasks 4–6: the gate ratchet

### Task 4: the reusable workflow, its smoke callers, and the demo's gate steps

**Files:**
- Delete: `.github/workflows/check.yml`, `.github/workflows/smoke-release.yml`
- Modify: `.github/workflows/smoke.yml` (the `same-repository-form` job, its `needs` and the
  comments that name `check.yml`), `.github/workflows/ci.yml` (any path filter or comment naming
  `check.yml`), `tests/test_check_workflow.py` → renamed `tests/test_workflows.py` (its `check.yml`
  cases go: the module docstring, `GATES`, `JUDGE`, `CUSTOM`, `PROOF`, `BASE`, `LOOSENED`,
  `OVER_BUDGET`, `STAYFIXED_INVOCATIONS`, `PLATFORM_ARGUMENTS`, `GATE_ARGUMENTS`, `CHECKOUT_STEP` and
  the cases that read `check.yml`; the cases on `smoke.yml`, `ci.yml`, `release.yml` and
  `RELEASING.md` stay), every `reddens` id naming the old path (`tests/test_check_workflow.py::` →
  `tests/test_workflows.py::`), `tests/test_ci_scope.py` and `scripts/ci_scope.py` if they name
  `check.yml`, `examples/demo/demo.py` (act 5), `examples/demo/README.md`, `docs/cli.md` ("The
  reusable workflow"), `README.md`, `RELEASING.md` (the `check.yml` steps and the
  `smoke-release.yml` run), `SECURITY.md`, `CONTRIBUTING.md`

**Interfaces:**
- Consumes: nothing. It runs first in the wave so that no surviving test or job calls `gate` once
  Task 5 deletes it.
- Produces: `tests/test_workflows.py`, the holder of `ci.yml`, `smoke.yml` and `release.yml`'s
  shape. Demo act 5 = "a fixed bug's regression fails the change that brings it back", run with
  `bugs regressions` alone.

- [ ] **Step 1: Red.** Delete the two workflow files; run
  `uv run pytest -n auto tests/test_check_workflow.py tests/test_ci_scope.py tests/test_documents.py -q`.
  Expected: the `check.yml` cases fail on a missing file.
- [ ] **Step 2:** delete those cases and constants, rename the file with `git mv`, and rewrite every
  `reddens` id and every citation of the old path (`grep -rn "test_check_workflow" .`). The
  `release.yml` (29), `smoke.yml` (17), `ci.yml` (5), `RELEASING.md` (4), `publish_plugin.py` (3) and
  `plugin_tree.py` (2) entries keep their tests under the new path.
- [ ] **Step 3:** `smoke.yml` loses `same-repository-form`; its `changes` gate and any job list
  that named it follow.
- [ ] **Step 4: the demo.** Act 5's configuration loses `[gates]` (it keeps `[stayfixed] version` and
  `[project] name`); after the fixed bug's `bugs regressions` passes on `main`, the act switches to
  `change`, breaks `total.py` and runs `bugs regressions --json` again: exit `1`, the entry's
  verdict not `proved`. The `adopt promote` and `gate` calls go. Act 7 still finds the fixture on
  `change`. Run `python3 -I examples/demo/demo.py "$PWD/.venv/bin/stayfixed"` under a scratch
  `HOME` and paste its act lines. Expected: every act passes.
- [ ] **Step 5:** the documents. `RELEASING.md`, `SECURITY.md` and `CONTRIBUTING.md` lose every line
  about the reusable workflow and the release smoke of it; `README.md` and `docs/cli.md` lose the
  workflow's section and rows.
- [ ] **Step 6: Green** on the Step 1 command with the new file name, `tests/scripts`, and the oracle
  on `"<pattern for the renamed ids' entries>"`.
- [ ] **Step 7: Commit** `ci: drop the reusable gate workflow and its smoke callers`.

### Task 5: the `assess` area (`assess`, `gate`, `adopt promote`)

**Files:**
- Delete: `src/stayfixed/assess/` (11 modules), `tests/assess/` (21 files), `skills/adopt/`,
  `mutations/assess.toml`
- Modify: `src/stayfixed/areas.py` and `tests/boundaries/test_delivery.py` (`PACK_PACKAGES` loses
  `assess`), `tests/boundaries/test_api_surface.py` and `tests/boundaries/test_discovery.py` if they
  count areas, `tests/test_surfaces.py`, `tests/skills/test_skills.py` (its named-skill subsets),
  `CONTRIBUTING.md` ("Areas", "Configuration", "Named caps"), `docs/cli.md`, `README.md`,
  `docs/methodology/principles.md`, `skills/init/`, `skills/doctor/`, `skills/run-correctness-audit/`,
  `skills/sweep-defect-class/`, `skills/setup/` where they name `assess`, `gate` or `adopt`;
  `harnesses.py`'s and `CONTRIBUTING.md`'s sentence that `assess` reads every value's settings
  files

**Interfaces:**
- Consumes: nothing.
- Produces: no `assess`, `gate` or `adopt` command; `project.api`'s `rewrite_owned`, `ASSESSMENT` and
  `CI_WORKFLOW` lose their last consumer outside `project` (Tasks 5 and 7 delete them).

- [ ] **Step 1: Red.** Delete the area and its tests; run `uv run pytest -n auto -q -x
  --deselect tests/assess`. Expected: failures in the documentation, skill, surface and boundary
  tests, and in the mutation-soundness test for every entry whose `reddens` named `tests/assess/`.
- [ ] **Step 2:** delete the skill and every documentation row, section and sentence naming the three
  commands. `docs/cli.md` loses `stayfixed assess`, `stayfixed gate` and `stayfixed adopt promote`.
- [ ] **Step 3: Mutation entries.** `mutations/assess.toml` goes whole. Then, for the entries on
  surviving code whose `reddens` named `tests/assess/` (among them `committed.py` 9, `processes.py`
  5, `docs/hygiene.py` 2, `docs/trail.py` 2, and one each in `guards/roots.py`, `guards/commit.py`,
  `ledger/check.py`, `docs/plans.py`, `ledger/commands.py`), apply the global rule. Expected surviving
  candidates: `tests/test_committed.py`-style tests of each module; where a module's only test was a
  gate run, the entry is listed for the owner.
- [ ] **Step 4:** search for callers as string tokens: `grep -rnE "\"(assess|gate|adopt)\"|'(assess|gate|adopt)'|-m stayfixed (assess|gate|adopt)" examples scripts .github src tests skills`.
  Expected: no hit (Task 4 removed the workflow and the demo's calls).
- [ ] **Step 5: Green** on the full suite.
- [ ] **Step 6: Commit** `refactor(assess): drop assess, gate and adopt promote`.

### Task 6: the keys `[stayfixed] enforced`, `[gates.*]` and `[ci]`; `doctor`'s `ci-ref`; `bugs regressions --timeout`

**Files:**
- Modify: `src/stayfixed/config/schema.py` (`Stayfixed.enforced`, `Ci`, `CustomGate`, `Gates`,
  `Config.ci`, `Config.gates`, and constants only they read), `config/loader.py`, `config/classes.py`
  (their rows), `config/reading.py` comments, `src/stayfixed/presets/recommended.toml`
  (`enforced`, `[ci]`, `[gates]`), `src/stayfixed/doctor/checks.py` (`_ci_ref`,
  `_ref_is_released`, `_pinned_refs`, `WORKFLOW_MAX_BYTES` and whatever only they read; the
  `CHECKS` row), `src/stayfixed/project/{templates,commands,questions,init,layout,api}.py` (the
  caller workflow: `CI_WORKFLOW`, `CI_ARTIFACT`, `CI_REF`, `NO_TAG`, `NOT_ASKED`, `UVX_LATER`,
  `--no-ci`, the `ci.mode` question, the `[ci] ref` resolution), `src/stayfixed/release/` only where
  `init`'s pin was its last caller (keep what `doctor`'s `versions` row or `scripts/` read),
  `src/stayfixed/ledger/regressions.py` and `ledger/commands.py`, the tests of each, `mutations/*`,
  `docs/cli.md`, `README.md` (the doctor count, twice), `skills/doctor/SKILL.md` ("fourteen"),
  `.github/workflows/smoke.yml` (`assert len(rows) == 14` and its comment), `CONTRIBUTING.md`
  ("Named caps": the sentence on `[gates] custom_timeout_seconds`; the `WORKFLOW_MAX_BYTES`
  example), the fixtures `tests/fixtures/{smoke-project,ledger/project,hostile-project}/stayfixed.toml`
- Delete: `src/stayfixed/templates/project/stayfixed.yml`

**Interfaces:**
- Consumes: Task 5 (no reader of `config.gates` or `config.ci` is left in `assess`).
- Produces: `Config` without `ci` and `gates`; `Stayfixed` without `enforced`.
  `stayfixed bugs regressions [--timeout SECONDS]`, default `600`, the value `[gates]
  custom_timeout_seconds` had in the preset; in `ledger/regressions.py`:
  `DEFAULT_TIMEOUT_SECONDS = 600` (a named cap with its comment) and
  `regressions(root: Path, config: Config, *, timeout: int, echo: TextIO) -> list[tuple[Entry, Receipt]]`.

- [ ] **Step 1: Red.** Write `tests/ledger/test_regressions.py::test_the_timeout_is_the_option_or_ten_minutes`:
  through the real parser, `bugs regressions` with no option hands `prove` a bound of `600`, and
  with `--timeout 5` a bound of `5`; a non-positive or non-integer value is refused by the parser
  (`argparse` type, exit 2). Run it. Expected: FAIL (no such option).
- [ ] **Step 2:** add the option and the constant; `regressions` takes `timeout`. Run the test.
  Expected: PASS. This and the `upgrading` fragment are the only lines this task adds.
- [ ] **Step 3:** delete the schema fields, their loader branches and class rows, the preset's keys,
  `doctor`'s `ci-ref` row and its helpers, the caller-workflow template and every `init` branch that
  renders or asks about it. The loader's integer-limit and range cases in
  `tests/config/test_loader.py` that use `custom_timeout_seconds` move to a surviving integer key
  (a `[budgets]` or `[native_caps]` key), keeping their assertions; the entries that name them follow
  their new ids. `tests/config/test_classes.py`'s rows for the deleted keys go.
- [ ] **Step 4:** the count: `doctor` reports thirteen rows. Edit `README.md` (twice),
  `docs/cli.md`, `skills/doctor/SKILL.md` and `smoke.yml` (`== 13`, and its comment's "fourteen").
  Search `grep -rn "fourteen\|== 14\|14 checks" README.md docs skills .github src tests`; every hit
  that counts `doctor`'s rows changes.
- [ ] **Step 5:** a `stayfixed.toml` with a removed key: run
  `uv run pytest tests/config/test_loader.py -q -k unknown` and read that an unknown key in
  `[stayfixed]` and an unknown table are refused by name. Expected: the existing cases pass
  unchanged; no new message is written.
- [ ] **Step 6: Green** on `tests/config tests/doctor tests/ledger tests/project tests/test_documents.py
  tests/skills -q`, then the oracle on the moved and re-anchored entries.
- [ ] **Step 7: Commit** `refactor(config): drop enforced, [gates] and [ci], doctor's ci-ref row and
  init's caller workflow; bugs regressions takes --timeout`.

---

## Wave C — Tasks 7–9: the heavy scaffold

### Task 7: `upgrade`, `uninstall` and `rewrite_owned`

**Files:**
- Delete: `src/stayfixed/project/upgrade.py`, `uninstall.py`, `rewrite.py`;
  `tests/project/test_{upgrade,uninstall,rewrite,footprint_commands,round_trip,journey}.py`;
  `skills/upgrade/`, `skills/uninstall/`
- Modify: `src/stayfixed/project/commands.py` (the two `register` rows and `_judging` if only they use
  it), `project/api.py` (`rewrite_owned`, `ASSESSMENT`), `project/footprint.py` (the upgrade and
  uninstall policy; what `init` uses stays), `src/stayfixed/scaffold/*` only where a branch had no
  caller but the deleted commands, `tests/boundaries/test_delivery.py` (the
  `project/uninstall.py → stayfixed.attach.api {detach}` row), `tests/project/test_footprint_invariant.py`
  and `test_planning_seam.py` (their `upgrade`/`uninstall` arms), `tests/skills/test_skills.py`
  (`{"init", "upgrade", "uninstall", …}` subset), `CONTRIBUTING.md` ("Enumerated writes": the
  `uninstall` exception goes), `docs/cli.md`, `README.md`, `skills/init/`, `skills/doctor/`,
  `mutations/project.toml`, `mutations/scaffold.toml`

**Interfaces:**
- Consumes: Task 5 (no `assess` import of `project.api`).
- Produces: `project.api.__all__ == ["PROJECT_FILES", "Prepared", "project_templates"]` (Task 8 may
  shrink it further).

- [ ] **Step 1: Red.** Delete the modules, tests and skills; run
  `uv run pytest -n auto tests/project tests/scaffold tests/boundaries tests/skills tests/test_documents.py tests/test_surfaces.py -q`.
- [ ] **Step 2:** delete the crossing row and every document line naming either command.
  `CONTRIBUTING.md`'s removal rule names three exceptions after this.
- [ ] **Step 3: Mutation entries.** The scaffold's entries whose only tests were the upgrade and
  uninstall suites (`scaffold/entries.py` 7, `scaffold/engine.py` 4, `scaffold/manifest.py` 2,
  `project/footprint.py` 4, `project/commands.py` 1, `project/templates.py` 1, `config/layout.py` 1):
  first ask whether the line they mutate still has a caller. A branch only `upgrade` or `uninstall`
  reached (a retire, a keep-modified, a remove verb) is deleted with its entry, and that deletion is
  this lane's; a branch `init`, `overlay create` or `overlay upgrade` still reaches is re-anchored on
  `tests/scaffold/` or `tests/overlay/` by the oracle, or listed for the owner.
- [ ] **Step 4: Green** on the Step 1 command; oracle on the re-anchored entries.
- [ ] **Step 5: Commit** `refactor(project): drop upgrade, uninstall and rewrite_owned`.

### Task 8: a minimal `init`

**Files:**
- Delete: `src/stayfixed/templates/project/{documentation.md,adr-template.md,bug-reports-runbook.md,audits-readme.md,roadmap-history.md,gitkeep,agents-skeleton.md,agents-region.md,claude.md}`;
  `tests/project/test_gates.py` if Task 6 left it
- Modify: `src/stayfixed/project/{layout,templates,init,commands,questions,detect,ignored,footprint,api}.py`,
  `src/stayfixed/config/{schema,loader,classes,layout}.py` (the `[artifacts] local` key, whose only
  eligible files are templates this task deletes), `scripts/check_artifacts.py` (it reads
  `PROJECT_FILES`), the remaining `tests/project/*`, `tests/scripts/test_check_artifacts.py`,
  `tests/fixtures/smoke-project/` (its manifest records the old footprint), `docs/cli.md` (both
  `init` sections), `README.md` ("What it writes, and where", "Quickstart"), `skills/init/`,
  `mutations/project.toml`

**Interfaces:**
- Consumes: Tasks 6 and 7.
- Produces: `init --yes` writes, under the configured `[paths]`: `stayfixed.toml` (write-once, as
  today), `docs/roadmap.md` (the trail markers), `docs/trail.toml`, and the generated bug index
  `docs/bug-reports.md` (computed by `render_index`, as today; kept because `bugs index --check` fails
  without it), recorded in `.stayfixed/manifest.json`. `PROJECT_FILES == ("roadmap.md", "trail.toml")`.
  Answer flags kept: `--name`, `--base-branch`, `--agent`, `--profile` (until Task 16),
  `--memory-mode`, `--attribution-check`, `--commit-type`. Gone: `--local`, `--no-ci` (Task 6).

- [ ] **Step 1: Red.** Write `tests/project/test_init.py::test_a_fresh_init_leaves_trail_and_ledger_checks_green`:
  on an empty git repository under `tmp_path`, `init --yes` through the real parser, then
  `docs trail --check`, `bugs index --check` and `bugs check` each exit `0`, and `git ls-files
  --others` lists exactly `stayfixed.toml`, `docs/roadmap.md`, `docs/trail.toml`,
  `docs/bug-reports.md` and `.stayfixed/manifest.json`. Run it. Expected: FAIL on the file list
  (today's footprint writes thirteen files).
- [ ] **Step 2:** delete the nine templates, their `Template` builders, their `[paths]`-derived
  file names that nothing else reads, `LOCAL_ELIGIBLE`, `SHARED_FILE`, `ONE_FILE`, the `AGENTS.md`
  region and `CLAUDE.md` pointer logic, the `.gitignore` region artifact, the `--local` answer and
  question, and the `[artifacts] local` key with its class row. `[paths]` keys stay: `docs check`,
  `plan check` and the ledger read them. `scaffold/local.py` stays only if `overlay` or the engine
  still imports it after this; otherwise it goes with its tests and entries.
- [ ] **Step 3:** shrink the remaining `tests/project/*` to what `init` still does: delete the cases
  of deleted artifacts and answers, keep every case of the write-once document, the engine passes,
  the refusals and the containment walk. The smoke fixture (`tests/fixtures/smoke-project/`) keeps
  its files, which are now the project's own: its `.stayfixed/manifest.json` drops the records of
  artifacts `init` no longer builds, so `tests/project/test_fixture.py`'s claims (planning creates
  nothing, every record is recognised) hold for the four; its `README.md` stops saying it exists for
  the reusable workflow (the installed-plugin smoke and `scripts/smoke_hooks.py` still use it). Run
  the Step 1 test. Expected: PASS.
- [ ] **Step 4:** `docs/cli.md`'s `init` sections and `README.md` list the four files; `init`'s
  section says `docs check` will name a missing `AGENTS.md` until the project writes one.
  `skills/init/` follows.
- [ ] **Step 5: Mutation entries** on the deleted artifacts go; the 150 entries reddened from the
  trimmed `tests/project/` files are checked id by id by `test_every_declared_entry_is_sound_before_any_run`,
  and an entry that loses all its ids follows the global rule.
- [ ] **Step 6: Green** on `tests/project tests/scaffold tests/scripts tests/config tests/test_documents.py
  tests/test_fixtures.py tests/skills -q`; oracle on the touched entries (pattern `init` and
  `template`, narrowed to their names).
- [ ] **Step 7: Commit** `refactor(project): init writes stayfixed.toml, the roadmap, the trail and
  the bug index`.

### Task 9: what lost its last caller in wave C

**Files:** whatever Step 1 finds; expected candidates `project/detect.py`, `project/questions.py`,
`project/ignored.py`, `scaffold/regions.py`, `harnesses.py`'s agent-settings files list, `release/pins.py`.

**Interfaces:**
- Consumes: Tasks 1–8.
- Produces: no function, constant or module under `src/` that only tests reach.

- [ ] **Step 1:** list every top-level name under `src/stayfixed/` that no module under `src/`,
  `scripts/` or `examples/` reaches any more (an `ast` walk over names and attribute reads, the
  `api.py` re-exports counted as no use), restricted to modules this lane touched or that imported a
  deleted one. Paste the list.
- [ ] **Step 2:** delete each name with its tests and entries, unless a surviving command reaches it
  through discovery or `importlib.resources` (say which).
- [ ] **Step 3: Green** on the full suite. Commit `refactor: drop what the cuts left without a caller`.

---

## Wave D — Tasks 10–11: re-anchor, text, open pull request 1

### Task 10: the changelog, the remaining text, and the entries listed for the owner

**Files:** `changelog.d/`, `README.md`, `docs/cli.md`, `CONTRIBUTING.md`, `docs/methodology/principles.md`,
`skills/README.md`

- [ ] **Step 1:** one fragment `changelog.d/+restructure-cuts.upgrading.md`: the removed commands
  (`assess`, `gate`, `adopt promote`, `upgrade`, `uninstall`, `memory refs`, `memory fit`,
  `trust list`, `trust revoke`, `test hygiene`), the removed keys (`[stayfixed] enforced`, `[gates]`,
  `[ci]`, `[artifacts] local`), the reusable workflow, what `init` now writes, `bugs regressions
  --timeout`, and what to delete from an existing `stayfixed.toml`. Delete the unreleased fragments
  that describe only removed features (`+adoption-key.upgrading.md`, `+gate-platform-flags.change.md`,
  `+gate-named-repository.fix.md`); edit `+back-compat.upgrading.md` and `+demo-fixture.feature.md`
  where they name them.
- [ ] **Step 2:** one search over every tracked file outside `docs/plans/` and `CHANGELOG.md`:
  `git grep -nE "stayfixed (assess|gate|adopt|upgrade|uninstall)|memory (refs|fit)|trust (list|revoke)|test hygiene|check\.yml|smoke-release|\benforced\b|\[gates|\[ci\]|ci-ref|custom_timeout|artifacts\] local"`.
  Expected: only the `upgrading` fragment. Paste it.
- [ ] **Step 3:** collect every entry the waves listed for the owner (name and `before` line) into
  the wave report; delete nothing more.
- [ ] **Step 4: Commit** `docs: say what the cuts removed and what an existing stayfixed.toml drops`.

### Task 11: verify and open pull request 1 (controller with the wave D implementer)

- [ ] **Step 1:** `git merge origin/next`; resolve hot spots (`docs/cli.md`, `README.md`,
  `changelog.d/`, `config/*`, `mutations/core.toml`, `tests/boundaries/test_delivery.py`) by keeping
  both sides' surviving lines.
- [ ] **Step 2:** the full verification of the execution contract, item 5; then the oracle on every
  entry this pull request added, moved or re-anchored (`uv run python scripts/mutation_oracle.py
  "<names>"`). Paste both.
- [ ] **Step 3:** print the net size per area.
- [ ] **Step 4:** push and open the pull request into `next` with `gh pr create --base next`, body:
  "What this removes and what is lost", the net size, the follow-ups. Watch
  `gh run watch <id> --exit-status`; fix red; stop. The controller reviews and merges.
- [ ] **Step 5:** report to the controller: the pull request, the net size, the entries listed for
  the owner, and the callers list outside this repository (see "Report").

---

## Pull request 2 (after lane 6's runner table merges into `next`)

Waves E and F are planned at the level the tree allows today. **Task 12 re-measures and rewrites
them** against what the runner table and pull request 1 changed, before wave E is dispatched.

### Task 12: re-measure for pull request 2 (controller)

- [ ] **Step 1:** `git merge origin/next` after the controller says lane 6's first pull request (the
  test-runner table in `hints`) has merged.
- [ ] **Step 2:** re-run Task 0's measurements for `prove`, `profiles`, `examples/stop-hook`, the
  demo, `ci.yml`'s `runners` and `demo` jobs and their entries; read the runner table's interface
  (its module, the name of its lookup, what it returns for a launch).
- [ ] **Step 3:** rewrite waves E and F below with the measured files, crossings and interfaces;
  commit `docs(plans): restructure cuts, pull request 2 re-measured`.

## Wave E — Tasks 13–14: `prove`

### Task 13: `bugs regressions` without `prove`, then `prove`

**Files:**
- Modify: `src/stayfixed/ledger/regressions.py`, `ledger/commands.py`, `tests/ledger/test_regressions.py`,
  `docs/cli.md` (`bugs regressions`: verdict by exit code)
- Delete: `src/stayfixed/prove/`, `tests/prove/`, `tests/fixtures/prove/`, `tests/test_runners_job.py`,
  `ci.yml`'s `runners` job and the `-m runners` marker if nothing else uses it,
  `CONTRIBUTING.md`'s paragraph on the real runners, `README.md` and `docs/cli.md` rows, the crossing
  `prove/run.py → stayfixed.hints.api`, `PACK_PACKAGES`' `prove`, `mutations/core.toml`'s `prove`
  entries

**Interfaces:**
- Consumes: pull request 1's `regressions(root, config, *, timeout, echo)`; the product's process
  runner (`stayfixed.processes.run`, as Task 12 reads it).
- Produces: `bugs regressions` runs each fixed entry's `regression` argv from the project root
  through `processes.run` with `timeout`, and reports per entry `verdict` = `passed`, `failed`,
  `timed-out` or `not-run`; it exits `1` when any entry did not pass. A run an interrupt ended is
  the last, as today. JSON keys renamed to match (`not_passed` for `not_proved`).

- [ ] **Step 1: Red.** Rewrite `tests/ledger/test_regressions.py`'s verdict cases for the exit-code
  verdicts (a passing argv, a failing argv, a timed-out argv, an interrupted run stops the loop).
  Run them. Expected: FAIL (the receipt is still `prove`'s).
- [ ] **Step 2:** implement on `processes.run`; run them. Expected: PASS.
- [ ] **Step 3:** delete `prove` with everything listed; search argv callers
  (`grep -rnE "\"prove\"|'prove'|stayfixed prove" examples scripts .github src tests skills`).
- [ ] **Step 4: Green**, oracle on `regressions`. Commit
  `refactor(prove): drop prove; bugs regressions answers by exit code`.

### Task 14: the demo and the `Stop`-hook example

**Files:**
- Delete: `examples/stop-hook/`, `tests/test_stop_hook_recipe.py`, demo acts 1–4 and 7
  (`act_proved`, `act_not_recognised`, `act_all_skipped`, `act_forging`, `act_stop_hook`, `_stop`
  and their fixture files)
- Modify: `examples/demo/demo.py` (acts 5 and 6 stay; act 5's fields follow Task 13's keys),
  `examples/demo/README.md`, `ci.yml`'s `demo` job (drops `--require-claude` if only act 7 needed
  it), `README.md`, `docs/cli.md`, `mutations/repository.toml`

- [ ] **Step 1:** delete; run the demo under a scratch `HOME`; paste its act lines. Expected: two
  acts, both pass.
- [ ] **Step 2: Green**, commit `refactor(examples): the demo keeps the regression and attach acts`.

## Wave F — Tasks 15–17: `profiles`

### Task 15: the red-run note on the runner table

**Files:** `src/stayfixed/hints/hygiene.py`, its tests, `tests/boundaries/test_delivery.py` (the
three `hints/hygiene.py → stayfixed.profiles.*` rows), `mutations/*`

- [ ] **Step 1: Red.** The red-run note's tests name a runner by the table's program names
  (pytest, `uv run pytest`, `go test`, `npx jest`, …); run them against today's code. Expected: FAIL
  where a stack's hint came from `profiles`.
- [ ] **Step 2:** re-point the note at the table; delete what only the profile hints said. The
  `PostToolUse` note stays a convenience that never refuses.
- [ ] **Step 3: Green**; oracle on the note's entries (the 3 `hygiene.py` entries that lose their
  only test in this pull request are re-anchored here). Commit
  `refactor(hints): the red-run note reads the runner table`.

### Task 16: the `profiles` package and `[stayfixed] profile`

**Files:**
- Delete: `src/stayfixed/profiles/`, `tests/profiles/`, `tests/test_language_neutral.py`'s pardons
  that name a profile (the test stays)
- Modify: `config/schema.py` (`Stayfixed.profile`), `config/loader.py`, `config/classes.py`,
  `config/layout.py` (`rules_file`), `harnesses.py` (the `TYPE_CHECKING` import and the rendering of
  a profile's rules), `scaffold/engine.py` (`validate_sources`' profile check), `project/*` (`--profile`),
  `areas.py`, `tests/boundaries/test_delivery.py` (`PACK_PACKAGES` loses `profiles`; the
  `CORE_TO_PACK` rows; `DYNAMIC_IMPORTERS`' row), `scripts/check_artifacts.py` (`WHEEL_MUST`'s
  profile files), `CONTRIBUTING.md` (the profiles paragraph), `docs/cli.md`, `README.md`,
  `skills/init/`, `mutations/project.toml` (119 entries)

- [ ] **Step 1: Red.** Delete the package; run the full suite with `-x`. Expected: every importer
  named above fails.
- [ ] **Step 2:** delete each importer's profile branch; `uvrun` and anything else Task 17 finds.
- [ ] **Step 3: Green**, oracle on re-anchored entries. Commit
  `refactor(profiles): drop the stack profiles and [stayfixed] profile`.

### Task 17: last importers, text, open pull request 2

- [ ] **Step 1:** Task 9's walk again, for what pull request 2 left without a caller (`hints/uvrun.py`
  if only `prove` used it, `guards/roots.py` helpers, `fsops` helpers, `cli.py` branches). Delete
  with tests and entries.
- [ ] **Step 2:** an `upgrading` fragment for `prove`, `[stayfixed] profile` and `bugs regressions`'
  new verdicts; Task 10 Step 2's search with `prove|profile`.
- [ ] **Step 3:** Task 11's Steps 1–5 for pull request 2.

---

## Report (to the controller, never in a pull request body)

After each pull request: its link and CI run; the net size per area; the entries listed for the
owner; and the callers outside this repository of every deleted command or key, searched as string
tokens (argv lists, workflow `uses:` lines, configuration keys) in the owner's overlay and other
repositories. That list is kept in the restructure's shared notes folder, never in this repository.
