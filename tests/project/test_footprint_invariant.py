"""One invariant for `init`, `upgrade` and `uninstall`, asked of every hostile input at once.

A write or removal must never land on a file whose bytes the committer does not control and git
does not show. The inputs that could aim one are repository-authored: the committed
`stayfixed.toml` (`[paths]`, `[artifacts] local`), the committed manifest, and the local ledger a
clone can force-add; and, at `init`, the answers a person passes as flags, which `precheck`
keeps off any committed document. Each hostile case below is one such input, run at every
command that meets it — `init` reads `[paths]` from a fresh clone; `upgrade` and `uninstall` act
on recorded targets, so they meet a `[paths]` value only together with a record placing the
artifact there.

- **I1, nothing hidden is clobbered.** After every command, finished or refused, each file the
  case planted where git does not show it — an ignored file, a file under `.git/`, stayfixed's
  out-of-git state, another artifact's kept-out-of-git copy — is present with its bytes, and no
  file has appeared under `.git/`.
- **I2, the legitimate user is not refused.** The legitimate cases run their commands to the
  end: no `Refusal` raised, and no refusal returned in the report's plans, which is the other
  way a command refuses.
- **I3, the end state is consistent.** After a finished `init` or `upgrade`, a
  dry-run `upgrade` of the same tree plans nothing and refuses nothing: every artifact the
  configuration builds is at its own place with its own bytes. After a finished `uninstall`, a
  second one says there is nothing to uninstall, and stayfixed's own directory is gone.

Mutations (declared): each guard of the class put back one at a time — the ignore guard, the
shared `.git` predicate and its case folding, the `.stayfixed` reservation, the ledger's and the
collision rule's ownership checks — and guards made to refuse more than they should, which the
legitimate cases catch. An entry names every row it reddens; a row no single line can redden
says so where it is declared.

What this module does not cover: guards that decide nothing about a hidden file's bytes, such
as the attach refusal and the refusals over files `uninstall` would leave under
`.stayfixed/local/`, which their own modules hold.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pytest

from stayfixed.config.layout import ATTACH_LEDGER
from stayfixed.config.loader import CONFIG_FILE
from stayfixed.config.paths import STAYFIXED_DIRECTORY
from stayfixed.errors import Refusal
from stayfixed.project.init import ANSWER_SHEET, NO_ANSWERS, Given, InitReport, init
from stayfixed.project.templates import LOCAL_ELIGIBLE
from stayfixed.project.uninstall import NOTHING, UninstallReport, uninstall
from stayfixed.project.upgrade import UpgradeReport, upgrade
from stayfixed.scaffold import digest
from stayfixed.scaffold.local import LOCAL_ARTIFACTS, LocalDigests
from tests.gitfixture import git, needs_git
from tests.project.repos import DOCUMENT, MOVED_OFF_DOCS, forge_record, repository
from tests.runners import LsRemote, Recorder

Command = Literal["init", "upgrade", "uninstall"]
Report = InitReport | UpgradeReport | UninstallReport

# Bytes no stayfixed build renders: a person's file, or a tool's.
FOREIGN = "bytes a person or another tool wrote\n"
HOOK = "#!/bin/sh\n# the clone's own pre-commit hook\n"
CLAUDE_COPY = f"{LOCAL_ARTIFACTS}/CLAUDE.md"
CLAUDE_COPY_FOLDED = f"{LOCAL_ARTIFACTS}/claude.md"


def _forge_roadmap_at(target: str, text: str) -> Callable[[Path], None]:
    """A record moving `roadmap` onto `target`, stating the digest of `text` found there."""

    def forge(root: Path) -> None:
        forge_record(root, "roadmap", target=target, sha256=digest(text))

    return forge


def _forge_ledger_entry(target: str) -> Callable[[Path], None]:
    """A force-added ledger whose one entry, under `roadmap`, names `target` with the digest of
    `claude-md`'s unedited, and so predictable, copy."""

    def forge(root: Path) -> None:
        sha = digest((root / CLAUDE_COPY).read_text(encoding="utf-8"))
        LocalDigests().with_entry("roadmap", target, sha).write(root)

    return forge


