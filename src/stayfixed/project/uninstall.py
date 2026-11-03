"""`stayfixed uninstall`: `upgrade`'s rule run backwards.

Every artifact the manifest records is retired: one this build still produces with its own
template, one it no longer produces at a recorded target `Prepared.could_write` lists for its id.
`[artifacts] local` artifacts are never recorded and are retired by
id. The engine then removes a whole file while its bytes are stayfixed's, takes a region out of a
file (and the file, if nothing else was in it), and leaves anything else in place and listed.
`--force PATH` takes a listed file anyway. Records naming an id this build does not produce, or a
target it could not have written, are counted and never touched.

**A region leaves as a region.** A record this build no longer produces is judged against a
whole-file stub, which names no region, so `retired_templates` never retires a record whose kind
says it lived inside a host file: it is counted as an orphan, by the one rule `upgrade` applies
too. A region comes out only through the template this build produces for it.

**What anchors a removal, and what a commit can move.** Which artifact ids exist, which targets
each could have, and every region's name are this build's: constants in the installed package
that no repository can extend. The `[paths]` value a target is built from, and the digest a record
carries, come from committed files. So a commit can have this command remove only a whole file
whose exact bytes the same commit records, or the region a template of this build names, and its
diff shows the `[paths]` edit and the record. The kind a record carries is committed too, and all
it can do here is turn a removal into an orphan. Nothing committed reaches `.git/` or
`.stayfixed/`: the loader refuses a `[paths]` value inside either, and the manifest is read through
`contained()`, so a symlinked `.stayfixed/` is a refusal. Nor is a file git ignores at a place a
`[paths]` value chose: `ignored.refuse_ignored` refuses the run before any write when git ignores
an existing file there that a plan would remove or rewrite, `.stayfixed/local/artifacts/` excepted,
and says to take the key out, after which the file is left and listed. That is the whole
boundary, and why `docs/cli.md` says to run it on a checkout you trust.

**Two passes, footprint first.** `AGENTS.md` holds the write-once skeleton and the footprint's
`harness` region. Once the region is out, an untouched skeleton is byte-identical to the one
recorded, and the write-once pass removes it. The dry run judges the skeleton with its region still
in, and `ORDER_NOTE` says so. `--force` never reaches the write-once pass at a path the footprint
pass also targets: forcing `AGENTS.md` forces stayfixed's region out of it, and the skeleton, with
whatever a person wrote into it, is then judged on its own bytes.

**The ignore region last, and only over nothing.** The footprint's `.gitignore` region is the
only thing keeping `.stayfixed/local/` out of git, so it is taken out in a third pass, after the
disk shows nothing left under `.stayfixed/local/`. If something is left, the run stops before that
pass, with the region and the manifest in place, so git still ignores the files, and once they
are moved out the next run can finish (`KEPT_AFTER`).

**Directories as each pass goes, then `stayfixed.toml`, then the ledger.** Every directory above
a file a pass removed goes once it is empty, when the pass ends or stops (`_apply`), and no other:
a `[paths]` value is committed, so a directory it merely names may be a person's. Then
`stayfixed.toml`, whose removal the write-once pass holds back for this point, then
`.stayfixed/assessment.json`, the manifest, and `.stayfixed/` once it is empty. So a run stopped at
any earlier point leaves the configuration and the manifest the next run needs to finish it. A
process killed mid-pass can leave an empty directory behind, which no later run removes.

**An attached repository is detached first.** `attach`'s ledger, which records what it placed,
the overlay's plugin and the allow rules among it, lives under `.stayfixed/local/` in the main
checkout, and taking it with the scaffold would leave nothing to withdraw them by. Attached means
the ledger and the render `attach` writes for the binding id, outside the work tree and removed by
`detach`, which the id outlives: a ledger a clone commits, before an attach or after a `detach`,
is a file this run would not remove, and is refused below.
So once every refusal below has been asked, and before this run's first write, it runs `detach`,
which takes back exactly what the ledger records and the ledger with it; a dry run says it would.
A `detach` that refuses or stops part-way stops this run with nothing of its own done. While the
render is there the next run finishes; once it is gone, after a `detach` stopped past it or an
`attach` stopped before it, the ledger is counted below: `stayfixed detach`, then `uninstall`.

**One refusal comes before any write**: while `.stayfixed/local/` holds a file this run would not
remove, the local-only memory notes above all, `attach`'s ledger aside, which `detach` takes.
That count is a prediction from the plans: a file goes only when an action unlinks it, or when
a region's removal leaves exactly what the write-once pass then removes, which the engine's own
rule for a file kept out of git (`ours_locally`, asked of each file `local_copies` names) answers
before anything is written. An edited region, or a skeleton a person wrote into that shares the
region's file, keeps the file, so the run refuses before it writes rather than part-way. The check
above stays as the fact behind the prediction. It counts and never names a path, and a dry run
reports it instead of refusing, even when a plan refuses, so the report that lists an edited
local artifact is still printed.

**The engine's ledger of what it wrote under `.stayfixed/local/artifacts/`** (`LOCAL_DIGESTS`) is
stayfixed's own and is never counted. It goes after the write-once pass, once nothing else is left
under `.stayfixed/local/`, and before the ignore block. Every artifact it records is judged, so a
copy left behind when its id left `[artifacts] local` goes while its bytes are stayfixed's, and is
listed `skip_modified` otherwise, where `--force` with its path reaches it.

**A refusal while writing is not a refusal before it.** The engine keeps what it applied, and
records it, when a later write or removal fails; so does this command across its passes. Exit 2
then means "stopped part-way": what was done is on disk and in the manifest, and running the
command again re-plans from there to the end. `stayfixed.toml` is still there, since it goes last,
unless the last pass removed it and then could not write the manifest; that state is the next
paragraph's, and restoring the file finishes it.

**Without `stayfixed.toml`, nothing can be judged.** While the manifest still records the file
(`CONFIG_ARTIFACT`), either something other than this command took it, a person deleting it above
all, or a run of this command removed it inside `apply` and then never wrote the manifest: it was
killed in between, or the manifest write itself failed (`Manifest.write` raising in `apply`'s
`finally`). `apply` otherwise drops the record with the file, and writes the manifest even when a
later action refuses. Going on would drop the manifest and leave every recorded file untracked for
good, so the run refuses before any write and says to restore the file (`DELETED_CONFIG`), which is
the remedy in both cases: a restored file is judged like any other, and the next run converges. With
no such record, either a run stopped after removing it and before the manifest, or the file was the
project's own and never recorded; then the ledger goes, every recorded file stays, and the note
gives their count, so the next run converges instead of refusing for ever. No directory is pruned on
that path: nothing says where this configuration put its artifacts, and a target the manifest
records is a committed string.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from stayfixed import fsops
from stayfixed.binding import delivery_directory, main_checkout_or_none, read_id
from stayfixed.config.layout import ATTACH_LEDGER
from stayfixed.config.loader import loads, read_document
from stayfixed.config.owner import Owner
from stayfixed.config.paths import STAYFIXED_DIRECTORY, contained
from stayfixed.errors import Failure, Refusal
from stayfixed.fsops import path_key, remove_within, rmdir_within, said
from stayfixed.project.footprint import prepare
from stayfixed.project.templates import CONFIG_ARTIFACT, IGNORE_ARTIFACT
from stayfixed.runner import Runner
from stayfixed.scaffold import (
    LOCAL_ARTIFACTS,
    LOCAL_DIGESTS,
    LOCAL_ROOT,
    MANIFEST_PATH,
    Action,
    LocalDigests,
    Manifest,
    Plan,
    Template,
    Verb,
    apply,
    effective_target,
    ours_locally,
    unlinks,
)

NOTHING = (
    f"{MANIFEST_PATH} is not there; nothing records what stayfixed wrote here, so there is "
    "nothing to uninstall"
)
KEPT_LOCALLY = (
    f"{LOCAL_ROOT}/ holds {{count}} file(s) uninstall would not remove, and the ignore block it "
    "takes out is what keeps them out of git: local-only memory notes, or a file kept out of git "
    "that changed since stayfixed wrote it or that nothing records stayfixed writing. uninstall "
    "refuses until they are moved out of it; one the report lists skip_modified in a file of its "
    "own can instead be named with --force"
)
KEPT_AFTER = (
    f"{LOCAL_ROOT}/ still holds {{count}} file(s) after the other removals, so the ignore block "
    "that keeps them out of git and the manifest were left in place; move them out, then run "
    "uninstall again"
)
ORDER_NOTE = (
    "AGENTS.md is judged twice: the dry run sees the skeleton with stayfixed's region still in "
    "it and calls it edited, and the real run takes the region out first and judges what is left"
)
NO_CONFIG = (
    "stayfixed.toml is not there, so nothing the manifest records can be judged: those {count} "
    "file(s) stay where they are, and only the ledger goes"
)
# Fixed text. The manifest still records `stayfixed.toml`, so something other than this command's
# own removal took it (`apply` drops the record with the file), or a run removed it and then did
# not write the manifest (killed in between, or the manifest write failed); either way restoring
# it is the remedy, and git can usually give it back.
DELETED_CONFIG = (
    "stayfixed.toml is not there while .stayfixed/manifest.json still records it; without it "
    "nothing the manifest records can be judged, and going on would leave those files untracked "
    "for good, so nothing was removed. Restore stayfixed.toml (from git, for instance), then run "
    "uninstall again"
)
# Fixed text: a `stayfixed.toml` a person wrote before `init` is recorded nowhere, so no report
# line names it, and it stays with the version `init` added and whatever the adoption wrote.
KEPT_CONFIG = (
    "stayfixed.toml was yours before `stayfixed init`, so it is left as it is, with the keys "
    "stayfixed wrote into it; delete it by hand if you want it gone"
)
ASSESSMENT = f"{STAYFIXED_DIRECTORY}/assessment.json"
LEDGER_DIRS = (LOCAL_ROOT, STAYFIXED_DIRECTORY)


@dataclass(frozen=True)
class UninstallReport:
    footprint: Plan
    once: Plan
    orphans: int
    dry_run: bool
    note: str
    kept_locally: int
    # `stayfixed.toml` is one a person wrote, which no record names and nothing here removes.
    kept_config: bool = False
    # The repository was attached, and this run detached it first, or a dry run would have.
    detached: bool = False

    @property
    def refused(self) -> bool:
        """Whether either plan refused an artifact: the other way than a raised `Refusal` that
        this command refuses, with nothing removed."""
        return bool(self.footprint.refusals or self.once.refusals)


def _retire(templates: Sequence[Template], ids: Set[str]) -> tuple[Template, ...]:
    return tuple(replace(t, retired=True) for t in templates if t.id in ids)


def _kept_locally(root: Path, removing: Set[str]) -> int:
    """How many files under `LOCAL_ROOT` this run leaves behind: counted, never named.

    Exact names, not `fsops.path_key`: a file whose name only case-folds to one the run removes
    is, on a filesystem that does not fold case, a second file that stays, and counting it gone
    would take the ignore block out from over it. Counting too many only refuses the run.
    """
    base = contained(root, LOCAL_ROOT)
    kept = (p for p in base.rglob("*") if fsops.is_symlink(p) or not fsops.is_dir(p))
    return sum(1 for p in kept if f"{LOCAL_ROOT}/{p.relative_to(base).as_posix()}" not in removing)


def _rmdirs(root: Path, directories: Set[str]) -> None:
    """Remove each directory that is empty, deepest first; leave every other one.

    Each is asked only whether it is empty: `rmdir` refuses a directory with anything in it,
    which is the whole safety of the walk, and a refusal of any kind (`UnsafePath` is an
    `OSError`) leaves the directory where it is. A harness's own directory is never asked
    (`Harness.marker_dir`). It is the harness's before it is stayfixed's, and detection reads its
    presence, so an empty one stays whoever made it: nothing records whether a person or `init`
    did, and `docs/cli.md` says a later `init` detects the harness until it is removed. Compared
    through `fsops.path_key`: a `[paths]` value under `.Claude/` prunes `.claude/` itself where case
    folds, so a case variant of a marker directory is never asked either, on any filesystem.
    """
    from stayfixed.harnesses import HARNESSES

    marker_dirs = {path_key(harness.marker_dir) for harness in HARNESSES}
    for directory in sorted(directories, key=lambda d: d.count("/"), reverse=True):
        if path_key(directory) in marker_dirs:
            continue
        with contextlib.suppress(OSError):
            rmdir_within(root, directory)


def _prune(root: Path, removed: Sequence[str]) -> None:
    """Every directory above a file this run removed, once it is empty.

    Only those. It used to be every directory above every place this configuration puts an
    artifact, and a place is a committed `[paths]` value: `roadmap = "some/dir/x.md"` had the
    run remove an empty `some/dir/` a person made, a git-ignored placeholder included, though
    nothing of stayfixed's was ever in it. A directory above a file this run took held that file
    when the run began, so emptying it is this run's doing.
    """
    _rmdirs(
        root,
        {
            parent.as_posix()
            for target in removed
            for parent in PurePosixPath(target).parents
            if parent.as_posix() != "."
        },
    )


def _apply(root: Path, planned: Plan) -> None:
    """`apply`, then `_prune` over what it removed, whether or not it finished.

    In a `finally`, so a pass that stops part-way still empties the directories of the files it
    took: the run that finishes it cannot tell a directory an earlier run emptied from one a
    person left empty, so it would never prune one. What counts as removed is a file an action
    of this plan unlinks that was there before `apply` and is not after it. Both halves are
    needed: a relocation whose old file is already gone is still a `REMOVE` that unlinks nothing,
    and with a forged record and a committed `[paths]` value it named an empty `some/dir/x.md`
    whose absent file read as removed, so a directory a person made went with it.
    """
    unlinking = [a.target for a in planned.actions if unlinks(a)]
    present = [target for target in unlinking if os.path.lexists(root / target)]
    try:
        apply(root, planned)
    finally:
        _prune(root, [target for target in present if not os.path.lexists(root / target)])


def _remove_local_artifacts(root: Path) -> None:
    """The engine's ledger of what it wrote under `.stayfixed/local/artifacts/`, then every empty
    directory there, before the ignore block that keeps them out of git goes.

    Reached only once nothing but the ledger is left under `.stayfixed/local/`, so every directory
    under `LOCAL_ARTIFACTS` is empty or holds only empty ones. They are pruned whole, and not
    only above what this run removed, because the directory is stayfixed's own, which no `[paths]`
    value reaches, and an `upgrade` that moved an artifact out of it left its directories behind.
    A directory where the ledger belongs is not a file stayfixed wrote: it goes only if empty.
    """
    path = root / LOCAL_DIGESTS
    if not fsops.is_symlink(path) and fsops.is_dir(path):
        with contextlib.suppress(OSError):
            rmdir_within(root, LOCAL_DIGESTS)
    else:
        try:
            remove_within(root, LOCAL_DIGESTS)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise Refusal(f"{LOCAL_DIGESTS} cannot be removed ({said(exc)})") from exc
    base = contained(root, LOCAL_ARTIFACTS)
    if fsops.is_dir(base) and not fsops.is_symlink(base):
        below = (p for p in base.rglob("*") if fsops.is_dir(p) and not fsops.is_symlink(p))
        found = {f"{LOCAL_ARTIFACTS}/{p.relative_to(base).as_posix()}" for p in below}
        _rmdirs(root, {*found, LOCAL_ARTIFACTS})


def _remove_ledger(root: Path) -> None:
    """`.stayfixed/assessment.json`, the manifest last, then `.stayfixed/` once it is empty.

    A directory where a ledger file belongs is not a file stayfixed wrote; it is left where it is,
    and so is `.stayfixed/` around it, rather than refusing every later run before the manifest
    goes.
    """
    for target in (ASSESSMENT, MANIFEST_PATH.as_posix()):
        path = root / target
        # Whether it is a link first, so a link is never followed to answer: one into a directory
        # nobody may search would meet a fault there, and it is removed as a link either way.
        if not fsops.is_symlink(path) and fsops.is_dir(path):
            continue
        try:
            remove_within(root, target)
        except OSError as exc:
            raise Refusal(f"{target} cannot be removed ({said(exc)})") from exc
    _rmdirs(root, set(LEDGER_DIRS))


def _attached(root: Path) -> bool:
    """Whether `attach`'s ledger is in this checkout or the main one, where `attach` keeps it, and
    the render `attach` writes for the binding id is on this machine (the module docstring says
    why the render decides); a `git` that cannot name the main checkout leaves this one."""
    try:
        main = main_checkout_or_none(root) or root
    except Failure:
        main = root
    ledgered = any(fsops.is_file(contained(checkout, ATTACH_LEDGER)) for checkout in (root, main))
    binding_id = read_id(root) if ledgered else None
    try:
        return binding_id is not None and fsops.is_dir(delivery_directory(binding_id))
    except Failure:
        # A `HOME` that names no home holds no render.
        return False


def _detach(root: Path, runner: Runner) -> None:
    """`detach`, the attach area's, which withdraws what `attach` placed and takes its ledger."""
    from stayfixed.attach.api import detach

    detach(root, runner=runner)


