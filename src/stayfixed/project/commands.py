"""The project area's commands: `init` writes a repository's stayfixed scaffold once, `upgrade`
refreshes it, and `uninstall` takes it back.

**The summary is both rendered reports, the way `overlay upgrade`'s is.** It was four lines of
counts, with every artifact's verb and the whole REFUSED section reachable only under `--json`
— so the skill that tells a relayer to pass on "both reports" and "every refused line" was
describing output the command did not print, and the exit-1 path is the one a person meets
without a flag. `scaffold.render_report` is the renderer, and the same text goes into `--json`
under `once` and `scaffold`, so the two cannot disagree.

That is safe on the repository-bytes rule because `render_report` bounds every target it
prints: one outside `PATH_VALUE`, such as a target a committed manifest recorded, prints as its
artifact id. The reason beside it is the engine's own fixed vocabulary. The CI line is one of
this area's fixed sentences, or a tag and a commit the *release* area resolved from the public
repository's own tags. The project's name and its `[ci]` values reach none of them.

**The workflow is claimed only when nothing skipped it, and the ref it names is the one on
disk.** `_ci` reaches its branch-grammar check *after* the pin has resolved, so a repository with
a resolved tag and a `gate_branch` outside the grammar has a pin and no workflow; keying the CI
line on the pin told that repository `CI: <tag>@<sha>` while `skipped["ci-workflow"]` said the
opposite in `--json`. The key in `skipped` is the authority — `_ci` returns a template or a
reason and never both — and `report.ref` is the second half: on the adoption path the workflow
pins the ref `stayfixed.toml` already carried rather than one this run resolved, so the line says
that instead of naming a release the file does not record.

**Exit 1 on a refusal, not 2.** A refused artifact is a finding the report names, and `apply`
was never reached: nothing was written, there is no manifest, and re-running after the fix is
the whole remedy. That is `overlay upgrade`'s rule, and this command follows it so a caller
scripting over both reads one number. Exit 2 stays what it is everywhere — a refusal raised
above the plans, such as a missing `--yes` or a repository that is already initialised.
"""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from stayfixed.areas import SubParsers
from stayfixed.command import DRY_RUN_HELP, command_owner, common_flags, grammar
from stayfixed.errors import Refusal
from stayfixed.result import Result
from stayfixed.scaffold import Plan, Verb, printable, render_report, unlinks

if TYPE_CHECKING:
    from stayfixed.project.init import Given
    from stayfixed.release.api import Pin

# What the flag does and what it does not: it sets `[ci] mode` in the document this run builds,
# and on the adoption path that document is a `Kind.ONCE` artifact already on disk — reported
# `skip_modified`, and given at most a missing `[stayfixed] version` — so the file goes on saying
# `reusable` and the flag is spent on this run alone. Saying "sets [ci] mode" flat sent an
# operator looking for a key nothing wrote.
NO_CI_HELP = (
    'write no CI workflow and ask no remote for a pin; sets [ci] mode = "none" in the document '
    "this run builds, which on a repository that already has a stayfixed.toml is this run only"
)
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
# A count and fixed text: `[stayfixed] agents` is repository-authored, so its names never print.
UNKNOWN_HARNESSES = (
    "note: {count} name(s) in [stayfixed] agents name no harness this stayfixed serves; those "
    "harnesses were given the AGENTS.md region only"
)
YES_HELP = (
    "take the defaults `init --questions` shows, with any answer flag below replacing one, and "
    "write the scaffold; without it nothing is written"
)
# Fixed text: the verb is one of two this module chooses, and nothing the file says prints.
STAMPED = (
    "note: stayfixed.toml carried no [stayfixed] version, the one key stayfixed owns that the "
    "loader requires; this run {verb} it and leaves every other line as it was"
)
# Heads the list of what the run took for each question, which the skip path took unasked. Said
# of the run, as every other line of the report is, and never in the first person.
PICKED = "picked:"
PICKED_WITHHELD = "<unprintable; see stayfixed.toml>"
QUESTIONS_HELP = (
    "print the defaults init would take, where each came from and the flag that changes it; "
    "under --json, as a JSON Schema. Writes nothing"
)
# `--yes` is excluded by the parser. `--dry-run`, `--no-ci` and the answer flags are flags `--yes`
# takes, so one mutually exclusive group cannot exclude them as well, and this refusal is that
# half of the rule.
QUESTIONS_ALONE = (
    "--questions writes nothing and takes no flag but --root, --machine and --json; the "
    "answers go on `stayfixed init --yes`"
)


