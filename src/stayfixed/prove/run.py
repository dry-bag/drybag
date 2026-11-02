"""`stayfixed prove`: run a test command where it is typed, count only its runner's report, and
say what that proves.

What `prove` does, in order. `hints.api.read_launch` reads the command past its assignments,
`env` and `uv run …` up to the first word a runner adapter recognises (the launch), and the first
adapter that recognises what is left plans the run. The command is launched in the directory it
is typed in, never in the top-level, and is judged in the directory it runs in (`moved`): the one
its launcher moves it to (`uv run --directory`, `UV_WORKING_DIR`), else that same directory. The
adapter plans from it, the project it answers for is its git top-level, or the directory itself
outside a repository, and the receipt names it. Every `NAME=value` the launch holds before its
launcher, bare or after an `env`, is an assignment of the command: one the adapter's `forging` set
says forges (a variable it names, set to a value its test says shapes the report) is `refused`
before anything is planned. The run's environment is built once: the caller's, less every inherited
variable the adapter's `forging` set says forges, then the command's own assignments in order, the
last of two for one name winning, as a shell builds it. The adapter plans in that environment,
finding its program on its `PATH` (`stayfixed.profiles.programs`), and the command runs in it. The
adapter is handed the launcher's words alone, never an assignment read before them, and keeps them
in front of the command as typed. The plan names the argv to execute, where the report arrives and
in which format, and the globs of the files the runner collects tests from. The tree's state is
taken and the command runs in a session of its own; then the report is counted, the tree's state
is taken again, and `CASCADE` says what the run proved. The plan's scratch directory, made outside
the project and readable by its owner alone, is removed on every path.

The bound, `BOUND`, which `docs/cli.md` states word for word: what a file in the tree, and the
environment, can do to the report is conceded, never checked. So the tree's state is information
for a reader of the receipt and never an input to the verdict: everything it reads, the agent that
typed the command can write.

**Every control here, with what it catches and its anchor.** Each guards against a mistake that
reads as a green run, never against an agent forging the report, which the bound concedes.

- `ASSIGNED_FORGING`: a variable under which the runner reports tests that checked nothing as
  passed, set to a value that does so (`PYTHONOPTIMIZE=1`, never `=0`), assigned in the command
  itself before its launcher, bare or after `env`; one behind `uv run` is a launcher word, the
  bound's. The anchor is the command's own words, which
  stayfixed reads before anything runs; the control is a closed list the adapter names
  (`forging`), and refuses nothing outside it. The same variable inherited with such a value is
  removed from the run's environment, which the receipt names (`scrubbed`). A variable an env file
  sets (`uv run --env-file`, an inherited `UV_ENV_FILE`) is past this reading: the file is the
  agent's to write, so that is the bound's.
- The report is read where the adapter put it, in the scratch directory, and where it is the
  runner's standard output, off the pipe: a file the repository committed, or text a test printed
  outside the format's own framing, is never counted. The anchor, the scratch directory and the
  pipe, is stayfixed's own; a test that writes the format's framing itself is the bound's.
- The process group: a child the command left in the background goes on writing into the tree
  after the verdict. The group is stayfixed's own anchor and is ended however the run finishes
  (`stayfixed.processes`); a descendant that leaves it is not reached, and the tee lets go of the
  pipe such a descendant holds once it has copied what is there.
- The runner's standard input: the agent, or anything upstream of `prove`, feeding it what drives
  the runner, such as the commands of pytest's debugger. The anchor is the launch stayfixed makes,
  which no one else writes: the run's standard input is `/dev/null`. It refuses no one; a test that
  reads standard input sees its end.
- `PROVE_TIMEOUT_SECONDS`: a suite that hangs. A named cap with its flag, `not proven` past it.
- `--junit PATH` (`prove(junit=…)`), for a runner no adapter knows: no adapter is consulted, the
  command runs as typed, and the report is the file at `PATH`, read from the directory the command
  runs in. `JUNIT_UNCHANGED`: a stale or committed report the run never wrote; the anchor is the
  state of the file the path reaches, followed through a link, as the run found it before it
  started (absent, or its inode, size and modification time), so a `latest.xml` link the run
  points at the report it just wrote is counted, and a link it newly makes to a stale file is
  the bound's. The agent can write that file too, so it is a convenience and never a guarantee;
  its detail names the file by its realpath. The receipt marks the runner not verified, and the
  verdict is the cascade's as for any other run.
"""

