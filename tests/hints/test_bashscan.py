"""Contracts for the shared Bash-scanning module the session hints import."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from stayfixed.hints import bashscan, uvrun
from stayfixed.profiles.adapters import shipped_adapters


def test_quoted_heredoc_bodies_are_stripped_but_the_command_remains() -> None:
    """A QUOTED delimiter's body is data the shell does not expand — this is the property
    that keeps this repository's own guard fixtures authorable."""
    cmd = "cat > tests/x.py <<'EOF'\nsecret .env mention\nEOF\necho done"
    stripped = bashscan.prepare(cmd)[0]
    assert ".env" not in stripped
    assert "echo done" in stripped


def test_unquoted_heredoc_bodies_stay_visible() -> None:
    """The inversion of the old heredoc-stripping contract. An UNQUOTED delimiter's body is
    expanded by the shell, and — when the heredoc is a shell's stdin — executed. Deleting it
    before any check ran is what made `bash <<EOF` / `cat secrets/.env` / `EOF` allowed."""
    cmd = "bash <<EOF\ncat secrets/.env\nEOF\necho done"
    stripped = bashscan.prepare(cmd)[0]
    assert ".env" in stripped
    assert "echo done" in stripped


def test_unterminated_quoted_heredoc_strips_to_the_end() -> None:
    cmd = "cat <<'EOF'\nline .env"
    assert ".env" not in bashscan.prepare(cmd)[0]


def test_unterminated_unquoted_heredoc_keeps_its_body() -> None:
    cmd = "bash <<EOF\ncat secrets/.env"
    assert ".env" in bashscan.prepare(cmd)[0]


def test_heredocs_are_reported_with_their_header_and_quoting() -> None:
    cmd = "bash <<EOF\ncat secrets/.env\nEOF"
    _, heredocs = bashscan.prepare(cmd)
    assert len(heredocs) == 1
    assert heredocs[0].tag == "EOF"
    assert heredocs[0].quoted is False
    assert heredocs[0].header == "bash <<EOF"
    assert heredocs[0].body == "cat secrets/.env"


def test_a_quoted_body_is_still_reported_even_though_it_is_stripped() -> None:
    """Quoting suppresses expansion, never execution: `bash <<'EOF'` runs its body. The text
    half may drop it; the reported list may not, or a caller cannot judge what runs."""
    _, heredocs = bashscan.prepare("bash <<'EOF'\ncat secrets/.env\nEOF")
    assert [(h.quoted, h.body) for h in heredocs] == [(True, "cat secrets/.env")]


def test_backslash_delimiter_counts_as_quoted() -> None:
    _, heredocs = bashscan.prepare("cat <<\\EOF\nbody\nEOF")
    assert [h.quoted for h in heredocs] == [True]


def test_two_heredocs_on_one_line_are_consumed_in_order() -> None:
    cmd = "cat <<'A' <<B\nfirst .env\nA\nsecond secrets/.env\nB"
    text, heredocs = bashscan.prepare(cmd)
    assert [(h.tag, h.quoted) for h in heredocs] == [("A", True), ("B", False)]
    assert "first" not in text
    assert "second" in text


def test_tokenize_keeps_redirects_and_separators() -> None:
    tokens = bashscan.tokenize("echo x > f && cat f")
    assert tokens == ["echo", "x", ">", "f", "&&", "cat", "f"]


def test_tokenize_returns_none_on_unbalanced_quotes() -> None:
    assert bashscan.tokenize("echo 'unterminated") is None


def test_segments_split_on_every_separator() -> None:
    tokens = bashscan.tokenize("a b; c | d && e")
    assert tokens is not None
    assert bashscan.segments(tokens) == [["a", "b"], ["c"], ["d"], ["e"]]


def test_pipelines_group_the_commands_a_pipe_joins() -> None:
    tokens = bashscan.tokenize("a | b; c && d | e")
    assert tokens is not None
    assert bashscan.pipelines(tokens) == [[["a"], ["b"]], [["c"]], [["d"], ["e"]]]


def test_a_fused_pipe_and_separator_still_ends_the_pipeline() -> None:
    tokens = bashscan.tokenize("a |; b | c")
    assert tokens is not None
    assert bashscan.pipelines(tokens) == [[["a"]], [["b"], ["c"]]]


