"""One invariant for `init`, asked of every hostile input at once.

A write must never land on a file whose bytes the committer does not control and git does not
show. The inputs that could aim one are repository-authored: the committed `stayfixed.toml`
(`[paths]`); and the answers a person passes as flags, which `precheck`
keeps off any committed document. Each hostile case below is one such input, met by `init` on a
fresh clone.

- **I1, nothing hidden is clobbered.** After `init`, finished or refused, each file the case
  planted where git does not show it — an ignored file, a file under `.git/`, stayfixed's
  out-of-git state — is present with its bytes, and no file has appeared under `.git/`.
- **I2, the legitimate user is not refused.** The legitimate cases run `init` to the end: no
  `Refusal` raised, and no refusal returned in the report's plans, which is the other way a
  command refuses.
- **I3, the end state is consistent.** After a finished `init`, the footprint planned again over
  the same tree plans nothing but what it skips and refuses nothing: every artifact the
  configuration builds is at its own place with its own bytes, or is a file stayfixed did not
  write, left and named.

Mutations (declared): each guard of the class put back one at a time — the shared `.git`
predicate and its case folding, the `.stayfixed` reservation, the collision rule's ownership
checks — and guards made to refuse more than they should, which the legitimate cases catch. An
entry names every row it reddens; a row no single line can redden says so where it is declared.

What this module does not cover: guards that decide nothing about a hidden file's bytes, such
as the attach refusal, which their own modules hold.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, load, read_document
from stayfixed.errors import Refusal
from stayfixed.project.init import ANSWER_SHEET, NO_ANSWERS, Given, InitReport, init
from stayfixed.project.templates import project_templates
from stayfixed.scaffold import Verb, plan
from tests.gitfixture import git, needs_git
from tests.project.repos import DOCUMENT, MOVED_OFF_DOCS, repository

# Bytes no stayfixed build renders: a person's file, or a tool's.
FOREIGN = "bytes a person or another tool wrote\n"
# A file in the directory stayfixed reserves for state git never sees.
LOCAL_STATE = ".stayfixed/local/state.json"
HOOK = "#!/bin/sh\n# the clone's own pre-commit hook\n"


@dataclass(frozen=True)
class Case:
    """One configuration of repository-authored inputs, and what git hides around it."""

    name: str
    paths: Mapping[str, str] = field(default_factory=dict)
    ignore: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    # Hidden files the case plants, root-relative, with their text: held to I1 unless tracked.
    plant: Mapping[str, str] = field(default_factory=dict)
    links: Mapping[str, str] = field(default_factory=dict)
    track: tuple[str, ...] = ()
    # The answers `init` is given as flags; `NO_ANSWERS` is `--yes` alone.
    given: Given = NO_ANSWERS
    # Whether the clone commits the case's `stayfixed.toml`; a fresh clone has none.
    written: bool = True
    # The one refusal a hostile case must meet, where another guard would also refuse it and so
    # hide the one the row is about.
    refusal: str | None = None

    def document(self, *, with_paths: bool) -> str:
        text = DOCUMENT
        if with_paths and self.paths:
            text += "\n[paths]\n" + "".join(f'{k} = "{v}"\n' for k, v in self.paths.items())
        return text


HOSTILE = (
    # A whole file stayfixed did not write is never written over: the roadmap at an existing
    # ignored file is skipped and named.
    Case(
        "roadmap-onto-an-ignored-file",
        paths={"roadmap": ".env"},
        ignore=(".env",),
        plant={".env": FOREIGN},
    ),
    Case(
        "roadmap-onto-git-s-hook",
        paths={"roadmap": ".git/hooks/pre-commit"},
    ),
    Case(
        "roadmap-onto-git-s-hook-case-folded",
        paths={"roadmap": ".GIT/hooks/pre-commit"},
    ),
    # A file git does not have yet: the only way to see a write that creates one under `.git/`.
    Case(
        "a-new-file-under-git",
        paths={"roadmap": ".git/info/attributes"},
    ),
    # Held by two layers — `contained()`'s symlink check and the write walk's `O_NOFOLLOW` — so
    # no single line reddens it: it pins that the two never go at once.
    Case(
        "roadmap-onto-git-s-hook-through-a-symlink",
        paths={"roadmap": "gitlink/hooks/pre-commit"},
        links={"gitlink": ".git"},
    ),
    Case(
        "roadmap-onto-a-local-state-file",
        paths={"roadmap": LOCAL_STATE},
        plant={LOCAL_STATE: FOREIGN},
    ),
    Case(
        "roadmap-onto-a-local-state-file-case-folded",
        paths={"roadmap": LOCAL_STATE.replace(".stayfixed", ".STAYFIXED")},
        plant={LOCAL_STATE: FOREIGN},
    ),
    # The same two layers as the `.git` symlink.
    Case(
        "roadmap-onto-a-local-state-file-through-a-symlink",
        paths={"roadmap": "hidden/state.json"},
        plant={LOCAL_STATE: FOREIGN},
        links={"hidden": ".stayfixed/local"},
    ),
    # `roadmap` placed at the bug index spelled in another case: one file where case folds, an
    # existing file stayfixed did not write where it does not. Either way the collision must be
    # refused, or one artifact is never written and a second plan still has work to do.
    Case(
        "a-paths-value-at-another-artifact-s-file-case-folded",
        paths={"roadmap": "docs/Bug-Reports.md"},
        plant={"docs/Bug-Reports.md": FOREIGN},
    ),
    # Answers over a document the clone committed would rewrite what the committer chose; they
    # are refused before anything is read beyond the root.
    Case(
        "answers-over-a-committed-document",
        paths={"roadmap": ".env"},
        ignore=(".env",),
        plant={".env": FOREIGN},
        given=Given(memory_mode="local-only"),
        refusal=ANSWER_SHEET,
    ),
)

LEGITIMATE = (
    Case(
        "a-new-file-at-an-ignored-place",
        paths={"roadmap": "private/roadmap.md"},
        ignore=("private/",),
    ),
    # Its own guard is that planning reads no disk for a place this configuration never uses;
    # breaking it means putting `contained()` back into the trail's target, an edit of several
    # lines, so its entry is the engine refusing every recorded artifact, shared with the others.
    Case(
        "a-symlinked-directory-no-value-uses",
        paths=MOVED_OFF_DOCS,
        links={"docs": "planning"},
    ),
    Case("an-adopted-project"),
    # A person who keeps `stayfixed.toml` out of git is not refused.
    Case(
        "an-adopted-project-with-its-config-in-the-clone-s-excludes",
        exclude=(CONFIG_FILE,),
    ),
    # Every answer given, on a clone with no `stayfixed.toml`: the document `init` writes from
    # them is one `init` finishes on.
    Case(
        "answers-on-a-fresh-clone",
        written=False,
        given=Given(
            name="widget",
            base_branch="main",
            agents=("claude", "codex"),
            profile="",
            memory_mode="local-only",
        ),
    ),
)


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One repository per module, copied per case: a `git init` per case was most of the run."""
    return repository(tmp_path_factory.mktemp("template"))


