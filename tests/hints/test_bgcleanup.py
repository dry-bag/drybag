"""Contract for the background-cleanup guard, driven through `judge`.

The command this guard exists to name was measured on 2026-09-02: a session backgrounded
fourteen busy-loop subshells with a bare ``&`` and expressed the cleanup as a LATER LINE of
the same command. The harness reaped the parent shell before that line ran, the subshells
re-parented to PID 1, and they burned 7.4 of 10 cores for 39 minutes with no writer left to
stop them. A trailing ``kill`` line is not cleanup; ``trap ... EXIT`` is.
"""

from __future__ import annotations

import re
import shlex
import time

import pytest

from drybag.hints import bgcleanup
from drybag.hints.bashscan import MAX_COMMAND_CHARS
from drybag.hints.bgcleanup import (
    EXIT_ECHO_HINT,
    LEAK_HINT,
    RESTORE_HINT,
    SLEEP_HINT,
    judge,
)

# The command from the incident, verbatim.
_INCIDENT = """for i in $(seq 1 14); do (while :; do :; done) & done
LOADPIDS=$(jobs -p)
sleep 2
PYTHONPATH=$PWD/src .venv/bin/python .../rate.py 15 2>&1 | grep -E '^idle|^under|failures'
kill $LOADPIDS 2>/dev/null"""


def flagged(command: str, *, background: bool = True) -> bool:
    return judge(command, background=background) in (LEAK_HINT, SLEEP_HINT)


def hint(command: str) -> str | None:
    return judge(command, background=False)


def test_the_incident_command_is_flagged() -> None:
    assert flagged(_INCIDENT)


def test_the_incident_command_with_a_trap_is_allowed() -> None:
    """The same command, with the cleanup moved into a trap. This is the remedy the hint
    names, so it has to actually be accepted -- a guard whose stated fix is also flagged
    teaches people to work around the guard rather than to fix the command."""
    remedied = _INCIDENT.replace(
        "LOADPIDS=$(jobs -p)",
        "LOADPIDS=$(jobs -p)\ntrap 'kill ${=LOADPIDS}' EXIT INT TERM",
    ).replace("\nkill $LOADPIDS 2>/dev/null", "")

    assert judge(remedied, background=True) is None


def test_the_incident_command_in_the_foreground_is_allowed() -> None:
    """The rule is keyed on `run_in_background`, and that is what holds false positives near
    zero. A foreground command's trailing `kill` line is reached because the tool is waiting
    on the very shell that runs it."""
    assert judge(_INCIDENT, background=False) is None


def test_a_command_with_no_ampersand_at_all_is_allowed() -> None:
    assert judge("PYTHONPATH=src .venv/bin/python -m pytest -n 8", background=True) is None


def test_a_chain_is_not_read_as_backgrounding() -> None:
    """`&&` is one compound token, not two `&`. A regex over raw text gets this wrong, which
    is why the check reads tokens."""
    assert judge("make && make test", background=True) is None


def test_a_redirect_is_not_read_as_backgrounding() -> None:
    """`2>&1` tokenizes to `['cmd', '2', '>&', '1']` -- the `>&` is its own compound token and
    no bare `&` is produced."""
    assert judge("pytest -q 2>&1 | tail -5", background=True) is None


def test_a_redirect_and_a_real_background_together_are_told_apart() -> None:
    """The discriminating case for the three shapes at once: this command contains `>`, `2>&1`
    AND a genuine backgrounding `&`. With a trap it is allowed; the test below removes only
    the trap and the same command is flagged, attributably to the missing cleanup
    and not to any of the redirects."""
    with_trap = "trap 'kill ${=PID}' EXIT INT TERM; server >file 2>&1 & PID=$!; sleep 1"

    assert judge(with_trap, background=True) is None


def test_the_same_redirecting_command_without_its_trap_is_flagged() -> None:
    without_trap = "server >file 2>&1 & PID=$!; sleep 1; kill $PID"

    assert flagged(without_trap)


def test_a_lone_backgrounded_server_is_flagged_too() -> None:
    """The deliberate no-exemption decision, pinned so it is not silently rediscovered.

    A bare `&` on a command that is the only thing being run -- a server meant to outlive the
    shell -- is still flagged, because `run_in_background: true` already backgrounds the whole
    command. The inner `&` therefore only adds a child the harness cannot track and the reap
    cannot collect."""
    assert flagged("python -m http.server 8000 &")


