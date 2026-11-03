"""The sync's git layer: the bounded runner, the job's environment and the guard.

Every call the job makes goes through `run`, which starts the child in a session of its own and
kills the whole group on a timeout, so an ssh or a credential helper under git cannot outlive the
step that started it. The guard decides whether the overlay is in a shape the job may act on at
all. Real git on repositories under `tmp_path`; a test about a bound running out passes a small
one of its own, and every other call a large one, since the machine these run on is rarely idle.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from stayfixed.sync import git as G
from tests import gitfixture as fx
from tests.sync.conftest import (
    SLOW,
    World,
    commit_all,
    git,
    init,
    slow_git,
    write,
)

# -- the runner -----------------------------------------------------------------------------------


def test_the_runner_kills_the_group_of_a_child_that_outlives_its_timeout(tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"

    ran = G.run(["sh", "-c", f"sleep 300 & echo $! > '{pidfile}'; wait"], cwd=tmp_path, timeout=5)

    assert ran.timed_out is True
    pid = int(pidfile.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, 9)
        pytest.fail("the grandchild outlived the timeout: only the child was killed, not its group")


def test_a_run_that_finishes_in_time_is_not_timed_out(tmp_path: Path) -> None:
    ran = G.run(["sh", "-c", "echo out; echo err >&2; exit 3"], cwd=tmp_path, timeout=SLOW)

    assert ran == G.Ran(code=3, out="out\n", err="err\n", timed_out=False)


def test_the_runner_reports_a_program_or_directory_that_is_not_there(tmp_path: Path) -> None:
    missing = G.run([str(tmp_path / "no-such-program")], cwd=tmp_path, timeout=5)
    assert missing.code == 127 and missing.timed_out is False
    assert "no-such-program" in missing.err

    nowhere = G.run(["sh", "-c", "true"], cwd=tmp_path / "no-such-directory", timeout=5)
    assert nowhere.code == 127 and nowhere.err


def test_the_runner_decodes_bytes_that_are_not_utf_8_and_gives_them_back(tmp_path: Path) -> None:
    """A path git prints in another encoding survives the round trip into the next argv."""
    ran = G.run(["printf", r"a\377b"], cwd=tmp_path, timeout=SLOW)

    assert ran.out == "a\udcffb"
    assert ran.out.encode("utf-8", "surrogateescape") == b"a\xffb"


def test_stdin_is_what_the_caller_gives_or_nothing(tmp_path: Path) -> None:
    assert G.run(["cat"], cwd=tmp_path, timeout=SLOW, stdin=b"bytes in\n").out == "bytes in\n"
    # Nothing the job runs may wait for an answer: with no input given, stdin is empty.
    assert G.run(["cat"], cwd=tmp_path, timeout=SLOW).out == ""


def test_the_runner_hands_on_the_environment_less_what_redirects_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ssh agent must reach the push, a hook's `GIT_DIR` must not reach anything."""
    monkeypatch.setenv("SSH_AUTH_SOCK", "/agent.sock")
    monkeypatch.setenv("GIT_DIR", "/elsewhere/.git")
    monkeypatch.setenv("GIT_INDEX_FILE", "/elsewhere/index")
    monkeypatch.setenv("GITLEAKS_CONFIG", "/loosened.toml")

    def seen(**given: object) -> dict[str, str]:
        ran = G.run(["env"], cwd=tmp_path, timeout=SLOW, **given)  # type: ignore[arg-type]
        return dict(line.split("=", 1) for line in ran.out.splitlines() if "=" in line)

    plain = seen()
    assert plain["SSH_AUTH_SOCK"] == "/agent.sock"
    assert plain["GITLEAKS_CONFIG"] == "/loosened.toml"
    assert "GIT_DIR" not in plain and "GIT_INDEX_FILE" not in plain

    chosen = seen(
        env={"GIT_DIR": "given"},
        index_file=tmp_path / "chosen.index",
        unset_prefixes=("GITLEAKS_",),
    )
    assert chosen["GIT_DIR"] == "given"  # `env` is the one way to set them
    assert chosen["GIT_INDEX_FILE"] == str(tmp_path / "chosen.index")
    assert "GITLEAKS_CONFIG" not in chosen


