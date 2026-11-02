# Tags, owner-held checkout files, and the platform without a pack — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **The lettered wave is the dispatch unit, not the task.** This overrides the skill's default of a
> fresh subagent per task: one implementer per wave (A–E below), each task inside it keeping its own
> failing test, verification and commit. No review per wave: one final review for the PR, one scoped
> re-review, then stop (see "Execution contract").

**Goal:** an overlay can give a set of projects shared content through tags, a new linked worktree of
a bound checkout gets the owner-held files its main checkout has, and a checkout bound with no
`stayfixed.toml` gets its memory.

**Architecture:** one core module, `config/plates.py`, reads a bound project's tags and lists its
plates in the one precedence order (`common`, each tag in list order, `projects/<name>`); every
reader of the overlay's layers — the value layers, the rules, the permission and hook union, the
rendered plugin, the Codex rule files, the composed memory store — iterates that list instead of
naming two directories. A checkout's configuration with no `stayfixed.toml` comes from one core
seam, `config.session.bound_config`, which `doctor` and every memory command already needed. The
owner-held files reach a new linked worktree through an `attach` `SessionStart` handler matched by
the binding.

**Tech stack:** Python ≥ 3.11 standard library only; pytest with xdist; `scripts/mutation_oracle.py`.

**Design:** the design this implements is not public (`CONTRIBUTING.md`, "Plans"); this plan
restates every requirement it relies on, under "Global constraints" and "Decisions this plan takes".

**Base:** the integration branch `next`, after the PR that splits the hints out of `guards` and adds
the three-sided ownership test merged into it. This plan names the post-merge tree; pre-flight (below)
checks it.

## Global constraints

- `CONTRIBUTING.md` holds: runtime imports the standard library only; every write through `fsops`;
  path questions through `fsops.is_file/is_dir/exists/is_symlink`; repository bytes are data and a
  name a repository chose prints through `stayfixed.printed`; a control names its adversary and its
  anchor; each declared mutation reddens; `docs/cli.md`'s **Writes** paragraphs enumerate every path.
- `attach`, `memory` and `overlay` are delivery areas; `config` is core. Core imports no delivery
  area (`tests/boundaries/test_delivery.py`). Everything this plan adds that core needs lives in core.
- `attach/api.py` and `memory/api.py` gain nothing unless a task says so: another lane edits them.
- Never copy a `.env*` file or `settings.local.json` into a worktree.
- A tag is read from `projects/<name>/project.toml` of the project this machine's binding record
  names, never from anything in the repository.
- One precedence for values and item names: `common`, the project's tags in list order,
  `projects/<name>`, then the machine file; a later plate wins. Content otherwise unions.
- A collision between two tags is a `doctor` warning, never a refusal.
- No new `doctor` row: the row count is pinned in several files other work also edits.
- Tests and tries use a scratch `HOME` and a fixture overlay, never a real one. Run the oracle
  locally only with a pattern naming this plan's entries.
- English in code, commits and the PR; no AI attribution; conventional-commit subjects.

## Decisions this plan takes

1. **Tag names:** `\A[a-z0-9][a-z0-9-]{0,39}\Z` (`plates.TAG`). A named cap: the name becomes a
   directory name, a link name, an exclude-free index heading and a TOML string, and forty characters
   is past every tag a person types. A tag outside it is skipped with a note, never a refusal.
