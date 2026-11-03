"""Decide, then write.

`plan` reads and decides; `apply` writes. The split is what makes `--dry-run` honest — the
report a user approves is produced by the same code path that then runs — and it is what makes
the containment rule testable without a filesystem full of traps.

Two rules are easy to state and easy to get backwards, so they are stated here once.

*An absent record does not mean "hands off" for every kind.* For a whole file it does: a file
stayfixed never wrote is somebody's. For a managed region and for keyed entries the file
belongs to somebody by definition, and an absent record is the ordinary first install — the
rules for regions and for keyed entries exist for exactly that case. The hand-edit oracle for
those two kinds is the region body and the marked entries, never the file around them.

*A refusal is an artifact's, not the plan's.* A file that cannot be read, a region whose markers
no longer say where it ends, a settings document that is not JSON: each is recorded in
`Plan.refusals` and the remaining templates are still decided. `plan` raises only for input no
per-artifact report could rescue — the configured profile, the manifest itself, and a malformed
`Template`, which is a bug in the caller that built it rather than a file a user can put right.
Both shapes of malformed `Template` raise, symmetrically: a managed region that names no
region, and keyed entries that name no entries. The second did not, and `entries or {}` turned
it into a silent uninstall of whatever the user had wired up.

*Containment is not a string check.* `contained()` decides whether a path may be written;
`fsops.open_within` decides what is actually written to, by walking the path with `O_NOFOLLOW`
and handing back a descriptor. A component can still become a symlink after `contained()` has
passed — that is the race this layer exists to survive — but it cannot redirect the write: the
walk fails the open rather than following the link, and the string is never resolved a second
time, not for the write and not for the parent directories, which `fsops.mkdirs_within`
creates one component at a time through the same walk rather than with `Path.mkdir`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence, Set
from pathlib import Path
from typing import Protocol

from stayfixed.config.paths import PathEscape, contained
from stayfixed.config.schema import PROJECT_NAME, Config
from stayfixed.errors import Refusal
from stayfixed.fsops import (
    UnsafePath,
    path_key,
    read_regular_text,
    remove_within,
    unreadable,
    write_within,
)
from stayfixed.printed import quoted
from stayfixed.scaffold.entries import ENTRY_MARKER, EntriesError, apply_entries, owned, unmarked
from stayfixed.scaffold.local import LOCAL_ARTIFACTS, LocalDigests
from stayfixed.scaffold.manifest import Kind, Location, Manifest, Record, digest
from stayfixed.scaffold.model import WRITING, Action, Applied, Plan, Refused, Template, Verb
from stayfixed.scaffold.regions import RegionError, drop, extract, upsert

# The reasons a file kept out of git is left alone, which is the rule for one: an edit
# overwritten or removed there is one git cannot give back, so only bytes stayfixed can show are
# its own go. `CHANGED_LOCALLY` when `LocalDigests` records what stayfixed last wrote there and the
# file no longer holds it; `NOT_OURS_LOCALLY` when nothing records it (the ledger was deleted,
# say) and the file is not what this build writes either, which says nothing about who changed it.
CHANGED_LOCALLY = "kept out of git, and changed since stayfixed wrote it"
NOT_OURS_LOCALLY = (
    "kept out of git, with no record of what stayfixed wrote there, and not the bytes it writes now"
)
# A copy stayfixed wrote under `LOCAL_ARTIFACTS` at a place this configuration no longer gives the
# artifact (its id left `[artifacts] local`, or its `[paths]` value moved), and whose bytes are no
# longer the ones it wrote.
LEFT_LOCALLY = (
    "kept out of git where this configuration no longer puts it, and changed since stayfixed "
    "wrote it"
)
SOURCE_NAME = PROJECT_NAME  # the one name grammar, `config.schema.PROJECT_NAME`
SOURCE_RULE = "lowercase letters, digits, `.`, `_` and `-`, starting with a letter or digit"
_IN_FILE = (Kind.MANAGED_REGION, Kind.KEYED_ENTRIES)
# The two refusals that belong to one artifact's own file: a region whose markers no longer say
# where it ends, and a settings document that cannot be parsed. Both are ordinary user state — a
# bad merge, a half-typed edit — and both are answered per artifact. `Refusal` itself is
# deliberately not caught: `_payload_and_stamp` raises it for a `MANAGED_REGION` template
# carrying no region name and for a `KEYED_ENTRIES` template carrying no entries, each a
# malformed `Template` and so a bug in the caller that built it, not something a user can put
# right by editing a file.
_OWN_FILE_REFUSALS = (RegionError, EntriesError)
_VERB_FOR = {Kind.MANAGED_REGION: Verb.REGION_UPDATE, Kind.KEYED_ENTRIES: Verb.ENTRIES_UPDATE}


def validate_sources(config: Config) -> None:
    """Contain the two values that name a file inside the *plugin* root, not the project root.

    "Inside the project root" cannot bound them by construction, so each is validated as one
    path segment and looked up against the listing. The preset half is already enforced by the
    configuration loader through `presets.load_preset`; the profile half is enforced here,
    because the loader stores `profile` as a bare string and widening `Config` would change a
    frozen contract.
    """
    profile = config.stayfixed.profile
    if not profile:
        return
    # Named and never quoted, in both refusals: `profile` is repository-authored, and the first
    # runs exactly for a value outside `SOURCE_NAME`, which can hold ESC and line breaks. The
    # rule is stated in words and the listing is stayfixed's own, so nothing here is the clone's.
    if not SOURCE_NAME.match(profile):
        raise PathEscape(f"[stayfixed] profile is not one path segment ({SOURCE_RULE})")
    # The package is the one listing: `profiles.shipped` lists a directory under it only when it
    # holds a `profile.toml`, which answers for an installed wheel and a `src/` checkout alike.
    from stayfixed import profiles

    shipped = profiles.shipped()
    if profile not in shipped:
        known = ", ".join(shipped) or "none"
        raise PathEscape(
            "[stayfixed] profile names a profile this version of stayfixed does not ship "
            f"(available: {known})"
        )


def effective_target(template: Template, config: Config) -> tuple[str, Location]:
    """Where `plan` puts `template` under `config`, and whether that place is kept out of git.

    An `[artifacts] local` artifact lives under `LOCAL_ARTIFACTS`, which `Template.target` does
    not say.
    """
    if template.id in config.artifacts.local:
        return f"{LOCAL_ARTIFACTS}/{template.target}", Location.LOCAL
    return template.target, Location.REPO


def _matches_render(template: Template, current: str) -> bool:
    """Whether `current` holds exactly the bytes this build renders for `template`'s part of it.

    For a file kept out of git, the second answer `ours_locally` gives, at the artifact's own
    place only, when the ledger does not vouch for the bytes there: it records no entry for that
    file (no ledger yet, or one deleted), or its entry records other bytes (the render changed
    back, say). `ours_locally` is the rule anything outside this module asks.
    """
    _, stamp = _payload_and_stamp(template, current)
    present = _present_stamp(template, current)
    return present is not None and digest(present) == digest(stamp)


def ours_locally(template: Template, current: str, target: str, digests: LocalDigests) -> bool:
    """Whether `current`, the file at `target` under `LOCAL_ARTIFACTS`, holds only bytes stayfixed
    can show are its own for `template`. The one rule `plan` removes or refreshes a file kept out
    of git by.

    Anywhere under `LOCAL_ARTIFACTS`: exactly what `digests` records stayfixed last wrote there for
    this artifact. At the artifact's own place there, `LOCAL_ARTIFACTS/<its target>`, also what
    this build renders, the rule from before the ledger existed and the one a deleted ledger falls
    back to; anywhere else only the recorded digest vouches, since the place itself came from the
    ledger.
    """
    present = _present_stamp(template, current)
    if present is not None and digests.matches(template.id, target, digest(present)):
        return True
    own = path_key(target) == path_key(f"{LOCAL_ARTIFACTS}/{template.target}")
    return own and _matches_render(template, current)


class Ownership(Protocol):
    """Which artifacts are built to write a place. `project.templates.Owners` is the relation,
    and says why a ledger entry never reaches a place it calls another artifact's."""

    def foreign(self, artifact_id: str, place: str) -> Set[str]: ...


