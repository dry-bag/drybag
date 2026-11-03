"""What the one seam out of this process gives the commands it launches.

Every case here runs `sh` or a nonexistent name and never `gh`, `git` or `pre-commit`: the
subject is the environment, the stdin and the exit-code mapping, not any of those binaries.
"""

from __future__ import annotations

import os
import pty
from pathlib import Path

import pytest

from stayfixed.runner import (
    _ENV_DROP,
    _ENV_FORCE,
    NETWORK_TIMEOUT_SECONDS,
    NOT_FOUND,
    TIMED_OUT,
    Completed,
    _SubprocessRunner,
    subprocess_runner,
)

PROBE = [
    "sh",
    "-c",
    'echo "tty=$( [ -t 0 ] && echo yes || echo no ) '
    'prompt=${GIT_TERMINAL_PROMPT-unset} dir=${GIT_DIR-unset} index=${GIT_INDEX_FILE-unset}"',
]


def test_a_launched_command_gets_no_stdin_and_no_credential_prompt(tmp_path: Path) -> None:
    # Every call here runs with output captured, so a `git` or `gh` that asks for a credential
    # on an inherited stdin is invisible and blocks for the whole of NETWORK_TIMEOUT_SECONDS.
    # What makes that a finding rather than an annoyance is which callers reach the network
    # through this seam: `setup --overlay create:` launches `gh` with the machine owner's own
    # authentication, a write meant to be non-interactive. See `stayfixed.runner._ENV_FORCE`.
    #
    # The pty is the point of the case: without it this process's own stdin is already not a
    # terminal under pytest, and the assertion would pass with the guard deleted.
    master, slave = pty.openpty()
    saved = os.dup(0)
    try:
        os.dup2(slave, 0)
        done = _SubprocessRunner().launch(PROBE, tmp_path)
    finally:
        os.dup2(saved, 0)
        for descriptor in (master, slave, saved):
            os.close(descriptor)
    assert "tty=no" in done.stdout
    assert "prompt=0" in done.stdout


def test_the_variables_that_redirect_git_are_dropped(tmp_path: Path) -> None:
    # A clone into a fresh directory must not inherit what points git at a different repository,
    # index or object store. `GIT_DIR` and `GIT_WORK_TREE` were the only two dropped, and the
    # comment beside them claimed they were "the two" that do it; `GIT_INDEX_FILE` is one of
    # several counterexamples, and is the arm asserted here.
    for name in ("GIT_DIR", "GIT_INDEX_FILE"):
        os.environ[name] = str(tmp_path / name)
    try:
        done = _SubprocessRunner().launch(PROBE, tmp_path)
    finally:
        for name in ("GIT_DIR", "GIT_INDEX_FILE"):
            del os.environ[name]
    assert "dir=unset" in done.stdout
    assert "index=unset" in done.stdout
    assert set(_ENV_DROP) >= {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}
    assert _ENV_FORCE["GIT_TERMINAL_PROMPT"] == "0"


def test_the_variables_that_make_gh_write_for_a_terminal_are_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Either variable makes a captured `gh` colour its JSON, and every caller that parses it, the
    # publisher's `gh api` and `create:`'s `gh repo view --json isTemplate` among them,
    # then read no answer. Mutations (declared): `mutations/`'s "the runner hands gh
    # GH_FORCE_TTY" and "the runner hands gh CLICOLOR_FORCE" -> each reaches the child.
    monkeypatch.setenv("GH_FORCE_TTY", "1")
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    probe = ["sh", "-c", 'echo "tty=${GH_FORCE_TTY-unset} colour=${CLICOLOR_FORCE-unset}"']
    done = _SubprocessRunner().launch(probe, tmp_path)
    assert done.stdout.split() == ["tty=unset", "colour=unset"], done.stdout


