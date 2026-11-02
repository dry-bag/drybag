# Wave 8, core-cut — a language-neutral core behind a declared delivery boundary: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.
>
> **The wave is the dispatch unit, not the task.** Waves are lettered (`A`, `B`, …) and own a
> run of the continuously numbered tasks. One implementer, one review round and one reviewer
> per **dispatched** wave; inside a wave every task keeps its own failing test, verification
> and commit. Do not dispatch one subagent per task.
>
> **Wave L is not dispatched.** It measures, runs the final review seats, and hands the release
> to the owner; the controller runs it with the owner, step by step.
>
> **Three lanes, six pull requests.** Each lane runs in its own worktree and session; inside a
> lane, waves run in order and each pull request merges before the lane's next one branches
> from `dev`. The launch graph below draws the edges between lanes. Every branch rebases on
> `dev` before every push.

**Goal:** cut stayfixed to a sharp, language-neutral core — methodology gates and the records
they check — with the private-layer code held behind a declared delivery boundary that a test
enforces, every harness reached through one two-sided adapter value with a stated capability
tier, and the surface the migration journal showed nobody needs removed; then measure the cut
and hand `0.3.0` to the release.

**Architecture:** no package moves. `memory`, `overlay` and `attach` are named as the delivery
areas in `areas.py`, and `tests/test_areas.py` holds that no core module imports one, with a
single pinned crossing (`setup --overlay`) until wave 9. The twelve imports that cross today are
cut by moving generic helpers into core modules and by two discovery conventions in the style
the CLI and the hook registry already use: an area may ship `doctor.py`, and a profile may ship
code beside its data. The harness registry grows from a list of settings paths into the adapter:
one value per harness owns its positive detection, the name of its project-root variable, the
shape of its output and its capability tiers, which the README mirrors and `doctor` reports;
every payload is read one way, because the detected harness is one a repository can choose. The ledger engine takes a `Register` value instead of reading the bug
ledger's configuration in forty places, so wave 9 adds a debt register without touching it. The
release tooling leaves the shipped CLI for a repository script.

**Tech Stack:** Python ≥ 3.11 standard library at runtime; `uv`, pytest (`-n auto`), ruff, mypy,
the mutation oracle (`scripts/mutation_oracle.py`), towncrier fragments in `changelog.d/`.

**Spec:** the agent-harness extraction design, in a private repository this one cannot link to —
§15.2 (package `core-cut`), §15.5 (the re-plan and the freeze for waves 7 and 8), §15.6 (the
core-cut decisions this plan implements, settled with the owner on 2026-10-03 and 2026-10-04),
§5.3 and §10 (the hooks core and the cross-harness contract), §9.5 (session-context bundles).
Licensed contract changes (§15.5, "Contracts"): **C4**, for the harness-adapter boundary, and
**C5**, restated from the shipped CLI after the cut. C1, C2, C3 and C6 are not edited: no
configuration key, path, note-schema field or version rule changes; a task that finds one
insufficient stops and reports.

**Scope:** package `core-cut` of wave 8. A change belongs to this plan iff it (a) declares or
enforces the core/delivery boundary, or moves code so that it holds; (b) makes the harness
registry the two-sided adapter or states a harness's capability tier; (c) removes a command, a
flag, a session-context bundle, a hook slot or a template file that §15.6 names, or moves
knowledge of one language stack out of a core area into its profile; (d) reshapes the ledger
engine around a `Register` with byte-identical behaviour for the bug ledger; (e) restates the
documents those changes falsify (README, `CONTRIBUTING.md`, `RELEASING.md`, `docs/cli.md`, skills,
fragments); or (f) records the before/after counts in this plan's Findings. Out: the migration
journal's defects (a separate fix lane); the optional `adopt` skill, `prove`, regression
commands, evidence records and the debt register itself (wave 9); event bundles (overlay, wave 9
measures); `profile` as a list; any new command, flag, configuration key, skill or hook handler.

**Premise:** measured on 2026-10-04 at `dev` = `aed27b6`. A task that finds one no longer holds
stops and reports the mismatch instead of guessing.

- **Before counts** (the cut's baseline, recorded again in Findings): 32,736 lines in the 141
  tracked `src/stayfixed/**/*.py` files; 38 commands registered by the parser, under 40 command
  headings of `docs/cli.md` (`init` and `setup` each document two); 14 skills and 1 agent;
  `hooks/hooks.json` with 13 entries, 11 of them `SessionStart` (the dispatcher and ten bundle
  slots); 1,225 mutation entries in 8 group files; 12 discovered areas; 476 tracked files.
- **The core reaches into delivery through 12 imports.** Module level unless marked:
  `src/stayfixed/assess/rule.py:60` (`overlay.api.later`), `src/stayfixed/docs/commands.py:36` (function, `memory.api.resolved`),
  `src/stayfixed/docs/graph.py:17` (`memory.api.WIKI_LINK, Store, walk`), `src/stayfixed/doctor/checks.py:65` (`attach.api`),
  `src/stayfixed/doctor/checks.py:79` (`memory.api`, 16 names), `src/stayfixed/doctor/checks.py:97` (`overlay.api`),
  `src/stayfixed/project/detect.py:32` (`memory.api.GitUnavailable, origin_remote`), `src/stayfixed/project/questions.py:67`
  (function, `memory.api.overlay_root`), `src/stayfixed/project/templates.py:43` (`attach.api.IGNORE_BODY,
  IGNORE_REGION`), `src/stayfixed/project/uninstall.py:98` (`attach.api.LEDGER`), `src/stayfixed/project/upgrade.py:59`
  (`overlay.api.RELEASE, later`), `src/stayfixed/setup/run.py:116` (`overlay.api`, the `--overlay` path).
  `scripts/check_artifacts.py:34` imports `overlay.api.OVERLAY_FILES`; scripts are repository
  tooling and outside the rule.
- **`tests/test_areas.py` already holds a boundary.** `_area_names` lists `src/stayfixed/*` with a
  `commands.py` or `hooks.py`; `_imported_modules` resolves every import spelling, relative ones
  included; `_boundary_offences` refuses a cross-area import past `api.py`, with the named, sized
  exemption `SURFACE_EXEMPT`; `test_no_area_reaches_into_another_areas_private_module` walks
  `src/` and `scripts/`. Area discovery (`areas.area_modules`) is one level deep.
- **The hooks core is Claude-Code-shaped and harness-blind.** `src/stayfixed/hooks/dispatch.py` `parse_event`
  reads Claude Code's field names and only stamps `HookEvent.harness`; `render` always writes
  `hookSpecificOutput`; a deny bypasses `render` (exit 2, empty stdout, the reason on stderr).
  `src/stayfixed/hooks/api.py` `detect_harness` has two callers: `parse_event` and the Codex-only `index`
  bundle gate (`src/stayfixed/memory/commands.py:334`). `HookEvent.harness` is read only by tests.
  `harnesses.py` holds `Harness(name, marker_dir, settings, render_profile)` and is not imported by
  hook discovery (`tests/test_areas.py` asserts it); `src/stayfixed/doctor/checks.py` and `src/stayfixed/attach/permissions.py`
  still spell *.codex/hooks.json* and the Codex rules path on their own. `parse_event` needs
  `project_root` (with `_walk_to_git_root` and `_git_toplevel`, `src/stayfixed/hooks/dispatch.py` lines 54–101),
  which reads Claude Code's `CLAUDE_PROJECT_DIR` before falling back to git; `run_hook` parses the
  event before hook discovery runs. A committed *.claude/settings.json* `env` block can set
  `PLUGIN_ROOT`, so the harness a process detects is one a repository can choose.
- **Codex runs no plugin hook.** The wave-7 delivery spike recorded that Codex 0.160.0 ran none of
  the plugin's hooks, with or without the hook-trust bypass flag (wave-7 side-lanes plan,
  Findings, "What this settles", observation 7). On Codex, skills arrive through the plugin, and
  instructions through `AGENTS.md`. The repository's claim that "Codex downgrades an exit 2 with
  empty stderr" is unmeasured (foundation plan, the eight unmeasured Codex clauses).
- **Two session-context bundles are dead weight.** `preset-rules` prints nothing in production:
  `load_preset` refuses any preset but the shipped `recommended`, which has no `[rules]` table.
  `index` emits only under Codex (`src/stayfixed/memory/commands.py:334-337`). Together they hold four of the
  eleven `SessionStart` entries.
- **Python-specific knowledge sits in a core area.** `src/stayfixed/guards/hygiene.py` (253 lines) recognises a
  `pytest` run (`PYTEST`, `is_pytest_run`) and counts stale `.pyc` files by parsing PEP 552
  headers; the `test-hygiene` handler (`src/stayfixed/guards/hooks.py`) and `stayfixed test hygiene`
  (`src/stayfixed/guards/commands.py`) use it whenever a configuration loads. `src/stayfixed/guards/audit.py` (562 lines) is
  pytest-only and has one importer, `run_test_audit`. Profiles today are data only
  (`src/stayfixed/profiles/model.py` `Profile(name, detect, scope, essentials, checks, rules)`; one shipped
  profile, `profiles/python/` with `profile.toml` and `rules.md`).
- **`adopt begin` is a ritual.** `src/stayfixed/assess/state.py` `promote` moves `initialised` to `adopting` or
  `installed` itself (`test_a_named_gate_that_passes_is_enforced_without_begin_first` covers it);
  `begin` adds a plan lint and the `adopting` write. Its only callers outside tests:
  `src/stayfixed/assess/commands.py`, and the step `skills/init/references/adoption.md:41`.
- **The release area is half shipped.** `src/stayfixed/release/pins.py` (`Pin`, `Resolution`, `resolve_pin`,
  `is_released`) and the hash record's reader (`HASHED_FILES`, `RECORD`, `UnreadableRecord`,
  `digests`, `read_record`) are imported by `doctor`, `assess`, `project`; `commands.py`,
  `notes.py`, most of `versions.py` and `hashes.write_record`/`drift` serve only this repository's
  release. `ci.yml`, `release.yml`, the pull-request template, `CONTRIBUTING.md` and
  `RELEASING.md` call `uv run stayfixed release check`; `tests/test_fixtures.py` holds that string
  in all of them.
- **The ledger engine reads the bug ledger's configuration everywhere.** Every function takes
  `(root, config)`; `config.paths.bugs` is read in 15 places, `config.paths.bug_index` in 10,
  `identifiers(config)` in 11 inside the ledger plus `src/stayfixed/docs/plans.py:399` and `src/stayfixed/docs/graph.py:36`;
  the schema is module constants in `src/stayfixed/ledger/entries.py`, `src/stayfixed/ledger/check.py`, `src/stayfixed/ledger/index.py`,
  `src/stayfixed/ledger/write.py`. `Identifiers(prefix)` is already a prefix-parameterised value.
  `src/stayfixed/project/templates.py` renders the empty index at `init`, and its bytes are the `bug-index`
  artifact's manifest digest in every project.
- **The overlay template ships two files nothing needs.** `src/stayfixed/templates/overlay/common/rules/README.md` ("Nothing reads
  this directory yet.") and `skills/attach/SKILL.md` (a 20-line subset of the plugin's 31-line
  skill). The retirement mechanism exists: `src/stayfixed/overlay/layout.py` `RETIRED_OVERLAY_FILES`,
  `src/stayfixed/overlay/template.py` `_RETIRED` (digests of every released copy), and the scaffold engine's
  `_plan_retired`, which removes a file only while its bytes are ones a release shipped. The
  released digests: `src/stayfixed/templates/overlay/common/rules/README.md` `926060a042a6ab26f407fbe7fe84bf30771d8c279fdbce49848f051d710443d9`
  (`v0.1.0`, `v0.1.1`) and `62b01f752ee77c3c8fb5fcc0b78b14907a3b98072ff3c9b7e76f6b792e7c065b`
  (`v0.2.0`); `skills/attach/SKILL.md` `845e67006aa4303a2c69d1601c987f58ca28acf806f2e89f272b63ae8bb572c9`
  (all three).
- **`docs/cli.md` has 45 `## ` headings**, and `tests/test_documents.py` holds `len(headings) >= 44`;
  every task that deletes a section sets that floor to the new exact count.
- **The oracle proves `HEAD`.** `scripts/mutation_oracle.py` applies each mutation in a scratch
  checkout and refuses when a mutated file or a named test file is uncommitted, so it runs after
  a task's commit, never before.
- **The release itself is separate.** `RELEASING.md` cuts a release from `main` in a
  `chore(release): X.Y.Z` commit after `dev` merges; no pull request of this plan edits a version
  string.

## Global Constraints

- **Runtime imports only the standard library**, writes into a repository go through `fsops`, and
  repository-authored bytes reach the model only inside `trust.wrap` (`CONTRIBUTING.md`).
- **No new surface** (§15.5 freeze): no command, flag, configuration key, skill, hook handler or
  hook event. Removing and moving are the whole job; a discovery convention (`doctor.py`, a
  profile's code) is internal structure, not surface.
- **The core is language-neutral.** No core module names one stack's test runner, build artifact
  or package manager, except the pardons `tests/test_language_neutral.py` (create, Task 13) pins
  with a reason each; that knowledge lives in the stack's profile, and a polyglot repository must
  work without configuration (§15.6, decision 3).
- **Core may name delivery's paths and configuration keys** (the `.stayfixed/` namespace and the
  machine file's keys are core's); it never imports delivery's code or calls its behaviour.
- **Core never imports delivery** once Wave B lands, except the one pinned crossing.
- **Every new assertion ships with the mutation that reddens it, or a sentence saying why none
  exists** (`CONTRIBUTING.md`, "Tests"). A mutation this plan names is a hypothesis until a run
  watched it fail; a load-bearing guard gets a `mutations/` entry in the group file its path routes
  to.
- **Every removal deletes its tests, its mutation entries and every comment that cites them in
  the same commit** (`tests/scripts/test_mutation_oracle.py` resolves cited entry names).
- **Neutral text.** Committed text names no project outside this repository, no home directory,
  login or private repository; commit ids in text are 7 characters or 40.
- **User-visible changes carry a towncrier fragment** (`+<slug>.change.md`) written as a release
  note for a stranger; internal moves carry none.
- **Tests never run `gh`, `claude`, `codex`, `pip` or `pre-commit`,** and never read the
  developer's `~/.claude`, `~/.codex` or `~/.config/stayfixed`.
- Conventional commit subjects describing intent; no attribution trailer.

## Execution contract

Every seat's brief carries the section of this contract that applies to it, copied rather than
referenced, a fix round and a post-PR dispatch included.

**1. Final review.** Each pull request gets three parallel read-only seats — **correctness**,
**architecture** (is the boundary real, is every move a move and not a copy, does any core module
still know a stack or a harness it should not), **security** (containment, the trust wrap, the deny
path and the hook policy untouched by the adapter, nothing a repository authored reaching a
message unwrapped) — and a **lifecycle** seat that walks section 2's rows for the commands the
pull request touches.

**2. Lifecycle matrix.** Checked at pre-flight like a task, walked by the lifecycle seat. A cell
names the test or step that covers it, or "—" when the change cannot reach the command.