def left_copies(
    template: Template,
    config: Config,
    digests: LocalDigests,
    owners: Ownership | None,
) -> tuple[str, ...]:
    """The copies kept out of git `digests` says stayfixed left for `template` at a place this
    configuration no longer gives it: its id left `[artifacts] local`, or its `[paths]` value
    moved while it stayed there. Every place the ledger records for its id but its current one,
    and none that `owners` calls another artifact's (`project.templates.Owners`). A copy at a case
    variant of the artifact's own place is that place (`fsops.path_key`), not one left behind.
    """
    target, _ = effective_target(template, config)
    kept = f"{LOCAL_ARTIFACTS}/"
    return tuple(
        copy
        for copy in digests.targets_of(template.id)
        if path_key(copy) != path_key(target)
        and not (owners is not None and owners.foreign(template.id, copy.removeprefix(kept)))
    )


def _read(path: Path, relative: str) -> tuple[str | None, str | None]:
    """`(content, reason)`: a reason is a refusal for this one artifact, never for the plan.

    The reason names the file by `relative`, its path from the project root, and says why in
    words (`fsops.unreadable`), as every other refusal here does: the error's own text carries the
    absolute path, this machine's layout, and `path` is a configured target a clone may choose.

    `newline=""` and not `read_text`: universal-newline translation turns every `\\r\\n` and
    every lone `\\r` into `\\n` before `regions.py` is reached, and `regions.py` is the module
    promising to return every byte outside its own markers unchanged. Translating on the way in
    makes that promise false for a CRLF file no matter how carefully the rewrite is done.

    To the read cap, a regular file only (`fsops.read_regular_text`): the file is one a clone
    commits, so one past the cap, or a FIFO a local process left there, is this artifact's
    refusal rather than a read to its end or a wait on a writer.
    """
    try:
        return read_regular_text(path, newline=""), None
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError) as exc:
        return None, unreadable(quoted(relative), exc)