def _run(root: Path, tmp_path: Path, *, given: Given = NO_ANSWERS) -> InitReport:
    return init(root, machine=tmp_path / "absent.toml", yes=True, dry_run=False, given=given)


def _refusals(report: InitReport) -> list[str]:
    """The refusals a call returned in its report rather than raised, when the report says it
    refused (`refused`, the one predicate the CLI's exit code reads too)."""
    if not report.refused:
        return []
    plans = (report.footprint, report.once)
    return [f"{r.artifact_id} {r.target}: {r.reason}" for p in plans for r in p.refusals]


def _outcome(root: Path, tmp_path: Path, given: Given = NO_ANSWERS) -> list[str] | None:
    """`None` when `init` finished; its refusals, raised or returned, otherwise."""
    try:
        report = _run(root, tmp_path, given=given)
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
    for name, target in case.links.items():
        (root / target).mkdir(parents=True, exist_ok=True)
        (root / name).symlink_to(target, target_is_directory=True)
    for relative in case.track:
        git(root, "add", "-f", "--", relative)


def _git_files(root: Path) -> set[str]:
    """Every file under `.git/` but git's own index and locks.

    The whole directory and not `tests/snapshot.py`'s stable subset, because a write creating a
    file anywhere under `.git/` is what this module has to see. `init` runs no `git` that writes
    objects or starts maintenance, so nothing else races the walk.
    """
    git_dir = root / ".git"
    return {
        p.relative_to(git_dir).as_posix()
        for p in git_dir.rglob("*")
        if p.is_file() and p.name != "index" and not p.name.endswith(".lock")
    }


