"""The job's fetch, its integration of the checked upstream sha by replay, and the index union.

Integration never rebases. The new tip is computed without touching the working tree or the real
index -- a fast-forward to the fetched sha, or each local commit replayed onto it with `merge-tree
--write-tree` and `commit-tree` -- and only a range that is memory-only by both rules is integrated
at all; anything else is an upstream hold. Then the move is recorded, `main` moved by
compare-and-swap, the incoming notes written through git, and the index aligned.
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import time
from pathlib import Path

import pytest

from stayfixed.sync import git as G
from stayfixed.sync import job as J
from stayfixed.sync.git import Ran
from stayfixed.sync.state import Holds, SyncState, read_state
from tests.gitfixture import git_bytes
from tests.sync.conftest import (
    HOST,
    SLOW,
    TAG,
    Overlays,
    commit_all,
    context,
    crafted_commit,
    git,
    head,
    memory_status,
    merge_with_resolution,
    note_text,
    push_note,
    rename,
    slow_git,
    ssh_signing,
    staged,
    write,
)


def fetched(overlays: Overlays, clone: Path) -> str:
    sha, failed = J.fetch(context(overlays, clone))
    assert failed is None and sha is not None, failed
    return sha


def no_rebase_dir(repo: Path) -> bool:
    return (
        not (repo / ".git" / "rebase-merge").exists()
        and not (repo / ".git" / "rebase-apply").exists()
    )


# -- the union ------------------------------------------------------------------------------------


def test_the_union_keeps_upstream_and_adds_the_local_only_bullets() -> None:
    # Mutation (oracle): `mutations/`'s "the union drops the local-only bullets".
    upstream = b"# Memory Index\n\n## g\n\n- [Up](g/u.md)\n- [Both](g/b.md)\n"
    local = b"# Memory Index\n\n## g\n\n- [Both](g/b.md)\n- [Mine](g/m.md)\nprose only local\n"

    assert J.union_index(local, upstream) == upstream + b"- [Mine](g/m.md)\n"
    assert J.union_index(local, upstream.rstrip(b"\n")) == upstream + b"- [Mine](g/m.md)\n"
    assert J.union_index(upstream, upstream) == upstream


# -- fast-forward and replay ----------------------------------------------------------------------


def test_a_memory_only_upstream_fast_forwards_onto_the_checked_sha(overlays: Overlays) -> None:
    u = push_note(overlays.b, "common/memory/from-b.md", "from b\n")
    ctx = context(overlays, overlays.a)

    assert J.integrate(ctx, fetched(overlays, overlays.a)) is None

    assert not ctx.holds.any and ctx.pending is None
    assert head(overlays.a) == u
    assert (overlays.a / "common/memory/from-b.md").read_text() == "from b\n"
    assert memory_status(overlays.a) == "" and staged(overlays.a) == ""


def test_an_upstream_group_note_is_integrated(overlays: Overlays) -> None:
    note = f"groups/{TAG}/memory/{TAG}-from-b.md"
    u = push_note(overlays.b, note, note_text("from-b"))

    assert J.integrate(context(overlays, overlays.a), fetched(overlays, overlays.a)) is None

    assert head(overlays.a) == u and (overlays.a / note).read_text() == note_text("from-b")


def test_a_local_memory_commit_is_replayed_onto_the_checked_sha(overlays: Overlays) -> None:
    # Mutation (oracle): `mutations/`'s "the integration rebases".
    u = push_note(overlays.b, "common/memory/from-b.md", "from b\n")
    a = overlays.a
    write(a, "projects/alpha/memory/project-stable/from-a.md", "from a\n")
    git(a, "add", "-A")
    git(
        a, "-c", "user.name=Someone Else", "commit", "-q", "--author",
        "Owner A <a@example.invalid>", "-m", "memory: from a\n\nwith a body line",
    )  # fmt: skip

    assert J.integrate(context(overlays, a), fetched(overlays, a)) is None

    assert git(a, "rev-parse", "HEAD^").strip() == u
    assert git(a, "log", "-1", "--format=%an <%ae>%n%B").strip() == (
        "Owner A <a@example.invalid>\nmemory: from a\n\nwith a body line"
    )
    assert (a / "common/memory/from-b.md").read_text() == "from b\n"
    assert (a / "projects/alpha/memory/project-stable/from-a.md").read_text() == "from a\n"
    assert memory_status(a) == "" and no_rebase_dir(a)


@pytest.mark.parametrize("local_commit", [False, True], ids=["fast-forward", "replay"])
def test_an_unstaged_non_memory_edit_does_not_block_a_memory_upstream(
    overlays: Overlays, local_commit: bool
) -> None:
    a = overlays.a
    push_note(overlays.b, "common/memory/from-b.md", "from b\n")
    edit = b"print('work in progress')\r\n\xfe no newline"
    (a / "common/claude/hooks/x.py").write_bytes(edit)
    write(a, "README.md", "staged by the owner\n")
    git(a, "add", "README.md")
    if local_commit:
        write(a, "common/memory/from-a.md", "from a\n")
        git(a, "add", "common/memory/from-a.md")
        git(a, "commit", "-q", "-m", "memory: from a", "--", "common/memory/from-a.md")

    assert J.integrate(context(overlays, a), fetched(overlays, a)) is None

    assert (a / "common/memory/from-b.md").read_text() == "from b\n"
    assert (a / "common/claude/hooks/x.py").read_bytes() == edit
    assert staged(a) == "README.md\n"
    assert git(a, "status", "--porcelain", "--", "common/claude/hooks/x.py") == (
        " M common/claude/hooks/x.py\n"
    )


def test_an_identical_change_on_both_sides_is_not_replayed_as_an_empty_commit(
    overlays: Overlays,
) -> None:
    u = push_note(overlays.b, "common/memory/same.md", "same\n")
    a = overlays.a
    write(a, "common/memory/same.md", "same\n")
    commit_all(a, "memory: same")

    assert J.integrate(context(overlays, a), fetched(overlays, a)) is None

    assert head(a) == u


def test_a_replay_keeps_the_author_of_a_signed_commit_under_show_signature(
    overlays: Overlays, tmp_path: Path
) -> None:
    # With `log.showSignature`, `git log --format` prints the signature check first; the author
    # comes from the commit itself, never from that text. Mutation (oracle): `mutations/`'s "a
    # replay drops its commit's author".
    a = overlays.a
    ssh_signing(tmp_path, a)
    push_note(overlays.b, "common/memory/from-b.md", "from b\n")
    write(a, "common/memory/from-a.md", "from a\n")
    git(a, "add", "-A")
    git(a, "commit", "-q", "--author", "Owner A <a@example.invalid>", "-m", "memory: from a")
    assert "Good" in git(a, "log", "-1", "--format=%an")  # the shape that misleads a parser

    assert J.integrate(context(overlays, a), fetched(overlays, a)) is None

    raw = git(a, "cat-file", "commit", "HEAD")
    author = next(line for line in raw.splitlines() if line.startswith("author "))
    assert author.startswith("author Owner A <a@example.invalid> ")
    assert "gpgsig" in raw  # replayed, and signed as `commit.gpgsign` says


def test_a_replay_keeps_a_non_utf8_message_and_its_encoding(
    overlays: Overlays, tmp_path: Path
) -> None:
    a = overlays.a
    push_note(overlays.b, "common/memory/from-b.md", "from b\n")
    message = tmp_path / "message"
    message.write_bytes("memory: café au lait\n".encode("latin-1"))
    write(a, "common/memory/from-a.md", "from a\n")
    git(a, "add", "-A")
    git(a, "-c", "i18n.commitEncoding=ISO-8859-1", "commit", "-q", "-F", str(message))

    assert J.integrate(context(overlays, a), fetched(overlays, a)) is None

    raw = git_bytes(a, "cat-file", "commit", "HEAD")
    assert b"\nencoding ISO-8859-1\n" in raw
    assert raw.endswith(b"\n\nmemory: caf\xe9 au lait\n")


# -- what is replayed at all ----------------------------------------------------------------------


def _job(overlays: Overlays) -> SyncState:
    state = J.run_job(context(overlays, overlays.a))
    assert state is not None
    return state


def test_an_owners_commit_outside_memory_keeps_its_sha_and_holds_the_sync(
    overlays: Overlays,
) -> None:
    # A replay rebuilds a commit with the job as committer and its own signing: the owner's hook
    # commit would get a sha the owner never made, and the hold would name that copy. Only a local
    # range of memory alone is replayed; anything else is the local hold, `HEAD` untouched.
    # Mutation (oracle): `mutations/`'s "a local range outside memory is replayed".
    a = overlays.a
    write(a, "common/claude/hooks/launch.sh", "#!/bin/sh\nthe owner's own hook change\n")
    own = commit_all(a, "the owner's hook")
    upstream = push_note(overlays.b, "common/memory/from-b.md", "from b\n")

    state = _job(overlays)

    assert head(a) == own
    assert state.holds.local_commits == (own,)
    assert git(overlays.bare, "rev-parse", "main").strip() == upstream
    assert not (a / "common/memory/from-b.md").exists()  # nothing integrated either
    assert f"git log -p --no-renames HEAD..{upstream}" in str(state.outcome.detail)


@pytest.mark.parametrize("kind", ["merge", "empty"])
def test_a_local_merge_or_empty_commit_is_held_never_replayed(
    overlays: Overlays, kind: str
) -> None:
    # Neither lists a path a range check could judge: each is the owner's, held as it is.
    a = overlays.a
    if kind == "merge":
        git(a, "checkout", "-q", "-b", "side")
        write(a, "common/memory/side.md", "side\n")
        commit_all(a, "memory: side")
        git(a, "checkout", "-q", "main")
        write(a, "common/memory/main.md", "main\n")
        commit_all(a, "memory: main")
        git(a, "merge", "-q", "--no-ff", "-m", "memory: merge side", "side")
    else:
        git(a, "commit", "-q", "--allow-empty", "-m", "owner: a marker")
    own = head(a)
    push_note(overlays.b, "common/memory/from-b.md", "from b\n")

    state = _job(overlays)

    assert head(a) == own and own in state.holds.local_commits


def _purged_on_b(overlays: Overlays) -> str:
    """A private note pushed from `b` and integrated by `a`'s job, then purged on `b`: the commit
    dropped and `main` forced back, with a later note on top. The purged commit's sha."""
    b = overlays.b
    leaked = push_note(b, "common/memory/private.md", "private address: 1 Example Road\n")
    assert _job(overlays).outcome.state == "ok" and head(overlays.a) == leaked
    git(b, "reset", "-q", "--hard", "HEAD~1")
    write(b, "common/memory/other.md", "unrelated\n")
    commit_all(b, "memory: other")
    git(b, "push", "-q", "--force", "origin", "main")
    return leaked


