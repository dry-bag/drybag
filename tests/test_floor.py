from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from drybag import gitenv
from tests.floor import SUITE_GIT_FLOOR_SECONDS, developer_free_environ, is_developers

LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "drybag"


def test_a_spawner_strips_the_developers_variables_and_keeps_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One predicate for both halves, so a spawner cannot take the strip without the floor: the
    # floor is a `DRYBAG_*` name, and the strip used to take it with the developer's own
    # configuration. Mutation (oracle): `mutations/`'s "the suite's developer strip drops the floor"
    # -> this reddens, and so does the launcher case below.
    monkeypatch.setenv("DRYBAG_CONFIG", "/developer/drybag.toml")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/developer/project")
    env = developer_free_environ()
    assert env[gitenv.FLOOR_VARIABLE] == str(SUITE_GIT_FLOOR_SECONDS)
    assert "DRYBAG_CONFIG" not in env
    assert "CLAUDE_PROJECT_DIR" not in env
    assert not is_developers(gitenv.FLOOR_VARIABLE)


def test_a_drybag_the_suite_starts_runs_its_git_under_the_floor(tmp_path: Path) -> None:
    # The case the floor exists for. It used to be an assignment in the test's own process, so a
    # `drybag` a test started as a separate process ran under the product's bare bounds, and
    # under load one of them ran out and failed a test that passed alone.
    #
    # The shipped launcher, started the way the suite's spawners start it, runs a hook outside
    # any repository, so the hook asks `git rev-parse --show-toplevel` under the default bound.
    # The stand-in `git` answers only after that bound, and marks that it did: under the floor
    # the launcher waits for it; without it the stand-in is killed at the bound and the mark is
    # never written. No second run without the floor is needed to make that non-vacuous, and none
    # is made, because it would cost the same wait again. Mutation (oracle): `mutations/`'s "the git
    # runner ignores the floor a test runner sets" -> this reddens.
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    assert not gitenv.in_work_tree(nowhere), "the hook would find a repository by walking up"
    answered = tmp_path / "answered"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stand_in = bin_dir / "git"
    past_the_bound = gitenv.GIT_TIMEOUT_SECONDS + 0.5
    stand_in.write_text(
        f'#!/bin/sh\nif [ ! -e "{answered}" ]; then sleep {past_the_bound}; : > "{answered}"; fi\n'
        "exit 128\n",
        encoding="utf-8",
    )
    stand_in.chmod(0o755)
    env = developer_free_environ()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    done = subprocess.run(
        [sys.executable, str(LAUNCHER), "hook", "SessionStart"],
        input=json.dumps({"cwd": str(nowhere)}),
        capture_output=True,
        text=True,
        check=False,
        cwd=nowhere,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    assert answered.exists(), "the hook's git was killed at the product's bound"