def test_arithmetic_shift_with_spaces_is_not_a_heredoc() -> None:
    cmd = "count=$((1 << 3))\nrm -rf .env\necho done"
    stripped = bashscan.prepare(cmd)[0]
    assert ".env" in stripped
    assert "echo done" in stripped


def test_arithmetic_shift_without_spaces_is_not_a_heredoc() -> None:
    cmd = "x=$(( 1<<3 ))\ncat secrets/.env"
    assert ".env" in bashscan.prepare(cmd)[0]


def test_here_string_is_not_a_heredoc() -> None:
    cmd = "echo a <<< word\ncat secrets/.env"
    assert ".env" in bashscan.prepare(cmd)[0]


def test_a_mid_word_hash_does_not_truncate_the_command() -> None:
    """`shlex`'s own `commenters` ends a token at ANY unquoted `#`, so this command
    tokenized to `['echo', 'a']` and everything after it was invisible to every check."""
    tokens = bashscan.tokenize("echo a#b && cat secrets/.env")
    assert tokens is not None
    assert "secrets/.env" in tokens


def test_a_hash_inside_a_path_argument_survives() -> None:
    assert bashscan.tokenize("git add notes#1.md") == ["git", "add", "notes#1.md"]


def test_a_real_comment_is_removed() -> None:
    tokens = bashscan.tokenize("ls # do not cat secrets/.env")
    assert tokens == ["ls"]


def test_a_hash_inside_quotes_is_not_a_comment() -> None:
    assert bashscan.tokenize('git log --format="%h#%s"') == ["git", "log", "--format=%h#%s"]


def test_a_commented_out_heredoc_does_not_swallow_the_next_line() -> None:
    """`echo hi # <<'EOF'` is a comment, not a redirect. Recognising it as one would delete
    every following line, including the real command a shell would go on to run."""
    text, heredocs = bashscan.prepare("echo hi # <<'EOF'\ncat secrets/.env\nEOF")
    assert heredocs == []
    assert ".env" in text


def test_a_newline_separates_commands_the_way_a_semicolon_does() -> None:
    """`shlex` with `whitespace_split` discards a newline as ordinary whitespace, so a
    multi-line command collapsed into ONE segment whose argv0 was the FIRST line's program.
    Token-based checks survived that; every argv0-keyed one — including the edit-gated
    boundary protecting this module — judged `rm scripts/guard.py` as if it were
    `echo`. `;` denied and `\\n` allowed, one character apart.

    The second half is the same contract read the other way: a newline the shell keeps as a
    literal character of a word is not a separator, or `git commit -m "two\\nlines"` would
    segment into two commands.
    """
    tokens = bashscan.tokenize("echo hi\nrm scripts/guard.py")
    assert tokens is not None
    assert bashscan.segments(tokens) == [
        ["echo", "hi"],
        ["rm", "scripts/guard.py"],
    ]
    quoted = bashscan.tokenize('git commit -m "first line\nsecond line"')
    assert quoted == ["git", "commit", "-m", "first line\nsecond line"]


def test_a_heredoc_tag_inside_a_quoted_string_is_not_a_redirect() -> None:
    """`_HEREDOC.finditer` ran against the raw line, so a `<<'TAG'` that merely APPEARED
    inside a quoted string was taken for a real quoted heredoc and every following line was
    deleted from the text every check reads — the one thing this module must never do.
    `git commit -m "note <<'E' "` is a plausible command, so this was reachable by accident
    and not only on purpose.
    """
    text, heredocs = bashscan.prepare("git commit -m \"note <<'E' \"\ncat secrets/.env")
    assert heredocs == []
    assert "secrets/.env" in text


def test_a_newline_after_a_separator_arrives_as_its_own_token() -> None:
    """The newline's separator must not fuse with a separator the user typed.

    `shlex`'s `punctuation_chars` mode emits a RUN of adjacent punctuation as ONE token, so
    an unpadded `;` written straight after a line already ending in `;` produces `;;` —
    which is not in `_SEPARATORS`, so `segments` does not split there and the multi-line
    hole reopens for any command whose previous line ends in shell punctuation. A trailing
    semicolon is not obfuscation, which is what makes this worth pinning.
    """
    tokens = bashscan.tokenize("echo hi;\nrm scripts/guard.py")
    assert tokens is not None
    assert tokens.count(";") == 2  # the typed one and the newline's, never fused into `;;`
    assert bashscan.segments(tokens) == [
        ["echo", "hi"],
        ["rm", "scripts/guard.py"],
    ]


