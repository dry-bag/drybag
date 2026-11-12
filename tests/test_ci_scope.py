"""The `changes` job of `ci.yml` and `smoke.yml`: what a change reaches, and the jobs that read it.

A pull request that changes only documents, or Python comments, runs the suite on one leg and skips
the other legs, the oracle, the demo, the plugin validator and the install smoke. That is a
narrowing, so it must be said in so many words: the scope step answers `false` only when
`scripts/ci_scope.py` finds every path the merge commit changes against its first parent to be one
of those, and every job that reads it treats any other answer, or none, as a change to code. The
step runs here as shipped, under `bash -e`, against a real merge commit; the wiring is read by
`tests.workflow_yaml`'s strict reader.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests import gitfixture
from tests.floor import developer_free_environ
from tests.gitfixture import git, needs_git
from tests.test_fixtures import (
    CI_WORKFLOW,
    SMOKE_WORKFLOW,
    needs_bash,
    needs_ci_workflow,
    needs_smoke_workflow,
    step_script,
)
from tests.workflow_yaml import Node, load

SCOPE = "Whether the change reaches code"
GATE = "env.FULL == 'true'"
NARROWED = "${{ !cancelled() && needs.changes.outputs.code != 'false' }}"
CHECKS_FULL = (
    "${{ needs.changes.outputs.code != 'false'"
    " || matrix.os == 'ubuntu-latest' && matrix.python == '3.13' }}"
)
SMOKE_FULL = "${{ needs.changes.outputs.code != 'false' }}"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci_scope.py"
WIDGET = 'def widget():\n    """Make a widget."""\n    return 1\n'


def _jobs(workflow: Path) -> dict[str, dict[str, Node]]:
    document = load(workflow.read_text(encoding="utf-8"))
    assert isinstance(document, dict), document
    jobs = document["jobs"]
    assert isinstance(jobs, dict), jobs
    return {name: job for name, job in jobs.items() if isinstance(job, dict)}


def _merge(
    tmp_path: Path,
    change: dict[str, str | None],
    renames: dict[str, str],
    then: Callable[[Path], object] = Path,
) -> Path:
    """A repository whose `HEAD` is a merge commit, as the platform checks a pull request out: the
    first parent is the base, the second a branch that writes `change` (`None` deletes) and moves
    each `renames` key to its value. The base moves on beside it, so the merge is a real one."""
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q", "-b", "base")
    for path in ("docs/guide.md", "docs/old.md", "README.md"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(f"{path}\n" * 20, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "widget.py").write_text(WIDGET, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "checkout", "-q", "-b", "change")
    for path, text in change.items():
        if text is None:
            git(root, "rm", "-q", path)
        else:
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(text.encode("utf-8"))
            git(root, "add", path)
    for old, new in renames.items():
        (root / new).parent.mkdir(parents=True, exist_ok=True)
        git(root, "mv", old, new)
    then(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", "change")
    git(root, "checkout", "-q", "base")
    (root / "LICENSE").write_text("moved on\n", encoding="utf-8")
    git(root, "add", "LICENSE")
    git(root, "commit", "-q", "-m", "base moves on")
    git(root, "merge", "-q", "--no-ff", "--no-edit", "change")
    # The step runs the script from the checkout, as the workflow does; untracked, it changes no
    # commit the step compares.
    (root / "scripts").mkdir(exist_ok=True)
    shutil.copy(SCRIPT, root / "scripts" / "ci_scope.py")
    return root


def _scope(root: Path, event: str) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    output = root.parent / "output"
    output.unlink(missing_ok=True)
    environ = {
        **developer_free_environ(),
        **gitfixture.env(root.parent),
        "EVENT": event,
        "GITHUB_OUTPUT": str(output),
    }
    done = subprocess.run(
        ["bash", "-e", "-c", step_script(CI_WORKFLOW, SCOPE)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=environ,
    )
    written = output.read_text(encoding="utf-8") if output.is_file() else ""
    return done, dict(line.split("=", 1) for line in written.splitlines())


@needs_ci_workflow
@needs_smoke_workflow
def test_both_workflows_run_one_scope_step() -> None:
    # `smoke.yml` cannot read `ci.yml`'s job, so it carries its own; the two may not drift.
    assert step_script(SMOKE_WORKFLOW, SCOPE) == step_script(CI_WORKFLOW, SCOPE)


@needs_git
@needs_bash
@needs_ci_workflow
@pytest.mark.parametrize(
    ("change", "renames", "code"),
    [
        pytest.param({"docs/guide.md": "edited\n"}, {}, "false", id="a-document-edited"),
        pytest.param({"docs/new.md": "new\n"}, {}, "false", id="a-document-added"),
        pytest.param({"docs/old.md": None}, {}, "false", id="a-document-deleted"),
        # Mutation (oracle): `mutations/`'s "the scope step asks whether any path is a document".
        pytest.param(
            {"docs/guide.md": "edited\n", "src/widget.py": "edited\n"},
            {},
            "true",
            id="a-document-and-code",
        ),
        pytest.param({"README.md": "edited\n"}, {}, "false", id="a-markdown-file-at-the-root"),
        pytest.param({"CHANGELOG.md": "new\n"}, {}, "false", id="the-changelog"),
        pytest.param({"changelog.d/+x.fix.md": "new\n"}, {}, "false", id="a-changelog-fragment"),
        # The plugin validator reads a skill's frontmatter. Mutation (oracle): `mutations/`'s
        # "Markdown anywhere counts as a document".
        pytest.param({"skills/x/SKILL.md": "new\n"}, {}, "true", id="a-skill"),
        # Mutation (oracle): `mutations/`'s "a comment counts as code".
        pytest.param(
            {"src/widget.py": "# Widgets.\n" + WIDGET.replace("1\n", "1  # one\n")},
            {},
            "false",
            id="python-comments-alone",
        ),
        pytest.param(
            {"src/widget.py": "# Widgets.\n", "docs/guide.md": "edited\n"},
            {},
            "true",
            id="python-comments-and-code-removed",
        ),
        pytest.param(
            {"src/widget.py": WIDGET.replace("return 1", "return 2")}, {}, "true", id="python-code"
        ),
        # A docstring is a string the program can read. Mutation (oracle): `mutations/`'s "a
        # docstring counts as a comment".
        pytest.param(
            {"src/widget.py": WIDGET.replace("Make", "Build")}, {}, "true", id="a-docstring"
        ),
        pytest.param({"src/new.py": "# nothing yet\n"}, {}, "true", id="a-python-file-added"),
        pytest.param({"docs/new.py": "# nothing yet\n"}, {}, "true", id="python-under-docs"),
        pytest.param(
            {"src/widget.py": WIDGET + '"""\n'}, {}, "true", id="python-that-does-not-tokenize"
        ),
        # The rename lists only `docs/widget.py` without `--no-renames`, and the code it took away
        # would go unjudged. Mutation (oracle): `mutations/`'s "a rename into docs hides the file
        # it moved".
        pytest.param({}, {"src/widget.py": "docs/widget.py"}, "true", id="code-moved-into-docs"),
        # Read with `-z`, a name outside ASCII is the name it is.
        pytest.param({"docs/résumé.md": "new\n"}, {}, "false", id="a-name-outside-ascii"),
        # Mutation (oracle): `mutations/`'s "an empty change narrows the run".
        pytest.param({}, {}, "true", id="nothing-changed"),
    ],
)
def test_the_scope_step_answers_false_only_for_documents_and_comments(
    tmp_path: Path, change: dict[str, str | None], renames: dict[str, str], code: str
) -> None:
    done, outputs = _scope(_merge(tmp_path, change, renames), "pull_request")
    assert done.returncode == 0, done.stdout + done.stderr
    assert outputs == {"code": code}, outputs


