"""`stayfixed init` through the real parser: the flags, the exit codes and the `--json` keys.

Nothing here reaches the network, and it is kept out three ways. Every case that writes or plans
a footprint but one goes through `_invoke`, which appends `--no-ci`: with `[ci] mode` set to
`none` the run never asks the `release` package to resolve a pin, so the `subprocess_runner()`
`commands.py` builds is never handed a `git ls-remote` against the public repository. The one
case that must resolve a pin — the hostile `gate_branch` arm, which exists precisely because
`_ci` reaches that check *after* the pin — stubs `subprocess_runner` at the seam `commands.py`
builds it from and answers one released tag from a string. The `--questions` cases go through
`_run`, because `--questions` resolves no pin and refuses `--no-ci` beside it.
"""

from __future__ import annotations

import inspect
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from stayfixed import __version__
from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.config.loader import load, loads
from stayfixed.config.schema import NAME_RULE, Config
from stayfixed.project.commands import STAMPED, run_init
from stayfixed.project.init import (
    HEAD_CURRENT,
    HEAD_DEFAULTED,
    HEAD_REMOTES_UNKNOWN,
    HEAD_UNRECORDED,
)
from stayfixed.project.templates import _ci
from stayfixed.project.uninstall import KEPT_CONFIG
from stayfixed.release.api import Resolution
from stayfixed.scaffold import Manifest
from tests.cli import cli
from tests.gitfixture import git, needs_git
from tests.project.repos import DOCUMENT, repository
from tests.runners import LsRemote
from tests.snapshot import assert_snapshot_unchanged, snapshot

TAG = f"v{__version__}"  # the release tag the running version would carry


JSON_KEYS = {
    "dry_run",
    "adopted",
    "once",
    "scaffold",
    "writes",
    "skipped",
    "pin",
    "asked",
    "note",
    "unknown_harnesses",
    "head_note",
    "stamped",
}


def _run(root: Path, tmp_path: Path, *argv: str) -> tuple[int, str]:
    parser = build_parser(discover_registrars())
    flags = ["--root", str(root), "--machine", str(tmp_path / "absent.toml")]
    with redirect_stdout(io.StringIO()) as out:
        code = run(["init", *argv, *flags], parser=parser)
    return code, out.getvalue()


def _invoke(root: Path, tmp_path: Path, *argv: str) -> tuple[int, str]:
    """`_run` with `--no-ci`, which is what keeps the network out of it."""
    return _run(root, tmp_path, *argv, "--no-ci")


@needs_git
def test_without_yes_the_command_refuses_and_names_the_command_that_prints_the_questions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The refusal names the command that prints the questions, so a relayer has the next step.
    # Mutation (by hand): the refusal names `stayfixed init` alone -> the first `in` reddens.
    root = repository(tmp_path)
    code, printed = _invoke(root, tmp_path)
    assert code == 2 and printed == ""
    stderr = capsys.readouterr().err
    assert "`stayfixed init --questions`" in stderr and "--yes" in stderr
    assert not (root / ".stayfixed").exists()


@needs_git
def test_a_dry_run_prints_both_reports_and_says_it_wrote_nothing(tmp_path: Path) -> None:
    root = repository(tmp_path)
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--json")
    assert code == 0, printed
    data = json.loads(printed)
    assert set(data) >= JSON_KEYS and data["dry_run"] is True
    # Renamed with no alias: a script reading the old key finds nothing rather than a stale copy.
    assert "footprint" not in data
    # Two reports, not one rendered twice: the write-once pass plans three files and the
    # footprint pass plans the rest, and a summary that showed one of them would hide
    # whichever half a refusal landed in.
    assert "CLAUDE.md" in data["once"] and "CLAUDE.md" not in data["scaffold"]
    assert ".gitignore" in data["scaffold"]
    assert data["adopted"] is False and data["pin"] is None
    assert set(data["writes"]) >= {"CLAUDE.md", "stayfixed.toml", ".gitignore"}
    assert not (root / "CLAUDE.md").exists()


