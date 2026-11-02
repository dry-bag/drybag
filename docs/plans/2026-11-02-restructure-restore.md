# Restructure lane 6 — the runner table, the pipe hint, `setup --restore`, the hook wrapper: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking. **The lettered wave is the
> dispatch unit, not the task:** one implementer per wave (at most about 900 plan lines and three
> tasks), and every task inside it keeps its own failing test, verification and commit. **Reviews
> are per pull request, never per wave:** one final review per pull request, one scoped re-review,
> then stop (see "Execution contract").

**Goal:** two pull requests into `next`. **A:** a table of test-runner program names in the `hints`
area and a `PreToolUse` hint for a test run piped into `tail`, `head` or `grep` without `pipefail`.
**B:** `stayfixed setup --restore`, which restores a machine from the overlay the machine file
records; a hook wrapper that falls back to uv for its interpreter without reading the repository;
and `stayfixed hook` dispatched before the full parser is built.

**Architecture:** A adds two modules to `hints` (the area #158 creates out of `guards`): the table
and the hint, which reuses the area's shell scanner. B adds no area: `--restore` is a mode of
`setup` (`src/stayfixed/setup/restore.py`, new) that runs today's machine setup, installs the
plugins the overlay's machine layer lists, and attaches every listed checkout that exists through
the `attach` area's own `attach`, so the project-name check is attach's existing store check. The
wrapper change is a few lines of `hooks/run-hook.sh`; the hook route is a few lines of `cli.main`.

**Tech Stack:** Python ≥ 3.11 standard library; POSIX `sh` for the wrapper; pytest with xdist; the
mutation oracle (`scripts/mutation_oracle.py`, entries under `mutations/`); towncrier fragments in
`changelog.d/`.

**Spec:** the restructure's design is private. What this lane needs from it is restated in
"Requirements" below, and nothing here depends on reading it.

**Scope:** the restructure into one repository shipping a layers platform and a hook-free
methodology pack, lane 6. A change belongs to this branch when it is the runner table, the pipe
hint, `setup --restore`, the wrapper's interpreter choice or the early `hook` route, or a caller's,
test's or document's adaptation to one of them. Out: re-pointing the red-run note at the runner
table (lane 3's second pull request), the machine file's `[sync]` key and its writer (lane 5), tags
and owner-held files (lane 4), and every step an overlay's own setup script keeps (cloning, `.env`
files, the main checkout's owner-held files, `info/exclude` lines, links, each project's commit
hook and push guard, the user settings merge, a core-budget tool, a cloud profile).

**Premise:** measured on 2026-11-02 at `d00b726` (`dev`, which `next` was cut from), before #158.
Each wave re-measures its own part on the merged `next` before its first edit and reports a
mismatch instead of guessing.
- `hooks/run-hook.sh` enters the project root, then takes `command -v python3` and probes it with
  `-I` for 3.11; no usable `python3` is `off()`, which on `hook SessionStart` prints the JSON notice.
  It never asks uv.
- `stayfixed.cli.main` builds the whole parser (`discover_registrars`, every area's `commands.py`)
  before any command runs, `hook` included; `_discovery_failed` maps a broken area to exit 0 for
  `hook`.
- `setup` (`src/stayfixed/setup/commands.py`, `src/stayfixed/setup/run.py`) writes the machine
  file and the user settings, installs `--plugin` names from the preset's marketplace through
  `Runner.launch`, and records, renders or creates the overlay with `--overlay`.
- `attach` (`src/stayfixed/attach/write.py`) takes `store=`; `read_binding`
  (`src/stayfixed/attach/binding.py`) refuses a store that is not
  `<overlay>/projects/<config.project.name>/memory`, and for a checkout with no `stayfixed.toml` the
  project is chosen by the binding or the origin the overlay records. `src/stayfixed/attach/api.py` does not
  publish `attach` or `Attached` (trimmed for want of a consumer).
- `memory promote --changed` (`src/stayfixed/memory/commands.py`, `run_promote`) records every
  unreviewed note of the store as reviewed; `src/stayfixed/memory/api.py` publishes no promote.
- `src/stayfixed/guards/hygiene.py` recognises a test command only through `profiles`' runner adapters;
  `src/stayfixed/guards/bashscan.py`'s `segments` splits at `|` as at every separator, so it cannot say which
  commands form one pipeline.
- `uv python find` (uv 0.12.19), run in a directory whose `.python-version` holds the path of an
  executable script, absolute or relative (`./evil`), **runs that script**; with `--no-config`, or
  run from `/`, it does not, and answers a uv-managed or `PATH` interpreter. Measured in a scratch
  directory, not a repository.

---

## Requirements

Restated from the private design; each line is the decision this plan implements.

- **R1 (hints).** Test commands are recognised by a small table of runner program names in `hints`,
  for every common runner, matched by program name and never by parsing their options. The hints
  stay conveniences that never refuse.
- **R2 (pipe hint).** A test run piped through `tail`, `head` or `grep` without `pipefail` gets a
  hint at `PreToolUse`.
- **R3 (wrapper).** The hook wrapper finds a ≥ 3.11 interpreter without reading the repository:
  `python3` as today, then uv asked from a neutral directory with `--no-config`. A test with a
  repository `.python-version` naming a script shows the script never runs.
- **R4 (hook route).** `stayfixed hook` is dispatched before the full parser is built.
- **R5 (restore).** `setup --restore` restores a machine from the overlay the machine file records:
  1. check the tools (git, a Python ≥ 3.11 for the hooks, `claude` and/or `codex`) and print what is
     missing;
  2. machine setup (today's `setup`);
  3. install the plugins the overlay's machine layer lists;
  4. for each project in `<overlay>/machine/projects.toml` whose `dir` exists, attach it, refusing a checkout
     whose project name is not that table's key;
  5. with `--yes` only, record the overlay's notes as reviewed on this machine; with `--sync`, set
     `[sync] enabled = true` in the machine file.

  `attach` already renders a missing memory index. `<overlay>/machine/projects.toml`'s `dir` and table keys
  become a product input, documented in `docs/cli.md`. No new area.

## Global constraints

- `CONTRIBUTING.md` holds: standard library only at runtime; every write through `fsops`; a
  repository's bytes are data; a control names its adversary and its anchor; named caps; enumerated
  writes in `docs/cli.md`; the neutrality gate (`tests/test_neutral.py`: no bare abbreviated commit
  id of eight to ten hex digits, no two-letter-then-space-then-hash token, no vendor-prefixed branch
  name); conventional commits; one towncrier fragment per user-visible change.
- Pull requests target `next`. Branches: `restructure/runner-table` (A) and `restructure/restore`
  (B), both cut from `origin/next` after #158 merged. No vendor-prefixed branch name is pushed. The
  controller merges; this lane never merges, squashes or rebases.
- **No run against the real home.** No test, try or probe runs `setup`, `--restore`, `attach` or a
  hook against the developer's real `HOME`, `~/.config/stayfixed/` or overlay: `tmp_path` homes,
  `--home`/`--machine`, a fixture overlay, `tests/runners.py`'s `Recorder` for `claude`/`codex`.
  No pytest probe outside `tests/` imports `tests.conftest` (it runs under the real `HOME`).
- `src/stayfixed/attach/api.py` and `src/stayfixed/memory/api.py` are edited by lane 4 too: add only the names this lane calls,
  with the docstring line that names the consumer.
- The oracle runs locally only with a pattern naming this lane's entries
  (`uv run python scripts/mutation_oracle.py <pattern>`); its lock is per machine, so a run told
  another holds it waits and retries.
- Each pull request body prints its net size:
  `git diff --shortstat origin/next HEAD -- src tests mutations docs`.

## Execution contract

The controller copies the relevant part into every brief.

1. **Final review, per pull request.** A: a correctness seat and a "what can be deleted / who does
   this refuse" seat. B: those two and a **security seat**, because B chooses the program every hook
   starts. Then one scoped re-review, and stop. Reviewers report every finding with no replacement
   text; only correctness and requirement gaps go back to the implementer; Minors become follow-ups
   in "Findings".
2. **Lifecycle matrix** (below) is checked at each wave's pre-flight like a task.
3. **Parallelism.** One worktree, so implementers serialise: Wave A, then Wave B, then Wave C.
   Review seats are read-only and run beside each other. Pull request A's CI wait and review overlap
   Wave B. One oracle at a time.
4. **Fix briefs** fold sibling instances into one rule or delete them, never add a guard to each,
   and carry a net budget: `src` and tests together no larger after the round than before it,
   unless the finding is a missing requirement.
5. **Verification.** Focused runs while iterating; one full suite
   (`uv run pytest -n auto --cov --cov-fail-under=92`), ruff, `ruff format --check`, mypy and
   `uv run python scripts/release.py check` before each push; paste what each printed. A mutation
   outcome this plan predicts is a hypothesis until the oracle prints it. Wait for CI with
   `gh run watch <run-id> --exit-status` (run id from `gh pr checks`), fix red, then stop and report.

**Every brief also carries:** report a mismatch between this plan and the tree instead of guessing;
no line numbers from this plan; write nothing under the repository but this lane's change; a private
scratch subdirectory per agent; never kill a process by a name pattern; no `git checkout`, `restore`,
`stash` or `clean` in a reviewer; no nested agents.

**This lane's size (estimate):** A: `src` about +250, tests about +350. B: `src` about +600, tests
about +1,000. Dispatches: three implementers, five review seats, two re-reviews, and at most one fix
round per pull request: about twelve.

## Lifecycle matrix

Every command this lane adds or changes, against each situation. "Task" names the test that holds
the row; "doc" means the row is a documented bound with no test.

| Situation | `setup --restore` | wrapper interpreter | early `hook` route | pipe hint |
|---|---|---|---|---|
| First run | fresh `HOME`, `--overlay PATH`: machine file and user settings written, listed plugins installed, every listed checkout that exists attached (Task 5 end-to-end) | `python3` ≥ 3.11 on `PATH`: chosen as today (existing tests) | `hook <Event>` dispatches with no area's `commands.py` imported (Task 3) | piped test run: one hint per context (Task 2) |
| Run twice | nothing new: setup keeps recorded values, attach is idempotent, installed plugins and registered marketplaces are not asked again, `--yes` promotes nothing, exit 0 (Tasks 5, 6, 7) | same interpreter (no state) | no state | second piped run in the same context: silent (`once_key`, Task 2) |
| A project missing | `dir` not there: reported "not there", skipped, the rest attached, exit 0 (Task 5) | no `python3`, uv present: uv's interpreter, asked from `/` (Task 4) | — | — |
| A refused project | checkout whose project name is not its table key: refused by attach's store check, nothing written into it, the rest attached, exit 1 (Task 5) | repository `.python-version` names a script: the script never runs (Task 4) | `hook --help`, `hook` alone: through the full parser (Task 3) | `pipefail` named in the command: silent (Task 2) |
| Change | a project added to `<overlay>/machine/projects.toml`: the next run attaches it (Task 5); `dir` changed to a moved checkout: attached where it now is, its binding id travels with its git directory (attach's own tests; doc) | uv installed or removed between sessions: taken or not on the next hook (doc) | — | — |
| Unlist | a project removed from `<overlay>/machine/projects.toml`: restore never detaches it; it stays attached until `stayfixed detach` there (Task 5) | — | — | — |
| Fail part-way | one attach fails (`claude plugin` install of its delivery exits non-zero): that project reported failed, the rest continue, exit 1, a re-run completes (Task 5); a plugin install fails: a note, the run goes on (Task 6); an unreadable `<overlay>/machine/projects.toml`: refused before anything is written (Task 5) | uv answers nothing ≥ 3.11: `off()` with today's message (Task 4) | an area's `commands.py` that raises at import: hooks still dispatch (Task 3) | a command the scanner cannot read: silent (Task 2) |
| Undo | `stayfixed detach` per project returns the checkout to where it started (Task 5 end-to-end); `--yes`: a reviewed note is withdrawn by editing or deleting it; `--sync`: the machine file's `[sync] enabled = false`, as lane 5 documents; plugins: `claude plugin uninstall` (doc) | uninstalling uv: back to `python3` alone | — | — |

## Review focus

The five inputs most likely to bite a person that no requirement names, each pinned by a test in the
owning task.

1. **A table key that is no project name** (`[projects."../x"]`, `[projects."a b"]`): attach's store
   check refuses it, nothing is written outside the overlay, the other projects attach. Task 5,
   `test_a_table_key_that_is_no_project_name_is_refused_and_the_rest_attach`.
2. **A listed `dir` that is not a git checkout** (a plain directory, a file): that project is
   reported with attach's own refusal, the rest attach. Task 5,
   `test_a_listed_dir_that_is_no_checkout_is_reported_and_the_rest_attach`.
3. **A `dir` that is relative or not a string:** an input error in the owner's file, refused before
   anything is written, naming the table. Task 5,
   `test_a_relative_dir_is_refused_before_anything_is_written`.
4. **`uv run pytest | grep FAIL` and `PYTHONPATH=src pytest | tail`:** the launcher and the
   assignment are unwrapped before the table is asked, so both get the hint. Task 2,
   `test_a_piped_run_behind_uv_or_an_assignment_gets_the_hint`.
5. **The wrapper's existing degrade tests with uv on `PATH`:** a sub-floor `python3` now falls to uv,
   so every test that expects `off()` builds a `PATH` without uv. Task 4,
   `test_no_python3_and_no_uv_degrades_open`, and the helper change named there.

---

## Wave A — Tasks 1–2 (pull request A, branch `restructure/runner-table`)

**Pre-flight:** `git merge origin/next` into this worktree; then
`ls src/stayfixed/hints/` must list `bashscan.py`, `hygiene.py`, `hooks.py` and `api.py`, and
`src/stayfixed/hints/hooks.py` must register `bg-cleanup` and `test-hygiene`. Read the lifecycle
matrix's "pipe hint" column. Mismatch: stop and report.

### Task 1: The runner table

**Files:**
- Create: `src/stayfixed/hints/runners.py`
- Test: `tests/hints/test_runners.py`
- Modify: `tests/test_language_neutral.py` (pardons)

**Interfaces:**
- Consumes: `stayfixed.hints.bashscan.tokenize`, `segments`, `command_words(segment, recognises)`
  (moved by #158 unchanged).
- Produces:
  - `RUNNERS: tuple[tuple[str, ...], ...]` — each row the leading words of one runner's test
    command.
  - `names_a_test_run(words: Sequence[str]) -> bool` — whether `words`, one simple command already
    unwrapped by `command_words`, begins with a row. Also the `recognises` callable handed to
    `command_words`, so `uv run <runner>` unwraps to the runner. Lane 3 re-points the red-run note
    at it.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("command", [
    "pytest", "pytest -x tests/a.py", "py.test", "python -m pytest", "python3 -m pytest -q",
    "python3.13 -m pytest", ".venv/bin/pytest", "go test ./...", "cargo test", "cargo nextest run",
    "npm test", "npm t", "npm run test", "pnpm test", "yarn test", "bun test", "npx jest",
    "npx vitest run", "jest", "vitest", "deno test", "dotnet test", "mvn test", "gradle test",
    "./gradlew test", "rspec", "bundle exec rspec", "phpunit", "mix test", "tox", "nox",
    "ctest", "swift test", "make test",
])
def test_a_common_runner_is_named_by_its_program(command: str) -> None:
    assert names_a_test_run(command.split())

@pytest.mark.parametrize("command", [
    "go vet ./...", "cargo build", "npm install", "npm run build", "echo pytest", "grep pytest x",
    "python -m pip install pytest", "make", "git test",
])
def test_a_command_that_runs_no_tests_is_not_named(command: str) -> None:
    assert not names_a_test_run(command.split())

@pytest.mark.parametrize("command", ["uv run pytest -x", "uv run --locked pytest",
                                     "PYTHONPATH=src pytest", "env CI=1 npm test"])
def test_a_runner_behind_a_launcher_or_an_assignment_is_named(command: str) -> None:
    [segment] = bashscan.segments(bashscan.tokenize(command))
    assert names_a_test_run(bashscan.command_words(segment, names_a_test_run))
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/hints/test_runners.py -q`
Expected: collection fails with `ModuleNotFoundError: stayfixed.hints.runners`.

- [ ] **Step 3: Implement `RUNNERS` and `names_a_test_run` in `src/stayfixed/hints/runners.py`**

The first word is compared by its `Path(word).name`, and a `python3.<minor>` name reads as
`python3`; every later word of a row is compared as typed. No option is read: a word between the
program and its subcommand (`npm --prefix x test`) is no match, and the module docstring says so as
the table's bound. The rows are exactly the positive cases of Step 1, `gradlew` for `./gradlew`,
`npx jest` and `npx vitest` as two-word rows.

- [ ] **Step 4: Pardon the table in the neutrality walk**

`tests/test_language_neutral.py`'s `STACK_NAMED` gains one row per stack word the new module names
(`python`, `python3`, `pytest`, `npm`, `npx`, `yarn`, `pnpm`, `jest`, `vitest`, `cargo`, `tox`,
`mvn`, `gradle`, whatever the walk reports), under one comment: the table names runners only to say
that a command is a test run, never to run, plan or advise one, and it is the one place the hints
look this up. Run `uv run pytest tests/test_language_neutral.py -q` and paste the result; the
pardon set equals the walk's findings both ways.

- [ ] **Step 5: Run the focused tests**

Run: `uv run pytest tests/hints/test_runners.py tests/test_language_neutral.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/stayfixed/hints/runners.py tests/hints/test_runners.py tests/test_language_neutral.py
git commit -m "feat(hints): name a test run by its runner's program, from one table"
```

### Task 2: The pipe hint

**Files:**
- Create: `src/stayfixed/hints/pipes.py`
- Modify: `src/stayfixed/hints/bashscan.py` (`pipelines`), `src/stayfixed/hints/hooks.py`
  (handler), `docs/cli.md` (the hook section's handler list), `README.md` where it lists the hints
- Create: `changelog.d/+pipe-status-hint.feature.md`
- Test: `tests/hints/test_pipes.py`

**Interfaces:**
- Consumes: Task 1's `names_a_test_run`; `bashscan.tokenize`, `operator_pieces`, `command_words`.
- Produces:
  - `bashscan.pipelines(tokens: list[str]) -> list[list[list[str]]]` — each pipeline (its simple
    commands joined by `|`; `;`, `&&`, `||` and `&` end one) as its list of simple commands, fused
    punctuation decomposed by `operator_pieces` as `segments` does.
  - `pipes.READERS = frozenset({"tail", "head", "grep"})`.
  - `pipes.notice_for(command: str) -> str | None` — the fixed notice when some pipeline holds a
    test run that is not its last command and a later command of that pipeline is a reader, and the
    command's text names neither `pipefail` nor `PIPESTATUS`; else `None`. `None` for a command
    `tokenize` cannot read.
  - Handler `pipe-status` on `PreToolUse`, `once_key="pipe-status"`, speaking with or without the
    project's configuration and with no switch: it reads the command alone, as `bg-cleanup` does.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("command", [
    "pytest -x 2>&1 | tail -20", "cargo test 2>&1 | head -50", "npm test | grep -i fail",
    "go test ./... | tee log | tail", "cd a && pytest | tail",
])
def test_a_test_run_piped_into_a_reader_gets_the_hint(command: str) -> None:
    assert notice_for(command) == NOTICE

@pytest.mark.parametrize("command", ["uv run pytest | grep FAIL", "PYTHONPATH=src pytest | tail"])
def test_a_piped_run_behind_uv_or_an_assignment_gets_the_hint(command: str) -> None:
    assert notice_for(command) == NOTICE

@pytest.mark.parametrize("command", [
    "set -o pipefail; pytest | tail", "set -euo pipefail\npytest | tail",
    "pytest | tail; echo ${PIPESTATUS[0]}", "pytest | tee log", "pytest > log; tail log",
    "pytest; ls | tail", "grep x log | tail", "tail -f log | grep pytest", "pytest 'a | tail",
])
def test_no_hint_where_the_status_is_kept_or_no_test_run_is_piped(command: str) -> None:
    assert notice_for(command) is None

def test_the_hint_is_given_once_per_context(...) -> None:
    # Two PreToolUse Bash events of one session through `hooks.dispatch.dispatch` with a
    # `Recorder` sink: the first carries the notice, the second carries none.
```

`pipelines` gets two cases in the scanner's own test file (moved by #158): `a | b; c && d | e` is
three pipelines of 2, 1 and 2 commands, and a fused `|;` still ends the pipeline.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/hints/test_pipes.py -q`
Expected: collection fails with `ModuleNotFoundError: stayfixed.hints.pipes`.

- [ ] **Step 3: Implement `pipelines`, `notice_for` and the handler**

`NOTICE` is fixed text and names no part of the command, so nothing a repository wrote reaches the
context: the test run is piped into a reader, and without `pipefail` a pipeline's exit status is its
last command's, so a red run reads as green; put `set -o pipefail;` in front, or write the output to
a file and read the file. The handler's registration sits beside `bg-cleanup`'s, with a comment that
the hint never refuses: the agent writes the command, so a refusal would be a convenience it spells
around. Measure whether `operator_pieces` yields `|&` as a pipe; if it does not, the docstring
states `|&` as a bound.

- [ ] **Step 4: Document it**

Every listing of the hint handlers by name gets the new one: run
`grep -rn "bg-cleanup" docs README.md skills src/stayfixed/hints` and add `pipe-status` beside each
listing that names the handlers; a test that holds a listing equal to the registry names the files.
The fragment says what the hint says and when, in a sentence a user can read.

- [ ] **Step 5: Run the focused tests, then the area and the boundaries**

Run: `uv run pytest tests/hints tests/hooks tests/boundaries tests/test_documents.py -q -n auto`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/stayfixed/hints tests/hints docs/cli.md README.md changelog.d
git commit -m "feat(hints): say when a piped test run's exit status is not the runner's"
```

**Mutation entries:** none. Neither the table nor the hint decides a verdict, a containment or a
data-loss path: the hint warns once and the command runs either way.

**Pull request A:** full suite, static checks, `release.py check`, push
`restructure/runner-table`, open the pull request into `next` with the net size, final review (two
seats), one fix round if needed, re-review, `gh run watch`, report. Wave B starts once the fix round
is pushed.

---

## Wave B — Tasks 3–4 (pull request B, branch `restructure/restore`)

**Pre-flight:** `git fetch`, then `git switch -c restructure/restore origin/next`. Re-measure:
`hooks/run-hook.sh` as the Premise says; `cli.main` calls `discover_registrars` first;
`uv --version` prints a version. Read the matrix's wrapper and route columns. Mismatch: stop and
report.

### Task 3: `stayfixed hook` before the parser

**Files:**
- Modify: `src/stayfixed/cli.py` (`main`), `src/stayfixed/hooks/api.py` (`run_event`),
  `docs/cli.md` (`stayfixed hook`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `stayfixed.hooks.api.run_event(event: str) -> int` — runs
  `stayfixed.hooks.commands.run_hook` for `event`, its import deferred into the function body so
  `hooks.api` keeps importing nothing of `hooks.commands` at module level. If a rule under
  `tests/boundaries/` refuses this placement, report it with the failing output instead of adding a
  pin.
- `cli.main(argv)`: when the raw argv is exactly `["hook", EVENT]` and `EVENT` does not begin with
  `-`, makes both streams printable (`_printable`, as `run` does) and returns `run_event(EVENT)`
  without calling `discover_registrars`. Any other argv, `hook --help` and `hook` alone included,
  takes today's path.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_hook_event_dispatches_with_no_command_module_discovered(monkeypatch, capsys) -> None:
    def broken() -> list:
        raise RuntimeError("an area's commands.py failed")
    monkeypatch.setattr(cli, "discover_registrars", broken)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert cli.main(["hook", "PreToolUse"]) == 0
    assert "internal error" not in capsys.readouterr().err

def test_hook_help_still_goes_through_the_parser(monkeypatch, capsys) -> None:
    # same `broken`; `hook --help` reaches `_discovery_failed`, which says so on stderr
    assert cli.main(["hook", "--help"]) == 0
    assert "internal error" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to see the first fail**

Run: `uv run pytest tests/test_cli.py -q -k "hook_event_dispatches or hook_help"`
Expected: the first fails (`internal error` on stderr); the second passes.

- [ ] **Step 3: Implement `run_event` and the route**

- [ ] **Step 4: Measure what it saves**

Run `python -X importtime scripts/stayfixed hook PreToolUse < /dev/null 2>&1 | grep -c "stayfixed\."`
on this commit and on its parent, with `HOME` and `CLAUDE_PLUGIN_DATA` pointing into a scratch
directory; paste both counts for the pull request body.

- [ ] **Step 5: Declare the mutation and run it**

Entry: name "the hook route builds the whole parser first", file `src/stayfixed/cli.py`, the route's
condition line, `after` a condition that is never true, reddens
`tests/test_cli.py::test_a_hook_event_dispatches_with_no_command_module_discovered`. Commit first,
then `uv run python scripts/mutation_oracle.py "hook route"`. Expected: caught; if it survives or
reddens for another reason, the assertion needs work, not the entry.

- [ ] **Step 6: Document and commit**

`docs/cli.md`'s `stayfixed hook` section: the event is dispatched before the parser is built, so an
area whose command module fails to load costs that area's commands and never a hook; `hook --help`
goes through the parser.

```bash
git add src/stayfixed/cli.py src/stayfixed/hooks/api.py tests/test_cli.py docs/cli.md mutations
git commit -m "perf(hooks): dispatch a hook event before building the command parser"
```

### Task 4: The wrapper falls back to uv, asked from `/`

**Files:**
- Modify: `hooks/run-hook.sh`, `docs/cli.md` (the wrapper paragraph), `README.md` (the
  requirement line naming `python3`)
- Create: `changelog.d/+hook-wrapper-uv.feature.md`
- Test: `tests/hooks/test_wrapper.py`

**Interfaces:**
- The wrapper's order: enter the project root as today; take `command -v python3` and probe it with
  `-I` as today; when that is absent or below 3.11 and `command -v uv` names a uv, take
  `$(cd / && uv python find --no-config --no-python-downloads '>=3.11' 2>/dev/null)` and probe it the
  same way; when neither passes, `off()` as today, with today's messages (the one for a sub-floor
  `python3` when there was one). The `cd /` runs in the command substitution's subshell, so the
  launcher still runs in the project root.
- **Anchor sentence** (for the comment above the uv line and the security seat): the program every
  hook starts comes from `PATH`, which is the person's and the harness's, and from uv asked in `/`
  with `--no-config`; uv reads `.python-version`, `pyproject.toml` and `uv.toml` from its working
  directory and its parents, which in `/` are no repository's, so a repository's bytes choose
  nothing here. `python3` is still asked from the project root, as today, because a version
  manager's shim answers for the directory it runs in.

- [ ] **Step 1: Write the failing test**

```python
def test_uv_is_asked_from_a_neutral_directory_and_a_repository_script_never_runs(tmp_path) -> None:
    # No `python3` on PATH: one directory holds a link to the real uv, another a link named
    # `python3.<minor>` to `_base_interpreter()`, which uv finds and the wrapper's `python3`
    # lookup does not. The project commits a `.python-version` naming its own executable script,
    # which writes a marker when run: uv runs such a script when asked from that directory.
    # Skips only where no uv is on PATH; CI runs the suite under `uv run`, so it runs there.
    ...
    result = _run("hook", "PreToolUse", plugin_root=_plugin_root(tmp_path, 0, echo_cwd=True),
                  project=project, path=path)
    assert not marker.exists()
    assert result.returncode == 0 and "continuing open" not in result.stderr
    assert Path(result.stdout.strip()) == project.resolve()   # the launcher ran, in the project
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/hooks/test_wrapper.py -q -k neutral_directory`
Expected: fails on the last two assertions (`off()`: "no python3 on PATH; continuing open").

- [ ] **Step 3: Implement the fallback in `hooks/run-hook.sh`**

- [ ] **Step 4: Keep the degrade tests about the wrapper**

`_python_on_path` appends this process's `PATH`, which under `uv run` holds uv, so the tests that
expect `off()` from a missing or sub-floor `python3` would now pass through uv. Give them a `PATH`
without any directory holding `uv`, in the helper and not in each test, and add
`test_no_python3_and_no_uv_degrades_open` beside `test_no_python3_on_path_degrades_open` with an
empty `PATH`. Run `uv run pytest tests/hooks/test_wrapper.py tests/doctor -q -n auto` and paste it.

- [ ] **Step 5: Declare the mutation and run it**

Entry: name "the hook wrapper asks uv from the project root", file `hooks/run-hook.sh`, `before` the
uv line's `cd / && `, `after` the same line without it, reddens the Step 1 test. Commit, then
`uv run python scripts/mutation_oracle.py "asks uv from the project root"`. Expected: caught by the
marker assertion; paste the line.

- [ ] **Step 6: Document and commit**

`docs/cli.md`'s wrapper paragraph and the README requirement: `python3` 3.11 or newer on `PATH`, or
uv, which is asked from `/` with `--no-config` so that no repository file chooses the interpreter.

```bash
git add hooks/run-hook.sh tests/hooks/test_wrapper.py docs/cli.md README.md changelog.d mutations
git commit -m "feat(hooks): fall back to uv's interpreter, asked where no repository chooses it"
```

---

## Wave C — Tasks 5–7 (pull request B, continued)

**Pre-flight:** on `restructure/restore` after Wave B. Re-measure: `attach(root, *, store, machine,
runner, owner, project)` in `src/stayfixed/attach/write.py`; `read_binding`'s store refusal;
`permitted_roots(overlay, project)` in `src/stayfixed/memory/api.py`; `run_promote` in
`src/stayfixed/memory/commands.py`; `write_machine` in `src/stayfixed/setup/machine.py`; whether
`next` holds lane 5's `[sync]` class in `src/stayfixed/config/classes.py` (Task 7 needs it). Read
the matrix's restore column. Mismatch: stop and report.

### Task 5: `setup --restore`: the projects file, the tools, the attach loop

**Files:**
- Create: `src/stayfixed/setup/restore.py`
- Modify: `src/stayfixed/setup/commands.py` (`--restore`, the refusals), `src/stayfixed/attach/api.py`
  (`attach`, `Attached`), `docs/cli.md` (`stayfixed setup`), `README.md` (the command list)
- Create: `changelog.d/+setup-restore.feature.md`
- Test: `tests/setup/test_restore.py`, `tests/test_install_path.py`

**Interfaces:**
- Consumes: `stayfixed.attach.api.attach` and `Attached` (published here, the docstring naming
  `setup --restore` as the consumer); `stayfixed.memory.api.permitted_roots`; `setup.run.setup`.
- Produces, in `stayfixed.setup.restore`:
  - `PROJECTS_FILE = Path("machine") / "projects.toml"`.
  - `class Listed(NamedTuple): name: str; dir: Path`.
  - `listed_projects(overlay: Path, *, home: Path) -> tuple[Listed, ...]` — the
    `[projects.<name>]` tables of `<overlay>/machine/projects.toml` in file order; `dir` is required,
    absolute or `~/`-led (read under `home`); every other key is ignored. `()` when the file is not
    there. A file that cannot be read, is not TOML, has a `projects` that is not a table, or a table
    whose `dir` is missing, not a string or relative is a `Refusal` naming the table.
  - `missing_tools(which: Callable[[str], str | None] = shutil.which) -> tuple[str, ...]` — `"git"`
    when absent, `"claude or codex"` when both are, `"python3 or uv"` when both are.
  - `class Outcome(NamedTuple): name: str; dir: Path; state: Literal["attached", "absent",
    "refused", "failed"]; detail: str; promoted: int`.
  - `@dataclass(frozen=True) class RestoreReport: missing: tuple[str, ...]; plugins:
    tuple[str, ...]; notes: tuple[str, ...]; projects: tuple[Outcome, ...]; sync: bool`.
  - `restore(overlay: Path, listed: Sequence[Listed], *, home: Path, machine: Path, runner: Runner,
    yes: bool, sync: bool) -> RestoreReport` — per listed project: `absent` when `dir` is not there;
    otherwise `attach(dir, store=permitted_roots(overlay, name)[1], machine=machine, runner=runner,
    owner=command_owner(machine), project=None)`, a `Refusal` → `refused`, a `Failure` → `failed`,
    each with the message as `detail`, and the next project goes on. Task 6 fills `plugins` and
    `notes`; Task 7 fills `promoted` and `sync`.
- `setup --restore` in `run_setup`: before anything is written, the overlay root is `--overlay`'s
  path when it names one that holds an overlay, else the machine file's recorded root, and
  `listed_projects` reads it; `--overlay create:…` or a vacant path lists nothing. No overlay at all
  is a `Refusal` ("--restore restores from an overlay: name it with --overlay PATH"). Then today's
  `setup(...)`, then `restore(...)`. `--restore` joins `--overlay` and `--preset` in the flags
  `--git-hooks` and `--approval-boundary` refuse beside them. The `Result`'s summary is setup's,
  then one line per project; its exit code is 1 when a project is `refused` or `failed`, else 0;
  `--json` carries each outcome's `name`, `dir`, `state` and `detail`; `name` and `dir` come from the
  overlay, which is the owner's, and `detail` is attach's own message, already printed through
  `stayfixed.printed`.
- **Anchor sentence** (for `restore`'s docstring and the security seat): a listed checkout's tracked
  `stayfixed.toml` can claim another of the owner's projects; the store restore hands `attach` comes
  from the table key in `<overlay>/machine/projects.toml`, which no repository writes, and
  attach refuses a store that is not the checkout's own project's, so such a checkout is refused
  rather than given another project's notes, rules and delivery.

- [ ] **Step 1: Write the failing tests**

In `tests/setup/test_restore.py`, a fixture overlay under `tmp_path` built the way the attach
tests build theirs (re-measure the helper), checkouts from `tests.gitfixture`, a `Recorder` runner,
`home` and `machine` under `tmp_path`:

```python
def test_a_listed_checkout_that_exists_is_attached(...)
    # outcome "attached"; the binding record exists under the overlay's projects/<name>/
def test_a_listed_dir_that_is_not_there_is_reported_and_skipped(...)
    # outcome "absent"; nothing created at that path; the run's exit code is 0
def test_a_checkout_whose_project_is_not_its_table_key_is_refused_and_the_rest_attach(...)
    # alpha's checkout tracks a stayfixed.toml naming "beta"; listed as alpha: "refused",
    # no `.stayfixed/local/attach.json` and no binding id in its git directory; gamma attached
def test_a_table_key_that_is_no_project_name_is_refused_and_the_rest_attach(...)
    # [projects."../x"]: "refused"; nothing written outside tmp_path's overlay; gamma attached
def test_a_listed_dir_that_is_no_checkout_is_reported_and_the_rest_attach(...)
def test_a_relative_dir_is_refused_before_anything_is_written(...)
    # through the command: Refusal (exit 2), the machine file does not exist afterwards
def test_keys_the_product_does_not_read_are_ignored(...)
    # branch, sync, exclude, links in a table change nothing
def test_restore_twice_changes_nothing_the_second_time(...)
    # second run: every outcome "attached", attach notes "already recorded", the checkout's
    # tracked and excluded files byte-equal to after the first run (`tests/snapshot.py`)
def test_restore_never_detaches_a_project_no_longer_listed(...)
def test_one_failed_attach_leaves_the_others_and_exits_1(...)
    # the Recorder answers the failing project's delivery install with exit 1
def test_restore_without_an_overlay_is_refused_before_anything_is_written(...)
def test_restore_is_refused_beside_git_hooks_and_approval_boundary(...)
```

In `tests/test_install_path.py`, end to end through the CLI with its fake binaries:
`test_restore_attaches_every_listed_checkout_and_detach_undoes_it` — `setup --restore --overlay
<fixture> --home … --machine …` with one present and one absent project, `doctor`'s `attached` row
ok for the present one, then `detach` there returns the checkout to its starting snapshot.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/setup/test_restore.py -q`
Expected: collection fails with `ModuleNotFoundError: stayfixed.setup.restore`.

- [ ] **Step 3: Implement `restore.py`, the command wiring and the `src/stayfixed/attach/api.py` names**

The tools line is printed first and refuses nothing: a missing `git` makes each attach fail with
attach's own words.

- [ ] **Step 4: Run the focused tests and the boundaries**

Run: `uv run pytest tests/setup tests/attach tests/boundaries tests/test_surfaces.py tests/test_install_path.py -q -n auto`
Expected: all pass. `tests/boundaries/test_delivery.py` takes `setup` → `attach.api` and
`setup` → `memory.api` as delivery-to-delivery after #158; if it refuses either, report the output.

- [ ] **Step 5: Declare the mutation and run it**

Entry: name "restore attaches without the store its table key names", file
`src/stayfixed/setup/restore.py`, `before` the `store=permitted_roots(...)` argument, `after`
`store=None`, reddens
`tests/setup/test_restore.py::test_a_checkout_whose_project_is_not_its_table_key_is_refused_and_the_rest_attach`.
Commit, then `uv run python scripts/mutation_oracle.py "restore attaches"`. Expected: caught; paste
the line.

- [ ] **Step 6: Document and commit**

`docs/cli.md`'s `setup` section: `--restore` and its five steps; the input, `<overlay>/machine/projects.toml`:
one `[projects.<name>]` table per project, `<name>` the overlay project the checkout belongs to,
`dir` where its main checkout lives (absolute or `~/`), every other key ignored by stayfixed (an
overlay's own scripts may read them); the steps an overlay's own script keeps (cloning, owner-held
files, excludes, links, commit hooks, the settings merge); the **Writes** paragraph: what `setup`
writes, and for each attached checkout what `attach` writes, by reference to its section. The
README command list gains the flag.

```bash
git add src/stayfixed/setup src/stayfixed/attach/api.py tests/setup tests/test_install_path.py docs/cli.md README.md changelog.d mutations
git commit -m "feat(setup): restore a machine's attached checkouts from the overlay's projects file"
```

### Task 6: `--restore` installs the plugins the overlay's machine layer lists

**Files:**
- Modify: `src/stayfixed/setup/restore.py`, `README.md` ("What stayfixed sends where", the
  `claude plugin` row), `docs/cli.md`
- Test: `tests/setup/test_restore.py`, and `tests/test_outbound.py`'s declarations if it reports the
  new launch site

**Interfaces:**
- `PLUGINS_FILE = Path("machine") / "claude" / "settings.json"` — the overlay's copy of Claude
  Code's user settings; restore reads two keys of it and writes nothing from it.
- `listed_plugins(overlay: Path) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...],
  tuple[str, ...]]` — `(marketplaces as (name, add-argument), plugin ids, notes)`.
  `extraKnownMarketplaces.<name>.source`: `{"source": "github", "repo": "owner/name"}` with an
  optional `ref` gives `owner/name[@ref]`; `{"source": "git", "url": …}` with an `https://` or
  `git@` URL gives the URL; any other shape, or a value that could read as an option, is a note
  and is not added. `enabledPlugins` entries whose value is `true` and whose id matches
  `<name>@<marketplace>` are the ids. No file: `((), (), ())`.
- `install_listed(marketplaces, ids, *, home: Path, runner: Runner) -> tuple[tuple[str, ...],
  tuple[str, ...]]` — `(installed ids, notes)`: `claude plugin marketplace list --json` and
  `claude plugin list --json`, then `claude plugin marketplace add <argument>` for each listed
  marketplace not registered and `claude plugin install <id>` for each id not installed at user
  scope; a non-zero exit is a note naming the argv, never a refusal. Without `claude` on `PATH`, one
  note and nothing launched. The overlay's list is Claude Code's; Codex gets one note.

- [ ] **Step 0: Measure the two listings' shapes**

Under a scratch `HOME` (`HOME=<scratch> claude plugin marketplace list --json` and
`HOME=<scratch> claude plugin list --json`, after one `marketplace add` of a public marketplace
there), paste both outputs; the field names `install_listed` reads come from them, and the
`Recorder`'s canned answers copy them. If `claude` is not installed here, say so and stop.

- [ ] **Step 1: Write the failing tests**

```python
def test_only_the_missing_marketplaces_and_plugins_are_installed(...)
def test_a_second_restore_installs_nothing(...)
def test_a_marketplace_source_of_another_shape_is_a_note_and_not_added(...)
def test_a_failed_install_is_a_note_and_the_projects_still_attach(...)
def test_no_claude_on_path_is_one_note_and_no_launch(...)
def test_an_overlay_with_no_machine_settings_lists_no_plugins(...)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/setup/test_restore.py -q -k "plugin or marketplace or claude"`
Expected: `ImportError` for `listed_plugins`.

- [ ] **Step 3: Implement, wire into `restore` between machine setup and the attach loop**

- [ ] **Step 4: Run the focused tests and the outbound walk**

Run: `uv run pytest tests/setup tests/test_outbound.py tests/test_documents.py -q -n auto`
Expected: all pass once the README row names `setup --restore` beside `setup --plugin`.

- [ ] **Step 5: Commit**

```bash
git add src/stayfixed/setup/restore.py tests/setup README.md docs/cli.md tests/test_outbound.py
git commit -m "feat(setup): restore installs the plugins the overlay's machine settings enable"
```

### Task 7: `--yes` records the notes as reviewed; `--sync` switches sync on

**Files:**
- Modify: `src/stayfixed/setup/restore.py`, `src/stayfixed/setup/commands.py`,
  `src/stayfixed/memory/api.py` (`promote_changed`), the memory module that defines it,
  `src/stayfixed/memory/commands.py` (`run_promote --changed` calls it), `docs/cli.md`
- Test: `tests/setup/test_restore.py`

**Interfaces:**
- `stayfixed.memory.api.promote_changed(root: Path, *, machine: Path | None) -> list[Path]` — the
  notes `memory promote --changed --root root` would promote, promoted, by the same code path that
  command now calls; the docstring names `setup --restore` as the consumer.
- `restore(..., yes=True)`: after each attached project, `promote_changed(dir, machine=machine)`;
  its count is the outcome's `promoted`. Without `--yes`, nothing is recorded as reviewed.
  **Anchor sentence:** `--yes` is the owner's word on their own command line, the same act as
  `memory promote --changed` in each attached checkout; it adds no control and removes none.
- `--sync`: sets the machine file's `[sync] enabled = true` through the writer lane 5 gives
  `setup --overlay`; without `--sync` restore never writes `[sync]`. `--yes` and `--sync` without
  `--restore` are refused, as `--uninstall` without `--git-hooks` is.
- **Dependency:** `--sync` needs lane 5's `[sync]` class and writer on `next`. When the pre-flight
  finds them absent, implement `--yes` only, leave `--sync` out of the parser, and report; the
  controller decides whether pull request B waits for lane 5 or `--sync` follows it.

- [ ] **Step 1: Write the failing tests**

```python
def test_without_yes_no_note_is_recorded_as_reviewed(...)
def test_yes_records_every_unreviewed_note_of_each_attached_project(...)
def test_a_second_restore_with_yes_promotes_nothing(...)
def test_sync_switches_sync_on_in_the_machine_file(...)
def test_without_sync_the_machine_file_keeps_its_sync_setting(...)
def test_yes_and_sync_are_refused_without_restore(...)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/setup/test_restore.py -q -k "yes or sync"`
Expected: argparse refuses `--yes` (exit 2) and the promote assertions fail.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the focused tests, then the memory area**

Run: `uv run pytest tests/setup tests/memory tests/boundaries -q -n auto`
Expected: all pass; `memory promote --changed`'s own tests unchanged.

- [ ] **Step 5: Declare the mutation and run it**

Entry: name "restore records notes as reviewed without --yes", file
`src/stayfixed/setup/restore.py`, `before` the `if yes` line, `after` the line made always true,
reddens `tests/setup/test_restore.py::test_without_yes_no_note_is_recorded_as_reviewed`. Commit,
then `uv run python scripts/mutation_oracle.py "without --yes"`. Expected: caught; paste the line.

- [ ] **Step 6: Document and commit**

`docs/cli.md`: `--yes` and `--sync`, their **Writes** (the trust record's reviewed notes, the
machine file's `[sync]`), and how each is undone (edit or delete a note; `[sync] enabled = false`).

```bash
git add src/stayfixed/setup src/stayfixed/memory tests/setup docs/cli.md mutations
git commit -m "feat(setup): restore records the overlay's notes as reviewed with --yes and switches sync on with --sync"
```

**Pull request B:** merge the current `origin/next` first; full suite, static checks,
`release.py check`; push `restructure/restore`; open into `next` with the net size, the Task 3
import counts and each anchor sentence; final review with three seats (the security seat reads the
wrapper, the route and the restore anchor); one fix round; re-review; `gh run watch`; report. The
report to the controller (not the pull request body) lists the overlay-side callers this changes.

---

## Findings

Filled in as the waves run: each implementer's token total, the review findings with their
dispositions, the Minors left as follow-ups, and every place the tree differed from this plan.
