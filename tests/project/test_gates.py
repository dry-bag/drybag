"""A bare repository `init --yes` has just written passes every check.

The fixture guard beside this one says planning over the committed fixture has nothing left to
create; this one says the templates render a project the checks accept, which is a different claim
and the one a first adopter meets. The five invocations are the five checks, driven through their
own commands and the real parser the way `tests/test_fixtures.py` drives them.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from stayfixed.cli import build_parser, discover_registrars, run
from stayfixed.project.init import init
from tests.gitfixture import git, needs_git

GATES = (
    ["docs", "check"],
    ["bugs", "check"],
    ["docs", "trail", "--check"],
    ["plan", "check", "--base", "HEAD~1"],
    ["commit", "check", "--range", "HEAD~1..HEAD"],
)


def _initialised(tmp_path: Path) -> Path:
    """A bare repository, initialised in process, then committed twice.

    Two commits, for `tests/test_fixtures.py`'s reason: `commit check
    --range HEAD~1..HEAD` over an empty range checks one message rather than none, and the
    second commit touches a real file so the range is not empty.
    """
    root = tmp_path / "fresh"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", "git@github.com:owner/fresh.git")
    init(
        root,
        machine=tmp_path / "absent.toml",
        yes=True,
        dry_run=False,
    )
    git(root, "add", "-A")
    git(root, "commit", "-qm", "chore: initialise stayfixed")
    history = root / "docs" / "roadmap-history.md"
    history.write_text(
        history.read_text(encoding="utf-8") + "\nA line the second commit adds.\n",
        encoding="utf-8",
    )
    git(root, "add", "-A")
    git(root, "commit", "-qm", "docs: a second one")
    return root


def _invoke(root: Path, tmp_path: Path, argv: list[str]) -> tuple[int, str]:
    parser = build_parser(discover_registrars())
    flags = ["--root", str(root), "--machine", str(tmp_path / "absent.toml")]
    with redirect_stdout(io.StringIO()) as out:
        code = run([*argv, *flags], parser=parser)
    return code, out.getvalue()


@needs_git
@pytest.mark.parametrize("argv", GATES, ids=lambda argv: " ".join(argv))
def test_every_gate_the_workflow_runs_passes_on_a_freshly_initialised_repository(
    tmp_path: Path, argv: list[str]
) -> None:
    # The from-scratch half of what the fixture guard beside this one holds, and the one that would
    # catch a template the gates reject: the captured trail block is held green by `docs trail
    # --check` here, an `AGENTS.md` skeleton over its budget would fail `docs check`, and a
    # `docs/bugs/` with an audits directory and a rendered index is what keeps `bugs check` out of
    # its inert arm.
    root = _initialised(tmp_path)
    code, printed = _invoke(root, tmp_path, argv)
    assert code == 0, printed


@needs_git
def test_the_bug_ledger_gate_is_not_merely_inert_on_a_fresh_project(tmp_path: Path) -> None:
    # `bugs check` exits 0 two ways: having judged an initialised ledger, and having found none
    # to judge. The row above cannot tell them apart, and "the footprint passes the gates"
    # means the first.
    #
    # Measured on this tree, both halves, because the footprint's two ledger artifacts fail
    # differently: with `ledger-audits` dropped from `project_templates` the ledger directory
    # is gone while the generated index remains, `bugs check` reports `entries-missing` and
    # exits 1 — so the row above catches that one. With `bug-index` dropped as well there is
    # neither, `bugs check` takes its inert arm, reports `{"checked": false}` and exits 0, and
    # the row above stays green. That second state is what this test exists for: the only
    # observable difference is the field asserted here.
    import json

    root = _initialised(tmp_path)
    code, printed = _invoke(root, tmp_path, ["bugs", "check", "--json"])
    assert code == 0, printed
    assert json.loads(printed)["checked"] is True