def _given(args: argparse.Namespace) -> Given:
    """The answer flags as `init` takes them: `None` for a flag not given, and a list flag's
    values in the order first given, each once."""
    from stayfixed.project.init import Given

    def listed(values: list[str] | None) -> tuple[str, ...] | None:
        return None if values is None else tuple(dict.fromkeys(values))

    return Given(
        name=args.name,
        base_branch=args.base_branch,
        agents=listed(args.agent),
        profile=args.profile,
        memory_mode=args.memory_mode,
        local=listed(args.local),
        attribution_check=args.attribution_check,
        types=listed(args.commit_type),
    )


def _pin(pin: Pin | None) -> dict[str, str] | None:
    """The resolved pin as `--json` prints it, for `init` and `upgrade` alike."""
    return None if pin is None else {"tag": pin.tag, "sha": pin.sha}


def run_questions(args: argparse.Namespace) -> Result:
    """The questions `init` would ask, printed as a card and carried under `--json` as a JSON
    Schema. Every value in either is bounded by a grammar or is stayfixed's own vocabulary."""
    from stayfixed.project.questions import card, questions

    root = Path(args.root).resolve()
    schema = questions(root, machine=Path(args.machine) if args.machine else None)
    return Result(card(schema), {"questions": schema})


def _picked_line(key: str, value: object) -> str:
    """One line of what `init --yes` picked. A value an adopted `stayfixed.toml` wrote, a commit
    type above all, prints through `printable`, withheld as `PICKED_WITHHELD` outside the grammar:
    the file holds it as it is."""
    from stayfixed.printed import printable
    from stayfixed.project.questions import shown

    if isinstance(value, str) and value:
        value = printable(value, PICKED_WITHHELD)
    elif isinstance(value, list):
        value = [printable(item, PICKED_WITHHELD) for item in value]
    return f"  {key}: {shown(value)}"


def run_init(args: argparse.Namespace) -> Result:
    from stayfixed.project.init import NO_ANSWERS, init
    from stayfixed.project.questions import picked
    from stayfixed.project.templates import CI_ARTIFACT
    from stayfixed.runner import subprocess_runner

    if args.questions:
        if args.dry_run or not args.ci or _given(args) != NO_ANSWERS:
            raise Refusal(QUESTIONS_ALONE)
        return run_questions(args)
    root = Path(args.root).resolve()
    machine = Path(args.machine) if args.machine else None
    report = init(
        root,
        machine=machine,
        runner=subprocess_runner(),
        yes=args.yes,
        dry_run=args.dry_run,
        ci=args.ci,
        given=_given(args),
        owner=command_owner(machine),
    )
    once, footprint = render_report(report.once), render_report(report.footprint)
    pin = report.resolution.pin
    skipped = report.skipped.get(CI_ARTIFACT)
    # `skipped is not None` is the whole condition, and the `or not report.ref` that stood
    # beside it and the `or 'no workflow was planned'` under it were both unreachable.
    # `templates._ci` returns a rendered workflow only for a non-empty `[ci] ref` that matches
    # `CI_REF`, and returns a non-empty reason in every other arm; `init` then derives
    # `report.ref` as `"" if CI_ARTIFACT in passes.skipped else config.ci.ref`. So a run
    # with no skip has a ref, the fallback string could never be formatted, and the disjunct
    # could never be the reason this branch was taken. `init`'s own comment calls the two "one
    # value by construction" and `doctor`'s `ci-ref` row enforces it; an unreachable arm that
    # would print a sentence nobody can provoke is the same species as a vacuous assertion,
    # and this repository deletes those.
    if skipped is not None:
        ci_line = f"CI: skipped — {skipped}"
    elif pin is not None and pin.sha == report.ref:
        ci_line = f"CI: {pin.tag}@{pin.sha}"
    else:
        ci_line = "CI: the workflow pins the [ci] ref this repository already recorded"
    refused = report.refused
    lines = [
        HEADINGS[(refused, report.dry_run)],
        "",
        "write-once:",
        once,
        "",
        "scaffold:",
        footprint,
        "",
        ci_line,
    ]
    chosen = picked(report.config) if report.config is not None else {}
    if chosen:
        lines += [PICKED, *(_picked_line(key, value) for key, value in chosen.items())]
    if report.note:
        lines.append(f"note: {report.note}")
    if report.unknown_harnesses:
        lines.append(UNKNOWN_HARNESSES.format(count=report.unknown_harnesses))
    if report.head_note:
        lines.append(f"note: {report.head_note}")
    if report.stamped:
        # Nothing is written by a dry run or a refused one, the stamp included.
        verb = "would write" if report.dry_run or report.refused else "wrote"
        lines.append(STAMPED.format(verb=verb))
    data = {
        "dry_run": report.dry_run,
        "adopted": report.adopted,
        "once": once,
        "scaffold": footprint,
        "writes": [*report.once.writes, *report.footprint.writes],
        "skipped": dict(report.skipped),
        "pin": _pin(pin),
        "asked": report.resolution.asked,
        "note": report.note,
        "ref": report.ref,
        "unknown_harnesses": report.unknown_harnesses,
        "head_note": report.head_note,
        "stamped": report.stamped,
    }
    return Result("\n".join(lines), data, exit_code=1 if refused else 0)