def _payload_and_stamp(template: Template, current: str | None) -> tuple[str, str]:
    """The text `apply` writes, and the text whose digest the manifest records.

    They differ for the two kinds that live inside a file somebody else owns: what is written
    is the whole file, what is recorded is only stayfixed's own part of it.
    """
    if template.kind is Kind.MANAGED_REGION:
        if template.region is None:
            raise Refusal(f"{template.id}: a managed-region template names no region")
        body = template.render()
        return upsert(current or "", template.region, body, template.style), body.rstrip("\r\n")
    if template.kind is Kind.KEYED_ENTRIES:
        if template.entries is None:
            # `{}` means "remove every stayfixed entry", and `Template.entries` defaults to
            # `None` — so `template.entries or {}` read a caller that forgot one keyword argument
            # as a caller asking to uninstall the user's hook wiring, reported the result as
            # `entries_update` / "refreshed", and rewrote the manifest as though it were an
            # ordinary upgrade. The malformed-`Template` rule five lines above is the same
            # rule: a bug in the caller that built it, raised rather than acted on. `{}` is left
            # to mean removal, for the caller that genuinely wants it.
            raise Refusal(f"{template.id}: a keyed-entries template names no entries")
        if missing := unmarked(template.entries):
            # The same defect class as the branch above, in the other direction, and it landed
            # the other way round: `entries=None` silently *uninstalled* the user's wiring,
            # while entries carrying no `# stayfixed:<id>` marker silently fail to install it.
            # `owned()` renders the marked entries alone, so with none marked it answers `{}`
            # for both the payload and what is already on disk, the digests match, and the
            # artifact is reported `unchanged` — the report says "up to date" about a file
            # nothing wrote. A caller that did not call `entries.mark` is a bug in that caller,
            # raised rather than acted on, exactly like a malformed `Template` above.
            raise Refusal(
                f"{template.id}: a keyed-entries template carries {len(missing)} entry/entries "
                f"with no `{ENTRY_MARKER}<id>` marker, so nothing could ever recognise them as "
                f"stayfixed's own: {', '.join(repr(command) for command in missing)}"
            )
        document = apply_entries(current or "", template.entries)
        return document, owned(document)
    body = template.render()
    return body, body