def test_a_quoted_mention_of_a_trap_does_not_excuse_the_leak() -> None:
    """`echo 'trap ... EXIT'` tokenizes to `['echo', 'trap ... EXIT']` -- the quoted string is
    ONE token, so exact-token matching sees no trap. A substring test on raw command text
    would see one and allow a real leak."""
    assert flagged("echo 'trap it on EXIT'; sleep 300 &")


def test_a_trap_past_a_bare_double_dash_does_not_count() -> None:
    """`--` ends option parsing, so those words are operands to `printf`, not a trap."""
    assert flagged("sleep 300 & printf '%s\\n' -- trap EXIT")


def test_a_trap_naming_only_int_and_term_does_not_count() -> None:
    """`INT`/`TERM` are accepted ALONGSIDE `EXIT`, never instead of it: a reap is neither
    signal, so a trap that does not name `EXIT` would not have run in the incident either."""
    assert flagged("trap 'kill ${=P}' INT TERM; sleep 300 & P=$!; kill $P")


def test_a_trap_inside_a_compound_statement_counts() -> None:
    """`for ...; do trap ...; done` gives a segment whose first token is the keyword `do`, so
    an argv0-keyed test would miss the trap and wrongly flag a command that cleans up."""
    command = "for i in 1 2; do trap 'kill ${=P}' EXIT; sleep 9 & P=$!; done; kill $P"

    assert judge(command, background=True) is None


def test_a_trailing_wait_is_cleanup() -> None:
    """A last `wait` reaps the jobs before the shell exits; one that is not last does not. No
    mutation entry: a hint is neither a verdict nor a control."""
    assert judge("pytest a & pytest b & wait", background=True) is None
    assert flagged("pytest a & wait; echo done")


def test_a_background_hidden_in_a_shell_c_string_is_flagged() -> None:
    """A `-c` string is ONE token however long the command inside it is, so without recursion
    this command's tokens say nothing but `bash`."""
    assert flagged("bash -c 'sleep 300 &'")


@pytest.mark.parametrize("delimiter", ["'EOF'", "EOF"])
def test_a_background_hidden_in_a_shell_fed_heredoc_is_flagged(delimiter: str) -> None:
    """A heredoc body fed to a SHELL is a program, and both delimiter spellings must be read
    as one. A body with a QUOTED delimiter is removed from the scanned text entirely, so it
    presents nothing but the word `bash` unless it is pulled back out of the heredoc list; an
    UNQUOTED one is now removed from that text too (see the module docstring's `&` rule), so
    it reaches this guard by the same route and by no other. The unquoted row is what proves
    the fix for the false hint below did not switch this path off with it."""
    command = f"bash <<{delimiter}\nsleep 300 &\nEOF"

    assert flagged(command)


@pytest.mark.parametrize(
    "command",
    [
        "cat > /tmp/x.sh <<'EOF'\nsleep 300 &\nEOF",
        # The same body with an UNQUOTED delimiter -- which is what a writer must use to get
        # `$VAR` expanded. Measured flagged before `_scan` stopped reading bodies as grammar:
        # `prepare` re-inserts an unquoted body into the scanned text, so its `&` arrived as
        # an async operator.
        "cat > /tmp/x.sh <<EOF\nsleep 300 &\nEOF",
        # The cost in the shape a person actually hits: a README line carrying a URL's query
        # separator, written with expansion wanted. Measured flagged as well.
        "cat > README.md <<EOF\nsee https://h/p?a=1&b=2 for $USER\nEOF",
    ],
)
def test_a_heredoc_written_to_a_file_is_data_not_a_program(command: str) -> None:
    """`cat > file <<EOF` writes its body; it does not run it. Reading it as a program would
    make this plugin's own fixture authoring -- including this test file -- undeniable, and
    reading it as GRAMMAR flags every file whose content happens to contain an `&`."""
    assert judge(command, background=True) is None


def test_an_apostrophe_in_a_heredoc_body_does_not_hide_a_real_leak() -> None:
    """The same root cause running the other way, and the direction that costs a leaked job
    rather than a false hint. With the unquoted body in the scanned text, `don't` opened a quote
    that never closed, `bashscan.tokenize` returned `None`, and `_scan` said nothing --
    so the `sleep 5 &` AFTER the heredoc, a genuine unreaped job, walked through. A body is
    stdin to `cat`; the shell never parses an apostrophe in one."""
    command = "cat > notes.md <<EOF\ndon't stop for $USER\nEOF\nsleep 5 &"

    assert flagged(command)


