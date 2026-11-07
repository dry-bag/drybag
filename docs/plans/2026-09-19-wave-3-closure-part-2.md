# Wave 3 closure — the deferred lane, `skills-author`, `workflows`, `release`: Implementation Plan, part 2
**Scope:** continuation of [part 1](2026-09-19-wave-3-closure.md); its Scope line governs

## Wave E — Tasks 13-15: `workflows`

§15.2: "**workflows** — reusable `check.yml` (base-ref state), smoke workflow with both call
forms and the exfiltration scenario", depending on `ledger`, `docs-tooling`, `guards` and
`hooks-core`, all merged. §5.8 adds the whole-tree gate, which the two lane copies have been
holding the door for since wave 2.

### Task 13: the whole-tree neutrality gate

**Files:**
- Create: `tests/test_neutral.py` (from `tests/test_neutral_wave2.py` and
  `tests/guards/test_neutral.py`: `_digest`, `digest_of`, `FORBIDDEN`, `_URL`, `URL_BLIND`,
  `SHAPES`, `offending`, `_preset_paths`, `PUBLIC_FORBIDDEN`, and the five tests
  `test_the_denylist_is_stored_as_digests`, `test_the_digest_function_is_pinned`,
  `test_the_gate_discriminates`, `test_the_exemption_is_exactly_the_presets_default_paths`,
  `test_the_public_table_still_discriminates`, plus
  `test_mutations_toml_carries_no_source_repository_string` scoped as today)
- Delete: `tests/test_neutral_wave2.py`, `tests/guards/test_neutral.py`
- Modify: `mutations.toml` (every entry whose `file` or `reddens` names one of the two
  deleted modules now names `tests/test_neutral.py`)
- Modify: any document, and any source file no in-flight wave holds, that the first
  whole-tree run reports (Step 2); hits in files Wave C or D is editing are deferred to
  Task 20 through `DEFERRED_TO_WAVE_G`

**Interfaces:**
- Produces: `tests.test_neutral.{offending, digest_of, FORBIDDEN, PUBLIC_FORBIDDEN,
  tracked_files, table_for}`; `tracked_files() -> list[Path]`; `table_for(path: Path) ->
  tuple[tuple[int, str], ...]`.

- [ ] **Step 1: Write the walk and its non-vacuity test**

```python
# tests/test_neutral.py  (the walk; the moved functions and tests keep their bodies)
"""§5.8: no project-identifying string anywhere in the public repository — the whole tree.

Two lane-scoped copies of this gate held the door since wave 2, the second of them saying
"both gates are deleted the day the `workflows` lane ships the whole-tree gate — do not
extend either into a third." This is that day. Source under `src/`, `tests/` and `scripts/` is held to the full
table: a module has no reason to spell a default path. Every other tracked text file is
held to the public table, which exempts exactly the preset's own default `[paths]` values,
because a document that could not say where the note store lives by default would be
useless. The denylist is digests; the two docstrings this replaces say why, and their
reasoning is kept verbatim in `digest_of`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
THIS = Path(__file__).resolve()
FULL_TABLE_TREES = ("src", "tests", "scripts")
# Only for the fallback walk in an unpacked sdist, where `git ls-files` cannot answer.
FALLBACK_EXCLUDED = {
    ".git", ".venv", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "htmlcov", ".claude", ".superpowers",
}


def tracked_files() -> list[Path]:
    """Every file git tracks, or every file under the tree minus the fixed exclusions."""
    # `--others --exclude-standard` as well as `--cached`: a fixture added in this wave is
    # untracked until its commit, and a gate that could not see it until the commit after
    # would let the commit that adds it land unwalked. Step 2 says `git add -N` first.
    done = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=False,
    )
    if done.returncode == 0 and done.stdout:
        names = [n for n in done.stdout.decode("utf-8").split("\0") if n]
        return sorted(ROOT / n for n in names if (ROOT / n).is_file())
    # Anchored on the FIRST component: `tests/fixtures/hostile-project/.claude/settings.json`
    # is a fixture to walk, not a configuration directory to skip.
    return sorted(
        p for p in ROOT.rglob("*")
        if p.is_file() and p.relative_to(ROOT).parts[0] not in FALLBACK_EXCLUDED
    )


def table_for(path: Path) -> tuple[tuple[int, str], ...]:
    relative = path.relative_to(ROOT)
    if relative.parts[0] in FULL_TABLE_TREES and (path.suffix == ".py" or relative.parts[0] == "scripts"):
        return FORBIDDEN
    return PUBLIC_FORBIDDEN


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def test_the_gate_reads_the_whole_tree() -> None:
    # The non-vacuity guard for the parametrised walk below. Named files from six different
    # trees, and a floor well under today's count (measured when written; say the number in
    # the commit), so a walk that stopped at one directory cannot pass.
    files = tracked_files()
    names = {str(p.relative_to(ROOT)) for p in files}
    # No `.github/` name here: that tree is outside `source-include`, and this floor has to
    # hold in the unpacked sdist the fallback walk exists for.
    for wanted in (
        "README.md", "src/keelline/cli.py", "docs/cli.md", "mutations.toml",
        "hooks/run-hook.sh", "scripts/keelline", "tests/test_fsops.py",
    ):
        assert wanted in names, wanted
    assert len(files) >= 200, len(files)
    assert THIS in files


@pytest.mark.parametrize(
    "path",
    [p for p in tracked_files() if p != THIS],
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_no_tracked_file_carries_a_project_identifying_string(path: Path) -> None:
    text = _text(path)
    if text is None:
        pytest.skip("binary")
    assert offending(text, table_for(path)) == [], path
```

`offending`, `FORBIDDEN`, `PUBLIC_FORBIDDEN` and the rest come above this block, verbatim
from the two deleted modules (one copy). `test_mutations_toml_carries_no_source_repository_string`
keeps its scope (the `guards` entries under the full table).

- [ ] **Step 2: Measure before editing anything else**

Run: `git add -N tests/test_neutral.py && uv run pytest tests/test_neutral.py -q 2>&1 | tail -40`
(`git add -N` records the intent so the walk sees the new file; `assert THIS in files` fails
otherwise.)
Expected: the walk passes its floor; some parametrised cases FAIL — every one is a finding
of this task. List them in the commit message with the digest each hit. Then, per hit:

- a **source module** spelling a default path (`token` under the full table): reword the
  comment or docstring to say "the configured memory path", "the ledger directory", "the
  plans directory" — the rule the lane gates already state, applied to the modules they
  never walked;
- a **document** hit under the public table: neutralise the text;
- a **shape** hit (`personal email`, `bare commit id`, `vendor branch`): rewrite it.

A source hit in a file another in-flight wave holds — `src/keelline/fsops.py` and
`src/keelline/memory/worktree.py` (Wave C), `src/keelline/guards/attribute.py` and
`src/keelline/guards/commands.py` (Wave D) — is **not** reworded here: list it in
`DEFERRED_TO_WAVE_G`, a tuple of relative paths beside `FULL_TABLE_TREES` that
`test_no_tracked_file_carries_a_project_identifying_string` marks `xfail(strict=True)` for,
with the reason "reworded in Task 20 once Waves C and D have merged". Task 20 empties the
tuple. **If the count of source hits exceeds twenty, stop and report the list before
rewording any** — that many is a scope decision for the controller, not an afternoon for
the implementer. Record the wall clock of this run beside the count: the walk hashes every
byte window at each stored length over `uv.lock`, `mutations.toml` and the plans, and the
number is what decides whether the parametrisation needs to skip the two lockfile-sized
data files by name.

- [ ] **Step 3: Delete the two copies and re-point the entries**

`git rm tests/test_neutral_wave2.py tests/guards/test_neutral.py`; every `mutations.toml`
entry naming either now names `tests/test_neutral.py` and the same test name — except
`"the two copies of the neutrality gate diverge again"`, whose test
(`test_the_two_copies_of_the_gate_agree`) has no successor because there is one copy now:
delete that entry, and say so in the commit.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_neutral.py -q && uv run python scripts/mutation_oracle.py neutral`
Expected: PASS; every re-pointed entry `caught`.

- [ ] **Step 5: Run the full gate, sweep, commit**

```bash
uv run python "$SCRATCH/neutral_hits.py" $(git diff --name-only --cached)
git add -A tests mutations.toml src docs README.md
git commit -m "test: hold the whole tree to the neutrality gate, and retire the two lane copies"
```

The commit message carries the before-count from Step 2 and the list of files reworded.

### Task 14: `check.yml`, and the fixture project it runs against

**Files:**
- Create: `.github/workflows/check.yml`
- Create: `tests/fixtures/smoke-project/` — and under it, every path below: `keelline.toml`, `AGENTS.md`, `docs/roadmap.md`,
- Create: `docs/roadmap-history.md`, `docs/bugs/BR-001.md`, `docs/bug-reports.md` (generated),
- Create: the bug runbook, `docs/specs/README.md`, `docs/plans/README.md`,
- Create: the architecture directory's `README.md`, `docs/adr/README.md`, and whatever else the five gates
  need (Step 3 measures it)
- Create: `tests/test_fixtures.py`
- Modify: `docs/cli.md` (a `## The reusable workflow` section above `## Shared flags`),
  `README.md` (one paragraph under `## Install`: how a project calls the workflow)

**Interfaces:**
- Consumes: `keelline docs check`, `bugs check`, `plan check --base`, `commit check
  --range`, `docs trail --check`, each with `--root`.
- Produces: the reusable workflow with inputs `base: string = ""`, `path: string = "."`,
  `python-version: string = "3.13"`; the fixture project, `state = "installed"`, that every
  gate passes on.

- [ ] **Step 1: Write the fixture's contract test**

```python
# tests/test_fixtures.py
"""The two fixture projects the smoke workflow runs against, held to what they claim.

`smoke-project` is a project every gate passes on, with `state = "installed"` so the gates
enforce; `hostile-project` (Task 15) is the S10 clone. Both are read by CI from this tree,
so a fixture that drifted from what a gate accepts would fail the smoke workflow with a
message about the fixture rather than about Keelline.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from keelline.cli import build_parser, discover_registrars, run

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tests" / "fixtures" / "smoke-project"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _copy_as_repository(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(SMOKE, root)
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": "/usr/bin:/bin"}
    # Two commits, so that `commit check --range HEAD~1..HEAD` checks one message rather than
    # an empty range that proves nothing.
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "chore: the fixture"],
        ["-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "docs: a second message to check"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)
    return root


@needs_git
@pytest.mark.parametrize(
    "argv",
    [
        ["docs", "check"],
        ["bugs", "check"],
        ["docs", "trail", "--check"],
        ["plan", "check"],
        ["commit", "check", "--range", "HEAD~1..HEAD"],
    ],
    ids=lambda argv: " ".join(argv),
)
def test_every_gate_the_workflow_runs_passes_on_the_smoke_fixture(tmp_path: Path, argv: list[str]) -> None:
    # Mutation: delete `docs/roadmap.md`'s trail marker in the fixture -> `docs trail --check`
    # reddens (measured by hand, not declared: the fixture is data and the oracle mutates
    # source).
    root = _copy_as_repository(tmp_path)
    parser = build_parser(discover_registrars())
    with redirect_stdout(io.StringIO()) as out:
        code = run([*argv, "--root", str(root), "--machine", str(tmp_path / "m.toml")], parser=parser)
    assert code == 0, out.getvalue()


def test_the_smoke_fixture_is_installed_so_the_gates_enforce() -> None:
    import tomllib

    config = tomllib.loads((SMOKE / "keelline.toml").read_text(encoding="utf-8"))
    assert config["keelline"]["state"] == "installed"
    assert config["project"]["name"] == "smoke"
```

`plan check` with no paths lints the plans the diff touched against `origin/<base>`; in a
fresh repository with no `origin`, read what the command does (`docs/cli.md`) and, if it
refuses without a remote, give the fixture test a `--base HEAD` or pass the README path
explicitly — and say which in the commit.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_fixtures.py -q`
Expected: FAIL, `FileNotFoundError` on the fixture.

- [ ] **Step 3: Write the fixture, gate by gate**

*tests/fixtures/smoke-project/keelline.toml*:

```toml
# A project every gate passes on: the smoke workflow's caller, and `check.yml`'s
# same-repository and cross-repository forms both run against it. `init --yes` writes the
# real one when the templates package ships; until then this is hand-written and its
# version is whatever this Keelline is — `doctor` warns on drift and nothing fails.
[keelline]
version = "0.1.0"
state = "installed"