def _present_stamp(template: Template, current: str) -> str | None:
    if template.kind is Kind.MANAGED_REGION:
        if template.region is None:
            return None
        return extract(current, template.region, template.style)
    if template.kind is Kind.KEYED_ENTRIES:
        return owned(current)
    return current


def _removal_payload(template: Template, current: str) -> str | None:
    """What `remove` leaves behind.

    Nothing for a whole file. For the two kinds that live inside somebody else's file, the file
    minus stayfixed's part, and nothing either when stayfixed's part was all the file held, which
    is what `detach` already does with the `.gitignore` it emptied. Emptiness is exact: a
    remainder of whitespace is somebody's and stays. A host file that already existed and was
    empty before the region went in is removed with the region, as `detach` removes it.
    """
    if template.kind is Kind.MANAGED_REGION and template.region is not None:
        remainder = drop(current, template.region, template.style)
        return remainder if remainder else None
    if template.kind is Kind.KEYED_ENTRIES:
        return apply_entries(current, {})
    return None


def plan(
    root: Path,
    config: Config,
    templates: Sequence[Template],
    *,
    owners: Ownership | None = None,
) -> Plan:
    """What applying `templates` under `config` would do, decided and not yet written.

    `owners` is which artifacts the caller that built `templates` builds to write each place, and
    `left_copies` says what it guards. A caller whose templates are never kept out of git (the
    overlay's) has no ledger to guard and passes none.
    """
    validate_sources(config)
    manifest = Manifest.read(root)
    digests = LocalDigests.read(root)
    resolved_root = root.resolve()
    # A left copy at a file another template of this plan now targets is that template's to
    # judge; its entry stays until that file is stayfixed's again or gone.
    planned = {path_key(effective_target(template, config)[0]) for template in templates}
    actions: list[Action] = []
    refusals: list[Refused] = []
    unchanged: list[str] = []

    for template in templates:
        target, location = effective_target(template, config)
        try:
            path = contained(root, target, resolved_root=resolved_root)
        except PathEscape as exc:
            refusals.append(Refused(template.id, target, str(exc)))
            continue

        record = manifest.get(template.id)
        if record is not None and path_key(record.target) != path_key(target):
            # The relocation reads and rewrites the artifact's own old file, so a refusal from
            # it is this artifact's refusal — the same rule the block below runs under.
            try:
                moved = _relocation(root, resolved_root, template, record)
            except _OWN_FILE_REFUSALS as exc:
                refusals.append(Refused(template.id, record.target, str(exc)))
                continue
            actions.append(moved)
            record = None
        refused = False
        for copy in left_copies(template, config, digests, owners):
            if path_key(copy) in planned:
                continue
            try:
                left = _left_locally(root, resolved_root, template, copy, digests)
            except _OWN_FILE_REFUSALS as exc:
                refusals.append(Refused(template.id, copy, str(exc)))
                refused = True
                continue
            if left is not None:
                actions.append(left)
        if refused:
            continue

        current, reason = _read(path, target)
        if reason is not None:
            refusals.append(Refused(template.id, target, reason))
            continue

        # Everything below reads or rewrites this one artifact's own file, so a refusal from it
        # is this artifact's refusal. Letting one escape would hide every other template and
        # leave the command with no report at all — including the REFUSED section that exists to
        # name exactly these.
        try:
            if template.kind is Kind.ONCE and current is not None:
                # `skip_modified` (no record, file present, kind `template` or `once`), and not
                # `unchanged`, which is what this said: `unchanged` renders as "up to date", and
                # stayfixed has no idea whether this file is up to date — a create-once artifact
                # is one it deliberately never looks inside again. "Left alone because it is
                # yours" is the true statement, and it is the one the user can act on.
                actions.append(
                    Action(
                        Verb.SKIP_MODIFIED,
                        template.id,
                        target,
                        None,
                        "create-once, and the file is already there",
                        None,
                    )
                )
                continue

            payload, stamp = _payload_and_stamp(template, current)
            new_record = Record(
                id=template.id,
                kind=template.kind,
                location=location,
                target=target,
                template=template.source,
                version=config.stayfixed.version,
                sha256=digest(stamp),
            )
            if current is None:
                actions.append(Action(Verb.CREATE, template.id, target, payload, "new", new_record))
                continue

            present = _present_stamp(template, current)
            if present is not None and digest(present) == digest(stamp):
                unchanged.append(template.id)
                continue
            if record is None and location is Location.REPO and template.kind not in _IN_FILE:
                # A whole file stayfixed never wrote is somebody's; a region or a hook entry
                # inside a file stayfixed never wrote is the ordinary first install. A local
                # artifact is answered by the next branch instead: it is never recorded, so
                # `record is None` there says nothing about who wrote the file.
                actions.append(
                    Action(
                        Verb.SKIP_MODIFIED,
                        template.id,
                        target,
                        None,
                        "exists and stayfixed did not write it",
                        None,
                    )
                )
                continue
            if (
                record is None
                and location is Location.LOCAL
                and present is not None
                and not digests.matches(template.id, target, digest(present))
            ):
                # Neither this build's bytes nor, by the ledger, the bytes stayfixed last wrote
                # here: an edit, or a file nothing records. What the ledger does record goes on to
                # be refreshed below, which is how an unedited copy follows a changed template.
                recorded = digests.records(template.id, target)
                reason = CHANGED_LOCALLY if recorded else NOT_OURS_LOCALLY
                actions.append(Action(Verb.SKIP_MODIFIED, template.id, target, None, reason, None))
                continue
            hand_edited = (
                record is not None and present is not None and digest(present) != record.sha256
            )
            if hand_edited:
                actions.append(
                    Action(Verb.SKIP_MODIFIED, template.id, target, None, "hand-edited", None)
                )
                continue
            verb = _VERB_FOR.get(template.kind, Verb.UPDATE)
            actions.append(Action(verb, template.id, target, payload, "refreshed", new_record))
        except _OWN_FILE_REFUSALS as exc:
            refusals.append(Refused(template.id, target, str(exc)))

    # The conversion to tuples happens here, at the boundary, so the object a user approves
    # through `render_report` is the object `apply` consumes. See `Plan`.
    return Plan(actions=tuple(actions), refusals=tuple(refusals), unchanged=tuple(unchanged))


