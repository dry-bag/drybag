"""The `commit` and `test` groups."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from stayfixed import fsops
from stayfixed.areas import SubParsers
from stayfixed.command import command_owner, common_flags
from stayfixed.config.loader import load
from stayfixed.errors import Failure, Refusal
from stayfixed.findings import listed
from stayfixed.result import Result

if TYPE_CHECKING:
    from stayfixed.config.schema import Config

# Printed on every `commit check` failure, which is inside the CI gate's own output, so it may
# only name commands that exist. The clause naming the installer was dropped while the hook
# installer shipped as a library alone and `setup` had not yet offered it from the command line;
# `stayfixed setup --git-hooks` ships now, so the clause is back, and the rule it was dropped for
# — a remedy that sends a person to an unknown subcommand costs more than a missing clause does
# — is what holds it to `setup --git-hooks` and nothing else.
_STRIP_REMEDY = (
    "Rewrite the messages without the trailer (`git rebase -i --exec 'git commit --amend "
    "--no-edit' <base>`, or `git commit --amend` for the last one). `stayfixed commit strip "
    "FILE` does the same to one message file, and `stayfixed setup --git-hooks` installs the "
    "hook that strips it before the commit exists."
)

# Fixed text and a count: what `commit strip` says when it keeps attribution lines it would have
# stripped, because the person set what the harness's commits carry
# (`harness_says_what_commits_carry`). Never begins "nothing to strip", the one line the hook keeps
# quiet: a kept trailer is worth a line on the terminal, and a message with nothing to strip says
# that instead, whatever the setting.
GIVES_WAY = (
    "kept {count} attribution line(s): Claude Code's attribution.commit setting in your own "
    "settings says what a commit carries, so the message is left as it is"
)
# The one line the hook filters out (`githooks.HOOK_TEXT`'s `quiet`), and every earlier
# release's hook with it.
NOTHING_TO_STRIP = "nothing to strip"

# git's own default for `core.commentChar` (the `prepare-commit-msg` comment block). Not read from
# the repository's config: a value this module would feed straight into a line-prefix comparison is
# exactly the kind of repository-authored value principle 5 calls untrusted, and there is no
# subprocess guard to put around a plain string compare. A repository that changed the default gets
# no split and therefore no strip on that file — a no-op, not a corruption.
_COMMENT_CHAR = "#"

# git's scissors line, matched on `>8` alone and not on the sentence around it. The line git
# writes is `# ------------------------ >8 ------------------------`, and the two lines under it
# ("Do not modify or remove the line above.") go through gettext — a German or Japanese checkout
# writes them translated, and a rule keyed on the English wording would silently stop splitting
# there. The ruler and its `>8` are not translated.
_SCISSORS_MARKER = ">8"


def _split_trailing_comment_block(text: str) -> tuple[str, str]:
    """Split a `prepare-commit-msg` file into `(message region, everything git will discard)`.

    Two things are discarded, and the first of them was missed. **`commit.verbose = true` puts
    the staged diff in this file**, below a scissors line, and a diff's lines start with `diff`,
    `+`, `-`, `@@` or a space — so the walk back over comment and blank lines stopped at the
    very first one it saw, the whole file read as "message", the attribution block was no longer
    trailing and the hook became a silent no-op. Measured: with `commit.verbose` set, the same
    commit that reports `stripped 2 attribution line(s)` without it stored the trailer intact.
    One config key disabling the whole local layer is worth the extra rule.

    So the scissors line is found first and everything from it down is discarded region; then
    the run of comment and blank lines at the end of what is left is discarded too. The second
    part is the ordinary interactive commit: git's `# Please enter the commit message…` block is
    the file's last paragraph, and `offending_lines`/`strip_message` judge only a message's
    *trailing attribution block* (see `commit.py`'s docstring), which a comment line is not — so
    stripping the file's text whole would no-op on exactly the file the hook is handed.

    `commit.py` must never learn about `#` or about scissors: in a message read from `git log` a
    `#` line is real content, so this split lives here, on the file-reading side. Both rules fail
    the same way, which is the safe way: a message that itself carries a `#` line with `>8` in it
    loses the strip below that point and keeps every byte, a no-op rather than a corruption.
    """
    lines = text.splitlines(keepends=True)
    cut = len(lines)
    for index, line in enumerate(lines):
        # The FIRST scissors line: git truncates the message there, so anything below it —
        # including a second one — is already not part of the message.
        if line.startswith(_COMMENT_CHAR) and _SCISSORS_MARKER in line:
            cut = index
            break
    above, below = lines[:cut], lines[cut:]
    index = len(above)
    while index > 0 and (
        above[index - 1].strip() == "" or above[index - 1].startswith(_COMMENT_CHAR)
    ):
        index -= 1
    if not any(line.startswith(_COMMENT_CHAR) for line in above[index:]):
        index = len(above)  # no comment line back there; nothing to split off
    return "".join(above[:index]), "".join(above[index:] + below)


def _root_and_config(args: argparse.Namespace) -> tuple[Path, Config]:
    root = Path(args.root).resolve()
    machine = Path(args.machine) if getattr(args, "machine", None) else None
    return root, load(root, machine=machine, owner=command_owner(machine))


def run_commit_check(args: argparse.Namespace) -> Result:
    from stayfixed.guards.commit import check_range

    root, config = _root_and_config(args)
    report = check_range(root, str(args.rev_range), config)
    data = {
        "commits": report.commits,
        "violations": [
            {"sha": v.sha, "offences": [{"line": o.line, "label": o.label} for o in v.offences]}
            for v in report.violations
        ],
    }
    if not report.violations:
        return Result(f"OK: {report.commits} commit message(s) checked", data)
    # Capped: a range holds any number of commits, and `violations` carries every offence.
    items = listed(
        [f"{v.sha[:12]} line {o.line} [{o.label}]" for v in report.violations for o in v.offences]
    )
    return Result(
        f"FAIL: {len(report.violations)} of {report.commits} commit message(s) carry an "
        f"attribution trailer: {items}. {_STRIP_REMEDY}",
        data,
        exit_code=1,
    )


def run_commit_strip(args: argparse.Namespace) -> Result:
    from stayfixed.config.machine import owner_home
    from stayfixed.guards.commit import (
        harness_says_what_commits_carry,
        offending_lines,
        strip_message,
    )

    raw = str(args.file)
    if raw.startswith("-"):
        raise Refusal(f"{raw!r} looks like an option, not a file")
    path = Path(raw)
    if fsops.is_symlink(path):
        raise Refusal(f"{path} is a symlink; refusing to write through it")
    # `--root` elsewhere is never `-`-checked and is safe only because `Path(...).resolve()`
    # makes it absolute before any `git -C` sees it; this argument is not resolved, so it is.
    try:
        original = path.read_text(encoding="utf-8")
    # `UnicodeDecodeError` is not an `OSError`, and without it a message file in a non-UTF-8
    # encoding — `i18n.commitEncoding` is a real git setting — reached the CLI frame as
    # `internal error: UnicodeDecodeError` and exit 2, the code a caller is told never to read
    # as permission. It is a file this command cannot read, exactly like the `OSError` beside
    # it, so it is the same `Failure`. `githooks.py` catches it explicitly; this was the one
    # place that did not. It does not render the exception: that one names the
    # offending byte, and the byte came out of the file.
    except OSError as exc:
        raise Failure(f"cannot read {path}: {exc}") from None
    except UnicodeDecodeError:
        raise Failure(f"cannot read {path}: it is not valid UTF-8") from None
    message, comment_block = _split_trailing_comment_block(original)
    stripped_message = strip_message(message)
    # A message that is *only* attribution would be emptied, which aborts the commit with a
    # confusing "empty message" error. Leave it alone and let CI explain.
    if not stripped_message.strip() or stripped_message == message:
        return Result(NOTHING_TO_STRIP, {"stripped": 0})
    count = len(offending_lines(message))
    # Asked only once a line would go, so a message with nothing to strip says so whatever the
    # setting, and the hook stays quiet on it.
    if harness_says_what_commits_carry(owner_home()):
        return Result(GIVES_WAY.format(count=count), {"stripped": 0})
    fsops.write_atomically(path, stripped_message + comment_block)
    return Result(f"stripped {count} attribution line(s) from {path}", {"stripped": count})


# A tree git could not report on is not a clean tree. Exit 2 (refusal), never exit 0: the whole
# value of this command is that it answers "can this red run be trusted", and "I do not know"
# reported as "yes" is the one wrong answer.
_NO_GIT = "git could not report the tree's status, so this tree cannot be judged"
# The same answer for a profile this command could not ask, which is not one with nothing to
# report: its hint did not load, answered outside its protocol, or raised. `{name}` is a shipped
# profile's directory name, never a repository value, and of an exception only its type is
# printed: its message can carry a path the hint walked, and a path is repository-authored text.
_UNLOADED = "the {name} profile's red-run hint could not be loaded"
_WORDLESS = "the {name} profile's red-run hint answered in something other than text"
_FAILED = "the {name} profile's red-run hint failed: {kind}"
# And for a hint whose walk stopped at its bound (a report of `None`): it has not seen the tree,
# so neither its count nor its silence is an answer, and a refusal is the one that says so. Even
# over a tree with no bytecode in it: a walk cut short that met none has not seen the rest, and
# the order it lists in is the filesystem's. The bound is not configurable and what it walks is,
# so the refusal names that way out.
_UNTOLD = "the {name} profile's red-run hint stopped its walk at a bound and could not tell"
_UNJUDGED = ", so this tree cannot be judged"
_NARROW = "; narrow `[ledger] code_roots` to the directories that hold code"
# What the summary says after the uncommitted-change check's answer, in place of "tree is clean",
# when no code root is left to walk: every profile's walk saw nothing, so its silence is no answer
# about the tree. `assess` counts each entry left out; its inventory names it, and why.
NO_ROOTS = "no [ledger] code_roots entry names a directory here, so no code root was walked"
NO_CHANGE = "no uncommitted change"


def run_test_hygiene(args: argparse.Namespace) -> Result:
    from stayfixed.guards.roots import contained_roots
    from stayfixed.hints.api import dirty_count
    from stayfixed.profiles import detects, load_profile
    from stayfixed.profiles.hints import NotText, answer, shipped_hints

    root, config = _root_and_config(args)
    dirty = dirty_count(root)
    if dirty is None:
        raise Refusal(_NO_GIT)
    findings: list[str] = []
    if dirty:
        findings.append(f"{dirty} uncommitted change(s) in the tree")
    hints = shipped_hints()
    unloaded = [name for name, hint in hints if hint is None]
    if unloaded:
        raise Refusal("; ".join(_UNLOADED.format(name=name) for name in unloaded) + _UNJUDGED)
    # Every stack the repository is written in, and not the one `[stayfixed] profile` names: a
    # repository in two stacks gets two entries. A profile is listed when its markers sit at the
    # root, and also, whether or not they do, when it has something to say: the hook asks every
    # hint and detects nothing, so a Python project in a subdirectory gets the stale-bytecode
    # note after a failed run, and this command must not call the same tree clean.
    reports: dict[str, dict[str, int]] = {}
    roots = contained_roots(root, config)
    for name, hint in ((name, hint) for name, hint in hints if hint is not None):
        try:
            report, note = answer(hint, roots)
        except NotText:
            raise Refusal(_WORDLESS.format(name=name) + _UNJUDGED) from None
        except Exception as exc:
            kind = type(exc).__name__
            raise Refusal(_FAILED.format(name=name, kind=kind) + _UNJUDGED) from None
        if report is None:
            raise Refusal(_UNTOLD.format(name=name) + _UNJUDGED + _NARROW)
        if note is None and not detects(load_profile(name), root):
            continue
        reports[name] = report
        if note:
            findings.append(f"{name}: {note}")
    # Counts, fixed sentences and shipped profiles' names only: a `ledger.code_roots` entry is a
    # repository-authored string and never reaches the summary. `data` is the documented
    # exception and carries none either: each report is what `counts` kept, count names in a
    # fixed grammar with plain integers.
    clean = "tree is clean" + "".join(
        f"; the {name} profile has nothing to report" for name in reports
    )
    summary = "; ".join(findings) or clean
    if not roots:
        summary = "; ".join([*(findings or [NO_CHANGE]), NO_ROOTS])
    data = {"dirty": dirty, "profiles": reports}
    return Result(summary, data, exit_code=1 if findings else 0)


def run_test_attribute(args: argparse.Namespace) -> Result:
    from stayfixed.config.layout import local_base
    from stayfixed.guards.attribute import attribute
    from stayfixed.runner import subprocess_runner

    root, config = _root_and_config(args)
    base = args.base or local_base(config)
    result = attribute(root, command=args.command, base=base, runner=subprocess_runner())
    data = {
        "runs": {
            "head_ambient": result.head_ambient,
            "head_clean": result.head_clean,
            "base_clean": result.base_clean,
        },
        "base": result.base,
        "merge_base": result.merge_base,
        "verdict": result.verdict,
    }
    return Result(result.verdict, data)


def register(groups: SubParsers) -> None:
    commit = groups.add_parser("commit", help="commit-message rules")
    commit_sub = commit.add_subparsers(dest="command", metavar="<command>")
    check = common_flags(
        commit_sub.add_parser("check", help="check every message in a revision range")
    )
    check.add_argument("--range", dest="rev_range", required=True, help="e.g. main..HEAD")
    check.set_defaults(func=run_commit_check)
    strip = commit_sub.add_parser("strip", help="strip attribution lines from a message file")
    strip.add_argument("file", help="the commit-message file git handed the hook")
    strip.set_defaults(func=run_commit_strip)

    test = groups.add_parser("test", help="test-suite hygiene")
    test_sub = test.add_subparsers(dest="command", metavar="<command>")
    hygiene = common_flags(
        test_sub.add_parser("hygiene", help="what could falsify a red run in this tree")
    )
    hygiene.set_defaults(func=run_test_hygiene)
    attribute = common_flags(
        test_sub.add_parser(
            "attribute", help="attribute a failing command to the change or to the environment"
        )
    )
    attribute.add_argument(
        "--command",
        required=True,
        help="the exact failing command, including the environment sync it needs",
    )
    attribute.add_argument(
        "--base",
        default=None,
        help="ref to compare against (default: refs/remotes/origin/<project.base_branch>)",
    )
    attribute.set_defaults(func=run_test_attribute)
