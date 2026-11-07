# Keelline Foundation Implementation Plan

> **Delivered — do not re-execute.** This plan ran, and the Keelline repository's own history
> is authoritative for what was built. The steps keep their `- [ ]` checkboxes as the record
> of what was planned; nothing here is a work item. Two kinds of block are governed
> differently, and the difference matters to a later lane reading this file:
>
> - **`**Interfaces:**` blocks are current.** They state the contracts (C1, C4, C5, C6) other
>   lanes build against, and they are kept in step with the shipped code, not with the code
>   blocks below them.
> - **Code blocks are as-planned, not as-shipped.** Several were hardened during execution
>   (the Premise lists them) and some diverge in ways the Premise did not list. Read them as
>   the design that was written, and read `~/Dev/keelline` for the code that runs.
>
> A lane that needs the built behaviour opens the repository. A lane that needs the contract
> reads the Interfaces block.

**Goal:** Create the Keelline repository as an installable Claude Code and Codex plugin and a stdlib-only Python package, with the four contracts every other lane builds on — configuration (C1), the hook dispatcher interface (C4), the CLI frame (C5) and version discipline (C6) — each proven by a test.

**Architecture:** One repository, `~/Dev/keelline`, is at once a plugin (manifests under `.claude-plugin/` and `.codex-plugin/`, a launcher under `scripts/`) and a package (`src/keelline/`, built by `uv_build`). Areas are subpackages that the CLI frame and the hook registry discover by name, so later lanes add `keelline/<area>/commands.py` and `keelline/<area>/hooks.py` without editing a shared registry. The runtime imports only the standard library, enforced by a test on every supported interpreter; Python 3.11 is the floor because the config loader uses `tomllib`, and the launcher refuses anything older with a reason.