from __future__ import annotations

import codecs
import contextlib
import hashlib
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO, BinaryIO, TextIO

from stayfixed import fsops, processes
from stayfixed.gitenv import checkout_root
from stayfixed.hints.api import Launch, read_launch, run_directory
from stayfixed.printed import clipped, printable
from stayfixed.profiles.adapters import shipped_adapters
from stayfixed.profiles.programs import found, launched
from stayfixed.profiles.runners import (
    Plan,
    Refused,
    ReportKind,
    ReportSource,
    RunnerAdapter,
    Unresolved,
)
from stayfixed.prove import tree
from stayfixed.prove.counts import (
    MAX_REPORT_BYTES,
    REPORT_DOCTYPE,
    REPORT_ENTITY,
    REPORT_MALFORMED,
    REPORT_NOT_UTF8,
    REPORT_TOO_LARGE,
    Counts,
    ReportError,
)
from stayfixed.prove.reports import read_lines, read_report


class Verdict(StrEnum):
    """What a run proved, each a word the receipt and `--json` carry as it is."""

    PROVED = "proved"
    FAILED = "failed"
    NOT_PROVEN = "not proven"
    REFUSED = "refused"


# What `proved` means, in the one sentence `docs/cli.md` quotes word for word.
BOUND = (
    "The code under test, any file in the runner's load path, tracked or not, and the environment "
    "the runner reads can shape its report, so `proved` means the runner reported green on this "
    "tree, for the tests this command selected."
)

# The exit code of each verdict: a refusal is the 2 every refusal exits with, so a caller never
# reads it as a run that failed.
EXIT: Mapping[Verdict, int] = {
    Verdict.PROVED: 0,
    Verdict.FAILED: 1,
    Verdict.NOT_PROVEN: 1,
    Verdict.REFUSED: 2,
}

# A named cap: how long a run may take before its process group is ended and it is `not proven`.
# An hour bounds a suite that hangs and is no suite's budget; `--timeout` raises or lowers it. No
# shipped file states it.
PROVE_TIMEOUT_SECONDS = 3600
# A named cap: how long the runner's group has to exit on SIGTERM before it is sent SIGKILL
# (`processes.end`). Below `processes.TERM_WAIT_SECONDS`, so that a `prove` a gate ends that way
# (a `[gates.custom]` gate past its time limit, or interrupted) has ended its runner, whose
# session no signal to `prove`'s group reaches, before the gate's own SIGKILL ends `prove`.
RUNNER_TERM_WAIT_SECONDS = 2

# The reasons, each one arm of `CASCADE` or the step that stopped the run before it. An adapter's
# own refusals and unresolved plans are its module's constants, and the reports' are
# `stayfixed.prove.counts`'.
NOT_RECOGNISED = "not-recognised"
ASSIGNED_FORGING = "assigned-forging"
NOT_STARTED = "not-started"
TIMED_OUT = "timed-out"
INTERRUPTED = "interrupted"
NO_REPORT = "no-report"
FAILING = "failing"
NONE_RAN = "none-ran"
ALL_SKIPPED = "all-skipped"
GREEN_BUT_EXITED = "green-but-exited"
JUNIT_UNCHANGED = "junit-unchanged"

# What the receipt's line says for each reason, every arm in words of its own.
WORDS: Mapping[str, str] = {
    "": "the runner reported every test it ran as passed",
    NOT_RECOGNISED: "no runner adapter recognises this command, so nothing can count its report",
    ASSIGNED_FORGING: "the command assigns a variable its runner reads to shape the report",
    NOT_STARTED: "the command could not be started",
    TIMED_OUT: "the run passed its time limit and was ended",
    INTERRUPTED: "the run was interrupted and ended",
    NO_REPORT: "the runner wrote no report",
    FAILING: "the runner reported a failed test",
    NONE_RAN: "the runner reported no test run",
    ALL_SKIPPED: "the runner reported every test skipped",
    GREEN_BUT_EXITED: "the runner reported green and the command exited non-zero",
    JUNIT_UNCHANGED: "the run did not write the `--junit` report as a file of its own",
    REPORT_TOO_LARGE: "the report is past the size `prove` reads",
    REPORT_NOT_UTF8: "the report is not UTF-8",
    REPORT_MALFORMED: "the report does not parse as its format",
    REPORT_DOCTYPE: "the report declares a doctype",
    REPORT_ENTITY: "the report names an entity it never declared",
}
# The words for a reason an adapter names, by the verdict it stopped the run with.
_ADAPTER_WORDS: Mapping[Verdict, str] = {
    Verdict.REFUSED: "the runner's adapter refuses this command",
    Verdict.NOT_PROVEN: "the runner's adapter cannot plan this run",
}