@needs_git
@needs_bash
@needs_ci_workflow
@pytest.mark.parametrize(
    "then",
    [
        pytest.param(lambda r: (r / "src/widget.py").chmod(0o755), id="a-mode-change"),
        pytest.param(lambda r: (r / "docs/guide.md").chmod(0o755), id="an-executable-under-docs"),
        pytest.param(lambda r: (r / "docs/link.md").symlink_to("guide.md"), id="a-symlink"),
    ],
)
def test_a_mode_or_link_change_is_code(tmp_path: Path, then: Callable[[Path], object]) -> None:
    # A link, an executable or a mode the plugin tree records is code whatever its text. Mutation
    # (oracle): `mutations/`'s "the scope step reads no modes".
    done, outputs = _scope(_merge(tmp_path, {}, {}, then), "pull_request")
    assert done.returncode == 0, done.stdout + done.stderr
    assert outputs == {"code": "true"}, outputs


@needs_git
@needs_bash
@needs_ci_workflow
def test_a_push_reaches_everything_whatever_it_changed(tmp_path: Path) -> None:
    done, outputs = _scope(_merge(tmp_path, {"docs/guide.md": "edited\n"}, {}), "push")
    assert done.returncode == 0, done.stdout + done.stderr
    assert outputs == {"code": "true"}, outputs