@needs_git
def test_a_real_run_prints_both_reports_in_full_and_the_ci_line(tmp_path: Path) -> None:
    # The summary used to be four count lines, so a person without `--json` was told how many files
    # there were and never which. The skill relays "both reports … each one names every file with
    # its verdict", which it could not do from counts.
    root = repository(tmp_path)
    code, printed = _invoke(root, tmp_path, "--yes")
    assert code == 0, printed
    assert printed.startswith("initialised:")
    assert "write-once:" in printed and "scaffold:" in printed
    # Per-artifact lines, from both passes, with their verbs — not just the counts.
    assert "create         CLAUDE.md  (new)" in printed
    assert "create         docs/adr/0000-template.md  (new)" in printed
    assert "CI: skipped — [ci] mode is none" in printed
    assert (root / ".stayfixed" / "manifest.json").is_file()


@needs_git
def test_a_refused_footprint_exits_one_with_the_refused_section_in_that_report(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path)
    (root / "AGENTS.md").write_text("# Mine\n\n<!-- stayfixed:harness:end -->\n", encoding="utf-8")
    code, printed = _invoke(root, tmp_path, "--yes", "--json")
    assert code == 1, printed
    data = json.loads(printed)
    assert "REFUSED" in data["scaffold"] and "REFUSED" not in data["once"]
    assert not (root / ".stayfixed").exists()
    # And in plain text, which is the output a person meets on this path: the REFUSED section
    # with the artifact and the engine's reason, and a heading that does not claim otherwise.
    code, plain = _invoke(root, tmp_path, "--yes")
    assert code == 1
    assert plain.startswith("refused, and nothing was written:")
    assert "REFUSED — nothing will be written" in plain
    assert "AGENTS.md  (region 'harness' has an end marker with no beginning" in plain


@needs_git
def test_a_refused_write_once_pass_exits_one_and_writes_nothing(tmp_path: Path) -> None:
    # The write-once half of `InitReport.refused`, which the case above cannot reach: its
    # refusal is the footprint pass's. A `CLAUDE.md` that is a symlink is refused by the
    # write-once pass alone, and the run must stop there with its report. Mutation (oracle):
    # `mutations/`'s "init's refusal reads only the footprint plan" -> the run goes on to `apply`,
    # whose own backstop refuses the plan: exit 2 with the engine's message, and no report.
    root = repository(tmp_path)
    (tmp_path / "elsewhere.md").write_text("theirs\n", encoding="utf-8")
    (root / "CLAUDE.md").symlink_to(tmp_path / "elsewhere.md")
    before = snapshot(root)
    code, printed = _invoke(root, tmp_path, "--yes", "--json")
    assert code == 1, printed
    data = json.loads(printed)
    assert "REFUSED" in data["once"] and "REFUSED" not in data["scaffold"]
    assert data["summary"].startswith("refused, and nothing was written:")
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_hostile_gate_branch_is_reported_as_a_skipped_workflow_and_not_as_a_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A gate branch that is not a plain branch name used to be reported as a release pin, though no
    # workflow was written; this holds it end to end. `[ci] mode` stays `reusable` here — this is
    # the one case in this module that does not pass `--no-ci` — so the command really reaches the
    # `release` package; the runner it would use is stubbed at the seam `commands.py` builds it
    # from, so no network call is made and the answer is one released tag.
    from stayfixed import runner as runner_module

    root = repository(tmp_path)
    # A recorded ref as well: the branch check is reached only once there is a ref to render,
    # and it is deliberately not the sha the stub listing resolves, so the assertions below can
    # tell the two sources apart.
    recorded = "e" * 40
    (root / "stayfixed.toml").write_text(
        '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
        f'[ci]\nref = "{recorded}"\ngate_branch = "main\'; rm -rf"\n',
        encoding="utf-8",
    )
    sha = "c" * 40
    monkeypatch.setattr(
        runner_module,
        "subprocess_runner",
        lambda: LsRemote(stdout=f"{sha}\trefs/tags/{TAG}\n"),
    )
    code, printed = _run(root, tmp_path, "--yes")
    assert code == 0, printed
    assert "CI: skipped — [ci] gate_branch is not a plain branch name" in printed
    assert sha not in printed and f"{TAG}@" not in printed
    assert not (root / ".github").exists()


