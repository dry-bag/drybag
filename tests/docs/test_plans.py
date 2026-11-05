"""Contracts for the plan lint: references resolve, steps are non-leading, mutation outcomes are
expectations, Scope/Premise are present. stayfixed:ledger:fixtures — `BR-` strings here are
sample data.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from stayfixed.config.loader import load
from stayfixed.config.schema import Config
from stayfixed.docs.plans import (
    BaseUnresolvable,
    asserted_outcomes,
    lint,
    touched_plans,
)
from stayfixed.errors import Failure, Refusal
from stayfixed.gitenv import DISJOINT, NO_ANSWER, git_run
from tests.cli import cli
from tests.crafted import CRAFTED, assert_never_raw
from tests.gitfixture import answer_shallow_check, criss_cross, dated, git, plant_path

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
"""
SCOPE = "**Scope:** a change belongs to this branch iff it touches the widget.\n\n"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def project(tmp_path: Path) -> tuple[Path, Config]:
    root = tmp_path / "widget"
    (root / "docs" / "plans").mkdir(parents=True)
    (root / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    return root, load(root, machine=tmp_path / "m.toml")


def plan(root: Path, body: str, name: str = "2026-01-01-x.md") -> Path:
    path = root / "docs" / "plans" / name
    path.write_text(body, encoding="utf-8")
    return path


def rules(root: Path, config: Config, *paths: Path) -> list[str]:
    return [f.rule for f in lint(root, config, plans=list(paths)).findings]


def test_an_unresolvable_reference_fails_and_a_resolvable_or_created_one_passes(
    tmp_path: Path,
) -> None:
    root, config = project(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "ok.py").write_text("", encoding="utf-8")
    path = plan(
        root,
        SCOPE + "- Modify: `src/gone.py`\n- Modify: `src/ok.py`\n- Create: `src/new.py`\n"
        "later `src/new.py` (create)\n",
    )
    found = lint(root, config, plans=[path]).findings
    assert [(f.rule, f.line, f.detail) for f in found] == [("dead-reference", 3, "src/gone.py")]


def test_a_dependency_named_by_its_host_is_not_a_dead_reference(tmp_path: Path) -> None:
    # Go's import spelling in a plan line failed the gate as a missing file of this repository.
    # The path beside it on the same line is still checked. Oracle: `mutations/`'s "a
    # host-shaped first component is read as a directory".
    root, config = project(tmp_path)
    path = plan(root, SCOPE + "Use `gopkg.in/yaml.v3` to parse `internal/config/load.go`.\n")
    found = lint(root, config, plans=[path]).findings
    assert [(f.rule, f.line, f.detail) for f in found] == [
        ("dead-reference", 3, "internal/config/load.go")
    ]


def test_a_reference_the_filesystem_cannot_name_is_not_found_rather_than_a_crash(
    tmp_path: Path,
) -> None:
    # A 5,000-character backticked path made `exists()` raise `ENAMETOOLONG` on Python 3.11 to
    # 3.13, which crashed the lint on the author's own plan instead of reporting the claim, and
    # answered `False` on 3.14. `fsops.exists` answers it on every interpreter, unforced. No entry
    # of its own: `mutations/`'s "the path predicates read a name longer than the system takes as
    # a fault" moves the answer to the arm below it, which answers the same.
    root, config = project(tmp_path)
    long = "src/" + "a" * 5000 + ".py"
    path = plan(root, SCOPE + f"- Modify: `{long}`\n")
    found = lint(root, config, plans=[path]).findings
    assert [(f.rule, f.line, f.detail) for f in found] == [("dead-reference", 3, long)]


def test_a_reference_below_a_directory_that_cannot_be_searched_is_not_found_rather_than_a_crash(
    tmp_path: Path,
) -> None:
    # What the existence query still raises -- a fault that leaves the question open -- is the
    # reference checks' to answer, and they answer it as a claim not found rather than a crash.
    # Oracle: `mutations/`'s "a path the filesystem cannot answer for crashes the reference checks".
    if os.geteuid() == 0:
        pytest.skip("root searches every directory")
    root, config = project(tmp_path)
    (root / "src" / "locked" / "child").mkdir(parents=True)
    path = plan(root, SCOPE + "- Modify: `src/locked/child/x.py`\n")
    (root / "src" / "locked").chmod(0o600)
    try:
        found = lint(root, config, plans=[path]).findings
    finally:
        (root / "src" / "locked").chmod(0o700)
    assert [(f.rule, f.line, f.detail) for f in found] == [
        ("dead-reference", 3, "src/locked/child/x.py")
    ]


def test_a_reference_through_a_symlink_out_of_the_tree_is_not_asked_of_the_filesystem(
    tmp_path: Path,
) -> None:
    # `resolves_within` is lexical, and `exists()` follows symlinks: a committed `docs/l -> /`
    # made the lint a one-bit existence oracle for any path on the machine, a present file
    # passing and an absent one reported. A claim whose real path leaves the root is now not
    # settled at all, as one whose spelling leaves it is not. A symlink that stays inside the
    # tree is still followed. Oracle: `mutations/`'s "the plan lint follows a symlink out of
    # the tree", "a path claim is followed through a symlink out of the tree".
    root, config = project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("", encoding="utf-8")
    (root / "docs" / "l").symlink_to(outside)
    (root / "src").mkdir()
    (root / "src" / "ok.py").write_text("", encoding="utf-8")
    (root / "docs" / "alias").symlink_to(Path("..") / "src")
    path = plan(
        root,
        SCOPE + "- `docs/l/secret.md`\n- `docs/l/absent.md`\n"
        "- `docs/alias/ok.py`\n- `docs/alias/gone.py`\n",
    )
    found = lint(root, config, plans=[path]).findings
    assert [(f.rule, f.line, f.detail) for f in found] == [
        ("dead-reference", 6, "docs/alias/gone.py")
    ]


def test_a_path_the_plan_declares_deleted_is_not_a_dead_reference_once_it_is_gone(
    tmp_path: Path,
) -> None:
    # A plan lists the files its tasks remove under `- Delete:`, so once those tasks land every
    # mention of them read as dead, and any later change editing that finished plan failed the
    # diff-scoped `plan check`. A `Delete:` line declares its paths as `Create:` does, for the
    # whole plan, and `(delete)` exempts its own line as `(create)` does. The path named nowhere
    # as deleted still fails, so the rule did not stop reading references.
    root, config = project(tmp_path)
    path = plan(
        root,
        SCOPE + "- Delete: `src/old.py`, `tests/test_old.py`\n"
        "A later step removes `src/old.py` and its test.\n"
        "the module `src/retired.py` goes too (delete)\n"
        "- Modify: `src/gone.py`\n",
    )
    found = lint(root, config, plans=[path]).findings
    assert [(f.rule, f.line, f.detail) for f in found] == [("dead-reference", 6, "src/gone.py")]


def test_a_reference_inside_a_fence_is_fixture_text(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    path = plan(root, SCOPE + "```\n`src/gone.py`\n```\n")
    assert rules(root, config, path) == []


@pytest.mark.parametrize(
    "step",
    [
        "confirm that nothing bounds X",
        "verify nothing is logged",
        "check that no row exists",
        "Confirm it does not raise",
    ],
)
def test_a_leading_verification_step_fails(tmp_path: Path, step: str) -> None:
    root, config = project(tmp_path)
    assert rules(root, config, plan(root, SCOPE + f"- {step}\n")) == ["leading-step"]


def test_a_hyphenated_no_op_step_passes(tmp_path: Path) -> None:
    # `no(?!-)`: a hyphen is a word boundary, so plain `\bno\b` flags `no-op`. Mutation: drop
    # the lookahead — this reddens.
    root, config = project(tmp_path)
    assert rules(root, config, plan(root, SCOPE + "- verify no-op handling stays\n")) == []


def test_a_plan_without_a_scope_line_fails_and_a_bare_marker_does_not_count(
    tmp_path: Path,
) -> None:
    root, config = project(tmp_path)
    assert rules(root, config, plan(root, "no scope here\n")) == ["scope-missing"]
    assert rules(root, config, plan(root, "**Scope:**\n\nlater text\n")) == ["scope-missing"]
    assert rules(root, config, plan(root, "```\n**Scope:** in a fence\n```\n")) == ["scope-missing"]


def test_a_fixes_claim_needs_a_premise_line_with_content(tmp_path: Path) -> None:
    # The prefix comes from `[ledger] id_prefix`. Mutation: replace `[^\S\n]*\S` with `\s*\S`
    # in the premise rule — the bare-marker case reddens.
    root, config = project(tmp_path)
    assert rules(root, config, plan(root, SCOPE + "Fixes BR-042.\n")) == ["premise-missing"]
    assert rules(root, config, plan(root, SCOPE + "Fixes BR-042.\n\n**Premise:**\n\nlater\n")) == [
        "premise-missing"
    ]
    assert (
        rules(
            root, config, plan(root, SCOPE + "Fixes BR-042.\n\n**Premise (entry):** X says so.\n")
        )
        == []
    )
    assert rules(root, config, plan(root, SCOPE + "```\nFixes BR-042\n```\n")) == []


def test_a_fixes_claim_names_the_bug_ledgers_configured_prefix(tmp_path: Path) -> None:
    # The identifiers are the bug ledger's, as `[ledger] id_prefix` configures them. Mutation
    # (oracle): the rule reads the default prefix whatever the project configures -> the `DF`
    # claim needs no premise and the `BR` one does.
    root, config = project(tmp_path)
    config = replace(config, ledger=replace(config.ledger, id_prefix="DF"))
    assert rules(root, config, plan(root, SCOPE + "Fixes DF-042.\n")) == ["premise-missing"]
    assert rules(root, config, plan(root, SCOPE + "Fixes BR-042.\n")) == []


# Plans the rules read in time quadratic in their length, each with the rules it must end in:
# blank lines below the scope, which the declaring-line pattern read again from every one of them,
# 0.33 s over 16,000; and premise markers no colon follows, which the premise pattern read on from
# every marker to the end, 0.51 s over 16,000. Each is sized so that the old reading takes over
# two minutes and the lint a quarter of a second.
LONG_PLANS = {
    "blank lines": (SCOPE + "\n" * (1 << 19), []),
    "premise markers": (SCOPE + "Fixes BR-042.\n" + "**Premise\n" * (1 << 18), ["premise-missing"]),
}
# The child's bound: a fifteenth of the old reading's time over either plan on a laptop, and thirty
# times the lint's there, start-up included.
_LONG_PLAN_SECONDS = 10


@pytest.mark.parametrize("shape", sorted(LONG_PLANS))
def test_a_long_plan_is_linted_in_time_linear_in_its_length(tmp_path: Path, shape: str) -> None:
    # In a child under a timeout, so a regression fails this case rather than holding a worker.
    # Mutations (oracle): `mutations/`'s "a declaring line is read for from every blank line above
    # it" -> `blank lines`; "a premise marker is read on from every marker" -> `premise markers`.
    root, _ = project(tmp_path)
    body, expected = LONG_PLANS[shape]
    path = plan(root, body)
    probe = (
        "import sys\n"
        "from pathlib import Path\n"
        "from stayfixed.config.loader import load\n"
        "from stayfixed.docs.plans import lint\n"
        "root, machine, path = map(Path, sys.argv[1:])\n"
        "found = lint(root, load(root, machine=machine), plans=[path]).findings\n"
        "print([finding.rule for finding in found])\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, str(root), str(tmp_path / "m.toml"), str(path)],
            capture_output=True,
            text=True,
            timeout=_LONG_PLAN_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the plan lint ran past {_LONG_PLAN_SECONDS} s on one plan")
    assert done.stdout == f"{expected}\n", done.stderr


# Paragraphs of claims, one a line, which the asserted-outcome rule read again from the paragraph's
# start at every claim: for the last sentence end before it, 12.7 s over 16,000 claims each in a
# sentence of its own, and, where no sentence ends, for an expectation marker, 10.9 s over 16,000.
# Each is sized so that the old reading takes three minutes and the rule a tenth of a second; the
# answer is how many lines open a claim and the last of them.
LONG_CLAIMS = {
    "a sentence each": "It reddens 8.\n",
    "one sentence": "it reddens 8\n",
}
_LONG_CLAIM_COUNT = 1 << 16


@pytest.mark.parametrize("shape", sorted(LONG_CLAIMS))
def test_a_paragraph_of_claims_is_read_in_time_linear_in_its_length(shape: str) -> None:
    # In a child under the plan lint's timeout. Mutations (oracle): `mutations/`'s "a claim's
    # sentence is looked for from its paragraph's start" -> both cases; "an expectation marker is
    # looked for over the claim's whole sentence again" -> `one sentence`.
    probe = (
        "import sys\n"
        "from stayfixed.docs.plans import asserted_outcomes\n"
        "found = asserted_outcomes(sys.argv[1] * int(sys.argv[2]))\n"
        "print([len(found), found[-1]])\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe, LONG_CLAIMS[shape], str(_LONG_CLAIM_COUNT)],
            capture_output=True,
            text=True,
            timeout=_LONG_PLAN_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the asserted-outcome rule ran past {_LONG_PLAN_SECONDS} s on one paragraph")
    assert done.stdout == f"{[_LONG_CLAIM_COUNT, _LONG_CLAIM_COUNT]}\n", done.stderr


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Remove the guard -> the test reddens.", True),
        ("Watch the fail-closed test go red under that mutation.", True),
        ("Verify it stays green if the clone step is dropped.", True),
        ("The change reddens **8 assertions** in the module.", True),
        (
            "Expected: removing the guard -> the test reddens; if it reddens for another "
            "reason redesign it.",
            False,
        ),
        ("Removing the guard -> the test reddened, alone.", False),
        ("Run the test to verify it fails.", False),
        (
            "Data flows a -> b -> c, and very much later in this deliberately long and winding "
            "sentence the structural check must stay green.",
            False,
        ),
    ],
)
def test_an_asserted_mutation_outcome_is_a_finding_unless_marked_or_reported(
    text: str, flagged: bool
) -> None:
    assert (asserted_outcomes(text + "\n") != []) is flagged


def test_a_claim_split_across_a_wrap_is_still_one_sentence(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    path = plan(
        root,
        SCOPE + "Drop the guard ->\nthe test reddens.\n\n"
        "**Expected:** dropping the other guard ->\nit reddens.\n",
    )
    found = lint(root, config, plans=[path]).findings
    assert [(f.rule, f.line) for f in found] == [("asserted-outcome", 3)]


def test_a_finding_after_a_fence_reports_the_files_own_line(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    path = plan(root, SCOPE + "```\n1\n2\n3\n```\n- `src/gone.py`\n")
    assert [f.line for f in lint(root, config, plans=[path]).findings] == [8]


@needs_git
def test_without_paths_only_the_plans_the_diff_touches_are_linted(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    old = plan(root, "no scope, but committed on the base\n", "2026-01-01-old.md")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    git(root, "remote", "add", "origin", str(root))  # the base ref resolves to the seed
    git(root, "fetch", "-q", "origin")
    git(root, "checkout", "-qb", "feature")
    new = plan(root, "no scope either\n", "2026-01-02-new.md")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "new plan")
    result = lint(root, config, plans=[])
    assert result.linted == [new] and old not in result.linted
    assert [f.rule for f in result.findings] == ["scope-missing"]


@needs_git
def test_an_edit_to_a_plan_is_held_to_the_references_on_the_lines_it_writes(
    tmp_path: Path,
) -> None:
    # A delivered plan is a record, and the paths it names go stale as the tree moves on. The
    # diff-scoped check read every line of every plan a change touched, so a change editing one
    # line of an old plan (an `Interfaces:` block, which is kept current) failed on every stale
    # reference in it, and the only way through was to rewrite history. Without `PATH`
    # arguments a reference is now judged only on a line the change adds or rewrites; naming the
    # plan still lints all of it.
    # Mutation: `mutations/`'s "plan check judges an edited plan's untouched lines".
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    old = plan(
        root,
        SCOPE + "- Modify: `src/gone.py`\n- Modify: `src/also_gone.py`\nthe end\n",
        "2026-01-01-old.md",
    )
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    git(root, "remote", "add", "origin", str(root))
    git(root, "fetch", "-q", "origin")
    git(root, "checkout", "-qb", "feature")
    old.write_text(
        SCOPE + "- Modify: `src/gone.py`\n- Modify: `src/also_gone.py` (reworded)\nthe end\n"
        "- Modify: `src/new_and_gone.py`\n",
        encoding="utf-8",
    )
    git(root, "commit", "-qam", "edit the old plan")
    result = lint(root, config, plans=[])
    assert result.linted == [old]
    assert [(f.rule, f.line, f.detail) for f in result.findings] == [
        ("dead-reference", 4, "src/also_gone.py"),
        ("dead-reference", 6, "src/new_and_gone.py"),
    ]
    named = lint(root, config, plans=[old]).findings
    assert [(f.line, f.detail) for f in named] == [
        (3, "src/gone.py"),
        (4, "src/also_gone.py"),
        (6, "src/new_and_gone.py"),
    ]


@needs_git
def test_a_line_the_base_rewrote_since_the_fork_is_not_the_change_s_to_answer_for(
    tmp_path: Path,
) -> None:
    # Against the base alone, a line the base rewrote after the change forked reads as written
    # by the change (it holds the old text the base no longer has), so the change would answer
    # for a stale path it never touched. A line is the change's only when it differs from every
    # fork point's copy as well as the base's.
    # Mutation: `mutations/`'s "plan check reads the lines a change wrote against the base alone".
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    old = plan(root, SCOPE + "- Modify: `src/gone.py`\nthe middle\nthe end\n", "2026-01-01-old.md")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    git(root, "checkout", "-qb", "feature")
    old.write_text(
        SCOPE + "- Modify: `src/gone.py`\nthe middle\nthe end, edited\n", encoding="utf-8"
    )
    git(root, "commit", "-qam", "edit the old plan's last line")
    git(root, "checkout", "-q", "main")
    old.write_text(SCOPE + "- Modify: `src/elsewhere.py`\nthe middle\nthe end\n", encoding="utf-8")
    git(root, "commit", "-qam", "the base rewrites its first entry")
    git(root, "checkout", "-q", "feature")
    git(root, "remote", "add", "origin", str(root))
    git(root, "fetch", "-q", "origin")
    assert lint(root, config, plans=[]).findings == []


@needs_git
def test_a_tag_named_like_the_tracking_branch_does_not_choose_the_default_base(
    tmp_path: Path,
) -> None:
    # git resolves a short `origin/main` through `refs/tags/` first, so a tag of that spelling
    # on the change's own head made the default base the head, the range empty, and `plan
    # check` printed OK having linted nothing, while the `plan` gate, which names the base in
    # full, failed. One spelling of the default now. Mutation (declared): `lint`'s default
    # spelled `origin/<base_branch>` again -> nothing is linted.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    git(root, "remote", "add", "origin", str(root))
    git(root, "fetch", "-q", "origin")
    git(root, "checkout", "-qb", "feature")
    new = plan(root, "no scope here\n", "2026-01-02-new.md")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "new plan")
    git(root, "tag", "origin/main", "HEAD")
    result = lint(root, config, plans=[])
    assert result.linted == [new]
    assert [f.rule for f in result.findings] == ["scope-missing"]


@needs_git
def test_a_touched_plan_whose_name_holds_a_space_is_linted_and_does_not_vanish(
    tmp_path: Path,
) -> None:
    # `git diff --name-only` prints such a path unquoted, so splitting on whitespace tears it in
    # two and neither fragment ends in `.md`. The plan is committed, so `unlinted_plans` does not
    # list it either: it would be neither linted nor reported. Mutation: drop `-z` and split on
    # whitespace — this reddens.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    git(root, "remote", "add", "origin", str(root))
    git(root, "fetch", "-q", "origin")
    git(root, "checkout", "-qb", "feature")
    spaced = plan(root, "no scope here\n", "2026-01-03-a draft.md")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "a plan with a space in its name")
    result = lint(root, config, plans=[])
    assert result.linted == [spaced] and result.unlinted == []
    assert [f.rule for f in result.findings] == ["scope-missing"]


@needs_git
def test_a_base_that_will_not_resolve_is_raised_never_an_ok(tmp_path: Path) -> None:
    # This gate ran green for its whole life on a shallow checkout that had no base ref. The cause
    # is the checkout's, not a plan's, so the lint raises it; `plan check` alone prints it as its
    # `base-unresolvable` finding, exit 1. Mutation (oracle): `mutations/`'s "an unresolvable base
    # reads as a clean run" -> nothing is raised and this reddens.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    with pytest.raises(BaseUnresolvable, match="fetch-depth: 0"):
        lint(root, config, plans=[])
    code, out, _ = cli(root, tmp_path, "plan", "check", "--json")
    assert code == 1
    printed = json.loads(out)
    assert [f["rule"] for f in printed["findings"]] == ["base-unresolvable"]
    assert printed["linted"] == []


@needs_git
def test_a_touched_plan_named_in_bytes_that_are_not_utf_8_is_listed_and_linted(
    tmp_path: Path,
) -> None:
    # `diff --name-only -z` prints a committed name raw. Decoded strictly, one latin-1 plan name
    # raised `UnicodeDecodeError` out of `plan check` and the `plan` gate; read as no answer, it
    # failed the gate on every run of a repository that holds one, a plan nobody could lint.
    # Decoded losslessly, the name is the path on disk and the plan is linted like any other.
    # The name is planted through the index because APFS refuses to create it; where the disk
    # can hold it (Linux, where CI's oracle runs) the file is written too and its finding is the
    # proof it was read. Mutation (declared, on `gitenv`): the answer read as no answer again ->
    # `lint` raises and this reddens.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    raw = b"docs/plans/2026-01-02-caf\xe9.md"
    plant_path(root, raw, "no scope here\n")
    git(root, "commit", "-qm", "a plan whose name is not UTF-8")
    named = root / os.fsdecode(raw)
    assert touched_plans(root, "HEAD~1", root / "docs" / "plans") == [named]
    try:
        named.write_text("no scope here\n", encoding="utf-8")
    except OSError:  # APFS: `Illegal byte sequence`
        written = False
    else:
        written = True
    result = lint(root, config, plans=[], base="HEAD~1")
    assert result.linted == ([named] if written else [])
    assert [f.rule for f in result.findings] == (["scope-missing"] if written else [])


@needs_git
def test_a_diff_git_gave_no_answer_for_is_not_a_shallow_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `git_run`'s `-1` — git could not be run or ran past its time limit — is not "the base
    # does not resolve": that finding sends a reader to `fetch-depth: 0` in a clone that holds
    # every ref, and reads as a finding rather than as a gate that never looked. Still exit 1,
    # with the cause in words. Mutation (advisory): drop the `code == -1` arm in
    # `_unresolved` — `BaseUnresolvable` is raised instead of this `Failure` and this reddens.
    from stayfixed.docs import plans as module

    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    real = git_run

    def unanswered(where: Path, *args: str, **kwargs: Any) -> tuple[int, str]:
        return (-1, "") if args[0] == "diff" else real(where, *args, **kwargs)

    monkeypatch.setattr(module, "git_run", unanswered)
    with pytest.raises(Failure, match=re.escape(NO_ANSWER)) as caught:
        lint(root, config, plans=[], base="HEAD")
    assert "fetch-depth" not in str(caught.value)


OLD = "an old plan, from before it had a Scope line\n"


@needs_git
def test_a_plan_is_linted_whichever_of_several_merge_bases_git_would_pick(tmp_path: Path) -> None:
    # A criss-cross: `main` fixes an old plan and then merges a colleague's side branch, forked
    # before the fix and committed after it; the change merges the fixing commit and the side
    # branch itself, then puts the old plan back. `<base>...HEAD` diffs against git's pick, the
    # side branch, which holds the old plan too: nothing was linted, and merging the change put
    # the old plan back on `main`. Every merge base is diffed and the plans are taken together.
    # Mutations (declared): `--all` dropped, or only the first merge base diffed -> nothing is
    # linted.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    old = plan(root, OLD)
    git(root, "add", "-A")
    dated(root, 1, "commit", "-q", "-m", "the old plan")
    shape = criss_cross(root, lambda: plan(root, SCOPE + "fixed\n"))
    git(root, "checkout", "-q", "-b", "change")
    # A branch that merged both and put nothing back lints nothing: its plan is the base's own.
    assert lint(root, config, plans=[], base=shape.base).findings == []
    old.write_text(OLD, encoding="utf-8")
    dated(root, 6, "commit", "-q", "-am", "put the old plan back")
    # The premise: git's one pick hides the plan.
    assert git(root, "diff", "--name-only", f"{shape.base}...HEAD", "--", "docs/plans") == ""
    result = lint(root, config, plans=[], base=shape.base)
    assert result.linted == [old]
    assert [f.rule for f in result.findings] == ["scope-missing"]


@needs_git
def test_a_plan_the_base_holds_as_head_does_is_not_linted(tmp_path: Path) -> None:
    # A branch stacked on another, which merged `main` after `main` gained a plan with a
    # finding, and then `main` merged the branch below it: the two merge bases are the commit
    # the stack merged and the lower branch's tip, and against the second that plan differs.
    # The stack never touched it, and merging the stack alters nothing about it, because its
    # copy is the base's own. Mutation (declared): the base comparison dropped -> the base's
    # plan is linted here and its finding fails a change that never touched it.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    dated(root, 1, "commit", "-q", "-m", "seed")
    git(root, "checkout", "-q", "-b", "lower")
    (root / "lower.txt").write_text("lower\n", encoding="utf-8")
    git(root, "add", "-A")
    dated(root, 2, "commit", "-q", "-m", "the lower branch")
    git(root, "checkout", "-q", "main")
    plan(root, "a plan the base took with no Scope line\n")
    git(root, "add", "-A")
    dated(root, 3, "commit", "-q", "-m", "a plan on the base")
    git(root, "checkout", "-q", "-b", "stacked", "lower")
    dated(root, 4, "merge", "-q", "--no-ff", "--no-edit", "main")
    (root / "stacked.txt").write_text("stacked\n", encoding="utf-8")
    git(root, "add", "-A")
    dated(root, 5, "commit", "-q", "-m", "the stacked branch")
    git(root, "checkout", "-q", "main")
    dated(root, 6, "merge", "-q", "--no-ff", "--no-edit", "lower")
    base = dated(root, 6, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "stacked")
    # The premise: two merge bases, and against one of them the base's plan differs.
    forks = git(root, "merge-base", "--all", base, "HEAD").split()
    assert len(forks) == 2
    assert any(git(root, "diff", "--name-only", fork, "HEAD", "--", "docs/plans") for fork in forks)
    result = lint(root, config, plans=[], base=base)
    assert result.linted == []
    assert result.findings == []


@needs_git
def test_a_shallow_clone_is_a_base_that_will_not_resolve_never_an_older_fork_point(
    tmp_path: Path,
) -> None:
    # In a shallow clone the commits HEAD forked from can be cut off, and the merge base git
    # sees is then an older one. Here the base merges an old commit back in, a clone of depth 2
    # keeps that commit and cuts the base's path to the real fork point, and git names the old
    # commit: a change that put a plan back as it was there was not linted. A shallow clone is a
    # base that will not resolve, whose remedy is the whole history. Mutation (declared): the
    # shallow check reads only whether git answered -> the older commit is diffed and nothing
    # is linted.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    old = plan(root, OLD)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the old plan")
    older = git(root, "rev-parse", "HEAD").strip()
    plan(root, SCOPE + "fixed\n")
    git(root, "commit", "-q", "-am", "fix the plan")
    forked = git(root, "rev-parse", "HEAD").strip()
    (root / "later.txt").write_text("later\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "later")
    later = git(root, "rev-parse", "HEAD").strip()
    tree = f"{later}^{{tree}}"
    base = git(root, "commit-tree", "-m", "merge the old commit", "-p", later, "-p", older, tree)
    git(root, "update-ref", "refs/heads/main", base.strip())
    git(root, "checkout", "-q", "-b", "change", forked)
    old.write_text(OLD, encoding="utf-8")
    git(root, "commit", "-q", "-am", "put the old plan back")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--depth", "2", "--branch", "main", root.as_uri(), str(clone))
    git(clone, "fetch", "-q", "origin", "change")
    git(clone, "checkout", "-q", "--detach", "FETCH_HEAD")
    # The premise: the clone is shallow, and the merge base it sees is the old commit.
    assert git(clone, "rev-parse", "--is-shallow-repository").strip() == "true"
    assert git(clone, "merge-base", "--all", "origin/main", "HEAD").split() == [older]
    config = load(clone, machine=tmp_path / "m.toml")
    with pytest.raises(BaseUnresolvable, match="fetch-depth: 0") as caught:
        lint(clone, config, plans=[])
    assert "shallow" in str(caught.value)


@needs_git
@pytest.mark.parametrize(
    ("answer", "raised", "cause"),
    [(-1, Failure, NO_ANSWER), (128, BaseUnresolvable, "git exited 128")],
    ids=["no-answer", "refused"],
)
def test_a_shallow_check_git_does_not_answer_never_reads_as_a_full_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: int,
    raised: type[Failure],
    cause: str,
) -> None:
    # What an unknown fork point means to this lint: a git that gave no answer is a plain
    # `Failure`, whose remedy is not a deeper checkout, and a refusal is `BaseUnresolvable`.
    # Mutation (declared, on `gitenv`): the shallow check's failure ignored -> the diff goes
    # ahead and nothing raises; (declared) `answered` ignored -> no answer is `BaseUnresolvable`.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    answer_shallow_check(monkeypatch, answer)
    with pytest.raises(Failure, match=re.escape(cause)) as caught:
        lint(root, config, plans=[], base="HEAD")
    assert type(caught.value) is raised
    assert "NOTHING was linted" in str(caught.value)


@needs_git
def test_a_base_that_shares_no_history_with_the_tree_will_not_resolve(tmp_path: Path) -> None:
    # A base with no commit in common with HEAD leaves nothing to diff against, and "no plan
    # changed" would pass whatever the change carries. Mutation (declared, on `gitenv`): no
    # merge base read as none to compare -> the lint answers OK over no plans.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    plan(root, "no scope here\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    git(root, "checkout", "-q", "--orphan", "unrelated")
    git(root, "commit", "-q", "-m", "no shared history")
    other = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "-f", "main")
    with pytest.raises(BaseUnresolvable, match=re.escape(DISJOINT)):
        lint(root, config, plans=[], base=other)


@needs_git
def test_an_option_shaped_base_never_reaches_a_git_argv_slot(tmp_path: Path) -> None:
    # The reproduction rather than the guard's own vocabulary: `--base=--output=<path>` is an
    # argv slot ahead of `--`, so `git diff` read it as its own option, wrote the diff to that
    # absolute path — outside `contained()` and outside `fsops` — and exited 0 with empty
    # stdout. `touched_plans` then answered `[]` instead of None, so a committed plan was never
    # linted and the command printed OK: the exact state raising `BaseUnresolvable` exists to
    # prevent, reached by a typo. Mutation: drop the `base.startswith("-")` refusal in
    # `touched_plans` — this reddens, on the written file first.
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    plan(root, "a committed plan with no Scope line, which the gate must not skip\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    victim = tmp_path / "victim"
    victim.mkdir()
    with pytest.raises(Refusal):
        lint(root, config, plans=[], base=f"--output={victim / 'PWNED'}")
    assert list(victim.iterdir()) == []


@needs_git
def test_an_uncommitted_plan_is_reported_as_unlinted_and_linted_when_named(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    git(root, "remote", "add", "origin", str(root))
    git(root, "fetch", "-q", "origin")
    draft = plan(root, "a draft with a space in it\n", "2026-01-03-a draft.md")
    result = lint(root, config, plans=[])
    assert result.unlinted == [draft] and result.linted == []
    named = lint(root, config, plans=[draft])
    assert named.linted == [draft] and [f.rule for f in named.findings] == ["scope-missing"]


def test_a_named_plan_that_does_not_exist_is_a_failure(tmp_path: Path) -> None:
    from stayfixed.errors import Failure

    root, config = project(tmp_path)
    with pytest.raises(Failure):
        lint(root, config, plans=[root / "docs" / "plans" / "missing.md"])


def test_a_named_plan_outside_the_project_is_a_failure_not_an_internal_error(
    tmp_path: Path,
) -> None:
    # Every finding carries a repo-relative path, so this would otherwise reach `relative_to`
    # and raise `ValueError`, which the frame reports as an internal error (2) rather than as
    # the failure the missing-file case beside it already produces. Mutation: drop the
    # `is_relative_to` guard — this reddens with `ValueError`.
    from stayfixed.errors import Failure

    root, config = project(tmp_path)
    elsewhere = tmp_path / "other" / "2026-01-01-x.md"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("**Scope:** iff x.\n", encoding="utf-8")
    with pytest.raises(Failure, match="not inside the project root"):
        lint(root, config, plans=[elsewhere])


def test_a_plan_that_is_not_utf8_is_a_failure_not_an_internal_error(tmp_path: Path) -> None:
    # A repository's malformed input must read as their input being wrong (1), never as this
    # tool being broken (2). Mutation: drop `read_document`'s `UnicodeDecodeError` arm — this
    # reddens with `UnicodeDecodeError` escaping instead.
    root, config = project(tmp_path)
    path = root / "docs" / "plans" / "2026-01-01-x.md"
    path.write_bytes(b"**Scope:** iff x.\n\ncaf\xe9\n")
    with pytest.raises(Failure, match="is not valid UTF-8"):
        lint(root, config, plans=[path])


def test_a_crafted_plan_name_reaches_the_refusal_escaped_never_raw(tmp_path: Path) -> None:
    # `plan check` runs in CI and names the plan it could not read; the name is the pull
    # request's, and a line break and `::error::` in it forged a workflow command on the runner.
    # The refusal is the only place the name appears, so it is escaped rather than withheld.
    # Mutation: format `where` unquoted in `hygiene.read_document` — this reddens.
    root, config = project(tmp_path)
    name = f"2026-01-01-{CRAFTED}.md"
    path = root / "docs" / "plans" / name
    path.write_bytes(b"**Scope:** iff x.\n\ncaf\xe9\n")
    with pytest.raises(Failure, match="is not valid UTF-8") as raised:
        lint(root, config, plans=[path])
    assert_never_raw(str(raised.value))
    assert repr(f"docs/plans/{name}") in str(raised.value)


def test_a_path_claim_outside_the_root_is_never_settled_against_this_disk(tmp_path: Path) -> None:
    # The verdict must not depend on the developer's filesystem. Before, `/abs/x.md` that
    # happened to exist locally passed the lint and did not exist in CI, while the same claim
    # with the file absent was a finding — which is an existence oracle for every path outside
    # the root, in both directions. The assertion is that the two answers are the same.
    # Mutation: drop `resolves_within`'s containment and resolve the claim anyway — the second
    # and fourth `rules(...)` calls redden.
    root, config = project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    absolute = plan(root, SCOPE + f"see `{outside / 'secret.md'}`\n", "2026-01-01-abs.md")
    relative = plan(root, SCOPE + "see `../outside/secret.md`\n", "2026-01-02-rel.md")
    (outside / "secret.md").write_text("", encoding="utf-8")
    assert rules(root, config, absolute) == [] and rules(root, config, relative) == []
    (outside / "secret.md").unlink()
    assert rules(root, config, absolute) == [] and rules(root, config, relative) == []
    # And a claim that does stay inside the root is still settled, so this did not turn the
    # lint off.
    assert rules(root, config, plan(root, SCOPE + "see `src/gone.py`\n", "2026-01-03-in.md")) == [
        "dead-reference"
    ]