@dataclass(frozen=True)
class Case:
    """One configuration of repository-authored inputs, and what git hides around it.

    For a hostile case `commands` are the commands that meet it, each run in a tree of its own;
    for a legitimate case they are one sequence, each run in the tree the last one left.
    """

    name: str
    commands: tuple[Command, ...]
    paths: Mapping[str, str] = field(default_factory=dict)
    local: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    # Hidden files the case plants, root-relative, with their text: held to I1 unless tracked.
    plant: Mapping[str, str] = field(default_factory=dict)
    # Files `init` leaves hidden, held to I1 except by `uninstall`, whose job is removing them.
    # A kept `CLAUDE_COPY` brings its case-folded spelling along (see `_surround`).
    keep: tuple[str, ...] = ()
    links: Mapping[str, str] = field(default_factory=dict)
    track: tuple[str, ...] = ()
    forge: Callable[[Path], None] | None = None
    # The answers `init` is given as flags; `NO_ANSWERS` is `--yes` alone.
    given: Given = NO_ANSWERS
    # Whether the clone commits the case's `stayfixed.toml`; a fresh clone has none.
    written: bool = True
    # The one refusal a hostile case must meet, where another guard would also refuse it and so
    # hide the one the row is about.
    refusal: str | None = None

    def document(self, *, with_paths: bool) -> str:
        text = DOCUMENT
        if self.local:
            listed = ", ".join(f'"{name}"' for name in self.local)
            text += f"\n[artifacts]\nlocal = [{listed}]\n"
        if with_paths and self.paths:
            text += "\n[paths]\n" + "".join(f'{k} = "{v}"\n' for k, v in self.paths.items())
        return text


HOSTILE = (
    Case(
        "region-into-an-ignored-file",
        ("init", "upgrade"),
        paths={"agents_md": ".env"},
        ignore=(".env",),
        plant={".env": FOREIGN},
    ),
    Case(
        "forged-record-at-an-ignored-file",
        ("upgrade", "uninstall"),
        paths={"roadmap": "build/marker.txt"},
        ignore=("build/",),
        plant={"build/marker.txt": FOREIGN},
        forge=_forge_roadmap_at("build/marker.txt", FOREIGN),
    ),
    Case(
        "region-into-git-s-hook",
        ("init", "upgrade"),
        paths={"agents_md": ".git/hooks/pre-commit"},
    ),
    Case(
        "region-into-git-s-hook-case-folded",
        ("init", "upgrade"),
        paths={"agents_md": ".GIT/hooks/pre-commit"},
    ),
    # A file git does not have yet: the only way to see a write that creates one under `.git/`.
    Case(
        "a-new-file-under-git",
        ("init", "upgrade"),
        paths={"agents_md": ".git/info/attributes"},
    ),
    Case(
        "forged-record-at-git-s-hook",
        ("upgrade", "uninstall"),
        paths={"roadmap": ".git/hooks/pre-commit"},
        forge=_forge_roadmap_at(".git/hooks/pre-commit", HOOK),
    ),
    # Held by three layers — `contained()`'s symlink check, the ignore guard failing closed on a
    # path git cannot answer about, and the write walk's `O_NOFOLLOW` — so no single line
    # reddens it: it pins that the three never go at once.
    Case(
        "region-into-git-s-hook-through-a-symlink",
        ("init", "upgrade"),
        paths={"agents_md": "gitlink/hooks/pre-commit"},
        links={"gitlink": ".git"},
    ),
    # At `upgrade` the planted ledger is also an existing file git ignores, so the ignore guard
    # holds it beside the `.stayfixed` reservation: that row reddens only with both gone.
    Case(
        "region-into-attach-s-ledger",
        ("init", "upgrade"),
        paths={"agents_md": ATTACH_LEDGER},
        plant={ATTACH_LEDGER: FOREIGN},
    ),
    Case(
        "region-into-attach-s-ledger-case-folded",
        ("init", "upgrade"),
        paths={"agents_md": ATTACH_LEDGER.replace(".stayfixed", ".stayfixed")},
        plant={ATTACH_LEDGER: FOREIGN},
    ),
    # The same three layers as the `.git` symlink.
    Case(
        "region-into-attach-s-ledger-through-a-symlink",
        ("init", "upgrade"),
        paths={"agents_md": "hidden/attach.json"},
        plant={ATTACH_LEDGER: FOREIGN},
        links={"hidden": ".stayfixed/local"},
    ),
    Case(
        "region-into-another-artifact-s-hidden-copy",
        ("upgrade",),
        paths={"agents_md": CLAUDE_COPY},
        local=("claude-md",),
        keep=(CLAUDE_COPY,),
    ),
    Case(
        "cross-id-ledger-entry",
        ("upgrade",),
        local=("claude-md",),
        keep=(CLAUDE_COPY,),
        forge=_forge_ledger_entry(CLAUDE_COPY),
    ),
    Case(
        "cross-id-ledger-entry-case-folded",
        ("upgrade",),
        local=("claude-md",),
        keep=(CLAUDE_COPY,),
        forge=_forge_ledger_entry(CLAUDE_COPY_FOLDED),
    ),
    # `roadmap` placed at `CLAUDE.md` spelled in another case: one file where case folds, an
    # existing file stayfixed did not write where it does not. Either way the collision must be
    # refused, or the roadmap is never written and the next upgrade still has work to do.
    Case(
        "a-paths-value-at-another-artifact-s-file-case-folded",
        ("init", "upgrade"),
        paths={"roadmap": "claude.md"},
        plant={"claude.md": FOREIGN},
    ),
    # Answers over a document the clone committed would rewrite what the committer chose; they
    # are refused before anything is read beyond the root.
    Case(
        "answers-over-a-committed-document",
        ("init",),
        paths={"agents_md": ".env"},
        ignore=(".env",),
        plant={".env": FOREIGN},
        given=Given(local=("roadmap-history",)),
        refusal=ANSWER_SHEET,
    ),
)

