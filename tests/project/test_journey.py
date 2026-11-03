"""The whole path a person takes onto stayfixed, run as one scenario through the real parser: the
questions, `init --yes` with an answer, an adoption design and plan with an accurate trail, and an
`upgrade` that keeps a hand edit.

Each command's own tests hold one guard each. What none of them holds is the composition: that
the repository one command leaves is one every later command accepts, on a base branch that is
not `main`. A failure here is a defect between commands, not a reason to weaken a step.

Nothing reaches the network. The runner the CLI builds is stubbed for the whole scenario at the
seam `tests/project/test_command.py` stubs (`stayfixed.runner.subprocess_runner`).

Neither scenario declares a mutation. Every guard it composes has its own entry against the
narrower test that states it, and a scenario that one mutation reddens proves less than those do.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest

import stayfixed
from stayfixed.config.loader import CONFIG_FILE, load, preset_defaults
from stayfixed.project.templates import CONFIG_ARTIFACT
from stayfixed.scaffold import Manifest, digest
from tests.cli import cli
from tests.gitfixture import git, needs_git
from tests.project.repos import repository
from tests.runners import Recorder
from tests.snapshot import assert_snapshot_unchanged, snapshot

pytestmark = needs_git

PATHS = preset_defaults("widget").paths
DATE = "2026-09-26"
DESIGN = f"{PATHS.specs}/{DATE}-stayfixed-adoption-design.md"
PLAN = f"{PATHS.plans}/{DATE}-stayfixed-adoption.md"
TRAIL = f"{PurePosixPath(PATHS.roadmap).parent}/trail.toml"
# The one policy file a person is most likely to rewrite, and a whole-file template.
POLICY = "documentation-policy"


@pytest.fixture
def released(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    """The runner every command builds."""
    from stayfixed import runner as runner_module

    stub = Recorder()
    monkeypatch.setattr(runner_module, "subprocess_runner", lambda **_: stub)
    return stub


def _fresh_develop_repository(tmp_path: Path) -> Path:
    """A repository on `develop` whose `origin/HEAD` names `develop`, with a README committed."""
    root = repository(tmp_path)
    git(root, "symbolic-ref", "HEAD", "refs/heads/develop")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "chore: first")
    git(root, "update-ref", "refs/remotes/origin/develop", "HEAD")
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
    return root


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_fresh_non_main_repository_goes_from_its_answers_to_an_upgrade_that_keeps_a_hand_edit(
    tmp_path: Path, released: Recorder
) -> None:
    # 1-2. The questions: the base branch is the one `origin/HEAD` names, not `main`.
    root = _fresh_develop_repository(tmp_path)
    code, out, err = cli(root, tmp_path, "init", "--questions", "--json")
    assert code == 0, err
    asked = json.loads(out)["questions"]["properties"]
    assert asked["project.base_branch"]["default"] == "develop"
    assert asked["project.base_branch"]["x-stayfixed-source"] == "origin/HEAD"

    # 3. `init --yes` with one answer; commit it all.
    code, out, err = cli(root, tmp_path, "init", "--yes", "--name", "widget")
    assert code == 0, out + err
    git(root, "add", "-A")
    git(root, "commit", "-qm", "chore: stayfixed init")

    # 4. The adoption's design and plan, with a state each in the trail, staged before the trail
    # is rewritten because it lists tracked files only.
    _write(root, DESIGN, "# stayfixed adoption\n\nWhat the project adopts, and why.\n")
    _write(root, PLAN, "# stayfixed adoption\n\n**Scope:** the gates.\n\n**Premise:** none.\n")
    trail = (root / TRAIL).read_text(encoding="utf-8")
    rows = [f"{PurePosixPath(p).parent.name}/{PurePosixPath(p).name}" for p in (DESIGN, PLAN)]
    _write(root, TRAIL, trail + "".join(f'"{row}" = "in progress"\n' for row in rows))
    git(root, "add", "-A")
    code, out, err = cli(root, tmp_path, "docs", "trail")
    assert code == 0, out + err
    code, out, err = cli(root, tmp_path, "docs", "trail", "--check")
    assert code == 0, out + err
    # Accurate, not only current: the first documents a listing ever holds are not reported
    # when they carry no state, and would read `delivered` before anything was built.
    roadmap = (root / PATHS.roadmap).read_text(encoding="utf-8")
    for row in rows:
        assert f"[`{row}`]" in roadmap and f"{row}) — in progress" in roadmap, roadmap
    code, out, err = cli(root, tmp_path, "plan", "check", str(root / PLAN))
    assert code == 0, out + err
    git(root, "add", "-A")
    git(root, "commit", "-qm", "docs: the stayfixed adoption design and plan")

    # 5. A hand edit to a whole-file template survives an upgrade, planned and real.
    record = Manifest.read(root).get(POLICY)
    assert record is not None
    policy = root / record.target
    edited = policy.read_text(encoding="utf-8") + "\nOur own rule.\n"
    policy.write_text(edited, encoding="utf-8")
    code, out, err = cli(root, tmp_path, "upgrade", "--dry-run")
    assert code == 0, out + err
    assert f"skip_modified  {record.target}  " in out, out
    code, out, err = cli(root, tmp_path, "upgrade")
    assert code == 0, out + err
    assert policy.read_text(encoding="utf-8") == edited

    # What a person sees at the end.
    config = load(root, machine=tmp_path / "absent.toml")
    assert config.project.base_branch == "develop"
    assert config.project.release_branch == "develop"
    for argv in (("docs", "check"), ("docs", "trail", "--check")):
        code, out, err = cli(root, tmp_path, *argv)
        assert code == 0, (argv, out + err)
    config_record = Manifest.read(root).get(CONFIG_ARTIFACT)
    assert config_record is not None
    on_disk = (root / CONFIG_FILE).read_text(encoding="utf-8")
    assert config_record.sha256 == digest(on_disk)


def test_a_versionless_answer_sheet_goes_through_the_same_confirmation(
    tmp_path: Path, released: Recorder
) -> None:
    # The other way in: a `stayfixed.toml` the user wrote, with `[project]` and no version. It
    # meets the same dry run and the same refusal as an answered run, and the one line `init`
    # adds to it is the version. The sheet carries a `[stayfixed]` table of its own, so that line
    # has a table to go into; one without it gains the table's header too.
    root = repository(tmp_path)
    sheet = '[stayfixed]\nagents = ["claude"]\n\n[project]\nname = "widget"\n'
    (root / CONFIG_FILE).write_text(sheet, encoding="utf-8")
    before = snapshot(root)

    code, out, err = cli(root, tmp_path, "init", "--yes", "--dry-run")
    assert code == 0, out + err
    assert "this run would write it" in out, out
    assert_snapshot_unchanged(root, before)

    (root / "CLAUDE.md").mkdir()
    blocked = snapshot(root)
    code, out, err = cli(root, tmp_path, "init", "--yes")
    assert code == 1, out + err
    assert out.startswith("refused, and nothing was written:"), out
    assert "this run would write it" in out, out
    assert_snapshot_unchanged(root, blocked)

    (root / "CLAUDE.md").rmdir()
    code, out, err = cli(root, tmp_path, "init", "--yes")
    assert code == 0, out + err
    assert "this run wrote it" in out, out
    written = (root / CONFIG_FILE).read_text(encoding="utf-8")
    added = [line for line in written.splitlines() if line not in sheet.splitlines()]
    assert added == [f'version = "{stayfixed.__version__}"'], added
    kept = [line for line in written.splitlines() if line not in added]
    assert kept == sheet.splitlines(), kept
    # The stamped file loads.
    assert load(root, machine=tmp_path / "absent.toml").stayfixed.version == stayfixed.__version__