| Command \ change | re-run, nothing changed | a project or install upgraded from `0.2.0` | a path moved or a file absent | killed or failing part-way | uninstalled or detached |
|---|---|---|---|---|---|
| `doctor` (Tasks 4–5, 8) | Task 17 `tests/doctor/test_command.py::test_a_second_report_is_the_first_and_neither_writes_anything` (two runs, one report, the tree and home unchanged); the row set itself: Task 5 `test_every_check_has_one_row_in_one_report`, Task 8 `test_the_codex_row_names_what_does_not_run_on_codex` | Changes, and the Upgrading notes say so: on a `0.2.0` install whose machine records no overlay, `hook-entries` is red and the report exits `1`, where `0.2.0` warned and exited `0` (93a5ebb). Task 5 `test_a_project_with_no_overlay_gets_skips_from_delivery_checks` pins the red; nothing else in an unchanged `0.2.0` install changes doctor's verdict (lifecycle review's upgrade run: `0` red, `2` warn) | Task 5 `test_a_project_with_no_overlay_gets_skips_from_delivery_checks` | Task 4 `test_a_contribution_that_raises_costs_one_row` | Task 5 `test_an_unattached_project_reports_attached_as_it_did` |
| `memory refs` (Task 3) | Task 17 `tests/memory/test_refs.py::test_a_second_run_answers_as_the_first_and_neither_writes_anything` (a stale path and a graph notice, two runs, one exit and line, the tree unchanged); the exit itself: Task 3 `test_refs_reports_graph_notices_without_changing_its_exit` | — | — (refs already refuses an unresolved store: `tests/memory/test_refs.py`) | — | — |
| `hook <event>` (Tasks 6, 7, 13) | `tests/hooks/test_hook_command.py::test_a_once_per_context_handler_really_runs_once` (`hook PostToolUse` run twice through the CLI: the second delivers nothing) and `tests/attach/test_hooks.py::test_a_context_that_has_already_been_asked_does_not_re_pay_the_sync` (the `SessionStart` handler asked again for one tree gives the same answer) | — for a marketplace install (`hooks/hooks.json` and the code ship in one plugin version, and the hook launcher runs the plugin's own `src`). Upgraded in place (a local-path marketplace or `--plugin-dir`), a session already running may keep the `hooks.json` it loaded until it reloads (not measured). Measured: against the new code, the four `memory session-context` slots `0.2.0`'s `hooks.json` has and this one removes (`preset-rules` 1, `index` 1–3) each exit `2` with `unknown bundle` on stderr, at the CLI and through `hooks/run-hook.sh`. A `SessionStart` hook's exit `2` cannot block (`tests/hooks/test_hooks_json.py`), so such a session goes on without those bundles at its next `SessionStart` (resume, clear or compact); where Claude Code shows that stderr was not measured | `tests/attach/test_hooks.py::test_a_mismatched_record_and_a_missing_overlay_each_get_their_own_line` (the overlay this machine records is gone: `SessionStart` says so in one line) and `tests/memory/test_hooks.py::test_a_broken_store_is_silence_not_an_exception` | Task 7 `test_a_deny_never_goes_through_render` | — |
| `test hygiene` and the `PostToolUse` notice (Task 13) | Task 13 `test_a_red_pytest_run_gets_the_python_profiles_note` | — | Task 13 `test_test_hygiene_reports_a_profile_with_something_to_say_wherever_its_markers_sit`, `test_only_contained_code_roots_are_scanned` | Task 13 `test_a_hint_that_raises_costs_its_note_not_the_dispatch` | — |
| `bugs new|index|check|renumber` (Tasks 14, 15) | Task 14 `test_the_bug_register_renders_the_index_byte_for_byte` | Task 14 `test_init_renders_the_empty_index_with_the_same_digest` | Task 15 `test_a_second_register_without_its_directory_is_inert_while_the_bug_ledger_is_live`; for the bug ledger: `tests/ledger/test_register.py::test_the_bug_ledgers_header_and_links_keep_their_bytes_on_every_layout`, and Task 15 `tests/project/test_templates.py::test_init_writes_the_runbook_and_audits_readme_where_the_bug_index_links_them` | `renumber`, kept and passed the register (`tests/ledger/test_write.py`): `test_renumber_reports_a_file_it_could_not_sweep_and_keeps_both_endpoints`, `test_renumber_reports_a_file_it_could_not_write_back`, `test_renumber_rejects_a_malformed_sibling_before_it_moves_anything`, `test_renumber_refuses_over_foreign_index_content_without_moving_anything` | — |
| `init`, `upgrade`, `uninstall` (Task 2) | Task 17 `tests/project/test_upgrade.py::test_a_second_upgrade_to_the_same_release_writes_nothing` (the second run plans nothing and the tree is compared byte for byte) | Task 2 `test_the_ignore_block_init_writes_is_the_block_attach_writes` (the block's bytes pinned as at `aed27b6`, so `upgrade` sees no change) | Task 2 `test_an_attached_repository_is_refused_and_told_to_detach` (kept, pinned to the literal path) | — | Task 17 `tests/attach/test_detach.py::test_uninstall_after_a_real_detach_takes_the_footprint_back` (a real attach and detach over an `init` footprint, then `uninstall` runs, and a second finds nothing) |
| `overlay upgrade`, `overlay init` (Task 12) | Task 12 `test_an_overlay_without_the_retired_files_plans_nothing` | Task 12 `test_each_released_copy_of_a_retired_file_is_removed` | Task 12 `test_an_overlay_without_the_retired_files_plans_nothing` (absent and unrecorded: no action, and not listed as unchanged) and `test_the_record_of_a_memory_readme_already_gone_is_dropped` (absent and recorded); an edited one: Task 12 `test_an_edited_retired_file_is_kept_and_named` | — | — |
| `setup --overlay` (Task 1) | — | — | — | — | — (the pinned crossing; Task 1 `test_core_never_imports_delivery`) |
| `scripts/release.py` (create, Task 11) | Task 11 `test_the_repository_passes_release_check` | — | Task 11 `test_a_drifted_record_fails_the_hashes_check` (create) | — | — |

The lifecycle seat resolves every test name in this matrix against the pull request's tests; a
task that renames a test renames its cell in the same commit, so the matrix never names a test
that does not exist.

**3. Parallelism map.** Three lanes in three worktrees, with the edges of the launch graph.
Read-only seats run beside each other and beside the next wave's implementer. Writers of one
worktree serialise. The mutation oracle runs one at a time per host (it starts up to four
worktrees itself).

**4. Templates.** An implementer's brief carries these lines, copied:

- A mismatch between this plan and the tree beats a guess: stop, quote both, report.
- Paste the output of every verification command into the report; "passed" without output is
  not a result.
- Focused tests while iterating; one full run (`uv run pytest -n auto --cov --cov-fail-under=92`)
  at the end of the wave, not after every step.
- A mutation this plan names is a hypothesis: apply it, run the named test, restore the line by
  re-applying the original text, and report what happened. If it does not redden, design one that
  does and say so; do not weaken it.
- Line numbers in this plan are as of `aed27b6`; locate by the quoted text.
- Static checks at CI's scope: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy` (it covers `src`, `tests` and `scripts`).
- Do not spawn subagents. Do not run `git restore`, `git checkout -- <path>`, `git stash`,
  `git reset --hard` or `git clean`.
- Write nothing outside the worktree but your scratchpad.
- The oracle proves `HEAD`: commit the task, then run `uv run python scripts/mutation_oracle.py <filter>`;
  a fix to an entry is a follow-up commit inside the same task.
- Where a test pins bytes "as at `aed27b6`", capture them from the unchanged code before the
  task's first edit (`git diff aed27b6 -- <paths>` empty, then run the old code or
  `git show aed27b6:<path>`), paste the captured text into the report, and never derive the
  literal from the code under test.
- Already verified before dispatch: the Premise section's numbers.

A fix brief enumerates the sibling instances of the defect class it fixes (the
`sweep-defect-class` skill) and reports the neighbour probes it ran. A security ruling names the
minimal preconditions, where the anchor it trusts came from, and one legitimate user it must not
refuse.

**5. Verification.** The controller re-verifies only the heads it pushes or merges, and
re-derives each pull request's body from the branch before every push. The full set before every
push:

```bash
uv run pytest -n auto --cov --cov-fail-under=92
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run python scripts/mutation_oracle.py
uv run stayfixed release check            # after Wave F lands: uv run python scripts/release.py check
uv run stayfixed plan check docs/plans/2026-10-04-wave-8-core-cut.md
```

## Waves

| Wave | Tasks | Lane | Pull request (branch) | Mode | Size (plan lines) |
|---|---|---|---|---|---|
| 0 | — | — | this file (`plans/wave-8-core-cut`) | delivered by the commit that adds it | — |
| A | 1–3 | 1 | 1 (`wp/core-cut-boundary`) | dispatched | ~200 |
| B | 4–5 | 1 | 1 | dispatched | ~115 |
| C | 6 | 1 | 2 (`wp/core-cut-harness`) | dispatched | ~50 |
| D | 7–8 | 1 | 2 | dispatched | ~175 |
| E | 9–10 | 2 | 3 (`wp/core-cut-surface`) | dispatched | ~90 |
| F | 11 | 2 | 3 | dispatched | ~65 |
| G | 12 | 2 | 3 | dispatched | ~45 |
| H | 13 | 2 | 4 (`wp/core-cut-profiles`) | dispatched | ~90 |
| I | 14 | 3 | 5 (`wp/core-cut-registers`) | dispatched | ~85 |
| J | 15 | 3 | 5 | dispatched | ~50 |
| K | 16 | — | 6 (`wp/core-cut-record`) | dispatched | ~35 |
| L | 17 | — | — | controller-run, owner present | ~30 |

Letters run in execution order inside each lane, and lanes run side by side. Waves I and J were split
from one wave after review: the engine's write side and its check side each rewrite most of the
ledger's 1,841 lines against 2,547 lines of its tests, which is past one dispatch together.
Wave B is the largest dispatch by code read (`src/stayfixed/doctor/checks.py` is 1,812 lines, its test file
2,472): if the implementer's first pass nears the ceiling, Task 5 goes to a fresh agent with
Task 4's report. Wave G depends on nothing in this plan (it touches only the overlay template
and its retirement table) and rides lane 2 so lane 1 stays the critical path's length.

Launch graph, drawn last and over what each task consumes:

```text
Wave 0 ──┬──> A ──> B ──[PR 1]──┬──> C ──> D ──[PR 2]─────────────┐
         │                      │      ▲                          │
         │                      │      ┊ hashes tool (F)          │
         ├──> I ────────────────┴──> J ──[PR 5]───────────────────┤
         │                                                        ├──> K ──[PR 6]──> L
         └──> E ──> F ──> G ──[PR 3]──> H ──[PR 4]────────────────┘
```

- **A → B**: Task 4's `doctor.py` convention extends the area discovery Task 1 declares the
  delivery areas in, and Task 5 deletes the doctor rows of `CORE_TO_DELIVERY` (Task 1).
- **B → C**: Task 6 edits the `bundles` check's comment in `src/stayfixed/memory/doctor.py`, which Task 5
  creates.
- **C → D**: Task 6 deletes the `index` bundle, one of `detect_harness`'s two callers, so Task 7
  removes the function with nothing to repoint; Task 8 rewrites `src/stayfixed/doctor/checks.py`'s settings
  list, which Task 5 restructured.
- **F ┄ C**: Task 6 regenerates `hooks/hashes.json`. Before PR 3 merges that is
  `uv run stayfixed release hashes`; after, `uv run python scripts/release.py hashes`. Whichever
  merges second regenerates on the rebased branch.
- **E → H**: Task 10 deletes `src/stayfixed/guards/audit.py` and its command beside `test hygiene`, which
  Task 13 rewires; H branches after PR 3 merges.
- **0 → I, A → J**: Task 14 touches only `src/stayfixed/ledger/` and one call in `src/stayfixed/project/templates.py`, so it
  branches from Wave 0; Task 15 rewires `src/stayfixed/memory/graph.py`, which Task 3 creates, so the lane's
  branch rebases onto a `dev` carrying PR 1 before J starts. **I → J**: Task 15 passes Task 14's
  `Register`.
- **K** restates the README and `CONTRIBUTING.md` over every merged change; **L** measures the
  merged `dev`.

## File structure

| Path | Task | Responsibility |
|---|---|---|
| `src/stayfixed/areas.py` | 1, 4 | `DELIVERY_AREAS`; `area_modules` serves `doctor` as it serves `commands` and `hooks` |
| `tests/test_areas.py` | 1, 2, 3, 5 | the core/delivery rule and `CORE_TO_DELIVERY`, which shrinks to one row |
| `src/stayfixed/semver.py` (create) | 2 | `RELEASE` and `later`, the version order every area shares |
| `src/stayfixed/config/overlay.py` (create) | 2 | `overlay_root`, the reader of the `[overlay] root` key `setup` writes |
| `src/stayfixed/config/layout.py` | 2 | gains the `.gitignore` block `init` and `attach` both write, and `ATTACH_LEDGER` |
| `src/stayfixed/memory/graph.py` (create) | 3 | the link-graph notices, moved from `src/stayfixed/docs/graph.py` and reported by `memory refs` |
| `src/stayfixed/doctor/model.py` (create) | 4 | `Check`, `Row`, the statuses, `Context`, `Claims`, `Contribution`; `src/stayfixed/doctor/api.py` re-exports them |
| `src/stayfixed/{memory,overlay,attach}/doctor.py` (create) | 5 | each delivery area's checks |
| `src/stayfixed/harnesses.py` | 7, 8 | the adapter: `Harness` with `detects`, `project_dir_env`, `render`, `reach`, `local_settings`; `detect`, `Tier`, `Surface` |
| `src/stayfixed/gitenv.py` | 2, 7 | gains `origin_remote`, `GitUnavailable`, `checkout_root` |
| `src/stayfixed/hooks/dispatch.py` | 7 | one canonical `read_event`; renders and clamps through the detected harness; the deny floor unchanged |
| `README.md` | 8–13, 16 | the capability table, the command list, the cut's narrative |
| `scripts/release.py` (create) | 11 | `check`, `notes`, `hashes`, `write_record`, `drift` for this repository's release |
| `src/stayfixed/memory/bundles.py` | 6 | two bundles: `standing-rules`, `volatile-notes` |
| `hooks/hooks.json` | 6 | 9 entries |
| `src/stayfixed/profiles/python/hygiene.py` (create) | 13 | the Python profile's red-run hint: a pytest run, stale bytecode |
| `src/stayfixed/profiles/hints.py` (create) | 13 | `RedRunHint`, and discovery of every shipped profile's hint |
| `tests/test_language_neutral.py` (create) | 13 | no core module names a stack beyond its pinned pardons |
| `src/stayfixed/ledger/register.py` (create) | 14, 15 | `Register`, `Schema`, `bug_register(config)` |
| this file, Findings | 17 | the before/after counts and the review record |

---

## Lane 1 — the boundary and the harness

### Wave A — Tasks 1–3

#### Task 1: Declare the delivery areas and hold the core to them

**Files:**
- Modify: `src/stayfixed/areas.py`
- Modify: `tests/test_areas.py`
- Modify: `CONTRIBUTING.md` ("Areas")

**Interfaces:**
- Produces: `areas.DELIVERY_AREAS: frozenset[str]`, the delivery side: `attach`, `hints`,
  `memory`, `overlay`, `setup` and `trust`, beside `PACK_PACKAGES` and `CORE_AREAS`.
- Produces: in `tests/test_areas.py`, `_delivery_offences(where: str, text: str, areas: frozenset[str]) -> list[tuple[str, str]]`
  and `CORE_TO_DELIVERY: frozenset[tuple[str, str]]`. A row is one import statement: the importing
  file relative to `src/stayfixed` and the imported module cut to its first three dotted parts —
  `("setup/run.py", "stayfixed.overlay.api")`. Keyed on `ImportFrom.module` or the `Import` name,
  never on `module.alias` (`_imported_modules` also yields `stayfixed.memory.api.WIKI_LINK`-style
  names, which would make 55 rows of the 12 imports). Tasks 2, 3 and 5 delete rows; after Wave B
  exactly that one remains.

The rule: a module under `src/stayfixed/` whose first path part is not in `DELIVERY_AREAS` (that
includes `cli.py`, `config/`, `scaffold/` and every other non-area subpackage) imports nothing
whose second dotted part is in `DELIVERY_AREAS`, through `api` or not, at module level or inside
a function. Delivery may import core. The rule walks `src/stayfixed/` only; `scripts/` is
repository tooling and stays under the existing `api.py` rule. It reads source, so an
`importlib.import_module` call is invisible to it — the same mechanism area discovery uses, which
is accepted and said in the comment beside the constant.

