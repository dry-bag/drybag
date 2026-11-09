"""One binding question, one answer, on every surface that asks it.

`memory` commands, `attach`, `attach --check` and `doctor` each say whether this machine binds the
checkout. They used to answer it from the overlay's record of a remote, and a checkout whose
`origin` was removed was refused on every surface, each with a way out that refused in turn. The
binding is the id in the git common directory now, and a removed `origin` is a note: no surface
refuses for it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from drybag.attach.check import check
from drybag.attach.write import attach
from drybag.config.loader import load
from drybag.doctor.api import run_checks
from drybag.memory.store import resolved
from tests.attach.test_write import RULE, _attachable
from tests.gitfixture import git
from tests.runners import Recorder

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _attached_then_origin_removed(tmp_path: Path) -> tuple[Path, Path, Path]:
    root, store, machine = _attachable(tmp_path, allow=(RULE,))
    attach(
        root,
        store=store,
        machine=machine,
        runner=Recorder(),
    )
    git(root, "remote", "remove", "origin")
    return root, store, machine


def test_a_checkout_whose_origin_was_removed_stays_bound_on_every_surface(
    tmp_path: Path,
) -> None:
    root, store, machine = _attached_then_origin_removed(tmp_path)
    home = tmp_path / "home"

    found, why = resolved(root, load(root, machine=machine), machine=machine)
    assert why is None and found is not None

    attached = attach(root, store=store, machine=machine, runner=Recorder())
    assert not attached.binding_recorded

    checked = check(root, store=store, machine=machine)
    assert checked.exit_code == 0 and "; bound; " in checked.summary

    doctor = next(
        row
        for row in run_checks(root, home=home, machine=machine, env={"HOME": str(home)})
        if row.name == "attached"
    )
    assert "the binding is bound" in doctor.detail