@needs_git
def test_an_adopted_ref_is_reported_as_the_repositorys_own_and_not_as_a_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The summary's third arm, and the one the invariant needs: a workflow was planned, but from
    # the ref `stayfixed.toml` already recorded rather than from the pin this run resolved. Naming
    # the resolved release here would assert that the gate GitHub runs is that release's, which
    # is exactly what `doctor`'s `ci-ref` row would then report as red.
    from stayfixed import runner as runner_module

    root = repository(tmp_path)
    recorded = "e" * 40
    (root / "stayfixed.toml").write_text(
        '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
        f'[ci]\nmode = "reusable"\nref = "{recorded}"\n',
        encoding="utf-8",
    )
    sha = "c" * 40
    monkeypatch.setattr(
        runner_module,
        "subprocess_runner",
        lambda: LsRemote(stdout=f"{sha}\trefs/tags/{TAG}\n"),
    )
    # The dry run first, because it writes nothing and leaves the repository fresh for the real
    # one below: `--json` is where a caller reads which ref the workflow will carry.
    code, printed = _run(root, tmp_path, "--yes", "--dry-run", "--json")
    assert code == 0, printed
    data = json.loads(printed)
    assert data["ref"] == recorded and data["pin"] == {"tag": TAG, "sha": sha}
    code, plain = _run(root, tmp_path, "--yes")
    assert code == 0, plain
    assert "CI: the workflow pins the [ci] ref this repository already recorded" in plain
    assert f"{TAG}@{sha}" not in plain
    workflow = (root / ".github" / "workflows" / "stayfixed.yml").read_text(encoding="utf-8")
    assert f"check.yml@{recorded}" in workflow and sha not in workflow


def _ci_config(mode: str, ref: str, tmp_path: Path) -> Config:
    text = (
        '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
        f'[ci]\nmode = "{mode}"\nref = "{ref}"\n'
    )
    return loads(text, tmp_path, machine=tmp_path / "absent.toml")


def test_the_ci_line_has_no_arm_no_run_can_reach(tmp_path: Path) -> None:
    """An unreachable branch is a vacuous assertion in another shape.

    `run_init` read `if skipped is not None or not report.ref:` and formatted
    `skipped or <a fallback>`, and neither the disjunct nor the fallback could ever fire.
    `templates._ci` returns a rendered workflow only for a `[ci] ref` that is non-empty and
    matches `CI_REF`, and a non-empty reason in every other arm; `init` then derives
    `report.ref` as `"" if "ci-workflow" in passes.skipped else config.ci.ref` -- its own
    comment calls the two "one value by construction", and `doctor`'s `ci-ref` row enforces it.
    So a run with no skip has a ref, and a sentence nobody can provoke has been deleted rather
    than left standing as a claim about a state the code forbids.

    Both halves are asserted. The invariant is walked over `_ci`'s own arms, so this is a
    statement about the code rather than about one run; the source is read with its comments
    stripped, because what "unreachable" means here is that the arm is gone and no behaviour
    moved when it went.

    Mutation: `mutations/`'s "the init CI line grows an arm no run can reach".
    """
    code = "\n".join(
        line
        for line in inspect.getsource(run_init).splitlines()
        if not line.strip().startswith("#")
    )
    assert "no workflow was planned" not in code
    assert "not report.ref" not in code

    rendered, skipped = 0, 0
    for mode, ref, adopted in [
        ("none", "", False),
        ("uvx", "", False),
        ("reusable", "", True),
        ("reusable", "", False),
        ("reusable", "not-a-sha", False),
        ("reusable", "a" * 40, False),
    ]:
        config = _ci_config(mode, ref, tmp_path)
        workflow, reason = _ci(config, Resolution(None, True), adopted=adopted)
        if workflow is not None:
            # The half the deleted arm rested on: a workflow is planned only for a ref, so
            # `init`'s `report.ref` cannot be empty while `ci-workflow` is absent from `skipped`.
            assert reason is None and config.ci.ref
            rendered += 1
        else:
            # And the other half: every skip carries a sentence, so the fallback had nothing to
            # stand in for either.
            assert reason
            skipped += 1
    # Non-vacuous: both branches were actually taken.
    assert rendered and skipped