def test_an_unbalanced_quote_does_not_hide_a_real_heredoc() -> None:
    """Quote tracking across lines is only as good as its own premise.

    When the quotes do not balance, "this `<<` is inside a string" is an unreliable claim,
    and acting on it hides a REAL heredoc: its body never reaches the caller's list, so a
    caller that judges a shell body as a program never sees this one. The scan therefore
    abandons the quote-aware pass and redoes it unaware whenever the pass ends still inside a
    quote — bash will not run an unbalanced command either, so nothing a shell would execute
    loses the quote-aware answer.
    """
    _, heredocs = bashscan.prepare("echo \"unbalanced\nbash <<'EOF'\nrm scripts/guard.py\nEOF")
    assert [(h.tag, h.quoted, h.body) for h in heredocs] == [("EOF", True, "rm scripts/guard.py")]


def test_a_fused_punctuation_run_still_separates_commands() -> None:
    """A separator welded to its neighbour is still a separator.

    `punctuation_chars` fuses adjacent punctuation, so `);`, `;;`, `&;`, `));` and `;>` are
    none of them members of `_SEPARATORS` and `segments` carried straight past them into one
    segment — the same argv0-blindness as the newline defect, reached with an ordinary typed
    `;` and no newline anywhere.

    The second assertion is the part most likely to break when this is changed: the boundary
    check finds a write target by looking at `segment[index - 1]`, so the `>` of a fused `;>`
    has to end up at the FRONT of the segment it opens. Before, `;>` matched neither a
    separator nor a redirect operator, and the write was invisible to both checks at once.
    """
    tokens = bashscan.tokenize("(cd /tmp); rm scripts/guard.py")
    assert tokens is not None
    assert bashscan.segments(tokens) == [
        ["(", "cd", "/tmp", ")"],
        ["rm", "scripts/guard.py"],
    ]
    redirected = bashscan.tokenize("echo hi;>scripts/guard.py")
    assert redirected is not None
    assert bashscan.segments(redirected) == [
        ["echo", "hi"],
        [">", "scripts/guard.py"],
    ]
    # a redirect operator that CONTAINS a separator character must survive whole
    compound = bashscan.tokenize("ls /x &>/tmp/out.log")
    assert compound is not None
    assert bashscan.segments(compound) == [["ls", "/x", "&>", "/tmp/out.log"]]


# --- 2026-08-23 security fix: `\<newline>` line continuations ------------------------------


def test_line_continuation_outside_quotes_is_joined() -> None:
    """`shlex` strips the backslash but leaves the newline inside the token, so
    `secrets/\\<newline>.env` never equalled `secrets/.env` until this pass joined it
    first — verified against real bash: `cat secrets/\\<newline>.env` reads the file."""
    tokens = bashscan.tokenize("cat secrets/\\\n.env")
    assert tokens == ["cat", "secrets/.env"]


def test_line_continuation_splitting_the_verb_is_joined() -> None:
    tokens = bashscan.tokenize("ca\\\nt secrets/.env")
    assert tokens == ["cat", "secrets/.env"]


def test_two_line_continuations_in_one_argument_are_both_joined() -> None:
    tokens = bashscan.tokenize("cat sec\\\nrets/\\\n.env")
    assert tokens == ["cat", "secrets/.env"]


def test_line_continuation_inside_double_quotes_is_joined() -> None:
    """Bash strips `\\<newline>` inside double quotes exactly as it does outside them —
    verified with `bash -c 'echo "secrets/\\<newline>.env"'`, which prints the joined
    path. `\\<newline>` is one of the five sequences double quotes still give backslash
    special meaning for (alongside `\\"`, `\\\\`, `\\$`, and `` \\` ``)."""
    tokens = bashscan.tokenize('echo "secrets/\\\n.env"')
    assert tokens == ["echo", "secrets/.env"]