# The refused lines are `init`'s, word for word: a refused plan wrote nothing, whichever command
# planned it.
UPGRADE_HEADINGS = {**HEADINGS, (False, True): "would upgrade:", (False, False): "upgraded:"}
# What `--force` reaches is what `scaffold.plan` lets it reach: a file you edited, a whole file
# stayfixed never wrote at a path it writes (a caller workflow written by hand), and a copy under
# `.stayfixed/local/artifacts/` that changed since stayfixed wrote it or that nothing records.
FORCE_HELP = (
    "overwrite or remove a file the report lists skip_modified because you edited it, stayfixed "
    "never wrote it, or it is a changed or unrecorded copy under .stayfixed/local/artifacts/ "
    "(not one left at an artifact's old place, relocated and hand-edited, which is yours to keep "
    "or delete by hand); give it as a path relative to --root, repeat for each file, and never "
    "name one you did not mean"
)
# Fixed text: the value is what the operator typed, and the rule is what they can act on.
FORCE_OUTSIDE = "--force takes a path relative to --root, with no '..' component"
FORCE_UNMATCHED = (
    "note: {count} --force path(s) named no file this run had to judge, so they forced nothing; "
    "a path is compared exactly, relative to --root"
)
# The `upgrade` CI line when a workflow was rendered. Keyed on what the plan does with it, not on
# the absence of a skip reason: a workflow the report lists `skip_modified` (edited by hand, or
# never stayfixed's) or refuses is left as it is, and may pin anything at all.
CI_PINNED = "CI: the workflow pins [ci] ref"
CI_LEFT = (
    "CI: the workflow was left as it is, so what it pins is not this run's to say; the "
    "scaffold report names it and why"
)
# A count: the ids of records this build does not produce are repository-authored.
ORPHANS = (
    "note: {count} record(s) in .stayfixed/manifest.json name artifacts this stayfixed does not "
    "produce; they were left where they are"
)


def _force_paths(raw: list[str]) -> tuple[str, ...]:
    """Each `--force` value as the engine compares it: root-relative, with a leading `./` gone.

    An absolute path or one with a `..` component is refused naming the rule, never the value.
    """
    paths: list[str] = []
    for value in raw:
        path = PurePosixPath(value.removeprefix("./"))
        if path.is_absolute() or ".." in path.parts:
            raise Refusal(FORCE_OUTSIDE)
        paths.append(path.as_posix())
    return tuple(paths)


def _unmatched(force: tuple[str, ...], *plans: Plan) -> int:
    """How many forced paths no planned action names: a typo, or a file with nothing to force."""
    targets = {action.target for planned in plans for action in planned.actions}
    return sum(1 for path in force if path not in targets)


