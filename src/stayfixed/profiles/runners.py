"""What a test runner's adapter and the core say to each other about a run and its report.

A leaf: the adapters under `profiles/<stack>/` and the `prove` core both import it, and it imports
nothing from either, so neither reaches the other through it and no package cycle forms. It is
also the public contract an adapter stayfixed does not ship implements: `RunnerAdapter`, and the
three answers its `plan` gives.

An adapter plans the command as it was typed: the launcher's words kept in front, the runner's
own words as they are, and only its report options added, so that what runs is what the command
selects. It refuses only what a person or an agent could type by mistake and get a green report
for tests that never ran or never checked anything, from a short closed list of its own.
Everything else a file in the tree, or the environment, can do is the bound's, which
`docs/cli.md` states.

No entry in `mutations/` covers this module: it declares names and records and decides nothing.
Which reader a kind is read with is `stayfixed.prove.reports.read_report`'s, and what the core
does with a plan is `stayfixed.prove.run`'s; their entries cover those.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

# The reasons every adapter may name, published once here so that two adapters never spell one
# differently: an option of its closed list that the command spells (`Refused`), and a runner's
# entry point that does not resolve, or a run that never ends (`Unresolved`). An adapter's own
# further reasons are its module's; each module lists every reason it names as `REASONS`, which
# the documents hold apart from the core's.
REFUSED_OPTION = "refused-option"
ENTRY_NOT_FOUND = "entry-not-found"
NEVER_ENDS = "never-ends"


class ReportKind(StrEnum):
    """The report formats `prove` counts, each by the format's own name and never a runner's."""

    # JUnit XML: `testcase` elements.
    JUNIT = "junit"
    # The JSON test-results report: `testResults`, each with its `assertionResults`.
    RESULTS_JSON = "results-json"
    # The test event stream: one JSON object a line, each with its `Action`.
    EVENTS = "events"


class ReportSource(StrEnum):
    """Where the report arrives: a file the runner writes at `Plan.report`, or the runner's own
    standard output, which the core copies to the caller whole and to `Plan.report`."""

    FILE = "file"
    STDOUT = "stdout"


@dataclass(frozen=True)
class Plan:
    """How to run a recognised command so that its report can be counted.

    `argv` is what is executed, its first item absolute: the program, which the receipt names by
    its realpath. `kind`, `source` and `report` say what the report is and where it arrives;
    `report` lies in the scratch directory the core handed the plan. `argv` holds no assignment
    and no `env`: the core takes every `NAME=value` the command spells, before its launcher or
    after it, out of the launch it hands `plan`, and puts it in the run's environment, the one
    `plan` is handed too. `argv[0]` not absolute is a defect in the adapter, and the core raises.
    `discovery` is the globs of the files the runner collects tests from, matched from the right
    (`stayfixed.prove.tree`). `drop` is the JUnit reader's (`stayfixed.prove.junit.read_junit`),
    for a testcase a runner writes that is no test; a testcase holding a failure counts as failed
    whatever it answers. Whether a runner is verified is no plan's to say: the core marks every
    `--junit` run's receipt, and only those, not verified.
    """

    argv: tuple[str, ...]
    kind: ReportKind
    source: ReportSource
    report: Path
    discovery: tuple[str, ...]
    drop: Callable[[Mapping[str, str]], bool] | None = None


@dataclass(frozen=True)
class Refused:
    """The command spells something on the adapter's closed list: an option under which the
    runner reports tests that never ran, or checked nothing, as passed. `reason` is a constant of
    the adapter's module, and `detail` names what the command spelled, the option, for the
    receipt."""

    reason: str
    detail: str = ""


@dataclass(frozen=True)
class Unresolved:
    """The adapter cannot plan a run it can prove: the runner's entry point does not resolve from
    where the command runs, the command asks for a run that never ends, or for one that runs no
    test suite that reports (vitest's `no-test-run`). `reason` is a constant of the adapter's
    module, and `detail` says what was looked for or asked for, and what to do instead, for the
    receipt."""

    reason: str
    detail: str = ""


class RunnerAdapter(Protocol):
    """One test runner, as `prove` asks about it. A stack ships its adapters as `ADAPTERS`, a
    tuple, in `profiles/<stack>/adapters.py`, and `stayfixed.profiles.adapters.shipped_adapters`
    lists them."""

    @property
    def name(self) -> str:
        """The runner's name, for the receipt."""
        ...

    @property
    def forging(self) -> Mapping[str, Callable[[str], bool]]:
        """The variables under which the runner reports tests that checked nothing as passed, each
        with the test of a value that does (`PYTHONOPTIMIZE=0` optimises nothing): assigned such a
        value in the command itself, the command is refused; inherited with one, the variable is
        removed from the run's environment, and the receipt names it."""
        ...

    def recognises(self, command: Sequence[str]) -> bool:
        """Whether `command` runs this runner. `command` is what is left once the assignments,
        `env` and `uv run …` are read past (`hints.api.read_launch`)."""
        ...

    def plan(
        self,
        launch: Sequence[str],
        command: Sequence[str],
        *,
        cwd: Path,
        scratch: Path,
        environ: Mapping[str, str],
    ) -> Plan | Refused | Unresolved:
        """How to run `command`, run in `cwd` after `launch`, its report put under `scratch`; or
        why not. A pure function of its arguments and of the filesystem it reads: it runs
        nothing. `cwd` is the directory the command runs in: the one it was typed in, or the one
        its launcher moves it to (`uv run --directory`). Where the launcher moves it, the core
        hands the launcher's first word by the path a shell finds it at from the directory the
        command was typed in, so that the plan never looks for it from the one it moves to.

        `launch` is the launcher's words alone (`uv run` and its options, and whatever launcher
        the core reads through): the core has taken every assignment and every `env` out of it.
        Every adapter keeps the launcher's words in front of its plan, as they were typed, so the
        program is then the launcher. `environ` is the run's own environment, the one the command
        runs under: the caller's less the inherited variables `forging` removes, then the
        command's own assignments, the last of two for one name winning; a program is found on
        its `PATH` (`stayfixed.profiles.programs.found`), as the shell running the command would
        find it."""
        ...
