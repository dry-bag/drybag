"""The job's push of the checked range, its end, and the whole job run against real repositories.

The push sends the sha the checks were run on, never a branch name that may have moved since, and
never with force. A local range that is not memory-only is a local hold, recorded and left; an
upstream hold skips the push. Every byte a push sends is scanned first: the patches, and each
commit object whole with its path names. Holds outlive every later outcome, and the job's end is
one outcome chosen by one rule, its detail naming the rest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from stayfixed.sync import job as J
from stayfixed.sync.state import LOCK_FILE, STATE_FILE, Lock, Outcome, SyncState, read_state
from tests.sync.conftest import (
    LEAK,
    Overlays,
    commit_all,
    context,
    git,
    head,
    merge_with_resolution,
    note_text,
    push_note,
    rename,
    slow_git,
    write,
)

NOTE = "common/memory/new.md"
OFFLINE = "echo 'ssh: Could not resolve hostname git.example.invalid' >&2; exit 255"


def job(world: Overlays, clone: Path | None = None, **limits: float) -> SyncState:
    state = J.run_job(context(world, clone or world.a, **limits))
    assert state is not None
    return state


def remote_main(world: Overlays) -> str:
    return git(world.bare, "rev-parse", "main").strip()


def remote_files(world: Overlays, *paths: str) -> list[str]:
    return git(world.bare, "ls-tree", "-r", "--name-only", "main", "--", *paths).split()


def a_note(world: Overlays, relative: str = NOTE, name: str = "new") -> None:
    write(world.a, relative, note_text(name))


def fake_ssh(world: Overlays, script: str) -> None:
    """Make `a` reach its remote over ssh through `script`, a stand-in for ssh."""
    program = world.bare.parent / "fake-ssh"
    program.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    program.chmod(0o755)
    git(world.a, "config", "core.sshCommand", str(program))
    git(world.a, "remote", "set-url", "origin", "ssh://git.example.invalid/overlay.git")


def real_remote(world: Overlays) -> None:
    git(world.a, "remote", "set-url", "origin", str(world.bare))


# -- the push -------------------------------------------------------------------------------------


def test_the_memory_only_range_is_pushed_as_the_checked_sha(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A commit landing between the checks and the push is not pushed: the push names the sha the
    # checks read, never `main`, which has moved past it.
    a = overlays.a
    a_note(overlays)
    later: list[str] = []

    def a_commit_lands_after_the_check() -> None:
        write(a, "common/memory/later.md", note_text("later"))
        later.append(commit_all(a, "memory: later"))

    monkeypatch.setattr(J, "_before_push", a_commit_lands_after_the_check)

    state = job(overlays)

    assert state.outcome.state == "ok", state.outcome.detail
    assert remote_main(overlays) == head(a, f"{later[0]}^")
    assert "common/memory/new.md" in remote_files(overlays, "common/memory")
    assert "common/memory/later.md" not in remote_files(overlays, "common/memory")
    assert state.fetched_sha is not None and state.last_fetch_ok == state.last_job_at
    assert state.head == later[0] and not state.holds.any


def test_a_local_commit_outside_memory_is_held_and_named(overlays: Overlays) -> None:
    a = overlays.a
    before = remote_main(overlays)
    write(a, "common/claude/hooks/launch.sh", "#!/bin/sh\nlocal change\n")
    hook = commit_all(a, "hook")
    a_note(overlays)

    state = job(overlays)

    assert remote_main(overlays) == before
    assert state.holds.local_commits == (hook,)
    assert state.holds.local_since == state.last_job_at
    assert not state.holds.upstream_paths
    assert state.outcome.detail is not None and "outside memory" in state.outcome.detail
    assert hook in state.outcome.detail


def test_a_binary_note_committed_by_hand_is_held(overlays: Overlays) -> None:
    a = overlays.a
    before = remote_main(overlays)
    (a / "common/memory/blob.md").write_bytes(b"token: x\x00y\n")
    binary = commit_all(a, "memory: by hand")

    state = job(overlays)

    assert remote_main(overlays) == before
    assert state.holds.local_commits == (binary,)


def test_a_rename_and_a_merge_committed_by_hand_are_held(overlays: Overlays) -> None:
    a = overlays.a
    before = remote_main(overlays)
    rename(a, ".pre-commit-config.yaml", "common/memory/pre-commit.md")
    renamed = commit_all(a, "rename into memory")

    state = job(overlays)

    assert remote_main(overlays) == before and state.holds.local_commits == (renamed,)

    git(a, "reset", "-q", "--hard", "origin/main")  # the owner drops it
    git(a, "checkout", "-q", "-b", "side")
    write(a, "common/memory/side.md", note_text("side"))
    commit_all(a, "side")
    git(a, "checkout", "-q", "main")
    write(a, "common/memory/main.md", note_text("main"))
    commit_all(a, "main")
    merge = merge_with_resolution(a, "side", {})
    git(a, "branch", "-q", "-D", "side")

    state = job(overlays)

    assert remote_main(overlays) == before
    assert state.holds.local_commits == (merge,)


def test_both_holds_are_recorded_at_once_and_outlive_a_later_outcome(overlays: Overlays) -> None:
    b, a = overlays.b, overlays.a
    write(b, "common/claude/hooks/launch.sh", "#!/bin/sh\nupstream change\n")
    upstream = commit_all(b, "upstream hook")
    git(b, "push", "-q", "origin", "main")
    write(a, "common/claude/hooks/x.py", "print('local hook')\n")
    local = commit_all(a, "local hook")
    a_note(overlays)

    state = job(overlays)

    assert state.holds.upstream_paths == ("common/claude/hooks/launch.sh",)
    assert local in state.holds.local_commits
    assert remote_main(overlays) == upstream  # no push attempted
    assert state.outcome.detail is not None
    assert "git log -p --no-renames HEAD.." in state.outcome.detail

    fake_ssh(overlays, OFFLINE)
    later = job(overlays)

    assert later.outcome.state == "offline"
    assert later.holds == state.holds


def test_an_upstream_hold_skips_the_push(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Local memory-only commits wait while upstream is held: no scan, no push attempted.
    b = overlays.b
    write(b, "common/claude/hooks/launch.sh", "#!/bin/sh\nupstream change\n")
    upstream = commit_all(b, "upstream hook")
    git(b, "push", "-q", "origin", "main")
    a_note(overlays)
    attempts: list[int] = []
    monkeypatch.setattr(J, "_before_push", lambda: attempts.append(1))

    state = job(overlays)

    assert state.outcome.state == "ok" and attempts == []
    assert state.holds.upstream_paths and not state.holds.local_commits
    assert remote_main(overlays) == upstream
    assert git(overlays.a, "log", "-1", "--format=%s").startswith("memory: 1 notes")
    assert state.outcome.detail is not None
    assert "not pushed while upstream is held" in state.outcome.detail


def test_a_rejected_push_is_retried_on_the_next_trigger(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_note(overlays, "common/memory/from-a.md", "from-a")
    raced: list[str] = []

    def another_machine_pushes() -> None:
        raced.append(push_note(overlays.b, "common/memory/from-b.md", note_text("from-b")))

    with monkeypatch.context() as patch:
        patch.setattr(J, "_before_push", another_machine_pushes)
        state = job(overlays)

    assert state.outcome.state == "rejected", state.outcome
    assert remote_main(overlays) == raced[0]

    state = job(overlays)

    assert state.outcome.state == "ok", state.outcome.detail
    files = remote_files(overlays, "common/memory")
    assert {"common/memory/from-a.md", "common/memory/from-b.md"} <= set(files)
    assert git(overlays.bare, "rev-parse", "main~1").strip() == raced[0]


def test_a_secret_in_the_range_is_secret_found_with_its_sha(overlays: Overlays) -> None:
    a = overlays.a
    before = remote_main(overlays)
    write(a, "common/memory/leak.md", f"key = {LEAK}\n")
    leaky = commit_all(a, "memory: by hand")  # committed outside the job: no scan ran

    state = job(overlays)

    assert state.outcome.state == "secret_found"
    assert state.outcome.commits == (leaky,)
    assert state.outcome.detail is not None
    assert f"git rebase -i {leaky}^" in state.outcome.detail
    assert LEAK not in state.outcome.detail
    assert remote_main(overlays) == before


@pytest.mark.parametrize("where", ["message", "file name", "header"])
def test_a_secret_outside_any_patch_is_never_pushed(overlays: Overlays, where: str) -> None:
    # An agent's `git commit -m "remember the deploy token ..."`, or a note named after one: the
    # patches are clean, the push still sends it, so it is scanned too.
    a = overlays.a
    before = remote_main(overlays)
    write(a, "common/memory/clean.md", "a clean note\n")
    clean = commit_all(a, "memory: clean")  # one before it: the finding names the right commit
    if where == "message":
        write(a, "common/memory/deploy.md", "a harmless note\n")
        leaky = commit_all(a, f"remember the deploy token {LEAK}")
    elif where == "file name":
        write(a, f"common/memory/{LEAK}.md", "a harmless note\n")
        leaky = commit_all(a, "memory: by hand")
    else:  # a header of its own, which `git log` never prints
        write(a, "common/memory/deploy.md", "a harmless note\n")
        plain = git(a, "cat-file", "commit", commit_all(a, "memory: by hand"))
        header, _, message = plain.partition("\n\n")
        crafted = subprocess.run(
            ["git", "-C", str(a), "hash-object", "-t", "commit", "-w", "--stdin"],
            input=f"{header}\nx-deploy-token {LEAK}\n\n{message}".encode(),
            capture_output=True,
            check=True,
        )
        leaky = crafted.stdout.decode().strip()
        git(a, "update-ref", "refs/heads/main", leaky)

    state = job(overlays)

    assert state.outcome.state == "secret_found", state.outcome
    assert state.outcome.commits == (leaky,) != (clean,)
    assert state.outcome.detail is not None
    assert f"git rebase -i {leaky}^" in state.outcome.detail
    assert LEAK not in state.outcome.detail.replace(f"common/memory/{LEAK}.md", "")
    assert remote_main(overlays) == before


def test_a_failed_range_scan_is_hook_failed_not_secret_found(overlays: Overlays) -> None:
    a = overlays.a
    before = remote_main(overlays)
    write(a, "common/memory/n.md", "n\n")
    commit_all(a, "memory: by hand")
    overlays.mode("fail")

    state = job(overlays)

    assert state.outcome.state == "hook_failed", state.outcome
    assert state.outcome.detail is not None and state.outcome.detail.startswith("gitleaks:")
    assert state.outcome.commits == ()
    assert remote_main(overlays) == before


def test_scan_unavailable_still_integrates_upstream_and_pushes_nothing(
    overlays: Overlays,
) -> None:
    # No scanner build, an uncommitted note, an upstream note and an unpushed local one. The commit
    # step's failure is a notice; fetch and integrate still run, so the upstream note arrives; the
    # push needs its own scan, so nothing is pushed and the end is `scan_unavailable`.
    a = overlays.a
    (overlays.home / ".cache" / "pre-commit" / "db.db").unlink()
    push_note(overlays.b, "common/memory/from-b.md", note_text("from-b"))
    write(a, "common/memory/local.md", note_text("local"))
    git(a, "add", "common/memory/local.md")
    git(a, "commit", "-q", "-m", "memory: by hand")
    a_note(overlays)
    before = remote_main(overlays)

    state = job(overlays)

    assert state.outcome.state == "scan_unavailable", state.outcome
    assert state.outcome.detail is not None and "pre-commit install-hooks" in state.outcome.detail
    assert (a / "common/memory/from-b.md").read_text() == note_text("from-b")
    assert head(a, "HEAD^") == before  # the local commit, replayed onto upstream's
    assert remote_main(overlays) == before
    assert "?? common/memory/new.md" in git(a, "status", "--porcelain", "--", "common/memory")


def test_scan_unavailable_alone_is_the_end_after_a_clean_integration(overlays: Overlays) -> None:
    a = overlays.a
    (overlays.home / ".cache" / "pre-commit" / "db.db").unlink()
    push_note(overlays.b, "common/memory/from-b.md", note_text("from-b"))
    a_note(overlays)

    state = job(overlays)

    assert state.outcome.state == "scan_unavailable", state.outcome
    assert (a / "common/memory/from-b.md").exists()


def test_a_failed_commit_scan_then_offline_is_offline_naming_both(overlays: Overlays) -> None:
    # A later step's own failure is the end, and its detail names the commit step's.
    write(overlays.a, "common/memory/leak.md", f"key = {LEAK}\n")
    fake_ssh(overlays, OFFLINE)

    state = job(overlays)

    assert state.outcome.state == "offline", state.outcome
    detail = state.outcome.detail
    assert detail is not None and "Could not resolve hostname" in detail
    assert "also hook_failed: gitleaks" in detail
    assert LEAK not in detail


def test_offline_then_restored_pushes_with_a_clean_tree(overlays: Overlays) -> None:
    a = overlays.a
    fake_ssh(overlays, "echo 'ssh: connect to host x: Network is unreachable' >&2; exit 255")
    a_note(overlays)

    state = job(overlays)

    assert state.outcome.state == "offline"
    assert git(a, "log", "-1", "--format=%s").startswith("memory: 1 notes from")
    assert git(a, "status", "--porcelain") == ""

    real_remote(overlays)
    state = job(overlays)

    assert state.outcome.state == "ok", state.outcome
    assert remote_main(overlays) == head(a)


def test_a_refused_link_does_not_stop_notes_travelling(overlays: Overlays) -> None:
    # A link beside a plain note: the note is committed and pushed, upstream's note arrives, and
    # only the end names the link.
    a = overlays.a
    push_note(overlays.b, "common/memory/from-b.md", note_text("from-b"))
    (a / "common/memory/pw.md").symlink_to("/etc/passwd")
    a_note(overlays, "common/memory/from-a.md", "from-a")

    state = job(overlays)

    assert state.outcome.state == "hook_failed", state.outcome
    assert state.outcome.detail is not None and state.outcome.detail.startswith("job:")
    assert state.outcome.paths == ("common/memory/pw.md",)
    assert (a / "common/memory/from-b.md").read_text() == note_text("from-b")
    assert remote_main(overlays) == head(a)
    files = remote_files(overlays, "common/memory")
    assert "common/memory/from-a.md" in files and "common/memory/pw.md" not in files


def test_a_refused_link_with_a_rejected_push_is_rejected_and_names_the_link(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = overlays.a
    (a / "common/memory/pw.md").symlink_to("/etc/passwd")
    a_note(overlays, "common/memory/from-a.md", "from-a")
    monkeypatch.setattr(
        J, "_before_push", lambda: push_note(overlays.b, "common/memory/race.md", "race\n")
    )

    state = job(overlays)

    assert state.outcome.state == "rejected", state.outcome
    assert state.outcome.detail is not None and "common/memory/pw.md" in state.outcome.detail


# -- the job's end: one rule ----------------------------------------------------------------------


def _said(state: str, detail: str, *paths: str) -> Outcome:
    return Outcome(state, "2026-10-12T12:00:00+00:00", detail, paths, ())


def test_the_end_is_ok_with_nothing_said_and_the_remarks_otherwise(overlays: Overlays) -> None:
    ctx = context(overlays, overlays.a)
    end = J._end(ctx, None)
    assert (end.state, end.detail) == ("ok", None)

    ctx.remarks.append("not pushed while upstream is held")
    end = J._end(ctx, None)
    assert (end.state, end.detail) == ("ok", "not pushed while upstream is held")


def test_without_a_stop_the_end_is_the_latest_notice_refusals_counting_first(
    overlays: Overlays,
) -> None:
    ctx = context(overlays, overlays.a)
    ctx.refused.append("common/memory/link.md")
    end = J._end(ctx, None)
    assert (end.state, end.paths) == ("hook_failed", ("common/memory/link.md",))

    ctx.notices.append(_said("scan_unavailable", "no gitleaks build"))
    assert J._end(ctx, None).state == "scan_unavailable"

    ctx.notices.append(_said("resolved_index", "united: alpha"))
    end = J._end(ctx, None)
    assert end.state == "resolved_index"
    assert end.detail is not None
    assert end.detail.splitlines()[:3] == [
        "united: alpha",
        "also scan_unavailable: no gitleaks build",
        "also hook_failed: " + J._refusal_detail(["common/memory/link.md"]),
    ]


def test_a_stop_is_the_end_whatever_was_noted_and_each_is_said_once(overlays: Overlays) -> None:
    ctx = context(overlays, overlays.a)
    failed = _said("hook_failed", "gitleaks: failed")
    ctx.notices += [failed, failed]
    ctx.remarks.append("a remark")

    end = J._end(ctx, _said("offline", "no route to host"))

    assert end.state == "offline"
    assert end.detail is not None
    assert end.detail.splitlines() == [
        "no route to host",
        "also hook_failed: gitleaks: failed",
        "a remark",
    ]


def test_the_end_detail_cuts_each_part_fairly_and_drops_none(overlays: Overlays) -> None:
    ctx = context(overlays, overlays.a)
    ctx.refused.extend(f"common/memory/link-{number:04}.md" for number in range(200))
    ctx.remarks.append("the remark that must survive")

    end = J._end(ctx, _said("offline", "no route to host"))

    assert end.detail is not None and len(end.detail) <= J.DETAIL_LIMIT
    lines = end.detail.splitlines()
    assert lines[0] == "no route to host" and lines[-1] == "the remark that must survive"
    assert lines[1].startswith("also hook_failed: job: not committed")
    assert lines[1].endswith("...")


# -- bounds ---------------------------------------------------------------------------------------


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_hung_remote_times_out_and_releases_the_lock(overlays: Overlays) -> None:
    # The hung remote has a child of its own: the whole group goes, not only git.
    pidfile = overlays.bare.parent / "grandchild.pid"
    fake_ssh(overlays, f"sleep 60 &\necho $! > '{pidfile}'\nwait")
    started = time.monotonic()
    try:
        state = job(overlays, fetch=1)

        assert time.monotonic() - started < 30
        assert state.outcome.state == "timeout"
        assert state.outcome.detail is not None and "1 s" in state.outcome.detail
        lock = Lock.try_acquire(overlays.state_dir / LOCK_FILE)
        assert lock is not None
        lock.release()
        grandchild = int(pidfile.read_text())
        deadline = time.monotonic() + 5
        while _alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _alive(grandchild), "the remote's child outlived the step"
    finally:
        if pidfile.exists() and _alive(int(pidfile.read_text())):
            os.kill(int(pidfile.read_text()), 9)


def test_the_whole_jobs_limit_records_timeout_and_releases_the_lock(
    overlays: Overlays, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A git the job's own limit has to end: no step's limit is reached, only the whole job's.
    slow_git(tmp_path, monkeypatch, {"status": 30})
    a_note(overlays)
    started = time.monotonic()

    state = job(overlays, job=2)

    assert time.monotonic() - started < 30
    assert state.outcome.state == "timeout", state.outcome
    lock = Lock.try_acquire(overlays.state_dir / LOCK_FILE)
    assert lock is not None
    lock.release()


@pytest.fixture
def git_spy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `git` first on `PATH` that logs, per call, the prompt switch, the ssh command and the
    arguments; the log is the file it returns."""
    real = shutil.which("git")
    shim = tmp_path / "spy"
    shim.mkdir()
    log = shim / "calls.log"
    (shim / "git").write_text(
        "#!/bin/sh\n"
        f'printf "%s\\t%s\\t%s\\n" "${{GIT_TERMINAL_PROMPT-unset}}" "${{GIT_SSH_COMMAND-unset}}" '
        f'"$*" >> "{log}"\n'
        f'exec "{real}" "$@"\n',
        encoding="utf-8",
    )
    (shim / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")
    return log


def test_every_git_call_of_the_job_and_its_scans_runs_non_interactive(
    overlays: Overlays, git_spy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `GIT_TERMINAL_PROMPT=0` and the batch ssh command reach every git call the job's runner
    # makes, the scanner's included, not only fetch and push. The sealed test environment sets
    # the prompt switch itself, so it is taken out here: the job must set it on its own.
    monkeypatch.delenv("GIT_TERMINAL_PROMPT")
    push_note(overlays.b, "common/memory/from-b.md", note_text("from-b"))
    a_note(overlays, "common/memory/from-a.md", "from-a")
    git_spy.unlink(missing_ok=True)

    state = job(overlays)

    assert state.outcome.state == "ok", state.outcome
    calls = [line.split("\t", 2) for line in git_spy.read_text().splitlines()]
    assert any("diff --cached" in argv and "-U0" in argv for _, _, argv in calls)  # the scanner's
    batch = ("0", "ssh -o BatchMode=yes -o ConnectTimeout=10")
    remote = [call for call in calls if call[2].startswith(("push ", "-c fetch.fsckObjects"))]
    assert len(remote) == 2 and all(tuple(call[:2]) == batch for call in remote), remote
    # Three local reads cannot carry the job's environment, and none reaches a remote: the lookup
    # of the ssh command itself, the last read of `HEAD` (made when the job's time may be spent),
    # and the product's own `git -C <checkout> rev-parse` the pre-render asks of each checkout.
    local = ["config --get core.sshCommand", "rev-parse -q --verify HEAD"]
    wrong = [
        call
        for call in calls
        if tuple(call[:2]) != batch
        and call[2] not in local
        and not (call[2].startswith("-C ") and call[2].split(" ")[2] == "rev-parse")
    ]
    assert wrong == [], "\n".join(map(str, wrong))


def test_the_push_is_never_forced_and_carries_no_tags(
    overlays: Overlays, git_spy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_note(overlays, "common/memory/from-a.md", "from-a")
    with monkeypatch.context() as patch:
        patch.setattr(
            J,
            "_before_push",
            lambda: push_note(overlays.b, "common/memory/from-b.md", note_text("from-b")),
        )
        assert job(overlays).outcome.state == "rejected"
    assert job(overlays).outcome.state == "ok"

    calls = [line.split("\t", 2)[2].split(" ") for line in git_spy.read_text().splitlines()]
    pushes = [argv for argv in calls if argv[0] == "push" and "--porcelain" in argv]
    assert len(pushes) == 2
    for argv in pushes:
        assert not {"-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror"} & set(
            argv
        )
        assert not any(item.startswith(("+", "--force")) for item in argv)
        assert argv[-1].endswith(":refs/heads/main") and len(argv[-1].split(":")[0]) == 40
        assert "--no-follow-tags" in argv  # whatever `push.followTags` says: the range only


def test_a_replace_ref_cannot_disguise_a_commit(overlays: Overlays) -> None:
    # With `refs/replace/`, `git log` would show the range check a memory-only stand-in for a
    # commit that changes a hook; the job reads the real objects.
    a = overlays.a
    before = remote_main(overlays)
    write(a, "common/claude/hooks/launch.sh", "#!/bin/sh\necho changed\n")
    real = commit_all(a, "hook")
    git(a, "reset", "-q", "--hard", "HEAD^")
    write(a, "common/memory/innocent.md", note_text("innocent"))
    fake = commit_all(a, "memory: innocent")
    git(a, "reset", "-q", "--hard", real)
    git(a, "replace", real, fake)

    state = job(overlays)

    assert state.holds.local_commits == (real,)
    assert remote_main(overlays) == before


def test_an_unreadable_state_is_replaced_and_said(overlays: Overlays) -> None:
    overlays.state_dir.mkdir(parents=True, exist_ok=True)
    (overlays.state_dir / STATE_FILE).write_text("{not json", encoding="utf-8")

    state = job(overlays)

    assert state.outcome.state == "ok", state.outcome
    assert state.outcome.detail is not None
    assert "the previous state could not be read and was replaced" in state.outcome.detail
    assert read_state(overlays.state_dir) == state


def test_the_guard_skips_another_branch_and_an_operation_in_progress(overlays: Overlays) -> None:
    a = overlays.a
    git(a, "checkout", "-q", "-b", "elsewhere")
    state = job(overlays)
    assert state.outcome.state == "skipped"
    assert state.outcome.detail is not None and "elsewhere" in state.outcome.detail
    git(a, "checkout", "-q", "main")

    (a / ".git" / "rebase-merge").mkdir()
    a_note(overlays)
    state = job(overlays)
    assert state.outcome.state == "skipped"
    assert state.outcome.detail is not None and "rebase" in state.outcome.detail
    assert "?? common/memory/new.md" in git(a, "status", "--porcelain")