def run_upgrade(args: argparse.Namespace) -> Result:
    from stayfixed.project.templates import CI_ARTIFACT
    from stayfixed.project.upgrade import upgrade
    from stayfixed.runner import subprocess_runner

    force = _force_paths(args.force)
    machine = Path(args.machine) if args.machine else None
    report = upgrade(
        Path(args.root).resolve(),
        machine=machine,
        runner=subprocess_runner(),
        dry_run=args.dry_run,
        force=force,
        owner=command_owner(machine),
    )
    refused = report.refused
    moved = "; ".join(f"[{m.key[0]}] {m.key[1]} {m.before} -> {m.after}" for m in report.moved)
    shown = render_report(report.footprint)
    lines = [
        UPGRADE_HEADINGS[(refused, report.dry_run)],
        f"stayfixed.toml: {moved or 'nothing to move'}",
        "scaffold:",
        shown,
    ]
    skipped = report.skipped.get(CI_ARTIFACT)
    if skipped:
        lines.append(f"CI: skipped — {skipped}")
    else:
        lines.append(CI_PINNED if report.workflow_current else CI_LEFT)
    if report.held:
        lines.append(f"note: {report.held}")
    if report.orphans:
        lines.append(ORPHANS.format(count=report.orphans))
    if unmatched := _unmatched(force, report.footprint):
        lines.append(FORCE_UNMATCHED.format(count=unmatched))
    data = {
        "dry_run": report.dry_run,
        "moved": [
            {"key": ".".join(m.key), "before": m.before, "after": m.after} for m in report.moved
        ],
        "held": report.held,
        "scaffold": shown,
        "writes": report.footprint.writes,
        "skipped": dict(report.skipped),
        "orphans": report.orphans,
        "pin": _pin(report.resolution.pin),
        "asked": report.resolution.asked,
    }
    return Result("\n".join(lines), data, exit_code=1 if refused else 0)


# Said when the repository was attached: fixed text, since `detach`'s own report is counts of what
# the repository's ledger and settings named.
DETACHED = (
    "this repository was attached to an overlay, so uninstall ran `stayfixed detach` first, which "
    "withdrew what attach placed and its ledger"
)
DETACHED_DRY = (
    "this repository is attached to an overlay, so uninstall would run `stayfixed detach` first, "
    "which withdraws what attach placed and its ledger"
)
# The refused lines are `init`'s in substance, with the verb this command performs.
UNINSTALL_HEADINGS = {
    (True, True): "refused, and nothing would be removed:",
    (True, False): "refused, and nothing was removed:",
    (False, True): "would uninstall:",
    (False, False): "uninstalled:",
}


def run_uninstall(args: argparse.Namespace) -> Result:
    from stayfixed.project.uninstall import KEPT_CONFIG, KEPT_LOCALLY, uninstall
    from stayfixed.runner import subprocess_runner

    force = _force_paths(args.force)
    machine = Path(args.machine) if args.machine else None
    report = uninstall(
        Path(args.root).resolve(),
        machine=machine,
        dry_run=args.dry_run,
        force=force,
        runner=subprocess_runner(),
        owner=command_owner(machine),
    )
    refused = report.refused
    # Through `printable`, the bound the reports use, so a forged target is `<id>` in both. A
    # file one pass left and a later action deletes is gone, not left: with stayfixed's region
    # taken out of `AGENTS.md` by hand, the scaffold pass skips the file and the write-once pass
    # removes the untouched skeleton, and counting the skip told the person a deleted file was
    # theirs now.
    actions = (*report.footprint.actions, *report.once.actions)
    gone = {a.target for a in actions if unlinks(a)}
    left = sorted(
        printable(a) for a in actions if a.verb is Verb.SKIP_MODIFIED and a.target not in gone
    )
    footprint, once = render_report(report.footprint), render_report(report.once)
    lines = [
        UNINSTALL_HEADINGS[(refused, report.dry_run)],
        "scaffold:",
        footprint,
        "write-once:",
        once,
    ]
    if report.detached:
        lines.append(f"note: {DETACHED_DRY if report.dry_run else DETACHED}")
    if left:
        lines.append(f"left in place, yours now: {len(left)} file(s), each named above")
    if report.orphans:
        lines.append(ORPHANS.format(count=report.orphans))
    if report.note:
        lines.append(f"note: {report.note}")
    if report.kept_locally:
        lines.append(f"note: {KEPT_LOCALLY.format(count=report.kept_locally)}")
    if report.kept_config:
        lines.append(f"note: {KEPT_CONFIG}")
    if unmatched := _unmatched(force, report.footprint, report.once):
        lines.append(FORCE_UNMATCHED.format(count=unmatched))
    data = {
        "dry_run": report.dry_run,
        "scaffold": footprint,
        "once": once,
        "left": left,
        "orphans": report.orphans,
        "note": report.note,
        "kept_locally": report.kept_locally,
        "kept_config": report.kept_config,
    }
    return Result("\n".join(lines), data, exit_code=1 if refused else 0)