def test_a_purge_forced_elsewhere_does_not_come_back(overlays: Overlays) -> None:
    # The fetched sha the last job recorded is not in the new upstream: upstream lost history,
    # and the purged commit, still in this `HEAD`, would read as a local commit to replay and
    # push. Held instead, naming it, until the owner takes the rewrite or undoes it by hand.
    # Mutation (oracle): `mutations/`'s "an upstream rewrite is replayed".
    a = overlays.a
    leaked = _purged_on_b(overlays)
    before, remote = head(a), git(overlays.bare, "rev-parse", "main").strip()

    for _ in range(2):  # the next job still holds: the record is the hold, not the last fetch
        state = _job(overlays)
        assert head(a) == before and git(overlays.bare, "rev-parse", "main").strip() == remote
        assert state.holds.upstream_paths == (leaked,) and state.holds.upstream_why == "rewritten"
        assert "upstream was rewritten" in str(state.outcome.detail)

    git(a, "reset", "-q", "--hard", "origin/main")  # the owner takes the rewrite
    state = _job(overlays)
    assert not state.holds.any and head(a) == remote
    assert "common/memory/private.md" not in git(a, "ls-tree", "-r", "--name-only", "HEAD")


def test_a_purge_of_a_note_this_machine_pushed_does_not_come_back(overlays: Overlays) -> None:
    # After its push the job records the sha it pushed as upstream's: a purge of its own note
    # before its next fetch is a rewrite too, not a local commit to push again. Mutation (oracle):
    # `mutations/`'s "the push records nothing of what upstream now has".
    a, b = overlays.a, overlays.b
    write(a, "common/memory/mine.md", note_text("mine"))
    assert _job(overlays).outcome.state == "ok"
    mine = head(a)
    assert git(overlays.bare, "rev-parse", "main").strip() == mine
    git(b, "fetch", "-q", "origin")
    git(b, "reset", "-q", "--hard", f"{mine}~1")
    write(b, "common/memory/other.md", "unrelated\n")
    commit_all(b, "memory: other")
    git(b, "push", "-q", "--force", "origin", "main")

    state = _job(overlays)

    assert mine in state.holds.upstream_paths and state.holds.upstream_why == "rewritten"
    assert "mine.md" not in git(overlays.bare, "ls-tree", "-r", "--name-only", "main")


