"""`stayfixed upgrade`: the scaffold refreshed against the running stayfixed.

Every refusal comes before every write.

1. A `stayfixed.toml` recording a newer stayfixed than the one running is refused: moving a project
   backward would repin an older release and put older bytes over newer ones. So is one whose
   version has no leading `X.Y.Z`, or shares the running one's and differs after it in a way
   `later` does not order, because its direction is unknown.
2. `[stayfixed] version` moves to the running version.
3. The footprint pass is re-planned by hash against the manifest; the write-once pass is not.
   An artifact this configuration no longer produces is retired only at a recorded target
   `Prepared.could_write` lists for its id. Every other record is an orphan, counted and left
   alone.

Written: the footprint, then `stayfixed.toml` through `rewrite_owned`, last. An interrupted run
leaves the document naming the old version, and the next run re-plans from there.

What anchors a write, and what does not. Which artifacts exist and which targets each could have
come from this build. The `[paths]` value a target is built from, and the digest a record carries,
come from committed files. For a whole file that means a commit can have this command rewrite it
only while it holds exactly the bytes the same commit records. `--force` aside: it overwrites a
whole file whatever it holds, one nothing records included, but only at a path the operator gave
exactly on the command line, which no commit can supply. A managed region is different: it is
inserted into whatever file its `[paths]` key names, recorded or not, so a commit that points
`agents_md` at a tracked file gets the region written into it, and the diff of both shows it. What
no committed value can reach is state git never sees: the loader refuses any `[paths]` value inside
git's control directory or stayfixed's own `.stayfixed/`, and `ignored.refuse_ignored` refuses the
whole run, before any write, when git ignores an existing file it would write or remove at a place a
`[paths]` value chose rather than the preset (`.stayfixed/local/artifacts/` exempt, which
`[artifacts] local` asks for). A fixed name or a preset's place no repository value chose, and a
file that is not there yet, are not refused. Outside a git work tree there is no diff to hide from,
and no such guard. That is why `docs/cli.md` says to run it on a checkout you trust.

What prints is bounded. `Moved.before` is the repository's own value, so a version outside
`X.Y.Z` prints as `(not a version)`. `Moved.after` is stayfixed's own: the running version.
`orphans` is a count, because the ids of records this build does not produce are
repository-authored.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import stayfixed
from stayfixed.config.loader import loads, read_document
from stayfixed.config.owned import Value, rewrite
from stayfixed.config.owner import Owner
from stayfixed.config.schema import Config
from stayfixed.errors import Refusal
from stayfixed.project.footprint import Passes, prepare
from stayfixed.project.rewrite import NO_DOCUMENT, rewrite_owned
from stayfixed.runner import Runner
from stayfixed.scaffold import MANIFEST_PATH, Manifest, Plan, apply
from stayfixed.semver import RELEASE, later

NOT_INITIALISED = (
    f"{MANIFEST_PATH} is not there, so there is no scaffold to upgrade; `stayfixed init` writes one"
)
# Fixed text: the recorded string is repository-authored and is never quoted.
UNREADABLE_VERSION = (
    "stayfixed.toml's [stayfixed] version does not begin with a version stayfixed can read "
    "(X.Y.Z), so which way upgrade would move it is unknown and nothing was written; set it to the "
    "stayfixed release this project was last upgraded with, then run `stayfixed upgrade` again"
)
# Fixed text with the running version, which is stayfixed's own; the recorded one is not quoted.
UNORDERED = (
    "stayfixed.toml's [stayfixed] version and the {running} running here share one X.Y.Z and "
    "differ after it, in a way stayfixed does not order (two pre-releases, or a post-release), "
    "so which way upgrade would move it is unknown and nothing was written; set it to {running} "
    "by hand if that is the release this project should move to, then run `stayfixed upgrade` "
    "again"
)
NEWER = (
    "stayfixed.toml records a newer stayfixed than the {running} running here, and upgrade never "
    "moves a project backward; update the stayfixed plugin, then run `stayfixed upgrade` with it"
)


@dataclass(frozen=True)
class Moved:
    # `(table, key)`, as `config.owned` names a tool-owned key.
    key: tuple[str, str]
    before: str
    after: str


@dataclass(frozen=True)
class UpgradeReport:
    footprint: Plan
    moved: tuple[Moved, ...]
    skipped: dict[str, str]
    orphans: int
    dry_run: bool

    @property
    def refused(self) -> bool:
        """Whether the plan refused an artifact: the other way than a raised `Refusal` that this
        command refuses, with nothing written."""
        return bool(self.footprint.refusals)


def _printable(value: str) -> str:
    return value if RELEASE.match(value) else "(not a version)"


def _footprint(
    root: Path,
    config: Config,
    text: str,
    force: Sequence[str],
) -> tuple[Passes, Plan]:
    """The footprint pass, predicted: the write-once pass is never planned here, and the
    ownership relation `predict` binds covers it too, so no ledger entry under a footprint id
    reaches a write-once artifact's copy kept out of git."""
    records = Manifest.read(root).records
    passes = prepare(root, config, records, document=text)
    (planned,) = passes.predict((passes.footprint, force))
    return passes, planned


def upgrade(
    root: Path,
    *,
    machine: Path | None,
    runner: Runner,
    dry_run: bool,
    force: Sequence[str],
    owner: Owner | None = None,
) -> UpgradeReport:
    """`owner` is the owner's layer the command resolved, which both loads take, so the machine
    file is read once and what it read past is said once (`config.loader.loads`' own)."""
    if not Manifest.present(root):
        raise Refusal(NOT_INITIALISED)
    text = read_document(root)
    if text is None:
        raise Refusal(NO_DOCUMENT)
    before = loads(text, root, machine=machine, owner=owner)
    running = stayfixed.__version__
    # Read by its leading `X.Y.Z`, so `1.0.0-rc1` is newer than `0.9.9` and not unknown, and a
    # release is newer than its own pre-release; a value with no leading `X.Y.Z` at all is
    # refused, and so is a pair `later` does not order, because moving either could be moving
    # it backward. `later(v, v)` is `None` exactly when `v` has no leading `X.Y.Z`.
    ahead = later(before.stayfixed.version, running)
    if ahead is None and later(before.stayfixed.version, before.stayfixed.version) is None:
        raise Refusal(UNREADABLE_VERSION)
    if ahead is None:
        raise Refusal(UNORDERED.format(running=running))
    if ahead:
        raise Refusal(NEWER.format(running=running))
    changes: dict[tuple[str, str], Value] = {("stayfixed", "version"): running}
    # The pure editor, to learn what the document would become before anything is written; the
    # one write of `stayfixed.toml` below still goes through `rewrite_owned`, which re-stamps the
    # `config` record with it. Not replaced by comparing the loaded version with `running`: the
    # editor refuses a `version` written in a shape it cannot rewrite, here, before any write.
    document = rewrite(text, changes)
    config = loads(document, root, machine=machine, owner=owner)
    passes, footprint = _footprint(root, config, text, force)
    moved = (
        (Moved(("stayfixed", "version"), _printable(before.stayfixed.version), running),)
        if before.stayfixed.version != config.stayfixed.version
        else ()
    )
    report = UpgradeReport(
        footprint,
        moved,
        passes.skipped,
        passes.orphans,
        dry_run,
    )
    if dry_run or report.refused:
        return report
    apply(root, footprint)
    rewrite_owned(root, changes)
    return report