# A shell assignment, `NAME=value`, as the shell reads one before a command and `env` after it.
_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.DOTALL)
# An option given its value in the same word, `--name=value`.
_OPTION_VALUE = re.compile(r"(--[^=]+=).*", re.DOTALL)
REDACTED = "…"


@dataclass(frozen=True)
class Receipt:
    """What one run of `prove` came to, and what a reader needs to weigh it.

    `argv` is the command as given with every `NAME=value` and `--option=value` value replaced by
    `REDACTED`; a value passed as the word after its option is kept, since nothing tells it from an
    operand. `directory` is the directory the command was judged in: the one it runs in, where
    its launcher moves it (`uv run --directory`), else the one it was typed in. `detail` is where
    the step that stopped the run stopped: the variable assigned, the option or word the runner's
    adapter refused, what the adapter looked for or was asked for
    where it could not plan the run, the `--junit` path the run did not write (`JUNIT_UNCHANGED`),
    or where a report stopped reading. `program` is the realpath of what ran; `verified` is false
    on every `--junit` receipt, a plan made or not, and true on every other. `scrubbed` names,
    sorted, each
    variable the caller's environment held that the run did not get, one of the adapter's
    `forging` set, since such a removal can turn a legitimate run red. `commit` and `dirty_before`
    are the tree's state before the run, `dirty_after` after it, and `untracked` (at most
    `tree.UNTRACKED_LISTED`, `untracked_more` past it) after it, or before it where git could not
    answer after: none of them is an input to the verdict.
    """

    verdict: Verdict
    reason: str
    detail: str
    argv: tuple[str, ...]
    directory: str | None = None
    runner: str | None = None
    program: str | None = None
    verified: bool = True
    scrubbed: tuple[str, ...] = ()
    counts: Counts | None = None
    exit_code: int | None = None
    report_digest: str | None = None
    commit: str | None = None
    dirty_before: bool | None = None
    dirty_after: bool | None = None
    untracked: tuple[str, ...] = ()
    untracked_more: int = 0


_NO_COUNTS = Counts(0, 0, 0)


@dataclass(frozen=True)
class _Outcome:
    """What the run came to before the cascade reads it: the reason of a step that refused or
    could not go on, or the counts and the exit code."""

    refused: str | None = None
    unproven: str | None = None
    counts: Counts | None = None
    exit_code: int | None = None

    @property
    def counted(self) -> Counts:
        """The counts, or none of each where there are none: only the rows past the first two
        read them, and an outcome without counts holds one of those two."""
        return self.counts if self.counts is not None else _NO_COUNTS


# The verdict cascade, one ordered table and the first row that holds wins; `docs/cli.md` states
# it row for row. A row is the verdict, its reason (`None` for the reason the step that stopped the
# run named), and what must hold. A run that ran no test, or skipped every one, has proved
# nothing whatever its exit code, so those rows stand before the exit code's.
CASCADE: tuple[tuple[Verdict, str | None, Callable[[_Outcome], bool]], ...] = (
    (Verdict.REFUSED, None, lambda outcome: outcome.refused is not None),
    (Verdict.NOT_PROVEN, None, lambda outcome: outcome.unproven is not None),
    (Verdict.FAILED, FAILING, lambda outcome: outcome.counted.failed > 0),
    (Verdict.FAILED, NONE_RAN, lambda outcome: outcome.counted.total == 0),
    (Verdict.FAILED, ALL_SKIPPED, lambda outcome: outcome.counted.skipped == outcome.counted.total),
    (Verdict.NOT_PROVEN, GREEN_BUT_EXITED, lambda outcome: outcome.exit_code != 0),
    (Verdict.PROVED, "", lambda outcome: True),
)


def judged(outcome: _Outcome) -> tuple[Verdict, str]:
    """The first row of `CASCADE` that holds for `outcome`: its verdict and its reason."""
    verdict, reason = next(
        (verdict, reason) for verdict, reason, holds in CASCADE if holds(outcome)
    )
    return verdict, reason if reason is not None else outcome.refused or outcome.unproven or ""