def _hidden(root: Path, case: Case) -> dict[str, bytes]:
    held = {".git/hooks/pre-commit", *case.plant} - set(case.track)
    return {relative: (root / relative).read_bytes() for relative in held}


def _assert_invariant(
    root: Path, tmp_path: Path, hidden: Mapping[str, bytes], git_before: set[str], *, finished: bool
) -> None:
    clobbered = {
        relative
        for relative, data in hidden.items()
        if not (root / relative).is_file() or (root / relative).read_bytes() != data
    }
    assert clobbered == set(), f"I1: hidden files changed or removed: {sorted(clobbered)}"
    appeared = _git_files(root) - git_before
    assert appeared == set(), f"I1: files appeared under .git/: {sorted(appeared)}"
    if not finished:
        return
    document = read_document(root) or ""
    config = load(root, machine=tmp_path / "absent.toml")
    try:
        planned = plan(root, config, project_templates(config, document=document).footprint)
    except Refusal as refused:
        pytest.fail(f"I3: planning again after a finished init refused: {refused}")
    # A whole file stayfixed did not write is skipped and named on every run, by design.
    actions = [
        (a.artifact_id, str(a.verb), a.target)
        for a in planned.actions
        if a.verb is not Verb.SKIP_MODIFIED
    ]
    assert actions == [], f"I3: a finished init left work for a second plan: {actions}"
    refusals = [f"{r.artifact_id} {r.target}: {r.reason}" for r in planned.refusals]
    assert refusals == [], f"I3: after a finished init: {refusals}"


@needs_git
@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c.name}-init") for c in HOSTILE])
def test_no_hostile_input_reaches_a_file_git_hides(
    template: Path, tmp_path: Path, case: Case
) -> None:
    """I1 and I3 for every hostile case; a refusal passes as long as it wrote nothing hidden. The
    hostile configuration is there from the start, as in a fresh clone."""
    root = tmp_path / "widget"
    shutil.copytree(template, root, symlinks=True)
    (root / CONFIG_FILE).write_text(case.document(with_paths=True))
    _surround(root, case)
    hidden = _hidden(root, case)
    git_before = _git_files(root)
    refused = _outcome(root, tmp_path, case.given)
    if case.refusal is not None:
        # Without it the answers row would pass on another guard's refusal alone.
        assert refused == [case.refusal], refused
    _assert_invariant(root, tmp_path, hidden, git_before, finished=refused is None)


@needs_git
@pytest.mark.parametrize("case", [pytest.param(c, id=c.name) for c in LEGITIMATE])
def test_the_legitimate_user_runs_every_command_to_the_end(
    template: Path, tmp_path: Path, case: Case
) -> None:
    """I2, with I1 and I3 after it: `init` finishes."""
    root = tmp_path / "widget"
    shutil.copytree(template, root, symlinks=True)
    if case.written:
        (root / CONFIG_FILE).write_text(case.document(with_paths=True))
    _surround(root, case)
    hidden = _hidden(root, case)
    git_before = _git_files(root)
    refused = _outcome(root, tmp_path, case.given)
    assert refused is None, f"I2: init refused a legitimate configuration: {refused}"
    _assert_invariant(root, tmp_path, hidden, git_before, finished=True)