def test_a_malformed_command_gets_no_hint() -> None:
    """An unbalanced quote is a command no shell would run. The judge says nothing: the token
    it needs is `&`, the one thing a raw-text scan provably gets wrong, so there is no
    fallback that would not flag ordinary quoted text."""
    assert judge("sleep 300 & echo 'unbalanced", background=True) is None


def test_an_ampersand_inside_a_quoted_argument_is_not_backgrounding() -> None:
    """The likeliest accidental false positive, and the one a raw-text scan would hit hardest:
    a URL's query separators. `curl 'https://h/p?a=1&b=2'` contains two `&` characters and
    backgrounds nothing -- the tokenizer keeps the quoted argument as ONE token, so no bare
    `&` is produced."""
    assert judge('curl -s "https://h/p?a=1&b=2&c=3" | jq .', background=True) is None


def test_a_background_welded_to_a_closing_paren_is_flagged() -> None:
    """`(sleep 300 &)` is THE deliberate-detach idiom, and it is exactly the leak this guard
    exists to name. `shlex`'s `punctuation_chars` mode fuses adjacent punctuation into one
    token, so the `&` arrives welded as `&)` and a membership test on the raw token list never
    sees it. `bashscan` already paid for this lesson once -- its header records
    "A SEPARATOR WELDED TO ITS NEIGHBOUR IS STILL A SEPARATOR".

    What this no longer measures, said here so the docstring is not read as a promise it does
    not keep: the ported `_begins_with_sleep` skips the leading `(`, so this command meets the
    `sleep` rule before the `&` scan and would be flagged even with the weld unread.
    `test_a_non_sleep_background_welded_to_a_closing_paren_is_flagged` below is the test that
    still proves the weld is seen, and it is the one the mutation entry names."""
    assert flagged("(sleep 300 &)")


def test_a_non_sleep_background_welded_to_a_closing_paren_is_flagged() -> None:
    """The same weld with a program the `sleep` rule does not already flag.

    Not in the source, and needed only because of what changed in the port: the ported
    `_begins_with_sleep` skips a leading `(`, so `(sleep 300 &)` now meets the `sleep` rule
    first and is flagged whether or not the weld is read at all. It can no longer prove the
    weld is seen; this can, because `LEAK_HINT` is reachable for this command only through
    the decomposition of `&)` into two pieces."""
    assert judge("(python -m http.server 8000 &)", background=True) == LEAK_HINT


def test_the_incident_command_is_flagged_without_the_space_before_the_ampersand() -> None:
    """The module docstring's own incident command with ONE space deleted. A guard that
    catches the incident only when its author happened to type a space is not catching the
    incident."""
    welded = _INCIDENT.replace("done) & done", "done)& done")
    assert welded != _INCIDENT, "the fixture no longer contains the shape under test"

    assert flagged(welded)


def test_a_subshell_background_inside_another_subshell_is_flagged() -> None:
    """`((cmd) & wait)` opens with the token `((` -- the same token arithmetic opens with.
    Pinned because the tempting fix for the arithmetic false positive (suppress `&` inside a
    `((` run) would silence this, which is a real leak and closer to the incident than
    arithmetic ever is."""
    assert flagged("((sleep 300; sleep 1) & echo started)")


@pytest.mark.parametrize(
    "command", ["echo $((3 & 1))", "echo $(( 3 & 1 ))", "x=$((5 & 3)); echo $x"]
)
def test_a_bitwise_and_in_an_arithmetic_expansion_is_the_documented_false_hint(
    command: str,
) -> None:
    """The module docstring's known false hint, measured here rather than restated: a
    documented false hint that drifts either becomes a lie in the docstring or a silent
    widening of what the guard flags, and neither shows up in a diff.

    It has no mutation of its own, by construction: what reddens it is the fix the docstring
    rejects -- suppressing `&` inside a run opened by `((` -- and that same edit reddens
    `test_a_subshell_background_inside_another_subshell_is_flagged`, which is the leak the
    exception is paid for. The pair is the point; either alone can be made green by the wrong
    change. The `background=False` half is what keeps the cost as small as the docstring says:
    an arithmetic expression in an ordinary foreground call is not touched.
    """
    assert flagged(command)
    assert judge(command, background=False) is None


