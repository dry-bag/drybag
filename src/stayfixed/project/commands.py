"""The project area's command: `init` writes what is missing of a repository's scaffold.

**The summary is the rendered report, the way `overlay upgrade`'s is.** It was four lines of
counts, with every artifact's verb and the whole REFUSED section reachable only under `--json`
— so the skill that tells a relayer to pass on the report and "every refused line" was
describing output the command did not print, and the exit-1 path is the one a person meets
without a flag. `scaffold.render_report` is the renderer, and the same text goes into `--json`
under `scaffold`, so the two cannot disagree.

That is safe on the repository-bytes rule because every target it prints is a `Template`'s, held
to `PATH_VALUE` by the loader. The reason beside it is the engine's own fixed vocabulary. The
project's name reaches none of them.

**Exit 1 on a refusal, not 2.** A refused artifact is a finding the report names, and `apply`
was never reached: nothing was written, and re-running after the fix is the whole remedy. That
is `overlay upgrade`'s rule, and this command follows it so a caller scripting over both reads
one number. Exit 2 stays what it is everywhere — a refusal raised above the plan, such as a
missing `--yes`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from stayfixed.areas import SubParsers
from stayfixed.command import DRY_RUN_HELP, command_owner, common_flags, grammar
from stayfixed.errors import Refusal
from stayfixed.result import Result
from stayfixed.scaffold import render_report

if TYPE_CHECKING:
    from stayfixed.project.init import Given

# `(refused, dry_run)` -> the opening line. Three states and not two: a refused run wrote
# nothing, and it used to open `initialised:` above a REFUSED section saying the opposite. That
# was invisible while the summary was four count lines; printing the report is what made the
# header a claim a reader checks. A dry run that also refuses is reported as the refusal,
# because that is the finding the operator has to act on before either sentence is true.
HEADINGS = {
    (True, True): "refused, and nothing would be written:",
    (True, False): "refused, and nothing was written:",
    (False, True): "would initialise:",
    (False, False): "initialised:",
}
YES_HELP = (
    "take the defaults `init --questions` shows, with any answer flag below replacing one, and "
    "write the scaffold; without it nothing is written"
)
# Heads the list of what the run took for each question, which the skip path took unasked. Said
# of the run, as every other line of the report is, and never in the first person.
PICKED = "picked:"
# Over a `stayfixed.toml` somebody wrote, in place of that list: a run reads the file for where the
# scaffold lands and for nothing else, so its opening line is no verdict on the file.
ADOPTED_LEFT = (
    "stayfixed.toml is left as it is: this run read it only for where the scaffold lands, and the "
    "next command that loads it judges the file"
)
QUESTIONS_HELP = (
    "print the defaults init would take, where each came from and the flag that changes it; "
    "under --json, as a JSON Schema. Writes nothing"
)
# `--yes` is excluded by the parser. `--dry-run` and the answer flags are flags `--yes`
# takes, so one mutually exclusive group cannot exclude them as well, and this refusal is that
# half of the rule.
QUESTIONS_ALONE = (
    "--questions writes nothing and takes no flag but --root, --machine and --json; the "
    "answers go on `stayfixed init --yes`"
)


def _given(args: argparse.Namespace) -> Given:
    """The answer flags as `init` takes them: `None` for a flag not given."""
    from stayfixed.project.init import Given

    return Given(
        name=args.name,
        base_branch=args.base_branch,
        memory_mode=args.memory_mode,
        attribution_check=args.attribution_check,
    )


def run_questions(args: argparse.Namespace) -> Result:
    """The questions `init` would ask, printed as a card and carried under `--json` as a JSON
    Schema. Every value in either is bounded by a grammar or is stayfixed's own vocabulary."""
    from stayfixed.project.questions import card, questions

    root = Path(args.root).resolve()
    schema = questions(root, machine=Path(args.machine) if args.machine else None)
    return Result(card(schema), {"questions": schema})


def run_init(args: argparse.Namespace) -> Result:
    from stayfixed.project.init import NO_ANSWERS, init
    from stayfixed.project.questions import picked, shown

    if args.questions:
        if args.dry_run or _given(args) != NO_ANSWERS:
            raise Refusal(QUESTIONS_ALONE)
        return run_questions(args)
    root = Path(args.root).resolve()
    machine = Path(args.machine) if args.machine else None
    report = init(
        root,
        machine=machine,
        yes=args.yes,
        dry_run=args.dry_run,
        given=_given(args),
        owner=command_owner(machine),
    )
    scaffold = render_report(report.plan)
    refused = report.refused
    lines = [HEADINGS[(refused, report.dry_run)], "", scaffold]
    if report.adopted:
        lines.append(f"note: {ADOPTED_LEFT}")
    else:
        chosen = picked(report.config)
        lines += [PICKED, *(f"  {key}: {shown(value)}" for key, value in chosen.items())]
    if report.head_note:
        lines.append(f"note: {report.head_note}")
    data = {
        "dry_run": report.dry_run,
        "adopted": report.adopted,
        "scaffold": scaffold,
        "writes": report.plan.writes,
        "head_note": report.head_note,
    }
    return Result("\n".join(lines), data, exit_code=1 if refused else 0)


def _answers(parser: argparse.ArgumentParser) -> None:
    """The answer flags on `init --yes`, one per question `init --questions` prints.

    Each flag's `default` stays `None`, which is what lets `Given` tell a question not asked from
    an answer. A name and a branch are held to their grammar by `stayfixed.command.grammar`, whose
    refusal names the rule and never the value; every other answer is a `choices`, whose error
    quotes only the operator's own argument.
    """
    from stayfixed.config.schema import (
        BRANCH_NAME,
        BRANCH_RULE,
        MEMORY_MODES,
        NAME_RULE,
        PROJECT_NAME,
    )

    answers = parser.add_argument_group(
        "answers", "each replaces one default; `stayfixed init --questions` lists them"
    )
    name_rule = f"not {NAME_RULE}"
    branch_rule = f"not a plain branch name: {BRANCH_RULE}"
    answers.add_argument("--name", type=grammar(PROJECT_NAME, name_rule), help="[project] name")
    answers.add_argument(
        "--base-branch",
        type=grammar(BRANCH_NAME, branch_rule),
        help="[project] base_branch",
    )
    answers.add_argument("--memory-mode", choices=MEMORY_MODES, help="[memory] mode")
    answers.add_argument(
        "--attribution-check",
        action="store_const",
        const=True,
        help="[commit_messages] attribution_check = true: the commit gate fails a message "
        "carrying an AI tool's attribution",
    )


def register(groups: SubParsers) -> None:
    # `parser` and not `init`: the name `init` in this module is the command, and the function
    # `run_init` imports from `stayfixed.project.init`.
    parser = common_flags(groups.add_parser("init", help="write this repository's scaffold"))
    asking = parser.add_mutually_exclusive_group()
    asking.add_argument("--yes", action="store_true", help=YES_HELP)
    asking.add_argument("--questions", action="store_true", help=QUESTIONS_HELP)
    parser.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    _answers(parser)
    parser.set_defaults(func=run_init)