- [ ] **Step 1: Write the failing tests.** In `tests/test_areas.py`:
  `test_core_never_imports_delivery` walks `src/stayfixed/**/*.py`, collects the rows above, and
  asserts they equal `CORE_TO_DELIVERY`, with `assert len(CORE_TO_DELIVERY) == 12` at this commit
  (each later task lowers it). Equality both ways is the point: a new crossing reddens it, and so
  does a row whose import is gone, so the set never carries a stale pardon.
  `test_the_delivery_areas_are_the_three_the_design_names` pins
  `areas.DELIVERY_AREAS == frozenset({"attach", "memory", "overlay"})` as a literal: the one row
  left after Wave B exercises only `overlay`, so without the pin a change could drop `memory` from
  the constant beside a new crossing and stay green.
- [ ] **Step 2: Run them.** `uv run pytest tests/test_areas.py -q`. Expected: FAIL on
  `AttributeError: module 'stayfixed.areas' has no attribute 'DELIVERY_AREAS'`.
- [ ] **Step 3: Implement.** Add `DELIVERY_AREAS` to `src/stayfixed/areas.py` with a comment in this repository's
  own words (the design is private and is not cited from code): the private layer's code — the
  overlay, binding a repository to it, and the note store; core never imports it and it may import
  core, so the private layer can be reworked without touching the core; the rule reads source,
  not `importlib` calls; the test that holds it.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Prove the rule discriminates.** Add
  `test_the_delivery_rule_judges_the_importer_and_the_imported` beside
  `test_the_boundary_rule_resolves_a_relative_import_before_judging_it`, over synthetic source:
  a core module with `from ..memory import api` inside a function gives one offence; a delivery
  module (*memory/x.py*) importing `stayfixed.overlay.api` gives none. Commit, then declare in
  `mutations/repository.toml` (where `tests/` routes):
  (1) in `_delivery_offences`, replace the imported module's delivery-membership test with `False`.
  Expected to redden: `test_the_delivery_rule_judges_the_importer_and_the_imported`.
  (2) Replace the importer-is-core test with `True`. Expected to redden: the same test, through its
  delivery-to-delivery case.
  (3) In `src/stayfixed/areas.py`, drop `"memory"` from `DELIVERY_AREAS`. Expected to redden:
  `test_the_delivery_areas_are_the_three_the_design_names`.
- [ ] **Step 6: Document.** `CONTRIBUTING.md`, "Areas": one paragraph after the area list — the
  three delivery areas, the direction of the rule, the pinned crossing and why it is pinned, the
  `importlib` limit, that a new crossing is refused by `test_core_never_imports_delivery`, and the
  rule for what core may know: core may name delivery's paths and configuration keys (the
  `.stayfixed/` namespace and the machine file's keys are core's), and never imports delivery's
  code or calls its behaviour.
- [ ] **Step 7: Commit** `refactor(areas): declare the delivery areas and hold the core to them`,
  then run the oracle over the three entries. No fragment: nothing a user runs changes.

#### Task 2: Move the generic helpers the core borrows into core modules

**Files:**
- Create: `src/stayfixed/semver.py`, `src/stayfixed/config/overlay.py`
- Modify: `src/stayfixed/overlay/requires.py`, `src/stayfixed/overlay/api.py`
- Modify: `src/stayfixed/gitenv.py`, `src/stayfixed/memory/store.py`, `src/stayfixed/memory/api.py`
- Modify: `src/stayfixed/config/layout.py`, `src/stayfixed/attach/write.py`, `src/stayfixed/attach/api.py`
- Modify (importers): `src/stayfixed/assess/rule.py`, `src/stayfixed/project/detect.py`,
  `src/stayfixed/project/questions.py`, `src/stayfixed/project/templates.py`,
  `src/stayfixed/project/uninstall.py`, `src/stayfixed/project/upgrade.py`, `src/stayfixed/doctor/checks.py`,
  and every delivery module that imported a moved name
- Test: `tests/test_semver.py`, `tests/config/test_overlay_root.py`
- Modify: `tests/test_areas.py` (rows), `tests/overlay/test_requires.py`, `tests/test_git_answers.py`,
  tests that import or monkeypatch the moved names, `mutations/*.toml` entries whose `file` or
  `before` moved

**Interfaces:**
- Produces: `semver.RELEASE`, `semver.later(version: str, than: str) -> bool | None`, and, under
  public names, the component and prefix patterns `overlay.requires.satisfies` shares with them
  today (`_COMPONENT`, `_VERSION`). `requires_of` and `satisfies` stay in overlay and import those
  patterns from `semver`; neither calls `later`.
- Produces: `gitenv.origin_remote(root: Path) -> str | None` and `gitenv.GitUnavailable(Failure)`.
  `origin_remote` is rebuilt on `gitenv.git_run` and `answer_lines` rather than on
  `src/stayfixed/memory/store.py`'s private `_git`, `GitAnswer` and `_git_is_usable`, which stay where they are;
  its answers (a URL, `None` with no `origin`, `GitUnavailable` when git cannot answer) do not
  change, and its tests in `tests/test_git_answers.py` move with it. `gitenv` gains an
  `errors` import and stays otherwise a leaf.