def test_the_pipe_both_operator_is_not_backgrounding() -> None:
    """The negative control for the welded-separator fix. `|&` is bash's "pipe stdout and
    stderr"; `bashscan` deliberately leaves it out of its compound-operator table, so it
    decomposes to `['|', '&']` and a naive scan of the pieces would read it as backgrounding.
    Its `&` is part of a pipe operator, not the async operator."""
    assert judge("make 2>/dev/null |& grep -i warning", background=True) is None


def test_a_case_fallthrough_terminator_is_not_backgrounding() -> None:
    """The other piece-decomposition trap: `;&` and `;;&` end a `case` branch and fall
    through. They decompose to `[';', '&']` and `[';', ';', '&']`, and neither `&` is the
    async operator."""
    command = "case $x in a) echo a ;& b) echo b ;; esac"

    assert judge(command, background=True) is None


def test_a_plain_argument_after_a_shell_c_cluster_is_not_a_program() -> None:
    """A quoted argument must not lose its quoting by being re-tokenized as a program.

    For any `-c` cluster other than the exact `-c`, every remaining token used to be scanned
    as a command in its own right -- and `tokenize("https://h/p?a=1&b=2")` yields
    `['https://h/p?a=1', '&', 'b=2']`, a bare `&`. So a URL passed as an ordinary argument
    was flagged, contradicting `test_an_ampersand_inside_a_quoted_argument_is_not_backgrounding`
    which pins the identical shape at the top level."""
    command = "bash -lc 'echo hi' \"https://h/p?a=1&b=2\""

    assert judge(command, background=True) is None


def test_the_reasons_carry_the_neutral_remedy_and_no_repository_path() -> None:
    """Every hint is shown to whoever just ran a command, in a repository this
    plugin has never seen. The positive half is what the neutralisation actually changed --
    the path regex alone is green against the unported source, whose residue was a sentence
    about two named test suites, not a path."""
    assert "parallelise the suite rather than wait on it" in LEAK_HINT
    for text in (LEAK_HINT, SLEEP_HINT, RESTORE_HINT, EXIT_ECHO_HINT):
        assert re.findall(r"(?:docs|scripts|src|tests)/[\w./-]+", text) == [], text
        assert "suite" not in text.replace("parallelise the suite", "")


def test_a_backgrounded_command_that_begins_with_sleep_is_flagged() -> None:
    """`run_in_background: true` returns at once, whatever the command sleeps for. Measured: a
    session believed it had waited nine minutes across fifteen such calls while 39 s passed."""

    reason = judge("sleep 300; gh pr checks 1", background=True)
    assert reason is not None
    assert "returns immediately" in reason and "Monitor" in reason


@pytest.mark.parametrize(
    "command", ["/bin/sleep 30; gh pr checks 1", "FOO=1 sleep 30", "env sleep 30", "( sleep 30 )"]
)
def test_a_backgrounded_leading_sleep_is_flagged_however_it_is_spelled(command: str) -> None:
    # None of these is adversarial; the source's exact `["sleep"]` comparison allowed all four.
    assert judge(command, background=True) == SLEEP_HINT


@pytest.mark.parametrize(
    "command",
    [
        "uv run sleep 30",
        "uv run -m sleep 30",
        "uv run --with sleep pytest -q > out.log 2>&1",
        "pytest -q > out.log; uv run echo done",
    ],
)
def test_what_uv_runs_is_uv_to_this_guard(command: str) -> None:
    """This guard asks about no runner, so `command_words` reads no `uv run` through for it: what
    uv launches is `uv`, never a `sleep` or an `echo`, and `uv run -m sleep` runs a module."""
    assert judge(command, background=True) is None


def test_a_sleep_inside_a_command_substitution_is_not_a_leading_sleep() -> None:
    """`X=$(sleep 5) pytest -q` does not begin with `sleep`; it begins with an assignment whose
    value a substitution computes. It segments to
    `['X=$', '(', 'sleep', '5', ')', 'pytest', '-q']`, so filtering EVERY `(` out of the first
    segment -- rather than dropping the leading run of them -- put `sleep` at the front and
    flagged it. Measured on the shipped module before the fix: `SLEEP_HINT`."""
    assert judge("X=$(sleep 5) pytest -q", background=True) is None


def test_a_foreground_sleep_is_not_this_guard_s_business() -> None:
    assert judge("sleep 5; ls", background=False) is None