@needs_git
def test_a_harness_no_adapter_serves_is_counted_and_never_named(tmp_path: Path) -> None:
    # `[stayfixed] agents` is repository-authored, so the report prints how many names went
    # unserved and none of them. Mutation: print the loaded `agents` names beside the count on
    # the note line -> the `cursor` and ESC assertion reddens. (Printing them instead of the
    # count reddens the note assertion first, which proves nothing about the names.)
    root = repository(tmp_path)
    (root / "stayfixed.toml").write_text(
        '[stayfixed]\nversion = "0.1.0"\nagents = ["claude", "cursor\\u001b[31m"]\n\n'
        '[project]\nname = "widget"\n',
        encoding="utf-8",
    )
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run")
    assert code == 0, printed
    assert "note: 1 name(s) in [stayfixed] agents name no harness" in printed
    assert "cursor" not in printed and "\x1b" not in printed
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--json")
    assert json.loads(printed)["unknown_harnesses"] == 1


@needs_git
def test_questions_print_each_default_with_its_source_and_write_nothing(tmp_path: Path) -> None:
    # The card is what a person reads before choosing any answer, so each line carries the
    # value `init --yes` would take and where it came from; the questions plan nothing.
    # The help and the docs promise the flag that changes each one, so the line names it too.
    # Mutation (by hand): the card drops the source, or the flag -> the `project.name` line
    # reddens.
    root = repository(tmp_path)
    before = snapshot(root)
    code, printed = _run(root, tmp_path, "--questions")
    assert code == 0, printed
    assert printed.startswith("detected:\n")
    assert "  project.name: widget (origin remote; --name)\n" in printed
    assert "  memory.mode: harness (default; --memory-mode)\n" in printed
    assert "  artifacts.local: none (the preset's default; --local)\n" in printed
    code, printed = _run(root, tmp_path, "--questions", "--json")
    assert code == 0, printed
    assert json.loads(printed)["questions"]["type"] == "object"
    assert_snapshot_unchanged(root, before)
    assert not (root / ".stayfixed").exists()


