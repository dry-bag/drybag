"""The owner-held files a new linked worktree gets: `projects/<name>/checkout/` of the overlay.

Some files belong to the owner and to no commit -- an `AGENTS.md` or `CLAUDE.md` the repository does
not track, a `stayfixed.toml` -- and a new linked worktree does not have them: git makes it from
the branch alone. The `owner-files` handler (`attach.hooks`) puts them there on `SessionStart`.

**What is placed.** Every regular file directly inside `<overlay>/projects/<project>/checkout/`,
except `LITTER`, `NEVER` and any name starting `NEVER_PREFIXES` (in any case: a folding filesystem
reads `.ENV` as `.env`); a subdirectory or a link there is skipped. Each is created exclusively
(`fsops.create_within`), with the source's permission bits, only where nothing is at the name: a
file the branch tracks is already there, so the branch wins, and a file, directory or link at a
name is never replaced, followed or written through. **Only a name git ignores is placed.** Git is
asked which of the names to place it ignores *before* any is created, and the others are named to
the session and left out: they would show in `git status` and go out with the next `git add -A`.

**Where.** Only a linked worktree (`linked_worktree`) that this machine
binds to a project, in the overlay the machine file records. `attach` itself places nothing in the
main checkout, where the owner's files already are.

**Adversary and anchor.** The adversary is a repository: a clone, or a branch checked out in the
owner's worktree. The anchor is the binding id in the repository's git common directory and this
machine's record of it (`binding.bound_project`), which a clone carries neither of and a branch
cannot write, and the overlay root, which comes from the machine file. A branch can commit a file
or a link at a target name; the name is then "there" and nothing is written. A branch can also
commit a `.gitignore` that re-includes a name (`!/AGENTS.md` outranks `info/exclude`); the anchor of
the ignore question is git's own evaluation of it, asked before the file exists, so the branch can
only make fewer files be placed and never more. Where git cannot answer, nothing is placed and
nothing is said. The git questions are
`rev-parse` and `check-ignore --no-index`, neither of which refreshes the index, so a repository's
`core.fsmonitor` does not run. Who must not be refused: a repository that tracks `AGENTS.md` --
the worktree has it from the branch, nothing is placed and nothing is said.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from stayfixed import fsops
from stayfixed.attach.exclude import unignored
from stayfixed.binding import bound_project
from stayfixed.config.overlay import overlay_root
from stayfixed.config.plates import PROJECTS
from stayfixed.errors import Refusal
from stayfixed.gitenv import answer_lines, git_run
from stayfixed.printed import printable

CHECKOUT = "checkout"
# Never placed: the machine's own settings and anything that holds secrets, whatever the owner put
# in `checkout/`.
NEVER = ("settings.local.json",)
NEVER_PREFIXES = (".env",)
LITTER = (".DS_Store",)
_WORKTREES = "worktrees"

PLACED = "stayfixed placed your owner-held files in this new worktree: {names}."
READ_AGENTS = "Read AGENTS.md now."
# Said of names left out because git would show them: the owner adds them to the checkout's
# `.git/info/exclude` to have them placed, unless the branch's `.gitignore` re-includes a name on
# purpose, which then stays out.
WITHHELD = (
    "{names} not placed: git would show them in `git status` here. Add them to the checkout's "
    "`.git/info/exclude` to have them placed, unless this branch's `.gitignore` un-ignores them on "
    "purpose, in which case they stay out."
)
# What is said of a name outside the path grammar.
THIS_FILE = "a file with an unprintable name"


def linked_worktree(root: Path) -> Path | None:
    """The toplevel of the linked worktree `root` is in, or `None`.

    A linked worktree is where `git rev-parse` says the git directory is
    `<common>/worktrees/<name>`. The main checkout (its git directory is the common one), a
    submodule (its git directory is under `modules/`) and a `git` that gives no answer are none.
    """
    code, out = git_run(
        root,
        "rev-parse",
        "--path-format=absolute",
        "--show-toplevel",
        "--git-dir",
        "--git-common-dir",
    )
    lines = answer_lines(out)
    if code != 0 or len(lines) != 3:
        return None
    toplevel, git_dir, common = (Path(line) for line in lines)
    return toplevel if git_dir.parent == common / _WORKTREES else None


def _held(source: Path) -> list[str]:
    """The names directly inside `source` that may be placed, in name order."""
    held: list[str] = []
    for name in sorted(os.listdir(source)):
        folded = name.lower()
        if name in LITTER or folded in NEVER or folded.startswith(NEVER_PREFIXES):
            continue
        if fsops.is_symlink(source / name) or not fsops.is_file(source / name):
            continue
        held.append(name)
    return held


def place(root: Path, *, machine: Path | None) -> tuple[list[str], list[str]]:
    """Place the owner-held files in the linked worktree `root` is in, and return the names placed
    and the names withheld, those no ignore pattern hides (`exclude.unignored`), which are not
    created.

    `([], [])` where `root` is not in a linked worktree, this machine binds it to no project, it
    records no overlay, or the project has no `checkout/` directory. A name with anything at it is
    neither placed nor withheld. A file that cannot be read or created is left out and the rest
    are placed; where git cannot say what is ignored, nothing is placed and nothing is withheld.
    """
    tree = linked_worktree(root)
    bound = bound_project(tree) if tree is not None else None
    overlay = overlay_root(machine) if bound is not None else None
    if tree is None or bound is None or overlay is None:
        return [], []
    source = overlay / PROJECTS / bound.project / CHECKOUT
    if not fsops.is_dir(source):
        return [], []
    try:
        vacant = [
            name
            for name in _held(source)
            if not fsops.is_symlink(tree / name) and not fsops.exists(tree / name)
        ]
        withheld = unignored(tree, vacant)
    except (Refusal, OSError):
        return [], []
    placed: list[str] = []
    for name in vacant:
        if name in withheld:
            continue
        try:
            data = fsops.read_regular_bytes(source / name)
            mode = stat.S_IMODE(os.stat(source / name).st_mode)
            if fsops.create_within(tree, name, data, mode=mode):
                placed.append(name)
        except OSError:
            continue
    return placed, list(withheld)


def said(placed: list[str], withheld: list[str]) -> str:
    """What the session is told about the `placed` names and the `withheld` ones: nothing where
    there are neither. The instruction to read `AGENTS.md` only where that file itself was placed,
    since a `CLAUDE.md` placed alone would point at whatever `AGENTS.md` the branch holds."""
    lines = [PLACED.format(names=_names(placed))] if placed else []
    if "AGENTS.md" in placed:
        lines.append(READ_AGENTS)
    if withheld:
        lines.append(WITHHELD.format(names=_names(withheld)))
    return " ".join(lines)


def _names(names: list[str]) -> str:
    return ", ".join(printable(name, withheld=THIS_FILE) for name in names)