def test_a_backgrounded_command_that_only_mentions_sleep_later_is_allowed() -> None:
    """Keyed on the FIRST simple command: `pytest … ; sleep 1` is not the misunderstanding."""

    assert judge(".venv/bin/python -m pytest tests/x.py; sleep 1", background=True) is None


def test_a_command_past_the_size_cap_is_allowed_unread() -> None:
    # A named cap, not a config key. Tokenizing is quadratic in token length and every Bash
    # call pays it; a hook past its timeout lets the call through unjudged.
    # The fixture leads with `echo`, not `sleep`: the `sleep` rule is judged before the `&`
    # scan, so a leading `sleep` would pin SLEEP_HINT and say nothing about the `&` rule.
    #
    # THE VALUE IS PINNED AGAINST THE LITERAL FIRST, and that line is not decoration. Every
    # assertion below derives its fixture from `MAX_COMMAND_CHARS`, so all of them survive any
    # change to the constant BY CONSTRUCTION -- the boundary moves and the fixture moves with
    # it. The suite stayed green with the cap set to 200, which would silently stop reading
    # ordinary commands. What the derived assertions do prove, and the literal cannot, is that
    # the boundary is judged at `<=` rather than `<`: one character past it is unread and the
    # command exactly at it is read.
    assert MAX_COMMAND_CHARS == 65_536
    at_the_cap = "echo " + "x" * (MAX_COMMAND_CHARS - len("echo  &")) + " &"
    assert len(at_the_cap) == MAX_COMMAND_CHARS
    assert judge(at_the_cap + "x", background=True) is None
    assert judge(at_the_cap, background=True) == LEAK_HINT


def test_the_shell_c_flag_matches_exactly_what_the_backtracking_pattern_did() -> None:
    """The `-c` cluster pattern was rewritten for speed, so its LANGUAGE has to be pinned
    against the pattern it replaced rather than against a description of it. The old pattern
    is written out here as a literal -- never imported -- so the two sides cannot move
    together.

    The probe set is enumerated, not hand-picked: every string up to four characters over an
    alphabet carrying each class the pattern distinguishes -- the leading `-`, the marker `c`,
    another lowercase letter, an uppercase `C` (which is NOT the marker, since the pattern's
    literal is lowercase), a digit, and the two braces from `-I{}`. 2,801 probes, covering
    `-c`, `-ac`, `-ca`, `--c`, `-cC`, `-c0`, `-{c}` and every other arrangement of those
    classes at that length.

    No mutation entry: what this test is about is that two regexes accept the same strings, so
    what reddens it is editing either pattern -- and editing the subject's pattern is the
    change it exists to catch. Verified by putting `[A-Za-z]` back in the leading class of the
    subject only... which does NOT redden it, because that is the slow pattern and the
    languages agree. Measured, and recorded rather than hidden: equivalence is the claim, and
    the timing test below is the separate assertion that the fast spelling is the one shipped.
    """
    old = re.compile(r"\A-[A-Za-z]*c[A-Za-z]*\Z")
    alphabet = "-caC0{}"
    probes: list[str] = [""]
    frontier = [""]
    for _ in range(4):
        frontier = [prefix + letter for prefix in frontier for letter in alphabet]
        probes.extend(frontier)
    probes = sorted(set(probes))
    assert len(probes) > 2_000  # the corpus must not have collapsed to a handful

    disagreements = [
        probe
        for probe in probes
        if bool(old.match(probe)) != bool(bgcleanup._SHELL_C_FLAG.match(probe))
    ]
    assert disagreements == []
    # And it still matches the spellings the module's own docstring names, so an "equivalent"
    # pair of patterns that both reject everything cannot pass this.
    assert [p for p in ("-c", "-lc", "-ic") if bgcleanup._SHELL_C_FLAG.match(p)] == [
        "-c",
        "-lc",
        "-ic",
    ]
    assert not any(bgcleanup._SHELL_C_FLAG.match(p) for p in ("--check", "--color", "-I{}", "-l"))


