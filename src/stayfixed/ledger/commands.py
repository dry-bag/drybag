"""The `bugs` group: `new`, `index [--check]`, `check`, `regressions`, `renumber OLD NEW`."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from stayfixed import fsops
from stayfixed.areas import SubParsers
from stayfixed.command import CHECK_HELP, common_flags, root_and_config
from stayfixed.errors import Failure
from stayfixed.findings import labels, listed
from stayfixed.ledger.register import BUG_SCHEMA, bug_register
from stayfixed.ledger.regressions import DEFAULT_TIMEOUT_SECONDS
from stayfixed.printed import printable, quoted
from stayfixed.result import Result

_OK = "OK: bug ledger entries, index freshness, and identifier references"
# What `index` says of an index it could not write: the command's failure, the reason in words,
# where the `OSError` was an internal error that named no way on.
UNWRITTEN = (
    "{index} could not be written ({reason}); once it can be, run `stayfixed {name} index` again"
)
_INERT = "nothing to check: no ledger directory and no generated index"
# What `regressions` says when no fixed entry carries a `regression` to run, and after its runs.
NO_REGRESSIONS = "nothing to run: no fixed entry carries a regression"
REGRESSIONS_RAN = "{ran} regression(s), {not_proved} not proved"
# `bugs regressions --timeout`'s grammar, said by the parser's refusal.
NOT_SECONDS = "--timeout takes a whole number of seconds above 0"
BASE_HELP = (
    "also fail when a commit HEAD forked from this base ref at carries the ledger and the tree "
    "has none, or carries an entry the tree lacks, so a change that deletes the ledger or an "
    "entry of it answers for it; without it the tree alone is judged"
)


def run_bugs_index(args: argparse.Namespace) -> Result:
    from stayfixed.ledger.entries import load_entries
    from stayfixed.ledger.index import index_text, refuse_index_overwrite, render_index

    root, config = root_and_config(args)
    ledger = bug_register(config)
    current = index_text(root, ledger)
    refuse_index_overwrite(root, ledger, current)
    entries = load_entries(root, ledger)
    rendered = render_index(entries, ledger)
    index = ledger.index
    if args.check:
        if current != rendered:
            return Result(
                f"{index} is stale; run: stayfixed {ledger.name} index",
                {"stale": True},
                exit_code=1,
            )
        return Result(f"OK: {index} is current ({len(entries)} entries)", {"stale": False})
    if current == rendered:
        return Result(
            f"{index} is current ({len(entries)} entries)",
            {"written": False, "entries": len(entries)},
        )
    try:
        fsops.write_within(root, index, rendered)
    except OSError as error:
        reason = fsops.said(error)
        raise Failure(
            UNWRITTEN.format(index=quoted(index), reason=reason, name=ledger.name)
        ) from error
    return Result(
        f"rewrote {index} ({len(entries)} entries)", {"written": True, "entries": len(entries)}
    )


def run_bugs_check(args: argparse.Namespace) -> Result:
    from pathlib import Path

    from stayfixed.committed import repository_prefix
    from stayfixed.ledger.check import bugs_gate, uninitialised

    if args.base:
        # The root as it was given, before `root_and_config` resolves it: against a base, a root
        # reached through a symlink is refused, since resolved it is the link's target, where the
        # base's copy can be made to be missing.
        repository_prefix(Path(args.root).absolute())
    root, config = root_and_config(args)
    # The `bugs` gate itself, so this command and a gate run cannot disagree.
    found = bugs_gate(root, config, args.base or "")
    # Before a ledger exists only a reference to an entry, or a ledger the change forked with, is
    # a finding, and there is none.
    if not found and uninitialised(root, bug_register(config)):
        return Result(_INERT, {"checked": False, "findings": []})
    data = {"checked": True, "findings": [asdict(p) for p in found]}
    if not found:
        return Result(_OK, data)
    # Labels only on the line: a path, a line number and a rule are this command's; the detail
    # may quote the repository and stays in `data`.
    return Result(f"FAIL: {len(found)} ledger problem(s): {labels(found)}", data, exit_code=1)


def run_bugs_regressions(args: argparse.Namespace) -> Result:
    import sys

    from stayfixed.ledger.regressions import regressions
    from stayfixed.prove.api import Verdict, line

    root, config = root_and_config(args)
    # The runner's output goes to standard error in both forms, so that under `--json` standard
    # output holds the one object.
    ran = regressions(root, config, timeout=args.timeout, echo=sys.stderr)
    rows = []
    lines = []
    for entry, receipt in ran:
        said = line(receipt)
        rows.append(
            {
                "id": entry.id,
                "path": entry.path.as_posix(),
                "verdict": str(receipt.verdict),
                "line": said,
            }
        )
        lines.append(f"{printable(entry.id)}: {said}")
    not_proved = sum(1 for _, receipt in ran if receipt.verdict is not Verdict.PROVED)
    data = {"regressions": rows, "not_proved": not_proved}
    if not ran:
        return Result(NO_REGRESSIONS, data)
    lines.append(REGRESSIONS_RAN.format(ran=len(ran), not_proved=not_proved))
    return Result("\n".join(lines), data, exit_code=1 if not_proved else 0)


def run_bugs_new(args: argparse.Namespace) -> Result:
    from stayfixed.ledger.write import file_entry

    root, config = root_and_config(args)
    filed = file_entry(
        root,
        bug_register(config),
        title=args.title,
        values={"severity": args.severity, "area": args.area, "source": args.source},
        related=tuple(args.related),
        fetch=not args.no_fetch,
    )
    relative = filed.path.relative_to(root).as_posix()
    summary = f"filed {relative}" + (f"; {filed.warning}" if filed.warning else "")
    return Result(summary, {"id": filed.identifier, "path": relative, "warning": filed.warning})


def run_bugs_renumber(args: argparse.Namespace) -> Result:
    from stayfixed.ledger.write import renumber

    root, config = root_and_config(args)
    result = renumber(root, config, bug_register(config), args.old, args.new)
    void = result.void.relative_to(root).as_posix()
    # Each file as `{path, reason}`, and the line names each by its `path`: a path may hold
    # `": "`, so a `"path: reason"` string could not be split back into the two.
    data = {
        "old": args.old,
        "new": args.new,
        "void": void,
        "unswept": [asdict(u) for u in result.unswept],
        "moved": result.moved,
        "lists_naming_old": list(result.lists_naming_old),
    }
    if not result.moved:
        return Result(f"{args.old} was already moved to {args.new}; nothing to do", data)
    naming = ""
    if result.lists_naming_old:
        naming = (
            f"; {len(result.lists_naming_old)} entry file(s) still name {args.old} in a list left "
            f"as written, which may need editing by hand "
            f"({listed([printable(path) for path in result.lists_naming_old])})"
        )
    if result.unswept:
        return Result(
            f"FAIL: {args.old} moved to {args.new}, but {len(result.unswept)} file(s) still "
            f"reference {args.old} and must be fixed by hand "
            f"({listed([printable(u.path) for u in result.unswept])}); "
            f"a void pointer remains at {void}{naming}",
            data,
            exit_code=1,
        )
    return Result(f"{args.old} -> {args.new}; a void pointer remains at {void}{naming}", data)


def _seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(NOT_SECONDS) from None
    if seconds <= 0:
        raise argparse.ArgumentTypeError(NOT_SECONDS)
    return seconds


def register(groups: SubParsers) -> None:
    bugs = groups.add_parser("bugs", help="the bug ledger")
    sub = bugs.add_subparsers(dest="command", metavar="<command>")
    new = common_flags(sub.add_parser("new", help="file a new entry and regenerate the index"))
    new.add_argument("title")
    # The levels no project configures, so the parser needs no configuration to offer them.
    new.add_argument("--severity", required=True, choices=BUG_SCHEMA.levels)
    new.add_argument("--area", required=True)
    new.add_argument("--source", default="")
    new.add_argument("--related", nargs="*", default=[])
    new.add_argument("--no-fetch", action="store_true", help="skip the pre-allocation fetch")
    new.set_defaults(func=run_bugs_new)
    index = common_flags(sub.add_parser("index", help="regenerate the index from the entry files"))
    index.add_argument("--check", action="store_true", help=CHECK_HELP)
    index.set_defaults(func=run_bugs_index)
    check = common_flags(
        sub.add_parser("check", help="validate the ledger, the index and every reference")
    )
    check.add_argument("--base", default=None, help=BASE_HELP)
    check.set_defaults(func=run_bugs_check)
    regressions = common_flags(
        sub.add_parser(
            "regressions", help="run each fixed entry's regression and say what its runner proved"
        )
    )
    regressions.add_argument(
        "--timeout",
        type=_seconds,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=f"end each run past this many seconds (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    regressions.set_defaults(func=run_bugs_regressions)
    renumber = common_flags(sub.add_parser("renumber", help="move an entry to a free identifier"))
    renumber.add_argument("old")
    renumber.add_argument("new")
    renumber.set_defaults(func=run_bugs_renumber)