2. **A tag's memory link name** in the composed store is `tag-<tag>` (`store.TAG_LINK_PREFIX =
   "tag-"`). The store's other link names are `developer` (the common notes), `MEMORY.md`, and each
   directory under `projects/<name>/memory/`. So the project side gives up the `tag-` prefix: a
   project memory directory whose name starts with `tag-` is not linked, and `doctor` names it. One
   rule, `store.reserved(name)`, folds that with the existing `developer` exclusion.
3. **A tag's memory is linked only when `groups/<tag>/memory/` is a directory.** A dangling link
   would take a note the agent writes through it into nowhere; creating the directory later is picked
   up by the next `attach`.
4. **The project record keeps every byte it did not write.** `attach` writes `remote` and
   `first_attach` into `projects/<name>/project.toml` only where the parsed record has no such key at
   all, and it prepends them (top-level keys before any table), so `tags`, comments and every other
   key stay byte for byte. A key present with an unusable value (an empty `remote`) is left as is: a
   second spelling of it would make the file invalid TOML.
5. **The project record has one reader**, core `plates.read_record`, raising what it meets;
   `memory.store.read_binding_record` stays (its callers read strings) and becomes a filter over it.
6. **Re-attach takes back an allow rule the overlay no longer grants** where the attach ledger
   recorded it and the settings file still holds it. Without this, untagging a tag leaves its
   allow rules in place until `detach`, which is true today of a rule removed from `common/` or
   `projects/<name>/` too.
7. **Owner-held files** go into a new linked worktree from an `attach` `SessionStart` handler,
   `owner-files`: a linked worktree of an ordinary checkout, bound on this machine; every regular
   file directly inside `<overlay>/projects/<project>/checkout/`, except `.DS_Store`, any `.env*` and
   `settings.local.json`; only where nothing (file, directory or link) is at the name; created
   exclusively, never through a link. The handler prints what it placed and nothing when it placed
   nothing. `attach` itself places nothing in the main checkout.
8. **A checkout's configuration with no `stayfixed.toml`** is `bound_config`: the preset's under the
   overlay's layers, for the project the binding record names, where this machine binds the
   checkout; `None` otherwise. `session_config` is not changed: the hooks of the methodology side keep
   answering nothing where the checkout has no file. Every memory reader and `doctor`'s
   `attach_config` go through `bound_config`.

**Measured, not fixed:** whether notes the harness writes as plain files at the composed store's top
level (outside every link) are lost to the overlay. On the owner's machine on 2026-11-02, read-only:
9 composed stores, 0 entries at the top level that are not links, and 0 index lines in any project's
index naming a note outside a group directory. Not live, so no change; the composed store's docstring
already says a file there is a note the harness wrote and nothing removes it.

## Execution contract (the controller copies the relevant part into every brief)

1. **Final review:** one for the PR, three seats, read-only, beside each other: correctness;
   "what can be deleted / who does this refuse"; security (this change decides what reaches a
   worktree and a session: the binding, delivered files, the composed store, allow rules). Reviewers
   report findings with no replacement text. Only correctness and requirement gaps go back to an
   implementer; Minors become follow-ups. One scoped re-review of the fix commits, then stop.
2. **Lifecycle matrix:** the table below, checked at pre-flight and again by the correctness seat.
3. **Parallelism:** implementers serialise (one worktree). Review seats run beside each other. One
   oracle run at a time per machine; a run that finds the lock held waits and retries.
4. **Templates:** a fix brief folds sibling instances into one rule or deletes them, never adds a
   guard to each; it carries a net budget (src and tests together, from the review package's
   `--shortstat`). A security ruling names its anchor's provenance first and one legitimate user it
   must not refuse.
5. **Verification:** focused runs while iterating, one full suite before each push; paste what a
   command printed; a predicted mutation outcome is a hypothesis until the oracle prints it. The
   controller re-verifies only heads it pushes.

**Implementer briefs carry:** report a mismatch between plan and tree instead of guessing; no line
numbers from this plan; write nothing under the repository but the wave's change; a private scratch
subdirectory per agent; never kill a process by a name pattern; no `git checkout/restore/stash/clean`
on files you did not create; scratch `HOME` only. **Reviewer briefs:** no nested agents; no git
command that changes the tree.

**Net size,** printed in every review package and the PR body:
`git diff --shortstat origin/next HEAD -- src tests mutations docs`. Estimate: src +0.7–1.0k,
tests +1.5–2.5k.

## Pre-flight (controller, after merging `origin/next`)

- [ ] `tests/boundaries/test_delivery.py` puts `attach`, `memory`, `overlay` on the delivery side and
  `config` in the core; a new core module `config/plates.py` needs no pinned row.
- [ ] `grep -rn "config.memory.groups if g in store.groups" src/` lists the walk sites Task 7 folds
  (expected: `memory/commands.py`, `memory/doctor.py`, `memory/hooks.py`, `memory/bundles.py`,
  `memory/index.py`, and `memory/refs.py` unless it was deleted).
- [ ] `doctor`'s row count is unchanged by this plan (no task adds a row).
- [ ] The lifecycle matrix rows name a test or a check each.

## Lifecycle matrix

"Next attach" means `stayfixed attach` run again in the main checkout. Values and rules are read per
session, so they need no attach.

| Change | Values (`stayfixed.toml` layers) | Rules (standing, path-scoped) | Hooks, skills, agents (render), Codex rules | Allow rules | Memory (store links, index) | Owner-held files |
|---|---|---|---|---|---|---|
| tag (add to `tags`) | next session (T2) | next session (T3) | next attach; `doctor` digest drift until then (T3) | next attach adds (existing) | next attach links `tag-<t>` (T6); index drifts until `memory index` (existing `--check`) | unaffected |
| change a tag's content | next session | next session | next attach; digest drift | next attach adds | notes live through the link | unaffected |
| untag | next session | next session | next attach drops them (render takes back what the overlay no longer holds) | next attach takes back (T4) | next attach unlinks (`build` keeps exactly the current set, T6); index drifts until `memory index` | unaffected |
| rename a tag (rename `groups/<a>` and the list entry) | as untag + tag | as untag + tag | as untag + tag | as untag + tag | link `tag-a` → `tag-b`; the notes' reviewed records are keyed by path, so they read as unreviewed again once (stated in `docs/cli.md`) | unaffected |
| a listed tag with no `groups/<t>/` | skipped, note | skipped | skipped | skipped | no link | — |
| list order changed | later tag wins (T2) | later tag's rule wins its name (T3) | later tag's file wins its path; hooks union in the new order (T3) | union, unchanged | index sections follow list order after `memory index` | — |
| two tags hold one item or key | later wins | later wins | later wins | union | union | `doctor` warns (T5) |
| move a path: overlay root | per machine file, as today | as today | next attach re-renders | as today | next attach rebuilds links (as today) | handler reads the machine file each session |
| move a path: worktree removed / checkout moved | — | — | — | — | — | binding is in the git common directory; nothing to undo |
| fail part-way (an unreadable tag file) | that layer sets nothing, note (T2) | `Failure`, no rule read (as a common rule file today) | `read_parts` reads every source before any write: attach stops with nothing written (T3) | diff read before writes (as today) | `build` error names the data directory (as today) | per-file `OSError` skips that file; any other fault: nothing said, session goes on (T11) |
| undo: detach | — | unbound: nothing | render removed whole (as today) | ledger's rules taken (as today) | every link taken (as today), the record and its `tags` kept | placed files stay: they are the owner's copies in the owner's worktree (stated in `docs/cli.md`) |
| no `stayfixed.toml`, bound | `bound_config` (T8) | as today | as today | as today | memory commands and bundles work (T8) | handler acts on the binding, not the file |

## Review focus

1. A repository with a tracked `AGENTS.md`: a new worktree has it from the branch, so nothing is
   placed and nothing is said (T11, `test_a_tracked_name_is_left_to_the_branch`).
2. An owner who hand-edits `project.toml` with comments and a `tags` list before the project's first
   attach on a second machine: every byte survives (T1).
3. A tag that is also a project's memory directory name: both reach the session, under two names
   (T6, `test_a_tag_and_a_project_group_of_one_name_both_link`).
4. A checkout nothing binds and with no `stayfixed.toml`: still refused with the `init` remedy by
   every memory command (T8).
5. A worktree of a bare repository, a submodule, and the main checkout: nothing placed (T11).

## Launch graph

Drawn last, over each task's Consumes.

```
A (T1 plates, record; T2 value layers) ──┬─► B (T3 delivery through plates; T4 allow take-back; T5 doctor)
                                         └─► C (T6 tag links; T7 walk seam)