def test_line_continuation_inside_single_quotes_is_left_alone() -> None:
    """The one direction stripping must NOT take: inside `'...'` bash gives backslash no
    special meaning at all, so `\\<newline>` stays two literal characters — verified with
    `bash -c "echo 'secrets/\\<newline>.env'" | od -c`, where both the backslash and the
    newline survive in the printed argument. Stripping it anyway would make the guard see
    `secrets/.env` for an argument bash never produces — a false denial, and proof the
    guard would be running on a different command than the one that executes."""
    tokens = bashscan.tokenize("echo 'secrets/\\\n.env'")
    assert tokens == ["echo", "secrets/\\\n.env"]


def test_line_continuation_does_not_apply_inside_a_comment() -> None:
    """A backslash has no special meaning inside a comment — verified against real bash:
    `echo hi # comment \\<newline>rm ...` still runs `rm ...` as its own statement, because
    the comment ends at the literal newline regardless of what precedes it. Stripping
    continuations before comments are recognised would glue this "comment" to the next
    line and hide a real command inside it — the reverse of what this fix is for, so the
    two passes must run in this order and this line must still split into two segments."""
    tokens = bashscan.tokenize("echo hi # comment \\\nrm scripts/guard.py")
    assert tokens is not None
    assert bashscan.segments(tokens) == [["echo", "hi"], ["rm", "scripts/guard.py"]]


def test_an_escaped_backslash_before_a_newline_is_not_a_continuation() -> None:
    """`\\\\` outside quotes is an escaped backslash — bash consumes the pair into one
    literal `\\`, which leaves the following newline unescaped and therefore a REAL
    separator, not a continuation. Verified against real bash: `echo a\\\\` + newline +
    `b` prints `a\\` and then fails to run `b` as a separate, unjoined command — the
    opposite of `echo a\\\\\\` + newline + `b`, which bash joins into `echo a\\b`. Both
    shapes are pinned here because they exercise the same escape-parity the module's other
    passes already rely on, and a continuation pass that got this backward would silently
    re-open the exact hole this fix closes for any argument built by doubling a backslash."""
    two_backslashes = bashscan.tokenize("echo a\\\\\nrm scripts/guard.py")
    assert two_backslashes is not None
    assert bashscan.segments(two_backslashes) == [
        ["echo", "a\\"],
        ["rm", "scripts/guard.py"],
    ]
    three_backslashes = bashscan.tokenize("echo a\\\\\\\nb")
    assert three_backslashes == ["echo", "a\\b"]


def test_a_trailing_continuation_with_nothing_after_it_elides_to_nothing() -> None:
    """A continuation as the very last two characters of the command has nothing to join
    onto — it still elides, leaving a shorter but perfectly ordinary, parseable command
    rather than a dangling escape. This is a different shape from a bare trailing
    backslash with NO newline at all, which was already, and remains, unparseable
    (`test_tokenize_returns_none_on_unbalanced_quotes`'s sibling case) — unaffected by
    this fix either way, since there is no newline for it to pair with."""
    tokens = bashscan.tokenize("echo a\\\n")
    assert tokens == ["echo", "a"]


def test_line_continuation_inside_a_quoted_heredoc_body_is_left_alone() -> None:
    """A quoted-delimiter heredoc body gets no expansion at all, so bash performs no
    continuation-joining inside it either — verified: `cat <<'EOF'` with a body
    continuation keeps both the backslash and the newline. The body is already absent from
    `prepare`'s text (quoted bodies are stripped by `scan_heredocs`), so this pass has
    nothing to do here and the reported body must come back untouched."""
    _, heredocs = bashscan.prepare("cat <<'EOF'\nfoo\\\nbar\nEOF")
    assert [h.body for h in heredocs] == ["foo\\\nbar"]


def test_arithmetic_shift_is_not_taken_for_a_heredoc() -> None:
    """`$((1<<2))` must stay unmatched: the trailing `(?!\\S)` after the tag rejects it, since `)`
    follows, and a match would hide the rest of the command as a heredoc body."""
    for text in ("echo $((1<<2))\ncat x", "echo $((n<<3))\ncat x"):
        stripped, heredocs = bashscan.prepare(text, keep_unquoted_bodies=False)
        assert (heredocs, "cat x" in stripped) == ([], True), text