def _judging(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The two flags of a command that re-judges a scaffold, `upgrade` and `uninstall`."""
    parser.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    parser.add_argument("--force", action="append", default=[], metavar="PATH", help=FORCE_HELP)
    return parser


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
        COMMIT_TYPE,
        COMMIT_TYPE_RULE,
        MEMORY_MODES,
        NAME_RULE,
        PROJECT_NAME,
    )
    from stayfixed.harnesses import HARNESSES
    from stayfixed.profiles import shipped
    from stayfixed.project.templates import LOCAL_ELIGIBLE

    answers = parser.add_argument_group(
        "answers", "each replaces one default; `stayfixed init --questions` lists them"
    )
    name_rule = f"not {NAME_RULE}"
    branch_rule = f"not a plain branch name: {BRANCH_RULE}"
    answers.add_argument("--name", type=grammar(PROJECT_NAME, name_rule), help="[project] name")
    answers.add_argument(
        "--base-branch",
        type=grammar(BRANCH_NAME, branch_rule),
        help="[project] base_branch and release_branch",
    )
    answers.add_argument(
        "--agent",
        action="append",
        choices=[h.name for h in HARNESSES],
        help="[stayfixed] agents; once per harness",
    )
    answers.add_argument(
        "--profile",
        choices=("", *shipped()),
        metavar="NAME",
        help="[stayfixed] profile; an empty value for none",
    )
    answers.add_argument("--memory-mode", choices=MEMORY_MODES, help="[memory] mode")
    answers.add_argument(
        "--attribution-check",
        action="store_const",
        const=True,
        help="[commit_messages] attribution_check = true: the commit gate fails a message "
        "carrying an AI tool's attribution",
    )
    answers.add_argument(
        "--commit-type",
        action="append",
        type=grammar(COMMIT_TYPE, f"not a commit type: {COMMIT_TYPE_RULE}"),
        metavar="TYPE",
        help="[commit_messages] types; once per type",
    )
    answers.add_argument(
        "--local",
        action="append",
        choices=LOCAL_ELIGIBLE,
        help="[artifacts] local: keep this file out of git; once per file",
    )


def register(groups: SubParsers) -> None:
    # `parser` and not `init`: the name `init` in this module is the command, and the function
    # `run_init` imports from `stayfixed.project.init`.
    parser = common_flags(groups.add_parser("init", help="write this repository's scaffold"))
    asking = parser.add_mutually_exclusive_group()
    asking.add_argument("--yes", action="store_true", help=YES_HELP)
    asking.add_argument("--questions", action="store_true", help=QUESTIONS_HELP)
    parser.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    parser.add_argument("--no-ci", dest="ci", action="store_false", help=NO_CI_HELP)
    _answers(parser)
    parser.set_defaults(func=run_init, ci=True)
    upgrade = common_flags(groups.add_parser("upgrade", help="refresh this repository's scaffold"))
    _judging(upgrade).set_defaults(func=run_upgrade)
    uninstall = common_flags(
        groups.add_parser(
            "uninstall", help="remove this repository's scaffold; leave what you edited"
        )
    )
    _judging(uninstall).set_defaults(func=run_uninstall)