D (T8 bound_config; T9 doctor row; T10 --check names the project)   — imports nothing from A–C
E (T11 owner-held files)                                            — imports nothing from A–D
```

Writers of one worktree serialise, so the order is A, B, C, D, E. D and E consume nothing from A–C;
T5 consumes T2 (`Layer.label`) and T3; T6 consumes T1 (`plates`, `tags_of`); T7 consumes T6.

| Wave | Tasks | Plan lines (est.) | Why one context |
|---|---|---|---|
| A | 1–2 | ~150 | the plate list and its first reader |
| B | 3–5 | ~170 | every `attach` reader of plates, and the report on them |
| C | 6–7 | ~120 | the composed store and the walk over it |
| D | 8–10 | ~130 | one configuration seam and the two reports that assumed a file |
| E | 11 | ~90 | a hook, git, `fsops`; no other task's code |

---

## Wave A — Tasks 1–2

### Task 1: the plate list, and a project record that keeps what `attach` did not write

**Files:**
- Create: `src/stayfixed/config/plates.py`
- Modify: `src/stayfixed/memory/store.py` (`read_binding_record` over `read_record`)
- Modify: `src/stayfixed/attach/write.py` (`_record_project`)
- Test: `tests/config/test_plates.py` (new), `tests/attach/test_write.py`

**Interfaces:**
- Produces, in `stayfixed.config.plates`:
  - `COMMON = "common"`, `GROUPS = "groups"`, `PROJECTS = "projects"`, `RECORD = "project.toml"`,
    `TAG: re.Pattern[str]` (decision 1).
  - `class PlateKind(StrEnum)`: `COMMON = "common"`, `TAG = "tag"`, `PROJECT = "project"`.
  - `@dataclass(frozen=True) class Plate: kind: PlateKind; name: str; directory: Path` — `name` is
    `"common"`, the tag, or the project.
  - `read_record(path: Path) -> dict[str, Any]` — the parsed TOML table, through
    `fsops.read_regular_text`; raises `OSError`, `UnicodeDecodeError` and `config.reading.UNPARSEABLE`
    as met.
  - `tags(overlay: Path, project: str) -> tuple[tuple[str, ...], tuple[str, ...]]` — the usable tags
    in list order, each once, and the notes: record unreadable or not TOML, `tags` not a list of
    strings, a name outside `TAG`, `groups/<tag>` not a directory. No record, or no `tags` key: `()`,
    no note.
  - `plates(overlay: Path, project: str) -> tuple[tuple[Plate, ...], tuple[str, ...]]` — `common`,
    each usable tag, the project; the project plate is present whether or not its directory exists
    (readers already handle an absent share).
- `overlay_layers.COMMON` and `.PROJECTS` become imports from `plates` (one spelling in core).

- [ ] **Step 1: failing tests** in `tests/config/test_plates.py`:
  - `test_plates_are_common_then_tags_in_list_order_then_the_project` — record
    `tags = ["b", "a"]`, `groups/a/`, `groups/b/` → kinds `[COMMON, TAG, TAG, PROJECT]`, names
    `["common", "b", "a", "<project>"]`.
  - `test_a_tag_listed_twice_is_one_plate`.
  - `test_a_tag_outside_the_grammar_is_skipped_with_a_note` — `"../x"`, `"X"`, `""`, 41 chars: no
    plate; one note each, naming the tag through `printed.quoted`.
  - `test_a_tag_with_no_directory_is_skipped_with_a_note`.
  - `test_tags_that_are_not_a_list_of_strings_are_a_note` — `tags = "a"`, `tags = [1]`.
  - `test_an_unparseable_record_gives_no_tags_and_a_note`.
  - `test_no_record_gives_no_tags_and_no_note`.
  - `test_the_repository_cannot_name_a_tag` — the checkout's `stayfixed.toml` carries
    `[project] tags = ["a"]` (or any spelling): the loader refuses or ignores it as an unknown key,
    and `plates` for the bound project lists no tag. (Holds the anchor: tags come from the record.)
  In `tests/attach/test_write.py`:
  - `test_attach_keeps_every_key_and_byte_of_the_record_it_did_not_write` — a record holding a
    comment, `tags = ["a"]` and a `[notes]` table and no `remote`: after `attach`, the file is
    `'remote = "<origin>"\nfirst_attach = "<today>"\n' + original`, and it parses.
  - `test_attach_writes_no_key_the_record_holds_unusable` — `remote = ""`: the file is unchanged
    but for a prepended `first_attach` if absent, and parses.
- [ ] **Step 2:** run them; they fail (`ModuleNotFoundError`, then the rewrite).
- [ ] **Step 3:** implement `plates.py`; `read_binding_record(record)` returns
  `{k: v for k, v in read_record(record).items() if isinstance(v, str) and v}` and its docstring names
  `read_record` as the one reader; `_record_project` reads the raw table (or none), writes only the
  keys absent from it, prepending `tomlout.dumps({"": missing})` to the existing text through
  `fsops.write_within`; nothing written where nothing is missing.
- [ ] **Step 4:** focused run green; `uv run mypy`; `uv run ruff check . && uv run ruff format --check .`.
- [ ] **Step 5:** mutation entries (group by `GROUP_OF`): "plates keeps the tags in sorted order
  instead of list order" (→ the order test); "attach rewrites the whole project record" (→ the
  byte test). Run `uv run python scripts/mutation_oracle.py "plates keeps"` and the second by its
  name; paste both.
- [ ] **Step 6:** commit `feat(config): read a project's tags into one ordered list of plates`.