def test_a_long_option_cluster_does_not_hang_the_hook() -> None:
    """`judge` runs on every `PreToolUse` Bash call, so the time it takes is part of its
    contract: a hook past its timeout lets the call through unjudged. The old
    `-[A-Za-z]*c[A-Za-z]*` backtracked quadratically on a cluster of `c`s ending in a
    non-letter -- measured through `judge`, INSIDE `MAX_COMMAND_CHARS`, at 1.09 s / 4.44 s /
    10.14 s for 20k / 40k / 60k characters, which is the 4x-per-doubling signature. The same
    call now takes 0.13 s at 60k.

    Measured as a RATIO against a benign cluster of the same length, not against a clock. An
    absolute ceiling of three seconds held on one machine and failed on another: under coverage
    across four workers on a CI runner the fixed call spent 3.07 s of CPU (Python 3.12,
    2026-09-26), because coverage traces `judge`'s pure-Python scan line by line and shared cores
    stretch the same work into more CPU-seconds. Both calls below run through `judge` back to
    back, so whatever inflates one inflates the other. A `b` cluster takes the same path to the
    same verdict but gives the flag pattern nothing to backtrack over. Measured: 1.0 with the
    fixed pattern and 1.1 under coverage; with the old one, 48 and 19. Five sits between them
    with room on both sides.
    """
    cluster = "c" * 60_000
    command = f"bash -{cluster}0 'echo hi'"
    assert len(command) <= MAX_COMMAND_CHARS  # inside the cap, so the command IS read

    def cpu(text: str) -> float:
        start = time.process_time()
        judge(text, background=True)
        return time.process_time() - start

    benign = cpu(command.replace(cluster, "b" * len(cluster)))
    assert cpu(command) < 5 * benign


def test_a_trailing_restore_without_a_trap_is_warned_about() -> None:
    """Measured 2026-09-05: a foreground mutate-test-restore command outlived the 120 s
    timeout, was backgrounded by the harness and reaped before its restore line."""

    command = (
        "cp ci.yml ci.yml.bak; sed -i '' 's/a/b/' ci.yml; "
        ".venv/bin/python -m pytest tests/x.py; cp ci.yml.bak ci.yml"
    )
    context = hint(command)
    assert context is not None
    assert "trap" in context and "EXIT" in context and "cp ci.yml.bak ci.yml" in context


def test_a_restore_after_a_subshell_is_still_seen() -> None:
    """`(pytest); cp a.bak a` tokenizes with `);` fused; a split on bare separators misses the
    boundary and reads the restore as part of the subshell's command."""

    context = hint("cp a a.bak; (pytest); cp a.bak a")
    assert context is not None and "cp a.bak a" in context


@pytest.mark.parametrize(
    "options",
    ["-a", "-p", "--", "--preserve=all"],
)
def test_a_restore_written_with_options_is_still_seen(options: str) -> None:
    """`cp -a` and `cp -p` are how the measured mutate-test-restore is ORDINARILY written, and
    both were silent while the bare two-operand spelling -- the only one anyone had tested --
    warned. Reading `command[-1]` as the destination and `command[1]` as the source is true of
    exactly that one spelling: an option, a `--`, or a `-t` breaks both positions.

    `--preserve=all` is here for the long-option half: it must be dropped as an option WITHOUT
    consuming the operand behind it, which is the failure mode of treating every `-` token as
    something that takes an argument."""

    command = (
        f"cp {options} ci.yml ci.yml.bak; sed -i '' 's/a/b/' ci.yml; "
        f"pytest tests/x.py; cp {options} ci.yml.bak ci.yml"
    )

    context = hint(command)
    assert context is not None
    assert "ci.yml.bak ci.yml" in context


@pytest.mark.parametrize(
    "command",
    [
        "cp src/a.py build/a.py; make; cp build/a.py dist/a.py",
        "mv report.json reports/run1.json; pytest; mv reports/run1.json reports/final.json",
    ],
)
def test_a_chained_copy_is_not_a_restore(command: str) -> None:
    """The cry-wolf case, and the reason the match is a ROUND TRIP rather than "the last
    command's source is something an earlier one wrote".

    Both of these end by moving a file the command produced earlier and neither puts anything
    back -- the restore's destination is a THIRD path, not the backup's original. Under the
    weaker rule every chained copy and every staged rename warned, on a guard that reads
    foreground calls too. A guard that fires on ordinary work is one people learn to ignore."""

    assert hint(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "cp a.yml b.yml backup/; pytest; cp backup/ a.yml",
        "mv -t reports/ report.json; pytest; mv reports/ report.json",
    ],
)
def test_a_backup_copied_into_a_directory_is_not_a_round_trip(command: str) -> None:
    """A directory destination -- said by a third operand or by `-t` -- means the backup lives
    at `DIR/<name>`, a path this reader does not construct, so there is no round trip to see.

    The `-t` row is the one that read a SOURCE as the destination: `mv -t reports/ report.json`
    put `report.json` into the set of things that had been backed up, which is the opposite of
    what the command did with it."""

    assert hint(command) is None