[project]
name = "smoke"
base_branch = "main"
```

Then create each document the gates read, running the five commands from Step 1 against a
copy until each exits 0, and commit **what they accepted**: `AGENTS.md` (a heading and two
sentences, under every budget), `docs/roadmap.md` with the trail marker line and the end
marker `docs trail` writes, *docs/bugs/BR-001.md* (one `fixed` entry, severity `low`, with
its `## Fix` section), *docs/bug-reports.md* produced by `keelline bugs index --root <copy>`
and copied back, the bug runbook (the index's header links it), and a
`README.md` under `docs/specs/`, `docs/plans/`, the architecture directory and `docs/adr/` so the
trail and the link walk have directories to list. Every word in the fixture is neutral:
the whole-tree gate (Task 13) walks it under the public table.

- [ ] **Step 4: Write the workflow**

```yaml
# .github/workflows/check.yml
#
# The reusable workflow a project calls (§5.8). It checks out the caller, checks out Keelline
# at THIS FILE's own commit — no resolver, no build backend, no network beyond the two
# checkouts — and runs the documentation, ledger, plan, commit-message and trail gates with
# `python3 -m keelline`. The gate's configuration is read from the base ref (§8.3): the
# base's own copy of `keelline.toml` decides the state, and on any branch but the base itself
# the tree's copy must equal it. While the base's state is not `installed`, every check is
# advisory and annotates. Every value that reaches a shell here arrives through `env:`; a
# `${{ }}` spliced into `run:` is a command injection waiting for a ref name that permits it.
#
# **Anchor provenance, said once.** The base ref comes from the caller's `with:`, from the
# pull request's base, or from the repository's default branch as the platform reports it —
# never from the tree under review. The Keelline that runs comes from the platform's own
# record of which reusable workflow is executing (`job.workflow_repository`,
# `job.workflow_sha`), never from the caller's inputs. The design's §5.8 names a
# `github.job_workflow_sha` property; the platform documents no such property on the
# `github` context (an undefined property is the empty string, and `actions/checkout` with
# an empty `ref` checks out the DEFAULT BRANCH — a pin silently turned into a floating ref),
# so this file departs from the design on that point of fact and asserts the checkout it got.
name: keelline-check

on:
  workflow_call:
    inputs:
      base:
        description: "the branch the gate's configuration is read from; empty means the pull request's base, or the repository's default branch on a push"
        type: string
        default: ""
      path:
        description: "the project root inside the caller's checkout"
        type: string
        default: "."
      python-version:
        type: string
        default: "3.13"

permissions:
  contents: read

jobs:
  gates:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        shell: bash
    steps:
      - name: The caller's repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          path: project
          fetch-depth: 0
          persist-credentials: false
      - name: Keelline, at this workflow's own commit
        # The `job.workflow_*` properties are unavailable on GitHub Enterprise Server.
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          repository: ${{ job.workflow_repository }}
          ref: ${{ job.workflow_sha }}
          path: keelline
          persist-credentials: false
      - name: The checkout is the commit this workflow file is at
        # The assertion that would have caught an empty `ref`: a default-branch checkout
        # answers a different sha.
        env:
          EXPECTED: ${{ job.workflow_sha }}
        run: |
          actual="$(git -C keelline rev-parse HEAD)"
          [ "$actual" = "$EXPECTED" ] || { echo "::error::checked out $actual, not the workflow's own $EXPECTED"; exit 1; }
      - uses: actions/setup-python@e797f83bcb11b83ae66e0230d6156d7c80228e7c # v6.0.0
        with:
          python-version: ${{ inputs.python-version }}
      - name: The base ref, and the configuration it carries
        id: base
        working-directory: project
        env:
          INPUT_BASE: ${{ inputs.base }}
          INPUT_PATH: ${{ inputs.path }}
          PR_BASE: ${{ github.base_ref }}
          DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
          CURRENT_REF: ${{ github.ref }}
        run: |
          set -o pipefail
          p="${INPUT_PATH#./}"; [ "$p" = . ] && p=""
          file="${p:+$p/}keelline.toml"
          base="$INPUT_BASE"
          [ -n "$base" ] || base="$PR_BASE"
          [ -n "$base" ] || base="$DEFAULT_BRANCH"
          [ -n "$base" ] || { echo "::error::no base ref: pass `base:`"; exit 1; }
          git check-ref-format --branch "$base" >/dev/null
          git fetch --quiet origin "$base"
          # Three states of the base's copy, each named. Absent: an adopting project whose
          # base branch carries no configuration yet (the bootstrap; D8 says it is not
          # installed). Present and readable: the gate's configuration. Present and
          # unreadable: a failure, never a default — `git show | python` without pipefail
          # turned a failed `git show` into `state=initialised`, which is the gate reporting
          # green with nothing enforced.
          if git cat-file -e "origin/$base:$file" 2>/dev/null; then
            state="$(git show "origin/$base:$file" | python3 -c 'import sys, tomllib; s = tomllib.loads(sys.stdin.read()).get("keelline", {}).get("state", "initialised"); print(s if s in {"initialised", "adopting", "installed"} else "initialised")')"
            if [ "$CURRENT_REF" != "refs/heads/$base" ] && ! git diff --quiet "origin/$base" -- "$file"; then
              if [ "$state" = installed ]; then
                echo "::error file=$file::keelline.toml differs from origin/$base; a pull request may not change an installed project's gate configuration (the keys a pull request may change arrive with assess)"
                exit 1
              fi
              echo "::warning file=$file::keelline.toml differs from origin/$base; advisory while the base's state is $state"
            fi
          else
            echo "::notice::$file is not on origin/$base; treating this project as not yet installed"
            state=absent
          fi
          {
            echo "base=$base"
            echo "root=project/${p:-.}"
            echo "state=$state"
            echo "enforce=$([ "$state" = installed ] && echo true || echo false)"
          } >> "$GITHUB_OUTPUT"
      - name: docs check
        id: docs
        continue-on-error: true
        env: { PYTHONPATH: keelline/src, ROOT: "${{ steps.base.outputs.root }}" }
        run: python3 -m keelline docs check --root "$ROOT"
      - name: bugs check
        id: bugs
        continue-on-error: true
        env: { PYTHONPATH: keelline/src, ROOT: "${{ steps.base.outputs.root }}" }
        run: python3 -m keelline bugs check --root "$ROOT"
      - name: plan check
        id: plan
        continue-on-error: true
        env: { PYTHONPATH: keelline/src, ROOT: "${{ steps.base.outputs.root }}", BASE: "${{ steps.base.outputs.base }}" }
        run: python3 -m keelline plan check --root "$ROOT" --base "origin/$BASE"
      - name: commit check
        id: commit
        continue-on-error: true
        env: { PYTHONPATH: keelline/src, ROOT: "${{ steps.base.outputs.root }}", BASE: "${{ steps.base.outputs.base }}" }
        run: python3 -m keelline commit check --root "$ROOT" --range "origin/$BASE..HEAD"
      - name: docs trail
        id: trail
        continue-on-error: true
        env: { PYTHONPATH: keelline/src, ROOT: "${{ steps.base.outputs.root }}" }
        run: python3 -m keelline docs trail --check --root "$ROOT"
      - name: Verdict
        # Every gate ran, whatever the first one said — a project fixing gates one round
        # trip at a time was the alternative. Enforcing: any failed gate fails the job.
        # Advisory (D8: `initialised`, `adopting`, or no configuration on the base yet):
        # each failed gate is one warning, and the job is green.
        env:
          ENFORCE: ${{ steps.base.outputs.enforce }}
          STATE: ${{ steps.base.outputs.state }}
          O_DOCS: ${{ steps.docs.outcome }}
          O_BUGS: ${{ steps.bugs.outcome }}
          O_PLAN: ${{ steps.plan.outcome }}
          O_COMMIT: ${{ steps.commit.outcome }}
          O_TRAIL: ${{ steps.trail.outcome }}
        run: |
          failed=0
          for pair in "docs:$O_DOCS" "bugs:$O_BUGS" "plan:$O_PLAN" "commit:$O_COMMIT" "trail:$O_TRAIL"; do
            name="${pair%%:*}"; outcome="${pair#*:}"
            if [ "$outcome" = failure ]; then
              failed=$((failed + 1))
              if [ "$ENFORCE" = true ]; then echo "::error::$name failed"; else echo "::warning::$name failed, advisory while the base's state is $STATE"; fi
            fi
          done
          [ "$ENFORCE" != true ] || [ "$failed" -eq 0 ]
```

The action SHAs are the ones `ci.yml` pins today; Dependabot bumps them together.
`python3 -m keelline` with `PYTHONPATH=keelline/src` is what §5.8 asks for: "it checks out
Keelline at [the workflow's own commit] and runs `python3 -m keelline`, so it needs no
resolver, no build backend and no network beyond the checkout" — with the property name
corrected as the file's header comment records. `set -o pipefail` and `shell: bash` are
both there because the platform's default `run` shell on Linux is `bash -e` **without**
pipefail. `tests/test_fixtures.py` gains a case for the absent-on-base arm: a fixture copy
whose base branch has no `keelline.toml` is judged advisory, not refused (assert on the
shell logic by running the step's script body with `bash` against the copy, with
`INPUT_PATH`, `CURRENT_REF` and a fetched `origin` set as the workflow sets them).

- [ ] **Step 5: Document it**

`docs/cli.md`, a section `## The reusable workflow` above `## Shared flags`: the caller's
YAML —

```yaml
jobs:
  keelline:
    uses: Nezhinskiy/keelline/.github/workflows/check.yml@<40-hex sha>
    with:
      base: main
```

— the three inputs, the base-ref rule and its strict form, the advisory rule, and that the
SHA pin is what `init` will write and `upgrade` bump (D16; `v1` is the documented opt-in).
`README.md`, under `## Install`, one paragraph: "In CI, a project calls the reusable
workflow at a commit SHA; `docs/cli.md` shows the three lines." The `.github/workflows/`
tree is not in the sdist and needs no `source-include` line.

- [ ] **Step 6: Run the tests, the full gate, sweep, commit**

```bash
uv run pytest tests/test_fixtures.py tests/test_neutral.py tests/test_documents.py -q
uv run python "$SCRATCH/neutral_hits.py" $(git ls-files --others --exclude-standard tests/fixtures) .github/workflows/check.yml docs/cli.md README.md
git add .github/workflows/check.yml tests/fixtures/smoke-project tests/test_fixtures.py docs/cli.md README.md
git commit -m "feat(workflows): the reusable check workflow, reading its configuration from the base ref, and the fixture it runs on"
```

No mutation entry: a workflow is not mutated by the oracle; its proof is Task 15's two
call forms, which run it.

### Task 15: `smoke.yml` — the installed plugin, every hook, both call forms, and S10

**Files:**
- Create: `scripts/smoke_hooks.py`, `scripts/smoke_exfiltration.py`
- Create: `tests/fixtures/hostile-project/` (`keelline.toml`, `docs/memory/MEMORY.md`,
- Create: `docs/memory/developer/canary.md`, `.claude/settings.json`, `README.md`)
- Create: `tests/scripts/test_smoke_scripts.py`
- Create: `.github/workflows/smoke.yml`, `.github/workflows/smoke-release.yml`
- Modify: `tests/test_fixtures.py` (the hostile fixture's contract), `docs/cli.md` (the
  reusable-workflow section names the smoke), `RELEASING.md` (one line: the version of the
  harness CLI the smoke pins, and that it is bumped by hand)

**Interfaces:**
- Consumes: `hooks/hooks.json`'s shape (`hooks.<event>[].hooks[].command` with
  `${CLAUDE_PLUGIN_ROOT}`), `hooks/run-hook.sh`'s argv, `keelline doctor --json`,
  `keelline attach`, `keelline memory session-context`.
- Produces: `smoke_hooks.main(argv) -> int` with `--plugin-root`, `--fixture`, `--scratch`
  (the fixture is copied to `<scratch>/project` and committed; `<scratch>/home` and
  `<scratch>/data` are created); `smoke_exfiltration.main(argv) -> int` with the same
  three flags; both print one row per assertion and exit 1 on any mismatch.

- [ ] **Step 1: Write the scripts' tests**

```python
# tests/scripts/test_smoke_scripts.py
"""The two smoke scripts, run here against the checkout as the plugin root.

CI runs them against the INSTALLED copy (DC8); this proves the scripts' own logic — that a
mismatch is reported and a match is not — so a green CI row means the plugin, not the script.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@needs_git
def test_every_hook_entry_answers_its_sample_event_through_the_checkout(tmp_path: Path) -> None:
    # S8's matrix lives in tests/hooks/test_wrapper.py; this is the positive row per entry:
    # every `hooks.json` command, fed the event it is filed under, exits as the policy says.
    # The closed `PreToolUse` entry is fed a leaking background command and must exit 2 with
    # a reason; every open entry exits 0.
    smoke = _load("smoke_hooks")
    code = smoke.main(
        ["--plugin-root", str(ROOT), "--fixture", str(ROOT / "tests" / "fixtures" / "smoke-project"), "--scratch", str(tmp_path)]
    )
    assert code == 0


@needs_git
def test_a_wrapper_that_answers_wrongly_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The script's own oracle: a plugin root whose wrapper exits 0 on everything must make
    # the closed row fail. Mutation (declared): drop the `expected != done.returncode`
    # comparison in `smoke_hooks.check_entry` -> this passes with code 0 and reddens.
    smoke = _load("smoke_hooks")
    planted = tmp_path / "plugin"
    shutil.copytree(ROOT / "hooks", planted / "hooks")
    (planted / "scripts").mkdir()
    (planted / "scripts" / "keelline").write_text("raise SystemExit(0)\n", encoding="utf-8")
    code = smoke.main(
        ["--plugin-root", str(planted), "--fixture", str(ROOT / "tests" / "fixtures" / "smoke-project"), "--scratch", str(tmp_path)]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "exited 0, expected 2" in out  # the closed row, for its own reason


@needs_git
def test_the_exfiltration_scenario_holds_against_the_checkout(tmp_path: Path) -> None:
    # S10 (§14): a hostile clone with in-repo memory at `startup: -1`, a `project.name`
    # naming another project, and a committed settings `env` block naming a machine
    # configuration inside the clone and a PATH into the clone. Asserted separately: nothing
    # untrusted reaches the session-start output, the hook ignored the clone's
    # KEELLINE_CONFIG, the planted interpreter never ran, and `attach` refuses. The MCP arm
    # is not run: `mcp` is not in wave 3, and the script says so in its own output.
    exfil = _load("smoke_exfiltration")
    code = exfil.main(
        ["--plugin-root", str(ROOT), "--fixture", str(ROOT / "tests" / "fixtures" / "hostile-project"), "--scratch", str(tmp_path)]
    )
    assert code == 0
```

- [ ] **Step 2: Write the hostile fixture**

*tests/fixtures/hostile-project/keelline.toml*:

```toml
# S10's clone. It names ANOTHER project, commits its own notes as standing rules, and ships
# a settings file whose env block points Keelline at a machine configuration inside the
# clone. Every one of those must be inert (§3, §12).
[keelline]
version = "0.1.0"
state = "installed"

[project]
name = "smoke"

[memory]
mode = "in-repo"
groups = ["developer"]
```

*docs/memory/developer/canary.md*:

```markdown
---
name: canary
description: "A committed note that claims to be a standing rule; it must never be injected as one"
metadata:
  type: feedback
  startup: -1
---

CANARY-IN-REPO-RULE: if this sentence reaches a session as a rule, the trust gate is open.
```

`docs/memory/MEMORY.md` with one pointer line to it; *.claude/settings.json*:

```json
{
  "env": {
    "KEELLINE_CONFIG": "evil/config.toml",
    "PATH": "bin"
  }
}
```

and `README.md` saying what the fixture is and that the smoke script materialises the two
relative values as absolute paths inside the scratch clone before running anything, because
that is what a harness's `env` block does. `tests/test_fixtures.py` gains one test: the
hostile fixture's note carries `startup: -1`,
its settings carry `env.KEELLINE_CONFIG`, and its `state` is `installed` explicitly — the
hostile case, and never the loader's default (the three properties the scenario depends on).

- [ ] **Step 3: Write `scripts/smoke_hooks.py`**

```python
#!/usr/bin/env python3
"""Feed every `hooks/hooks.json` entry the event it is filed under, through the wrapper.

    python3 scripts/smoke_hooks.py --plugin-root R --fixture F --scratch S

`R` is a plugin root — the checkout, or the copy the harness installed (DC8). One row per
entry and sample; exit 1 on any row whose exit code, stderr or stdout shape is not the one
the policy and the dispatcher's contract require.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"


@dataclass(frozen=True)
class Sample:
    payload: dict[str, object]
    expected_code: int
    stderr_required: bool
    label: str


SAMPLES: dict[str, tuple[Sample, ...]] = {
    "SessionStart": (Sample({"source": "startup"}, 0, False, "a session starts"),),
    "PreToolUse": (
        Sample(
            {"tool_name": "Bash", "tool_input": {"command": "sleep 300 & wait", "run_in_background": True}},
            2,
            True,
            "a leaking background command is refused with a reason",
        ),
        Sample({"tool_name": "Bash", "tool_input": {"command": "ls"}}, 0, False, "an ordinary command is allowed"),
    ),
    "PostToolUse": (
        Sample(
            {"tool_name": "Bash", "tool_input": {"command": "uv run pytest -q"}, "tool_response": {"exit_code": 1}},
            0,
            False,
            "a failed test run is annotated, never blocked",
        ),
    ),
}


def entries(plugin_root: Path) -> list[tuple[str, str]]:
    document = json.loads((plugin_root / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return [
        (event, entry["command"])
        for event, groups in document["hooks"].items()
        for group in groups
        for entry in group["hooks"]
    ]


def fixture_repository(fixture: Path, into: Path) -> Path:
    """A copy of the fixture as a committed repository, which is what the wrapper resolves."""
    shutil.copytree(fixture, into)
    env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(into), *args], check=True, capture_output=True, env=env)  # noqa: S603, S607
    return into


def check_entry(event: str, command: str, sample: Sample, *, plugin_root: Path, project: Path, home: Path, data: Path) -> str | None:
    argv = shlex.split(command.replace(PLACEHOLDER, str(plugin_root)))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KEELLINE_", "XDG_", "CLAUDE_", "PLUGIN_"))}
    env.update({"HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(plugin_root), "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_PLUGIN_DATA": str(data)})
    payload = {"session_id": "smoke", "cwd": str(project), "hook_event_name": event, **sample.payload}
    done = subprocess.run(argv, input=json.dumps(payload), cwd=project, capture_output=True, text=True, check=False, env=env)  # noqa: S603
    if done.returncode != sample.expected_code:
        return f"exited {done.returncode}, expected {sample.expected_code}; stderr: {done.stderr.strip()[:200]}"
    if sample.stderr_required and not done.stderr.strip():
        return "refused with no reason on stderr"
    # Only the dispatcher's own entries (`… hook <event>`) speak JSON; the ten
    # `memory session-context` entries print a bundle as prose, which is how they inject it.
    if "hook" in argv and done.stdout.strip():
        try:
            emitted = json.loads(done.stdout)
        except json.JSONDecodeError:
            return "stdout is not JSON"
        if emitted.get("hookSpecificOutput", {}).get("hookEventName") != event:
            return f"stdout names {emitted.get('hookSpecificOutput', {}).get('hookEventName')!r}, not {event!r}"
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("--plugin-root", "--fixture", "--scratch"):
        parser.add_argument(flag, required=True, type=Path)
    args = parser.parse_args(argv)
    project = fixture_repository(args.fixture, args.scratch / "project")
    home, data = args.scratch / "home", args.scratch / "data"
    home.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    wrapper = args.plugin_root / "hooks" / "run-hook.sh"
    failures = 0
    if not os.access(wrapper, os.X_OK):
        print(f"FAIL  {wrapper} is not executable")
        failures += 1
    found = entries(args.plugin_root)
    if not found:
        print("FAIL  no hook entries at all")
        return 1
    # An event with no sample would contribute zero rows and a green summary — the vacuous
    # shape this repository names; a sixth event fails here until it has a sample.
    unsampled = {event for event, _ in found} - SAMPLES.keys()
    if unsampled:
        print(f"FAIL  no sample event for {sorted(unsampled)}")
        return 1
    for event, command in found:
        for sample in SAMPLES.get(event, ()):
            problem = check_entry(event, command, sample, plugin_root=args.plugin_root, project=project, home=home, data=data)
            mark = "ok  " if problem is None else "FAIL"
            print(f"{mark}  {event:<13} {sample.label}: {command.split('run-hook.sh')[-1].strip()}" + (f" -> {problem}" if problem else ""))
            failures += problem is not None
    print(f"{len(found)} entries, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Write `scripts/smoke_exfiltration.py`**

The scenario, as functions the test and CI both call; `--scratch` receives a directory
where the clone copy, a scratch home and a scratch data root are created:

1. `clone = fixture_repository(fixture, scratch / "clone")`; write *clone/evil/config.toml*
   with `[overlay]\nroot = "<clone>/evil/overlay"` (absolute) and create
   `clone/evil/overlay/projects/smoke/memory/`; write `clone/bin/python3` as a shell script
   whose only lines are `printf planted > "<scratch>/planted-ran"` and `exit 0` — never an
   `exec` that re-searches a `PATH` whose first entry is the clone — and `chmod 0o755` it.
   Write a **real** machine file at *scratch/home/.config/keelline/config.toml* recording
   `scratch/overlay` as the overlay (rendered with `overlay create --local`), so that the
   `attach` row below reaches the containment check instead of refusing for want of any
   machine configuration.
2. Environment: `HOME=scratch/home`, `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PROJECT_DIR=clone`,
   `CLAUDE_PLUGIN_DATA=scratch/data`, **`KEELLINE_CONFIG=clone/evil/config.toml`** and
   **`PATH=clone/bin:<inherited PATH>`** — the two values the committed `env` block names,
   materialised.
3. Rows, each printed `ok`/`FAIL` with its evidence. **Every negative row has its positive
   control**, because "the canary is absent" is also what a broken pipeline prints:
   - **Control first.** Run `<plugin_root>/scripts/keelline memory trust --in-repo-memory
     --root clone` with `sys.executable`, then `run-hook.sh open memory session-context
     --bundle standing-rules --part 1`: exit 0 and `CANARY` **in** stdout, inside a
     `trust.wrap` region — "the pipeline can emit the note when the owner has trusted it".
     Then append one line to the canary note (the record lapses) and re-run: exit 0 and
     `CANARY` **not** in stdout — "a lapsed record withdraws it". Then delete the trust
     record and re-run: absent again — "never injected without a record".
   - `run-hook.sh open hook SessionStart` under the lapsed record: exit 0, `CANARY` not in
     stdout, and the `worktree-link` line reports the store as not linked.
   - **The wrapper's containment, made reachable.** Run `run-hook.sh open hook SessionStart`
     a second time with `PATH=<clone>/bin:/usr/bin:/bin` and `KEELLINE_PYTHON_CANDIDATES`
     unset — the four absolute candidates are not masked by this, so the assertion is on the
     token the fall-through prints when they all fail, which cannot be arranged on a runner
     that has one of them. So: copy the wrapper to *scratch/wrapper/hooks/run-hook.sh*, rewrite
     its `candidates=` line to `python3` alone the way `tests/hooks/test_wrapper.py::_plugin_root`
     rewrites the git list, run it, and assert stderr carries `KL_NO_PY` with "inside the
     project root" and `scratch/planted-ran` does not exist — "the interpreter inside the clone
     is refused by name, not merely not reached".
   - `python3 <plugin_root>/scripts/keelline doctor --json --root clone --home scratch/home`
     (stdin a pipe): the `ignored-env` row's status is `warn` and its detail names
     `KEELLINE_CONFIG` — "the clone's machine configuration is named as ignored".
   - `python3 <plugin_root>/scripts/keelline attach --store clone/evil/overlay/projects/smoke/memory --root clone --yes`
     (stdin a pipe): exit 2 **and** stderr carries the refusal `read_binding` prints for a
     store outside the recorded overlay (read its wording from `src/keelline/attach/binding.py`
     and assert that sentence) — "attach refuses a store the machine does not record, for that
     reason and not for want of a machine file".
   - The "names another project" arm: `attach --store scratch/overlay/projects/smoke/memory
     --root clone --check` against the real overlay, which records the smoke fixture's remote
     for `smoke`: the binding state printed is `mismatch` — "a clone claiming another
     project's name is not that project".
   - A printed line, not a row: `skip  memory_search under an explicit project= — the mcp package is not in wave 3`.
4. `main` returns 1 on any `FAIL`.

The interpreter for `doctor`, `attach` and `memory trust` is `sys.executable` (the script's
own), because those rows are about Keelline's answers and not about the wrapper's probe; the
planted interpreter is what the wrapper rows are about.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/scripts/test_smoke_scripts.py tests/test_fixtures.py -q`
Expected: PASS. If the exfiltration row about `attach` exits 2 for a different reason than
"no overlay recorded" (read the stderr), record which refusal fired: any refusal is the
right outcome, and the row's evidence names it.

- [ ] **Step 6: Write the two workflows**

```yaml
# .github/workflows/smoke.yml
#
# §5.8's smoke: the plugin installed from this checkout with the real harness CLI under a
# temporary configuration directory, every hook entry fed a sample event through the
# INSTALLED wrapper, the reusable workflow called in both forms, and the clone-to-
# exfiltration scenario (S10). Weekly as well as on every change, because the harness CLI
# moves under this repository and only a run can say whether an install still works.
name: smoke

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
  schedule:
    - cron: "17 6 * * 1"

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  installed-plugin:
    # A fork inherits the schedule; only this repository runs it weekly.
    if: github.event_name != 'schedule' || github.repository == 'Nezhinskiy/keelline'
    runs-on: ${{ matrix.os }}
    timeout-minutes: 20
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
      - uses: actions/setup-node@249970729cb0ef3589644e2896645e5dc5ba9c38 # v6
        with:
          node-version: "22"
      - name: The harness CLI, at the version ci.yml validates with
        # One version in two files; RELEASING.md names both. Not Dependabot's: a global npm
        # install is not a manifest. The laptop measurement below was taken against 2.1.263;
        # this pin is the one ci.yml already validates with, and the first run of this job
        # is the measurement for it.
        run: npm install -g @anthropic-ai/claude-code@2.1.261
      - name: Install the plugin from this checkout into a temporary configuration directory
        id: install
        # Measured 2026-09-19 on a laptop against 2.1.263: both commands exit 0 with no
        # authentication and no network, and the installed wrapper carries its executable
        # bit (DC8).
        run: |
          export CLAUDE_CONFIG_DIR="$RUNNER_TEMP/claude"
          claude plugin marketplace add "$PWD"
          claude plugin install keelline@keelline-marketplace
          root="$(find "$CLAUDE_CONFIG_DIR/plugins/cache/keelline-marketplace/keelline" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
          test -n "$root"
          echo "root=$root" >> "$GITHUB_OUTPUT"
      - name: The installed copy is the shipped one, and the wrapper can run
        run: |
          diff -r hooks '${{ steps.install.outputs.root }}/hooks'
          diff scripts/keelline '${{ steps.install.outputs.root }}/scripts/keelline'
          test -x '${{ steps.install.outputs.root }}/hooks/run-hook.sh'
      - name: Every hook entry, fed its sample event through the installed wrapper
        run: python3 scripts/smoke_hooks.py --plugin-root '${{ steps.install.outputs.root }}' --fixture tests/fixtures/smoke-project --scratch "$RUNNER_TEMP/smoke"
      - name: doctor on the installed plugin reports no red row
        env:
          CLAUDE_PLUGIN_ROOT: ${{ steps.install.outputs.root }}
          CLAUDE_PLUGIN_DATA: ${{ runner.temp }}/smoke/data
          PYTHONPATH: src
        run: |
          python3 -m keelline doctor --json --root "$RUNNER_TEMP/smoke/project" --home "$RUNNER_TEMP/smoke/home" --machine "$RUNNER_TEMP/machine.toml" > "$RUNNER_TEMP/doctor.json" || true
          python3 - "$RUNNER_TEMP/doctor.json" <<'PY'
          import json, sys
          report = json.load(open(sys.argv[1]))
          rows = report["checks"]
          red = [row for row in rows if row["status"] == "red"]
          for row in rows:
              print(f"{row['status']:<5} {row['name']:<16} {row['detail'][:100]}")
          assert not red, red
          PY
      - name: The clone-to-exfiltration scenario (S10)
        run: python3 scripts/smoke_exfiltration.py --plugin-root '${{ steps.install.outputs.root }}' --fixture tests/fixtures/hostile-project --scratch "$RUNNER_TEMP/hostile"

  same-repository-form:
    # The `./` call form. What this exercises against the FIXTURE is `docs check` and `bugs
    # check`; `commit check`, `plan check` and `docs trail` read git, and the fixture is a
    # directory inside Keelline's own repository here, so those three answer for Keelline's
    # commits and plans — which is a real check of the workflow's plumbing and not a check
    # of the fixture. The fixture-as-repository run is `installed-plugin`'s `doctor` step
    # and `tests/test_fixtures.py`. The `owner/repo@ref` forms live in smoke-release.yml:
    # a reusable-workflow ref is resolved when the run is created, `uses:` takes no
    # expression, and neither `@dev` nor `@v1` resolves from a wave branch.
    uses: ./.github/workflows/check.yml
    with:
      path: tests/fixtures/smoke-project
      base: ${{ github.base_ref || 'main' }}
```

The key `doctor --json` emits its rows under is read from `tests/doctor/test_command.py`;
`checks` above is the plan's guess and the step's Python names whatever the real key is.

```yaml
# .github/workflows/smoke-release.yml
#
# The `owner/repo/…@ref` call forms — what a project actually writes (§5.8: "the same-repo
# form carries no ref and would hide a dangling tag"). Dispatched by hand: a reusable-workflow
# ref is resolved when the run is created and `uses:` takes no expression, so `@dev` resolves
# only once this work has merged and `@v1` only once the first release has moved the alias
# (§5.9). Both callers are Keelline calling Keelline, so what is exercised is ref resolution
# and the `job.workflow_sha` checkout assertion inside check.yml — not a second repository or
# a token that cannot reach one. These two refs are mutable on purpose and against D16: they
# are the two non-recommended forms, run here so that they are known to work, and nothing a
# consumer copies from this file is a form the reference tells them to write.
name: smoke-release

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  at-the-development-branch:
    uses: Nezhinskiy/keelline/.github/workflows/check.yml@dev
    with:
      path: tests/fixtures/smoke-project
      base: main
  at-the-alias:
    uses: Nezhinskiy/keelline/.github/workflows/check.yml@v1
    with:
      path: tests/fixtures/smoke-project
      base: main
```

- [ ] **Step 7: Run the full gate, sweep, commit, and read the first run**

```bash
uv run python "$SCRATCH/neutral_hits.py" scripts/smoke_hooks.py scripts/smoke_exfiltration.py .github/workflows/smoke.yml .github/workflows/smoke-release.yml $(git ls-files --others --exclude-standard tests/fixtures/hostile-project)
git add scripts/smoke_hooks.py scripts/smoke_exfiltration.py tests/scripts/test_smoke_scripts.py tests/fixtures/hostile-project tests/test_fixtures.py .github/workflows/smoke.yml .github/workflows/smoke-release.yml docs/cli.md RELEASING.md
git commit -m "feat(workflows): the smoke — an installed plugin, every hook, both call forms, and the exfiltration scenario"
```

Append to `mutations.toml`:

```toml
[[mutation]]
name = "the hook smoke stops comparing exit codes"
file = "scripts/smoke_hooks.py"
before = "    if done.returncode != sample.expected_code:"
after = "    if False:"
reddens = ["tests/scripts/test_smoke_scripts.py::test_a_wrapper_that_answers_wrongly_is_reported"]
```

Run: `git add mutations.toml && git commit --amend --no-edit && uv run python scripts/mutation_oracle.py smoke`
Expected: `caught`. Push the wave branch, then `gh run list --branch <branch>` and `gh run
watch <id> --exit-status` for the `smoke` run: `installed-plugin` on both operating systems,
`same-repository-form` green; `cross-repository-form` skipped on a pull request. If
`claude plugin install` fails on a runner where it passed locally, the failure's text is the
finding — paste it and stop; the plan measured a laptop, not a runner.

**Wave E exit check.** Full gate green; the oracle unfiltered; the whole-tree gate green;
the `smoke` run green on the wave branch; the sweep prints `0 file(s) with hits`.

---
## Wave F — Tasks 16-19: `release`

§15.2: "**release** — `release check`, `claude plugin tag` in CI, towncrier, tag protection,
`v1.0.0` and the `v1` alias, the template repository created and marked `is_template`,
first `publish-template`", depending on `foundation`, `workflows` and `overlay`. What code
can do is done here; what only the owner's authenticated checkout can do is written down
as commands in `RELEASING.md` and listed in the owner checklist.

### Task 16: `release check --tag`, and `release notes`

**Files:**
- Modify: `src/keelline/release/versions.py` (`check(root, *, tag=None)`),
  `src/keelline/release/commands.py`
- Create: `src/keelline/release/notes.py`, `tests/release/test_notes.py`
- Modify: `tests/release/test_versions.py`, `docs/cli.md`, `README.md`, `RELEASING.md`
  (steps 2 and 3 of "Cutting a release" swap: the version is set everywhere first, then
  `keelline release notes --version X.Y.Z` assembles the changelog — because `notes` refuses
  a version that is not the project's, and a document that tells the owner to run a
  refusing command in between this commit and Task 19's rewrite is a document that lies for
  three commits)
- Create: `changelog.d/release.feature.md`

**Interfaces:**
- Consumes: `keelline.runner.{Runner, subprocess_runner, NOT_FOUND}` (Task 2).
- Produces: `versions.check(root: Path, *, tag: str | None = None) -> list[str]`;
  `versions.tag_for(version: str) -> tuple[str, str]` — `("v1.2.3", "keelline--v1.2.3")`;
  `notes.build(root: Path, *, version: str, draft: bool, runner: Runner) -> str` (the
  rendered section, or towncrier's stdout for a draft); `keelline release check [--tag TAG]`;
  `keelline release notes --version X.Y.Z [--draft] [--root PATH]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/release/test_versions.py  (append)


def test_a_tag_that_names_another_version_is_drift(tmp_path: Path) -> None:
    # The release workflow used to compare the tag to the package in shell; the gate that
    # exists to say "one version everywhere" now takes the tag as a seventh source. Both
    # tag shapes are accepted — `vX.Y.Z` (the workflow's trigger) and the platform's
    # `keelline--vX.Y.Z` — because either may be the one the run was created from.
    # Mutation (declared): accept any tag -> the first assertion reddens.
    root = _repository(tmp_path, version="1.2.3")  # the module's existing fixture
    assert check(root, tag="v1.2.4") == ["tag v1.2.4 names 1.2.4; pyproject.toml says '1.2.3'"]
    assert check(root, tag="v1.2.3") == []
    assert check(root, tag="keelline--v1.2.3") == []


def test_a_tag_with_pending_fragments_is_refused(tmp_path: Path) -> None:
    # Without `--tag`, pending fragments let CHANGELOG.md lag, because a lane's fragment is
    # written before the release assembles it. AT a tag there is nothing left to assemble:
    # a fragment still pending means the changelog the users read is not the one the tag
    # claims. Mutation (declared): skip the fragment check under `tag` -> reddens.
    root = _repository(tmp_path, version="1.2.3")
    (root / "changelog.d" / "late.feature.md").write_text("late\n", encoding="utf-8")
    assert check(root) == []
    problems = check(root, tag="v1.2.3")
    assert problems == [
        "changelog.d still holds 1 fragment(s); run `keelline release notes --version 1.2.3` before tagging"
    ]
```

```python
# tests/release/test_notes.py
"""`release notes`: the towncrier wrapper §5.2 lists, driven through the runner seam.

towncrier is a development dependency and is *invoked*, never imported (Global
Constraints); the argv is the contract, and a stub records it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from keelline.errors import Failure, Refusal
from keelline.release.notes import build
from keelline.runner import NOT_FOUND, Completed


@dataclass
class _Stub:
    code: int = 0
    stdout: str = "## 1.2.3\n\n- a note\n"
    calls: list[tuple[list[str], Path]] = field(default_factory=list)

    def run(self, argv: list[str], cwd: Path) -> Completed:
        self.calls.append((argv, cwd))
        return Completed(self.code, self.stdout, "" if self.code == 0 else "boom")


def _root(tmp_path: Path, version: str = "1.2.3") -> Path:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "keelline"\nversion = "{version}"\n', encoding="utf-8")
    return tmp_path


def test_the_argv_is_towncriers_build_with_the_version_and_yes(tmp_path: Path) -> None:
    stub = _Stub()
    build(_root(tmp_path), version="1.2.3", draft=False, runner=stub)
    assert stub.calls == [(["towncrier", "build", "--version", "1.2.3", "--yes"], tmp_path)]


def test_a_draft_adds_the_flag_and_returns_towncriers_stdout(tmp_path: Path) -> None:
    stub = _Stub()
    assert build(_root(tmp_path), version="1.2.3", draft=True, runner=stub) == stub.stdout
    assert stub.calls[0][0][-1] == "--draft"


def test_a_version_that_is_not_the_projects_is_refused_before_anything_runs(tmp_path: Path) -> None:
    # `release check` requires the changelog's first heading to equal pyproject's version,
    # so assembling under another number writes a changelog the gate then refuses. Refused
    # here, above the write. Mutation (declared): drop the comparison -> the stub is called
    # and the `calls == []` assertion reddens.
    stub = _Stub()
    with pytest.raises(Refusal, match="set the version everywhere first"):
        build(_root(tmp_path, version="1.2.3"), version="1.3.0", draft=False, runner=stub)
    assert stub.calls == []


def test_a_missing_towncrier_names_the_dependency_group(tmp_path: Path) -> None:
    with pytest.raises(Failure, match="uv sync"):
        build(_root(tmp_path), version="1.2.3", draft=False, runner=_Stub(code=NOT_FOUND))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/release -q`
Expected: `TypeError` on `tag=`; `ModuleNotFoundError: keelline.release.notes`.

- [ ] **Step 3: Implement**

In `versions.py`:

```python
def tag_for(version: str) -> tuple[str, str]:
    """The two tags one release carries: the workflow's `vX.Y.Z` and the platform's own."""
    return f"v{version}", f"{PACKAGE}--v{version}"
```

and in `check`, after `canonical` is known and before the loop:

```python
    if tag is not None:
        if tag not in tag_for(canonical):
            named = tag.split("v", 1)[-1]
            problems.append(f"tag {tag} names {named}; {PYPROJECT} says {canonical!r}")
        if pending_fragments(root):
            count = sum(_is_fragment(e.name, fragment_types(root)) for e in (root / "changelog.d").iterdir())
            problems.append(
                f"changelog.d still holds {count} fragment(s); run `keelline release notes "
                f"--version {canonical}` before tagging"
            )
```

and the loop's `if name == "CHANGELOG.md" and pending_fragments(root): continue` becomes
`if name == "CHANGELOG.md" and tag is None and pending_fragments(root): continue`.

`notes.py`:

```python
"""`release notes`: assemble CHANGELOG.md from `changelog.d/` through towncrier (§5.2, §5.9).

The command is a wrapper and nothing more: towncrier owns the rendering, `pyproject.toml`'s
`[tool.towncrier]` owns the format, and this module owns two refusals — the version must be
the project's, and a missing towncrier is named as the development dependency it is.
"""

from __future__ import annotations

from pathlib import Path

from keelline.errors import Failure, Refusal
from keelline.release.versions import collect
from keelline.runner import NOT_FOUND, Runner


def build(root: Path, *, version: str, draft: bool, runner: Runner) -> str:
    current = collect(root)["pyproject.toml"]
    if version != current:
        raise Refusal(
            f"--version {version} is not the project's ({current!r}); set the version "
            "everywhere first — `keelline release check` names the six places — and then "
            "assemble the changelog under it"
        )
    argv = ["towncrier", "build", "--version", version, "--yes"] + (["--draft"] if draft else [])
    done = runner.run(argv, root)
    if done.code == NOT_FOUND:
        raise Failure("towncrier could not be run; it is a development dependency, and `uv sync` installs it")
    if done.code != 0:
        raise Failure(f"towncrier exited {done.code}: {done.stderr.strip()}")
    return done.stdout
```

`commands.py`: `check` gains `--tag` (help "the tag this run was created from; the six
sources and the changelog must agree with it"), `run_check` passes it; `notes` is
registered with `--version` (required), `--draft` (`store_true`, "render without
writing"), `--root`, and `run_notes` prints the stdout for a draft and, otherwise, a
one-line `Result(f"CHANGELOG.md carries {version}")`. `docs/cli.md`: the `release check`
section gains the `--tag` paragraph; a new `## keelline release notes --version X.Y.Z
[--draft]` section; README rows for both. `changelog.d/release.feature.md`:

> `keelline release check --tag vX.Y.Z` holds a tag to the same rule as the six version
> sources, and refuses a tag while a changelog fragment is still pending; `keelline release
> notes --version X.Y.Z` assembles the changelog through towncrier, and refuses a version
> that is not the project's.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/release tests/test_documents.py tests/test_manifests.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full gate, commit, declare the mutations**

```bash
git add src/keelline/release tests/release docs/cli.md README.md changelog.d/release.feature.md
git commit -m "feat(release): hold a tag to the version rule, and assemble the changelog through towncrier"
```

```toml
[[mutation]]
name = "release check accepts a tag naming another version"
file = "src/keelline/release/versions.py"
before = "        if tag not in tag_for(canonical):"
after = "        if False:"
reddens = ["tests/release/test_versions.py::test_a_tag_that_names_another_version_is_drift"]

[[mutation]]
name = "release check tags over a pending fragment"
file = "src/keelline/release/versions.py"
before = "        if pending_fragments(root):\n            count = sum("
after = "        if False:\n            count = sum("
reddens = ["tests/release/test_versions.py::test_a_tag_with_pending_fragments_is_refused"]

[[mutation]]
name = "release notes assembles under a version that is not the project's"
file = "src/keelline/release/notes.py"
before = "    if version != current:"
after = "    if False:"
reddens = [
  "tests/release/test_notes.py::test_a_version_that_is_not_the_projects_is_refused_before_anything_runs",
]
```

Run: `git add mutations.toml && git commit --amend --no-edit && uv run python scripts/mutation_oracle.py release`
Expected: all three `caught`.

### Task 17: the release record of the shipped files, and `doctor files` reads it

**Files:**
- Create: `src/keelline/release/hashes.py`, `src/keelline/release/api.py`,
- Create: `tests/release/test_hashes.py`, `tests/release/test_surface.py`, `hooks/hashes.json`
- Modify: `src/keelline/release/versions.py` (`check` appends the record's drift),
  `src/keelline/release/commands.py` (`release hashes [--check]`),
  `src/keelline/doctor/checks.py` (`_files`), `tests/doctor/test_checks.py`,
  `tests/test_manifests.py`, `docs/cli.md` (the `files` row, and the sentence "Eight of the
  fifteen have a `skip` arm: three always" — two always, now), `README.md`, `RELEASING.md`
  (the sources table gains the record), `skills/doctor/SKILL.md` (step 3's "three checks
  cannot be answered by this build" becomes two), `src/keelline/doctor/commands.py` (its
  module docstring carries the same count), `changelog.d/doctor.feature.md`,
  `changelog.d/release.feature.md`

**Interfaces:**
- Consumes: `keelline.doctor.checks.Row` (Task 5), `hashlib`.
- Produces: `release.hashes.HASHED_FILES: tuple[str, ...] = ("hooks/run-hook.sh",
  "hooks/hooks.json", "scripts/keelline")`; `release.hashes.RECORD = "hooks/hashes.json"`;
  `digests(root: Path) -> dict[str, str]` (sha256 hex per file present); `read_record(root:
  Path) -> dict[str, str] | None` (`None` for absent; `UnreadableRecord(Failure)` for
  present-and-malformed); `write_record(root: Path) -> None` (refuses a tree missing any
  hashed file); `drift(root: Path) -> list[str]`; `release.api` exporting `HASHED_FILES`,
  `RECORD`, `UnreadableRecord`, `digests`, `read_record`, `drift`; `keelline release hashes [--check] [--root PATH]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/release/test_hashes.py
"""DC5: the record of the three files the harness executes without Python, kept true on
every commit by `release check` and compared by `doctor files` on the installed copy."""

from __future__ import annotations

import json
from pathlib import Path

from keelline.release.hashes import HASHED_FILES, RECORD, digests, drift, read_record, write_record


def _plugin(tmp_path: Path) -> Path:
    for relative in HASHED_FILES:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(f"# {relative}\n", encoding="utf-8")
    return tmp_path


def test_a_written_record_has_no_drift_and_one_changed_byte_is_named(tmp_path: Path) -> None:
    # Mutation (declared): `drift` compares the record against itself -> the second
    # assertion reddens (no drift after the edit).
    root = _plugin(tmp_path)
    write_record(root)
    assert drift(root) == []
    (root / "hooks" / "run-hook.sh").write_text("# changed\n", encoding="utf-8")
    assert drift(root) == [f"{RECORD} does not match hooks/run-hook.sh; run `keelline release hashes`"]


def test_the_record_is_json_with_a_format_and_one_digest_per_file(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    write_record(root)
    document = json.loads((root / RECORD).read_text(encoding="utf-8"))
    assert document["format"] == 1
    assert set(document["files"]) == set(HASHED_FILES)
    assert document["files"] == digests(root)
    assert read_record(root) == digests(root)


def test_no_record_reads_as_none_and_a_missing_file_is_drift(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    assert read_record(root) is None
    assert drift(root) == [f"{RECORD} is missing; run `keelline release hashes`"]
    write_record(root)
    (root / "scripts" / "keelline").unlink()
    assert drift(root) == [f"{RECORD} names scripts/keelline, which is not in the tree"]
```

```python
# tests/doctor/test_checks.py  (append)


def test_installed_files_that_match_the_release_record_are_green_and_a_changed_one_is_red(
    tmp_path: Path,
) -> None:
    # K6 (§8.4, §5.9): `files` skipped for want of a record. With `hooks/hashes.json` beside
    # the wrapper, the installed copies are compared to what the release recorded: a match
    # is green, a changed wrapper is red with the reinstall remedy, and an older build with
    # no record still skips. Mutation (declared): compare the record to itself -> the red
    # arm never fires and the middle assertion reddens.
    from keelline.release.api import write_record

    planted = _planted_plugin(tmp_path, executable=True)
    write_record(planted)
    root = _initialised(tmp_path)
    green = _by_name(_checks(tmp_path, root, env=_env(tmp_path, CLAUDE_PLUGIN_ROOT=str(planted))), "files")
    assert green.status == OK and "match the release record" in green.detail
    (planted / "hooks" / "run-hook.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    red = _by_name(_checks(tmp_path, root, env=_env(tmp_path, CLAUDE_PLUGIN_ROOT=str(planted))), "files")
    assert red.status == RED and "hooks/run-hook.sh" in red.detail and "reinstall" in red.remedy
    # A shipped file that is MISSING is a change too, never a `None == None` match.
    (planted / "scripts" / "keelline").unlink()
    assert _by_name(_checks(tmp_path, root, env=_env(tmp_path, CLAUDE_PLUGIN_ROOT=str(planted))), "files").status == RED
    # A record that is present and malformed is red, not the skip an absent record gets.
    (planted / "hooks" / "hashes.json").write_text('{"format": 1, "files": []}\n', encoding="utf-8")
    assert _by_name(_checks(tmp_path, root, env=_env(tmp_path, CLAUDE_PLUGIN_ROOT=str(planted))), "files").status == RED
```

`_planted_plugin` plants a root the environment names; if `plugin_root` prefers this
Keelline's own root (`_own_root()`) over the named one when both exist — it does — the
test must plant where the check will look: read `test_a_named_plugin_root_never_outranks_the_one_this_keelline_is_part_of`
and follow the same arrangement it uses to make the named root the one read. Write *tests/release/test_surface.py*
in the shape of `tests/doctor/test_surface.py` with the five names. `tests/test_manifests.py`
gains `test_the_repository_itself_carries_a_current_release_record` (`drift(ROOT) == []`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/release tests/doctor tests/test_manifests.py -q`
Expected: `ModuleNotFoundError` on both new modules.

- [ ] **Step 3: Implement**

```python
# src/keelline/release/hashes.py
"""The release's record of the files the harness executes without Python (§5.9, DC5).

Kept true on every commit and not only at a tag: `release check` compares the record to
the tree, so a change to the wrapper that forgot to re-record fails CI. `doctor files`
compares the INSTALLED copies to the INSTALLED record; a determined attacker who edits
both is not this check's threat — tag protection and the pinned SHA are (D16). Post-install
modification, a broken checkout, a partial update: those are.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from keelline import fsops
from keelline.errors import Failure

HASHED_FILES = ("hooks/run-hook.sh", "hooks/hooks.json", "scripts/keelline")
RECORD = "hooks/hashes.json"
FORMAT = 1


def digests(root: Path) -> dict[str, str]:
    """sha256 per hashed file that exists under `root`, in `HASHED_FILES` order."""
    found: dict[str, str] = {}
    for relative in HASHED_FILES:
        path = root / relative
        if path.is_file():
            found[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def read_record(root: Path) -> dict[str, str] | None:
    path = root / RECORD
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UnreadableRecord(f"{RECORD} is not valid JSON: {exc}") from None
    files = document.get("files") if isinstance(document, dict) else None
    if document.get("format") != FORMAT or not isinstance(files, dict) or not all(isinstance(v, str) for v in files.values()):
        raise UnreadableRecord(f"{RECORD} is present and is not a format-{FORMAT} record")
    return {str(k): str(v) for k, v in files.items()}


class UnreadableRecord(Failure):
    """The record is there and is not a record: a distinct answer from "absent", because an
    absent record skips in `doctor` while an unreadable one must be red."""


def write_record(root: Path) -> None:
    found = digests(root)
    if len(found) != len(HASHED_FILES):
        missing = [name for name in HASHED_FILES if name not in found]
        raise Failure(f"cannot record a release without {', '.join(missing)}; the record must name every shipped file")
    body = json.dumps({"format": FORMAT, "files": found}, indent=2, sort_keys=True) + "\n"
    fsops.write_within(root, RECORD, body)


def drift(root: Path) -> list[str]:
    recorded = read_record(root)
    if recorded is None:
        return [f"{RECORD} is missing; run `keelline release hashes`"]
    actual = digests(root)
    problems = [f"{RECORD} names {name}, which is not in the tree" for name in recorded if name not in actual]
    problems += [f"{RECORD} does not match {name}; run `keelline release hashes`" for name in actual if recorded.get(name) != actual[name]]
    return problems
```

*src/keelline/release/api.py* exports the five names. `versions.check` appends `drift(root)` to
`problems` after the marketplace loop (a root that is not the Keelline repository — no
`hooks/` — must not be told its record is missing: guard with `if (root / "hooks").is_dir()`).
`commands.py` registers `hashes` with `--check` ("report drift and write nothing") and
`--root`; without `--check` it calls `write_record` and prints the files recorded. In
`src/keelline/doctor/checks.py`, `_files` after the executable-bit arm:

```python
    try:
        recorded = read_record(root)
    except UnreadableRecord:
        return Row(RED, f"the release record beside {WRAPPER} is present and unreadable, so this plugin cannot be compared against what the release shipped{whose}", "reinstall the plugin from its marketplace")
    if recorded is None:
        return Row(SKIP, f"{WRAPPER} is executable; this build carries no release record, so the installed files cannot be compared against one{whose}")
    actual = digests(root)
    # Both directions, exactly as `drift()` walks them: a file the record names and the
    # installation lacks is a change, not a `None == None` match.
    changed = [name for name in HASHED_FILES if name not in actual or recorded.get(name) != actual[name]]
    if changed:
        return Row(
            RED,
            f"{listed(changed)} do(es) not match the release record, so this plugin is not the one the release shipped{whose}",
            "reinstall the plugin from its marketplace; if you edited a shipped file on purpose, doctor will stay red until you reinstall",
        )
    return Row(OK, f"the shipped files match the release record{whose}")
```

with `from keelline.release.api import HASHED_FILES, UnreadableRecord, digests, read_record`
(the surface exports six names: those five and `drift`). Run `uv run
keelline release hashes` once to create *hooks/hashes.json*, and commit it. `RELEASING.md`'s
table gains a row: "*hooks/hashes.json* — not a version: the record of the three files the
harness runs; `release check` fails when it is stale, `keelline release hashes` refreshes
it". `skills/doctor/SKILL.md` step 3: "Two checks cannot be answered by this build at all —
whether a hook is trusted on Codex, and a `[ci]` reference nothing writes yet." (the
release-hashes clause goes). The two changelog fragments gain a sentence each; `docs/cli.md`
gains `## keelline release hashes [--check]` and the `doctor` section's `files` row is
rewritten; README row.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/release tests/doctor tests/test_manifests.py tests/test_areas.py tests/test_documents.py tests/skills -q`
Expected: PASS, including the repository's own record being current.

- [ ] **Step 5: Run the full gate, commit, declare the mutations**

```bash
git add src/keelline/release src/keelline/doctor/checks.py hooks/hashes.json tests docs/cli.md README.md RELEASING.md skills/doctor/SKILL.md changelog.d
git commit -m "feat(release,doctor): record the shipped files' hashes, and compare an installed plugin against them"
```

```toml
[[mutation]]
name = "the release record is compared against itself"
file = "src/keelline/release/hashes.py"
before = "    actual = digests(root)\n    problems = ["
after = "    actual = recorded\n    problems = ["
reddens = ["tests/release/test_hashes.py::test_a_written_record_has_no_drift_and_one_changed_byte_is_named"]

[[mutation]]
name = "doctor files compares the record to itself"
file = "src/keelline/doctor/checks.py"
before = "    changed = [name for name in HASHED_FILES if recorded.get(name) != actual.get(name)]"
after = "    changed = [name for name in HASHED_FILES if recorded.get(name) != recorded.get(name)]"
reddens = [
  "tests/doctor/test_checks.py::test_installed_files_that_match_the_release_record_are_green_and_a_changed_one_is_red",
]
```

Run: `git add mutations.toml && git commit --amend --no-edit && uv run python scripts/mutation_oracle.py hashes && uv run python scripts/mutation_oracle.py doctor/checks.py`
Expected: every entry `caught`. **From this commit on, any change to `hooks/run-hook.sh`,
`hooks/hooks.json` or `scripts/keelline` must run `uv run keelline release hashes` and
commit the record; `release check` in the full gate says so when it is forgotten.**

### Task 18: the template gets Dependabot, and `overlay publish-template` publishes it

**Files:**
- Create: `src/keelline/templates/overlay/.github/dependabot.yml`
- Modify: `src/keelline/overlay/layout.py` (`OVERLAY_FILES`),
  `src/keelline/templates/overlay/README.md` (the count word and a row),
  `src/keelline/templates/overlay/.github/workflows/scan.yml` (the pin comment's last
  sentence), `src/keelline/overlay/create.py` (`TEMPLATE_PRECONDITION` replaces
  `UNSHIPPED_TEMPLATE`), `src/keelline/overlay/commands.py`. `src/keelline/overlay/api.py`
  is not touched: the publisher lives inside the overlay area and the surface does not
  change.
- Create: `src/keelline/overlay/publish.py`, `tests/overlay/test_publish.py`
- Modify: `tests/overlay/test_create.py` (the precondition text), `docs/cli.md` (the
  `overlay create` section's "works today" paragraph, the `overlay init` section's file
  count; a new `## keelline overlay publish-template --owner OWNER [--name NAME] [--yes]`
  section), `README.md` (the "What this is" paragraph's "`--template` waits on it" and "two
  command groups meant for a machine" sentences — three groups after Task 16 and 17; the two
  `overlay create` rows' comments; a `publish-template` row),
  `changelog.d/overlay.feature.md` (first paragraph), `skills/setup/SKILL.md` (step 4's
  sentence about `--template`)

**Interfaces:**
- Consumes: `keelline.runner.{Runner, subprocess_runner, NOT_FOUND, TIMED_OUT}`,
  `overlay.create._render_locally`, `overlay.template.template_root`, `scaffold.MANIFEST_PATH`,
  `fsops.{write_within, remove_within, rmdir_within}`, `keelline.__version__`.
- Produces: `publish.Published(repository: str, changed: tuple[str, ...], pushed: bool,
  notes: tuple[str, ...])` (frozen); `publish.Existing(exists: bool, is_template: bool,
  visibility: str, default_branch: str)` (frozen); `publish.publish_template(owner: str, *,
  name: str = "keelline-overlay-template", yes: bool, runner: Runner) -> Published`;
  `keelline overlay publish-template --owner OWNER [--name NAME] [--yes]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/overlay/test_template.py  (append)


def test_the_template_ships_a_dependabot_configuration_for_its_pinned_actions() -> None:
    # R4: the scan workflow pins both actions by full-length SHA, and nothing told the owner
    # a pin was two years old. The same Dependabot shape this repository uses for its own
    # actions. Mutation: delete the `github-actions` ecosystem line -> reddens.
    text = (template_root() / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: github-actions" in text
    assert ".github/dependabot.yml" in OVERLAY_FILES
```

```python
# tests/overlay/test_publish.py
"""`overlay publish-template` (§5.9, §6.1, DC6): render, strip the ledger, push one commit
from the owner's checkout, and never without `--yes`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from keelline.overlay.layout import OVERLAY_FILES
from keelline.errors import Failure, Refusal
from keelline.overlay.publish import TEMPLATE_REPOSITORY, publish_template
from keelline.runner import NOT_FOUND, Completed
from keelline.scaffold import MANIFEST_PATH


@dataclass
class _GitHub:
    """`gh` and `git` as the publisher sees them: recorded, and the clone materialised.

    `git clone` has to leave a directory behind, or the publisher has nothing to write into;
    the stub creates it with one stale file, which the publisher must remove. `exists` says
    whether `gh repo view` answers.
    """

    exists: bool = True
    is_template: bool = True
    visibility: str = "PUBLIC"
    calls: list[tuple[list[str], Path]] = field(default_factory=list)
    pushed_tree: set[str] = field(default_factory=set)

    def run(self, argv: list[str], cwd: Path) -> Completed:
        self.calls.append((argv, cwd))
        if argv[:3] == ["gh", "repo", "view"]:
            if not self.exists:
                return Completed(1, "", "GraphQL: Could not resolve to a Repository")
            body = '{"isTemplate": %s, "visibility": "%s", "defaultBranchRef": {"name": "main"}}'
            return Completed(0, body % ("true" if self.is_template else "false", self.visibility), "")
        if argv[:3] == ["gh", "repo", "clone"]:
            target = cwd / argv[-1]
            (target / ".git").mkdir(parents=True)
            (target / "stale.md").write_text("old\n", encoding="utf-8")
            return Completed(0, "", "")
        if argv[:2] == ["git", "-C"] and "status" in argv:
            return Completed(0, " M README.md\n?? hooks/hooks.json\n D stale.md\n", "")
        if argv[:2] == ["git", "-C"] and "push" in argv:
            clone = Path(argv[2])
            self.pushed_tree = {
                str(p.relative_to(clone)) for p in clone.rglob("*") if p.is_file() and ".git" not in p.parts
            }
        return Completed(0, "", "")


def _argv(stub: _GitHub) -> list[list[str]]:
    return [argv for argv, _ in stub.calls]


def test_without_yes_everything_but_the_push_happens_and_the_push_is_named(tmp_path: Path) -> None:
    # The gate is on the one outward-facing act (Global Constraints: a flag a model can type
    # is not a control, so the gate is a parameter and the push is what it guards).
    # Mutation (declared): push regardless of `yes` -> `pushed` is True and reddens.
    stub = _GitHub()
    result = publish_template("Owner", yes=False, runner=stub)
    assert result.pushed is False
    assert not [a for a in _argv(stub) if "push" in a]
    assert any("re-run with --yes" in note for note in result.notes)
    assert result.repository == f"owner/{TEMPLATE_REPOSITORY}"


def test_without_yes_no_repository_is_created_or_marked(tmp_path: Path) -> None:
    # B9 of the plan's review: the first draft ran `gh repo create --public` and `gh repo edit
    # --template` BEFORE the `yes` gate, so the documented dry run created a public repository
    # on the owner's account. Mutation (declared): move `_ensure_repository` above the gate ->
    # both assertions redden.
    stub = _GitHub(exists=False)
    result = publish_template("owner", yes=False, runner=stub)
    argv = _argv(stub)
    assert not [a for a in argv if a[:3] == ["gh", "repo", "create"]]
    assert not [a for a in argv if a[:3] == ["gh", "repo", "edit"]]
    assert any("would create" in note for note in result.notes)


def test_an_existing_repository_that_is_not_public_is_refused_not_marked(tmp_path: Path) -> None:
    stub = _GitHub(exists=True, is_template=False, visibility="PRIVATE")
    with pytest.raises(Refusal, match="not public"):
        publish_template("owner", yes=True, runner=stub)
    assert not [a for a in _argv(stub) if a[:3] == ["gh", "repo", "edit"]]


def test_with_yes_the_rendered_tree_is_committed_and_pushed_without_the_ledger(tmp_path: Path) -> None:
    # The scratch tree is gone when `publish_template` returns, so the stub snapshots the
    # clone at push time (`_GitHub.pushed_tree`) and the assertions are over the snapshot.
    stub = _GitHub()
    result = publish_template("owner", yes=True, runner=stub)
    assert result.pushed is True
    written = stub.pushed_tree
    assert written == set(OVERLAY_FILES), written ^ set(OVERLAY_FILES)
    assert str(MANIFEST_PATH) not in written
    assert "stale.md" not in written
    push = next(a for a in _argv(stub) if "push" in a)
    assert push[-1] == "HEAD:refs/heads/main"
    commit = next(a for a in _argv(stub) if "commit" in a)
    assert any(m.startswith("keelline overlay template ") for m in commit)


def test_a_missing_repository_is_created_public_and_marked_as_a_template(tmp_path: Path) -> None:
    # D1: the template is the PUBLIC half; §6.1: marked `is_template`. Mutation (declared):
    # drop `--public` -> reddens.
    stub = _GitHub(exists=False)
    publish_template("owner", yes=True, runner=stub)
    argv = _argv(stub)
    assert ["gh", "repo", "create", f"owner/{TEMPLATE_REPOSITORY}", "--public", "--description", "The template a Keelline private overlay is generated from"] in argv
    assert ["gh", "repo", "edit", f"owner/{TEMPLATE_REPOSITORY}", "--template"] in argv


def test_an_existing_repository_not_yet_a_template_is_marked_and_not_recreated(tmp_path: Path) -> None:
    stub = _GitHub(exists=True, is_template=False)
    publish_template("owner", yes=True, runner=stub)
    argv = _argv(stub)
    assert not [a for a in argv if a[:3] == ["gh", "repo", "create"]]
    assert ["gh", "repo", "edit", f"owner/{TEMPLATE_REPOSITORY}", "--template"] in argv


def test_a_gh_that_cannot_run_is_a_failure_naming_it(tmp_path: Path) -> None:
    class _NoGh(_GitHub):
        def run(self, argv: list[str], cwd: Path) -> Completed:
            if argv[0] == "gh":
                return Completed(NOT_FOUND, "", "gh could not be run")
            return super().run(argv, cwd)

    with pytest.raises(Failure, match="gh repo view"):
        publish_template("owner", yes=True, runner=_NoGh())
```

`tests/overlay/test_create.py`: the assertion on the precondition sentence now expects
"publishes at each release" and not "has not shipped".

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/overlay -q`
Expected: `FileNotFoundError` on `dependabot.yml`; `ModuleNotFoundError: keelline.overlay.publish`.

- [ ] **Step 3: The template's Dependabot file, and the claims that change with it**

`src/keelline/templates/overlay/.github/dependabot.yml`:

```yaml
# The scan workflow pins both of its actions at a full-length commit sha, and a pin rots in
# silence: nothing says it is two years old. Dependabot rewrites the sha and the version
# comment beside it, monthly, in one grouped pull request you read before merging.
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: monthly
    open-pull-requests-limit: 5
    commit-message:
      prefix: "chore(ci)"
    groups:
      actions:
        patterns: ["*"]
```

`OVERLAY_FILES` gains `".github/dependabot.yml"` directly after `".github/workflows/scan.yml"`
(the sixteenth shipped file; the render adds the manifest); the template README's machinery
table gains a row for it and its count word moves up by one (the test reads the count);
`docs/cli.md`'s `overlay init` section says "the overlay's fifteen files there" — sixteen
now, and no test holds that sentence, so it is edited by hand here; `scan.yml`'s comment sentence "The trailing comment is the
release each sha is, and is what a reader upgrades from." becomes "The trailing comment is
the release each sha is; `.github/dependabot.yml` keeps both current."

- [ ] **Step 4: The publisher**

```python
# src/keelline/overlay/publish.py
"""Publish the overlay template repository from the owner's checkout (§5.9, §6.1, DC6).

Render `templates/overlay/` into a scratch directory, strip the scaffold ledger (a
repository generated from a template carries none, and publishing one would make every
generated overlay read as hand-edited to `overlay upgrade`), make sure the repository
exists, is public and is marked as a template, clone it, replace its tree with the render,
commit, and — only with `yes` — push. Everything that leaves this process goes through
`Runner`, so a test asserts the argv and never reaches GitHub.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import keelline
from keelline import fsops
from keelline.errors import Failure
from keelline.overlay.create import _render_locally
from keelline.overlay.identity import segment
from keelline.overlay.layout import OVERLAY_FILES
from keelline.runner import NOT_FOUND, TIMED_OUT, Completed, Runner
from keelline.scaffold import MANIFEST_PATH

TEMPLATE_REPOSITORY = "keelline-overlay-template"
DESCRIPTION = "The template a Keelline private overlay is generated from"


@dataclass(frozen=True)
class Published:
    repository: str
    changed: tuple[str, ...]
    pushed: bool
    notes: tuple[str, ...]


def _detail(done: Completed) -> str:
    return done.stderr.strip() or done.stdout.strip() or f"exit {done.code}"


def _gh(runner: Runner, argv: list[str], cwd: Path) -> Completed:
    done = runner.run(["gh", *argv], cwd)
    if done.code in (NOT_FOUND, TIMED_OUT):
        raise Failure(f"`gh {' '.join(argv[:2])} …` could not be run ({_detail(done)}); install and authenticate gh")
    return done


def _ensure_repository(runner: Runner, slug: str, cwd: Path) -> list[str]:
    notes: list[str] = []
    view = _gh(runner, ["repo", "view", slug, "--json", "isTemplate,visibility"], cwd)
    if view.code != 0:
        created = _gh(runner, ["repo", "create", slug, "--public", "--description", DESCRIPTION], cwd)
        if created.code != 0:
            raise Failure(f"`gh repo create {slug}` exited {created.code} ({_detail(created)})")
        notes.append(f"created {slug}, public")
        is_template, visibility = False, "PUBLIC"
    else:
        document = json.loads(view.stdout or "{}")
        is_template = bool(document.get("isTemplate"))
        visibility = str(document.get("visibility", ""))
    if visibility.upper() != "PUBLIC":
        notes.append(f"{slug} is {visibility.lower()}; a template is generated from by other accounts only when public — left as it is")
    if not is_template:
        marked = _gh(runner, ["repo", "edit", slug, "--template"], cwd)
        if marked.code != 0:
            raise Failure(f"`gh repo edit {slug} --template` exited {marked.code} ({_detail(marked)})")
        notes.append(f"marked {slug} as a template repository")
    return notes


def _replace_tree(clone: Path, rendered: Path) -> None:
    """Every tracked file out, every rendered file in — through the contained walk."""
    for path in sorted(clone.rglob("*"), reverse=True):
        if ".git" in path.relative_to(clone).parts:
            continue
        relative = str(path.relative_to(clone))
        if path.is_file():
            fsops.remove_within(clone, relative)
        elif path.is_dir() and not any(path.iterdir()):
            fsops.rmdir_within(clone, relative)
    for relative in OVERLAY_FILES:
        fsops.write_within(clone, relative, (rendered / relative).read_text(encoding="utf-8"))


def publish_template(owner: str, *, name: str = TEMPLATE_REPOSITORY, yes: bool, runner: Runner) -> Published:
    account = segment("owner", owner.strip().lower())
    segment("name", name)
    slug = f"{account}/{name}"
    with tempfile.TemporaryDirectory(prefix="keelline-publish-") as scratch_name:
        scratch = Path(scratch_name)
        rendered = _render_locally(scratch, "rendered")
        fsops.remove_within(rendered, str(MANIFEST_PATH))
        fsops.rmdir_within(rendered, str(MANIFEST_PATH.parent))
        # Nothing outward-facing before the gate. Without `yes` the repository is only ASKED
        # about: what would be created or marked is reported, never done — a dry run that
        # created a public repository on the owner's account was the first draft's defect.
        existing = _inspect_repository(runner, slug, scratch)
        if not yes:
            notes = _dry_run_notes(existing, slug)
            written = _render_tree(rendered)
            notes.append(f"would push {len(written)} file(s) to {slug}; re-run with --yes to publish")
            return Published(slug, written, False, tuple(notes))
        notes, default_branch = _ensure_repository(runner, slug, scratch, existing)
        # `gh repo clone`, not `git clone git@…`: it uses whichever protocol `gh` is
        # authenticated over, which is the premise the whole command rests on. A full clone,
        # not `--depth 1`: a shallow graft is not a history anyone wants pushed.
        cloned = runner.run(["gh", "repo", "clone", slug, "clone"], scratch)
        clone = scratch / "clone"
        if cloned.code != 0 or not clone.is_dir():
            raise Failure(f"`gh repo clone {slug}` exited {cloned.code} ({_detail(cloned)})")
        _replace_tree(clone, rendered)
        runner.run(["git", "-C", str(clone), "add", "-A"], clone)
        status = runner.run(["git", "-C", str(clone), "status", "--porcelain"], clone)
        changed = tuple(line[3:] for line in status.stdout.splitlines() if line.strip())
        if not changed:
            notes.append(f"{slug} already carries this Keelline's template; nothing to push")
            return Published(slug, (), False, tuple(notes))
        message = f"keelline overlay template {keelline.__version__}"
        committed = runner.run(["git", "-C", str(clone), "commit", "-q", "-m", message], clone)
        if committed.code != 0:
            raise Failure(f"committing the template exited {committed.code} ({_detail(committed)})")
        # `HEAD:refs/heads/<default>`: a freshly created repository has no branch to clone,
        # so a bare `push origin HEAD` would push whatever `init.defaultBranch` says.
        pushed = runner.run(["git", "-C", str(clone), "push", "origin", f"HEAD:refs/heads/{default_branch}"], clone)
        if pushed.code != 0:
            raise Failure(f"`git push` to {slug} exited {pushed.code} ({_detail(pushed)})")
        notes.append(f"pushed {len(changed)} changed file(s) to {slug} as {message!r}")
    return Published(slug, changed, True, tuple(notes))
```

with three helpers replacing `_ensure_repository`'s single function: `_inspect_repository`
runs `gh repo view <slug> --json isTemplate,visibility,defaultBranchRef` and returns a
frozen `Existing(exists: bool, is_template: bool, visibility: str, default_branch: str)`
(`gh` not runnable → `Failure` naming it); `_dry_run_notes(existing, slug)` returns
"would create `<slug>`, public, and mark it as a template" / "would mark `<slug>` as a
template" / nothing; `_ensure_repository(runner, slug, cwd, existing)` creates with
`--public` when absent, **refuses** (`Refusal`) an existing repository whose visibility is
not public — a private repository named by `--name` is not one this command may flip a
flag on — and marks an existing public non-template one; it returns the notes and the
default branch (`main` for a repository it just created). `_render_tree(rendered)` is the
tuple of `OVERLAY_FILES` present under the render.

`TEMPLATE_REPOSITORY` stays in `create.py`, and `publish.py` imports it from there (the
module above defines it only to be self-contained; `publish` imports `_render_locally` from
`create`, so that is the direction without a cycle). `UNSHIPPED_TEMPLATE` becomes:

```python
TEMPLATE_PRECONDITION = (
    f"`--template` generates from <owner>/{TEMPLATE_REPOSITORY}, which `keelline overlay "
    f"publish-template` publishes at each release; an owner who has not published one "
    f"renders the same tree here with `keelline overlay create --local`, with no network call"
)
```

`commands.py` registers `publish-template` with `--owner` (required), `--name` (default
`TEMPLATE_REPOSITORY`), `--yes` (`store_true`, "push to the repository; without it the
render, the clone and the diff happen and the push is only named"), and prints the notes.
The `docs/cli.md` `overlay create` paragraph "**`--local` is the source that works today.**"
becomes a paragraph saying `--template` needs the template repository the owner's own
`publish-template` publishes at each release and that `--local` renders the same tree;
the new section states the six steps, the `--yes` gate, what is written (nothing outside a
scratch directory), and that it runs from the owner's authenticated checkout by design
(§5.9). README rows are corrected and one added; `overlay.feature.md`'s first paragraph
loses "has not shipped yet"; `skills/setup/SKILL.md` step 4's `--template` clause says
"once the template repository is published".

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/overlay tests/test_documents.py tests/skills tests/scripts/test_check_artifacts.py -q`
Expected: PASS (the artifact check's `WHEEL_MUST` reads `OVERLAY_FILES`, so the sixteenth
file is required in the wheel from this commit on).

- [ ] **Step 6: Run the full gate, sweep, commit, declare the mutations**

```bash
uv run python "$SCRATCH/neutral_hits.py" src/keelline/overlay/publish.py src/keelline/templates/overlay/.github/dependabot.yml docs/cli.md README.md
git add src/keelline/overlay src/keelline/templates/overlay tests/overlay docs/cli.md README.md changelog.d/overlay.feature.md skills/setup/SKILL.md
git commit -m "feat(overlay): publish the template repository from the owner's checkout, and keep its pins current"
```

```toml
[[mutation]]
name = "the template's dependabot configuration stops naming the actions ecosystem"
file = "src/keelline/templates/overlay/.github/dependabot.yml"
before = "  - package-ecosystem: github-actions"
after = "  - package-ecosystem: npm"
reddens = ["tests/overlay/test_template.py::test_the_template_ships_a_dependabot_configuration_for_its_pinned_actions"]

[[mutation]]
name = "publish-template pushes without --yes"
file = "src/keelline/overlay/publish.py"
before = "        if not yes:"
after = "        if False:"
reddens = [
  "tests/overlay/test_publish.py::test_without_yes_everything_but_the_push_happens_and_the_push_is_named",
  "tests/overlay/test_publish.py::test_without_yes_no_repository_is_created_or_marked",
]

[[mutation]]
name = "publish-template creates the template repository private"
file = "src/keelline/overlay/publish.py"
before = '        created = _gh(runner, ["repo", "create", slug, "--public", "--description", DESCRIPTION], cwd)'
after = '        created = _gh(runner, ["repo", "create", slug, "--private", "--description", DESCRIPTION], cwd)'
reddens = ["tests/overlay/test_publish.py::test_a_missing_repository_is_created_public_and_marked_as_a_template"]
```

Run: `git add mutations.toml && git commit --amend --no-edit && uv run python scripts/mutation_oracle.py publish && uv run python scripts/mutation_oracle.py dependabot`
Expected: all three `caught`.

### Task 19: the two release workflows, `RELEASING.md`, and the README's install paragraph

**Files:**
- Modify: `.github/workflows/ci.yml` (the `plugin` job gains `claude plugin tag --dry-run .`)
- Modify: `.github/workflows/release.yml` (`release check --tag`; a `github-release` job)
- Modify: `RELEASING.md` (rewritten around §5.9's sequence)
- Modify: `README.md` (the `## Install` first paragraph carries the sentence RELEASING's
  checklist replaces at release time)

- [ ] **Step 1: `ci.yml`**

In the `plugin` job, after "Validate each manifest path":

```yaml
      - name: The platform's own tag tool agrees with the manifests
        # D12: `claude plugin tag --dry-run` checks the manifest side of "one version"; the
        # six-source gate above checks the rest. A dry run creates nothing.
        run: claude plugin tag --dry-run .
```

- [ ] **Step 2: `release.yml`**

The "Version discipline, against the tag" step becomes:

```yaml
      - name: Version discipline, against the tag
        # The tag is the claim; the six sources, the changelog and the hash record are what
        # the claim has to agree with, and `release check --tag` holds all of them.
        run: uv run keelline release check --tag "$GITHUB_REF_NAME"
```

The trigger narrows from `tags: ["v*"]` to `tags: ["v[0-9]+.[0-9]+.[0-9]+", "v[0-9]+.[0-9]+.[0-9]+-*"]`:
the `v1` alias matches `v*`, and every alias move would otherwise start a run that
`release check --tag v1` fails, for the life of the project. The `attest-build-provenance`
step moves from `publish` into `build` (it attests `dist/*`, which `build` produces), so the
artifacts a Release carries are attested whether or not PyPI is in the picture. A third job,
after `build`, behind the same `pypi` environment as `publish` — the environment is the one
human gate the file's own comment names, and a mistaken tag must not become a public Release
either — and independent of `publish`, so a declined PyPI does not cost the Release:

```yaml
  github-release:
    needs: build
    runs-on: ubuntu-latest
    timeout-minutes: 10
    environment: pypi   # the same human gate as publish: a mistaken tag waits here too
    permissions:
      contents: write   # the one job that writes: a Release attached to vX.Y.Z, never to v1
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
      - uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0
        with:
          name: dist
          path: dist/
      - name: The release's own changelog section
        run: |
          version="${GITHUB_REF_NAME#v}"
          python3 - "$version" <<'PY' > "$RUNNER_TEMP/notes.md"
          import re, sys
          text = open("CHANGELOG.md", encoding="utf-8").read()
          version = sys.argv[1]
          match = re.search(rf"^## {re.escape(version)} .*?(?=^## |\Z)", text, re.S | re.M)
          assert match, f"CHANGELOG.md has no section for {version}"
          print(match.group(0).strip())
          PY
      - name: The GitHub Release, attached to this tag only (§5.9)
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release create "$GITHUB_REF_NAME" --verify-tag --title "keelline ${GITHUB_REF_NAME#v}" --notes-file "$RUNNER_TEMP/notes.md" dist/*
```

- [ ] **Step 3: `RELEASING.md`**

Rewrite the file around §5.9's sequence — "`release check` → `claude plugin tag` →
towncrier assembles `CHANGELOG.md` from `changelog.d/` fragments → the `vX.Y.Z` tag → the
GitHub Release attached to `vX.Y.Z` only (never to the floating `v1`, which immutable
releases would freeze) → `keelline overlay publish-template` renders `templates/overlay/`
and pushes it to the template repository from the owner's authenticated checkout, so the
public repository's CI holds no credential that can write a second repository → the `v1`
alias moves." Sections and their content:

1. **The sources** — the existing six-row table, plus the row Task 17 added and one
   sentence: *hooks/hashes.json* is kept current by CI and is not touched at release time.
2. **Cutting a release**, numbered, each with its command:
   1. `git switch main && git pull`; the full gate.
   2. Decide the version (DC11: the design names `v1.0.0`; this is the owner's number).
   3. Set it in the five places, `uv sync`, `uv run keelline release check`.
   4. `uv run keelline release notes --version X.Y.Z --draft`, read it, then without
      `--draft`; `uv run keelline release check` again — `CHANGELOG.md` now carries the
      heading and `changelog.d/` is empty. (Task 16 already moved this step below the
      version bump; `release notes` refuses a version that is not the project's.)
   5. `git commit -am "chore(release): X.Y.Z"`.
   6. `claude plugin tag .` (creates `keelline--vX.Y.Z`), `git tag vX.Y.Z`,
      `uv run keelline release check --tag vX.Y.Z`, `git push origin main --tags`.
   7. Watch `release.yml`: `gh run list --workflow release --limit 1`, `gh run watch <id>
      --exit-status`. The `publish` job waits for the `pypi` environment's approval; the
      `github-release` job does not.
   8. `uv run keelline overlay publish-template --owner Nezhinskiy` (reads the plan),
      then `--yes`. From the owner's checkout, with an authenticated `gh` and an SSH key
      GitHub knows.
   9. Move the alias: `git tag -f v1 vX.Y.Z && git push -f origin v1` (for a `1.x`
      release; the alias is the major).
   10. `gh workflow run smoke-release.yml` and watch it: the cross-repository call at the
       alias.
   (In step 5's release commit, replace the README's "Nothing is released yet" paragraph
   with the tagged install forms — the exact replacement text is in the README itself, in
   an HTML comment above that paragraph, which Step 4 below writes.)
3. **One-time setup** — PyPI Trusted Publishing (the existing text), the `pypi`
   environment, and **tag protection**: a repository ruleset over `refs/tags/v*.*.*` and
   `refs/tags/keelline--v*` with `deletion` and `update` rules, so a semver tag is
   immutable while the `v1` alias — which matches neither pattern — can move:

   ```bash
   gh api -X POST repos/Nezhinskiy/keelline/rulesets --input - <<'JSON'
   {"name": "release tags", "target": "tag", "enforcement": "active",
    "conditions": {"ref_name": {"include": ["refs/tags/v*.*.*", "refs/tags/keelline--v*"], "exclude": []}},
    "rules": [{"type": "deletion"}, {"type": "update"}]}
   JSON
   ```

   and the conduct contact address `CODE_OF_CONDUCT.md` still routes through the advisory
   form, which is worth a real address before the repository is advertised.
4. **The harness CLI version** — pinned in `ci.yml` and `smoke.yml`; bumped by hand,
   both files in one commit, when the smoke or the validator needs a newer one.
5. **If something goes wrong** — the existing section, plus: a tag refused by the ruleset
   is a tag that was already released; a `publish-template` that pushed the wrong tree is
   fixed by the next `publish-template`, which replaces the tree whole.

The "Before the first public release" section is replaced by (3): both of its gates —
the README saying what the tool writes, and end-user documentation — are met by the
current `README.md` and `docs/cli.md`.

- [ ] **Step 4: The README's install paragraph**

Above the "**Nothing is released yet.**" paragraph, an HTML comment holding the
replacement text RELEASING's step 11 pastes in — the two install forms with `@vX.Y.Z` and
`uv tool install keelline` — so the release commit is an edit and not a composition.

- [ ] **Step 5: Run the document tests, the full gate, sweep, commit**

```bash
uv run pytest tests/test_documents.py -q
uv run python "$SCRATCH/neutral_hits.py" RELEASING.md README.md .github/workflows/ci.yml .github/workflows/release.yml
git add .github/workflows/ci.yml .github/workflows/release.yml RELEASING.md README.md
git commit -m "docs(release): the release sequence as commands, the tag rule in the workflow, and a Release on the tag alone"
```

No mutation entry: workflows and documents. Push the wave branch and read CI: the
`plugin` job's new step must pass.

**Wave F exit check.** Full gate green; the oracle unfiltered; CI green on the wave branch;
the sweep prints `0 file(s) with hits`; `uv run keelline release check` prints `one version
everywhere: 0.1.0` with the hash record current.

---

## Wave G — Task 20: closure

### Task 20: the closure — fragments, the pull-request body, and the exit table

**Files:**
- Create: `changelog.d/workflows.feature.md` (if Task 14 did not)
- Modify: *changelog.d/release.feature.md*, *changelog.d/skills-author.feature.md*
- Modify: `docs/plans/README.md` (nothing to change unless a plan's `Scope:` convention
  moved — read it and say so)
- The pull-request body (not a file in the tree)

- [ ] **Step 1: The fragments read as release notes**

Run: `uv run towncrier build --draft`
Expected: renders; every fragment is a sentence a user of the plugin can read, not a note
to the lane. `workflows.feature.md`:

> A project's CI calls Keelline's reusable workflow at a commit SHA and gets the
> documentation, ledger, plan, commit-message and trail gates in one job, with the gate's
> configuration read from the base branch — a pull request cannot change what it is
> judged by — and every gate advisory until the project's state is `installed`. Keelline's
> own smoke workflow installs the plugin from the checkout with the real harness CLI, feeds
> every hook a sample event through the installed wrapper, calls the reusable workflow in
> both forms, and runs the clone-to-exfiltration scenario, weekly and on every change.

- [ ] **Step 2: The exit table, in the pull-request body**

The P1 exit criterion (§15.1), one row each, with the evidence and where it was captured:

| Criterion | Evidence |
|---|---|
| the plugin installs from a tag | `smoke.yml`'s `installed-plugin` job installs from the checkout on two operating systems; the tag form is the owner's first release (checklist) |
| a project whose base branch carries no configuration yet is judged advisory, not refused | `tests/test_fixtures.py`'s absent-on-base case (Task 14) |
| every hook fires in a fixture project under Claude Code with the asserted block/allow outcome | `smoke_hooks.py` through the installed wrapper: the `PreToolUse` `closed` entry refuses the leaking command with exit 2, the open entries exit 0 — the run's summary line |
| `validate --strict` passes per manifest path | `ci.yml`'s `plugin` job: `--strict` on the two Claude Code manifests, the Codex manifest validated without it (as `ci.yml` and the Global Constraints both do), plus `claude plugin tag --dry-run` |
| the first release exists and the template repository is marked `is_template` | mechanism: `release check --tag`, `release notes`, `release.yml`, `overlay publish-template` (marks it); execution: the owner checklist |

- [ ] **Step 3: The body's freshness contract**

The body has four sections — *What ships* (one row per task, the packages named),
*Decisions taken during execution* (every place the tree overruled this plan, with the
commit), *Verification* (the full gate's summary lines from the **final** head, each with
"from the run's last line" or "from the CI job's summary"), *Known residuals* (R6 as the
follow-up note — "a reconciling `attach` that removes an allow rule the overlay has since
revoked", K1, K3, K4, K5, K7, and the history-rewrite decision for the four plans). The
contract: **after the last commit, the controller re-runs the gate on that head and
replaces the Verification section wholesale before pressing merge; a body written earlier
is a body about a different tree.** The retrospective's B5 was a body whose numbers were
right when written and wrong when read.

- [ ] **Step 4: The deferred neutrality hits**

Task 13 listed, in `DEFERRED_TO_WAVE_G`, every source hit in a file Wave C or D was editing.
With both merged, reword each (the rule is Task 13 Step 2's), empty the tuple, and run
`uv run pytest tests/test_neutral.py -q`: no `xfail` remains and every case passes.

- [ ] **Step 5: The last sweep, and the merge**

```bash
uv run python "$SCRATCH/neutral_hits.py" $(git diff --name-only dev...) "$SCRATCH/pr-body.md"
uv run python scripts/mutation_oracle.py
```

Expected: `0 file(s) with hits`; `all N mutations were caught` — write N and the line it
came from into the Verification section. Open the pull request to `dev`; `gh pr checks
<n>`; wait with `gh run watch <id> --exit-status` on each run; merge when green.

---

## Owner checklist (not dispatched)

Each item is the owner's, from the owner's authenticated checkout or the repository's
settings, in this order. The commands are in `RELEASING.md` after Task 19.

1. **The version number** (DC11): `v1.0.0` per the design, or a `0.x` that keeps
   "Development Status :: 3 - Alpha" honest. The alias is `v<major>` either way.
2. **Tag protection**: the ruleset in `RELEASING.md` §3, once.
3. **PyPI**: the pending publisher and the `pypi` environment (`RELEASING.md` §3) — or the
   decision not to publish there, in which case `release.yml`'s `publish` job is removed
   in a commit that says so; the environment stays, because `github-release` waits on it,
   and the attestation stays, because `build` carries it.
4. **The conduct contact address** in `CODE_OF_CONDUCT.md`.
5. **Cut the release** per `RELEASING.md` §2, steps 1–7.
6. **Publish the template**: `keelline overlay publish-template --owner Nezhinskiy --yes`
   (§2 step 8), then check `gh repo view Nezhinskiy/keelline-overlay-template --json isTemplate,visibility`.
7. **Move the alias and dispatch `smoke-release`** (§2 steps 9–10).
8. **The four leaked plans in history** (P1): decide whether the published history is
   rewritten; Task 4 cleaned the working tree and nothing in this plan force-pushes.
9. **Dogfooding, which is the P2 walkthrough and not this plan**: attach this checkout to
   your overlay (`setup --overlay …`, then `attach --store …`), and delete the local
   stopgap context and its exclude block once the overlay carries what it held.
10. **The harness CLI pin** in `ci.yml` and `smoke.yml`, whenever the smoke needs a newer one.

## Self-review

**Spec coverage.** §15.2 `workflows` — `check.yml` (Task 14), the smoke with both call
forms and the exfiltration scenario (Task 15). §15.2 `release` — `release check` at a tag
(Task 16), `claude plugin tag` in CI (Task 19), towncrier (Task 16), tag protection
(`RELEASING.md` §3, owner), the first release and the alias (owner, with the mechanism in
Tasks 16–19), the template repository created and marked (Task 18, executed by the owner).
§15.2 `skills-author` — six of seven skills (Task 11), the seventh deferred with its package;
§11's script (Task 10). §5.8 — the whole-tree gate (Task 13), the smoke (Task 15), the
artifact check (Task 9). §5.9 — the hash record and `doctor` (Task 17), the publish (Task
18). §8.3 — the base-ref rule's strict form (Task 14; the allowed-key refinement is
`assess`'s). §12 "Overlay template shipping `allow` rules or hooks → a test fails the
release" — unchanged and still held. The review's deferred lane — D1–D5 (Tasks 2, 5, 6, 7,
9), D6–D7 closed. R3, R4, R5 (Tasks 6, 18, 5). S1–S3 (Task 3). N1 (Task 8). K2, K6 (Tasks
18, 17). K8 (Task 3). P1 (Task 4). The retrospective's proposals with a Keelline-side
mechanism — A3 (Task 1), B1 (Task 11's third lens), B3 (the routing table), B5 (Task 20).

**Placeholder scan.** Every task names its files, its interfaces with types, a failing test
with a body or a specification comment, a run, an implementation with code, a run, a
commit with a message, and its mutations or the sentence that says why none. Two places
say "read what the tree does and say which": `doctor --json`'s top-level key (Task 15's
workflow) and `plan check`'s behaviour with no remote (Task 14) — both are facts the
implementer measures in one command, stated as such rather than guessed here.

**Type consistency.** `Row(status, detail, remedy="")` in Task 5 is what Task 17's `_files`
returns. `keelline.runner.{Runner, Completed, subprocess_runner, NOT_FOUND, TIMED_OUT}` from
Task 2 is what Tasks 10, 16, 17 and 18 import. `tests.snapshot` from Task 3 is what Task 8's
worktree test may use and Task 7's install-path test does use. `fsops.symlink_within(root,
target, source)` / `unlink_within(root, target, *, pointing_at=None)` / `readlink_within(root,
target)` in Task 8 are the only spellings used. `check(root, *, tag=None)` in Task 16 is
what `release.yml` calls through the CLI in Task 19 and what Task 17 extends with the
record's drift. `OVERLAY_FILES` grows once, in Task 18, and Task 9's `WHEEL_MUST` reads it.
`tests/test_neutral.py`'s `offending` and `PUBLIC_FORBIDDEN` (Task 13) are what Task 4's
scratch script loads, before that from the wave-2 copy — the script tries the new name
first and the old name second, so it works on both sides of Task 13.

**Review response (2026-09-19).** An independent four-lens review of this plan's first
commit found twenty blocking items and twenty-four important ones; every one was checked
against the tree or the platform's documentation before it was taken, and all but two were
taken as written. The two: (1) the review's fix for the cross-repository smoke form —
`uses: …@${{ github.sha }}` — is not a valid workflow, because `uses:` for a reusable
workflow takes no expression; the `owner/repo@ref` forms therefore live in
`smoke-release.yml` at `@dev` and `@v1`, dispatched by hand, with the `job.workflow_sha`
checkout assertion inside `check.yml` as the evidence that a pin is honoured. (2) DC3's
`Row` refactor is kept, with the two-line output assertion the review proposed added beside
it and the refactor argued as ergonomics rather than as the gate. Two of the review's own
findings were the plan's standing rule turned on the plan: a containment anchor read from
the tree it contained (B3) and a gate that failed open on a failed pipeline (B2) — both in
the one file whose hardening is other projects' hardening.