def _relocation(root: Path, resolved_root: Path, template: Template, record: Record) -> Action:
    """A recorded artifact whose effective target moved — `[artifacts] local` gained or lost its id.

    The recorded target is repository-controlled through the committed manifest, so "does this
    record describe the file I am about to delete" cannot rest on the record alone: a committed
    manifest naming any in-root file, stamped with the bytes that file is committed with, would
    otherwise make `plan` emit a `REMOVE` for it. So the recorded target must be one of the two
    paths this template can produce — its configured target, or that target under
    `LOCAL_ARTIFACTS` — before anything else is asked. It is then contained before it is read,
    exactly like a configured one.

    **Always an `Action`, never `None`.** Every branch that declines to remove the old file used
    to answer `None`, and `plan` read that as "nothing to do here" and carried on creating the
    file at the new target — so a relocated artifact whose old file a user had hand-edited was
    left on disk holding that edit, the manifest ended empty, and the report said "0 skipped,
    0 refused". `apply`'s own comment calls that state a defect: "a file stayfixed wrote carrying
    no record, which every later run reads as somebody else's".

    So the three ways the old file is not stayfixed's to remove — a recorded target this template
    could not have produced, one that no longer contains, and one whose bytes are not the ones
    recorded — each become a `skip_modified` naming the old path and saying which it was.
    """
    producible = (template.target, f"{LOCAL_ARTIFACTS}/{template.target}")
    if path_key(record.target) not in {path_key(place) for place in producible}:
        return _left_behind(
            template,
            record,
            "the manifest records a target this artifact cannot produce, so the file at it "
            "is not stayfixed's to remove",
        )
    try:
        old_path = contained(root, record.target, resolved_root=resolved_root)
    except PathEscape as exc:
        return _left_behind(template, record, str(exc))
    old, reason = _read(old_path, record.target)
    if reason is not None:
        return _left_behind(template, record, reason)
    if old is None:
        # Nothing at the old path: the move has effectively already happened, and there is no
        # file to leave behind. A `skip_modified` here would report a file that is not there.
        return Action(Verb.REMOVE, template.id, record.target, None, "relocated", record)
    # What the record stamps is what `_payload_and_stamp` stamped: the whole file for a whole
    # file, and stayfixed's own part of it for a region or a set of keyed entries. Comparing the
    # whole old file with a region's stamp read every real relocation of a region as a hand edit.
    present = _present_stamp(template, old)
    if present is None or digest(present) != record.sha256:
        return _left_behind(template, record, "relocated and hand-edited")
    # For a managed region or a set of keyed entries the file at the old path belongs to somebody
    # else, so what leaves is stayfixed's own part of it and not the file.
    payload = _removal_payload(template, old)
    return Action(Verb.REMOVE, template.id, record.target, payload, "relocated", record)