def test_scan_heredocs_finds_a_glued_redirect() -> None:
    """The same relaxation seen through the caller that shares `_HEREDOC`: a quoted body
    leaves the general text and is still REPORTED, so `bgcleanup._nested_programs` can judge
    it."""
    stripped, heredocs = bashscan.prepare("bash<<'EOF'\ncat secrets/.env\nEOF")
    assert "secrets/.env" not in stripped
    assert [h.body for h in heredocs] == ["cat secrets/.env"]


# --- `command_words`, moved here because two guards need the same argv0 resolution ---------


def test_command_words_strips_a_leading_assignment_and_wrapper() -> None:
    """`Path(segment[0]).name` alone missed `PYTHONPATH=src pytest` and `FOO=1 BAR=2 pytest`
    entirely, so an argv0 test saw the assignment instead of the program."""
    assert bashscan.command_words(["FOO=1", "env", "sleep", "3"]) == ["sleep", "3"]


def a_runner(words: Sequence[str]) -> bool:
    """Whether a shipped runner adapter recognises `words`: what `prove` and the red-run hint ask
    of each word after `uv run`."""
    return any(adapter.recognises(words) for adapter in shipped_adapters())


def test_command_words_strips_uv_run_with_nothing_before_the_program() -> None:
    """CI's own invocation shape, with nothing between `uv run` and the program it launches.
    Oracle: `mutations/`'s "`uv run` stops being stripped off a segment"."""
    assert bashscan.command_words(["uv", "run", "pytest"], a_runner) == ["pytest"]


@pytest.mark.parametrize(
    ("command", "launcher"),
    [
        ("uv run -m pytest", "uv run -m"),
        ("uv run python -m pytest", "uv run"),
        ("uv run --with pytest-xdist pytest -n 4", "uv run --with pytest-xdist"),
        ("uv run --extra dev pytest", "uv run --extra dev"),
        ("uv run --group test pytest", "uv run --group test"),
        ("uv run -p 3.13 pytest", "uv run -p 3.13"),
        ("uv run --project sub pytest", "uv run --project sub"),
        ("uv run --env-file .env pytest", "uv run --env-file .env"),
        ("uv run --locked pytest -q", "uv run --locked"),
        ("uv run --directory sub pytest", "uv run --directory sub"),
        ("uv --directory sub run pytest", "uv --directory sub run"),
        ("uv run -- pytest", "uv run --"),
        # The documented bound: a runner named as an option's value is read as the command.
        ("uv run --with pytest python -O -m pytest", "uv run --with"),
    ],
    ids=[
        "module",
        "interpreter",
        "with",
        "extra",
        "group",
        "python",
        "project",
        "env-file",
        "locked",
        "directory",
        "global",
        "separator",
        "bound",
    ],
)
def test_the_command_uv_runs_starts_at_the_first_word_a_runner_adapter_recognises(
    command: str, launcher: str
) -> None:
    """No option of uv's is read to find the command: every word before the first a runner
    adapter recognises is the launcher's, handed to uv as typed. Oracle: `mutations/`'s "the
    command `uv run` launches starts at its first word that is no option"."""
    words = command.split()
    launch = bashscan.read_launch(words, a_runner)
    assert launch.launcher == tuple(launcher.split())
    assert launch.command == tuple(words[len(launch.launcher) :])


@pytest.mark.parametrize(
    ("command", "recognises"),
    [
        ("uv run --frozen mvn test", a_runner),
        ("uv pip install pytest", a_runner),
        ("uv run pytest", None),
    ],
    ids=["no-runner", "no-run", "no-recogniser"],
)
def test_a_uv_command_in_which_no_runner_is_recognised_is_left_whole(
    command: str, recognises: Callable[[Sequence[str]], bool] | None
) -> None:
    """Its program is `uv`, which no hint recognises and no guard refuses: no word after `run`
    that a runner adapter recognises, no `run`, or a caller that asks about no runner, as the
    background guard does."""
    assert bashscan.command_words(command.split(), recognises) == command.split()


# --- `read_launch`: the same walk, every word of the launch named by its part ------------------