**Order:** the P0 spikes plan has recorded its Findings (merged into this branch). This plan takes from them: **S1** — Codex's hook launch sets `PLUGIN_ROOT` and `PLUGIN_DATA` (Codex-only names) *and also* `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PLUGIN_DATA`, so the `CLAUDE_*` names alone identify nothing, and Codex's `SessionStart` stdin carries `model` and `permission_mode` while Claude Code's does not; **S2** — `${CLAUDE_PLUGIN_ROOT}` resolves to the marketplace's `installLocation` (the source directory for a directory-sourced marketplace), not to the `plugins/cache` copy, and a directory-sourced install preserves file modes; **S4** — only the `.claude-plugin/plugin.json` path validates skills and agents (the directory and marketplace targets report none of the planted defects), the Codex manifest is validated only by its own path, and its `skills` value resolves relative to `.codex-plugin/`; **S7** — the cap is exactly 10,000 characters per hook entry; **S8** — a hook file whose executable bit is lost degrades open on the platform side, which the installer and `doctor` must check at `installLocation` (a `hooks-core` concern, recorded in the Premise). Codex-side verification (S1's tool names, S2's Codex arm, S3) was deferred by the owner to the end of the programme on 2026-09-05; a follow-up spike round has since measured two of those three. **S1**: Codex's `PreToolUse` reports `Bash` uniformly for a shell command, a shell-routed file read and a shell-routed write attempt, and reports the literal string `apply_patch` — not `Write`, not `Edit` — for a patch-based edit; a separate probe then showed that a matcher of exactly `Edit|Write` still fires on that edit, so the aliases govern matching while the payload carries only the canonical name. The same round also measured `additionalContext` on Codex's `PreToolUse` specifically: the probe's canary reached the model in full and unabbreviated on all three firings. **S2**: no `${CLAUDE_PLUGIN_ROOT}` substitution in skill content under Codex. Those results — the Codex tool names, the `PreToolUse` `additionalContext` canary, and S2's Codex arm — are now recorded in §10. **S3** (whether Codex's `/import` carries Claude memory notes) is still open: the interactive `/import` has since been run, but it read the owner's default Claude Code configuration directory rather than the seeded scratch one, so the fixture's canary was never in scope and the question needs a redesigned fixture rather than another keystroke. The eight Codex clauses §10 marks unmeasured — the hook-trust hash, `prompt`/`agent` handlers, `additionalContext` on the four events other than `PreToolUse`, async hooks unable to block, an exit 2 with empty stderr, `userConfig`, the ask-user fallback, `UserPromptExpansion` — stay unmeasured; §10's other Codex rows (the plugin-root variables reaching hooks, the absent `CLAUDE_PROJECT_DIR`, and the read/search routing) are Confirmed and must not be re-measured. So this plan still ships and validates the Codex manifest without depending on a Codex measurement of its own dispatcher.

**Tech Stack:** Python ≥ 3.11 (stdlib only at runtime), `uv` 0.11 with the `uv_build` backend, pytest, ruff, mypy, towncrier 26.9 (dev-time only), `claude` CLI for `plugin validate`, GitHub Actions.

**Spec:** the agent-harness extraction design, at the source's spec path — a private repository; it cannot be opened from this one — §5 (public repository), §7.1 (configuration schema), §15.2 (the `foundation` row), §15.4 (contracts C1, C4, C5, C6 and disjoint ownership).

**Scope:** package `foundation` (§15.2); produces C1, C4 (interface), C5 and C6; consumes the S1, S4 and S7 answers of the spike record. A change belongs to this plan iff it lands in the Keelline repository under a path this plan's Files blocks name, or copies the two P0 documents from this repository into `docs/plans/` there. Handlers, hook entries, the wrapper, templates, skills and every preset section other than the three named below belong to other lanes.

**Premise (recorded deviations from the frozen design, for the wave-1 merger):**

- §5.1 draws `presets/` at the plugin root. The preset lives inside the package as `src/keelline/presets/recommended.toml`, because a plugin-root file is invisible to a wheel installed with `uv tool install` and a second copy would drift. Foundation writes only its `[budgets]`, `[native_caps]` and `[defaults.*]` sections; the `setup` lane owns every other section (§15.4).
- §15.2 assigns `keelline hook <event>` to `hooks-core`. Foundation ships the smallest command that can exercise the C4 interface — stdin in, registry, dispatcher, exit code out — and `hooks-core` owns the wrapper, the plugin's hooks file, the per-harness emitter and the diagnostics sink implementation; the seams for those are part of C4 here.
- §15.4 gives `README.md` to `readme-methodology`, which runs in parallel in wave 2. Foundation writes a two-line install stub and nothing else there, so the two lanes never edit the same paragraph.
- §9.5 phrases budgets as `min(configured, preset, ceiling)`. The native caps §7.1 lists (index lines and bytes, hook output characters) are in units no budget shares, so they are exposed as `config.native_caps` for the consumers that bound those things, and a budget's effective value is `min(configured, preset)`; a project can lower a budget and never raise it, which is what D7 asks.
- §5.9 names the release tag `vX.Y.Z`. `claude plugin tag` creates `<name>--v<version>` (measured 2026-09-05: `probe--v0.0.1`), so the release lane keeps both tags and this plan does not run the tag tool in CI.
- §12 says marketplace names carry the owner suffix; that row concerns overlays (§6.1). The public marketplace is `keelline-marketplace`.
- S8 measured that a hook wrapper whose executable bit is lost never runs, and Claude Code lets the tool call through as a non-blocking hook error; no wrapper code can catch that. The `hooks-core` lane owns the remedy — an install-time and `doctor` check of the executable bit at the marketplace's `installLocation`, or declaring the entry as `sh "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.sh"` so the bit stops mattering — and this plan's launcher test only proves the bit survives a directory-sourced install (S2).
- An area must be a regular package: measured 2026-09-06, `pkgutil.iter_modules` does not yield a
  directory without `__init__.py`, so an area shipped as an implicit namespace package is
  invisible to both `discover_registrars()` and the hook registry. Every `keelline/<area>/`
  carries an `__init__.py`, and later lanes must too.
- The Codex manifest's `skills` path is an open item, not a solved one. `claude plugin validate`
  refuses `../skills/` as a path traversal attempt and reports `./skills/` as not found, so no
  value reaches the root-level `skills/` from inside `.codex-plugin/`; foundation ships no
  `skills` key. S4's own recommended amendment to §5.8 — correct the convention so a valid tree
  does not fail validation on its own — is still owed, and the skills lanes settle it once Codex
  has actually been measured.
- The executed branch hardened several of the code blocks below during review, rather than
  shipping them verbatim: the containment guard now compares the parsed path so `"./"` cannot
  return the project root, the CLI frame maps a broken area module to exit 2 instead of a
  traceback, and the hook dispatcher closed three fail-open paths on the decision that blocks a
  tool call — argv rather than stdin naming the event, `==` rather than `is` against the policy
  enum, and a typed `Decision` for the field that refuses. Each of those changes shipped with
  the mutation that reddens it, **in the Keelline repository's own history** — no Step 5
  matrix below covers them, because every matrix here was written against the code beside it.
  The Keelline repository's history is authoritative for what was built; the blocks below
  record what was planned.
- That list is **not exhaustive**, and a review found four more divergences worth naming so a
  reader does not take a code block for a specification. `Handler` gained `once_key` and
  `dispatch` lost its `sink` default, both of which the Task 7 **Interfaces** line records
  and its code block predates. `src/keelline/config/paths.py`'s module docstring, which here claims to
  cover "every path a repository-controlled file can name (§7.4)", ships saying the opposite
  and naming the four fields the guard does **not** reach (`ledger.code_roots`,
  `artifacts.local`, `memory.groups`, `memory.index_extra`) — design §7.4 has since been
  widened to those fields, and closing the gap belongs to the lanes that first read them.
  And two tests differ: the import-boundary walk parses each file once through a walrus
  rather than twice, and the hook command's broken-config fixture is valid everywhere the
  loader checks before `[ci]`, because the shape written here is rejected earlier and never
  reaches the branch under test.
- **Open against C5, for the first lane that returns findings.** `Result.exit_code` exists
  and `cli._emit` returns it, but no command sets it — every failure raises `Failure` or
  `Refusal`, which is what puts `"error"` into the `--json` object. A `Result` carrying
  `exit_code=1` therefore prints a success-shaped object on a failing exit code, which
  breaks the C5 contract for the first lane (`ledger`, `docs-tooling`, `assess`) that
  reports findings without raising. That lane either derives `"error": "findings"` from a
  non-zero `exit_code` or drops the field; it must not inherit the current shape silently.

## Global Constraints

- Repository `~/Dev/keelline`, default branch `main`, license MIT (the owner may change it before the first release; `pyproject.toml` and both manifests must then change together).
- Runtime imports only the standard library on every interpreter from 3.11 to 3.13; `requires-python = ">=3.11"`; dev dependencies are allowed in the `dev` group only.
- No top-level `bin/`; the launcher lives under `scripts/`. Skills reference the CLI by name, never through the launcher path (§5.1).
- Plugin name `keelline` (an immutable slug once published); marketplace name `keelline-marketplace`; package and CLI name `keelline`.
- One version string, checked by `keelline release check`: `pyproject.toml`, `src/keelline/__init__.py`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, and the top `CHANGELOG.md` heading unless `changelog.d/` holds pending fragments. The marketplace entry carries no `version`, and `release check` refuses one.
- CLI exit codes: 0 success, 1 findings or failure, 2 refusal or internal error; `--json` accepted anywhere on the line, on every command, for success and failure alike. `argparse` usage errors also exit 2, which is why hooks are wrapped (§5.3) rather than called bare.
- Every assertion ships with the mutation expected to redden it, or one sentence saying why none exists.
- Every code block below is ruff-clean at 100 columns and mypy-strict-clean; a task's tests, `ruff check`, `ruff format --check` and `mypy` all pass before its commit.
- Commit messages use the types `feat|fix|docs|test|refactor|style|chore|harden|guard`, carry no AI attribution, and are English, as is every file.
- Writes go under `~/Dev/keelline`, under Task 11's temporary `CLAUDE_CONFIG_DIR` (deleted), and — after explicit consent in chat — to GitHub, where Task 11 creates the public repository and pushes `main`, including the copied spike record.

---

### Task 1: Repository skeleton, package, and `--version`

**Files:**
- Create: `pyproject.toml`
- Create: `src/keelline/__init__.py`
- Create: `src/keelline/__main__.py`
- Create: `src/keelline/cli.py`
- Create: `src/keelline/errors.py`
- Create: `README.md`
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `CHANGELOG.md`
- Create: `changelog.d/foundation.feature.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `keelline.__version__: str`; `keelline.cli.main(argv: list[str] | None = None) -> int`; `keelline.errors.Failure`, `keelline.errors.Refusal` (exit 1 and 2 respectively).

- [ ] **Step 1: Initialise the repository and the package layout**

```bash
mkdir -p ~/Dev/keelline && cd ~/Dev/keelline && git init -q -b main
mkdir -p src/keelline tests changelog.d
cat > pyproject.toml <<'EOF'
[project]
name = "keelline"
version = "0.1.0"
description = "A methodology harness for coding agents: a bug ledger, curated working memory, guards, and an adoption state machine, packaged as one plugin for Claude Code and Codex."
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [{ name = "Nezhinskiy" }]
dependencies = []

[project.scripts]
keelline = "keelline.cli:main"

[build-system]
requires = ["uv_build>=0.11,<0.13"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-root = "src"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.12", "mypy>=1.16", "towncrier>=26.9"]

[tool.ruff]
line-length = 100
target-version = "py311"
extend-include = ["scripts/keelline"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["src", "tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
filterwarnings = ["error"]

[tool.towncrier]
package = "keelline"
package_dir = "src"
directory = "changelog.d"
filename = "CHANGELOG.md"
start_string = "<!-- towncrier release notes start -->\n"
underlines = ["", "", ""]
title_format = "## {version} ({project_date})"
issue_format = "{issue}"

[[tool.towncrier.type]]
directory = "feature"
name = "Added"
showcontent = true

[[tool.towncrier.type]]
directory = "fix"
name = "Fixed"
showcontent = true

[[tool.towncrier.type]]
directory = "change"
name = "Changed"
showcontent = true
EOF
cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/
EOF
printf '# Changelog\n\n<!-- towncrier release notes start -->\n' > CHANGELOG.md
echo "Package skeleton, configuration loader, CLI frame, hook dispatcher interface, release check, and plugin manifests." > changelog.d/foundation.feature.md
cat > README.md <<'EOF'
# Keelline

    /plugin marketplace add Nezhinskiy/keelline
    /plugin install keelline@keelline-marketplace
EOF
cat > LICENSE <<'EOF'
MIT License

Copyright (c) 2026 Nezhinskiy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF
printf '"""Keelline: a methodology harness for coding agents."""\n\n__version__ = "0.1.0"\n' \
  > src/keelline/__init__.py
uv sync
```

`__init__.py`, `README.md` and the changelog fragment exist before `uv sync`, because the build backend needs the module and the readme, and `release check` (Task 8) reads the fragment.

`[tool.mypy] files` omits `scripts/keelline` here and Task 9 appends it in the commit that
creates the launcher: mypy exits 2 on a path in `files` that does not exist ("Cannot read file
'scripts/keelline': No such file or directory", measured 2026-09-06), which no task between this
one and Task 9 could satisfy. `[tool.ruff] extend-include` keeps the launcher's entry from the
start, because ruff treats it as a pattern and ignores it while nothing matches.

- [ ] **Step 2: Write the failing test for `--version`**

```python
# tests/test_cli.py
from __future__ import annotations

import subprocess
import sys

import pytest

from keelline import __version__
from keelline.cli import main


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_module_entry_point_runs_without_the_console_script() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "keelline", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert __version__ in completed.stdout
```

- [ ] **Step 3: Run it to watch it fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'keelline.cli'`.

- [ ] **Step 4: Write the errors and the minimal CLI**

```python
# src/keelline/__main__.py
from keelline.cli import main

raise SystemExit(main())
```

```python
# src/keelline/errors.py
"""Exit-code-bearing exceptions shared by every command (contract C5)."""


class KeellineError(Exception):
    """Base class; never raised directly."""


class Failure(KeellineError):
    """Findings or a failed operation: exit code 1."""


class Refusal(KeellineError):
    """A refusal or an internal error a caller must never read as permission: exit code 2."""
```

```python
# src/keelline/cli.py
"""The CLI frame (contract C5): one parser, three exit codes."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

import keelline
from keelline.errors import Failure, Refusal

if TYPE_CHECKING:
    SubParsers = argparse._SubParsersAction[argparse.ArgumentParser]
else:
    # Generic only in typeshed: subscripting the class at runtime raises TypeError.
    SubParsers = argparse._SubParsersAction

Registrar = Callable[[SubParsers], None]


def build_parser(registrars: Iterable[Registrar] = ()) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelline", description=keelline.__doc__)
    parser.add_argument("--version", action="version", version=f"keelline {keelline.__version__}")
    groups = parser.add_subparsers(dest="group", metavar="<group>")
    for register in registrars:
        register(groups)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except Refusal as exc:
        print(f"keelline: refused: {exc}", file=sys.stderr)
        return 2
    except Failure as exc:
        print(f"keelline: failed: {exc}", file=sys.stderr)
        return 1
```

- [ ] **Step 5: Run the tests to watch them pass, and the gates**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 2 passed. Then `uv run ruff check . && uv run ruff format --check . && uv run mypy`; fix anything reported before committing. Prove the alias guard matters: replace the `else:` branch's assignment with `SubParsers = argparse._SubParsersAction[argparse.ArgumentParser]` and run `uv run python -c "import keelline.cli"`; Expected: `TypeError: type '_SubParsersAction' is not subscriptable`; restore.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -q -m "feat: package skeleton with the CLI frame and --version"
```

---

### Task 2: The stdlib-only import boundary

**Files:**
- Test: `tests/test_import_boundary.py`

**Interfaces:**
- Produces: the invariant every later lane inherits — a module under `src/keelline/` importing outside the standard library and the package itself reddens this test on every interpreter in the CI matrix (Task 10), so a module that is stdlib on 3.13 but not on 3.11 is caught at the floor.

- [ ] **Step 1: Write the test**

```python
# tests/test_import_boundary.py
"""Every runtime module imports only the standard library and keelline itself.

Hooks run under whatever python3 the wrapper finds, before any environment exists, so a
third-party import works on the developer's machine and fails inside a hook on the next one.
`sys.stdlib_module_names` belongs to the running interpreter, which is why CI runs this on
every supported version. Dynamic imports (`importlib.import_module`) are resolved by name
inside the package and are covered by the discovery tests, not by this walk.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "keelline"
ALLOWED = set(sys.stdlib_module_names) | {"keelline"}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_runtime_modules_import_only_the_standard_library() -> None:
    offenders = {
        str(path.relative_to(SRC)): sorted(imported_roots(path) - ALLOWED)
        for path in SRC.rglob("*.py")
        if imported_roots(path) - ALLOWED
    }
    assert offenders == {}


def test_the_boundary_walk_sees_the_cli_module() -> None:
    assert (SRC / "cli.py") in set(SRC.rglob("*.py"))
```

- [ ] **Step 2: Run it to watch it pass, then prove it discriminates**

Run: `uv run pytest tests/test_import_boundary.py -v`
Expected: 2 passed. Add the line `import pytest  # noqa: F401` to the top of `src/keelline/errors.py` and rerun; Expected: `test_runtime_modules_import_only_the_standard_library` reddens naming `errors.py` and `pytest`; remove the line and rerun to green. If it reddens for another reason the assertion needs redesigning.

- [ ] **Step 3: Commit**

```bash
git add tests/test_import_boundary.py && git commit -q -m "guard: pin the stdlib-only import boundary"
```

---

### Task 3: The preset and the configuration schema (C1, part one)

**Files:**
- Create: `src/keelline/presets/__init__.py`
- Create: `src/keelline/presets/recommended.toml`
- Create: `src/keelline/config/__init__.py`
- Create: `src/keelline/config/schema.py`
- Test: `tests/config/__init__.py`
- Test: `tests/config/test_schema.py`

**Interfaces:**
- Produces: dataclasses `Keelline`, `Project`, `Paths`, `Memory`, `Budgets`, `NativeCaps`, `Ledger`, `Artifacts`, `Ci`, `CommitMessages`, `Personal`, `Config` in `keelline.config.schema`; `Budgets.effective(name) -> int` and `Budgets.overrides -> dict[str, int]`; `Paths.as_dict() -> dict[str, str]`; `keelline.presets.load_preset(name: str) -> dict[str, Any]`.

- [ ] **Step 1: Write the preset with the values §7.1 lists**

`hook_output_chars` is the cap S7 measured: exactly 10,000 characters per hook entry (10,000 stayed unspilled, 10,001 spilled), so the value below is measured, not merely documented. `memory_index_words` follows the enforced budget measured in the source project, raised from 1,100 to 1,200 on 2026-09-05.

```toml
# src/keelline/presets/recommended.toml
# Owned by the foundation lane: [budgets], [native_caps], [defaults.*]. The setup lane adds
# every other section.

[budgets]
agents_md_lines = 300
agents_md_words = 3000
status_lines = 50
roadmap_prose_lines = 350
roadmap_prose_words = 3500
memory_index_words = 1200
startup_rules_words = 1600
volatile_notes_words = 2500
volatile_ttl_days = 30

[native_caps]
# Platform limits in their own units, read by the consumers they bound (§9.5).
memory_index_lines = 200
memory_index_bytes = 25600
hook_output_chars = 10000

[defaults.keelline]
state = "initialised"
profile = ""
agents = ["claude", "codex"]

[defaults.project]
base_branch = "main"
release_branch = "main"

[defaults.paths]
agents_md = "AGENTS.md"
adr = "docs/adr"
specs = "docs/specs"
plans = "docs/plans"
bugs = "docs/bugs"
bug_index = "docs/bug-reports.md"
roadmap = "docs/roadmap.md"
roadmap_history = "docs/roadmap-history.md"
memory = "docs/memory"

[defaults.memory]
mode = "local-only"
groups = ["developer", "project-stable", "project-volatile", "specs"]
index_extra = []

[defaults.ledger]
id_prefix = "BR"
code_roots = ["src", "tests", "scripts"]
evidence_boundary_required_for = ["high"]

[defaults.artifacts]
local = []

[defaults.ci]
mode = "reusable"
ref = ""
gate_branch = "main"

[defaults.commit_messages]
attribution_check = true
types = ["feat", "fix", "docs", "test", "refactor", "style", "chore", "harden", "guard"]

[defaults.personal]
reply_language = ""
artifact_language = "en"
preset = "recommended"
```

```python
# src/keelline/presets/__init__.py
"""Presets ship inside the package so an installed wheel can read them."""

from __future__ import annotations

import tomllib
from importlib import resources
from typing import Any

from keelline.errors import Failure


def load_preset(name: str) -> dict[str, Any]:
    if not name.replace("-", "").replace("_", "").isalnum():
        raise Failure(f"preset name {name!r} is not a plain identifier")
    resource = resources.files(__package__).joinpath(f"{name}.toml")
    if not resource.is_file():
        raise Failure(f"preset {name!r} is not shipped with this version of Keelline")
    return tomllib.loads(resource.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Write the failing schema test**

```python
# tests/config/test_schema.py
from __future__ import annotations

import pytest

from keelline.config.schema import Budgets, NativeCaps
from keelline.presets import load_preset


def test_recommended_preset_carries_every_budget_and_cap_the_schema_knows() -> None:
    preset = load_preset("recommended")
    assert set(preset["budgets"]) == set(Budgets.NAMES)
    assert set(preset["native_caps"]) == set(NativeCaps.NAMES)


def test_effective_budget_is_the_minimum_of_preset_and_override() -> None:
    budgets = Budgets(
        preset={"memory_index_words": 1100, "agents_md_lines": 300},
        configured={"agents_md_lines": 250, "memory_index_words": 5000},
    )
    assert budgets.effective("agents_md_lines") == 250
    assert budgets.effective("memory_index_words") == 1100
    assert budgets.overrides == {"agents_md_lines": 250, "memory_index_words": 5000}


def test_unknown_budget_name_is_a_key_error() -> None:
    # The preset carries the name so that only the `NAMES` check can raise: with `preset={}`
    # the empty dict's own lookup raises the identical KeyError and the check is unfalsifiable.
    with pytest.raises(KeyError):
        Budgets(preset={"no_such_budget": 999}, configured={}).effective("no_such_budget")
```

`tests/config/__init__.py` is an empty file so pytest resolves the package.

- [ ] **Step 3: Run it to watch it fail**

Run: `uv run pytest tests/config/test_schema.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'keelline.config'`.

- [ ] **Step 4: Write the schema**

```python
# src/keelline/config/__init__.py
"""Configuration (contract C1): keelline.toml merged under a preset, typed and validated."""

from keelline.config.schema import Config

__all__ = ["Config"]
```

```python
# src/keelline/config/schema.py
"""Typed sections of keelline.toml. Numbers come from the preset, never from code."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar

PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
STATES = ("initialised", "adopting", "installed")
MEMORY_MODES = ("overlay", "in-repo", "local-only")
CI_MODES = ("reusable", "uvx", "none")


@dataclass(frozen=True)
class Keelline:
    version: str
    state: str
    preset: str
    profile: str
    agents: tuple[str, ...]


@dataclass(frozen=True)
class Project:
    name: str
    base_branch: str
    release_branch: str


@dataclass(frozen=True)
class Paths:
    agents_md: str
    architecture: str
    runbooks: str
    adr: str
    specs: str
    plans: str
    bugs: str
    bug_index: str
    roadmap: str
    roadmap_history: str
    memory: str

    def as_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Memory:
    mode: str
    groups: tuple[str, ...]
    index_extra: tuple[str, ...]


@dataclass(frozen=True)
class Budgets:
    """A project may lower a budget below the preset and never raise it (D7)."""

    NAMES: ClassVar[tuple[str, ...]] = (
        "agents_md_lines",
        "agents_md_words",
        "status_lines",
        "roadmap_prose_lines",
        "roadmap_prose_words",
        "memory_index_words",
        "startup_rules_words",
        "volatile_notes_words",
        "volatile_ttl_days",
    )

    preset: dict[str, int]
    configured: dict[str, int] = field(default_factory=dict)

    def effective(self, name: str) -> int:
        if name not in self.NAMES:
            raise KeyError(name)
        value = self.preset[name]
        if name in self.configured:
            value = min(value, self.configured[name])
        return value

    @property
    def overrides(self) -> dict[str, int]:
        return {k: v for k, v in self.configured.items() if v != self.preset.get(k)}


@dataclass(frozen=True)
class NativeCaps:
    """Platform limits in their own units; consumers of a bounded thing read them (§9.5)."""

    NAMES: ClassVar[tuple[str, ...]] = (
        "memory_index_lines",
        "memory_index_bytes",
        "hook_output_chars",
    )

    memory_index_lines: int
    memory_index_bytes: int
    hook_output_chars: int


@dataclass(frozen=True)
class Ledger:
    id_prefix: str
    code_roots: tuple[str, ...]
    evidence_boundary_required_for: tuple[str, ...]


@dataclass(frozen=True)
class Artifacts:
    local: tuple[str, ...]


@dataclass(frozen=True)
class Ci:
    mode: str
    ref: str
    gate_branch: str


@dataclass(frozen=True)
class CommitMessages:
    attribution_check: bool
    types: tuple[str, ...]


@dataclass(frozen=True)
class Personal:
    """Machine-level parameters (§5.4); never read from a repository."""

    reply_language: str
    artifact_language: str
    preset: str


@dataclass(frozen=True)
class Config:
    keelline: Keelline
    project: Project
    paths: Paths
    memory: Memory
    budgets: Budgets
    native_caps: NativeCaps
    ledger: Ledger
    artifacts: Artifacts
    ci: Ci
    commit_messages: CommitMessages
    personal: Personal
```

- [ ] **Step 5: Run the tests to watch them pass, then prove the clamp discriminates**

Run: `uv run pytest tests/config -v`
Expected: 3 passed. Change `min(value, self.configured[name])` to `self.configured[name]` and rerun; Expected: `test_effective_budget_is_the_minimum_of_preset_and_override` reddens on the `memory_index_words` assertion; restore. Then delete the two `if name not in self.NAMES: raise KeyError(name)` lines and rerun; Expected: `test_unknown_budget_name_is_a_key_error` reddens with `DID NOT RAISE`; restore. If either reddens for another reason the assertion needs redesigning.

- [ ] **Step 6: Commit**

```bash
git add src/keelline/presets src/keelline/config tests/config
git commit -q -m "feat(config): typed sections, the recommended preset, and lower-only budgets"
```

---

### Task 4: The loader — merge under the preset, validate, reject (C1, part two)

**Files:**
- Create: `src/keelline/config/loader.py`
- Create: `src/keelline/config/machine.py`
- Create: `src/keelline/config/paths.py` (a one-line stub here; Task 5 writes the real module)
- Test: `tests/config/test_loader.py`

**Interfaces:**
- Produces: `keelline.config.loader.load(root: Path, *, machine: Path | None = None) -> Config`; `keelline.config.loader.ConfigError(Failure)`; `keelline.config.loader.CONFIG_FILE = "keelline.toml"`; `keelline.config.machine.machine_config_path(env: Mapping[str, str]) -> Path` honouring `KEELLINE_CONFIG` then `$XDG_CONFIG_HOME/keelline/config.toml` then `~/.config/keelline/config.toml`. The loader calls `validate_paths` (Task 5) before returning, so a config that escapes the root never reaches a caller.

- [ ] **Step 1: Write the failing tests**

```python
# tests/config/test_loader.py
from __future__ import annotations

from pathlib import Path

import pytest

from keelline.config.loader import CONFIG_FILE, ConfigError, load

HEAD = '[keelline]\nversion = "0.1.0"\npreset = "recommended"\n'
MINIMAL = HEAD + '\n[project]\nname = "sample"\n'


def write(root: Path, text: str) -> None:
    (root / CONFIG_FILE).write_text(text, encoding="utf-8")


def test_missing_file_names_the_next_command(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="keelline init"):
        load(tmp_path, machine=tmp_path / "no-machine.toml")


def test_preset_defaults_fill_every_section(tmp_path: Path) -> None:
    write(tmp_path, MINIMAL)
    config = load(tmp_path, machine=tmp_path / "no-machine.toml")
    assert config.keelline.state == "initialised"
    assert config.paths.specs == "docs/specs"
    assert config.memory.mode == "local-only"
    assert config.budgets.effective("agents_md_lines") == 300
    assert config.native_caps.hook_output_chars == 10000
    assert config.commit_messages.types[-1] == "guard"
    assert config.personal.artifact_language == "en"


def test_file_values_override_preset_values(tmp_path: Path) -> None:
    write(
        tmp_path,
        MINIMAL + '\n[paths]\nspecs = "design/specs"\n\n[budgets]\nagents_md_lines = 250\n',
    )
    config = load(tmp_path, machine=tmp_path / "no-machine.toml")
    assert config.paths.specs == "design/specs"
    assert config.budgets.effective("agents_md_lines") == 250
    assert config.budgets.overrides == {"agents_md_lines": 250}


def test_machine_config_sits_between_file_and_preset(tmp_path: Path) -> None:
    write(tmp_path, MINIMAL)
    machine = tmp_path / "machine.toml"
    machine.write_text('[personal]\nreply_language = "ru"\n', encoding="utf-8")
    config = load(tmp_path, machine=machine)
    assert config.personal.reply_language == "ru"
    assert config.personal.artifact_language == "en"


def test_unknown_top_level_section_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, MINIMAL + "\n[commit]\nci_workflow = true\n")
    with pytest.raises(ConfigError, match=r"unknown section\(s\): commit"):
        load(tmp_path, machine=tmp_path / "no-machine.toml")


def test_unknown_key_inside_a_section_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, MINIMAL + '\n[ci]\nbranch = "dev"\n')
    with pytest.raises(ConfigError, match=r"\[ci\] has unknown key\(s\): branch"):
        load(tmp_path, machine=tmp_path / "no-machine.toml")


def test_a_section_that_is_not_a_table_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, 'ci = "not-a-table"\n' + MINIMAL)
    with pytest.raises(ConfigError, match=r"\[ci\] must be a table"):
        load(tmp_path, machine=tmp_path / "no-machine.toml")


@pytest.mark.parametrize("name", ["../common", "Two Words", "", "-leading", "a/b"])
def test_project_name_must_be_one_lowercase_path_segment(tmp_path: Path, name: str) -> None:
    write(tmp_path, MINIMAL.replace('"sample"', f'"{name}"'))
    with pytest.raises(ConfigError, match="project.name"):
        load(tmp_path, machine=tmp_path / "no-machine.toml")


@pytest.mark.parametrize(
    ("text", "key"),
    [
        (HEAD + 'state = "deployed"\n\n[project]\nname = "sample"\n', "keelline.state"),
        (MINIMAL + '\n[memory]\nmode = "cloud"\n', "memory.mode"),
        (MINIMAL + '\n[ci]\nmode = "pip"\n', "ci.mode"),
    ],
)
def test_enumerated_values_are_validated(tmp_path: Path, text: str, key: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError, match=key):
        load(tmp_path, machine=tmp_path / "no-machine.toml")


@pytest.mark.parametrize(
    "text",
    [
        MINIMAL + "\n[budgets]\nagents_md_lines = -5\n",
        MINIMAL + '\n[budgets]\nagents_md_lines = "many"\n',
        MINIMAL + '\n[commit_messages]\nattribution_check = "yes"\n',
        MINIMAL + '\n[ledger]\ncode_roots = "src"\n',
    ],
)
def test_value_types_and_ranges_are_validated(tmp_path: Path, text: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError):
        load(tmp_path, machine=tmp_path / "no-machine.toml")


@pytest.mark.xfail(strict=True, reason="validate_paths lands in Task 5")
def test_a_path_that_escapes_the_root_is_refused_by_load(tmp_path: Path) -> None:
    write(tmp_path, MINIMAL + '\n[paths]\nspecs = "../elsewhere"\n')
    with pytest.raises(Exception, match="project root"):
        load(tmp_path, machine=tmp_path / "no-machine.toml")
```

- [ ] **Step 2: Run them to watch them fail**

Run: `uv run pytest tests/config/test_loader.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'keelline.config.loader'`.

- [ ] **Step 3: Write the machine-config path helper and the loader**

```python
# src/keelline/config/machine.py
"""Where the machine-level configuration lives (§5.4); the file is optional."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


def machine_config_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    explicit = env.get("KEELLINE_CONFIG")
    if explicit:
        return Path(explicit)
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "keelline" / "config.toml"
```

```python
# src/keelline/config/loader.py
"""Read keelline.toml, merge it under the machine config and the preset, validate it."""

from __future__ import annotations

import tomllib
from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar, cast

from keelline.config.machine import machine_config_path
from keelline.config.paths import validate_paths
from keelline.config.schema import (
    CI_MODES,
    MEMORY_MODES,
    PROJECT_NAME,
    STATES,
    Artifacts,
    Budgets,
    Ci,
    CommitMessages,
    Config,
    Keelline,
    Ledger,
    Memory,
    NativeCaps,
    Paths,
    Personal,
    Project,
)
from keelline.errors import Failure
from keelline.presets import load_preset

CONFIG_FILE = "keelline.toml"
SECTIONS = (
    "keelline",
    "project",
    "paths",
    "memory",
    "budgets",
    "ledger",
    "artifacts",
    "ci",
    "commit_messages",
)


T = TypeVar("T")


class ConfigError(Failure):
    """A keelline.toml that cannot be trusted as written."""


def _table(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _merged(raw: dict[str, Any], defaults: dict[str, Any], name: str) -> dict[str, Any]:
    return {**defaults.get(name, {}), **_table(raw, name)}


def _build(cls: type[T], name: str, values: dict[str, Any]) -> T:
    known = {f.name: f.type for f in fields(cast(Any, cls))}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ConfigError(f"[{name}] has unknown key(s): {', '.join(unknown)}")
    missing = sorted(set(known) - set(values))
    if missing:
        raise ConfigError(f"[{name}] is missing required key(s): {', '.join(missing)}")
    coerced: dict[str, Any] = {}
    for key, value in values.items():
        annotation = str(known[key])
        if annotation.startswith("tuple"):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ConfigError(f"{name}.{key} must be a list of strings")
            coerced[key] = tuple(value)
        elif annotation == "bool":
            if not isinstance(value, bool):
                raise ConfigError(f"{name}.{key} must be true or false")
            coerced[key] = value
        elif annotation == "int":
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(f"{name}.{key} must be a positive integer")
            coerced[key] = value
        else:
            if not isinstance(value, str):
                raise ConfigError(f"{name}.{key} must be a string")
            coerced[key] = value
    return cls(**coerced)


def _enum(section: str, key: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ConfigError(f"{section}.{key} must be one of {', '.join(allowed)}; got {value!r}")


def _budgets(raw: dict[str, Any], preset: dict[str, Any]) -> Budgets:
    configured = _table(raw, "budgets")
    unknown = sorted(set(configured) - set(Budgets.NAMES))
    if unknown:
        raise ConfigError(f"[budgets] has unknown key(s): {', '.join(unknown)}")
    for key, value in configured.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"budgets.{key} must be a positive integer")
    return Budgets(preset=dict(preset["budgets"]), configured=dict(configured))


def _personal(machine: Path, preset: dict[str, Any]) -> Personal:
    values: dict[str, Any] = dict(preset.get("defaults", {}).get("personal", {}))
    if machine.is_file():
        try:
            raw = tomllib.loads(machine.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{machine} is not valid TOML: {exc}") from None
        values.update(_table(raw, "personal"))
    return _build(Personal, "personal", values)


def load(root: Path, *, machine: Path | None = None) -> Config:
    path = root / CONFIG_FILE
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path} does not exist; run `keelline init` first") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from None
    unknown = sorted(set(raw) - set(SECTIONS))
    if unknown:
        raise ConfigError(f"{path} has unknown section(s): {', '.join(unknown)}")

    head = _table(raw, "keelline")
    preset_name = str(head.get("preset", "recommended"))
    preset = load_preset(preset_name)
    defaults = dict(preset.get("defaults", {}))
    defaults["keelline"] = {**defaults.get("keelline", {}), "preset": preset_name}

    keelline = _build(Keelline, "keelline", _merged(raw, defaults, "keelline"))
    _enum("keelline", "state", keelline.state, STATES)
    project = _build(Project, "project", _merged(raw, defaults, "project"))
    if not PROJECT_NAME.match(project.name):
        raise ConfigError(
            "project.name must be one lowercase path segment matching "
            f"{PROJECT_NAME.pattern}; got {project.name!r}"
        )
    paths = _build(Paths, "paths", _merged(raw, defaults, "paths"))
    memory = _build(Memory, "memory", _merged(raw, defaults, "memory"))
    _enum("memory", "mode", memory.mode, MEMORY_MODES)
    ledger = _build(Ledger, "ledger", _merged(raw, defaults, "ledger"))
    artifacts = _build(Artifacts, "artifacts", _merged(raw, defaults, "artifacts"))
    ci = _build(Ci, "ci", _merged(raw, defaults, "ci"))
    _enum("ci", "mode", ci.mode, CI_MODES)
    commit_messages = _build(
        CommitMessages, "commit_messages", _merged(raw, defaults, "commit_messages")
    )
    caps = _build(NativeCaps, "native_caps", dict(preset["native_caps"]))
    personal = _personal(machine or machine_config_path(), preset)
    config = Config(
        keelline=keelline,
        project=project,
        paths=paths,
        memory=memory,
        budgets=_budgets(raw, preset),
        native_caps=caps,
        ledger=ledger,
        artifacts=artifacts,
        ci=ci,
        commit_messages=commit_messages,
        personal=personal,
    )
    validate_paths(config, root)
    return config
```

The `Ci.ref` default is the empty string in the preset; `init` writes the resolved SHA (§7.1), so an empty `ref` is a valid "not scaffolded yet" state and `_build` accepts empty strings.

- [ ] **Step 4: Run the tests to watch them pass, then prove the unknown-key check discriminates**

Run: `uv run pytest tests/config -v`
Expected: every loader test passes and `test_a_path_that_escapes_the_root_is_refused_by_load` xfails, because the stub cannot refuse anything; the marker is strict, so Task 5 must delete it when the real check lands. Write the typed stub `def validate_paths(config: object, root: object) -> dict[str, object]: return {}` in a new `paths.py` now, so the import resolves and this task's mypy gate passes, and Task 5 replaces it. The marker exists because this plan's Global Constraints require a task's tests to pass before its commit, which a knowingly red test cannot do; Task 6 marks its own forward reference to Task 8 the same way. Delete the two `unknown` lines in `_build` and rerun; Expected: `test_unknown_key_inside_a_section_is_rejected` reddens; restore. If it reddens for another reason the assertion needs redesigning.

- [ ] **Step 5: Commit**

```bash
git add src/keelline/config tests/config/test_loader.py
git commit -q -m "feat(config): load keelline.toml under the machine config and the preset"
```

---

### Task 5: Path containment (C1, part three; shared with C2)

**Files:**
- Modify: `src/keelline/config/paths.py`
- Modify: `tests/config/test_loader.py` (remove Task 4's `xfail` marker)
- Test: `tests/config/test_paths.py`

**Interfaces:**
- Produces: `keelline.config.paths.contained(root: Path, relative: str, *, allow_final_symlink: bool = False) -> Path`; `keelline.config.paths.PathEscape(Refusal)`; `keelline.config.paths.validate_paths(config: Config, root: Path) -> dict[str, Path]`. The scaffold lane calls `contained` from `plan()` and `apply()`; the memory-engine lane passes `allow_final_symlink=True` for `paths.memory` and validates the link target itself (§9.1).

- [ ] **Step 1: Write the failing tests**

```python
# tests/config/test_paths.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

from keelline.config.paths import PathEscape, contained


def test_a_plain_relative_path_resolves_under_the_root(tmp_path: Path) -> None:
    assert contained(tmp_path, "docs/specs") == tmp_path / "docs" / "specs"


@pytest.mark.parametrize(
    "relative", ["../sibling", "docs/../../x", "/etc/keelline", "", ".", "docs/./../.."]
)
def test_escapes_are_refused(tmp_path: Path, relative: str) -> None:
    with pytest.raises(PathEscape):
        contained(tmp_path, relative)


def test_dotdot_is_refused_even_when_it_resolves_inside_the_root(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    with pytest.raises(PathEscape, match="'..'"):
        contained(tmp_path, "docs/../docs/specs")


def test_a_symlinked_intermediate_directory_is_refused(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "docs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathEscape, match="symlink"):
        contained(tmp_path, "docs/specs")


def test_a_symlink_pointing_inside_the_root_is_still_refused(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "docs").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(PathEscape, match="symlink"):
        contained(tmp_path, "docs/specs")


def test_a_final_symlink_is_refused_unless_allowed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-store"
    outside.mkdir()
    (tmp_path / "docs").mkdir()
    os.symlink(outside, tmp_path / "docs" / "memory", target_is_directory=True)
    with pytest.raises(PathEscape):
        contained(tmp_path, "docs/memory")
    allowed = contained(tmp_path, "docs/memory", allow_final_symlink=True)
    assert allowed == tmp_path / "docs" / "memory"


def test_a_symlinked_root_does_not_confuse_containment(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert contained(link, "docs") == link / "docs"
```

- [ ] **Step 2: Run them to watch them fail**

Run: `uv run pytest tests/config/test_paths.py -v`
Expected: with the Task 4 stub in place, `ImportError: cannot import name 'PathEscape'`.

- [ ] **Step 3: Write the containment check**

```python
# src/keelline/config/paths.py
"""Root containment for every path a repository-controlled file can name (§7.4)."""

from __future__ import annotations

from pathlib import Path

from keelline.config.schema import Config
from keelline.errors import Refusal


class PathEscape(Refusal):
    """A configured path that leaves the project root or passes through a symlink."""


def contained(root: Path, relative: str, *, allow_final_symlink: bool = False) -> Path:
    if not relative or relative == ".":
        raise PathEscape("a path must name something inside the project root, not the root")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise PathEscape(f"{relative!r} is absolute; paths must stay inside the project root")
    if any(part == ".." for part in candidate.parts):
        raise PathEscape(f"{relative!r} contains '..'; paths must stay inside the project root")
    target = root / candidate
    for ancestor in [target, *target.parents]:
        if ancestor == root:
            break
        if ancestor.is_symlink() and not (allow_final_symlink and ancestor == target):
            raise PathEscape(f"{relative!r} passes through a symlink at {ancestor}")
    # Defence in depth: the two checks above already refuse every escape a path string can
    # express, so no mutation reddens a test through this line alone; it stays for the path
    # form nobody has thought of yet.
    resolved_root = root.resolve()
    resolved = target.parent.resolve() / target.name if allow_final_symlink else target.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise PathEscape(f"{relative!r} resolves outside the project root")
    return target


def validate_paths(config: Config, root: Path) -> dict[str, Path]:
    return {
        name: contained(root, relative, allow_final_symlink=(name == "memory"))
        for name, relative in config.paths.as_dict().items()
    }
```

- [ ] **Step 4: Run the tests to watch them pass, then prove each pinned check discriminates**

Run: `uv run pytest tests/config -v`
Delete the `@pytest.mark.xfail(...)` line above `test_a_path_that_escapes_the_root_is_refused_by_load` in `tests/config/test_loader.py` first; the marker is strict, so leaving it in place turns the now-passing test into a failure.
Expected: 12 path tests pass and Task 4's escape test turns green. Two mutations, each restored before the next: remove the `".."` rejection; Expected: `test_dotdot_is_refused_even_when_it_resolves_inside_the_root` reddens while the other escapes stay refused by the resolve check. Remove the `is_symlink()` branch; Expected: `test_a_symlink_pointing_inside_the_root_is_still_refused` reddens (the resolve check cannot see an inside-pointing link) and `test_a_symlinked_intermediate_directory_is_refused` reddens on its message. If either reddens for another reason the assertion needs redesigning.

- [ ] **Step 5: Commit**

```bash
git add src/keelline/config/paths.py tests/config/test_paths.py tests/config/test_loader.py
git commit -q -m "harden(config): contain every configured path inside the project root"
```

---

### Task 6: Area discovery, results, `--json` everywhere, exit codes (C5)

**Files:**
- Modify: `src/keelline/cli.py`
- Create: `src/keelline/result.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `keelline.result.Result(summary: str, data: dict[str, Any] = {}, exit_code: int = 0)`; `keelline.cli.discover_registrars() -> list[Registrar]` finding every `keelline.<area>.commands.register(subparsers)`; `keelline.cli.run(argv, *, registrars) -> int`; `keelline.cli.split_json_flag(argv) -> tuple[list[str], bool]`; a command function is `Callable[[argparse.Namespace], Result | int]`; `--json` anywhere on the line prints `{"summary": ..., **data}` on success and `{"summary": ..., "error": "failed" | "refused"}` on failure.

- [ ] **Step 1: Replace the test file**

```python
# tests/test_cli.py  (whole file)
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable

import pytest

from keelline import __version__
from keelline.cli import Registrar, SubParsers, discover_registrars, main, run
from keelline.errors import Failure, Refusal
from keelline.result import Result


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_module_entry_point_runs_without_the_console_script() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "keelline", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert __version__ in completed.stdout


def _area(name: str, func: Callable[[argparse.Namespace], Result]) -> Registrar:
    def register(groups: SubParsers) -> None:
        group = groups.add_parser(name)
        sub = group.add_subparsers(dest="command", metavar="<command>")
        cmd = sub.add_parser("go")
        cmd.set_defaults(func=func)

    return register


def _ok(args: argparse.Namespace) -> Result:
    return Result("probe ran", {"n": 1})


def _failing(args: argparse.Namespace) -> Result:
    raise Failure("three findings")


def _refusing(args: argparse.Namespace) -> Result:
    raise Refusal("an absent guard is not permission")


def test_a_result_prints_its_summary_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go"], registrars=[_area("probe", _ok)]) == 0
    assert capsys.readouterr().out.strip() == "probe ran"


def test_json_flag_works_anywhere_on_the_line(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go", "--json"], registrars=[_area("probe", _ok)]) == 0
    assert json.loads(capsys.readouterr().out) == {"summary": "probe ran", "n": 1}
    assert run(["--json", "probe", "go"], registrars=[_area("probe", _ok)]) == 0
    assert json.loads(capsys.readouterr().out) == {"summary": "probe ran", "n": 1}


def test_failure_exits_one_and_refusal_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go"], registrars=[_area("probe", _failing)]) == 1
    assert "three findings" in capsys.readouterr().err
    assert run(["probe", "go"], registrars=[_area("probe", _refusing)]) == 2
    assert "refused: an absent guard" in capsys.readouterr().err


def test_failures_emit_json_when_asked(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["probe", "go", "--json"], registrars=[_area("probe", _failing)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "failed"


@pytest.mark.xfail(strict=True, reason="the release area lands in Task 8")
def test_areas_are_discovered_from_the_package() -> None:
    names = {registrar.__module__ for registrar in discover_registrars()}
    assert "keelline.release.commands" in names
```

- [ ] **Step 2: Run them to watch them fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: `ImportError: cannot import name 'discover_registrars'`.

- [ ] **Step 3: Write the result type and replace the frame**

```python
# src/keelline/result.py
"""What a command returns; the frame turns it into one line or one JSON object."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Result:
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
```

```python
# src/keelline/cli.py  (whole file)
"""The CLI frame (contract C5): one parser, areas discovered by name, three exit codes."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import pkgutil
import sys
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

import keelline
from keelline.errors import Failure, Refusal
from keelline.result import Result

if TYPE_CHECKING:
    SubParsers = argparse._SubParsersAction[argparse.ArgumentParser]
else:
    # Generic only in typeshed: subscripting the class at runtime raises TypeError.
    SubParsers = argparse._SubParsersAction

Registrar = Callable[[SubParsers], None]


def discover_registrars() -> list[Registrar]:
    """Every `keelline.<area>.commands.register`, in name order, with no shared registry."""
    registrars: list[Registrar] = []
    for module in sorted(pkgutil.iter_modules(keelline.__path__), key=lambda m: m.name):
        if not module.ispkg:
            continue
        spec = importlib.util.find_spec(f"keelline.{module.name}.commands")
        if spec is None:
            continue
        registrars.append(importlib.import_module(spec.name).register)
    return registrars


def build_parser(registrars: Iterable[Registrar] = ()) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelline", description=keelline.__doc__)
    parser.add_argument("--version", action="version", version=f"keelline {keelline.__version__}")
    groups = parser.add_subparsers(dest="group", metavar="<group>")
    for register in registrars:
        register(groups)
    return parser


def split_json_flag(argv: list[str]) -> tuple[list[str], bool]:
    """`--json` is accepted anywhere, so every command carries it without declaring it."""
    return [arg for arg in argv if arg != "--json"], "--json" in argv


def _report(kind: str, message: str, code: int, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"summary": f"{kind}: {message}", "error": kind}, sort_keys=True))
    else:
        print(f"keelline: {kind}: {message}", file=sys.stderr)
    return code


def run(argv: list[str] | None, *, registrars: Iterable[Registrar]) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args_in, as_json = split_json_flag(raw)
    parser = build_parser(registrars)
    args = parser.parse_args(args_in)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        outcome = func(args)
    except Refusal as exc:
        return _report("refused", str(exc), 2, as_json)
    except Failure as exc:
        return _report("failed", str(exc), 1, as_json)
    if not isinstance(outcome, Result):
        return int(outcome)
    if as_json:
        print(json.dumps({"summary": outcome.summary, **outcome.data}, indent=2, sort_keys=True))
    else:
        print(outcome.summary)
    return outcome.exit_code


def main(argv: list[str] | None = None) -> int:
    return run(argv, registrars=discover_registrars())
```

- [ ] **Step 4: Run the tests and the gates**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 6 passed, 1 xfailed. Then `uv run ruff check . && uv run ruff format --check . && uv run mypy`, fixing anything reported. Prove the flag splitter is load-bearing: make `split_json_flag` return `(argv, False)` and rerun; Expected: `test_json_flag_works_anywhere_on_the_line` and `test_failures_emit_json_when_asked` both redden with an argparse usage error, because both pass `--json` through the same seam; restore.

- [ ] **Step 5: Commit**

```bash
git add src/keelline/cli.py src/keelline/result.py tests/test_cli.py
git commit -q -m "feat(cli): discover areas by name, accept --json anywhere, map failures to exit codes"
```

---

### Task 7: The hook dispatcher interface and a reference dispatcher (C4)

**Files:**
- Create: `src/keelline/hooks/__init__.py`
- Create: `src/keelline/hooks/api.py`
- Create: `src/keelline/hooks/registry.py`
- Create: `src/keelline/hooks/dispatch.py`
- Create: `src/keelline/hooks/commands.py`
- Test: `tests/hooks/__init__.py`
- Test: `tests/hooks/test_dispatch.py`
- Test: `tests/hooks/test_hook_command.py`

**Interfaces:** *(current — this block describes the C4 API as shipped; the Task 7 code
blocks below predate the hardening that produced it, per the Premise.)*
- Produces (fixed for every lane): `Policy` (`OPEN`, `CLOSED`); `HookEvent(name, session_id, agent_id, tool_name, tool_input, cwd, project_root, harness, raw)`; `HookResult(context=None, decision=None, reason=None)` (`decision` is a `Decision` member; an unrecognised one is that handler failing and is judged by its policy); `Handler(name, event, policy, run, once_key=None)` where `run: Callable[[HookEvent, Config | None], HookResult]`; `Sink` protocol with `diagnostic(record: dict[str, object]) -> None`, `seen(key: str) -> bool`, `mark(key: str) -> None`, and `NullSink`; `registry.discover() -> list[Handler]` collecting every `keelline.<area>.hooks.register() -> list[Handler]`; `dispatch.dispatch(event, handlers, config, *, sink, cap=None) -> Outcome(exit_code, stdout, stderr, decision)` — `sink` is required and has no default, so a caller cannot inherit an inert one by omission; until `hooks-core` supplies a durable session-keyed sink, `run_hook` passes `NullSink()` and `Handler.once_key` therefore degrades to every invocation rather than once; `dispatch.parse_event(payload, env) -> HookEvent`; `dispatch.detect_harness(env) -> str`; `keelline hook <event>` reads the event JSON from stdin. The `hooks-core` lane supplies the real sink (diagnostics log, once-per-context markers), the wrapper and the per-harness emitter without changing these names.

- [ ] **Step 1: Write the failing dispatcher tests**

The harness discriminator comes from the S1 record: Codex's hook launch sets `PLUGIN_ROOT` and `PLUGIN_DATA` alongside the `CLAUDE_*` names, and Codex's `SessionStart` stdin carries `model` and `permission_mode`. `detect_harness` keys on `PLUGIN_ROOT` first and on those two stdin fields second, never on `CLAUDE_PLUGIN_ROOT` alone; `CODEX_HOME` and `CLAUDE_CONFIG_DIR` are not used because S1 could not attribute them to the harness. Codex's `PreToolUse` tool names have since been measured (S1: `Bash` for every shell-routed action, the literal `apply_patch` for a patch-based edit; §10 of the design), and nothing here depends on them either way — `detect_harness` reads the environment and the stdin payload, never `tool_name`.

```python
# tests/hooks/test_dispatch.py
from __future__ import annotations

import json
from pathlib import Path

from keelline.hooks.api import Handler, HookEvent, HookResult, Policy
from keelline.hooks.dispatch import Recorder, dispatch, parse_event

CLAUDE_ENV = {"CLAUDE_PROJECT_DIR": "/p", "CLAUDE_PLUGIN_ROOT": "/r"}


def event(name: str = "PreToolUse", **raw: object) -> HookEvent:
    payload: dict[str, object] = {
        "hook_event_name": name,
        "session_id": "s",
        "cwd": "/tmp",
        "tool_name": "Bash",
    }
    payload.update(raw)
    return parse_event(payload, env=CLAUDE_ENV)


def handler(name: str, policy: Policy, result: HookResult | Exception) -> Handler:
    def run(ev: HookEvent, config: object) -> HookResult:
        if isinstance(result, Exception):
            raise result
        return result

    return Handler(name=name, event="PreToolUse", policy=policy, run=run)


def test_contexts_are_joined_into_the_claude_shape() -> None:
    handlers = [
        handler("a", Policy.OPEN, HookResult(context="A")),
        handler("b", Policy.OPEN, HookResult(context="B")),
    ]
    outcome = dispatch(event(), handlers, config=None)
    assert outcome.exit_code == 0
    assert json.loads(outcome.stdout) == {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "A\n\nB"}
    }


def test_a_deny_from_a_handler_exits_two_with_its_reason() -> None:
    handlers = [handler("g", Policy.CLOSED, HookResult(decision="deny", reason="no"))]
    outcome = dispatch(event(), handlers, config=None)
    assert outcome.exit_code == 2
    assert outcome.decision == "deny"
    assert "no" in outcome.stderr


def test_an_open_handler_that_raises_is_swallowed_and_recorded() -> None:
    recorder = Recorder()
    outcome = dispatch(
        event(), [handler("a", Policy.OPEN, RuntimeError("boom"))], None, sink=recorder
    )
    assert outcome.exit_code == 0
    assert "boom" in outcome.stderr
    assert recorder.records[0]["handler"] == "a"
    assert recorder.records[0]["error"] == "RuntimeError"


def test_a_closed_handler_that_raises_refuses() -> None:
    outcome = dispatch(event(), [handler("g", Policy.CLOSED, RuntimeError("boom"))], None)
    assert outcome.exit_code == 2
    assert "boom" in outcome.stderr


def test_policy_is_taken_from_handlers_that_failed_not_from_all_registered() -> None:
    handlers = [
        handler("g", Policy.CLOSED, HookResult()),
        handler("a", Policy.OPEN, RuntimeError("boom")),
    ]
    assert dispatch(event(), handlers, None).exit_code == 0


def test_context_above_the_cap_is_truncated_and_recorded() -> None:
    recorder = Recorder()
    handlers = [handler("a", Policy.OPEN, HookResult(context="x" * 50))]
    outcome = dispatch(event(), handlers, None, sink=recorder, cap=20)
    context = json.loads(outcome.stdout)["hookSpecificOutput"]["additionalContext"]
    assert len(context) <= 20
    assert recorder.records[0]["error"] == "context-truncated"


def test_project_root_prefers_the_claude_variable_over_git(tmp_path: Path) -> None:
    ev = parse_event({"hook_event_name": "SessionStart", "cwd": str(tmp_path)}, env=CLAUDE_ENV)
    assert ev.project_root == Path("/p")
    assert ev.harness == "claude"


def test_codex_is_detected_by_its_own_variable_even_beside_the_claude_ones() -> None:
    env = {"PLUGIN_ROOT": "/x", "CLAUDE_PLUGIN_ROOT": "/x"}
    ev = parse_event({"hook_event_name": "SessionStart", "cwd": "/tmp"}, env=env)
    assert ev.harness == "codex"


def test_codex_is_detected_by_the_stdin_fields_s1_recorded() -> None:
    payload = {
        "hook_event_name": "SessionStart",
        "cwd": "/tmp",
        "model": "m",
        "permission_mode": "p",
    }
    ev = parse_event(payload, env={"CLAUDE_PLUGIN_ROOT": "/x"})
    assert ev.harness == "codex"
```

`tests/hooks/__init__.py` is an empty file. Every test passes an `env` that carries `CLAUDE_PROJECT_DIR`, so no test shells out to git.

- [ ] **Step 2: Write the failing command test**

```python
# tests/hooks/test_hook_command.py
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def hook(event: str, stdin: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "keelline", "hook", event],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(ROOT / "src"),
            "CLAUDE_PROJECT_DIR": str(cwd),
            "KEELLINE_CONFIG": str(cwd / "no-machine.toml"),
        },
    )


def test_no_handlers_means_a_clean_empty_outcome(tmp_path: Path) -> None:
    completed = hook("SessionStart", json.dumps({"hook_event_name": "SessionStart"}), tmp_path)
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_malformed_stdin_on_pre_tool_use_refuses(tmp_path: Path) -> None:
    completed = hook("PreToolUse", "{not json", tmp_path)
    assert completed.returncode == 2
    assert "refused" in completed.stderr


def test_malformed_stdin_on_session_start_degrades_open(tmp_path: Path) -> None:
    completed = hook("SessionStart", "{not json", tmp_path)
    assert completed.returncode == 0
    assert "keelline" in completed.stderr


def test_a_broken_repository_config_on_pre_tool_use_refuses(tmp_path: Path) -> None:
    (tmp_path / "keelline.toml").write_text('ci = "not-a-table"\n', encoding="utf-8")
    completed = hook("PreToolUse", json.dumps({"hook_event_name": "PreToolUse"}), tmp_path)
    assert completed.returncode == 2
```

- [ ] **Step 3: Run them to watch them fail**

Run: `uv run pytest tests/hooks -v`
Expected: `ModuleNotFoundError: No module named 'keelline.hooks'`.

- [ ] **Step 4: Write the API, the registry, the dispatcher, and the command**

```python
# src/keelline/hooks/__init__.py
"""Hook dispatcher (contract C4): handlers are pure functions with a declared policy."""
```

```python
# src/keelline/hooks/api.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class Policy(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class HookEvent:
    name: str
    session_id: str | None
    agent_id: str | None
    tool_name: str | None
    tool_input: dict[str, Any]
    cwd: Path
    project_root: Path | None
    harness: str
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass
class HookResult:
    context: str | None = None
    decision: str | None = None
    reason: str | None = None


HandlerFn = Callable[[HookEvent, Any], HookResult]


@dataclass(frozen=True)
class Handler:
    name: str
    event: str
    policy: Policy
    run: HandlerFn


class Sink(Protocol):
    """Where the dispatcher records failures and once-per-context markers (§5.3)."""

    def diagnostic(self, record: dict[str, object]) -> None: ...

    def seen(self, key: str) -> bool: ...

    def mark(self, key: str) -> None: ...


class NullSink:
    def diagnostic(self, record: dict[str, object]) -> None:
        return None

    def seen(self, key: str) -> bool:
        return False

    def mark(self, key: str) -> None:
        return None
```

```python
# src/keelline/hooks/registry.py
"""Every `keelline.<area>.hooks.register()` result, by name, with no shared list to edit."""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil

import keelline
from keelline.hooks.api import Handler


def discover() -> list[Handler]:
    handlers: list[Handler] = []
    for module in sorted(pkgutil.iter_modules(keelline.__path__), key=lambda m: m.name):
        if not module.ispkg:
            continue
        spec = importlib.util.find_spec(f"keelline.{module.name}.hooks")
        if spec is None:
            continue
        handlers.extend(importlib.import_module(spec.name).register())
    return handlers
```

```python
# src/keelline/hooks/dispatch.py
"""Run the handlers registered for an event and own the exit code and output shape."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from keelline.hooks.api import Handler, HookEvent, NullSink, Policy, Sink

TRUNCATION_MARK = "\n[keelline: context truncated to the platform cap]"


@dataclass(frozen=True)
class Outcome:
    exit_code: int
    stdout: str
    stderr: str
    decision: str | None = None


@dataclass
class Recorder:
    """A sink that keeps records in memory; tests and `doctor --dry-run` use it."""

    records: list[dict[str, object]] = field(default_factory=list)
    marks: set[str] = field(default_factory=set)

    def diagnostic(self, record: dict[str, object]) -> None:
        self.records.append(record)

    def seen(self, key: str) -> bool:
        return key in self.marks

    def mark(self, key: str) -> None:
        self.marks.add(key)


def detect_harness(env: Mapping[str, str], payload: Mapping[str, Any] | None = None) -> str:
    # S1 (spike record): Codex sets PLUGIN_ROOT/PLUGIN_DATA and ALSO CLAUDE_PLUGIN_ROOT, so
    # the CLAUDE_* names alone identify nothing; Codex's SessionStart stdin also carries
    # `model` and `permission_mode`, which Claude Code's does not.
    if "PLUGIN_ROOT" in env:
        return "codex"
    if payload is not None and {"model", "permission_mode"} <= set(payload):
        return "codex"
    if "CLAUDE_PLUGIN_ROOT" in env or "CLAUDE_PROJECT_DIR" in env:
        return "claude"
    return "unknown"


def _git_toplevel(cwd: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    top = completed.stdout.strip()
    return Path(top) if completed.returncode == 0 and top else None


def parse_event(payload: dict[str, Any], env: Mapping[str, str]) -> HookEvent:
    cwd = Path(str(payload.get("cwd") or "."))
    root_var = env.get("CLAUDE_PROJECT_DIR")
    project_root = Path(root_var) if root_var else _git_toplevel(cwd)
    tool_input = payload.get("tool_input") or {}
    return HookEvent(
        name=str(payload.get("hook_event_name") or "unknown"),
        session_id=payload.get("session_id"),
        agent_id=payload.get("agent_id"),
        tool_name=payload.get("tool_name"),
        tool_input=tool_input if isinstance(tool_input, dict) else {},
        cwd=cwd,
        project_root=project_root,
        harness=detect_harness(env, payload),
        raw=payload,
    )


def dispatch(
    event: HookEvent,
    handlers: list[Handler],
    config: Any,
    *,
    sink: Sink | None = None,
    cap: int | None = None,
) -> Outcome:
    sink = sink or NullSink()
    contexts: list[str] = []
    reasons: list[str] = []
    refuse = False
    for handler in handlers:
        if handler.event != event.name:
            continue
        try:
            result = handler.run(event, config)
        except Exception as exc:  # a handler's failure is judged by its own policy
            reasons.append(f"{handler.name}: {type(exc).__name__}: {exc}")
            sink.diagnostic(
                {"event": event.name, "handler": handler.name, "error": type(exc).__name__}
            )
            refuse = refuse or handler.policy is Policy.CLOSED
            continue
        if result.context:
            contexts.append(result.context)
        if result.decision == "deny":
            reasons.append(f"{handler.name}: {result.reason or 'denied'}")
            refuse = True
    if refuse:
        return Outcome(2, "", "keelline: refused: " + "; ".join(reasons) + "\n", "deny")
    stderr = ("keelline: " + "; ".join(reasons) + "\n") if reasons else ""
    context = "\n\n".join(contexts)
    if cap is not None and len(context) > cap:
        context = context[: max(cap - len(TRUNCATION_MARK), 0)] + TRUNCATION_MARK
        context = context[:cap]
        sink.diagnostic({"event": event.name, "handler": "*", "error": "context-truncated"})
    payload: dict[str, Any] = {"hookSpecificOutput": {"hookEventName": event.name}}
    if context:
        payload["hookSpecificOutput"]["additionalContext"] = context
    return Outcome(0, json.dumps(payload), stderr, None)
```

```python
# src/keelline/hooks/commands.py
"""`keelline hook <event>`: stdin in, JSON out, the exit code owned here and event-aware."""

from __future__ import annotations

import argparse
import json
import os
import sys

from keelline.cli import SubParsers
from keelline.config.loader import CONFIG_FILE, load
from keelline.hooks.dispatch import dispatch, parse_event
from keelline.hooks.registry import discover

# The only event on which the platform blocks on exit 2 (§5.3); an internal error there
# refuses, everywhere else it degrades open and says so on stderr.
BLOCKING_EVENTS = frozenset({"PreToolUse"})


def run_hook(args: argparse.Namespace) -> int:
    event_name = str(args.event)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("hook payload is not a JSON object")
        payload.setdefault("hook_event_name", event_name)
        event = parse_event(payload, env=os.environ)
        config = None
        root = event.project_root
        if root is not None and (root / CONFIG_FILE).is_file():
            config = load(root)
        cap = config.native_caps.hook_output_chars if config is not None else None
        outcome = dispatch(event, discover(), config, cap=cap)
    except Exception as exc:  # an internal error must never read as permission
        reason = f"keelline: internal error: {type(exc).__name__}: {exc}"
        if event_name in BLOCKING_EVENTS:
            sys.stderr.write(f"{reason}; refused\n")
            return 2
        sys.stderr.write(f"{reason}; continuing open\n")
        return 0
    if outcome.stdout:
        sys.stdout.write(outcome.stdout)
    if outcome.stderr:
        sys.stderr.write(outcome.stderr)
    return outcome.exit_code


def register(groups: SubParsers) -> None:
    group = groups.add_parser("hook", help="dispatch one harness hook event (internal)")
    group.add_argument("event", help="hook event name, e.g. SessionStart")
    group.set_defaults(func=run_hook)
```

- [ ] **Step 5: Run the tests to watch them pass, then prove the policy rule and the guard discriminate**

Run: `uv run pytest tests/hooks -v`
Expected: 13 passed. Change `refuse = refuse or handler.policy is Policy.CLOSED` to `refuse = True` and rerun; Expected: `test_an_open_handler_that_raises_is_swallowed_and_recorded` and `test_policy_is_taken_from_handlers_that_failed_not_from_all_registered` redden; restore. Change `BLOCKING_EVENTS` to an empty set and rerun; Expected: both `PreToolUse` command tests redden; restore. If any reddens for another reason the assertion needs redesigning. Then the gates: `uv run ruff check . && uv run ruff format --check . && uv run mypy`.

- [ ] **Step 6: Commit**

```bash
git add src/keelline/hooks tests/hooks
git commit -q -m "feat(hooks): the dispatcher interface, per-handler policy, sinks, and keelline hook"
```

---

### Task 8: Version discipline (C6) — `keelline release check`

**Files:**
- Create: `src/keelline/release/__init__.py`
- Create: `src/keelline/release/commands.py`
- Create: `src/keelline/release/versions.py`
- Test: `tests/release/__init__.py`
- Test: `tests/release/test_versions.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `keelline.release.versions.collect(root: Path) -> dict[str, str | None]` reading `pyproject.toml`, the package `__version__`, both plugin manifests and the top released changelog heading; `keelline.release.versions.check(root: Path) -> list[str]` returning mismatches and any marketplace entry carrying a `version`; the CLI command `keelline release check [--root PATH]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/release/test_versions.py
from __future__ import annotations

import json
from pathlib import Path

from keelline.release.versions import check, collect

PYPROJECT = '[project]\nname = "keelline"\nversion = "{v}"\n'
INIT = '__version__ = "{v}"\n'
MARKETPLACE = {"name": "keelline-marketplace", "plugins": [{"name": "keelline", "source": "./"}]}


def repo(
    tmp_path: Path,
    *,
    pyproject: str,
    init: str,
    claude: str,
    codex: str,
    changelog: str,
    fragments: int = 0,
    marketplace: dict[str, object] | None = None,
) -> Path:
    (tmp_path / "src" / "keelline").mkdir(parents=True)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".codex-plugin").mkdir()
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "pyproject.toml").write_text(PYPROJECT.format(v=pyproject))
    (tmp_path / "src" / "keelline" / "__init__.py").write_text(INIT.format(v=init))
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "keelline", "version": claude})
    )
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(marketplace or MARKETPLACE)
    )
    (tmp_path / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "keelline", "version": codex})
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n<!-- towncrier release notes start -->\n\n"
        f"## {changelog} (2026-09-05)\n"
    )
    for index in range(fragments):
        (tmp_path / "changelog.d" / f"{index}.feature.md").write_text("x\n")
    return tmp_path


def test_all_equal_is_clean(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="0.1.0", init="0.1.0", claude="0.1.0", codex="0.1.0", changelog="0.1.0"
    )
    assert check(root) == []


def test_each_mismatch_is_named(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="0.1.0", init="0.1.0", claude="0.1.1", codex="0.1.0", changelog="0.1.0"
    )
    problems = check(root)
    assert len(problems) == 1
    assert ".claude-plugin/plugin.json" in problems[0]
    assert "0.1.1" in problems[0]


def test_pending_fragments_allow_the_changelog_to_lag(tmp_path: Path) -> None:
    root = repo(
        tmp_path,
        pyproject="0.2.0",
        init="0.2.0",
        claude="0.2.0",
        codex="0.2.0",
        changelog="0.1.0",
        fragments=1,
    )
    assert check(root) == []


def test_without_fragments_the_changelog_must_match(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="0.2.0", init="0.2.0", claude="0.2.0", codex="0.2.0", changelog="0.1.0"
    )
    assert any("CHANGELOG.md" in problem for problem in check(root))


def test_a_versioned_marketplace_entry_is_refused(tmp_path: Path) -> None:
    versioned: dict[str, object] = {
        "name": "m",
        "plugins": [{"name": "keelline", "source": "./", "version": "0.1.0"}],
    }
    root = repo(
        tmp_path,
        pyproject="0.1.0",
        init="0.1.0",
        claude="0.1.0",
        codex="0.1.0",
        changelog="0.1.0",
        marketplace=versioned,
    )
    assert any("marketplace" in problem for problem in check(root))


def test_collect_reads_every_source_value(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="1.0.0", init="1.0.1", claude="1.0.2", codex="1.0.3", changelog="1.0.4"
    )
    assert collect(root) == {
        "pyproject.toml": "1.0.0",
        "src/keelline/__init__.py": "1.0.1",
        ".claude-plugin/plugin.json": "1.0.2",
        ".codex-plugin/plugin.json": "1.0.3",
        "CHANGELOG.md": "1.0.4",
    }


def test_a_missing_version_key_reads_as_none(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="1.0.0", init="1.0.0", claude="1.0.0", codex="1.0.0", changelog="1.0.0"
    )
    (root / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "keelline"}))
    assert collect(root)[".codex-plugin/plugin.json"] is None
```

`tests/release/__init__.py` is an empty file. The changelog fixture carries an `## Unreleased` heading above the towncrier marker on purpose: the reader must take the first heading **below** the marker.

- [ ] **Step 2: Run them to watch them fail**

Run: `uv run pytest tests/release -v`
Expected: `ModuleNotFoundError: No module named 'keelline.release'`.

- [ ] **Step 3: Write the version reader and the command**

```python
# src/keelline/release/__init__.py
"""Release discipline (contract C6): one version string, checked before it ships."""
```

```python
# src/keelline/release/versions.py
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

SOURCES = (
    "pyproject.toml",
    "src/keelline/__init__.py",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "CHANGELOG.md",
)
MARKETPLACE = ".claude-plugin/marketplace.json"
START = "<!-- towncrier release notes start -->"
_INIT = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
_HEADING = re.compile(r"^## (\S+)", re.MULTILINE)


def _read(root: Path, name: str) -> str | None:
    path = root / name
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if name == "pyproject.toml":
        version = tomllib.loads(text).get("project", {}).get("version")
        return str(version) if version is not None else None
    if name.endswith("__init__.py"):
        match = _INIT.search(text)
        return match.group(1) if match else None
    if name.endswith(".json"):
        version = json.loads(text).get("version")
        return str(version) if version is not None else None
    released = text.split(START, 1)[1] if START in text else text
    match = _HEADING.search(released)
    return match.group(1) if match else None


def collect(root: Path) -> dict[str, str | None]:
    return {name: _read(root, name) for name in SOURCES}


def pending_fragments(root: Path) -> bool:
    directory = root / "changelog.d"
    return directory.is_dir() and any(p.name != ".gitkeep" for p in directory.iterdir())


def check(root: Path) -> list[str]:
    found = collect(root)
    canonical = found["pyproject.toml"]
    if canonical is None:
        return ["pyproject.toml has no [project].version"]
    problems: list[str] = []
    for name, value in found.items():
        if name == "CHANGELOG.md" and pending_fragments(root):
            continue
        if value != canonical:
            problems.append(f"{name} says {value!r}; pyproject.toml says {canonical!r}")
    marketplace = root / MARKETPLACE
    if marketplace.is_file():
        entries = json.loads(marketplace.read_text(encoding="utf-8")).get("plugins", [])
        for entry in entries:
            if "version" in entry:
                problems.append(
                    f"{MARKETPLACE} entry {entry.get('name')!r} carries a version; "
                    "plugin.json is the only source (D12)"
                )
    return problems
```

```python
# src/keelline/release/commands.py
from __future__ import annotations

import argparse
from pathlib import Path

from keelline.cli import SubParsers
from keelline.errors import Failure
from keelline.release.versions import check, collect
from keelline.result import Result


def run_check(args: argparse.Namespace) -> Result:
    root = Path(args.root)
    problems = check(root)
    if problems:
        raise Failure("version drift: " + "; ".join(problems))
    versions = collect(root)
    return Result(f"one version everywhere: {versions['pyproject.toml']}", {"versions": versions})


def register(groups: SubParsers) -> None:
    group = groups.add_parser("release", help="release discipline for the Keelline repository")
    sub = group.add_subparsers(dest="command", metavar="<command>")
    cmd = sub.add_parser("check", help="every version string agrees")
    cmd.add_argument("--root", default=".", help="repository root (default: current directory)")
    cmd.set_defaults(func=run_check)
```

- [ ] **Step 4: Remove the xfail marker and run every test, then prove the changelog rule discriminates**

Delete the `@pytest.mark.xfail(...)` line above `test_areas_are_discovered_from_the_package` in `tests/test_cli.py`. Run: `uv run pytest -v`
Expected: all pass. Delete the `pending_fragments` `continue` branch and rerun; Expected: `test_pending_fragments_allow_the_changelog_to_lag` reddens; restore. Make `_read` return `None` unconditionally; Expected: `test_collect_reads_every_source_value` reddens on the first value; restore. Then the gates.

- [ ] **Step 5: Commit**

```bash
git add src/keelline/release tests/release tests/test_cli.py
git commit -q -m "guard(release): one version string across package, manifests and changelog"
```

---

### Task 9: Plugin manifests and the launcher

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.claude-plugin/marketplace.json`
- Create: `.codex-plugin/plugin.json`
- Create: `scripts/keelline`
- Create: `skills/.gitkeep`
- Modify: `pyproject.toml` (add `scripts/keelline` to `[tool.mypy] files`)
- Test: `tests/test_manifests.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Produces: the installable plugin; `scripts/keelline` runs the package from the plugin root without an installed wheel, refusing interpreters below 3.11 with a reason. Hooks invoke it as `"${CLAUDE_PLUGIN_ROOT}/scripts/keelline"` through the wrapper; skills never do (§5.1).

- [ ] **Step 1: Write the failing manifest tests**

```python
# tests/test_manifests.py
from __future__ import annotations

import json
from pathlib import Path

from keelline import __version__
from keelline.release.versions import check

ROOT = Path(__file__).resolve().parents[1]


def test_claude_manifest_names_the_plugin_its_version_and_titled_user_config() -> None:
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "keelline"
    assert manifest["version"] == __version__
    for key, entry in manifest["userConfig"].items():
        assert entry["title"], key
        assert entry["description"], key


def test_marketplace_has_a_description_and_an_unversioned_entry() -> None:
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert marketplace["name"] == "keelline-marketplace"
    assert marketplace["description"]
    (entry,) = marketplace["plugins"]
    assert entry["name"] == "keelline"
    assert entry["source"] == "./"
    assert "version" not in entry


def test_codex_manifest_carries_no_hooks_or_skills_key() -> None:
    # `claude plugin validate` refuses `../skills/` as a path traversal attempt and reports
    # `./skills/` as not found, because the value resolves relative to `.codex-plugin/`, so no
    # value reaches the root-level `skills/`. Foundation ships no `skills` key at all; the Codex
    # skills-path convention belongs to the skills lanes, once Codex itself has been measured.
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "keelline"
    assert "hooks" not in manifest
    assert "skills" not in manifest


def test_the_repository_itself_passes_release_check() -> None:
    assert check(ROOT) == []


def test_no_top_level_bin_directory() -> None:
    assert not (ROOT / "bin").exists()
```

```python
# tests/test_launcher.py
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from keelline import __version__

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "keelline"


def test_the_launcher_runs_from_the_plugin_root() -> None:
    # `-S` suppresses `site`, and with it the project venv's `keelline.pth`, which would
    # otherwise put the source tree on `sys.path` for any invocation of this interpreter and
    # let this test pass even with the launcher's own `sys.path.insert` deleted. Under `-S`
    # the launcher's insertion is the only thing that can work — and the run exercises the
    # package with no site-packages at all, which is the stdlib-only constraint in action.
    completed = subprocess.run(
        [sys.executable, "-S", str(LAUNCHER), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert __version__ in completed.stdout


def test_the_floor_check_precedes_every_keelline_import() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert text.index("sys.version_info < (3, 11)") < text.index("from keelline")


def _old_python() -> str | None:
    for candidate in ("python3.9", "python3.10", "/usr/bin/python3"):
        path = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if not path:
            continue
        probe = subprocess.run(
            [path, "-c", "import sys; print(sys.version_info < (3, 11))"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.stdout.strip() == "True":
            return path
    return None


def test_an_old_interpreter_is_refused_with_a_reason() -> None:
    old = _old_python()
    if old is None:
        pytest.skip("no interpreter below 3.11 on this machine")
    completed = subprocess.run(
        [old, str(LAUNCHER), "--version"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 2
    assert "3.11 or newer" in completed.stderr
```

- [ ] **Step 2: Run them to watch them fail**

Run: `uv run pytest tests/test_manifests.py tests/test_launcher.py -v`
Expected: the manifest tests fail with `FileNotFoundError` on the Claude manifest (4 failed, 1 passed — the `bin/` test passes) and the launcher tests fail with `FileNotFoundError` on the launcher.

- [ ] **Step 3: Write the manifests and the launcher**

`.claude-plugin/plugin.json`:

```json
{
  "name": "keelline",
  "version": "0.1.0",
  "description": "A methodology harness for coding agents: bug ledger, curated working memory, guards, and an adoption state machine.",
  "author": { "name": "Nezhinskiy" },
  "repository": "https://github.com/Nezhinskiy/keelline",
  "license": "MIT",
  "keywords": ["methodology", "bug-ledger", "memory", "hooks", "guards", "codex"],
  "userConfig": {
    "reply_language": {
      "type": "string",
      "title": "Reply language",
      "description": "Language for chat replies; durable artifacts stay in the artifact language.",
      "default": ""
    },
    "artifact_language": {
      "type": "string",
      "title": "Artifact language",
      "description": "Language for documents, comments, commits and pull requests.",
      "default": "en"
    },
    "preset": {
      "type": "string",
      "title": "Preset",
      "description": "Preset applied by setup and init.",
      "default": "recommended"
    }
  }
}
```

`.claude-plugin/marketplace.json`:

```json
{
  "name": "keelline-marketplace",
  "description": "Keelline, a methodology harness for coding agents, published from its own repository.",
  "owner": { "name": "Nezhinskiy" },
  "plugins": [
    {
      "name": "keelline",
      "source": "./",
      "description": "A methodology harness for coding agents: bug ledger, curated working memory, guards, and an adoption state machine."
    }
  ]
}
```

`.codex-plugin/plugin.json`:

```json
{
  "name": "keelline",
  "version": "0.1.0",
  "description": "A methodology harness for coding agents: bug ledger, curated working memory, guards, and an adoption state machine.",
  "author": { "name": "Nezhinskiy" },
  "repository": "https://github.com/Nezhinskiy/keelline",
  "license": "MIT",
  "interface": {
    "displayName": "Keelline",
    "shortDescription": "Bug ledger, working memory, guards, and earned enforcement for coding agents",
    "developerName": "Nezhinskiy",
    "category": "Developer Tools"
  }
}
```

Create `skills/.gitkeep`, then the launcher:

```python
#!/usr/bin/env python3
"""Run Keelline from the plugin root, with no installed wheel required."""

import pathlib
import sys

if sys.version_info < (3, 11):  # noqa: UP036 - this check exists for older interpreters
    sys.stderr.write(
        "keelline: refused: python 3.11 or newer is required, found "
        f"{sys.version.split()[0]} at {sys.executable}\n"
    )
    sys.exit(2)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from keelline.cli import main  # noqa: E402

raise SystemExit(main())
```

Save that as `scripts/keelline` and `chmod +x scripts/keelline`, then extend `[tool.mypy]
files` in `pyproject.toml` to `["src", "tests", "scripts/keelline"]`, which Task 1 left short
because mypy refuses a path in `files` that does not exist yet.

- [ ] **Step 4: Run the tests, then the validator invocations S4 recorded**

Run: `uv run pytest tests/test_manifests.py tests/test_launcher.py -v`
Expected: every test passes (the old-interpreter test skips on a machine without one). Then the three validator invocations S4 showed to discriminate — the plugin-manifest path cascades into skills and agents, the marketplace path checks only itself, and the Codex manifest is reached only by its own path, where `--strict` is omitted because Claude Code's validator warns on Codex's `interface` field it does not know:

```bash
claude plugin validate .claude-plugin/plugin.json --strict; echo "rc=$?"
claude plugin validate .claude-plugin/marketplace.json --strict; echo "rc=$?"
claude plugin validate .codex-plugin/plugin.json; echo "rc=$?"
```

Expected: `rc=0` three times, the third with one warning about the unknown `interface` field. S4 measured that `"skills": "./skills/"` fails the third invocation with `Path not found`, because the value resolves relative to `.codex-plugin/`, and inferred `"../skills/"` as the remedy without re-running the validator against it — the spike record says so itself. Measured 2026-09-06 against `claude` 2.1.261: `../skills/` is refused as a path traversal attempt in both the string and the array form, `skills/` is refused too, and only omitting the key (or an empty list) validates. No value reaches the root-level `skills/` from inside `.codex-plugin/`, which is why the manifest above carries no `skills` key. A non-zero exit, or any warning on the first two, is a finding to fix in the manifest here, not to suppress. Then the gates: `uv run ruff check . && uv run ruff format --check . && uv run mypy`.

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin .codex-plugin scripts skills pyproject.toml \
  tests/test_manifests.py tests/test_launcher.py
git commit -q -m "feat: plugin manifests for Claude Code and Codex, and a floor-checked launcher"
```

---

### Task 10: Continuous integration for the Keelline repository

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: the check every lane's pull request runs on every supported interpreter; the `workflows` lane adds the reusable `check.yml` beside it later.

- [ ] **Step 1: Write the workflow**

Pins are commit SHAs resolved on 2026-09-05 (`gh api repos/<repo>/git/ref/tags/<tag>`): `actions/checkout` v7, `astral-sh/setup-uv` v10.0.1, `actions/setup-node` v6. Re-resolve before the first push and update both the SHA and the comment together.

```yaml
# .github/workflows/ci.yml
name: ci

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  checks:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
      - uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1
        with:
          enable-cache: true
          python-version: ${{ matrix.python }}
      - name: Install
        run: uv sync --locked
      - name: Lint and format
        run: |
          uv run ruff check .
          uv run ruff format --check .
      - name: Types
        run: uv run mypy
      - name: Tests
        run: uv run pytest -q
      - name: Version discipline
        run: uv run keelline release check
      - name: Build
        run: uv build

  plugin:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
      - uses: actions/setup-node@249970729cb0ef3589644e2896645e5dc5ba9c38 # v6
        with:
          node-version: "22"
      - name: Install Claude Code for the plugin validator
        run: npm install -g @anthropic-ai/claude-code@2.1.261
      - name: Validate each manifest path
        run: |
          claude plugin validate .claude-plugin/plugin.json --strict
          claude plugin validate .claude-plugin/marketplace.json --strict
          claude plugin validate .codex-plugin/plugin.json
```

`claude plugin tag` is not run here: it creates `keelline--v<version>` and its dry run depends on which tags the checkout fetched, so it belongs to the release lane's explicit release step (§5.9).

- [ ] **Step 2: Run the same steps locally on every interpreter before pushing**

```bash
uv lock
for py in 3.11 3.12 3.13; do
  uv sync --locked --python "$py" && uv run --python "$py" pytest -q || exit 1
done
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run keelline release check && uv build
```

Expected: every command exits 0 and `dist/` holds a wheel and an sdist. `uv sync --python 3.11` installs the interpreter into uv's managed cache if it is absent; that cache is outside the repository and is not a write this plan tracks. Commit `uv.lock` with the workflow.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml uv.lock
git commit -q -m "chore(ci): lint, types, tests on 3.11-3.13, version discipline, manifest validation"
```

---

### Task 11: The plans directory, the copied P0 documents, and the installability check

**Files:**
- Create: `docs/plans/README.md`
- Create: `docs/plans/2026-09-05-agent-harness-p0-spikes.md`
- Create: `docs/plans/2026-09-05-agent-harness-foundation.md`

**Interfaces:**
- Produces: the plan location every later lane writes to (`docs/plans/<date>-<slug>.md`), and the proof that the plugin installs from the checkout. The two P0 documents are **copied**: the source project keeps its copies as the historical record its design trail registers, and the Keelline copies are authoritative from this commit on.

- [ ] **Step 1: Copy the two P0 documents from the source project's branch and write the plans index**

```bash
mkdir -p docs/plans
SRC="${SOURCE_CHECKOUT:?the source project's checkout}"
REF=$(git -C "$SRC" rev-parse --verify --quiet "${SOURCE_BRANCH:?the source project's branch this plan executes on}" \
  || git -C "$SRC" rev-parse --verify --quiet "${SOURCE_DESIGN_BRANCH:?the source project's branch the extraction design sits on}" \
  || echo origin/dev)
for name in 2026-09-05-agent-harness-p0-spikes 2026-09-05-agent-harness-foundation; do
  git -C "$SRC" show "$REF:<the source's plans directory>/$name.md" > "docs/plans/$name.md"
done
cat > docs/plans/README.md <<'EOF'
# Plans

One implementation plan per work package, `YYYY-MM-DD-<slug>.md`, written against the
frozen extraction design. That design document is not public: it lives in a private
repository, and a plan's references to it cannot be followed from this repository. A
plan's `Scope:` line names the package it belongs to and the contracts it consumes and
produces. The two P0 documents here were copied from that repository, which keeps its
own copies as history.
EOF
if grep -nE '/[U]sers/[a-z]|/[h]ome/[a-z]|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' docs/plans/*.md \
     | grep -vE 'git@github\.com'; then
  echo "LEAK: the lines above must be rewritten before this is published" >&2; exit 1
fi
echo "the copied documents carry no home path and no personal address"
```

The branch is read at run time because the source project's branch may already have merged into `dev`; the executing branch is preferred over the one the extraction design sits on, so that amendments made while this plan runs travel with the copy. `SRC` and both branches are written as parameter expansions rather than as literals because this plan is itself one of the copied documents: a literal home directory here publishes the owner's account name, and a literal branch name publishes a private repository's refs. The last line scrubs **both** copied documents, not only the spike record: the earlier form greped the spike plan alone, and the one home path in the tree sat in this document, where nothing looked for it. It is anchored on the *shape* of a leak — a home directory with a user under it, or an address — rather than on the owner's login, because the login appears legitimately in a repository URL, in the licence and in both manifests: an earlier form matched six such lines and zero leaks, which left its "clean" branch unreachable and the check unable to say anything. `[U]sers` and `[h]ome` are bracketed so the pattern does not match its own text, and `git@github.com` is filtered because an SSH remote is not an address. The `if` carries the verdict: in the pipeline form this step first used, the exit status was the trailing `grep -v`'s, which is **0 when it printed leak lines** and 0 again through the `echo` when it printed none — measured with a planted `/Users/someone/Dev/…` line, the leak was printed and the pipeline exited 0. Step 4's consent question calls these documents "scrubbed … in Step 1", so an executor reading exit codes would have pushed the leak to a public repository. (Every raw match in today's text is a `git@github.com` line.)

- [ ] **Step 2: Install the plugin from the checkout into a temporary configuration**

```bash
CFG=$(mktemp -d)
CLAUDE_CONFIG_DIR="$CFG" claude plugin marketplace add ~/Dev/keelline
CLAUDE_CONFIG_DIR="$CFG" claude plugin install keelline@keelline-marketplace
CLAUDE_CONFIG_DIR="$CFG" claude plugin list | grep -A3 keelline
grep -o '"installLocation": "[^"]*"' "$CFG/plugins/known_marketplaces.json"
~/Dev/keelline/scripts/keelline --version   # the launcher probes the interpreter; §5.3
rm -rf "$CFG"
```

Expected: the list shows `keelline` enabled, `installLocation` names the checkout, and the launcher prints `keelline 0.1.0`. S2 measured that `${CLAUDE_PLUGIN_ROOT}` resolves to that `installLocation` for a directory-sourced marketplace, so the file hooks and skills will run is the checkout's own launcher, which this step exercises directly. If the install refuses, Task 9's validator step names the manifest fix; apply it and rerun.

- [ ] **Step 3: Run the full local check once more and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q && uv run keelline release check
git add docs/plans && git commit -q -m "docs: plans index and the copied P0 documents"
```

- [ ] **Step 4: Ask, then create the GitHub repository and push**

Ask in chat: "Create the public repository `Nezhinskiy/keelline` now and push `main`? The push publishes the copied spike record, scrubbed of home paths and logins in Step 1." Only after a yes:

```bash
gh repo view Nezhinskiy/keelline >/dev/null 2>&1 \
  || gh repo create Nezhinskiy/keelline --public --description "A methodology harness for coding agents"
git remote get-url origin >/dev/null 2>&1 || git remote add origin git@github.com:Nezhinskiy/keelline.git
git push -u origin main
gh run watch --exit-status "$(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId')"
```

The repository creation is re-run-safe: an existing repository is reused. The first green CI run on `main`, together with Step 2 and Task 9's validator invocations, is the foundation package's exit criterion (§15.1): the plugin installs from the checkout, every manifest validates under `--strict`, and Keelline's CI passes on every supported interpreter.