def _left_locally(
    root: Path,
    resolved_root: Path,
    template: Template,
    copy: str,
    digests: LocalDigests,
) -> Action | None:
    """A copy kept out of git that an artifact left behind at a place the configuration no longer
    gives it: its id left `[artifacts] local`, or its `[paths]` value moved while it stayed there.

    `copy` comes from the ledger, which `LocalDigests.read` has bounded to `LOCAL_ARTIFACTS`, and
    it is contained here before it is read, like every other target. Nothing there, or a file
    holding none of this artifact's part (a region whose markers are gone), is nothing to do.
    Bytes `ours_locally` accepts go, as a `REMOVE` that takes a region out of a file and leaves
    the rest: away from the artifact's own place only exactly the recorded digest vouches.
    Anything else is an edit git cannot give back, so it is left and named, its entry kept.
    """
    try:
        path = contained(root, copy, resolved_root=resolved_root)
    except PathEscape as exc:
        return Action(Verb.SKIP_MODIFIED, template.id, copy, None, str(exc), None)
    current, reason = _read(path, copy)
    if reason is not None:
        return Action(Verb.SKIP_MODIFIED, template.id, copy, None, reason, None)
    if current is None or _present_stamp(template, current) is None:
        return None
    if ours_locally(template, current, copy, digests):
        payload = _removal_payload(template, current)
        return Action(Verb.REMOVE, template.id, copy, payload, "relocated", None)
    return Action(Verb.SKIP_MODIFIED, template.id, copy, None, LEFT_LOCALLY, None)


def _left_behind(template: Template, record: Record, reason: str) -> Action:
    return Action(Verb.SKIP_MODIFIED, template.id, record.target, None, reason, None)