def uninstall(
    root: Path,
    *,
    machine: Path | None,
    dry_run: bool,
    force: Sequence[str],
    runner: Runner,
    owner: Owner | None = None,
) -> UninstallReport:
    if not Manifest.present(root):
        raise Refusal(NOTHING)
    attached = _attached(root)
    manifest = Manifest.read(root)
    document = read_document(root)
    if document is None:
        if CONFIG_ARTIFACT in manifest.records:
            raise Refusal(DELETED_CONFIG)
        # Only the ledger: without the configuration nothing says where its artifacts were, and a
        # target the manifest records is a committed string. No run of this command reaches here
        # with directories it emptied, because `stayfixed.toml` goes after they are pruned.
        if not dry_run:
            if attached:
                _detach(root, runner)
            _remove_ledger(root)
        note = NO_CONFIG.format(count=len(manifest.records))
        return UninstallReport(
            footprint=Plan(),
            once=Plan(),
            orphans=0,
            dry_run=dry_run,
            note=note,
            kept_locally=0,
            detached=attached,
        )
    config = loads(document, root, machine=machine, owner=owner)
    # `removing`: every record `retired_templates` lists goes, and a profile artifact kept out of
    # git is not refused, so a configuration written before that rule can still be taken back.
    passes = prepare(
        root,
        config,
        manifest.records,
        document=document,
        removing=True,
    )
    orphans = passes.orphans
    digests = LocalDigests.read(root)
    # Retired: what the manifest records (every retirement `prepare` found among it), what
    # `[artifacts] local` keeps out of git, and every artifact the ledger says stayfixed wrote a
    # copy of kept out of git, since one whose id has left `[artifacts] local` is recorded nowhere
    # else.
    wanted = set(manifest.records) | set(config.artifacts.local) | digests.ids
    footprint_retired = _retire(passes.footprint, wanted)
    once_retired = _retire(passes.once, wanted)
    # `stayfixed.toml` goes last of all, after the ignore pass and the directories: while it and
    # the manifest are there, a run stopped at any earlier point is finished by the next one.
    once_body = [t for t in once_retired if t.id != CONFIG_ARTIFACT]
    config_retired = [t for t in once_retired if t.id == CONFIG_ARTIFACT]
    # Paths as the engine resolves them: an `[artifacts] local` target lives under
    # `.stayfixed/local/artifacts/`, which `Template.target` does not say.
    footprint_targets = {effective_target(t, config)[0] for t in footprint_retired}
    # And every copy an artifact left kept out of git at a place this configuration no longer
    # gives it, which the footprint pass judges: forced, it must not reach a skeleton sharing that
    # file either.
    footprint_targets |= {
        copy for t in footprint_retired for copy in passes.left_copies(t, digests)
    }
    once_force = tuple(path for path in force if path not in footprint_targets)
    # The later passes re-plan the same templates at the same targets, so these two plans name
    # every file the run can write or remove.
    footprint, once = passes.predict((footprint_retired, force), (once_retired, once_force))
    note = ORDER_NOTE if dry_run else ""
    # Before any write, how many files under `.stayfixed/local/` the run would leave. A file goes
    # only when an action unlinks it, or when a region's removal leaves the bytes the write-once
    # pass will then remove: the engine's own verdict for a file kept out of git, asked of those
    # bytes now. Only such a file matters here, since no `[paths]` value reaches `.stayfixed/`.
    local_once = {
        copy: template for template in once_body for copy in passes.local_copies(template, digests)
    }
    unlinked = {a.target for a in footprint.actions if _goes(a, local_once, digests)}
    unlinked |= {a.target for a in once.actions if unlinks(a)}
    # `attach`'s ledger is not counted where the repository is attached: `detach` takes it before
    # the first pass.
    detaching = {ATTACH_LEDGER} if attached else set()
    kept = _kept_locally(root, unlinked | {LOCAL_DIGESTS} | detaching)
    kept_config = CONFIG_ARTIFACT not in manifest.records
    report = UninstallReport(
        footprint=footprint,
        once=once,
        orphans=orphans,
        dry_run=dry_run,
        note=note,
        kept_locally=kept,
        kept_config=kept_config,
        detached=attached,
    )
    if report.refused:
        # Returned below before `detach`, and a real run would stop here too, so the report says
        # no detach ran or would run.
        report = replace(report, detached=False)
    if dry_run or report.refused:
        return report
    if kept:
        raise Refusal(KEPT_LOCALLY.format(count=kept))
    # Nothing either pass targets is a path `detach` writes or removes, so the plans above are
    # the ones applied below.
    if attached:
        _detach(root, runner)
    # The footprint plan without the ignore region, which goes last: nothing has been written
    # since it was made, and each action is one template's, so this is the plan a re-plan of the
    # other templates would give, and the plan reported is the one applied.
    body = _without(footprint, IGNORE_ARTIFACT)
    _apply(root, body)
    # Re-planned once the region is out of `AGENTS.md`, so an untouched skeleton is judged on the
    # bytes `init` recorded. The report carries the plans that ran, not the prediction above.
    judged = passes.replan(once_body, force=once_force)
    _apply(root, judged)
    # What is on disk now decides, not the prediction: while anything is left under
    # `.stayfixed/local/`, the ignore region stays, and so does the manifest that records it.
    left = _kept_locally(root, frozenset({LOCAL_DIGESTS}))
    if left:
        raise Refusal(KEPT_AFTER.format(count=left))
    _remove_local_artifacts(root)
    # The footprint's ignore region: what keeps `.stayfixed/local/` out of git, so it goes last.
    ignore_region = [t for t in footprint_retired if t.id == IGNORE_ARTIFACT]
    ignore = passes.replan(ignore_region, force=force)
    _apply(root, ignore)
    last = passes.replan(config_retired, force=once_force)
    _apply(root, last)
    _remove_ledger(root)
    return UninstallReport(
        footprint=_joined(body, ignore),
        once=_joined(judged, last),
        orphans=orphans,
        dry_run=dry_run,
        note=note,
        kept_locally=0,
        kept_config=kept_config,
        detached=attached,
    )


