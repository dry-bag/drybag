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
per-artifact report could rescue — the manifest itself, and a malformed
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

from collections.abc import Sequence
from pathlib import Path

from stayfixed.config.paths import PathEscape, contained
from stayfixed.config.schema import Config
from stayfixed.errors import Refusal
from stayfixed.fsops import (
    UnsafePath,
    path_key,
    read_regular_text,
    unreadable,
    write_within,
)
from stayfixed.printed import quoted
from stayfixed.scaffold.entries import ENTRY_MARKER, EntriesError, apply_entries, owned, unmarked
from stayfixed.scaffold.manifest import Kind, Location, Manifest, Record, digest
from stayfixed.scaffold.model import WRITING, Action, Applied, Plan, Refused, Template, Verb
from stayfixed.scaffold.regions import RegionError, extract, upsert

# A recorded target this template could not have produced: the file at it is not stayfixed's.
NOT_PRODUCIBLE = (
    "the manifest records a target this artifact cannot produce, so the file at it is not "
    "stayfixed's to remove"
)
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
            # ordinary refresh. The malformed-`Template` rule five lines above is the same
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


def plan(
    root: Path,
    config: Config,
    templates: Sequence[Template],
) -> Plan:
    """What applying `templates` under `config` would do, decided and not yet written."""
    manifest = Manifest.read(root)
    resolved_root = root.resolve()
    actions: list[Action] = []
    refusals: list[Refused] = []
    unchanged: list[str] = []

    for template in templates:
        target = template.target
        try:
            path = contained(root, target, resolved_root=resolved_root)
        except PathEscape as exc:
            refusals.append(Refused(template.id, target, str(exc)))
            continue

        record = manifest.get(template.id)
        if record is not None and path_key(record.target) != path_key(target):
            # The manifest is committed, so `record.target` is repository-controlled: a record
            # naming another place than the one this template produces describes no file of
            # stayfixed's to touch. It is named, never followed, and the artifact is judged at its
            # own place as if nothing recorded it.
            actions.append(
                Action(Verb.SKIP_MODIFIED, template.id, record.target, None, NOT_PRODUCIBLE, None)
            )
            record = None

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
                location=Location.REPO,
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
            if record is None and template.kind not in _IN_FILE:
                # A whole file stayfixed never wrote is somebody's; a region or a hook entry
                # inside a file stayfixed never wrote is the ordinary first install.
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


def apply(root: Path, planned: Plan) -> Applied:
    """Write what `plan` decided, or refuse the whole plan.

    `apply` takes the `Plan` rather than a bare action list: a refusal is a property of the plan.
    A caller that wants the good half of a refused plan re-plans without the offending templates.
    """
    if planned.refusals:
        detail = "; ".join(f"{r.artifact_id}: {r.reason}" for r in planned.refusals)
        raise Refusal(f"{len(planned.refusals)} path(s) refused: {detail}")

    manifest = Manifest.read(root)
    resolved_root = root.resolve()
    written: list[str] = []
    skipped: list[str] = []

    # The manifest records what is on disk, so it is persisted for the actions that ran even when
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
            if action.verb in WRITING:
                if action.payload is None:
                    raise Refusal(f"{action.artifact_id}: {action.verb} with no payload")
                _write(root, action.target, action.payload)
                written.append(action.target)
                if action.record is not None:
                    manifest = manifest.with_record(action.record)
                else:
                    manifest = manifest.without(frozenset({action.artifact_id}))
    finally:
        manifest.write(root)

    return Applied(written=tuple(written), removed=(), skipped=tuple(skipped))


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