def apply(root: Path, planned: Plan) -> Applied:
    """Write what `plan` decided, or refuse the whole plan.

    `apply` takes the `Plan` rather than a bare action list: a refusal is a property of the plan.
    A caller that wants the good half of a refused plan re-plans without the offending templates.
    """
    if planned.refusals:
        detail = "; ".join(f"{r.artifact_id}: {r.reason}" for r in planned.refusals)
        raise Refusal(f"{len(planned.refusals)} path(s) refused: {detail}")

    manifest = Manifest.read(root)
    digests = kept = LocalDigests.read(root)
    resolved_root = root.resolve()
    written: list[str] = []
    removed: list[str] = []
    skipped: list[str] = []

    # The ledger records what is on disk, so it is persisted for the actions that ran even when
    # a later one refuses. Discarding it would leave a file stayfixed wrote carrying no record,
    # which every later run reads as somebody else's: `skip_modified` under a false reason. The
    # refusal still propagates; only the loop is wrapped, because the refusal above it has
    # written nothing to record.
    try:
        for action in planned.actions:
            if action.verb is Verb.SKIP_MODIFIED:
                skipped.append(action.target)
                continue
            # Re-validate the string against the live tree, then stop using the string: the
            # write happens through a descriptor `open_within` walked with O_NOFOLLOW.
            contained(root, action.target, resolved_root=resolved_root)
            if action.verb is Verb.REMOVE:
                # A removal whose file is already gone unlinks nothing and drops the record below.
                # Walking to it anyway failed on a directory that is gone too, as a refusal, and
                # `removed` would name a file this run did not remove.
                if action.payload is not None or os.path.lexists(root / action.target):
                    _remove(root, action.target, action.payload)
                    removed.append(action.target)
                # A record goes with the file it names and no other. The copy an artifact left
                # kept out of git carries the artifact's id too, and dropping by id alone took
                # the live record of its committed file with it: that file then read as nobody's
                # and was never recorded again.
                record = manifest.get(action.artifact_id)
                if record is not None and path_key(record.target) == path_key(action.target):
                    manifest = manifest.without(frozenset({action.artifact_id}))
                if action.payload is None:
                    digests = digests.without_file(action.target)
                else:
                    digests = digests.without(action.artifact_id, action.target)
                continue
            if action.verb in WRITING:
                if action.payload is None:
                    raise Refusal(f"{action.artifact_id}: {action.verb} with no payload")
                _write(root, action.target, action.payload)
                written.append(action.target)
                if action.record is not None and action.record.location is Location.REPO:
                    manifest = manifest.with_record(action.record)
                else:
                    manifest = manifest.without(frozenset({action.artifact_id}))
                if action.record is not None and action.record.location is Location.LOCAL:
                    # Kept out of git, so recorded where git never sees it: `LocalDigests`.
                    digests = digests.with_entry(
                        action.artifact_id, action.target, action.record.sha256
                    )
    finally:
        manifest.write(root)
        digests = digests.on_disk(root)
        # Written only when it changed, so a footprint with nothing kept out of git never gains
        # a `.stayfixed/local/` for it.
        if digests != kept:
            digests.write(root)

    return Applied(written=tuple(written), removed=tuple(removed), skipped=tuple(skipped))


def _write(root: Path, target: str, payload: str) -> None:
    """Create the parents and replace the file, or refuse — never raise a bare `OSError`.

    The walk, the parent creation and the atomic replacement are `fsops.write_within`; what is
    this area's is the translation below. That split is deliberate: `attach`, `setup`,
    `overlay` and the `hooks` area's sink all write files that are not `Template`s, and the half
    they need is the walk, not this area's verdict vocabulary.

    The second clause is what keeps the refusal exit code, 2, reachable. A user who saves a file
    where a directory component belongs while reading the dry-run report, then confirms, would
    otherwise get a traceback instead of a refusal, and no race is needed for that.
    """
    try:
        write_within(root, target, payload)
    except UnsafePath as exc:
        raise Refusal(str(exc)) from exc
    except OSError as exc:
        raise Refusal(f"{target} cannot be written: {exc}") from exc


def _remove(root: Path, target: str, payload: str | None) -> None:
    """Unlink the file, or rewrite it without stayfixed's part — never raise a bare `OSError`.

    The same second clause `_write` carries, for the same reason: a directory stayfixed may read
    but not write to arrives here as EACCES from `os.unlink` rather than as an `UnsafePath`, and
    only a refusal keeps the refusal exit code, 2, reachable.
    """
    if payload is not None:
        _write(root, target, payload)
        return
    try:
        remove_within(root, target)
    except UnsafePath as exc:
        raise Refusal(str(exc)) from exc
    except OSError as exc:
        raise Refusal(f"{target} cannot be removed: {exc}") from exc
