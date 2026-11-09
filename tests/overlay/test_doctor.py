"""What the `pre-commit` and `overlay-requires` rows in `drybag doctor` answer, now that
`overlay` contributes them.

Every case runs the whole report through `run_checks`, so the rows are asked the way a user's
`drybag doctor` asks them: discovered in this area's `doctor.py`, with the overlay root resolved
by the lazy value its `register()` creates. The fixtures are the doctor area's own
(`tests/doctor/test_checks.py`), shared rather than respelled.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import drybag
from drybag.config.overlay import overlay_root
from drybag.doctor.api import OK, RED, SKIP, WARN
from drybag.overlay.layout import IDENTITY_RECORD
from tests.doctor.test_checks import (
    OVERLAY,
    _attached,
    _by_name,
    _checks,
    _initialised,
    _machine,
)
from tests.gitfixture import git as _git
from tests.overlay.test_requires import overlay_with

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def test_the_overlays_secret_scan_is_reported_when_it_is_not_installed(tmp_path: Path) -> None:
    # The overlay holds the machine owner's own notes, so its commit-time secret scan is
    # the one that matters. `setup --overlay` installs it on the machine that made the overlay
    # and never on a second one that cloned it and only recorded it.
    root = _attached(tmp_path)
    (tmp_path / "overlay" / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    checks = _checks(tmp_path, root, machine=_machine(tmp_path))
    assert _by_name(checks, "pre-commit").status == "warn"
    (tmp_path / "overlay" / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "overlay" / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n")
    checks = _checks(tmp_path, root, machine=_machine(tmp_path))
    assert _by_name(checks, "pre-commit").status == "ok"


def test_the_overlays_hook_is_found_where_git_says_it_is_and_not_under_dot_git(
    tmp_path: Path,
) -> None:
    # `core.hooksPath` is an ordinary global dotfiles setting, and a worktree or submodule
    # overlay keeps `.git` as a *file*. Against either, a hardcoded `.git/hooks/pre-commit`
    # warns permanently with a remedy that cannot clear it — the reader runs `pre-commit
    # install`, it succeeds, and the row stays yellow. `docs/cli.md` states the rule this
    # follows: `git rev-parse --git-path hooks`, never `core.hooksPath`.
    root = _attached(tmp_path)
    overlay = tmp_path / "overlay"
    (overlay / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    hooks = tmp_path / "dotfiles" / "hooks"
    hooks.mkdir(parents=True)
    _git(overlay, "config", "core.hooksPath", str(hooks))
    checks = _checks(tmp_path, root, machine=_machine(tmp_path))
    assert _by_name(checks, "pre-commit").status == "warn"
    (hooks / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    checks = _checks(tmp_path, root, machine=_machine(tmp_path))
    assert _by_name(checks, "pre-commit").status == "ok"


def test_an_overlay_git_cannot_answer_about_is_a_warning_and_never_a_red_row(
    tmp_path: Path,
) -> None:
    # `hooks_dir` refuses when `git` cannot name the directory. `_guarded` would turn that into
    # a red row naming an exception type, which says nothing a reader can act on; the row says
    # what could not be asked instead. Reached by taking the repository away, which is the
    # cheapest state `rev-parse` cannot answer in.
    root = _attached(tmp_path)
    overlay = tmp_path / "overlay"
    (overlay / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    shutil.rmtree(overlay / ".git")
    check = _by_name(_checks(tmp_path, root, machine=_machine(tmp_path)), "pre-commit")
    assert check.status == "warn"
    assert "hooks directory" in check.detail


def _recorded_overlay(tmp_path: Path, requires: object) -> Path:
    """A machine file recording an overlay whose manifest declares `requires`.

    The manifest writer is `tests/overlay/test_requires.py::overlay_with`, shared rather than
    respelled: one spelling of the declaration the two readers of it are tested against.
    """
    overlay = overlay_with(tmp_path / "overlay", requires)
    machine = tmp_path / "machine.toml"
    machine.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    return machine


UNMET = "the overlay requires drybag >=99.0.0 and {running} does not satisfy it"


def test_overlay_requires_is_red_when_a_bound_project_needs_a_newer_drybag(
    tmp_path: Path,
) -> None:
    # Red because this project keeps its notes in the overlay, so the floor it declares is this
    # installation's business. Mutation (comment; the verdict's own arm): `if not verdict` ->
    # `if verdict` -> this and the ok case swap verdicts. The red-versus-warn split below has an
    # oracle entry of its own.
    machine = _recorded_overlay(tmp_path, ">=99.0.0")
    root = _initialised(tmp_path, template=OVERLAY)
    row = _by_name(_checks(tmp_path, root, machine=machine), "overlay-requires")
    assert row.status == RED
    assert row.detail == UNMET.format(running=drybag.__version__)
    assert "uv tool install" in row.remedy


def test_a_local_only_project_is_warned_and_never_reddened_by_an_unrelated_floor(
    tmp_path: Path,
) -> None:
    # The reason this requirement has a row of its own rather than being folded into
    # `versions`: a `local-only` project on a machine that records an overlay must not go red
    # for a requirement it has no relationship with. The finding is the same finding
    # and says the same thing; only the level moves, because red gates the exit code. Asserted
    # as the level AND the whole text, so this case cannot pass for the red case's reason or
    # vice versa.
    #
    # Mutation (declared): `unmet = RED if ... else WARN` -> `unmet = RED`.
    machine = _recorded_overlay(tmp_path, ">=99.0.0")
    row = _by_name(_checks(tmp_path, _initialised(tmp_path), machine=machine), "overlay-requires")
    assert row.status == WARN
    assert row.detail == UNMET.format(running=drybag.__version__)
    assert "uv tool install" in row.remedy


def test_overlay_requires_is_ok_when_the_floor_is_met_and_skips_without_an_overlay(
    tmp_path: Path,
) -> None:
    machine = _recorded_overlay(tmp_path, " >=0.0.1 ")
    row = _by_name(_checks(tmp_path, _initialised(tmp_path), machine=machine), "overlay-requires")
    assert row.status == OK and ">=0.0.1" in row.detail and " >=0.0.1 " not in row.detail
    row = _by_name(_checks(tmp_path, _initialised(tmp_path)), "overlay-requires")
    assert row.status == SKIP


def test_overlay_requires_warns_on_a_form_it_cannot_read(tmp_path: Path) -> None:
    machine = _recorded_overlay(tmp_path, "~=1.0")
    row = _by_name(_checks(tmp_path, _initialised(tmp_path), machine=machine), "overlay-requires")
    assert row.status == WARN and IDENTITY_RECORD in row.remedy


def test_a_local_only_project_is_not_judged_by_an_unrelated_overlays_floor(tmp_path: Path) -> None:
    # The reason for a row of its own: the verdict is the machine's, so the `versions` row
    # stays about the project and never goes red for this.
    #
    # And the consequence the decision is actually about, asserted over the whole report rather
    # than over one row: `doctor` does not exit 1 here. `overlay-requires` was measured as the
    # only red row this fixture produced while the unmet arm was unconditional, so this
    # assertion is the exit code and not a restatement of the case above.
    machine = _recorded_overlay(tmp_path, ">=99.0.0")
    checks = _checks(tmp_path, _initialised(tmp_path), machine=machine)
    assert _by_name(checks, "versions").status == OK
    assert [check.name for check in checks if check.status == RED] == []


def test_an_overlay_that_moved_is_not_reported_as_one_never_recorded(tmp_path: Path) -> None:
    """Two states, two sentences, and the same two in both rows that ask.

    `overlay_root` answers `None` for a machine that records no overlay -- the ordinary state
    before `drybag setup` has run -- and a `Path` for a recorded root whether or not anything
    is there. `pre-commit` and `overlay-requires` collapsed the two into
    `overlay is None or not overlay.is_dir()` and told both "no overlay root is recorded on this
    machine", which is false of the second and leaves the owner nothing to act on: the overlay
    is where the notes live, and a recorded root that is gone breaks the store too.

    The sentences come from `_overlay_absent` so the two rows cannot drift -- `overlay-requires`'
    arm was a byte-for-byte copy of `pre-commit`'s, which is how it inherited the defect: two
    rows that must say the same thing say it from one constant.

    Mutation: `mutations/`'s "the two overlay rows call a moved overlay an unrecorded one".
    """
    # The sentences are pasted rather than imported from the module under test: compared with
    # its own constants, `OVERLAY_GONE = NO_OVERLAY_RECORDED` — the very confusion this test is
    # for — left it green.
    gone = (
        "the overlay root this machine records is not a directory, so nothing about the overlay "
        "can be checked from here"
    )
    gone_remedy = (
        "put the overlay back where the machine configuration records it, or run `drybag setup "
        "--preset recommended --overlay <path>` to record where it is now"
    )
    machine = tmp_path / "machine.toml"
    machine.write_text(f'[overlay]\nroot = "{tmp_path / "moved-away"}"\n', encoding="utf-8")
    root = _initialised(tmp_path)
    assert overlay_root(machine) is not None, "the fixture records no overlay at all"
    for name in ("pre-commit", "overlay-requires"):
        row = _by_name(_checks(tmp_path, root, machine=machine), name)
        assert row.status == SKIP, row
        assert row.detail == gone, row
        assert row.remedy == gone_remedy, row
    # The other arm keeps the sentence it always had, and keeps carrying no remedy: a machine
    # that has not run `drybag setup` is not a machine with something wrong on it.
    for name in ("pre-commit", "overlay-requires"):
        row = _by_name(_checks(tmp_path, root), name)
        assert row.status == SKIP, row
        assert row.detail == "no overlay root is recorded on this machine", row
        assert not row.remedy, row


def test_a_machine_file_that_does_not_load_is_not_reported_as_one_that_records_no_overlay(
    tmp_path: Path,
) -> None:
    """A third state beside the two above, with a sentence of its own in both rows.

    A machine file nobody could read records nothing anybody knows of: `Context.overlay_root`
    swallowed the refusal into `None`, so both rows told an owner whose file had a stray bracket
    that no overlay root is recorded, while the `preferences` row, which names the file and its
    remedy, was the only one that knew. Neither row carries a remedy of its own for it, since that
    one does.

    Mutations: `mutations/`'s "the report reads a machine file it could not read as one that
    records no overlay" and "the two overlay rows say a machine file nobody could read records no
    overlay".
    """
    # Pasted rather than imported, for the reason the test above gives.
    unread = (
        "the machine configuration file could not be read, so whether this machine records an "
        "overlay is not known here; the `preferences` row says why"
    )
    machine = tmp_path / "machine.toml"
    machine.write_text("[personal\nx = 1\n", encoding="utf-8")
    rows = _checks(tmp_path, _initialised(tmp_path), machine=machine)
    for name in ("pre-commit", "overlay-requires"):
        row = _by_name(rows, name)
        assert (row.status, row.detail, row.remedy) == (SKIP, unread, ""), row


def test_an_overlay_root_inside_another_repositorys_work_tree_is_a_warning(tmp_path: Path) -> None:
    # `setup --overlay` no longer refuses where the owner puts the overlay: where it lives is the
    # owner's choice. A work tree that holds it is still a place another repository can put files
    # into, so the row says so, as a warning and never red, and names that work tree.
    #
    # Mutation: `mutations/`'s "doctor says nothing of the work tree that holds the overlay".
    from drybag.overlay.doctor import NESTED
    from drybag.printed import quoted

    outer = tmp_path / "dotfiles"
    (outer / ".git").mkdir(parents=True)
    overlay = overlay_with(outer / "overlay", ">=0.0.1")
    machine = tmp_path / "machine.toml"
    machine.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    row = _by_name(_checks(tmp_path, _initialised(tmp_path), machine=machine), "overlay-requires")
    assert (row.status, row.detail) == (WARN, NESTED.format(holder=quoted(str(outer))))
    # Without that `.git`, the next work tree up holds it, if any does: a temporary directory under
    # a checkout (a `TMPDIR` inside one) is in that checkout's work tree, and the row names it.
    # With none, the row is the floor's again.
    shutil.rmtree(outer / ".git")
    above = next((d for d in tmp_path.parents if os.path.lexists(d / ".git")), None)
    row = _by_name(_checks(tmp_path, _initialised(tmp_path), machine=machine), "overlay-requires")
    if above is None:
        assert row.status == OK, row
    else:
        assert (row.status, row.detail) == (WARN, NESTED.format(holder=quoted(str(above))))