def redacted(argv: Sequence[str]) -> tuple[str, ...]:
    """`argv` with the value of every `NAME=value` and `--option=value` word replaced. A
    single-dash `-name=value` (Go's spelling) and a value given as the word after its option are
    kept as they are: nothing tells either from an operand."""
    shown: list[str] = []
    for word in argv:
        if assignment := _ASSIGNMENT.fullmatch(word):
            shown.append(f"{assignment.group(1)}={REDACTED}")
        elif option := _OPTION_VALUE.fullmatch(word):
            shown.append(f"{option.group(1)}{REDACTED}")
        else:
            shown.append(word)
    return tuple(shown)


def assignments(words: Sequence[str]) -> dict[str, str]:
    """The variables `words`, a launch's assignments (`hints.api.Launch.assignments`, each a
    `NAME=value`), assign, in order, the last of two for one name winning."""
    assigned: dict[str, str] = {}
    for word in words:
        name, _, value = word.partition("=")
        assigned[name] = value
    return assigned


class _Signalled(Exception):
    """A terminating signal reached `prove` while its command ran."""


@contextlib.contextmanager
def _signals_end_the_run() -> Iterator[None]:
    """`SIGTERM` and `SIGHUP` raise `_Signalled` while the block runs, so a run ended from outside
    ends its command's process group as an interrupt does, instead of leaving it running. Only
    where Python lets a handler be set, the main thread; the handlers before are put back."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def raised(signum: int, frame: object) -> None:
        raise _Signalled(signum)

    kept = {number: signal.signal(number, raised) for number in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for number, handler in kept.items():
            signal.signal(number, handler)


class _Tee:
    """The runner's standard output, copied as it arrives to the caller's stream and, where it is
    the report, up to one byte past `MAX_REPORT_BYTES` to the report too, by a thread of its own
    that owns both descriptors.

    Given `read`, the report's reader's test of a line (`reports.read_lines`), only the lines it
    reads anything from are copied to the report, so the cap counts what the reader needs and never
    the text a test printed; the caller still gets every byte. A line is held until its line break
    arrives, and the last one, cut short, when the pipe ends. The held part is weighed after each
    read: a line whose break arrives in the read that takes it past `MAX_REPORT_BYTES` is still
    judged whole, so a line the reader reads nothing from is left out up to a read (64 KiB) past
    the cap; once the held part alone is past the cap, with no break yet, it is copied as it
    stands, its rest and every byte after it with it, and the report is then past the cap.

    The thread reads until the pipe ends; once `finish` is asked, it stops at the first moment the
    pipe holds nothing, or once it has copied `MAX_REPORT_BYTES` more, so a descendant that left the
    process group and writes on cannot keep it. A caller's stream that takes text alone is handed
    whole characters, decoded across reads. A caller that has gone (`| head`, a closed stream) is
    written nothing more, and the report goes on filling.
    """

    def __init__(
        self,
        source: IO[bytes],
        report: int | None,
        caller: TextIO,
        read: Callable[[bytes], bool] | None = None,
    ) -> None:
        self._source = source
        self._report = report
        self._room = MAX_REPORT_BYTES + 1 if report is not None else 0
        self._read = read
        self._line = bytearray()
        self._stop = threading.Event()
        self._out: BinaryIO | None = getattr(caller, "buffer", None)
        self._text = caller
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._gone = False
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _echo(self, chunk: bytes, *, final: bool = False) -> None:
        if self._gone:
            return
        try:
            if self._out is not None:
                self._out.write(chunk)
                self._out.flush()
            else:
                self._text.write(self._decoder.decode(chunk, final))
        except (OSError, ValueError):
            # The reader of the caller's stream went away, or the stream was closed: the run is
            # not the caller's to end, and its report is not cut short.
            self._gone = True

    def _keep(self, data: bytes | bytearray) -> None:
        share = data[: self._room]
        self._room -= len(share)
        while share and self._report is not None:
            share = share[os.write(self._report, share) :]

    def _copy(self, chunk: bytes) -> None:
        self._echo(chunk)
        read = self._read
        if read is None:
            self._keep(chunk)
            return
        *ended, rest = chunk.split(b"\n")
        kept: list[bytes] = []
        for index, part in enumerate(ended):
            line = part + b"\n"
            if index == 0 and self._line:
                line = bytes(self._line) + line
                self._line.clear()
            if read(line):
                kept.append(line)
        self._keep(b"".join(kept))
        self._line += rest
        if len(self._line) > MAX_REPORT_BYTES:
            self._keep(self._line)
            self._line.clear()
            self._read = None

    def _last(self) -> None:
        """The last line, where the pipe ended inside one, copied as a whole one is."""
        if self._line and self._read is not None and self._read(bytes(self._line)):
            self._keep(self._line)
        self._line.clear()

    def _pump(self) -> None:
        after_stop = 0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self._source, selectors.EVENT_READ)
                while True:
                    stopping = self._stop.is_set()
                    if not selector.select(timeout=0 if stopping else 0.1):
                        if stopping:
                            return
                        continue
                    chunk = os.read(self._source.fileno(), 64 * 1024)
                    if not chunk:
                        return
                    self._copy(chunk)
                    if stopping:
                        after_stop += len(chunk)
                        if after_stop > MAX_REPORT_BYTES:
                            return
        finally:
            if self._out is None:
                self._echo(b"", final=True)
            self._source.close()
            if self._report is not None:
                self._last()
                os.close(self._report)

    def finish(self) -> None:
        """Stop once the pipe is drained, and wait for the thread to end."""
        self._stop.set()
        self._thread.join()


def _open_report(path: Path) -> int:
    """A descriptor for the teed report, a file this run creates: refused if anything is there."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    return os.open(path, flags, 0o600)