LEGITIMATE = (
    Case(
        "fixed-names-in-the-clone-s-excludes",
        ("init", "upgrade", "uninstall"),
        exclude=("CLAUDE.md", "AGENTS.md"),
    ),
    # Not `uninstall`: it refuses to remove a file at an ignored place a `[paths]` value chose,
    # by design, and names the remedy (take the key out); `test_ignored.py` holds that.
    Case(
        "a-new-file-at-an-ignored-place",
        ("init", "upgrade"),
        paths={"agents_md": "private/AGENTS.md"},
        ignore=("private/",),
    ),
    Case(
        "artifacts-kept-out-of-git",
        ("init", "upgrade", "uninstall"),
        local=("claude-md", "roadmap"),
    ),
    # Its own guard is that planning reads no disk for a place this configuration never uses;
    # breaking it means putting `contained()` back into the trail's target, an edit of several
    # lines, so its entry is the engine refusing every recorded artifact, shared with the others.
    Case(
        "a-symlinked-directory-no-value-uses",
        ("init", "upgrade", "uninstall"),
        paths=MOVED_OFF_DOCS,
        links={"docs": "planning"},
    ),
    Case(
        "a-tracked-file-matching-an-ignore-pattern",
        ("init", "upgrade", "uninstall"),
        paths={"agents_md": "notes/AGENTS.md"},
        ignore=("notes/",),
        plant={"notes/AGENTS.md": "# Our notes\n"},
        track=("notes/AGENTS.md",),
    ),
    Case(
        "an-adopted-project",
        ("init", "upgrade", "uninstall"),
    ),
    # The user the ignore guard exempts on purpose: a person who keeps `stayfixed.toml` out of git
    # is not refused.
    Case(
        "an-adopted-project-with-its-config-in-the-clone-s-excludes",
        ("init", "upgrade", "uninstall"),
        exclude=(CONFIG_FILE,),
    ),
    # Every answer given, on a clone with no `stayfixed.toml`: the document `init` writes from
    # them, the files kept out of git included, is one `upgrade` and `uninstall` finish on.
    Case(
        "answers-on-a-fresh-clone",
        ("init", "upgrade", "uninstall"),
        written=False,
        given=Given(
            name="widget",
            base_branch="main",
            agents=("claude", "codex"),
            profile="",
            memory_mode="local-only",
            local=LOCAL_ELIGIBLE,
        ),
    ),
)


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One repository per module, copied per case: a `git init` per case was most of the run."""
    return repository(tmp_path_factory.mktemp("template"))


def _run(
    command: Literal["init", "upgrade", "uninstall"],
    root: Path,
    tmp_path: Path,
    *,
    dry_run: bool = False,
    given: Given = NO_ANSWERS,
) -> Report:
    machine = tmp_path / "absent.toml"
    if command == "init":
        return init(
            root,
            machine=machine,
            runner=LsRemote(),
            yes=True,
            dry_run=dry_run,
            ci=False,
            given=given,
        )
    if command == "upgrade":
        return upgrade(root, machine=machine, runner=LsRemote(), dry_run=dry_run, force=())
    return uninstall(root, machine=machine, dry_run=dry_run, force=(), runner=Recorder())


def _refusals(report: Report) -> list[str]:
    """The refusals a call returned in its report rather than raised, when the report says it
    refused (`refused`, the one predicate the CLI's exit code reads too)."""
    if not report.refused:
        return []
    plans = (
        (report.footprint,)
        if isinstance(report, UpgradeReport)
        else (report.footprint, report.once)
    )
    return [f"{r.artifact_id} {r.target}: {r.reason}" for p in plans for r in p.refusals]


def _outcome(
    command: Command, root: Path, tmp_path: Path, given: Given = NO_ANSWERS
) -> list[str] | None:
    """`None` when the command finished; its refusals, raised or returned, otherwise."""
    try:
        report = _run(command, root, tmp_path, given=given)
    except Refusal as refused:
        return [str(refused)]
    return _refusals(report) if report.refused else None


def _surround(root: Path, case: Case) -> None:
    """What the clone and the person hold around the configuration: ignore rules, excludes,
    planted hidden files, symlinks, force-tracked files."""
    if case.ignore:
        gitignore = root / ".gitignore"
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        gitignore.write_text(existing + "".join(f"{line}\n" for line in case.ignore))
    if case.exclude:
        exclude = root / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("".join(f"{line}\n" for line in case.exclude))
    (root / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "hooks" / "pre-commit").write_text(HOOK)
    for relative, text in case.plant.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if CLAUDE_COPY in case.keep and not (root / CLAUDE_COPY_FOLDED).exists():
        # The case-folded spelling as a file of its own where case does not fold, so a row about
        # it is a row on either filesystem; where case folds it already is the copy.
        shutil.copyfile(root / CLAUDE_COPY, root / CLAUDE_COPY_FOLDED)
    for name, target in case.links.items():
        (root / target).mkdir(parents=True, exist_ok=True)
        (root / name).symlink_to(target, target_is_directory=True)
    for relative in case.track:
        git(root, "add", "-f", "--", relative)


def _git_files(root: Path) -> set[str]:
    """Every file under `.git/` but git's own index and locks.

    The whole directory and not `tests/snapshot.py`'s stable subset, because a write creating a
    file anywhere under `.git/` is what this module has to see. None of these commands runs a
    `git` that writes objects or starts maintenance, so nothing else races the walk.
    """
    git_dir = root / ".git"
    return {
        p.relative_to(git_dir).as_posix()
        for p in git_dir.rglob("*")
        if p.is_file() and p.name != "index" and not p.name.endswith(".lock")
    }


def _hidden(root: Path, case: Case, command: Command) -> dict[str, bytes]:
    held = {".git/hooks/pre-commit", *case.plant} - set(case.track)
    if command != "uninstall" and case.keep:
        held |= {*case.keep, CLAUDE_COPY_FOLDED} if CLAUDE_COPY in case.keep else set(case.keep)
    return {relative: (root / relative).read_bytes() for relative in held}


def _assert_invariant(
    root: Path,
    tmp_path: Path,
    hidden: Mapping[str, bytes],
    git_before: set[str],
    *,
    finished: Command | None,
) -> None:
    clobbered = {
        relative
        for relative, data in hidden.items()
        if not (root / relative).is_file() or (root / relative).read_bytes() != data
    }
    assert clobbered == set(), f"I1: hidden files changed or removed: {sorted(clobbered)}"
    appeared = _git_files(root) - git_before
    assert appeared == set(), f"I1: files appeared under .git/: {sorted(appeared)}"
    if finished == "uninstall":
        with pytest.raises(Refusal) as again:
            _run("uninstall", root, tmp_path, dry_run=True)
        assert str(again.value) == NOTHING, f"I3: a finished uninstall left: {again.value}"
        assert not (root / STAYFIXED_DIRECTORY).exists(), "I3: a finished uninstall left .stayfixed"
    elif finished is not None:
        try:
            report = upgrade(
                root, machine=tmp_path / "absent.toml", runner=LsRemote(), dry_run=True, force=()
            )
        except Refusal as refused:
            pytest.fail(f"I3: a dry-run upgrade after a finished {finished} refused: {refused}")
        planned = [(a.artifact_id, str(a.verb), a.target) for a in report.footprint.actions]
        assert planned == [], f"I3: a finished {finished} left work for the next upgrade: {planned}"
        assert _refusals(report) == [], f"I3: after a finished {finished}: {_refusals(report)}"


@needs_git
@pytest.mark.parametrize(
    ("case", "command"),
    [
        pytest.param(case, command, id=f"{case.name}-{command}")
        for case in HOSTILE
        for command in case.commands
    ],
)
def test_no_hostile_input_reaches_a_file_git_hides(
    template: Path, tmp_path: Path, case: Case, command: Command
) -> None:
    """I1 and I3 for every hostile case, at every command that meets it; a refusal passes as
    long as it wrote nothing hidden. At `init` the hostile configuration is there from the
    start, as in a fresh clone; at `upgrade` and `uninstall` a pull brings it into a tree `init`
    already set up."""
    root = tmp_path / "widget"
    shutil.copytree(template, root, symlinks=True)
    if command == "init":
        (root / CONFIG_FILE).write_text(case.document(with_paths=True))
        _surround(root, case)
    else:
        (root / CONFIG_FILE).write_text(case.document(with_paths=False))
        assert _outcome("init", root, tmp_path) is None
        _surround(root, case)
        (root / CONFIG_FILE).write_text(case.document(with_paths=True))
        if case.forge is not None:
            case.forge(root)
    hidden = _hidden(root, case, command)
    git_before = _git_files(root)
    refused = _outcome(command, root, tmp_path, case.given)
    if case.refusal is not None:
        # Without it the answers row passes on the ignore guard's refusal of `.env` alone.
        assert refused == [case.refusal], refused
    finished = command if refused is None else None
    _assert_invariant(root, tmp_path, hidden, git_before, finished=finished)


@needs_git
@pytest.mark.parametrize("case", [pytest.param(c, id=c.name) for c in LEGITIMATE])
def test_the_legitimate_user_runs_every_command_to_the_end(
    template: Path, tmp_path: Path, case: Case
) -> None:
    """I2, with I1 and I3 after each step: every command the case lists finishes."""
    root = tmp_path / "widget"
    shutil.copytree(template, root, symlinks=True)
    if case.written:
        (root / CONFIG_FILE).write_text(case.document(with_paths=True))
    _surround(root, case)
    for command in case.commands:
        hidden = _hidden(root, case, command)
        git_before = _git_files(root)
        refused = _outcome(command, root, tmp_path, case.given)
        assert refused is None, f"I2: {command} refused a legitimate configuration: {refused}"
        _assert_invariant(root, tmp_path, hidden, git_before, finished=command)