def test_a_first_fetch_records_no_rewrite(overlays: Overlays) -> None:
    # No sha recorded yet: an upstream this machine never fetched cannot have lost anything.
    push_note(overlays.b, "common/memory/from-b.md", "from b\n")
    ctx = context(overlays, overlays.a)

    assert J.integrate(ctx, fetched(overlays, overlays.a), None) is None

    assert not ctx.holds.any and (overlays.a / "common/memory/from-b.md").exists()


# -- what blocks integration ----------------------------------------------------------------------


def test_a_dirty_incoming_note_is_waiting_clean_tree(overlays: Overlays) -> None:
    # Mutation (oracle): `mutations/`'s "an incoming note dirty here does not wait".
    a = overlays.a
    upstream_text = note_text("first", index="First trigger") + "An upstream line.\n"
    push_note(overlays.b, "common/memory/first.md", upstream_text)
    before = head(a)
    write(a, "common/memory/first.md", note_text("first", index="First trigger (edited here)"))
    ctx = context(overlays, a)

    outcome = J.integrate(ctx, fetched(overlays, a))

    assert outcome is not None and outcome.state == "waiting_clean_tree"
    assert "(common/memory/first.md)" in str(outcome.detail)
    assert head(a) == before and ctx.pending is None
    assert "edited here" in (a / "common/memory/first.md").read_text()


def _agent_appends(clone: Path, project: str, name: str, title: str) -> Path:
    """An agent's new note in `project` and its line appended to the index, both uncommitted."""
    write(clone, f"projects/{project}/memory/project-stable/{name}.md", note_text(name))
    index = clone / f"projects/{project}/memory/MEMORY.md"
    index.write_text(index.read_text() + f"- [{title}](project-stable/{name}.md)\n")
    return index


def test_a_dirty_index_is_united_in_the_working_tree_never_blocking(overlays: Overlays) -> None:
    # Every incoming shared note re-renders the indexes, so an index an agent appended to and
    # nobody committed is merged by union, the agent's line kept, and never waited on.
    # Mutation (oracle): `mutations/`'s "a dirty index waits like a note".
    a, b = overlays.a, overlays.b
    write(b, "common/memory/shared.md", note_text("shared", index="Shared"))
    overlays.render(b, "alpha")
    commit_all(b, "memory: shared, from b")
    git(b, "push", "-q", "origin", "main")
    index = _agent_appends(a, "alpha", "agent-note", "Agent line on a")
    ctx = context(overlays, a)

    assert J.integrate(ctx, fetched(overlays, a)) is None

    assert (a / "common/memory/shared.md").exists()
    text = index.read_text()
    assert "- [Agent line on a](project-stable/agent-note.md)" in text  # kept
    assert "- [Shared](developer/shared.md)" in text  # upstream's rendering, united
    assert [notice.state for notice in ctx.notices] == ["resolved_index"]