- Produces: `config.overlay.overlay_root(machine: Path | None) -> Path | None` (create, beside
  `src/stayfixed/config/loader.py` rather than in `src/stayfixed/config/machine.py`, which `src/stayfixed/config/loader.py` imports at module
  level). It moves verbatim except for the exception it raises: the loader's `MachineConfigError`
  (`src/stayfixed/config/loader.py`, a `ConfigError` and so a `Failure`), not memory's class of the same name, which
  is deleted. Raising memory's class from core would be a new crossing, and moving it would leave
  two unrelated `MachineConfigError`s in `config/`. Every caller already catches `Failure`
  (`doctor`'s `_context`, `src/stayfixed/memory/hooks.py`, the resolver), so no catch changes; the messages for a
  broken machine file converge on the loader's (`NOT_UTF8`, `UNREADABLE`, the TOML position), which
  the commit states. `tests/config/test_deep_toml.py` and `tests/memory/test_store.py` follow. It
  keeps reading `machine_config_path(interactive=False)`.
- Produces: in `src/stayfixed/config/layout.py`, the `.gitignore` block both `init` and `attach` write:
  `LOCAL_STATE_PATHS` (today `src/stayfixed/attach/write.py`'s `IGNORED`, renamed because
  `src/stayfixed/project/ignored.py` already defines an unrelated `IGNORED` message), `IGNORE_NOTE`,
  `IGNORE_REGION`, `IGNORE_BODY`; and `ATTACH_LEDGER` (`src/stayfixed/attach/write.py`'s ledger path,
  *.stayfixed/local/attach.json*). `attach` and `project` import them from there.

Each name moves; none is copied. Where a delivery module imported a moved name from its own area,
it now imports it from the core home. An `api.py` loses a name no consumer reaches through it any
more. `src/stayfixed/doctor/checks.py` switches to the new homes for the moved names in this task; its three
`CORE_TO_DELIVERY` rows stay, for the delivery names it still imports, until Task 5. Monkeypatch
targets move with the code: before the first run, collect every `monkeypatch.setattr` target in
`tests/` naming a moved function (the string targets on `stayfixed.memory.store` are in
`tests/memory/test_store.py`, `tests/attach/test_commands.py`, `tests/attach/test_detach.py`,
`tests/attach/test_binding.py`) and diff them against the new module's `dir()`.

- [ ] **Step 1: Write the failing tests.** `tests/test_semver.py`: move the `later` and release-pattern
  cases out of `tests/overlay/test_requires.py` (the existing cases pin how a pre-release orders;
  keep them as they are). `tests/config/test_overlay_root.py`: move `overlay_root`'s tests. In
  `tests/project/test_templates.py`, add `test_the_ignore_block_init_writes_is_the_block_attach_writes`:
  the region `init` renders and the region `attach` merges each equal, byte for byte, the block
  pinned as a literal in the test — copied from `tests/fixtures/smoke-project/.gitignore`, which
  holds it at `aed27b6` — and never read back from the constant. Keep
  `test_an_attached_repository_is_refused_and_told_to_detach` under its name (the entry
  `mutations/`'s project group names it), and make it write the ledger at the literal path, not
  through `ATTACH_LEDGER`, so a change to the constant's value is a change the test sees.
- [ ] **Step 2: Run them.** Expected: FAIL on the missing modules and names.
- [ ] **Step 3: Move the code**, one name family at a time, updating importers and
  `CORE_TO_DELIVERY` (delete the rows (spelled relative to `src/stayfixed/`) for `src/stayfixed/assess/rule.py`, `src/stayfixed/project/detect.py`,
  `src/stayfixed/project/questions.py`, `src/stayfixed/project/templates.py`, `src/stayfixed/project/uninstall.py`, `src/stayfixed/project/upgrade.py`;
  `len == 6`).
- [ ] **Step 4: Run.** `uv run pytest tests/test_semver.py tests/config tests/test_areas.py tests/test_git_answers.py tests/project tests/overlay tests/attach tests/memory tests/doctor -q`.
  Expected: PASS.
- [ ] **Step 5: Commit** `refactor(core): give the version order, the origin, the overlay root and
  the ignore block core homes`.
- [ ] **Step 6: Mutations, after the commit.** Re-route every entry whose `file` moved to the group
  its new path routes to (`semver.py`, `gitenv.py`, `config/` route to `core`), keep its `name`,
  re-anchor every `before` that spelled a renamed constant (`mutations/`'s project group: the
  uninstall refusal's `    if (root / LEDGER).is_file():`), and run each. Add, in
  `mutations/core.toml`: (1) in `src/stayfixed/config/layout.py`, change the `IGNORE_NOTE` line's text.
  Expected to redden: `test_the_ignore_block_init_writes_is_the_block_attach_writes`. (2) In
  `src/stayfixed/config/overlay.py`, pass `interactive=True` to `machine_config_path`. Expected to redden: the
  moved test that pins a non-interactive read (if none does, write
  `test_the_overlay_root_never_asks_where_the_machine_file_is` first). Commit the entries.

#### Task 3: Report the memory link graph from `memory refs`

**Files:**
- Create: `src/stayfixed/memory/graph.py`
- Delete: `src/stayfixed/docs/graph.py`
- Modify: `src/stayfixed/memory/refs.py`, `src/stayfixed/memory/commands.py`
- Modify: `src/stayfixed/docs/commands.py`, `src/stayfixed/docs/api.py`
- Modify: `docs/cli.md` (the `docs check` heading, its Contents line and section, `memory refs`)
- Test: `tests/memory/test_graph.py`
- Modify: the `tests/docs/` tests of `--memory-graph`, `tests/test_areas.py`, `tests/docs/test_surface.py`,
  `mutations/records.toml`, `mutations/core.toml` (the store entry below)
- Create: `changelog.d/+memory-graph-in-refs.change.md`

**Interfaces:**
- Produces: `memory.graph.check_memory_graph(store: Store, config: Config) -> list[Finding]`
  (moved verbatim); `memory refs` reports its findings as advisory `notices`, counted on the line
  and in `--json`, never in the exit code. `RefsReport` gains `notices`.
- Removes: `docs check --memory-graph`, `docs.api.check_memory_graph`, `_graph_notices`.

`memory refs` already walks the store for stale paths and the `audience` rule, and it already
refuses an unresolved store with exit 2 (`_no_store`, tested in `tests/memory/test_refs.py`), so
the graph rides that walk and inherits that refusal; the `docs check` notice for an unresolved
store goes with the flag. The graph's notices stay advisory, as they were: a `[[link]]` to a
missing note is a hint, a stale path in a note is a finding, and the exit code keeps meaning the
latter.

- [ ] **Step 1: Write the failing tests.** `tests/memory/test_graph.py`: move the graph tests from
  `tests/docs/`; add `test_refs_reports_graph_notices_without_changing_its_exit` (a store with one
  dangling `[[link]]` and no stale path: exit `0`, one notice in `--json`, the line counts it).
- [ ] **Step 2: Run.** Expected: FAIL (`memory.graph` does not exist; `refs` reports no notices).
- [ ] **Step 3: Implement.** Move the module; call it from `check_refs` after the walk; delete the
  flag, `_graph_notices` and the `docs.api` export; delete the rows for `src/stayfixed/docs/commands.py` and
  `src/stayfixed/docs/graph.py` (`len == 4`).
- [ ] **Step 4: Run.** `uv run pytest tests/memory tests/docs tests/test_areas.py tests/test_documents.py -q`. Expected: PASS.
- [ ] **Step 5: Docs and fragment.** `docs/cli.md`: drop `[--memory-graph]` from the `docs check`
  heading and its Contents line; move the advisory paragraph into `memory refs` as notices.
  Fragment: "`stayfixed docs check --memory-graph` is gone: `stayfixed memory refs` now reports the
  note store's link graph as notices, beside the stale paths it already finds, and its exit code
  still counts only the stale paths." Commit `refactor(memory): report the link graph from memory
  refs, not docs check`.
- [ ] **Step 6: Mutations, after the commit.** No entry has `file` on `src/stayfixed/docs/graph.py`. Two
  entries depend on the removed flag: replace `mutations/records.toml`'s "an advisory
  memory-graph finding gates the exit code" (anchored on `run_docs_check`'s
  `    return Result(verdict, data)`) with one on `run_refs` in `src/stayfixed/memory/commands.py`:
  `before = "    if report.findings:"`, `after = "    if report.findings or report.notices:"`.
  Expected to redden: `test_refs_reports_graph_notices_without_changing_its_exit`. Re-point
  "a missing store directory is reported with no reason of its own" (`file` in
  `src/stayfixed/memory/store.py`) from the deleted `docs check` test to the `memory refs` test of
  `tests/memory/test_refs.py` that asserts the refusal's reason for a missing directory, and run it.

### Wave B — Tasks 4–5

#### Task 4: Let an area contribute doctor checks

**Files:**
- Create: `src/stayfixed/doctor/model.py`
- Modify: `src/stayfixed/areas.py` (docstring: a third discovered submodule)
- Modify: `src/stayfixed/doctor/api.py`, `src/stayfixed/doctor/checks.py`
- Test: `tests/doctor/test_contributions.py`
- Modify: `CONTRIBUTING.md` ("Areas")

**Interfaces:**
- Produces, in `src/stayfixed/doctor/model.py`, re-exported by `src/stayfixed/doctor/api.py` (an area's `api.py` re-exports and
  never defines; `tests/test_surfaces.py` allows only `hooks` to define): `Row`, `Check`, the
  statuses (`OK`, `WARN`, `RED`, `SKIP`), the core `Context` (root, home, machine, runner, env,
  config, the two plugin roots — no `store`, no `overlay`, and not the never-assigned
  `store_refusal` field today's `Context` declares), and

  ```python
  @dataclass(frozen=True)
  class Claims:
      """What an area put into settings files, for `hook-entries`' provenance column.

      Carries every answer `_attach_ledger_entries` and `_granted_commands` give today, their
      `None`s included: `recorded is None` is "the record could not be read" (the row warns and
      says so), `granted is None` is "the overlay could not be asked" (the row withholds the
      overlay's provenance rather than calling its entries foreign)."""
      recorded: Mapping[str, str] | None
      granted: frozenset[str] | None

  @dataclass(frozen=True)
  class Contribution:
      checks: tuple[tuple[str, Callable[[Context], Row]], ...]
      claims: Callable[[Context], Claims] | None = None   # never raises on repository bytes
  ```
- Produces: an area's `doctor.py` with `register() -> Contribution`, discovered by
  `areas.area_modules("doctor")`. Its imports sit inside function bodies, as a `hooks.py`'s do.
- Produces: `doctor.checks.run_checks` runs the core `CHECKS`, then each contribution's checks in
  area-name order, every one through `_guarded`; a contributed name equal to a core check's name or
  to another area's is refused at discovery.

- [ ] **Step 1: Write the failing tests.** `tests/doctor/test_contributions.py`, with fake area modules
  injected through the discovery seam: `test_a_contributed_check_runs_after_the_core_checks`,
  `test_a_contribution_that_raises_costs_one_row` (its check raises `RuntimeError`: one red row
  naming the exception type and no message, every other row present),
  `test_a_contributed_name_may_not_repeat_a_core_or_another_areas_name` (both clashes refused).
- [ ] **Step 2: Run.** Expected: FAIL (no `Contribution`, no discovery of `doctor`).
- [ ] **Step 3: Implement.** Move the vocabulary into `src/stayfixed/doctor/model.py`; add the discovery, with a
  seam the tests replace the way `cli.discover_registrars` is replaced.
- [ ] **Step 4: Run.** `uv run pytest tests/doctor tests/test_areas.py tests/test_surfaces.py -q`. Expected: PASS.
- [ ] **Step 5: Document and commit.** `CONTRIBUTING.md`, "Areas": `doctor.py` with
  `register() -> Contribution` joins `commands.py` and `hooks.py`; a check's name is unique in the
  report. Commit `refactor(doctor): let an area contribute its own checks`.
- [ ] **Step 6: Mutations, after the commit** (`mutations/install.toml`): (1) in `run_checks`,
  drop the contributions' checks. Expected to redden:
  `test_a_contributed_check_runs_after_the_core_checks`. (2) Call a contributed check directly
  instead of through `_guarded`. Expected to redden: `test_a_contribution_that_raises_costs_one_row`.
  (3) Drop the duplicate-name refusal. Expected to redden:
  `test_a_contributed_name_may_not_repeat_a_core_or_another_areas_name`.

#### Task 5: Move the delivery checks into their areas

**Files:**
- Create: `src/stayfixed/memory/doctor.py`, `src/stayfixed/attach/doctor.py`, `src/stayfixed/overlay/doctor.py`
- Modify: `src/stayfixed/doctor/checks.py`
- Modify: `docs/cli.md` (the `doctor` table's order and prose)
- Test: `tests/doctor/test_checks.py`, `tests/memory/test_doctor.py`, `tests/attach/test_doctor.py`, `tests/overlay/test_doctor.py`
- Modify: `tests/test_areas.py`, `mutations/install.toml`, `mutations/records.toml`, `mutations/attach.toml`
- Create: `changelog.d/+doctor-report-order.change.md`

**Interfaces:**
- Consumes: Task 4's `Context`, `Claims`, `Contribution`.
- Produces: `memory` contributes `bundles` and `store-debris`; `attach` contributes `attached` and
  the `claims` for `hook-entries`; `overlay` contributes `pre-commit` and `overlay-requires`. Each
  resolves the overlay root (`config.overlay.overlay_root`) and the store (`memory.api.resolve`)
  through a lazy value the area's `register()` creates, so each `doctor` run gets a fresh one and
  no state crosses runs (tests run many in one process), and nothing about delivery lives in the
  core `Context`. That one helper keeps `_context`'s rule today: a `Failure`, `Refusal` or `OSError`
  from either resolution is `None`, so a `stayfixed.toml` that makes the store refuse yields the
  rows' skips, never "could not run". Resolving the overlay root once per area per run is one small
  file read.
- Keeps in core: `not-initialised`, `versions` (on `semver.later`), `files`, `wrapper`,
  `hook-entries` (provenance from every contribution's `Claims`), `codex-trust`, `budgets`,
  `cli-path`, `ci-ref`, `diagnostics`, `ignored-env`.

The report keeps its sixteen rows; their order changes (core first, then delivery by area), and
`docs/cli.md`'s table follows. What each check says and when it is red do not change: the existing
tests move with their checks, the forged-ledger and unreadable-ledger tests of `hook-entries` in
`tests/doctor/test_checks.py` included.

- [ ] **Step 1: Capture, then write the failing tests.** Before any edit, render `doctor --json` for a
  fixture project that is not attached, with `git diff aed27b6 -- src/stayfixed/doctor` empty, and
  paste the `attached` row. Then: `test_every_check_has_one_row_in_one_report` pins the sixteen
  names, in the new order, as a literal tuple (core: `not-initialised`, `versions`, `files`,
  `wrapper`, `hook-entries`, `codex-trust`, `budgets`, `cli-path`, `ci-ref`, `diagnostics`,
  `ignored-env`; then `attached`, then `bundles`, `store-debris`, then `pre-commit`,
  `overlay-requires`); `test_a_project_with_no_overlay_gets_skips_from_delivery_checks`;
  `test_an_unattached_project_reports_attached_as_it_did` (the captured row, pasted as a literal);
  `test_a_store_that_refuses_skips_the_store_checks` (a `stayfixed.toml` whose `memory.groups` the
  resolver refuses: `bundles` and `store-debris` skip, neither is red).
- [ ] **Step 2: Run.** Expected: FAIL on the order.
- [ ] **Step 3: Implement**; delete the three `src/stayfixed/doctor/checks.py` rows (`len == 1`: `src/stayfixed/setup/run.py`).
- [ ] **Step 4: Run.** `uv run pytest tests/doctor tests/memory tests/attach tests/overlay tests/test_areas.py tests/test_documents.py -q`. Expected: PASS.
- [ ] **Step 5: Docs, fragment, commit.** Fragment: "`stayfixed doctor` lists the same sixteen
  checks in a new order: the installation's own checks first, then the private overlay's,
  binding's and note store's. Anything that parsed the report by position should match on the
  check's name." Commit `refactor(doctor): move the overlay, binding and store checks into their areas`.
- [ ] **Step 6: Mutations, after the commit.** Re-route the moved checks' entries by their new
  `file`; run each. Add (`mutations/install.toml`): (1) in `hook-entries`, ignore the
  contributions' `Claims`. Expected to redden: the existing provenance test that names an
  overlay-granted entry (if none pins it, write `test_an_overlay_granted_entry_is_named_as_the_overlays`
  first). (2) In the store helper, let a `Refusal` escape instead of becoming `None`. Expected to
  redden: `test_a_store_that_refuses_skips_the_store_checks`.

**Pull request 1** (`wp/core-cut-boundary`, Waves A–B): the body states the rule, the one pinned
crossing and why, the twelve-to-one count, and the two user-visible changes (the `--memory-graph`
move, the doctor order).

### Wave C — Task 6

#### Task 6: Delete the two dead session-context bundles and their four slots

**Files:**
- Modify: `src/stayfixed/memory/bundles.py`, `src/stayfixed/memory/commands.py`, `src/stayfixed/memory/api.py`
- Modify: `src/stayfixed/memory/doctor.py` (the `bundles` check's comment), `src/stayfixed/doctor/checks.py` (`NEARLY_FULL`'s comment)
- Modify: `hooks/hooks.json`, `hooks/hashes.json`, `scripts/smoke_hooks.py`
- Modify: `docs/cli.md` (the bundle table, `memory session-context`, `memory fit`), `RELEASING.md`
- Test: `tests/memory/test_bundles.py`, `tests/memory/test_commands.py`, `tests/hooks/test_hooks_json.py`,
  `tests/hooks/test_wrapper.py`, `tests/scripts/test_smoke_scripts.py`, `tests/doctor/test_checks.py`
- Modify: `mutations/records.toml`, `mutations/project.toml`, `mutations/repository.toml`
- Create: `changelog.d/+two-session-bundles-gone.change.md`

**Interfaces:**
- Produces: `Bundle` with `STANDING_RULES` and `VOLATILE_NOTES`; `SLOTS = {STANDING_RULES: 3,
  VOLATILE_NOTES: 3}`; `memory session-context --bundle {standing-rules,volatile-notes}`.
- Removes: `_preset_rules`, `_index`, `_SECTION`, the `index` bundle's harness gate in
  `run_session_context` (one of `hooks.api.detect_harness`'s two callers; Task 8 then removes the
  function with nothing to repoint), the `load_preset` import.
- Keeps, reworded: the warning that a committed `MEMORY.md` has no trust record (`_UNTRUSTED` and
  `_trusted` in `src/stayfixed/memory/commands.py`). It named "index bundles"; a committed index's trust still
  gates the harness link `worktree.py` makes, and `memory index --check` and `memory fit` still
  print it. Its sentence names that consequence instead of the bundle.

- [ ] **Step 1: Write the failing test.** Extend `tests/hooks/test_hooks_json.py`:
  `test_there_are_entries_at_all` pins `== 9`; `test_there_is_one_session_start_entry_per_declared_bundle_slot`
  also pins the order — the dispatcher, `standing-rules` 1–3, `volatile-notes` 1–3. Rewrite
  `test_a_committed_index_is_not_reported_trusted_while_its_bundle_is_empty` as
  `test_a_committed_index_is_reported_untrusted` over its `memory index --check` and `memory fit`
  halves, dropping only its `--bundle index` call.
- [ ] **Step 2: Run.** Expected: FAIL (13 entries, 11 at `SessionStart`).
- [ ] **Step 3: Implement.** Delete the code, the four entries, and the tests and mutation entries
  that exist only for the two bundles (`mutations/records.toml`: "the index bundle is one block
  again…" and the three `_preset_rules` entries; `mutations/project.toml`: "the recommended preset
  imposes a standing rule again"). Update `scripts/smoke_hooks.py` (`EXPECTED_ENTRIES = 9`,
  `EXPECTED_ROWS = 10`, the `INJECTED` table and its comment), its tests, and the
  `mutations/repository.toml` smoke-count entries' `before` and `after`. Fix `bundles.py`'s stale
  "nine numbered slots" docstring. Regenerate `hooks/hashes.json` with the release tooling the
  branch's base carries (the launch graph's F ┄ C edge).
- [ ] **Step 4: Run.** `uv run pytest tests/memory tests/hooks tests/scripts tests/doctor tests/test_manifests.py -q`. Expected: PASS.
- [ ] **Step 5: Docs, fragment, commit.** `docs/cli.md`: the bundle table keeps two rows; drop
  "every bundle but `preset-rules`" and "Emitted on Codex only"; `RELEASING.md` follows. Fragment:
  "Two session-start bundles are gone: `preset-rules`, which no shipped preset filled after 0.2.0,
  and `index`, which only Codex asked for, and Codex does not run plugin hooks. `memory
  session-context --bundle` accepts `standing-rules` and `volatile-notes`; a session starts with
  four fewer hook commands." Commit `refactor(memory): drop the preset-rules and index bundles and their slots`.
- [ ] **Step 6: Mutations, after the commit** (`mutations/repository.toml`, where `hooks/` routes):
  in `hooks/hooks.json`, change the first `volatile-notes --part 1` to `--part 2`. Expected to
  redden: `test_there_is_one_session_start_entry_per_declared_bundle_slot`, through its order
  assertion (the slot count alone already has an entry). Run the moved smoke-count entries.

### Wave D — Tasks 7–8

#### Task 7: Make the harness registry the adapter the hooks core answers through

**Files:**
- Modify: `src/stayfixed/harnesses.py`, `src/stayfixed/gitenv.py`
- Modify: `src/stayfixed/hooks/dispatch.py`, `src/stayfixed/hooks/commands.py`, `src/stayfixed/hooks/api.py`
- Test: `tests/test_harnesses.py`, `tests/hooks/test_dispatch.py`, `tests/hooks/test_hook_command.py`
- Modify: `CONTRIBUTING.md` (the `stayfixed.hooks.api` vocabulary list), `mutations/core.toml`

**Interfaces:**
- Produces, in `gitenv.py`: `checkout_root(cwd: Path) -> Path | None` — today's
  `_walk_to_git_root`, then `_git_toplevel`, moved from `src/stayfixed/hooks/dispatch.py`; it reads no harness
  variable.
- Produces, in `harnesses.py`:

  ```python
  @dataclass(frozen=True)
  class Harness:
      name: str
      marker_dir: str
      settings: tuple[str, ...]
      # The variable this harness names the project root in, if any; the one datum of the
      # payload's reading that differs between harnesses today.
      project_dir_env: str | None
      # How the hook's stdout is shaped: (event name, joined context) -> stdout. Context only.
      render: Callable[[str, str], str]
      # Positive detection, for every harness but the canonical one, which is the fallback.
      detects: Callable[[Mapping[str, str], Mapping[str, Any] | None], bool] | None = None
      render_profile: Callable[[Profile, str], Rendition] | None = None

  CANONICAL: Harness   # CLAUDE: Claude Code's hook schema is the de-facto one

  def detect(env: Mapping[str, str], payload: Mapping[str, Any] | None) -> Harness:
      """The first non-canonical harness whose `detects` answers yes, else `CANONICAL`."""
  ```
  `CLAUDE`: `project_dir_env="CLAUDE_PROJECT_DIR"`, `render` today's `dispatch.render`, no
  `detects`. `CODEX`: `project_dir_env=None`, the same `render`, and `detects` today's two Codex
  rules (`PLUGIN_ROOT` in the environment, or the payload pair `model` and `permission_mode`), with
  the measurement the current `detect_harness` docstring records moving with them. A comment on
  `CODEX.render` cites the design's rule that a harness whose output differs is a different value,
  not a branch, and the delivery spike's observation that Codex 0.160.0 ran no plugin hook.
  `HARNESSES` keeps `(CLAUDE, CODEX)`, the order `init` writes into `agents`.
- Produces, in `src/stayfixed/hooks/dispatch.py`: one canonical reader,
  `read_event(payload: dict[str, Any], env: Mapping[str, str], harness: Harness) -> HookEvent`
  (today's `parse_event`, its project root from `env[harness.project_dir_env]` when the harness
  names one, then `gitenv.checkout_root`), and `_clamp(render, event_name, context, cap)`, which
  binary-searches the largest prefix whose envelope, as the detected harness renders it, fits the cap.
- Removes: `hooks.api.detect_harness`, `dispatch.parse_event`, `dispatch.render` as a module
  function. `HookEvent.harness` carries the detected harness's name; `"unknown"` goes, since
  detection now always answers. (As landed: `HookEvent.harness` is removed too, since no handler
  read it and it was the one field detection changed; `read_event(payload, env)` takes no harness,
  and its root is the first of `harnesses.project_root_variables()`, the canonical value's first,
  then `gitenv.checkout_root`.)

**Why the payload has one reader.** The detected harness is one a repository can choose: a
committed `env` block can set `PLUGIN_ROOT`. So no harness value may change what a handler sees,
and the way to hold that is to give no harness value a reader: every harness's payload goes
through the one `read_event`, and the only thing a harness contributes to it is the name of its
project-root variable. When a harness arrives whose payload genuinely differs, the question of
mapping it without letting a repository pick the mapping is answered then, with that harness's
evidence. A new harness is otherwise a new value: a positive `detects`, a `project_dir_env`, a
`render`.

**Invariants the adapter must not move.** (1) The deny path stays outside every harness: exit
`2`, empty stdout, `stayfixed: refused: …` on stderr, because the design makes that the complete
form of a gate for every harness and JSON an enhancement. (2) The event name is the one the
command line gave: `run_hook` keeps overwriting `payload["hook_event_name"]` before `read_event`.
(3) `render` carries context only: no harness value's output contains a decision key
(`permissionDecision`, `decision`, `continue`). `harnesses` is imported inside `run_hook`, at
function scope, and never at module level of a hook module, so hook discovery still imports
neither it nor the configuration layer. (As landed after review: the claim that holds is the
last one, which `tests/test_areas.py` asserts. A hook process loads the registry before
`run_hook` runs, because the CLI frame builds its parser from every area's `commands.py` and
`src/stayfixed/doctor/checks.py` imports the registry at module level, so the function-scope
imports saved nothing and are module-level imports now.)

- [ ] **Step 1: Write the failing tests.** `tests/test_harnesses.py`:
  `test_an_environment_codex_sets_is_codex` (`PLUGIN_ROOT` beside `CLAUDE_PLUGIN_ROOT`; and the
  Codex payload pair under Claude's variables); `test_no_input_is_claimed_by_two_harnesses` (a
  table of environments and payloads over every value with a `detects`);
  `test_an_input_no_harness_claims_is_the_canonical_harness`; `test_no_harness_renders_a_decision`
  (invariant 3, a deny-shaped context included). `tests/hooks/test_dispatch.py`:
  `test_a_detected_harness_renders_its_own_answer` (a fake value whose `render` returns a marker,
  injected through the registry seam with a `detects` that claims the payload: the marker is
  stdout); `test_a_handler_sees_one_event_whichever_harness_is_detected` (replacing
  `test_the_project_root_comes_from_the_harnesss_own_variable`, whose per-harness root a ruling
  overturned: the same stdin and `CLAUDE_PROJECT_DIR` make the same event, root included, under
  Claude Code, Codex and a value registered first);
  `test_a_harness_registered_first_never_takes_the_root_from_claude_code` (the canonical
  value's root variable is asked first whatever the registry's order);
  `test_an_unknown_harness_renders_the_canonical_shape` (the `hookSpecificOutput` JSON pinned as
  a literal, not compared with `CANONICAL.render`); `test_a_deny_never_goes_through_render`
  (calls `dispatch()` directly with a fake harness whose `render` raises and a denying handler:
  exit `2`, stdout empty, stderr exactly `stayfixed: refused: <name>: <reason>\n`, no
  `internal error`); `test_a_clamped_answer_is_the_detected_harnesss_envelope`.
- [ ] **Step 2: Run.** Expected: FAIL (no `detect`, no fields).
- [ ] **Step 3: Implement.** Move the bodies; make the registry injectable for tests through one
  function the tests replace; rewrite the three tests that read `HookEvent.harness`. (As landed
  after review: no such function. `detect` and `project_root_variables` read `HARNESSES` as every
  other reader does, and the tests replace `stayfixed.harnesses.HARNESSES` itself.)
- [ ] **Step 4: Run.** `uv run pytest tests/test_harnesses.py tests/hooks tests/memory tests/test_areas.py tests/project -q`. Expected: PASS.
- [ ] **Step 5: Document and commit.** `CONTRIBUTING.md`: drop `detect_harness` from the
  `hooks.api` vocabulary; a harness is a value in `harnesses.HARNESSES`, and adding one is a value
  with a positive `detects`, its project-root variable and its `render`. Commit
  `refactor(hooks): answer each harness through its registry value, reading every payload one way`.
- [ ] **Step 6: Mutations, after the commit** (`mutations/core.toml`). Re-anchor "the clamp drops
  the truncation mark" on its new line (its `before` spelled the module-level `render(`). Add:
  (1) in `dispatch`, render with `CANONICAL` instead of the detected harness. Expected to redden:
  `test_a_detected_harness_renders_its_own_answer`. (2) In `detect`, return `CANONICAL` before
  asking any `detects`. Expected to redden: `test_an_environment_codex_sets_is_codex`. (3) Route a
  deny through `harness.render`. Expected to redden: `test_a_deny_never_goes_through_render`.
  (4) Replaced, with the test it held: "the root is read from the detected harness only" (in
  `run_hook`, the event read with no environment under a harness that names no root variable).
  Expected to redden: `test_a_handler_sees_one_event_whichever_harness_is_detected`. (5) "the
  project-root variables are asked in registry order" (`harnesses.project_root_variables`).
  Expected to redden: `test_a_harness_registered_first_never_takes_the_root_from_claude_code`.

#### Task 8: State each harness's capability tier, once, in the code and the README

**Files:**
- Modify: `src/stayfixed/harnesses.py`, `src/stayfixed/doctor/checks.py` (`SETTINGS_FILES`, the `codex-trust` row)
- Modify: `README.md` (new section "What each agent enforces"), `docs/cli.md` ("Hooks": the
  unmeasured Codex exit-2 sentence)
- Test: `tests/test_harnesses.py`, `tests/test_documents.py`, `tests/doctor/test_checks.py`
- Modify: `mutations/core.toml`
- Create: `changelog.d/+harness-tiers-in-readme.change.md`

**Interfaces:**
- Produces:

  ```python
  class Surface(StrEnum):
      GUARDS = "session guards"        # bg-cleanup: a refusal before the command runs
      NOTICES = "session notices"      # test-hygiene, standing rules, volatile notes
      GATES = "repository gates"       # bugs, docs, plan, commit, trail through the reusable workflow
      METHOD = "methodology"           # skills and the AGENTS.md region

  class Tier(StrEnum):
      BLOCKS = "blocks in the session"
      CONTEXT = "context only"
      CI = "CI only"
      INSTRUCTIONS = "instructions only"

  @dataclass(frozen=True)
  class Reach:
      tier: Tier | None                # None: this surface does not reach that agent at all
      evidence: str                    # where the claim was measured, or "unmeasured"
  ```
  (As landed after review: `Reach` also carries `measured_on: str | None`, the agent and version
  the observation was made on, which the README test reads instead of parsing the evidence's
  prose.)
  `Harness` gains `reach: Mapping[Surface, Reach]` and `local_settings: tuple[str, ...]` (Claude
  Code: *.claude/settings.local.json*, the file `attach` merges the overlay's entries into).
  `CLAUDE`: guards `BLOCKS` (the P0 spike's S8), notices `CONTEXT`, gates `CI`, method
  `INSTRUCTIONS`. `CODEX`: guards and notices `None` (the wave-7 delivery spike: no plugin hook
  ran), gates `CI`, method `INSTRUCTIONS` (skills arrived through the plugin; `AGENTS.md`).
- Produces: a runtime reader for the tiers. `doctor`'s `codex-trust` row, when `[stayfixed] agents`
  lists `codex`, names the surfaces `CODEX.reach` says do not reach Codex ("on Codex the session
  guards and notices do not run; the repository gates hold in CI"), which is the fact a Codex user
  needs when they look; it stays a skip, since no Codex measurement makes it red.
- Produces: `doctor`'s settings walk is `settings + local_settings` over `HARNESSES`, the same
  three files `test_the_provenance_walk_covers_every_settings_file` pins today. `attach`'s
  `HOOKS_FILE` and `PROJECT_CODEX` are the overlay's per-project layout, not harness facts, and
  stay in `attach`.

The README states only what was measured: the tier column reads off `reach`, and the one variance
`Tier` allows beyond its surface's usual tier is unobserved, so the README does not suggest one.
The README table is generated from the registry in the test: the test renders the expected
Markdown from `HARNESSES` and asserts the README section equals it, so the table and the code
cannot drift and the README stays a plain file.

- [ ] **Step 1: Write the failing tests.** `tests/test_harnesses.py`:
  `test_every_harness_states_every_surface`. `tests/test_documents.py`:
  `test_the_readme_states_each_agents_reach_as_the_registry_does`. `tests/doctor/test_checks.py`:
  `test_the_codex_row_names_what_does_not_run_on_codex`. Keep
  `test_the_provenance_walk_covers_every_settings_file` as it is: it must pass unchanged.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement**, and write the README section: the table, then two sentences — a
  surface an agent does not reach is held by CI, which every agent's changes pass through; Codex ran
  none of the plugin's hooks when this was measured (Codex 0.160.0), so on Codex the session guards
  do not run until an adapter proves otherwise. In `docs/cli.md`, "Hooks": mark the Codex exit-2
  sentence as unmeasured and point at the README section.
- [ ] **Step 4: Run.** `uv run pytest tests/test_harnesses.py tests/test_documents.py tests/doctor -q`. Expected: PASS.
- [ ] **Step 5: Fragment and commit.** "The README now says, per agent, what stayfixed enforces
  where: on Claude Code the session guards block, on Codex they do not run (Codex ran none of the
  plugin's hooks when measured), and the repository gates hold in CI for both." Commit
  `docs(readme): state each agent's reach from the harness registry`.
- [ ] **Step 6: Mutations, after the commit** (`mutations/core.toml`): (1) set
  `CODEX.reach[Surface.GUARDS]` to `Reach(Tier.BLOCKS, …)`. Expected to redden:
  `test_the_readme_states_each_agents_reach_as_the_registry_does`. (2) Drop the `Surface.NOTICES`
  row from `CODEX.reach`. Expected to redden: `test_every_harness_states_every_surface`. (3) In the
  `codex-trust` row, list no surface. Expected to redden:
  `test_the_codex_row_names_what_does_not_run_on_codex`.

**Pull request 2** (`wp/core-cut-harness`, Waves C–D): the two bundles, the adapter and the tiers;
the body leads with the README table.

## Lane 2 — the CLI, the template and the profiles

### Wave E — Tasks 9–10

#### Task 9: Delete `adopt begin`

**Files:**
- Modify: `src/stayfixed/assess/commands.py`, `src/stayfixed/assess/state.py`
- Modify: `src/stayfixed/config/layout.py` (`ADOPTION_WORD`, `is_adoption_plan`), `src/stayfixed/docs/api.py`
  (the `declared_state` and `lint` re-exports and the docstring paragraph that serves them),
  `src/stayfixed/docs/trail.py` (`declared_state`), `src/stayfixed/project/api.py` (docstring)
- Modify: `skills/init/references/adoption.md`, `skills/init/SKILL.md`
- Modify: `docs/cli.md` (Contents, the `adopt begin` section, the three-shapes paragraph), `README.md`
  (the Commands row and the example block that runs `stayfixed adopt begin`), `CONTRIBUTING.md`
  ("Areas" prose), `docs/methodology/principles.md`
- Test: `tests/test_cli.py`, `tests/assess/test_state.py`, `tests/project/test_journey.py`,
  `tests/project/test_footprint_invariant.py`, `tests/config/test_symlinked_document.py`,
  `tests/config/test_layout.py`, `tests/docs/test_surface.py`, `tests/test_documents.py` (the
  heading floor: 44)
- Modify: `mutations/assess.toml`, `mutations/core.toml`
- Create: `changelog.d/+adopt-begin-removed.change.md`

**Interfaces:**
- Produces: `stayfixed adopt promote` is the one adoption command; `adopting` with an empty
  `enforced` stays a valid shape (written by hand or left by `0.2.0`), and the docs say so.
- Removes: `run_adopt_begin`, `state.begin`, `BEGIN_HELP`, `PLAN_HELP`, `BEGUN`, `KEPT`,
  `NOT_AN_ADOPTION_PLAN`, `NO_SUCH_PLAN`, `PLAN_FAILS`, `NO_TRAIL_STATE`, and four helpers `begin`
  was the only caller of (measured at `aed27b6`): `docs.trail.declared_state`, the `docs.api`
  re-export of `lint` (`src/stayfixed/docs/commands.py` imports `lint` from `docs.plans` itself),
  `config.layout.is_adoption_plan` and `ADOPTION_WORD`.

The tests that used `begin` only as setup keep their purpose: replace the `begin` step with the
state it produced (write `state = "adopting"` with the project's own editor) or with `promote`,
whichever the test is about; `test_a_project_with_no_gate_is_refused_rather_than_installed`'s
`begun` parameter keeps both shapes that way. The `init` skill's adoption reference ends at
`stayfixed assess`, then `stayfixed adopt promote` as gates pass; a written plan stays the
recommended habit, checked by `stayfixed plan check` rather than by a command that gates on it.

- [ ] **Step 1: Write the failing test.** `tests/test_cli.py`:
  `test_adopt_has_promote_and_nothing_else` (the `adopt` group's subcommands equal `{"promote"}`).
- [ ] **Step 2: Run.** Expected: FAIL (`begin` registered).
- [ ] **Step 3: Remove** the command, the code, its own tests and its six "adopt begin …" entries in
  `mutations/assess.toml`, and "an adoption plan is recognised outside [paths] plans" in
  `mutations/core.toml`, with the tests of the four helpers; re-point the setup-only tests; keep the two
  entries whose `reddens` named them ("a promotion writes the state and not the list", "promote
  installs a project that configures no gate") naming tests that still exist; rewrite the skill
  step and the docs; set the heading floor to `>= 44` with its comment's count.
- [ ] **Step 4: Run.** `uv run pytest tests/assess tests/project tests/config tests/docs tests/skills tests/test_cli.py tests/test_documents.py -q`. Expected: PASS.
- [ ] **Step 5: Fragment and commit.** "`stayfixed adopt begin` is gone. `stayfixed adopt promote`
  already moved a project from `initialised` itself, so the minimal path is `stayfixed init`, then
  `stayfixed assess`, then `stayfixed adopt promote` as each gate passes. A project `0.2.0` left in
  `adopting` keeps working." Commit `refactor(assess): remove adopt begin; promote is the one adoption step`.
- [ ] **Step 6: Mutations, after the commit** (`mutations/assess.toml`): in
  `src/stayfixed/assess/commands.py`, `before = '    promotion = common_flags(adopt_sub.add_parser("promote", help=PROMOTE_HELP))'`,
  `after = '    adopt_sub.add_parser("begin"); promotion = common_flags(adopt_sub.add_parser("promote", help=PROMOTE_HELP))'`.
  Expected to redden: `test_adopt_has_promote_and_nothing_else`. Then
  `uv run python scripts/mutation_oracle.py promote`.

#### Task 10: Delete `test audit-entrypoints`

**Files:**
- Delete: `src/stayfixed/guards/audit.py`, `tests/guards/test_audit.py`
- Modify: `src/stayfixed/guards/commands.py`, `src/stayfixed/guards/roots.py` (docstring), `src/stayfixed/assess/probes.py` (docstring)
- Modify: `skills/run-correctness-audit/SKILL.md` (step 4)
- Modify: `docs/cli.md` (the lead paragraph's "Five commands", Contents, the section, the link from
  `assess`), `README.md` (Commands row, the findings sentence, "Two commands are deliberately
  outside that rule")
- Test: `tests/test_cli.py`, `tests/guards/test_commands.py`, `tests/test_documents.py` (the findings
  floor `>= 4`; the heading floor: 43)
- Modify: `mutations/guards.toml`
- Create: `changelog.d/+test-audit-entrypoints-removed.change.md`

**Interfaces:**
- Removes: `run_test_audit`, the `audit-entrypoints` parser, `guards.audit`; the `test` group keeps
  `hygiene` and `attribute`.

- [ ] **Step 1: Write the failing test.** `tests/test_cli.py`:
  `test_the_test_group_has_hygiene_and_attribute` (`{"hygiene", "attribute"}`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Remove** the code, the two command tests, and eleven entries of
  `mutations/guards.toml` — the ten whose `file` is `src/stayfixed/guards/audit.py` and "a scanner that stopped
  discriminating still reports an audit" (`file` in `src/stayfixed/guards/commands.py`) — and every comment
  citing them (around the "an unreadable test file aborts the scan" citation). The README findings
  sentence names four commands; its test's floor becomes `>= 4`, with the comment saying which
  four. The heading floor becomes `>= 43`.
- [ ] **Step 4: Run.** `uv run pytest tests/guards tests/skills tests/test_cli.py tests/test_documents.py tests/scripts/test_mutation_oracle.py -q`. Expected: PASS.
- [ ] **Step 5: Fragment and commit.** "`stayfixed test audit-entrypoints` is gone: it read only
  pytest files and no gate ran it. The `run-correctness-audit` skill no longer calls it." Commit
  `refactor(guards): remove test audit-entrypoints, a pytest-only audit no gate ran`.
- [ ] **Step 6: Mutation, after the commit** (`mutations/guards.toml`): in
  `src/stayfixed/guards/commands.py`, add `test_sub.add_parser("audit-entrypoints"); ` in front of the `hygiene`
  parser's line. Expected to redden: `test_the_test_group_has_hygiene_and_attribute`.

### Wave F — Task 11

#### Task 11: Move the release tooling out of the shipped CLI

**Files:**
- Create: `scripts/release.py`
- Modify: `src/stayfixed/release/` (delete `commands.py` and `notes.py`; from `versions.py` keep only
  `tag_for`; from `hashes.py` keep only the reader half, moving `write_record` and `drift` to the
  script; `api.py` exports only what shipped code imports)
- Modify: `src/stayfixed/areas.py` (the `_has_submodule` docstring naming `stayfixed.release.versions`)
- Modify: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/pull_request_template.md`
- Modify: `CONTRIBUTING.md` (the short-version block, the area list, the changelog paragraph),
  `RELEASING.md`, `README.md` (the "Internal and release" rows and the lead's sentence about
  `release`), `docs/cli.md` (Contents, the three sections, the Shared-flags prose),
  `docs/methodology/principles.md`
- Test: `tests/scripts/test_release.py` (create, from `tests/release/test_versions.py` and
  `tests/release/test_notes.py`), `tests/test_fixtures.py`, `tests/test_manifests.py`, `tests/test_cli.py`,
  `tests/test_areas.py` (`len(areas) == 11`), `tests/config/test_deep_toml.py`, `tests/test_undecodable.py`,
  `tests/outbound/policy.py`, `tests/test_outbound.py`, `tests/test_documents.py` (the heading floor: 40)
- Modify: `mutations/core.toml` (entries out), `mutations/repository.toml` (entries in)
- Create: `changelog.d/+release-commands-are-repository-tooling.change.md`

**Interfaces:**
- Produces: `uv run python scripts/release.py check [--tag TAG]`, `notes --version X.Y.Z [--draft]`,
  `hashes [--check]`, with the exit codes and `--json` shapes of the commands they replace, pinned
  by the moved tests. The script imports from `stayfixed.release`; nothing imports the script.
- Keeps shipped: `stayfixed.release.api` with `Pin`, `Resolution`, `released`, `resolve_pin`,
  `is_released`, `HASHED_FILES`, `RECORD`, `UnreadableRecord`, `digests`, `read_record`, and
  `tag_for` for `pins.py`: exactly what `doctor`, `assess` and `project` read. `doctor`'s five tests
  that wrote a record through `write_record` load the script the way its own tests do. The package
  keeps its name: what stays in it is still about stayfixed's releases (the tags it pins, the
  record of the files a release ships). `release` stops being an area (no `commands.py`, no `hooks.py`), so
  `tests/test_areas.py` counts 11 and `CONTRIBUTING.md`'s area list drops it; `tests/test_surfaces.py`
  still finds its `api.py`.
- Removes: the `release` command group.

Load the script in its tests the way `tests/scripts/test_mutation_oracle.py` loads the oracle, with
`sys.modules[name] = module` before `exec_module` (the script uses `from __future__ import
annotations`, and a dataclass under it resolves types through `sys.modules`). Coverage is measured
over `src/stayfixed` only, so the moved code leaves the denominator; run the full suite with the
floor before committing.

- [ ] **Step 1: Write the failing tests.** Move the version and notes tests to
  `tests/scripts/test_release.py`, calling the script's `main(argv)`; the hash tests that drive the
  CLI move there too. In `tests/test_manifests.py`, rename
  `test_the_repository_itself_passes_release_check` to `test_the_repository_passes_release_check`
  (through the script) and add `test_a_drifted_record_fails_the_hashes_check` (create): a copy of
  the record with one digest changed makes `hashes --check` exit `1` naming that file.
- [ ] **Step 2: Run.** Expected: FAIL (`scripts/release.py` absent).
- [ ] **Step 3: Implement.** Move the code; delete the group; update both workflows to
  `uv run python scripts/release.py check` (`release.yml` with `--tag "$GITHUB_REF_NAME"`), the
  pull-request template, `CONTRIBUTING.md` and every `RELEASING.md` step that names
  `stayfixed release`; update `tests/test_fixtures.py`'s `required` tuple to the new string, so it
  still holds all five places to one spelling; move `tests/config/test_deep_toml.py`'s and
  `tests/test_undecodable.py`'s uses of `release.versions` to the script; drop the
  `src/stayfixed/release/notes.py` row of `tests/outbound/policy.py` and declare the script's `git` calls if it
  makes any; set the heading floor to `>= 40`.
- [ ] **Step 4: Run.** The full suite with coverage, then `uv run python scripts/release.py check`.
  Expected: PASS and `OK`.
- [ ] **Step 5: Fragment and commit.** "The `stayfixed release` commands are gone from the installed
  CLI: they only ever checked this repository's own release, and now live in its
  `scripts/release.py`. Nothing a project runs used them." Commit
  `refactor(release): move the repository's release tooling out of the shipped CLI`.
- [ ] **Step 6: Mutations, after the commit.** Move every `src/stayfixed/release/…` entry whose code moved into
  `mutations/repository.toml` with `file = "scripts/release.py"` and re-anchored `before` lines;
  re-point every `reddens` id under `tests/release/` (25 of them) to its new home; keep the
  `pins.py` and `hashes.py` entries in `core.toml`; run `uv run python scripts/mutation_oracle.py release`.

### Wave G — Task 12

#### Task 12: Retire the overlay template's `attach` skill and `common/rules/`

**Files:**
- Delete: `src/stayfixed/templates/overlay/skills/attach/SKILL.md`, `src/stayfixed/templates/overlay/common/rules/README.md`
- Modify: `src/stayfixed/overlay/layout.py`, `src/stayfixed/overlay/template.py`
- Modify: `src/stayfixed/templates/overlay/README.md` (its file count), `docs/cli.md` ("sixteen files",
  the retired-file paragraphs of `overlay init` and `overlay upgrade`)
- Test: `tests/overlay/test_upgrade.py`, `tests/overlay/test_template.py`, `tests/skills/test_skills.py`
- Modify: `mutations/project.toml`, `mutations/install.toml`
- Create: `changelog.d/+overlay-template-retires-two-files.change.md`

**Interfaces:**
- Produces: `RETIRED_OVERLAY_FILES` gains `RETIRED_ATTACH_SKILL = "skills/attach/SKILL.md"` and
  `RETIRED_RULES_README = "common/rules/README.md"`; `_RETIRED` holds, for each, the digests in the
  Premise and a remedy ("the plugin's own `attach` skill replaces it" / "nothing read this
  directory; a standing rule is a note with `metadata.startup`"). No `SUCCESSORS` entry.

- [ ] **Step 1: Write the failing tests.** `tests/overlay/test_upgrade.py`:
  `test_each_released_copy_of_a_retired_file_is_removed`, parametrised over each released copy,
  recorded and unrecorded overlays, with each released file's bytes held verbatim in the test as
  `SHIPPED_MEMORY_README` is, taken from `git show v0.1.0:<path>` and `git show v0.2.0:<path>` and
  checked against the Premise digest before pasting; `test_an_edited_retired_file_is_kept_and_named`;
  `test_an_overlay_without_the_retired_files_plans_nothing`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Delete `test_no_rendered_markdown_says_a_rules_file_is_injected`
  (`tests/overlay/test_template.py`), whose subject is the deleted README, and the entry that
  reddens it, `mutations/project.toml`'s "the rules directory's README promises injection again".
  In `tests/skills/test_skills.py`, the walk no longer finds a template `attach` skill: if the
  template ships no skill, the walk over it asserts the empty set explicitly, so a re-added
  template skill is still checked.
- [ ] **Step 4: Run.** `uv run pytest tests/overlay tests/skills tests/test_install_path.py tests/scaffold -q`. Expected: PASS.
- [ ] **Step 5: Fragment and commit.** "`stayfixed overlay upgrade` and `overlay init` remove two
  files the overlay template no longer ships: its copy of the `attach` skill (the plugin's own,
  which also covers detaching and a moved remote, is the one that stays) and
  *common/rules/README.md*, which nothing read. A copy you edited is kept and named." Commit
  `refactor(overlay): retire the template's attach skill and its unread rules directory`.
- [ ] **Step 6: Mutations, after the commit** (`mutations/install.toml`): remove the `v0.2.0`
  digest of *common/rules/README.md* from `_RETIRED`. Expected to redden: the unrecorded `v0.2.0`
  case of `test_each_released_copy_of_a_retired_file_is_removed`, named by its exact parametrised
  id (a recorded overlay is removed by its manifest record, not by `_RETIRED`). The kept-when-edited
  and nothing-to-plan paths are the scaffold engine's, already held by `mutations/core.toml`'s four
  retirement entries; the commit message names them.

**Pull request 3** (`wp/core-cut-surface`, Waves E–G): the body lists the command count before and
after (38 to 33 registered), each removal's reason, and the two retired template files.

### Wave H — Task 13

#### Task 13: Move the red-run hint into the Python profile, chosen by the command

**Files:**
- Create: `src/stayfixed/profiles/hints.py`, `src/stayfixed/profiles/python/__init__.py`, `src/stayfixed/profiles/python/hygiene.py`
- Create: `tests/test_language_neutral.py`
- Modify: `src/stayfixed/guards/hygiene.py` (keeps `red_exit`, the dirty-tree count and the lead
  sentence; loses `PYTEST`, `is_pytest_run`, `_segment_runs_pytest` and the bytecode code),
  `src/stayfixed/guards/hooks.py`, `src/stayfixed/guards/commands.py` (`test hygiene`)
- Modify: `docs/cli.md` (`test hygiene`, the `PostToolUse` row), `README.md` (if it names pytest
  for the notice), `CONTRIBUTING.md` ("Areas": a profile may carry code)
- Test: `tests/profiles/test_hints.py`, `tests/profiles/python/test_hygiene.py` (create, moved from
  `tests/guards/test_hygiene.py`), `tests/test_language_neutral.py`, `tests/guards/test_hooks.py`,
  `tests/guards/test_commands.py`
- Modify: `mutations/guards.toml`, `mutations/project.toml`
- Create: `changelog.d/+red-run-hint-from-the-profile.change.md`

**Interfaces:**
- Produces, in `src/stayfixed/profiles/hints.py`:

  ```python
  class RedRunHint(Protocol):
      """A stack's advice after its test runner failed. A profile ships one as `HINT` in its
      `hygiene.py`; the profile's name is its directory's, never a second attribute."""
      def recognises(self, argv: Sequence[str]) -> bool: ...
      def report(self, root: Path, config: Config) -> Mapping[str, int]: ...   # the one walk
      def note(self, counts: Mapping[str, int]) -> str | None: ...             # pure: counts in, one line out

  def hint_modules() -> tuple[str, ...]: ...            # profiles with a hygiene.py, by name
  def shipped_hints() -> tuple[tuple[str, RedRunHint], ...]: ...   # (profile name, its HINT), in name order
  ```
  `note` receives the counts and nothing else, so no path, file name or command text a repository
  authored can reach the line it renders: the trust rule holds by construction, not by each
  profile's care. `hint_modules` lists `profiles/<name>/hygiene.py` through
  `importlib.resources` over the package, never over a repository path; it is the seam tests
  replace, below `shipped_hints`.
- Produces: the `test-hygiene` handler imports `profiles.hints` inside its function body (hook
  discovery must not import `stayfixed.profiles`; `tests/test_areas.py` asserts it), splits the red
  command into simple commands with the existing `bashscan` unwrapping, asks each hint whether it
  recognises each one, and joins `note(report(...))` of those that do after the language-neutral
  dirty-tree line. A hint that raises costs its own note (the handler is `Policy.OPEN`).
  `stayfixed test hygiene` reports, per profile whose `detect` markers sit at the root, that hint's
  `report`; a repository in two stacks gets two entries.
- Produces: `tests/test_language_neutral.py` (create) holds the global constraint over every core
  module, the way `CORE_TO_DELIVERY` holds the boundary: it reads every module under
  `src/stayfixed/` outside `profiles/` with `ast`, finds string constants and identifiers that name
  one stack's runner or artifacts (`pytest`, `.pyc`, `__pycache__`, `node_modules`, `.venv`,
  `uv run`, outside docstrings and comments), and asserts the set of `(module, token)` pairs equals
  a pinned, sized `STACK_NAMED` set whose every row carries its reason as a comment — for example
  `src/stayfixed/ledger/scan.py`'s polyglot exclusion list (it names every common stack's build
  directories so a scan skips them all, which acts on no single stack) and `src/stayfixed/guards/bashscan.py`'s
  `uv run` unwrapping (it reads a command line CI writes, and is neutral in effect). Stayfixed's
  own runtime (`uv tool install stayfixed`) is not a stack a project is written in and is a
  pardoned row with that reason. Equality both ways: a new mention reddens it, and so does a pardon
  whose mention is gone.

**Why selection by command and not by `[stayfixed] profile`:** a repository may be written in several
languages, and `profile` names one. The test command says which stack's runner just failed; the
profile that recognises it is the one whose advice applies, with no configuration. Splitting into
argv drops `is_pytest_run`'s substring fallback for a command `tokenize` cannot read: such a command
gets no Python note, which under-reports rather than misleads, and the commit says so.

- [ ] **Step 1: Write the failing tests.** `tests/profiles/test_hints.py`:
  `test_a_red_pytest_run_gets_the_python_profiles_note` (through the handler, a stale `.pyc`
  fixture); `test_no_recognising_profile_means_no_notice` (a red `cargo test`: no notice, the
  dirty-tree line included, since that line comes only with a recognised run); `test_two_recognising_hints_both_speak` (two fake hint modules
  injected through `hint_modules`, a command each recognises);
  `test_a_hint_that_raises_costs_its_note_not_the_dispatch`;
  `test_the_note_is_a_function_of_the_report` (the Python hint's `note` over a fixed counts
  mapping, pinned as a literal). `tests/test_language_neutral.py`:
  `test_no_core_module_names_a_stack_it_does_not_pardon`, which also asserts it read at least the
  current module count (so an empty walk fails).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement**; move the existing hygiene tests with the code they test, and re-point the
  seven `reddens` ids that name `tests/guards/test_hygiene.py` (three of them on entries whose `file`
  is `src/stayfixed/guards/roots.py`, which stays) to wherever each test now lives. Measure the pardons before
  pinning them: run the walk, read every row it finds, and give each its reason.
- [ ] **Step 4: Run.** `uv run pytest tests/profiles tests/guards tests/hooks tests/test_areas.py tests/test_language_neutral.py -q`. Expected: PASS.
- [ ] **Step 5: Docs, fragment, commit.** `CONTRIBUTING.md`: a profile is a directory of data and,
  optionally, `hygiene.py`; no core module names a stack except the pardons
  `tests/test_language_neutral.py` lists. Fragment: "The note after a failing test run now comes
  from the profile of the stack whose runner failed, so a repository in several languages gets the
  right advice with no configuration. Python's note (stale bytecode, a dirty tree) reads as before;
  `stayfixed test hygiene --json` lists its counts per profile." Commit
  `refactor(profiles): let the profile whose runner failed give the red-run hint`.
- [ ] **Step 6: Mutations, after the commit.** Route the moved bytecode entries to
  `mutations/project.toml` by their new `file`. Add: (1) in the handler, keep only the first
  recognising hint's note. Expected to redden: `test_two_recognising_hints_both_speak`.
  (2) In `src/stayfixed/profiles/python/hygiene.py`, make `recognises` return `True`. Expected to redden:
  `test_no_recognising_profile_means_no_notice`. (3) Call the hint without its guard. Expected to
  redden: `test_a_hint_that_raises_costs_its_note_not_the_dispatch`. (4) In `mutations/guards.toml`:
  insert `PYTEST = "pytest"` into `src/stayfixed/guards/hygiene.py`. Expected to redden:
  `test_no_core_module_names_a_stack_it_does_not_pardon`.

**Pull request 4** (`wp/core-cut-profiles`, Wave H).

## Lane 3 — the ledger engine

The ledger engine becomes one engine over a `Register` value. The bug ledger is its only
configured register in this plan, built from today's keys; wave 9's debt register is a second
value, not a second engine. Byte-identity for the bug ledger is the contract: every index, entry
template, refusal and `--json` object the `bugs` commands produce is unchanged, and so is the
empty index `init` renders, whose digest every project's manifest records. Wave I touches only
`src/stayfixed/ledger/` and one call in `src/stayfixed/project/templates.py`, so it branches from Wave 0 and its captures from
`aed27b6` describe the code it starts from; Wave J rewires `src/stayfixed/memory/graph.py`, which Task 3 creates,
so it starts once PR 1 has merged and the lane's branch has rebased onto it.

### Wave I — Task 14

#### Task 14: Pass a `Register` through entries, the index and the writer

**Files:**
- Create: `src/stayfixed/ledger/register.py`
- Modify: `src/stayfixed/ledger/entries.py`, `src/stayfixed/ledger/index.py`, `src/stayfixed/ledger/write.py`,
  `src/stayfixed/ledger/commands.py`, `src/stayfixed/ledger/api.py`
- Modify: `src/stayfixed/project/templates.py` (`render_index([], …)`)
- Test: `tests/ledger/test_register.py`, `tests/ledger/test_index.py`, `tests/ledger/test_write.py`,
  `tests/ledger/test_entries.py`, `tests/ledger/test_surface.py`, `tests/project/test_templates.py`
- Modify: `mutations/records.toml`

**Interfaces:**
- Produces, in `src/stayfixed/ledger/register.py`:

  ```python
  @dataclass(frozen=True)
  class Schema:
      keys: tuple[str, ...]                    # frontmatter keys, in the order an entry writes them
      required: tuple[str, ...]
      required_unless_void: tuple[str, ...]
      statuses: tuple[str, ...]
      levels: tuple[str, ...]                  # the bug ledger's severities
      evidence_boundary_for: tuple[str, ...]   # levels whose entries need the evidence line
      template: str                            # the body `new` writes, with its placeholders
      sections: tuple[tuple[str, tuple[str, ...]], ...]   # index sections: (heading, statuses)

  BUG_SCHEMA: Schema    # today's module constants, gathered; levels and evidence from config below

  @dataclass(frozen=True)
  class Register:
      """One ledger the engine serves.

      `directory` and `index` must be `[paths]` values the configuration loader validated
      (`src/stayfixed/config/paths.py`: inside the root, no `.git`, no `.stayfixed`): the engine joins them to
      the root and does not check them again. A register built from anything else is a defect."""
      name: str             # "bugs": the command group, and the noun in messages
      title: str            # "Bug reports": the index's heading
      directory: str
      index: str
      ids: Identifiers      # `Identifiers(config.ledger.id_prefix)`
      schema: Schema
      runbook: str | None   # "<[paths] runbooks>/bug-reports.md", the index's link

  def bug_register(config: Config) -> Register: ...
  ```
- Produces: `Entry` keeps `id`, `title`, `status`, `area`, `related`, `body`, `path` as fields and
  carries the register's other keys in `fields: Mapping[str, str]`, read by the schema's key names.
  It has no bug-ledger property: nothing outside `src/stayfixed/ledger/` reads an `Entry` (measured at `aed27b6`:
  the only outside imports of `ledger.api` are `bugs_gate` and `render_index`), and property names
  like `severity` are the bug-ledger literals a second register must not inherit.
- Produces: `load_entries(root, register)`, `parse_entry(text, path, register)`,
  `render_index(entries, register)`, `file_entry(root, register, …)`,
  `next_identifier(root, register, *, fetch)`; `commands.py` builds `bug_register(config)` once
  per run and passes it.

- [ ] **Step 1: Capture.** Confirm `git diff aed27b6 -- src/stayfixed/ledger src/stayfixed/identifiers.py`
  prints nothing; if it prints anything, stop and report. With the unchanged code, render a fixture
  ledger of five entries across every status with `render_index(load_entries(root, config), config)`,
  and the empty index with `render_index([], config)`; paste both texts and their sha256 into the
  report.
- [ ] **Step 2: Write the failing tests.** `tests/ledger/test_register.py`:
  `test_the_bug_register_renders_the_index_byte_for_byte` (the fixture's captured text, as a
  literal); `test_init_renders_the_empty_index_with_the_same_digest` (the captured sha256, as a
  literal); `test_a_second_register_renders_its_own_title_prefix_and_fields` (a test-only
  register: `name="debt"`, `title="Tech debt"`, prefix `TD`, levels `("XS","S","M","L","XL")`, a
  key `impact`; `new` writes a `TD-001` entry with its template, and the index is headed "Tech
  debt" and links no runbook); `test_no_bug_literal_reaches_a_second_registers_output` (its index,
  entry and refusals contain none of `BR-`, `Bug reports`, `bug-reports.md`, `stayfixed bugs`).
- [ ] **Step 3: Run.** Expected: FAIL (no `register` module).
- [ ] **Step 4: Implement.** Thread the register through the three modules; gather the module
  constants into `BUG_SCHEMA`; keep `bugs_dir` only if a caller outside the ledger needs it.
- [ ] **Step 5: Run.** `uv run pytest tests/ledger tests/project tests/assess -q`. Expected: PASS.
  Commit `refactor(ledger): render and write entries for any register, the bug ledger byte for byte`.
  No fragment: no output changes.
- [ ] **Step 6: Mutations, after the commit.** Run `uv run python scripts/mutation_oracle.py ledger`;
  re-anchor each `before` that spelled `config` where the line now spells `register`, keeping its
  `name`. Add (`mutations/records.toml`): (1) in `index.py`, `register.title` replaced by the
  literal `"Bug reports"`. Expected to redden:
  `test_no_bug_literal_reaches_a_second_registers_output`. (2) In `write.py`,
  `register.schema.template` replaced by `BUG_SCHEMA.template`. Expected to redden:
  `test_a_second_register_renders_its_own_title_prefix_and_fields`. (3) In `index.py`, one
  section heading of `BUG_SCHEMA` changed. Expected to redden:
  `test_the_bug_register_renders_the_index_byte_for_byte`.

### Wave J — Task 15

#### Task 15: Pass the register through the checks, the scan and every outside caller

**Files:**
- Modify: `src/stayfixed/ledger/check.py`, `src/stayfixed/ledger/scan.py`, `src/stayfixed/ledger/api.py`
- Modify: `src/stayfixed/docs/plans.py` (the `Fixes` rule), `src/stayfixed/memory/graph.py` (the bracketed-identifier notice)
- Test: `tests/ledger/test_check.py`, `tests/ledger/test_scan.py`, `tests/ledger/test_register.py`,
  `tests/assess/test_gates.py`, `tests/docs/test_plans.py`
- Modify: `mutations/records.toml`

**Interfaces:**
- Produces: `uninitialised(root, register)`, `problems(root, config, register, base)`,
  `register_gate(root, config, register, base)`, `code_mentions(root, config, register)`,
  `entry_citations(root, config, register)`, `renumber(root, config, register, old, new)`. `config`
  stays where a function reads keys that are not the register's (`ledger.code_roots`, every
  `[paths]` value for `document_roots`).
- Keeps: `bugs_gate(root, config, base)` in `src/stayfixed/ledger/check.py`, the signature every gate in
  `src/stayfixed/assess/gates.py`'s table shares (`(root, config, base)`, as `src/stayfixed/ledger/api.py` documents): it
  builds `bug_register(config)` and calls `register_gate`. The gate table does not change.
- Produces: `src/stayfixed/docs/plans.py` and `src/stayfixed/memory/graph.py` read identifiers from `bug_register(config).ids`
  through `ledger.api`; `identifiers()` keeps its other callers.
- Produces: refusal and remedy texts name `register.name`, byte-identical for the bug ledger:
  `LEDGER_REMOVED`, `ENTRY_REMOVED`, `_BASE_UNREAD` and the inline `is stale; run: stayfixed bugs index`.

- [ ] **Step 1: Capture.** With `git diff aed27b6 -- src/stayfixed/ledger/check.py src/stayfixed/ledger/scan.py`
  empty, run the unchanged `problems()` over fixtures that produce each of the four texts above
  (a ledger removed on the branch, an entry removed, an unreadable base, a stale index) and paste the
  rendered findings.
- [ ] **Step 2: Write the failing tests.** In `tests/ledger/test_register.py`:
  `test_a_second_register_without_its_directory_is_inert_while_the_bug_ledger_is_live` (a fixture
  where `docs/bugs/` exists with entries and the test register's directory and index do not:
  `uninitialised(root, td)` is true and `uninitialised(root, bugs)` false, so the second register's
  gate returns the inert verdict while the bug ledger's runs);
  `test_the_gate_judges_a_second_register_against_its_base` (an entry removed on the branch is a
  finding naming `TD-001`); `test_the_bug_ledgers_refusals_are_unchanged` (the four captured
  renderings, as literals).
- [ ] **Step 3: Run.** Expected: FAIL.
- [ ] **Step 4: Implement**; the evidence-boundary rule reads `register.schema.evidence_boundary_for`.
- [ ] **Step 5: Run.** `uv run pytest tests/ledger tests/assess tests/docs tests/memory -q`. Expected: PASS.
  Commit `refactor(ledger): check and gate any register, the bug ledger byte for byte`.
- [ ] **Step 6: Mutations, after the commit.** Run the oracle over `ledger` and `bugs_gate`. Add
  (`mutations/records.toml`): (1) in `uninitialised`, replace `register.directory` with the
  literal `"docs/bugs"` (the bug ledger's directory in the fixture). Expected to redden:
  `test_a_second_register_without_its_directory_is_inert_while_the_bug_ledger_is_live`, because
  the second register then reads the bug ledger's live directory.
  (2) In the removed-entry rule, read identifiers from `BUG_SCHEMA`'s default prefix instead of
  `register.ids`. Expected to redden: `test_the_gate_judges_a_second_register_against_its_base`.

**Pull request 5** (`wp/core-cut-registers`, Waves I–J): the body says what wave 9 gets (a
register is a value) and what this plan proved (byte-identity, a test-only second register).

## The record

### Wave K — Task 16

#### Task 16: Restate the README, `CONTRIBUTING.md` and C5 over the merged cut

**Files:**
- Modify: `README.md`, `CONTRIBUTING.md`, `docs/cli.md`, `docs/methodology/README.md`
- Create: `changelog.d/+upgrading-from-0-2.change.md`
- Test: `tests/test_documents.py`
- Modify: `mutations/repository.toml`

**Interfaces:**
- Consumes: every merged pull request of this plan.
- Produces: the README's lead names what ships in the core and what in the delivery areas, says
  the core is language-neutral and a stack is a profile, carries the capability table (Task 8) and
  this paragraph under it: the one blocking guard judges only backgrounded commands, the same
  command run in the foreground passes, there is no switch that turns a guard off, and a false block
  is a defect to report. `docs/cli.md`'s Contents, headings and lead paragraph match the parser
  (C5 restated); `CONTRIBUTING.md`'s "Areas" reads as one account of core, delivery, `doctor.py`,
  profiles with code, and the harness registry.

- [ ] **Step 1: Write the failing test.** `tests/test_documents.py`:
  `test_the_readme_says_the_guards_have_no_off_switch_and_how_to_pass_one` (the paragraph exists
  under the capability section and names the foreground; "foreground" appears nowhere in the
  README today, so the needle is not already present).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Write** the sections. The "Upgrading from 0.2" fragment collects, in one paragraph a
  user reads before installing, what earlier fragments said one change at a time: three commands
  and one flag gone, two bundles gone, the doctor order, the overlay template's two retired files.
- [ ] **Step 4: Run.** `uv run pytest tests/test_documents.py tests/test_neutral.py tests/skills -q`. Expected: PASS.
  Commit `docs: restate the README and the CLI reference over the cut core`.
- [ ] **Step 5: Mutation, after the commit** (`mutations/repository.toml`): delete the paragraph's
  foreground sentence from `README.md`. Expected to redden:
  `test_the_readme_says_the_guards_have_no_off_switch_and_how_to_pass_one`.

**Pull request 6** (`wp/core-cut-record`, Wave K).

### Wave L — Task 17 (controller-run, owner present)

#### Task 17: Measure the cut, review it, hand over the release

- [x] **Step 1: Counts.** On merged `dev`, re-run the Premise's measurements and record them in
  Findings beside the before counts. Every cell comes from a command, so anyone can re-run them:

  ```bash
  git ls-files 'src/stayfixed/*.py' | wc -l
  git ls-files 'src/stayfixed/*.py' | xargs cat | wc -l
  uv run python -c "import argparse; from stayfixed.cli import build_parser
  def leaves(p):
      for a in p._actions:
          if isinstance(a, argparse._SubParsersAction):
              for sp in a.choices.values():
                  yield from (leaves(sp) if any(isinstance(x, argparse._SubParsersAction) for x in sp._actions) else [1])
  print(sum(leaves(build_parser())))"
  grep -c '^## `stayfixed' docs/cli.md
  ls -d skills/*/ | wc -l; ls agents/*.md | wc -l
  python3 -c "import json;h=json.load(open('hooks/hooks.json'))['hooks'];print({k:sum(len(g['hooks']) for g in v) for k,v in h.items()})"
  grep -c '^\[\[mutation\]\]' mutations/*.toml
  uv run python -c "from stayfixed.areas import area_modules; print(len({m.__name__.split('.')[1] for s in ('commands','hooks') for m in area_modules(s)}))"
  uv run python -c "import tests.test_areas as t; print(len(t.CORE_TO_DELIVERY))"
  git ls-files | wc -l
  ```
  If `build_parser` takes arguments by then, adapt the call and say so beside the number.
- [x] **Step 2: Final review** over the merged `dev` (section 1's seats), on what no single pull
  request's review could see: the boundary as a whole, the README against the code, the lifecycle
  matrix end to end. Each finding is reproduced before it is acted on.
- [x] **Step 3: Publish the plugin from its own repository** (the owner's decision of
  2026-10-05). Before the release, the plugin is published from a repository of its own whose
  root is the plugin, and the marketplace entry names it: `scripts/release.py check --tag` refuses
  a plugin folder of more than 512 files in `HEAD`'s tree, the repository root held 512 on
  2026-10-05 with pull requests free to add more, and moving the plugin into a subfolder here does not help, because the plugin
  directory holds a subfolder plugin whose hook runs a script that calls other files, as
  `hooks/run-hook.sh` does. `RELEASING.md`, section 2, is the step as the release process states it.
- [x] **Step 4: Record** the review's outcome in Findings and hand the owner `RELEASING.md` for
  `0.3.0`, naming the changed release step (`scripts/release.py`).

## Findings

### Counts (Task 17)

| Measure | Before (`aed27b6`) | After (`a920ba1`) |
|---|---|---|
| Lines in `src/stayfixed/**/*.py` | 32,736 (141 files) | 35,879 (154 files) |
| Commands registered by the parser | 38 | 33 |
| Command headings in `docs/cli.md` | 40 | 35 |
| Skills / agents | 14 / 1 | 14 / 1 |
| `hooks/hooks.json` entries (of them `SessionStart`) | 13 (11) | 9 (7) |
| Mutation entries | 1,225 | 1,648 |
| Discovered areas | 12 | 11 |
| Core imports into delivery | 12 | 2 (both in `src/stayfixed/setup/run.py`, the pinned crossing) |
| Tracked files | 476 | 555 |

`build_parser` now takes the registrars, so the command count is
`build_parser(discover_registrars())` from `stayfixed.cli`; `build_parser()` alone registers none.

The cut removed surface, not code. Five commands, four session-start entries, one area and ten of
the twelve crossings are gone, but the source grew by 3,143 lines. The largest growth is in
`attach` (+982), `ledger` (+667, one engine serving any register), `profiles` (+418, the hints the
core no longer holds), `overlay` (+353), `doctor` (+343, contributions and claims) and
`harnesses` (+246, the adapter). Of the 1,678 lines `attach`, `doctor` and `overlay` grew by
together, 962 came from follow-up pull requests merged during the wave (#69, #77, #79, #83) and
630 from the boundary pull request (#68), which moved the delivery checks into their areas
(`git diff --numstat` over each first-parent merge). The largest removals are in `guards` (-454), `release`
(-367, now repository tooling under `scripts/`) and `assess` (-117). Per-area counts:
`git ls-tree -r --name-only <rev> -- src/stayfixed`, summed by top-level module.

### Final review (Task 17)

Four seats reviewed merged `dev` (`a920ba1`): architecture, security, lifecycle and correctness. A
fifth, independent pass reproduced every finding before anything was fixed, and it is the authority
on each finding's true boundary. It confirmed 38 findings: 6 Important, 22 Minor or below plus 10
Nits. Several came out broader than the seat reported (`CONFIRMED-BROADER`), and two narrower.

- **Important:**
  - **`hook-entries` vouched for a whole entry by its command alone.** An `http` entry carrying a
    granted marker read as stayfixed's own. It now compares the entry whole.
  - **The hook path took `HOME` from the environment.** A relative `HOME` from a settings env
    block could select a clone-planted `trust.json`. The hook path now anchors on the password
    database's home (`config/machine.py`, `owner_home` and `anchor_home`).
  - **The release notes described 0.2.0 wrongly in four places:**
    - a write-back story that never happened;
    - the 64 MiB read cap as an unnamed upgrade path;
    - damaged-overlay behaviour from inside the cycle presented as 0.2.0's;
    - an overlay store's trust record called "inert".
- **All findings were fixed in one pull request, `wp/core-cut-measure`,** in six sequential waves:
  - A: what `hook-entries` vouches for, and the harness facts;
  - B: the machine owner's home on the hook path;
  - C: one bounded reader, and one reader per document;
  - D: the boundary guards, now a positive stdlib allowlist and a scope-aware name rule;
  - E: behaviour at the edges;
  - F: the release notes, the documents and this plan's lifecycle matrix.

  Each wave had a task review and scoped re-reviews. A final whole-branch review found one more
  Important issue: an import cycle that `attach --check` introduced. `check` moved to
  `src/stayfixed/attach/check.py`, and the module graph test, since moved under `tests/boundaries/`,
  now counts imports inside functions too. The same
  review found check-versus-run gaps that predate the branch. Eleven cases were measured, and ten
  of them already ended differently in 0.2.0. `attach --check` now calls the run's own refusals
  and planning, so where the run refuses or fails before its first write it ends with the run's
  code and line, past the gates it reports instead: a widening without `--yes` and a mismatch
  without `--trust-remote`, which it reads past, and a checkout with no `origin` and a memory group
  that never moved, which it reports with exit `1`. Outside overlay mode,
  anything past the binding gives way to the run's refusal of the mode. A last scoped
  re-review found two more gaps: the module graph gave a module no edge to the packages above the
  module it imports, and `--check` counted memory groups at a checkout with no `origin`. Both were
  fixed before the push.
- **`PATH` reached git on the hook path; it no longer does.** The owner measured Claude Code 2.1.293
  on 2026-10-07. A committed settings env block's `PATH` reaches project and plugin hooks as
  written, a relative entry resolved against the project, while `HOME` stays the real home and
  `XDG_CONFIG_HOME` empty. The settings reference agrees: project and local settings cannot set
  `HOME` or `XDG_*`, and `PATH` is not on that list. So, by the owner's decision:
  - in a stayfixed the hook wrapper launched, `gitenv` runs the first executable of the wrapper's
    absolute `git` candidates, one list spelled twice and held equal by a test, and hands it a
    `PATH` of their directories and the system's, so a `git-lfs` filter or an fsmonitor program is
    not the clone's either; no candidate is no answer. The wrapper exports
    `STAYFIXED_HOOK_WRAPPER=1` immediately before it runs the launcher, over any inherited value,
    and `gitenv` asks nothing else, so a value set elsewhere can only make git stricter;
  - the wrapper no longer runs `dirname` or `env` by name, which a clone's `fakebin` also reached;
  - the wrapper's first statement unsets every function named for a command it runs, and it
    spells `[` as `test`. The git-path security review found that bash, `/bin/sh` on macOS,
    imports a function from a `BASH_FUNC_<name>%%` variable, also in POSIX mode, and a function
    wins over a regular builtin: `BASH_FUNC_pwd%%` ran a clone's program five times per hook with
    no `PATH` entry at all. The review's one-line fix left `[` open, because bash 3.2 in POSIX
    mode refuses `unset -f [`, and `BASH_FUNC_[%%` still ran it twenty-six times;
  - anywhere else, `git` and its `PATH` are the environment's, as before: at a terminal, and in
    `stayfixed gate` in CI or a command an agent runs, where a fixed list buys nothing (the job is
    the repository's own, and the agent's `PATH` already chose the `stayfixed` binary) and would
    cost a machine whose only `git` is under a Nix store or `/opt/local/bin` every answer. The
    first cut of this fix keyed on "off a terminal", which covered those too; it was narrowed to
    the wrapper, since the owner's decision was for the hook. `HOME` stays kept for git, since
    Claude Code cannot set it.

  Measured against `v0.2.0` through each shipped wrapper and launcher: every hook entry with a
  planted program for every name in `/bin` and `/usr/bin` ran `git`, `git-lfs`, `dirname` and `env`
  from the clone under 0.2.0, and none under the branch, also with the block presetting
  `STAYFIXED_HOOK_WRAPPER=0`. `stayfixed gate` run without the wrapper, stdin not a terminal, ran
  a `git` found only elsewhere on `PATH` under both. One residual cannot be closed inside
  stayfixed: an agent that runs `stayfixed` through its shell tool runs the `stayfixed` that
  `PATH` names, and that `stayfixed` runs the `git` `PATH` names.

  What holds after the review: the hook path looks up no program through the inherited `PATH`
  but the wrapper's contained last-resort `python3`, and no exported function replaces one of
  the wrapper's builtins. What does not: `SHELLOPTS=xtrace` with `PS4='$(program)'` runs the
  program in the harness's own `sh -c` before the wrapper starts, and the wrapper's `/bin/sh`
  acts on both before its first line (measured against `/bin/sh` directly, not through Claude
  Code). `SECURITY.md` puts it out of scope beside the loader variables. Claude Code applies a
  trusted folder's `env` block to every process it starts and treats that as working as
  designed, so there is nothing to report to it either.
- **Every change a 0.2.0 caller must act on is in `changelog.d/+upgrading-from-0-2.upgrading.md`.**
  Other user-visible changes have their own entries and are not repeated there. After the
  pull request's review it holds 46 bullets, one contract each, each pointing at its full entry.

Recorded, not changed:

- **One claimant for the claims protocol.** `doctor`'s `Claims` and `Wording` are shaped for
  several areas, but only `attach` claims entries today. The tuple shape stays until a second
  claimant exists or the next wave's debt register shows none will.
- **Harness detection decides no byte today.** `harnesses.detect` picks a `render`, and every
  harness renders through the canonical one. This plan asked for that shape. It waits for a
  non-steerable signal.
- **`bg-cleanup` judges only the forms `docs/cli.md` names.** That is a command run in the
  background, directly, through `env`, or through `uv run <options>`. `nohup`, `timeout`,
  `command`, `uvx`, `uv tool run` and `bash -c` wrappers are not judged. The owner decided on
  2026-10-07 to document this scope rather than widen the guard.
- **`CLAUDE.md` is still written for a Codex-only project.** Changing it would make `upgrade` remove
  a tracked file. The owner confirmed this on 2026-10-07.
- **The overlay floor's pre-release ordering has no fragment.** No build ever carried a pre-release
  version, so no user can meet the change. `docs/cli.md` states what the floor does.

Left for later, by the owner's decision of 2026-10-07:

1. **Publish the plugin from its own repository (Step 3), as its own pull request.**
   - A generator produces the plugin tree.
   - CI builds it, tests it, and attests the generated tree's digest.
   - The owner pushes it with one command that checks the digest against the attestation, so CI
     holds no credential to a second repository (`RELEASING.md`).
   - The marketplace entry stays here, with a URL source pinned to the tag.
   - The 512-file check moves to the generated tree.
2. **A terminal command that makes the harness memory link** for in-repo and local-only stores when
   `HOME` differs from the password database's home. The hook path no longer makes that link
   itself.

Near limits, as the pull request leaves them:

- `mutations/install.toml` held 181,291 of 196,608 bytes and was split along `doctor/` during the
  review fixes; the largest group file is now `mutations/core.toml`, at 183,007.
- `docs/cli.md` is 498 bytes under the 256 KiB a plugin directory allows one file
  (`tests/test_payload.py`). The next addition needs a split or a cut first.
- An unreadable overlay `codex/` directory makes `attach` fail with an internal error
  (`PermissionError`), as 0.2.0 did. Since the run refuses a missing `origin` before it reads that
  directory, `--check` and the run end on different lines there. It is a defect of the run, left
  for its own fix.
- `hook-entries` reads a frontmatter only within a skill file's first 8,388,608 characters and
  10,000 lines, and names a file past either as one it cannot tell about.

### The pull request's own final review (2026-10-08 to 2026-10-09)

An external review of the pull request at `afbda57`, five seats and a controller pass, found it
not ready to merge: one blocker and six Important findings, with Minors in every area.

- **The blocker:** CI was red on every interpreter it runs, while the pull request reported a
  green suite measured on Python 3.14 alone. `contained()` asked each ancestor with
  `Path.is_symlink()`, which raises on a name past the system's limit up to 3.13 and answers
  `False` from 3.14. Every question about what is at a path now goes through `fsops` predicates
  that answer one way on every interpreter, a test refuses `pathlib`'s, and CI gained a 3.14 leg.
- **Important:**
  - `attach` run from a linked worktree wrote the settings fallback without hiding it;
  - a `HOME` inside the clone still chose the global configuration of hook-path git: every `git`
    on the hook path, the wrapper's own included, now gets the password database's home, so the
    statement above that `HOME` stays kept for git no longer holds on the hook path;
  - `hook-entries` compared a grant field by field; it now compares the whole entry;
  - core `doctor` carried the memory area's harness-link wording; the memory area's own
    `harness-link` row now says it;
  - `src/stayfixed/doctor/entries.py` held three responsibilities; it is split into the
    frontmatter reader, the walk for hooked files and the judgement;
  - the pull request's text, these Findings and two release-note entries misstated facts the code
    settles.

The fixes ran on the same branch, one wave at a time. Each wave was reviewed, then fixed in rounds
until its review found nothing Critical or Important:

- A: one answer to each path fault on every interpreter (one fix round);
- B: behaviour at the edges, and the home the wrapper's git gets, held under zsh as `/bin/sh`, a
  NixOS `id` and a user named by digits (two rounds);
- C: `doctor`'s structure and the frontmatter reader (six rounds, the reader's);
- R: the remaining patterns that read their input in more than linear time or memory;
- E1: the split of `mutations/install.toml` along `doctor/`;
- P: the possessive-repeat bug of Python 3.11.0 to 3.11.4 (one round);
- D: simplifications, and an empty `HOME` read as a value that names no home (one round);
- E: the boundary rules under `tests/boundaries/`, and every quoted mutation name read (three
  rounds);
- F: the documents, the release notes and this record.

Over the review the mutation set grew from 1,858 to 2,129 entries.

The owner's decisions:

- Python's floor stays 3.11, since Debian 12's system Python is 3.11.2. The patterns that 3.11.0 to
  3.11.4 read differently were rewritten to shapes those releases read alike, and CI's
  `checks (ubuntu-latest, 3.11.4)` leg holds them, rather than the floor moving to 3.11.5.
- The frontmatter reader answers "no" only for a frontmatter inside a plain YAML subset it reads
  exactly, and "could not tell" for any other in which no reading finds `hooks`. Claude Code
  2.1.293 was one of the four oracles it was measured against. An oracle of Claude Code's own
  parse kept in the repository is left as an improvement after the release, one an outside
  contributor may take.
- The wrapper's list of `git` paths stays spelled twice, the two held equal by a test.
- From 2026-10-09 only a Critical or Important finding opened another round. Every Minor went to
  the follow-ups below.

Decided during the review, as the hook and an unapproved store already behave: `attach` off a
terminal, where `HOME` is not the database's home, withholds only the harness memory link and says
so, and `detach` withdraws a link to the store under both homes.

Not settled here: the review's first point on the pull request's text, how `HOME` reaches a hook,
waits on the owner.

Follow-ups, to file when the pull request closes:

- `setup` writes the machine file before it finds that `--home` cannot be written, and ends in an
  internal error when `--home` names a directory it cannot create.
- What Claude Code does with an empty `HOME`, which the tests take to be a relative `.claude`, is
  unmeasured.
- An oracle of Claude Code's frontmatter parse for the skill reader.

### Pre-dispatch review (2026-10-04)

Three read-only seats reviewed this plan before its first dispatch, one per lens, against
`aed27b6`: premise (24 findings), oracle (27), boundary (7 of 19 anchors not holding). Every
finding that names the tree was reproduced before it was acted on, and every one was taken into
the text above. The two critical ones: the adapter task removed `detect_harness` while
`src/stayfixed/memory/commands.py` still imported it, which would have broken every CLI run until the bundles were
deleted (the bundles now go first, in Task 6); and Task 15 tested an "uninitialised" finding the code does
not emit (the test now pins the inert verdict over a fixture with a live bug ledger). Structural
changes the review caused: the ledger's wave split in two (now I and J); `overlay_root` moved to a new
`src/stayfixed/config/overlay.py` (create) because `src/stayfixed/config/loader.py` imports `src/stayfixed/config/machine.py`;
the ignore block moved to `src/stayfixed/config/layout.py` because `src/stayfixed/project/ignored.py` already defines
`IGNORED`; the doctor vocabulary defined in `src/stayfixed/doctor/model.py` (create) and re-exported, as
`tests/test_surfaces.py` requires; `Claims` made to carry the `None` answers `hook-entries` gives
today; harness detection made order-free so `HARNESSES` keeps the order `init` writes (since made positive, below); the
adapter's four invariants written down, because a repository can choose the detected harness;
the oracle run after each commit, since it proves `HEAD`; byte captures taken from unchanged code
before the first edit.

A second, final review read the revised plan for redundancy, architectural elegance and the
security of its design, against `aed27b6`. Two findings blocked dispatch and were taken: core
`overlay_root` raises the loader's `MachineConfigError` and memory's duplicate class goes (raising
memory's from core would have been a hidden crossing); and the payload has one canonical reader,
with a harness contributing only its project-root variable, so the rule that a
repository-selectable harness never changes what a handler sees holds by construction rather
than by a test over the shipped values. Also taken: the bundles go before the adapter, so nothing
is rewired only to be deleted; detection is positive with the canonical harness as the fallback,
so a new harness is a new value; `Entry` carries no bug-ledger property; the four `begin`-only
helpers are named; the release record's writer leaves the package; per-area lazy values replace a
shared cache, and the never-assigned `store_refusal` goes; a hint's note is a pure function of its
counts, which keeps repository text out by construction; language neutrality is held over every
core module with named pardons; core's licence to name delivery's paths and keys is written down;
`_clamp` takes the harness's `render`; the tiers gained a runtime reader in `doctor`; waves run in
lettered order; the ledger's write side branches from Wave 0. One suggestion was declined: renaming
the residual `release` package, whose remaining code is still about stayfixed's releases.

### The fix lane folded into the boundary PR (2026-10-04)

About fifteen commits of the pull request that carries Lane 1 fix behaviour that shipped in 0.2.0:
committed ledger and settings-file shapes that turned `hook-entries` or `attached` into "this check
could not run", or turned a marked entry's red into a warning and an exit of 0. The Scope above
sends the migration journal's defects to a separate fix lane, and Task 5 says that what each moved
check says and when it is red do not change; both were set aside for these fixes, deliberately.
The reason is `Claims`. Its record/grant split — an area may record from repository bytes, may
grant only from this machine's state, and only the same area's record and grant together absolve
an entry — was shaped by those fixes, and so were the `None` answers it carries. A boundary change
without them would have shipped a `Claims` protocol already known to be wrong, to be reworked by
the fix lane right after.

One consequence stays open. `Claims` is area-neutral, while `hook-entries` still words its
sentences and remedies in `attach`'s vocabulary: `.stayfixed/local/attach.json`,
`stayfixed attach --store …` and `stayfixed setup --overlay`. The owner deferred that to a
separate change before Task 8, which gives `Claims` a printable vocabulary of its own so the core
composes neutral sentences.

### After #84 (2026-10-14)

Pull requests #85, #86 and #88 built the means to publish the plugin from a repository of its own
and to pin the commit the marketplace entry names (#87 fixed a git timeout read as a broken
repository on the way). Nothing is published until `0.3.0`: Task 17 Step 3 stays open until that
release publishes the plugin, and is ticked by the pull request that returns the release to `dev`.
It was: `0.3.0` published the plugin commit `d34a4f0` to `stayfixed/stayfixed-plugin` on
2026-10-14, as that repository's `main` and `v0.3.0`.
The residuals this wave and wave 7 left reproducing on `dev` at `5f6db9f` were closed by #89
(`attach`, `detach`, `doctor`'s `attached` row, `memory index`) and #90 (`setup`, `init`,
`docs trail`, the commit and hook guards, the Codex prose), both merged before the release.