def _goes(action: Action, local_once: Mapping[str, Template], digests: LocalDigests) -> bool:
    """Whether the file `action` targets is gone once both passes ran: it unlinks it, or it takes
    a region out of a file kept out of git and leaves exactly what the write-once pass removes.
    A `REMOVE` with a payload keeps the file for the footprint pass, and a `SKIP_MODIFIED` keeps
    it for good. A forced path never reaches the write-once pass at such a target, so this is
    the whole of what that pass will do there."""
    if unlinks(action):
        return True
    template = local_once.get(action.target)
    return (
        action.verb is Verb.REMOVE
        and action.payload is not None
        and template is not None
        and ours_locally(template, action.payload, action.target, digests)
    )


def _without(planned: Plan, artifact_id: str) -> Plan:
    return Plan(
        actions=tuple(a for a in planned.actions if a.artifact_id != artifact_id),
        refusals=tuple(r for r in planned.refusals if r.artifact_id != artifact_id),
        unchanged=tuple(u for u in planned.unchanged if u != artifact_id),
    )


def _joined(first: Plan, second: Plan) -> Plan:
    return Plan(
        actions=(*first.actions, *second.actions),
        refusals=(*first.refusals, *second.refusals),
        unchanged=(*first.unchanged, *second.unchanged),
    )
