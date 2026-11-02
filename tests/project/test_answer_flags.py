"""`stayfixed init --yes`'s answers: each reaches the document this run creates, a fresh
repository gates the branch it chose, and every file `--local` offers leaves every check green.

The answers are given here as `Given` straight to `init`; `tests/project/test_command.py` gives
them as flags through the real parser, built from `init --questions --json`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import stayfixed
from stayfixed.config.loader import CONFIG_FILE, load, preset_defaults
from stayfixed.docs.hygiene import docs_gate
from stayfixed.docs.plans import lint
from stayfixed.docs.trail import trail_gate
from stayfixed.guards.commit import check_range
from stayfixed.ledger.check import bugs_gate
from stayfixed.project.init import Given, InitReport, init
from stayfixed.project.templates import LOCAL_ELIGIBLE
from stayfixed.scaffold import Verb
from stayfixed.scaffold.local import LOCAL_ARTIFACTS
from tests.gitfixture import git, needs_git
from tests.project.repos import repository
from tests.runners import LsRemote

SHA = "c" * 40
# A released tag at the running version, so a pin resolves and the caller is rendered.
LISTING = f"{SHA}\trefs/tags/v{stayfixed.__version__}\n"
# A ref an adopted document already records, deliberately not the one the listing resolves.
ADOPTED = "a" * 40
FOREIGN = "bytes a person wrote before stayfixed\n"
WORKFLOW = Path(".github") / "workflows" / "stayfixed.yml"


def _init(
    root: Path,
    tmp_path: Path,
    given: Given,
    *,
    runner: LsRemote | None = None,
    ci: bool = False,
) -> InitReport:
    return init(
        root,
        machine=tmp_path / "absent.toml",
        runner=runner or LsRemote(),
        yes=True,
        dry_run=False,
        ci=ci,
        given=given,
    )


def _commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD").strip()


@needs_git
@pytest.mark.parametrize("artifact_id", LOCAL_ELIGIBLE)
def test_every_file_offered_as_local_leaves_every_gate_green(
    tmp_path: Path, artifact_id: str
) -> None:
    # `--local` offers a file only if a project may keep it out of git with every check still
    # passing. Two commits, as `tests/project/test_gates.py` makes them, so the commit check reads
    # one message rather than an empty range. Mutation (oracle): `mutations/`'s "a file a gate reads
    # at its committed path is offered as local" adds `bug-index`, whose case is then red here: the
    # index is kept out of git and `bugs check` reads it at its committed path.
    root = repository(tmp_path)
    _init(root, tmp_path, Given(local=(artifact_id,)))
    kept = [p for p in (root / LOCAL_ARTIFACTS).rglob("*") if p.is_file()]
    assert len(kept) == 1, kept
    base = _commit(root, "chore: initialise stayfixed")
    (root / "README.md").write_text("# widget\n\nA line the second commit adds.\n")
    _commit(root, "docs: say what widget is")
    config = load(root, machine=tmp_path / "absent.toml")
    found = {
        "docs": docs_gate(root, config),
        "trail": trail_gate(root, config),
        "bugs": bugs_gate(root, config, base),
        "plan": lint(root, config, plans=[], base=base).findings,
        "commit": list(check_range(root, f"{base}..HEAD", config).violations),
    }
    assert found == {name: [] for name in found}


@needs_git
def test_each_answer_reaches_the_document_this_run_creates(tmp_path: Path) -> None:
    # Each flag replaces one default. Mutation (by hand): `_tables` ignores `given.agents` ->
    # the agents assertion reddens (the repository carries no harness directory, so the
    # default is both).
    root = repository(tmp_path)
    _init(
        root,
        tmp_path,
        Given(
            name="gadget",
            base_branch="develop",
            agents=("codex",),
            memory_mode="in-repo",
            local=("roadmap-history",),
        ),
    )
    config = load(root, machine=tmp_path / "absent.toml")
    assert config.project.name == "gadget"
    assert (config.project.base_branch, config.project.release_branch) == ("develop", "develop")
    assert config.stayfixed.agents == ("codex",)
    assert config.memory.mode == "in-repo"
    assert config.artifacts.local == ("roadmap-history",)


@needs_git
@pytest.mark.parametrize(
    ("profile", "markers", "expected"),
    [("python", False, "python"), ("", True, "")],
    ids=["named", "none-over-markers"],
)
def test_a_profile_answer_replaces_what_the_markers_suggest(
    tmp_path: Path, profile: str, markers: bool, expected: str
) -> None:
    # `""` is an answer: no profile, even where the root carries a shipped profile's markers.
    # Mutation (by hand): `profile = given.profile or found.profile` -> the `none-over-markers`
    # case writes `python` and reddens.
    root = repository(tmp_path)
    if markers:
        (root / "pyproject.toml").write_text("[project]\nname = 'widget'\n", encoding="utf-8")
    _init(root, tmp_path, Given(profile=profile))
    assert load(root, machine=tmp_path / "absent.toml").stayfixed.profile == expected


@needs_git
@pytest.mark.parametrize("how", ["answered", "detected", "main"])
def test_a_fresh_repository_gates_the_branch_it_chose(tmp_path: Path, how: str) -> None:
    # The rendered caller runs only for pull requests into `[ci] gate_branch`, so a fresh
    # `develop` repository whose file left that key at the preset's `main` got a workflow that
    # ran for none of its own pull requests, and a required check that stayed pending. Mutation
    # (oracle): "a fresh repository's caller gates the preset's branch, not its own" -> the
    # `answered` and `detected` cases redden.
    root = repository(tmp_path)
    given = Given(base_branch="develop") if how == "answered" else Given()
    if how == "detected":
        git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
    branch = "main" if how == "main" else "develop"
    report = _init(root, tmp_path, given, runner=LsRemote(stdout=LISTING), ci=True)
    assert report.ref == SHA
    config = load(root, machine=tmp_path / "absent.toml")
    chosen = (config.project.base_branch, config.project.release_branch, config.ci.gate_branch)
    assert chosen == (branch,) * 3
    workflow = (root / WORKFLOW).read_text(encoding="utf-8")
    assert workflow.count(f'branches: ["{branch}"]') == 3
    assert f'base: "{branch}"' in workflow
    # `gate_branch` is never written: left out, the loader takes it from `base_branch`, so a
    # `main` repository's file is the one it always was and a `develop` one's follows its base.
    assert "gate_branch" not in (root / CONFIG_FILE).read_text(encoding="utf-8")


@needs_git
@pytest.mark.parametrize(
    ("ci_table", "gated"),
    [("", "develop"), ('gate_branch = "main"\n', "main")],
    ids=["left-out", "chosen"],
)
def test_an_adopted_document_s_workflow_gates_the_branch_its_file_names(
    tmp_path: Path, ci_table: str, gated: str
) -> None:
    # A `stayfixed.toml` a person wrote, whose base branch is `develop`. Left out, `[ci]
    # gate_branch` is that base branch: a fixed `main` rendered a caller that never ran for a
    # pull request into `develop`, while `plan check` judged against `develop`,
    # and nothing said so. Written out, it is the person's choice and is kept. The file comes
    # back byte for byte either way. Mutation (oracle): `mutations/`'s "a document that leaves [ci]
    # gate_branch out gates main, not its base branch" -> the `left-out` case reddens.
    root = repository(tmp_path)
    hand_written = (
        f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n'
        '[project]\nname = "widget"\nbase_branch = "develop"\n\n'
        f'[ci]\nref = "{ADOPTED}"\n{ci_table}'
    )
    (root / CONFIG_FILE).write_text(hand_written, encoding="utf-8")
    report = _init(root, tmp_path, Given(), runner=LsRemote(stdout=LISTING), ci=True)
    assert report.adopted and report.ref == ADOPTED
    assert (root / CONFIG_FILE).read_text(encoding="utf-8") == hand_written
    assert load(root, machine=tmp_path / "absent.toml").ci.gate_branch == gated
    workflow = (root / WORKFLOW).read_text(encoding="utf-8")
    assert workflow.count(f'branches: ["{gated}"]') == 3 and f'base: "{gated}"' in workflow


@needs_git
def test_an_answered_local_copy_never_overwrites_a_file_already_at_its_place(
    tmp_path: Path,
) -> None:
    # A file already at a kept copy's place is a person's, or another tool's: create-once
    # reports it `skip_modified` and leaves its bytes. Not a footprint-invariant row: that
    # matrix's I3 ("a dry-run `upgrade` plans nothing") would list this `skip_modified` by design.
    root = repository(tmp_path)
    copy = root / LOCAL_ARTIFACTS / preset_defaults("widget").paths.roadmap_history
    copy.parent.mkdir(parents=True)
    copy.write_text(FOREIGN, encoding="utf-8")
    report = _init(root, tmp_path, Given(local=("roadmap-history",)))
    assert not report.refused
    verbs = {a.verb for a in report.footprint.actions if a.artifact_id == "roadmap-history"}
    assert verbs == {Verb.SKIP_MODIFIED}
    assert copy.read_text(encoding="utf-8") == FOREIGN
