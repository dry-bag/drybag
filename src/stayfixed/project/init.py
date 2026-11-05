"""`stayfixed init --yes`: the footprint, written by the engine in two passes.

`stayfixed.toml` is a `Kind.ONCE` artifact in a pass of its own, and the bug index, the roadmap,
`trail.toml` and the `.gitignore` region are the second. Both are planned before either is
applied, so a refusal anywhere leaves nothing written and no manifest; the dry run reports both
plans and writes nothing.

A repository that already holds a `stayfixed.toml` and no manifest is adopted. One that holds a
manifest is refused: `init` writes a scaffold once.

**Adopted means read, not replaced.** `stayfixed.toml` is a `Kind.ONCE` artifact: created when
absent, never looked inside again. So on a repository that already carries one the engine
reports `skip_modified` — "create-once, and the file is already there" — and the file comes
back byte for byte but for one key. What the hand-written document does is decide the whole
run: it is parsed, merged under stayfixed's own `version` and the preset's defaults, and
validated by `loads` before a byte is written, and the `Config` that comes out is what every
target below is built from.

**The one key is a missing `[stayfixed] version`**, the only tool-owned key the loader
requires, with its `[stayfixed]` header when the file has none. It is added through
`config.owned.rewrite`, which keeps every other line, and the file is checked with `loads` as it
will then be on disk — before any write, dry run included — because the merged document drops
every `[stayfixed]` key it does not carry over, and
detects a name the file may lack, and so loads where the next command's `load` would not. The
other tool-owned keys are written only into a file stayfixed itself creates, which is the only
file whose header claims them.

**Every value in the document this writes is stayfixed's own, the repository's own answer read
back, or an answer a person gave as a flag.** The tool-owned keys are `config.owned.OWNED`;
everything else is copied from a `stayfixed.toml` a person wrote, or — where there is none —
taken from the answers `Given` carries, each held by the parser to its grammar or its choices,
or detected under `PROJECT_NAME`'s grammar, which is the one thing `detect` refuses outside of.
Answers never reach a document a person wrote: `precheck` refuses them over one. `loads` then
validates the whole document before a byte is written, so a bad path or a bad name costs the
run rather than the repository.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import stayfixed
from stayfixed import fsops
from stayfixed.config.loader import CONFIG_FILE, loads, read_document
from stayfixed.config.owned import rewrite
from stayfixed.config.owner import Owner
from stayfixed.config.paths import contained
from stayfixed.config.reading import UNPARSEABLE, toml_position
from stayfixed.config.schema import Config
from stayfixed.errors import Failure, Refusal
from stayfixed.fsops import said, write_within
from stayfixed.project.detect import CURRENT_BRANCH, DEFAULT_BRANCH, Detected, detect
from stayfixed.project.templates import project_templates
from stayfixed.scaffold import MANIFEST_PATH, Manifest, Plan, apply, plan
from stayfixed.tomlout import dumps

VERSION = ("stayfixed", "version")
USER_OWNED = ("paths", "memory", "budgets", "ledger", "commit_messages")
HEAD_KEYS = ("preset", "agents")
HEADER = (
    "# Written by `stayfixed init`. Every key you leave out takes the preset's default;\n"
    "# `[stayfixed] version` is stayfixed's to rewrite in place; every other key is yours.\n\n"
)
# The pair is spelled literally because the intended reader is an agent relaying this sentence,
# and `--dry-run` on its own is refused by this same refusal: "pass --yes, and --dry-run to read
# them first" reads as two alternatives, one of which does not work.
NEEDS_YES = (
    "`stayfixed init` writes only with --yes, which takes the defaults `stayfixed init "
    "--questions` shows; an answer flag such as --name changes one of them, and --dry-run "
    "beside --yes reads the plan first"
)
ALREADY = (
    f"{MANIFEST_PATH} exists, so this repository is initialised; `init` writes a scaffold once"
)
ANSWER_SHEET = (
    "this repository already has a stayfixed.toml, which answers the questions `init` would ask; "
    "edit it, then run `stayfixed init --yes --dry-run` with no answer flag to read the plan"
)
# The table is stayfixed's own vocabulary (`stayfixed`, `project` or one of `USER_OWNED`), and it
# is the only thing this names: the key that failed is exactly the text no grammar has bounded.
UNWRITABLE_KEY = (
    "stayfixed.toml's [{table}] table holds a key stayfixed cannot write back as a bare TOML key, "
    "so nothing was written; rename it to letters, digits, `_` and `-`"
)
# Fixed text: the branch `origin/HEAD` named is the remote's, outside the grammar, and not printed.
HEAD_DEFAULTED = (
    "origin/HEAD does not name a plain branch, so [project] base_branch is main; if pull "
    "requests merge into another branch, answer it with `stayfixed init --yes --base-branch "
    "BRANCH` while nothing is written, or set [project] base_branch in stayfixed.toml"
)
# Fixed text too, though the branch passed the grammar: one sentence whatever it is called.
HEAD_CURRENT = (
    "this repository has no remote, so [project] base_branch is the branch checked out now; if "
    "pull requests merge into another branch, answer it with `stayfixed init --yes --base-branch "
    "BRANCH` while nothing is written, or set [project] base_branch in stayfixed.toml"
)
# A remote with no `origin/HEAD`: a repository created here and pushed, to `origin` or to
# another remote. The branch checked out is not taken, since it is typically the feature branch
# the adoption is made on. The remedy names no remote but `origin`, the only one detection reads.
HEAD_UNRECORDED = (
    "this repository has a remote and no origin/HEAD recorded, so [project] base_branch is main; "
    "answer it with `stayfixed init --yes --base-branch BRANCH` while nothing is written, or set "
    "[project] base_branch in stayfixed.toml; where the remote is origin, `git remote set-head "
    "origin --auto` records its default branch for the next run"
)
# git gave no answer to `git remote`, so whether the branch checked out may be taken is not
# known: the default stands.
HEAD_REMOTES_UNKNOWN = (
    "git could not list this repository's remotes, so [project] base_branch is main; answer it "
    "with `stayfixed init --yes --base-branch BRANCH` while nothing is written, or set [project] "
    "base_branch in stayfixed.toml"
)


@dataclass(frozen=True)
class Given:
    """The answers a person gave as flags on `init --yes`; `None` is a question not answered.

    Each replaces one default in the document this run creates, and none reaches one a person
    wrote (`precheck`). The parser has held each to its grammar or its choices.
    """

    name: str | None = None
    base_branch: str | None = None
    agents: tuple[str, ...] | None = None
    memory_mode: str | None = None
    attribution_check: bool | None = None


NO_ANSWERS = Given()


@dataclass(frozen=True)
class InitReport:
    once: Plan
    footprint: Plan
    adopted: bool
    dry_run: bool
    # `HEAD_DEFAULTED` when the detected base branch replaced a remote head outside the grammar;
    # `HEAD_UNRECORDED` when it is the default because a remote is there and `origin/HEAD` is
    # not; `HEAD_REMOTES_UNKNOWN` when it is the default because git could not list the remotes;
    # `HEAD_CURRENT` when, with no remote at all, it is a checked-out branch other than `main`.
    head_note: str = ""
    # Whether this run's plan adds `[stayfixed] version` to a `stayfixed.toml` a person wrote. It
    # is written only by a run that is neither a dry run nor refused.
    stamped: bool = False
    # The configuration the run wrote or adopted, from which the command says what it picked.
    config: Config | None = None

    @property
    def refused(self) -> bool:
        """Whether either plan refused an artifact: the other way than a raised `Refusal` that
        this command refuses, with nothing written."""
        return bool(self.once.refusals or self.footprint.refusals)


def _existing(root: Path) -> tuple[str, dict[str, object]] | None:
    """The `stayfixed.toml` already in the repository, as its text and parsed, or `None`.

    Read through `read_document`, the loader's reader, so a symlinked file is a
    refusal and is never followed: a clone's link to `/dev/zero` would end the run by exhausting
    memory. Its refusals for a file that is not UTF-8 text or cannot be read are the loader's.
    A file that will not parse is a `Failure` naming the file and the position `tomllib`
    stopped at, and nothing else the parser had to say. `tomllib`'s own message embeds the
    source for several of its faults — a duplicate table or inline-table key is reported with
    the key in it, and a TOML key is arbitrary quoted text — so the exception is bounded by
    `config.reading.toml_position` before any of it prints. The file is `stayfixed.toml`, which
    on adoption is the repository's own document, read as its answers rather than replaced, and
    this refusal is one the `init` skill is instructed to relay and stop on.
    """
    text = read_document(root)
    if text is None:
        return None
    try:
        return text, tomllib.loads(text)
    except UNPARSEABLE as exc:
        raise Failure(f"{CONFIG_FILE} is not valid TOML {toml_position(exc)}") from None


def _tables(
    root: Path, existing: dict[str, object] | None, *, given: Given
) -> tuple[dict[str, dict[str, object]], str]:
    """The document's tables, in order: stayfixed's own `version`, then the repository's own
    answers or the ones `given` carries; and the note for a detected base branch no remote head
    named (`_head_note`), empty when `--base-branch` answers it.

    **Detection runs only when no `[project]` table answers for the repository**, and not merely
    when some key of the head is absent; **it is lenient when `--name` answers the name, the one
    value it refuses, or when an adopted file leaves it out**, which the loader then refuses
    with its own sentence. `detect` is the one call here that can refuse — a directory name or a
    remote's last segment outside `PROJECT_NAME` — and the remedy for that refusal is to answer it
    with `--name`, or to write `[project] name` into `stayfixed.toml` by hand and run `init` again.
    A branch that consulted `detect` for anything the preset can default would make that second
    remedy dead: the repository whose name cannot be guessed would go on being refused after doing
    exactly what it was told. Everything else the head does not carry — `preset` and
    `agents` — has a preset default, and the loader supplies it.

    `precheck` guarantees that `given` is `NO_ANSWERS` whenever `existing` carries tables, so
    the answers never overwrite a table a person wrote.
    """
    head: dict[str, object] = {"version": stayfixed.__version__}
    tables: dict[str, dict[str, object]] = {"stayfixed": head}
    old_head = existing.get("stayfixed") if existing else None
    if isinstance(old_head, dict):
        head.update({k: old_head[k] for k in HEAD_KEYS if k in old_head})
    if existing:
        for name in ("project", *USER_OWNED):
            table = existing.get(name)
            if isinstance(table, dict):
                tables[name] = dict(table)
    head_note = ""
    if "project" not in tables:
        # Lenient where something else answers the name: `--name`, or an adopted file, whose
        # missing `[project] name` is the loader's to refuse, since `--name` cannot reach it.
        found = detect(root, lenient=given.name is not None or existing is not None)
        head_note = _head_note(found) if given.base_branch is None else ""
        head.setdefault("agents", list(given.agents or found.agents))
        name = given.name or found.name
        branch = given.base_branch or found.base_branch
        tables["project"] = {"base_branch": branch}
        if name:
            tables["project"] = {"name": name, **tables["project"]}
    if given.memory_mode is not None:
        tables["memory"] = {"mode": given.memory_mode}
    commit_messages: dict[str, object] = {}
    if given.attribution_check is not None:
        commit_messages["attribution_check"] = given.attribution_check
    if commit_messages:
        tables["commit_messages"] = commit_messages
    return tables, head_note


def _head_note(found: Detected) -> str:
    """The note for a base branch that no remote head named: the default standing in for one
    outside the grammar, for an `origin/HEAD` a repository with a remote never recorded, or for
    remotes git could not list; or, with no remote at all, a checked-out branch other than
    `main`."""
    if found.head_refused:
        return HEAD_DEFAULTED
    if found.head_unrecorded:
        return HEAD_UNRECORDED
    if found.remotes_unknown:
        return HEAD_REMOTES_UNKNOWN
    if found.sources.get("base_branch") == CURRENT_BRANCH and found.base_branch != DEFAULT_BRANCH:
        return HEAD_CURRENT
    return ""


def _rendered(tables: dict[str, dict[str, object]]) -> str:
    """The document `loads` validates: `HEADER` and `tables`, rendered by `tomlout.dumps`.

    Every table but stayfixed's own head is copied out of a hand-written document, and `dumps`
    refuses a key it cannot write bare by quoting it (`{name!r}`). A TOML key is arbitrary quoted
    text, so that put repository bytes, ESC and all, into a refusal the `init` skill relays to a
    model, ahead of the loader's own count-only answer. Each table is therefore rendered alone
    first, and a refusal is re-raised naming the table and nothing the document wrote. Rendering
    a table raises only for a key: every value `tomllib` can parse, `dumps` can emit.
    """
    for name, table in tables.items():
        try:
            dumps({name: table})
        except Refusal:
            raise Refusal(UNWRITABLE_KEY.format(table=name)) from None
    return HEADER + dumps(tables)


def _as_on_disk(read: tuple[str, dict[str, object]] | None) -> tuple[str | None, bool]:
    """The adopted `stayfixed.toml` as every later command will load it, and whether this run
    writes its missing `[stayfixed] version`; `(None, False)` when this run creates the file.

    `read` is `_existing`'s answer, the text `read_document` gave, so this is the file the write
    will meet; one without a version then meets the key editor, which refuses a `[stayfixed]` it
    cannot extend: the refusals the write would meet, met while planning.
    """
    if read is None:
        return None, False
    text, existing = read
    head = existing.get("stayfixed")
    if isinstance(head, dict) and "version" in head:
        return text, False
    return rewrite(text, {VERSION: stayfixed.__version__}), True


def precheck(root: Path, *, answering: bool) -> None:
    """The refusals `init` and `init --questions` share, before anything beyond the root is read.

    A manifest means `init` has already run. While `answering` — the questions always are, and
    `init` is whenever an answer flag is given — a `stayfixed.toml` already answers every
    question, so asking them over it would collect answers that nothing writes.
    """
    if Manifest.present(root):
        raise Refusal(ALREADY)
    # `contained` and not a bare `is_file`, which follows a link: a symlinked `stayfixed.toml` is
    # refused as every command refuses it, whatever it points at, and not taken for an answer
    # sheet (a link to a file) or for no file at all (a link to `/dev/zero`).
    if answering and fsops.is_file(contained(root, CONFIG_FILE)):
        raise Refusal(ANSWER_SHEET)


def init(
    root: Path,
    *,
    machine: Path | None,
    yes: bool,
    dry_run: bool,
    given: Given = NO_ANSWERS,
    owner: Owner | None = None,
) -> InitReport:
    """Plan both passes, then apply both — or neither.

    The refusals come in one order and all of them above every write: no `--yes`, a manifest
    that says this repository is already initialised, an answer given over a `stayfixed.toml`
    the repository already has, a `stayfixed.toml` that is not TOML, a detected name outside the
    grammar that no `--name` answers, an adopted table holding a key that cannot be written
    back bare (`_rendered`), a `Config` the loader refuses, an adopted `stayfixed.toml` whose
    missing version the key editor cannot add or that the loader refuses as it will be on disk
    (`_as_on_disk`), an artifact at a file another is built to write, in either pass
    (`templates.Owners`), and finally a refusal in either plan, which is returned rather than
    raised so the report can name the artifact.

    `owner` is the owner's layer the command resolved, which every load here takes, so the machine
    file is read once and what it read past is said once (`config.loader.loads`' own).
    """
    if not yes:
        raise Refusal(NEEDS_YES)
    precheck(root, answering=given != NO_ANSWERS)
    read = _existing(root)
    existing = read[1] if read is not None else None
    tables, head_note = _tables(root, existing, given=given)
    document = _rendered(tables)
    config = loads(document, root, machine=machine, owner=owner)
    on_disk, stamped = _as_on_disk(read)
    if on_disk is not None:
        # What the next command loads is the file, not the merged document: that one drops
        # every `[stayfixed]` key it does not carry over, and detects a name the file may lack.
        loads(on_disk, root, machine=machine, owner=owner)
    prepared = project_templates(config, document=document)
    once = plan(root, config, prepared.once)
    footprint = plan(root, config, prepared.footprint)
    report = InitReport(
        once,
        footprint,
        existing is not None,
        dry_run,
        head_note,
        stamped,
        config,
    )
    if dry_run or report.refused:
        return report
    if stamped and on_disk is not None:
        # No manifest yet, so there is no record to re-stamp: only the one line is written.
        try:
            write_within(root, CONFIG_FILE, on_disk)
        except OSError as exc:
            raise Refusal(f"{CONFIG_FILE} cannot be written ({said(exc)})") from exc
    apply(root, once)
    apply(root, footprint)
    return report