def _launch(plan: Plan, cwd: Path, env: Mapping[str, str], piped: bool) -> subprocess.Popen[bytes]:
    # S603: the adapter's plan of the command the caller typed, list form, never a shell. A
    # session of its own puts what it starts in one process group, which is ended however it
    # finishes. Standard input is `/dev/null`, never the caller's: what feeds `prove`'s could
    # drive the runner (a debugger takes its commands there), and a test that reads it sees its
    # end. Standard error is the caller's; standard output is too, or a pipe the tee copies whole
    # to the caller's stream, when it is the report or the caller named a stream of its own.
    return subprocess.Popen(  # noqa: S603
        list(plan.argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if piped else None,
        start_new_session=True,
    )


@dataclass(frozen=True)
class _Ran:
    stopped: str | None
    exit_code: int | None


def _run(
    plan: Plan, cwd: Path, env: Mapping[str, str], timeout: float, echo: TextIO | None
) -> _Ran:
    """Run `plan` in `cwd` under `env`, its process group ended however it finishes. The runner's
    standard output is the caller's, and a pipe teed to it when it is the report; given `echo`, it
    is always a pipe, teed to `echo`, whatever the report's source."""
    teed = plan.source is ReportSource.STDOUT
    piped = teed or echo is not None
    caller = echo if echo is not None else sys.stdout
    report = _open_report(plan.report) if teed else None
    sys.stdout.flush()
    with contextlib.suppress(OSError, ValueError):
        caller.flush()
    try:
        process = _launch(plan, cwd, env, piped)
    except OSError:
        if report is not None:
            os.close(report)
        return _Ran(NOT_STARTED, None)
    read = read_lines(plan.kind) if teed else None
    tee = None if process.stdout is None else _Tee(process.stdout, report, caller, read)
    try:
        try:
            with _signals_end_the_run():
                processes.exited(process, timeout)
                # The command has exited; what it left in its group goes now, while its pid is
                # unreaped. An interrupt here, as in the wait, ends the group the same way.
                processes.kill_group(process)
                code = process.wait()
        except subprocess.TimeoutExpired:
            processes.end(process, RUNNER_TERM_WAIT_SECONDS)
            return _Ran(TIMED_OUT, None)
        except (KeyboardInterrupt, _Signalled):
            # A terminal's Ctrl-C reaches stayfixed's process group and not the command's session,
            # so nothing but `prove` ends the command's group on the way out. One that landed after
            # the wait reaped the command leaves no group to end: its pid may be another's by now.
            if process.returncode is None:
                processes.end(process, RUNNER_TERM_WAIT_SECONDS)
            return _Ran(INTERRUPTED, None)
        except BaseException:
            processes.end(process, RUNNER_TERM_WAIT_SECONDS)
            raise
        return _Ran(None, code)
    finally:
        if tee is not None:
            tee.finish()


def _state(path: Path) -> tuple[int, int, int, int] | None:
    """What `path` reaches, followed through links: its mode, inode, size and modification time;
    `None` where it reaches nothing."""
    try:
        found = os.stat(path)
    except OSError:
        return None
    return found.st_mode, found.st_ino, found.st_size, found.st_mtime_ns


def _rewritten(before: tuple[int, int, int, int] | None, path: Path) -> bool:
    """Whether `path` now reaches a regular file that is not the one `before` found: one the run
    created or rewrote, or a link the run pointed at a file other than the one it reached. A
    path that reaches no regular file reads no report either way, so that test names the reason
    alone (Mutation: none -- the verdict is `not proven` with it or without it)."""
    after = _state(path)
    return after is not None and stat.S_ISREG(after[0]) and after != before


def _unverified(launch: Launch, report: Path, cwd: Path, environ: Mapping[str, str]) -> Plan | None:
    """The plan of a command no adapter is asked about: its launcher's words and its command, run
    as typed, the program found from `cwd` on `environ`'s `PATH` as the run finds it
    (`stayfixed.profiles.programs.launched`), and the report the file at `report`; `None` where
    the program is not there."""
    argv = launched(launch.launcher, launch.command, cwd, environ)
    if argv is None:
        return None
    return Plan(
        argv=argv,
        kind=ReportKind.JUNIT,
        source=ReportSource.FILE,
        report=report,
        discovery=(),
    )


def _counted(plan: Plan) -> tuple[Counts | None, str | None, str, str | None]:
    """The report counted, or the reason it was not, its detail, and the digest of what was read."""
    try:
        data, _ = fsops.read_bounded(plan.report, MAX_REPORT_BYTES + 1)
    except OSError:
        return None, NO_REPORT, "", None
    digest = hashlib.sha256(data).hexdigest()
    try:
        return read_report(plan.kind, data, drop=plan.drop), None, "", digest
    except ReportError as exc:
        return None, exc.reason, exc.detail, digest


@dataclass(frozen=True)
class _Run:
    """One run of `prove` once its command is read and its environment built: the command read
    into its parts as the adapter is handed it (`moved`: the launcher's first word by the path it
    was found at where the launcher moves the command, else as typed), the command as the receipt
    shows it, where it was typed (where the launch is made), the directory it is judged in and
    for which project, the run's environment and the inherited variables it lost, and how it is
    run and counted."""

    handed: Launch
    shown: tuple[str, ...]
    cwd: Path
    directory: Path
    root: Path
    env: Mapping[str, str]
    scrubbed: tuple[str, ...]
    timeout: float
    echo: TextIO | None
    junit: Path | None

    @property
    def verified(self) -> bool:
        """Whether the receipt calls its runner verified: false for a `--junit` run, and only
        for one."""
        return self.junit is None


def forges(forging: Mapping[str, Callable[[str], bool]], name: str, value: str) -> bool:
    """Whether `name=value` is one of `forging`'s, an adapter's (`RunnerAdapter.forging`): a
    variable it names, set to a value its test says shapes the report."""
    test = forging.get(name)
    return test is not None and test(value)


def environment(
    environ: Mapping[str, str],
    forging: Mapping[str, Callable[[str], bool]],
    assigned: Mapping[str, str],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """The run's environment, as a shell builds it for the command: `environ`, the caller's, less
    every variable `forging` says its value forges with (`forges`), then `assigned`, the command's
    own assignments, the last of two for one name winning; and the names, sorted, of the
    inherited variables it lost."""
    lost = tuple(sorted(name for name, value in environ.items() if forges(forging, name, value)))
    env = {name: value for name, value in environ.items() if name not in lost}
    env |= assigned
    return env, lost


def moved(launch: Launch, cwd: Path, environ: Mapping[str, str]) -> tuple[Launch, Path]:
    """`launch`, typed in `cwd` under `environ` (the run's environment), as the adapter is handed
    it, and the directory its command is judged in: the one its launcher runs it in
    (`hints.api.run_directory`), by its realpath, where that is a directory and the launcher's
    program is found from `cwd`, as a shell finds it there. The launcher's first word is then
    handed by the path it was found at, so that nothing looks for it from the directory it moves
    to. Else `launch` as typed and `cwd`: a launcher that names no directory there, or is not
    there itself, runs nothing, and the run is not started or fails as uv does."""
    target = run_directory(launch.launcher, cwd, environ)
    if target == cwd or not fsops.is_dir(target):
        return launch, cwd
    program = found(launch.launcher[0], cwd, environ)
    if program is None:
        return launch, cwd
    handed = launch._replace(launcher=(str(program), *launch.launcher[1:]))
    return handed, Path(os.path.realpath(target))


def prove(
    argv: Sequence[str],
    *,
    cwd: Path,
    environ: Mapping[str, str],
    timeout: float,
    adapters: Sequence[RunnerAdapter] | None = None,
    echo: TextIO | None = None,
    junit: Path | None = None,
) -> Receipt:
    """Run `argv` in `cwd` and say what its runner's report proves. `adapters` defaults to every
    adapter this stayfixed ships (`shipped_adapters`). Given `echo`, the runner's standard output,
    every byte, goes there whatever the report's source (`--json` hands standard error, so that
    standard output holds the one object); without it, the runner's standard output is the
    caller's.

    Given `junit`, a path read from the directory the command runs in (`moved`), no adapter is
    consulted: the command runs as typed and its report is the JUnit file at that path, counted
    only where the run created or rewrote it as a regular file (`JUNIT_UNCHANGED`), its runner
    marked not verified.

    An adapter whose plan's program is not an absolute path is a defect in stayfixed, as a module
    that does not import is, and raises `ValueError`: a bare name would be found from stayfixed's
    own directory and `PATH`, never where the adapter looked. So is a plan whose report, a file the
    runner writes, lies outside the scratch directory the core handed it: a report anywhere else
    could be one the repository committed.
    """
    given = tuple(argv)
    shown = redacted(given)
    known = shipped_adapters() if adapters is None else adapters
    launch = read_launch(given, lambda words: any(each.recognises(words) for each in known))
    command = launch.command
    adapter = (
        next((each for each in known if command and each.recognises(command)), None)
        if junit is None
        else None
    )
    runner = adapter.name if adapter is not None else None
    assigned = assignments(launch.assignments)
    forging = adapter.forging if adapter is not None else {}
    env, scrubbed = environment(environ, forging, assigned)
    handed, directory = moved(launch, cwd, env)
    root = checkout_root(directory) or directory
    run = _Run(handed, shown, cwd, directory, root, env, scrubbed, timeout, echo, junit)
    if adapter is None and (junit is None or not command):
        return _receipt(
            _Outcome(unproven=NOT_RECOGNISED), shown, directory=directory, verified=run.verified
        )
    forged = sorted(name for name, value in assigned.items() if forges(forging, name, value))
    if forged:
        return _receipt(
            _Outcome(refused=ASSIGNED_FORGING),
            shown,
            runner,
            directory=directory,
            detail=", ".join(forged),
            verified=run.verified,
        )
    # A Ctrl-C or a terminating signal anywhere from here on, the tree's state, the plan or the
    # reap as much as the wait, ends the run `not proven`, its scratch directory removed, and the
    # caller still prints its receipt: never an internal error.
    try:
        with _signals_end_the_run():
            return _planned_and_proved(adapter, run)
    except (KeyboardInterrupt, _Signalled):
        return _receipt(
            _Outcome(unproven=INTERRUPTED),
            shown,
            runner,
            directory=directory,
            verified=run.verified,
        )


def _planned_and_proved(adapter: RunnerAdapter | None, run: _Run) -> Receipt:
    if adapter is None:
        junit = run.junit
        unverified = (
            _unverified(run.handed, run.directory / junit, run.directory, run.env)
            if junit is not None
            else None
        )
        if unverified is None:
            return _receipt(
                _Outcome(unproven=NOT_STARTED),
                run.shown,
                directory=run.directory,
                verified=run.verified,
            )
        return _proved(None, unverified, run)
    scratch = Path(tempfile.mkdtemp(prefix="stayfixed-prove-"))
    try:
        planned = adapter.plan(
            run.handed.launcher,
            run.handed.command,
            cwd=run.directory,
            scratch=scratch,
            environ=run.env,
        )
        if isinstance(planned, Refused):
            return _receipt(
                _Outcome(refused=planned.reason),
                run.shown,
                adapter.name,
                directory=run.directory,
                detail=planned.detail,
            )
        if isinstance(planned, Unresolved):
            return _receipt(
                _Outcome(unproven=planned.reason),
                run.shown,
                adapter.name,
                directory=run.directory,
                detail=planned.detail,
            )
        if planned.source is ReportSource.FILE and scratch not in planned.report.parents:
            raise ValueError(
                f"the {adapter.name} adapter planned a report outside its scratch directory"
            )
        return _proved(adapter.name, planned, run)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _proved(runner: str | None, plan: Plan, run: _Run) -> Receipt:
    if not os.path.isabs(plan.argv[0]):
        raise ValueError(f"the {runner} adapter planned a program that is not absolute")
    program = os.path.realpath(plan.argv[0])
    before = tree.state(run.root, plan.discovery)
    found = _state(plan.report)
    ran = _run(plan, run.cwd, run.env, run.timeout, run.echo)
    after = tree.state(run.root, plan.discovery)
    if ran.stopped is not None:
        outcome, detail, digest = _Outcome(unproven=ran.stopped), "", None
    elif run.junit is not None and not _rewritten(found, plan.report):
        outcome = _Outcome(unproven=JUNIT_UNCHANGED, exit_code=ran.exit_code)
        detail, digest = os.path.realpath(plan.report), None
    else:
        counts, unread, detail, digest = _counted(plan)
        outcome = _Outcome(unproven=unread, counts=counts, exit_code=ran.exit_code)
    return _receipt(
        outcome,
        run.shown,
        runner,
        directory=run.directory,
        program=program,
        detail=detail,
        before=before,
        after=after,
        digest=digest,
        scrubbed=run.scrubbed,
        verified=run.verified,
    )


def _receipt(
    outcome: _Outcome,
    shown: tuple[str, ...],
    runner: str | None = None,
    *,
    directory: Path | None = None,
    program: str | None = None,
    detail: str = "",
    before: tree.TreeState | None = None,
    after: tree.TreeState | None = None,
    digest: str | None = None,
    verified: bool = True,
    scrubbed: tuple[str, ...] = (),
) -> Receipt:
    """The receipt of `outcome`; `verified` is false for a `--junit` run, and only for one."""
    verdict, reason = judged(outcome)
    files = after if after is not None and after.untracked is not None else before
    return Receipt(
        verdict=verdict,
        reason=reason,
        detail=detail,
        argv=shown,
        directory=str(directory) if directory is not None else None,
        runner=runner,
        program=program,
        verified=verified,
        scrubbed=scrubbed,
        counts=outcome.counts,
        exit_code=outcome.exit_code,
        report_digest=digest,
        commit=before.commit if before is not None else None,
        dirty_before=before.dirty if before is not None else None,
        dirty_after=after.dirty if after is not None else None,
        untracked=(files.untracked or ()) if files is not None else (),
        untracked_more=files.more if files is not None else 0,
    )


def line(receipt: Receipt) -> str:
    """The receipt in one line: the verdict and its reason in words, the counts, the runner and
    its program, the inherited variables the run did not get, and the untracked files in the
    discovery set. A variable's name is one of an adapter's forging set, never one the environment
    chose. A name the tree chose prints only inside the path grammar (`printed.printable`);
    `--json` carries every one."""
    words = WORDS.get(receipt.reason) or _ADAPTER_WORDS.get(receipt.verdict, receipt.reason)
    head = f"{receipt.verdict}: {words}"
    if receipt.reason not in WORDS:
        head += f" ({receipt.reason})"
    if receipt.detail:
        head += f": {clipped(receipt.detail)}"
    parts = [head]
    if receipt.counts is not None:
        counts = receipt.counts
        parts.append(f"{counts.passed} passed, {counts.failed} failed, {counts.skipped} skipped")
    if receipt.exit_code not in (None, 0):
        parts.append(f"exit {receipt.exit_code}")
    if receipt.runner is not None:
        runner = f"runner {receipt.runner}"
        if receipt.program is not None:
            runner += f" at {clipped(receipt.program)}"
        if not receipt.verified:
            runner += ", not verified"
        parts.append(runner)
    elif not receipt.verified:
        ran = f", ran {clipped(receipt.program)}" if receipt.program is not None else ""
        parts.append(f"runner not verified{ran}")
    if receipt.scrubbed:
        parts.append(f"removed from the run's environment: {', '.join(receipt.scrubbed)}")
    if receipt.untracked:
        listed = ", ".join(printable(name) for name in receipt.untracked)
        more = f" and {receipt.untracked_more} more" if receipt.untracked_more else ""
        parts.append(f"untracked in the discovery set: {listed}{more}")
    return "; ".join(parts)