@pytest.mark.parametrize(
    ("command", "assignments", "launcher", "program"),
    [
        ("A=1 env B=2 pytest -q", ["A=1", "B=2"], [], ["pytest", "-q"]),
        # Every word before the command is the launcher's, an `env` and its assignments or an
        # assignment-shaped word too, which a shell hands to uv as a word.
        ("uv run env FORGE=x pytest", [], ["uv", "run", "env", "FORGE=x"], ["pytest"]),
        ("env A=1 uv run env B=2 pytest", ["A=1"], ["uv", "run", "env", "B=2"], ["pytest"]),
        (
            "uv --config-file c.toml run --env-file=.env --with x==1 pytest",
            [],
            ["uv", "--config-file", "c.toml", "run", "--env-file=.env", "--with", "x==1"],
            ["pytest"],
        ),
        ("uv run FOO=1 pytest", [], ["uv", "run", "FOO=1"], ["pytest"]),
        ("uv run -- pytest", [], ["uv", "run", "--"], ["pytest"]),
        ("uv run --locked mvn test", [], [], "uv run --locked mvn test"),
        ("env -i A=1 pytest", [], [], ["-i", "A=1", "pytest"]),
    ],
    ids=[
        "assignments-and-env",
        "uv-env-assignment",
        "assignments-on-both-sides",
        "option-values",
        "launcher-word",
        "separator",
        "unread-launcher",
        "env-option",
    ],
)
def test_read_launch_names_each_word_of_the_launch_by_its_part(
    command: str, assignments: list[str], launcher: list[str], program: list[str] | str
) -> None:
    """A caller that runs the command needs more than the program: every assignment the shell or
    `env` would make before the launcher, and the launcher's own words apart from them.
    `command_words` is the same walk's last part. Oracle: `mutations/`'s "the launch keeps no
    launcher's words"."""
    words = command.split()
    expected = program.split() if isinstance(program, str) else program
    launch = bashscan.read_launch(words, a_runner)
    assert launch == bashscan.Launch(tuple(assignments), tuple(launcher), tuple(expected))
    assert bashscan.command_words(words, a_runner) == expected


@pytest.mark.parametrize(
    ("command", "environ", "moved"),
    [
        ("pytest", {"UV_WORKING_DIR": "a"}, ""),
        ("uv run pytest", {}, ""),
        ("uv run --directory a pytest", {}, "a"),
        ("uv run --directory=a pytest", {}, "a"),
        ("uv --directory a run --locked pytest", {}, "a"),
        ("uv run pytest", {"UV_WORKING_DIR": "a"}, "a"),
        ("uv run --directory a pytest", {"UV_WORKING_DIR": "b"}, "a"),
        ("uv run --directory a uv run --directory b pytest", {}, "a/b"),
        ("uv run --directory a uv run pytest", {"UV_WORKING_DIR": "b"}, "a/b"),
        ("uv run --directory /abs pytest", {}, "/abs"),
        ("uv run -m pytest", {"UV_WORKING_DIR": "a"}, "a"),
        ("uv run --project a pytest", {"UV_PROJECT": "b"}, ""),
        ("uv run --directory", {}, ""),
    ],
    ids=[
        "no-launcher",
        "none",
        "spaced",
        "equals",
        "global",
        "variable",
        "option-over-variable",
        "nested",
        "nested-variable",
        "absolute",
        "module",
        "project",
        "no-value",
    ],
)
def test_run_directory_is_where_uv_runs_the_program(
    command: str, environ: dict[str, str], moved: str
) -> None:
    """Measured on uv 0.12.19: `--directory`, before `run` or after it, spaced or with `=`, else
    `UV_WORKING_DIR`, moves where the program runs, the option winning; a `uv run` that a
    `uv run` launches reads its own from where the outer one moved to; `--project` and
    `UV_PROJECT` move nothing. Oracle: `mutations/`'s "uv's `--directory` is not read", "uv's
    spaced `--directory` value is not read", "`UV_WORKING_DIR` is not read", "uv's variable
    wins over its `--directory`", "a nested `uv run` reads its directory from where the command
    was typed"."""
    launcher = bashscan.read_launch(command.split(), a_runner).launcher
    typed = Path("/typed")
    assert uvrun.run_directory(launcher, typed, environ) == typed / moved