def test_an_index_changed_while_the_union_is_built_is_left_for_the_next_job(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An agent appending its line between the read and the write wins: nothing is overwritten.
    # Mutation (oracle): `mutations/`'s "the union overwrites a line appended while it was
    # built".
    a, b = overlays.a, overlays.b
    write(b, "common/memory/shared.md", note_text("shared", index="Shared"))
    overlays.render(b, "alpha")
    commit_all(b, "memory: shared")
    git(b, "push", "-q", "origin", "main")
    index = _agent_appends(a, "alpha", "first-agent", "First agent line")
    real_union = J.union_index

    def union_then_an_agent_appends(local: bytes, upstream: bytes) -> bytes:
        index.write_text(index.read_text() + "- [Late line](project-stable/late.md)\n")
        return real_union(local, upstream)

    monkeypatch.setattr(J, "union_index", union_then_an_agent_appends)
    ctx = context(overlays, a)

    assert J.integrate(ctx, fetched(overlays, a)) is None

    assert ctx.notices == [] and (a / "common/memory/shared.md").exists()
    text = index.read_text()
    assert "First agent line" in text and "Late line" in text and "Shared" not in text


def test_a_link_above_an_incoming_path_blocks_and_nothing_escapes(
    overlays: Overlays, tmp_path: Path
) -> None:
    a = overlays.a
    outside = tmp_path / "outside"
    outside.mkdir()
    push_note(overlays.b, "projects/zeta/memory/project-stable/n.md", "a note\n")
    (a / "projects" / "zeta").symlink_to(outside, target_is_directory=True)
    before = head(a)

    outcome = J.integrate(context(overlays, a), fetched(overlays, a))

    assert outcome is not None and outcome.state == "waiting_clean_tree"
    assert "(projects/zeta/memory/project-stable/n.md)" in str(outcome.detail)
    assert head(a) == before and list(outside.iterdir()) == []

    # A link inside memory, where upstream turns a note into a directory of notes.
    (a / "projects" / "zeta").unlink()
    push_note(overlays.b, "common/memory/sub/n.md", "a nested note\n")
    (a / "common/memory/sub").symlink_to(outside, target_is_directory=True)

    outcome = J.integrate(context(overlays, a), fetched(overlays, a))

    assert outcome is not None and outcome.state == "waiting_clean_tree"
    assert "common/memory/sub/n.md" in str(outcome.detail) and list(outside.iterdir()) == []


# -- a kill after the swap ------------------------------------------------------------------------


class _Killed(BaseException):
    """The job dies here: nothing after this point runs, as with SIGKILL."""


def _swap_then_die(monkeypatch: pytest.MonkeyPatch) -> None:
    real_swap = J._swap

    def swap_then_die(ctx: J.JobContext, new: str, old: str) -> bool:
        assert real_swap(ctx, new, old)
        raise _Killed

    monkeypatch.setattr(J, "_swap", swap_then_die)


def test_a_kill_after_the_swap_is_finished_by_the_next_job(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = overlays.a, overlays.b
    push_note(b, "common/memory/from-b.md", "from b\n")
    (b / "common/memory/first.md").unlink()
    git(b, "commit", "-q", "-am", "memory: drop first")
    git(b, "push", "-q", "origin", "main")
    upstream = fetched(overlays, a)

    with monkeypatch.context() as patch, pytest.raises(_Killed):
        _swap_then_die(patch)
        J.integrate(context(overlays, a), upstream)

    assert head(a) == upstream
    state = read_state(overlays.state_dir)
    assert state is not None and state.pending_align is not None
    assert state.pending_align.to_sha == upstream
    assert set(state.pending_align.paths) == {"common/memory/from-b.md", "common/memory/first.md"}
    assert not (a / "common/memory/from-b.md").exists()  # killed before the write

    assert J.align_first(context(overlays, a, pending=state.pending_align)) is None

    assert (a / "common/memory/from-b.md").read_text() == "from b\n"
    assert not (a / "common/memory/first.md").exists()
    assert memory_status(a) == "" and staged(a) == ""


def test_a_link_appearing_after_a_kill_is_named_by_the_job_that_finishes_it(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The pending write meets a link above its path: nothing is written beyond it, and a notice
    # names it instead of an arrival that did not happen.
    a = overlays.a
    outside = tmp_path / "outside"
    outside.mkdir()
    push_note(overlays.b, "common/memory/sub/n.md", "a nested note\n")
    upstream = fetched(overlays, a)
    with monkeypatch.context() as patch, pytest.raises(_Killed):
        _swap_then_die(patch)
        J.integrate(context(overlays, a), upstream)
    (a / "common/memory/sub").symlink_to(outside, target_is_directory=True)
    state = read_state(overlays.state_dir)
    assert state is not None
    ctx = context(overlays, a, pending=state.pending_align)

    assert J.align_first(ctx) is None

    [notice] = ctx.notices
    assert notice.state == "hook_failed" and str(notice.detail).endswith(": common/memory/sub/n.md")
    assert ctx.pending is None and list(outside.iterdir()) == []


def test_the_owners_edit_after_the_kill_wins_over_the_pending_write(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Incoming notes are written only where the working tree still has the old version.
    # Mutation (oracle): `mutations/`'s "a pending write goes over the owner's edit".
    a = overlays.a
    push_note(overlays.b, "common/memory/first.md", "upstream's first\n")
    upstream = fetched(overlays, a)
    with monkeypatch.context() as patch, pytest.raises(_Killed):
        _swap_then_die(patch)
        J.integrate(context(overlays, a), upstream)
    write(a, "common/memory/first.md", "the owner wrote this meanwhile\n")
    state = read_state(overlays.state_dir)
    assert state is not None

    assert J.align_first(context(overlays, a, pending=state.pending_align)) is None

    assert (a / "common/memory/first.md").read_text() == "the owner wrote this meanwhile\n"


def test_main_moved_by_the_owner_during_the_integration_is_raced(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The swap compares against the HEAD the integration checked: the owner's commit landing in
    # between stays on `main`.
    a = overlays.a
    push_note(overlays.b, "common/memory/from-b.md", "from b\n")
    upstream = fetched(overlays, a)
    owner: list[str] = []

    def owner_commits() -> None:
        write(a, "README.md", "the owner's edit\n")
        git(a, "commit", "-q", "-m", "owner", "--", "README.md")
        owner.append(head(a))

    monkeypatch.setattr(J, "_before_swap", owner_commits)
    ctx = context(overlays, a)

    outcome = J.integrate(ctx, upstream)

    assert outcome is not None and outcome.state == "raced"
    assert head(a) == owner[0] and ctx.pending is None
    state = read_state(overlays.state_dir)
    assert state is not None and state.pending_align is None
    assert not (a / "common/memory/from-b.md").exists()


def test_upstream_moving_after_the_fetch_is_not_integrated(overlays: Overlays) -> None:
    a = overlays.a
    u = push_note(overlays.b, "common/memory/one.md", "one\n")
    upstream = fetched(overlays, a)
    push_note(overlays.b, "common/memory/two.md", "two\n")  # a second pusher
    git(a, "fetch", "-q", "origin")  # and origin/main moves under the job

    assert J.integrate(context(overlays, a), upstream) is None

    assert head(a) == u
    assert (a / "common/memory/one.md").exists() and not (a / "common/memory/two.md").exists()


def test_the_fetched_sha_is_read_from_the_jobs_own_ref(
    overlays: Overlays, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The owner's `git fetch origin side` rewrites `FETCH_HEAD` at any moment; the job reads the
    # sha it fetched from its own ref. Mutation (oracle): `mutations/`'s "the fetched sha is
    # read from FETCH_HEAD".
    a, b = overlays.a, overlays.b
    u = push_note(b, "common/memory/one.md", "one\n")
    git(b, "push", "-q", "origin", "HEAD~1:refs/heads/side")
    real = G.git

    def and_the_owner_fetches(repo: Path, *args: str, **kwargs: object) -> Ran:
        result = real(repo, *args, **kwargs)  # type: ignore[arg-type]
        if "fetch" in args:
            git(a, "fetch", "-q", "origin", "side")
        return result

    monkeypatch.setattr(J, "git", and_the_owner_fetches)

    assert fetched(overlays, a) == u


# -- upstream holds -------------------------------------------------------------------------------


def test_a_tree_git_cannot_check_out_is_refused_at_the_fetch(overlays: Overlays) -> None:
    # A hostile remote's `projects/../memory/x.md`: the fetch checks every object it receives.
    # Mutation (oracle): `mutations/`'s "the fetch checks no object it receives".
    a, b = overlays.a, overlays.b
    crafted = crafted_commit(b, head(b), "projects/../memory/x.md")
    git(b, "push", "-q", "origin", f"{crafted}:refs/heads/main")

    sha, outcome = J.fetch(context(overlays, a))

    assert sha is None and outcome is not None and outcome.state == "hook_failed"
    assert str(outcome.detail).startswith("job: git fetch origin main failed")


def test_a_tree_git_cannot_check_out_is_held_not_moved_to(overlays: Overlays) -> None:
    # Past the fetch's check (an NTFS alias of `.git`, reached here without a fetch), a tree that
    # passes every rule but that git will not put in an index is an upstream hold. Mutation
    # (oracle): `mutations/`'s "a tip git cannot read is integrated".
    a = overlays.a
    path = "projects/alpha/memory/GIT~1/n.md"
    crafted = crafted_commit(a, head(a), path)
    before = head(a)
    ctx = context(overlays, a)

    assert J.integrate(ctx, crafted) is None

    assert head(a) == before and ctx.pending is None
    assert ctx.holds.upstream_paths == (path,)
    assert any("cannot be checked out" in remark for remark in ctx.remarks)
    assert read_state(overlays.state_dir) is None  # no pending record was ever written


def _held(overlays: Overlays, ctx: J.JobContext, before: str) -> set[str]:
    assert head(overlays.a) == before
    return set(ctx.holds.upstream_paths)


def test_an_upstream_hook_change_is_held(overlays: Overlays) -> None:
    # Mutation (oracle): `mutations/`'s "a range outside memory is integrated".
    b = overlays.b
    write(b, "common/claude/hooks/launch.sh", "#!/bin/sh\necho changed\n")
    write(b, "common/memory/from-b.md", "from b\n")
    commit_all(b, "hook and note")
    git(b, "push", "-q", "origin", "main")
    before = head(overlays.a)
    ctx = context(overlays, overlays.a)

    assert J.integrate(ctx, fetched(overlays, overlays.a)) is None

    assert "common/claude/hooks/launch.sh" in _held(overlays, ctx, before)
    assert not (overlays.a / "common/memory/from-b.md").exists()


def _review_and_take(remarks: list[str]) -> tuple[list[str], list[str]]:
    """The commands the hold remark gives: the review, and the take."""
    text = "\n".join(remarks)
    review = re.search(r"git log -p.*?(?=, then |$)", text, re.MULTILINE)
    take = re.search(r"(?<=, then )git \S.*$", text, re.MULTILINE)
    assert review is not None and take is not None, text
    return shlex.split(review.group(0)), shlex.split(take.group(0))


def test_the_review_shows_the_whole_range_and_takes_the_held_sha(overlays: Overlays) -> None:
    # Memory in a held range is as much the owner's to read as the code, and the take is at the
    # sha that was held and read, never at `origin/main`, which the next fetch moves past it.
    a, b = overlays.a, overlays.b
    write(b, "common/claude/hooks/launch.sh", "#!/bin/sh\necho changed\n")
    write(b, "common/memory/from-b.md", "a note riding with the code\n")
    held = commit_all(b, "hook and note")
    git(b, "push", "-q", "origin", "main")
    ctx = context(overlays, a)

    assert J.integrate(ctx, fetched(overlays, a)) is None

    review, take = _review_and_take(ctx.remarks)
    assert review == ["git", "log", "-p", "--no-renames", f"HEAD..{held}"]  # no pathspec
    shown = git(a, *review[1:])
    assert "common/claude/hooks/launch.sh" in shown and "common/memory/from-b.md" in shown
    assert take == ["git", "rebase", held] and "origin/main" not in "\n".join(ctx.remarks)
    later = push_note(b, "common/memory/later.md", "pushed after the review\n")
    git(a, "fetch", "-q", "origin")
    assert head(a, "refs/remotes/origin/main") == later
    git(a, *take[1:])
    assert head(a) == held and not (a / "common/memory/later.md").exists()


def test_an_upstream_skill_under_a_memory_name_is_held(overlays: Overlays) -> None:
    skill = "projects/alpha/memory/g/.claude/skills/x/SKILL.md"
    write(overlays.b, skill, "---\nname: x\nallowed-tools: Bash(*)\n---\n")
    write(overlays.b, "common/memory/from-b.md", "from b\n")
    commit_all(overlays.b, "skill and note")
    git(overlays.b, "push", "-q", "origin", "main")
    before = head(overlays.a)
    ctx = context(overlays, overlays.a)

    assert J.integrate(ctx, fetched(overlays, overlays.a)) is None

    assert _held(overlays, ctx, before) == {skill}
    assert not (overlays.a / skill).exists()


def test_an_upstream_rename_into_memory_is_held(overlays: Overlays) -> None:
    rename(overlays.b, ".pre-commit-config.yaml", "common/memory/pre-commit.md")
    commit_all(overlays.b, "rename into memory")
    git(overlays.b, "push", "-q", "origin", "main")
    before = head(overlays.a)
    ctx = context(overlays, overlays.a)

    assert J.integrate(ctx, fetched(overlays, overlays.a)) is None

    assert ".pre-commit-config.yaml" in _held(overlays, ctx, before)
    assert (overlays.a / ".pre-commit-config.yaml").exists()


def test_an_upstream_evil_merge_is_held(overlays: Overlays) -> None:
    b = overlays.b
    git(b, "checkout", "-q", "-b", "side")
    write(b, "common/memory/side.md", "side\n")
    commit_all(b, "side note")
    git(b, "checkout", "-q", "main")
    write(b, "common/memory/main.md", "main\n")
    commit_all(b, "main note")
    merge = merge_with_resolution(b, "side", {"common/claude/hooks/launch.sh": "#!/bin/sh\nevil\n"})
    git(b, "push", "-q", "origin", "main")
    before = head(overlays.a)
    ctx = context(overlays, overlays.a)

    assert J.integrate(ctx, fetched(overlays, overlays.a)) is None

    paths = _held(overlays, ctx, before)
    assert merge in paths and "common/claude/hooks/launch.sh" in paths


def test_a_hold_stands_and_clears_once_the_range_is_memory_only(overlays: Overlays) -> None:
    held = Holds(("common/claude/hooks/launch.sh",), ("abc",))
    write(overlays.b, "common/claude/hooks/launch.sh", "#!/bin/sh\nstill\n")
    commit_all(overlays.b, "hook")
    git(overlays.b, "push", "-q", "origin", "main")
    ctx = context(overlays, overlays.a)
    ctx.holds = held

    J.integrate(ctx, fetched(overlays, overlays.a))

    # Still held, and the local hold is not this step's business.
    assert ctx.holds.upstream_paths and ctx.holds.local_commits == ("abc",)

    git(overlays.a, "merge", "-q", "--ff-only", "origin/main")  # the owner reviews and takes it
    push_note(overlays.b, "common/memory/n.md", "n\n")
    ctx = context(overlays, overlays.a)
    ctx.holds = held

    J.integrate(ctx, fetched(overlays, overlays.a))

    assert ctx.holds.upstream_paths == ()
    assert ctx.holds.local_commits == ("abc",)


# -- conflicts ------------------------------------------------------------------------------------


def _note_conflict(overlays: Overlays) -> str:
    push_note(overlays.b, "common/memory/first.md", "upstream's version\n")
    write(overlays.a, "common/memory/first.md", "local version\n")
    write(overlays.a, "common/memory/other.md", "another local note\n")
    commit_all(overlays.a, "memory: local")
    return head(overlays.a)


def test_a_note_conflict_is_a_conflict_with_main_unmoved(overlays: Overlays) -> None:
    a = overlays.a
    before = _note_conflict(overlays)
    edit = b"x = 1  # in progress\n"
    (a / "common/claude/hooks/x.py").write_bytes(edit)
    upstream = fetched(overlays, a)
    ctx = context(overlays, a)

    outcome = J.integrate(ctx, upstream)

    assert outcome is not None and outcome.state == "conflict"
    assert "upstream on common/memory/first.md;" in str(outcome.detail)
    assert head(a) == before and ctx.pending is None
    assert (a / "common/memory/first.md").read_text() == "local version\n"
    assert (a / "common/claude/hooks/x.py").read_bytes() == edit
    assert memory_status(a) == "" and staged(a) == ""
    assert not (a / ".git" / "MERGE_HEAD").exists() and no_rebase_dir(a)
    assert read_state(overlays.state_dir) is None
    # Integrating by hand means the sha this job checked, never what `origin/main` names later.
    assert "origin/main" not in str(outcome.detail)
    review, take = _review_and_take([str(outcome.detail)])
    assert review == ["git", "log", "-p", "--no-renames", f"HEAD..{upstream}"]
    assert take == ["git", "rebase", upstream]


def _agent_line(clone: Path, project: str, name: str, title: str) -> None:
    """An agent's new note and its line appended to the index, committed as they are."""
    write(clone, f"projects/{project}/memory/project-stable/{name}.md", note_text(name))
    with open(clone / f"projects/{project}/memory/MEMORY.md", "a", encoding="utf-8") as index:
        index.write(f"- [{title}](project-stable/{name}.md)\n")


def _both_sides_append_to_two_indexes(overlays: Overlays) -> None:
    for project in ("alpha", "beta"):
        _agent_line(overlays.b, project, f"{project}-from-b", f"{project} line written on b")
    commit_all(overlays.b, "memory: b's agent lines")
    git(overlays.b, "push", "-q", "origin", "main")
    for project in ("alpha", "beta"):
        _agent_line(overlays.a, project, f"{project}-from-a", f"{project} line written on a")
    commit_all(overlays.a, "memory: a's agent lines")


def test_two_index_conflicts_are_resolved_by_union_and_re_rendered(overlays: Overlays) -> None:
    a = overlays.a
    _both_sides_append_to_two_indexes(overlays)
    upstream = fetched(overlays, a)
    ctx = context(overlays, a)

    assert J.integrate(ctx, upstream) is None

    [notice] = ctx.notices
    assert notice.state == "resolved_index"
    assert str(notice.detail).endswith("united: alpha, beta")
    for project in ("alpha", "beta"):
        index = (a / f"projects/{project}/memory/MEMORY.md").read_text()
        for side in ("a", "b"):
            title = f"{project} line written on {side}"
            assert f"- [{title}](project-stable/{project}-from-{side}.md)" in index
            note = a / f"projects/{project}/memory/project-stable/{project}-from-{side}.md"
            assert f"index: {title}" in note.read_text()  # harvested by the re-render
    # The replayed commit sits on the checked sha, and the re-render is committed after it.
    assert git(a, "rev-parse", "HEAD~2").strip() == upstream
    assert git(a, "log", "-1", "--format=%s").strip().endswith(f"from {HOST}")
    assert memory_status(a) == ""


def test_an_index_conflict_beside_a_note_conflict_is_a_conflict(overlays: Overlays) -> None:
    _agent_line(overlays.b, "alpha", "from-b", "line on b")
    write(overlays.b, "common/memory/first.md", "upstream's version\n")
    commit_all(overlays.b, "b")
    git(overlays.b, "push", "-q", "origin", "main")
    _agent_line(overlays.a, "alpha", "from-a", "line on a")
    write(overlays.a, "common/memory/first.md", "local version\n")
    commit_all(overlays.a, "a")
    before = head(overlays.a)

    outcome = J.integrate(context(overlays, overlays.a), fetched(overlays, overlays.a))

    assert outcome is not None and outcome.state == "conflict" and head(overlays.a) == before
    assert "on common/memory/first.md, projects/alpha/memory/MEMORY.md;" in str(outcome.detail)


# -- what runs ------------------------------------------------------------------------------------


@pytest.fixture
def git_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `git` first on PATH that records every argv, then runs the real one."""
    real = next(
        os.path.join(directory, "git")
        for directory in os.environ["PATH"].split(os.pathsep)
        if os.access(os.path.join(directory, "git"), os.X_OK)
    )
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    log = tmp_path / "git-argv.log"
    shim = shim_dir / "git"
    shim.write_text(
        f'#!/bin/sh\nprintf "%s\\0" "$@" >> "{log}"\nprintf "\\n" >> "{log}"\nexec "{real}" "$@"\n'
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def subcommands(log: Path) -> list[list[str]]:
    """Each recorded git call from its subcommand on, git's global options dropped."""
    calls = []
    for line in log.read_bytes().split(b"\0\n"):
        argv = [item.decode("utf-8", "surrogateescape") for item in line.split(b"\0") if line]
        while argv and argv[0].startswith("-"):
            argv = argv[2:] if argv[0] in ("-C", "-c") else argv[1:]
        if argv:
            calls.append(argv)
    return calls


def test_no_rebase_ever_runs(overlays: Overlays, git_log: Path) -> None:
    _agent_line(overlays.b, "alpha", "from-b", "line on b")
    commit_all(overlays.b, "b")
    git(overlays.b, "push", "-q", "origin", "main")
    _agent_line(overlays.a, "alpha", "from-a", "line on a")
    commit_all(overlays.a, "a")
    write(overlays.a, "common/memory/dirty.md", "a note to commit\n")
    git_log.unlink(missing_ok=True)
    ctx = context(overlays, overlays.a)

    assert J.commit_memory(ctx) is None
    assert J.integrate(ctx, fetched(overlays, overlays.a)) is None

    assert [notice.state for notice in ctx.notices] == ["resolved_index"]
    calls = subcommands(git_log)
    names = {call[0] for call in calls}
    assert {"merge-tree", "commit-tree", "update-ref", "fetch"} <= names
    assert names.isdisjoint(
        {"rebase", "pull", "stash", "checkout", "merge", "cherry-pick", "switch", "restore"}
    )
    assert not any(call[0] == "reset" and "--hard" in call for call in calls)
    assert no_rebase_dir(overlays.a)


# -- fetch failures and the record ----------------------------------------------------------------


def _ssh(overlays: Overlays, tmp_path: Path, said: str, code: int = 255) -> None:
    program = tmp_path / "fake-ssh"
    program.write_text(f"#!/bin/sh\necho '{said}' >&2\nexit {code}\n")
    program.chmod(0o755)
    git(overlays.a, "config", "core.sshCommand", str(program))
    git(overlays.a, "remote", "set-url", "origin", "ssh://git.example.invalid/overlay.git")


def test_a_fetch_offline_refused_or_failed_is_classified(
    overlays: Overlays, tmp_path: Path
) -> None:
    _ssh(overlays, tmp_path, "ssh: Could not resolve hostname git.example.invalid: not known")
    sha, outcome = J.fetch(context(overlays, overlays.a))
    assert sha is None and outcome is not None and outcome.state == "offline"
    assert "Could not resolve hostname" in str(outcome.detail)

    _ssh(overlays, tmp_path, "git@git.example.invalid: Permission denied (publickey).")
    sha, outcome = J.fetch(context(overlays, overlays.a))
    assert sha is None and outcome is not None and outcome.state == "auth_failed"

    _ssh(overlays, tmp_path, "something else entirely", code=1)
    sha, outcome = J.fetch(context(overlays, overlays.a))
    assert outcome is not None and outcome.state == "hook_failed"
    assert str(outcome.detail).startswith("job:")


@pytest.mark.parametrize(
    ("said", "state"),
    [
        (
            "fatal: unable to access 'https://github.com/o/overlay.git/': The requested URL "
            "returned error: 403",
            "auth_failed",
        ),
        (
            "fatal: unable to access 'https://github.com/o/overlay.git/': The requested URL "
            "returned error: 401",
            "auth_failed",
        ),
        (
            "fatal: unable to access 'https://github.com/o/overlay.git/': Could not resolve "
            "host: github.com",
            "offline",
        ),
        (
            "Connection closed by 140.82.121.4 port 22\r\nfatal: Could not read from remote "
            "repository.",
            "offline",
        ),
    ],
)
def test_remote_failures_are_classified_from_what_git_and_ssh_print(
    overlays: Overlays, said: str, state: str
) -> None:
    result = Ran(code=128, out="", err=said, timed_out=False)

    outcome = J._remote_failure(context(overlays, overlays.a), result, "git fetch origin main", 30)

    assert outcome.state == state, outcome


def test_a_fetch_that_hangs_is_a_timeout(
    overlays: Overlays, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow_git(tmp_path, monkeypatch, {"fetch": 30})
    started = time.monotonic()

    sha, outcome = J.fetch(context(overlays, overlays.a, fetch=1))

    assert sha is None and outcome is not None and outcome.state == "timeout"
    assert "did not finish within 1 s" in str(outcome.detail)
    assert time.monotonic() - started < SLOW


def test_the_fetch_records_the_sha(overlays: Overlays) -> None:
    u = push_note(overlays.b, "common/memory/n.md", "n\n")
    ctx = context(overlays, overlays.a)

    assert J.fetch(ctx) == (u, None)

    assert ctx.fetched_sha == u
    assert head(overlays.a, J.FETCHED_REF) == u