### Task 2: tag value layers

**Files:**
- Modify: `src/stayfixed/config/classes.py` (`LayerName.OVERLAY_TAG = "overlay tag"`, in `ORDER`
  between `OVERLAY_COMMON` and `OVERLAY_PROJECT`, admitted wherever `OVERLAY_COMMON` is; `Layer`
  gains `label: str = ""`)
- Modify: `src/stayfixed/config/overlay_layers.py` (`read` iterates `plates`)
- Test: `tests/config/test_overlay_layers.py`, `tests/config/test_classes.py`

**Interfaces:**
- Consumes: `plates.plates`, `Plate`, `PlateKind` (Task 1).
- Produces: `overlay_layers.read(root, *, machine)` returns one `Layer` per plate that has a readable
  `stayfixed.toml`, lowest first: `OVERLAY_COMMON`, then `OVERLAY_TAG` per tag with `label` = the
  tag, then `OVERLAY_PROJECT`; the notes include `plates`' notes. `Layer.label` is what Task 5 names
  a colliding tag by. `classes.resolve` ranks by `ORDER` with `sorted`, which is stable, so two tag
  layers keep list order.

- [ ] **Step 1: failing tests:**
  - `test_a_later_tag_wins_a_value_and_the_project_wins_over_every_tag` — `common` sets
    `memory.mode = "harness"`, tag `a` `"overlay"`, tag `b` `"local-only"`, list `["a", "b"]` →
    `local-only`; the project sets `"overlay"` → `overlay`.
  - `test_reordering_the_tags_reorders_the_win` — list `["b", "a"]` → `overlay`.
  - `test_a_tag_layer_is_admitted_where_the_common_layer_is` — `ALLOWED[c]` contains `OVERLAY_TAG`
    exactly where it contains `OVERLAY_COMMON`, for every class.
  - `test_an_unbound_checkout_reads_no_tag_layer` — a record with tags; the checkout is not bound →
    the common layer only.
  - `test_a_tag_file_that_is_not_toml_is_a_note_and_no_layer`.
- [ ] **Step 2:** run; fail.
- [ ] **Step 3:** implement; provenance for a tag layer prints `overlay tag <label>` wherever a
  provenance word is printed (find the printers by `LayerName` use; the label is owner-written and
  passes `TAG`, so it prints as is).
- [ ] **Step 4:** focused green; mypy; ruff.
- [ ] **Step 5:** mutation: "tag layers rank above the project layer" (swap in `ORDER`) → the first
  test. Oracle with its name; paste.
- [ ] **Step 6:** commit `feat(config): a project's tags set values between common and the project`.

## Wave B — Tasks 3–5

### Task 3: every `attach` reader iterates the plates

**Files:**
- Modify: `src/stayfixed/attach/rules.py` (`read`), `src/stayfixed/attach/permissions.py`
  (`_claude_sources`, `codex_rules`), `src/stayfixed/attach/render.py` (`read_parts`)
- Modify: `docs/cli.md` (`attach`: the tag plates in "Reads", the precedence sentence; `detach`
  unchanged), `README.md` where it lists what the overlay holds
- Test: `tests/attach/test_rules.py`, `tests/attach/test_render.py`, `tests/attach/test_write.py`
  (Codex rules, permissions)

**Interfaces:**
- Consumes: `plates.plates` (Task 1).
- Produces (signatures unchanged): `rules.read(overlay, project)`; `codex_rules(binding)`;
  `_claude_sources(binding, name) -> tuple[tuple[Path, Path | None], ...]` (one pair per plate:
  `(plate.directory / PROJECT_CLAUDE / name, share)`, `share` = the plate's directory for the project
  plate, `None` otherwise); `read_parts(overlay, project, *, command)`. Each reads `plate.directory /
  "claude"` or `/ "codex"` for every plate, so `common/claude` stays where it is.

- [ ] **Step 1: failing tests:**
  - `test_a_tag_rule_arrives_and_a_later_plate_wins_its_name` — `common`, tag `a`, project each hold
    `x.md` with different bodies; tags `["a"]` → the project's body; without the project's file → the
    tag's; rules from all three distinct names arrive in plate order.
  - `test_two_tags_hold_one_rule_name_and_the_later_wins`.
  - `test_a_tag_hook_group_is_rendered_between_common_and_the_project` — each plate's `hooks.json`
    has one `SessionStart` group → three groups, in plate order.
  - `test_a_tag_skill_is_rendered_and_a_later_plate_wins_its_path`.
  - `test_a_tag_codex_rule_is_placed_and_a_later_plate_wins_its_name`.
  - `test_a_tag_allow_rule_is_added` — `groups/a/claude/permissions.json` allow `Bash(x)` → in
    `diff_permissions(...).added_allow`.
  - `test_an_unreadable_tag_file_stops_attach_with_nothing_written` — a tag's `hooks.json` mode
    `0o000`: `attach` fails, the render directory and the settings file are as they were.
  - `test_a_clone_naming_the_project_hears_no_tag_rule` — an unbound clone whose `stayfixed.toml`
    names the project: `standing(root)` is empty (holds the anchor through the new reader).