def test_git_ignores_inherited_repository_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job started from inside a git hook must still address the overlay and its real index."""
    repo = init(tmp_path / "r")
    write(repo, "common/memory/a.md")
    commit_all(repo)
    elsewhere = init(tmp_path / "elsewhere")
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "nonexistent-index"))

    assert G.git(repo, "ls-files", timeout=SLOW).out == "common/memory/a.md\n"


def test_git_uses_the_index_file_it_is_given_for_that_call_only(tmp_path: Path) -> None:
    repo = init(tmp_path / "r")
    write(repo, "common/memory/a.md")
    commit_all(repo)
    temporary = tmp_path / "index.tmp"

    assert G.git(repo, "read-tree", "--empty", timeout=SLOW, index_file=temporary).code == 0

    assert G.git(repo, "ls-files", timeout=SLOW, index_file=temporary).out == ""
    assert G.git(repo, "ls-files", timeout=SLOW).out == "common/memory/a.md\n"


# -- the job's environment ------------------------------------------------------------------------

_APPENDED = " -o BatchMode=yes -o ConnectTimeout=10"


def test_job_env_pins_attributes_and_replace_refs_and_keeps_core_sshcommand(tmp_path: Path) -> None:
    repo = init(tmp_path / "r")
    git(repo, "config", "core.sshCommand", "ssh -i ~/.ssh/k")

    assert G.job_env(repo, timeout=SLOW) == {
        "GIT_TERMINAL_PROMPT": "0",
        "SSH_ASKPASS_REQUIRE": "never",
        "GIT_SSH_COMMAND": "ssh -i ~/.ssh/k" + _APPENDED,
        "GIT_NO_REPLACE_OBJECTS": "1",  # a replace ref must not show the checks another commit
        "GIT_ATTR_SOURCE": "HEAD",  # nor a working-tree `.gitattributes` filter another blob
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.askPass",
        "GIT_CONFIG_VALUE_0": "",
    }


def test_no_askpass_is_ever_asked_for_a_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # git asks an askpass before the terminal, so `GIT_TERMINAL_PROMPT=0` alone does not stop an
    # unattended job popping a password dialog from an editor's `GIT_ASKPASS`, the owner's
    # `core.askPass` or a desktop's `SSH_ASKPASS`. Mutations (oracle): `mutations/`'s "the job
    # keeps an inherited askpass" and "the job keeps the owner's core.askPass".
    repo = init(tmp_path / "r")
    asked = tmp_path / "asked"
    askpass = tmp_path / "askpass"
    askpass.write_text(f'#!/bin/sh\necho "$*" >> {asked}\necho secret\n')
    askpass.chmod(0o755)
    for name in ("GIT_ASKPASS", "SSH_ASKPASS"):
        monkeypatch.setenv(name, str(askpass))
    git(repo, "config", "core.askPass", str(askpass))
    env = G.job_env(repo, timeout=SLOW)
    request = b"protocol=https\nhost=example.invalid\n\n"

    filled = G.git(
        repo, "-c", "credential.helper=", "credential", "fill", timeout=SLOW, env=env, stdin=request
    )

    assert filled.code != 0 and not asked.exists()
    for name in ("GIT_ASKPASS", "SSH_ASKPASS"):
        monkeypatch.delenv(name)
    filled = G.git(
        repo, "-c", "credential.helper=", "credential", "fill", timeout=SLOW, env=env, stdin=request
    )
    assert filled.code != 0 and not asked.exists()  # the owner's `core.askPass` is off too


@pytest.mark.parametrize("entry", ["", "."])
def test_a_git_at_the_overlays_root_never_runs_from_a_relative_path_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    # Every call runs in the overlay, so an empty or `.` entry of `PATH` (a dotfile slip) would
    # find a `git` planted at its root, and git would find an `ssh` there the same way.
    # Mutation (oracle): `mutations/`'s "a relative PATH entry reaches the overlay".
    repo = init(tmp_path / "r")
    planted = repo / "git"
    planted.write_text("#!/bin/sh\necho planted\n")
    planted.chmod(0o755)
    monkeypatch.setenv("PATH", f"{entry}{os.pathsep}{os.environ['PATH']}")

    ran = G.git(repo, "version", timeout=SLOW)

    assert ran.out.startswith("git version"), ran
    shown = G.run(["sh", "-c", 'printf %s "$PATH"'], cwd=repo, timeout=SLOW).out
    assert all(os.path.isabs(part) for part in shown.split(os.pathsep)), shown


def test_job_env_defaults_to_ssh_and_prefers_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init(tmp_path / "r")
    assert G.job_env(repo, timeout=SLOW)["GIT_SSH_COMMAND"] == "ssh" + _APPENDED

    git(repo, "config", "core.sshCommand", "ssh -i ~/.ssh/k")
    monkeypatch.setenv("GIT_SSH_COMMAND", "/usr/bin/ssh -p 2222")
    assert G.job_env(repo, timeout=SLOW)["GIT_SSH_COMMAND"] == "/usr/bin/ssh -p 2222" + _APPENDED

    # `GIT_SSH` names a program, not a command line; git consults it after `core.sshCommand`.
    monkeypatch.delenv("GIT_SSH_COMMAND")
    git(repo, "config", "--unset", "core.sshCommand")
    monkeypatch.setenv("GIT_SSH", "/opt/my tools/plink")
    assert G.job_env(repo, timeout=SLOW)["GIT_SSH_COMMAND"] == "'/opt/my tools/plink'"


def test_job_env_leaves_a_wrapper_as_is(tmp_path: Path) -> None:
    repo = init(tmp_path / "r")
    git(repo, "config", "core.sshCommand", "/usr/local/bin/myssh")

    assert G.job_env(repo, timeout=SLOW)["GIT_SSH_COMMAND"] == "/usr/local/bin/myssh"

    git(repo, "config", "core.sshCommand", "env SSH_AUTH_SOCK=/tmp/x ssh")
    assert G.job_env(repo, timeout=SLOW)["GIT_SSH_COMMAND"] == "env SSH_AUTH_SOCK=/tmp/x ssh"


def test_job_env_and_the_guard_time_out_instead_of_answering(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guard call that times out is not "detached HEAD"; a config call is not "no setting"."""
    slow_git(tmp_path, monkeypatch, {"symbolic-ref": 60, "config": 60})

    with pytest.raises(G.GitTimeout):
        G.guard(world.a, timeout=4.0)
    with pytest.raises(G.GitTimeout):
        G.job_env(world.a, timeout=0.5)