@needs_git
def test_questions_take_no_flag_that_writes_or_plans(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--yes` is excluded by the parser; `--dry-run` and `--no-ci` are flags `--yes` takes, so
    # one mutually exclusive group cannot exclude them too, and the command refuses them.
    # Mutation (oracle): that refusal disabled -> `--questions --dry-run` prints the questions
    # and exits 0.
    root = repository(tmp_path)
    code, printed = _run(root, tmp_path, "--questions", "--dry-run")
    assert code == 2 and printed == ""
    assert "--questions writes nothing" in capsys.readouterr().err
    code, printed = _run(root, tmp_path, "--questions", "--no-ci")
    assert code == 2 and printed == ""
    # An answer flag is `--yes`'s too: the questions would print defaults it had replaced.
    code, printed = _run(root, tmp_path, "--questions", "--name", "widget")
    assert code == 2 and printed == ""
    with pytest.raises(SystemExit):
        _run(root, tmp_path, "--questions", "--yes")
    assert not (root / ".stayfixed").exists()


@needs_git
def test_a_remote_head_outside_the_grammar_is_noted_and_never_quoted(tmp_path: Path) -> None:
    # `init --yes` writes `main` where `origin/HEAD` named a branch outside the grammar, so the
    # report says the default replaced it, in stayfixed's words, without the remote's. Mutation
    # (by hand): the note dropped from the report -> the note assertion reddens.
    root = repository(tmp_path)
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run")
    assert code == 0 and HEAD_DEFAULTED not in printed, printed
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/`id`")
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run")
    assert code == 0, printed
    assert f"note: {HEAD_DEFAULTED}" in printed and "`id`" not in printed
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--json")
    assert json.loads(printed)["head_note"] == HEAD_DEFAULTED
    # An answered base branch replaced nothing, so there is nothing to note. Mutation (by hand):
    # the note keyed on detection alone -> this reddens.
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--base-branch", "develop")
    assert code == 0 and "origin/HEAD" not in printed, printed


@needs_git
def test_a_pushed_repository_on_a_feature_branch_gates_main_and_says_how_to_record_the_head(
    tmp_path: Path,
) -> None:
    # Created here, pushed with `git push -u origin main`, adopted from a feature branch: an
    # `origin` and no `origin/HEAD`. The feature branch was written as the base, so the workflow
    # gated it. Now `main` is written and the note names the command that records the remote's
    # default. Mutations (oracle): `mutations/`'s "a remote with no origin/HEAD takes the branch
    # checked out" -> the base branch assertion reddens; "the unrecorded remote head is never noted"
    # -> the note assertion reddens.
    #
    # The remote is created on `main`, as a forge creates it. Left to git's own default, its
    # `HEAD` named a branch that was never pushed wherever that default is `master` — upstream
    # git's built-in, which the fixture's sealed configuration leaves in force — so it advertised
    # no `HEAD` and `set-head --auto` below could not determine one; Apple's git names `main`
    # from a configuration file of its own that the seal does not reach, which is why that
    # mismatch never showed on a Mac.
    root = repository(tmp_path)
    git(root, "commit", "-q", "--allow-empty", "-m", "one")
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(root, "remote", "set-url", "origin", str(bare))
    git(root, "push", "-q", "-u", "origin", "main")
    git(root, "checkout", "-q", "-b", "chore/adopt-stayfixed")
    code, printed = _invoke(root, tmp_path, "--yes")
    assert code == 0 and f"note: {HEAD_UNRECORDED}" in printed, printed
    assert "`git remote set-head origin --auto`" in HEAD_UNRECORDED
    assert load(root).project.base_branch == "main"
    assert "chore/adopt-stayfixed" not in (root / "stayfixed.toml").read_text(encoding="utf-8")
    # Once `origin/HEAD` is recorded, it answers, and there is nothing to note.
    other = repository(tmp_path / "b")
    git(other, "commit", "-q", "--allow-empty", "-m", "one")
    git(other, "remote", "set-url", "origin", str(bare))
    git(other, "fetch", "-q", "origin")
    git(other, "remote", "set-head", "origin", "--auto")
    git(other, "checkout", "-q", "-b", "chore/adopt-stayfixed")
    code, printed = _invoke(other, tmp_path, "--yes", "--dry-run", "--json")
    assert code == 0 and json.loads(printed)["head_note"] == "", printed
    git(other, "remote", "set-head", "origin", "--delete")
    code, printed = _invoke(other, tmp_path, "--yes", "--dry-run", "--json")
    assert json.loads(printed)["head_note"] == HEAD_UNRECORDED, printed
    # An answered base branch replaced nothing.
    code, printed = _invoke(other, tmp_path, "--yes", "--dry-run", "--base-branch", "develop")
    assert code == 0 and HEAD_UNRECORDED not in printed, printed


@needs_git
@pytest.mark.parametrize("shape", ["pushed", "cloned"])
def test_a_repository_whose_only_remote_is_upstream_gates_main_and_says_how_to_answer_it(
    tmp_path: Path, shape: str
) -> None:
    # Only `origin/HEAD` is read, so a repository whose one remote is `upstream` — created here
    # and pushed there, or cloned with `-o upstream`, which records `upstream/HEAD` — has no
    # head detection reads. It is still a repository with a remote, adopted from a feature
    # branch, so `main` stands and the note names `--base-branch`, which answers it whatever the
    # remote is called. Mutation (oracle): `mutations/`'s "only an origin remote keeps the default"
    # -> the feature branch is written.
    bare = tmp_path / "upstream.git"
    if shape == "pushed":
        root = repository(tmp_path, origin=None)
        git(root, "commit", "-q", "--allow-empty", "-m", "one")
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
        git(root, "remote", "add", "upstream", str(bare))
        git(root, "push", "-q", "-u", "upstream", "main")
    else:
        seed = repository(tmp_path / "seed", origin=None)
        git(seed, "commit", "-q", "--allow-empty", "-m", "one")
        git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
        git(tmp_path, "clone", "-q", "-o", "upstream", str(bare), "widget")
        root = tmp_path / "widget"
    git(root, "checkout", "-q", "-b", "chore/adopt-stayfixed")
    code, printed = _invoke(root, tmp_path, "--yes", "--name", "widget")
    assert code == 0 and f"note: {HEAD_UNRECORDED}" in printed, printed
    assert "--base-branch BRANCH" in HEAD_UNRECORDED
    assert load(root).project.base_branch == "main"


@needs_git
def test_remotes_git_cannot_list_leave_main_with_a_note_of_their_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No answer to `git remote` is not "no remote": the branch checked out is not taken, and the
    # note says git could not tell. Mutation (oracle): `mutations/`'s "remotes git cannot list are
    # never noted" -> the note is missing.
    from stayfixed.gitenv import git_run as real

    root = repository(tmp_path, origin=None)
    git(root, "symbolic-ref", "HEAD", "refs/heads/develop")

    def unanswered(where: Path, *args: str, **kwargs: Any) -> tuple[int, str]:
        return (-1, "") if args[0] == "remote" else real(where, *args, **kwargs)

    monkeypatch.setattr("stayfixed.project.detect.git_run", unanswered)
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--json")
    assert code == 0 and json.loads(printed)["head_note"] == HEAD_REMOTES_UNKNOWN, printed


@needs_git
def test_a_checked_out_branch_standing_in_for_a_remote_head_is_noted(tmp_path: Path) -> None:
    # With no `origin/HEAD`, a repository on `develop` takes `develop` as its base: the report
    # says where the branch came from, so a person on a feature branch reads it before the
    # workflow gates the wrong one. `main` is what the default was anyway, and says nothing.
    # Mutation (oracle): `mutations/`'s "the checked-out branch is never noted" -> the note
    # assertion reddens.
    root = repository(tmp_path, origin=None)
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run")
    assert code == 0 and HEAD_CURRENT not in printed, printed
    git(root, "symbolic-ref", "HEAD", "refs/heads/develop")
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run")
    assert code == 0 and f"note: {HEAD_CURRENT}" in printed, printed
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--json")
    assert json.loads(printed)["head_note"] == HEAD_CURRENT
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--base-branch", "develop")
    assert code == 0 and HEAD_CURRENT not in printed, printed


def _answers(schema: dict[str, Any]) -> list[str]:
    """`init --yes` argv answering every question as the `init` skill does: each property's own
    flag with its default, one flag per list item, a switch only when its default is on, and
    `widget` where there is no default. CI is `_invoke`'s own `--no-ci`, and the plugins are
    `setup`'s, not `init`'s."""
    argv: list[str] = []
    for key, question in schema["properties"].items():
        if key in ("ci.mode", "plugins"):
            continue
        value = question.get("default", "widget" if key == "project.name" else None)
        assert value is not None, key
        if isinstance(value, bool):
            argv += [question["x-stayfixed-flag"]] if value else []
            continue
        for item in value if isinstance(value, list) else [value]:
            argv += [question["x-stayfixed-flag"], item]
    return argv


def _written(root: Path, tmp_path: Path) -> tuple[Config, dict[str, tuple[str, str]]]:
    """What a finished `init` leaves: the configuration the next command loads, and every
    manifest record but `config`'s as `(target, sha256)`."""
    config = load(root, machine=tmp_path / "absent.toml")
    records = Manifest.read(root).records
    return config, {k: (r.target, r.sha256) for k, r in records.items() if k != "config"}


@needs_git
@pytest.mark.parametrize("derivable", [True, False], ids=["derivable", "not-derivable"])
def test_the_questions_answered_as_the_skill_answers_them_write_what_yes_writes(
    tmp_path: Path, derivable: bool
) -> None:
    # The round trip through the real parser: the questions' own flags, each given its default,
    # write what `--yes` alone writes. The `not-derivable` repository's origin names no project,
    # so `--name` answers it, and its twin is one whose name derives to `widget`. Mutation
    # (oracle): `mutations/`'s "an answered name is still detected strictly" -> the `not-derivable`
    # case is refused naming the grammar, exit 2.
    origin = "git@github.com:owner/widget.git" if derivable else "git@github.com:owner/Not A.git"
    root = repository(tmp_path / "answered", origin=origin)
    code, printed = _run(root, tmp_path, "--questions", "--json")
    assert code == 0, printed
    schema = json.loads(printed)["questions"]
    assert ("default" in schema["properties"]["project.name"]) is derivable
    code, printed = _invoke(root, tmp_path, "--yes", *_answers(schema))
    assert code == 0, printed
    twin = repository(tmp_path / "twin")
    code, printed = _invoke(twin, tmp_path, "--yes")
    assert code == 0, printed
    assert _written(root, tmp_path) == _written(twin, tmp_path)


@needs_git
@pytest.mark.parametrize(
    "argv",
    [
        ("--yes", "--name", "Not A Name"),
        ("--yes", "--base-branch", "a b"),
        ("--yes", "--base-branch", "a..b"),
        ("--yes", "--base-branch", "HEAD"),
        ("--yes", "--local", "bug-index"),
        ("--yes", "--memory-mode", "cloud"),
        ("--yes", "--profile", "rust"),
        ("--yes", "--agent", "cursor"),
        ("--yes", "--commit-type", "Feat"),
        ("--questions", "--yes"),
    ],
    ids=[
        "name",
        "branch",
        "branch-git-refuses",
        "branch-head",
        "not-eligible",
        "mode",
        "profile",
        "agent",
        "commit-type",
        "questions-and-yes",
    ],
)
def test_the_parser_refuses_an_answer_outside_its_grammar_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    # A name or a branch is refused naming the rule and never the value, which is text a
    # person may have pasted from anywhere; a choice is refused by `choices`, whose error quotes
    # only the operator's own argument. `--profile` takes only the names this build ships.
    # Mutations (oracle): `mutations/`'s "a flag's grammar takes a value outside it as typed:
    # gate --base a short name a tag answers for, init an answer" -> `name` and `branch` redden;
    # "--local takes a file no gate can do without" -> `not-eligible` reddens. (By hand: `--profile`
    # without `choices` -> `profile` reddens with no `SystemExit`: the name reaches `init`, and only
    # the profile loader refuses it, after the parser.)
    root = repository(tmp_path)
    with pytest.raises(SystemExit):
        _invoke(root, tmp_path, *argv)
    err = capsys.readouterr().err
    assert "Not A Name" not in err
    # The rule in words, never the pattern: Python's `\Z` reads as nothing to a person.
    # Mutation (oracle): `mutations/`'s "the --name refusal prints the pattern" -> `name` reddens.
    assert "\\Z" not in err
    if "--name" in argv:
        assert NAME_RULE in err
    assert not (root / ".stayfixed").exists() and not (root / "stayfixed.toml").exists()


@needs_git
def test_an_answer_over_a_document_the_user_wrote_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Answers reach only a document this run creates; a `stayfixed.toml` already there is the
    # answer, so a flag over it would be silently dropped. Mutation (oracle): `mutations/`'s "an
    # answer overrides a stayfixed.toml the user wrote" -> the first run adopts the file and exits
    # 0.
    root = repository(tmp_path)
    (root / "stayfixed.toml").write_text(DOCUMENT, encoding="utf-8")
    before = snapshot(root)
    code, printed = _invoke(root, tmp_path, "--yes", "--name", "other")
    assert code == 2 and printed == ""
    assert "already has a stayfixed.toml" in capsys.readouterr().err
    code, printed = _invoke(root, tmp_path, "--name", "other")
    assert code == 2 and printed == ""
    assert "--yes" in capsys.readouterr().err
    assert_snapshot_unchanged(root, before)


@needs_git
def test_a_refused_adoption_says_its_version_would_be_written(tmp_path: Path) -> None:
    # A refused run writes nothing, the stamp included, so its note must not say "wrote".
    # A directory at `CLAUDE.md` is refused by the write-once pass. Mutation (oracle):
    # `mutations/`'s "a refused adoption reports its version stamp as written".
    root = repository(tmp_path)
    hand_written = '[project]\nname = "widget"\n'
    (root / "stayfixed.toml").write_text(hand_written, encoding="utf-8")
    (root / "CLAUDE.md").mkdir()
    code, printed = _invoke(root, tmp_path, "--yes")
    assert code == 1, printed
    assert STAMPED.format(verb="would write") in printed
    assert STAMPED.format(verb="wrote") not in printed
    assert (root / "stayfixed.toml").read_text(encoding="utf-8") == hand_written
    assert not (root / ".stayfixed" / "manifest.json").exists()


@needs_git
def test_uninstall_says_it_keeps_a_stayfixed_toml_you_wrote(tmp_path: Path) -> None:
    # An adopted file is recorded nowhere, so no report line named it, and it stays with the
    # version `init` added. The note says so. Mutation (by hand): the note dropped -> no line.
    root = repository(tmp_path)
    (root / "stayfixed.toml").write_text(DOCUMENT, encoding="utf-8")
    code, printed = _invoke(root, tmp_path, "--yes")
    assert code == 0, printed
    code, out, err = cli(root, tmp_path, "uninstall", "--dry-run")
    assert code == 0, err
    assert f"note: {KEPT_CONFIG}" in out.splitlines()
    code, out, err = cli(root, tmp_path, "uninstall", "--json")
    assert code == 0, err
    assert json.loads(out)["kept_config"] is True
    assert (root / "stayfixed.toml").is_file()


@needs_git
def test_an_adopted_document_without_a_version_is_named_in_a_note(tmp_path: Path) -> None:
    # The one line `init` writes into a file a person wrote is said, in the text and in
    # `--json`. Mutation (oracle): `mutations/`'s "an adopted document's added version goes
    # unmentioned".
    root = repository(tmp_path)
    (root / "stayfixed.toml").write_text('[project]\nname = "widget"\n', encoding="utf-8")
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run")
    assert code == 0, printed
    assert STAMPED.format(verb="would write") in printed
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--json")
    assert json.loads(printed)["stamped"] is True


@needs_git
def test_a_branch_with_a_slash_and_a_dot_is_a_base_branch_the_parser_takes(tmp_path: Path) -> None:
    # The branch grammar follows git's own rules, which a release branch meets: tightening it
    # must not refuse `release/2.0`. Mutation (by hand): refuse every `.` or `/` -> this reddens.
    root = repository(tmp_path)
    code, printed = _invoke(root, tmp_path, "--yes", "--dry-run", "--base-branch", "release/2.0")
    assert code == 0, printed