def test_the_suggested_trap_body_is_the_restore_and_nothing_more() -> None:
    """The hint tells the reader to install its text as a trap body, and the text is rebuilt
    from tokens the tokenizer has already stripped of quoting. Joining them with spaces gives
    back a DIFFERENT command whenever any operand needed quoting: here a correctly quoted
    filename containing `;` reappears as a command separator, so the suggested trap body ends
    at the `;` and the rest becomes a second command in the trap line.

    Asserted by re-parsing rather than by string equality: the trap line must be four words,
    and its body must carry exactly the restore's argv."""

    command = 'cp "a; touch /tmp/PWNED" a.bak && pytest -q; cp a.bak "a; touch /tmp/PWNED"'

    context = hint(command)
    assert context is not None
    suggested = re.search(r"`(trap .+?)` as the FIRST line", context)
    assert suggested is not None, context
    argv = shlex.split(suggested.group(1))

    assert argv[0] == "trap" and argv[2:] == ["EXIT", "INT", "TERM"], argv
    assert shlex.split(argv[1]) == ["cp", "a.bak", "a; touch /tmp/PWNED"], argv[1]


@pytest.mark.parametrize(
    "command",
    [
        "trap 'cp b a' EXIT; cp a b; sed -i '' 's/x/y/' a; pytest; cp b a",
        "cp a b",
        "pytest tests/x.py; cp report.xml /tmp/out/",
    ],
)
def test_restores_with_a_trap_or_with_nothing_to_restore_stay_silent(command: str) -> None:
    """A trap makes the last line cleanup; a lone `cp`, or a `cp` that copies output away
    rather than restoring a backup, is not the shape."""

    assert hint(command) is None


def test_a_restore_command_with_no_operands_is_judged_rather_than_raised() -> None:
    """`cp --` names nothing to move. In the source this was a crash into the handler, which
    costs every hint of the call; `judge` must return rather than raise on any string."""
    assert judge("cp ci.yml ci.yml.bak; pytest; cp --", background=False) is None


# A chain measured on 2026-09-16: argparse exited 2, the completion notification said 0.
_MASKING_CHAIN = 'python3 gate.py --run > out.log 2>&1; echo "EXIT=$?" >> out.log'


def test_a_trailing_echo_after_a_semicolon_is_warned_about_in_the_background() -> None:
    """The harness reports the exit code of the chain's LAST command -- the echo's."""

    context = judge(_MASKING_CHAIN, background=True)

    assert context is not None, "silence is the bug"
    assert "python3 gate.py --run" in context and "notification" in context


def test_a_newline_before_the_echo_is_the_same_chain() -> None:
    context = judge('pytest -q > out.log 2>&1\necho "EXIT=$?" >> out.log', background=True)

    assert context is not None and "pytest -q" in context


def test_an_env_prefixed_echo_is_still_an_echo() -> None:
    """`command_words` is what this scanner has that the repository the guards were extracted
    from lacks; pin that it is used."""

    context = judge("pytest -q > out.log; FOO=1 echo done", background=True)

    assert context is not None and "notification" in context


def test_the_same_chain_in_the_foreground_is_silent() -> None:
    assert judge(_MASKING_CHAIN, background=False) is None


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q > out.log 2>&1 && echo ok >> out.log",
        "pytest -q > out.log 2>&1",
        "echo starting; pytest -q > out.log 2>&1",
        "pytest -q > out.log 2>&1; grep -c FAILED out.log",
    ],
)
def test_chains_whose_last_exit_code_is_the_real_one_are_not_warned_about(command: str) -> None:
    assert judge(command, background=True) is None