def test_the_helpers_of_one_step_share_its_whole_budget(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each call sleeps less than the budget, so a fresh one per call would let the guard finish."""
    slow_git(tmp_path, monkeypatch, {"version": 1.2, "rev-parse": 1.2, "ls-files": 1.2})

    with pytest.raises(G.GitTimeout):
        G.guard(world.a, timeout=3.0)


# -- the guard ------------------------------------------------------------------------------------


def _diverge(repo: Path) -> None:
    """A topic branch and `main` that both rewrite README.md, so replaying either conflicts."""
    git(repo, "checkout", "-q", "-b", "topic")
    write(repo, "README.md", "topic\n")
    commit_all(repo, "topic")
    git(repo, "checkout", "-q", "main")
    write(repo, "README.md", "main\n")
    commit_all(repo, "main")


def test_the_guard_passes_a_clean_clone(world: World) -> None:
    assert G.guard(world.a, timeout=SLOW) == G.Guard(ok=True, reason=None)


def test_the_guard_refuses_another_branch_a_detached_head_and_a_rebase(world: World) -> None:
    a = world.a
    _diverge(a)

    git(a, "checkout", "-q", "topic")
    refused = G.guard(a, timeout=SLOW)
    assert refused.ok is False and refused.reason is not None and "topic" in refused.reason

    git(a, "checkout", "-q", "--detach", "main")
    refused = G.guard(a, timeout=SLOW)
    assert refused.ok is False and refused.reason is not None and "detached" in refused.reason

    git(a, "checkout", "-q", "main")
    fx.run_git(a, "rebase", "topic")
    assert (a / ".git" / "rebase-merge").exists() or (a / ".git" / "rebase-apply").exists()
    refused = G.guard(a, timeout=SLOW)
    assert refused.ok is False and refused.reason is not None and "rebase" in refused.reason
    git(a, "rebase", "--abort")
    assert G.guard(a, timeout=SLOW).ok is True


def test_the_guard_refuses_a_merge_and_a_cherry_pick_on_main(world: World) -> None:
    """Both leave HEAD on `main`, so only the in-progress markers can tell."""
    a = world.a
    _diverge(a)

    fx.run_git(a, "merge", "topic")
    refused = G.guard(a, timeout=SLOW)
    assert refused.ok is False and refused.reason is not None and "merge" in refused.reason
    git(a, "merge", "--abort")

    fx.run_git(a, "cherry-pick", "topic")
    refused = G.guard(a, timeout=SLOW)
    assert refused.ok is False and refused.reason is not None and "cherry-pick" in refused.reason
    git(a, "cherry-pick", "--abort")

    assert G.guard(a, timeout=SLOW).ok is True


def test_the_guard_refuses_unmerged_paths_a_stash_pop_left_without_a_marker(world: World) -> None:
    """No operation is in progress, yet the index holds unmerged entries and the note holds
    conflict markers: committed from the working tree, they would travel as a note."""
    a = world.a
    write(a, "common/memory/first.md", "stashed edit\n")
    git(a, "stash", "-q")
    write(a, "common/memory/first.md", "another edit\n")
    commit_all(a, "the owner's commit")
    fx.run_git(a, "stash", "pop")
    assert git(a, "ls-files", "--unmerged") != ""
    assert not any(
        (a / ".git" / name).exists() for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply")
    )

    refused = G.guard(a, timeout=SLOW)

    assert refused.ok is False and refused.reason == G.UNMERGED
    git(a, "checkout", "HEAD", "--", "common/memory/first.md")
    assert G.guard(a, timeout=SLOW).ok is True


def test_the_guard_refuses_main_not_tracking_origin_main(world: World) -> None:
    git(world.a, "branch", "--unset-upstream")

    refused = G.guard(world.a, timeout=SLOW)

    assert refused.ok is False and refused.reason is not None and "origin/main" in refused.reason


def test_the_guard_refuses_main_tracking_another_upstream(world: World) -> None:
    git(world.a, "remote", "add", "other", str(world.bare))
    git(world.a, "fetch", "-q", "other")
    git(world.a, "branch", "--set-upstream-to=other/main")

    refused = G.guard(world.a, timeout=SLOW)

    assert refused.ok is False and refused.reason is not None and "other/main" in refused.reason


def test_the_guard_refuses_a_directory_that_is_not_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    refused = G.guard(plain, timeout=SLOW)

    assert refused.ok is False and refused.reason is not None
    assert refused.reason.startswith("not a git repository")


def test_the_guard_allows_staged_and_unstaged_work_outside_memory(world: World) -> None:
    a = world.a
    write(a, "common/claude/hooks/launch.sh", "#!/bin/sh\n# staged\n")
    git(a, "add", "common/claude/hooks/launch.sh")
    write(a, "common/claude/hooks/launch.sh", "#!/bin/sh\n# staged\n# and more, unstaged\n")
    write(a, "common/claude/hooks/new.py", "untracked\n")

    assert G.guard(a, timeout=SLOW) == G.Guard(ok=True, reason=None)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("git version 2.54.0 (Apple Git-157)\n", True),
        ("git version 2.43.0\n", True),
        ("git version 2.43.0.windows.1\n", True),
        ("git version 3.0.1\n", True),
        ("git version 2.42.2\n", False),
        ("git version 2.40.0\n", False),  # ignores GIT_ATTR_SOURCE: attributes from the tree
        ("git version 2.39.5\n", False),
        ("git version 2.38.0\n", False),
        ("git version 2.37.9\n", False),
        ("git version 1.99.0\n", False),
        ("something else\n", False),
        ("", False),
    ],
)
def test_the_git_version_floor_is_2_43(text: str, ok: bool) -> None:
    assert G.MIN_GIT == (2, 43)
    assert G.version_ok(text) is ok


def test_the_guard_skips_a_git_older_than_2_43_with_the_reason(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older git is skipped, not failed: below 2.41 it would read attributes from the working
    tree without a word, below 2.40 it cannot replay at all."""
    real = shutil.which("git")
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "git").write_text(
        f'#!/bin/sh\nif [ "$1" = version ]; then echo "git version 2.42.2"; exit 0; fi\n'
        f'exec "{real}" "$@"\n'
    )
    (shim / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")

    refused = G.guard(world.a, timeout=SLOW)

    assert refused.ok is False and refused.reason is not None
    assert "2.43" in refused.reason and "GIT_ATTR_SOURCE" in refused.reason
    assert "2.42.2" in refused.reason


def test_the_guard_skips_when_there_is_no_git(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    refused = G.guard(world.a, timeout=SLOW)

    assert refused.ok is False and refused.reason is not None and "2.43" in refused.reason


def test_a_checked_call_names_a_failure_and_a_timeout() -> None:
    ok = G.Ran(0, "out", "", False)
    assert G.checked(ok, "git x") is ok
    with pytest.raises(G.GitTimeout):
        G.checked(G.Ran(-9, "", "", True), "git x")
    with pytest.raises(G.GitError, match=r"git x failed \(128\): fatal: bad"):
        G.checked(G.Ran(128, "", "fatal: bad\n", False), "git x")
    assert not issubclass(G.GitError, G.GitTimeout)