@needs_git
@needs_bash
@needs_ci_workflow
def test_a_checkout_with_no_first_parent_fails_the_step_and_answers_nothing(
    tmp_path: Path,
) -> None:
    # A shallow checkout that lost the base, or a commit that has none: the step fails, writes no
    # answer, and every job reading it runs whole.
    root = tmp_path / "repository"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "only")
    done, outputs = _scope(root, "pull_request")
    assert done.returncode != 0, done.stdout + done.stderr
    assert outputs == {}, outputs


@needs_ci_workflow
@needs_smoke_workflow
def test_every_job_that_reads_the_scope_runs_whole_on_any_answer_but_false() -> None:
    # `!cancelled()` runs a job whose `changes` failed, which `needs` alone would skip and report
    # as a success; `!= 'false'` turns the empty answer of a failed `changes` into a full run.
    # Mutation (oracle): `mutations/`'s "the install smoke narrows on an answer that is not false",
    # "every checks leg narrows on a change to docs" and "a failed scope job skips the oracle".
    ci, smoke = _jobs(CI_WORKFLOW), _jobs(SMOKE_WORKFLOW)
    assert [name for name in ci if "needs" not in ci[name]] == ["changes"]
    assert [name for name in smoke if "needs" not in smoke[name]] == ["changes"]
    for job in (ci["oracle"], ci["plugin"], ci["demo"]):
        assert job["needs"] == "changes" and job["if"] == NARROWED, job
    for job, full in ((ci["checks"], CHECKS_FULL), (smoke["installed-plugin"], SMOKE_FULL)):
        assert job["needs"] == "changes", job
        guard = job["if"]
        assert isinstance(guard, str) and guard.startswith("${{ !cancelled()"), guard
        assert job["env"] == {"FULL": full}, job["env"]
        steps = job["steps"]
        assert isinstance(steps, list) and steps, job
        assert all(isinstance(step, dict) and step.get("if") == GATE for step in steps), steps


@needs_ci_workflow
def test_the_leg_that_runs_on_a_change_to_docs_is_a_leg_of_the_matrix() -> None:
    # A `FULL` naming a leg the matrix lacks would skip the suite on every leg.
    strategy = _jobs(CI_WORKFLOW)["checks"]["strategy"]
    assert isinstance(strategy, dict), strategy
    matrix = strategy["matrix"]
    assert isinstance(matrix, dict), matrix
    legs = matrix["include"]
    assert isinstance(legs, list), legs
    assert {"os": "ubuntu-latest", "python": "3.13"} in legs, legs