def test_a_command_that_hangs_is_not_reported_as_one_that_is_missing(tmp_path: Path) -> None:
    # `TimeoutExpired` is a `SubprocessError`, so a `gh` that hung for the full five minutes
    # arrived as NOT_FOUND — which every caller reads as "gh is not installed". A wrong finding
    # is worse than a slow one, and the two have different remedies.
    import stayfixed.runner as runner

    before = runner.NETWORK_TIMEOUT_SECONDS
    runner.NETWORK_TIMEOUT_SECONDS = 1
    try:
        hung = _SubprocessRunner().launch(["sh", "-c", "sleep 5"], tmp_path)
    finally:
        runner.NETWORK_TIMEOUT_SECONDS = before
    assert hung.code == TIMED_OUT
    # Non-vacuous: a binary that really is missing still answers NOT_FOUND, which is the mapping
    # an optional binary needs — a missing one is a finding, never a traceback.
    assert _SubprocessRunner().launch(["stayfixed-no-such-binary"], tmp_path).code == NOT_FOUND


def test_a_caller_that_asks_for_a_narrower_bound_gets_it(tmp_path: Path) -> None:
    """`NETWORK_TIMEOUT_SECONDS` is right for what it was written for and wrong for a diagnostic.

    Five minutes bounds `gh repo create --clone` waiting on GitHub and the clone behind it. The
    bound belongs to the caller that knows how big its question is, so it
    is a keyword on the factory rather than a second module constant: the protocol is untouched
    and no stub in the suite grows a parameter it would ignore.

    Judged by what the subprocess did rather than by the wall: under a one-second bound, a
    command that would write a marker after five seconds answers `TIMED_OUT`, the marker is not
    there when the runner returns, and the sentence it carries names the bound that was applied
    and not the module's. The marker proves the call returned before the command's end, which is
    what a clock used to prove with a margin load can spend. That it never gets written later
    rests on `subprocess.run(timeout=)`, which kills `sh` before it reaches `: > finished`; the
    `sleep` it started outlives the test by about four seconds, writing nothing.

    Mutation (`mutations/`'s "the runner ignores the bound its caller asked for"): `timeout=bound`
    back to `timeout=NETWORK_TIMEOUT_SECONDS`. Measured: the command runs to completion and the
    runner answers `Completed(code=0)`, so the code assertion is what reddens and the marker is
    the floor under it — a bound of five minutes cannot cut a five-second sleep.
    """
    # The sleep's own output goes to /dev/null, so once the shell is killed nothing holds the
    # runner's pipes open for the rest of it.
    marker = tmp_path / "finished"
    hung = subprocess_runner(timeout=1).launch(
        ["sh", "-c", "sleep 5 >/dev/null 2>&1; : > finished"], tmp_path
    )
    assert hung.code == TIMED_OUT
    assert not marker.exists(), "the command ran to its end under a one-second bound"
    assert "within 1s" in hung.stderr and str(NETWORK_TIMEOUT_SECONDS) not in hung.stderr
    # Non-vacuous: the default is still the module's, and a runner asked for nothing in particular
    # is the one every other caller gets.
    assert _SubprocessRunner().timeout is None


def test_output_that_is_not_text_is_read_with_replacement_characters_not_raised(
    tmp_path: Path,
) -> None:
    # The tools this seam launches print what they like, and every caller reads their output as
    # a message or matches it against a grammar — a tag listing, JSON, a verdict's exit code —
    # and never as a path. Decoded strictly, one byte that was not text ended the command as
    # `internal error: UnicodeDecodeError`: `test attribute` over a test run whose output
    # quoted a latin-1 filename, measured. A byte the codec cannot read is U+FFFD instead, which
    # every stream and every UTF-8 file stayfixed writes can hold. Mutation (declared): decode
    # strictly again -> this reddens.
    done = subprocess_runner().launch(
        ["sh", "-c", "printf 'caf\\351'; printf 'x\\351' >&2"], tmp_path
    )
    assert done == Completed(0, "caf\ufffd", "x\ufffd")
