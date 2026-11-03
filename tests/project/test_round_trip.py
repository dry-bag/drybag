"""`init --yes`, `upgrade` and `uninstall` on one repository, through the real launcher: the
footprint's whole life, run where a person and a skill run it.

Every one-line mutation that would redden this case is already declared against a narrower test
of `init`, `upgrade`, `uninstall` and `rewrite_owned`, so it declares none of its own.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import stayfixed
from stayfixed.scaffold import Manifest, digest
from tests.floor import developer_free_environ
from tests.gitfixture import git, needs_git
from tests.project.repos import tree

ROOT = Path(__file__).resolve().parents[2]
OLDER = "0.0.1"


def _stayfixed(root: Path, home: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = developer_free_environ()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "stayfixed"), *argv, "--root", str(root)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _as_an_older_stayfixed_left_it(root: Path, record_id: str, text: str) -> None:
    """Write `text` where `record_id` lives, and record it, as a release ago would have."""
    manifest = Manifest.read(root)
    record = manifest.get(record_id)
    assert record is not None
    (root / record.target).write_text(text, encoding="utf-8")
    manifest.with_record(replace(record, sha256=digest(text), version=OLDER)).write(root)


@needs_git
def test_init_upgrade_and_uninstall_round_trip_and_keep_every_hand_edit(tmp_path: Path) -> None:
    # Through the launcher and not `cli.run`, so the proof covers the entry point a person and a
    # skill use.
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "widget"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", "git@github.com:owner/widget.git")

    done = _stayfixed(root, home, "init", "--yes")
    assert done.returncode == 0, done.stdout + done.stderr

    # A release ago stayfixed recorded an older version and wrote other bytes into the
    # documentation policy; the user has since edited the roadmap. An older stayfixed cannot be
    # run through a subprocess, so the repository is written as one would have left it.
    policy = root / "docs" / "architecture" / "documentation.md"
    current = policy.read_text(encoding="utf-8")
    config = (root / "stayfixed.toml").read_text(encoding="utf-8")
    running = stayfixed.__version__
    _as_an_older_stayfixed_left_it(
        root, "config", config.replace(f'version = "{running}"', f'version = "{OLDER}"')
    )
    _as_an_older_stayfixed_left_it(root, "documentation-policy", "an older release's policy\n")
    roadmap = root / "docs" / "roadmap.md"
    roadmap.write_text(roadmap.read_text(encoding="utf-8") + "\nOur own line.\n", encoding="utf-8")

    done = _stayfixed(root, home, "upgrade", "--json")
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["moved"] == [
        {"key": "stayfixed.version", "before": OLDER, "after": running}
    ]
    assert policy.read_text(encoding="utf-8") == current
    assert (root / "stayfixed.toml").read_text(encoding="utf-8") == config
    assert "Our own line." in roadmap.read_text(encoding="utf-8")

    # `stayfixed.toml` was re-stamped by the upgrade, so uninstall recognises it as stayfixed's.
    done = _stayfixed(root, home, "uninstall", "--json")
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["left"] == ["docs/roadmap.md"]
    assert tree(root) == {"docs", "docs/roadmap.md"}
    assert "Our own line." in roadmap.read_text(encoding="utf-8")