- [ ] **Step 2:** run; fail.
- [ ] **Step 3:** implement each reader as one loop over `plates(...)[0]`, later entries replacing
  earlier ones by name (rules, Codex) or path (skills, agents), hooks and allow rules appended in
  plate order. No reader keeps a second, two-directory spelling.
- [ ] **Step 4:** focused green; `uv run pytest -n auto tests/attach`; mypy; ruff.
- [ ] **Step 5:** mutation: "a tag's rule replaces the project's rule of its name" (iterate plates
  with tags last) → the first test. Oracle; paste.
- [ ] **Step 6:** commit `feat(attach): deliver each tag's rules, hooks, skills and allow rules`.

### Task 4: re-attach takes back an allow rule the overlay no longer grants

**Files:**
- Modify: `src/stayfixed/attach/write.py` (`_merged_settings`, `_write_ledger`)
- Modify: `docs/cli.md` (`attach`: what a re-attach takes back), `changelog.d/+attach-allow-take-back.fix.md`
- Test: `tests/attach/test_write.py`

**Interfaces:**
- Consumes: `PermissionDiff`, the previous `AttachLedger` (`allow`), and the rules the overlay grants
  now (the union `diff_permissions` computes before subtracting what is held).
- Produces: `PermissionDiff` gains `withdrawn_allow: tuple[str, ...]` — rules the previous ledger
  recorded, the overlay no longer grants, and the settings file still holds. `_merged_settings`
  removes them; the new ledger's `allow` is the previous minus `withdrawn_allow` plus `added_allow`.
  `attach --check` counts them in its summary (`N allow rule(s) would be taken back`).