def test_a_numeric_final_argument_before_a_redirect_reads_as_a_file_descriptor() -> None:
    """PINS A KNOWN LIMITATION, not a desired outcome: `_command_head` cannot tell an ordinary
    trailing numeric argument from a file descriptor before a redirect, so the masked command
    this hint names can be short by one token -- here, a duration argument goes missing.

    `cmd 2> err.log` and `sleep 5 > out.log` tokenize to the identical shape --
    `['cmd', '2', '>', 'err.log']` next to `['sleep', '5', '>', 'out.log']` -- because
    tokenizing drops the whitespace that is the only thing telling a numbered descriptor from
    a genuine argument apart, so `_command_head` guesses descriptor and pops it either way.
    Gating the pop on `>&`/`<&` does not help: measured directly against this module's own
    `bashscan.tokenize`, neither shape carries one. There is no fix available from the token
    list alone, which is all `_command_head` receives, and this test exists so a sharper
    heuristic over those tokens is not written in the belief that one is there to find.

    NOT AN IMPOSSIBILITY CLAIM. The caller holds the raw command text and does not pass it
    down; an adjacency test on that text separates `cmd 2> err.log` from `sleep 5 > out.log`
    at once. A change that supplies the text and updates this expectation is a correct
    change, and this docstring must not read as an argument against it.

    Prefixed with `true;` so the chain's FIRST command is not `sleep`: unprefixed, the
    unrelated backgrounded-`sleep` rule answers alone before this hint is ever
    computed, and the test would pin that rule instead of `_command_head`.
    """
    context = judge("true; sleep 5 > out.log; echo done", background=True)

    assert context is not None
    assert "`sleep`" in context and "sleep 5" not in context


@pytest.mark.parametrize(
    "command",
    [
        "for f in a b; do cat $f; done; echo done",
        "if make > out.log; then echo ok; fi; echo finished",
    ],
)
def test_a_compound_statement_terminator_is_never_named_as_the_masked_command(
    command: str,
) -> None:
    """A hint advising "make `done` the last command of the chain" advises a command nobody
    wrote.

    The last `;` of a compound statement falls after its terminator word, so the segment
    before it is `done` or `fi` alone -- a keyword, not a program with an exit code of its
    own. A backgrounded loop closing with a progress echo is ordinary traffic for this rule,
    so naming its terminator is the cry-wolf failure `_restores_at_the_end` records, reached
    by the very shape this module's header opens with.
    """
    assert judge(command, background=True) is None


def test_a_second_echo_is_never_named_as_the_masked_command() -> None:
    """`cmd > out.log; echo "----"; echo "EXIT=$?"` masks `cmd`, two breaks back, and the
    segment before the last `;` is another echo whose own exit code is never the one anyone
    wanted. Silence beats naming the wrong command: a hint that says to read the status of an
    `echo` from its output teaches the reader to distrust the rule."""
    command = 'python -m pytest > out.log; echo "----"; echo "EXIT=$?"'

    assert judge(command, background=True) is None


@pytest.mark.parametrize(
    "command",
    [
        'pytest -q > out.log 2>&1; echo "EXIT=$?" >> out.log;',
        'pytest -q > out.log 2>&1\necho "EXIT=$?" >> out.log\n',
    ],
)
def test_a_trailing_separator_does_not_silence_the_hint(command: str) -> None:
    """A chain that ends with a separator it could have ended without is the same chain.

    The tokenizer turns a newline into a `;`, so a command carrying the trailing newline
    every editor writes reaches this rule with one break more than its author typed, and that
    last break has nothing after it. Dropping the empty tail is what keeps the commonest
    authoring of the flagship shape from passing unread.
    """
    context = judge(command, background=True)

    assert context is not None, "silence is the bug"
    assert "pytest -q" in context


def test_the_rendered_tail_keeps_its_redirect_a_redirect() -> None:
    """`_as_shell_text` promises text a shell reads as this file read it, and the hint invites
    the reader to compare that text with what they typed. Quoting `>>` hands back a literal
    argument to `echo` instead of an append, in the shape this rule most often sees."""
    context = judge(_MASKING_CHAIN, background=True)

    assert context is not None
    assert "echo 'EXIT=$?' >> out.log" in context
    assert "'>>'" not in context


@pytest.mark.parametrize("operator", ["&>", "&>>"])
def test_an_ampersand_redirect_is_not_part_of_the_masked_command(operator: str) -> None:
    """Two redirect operators start with neither `>` nor `<`, so a head that stops on the
    first character alone walks past them and renders the redirect as part of the command's
    own name. Cosmetic -- `&>` is not a chain operator, so the right command is still found --
    but the name handed back is not one the reader typed."""
    context = judge(f"pytest -q {operator} out.log; echo done", background=True)

    assert context is not None
    assert "`pytest -q`" in context and operator not in context