Adversary and anchor: the ledger is the only witness of which allow rules are `attach`'s
(`write.py`'s module docstring); a rule the owner added by hand that the ledger does not name is never
taken. A legitimate user who must not be refused: an owner whose settings file no longer holds a
recorded rule (removed by hand) — nothing to take, no error.

- [ ] **Step 1: failing tests:**
  - `test_untagging_takes_back_the_tags_allow_rule` — attach with tag `a` granting `Bash(x)`; drop
    the tag; attach again → `Bash(x)` gone from the settings file and the ledger.
  - `test_a_hand_added_rule_the_ledger_does_not_name_stays`.
  - `test_a_recorded_rule_removed_by_hand_is_not_an_error`.
  - `test_check_counts_the_rules_it_would_take_back`.
- [ ] **Step 2:** run; fail.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** focused green; mypy; ruff.
- [ ] **Step 5:** mutation: "re-attach keeps an allow rule the overlay no longer grants" → the first
  test. Oracle; paste.
- [ ] **Step 6:** commit `fix(attach): take back an allow rule the overlay no longer grants`.

### Task 5: `doctor` names what the tags do not resolve

**Files:**
- Modify: `src/stayfixed/attach/doctor.py` (`_delivery`: warning findings), new
  `src/stayfixed/attach/tags.py` (`collisions`)
- Test: `tests/attach/test_doctor.py`, `tests/attach/test_tags.py` (new)

**Interfaces:**
- Consumes: `plates.plates` and its notes (Task 1); `overlay_layers.read` layers with `label`
  (Task 2); `rules.RULES`, `render.COPIED`, `permissions.PROJECT_CODEX` (existing names).
- Produces: `tags.collisions(overlay: Path, project: str, layers: Sequence[Layer]) -> tuple[str, ...]`
  — one sentence per item name or dotted key held by two or more tag plates, naming the kind, the
  name and the tags in list order, and which wins (`the later, <tag>, wins`). A collision between a
  tag and `common` or the project is precedence, not a finding.
- `_delivery` adds one `WARN` `_Finding` when `plates`' notes, `collisions`, or
  (from Task 6 on) `store.reserved_project_groups` are non-empty:
  the clause joins them, the remedy is "rename one of them in the overlay, or reorder `tags` in the
  project's `project.toml`". A red finding still answers first (`_worst`).

- [ ] **Step 1: failing tests:**
  - `test_two_tags_holding_one_rule_name_is_a_warning_naming_both_and_the_winner`.
  - `test_two_tags_setting_one_key_is_a_warning`.
  - `test_a_tag_and_the_project_holding_one_name_is_no_finding`.
  - `test_a_listed_tag_with_no_directory_is_a_warning` (the `plates` note).
  - `test_a_tag_warning_never_hides_a_red_finding` — overlay gone and a collision → red.
- [ ] **Step 2:** run; fail.
- [ ] **Step 3:** implement; names are the owner's (overlay) and pass `TAG`, but item names come off
  the overlay's disk, so each prints through `printed.quoted`.
- [ ] **Step 4:** focused green; mypy; ruff.
- [ ] **Step 5:** no mutation entry: a warning refuses nothing (`CONTRIBUTING.md`: a convenience).
- [ ] **Step 6:** commit `feat(attach): doctor warns where two tags hold one name`.

## Wave C — Tasks 6–7

### Task 6: each tag's notes in the composed store

**Files:**
- Modify: `src/stayfixed/memory/store.py` (`TAG_LINK_PREFIX`, `reserved`, `tag_link`,
  `permitted_roots`, `overlay_group_target`, `_group_targets`), `src/stayfixed/memory/composed.py`
  (`_sources`, `link_sources`), `src/stayfixed/attach/write.py` (`_group_directories`,
  `_check_groups`: create no reserved name), `src/stayfixed/attach/doctor.py` (Task 5's warning
  finding also names `reserved_project_groups`)
- Modify: `docs/cli.md` (`attach`'s store links; the rename row of the lifecycle matrix)
- Test: `tests/memory/test_composed.py`, `tests/memory/test_store.py`

**Interfaces:**
- Consumes: `plates.tags` (Task 1).
- Produces, in `memory.store`:
  - `TAG_LINK_PREFIX = "tag-"`; `tag_link(tag: str) -> str` (`"tag-" + tag`);
    `reserved(name: str) -> bool` — `name == COMMON_GROUP or name.startswith(TAG_LINK_PREFIX)`.
    (`MEMORY.md` needs no place in it: `_sources` takes directories only and sets the index link
    last.)
  - `permitted_roots(overlay, project) -> tuple[Path, ...]` — common notes, each usable tag's
    `groups/<tag>/memory`, the project's `memory/`; callers that took `[1]` take the last element.
  - `overlay_group_target(overlay, project, group)` resolves `tag-<t>` to `groups/<t>/memory` for a
    usable tag `t`.
  - `reserved_project_groups(overlay, project) -> tuple[str, ...]` — directories under
    `projects/<project>/memory/` that `reserved` excludes and are not `developer` (for Task 5's
    finding).
- `composed._sources` adds `tag-<t>` → `groups/<t>/memory` for each usable tag whose `memory/` is a
  directory, and skips every project directory `reserved` names; `build`'s "exactly the current set"
  then adds and takes the tag links with no other change.
- In overlay mode `_group_targets` resolves the configured groups and every `tag-<t>` link present in
  the store.

Adversary and anchor: the composed store is under the data directory and only `attach` puts links in
it; a link is followed only into `permitted_roots`, which now come from the binding's project record.
A repository's `memory.groups` entry spelled `tag-x` resolves to the tag's own link and cannot
reach anything outside those roots.

- [ ] **Step 1: failing tests:**
  - `test_a_tags_memory_is_linked_under_its_tag_name` — `groups/a/memory/` exists → store has
    `tag-a` → it.
  - `test_a_tag_without_memory_gets_no_link`.
  - `test_untagging_takes_the_link_and_keeps_a_note_the_harness_wrote`.
  - `test_a_project_memory_directory_in_the_tag_namespace_is_not_linked` — `projects/p/memory/tag-a/`
    and tag `a` → `tag-a` points into `groups/a/memory`, not the project.
  - `test_a_tag_and_a_project_group_of_one_name_both_link` — tag `specs` and `projects/p/memory/specs/`
    → `specs` and `tag-specs`, two links.
  - `test_a_link_outside_the_permitted_roots_is_unavailable` — a store link `tag-a` pointed at
    `groups/b/memory` while only `a` is listed → `unavailable`.
  - `test_doctor_names_a_project_memory_directory_in_the_tag_namespace` — the warning finding.
- [ ] **Step 2:** run; fail.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `uv run pytest -n auto tests/memory tests/attach`; mypy; ruff.
- [ ] **Step 5:** mutations: "the composed store links a project directory in the tag namespace"
  (drop the `reserved` skip) → the namespace test; "permitted roots leave out the tags' notes" → the
  first test. Oracle each; paste.
- [ ] **Step 6:** commit `feat(memory): link each tag's notes into the composed store`.

### Task 7: one walk over the store's groups

**Files:**
- Modify: `src/stayfixed/memory/store.py` (`walked_groups`), and each walk site from pre-flight
  (`memory/commands.py`, `memory/doctor.py`, `memory/hooks.py`, `memory/bundles.py`,
  `memory/index.py` (the walk and the section loop), `memory/refs.py` if present)
- Test: `tests/memory/test_index.py`, `tests/memory/test_bundles.py`

**Interfaces:**
- Consumes: `tag_link`, `Store.groups` with tag links (Task 6).
- Produces: `walked_groups(store: Store, config: Config) -> list[str]` — `config.memory.groups` in
  order, each only where `store.groups` holds it, with every `tag-*` name in `store.groups` inserted
  after `COMMON_GROUP` (or first, where the configuration lists no `COMMON_GROUP`), in the tags' list
  order. Every site that walked `[g for g in config.memory.groups if g in store.groups]`, and the
  index's section loop, calls it; no site keeps its own spelling.

- [ ] **Step 1: failing tests:**
  - `test_the_index_has_a_section_per_tag_after_the_common_notes`.
  - `test_a_standing_rule_in_a_tags_notes_is_in_the_standing_rules_bundle`.
  - `test_walked_groups_follows_the_tag_list_order`.
- [ ] **Step 2:** run; fail.
- [ ] **Step 3:** implement; replace every site.
- [ ] **Step 4:** `uv run pytest -n auto tests/memory`; mypy; ruff;
  `grep -rn "if g in store.groups" src/` prints only `walked_groups`.
- [ ] **Step 5:** mutation: "walked groups leave out the tags" → the bundle test. Oracle; paste.
- [ ] **Step 6:** commit `feat(memory): every reader of the store walks the tags' notes`.

## Wave D — Tasks 8–10

### Task 8: one configuration for a bound checkout with no `stayfixed.toml`

Today `attach` and `doctor` resolve such a checkout with `command_config(..., unnamed=<the bound
project>)`, while every `memory` command refuses with "run `stayfixed init` first" and the session's
memory bundles print empty.

**Files:**
- Modify: `src/stayfixed/config/session.py` (`bound_config`), `src/stayfixed/doctor/model.py`
  (`attach_config` calls it), `src/stayfixed/memory/commands.py` (`_store`, `run_session_context`),
  `src/stayfixed/memory/hooks.py` (`_unreviewed`)
- Modify: `docs/cli.md` (`memory`: a bound checkout with no file), `changelog.d/+bound-checkout-memory.fix.md`
- Test: `tests/config/test_session.py`, `tests/memory/test_commands.py`, `tests/memory/test_bundles.py`

**Interfaces:**
- Produces: `bound_config(root: Path, *, machine: Path | None, owner: Owner | None) -> Config | None`
  — where `root` has a `stayfixed.toml` (`read_document(root)`): `command_config(root, ...)`, as
  today. Where it has none and this machine binds `root`'s repository (`binding.bound_project`):
  `command_config(root, ..., unnamed=lambda: bound.project)`. Otherwise `None`. Raises what
  `command_config` raises. `doctor` keeps calling it with the main checkout, as `attach_config` does
  today, and keeps its rule that a file only the main checkout has gives `None`.
- `memory._store`: `bound_config(...)`; `None` → the `load` refusal it gives today (the `init`
  remedy). `run_session_context`: where `session_config(...).config` is `None`, the store's
  configuration is `errors.resolved_or_none(lambda: bound_config(...))`; still `""` where that is
  `None`. `memory.hooks._unreviewed` reads the same way. `doctor.model.Context.attach_config` becomes
  `config` or `resolved_or_none(bound_config(...))`; nothing else in `doctor` changes.

Adversary and anchor: a clone with no `stayfixed.toml` gains a configuration only through this
machine's binding record (the id in the git common directory, the record under the data directory),
which a clone carries neither of. Must not refuse: a checkout the owner bound with no file.

- [ ] **Step 1: failing tests:**
  - `test_memory_index_renders_in_a_bound_checkout_with_no_file` — fixture: overlay project layer
    `[memory] mode = "overlay"`, `attach` with `--project`, no `stayfixed.toml`; `memory index`
    exits 0 and writes the overlay's `MEMORY.md`.
  - `test_the_standing_rules_bundle_carries_a_reviewed_note_with_no_file` — one reviewed standing
    note in the store → `memory session-context --bundle standing-rules --part 1` prints it, with and
    without a `stayfixed.toml` naming the same project.
  - `test_an_unbound_checkout_with_no_file_is_still_told_to_init` — every `_store` command.
  - `test_a_checkout_with_its_own_file_reads_it_first` — the file names a different `memory.mode`
    than the overlay's project layer would give the preset → the file's resolution wins as today.
  - `test_methodology_hooks_still_answer_nothing_without_a_file` — `session_config(root).config is
    None` in the bound, no-file fixture.
- [ ] **Step 2:** run; fail.
- [ ] **Step 3:** implement; delete the now-duplicate body of `attach_config`.
- [ ] **Step 4:** `uv run pytest -n auto tests/config tests/memory tests/doctor`; mypy; ruff.
- [ ] **Step 5:** mutation: "bound_config answers for an unbound checkout" (drop the binding check)
  → the unbound test. Oracle; paste.
- [ ] **Step 6:** commit `fix(memory): a bound checkout with no stayfixed.toml gets its memory`.

### Task 9: `doctor`'s missing-file row in a bound checkout

**Files:**
- Modify: `src/stayfixed/doctor/checks.py` (`_not_initialised`, a new constant beside
  `NOT_INITIALISED`), `README.md`/`docs/cli.md` where they quote the row
- Test: `tests/doctor/test_checks.py` (or where `_not_initialised` is tested today)

**Interfaces:**
- Consumes: `Context.attach_config` (Task 8).
- Produces: where `context.config is None`, nothing was dropped, and `context.attach_config` is not
  `None`: `Row(OK, BOUND_WITHOUT_FILE)`, no remedy, with `BOUND_WITHOUT_FILE = f"there is no
  {CONFIG_FILE} here; this machine binds the checkout, so its configuration comes from the
  overlay's layers"`. An unbound checkout keeps `WARN`, `NOT_INITIALISED` and its remedy.

- [ ] **Step 1: failing tests:** `test_a_bound_checkout_without_a_file_is_ok_and_names_the_overlay`;
  `test_an_unbound_checkout_without_a_file_still_warns_with_the_init_remedy`.
- [ ] **Step 2:** run; fail. **Step 3:** implement. **Step 4:** focused green; mypy; ruff.
- [ ] **Step 5:** no mutation entry (a report row refuses nothing).
- [ ] **Step 6:** commit `fix(doctor): a bound checkout with no stayfixed.toml is not told to init`.

### Task 10: `attach --check` names the project and where the name came from

**Files:**
- Modify: `src/stayfixed/attach/binding.py` (`choose_project` returns `Chosen`),
  `src/stayfixed/attach/write.py` (`configured` returns the source too), `src/stayfixed/attach/check.py`
  (`_report`), `docs/cli.md` (`attach --check`)
- Test: `tests/attach/test_project_choice.py`, `tests/attach/test_commands.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Chosen: name: str; source: str`, `source` one of fixed
  phrases: `"named by --project"`, `"this machine's binding record"`, `"the overlay's record of the
  remote"`, `"the remote's name"`; a checkout with a `stayfixed.toml`: `"its stayfixed.toml"`.
  `configured(...) -> tuple[Config, str]` (the source). `_report`'s summary opens with
  `project <quoted name> (<source>); ` before the state; `--json` gains `project` (through
  `printed.printable`) and `project_source`, and keeps every existing field.

- [ ] **Step 1: failing tests:** one per source, each asserting the summary's opening and the two
  JSON fields; `test_check_json_keeps_its_existing_fields`.
- [ ] **Step 2:** run; fail. **Step 3:** implement. **Step 4:** focused green; mypy; ruff.
- [ ] **Step 5:** no mutation entry (a report refuses nothing).
- [ ] **Step 6:** commit `fix(attach): --check names the project it would bind and why`.

## Wave E — Task 11

### Task 11: owner-held files in a new linked worktree

**Files:**
- Create: `src/stayfixed/attach/checkout.py`
- Modify: `src/stayfixed/attach/hooks.py` (register `owner-files` on `SessionStart`, first in the
  list), `src/stayfixed/fsops.py` (`create_within`, if no exclusive-create write exists)
- Modify: `docs/cli.md` (`hook`'s **Writes**: the worktree root's owner-held files; `attach`: what
  `projects/<name>/checkout/` is for; `detach` leaves placed files), `README.md` ("What it writes"),
  `changelog.d/+owner-held-files.feature.md`
- Test: `tests/attach/test_checkout.py` (new), `tests/test_fsops.py`

**Interfaces:**
- Consumes: `binding.bound_project`, `config.overlay.overlay_root`, `config.plates.PROJECTS`,
  `attach.exclude.unignored`, `gitenv.git_run`.
- Produces:
  - `fsops.create_within(root: Path, target: str, data: bytes, *, mode: int) -> bool` — create
    `root/target` with `O_CREAT | O_EXCL | O_NOFOLLOW` through the `open_within` walk; `False` where a
    name is already there (`FileExistsError`), never writing through a link; a write that fails after
    the create removes what it created.
  - `checkout.CHECKOUT = "checkout"`, `checkout.NEVER = ("settings.local.json",)`,
    `checkout.NEVER_PREFIXES = (".env",)`, `checkout.LITTER = (".DS_Store",)`.
  - `checkout.linked_worktree(root: Path) -> Path | None` — the toplevel where `git rev-parse
    --path-format=absolute --show-toplevel --git-dir --git-common-dir` says the git directory is
    `<common>/worktrees/<name>`, `<common>` is named `.git`, and the toplevel is not `<common>`'s
    parent; `None` otherwise (main checkout, submodule, bare repository's worktree, separate git dir,
    no answer).
  - `checkout.place(root: Path, *, machine: Path | None) -> tuple[list[str], list[str]]` — the names
    placed and, of those, the ones `exclude.unignored` reports; `([], [])` when not a linked worktree,
    not bound, no overlay recorded, or no `checkout/` directory.
  - Handler `owner-files` (`SessionStart`, no `once_key`): `place(event.project_root, ...)`; context
    only when something was placed: the names, "read AGENTS.md now" when `AGENTS.md` or `CLAUDE.md` is
    among them, and the unignored names with "add them to the checkout's `.git/info/exclude`". Any
    exception → empty result.

Adversary and anchor: the adversary is a repository (a clone, or a branch checked out in the
owner's worktree). The anchor is the binding id in the repository's git common directory and this
machine's record of it, which a clone carries neither of and a branch cannot write; the overlay root
comes from the machine file. A branch can commit a file or a symlink at a target name: the name is
then "there", and nothing is written (a created file never follows a link). The git questions asked
are `rev-parse` and `check-ignore --no-index`, neither of which refreshes the index, so a
repository's `core.fsmonitor` does not run. Must not refuse: a repository that tracks `AGENTS.md` —
the worktree has it from the branch, nothing is placed, nothing is said.

- [ ] **Step 1: failing tests** (scratch `HOME`, fixture overlay with `projects/p/checkout/` holding
  `AGENTS.md`, `CLAUDE.md`, `stayfixed.toml`, `.env`, `.env.local`, `settings.local.json`,
  `.DS_Store`, a symlink, a subdirectory):
  - `test_a_new_linked_worktree_gets_the_regular_files_and_nothing_else` — placed: exactly
    `AGENTS.md`, `CLAUDE.md`, `stayfixed.toml`; bytes and mode bits equal to the sources.
  - `test_a_present_name_is_never_overwritten` — a file, a directory and a dangling symlink at
    `AGENTS.md` each stay as they were, and the symlink's target is not created.
  - `test_a_tracked_name_is_left_to_the_branch`.
  - `test_the_main_checkout_gets_nothing`; `test_a_worktree_of_a_bare_repository_gets_nothing`;
    `test_a_submodule_gets_nothing`.
  - `test_an_unbound_worktree_gets_nothing` — same `origin` as the bound project, no binding id.
  - `test_the_second_session_says_nothing`.
  - `test_the_context_names_unignored_files_and_asks_to_read_agents_md`.
  - `test_create_within_refuses_a_name_that_is_there_and_never_follows_a_link` (`tests/test_fsops.py`).
- [ ] **Step 2:** run; fail.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `uv run pytest -n auto tests/attach tests/test_fsops.py tests/hooks`; mypy; ruff;
  `scripts/smoke_hooks.py` still passes for `SessionStart`.
- [ ] **Step 5:** mutations: "owner-held files copy .env files" (drop the prefix rule) → the first
  test; "owner-held files are placed in the main checkout" (drop the linked check) → the main-checkout
  test; "owner-held files overwrite a present name" (`create_within` without `O_EXCL`) → the present-
  name test. Oracle each; paste.
- [ ] **Step 6:** commit `feat(attach): place the owner-held files in a new linked worktree`.

## Task 12: the PR

- [ ] `git merge origin/next`; resolve; the full suite once
  (`uv run pytest -n auto --cov --cov-fail-under=92`), `uv run ruff check . && uv run ruff format
  --check .`, `uv run mypy`, `uv run python scripts/release.py check`, and the oracle on this plan's
  entries by name; paste each.
- [ ] Final review per the execution contract; triage; at most one fix round; one scoped re-review.
- [ ] `gh pr create --base next`, body: what changed per area, the lifecycle matrix, the net size,
  the measurement above. No private names.
- [ ] `gh run watch <run-id> --exit-status` on the PR's run; fix red; stop. The controller merges.
