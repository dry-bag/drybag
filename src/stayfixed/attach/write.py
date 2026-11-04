"""What `stayfixed attach` actually writes, in the order the refusals have to happen in.

**No hook entry goes into `settings.local.json`.** Claude Code rewrites that file whole and adds
allow rules of its own to it, so no in-band marker survives there. The overlay's hook entries,
skills and agents are rendered into a local plugin named by the binding id (`attach.render`),
re-rendered in place and installed on every run, both `claude plugin` calls being idempotent; the
file keeps only the allow rules the ledger names, and the plugin's `enabledPlugins` and
`extraKnownMarketplaces` entries, which Claude Code writes. A checkout an earlier release attached
holds the entries that release merged, named by its ledger's `entries`: `attach` takes back
exactly those, through `scaffold.withdraw_entries`, and records none.

*Not the scaffold engine's `plan`/`apply` for the settings file.* The engine stamps a digest of
the document into the **committed** `.stayfixed/manifest.json`, which would publish a digest of
the owner's personal allow rules to every collaborator. The pure functions are called
instead — document string in, document string out, no manifest — and the ledger below takes
the manifest's place. This is the one place where refusing an existing mechanism is right.

An allow rule cannot carry a marker — `scaffold.mark` appends to a *command* — so it has exactly
**one** witness, the ledger at `.stayfixed/local/attach.json`, and `detach` is only ever as good
as that file.

**Delivery does not depend on the memory mode.** Every repository is rendered and installed; the
note half — the overlay's group directories, the composed store and the `autoMemoryDirectory` key
that points the harness at it — is made only for a repository whose `memory.mode` is `overlay`, and
every check that is about it is asked only there.

**One place per repository: the main checkout.** Claude Code reads the main checkout's
`settings.local.json` from every worktree and writes a worktree's own answers into it, so `attach`
and `detach` act on the main checkout whichever worktree they run from: its settings file, its
`.codex/rules/` copies and its ledger. Nothing is placed per worktree. Where git names no main
checkout, a bare repository's worktree, `attach` refuses with "cannot tell" (`NO_MAIN_CHECKOUT`).

**Nothing goes into `.gitignore`, and every placed path is ignored before the first write after
the exclude block.** `.gitignore` is tracked, so a line `attach` wrote there was a change every
collaborator got. Everything `attach` places in the checkout, the ledger with the owner's personal
allow rules included, is listed in the `info/exclude` block (`attach.exclude`), which no clone
carries; the block is written first, and git is then asked whether each placed path is ignored,
so a `.gitignore` that re-includes one (a `!` line outranks the exclude file) stops the run
before that path is written. The binding id is placed too, but in the git common directory, which
git never tracks, so it is neither listed nor asked about. A `stayfixed:ignore` region in
`.gitignore` is not this module's: it neither writes nor withdraws one.

**Every write goes through a primitive that already exists.** `fsops.write_within(root, …)` for
everything inside the project, `fsops.write_within(overlay, …)` for the overlay's project record,
and `stayfixed.binding` and `attach.render` for this machine's binding record and render.
"""

from __future__ import annotations

import datetime
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stayfixed import fsops, tomlout
from stayfixed.attach import exclude
from stayfixed.attach.binding import (
    BY_FILE,
    NAMED_BY_FILE,
    Binding,
    Chosen,
    choose_project,
    read_binding,
    refuse_unless_share_can_exist,
)
from stayfixed.attach.permissions import (
    CODEX_RULES,
    LOCAL_SETTINGS,
    PermissionDiff,
    allow_list,
    codex_rules,
    diff_permissions,
    local_document,
    settings_document,
    withdrawing,
)
from stayfixed.attach.render import (
    COPIED,
    HOOK_FILE,
    MARKETPLACE_PREFIX,
    PLUGIN_DIRECTORY,
    PLUGIN_INSTALL_LOCAL,
    PLUGIN_MARKETPLACE_ADD_LOCAL,
    PLUGIN_MARKETPLACE_REMOVE,
    PLUGIN_UNINSTALL_LOCAL,
    Part,
    Rendered,
    filled,
    marketplace_name,
    plugin_name,
    read_parts,
    remove_tree,
)
from stayfixed.attach.render import write as write_render
from stayfixed.binding import (
    bound_project,
    delivery_directory,
    ensure_id,
    main_checkout_or_none,
    read_id,
    record,
    short,
)
from stayfixed.config.layout import ATTACH_LEDGER
from stayfixed.config.owner import Owner
from stayfixed.config.paths import PathEscape, PathUnasked, contained
from stayfixed.config.plates import TAG_LINK_PREFIX, read_record, record_fault
from stayfixed.config.reading import UNPARSEABLE
from stayfixed.config.schema import OVERLAY_MODE, Config
from stayfixed.config.session import command_config
from stayfixed.errors import Failure, Refusal
from stayfixed.fsops import UnsafePath
from stayfixed.gitenv import without_userinfo
from stayfixed.jsonobject import NESTED, json_object
from stayfixed.memory.api import (
    BOUND,
    COMMON_GROUP,
    PROJECT_RECORD,
    PROJECTS,
    STORE_DIR,
    build_composed,
    render_missing_index,
    withdraw_composed,
)
from stayfixed.printed import quoted
from stayfixed.runner import Runner
from stayfixed.scaffold import (
    ParserLimitError,
    mark,
    marker_id,
    owned_ids,
    settings_text,
    withdraw_entries,
)

LEDGER_FORMAT = 1
# The one settings key `attach` writes: the harness's memory directory, which in overlay mode names
# the composed store (`memory.composed`), absolute, in the main checkout's `settings.local.json`,
# which Claude Code reads from every worktree.
POINTER_KEY = "autoMemoryDirectory"
# What `attach` says of a checkout with no `origin`, which binds as any other: the binding is the
# id in the git common directory, and the remote is only what the records note beside it.
NO_ORIGIN_NOTE = "this checkout has no `origin` remote, so the binding records none"
# Said where this machine's record bound the checkout to another project than the one it is bound
# to now: a renamed `[project] name` moves every worktree's binding. Both names print quoted.
REBOUND = "this checkout's binding moves from project {earlier} to project {project}"
# The third, and the first of the two whose trigger is repository-authored
# (`memory.groups` reaches no guard of its own). One constant for the check above every write
# and for the `O_NOFOLLOW` walk that is the floor under it, because two spellings of one
# refusal are two refusals to keep in step. The entry is never quoted back into it.
GROUP_ESCAPES = (
    "a memory.groups entry does not stay inside this project's share of the overlay, so it is "
    "refused rather than created"
)
# Said instead when no symlink is on the way and a directory on it cannot be asked whether it is
# one, which the sentence above would misname; `{fault}` is the system's words, never a path.
GROUP_UNASKED = (
    "a memory.groups entry's place in this project's share of the overlay cannot be checked for "
    "a symlink ({fault}), so it is refused rather than created"
)
# `fsops.mkdirs_within` creates a target's *parents*, so a directory is asked for as the parent
# of a name inside it. Nothing is ever written at this name; `overlay.create` asks the same way.
_INSIDE = ".keep"
# Every directory `attach` can bring into existence in the project root, as a *closed* list,
# deepest first — which is also the order `detach` has to remove them in.
#
# There are exactly three writes that create a directory here, and each one's parents are on
# this list: `ATTACH_LEDGER` under `.stayfixed/local/`, the rule copies under `.codex/rules/`, and
# `LOCAL_SETTINGS` under `.claude/`.
#
# Closed because a ledger is a file a clone can commit. `detach` iterates this tuple and keeps
# only the members the ledger names, so the ledger can shorten the list and never extend it,
# and a committed `["src"]` names nothing this loop will act on. `ledger()` refuses one anyway,
# on the same standard `rules` and `settings_keys` are held to.
CREATED_DIRS = (".stayfixed/local", ".stayfixed", ".codex/rules", ".codex", ".claude")


@dataclass(frozen=True)
class Carried:
    """What a render of the plugin carries, as `attach` names it on its screen: each hook entry by
    its event and command, and each skill and agent by its name under `skills/` or `agents/`.

    Every name is the overlay's, the owner's own, read either out of the parts this run renders or
    out of the render directory the last run left, which is this machine's; each prints through
    `printed`."""

    hooks: tuple[tuple[str, str], ...] = ()
    skills: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()

    def without(self, other: Carried) -> Carried:
        """What this carries that `other` does not."""
        return Carried(
            tuple(entry for entry in self.hooks if entry not in other.hooks),
            tuple(name for name in self.skills if name not in other.skills),
            tuple(name for name in self.agents if name not in other.agents),
        )


@dataclass(frozen=True)
class Attached:
    """What one `attach` changed, and the screen it is said on: the binding, then what will run
    that did not before and what no longer will, then the allow rules added and taken back.

    Nothing here is repository-authored but `origin`, this checkout's remote, and `project`, the
    name the binding is recorded under, both of which a caller prints through `printed`, and one
    note, `memory.store.origin_note`'s, which names the remotes through `printed.quoted`.
    `binding` is the binding id as `binding.short` prints it, never the whole id;
    `binding_recorded` says whether this run bound a checkout this machine did not bind before.
    `added` and `removed` are the executable diff against the render the last run left, and
    `allow_added` the allow rules this run merged and `allow_withdrawn` those it took back; all
    four are the overlay's.
    """

    settings_written: bool
    rules_written: tuple[str, ...]
    binding_recorded: bool
    notes: tuple[str, ...]
    binding: str
    origin: str | None = None
    project: str = ""
    added: Carried = Carried()
    removed: Carried = Carried()
    allow_added: tuple[str, ...] = ()
    allow_withdrawn: tuple[str, ...] = ()


@dataclass(frozen=True)
class AttachLedger:
    """The only witness an allow rule has, and the record `detach` acts from.

    Not *authority*, and the difference is the whole of this docstring. `.gitignore` does not
    untrack a file a clone committed, so this path can arrive in a fresh checkout with contents
    nobody on this machine wrote — and `detach` then deletes files by the strings in `rules` and
    drops settings keys by the strings in `settings_keys`. Obeyed, a ledger claiming
    `settings_keys = ["permissions"]` would delete the owner's whole `permissions` block, **deny
    rules included**: a widening driven by repository-authored bytes, out of a file that is no
    authority.

    So `ledger()` answers one question about every field before `detach` sees it — *what could
    `attach` possibly have written here?* — and refuses anything outside that answer rather than
    obeying it. The two fields that name things to destroy are bounded exactly:

    - `rules` may only be `.codex/rules/<file>`, the one place `permissions.codex_rules`
      enumerates, one path segment deep and never a dotfile; and
    - `settings_keys` may only be `autoMemoryDirectory`, the pointer at the composed store and the
      one key `_point` writes.

    `directories` is the third, and is bounded by membership in `CREATED_DIRS`. It records which
    of those directories this repository did **not** have before the attach, so `detach` can put
    the tree back as it found it; `rmdir` is the only removal it drives, so a directory holding
    anything at all survives regardless of what the ledger claims.

    `entries` keys must parse as marker ids, because `_write_ledger` builds them with
    `scaffold.marker_id` and nothing else can appear there.

    `allow` and `store` are not bounded here, and saying why is part of the rule rather than an
    omission. An allow rule has no grammar this area owns — the ledger exists *because* a rule
    cannot be told from the owner's own by its content — and its two consumers, `detach`
    (`_withdraw_settings`) and every re-attach (`permissions.withdrawing`), only ever remove a rule
    the settings file already holds, so the worst a committed `allow` achieves is taking a
    permission away, one the owner typed included. That bound is accepted: a branch can write this
    file, so it is a convenience and no anchor against one. `store` is read by nothing: `detach`
    derives every path it withdraws from the configuration and the overlay root, never from this
    field, so it is a record for a human reading the file and for `doctor`, and a committed value
    costs nothing — except one holding a NUL, which no path holds and `doctor`'s `Path.resolve`
    meets with `ValueError`, so that one is a ledger no attach wrote. So is any list field holding
    something other than a list, which reading it would meet with `TypeError`.

    `entries` maps each marker id to its event, which is the shape `scaffold.owned_ids` answers
    in, so `doctor` can compare the two without a translation in between. Only a ledger an earlier
    release wrote holds any: `attach` merges no hook entry now, takes back the ones recorded here,
    and records none.

    `render` is the digest and the parts of the render the last run installed, `None` before the
    first. It decides one thing, whether `attach` runs `claude plugin` again, and names nothing to
    destroy: each part is held to a path the contained walk accepts, and it is removed only from
    under `delivery_directory(id)`, which is derived from the id and never from this file.
    """

    store: str
    allow: tuple[str, ...]
    entries: dict[str, str]
    rules: tuple[str, ...]
    settings_keys: tuple[str, ...]
    directories: tuple[str, ...] = ()
    render: Rendered | None = None


def _rule_is_writable(rule: str) -> bool:
    """Whether `attach` could have written this path: `.codex/rules/<file>` and nothing else.

    `permissions.codex_rules` composes every target as `f"{CODEX_RULES}/{rule.name}"` over a
    directory listing, so the answer is one path segment under that prefix, never a dotfile and
    never a nested path. `.github/workflows/ci.yml` and `src/stayfixed/__init__.py` are all
    inside the root `fsops.remove_within` contains the removal to, which is why containment is
    not the guard that matters here.
    """
    prefix = f"{CODEX_RULES}/"
    if not rule.startswith(prefix):
        return False
    name = rule[len(prefix) :]
    return bool(name) and "/" not in name and not name.startswith(".")


def _listed(raw: dict[str, Any], key: str, path: Path) -> list[Any]:
    """The ledger's `key`, which `attach` always writes as a list: absent reads as empty, and
    anything else is a ledger no attach wrote — a `Failure`, the answer every reader of this file
    already handles, and not the `TypeError` iterating a number would raise past them."""
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise Failure(f"{path} is not a ledger `stayfixed attach` wrote: its {key!r} is not a list")
    return value


def _checked(
    raw: dict[str, Any], path: Path
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """`rules`, `settings_keys` and `directories`, or a `Refusal` counting what was never written.

    Counted and never quoted: these strings are repository-authored (principle 5), and a
    refusal built out of one is still one.
    """
    rules = tuple(r for r in _listed(raw, "rules", path) if isinstance(r, str))
    keys = tuple(k for k in _listed(raw, "settings_keys", path) if isinstance(k, str))
    # Held to the same standard as the two above rather than merely filtered at the removal
    # site, so the answer to "is this a record of an attach on this machine?" is one answer.
    # `detach` also intersects with `CREATED_DIRS` when it walks them, which is the floor under
    # this; a name outside the list is a ledger no attach wrote, and that is a refusal.
    directories = tuple(d for d in _listed(raw, "directories", path) if isinstance(d, str))
    foreign = sum(1 for rule in rules if not _rule_is_writable(rule))
    foreign += sum(1 for key in keys if key != POINTER_KEY)
    foreign += sum(1 for name in directories if name not in CREATED_DIRS)
    if foreign:
        raise Refusal(
            f"{path} names {foreign} file(s), settings key(s) or directory(ies) that "
            f"`stayfixed attach` could never have written, so it is not a record of an attach on "
            f"this machine; nothing "
            f"was removed. Delete it, or take it out of the clone that committed it"
        )
    return rules, keys, directories


def ledger(root: Path) -> AttachLedger:
    """The ledger this repository's last `attach` wrote, or a `Failure` naming the missing file.

    Never a best effort. Guessing which allow rules were stayfixed's from their content is the
    heuristic this file exists to replace, and a `detach` built on a guess removes a rule the
    owner wrote by hand — which is worse than removing none.

    A ledger whose `rules` or `settings_keys` name something `attach` could not have written is
    a `Refusal` rather than a filtered list: see `AttachLedger`. Filtering would let a committed
    ledger keep the members it is entitled to and lose only the hostile ones, which is a partial
    defence reported as a success.
    """
    path = root / ATTACH_LEDGER
    with fsops.reading(ATTACH_LEDGER, Failure):
        try:
            # A regular file only (`fsops.read_regular_text`): a clone can commit the ledger, and
            # `detach` read it with no other check first, so a link to `/dev/zero` read until
            # memory ran out.
            text = fsops.read_regular_text(path)
        except FileNotFoundError as exc:
            raise Failure(
                f"{ATTACH_LEDGER} is not there, so nothing records what `stayfixed attach` added "
                f"to this repository; there is no safe way to guess it from the settings file"
            ) from exc
    # Empty text fails as JSON: `attach` never writes an empty ledger, so one is no record. Valid
    # JSON past the parser's reach, which a clone can commit, is unreadable like the arms above,
    # and said in the words every other refusal of a ledger here uses: not one `attach` wrote.
    raw = json_object(
        text,
        str(path),
        error=Failure,
        limit=lambda clause: Failure(
            f"{path} is not a ledger `stayfixed attach` wrote: it {clause}"
        ),
    )
    rules, keys, directories = _checked(raw, path)
    store = raw.get("store", "")
    if not isinstance(store, str):
        # `attach` writes the store as a string. Anything else is refused rather than passed
        # through `str()`: `{"store": 5}` would read as the store `5`, and from Python 3.14, whose
        # parser follows deeper nesting than `str()` does, a deeply nested value raised
        # `RecursionError` past every reader's catch.
        raise Failure(f"{path} is not a ledger `stayfixed attach` wrote: its 'store' is not text")
    if "\0" in store:
        # `attach` records the store it was handed as a path, and no path holds a NUL; `doctor`
        # hands this field to `Path.resolve`, which meets one with `ValueError`.
        raise Failure(f"{path} is not a ledger `stayfixed attach` wrote: its 'store' holds a NUL")
    try:
        os.fsencode(store)
    except UnicodeEncodeError:
        # The same reason as the NUL: a lone surrogate (`"\ud800"` in the JSON) is no path this
        # system can name, and `Path.resolve` meets one with `UnicodeEncodeError`.
        raise Failure(
            f"{path} is not a ledger `stayfixed attach` wrote: its 'store' is not a path this "
            f"system can encode"
        ) from None
    render = _render(raw.get("render"), path)
    entries = raw.get("entries")
    if isinstance(entries, dict) and not all(isinstance(v, str) for v in entries.values()):
        # `attach` records each entry's event as a string; refused for the reason `store` is.
        raise Failure(
            f"{path} is not a ledger `stayfixed attach` wrote: its 'entries' hold a value that "
            f"is not text"
        )
    return AttachLedger(
        store=store,
        allow=tuple(r for r in _listed(raw, "allow", path) if isinstance(r, str)),
        entries=(
            # `mark`/`marker_id` and not a second copy of the marker grammar: `_write_ledger`
            # builds these keys with `marker_id`, so a key that does not round-trip through the
            # engine's own pair is one no attach could have recorded. Dropped rather than
            # refused, because a key names nothing to destroy: what it costs is a provenance
            # row, and `doctor` reporting an entry as unrecorded is the conservative answer.
            {k: v for k, v in entries.items() if marker_id(mark("", k)) == k}
            if isinstance(entries, dict)
            else {}
        ),
        rules=rules,
        settings_keys=keys,
        directories=directories,
        render=render,
    )


def _render(value: object, path: Path) -> Rendered | None:
    """The ledger's `render`, or `None` where it records none, or a `Failure` for one no attach
    wrote: `attach` writes a digest."""
    if value is None:
        return None
    digest = value.get("digest") if isinstance(value, dict) else None
    if not isinstance(digest, str):
        raise Failure(f"{path} is not a ledger `stayfixed attach` wrote: its 'render' is not one")
    return Rendered(digest)


def existing_ledger(root: Path) -> AttachLedger | None:
    """The ledger, or `None` when there is none: `attach` and `attach --check`, the two callers
    that may carry on without it, read it here, so the two end with one code on a ledger the run
    cannot take.

    Its path is held to the project before anything reads it: it is the one path `attach` writes
    inside the project that no other candidate names, so a `.stayfixed` committed as a link is
    refused here by name rather than by the walk that writes the ledger, after every write before
    it."""
    contained(root, ATTACH_LEDGER)
    if not fsops.is_file(root / ATTACH_LEDGER):
        return None
    return ledger(root)


def _allow_list(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The local settings document's `permissions` object, copied, and its allow list, read by
    `permissions.allow_list`: the reader `--check` reads the same file with, so the two refuse
    the same documents."""
    allow = allow_list(raw, LOCAL_SETTINGS)
    return dict(raw.get("permissions", {})), allow


def _merged_settings(document: str, diff: PermissionDiff, previous: AttachLedger | None) -> str:
    """The local settings document with the overlay's allow rules appended in order, the rules it
    no longer grants (`diff.withdrawn_allow`) taken out, and the hook entries an earlier attach
    recorded taken back out (`scaffold.withdraw_entries`).

    Only the entries and rules the earlier ledger names, and only where the file still holds them:
    the ledger and never the marker alone says which are stayfixed's.
    """
    recorded = previous.entries if previous is not None else {}
    held = owned_ids(document) if recorded else {}
    withdrawn = {id: event for id, event in recorded.items() if held.get(id) == event}
    if not diff.added_allow and not diff.withdrawn_allow and not withdrawn:
        # Nothing to add or take back, so nothing is touched. A rewrite here would reformat a file
        # the owner owns, on a run that changed nothing, and report itself as a write.
        return document
    raw = settings_document(document)
    permissions, allow = _allow_list(raw)
    allow = [rule for rule in allow if rule not in diff.withdrawn_allow]
    allow += [rule for rule in diff.added_allow if rule not in allow]
    if allow or permissions:
        permissions["allow"] = allow
        raw["permissions"] = permissions
    if diff.withdrawn_allow:
        # As `detach` leaves it: an allow list the take-back emptied is not what the file held.
        raw = _emptied(raw)
    text = settings_text(raw, LOCAL_SETTINGS) + "\n"
    return withdraw_entries(text, withdrawn) if withdrawn else text


def _codex_rule_texts(binding: Binding) -> tuple[tuple[str, str], ...]:
    """Each overlay standing rule's target under `.codex/rules/` and its text, read while the run
    is planned.

    Kept apart from the Claude settings merge because the two harnesses fail differently and a
    shared path would hide which. The list itself is `permissions.codex_rules`, so that
    `attach --check` reports exactly the files `attach` then writes rather than a second
    enumeration that could disagree with this one. Every source is read and decoded here and none
    while copying: a source that is not UTF-8, met while copying, would stop the copy after
    the exclude block and the rules before it were written, with the partial copies
    hidden by the block and no ledger for `detach` to remove them by.
    """
    texts: list[tuple[str, str]] = []
    for target, source in codex_rules(binding):
        # The overlay is the owner's, so its path may print, and through `quoted`, as the
        # directory holding it is printed when it cannot be listed (`permissions.codex_rules`): the
        # project's `codex/` carries `project.name`, which the repository chooses.
        with fsops.reading(quoted(str(source)), _nothing_written):
            texts.append((target, source.read_text(encoding="utf-8")))
    return tuple(texts)


def _nothing_written(sentence: str) -> Failure:
    """`fsops.reading`'s sentence about an overlay rule file, as the failure it ends a run in."""
    return Failure(f"{sentence}, so nothing was written")


def _record_project(binding: Binding, remote: str | None) -> None:
    """Put `remote` and the first-attach date into `projects/<name>/project.toml` where the record
    holds no such key at all, and write nothing else; a record that already names a remote is not
    written.

    The record is what the overlay keeps for the owner to read -- the remote the project was first
    bound with, the first attach's date, the `tags` the owner lists, whatever else they wrote --
    and binds nothing: the binding is this machine's (`stayfixed.binding`). So a key the record
    holds is left alone, whatever this checkout's `origin` says, and two machines attaching one
    project each keep their own binding without rewriting it; re-stamping the date on every attach
    would turn a fact into a timestamp of the last run. A key present with a value no one can use
    (an empty `remote`) is left too, since a second spelling of it would make the file invalid.
    The missing keys are prepended to the text as it stands, ahead of any table, so every byte the
    owner wrote stays. A record that cannot be read is never written over. `remote` is the `origin`
    as the machine's record kept it: none where a UTF-8 file cannot hold it.
    """
    if binding.recorded is not None or binding.fault is not None:
        return
    relative = f"{PROJECTS}/{binding.project}/{PROJECT_RECORD}"
    record = binding.overlay / relative
    held = _record_table(record)
    if held is None:
        return
    missing: dict[str, object] = {}
    if remote is not None and "remote" not in held:
        missing["remote"] = remote
    if "first_attach" not in held:
        missing["first_attach"] = datetime.date.today().isoformat()
    if not missing:
        return
    # `tomlout` and not an f-string: the value is a git remote URL, which is repository-authored
    # (principle 5), and one carrying a quote and a newline would write further keys into it.
    # Read with the file's own line endings, which `read_text` would translate.
    text = fsops.read_regular_text(record, newline="") if fsops.is_file(record) else ""
    fsops.write_within(binding.overlay, relative, tomlout.dumps({"": missing}) + text)


def _record_table(record: Path) -> dict[str, Any] | None:
    """The record's keys, `{}` where there is no record, and `None` where it cannot be read: that
    is `attach`'s `fault` already, so reaching here with one is a record swapped since."""
    if not fsops.is_file(record):
        return {}
    try:
        return read_record(record)
    except (OSError, UnicodeDecodeError, *UNPARSEABLE):
        return None


def _absent_directories(root: Path) -> tuple[str, ...]:
    """Which of `CREATED_DIRS` this repository does not have, asked before the first write.

    Asked *before*, because after the ledger is written `.stayfixed/local/` exists and the answer
    is not the one `detach` needs. `attach` therefore takes it at the top of the run and
    hands it down, the same way it hands down `previous`.

    `is_dir()` and not `exists()`: a path of this name that is a file, or a symlink to one, is
    not a directory this run created and `rmdir` would refuse it anyway — recording it would
    only put a name in the ledger that nothing can act on.

    A path the question cannot reach, below a committed `.codex` that links into a directory
    nobody may search, is not one either: every write of this run goes through the `O_NOFOLLOW`
    walk, which never reaches it, so this run cannot create it. Raised, the fault ended `attach`
    and `--check` in an internal error before the containment refusal that names the link.
    """
    return tuple(name for name in CREATED_DIRS if not _reached_directory(root / name))


def _reached_directory(path: Path) -> bool:
    """`fsops.is_dir`, and `True` for a path no write of this run can reach; see above."""
    try:
        return fsops.is_dir(path)
    except OSError:
        return True


def placed_paths(rules: Iterable[str]) -> tuple[str, ...]:
    """Every path an attach puts into the main checkout's work tree: the ledger, each rule copy in
    `rules` (`codex_rules`' targets for a run, the ledger's for `doctor`), and the settings file.
    These are what `attach.exclude` hides and holds inside the project, and what one rule holds:
    none tracked, each ignored once the block stands. The binding id is placed too, but under the
    git common directory, which git never tracks, so it is no path of the work tree.

    **The settings file always, because it names the id.** `claude plugin install --scope local`
    writes the plugin's `enabledPlugins` entry, `overlay-<id>@stayfixed-delivery-<id>`, into it on
    the first attach, and it holds that entry on every run after; a name a clone could read there is
    a name it could commit."""
    return (ATTACH_LEDGER, *rules, LOCAL_SETTINGS)


def named_placed(paths: tuple[str, ...]) -> str:
    """Placed paths as a refusal names them, each through `printed.quoted`."""
    return ", ".join(quoted(path) for path in paths)


def _write_ledger(
    root: Path, planned: AttachPlan, settings_keys: tuple[str, ...], render: Rendered | None
) -> None:
    """Record what this attach may remove again — the union with what an earlier one claimed.

    The union is not a nicety. A second attach against an unchanged overlay has an *empty*
    diff, because every rule is already present, so a ledger written from the diff alone would
    forget what the first one added and leave `detach` nothing to remove.

    **The earlier ledger arrives in the plan and is not read here**, which is a refusal's
    position and not a refactor. `ledger()` refuses a ledger naming files or settings keys
    `attach` could not have written, and read here that refusal would fire from the fourth write
    of the run, with the ignore region, the `.codex/rules/` copies and the settings merge already
    on disk and the committed ledger still there for `doctor._attached` to read as "attached".
    That is the shape `attach`'s own docstring says all its refusals must not have. `_plan` reads
    it once, above every write.

    Reading it once is also the more correct union: `attach` writes the ledger twice in a run,
    and the second call would otherwise union against the file the first call just wrote.
    """
    previous, binding = planned.previous, planned.binding
    rules = tuple(target for target, _ in planned.rules)
    # Only the rules the overlay grants now: one it no longer grants leaves the ledger whether or
    # not the settings file still held it, or a copy the owner types by hand later would be taken.
    granted = {*planned.diff.added_allow, *planned.diff.already_present}
    allow = [rule for rule in previous.allow if rule in granted] if previous else []
    allow += [rule for rule in planned.diff.added_allow if rule not in allow]
    # The same union as `allow` and `rules`, for the same reason sharpened once more: the second
    # attach in a repository finds every one of these directories already there and would record
    # none, so a ledger built from this run alone would leave `detach` unable to remove what the
    # first attach created. Ordered by `CREATED_DIRS` rather than by either input, so the written
    # list is deepest-first whatever order it was unioned in.
    made = set(previous.directories if previous is not None else ()) | set(planned.absent)
    document = {
        "format": LEDGER_FORMAT,
        "store": str(binding.store),
        "allow": allow,
        # No hook entry is merged any more, and the settings file this run writes has taken back
        # every one the earlier ledger recorded.
        "entries": {},
        # Only this run's copies: the ones the earlier ledger named and the overlay no longer holds
        # were removed before any ledger is written (`planned.dropped`), so none is left unrecorded.
        "rules": list(rules),
        "settings_keys": list(settings_keys),
        "directories": [name for name in CREATED_DIRS if name in made],
        # The digest, never the id and never a path on this machine (`render.Rendered`).
        "render": None if render is None else {"digest": render.digest},
    }
    fsops.write_within(root, ATTACH_LEDGER, json.dumps(document, indent=2, sort_keys=True) + "\n")


def _group_directories(binding: Binding, config: Config) -> list[str]:
    """Every directory this project's groups need inside the overlay, as one spelling.

    One list for the check and for the write both, so the refusal above every write and the
    `O_NOFOLLOW` walk that does the writing cannot come to disagree about which paths they are
    talking about. `common/memory` is not here — it is shared across projects and `overlay
    create` ships it — and skipping it in one of the two would be the first way they drift. Nor is a
    name in the tag namespace: the composed store links none (`memory.store.reserved`).
    """
    return [
        f"{PROJECTS}/{binding.project}/{STORE_DIR}/{group}/{_INSIDE}"
        for group in config.memory.groups
        if group != COMMON_GROUP and not group.startswith(TAG_LINK_PREFIX)
    ]


def _check_groups(binding: Binding, config: Config) -> None:
    """Refuse a `memory.groups` entry that leaves this project's share of the overlay — first.

    `memory.groups` is repository-authored (principle 5) and reaches no guard of its own —
    `config/paths.py` says so in as many words, and leaves the containment to the module that
    consumes the field. This module was calling it, and calling it too late: the refusal came
    out of `_prepare_store`, which runs after the ignore region, the `.codex/rules/` copies, the
    settings merge, the ledger **and** the overlay's binding record. So a clone committing
    `groups = ["../../escape"]` got `attach` to write five artifacts and exit 2, with
    `doctor._attached` — which keys on the ledger existing — then reporting the repository
    attached and the binding *bound*, because the record had been written too.

    Hoisting it here is not only a reordering: it is this project's own two-stage rule, which
    `attach` was skipping for this one path. `config.paths.contained` "decides whether a
    configured path *may* be written — it gives a user-facing refusal and catches a committed
    symlink", and `fsops.mkdirs_within` then does the write through an `O_NOFOLLOW` walk so a
    component that becomes a symlink *after* the check cannot redirect it. `attach` had only the
    second half, which is why its user-facing refusal arrived at write time.

    `resolved_root` is passed because this validates many paths against one root, which is the
    parameter's documented reason for existing.
    """
    resolved = binding.overlay.resolve()
    for relative in _group_directories(binding, config):
        try:
            contained(binding.overlay, relative, resolved_root=resolved)
        except PathUnasked as exc:
            raise Refusal(GROUP_UNASKED.format(fault=exc.fault)) from exc
        except PathEscape as exc:
            # The entry itself is repository-authored, so it is refused rather than quoted back.
            raise Refusal(GROUP_ESCAPES) from exc


def _prepare_store(binding: Binding, config: Config) -> None:
    """Create this project's own group directories in the overlay.

    The composed store links each one (`memory.composed`), and `memory.store` reads a group whose
    target does not exist as an empty one, so the native writer's notes would have no group.

    **The `UnsafePath` arm is the floor under `_check_groups` and is not dead.** A spelling that
    escapes was already refused above every write, so that half reaching here means the hoist
    drifted. The other half cannot be hoisted and should not be: `contained` asks the filesystem
    a question and this walk asks it again at the moment of writing, so a component of the
    overlay that became a symlink in between refuses here and nowhere earlier. That is the
    interval the `O_NOFOLLOW` walk exists for, and it is the one remaining way this refusal can
    arrive after a write.
    """
    for relative in _group_directories(binding, config):
        try:
            fsops.mkdirs_within(binding.overlay, relative)
        except UnsafePath as exc:
            raise Refusal(GROUP_ESCAPES) from exc


# Said where the repository is bare: git names no main checkout, the one whose
# `settings.local.json` Claude Code reads from every worktree and the overlay's plugin is installed
# from, and the common directory's parent is no checkout at all.
NO_MAIN_CHECKOUT = (
    "cannot tell which checkout is this repository's main one: the repository is bare, so git "
    "names none, and the overlay's plugin is installed from the main checkout; nothing was "
    "changed. Attach from a clone with a working tree of its own"
)


def main_checkout_of(root: Path) -> Path:
    """This repository's main checkout (`main_checkout_or_none`), or `NO_MAIN_CHECKOUT` in a bare
    repository, where git names none."""
    main = main_checkout_or_none(root)
    if main is None:
        raise Refusal(NO_MAIN_CHECKOUT)
    return main


def _keys_in(document: str) -> tuple[str, ...]:
    """The settings keys `attach` owns that a settings document holds."""
    return (POINTER_KEY,) if POINTER_KEY in settings_document(document) else ()


def _unpoint(root: Path) -> bool:
    """Take `POINTER_KEY` out of the main checkout's settings file, whether it was there."""
    document = settings_document(local_document(root))
    if document.pop(POINTER_KEY, None) is None:
        return False
    fsops.write_within(root, LOCAL_SETTINGS, settings_text(document, LOCAL_SETTINGS) + "\n")
    return True


def _point(root: Path, store: Path) -> bool:
    """Write `POINTER_KEY` naming `store` into the main checkout's settings file, whether it was
    written: the file is left alone where it already names `store`. Asked after the placed-path rule
    has passed for that file (`_carry_out`), since the path names the whole binding id."""
    document = settings_document(local_document(root))
    if document.get(POINTER_KEY) == str(store):
        return False
    document[POINTER_KEY] = str(store)
    fsops.write_within(root, LOCAL_SETTINGS, settings_text(document, LOCAL_SETTINGS) + "\n")
    return True


@dataclass(frozen=True)
class AttachPlan:
    """What `attach` decided before its first write, and all its writes are made from.

    `_plan` reads, decodes and refuses; `_carry_out` takes this value and writes. So a refusal
    after the first write is not something a later edit can bring back by moving a line: a read
    the writes need is a field here, and filling it is `_plan`'s job.
    """

    config: Config
    binding: Binding
    diff: PermissionDiff
    previous: AttachLedger | None
    # Whether the notes are composed: `memory.mode` is `overlay`. Delivery does not ask.
    memory: bool
    absent: tuple[str, ...]
    # The settings document to write, or `None` when the merge leaves it as it is.
    settings: str | None
    carried: tuple[str, ...]
    # Every path this run places in the work tree (`placed_paths`), and the exclude block that hides
    # them, or `None` when the owner's own excludes hide them all.
    placed: tuple[str, ...]
    hidden: exclude.ExcludeWrite | None
    # Each `.codex/rules/` target and the text to copy there.
    rules: tuple[tuple[str, str], ...]
    # The rule copies the earlier ledger names that the overlay no longer holds, removed by the run.
    dropped: tuple[str, ...]
    # What the rendered plugin carries, read from the overlay (`render.read_parts`).
    parts: dict[str, Part]


def attach(
    root: Path,
    *,
    store: Path | None,
    machine: Path | None,
    runner: Runner,
    owner: Owner | None = None,
    project: str | None = None,
) -> Attached:
    """Bind this repository to the overlay, merge the allow rules it grants, render and install
    its executable parts, and compose its notes.

    The main checkout first, whichever worktree this runs from, and every read and write after
    that is the main checkout's (`main_checkout_of`); a bare repository's worktree refuses there.
    Then the order below is the order they are enumerated in: read the binding, which already
    refuses a store outside the machine-recorded overlay; compute the diff, which gates nothing,
    since the overlay is the owner's and what it grants is shown rather than refused; refuse a
    `memory.groups` entry that leaves this project's share of the overlay; read the existing
    ledger, which refuses one no attach could have written; ask git what it already hides, which
    refuses a `check-ignore` with no answer, a placed path that leaves the project and a symlinked
    or unwritable exclude file; read the overlay's rule sources and the parts the plugin carries,
    which the writes below would otherwise read for themselves; then write the exclude block,
    refuse a placed path git would still not ignore (`exclude.NOT_IGNORED`), and only then write
    any file the block hides. The `memory.groups` containment is asked only of a repository whose
    `memory.mode` is `overlay`, whose notes are composed; delivery does not depend on the mode.

    **The split is what holds that order.** `_plan` reads and refuses and returns an
    `AttachPlan`; `_carry_out` takes only that value and writes. A read the writes need is a
    field of the plan, so it cannot drift below the first write the way the rule sources and the
    worktree listing each once did.

    **Neither a missing `origin` nor one the records do not name refuses.** The binding is the id
    `stayfixed.binding` writes into the git common directory, which no clone carries, and the
    machine's record of it; the remote decides nothing, so it is a note (`NO_ORIGIN_NOTE`,
    `memory.store.origin_note`).

    The binding is written before the composed store, the id and the machine's record first,
    because the store is named by the id and resolves only for a bound checkout. The render follows
    the binding, since it is named by the id, and is installed with two idempotent `claude plugin`
    calls on every run; the ledger records it once they succeed, and a call that fails exits 1 with
    the exclude block standing, so a re-run completes.

    `runner` is keyword-**required** rather than defaulted so that no test can reach a real
    `claude`. `owner` is the owner's layer the command resolved, which the one load
    takes (`config.loader.loads`' own). `project` is `--project`, which names the project of a
    repository with no `stayfixed.toml` (`configured`).
    """
    main = main_checkout_of(root)
    planned = _plan(main, store=store, machine=machine, owner=owner, project=project)
    return _carry_out(main, planned, machine=machine, runner=runner, owner=owner)


def gates(root: Path, config: Config, binding: Binding) -> PermissionDiff:
    """The refusals `attach` meets past the binding, in the order it meets them, and the diff read
    between them, so `_plan` and `attach --check` take one order and cannot come to disagree about
    it.

    **No refusal is about what the overlay grants.** The allow rules and the executable parts are
    the owner's, written by the owner and the owner's agents, neither of them this delivery's
    adversary, so `attach` shows them and proceeds (`Attached`) rather than asking for a flag.
    """
    # Beside the binding's own refusals: a `project.name` no directory under the overlay can
    # carry leaves the binding record and the group directories nowhere to go, and the
    # overlay's sources read under it answer "none" rather than refusing, so nothing below
    # would ask before writing.
    refuse_unless_share_can_exist(binding, config)
    # A record that cannot say which tags it lists would read as none, and the run would take back
    # what the tags delivered; the notes of a session take that, a write run does not.
    if (fault := record_fault(binding.overlay, binding.project)) is not None:
        raise Refusal(f"{fault}; nothing was written")
    # The diff, read in the run's order: it refuses a settings file the merge could not read.
    diff = diff_permissions(root, binding)
    # The check about the notes, asked only where they are composed.
    if config.memory.mode == OVERLAY_MODE:
        refuse_unless_share_holds(binding, config)
    return diff


def configured(
    root: Path, project: str | None, *, machine: Path | None, owner: Owner | None
) -> tuple[Config, str]:
    """The run's one `Config`, its project chosen where the repository has no `stayfixed.toml`
    (`binding.choose_project`, asked only then), and where the project's name came from
    (`binding.BY_FILE` or the phrase of the way it was chosen). `project` is `--project`, refused
    beside the file, which names the project already."""
    chosen: list[Chosen] = []

    def unnamed() -> str:
        chosen.append(choose_project(root, project, machine=machine))
        return chosen[0].name

    config = command_config(root, machine=machine, owner=owner, unnamed=unnamed)
    if project is not None and not chosen:
        raise Refusal(NAMED_BY_FILE)
    return config, chosen[0].source if chosen else BY_FILE


def _plan(
    root: Path,
    *,
    store: Path | None,
    machine: Path | None,
    owner: Owner | None,
    project: str | None,
) -> AttachPlan:
    """Every read, decode and check `attach` makes, in the order `attach` enumerates them, and
    nothing written: what it returns is all `_carry_out` may act on. `gates` and `plan_writes` are
    what `--check` asks too, so the preview stops on every refusal the run makes, with the same
    code and line, by calling what the run calls."""
    # One load for the whole run, handed to `read_binding` rather than left for it to make a
    # second of: a `--check` that read two documents reports the wrong thing, while an `attach`
    # that reads two writes under the wrong one.
    config, _ = configured(root, project, machine=machine, owner=owner)
    binding = read_binding(root, store=store, machine=machine, config=config)
    diff = gates(root, config, binding)
    return plan_writes(root, config, binding, diff)


def refuse_unless_share_holds(binding: Binding, config: Config) -> None:
    """Refuse a binding this project's share of the overlay cannot hold: a `memory.groups` entry
    that leaves the share.

    Asked in the run's gates (`gates`), above every write, by `attach` and by `attach --check`
    alike, so the two end alike on it.
    """
    _check_groups(binding, config)


def plan_writes(root: Path, config: Config, binding: Binding, diff: PermissionDiff) -> AttachPlan:
    """The rest of `_plan`: every read and refusal `attach` makes past its gates, and nothing
    written. The ledger, the settings merge, what git already hides and the exclude block, the
    overlay's rule sources and the parts the rendered plugin carries, in that order.

    `attach --check` calls it too and drops the plan, which is how the preview meets every one of
    these refusals with the run's code and line: each read here was once left out of the preview,
    and `--check` answered clean over a checkout the run then stopped on.
    """
    previous = existing_ledger(root)
    memory = config.memory.mode == OVERLAY_MODE
    # Above every write, because the first of them creates `.stayfixed/local/` and the answer
    # would then be wrong by exactly the directory this run brought into existence.
    absent = _absent_directories(root)
    # The settings merge is computed here, before any write, so a file it cannot read stops the
    # run while nothing is written.
    document = local_document(root)
    if previous is not None:
        diff = withdrawing(diff, previous.allow, _allow_list(settings_document(document))[1])
    merged = _merged_settings(document, diff, previous)
    written = merged != document
    placed = placed_paths(target for target, _ in codex_rules(binding))
    # One rule for every placed path: none tracked, asked here above every write, and each ignored,
    # asked once the block stands (`_carry_out`).
    if found := exclude.tracked(root, placed):
        raise Refusal(exclude.TRACKED.format(paths=named_placed(found)))
    # What git already hides decides the `info/exclude` block: a line for each path `attach` places
    # that the owner's own excludes do not hide (`exclude.unhidden_by_owner`). It can refuse — git
    # cannot answer, a path leaves the project, the exclude file is a symlink — and each refusal is
    # made while nothing has been written.
    hidden = exclude.planned_block(root, placed)
    # The reads the writes below would otherwise make for themselves, each of which can refuse
    # after the first write: the overlay's rule sources (a file that is not UTF-8) and what the
    # rendered plugin carries (a hook file of a shape it cannot read, a skill that cannot be read).
    rules = _codex_rule_texts(binding)
    kept = {target for target, _ in rules}
    dropped = tuple(rule for rule in previous.rules if rule not in kept) if previous else ()
    for rule in dropped:
        # The removal's walk, asked here as the writes' is: a link on the way refuses first.
        contained(root, rule, allow_final_symlink=True)
    parts = read_parts(binding.overlay, binding.project)
    return AttachPlan(
        config=config,
        binding=binding,
        diff=diff,
        previous=previous,
        memory=memory,
        absent=absent,
        settings=merged if written else None,
        # What an earlier attach left in the settings file, carried into the ledger written before
        # the composed store, so that a run stopping on the way still leaves `detach` able to
        # remove it. Read off the document this run leaves there.
        carried=_keys_in(merged),
        placed=placed,
        hidden=hidden,
        rules=rules,
        dropped=dropped,
        parts=parts,
    )


def _carry_out(
    root: Path, planned: AttachPlan, *, machine: Path | None, runner: Runner, owner: Owner | None
) -> Attached:
    """Write what `_plan` decided: the exclude block first, then ask git whether every placed path
    is ignored, and only then any file the block hides, so none is ever where git would show it —
    the settings file Claude Code writes the plugin's `enabledPlugins` entry into among them,
    before the first `claude plugin` call.

    What is still asked here is asked of what this run has just written, and cannot be asked
    before it: whether git ignores each placed path once the block stands, and whether the store
    resolves once the composed store stands. A write that itself fails is the other way this can
    stop after the first write.
    """
    config, binding, previous = planned.config, planned.binding, planned.previous
    if planned.hidden is not None:
        exclude.write(planned.hidden)
    # The rule's second half: a `.gitignore` re-including a placed path (`!`) outranks the block.
    if shown := exclude.unignored(root, planned.placed):
        raise Refusal(exclude.NOT_IGNORED.format(paths=named_placed(shown)))
    for target, text in planned.rules:
        fsops.write_within(root, target, text)
    # As `detach` removes a recorded copy: Codex reads whatever stays there as a standing rule.
    for rule in planned.dropped:
        if fsops.is_file(root / rule):
            fsops.remove_within(root, rule)
    rules = tuple(target for target, _ in planned.rules)
    written = planned.settings is not None
    if planned.settings is not None:
        fsops.write_within(root, LOCAL_SETTINGS, planned.settings)
    # The pointer is recorded before it is written, so a run that stops on the way leaves `detach`
    # a record of it; with no notes composed, what an earlier attach left there stays recorded.
    carried = (POINTER_KEY,) if planned.memory else planned.carried
    recorded = previous.render if previous is not None else None
    _write_ledger(root, planned, carried, recorded)
    # The binding: the id in the git common directory and the machine's record of it, then the
    # overlay's record where it has none. Before the composed store, which the id names and which
    # resolves only for a bound checkout, and before the render, which the id names.
    id = ensure_id(root)
    bound = record(root, binding.project, binding.remote)
    _record_project(binding, bound.origin)
    # The mode, resolved again now that the binding is recorded: the overlay's project layer is
    # read for a bound checkout only, so a first attach's plan could not see a mode set there. A
    # repository with no `stayfixed.toml` is named the project just bound (`configured`).
    config = command_config(root, machine=machine, owner=owner, unnamed=lambda: binding.project)
    memory = config.memory.mode == OVERLAY_MODE
    if memory:
        refuse_unless_share_holds(binding, config)
        carried = (POINTER_KEY,)
    # What ran before this render, read out of the render directory before it is rewritten, and
    # what will run after it, read out of the parts: the screen's executable diff.
    before, after = _carried_in(delivery_directory(id)), _carried(planned.parts)
    rendered = write_render(id, planned.parts)
    # Installed on every run, since both calls are idempotent: what Claude Code knows is its own
    # state, which a copy's detach or a lost id can take away whatever this ledger says. A call
    # that fails exits 1 with no render recorded and the exclude block standing, so a re-run
    # completes.
    if (failed := _install(id, root, runner)) is not None:
        _write_ledger(root, planned, carried, None)
        raise Failure(failed)
    if not memory:
        # Out of overlay mode, the pointer an earlier attach recorded and the composed store it
        # named are taken back, as `detach` takes them: left, the harness would go on reading the
        # overlay's notes and writing into them.
        if previous is not None and POINTER_KEY in previous.settings_keys and _unpoint(root):
            written, carried = True, ()
        withdraw_composed(id)
    _write_ledger(root, planned, carried, rendered.rendered)
    if memory:
        _prepare_store(binding, config)
        # The composed store, rebuilt, and the one key that points the harness at it, in the main
        # checkout's settings file, whose placed-path rule passed above; the ledger already records
        # the key (`carried`). The project is the one this machine's binding record names, read
        # back after `record` above wrote it, never `[project] name` on its own.
        project = (bound_project(root) or bound).project
        written = _point(root, build_composed(binding.overlay, project, id)) or written
        render_missing_index(root, config, machine=machine)
    notes: list[str] = []
    if binding.fault is not None:
        notes.append(binding.fault)
    if binding.bound is not None and binding.bound != binding.project:
        notes.append(REBOUND.format(earlier=quoted(binding.bound), project=quoted(binding.project)))
    if binding.remote is None:
        notes.append(NO_ORIGIN_NOTE)
    elif binding.note is not None:
        notes.append(binding.note)
    return Attached(
        written,
        rules,
        binding.state != BOUND,
        tuple(notes),
        short(id),
        origin=None if binding.remote is None else without_userinfo(binding.remote),
        project=binding.project,
        added=after.without(before),
        removed=before.without(after),
        allow_added=planned.diff.added_allow,
        allow_withdrawn=planned.diff.withdrawn_allow,
    )


def _named_under(files: Iterable[str], directory: str) -> tuple[str, ...]:
    """The first name below `directory/` of each of `files`, paths relative to the plugin, sorted
    and each once: a skill is its directory, an agent its file."""
    prefix = f"{directory}/"
    return tuple(
        sorted({path[len(prefix) :].split("/")[0] for path in files if path.startswith(prefix)})
    )


def _hook_entries(text: str) -> tuple[tuple[str, str], ...]:
    """Each entry of a rendered hook file as `(event, command)`, in its order; nothing for a file
    of any other shape, since the screen is a convenience and refuses nothing."""
    try:
        hooks = json.loads(text).get("hooks", {})
    except (ValueError, AttributeError, RecursionError):
        return ()
    found: list[tuple[str, str]] = []
    for event, groups in hooks.items() if isinstance(hooks, dict) else ():
        for group in groups if isinstance(groups, list) else ():
            entries = group.get("hooks", []) if isinstance(group, dict) else []
            for entry in entries if isinstance(entries, list) else ():
                if isinstance(entry, dict) and isinstance(entry.get("command"), str):
                    found.append((str(event), entry["command"]))
    return tuple(dict.fromkeys(found))


def _carried(parts: Mapping[str, Part]) -> Carried:
    """What the parts `render.read_parts` read carry."""
    hooks = parts[HOOK_FILE].text if HOOK_FILE in parts else ""
    return Carried(_hook_entries(hooks), *(_named_under(parts, name) for name in COPIED))


def _carried_in(directory: Path) -> Carried:
    """What the render directory the last run left carries, or nothing where it holds no render
    or cannot be read: asked after the first write, so it answers rather than refusing, and a
    directory it cannot read shows every part as added."""
    plugin = directory / PLUGIN_DIRECTORY
    try:
        hooks = fsops.read_regular_text(plugin / HOOK_FILE)
    except (OSError, UnicodeDecodeError):
        hooks = ""
    files: list[str] = []
    for name in COPIED:
        try:
            files += [f"{name}/{child}" for child in os.listdir(plugin / name)]
        except OSError:
            continue
    return Carried(_hook_entries(hooks), *(_named_under(files, name) for name in COPIED))


# Said where a `claude plugin` call did not succeed. Its code and nothing it printed: what Claude
# Code prints names the plugin, and the plugin's name carries the whole binding id.
NOT_INSTALLED = (
    "`claude plugin {verb}` did not succeed (exit {code}), so the overlay's hooks, skills and "
    "agents are rendered but not installed; run `stayfixed attach` again"
)


def _install(id: str, main: Path, runner: Runner) -> str | None:
    """Register the render as a marketplace of the main checkout and install its plugin there, or
    say which call failed. Run from the main checkout, whose `settings.local.json` Claude Code reads
    from every worktree and writes the plugin's entry into."""
    added = runner.launch(filled(PLUGIN_MARKETPLACE_ADD_LOCAL, str(delivery_directory(id))), main)
    if added.code != 0:
        return NOT_INSTALLED.format(verb="marketplace add", code=added.code)
    done = runner.launch(
        filled(PLUGIN_INSTALL_LOCAL, f"{plugin_name(id)}@{marketplace_name(id)}"), main
    )
    if done.code != 0:
        return NOT_INSTALLED.format(verb="install", code=done.code)
    return None


# Said where the main checkout's settings file still names the plugin once `detach` asked Claude
# Code to forget it: the keys left, never their names, which carry the whole binding id.
STILL_NAMED = (
    "the main checkout's `.claude/settings.local.json` still names the overlay's plugin under "
    "{keys}, so the exclude block, the ledger and the render were kept; run `stayfixed detach` "
    "again once `claude plugin` runs here"
)
# Said where the render directory could not be removed once Claude Code was told to forget it.
RENDER_STAYED = (
    "the overlay's rendered plugin under this machine's data directory could not be removed "
    "({fault}); the ledger was kept, so `stayfixed detach` can be run again"
)
# The two keys of the settings file Claude Code writes the plugin's entries under: `install` the
# plugin's, `marketplace add` its marketplace's, each named by the whole binding id.
ENABLED_PLUGINS = "enabledPlugins"
KNOWN_MARKETPLACES = "extraKnownMarketplaces"


def _plugin_keys(main: Path) -> dict[str, tuple[str, ...]]:
    """The names under each of the two keys in the main checkout's settings file."""
    document = settings_document(local_document(main))
    return {
        key: tuple(document[key]) if isinstance(document.get(key), dict) else ()
        for key in (ENABLED_PLUGINS, KNOWN_MARKETPLACES)
    }


def _withdraw_plugin(
    id: str | None, main: Path, held: dict[str, tuple[str, ...]], runner: Runner
) -> None:
    """Ask Claude Code, from the main checkout, to forget the plugin `id` names and its marketplace,
    each where `held` says that checkout's settings file names it; then read the file again and
    stop with `STILL_NAMED` while a name under either key names a `stayfixed-delivery-`
    marketplace, which needs no id. The file decides, never the exit codes: what must hold before
    the exclude block goes is that the file names no delivery.

    The calls leave the two keys behind, emptied. A file holding those and nothing else is one the
    delivery alone filled, and it goes here: kept, it is the trace `git status` shows once the
    exclude block is gone, in a checkout no global exclude hides it in. A file holding anything
    more stays as it is."""
    if id is not None:
        plugin = f"{plugin_name(id)}@{marketplace_name(id)}"
        if plugin in held[ENABLED_PLUGINS]:
            runner.launch(filled(PLUGIN_UNINSTALL_LOCAL, plugin), main)
        if marketplace_name(id) in held[KNOWN_MARKETPLACES]:
            runner.launch(filled(PLUGIN_MARKETPLACE_REMOVE, marketplace_name(id)), main)
    named = _plugin_keys(main).items()
    left = [key for key, names in named if any(MARKETPLACE_PREFIX in name for name in names)]
    if left:
        raise Failure(STILL_NAMED.format(keys=", ".join(f"`{key}`" for key in left)))
    document = settings_document(local_document(main))
    if document and all(
        key in (ENABLED_PLUGINS, KNOWN_MARKETPLACES) and value == {}
        for key, value in document.items()
    ):
        fsops.remove_within(main, LOCAL_SETTINGS)


def _remove_render(directory: Path) -> None:
    """Remove the render directory whole (`render.remove_tree`), or say why it stayed."""
    try:
        remove_tree(directory)
    except OSError as exc:
        raise Failure(RENDER_STAYED.format(fault=fsops.said(exc))) from exc


@dataclass(frozen=True)
class Detached:
    """What one `detach` withdrew. The binding record is not on this list, on purpose."""

    allow_removed: tuple[str, ...]
    entries_removed: tuple[str, ...]
    rules_removed: tuple[str, ...]
    settings_keys_removed: tuple[str, ...]
    directories_removed: tuple[str, ...] = ()
    exclude_block_removed: bool = False
    # The rendered plugin's render directory was removed, Claude Code having been told to forget
    # whatever of it the main checkout's settings file named.
    delivery_removed: bool = False
    # The composed store was kept, its links taken, because it holds a file that is not a link: a
    # note the harness wrote there, which nothing of stayfixed's placed.
    store_kept: bool = False


def _emptied(raw: dict[str, Any]) -> dict[str, Any]:
    """The settings document with the containers `detach` just emptied taken out again.

    An empty `permissions.allow` is not what the file looked like before `attach`, and the round
    trip this command promises is measured in bytes: `tests/attach/test_detach.py` snapshots
    every file under the root and compares. `apply_entries` already does the same for `hooks`.
    """
    permissions = raw.get("permissions")
    if isinstance(permissions, dict):
        if permissions.get("allow") == []:
            permissions.pop("allow")
        if not permissions:
            raw.pop("permissions")
    return raw


@dataclass(frozen=True)
class SettingsWithdrawal:
    """What `detach` takes out of the settings file, decided before its first withdrawal.

    `text` is the file's new content, `""` when nothing is left and the file goes, and `None`
    when nothing of stayfixed's is in it and it is not written at all: a rewrite of a file the
    withdrawal leaves as it was reformats somebody's file, and through a `.claude` linked in from
    elsewhere it is a write `detach` has no business making.
    """

    removed: tuple[str, ...]
    text: str | None


def _planned_settings(root: Path, recorded: AttachLedger) -> SettingsWithdrawal:
    """Take exactly the recorded rules, the recorded entries and the pointer key back out.

    The allow rules come from the ledger and never from a guess at their content: that is the
    whole reason the ledger exists. So do the hook entries an earlier release merged, through
    `scaffold.withdraw_entries`, which takes the ones the ledger names and never one by its marker
    alone — foreign entries keep their matcher and their position, and a group that mixes the two
    is split rather than dropped.
    """
    document = local_document(root)
    if not document.strip():
        return SettingsWithdrawal((), None)
    raw = settings_document(document)
    try:
        # The copy and the comparison recurse as the encoder does, and on Python 3.14 under a
        # reduced stack either overflows for a document the parser read: the reader's refusal of
        # one nested too deep, never an internal error.
        held = json.loads(json.dumps(raw))
        permissions, allow = _allow_list(raw)
        removed = tuple(rule for rule in recorded.allow if rule in allow)
        if permissions:
            permissions["allow"] = [rule for rule in allow if rule not in recorded.allow]
            raw["permissions"] = permissions
        for key in recorded.settings_keys:
            raw.pop(key, None)
        # Through `settings_text`, as every write-back of a parsed settings document: on Python
        # 3.12 an indented encode stops near 994 levels, under what the parser read.
        emptied = settings_text(_emptied(raw), LOCAL_SETTINGS) + "\n"
        remaining = json.loads(withdraw_entries(emptied, recorded.entries))
        unchanged = remaining == held
    except RecursionError:
        raise ParserLimitError(f"{LOCAL_SETTINGS} {NESTED}") from None
    if unchanged:
        return SettingsWithdrawal(removed, None)
    # `{}` is not what the file looked like before `attach`; a file holding nothing is one this
    # command created and is the last thing it takes away.
    text = settings_text(remaining, LOCAL_SETTINGS) + "\n" if remaining else ""
    return SettingsWithdrawal(removed, text)


def _withdraw_settings(root: Path, planned: SettingsWithdrawal) -> tuple[str, ...]:
    """Write what `_planned_settings` decided."""
    if planned.text:
        fsops.write_within(root, LOCAL_SETTINGS, planned.text)
    elif planned.text is not None:
        fsops.remove_within(root, LOCAL_SETTINGS)
    return planned.removed


def _withdraw_directories(root: Path, recorded: AttachLedger) -> tuple[str, ...]:
    """Remove the directories this repository did not have before the attach, and only those.

    The last step of a detach, after the ledger itself is gone, because `.stayfixed/local/` holds
    it. `docs/cli.md` promises "an attach and a detach leave the tree byte-for-byte as it was",
    and directories are part of the tree, though a snapshot that filters on `is_file()` cannot
    see them.

    **Three things keep this from deleting somebody's directory.** It walks `CREATED_DIRS`, a
    closed list, and keeps only what the ledger named — so a committed ledger can shorten the
    list, never extend it. The ledger names only what `_absent_directories` found missing before
    the first write, so a directory that was already there is never on it. And the removal is
    `rmdir`: a directory holding anything else at all — the owner's own `.claude/settings.json`,
    a `.codex/rules/` file they wrote by hand, a file some other tool left — survives, and its
    parents then survive with it because they are not empty either.

    `ENOTEMPTY` is therefore an ordinary outcome and not a failure, and it is the one this
    `except OSError` is written for: `fsops.rmdir_within` already contains the walk to `root` and
    tolerates an absent target, so what is left is "not empty" and "not permitted", and neither
    is a reason to fail a detach that has already put everything it recorded back.

    Two other things land in the same arm and are meant to. `fsops.UnsafePath` subclasses
    `OSError`, so a component of one of these paths that became a symlink between the check and
    the call is caught here too — the walk refuses it, the directory stays, and the detach
    finishes; that is the same answer "not empty" gets, and the right one for a path this
    function was never going to be able to remove safely. A `PermissionError` is the third, and
    is a fact about the filesystem rather than about the detach.
    """
    removed: list[str] = []
    for name in CREATED_DIRS:
        # `is_dir()` before the call and not only the ledger's say-so: `rmdir_within` tolerates
        # an absent target, so without this a directory the run never created — `.claude/`, when
        # the overlay grants nothing to merge — would be reported as one this detach removed.
        if name not in recorded.directories or not fsops.is_dir(root / name):
            continue
        try:
            fsops.rmdir_within(root, name)
        except OSError:
            continue
        removed.append(name)
    return tuple(removed)


# Said when a path `detach` removes or rewrites is reached through a symlink: a directory on the
# way to it became one after the attach. Asked before the first withdrawal, because its removal
# would find that out after the settings file was withdrawn, as `internal error: UnsafePath`. The
# path is named by what it is, never by its spelling: a recorded rule copy's name is a ledger's,
# which a clone can commit.
LINKED_ON_THE_WAY = (
    "{what} is reached through a symlink ({where} is one now), and `detach` removes nothing "
    "through one, so nothing was withdrawn; replace the link with the directory it points at and "
    "run `stayfixed detach` again"
)


def _walked(root: Path, relative: str, *, what: str, where: str) -> None:
    """`fsops.check_within`, the removal's own walk, with its refusal said by name."""
    try:
        fsops.check_within(root, relative)
    except UnsafePath as exc:
        raise Refusal(LINKED_ON_THE_WAY.format(what=what, where=where)) from exc


def _refuse_unwithdrawable(
    root: Path, recorded: AttachLedger, settings: SettingsWithdrawal
) -> None:
    """Walk to every path the withdrawal writes or removes, before the first withdrawal: the
    settings file when it is rewritten, each recorded rule copy, and the ledger.

    The writes and removals are `fsops` walks that refuse a symlinked component, and asked first
    by them, the question would come after the settings file was already withdrawn.
    `fsops.check_within` is the walk, so the two cannot disagree; it stays the floor for a
    component that changes in between.
    """
    if settings.text is not None:
        _walked(root, LOCAL_SETTINGS, what=f"`{LOCAL_SETTINGS}`", where="`.claude`")
    for rule in recorded.rules:
        _walked(
            root,
            rule,
            what="a `.codex/rules/` copy this checkout's attach recorded",
            where="`.codex` or `.codex/rules`",
        )
    _walked(
        root,
        ATTACH_LEDGER,
        what=f"the ledger, `{ATTACH_LEDGER}`",
        where="`.stayfixed` or `.stayfixed/local`",
    )


def detach(root: Path, *, runner: Runner) -> Detached:
    """Remove exactly what `attach` added, reading the ledger for what that was, and withdraw the
    rendered plugin and the composed store, whose directories are derived from the binding id and
    never read from the ledger.

    The main checkout's, whichever worktree this runs from, since `attach` wrote there alone
    (`main_checkout_or_none`); in a bare repository's worktree git names no main checkout, `attach`
    installed nothing there, and this checkout's own parts are withdrawn. The plugin is withdrawn
    with `claude plugin uninstall` where the main checkout's settings file names the plugin and
    `marketplace remove` where it names the marketplace, through `runner`, after this run's own
    withdrawal from the settings file and before the exclude block goes, then the render directory
    where there is one. While the file still names the id once they ran, whatever they exited with,
    it is a `Failure` there (`STILL_NAMED`), with the exclude block, the ledger and the render kept,
    and a second `detach` finishes from the ledger. The id and this machine's record of it are
    kept, as the overlay's record is.

    It does **not** touch `projects/<name>/project.toml`. That record is the overlay's note of
    the project's first remote and first attach, for the owner to read, and binds nothing: the
    overlay's, not this checkout's.

    It reads no configuration: every path it withdraws is the ledger's, bounded by `ledger()`, or
    derived from the id.

    **What it may refuse on, and when.** Everything structural this function can know before its
    first withdrawal is asked before it: the main checkout, which is the only question here that
    needs `git` besides the id, the ledger (which refuses one no attach could have written), the
    settings document's own shape through
    `owned_ids`, the exclude block, what the settings file becomes (`_planned_settings`), and every
    path the withdrawal writes or removes, walked the way the write or removal walks it
    (`_refuse_unwithdrawable`). What is left after the first withdrawal is exactly what cannot
    precede it — a write that fails, and a component that changed between the check and the
    removal.
    """
    main = main_checkout_or_none(root)
    root = main if main is not None else root
    recorded = ledger(root)
    held = owned_ids(local_document(root))
    entries = tuple(sorted(id for id, event in recorded.entries.items() if held.get(id) == event))
    # The rendered plugin, named by the id and installed in the main checkout. Its render directory
    # is derived from the id and never read from the ledger, whose `store` and `render` a clone can
    # commit; asked here, before the first withdrawal, since the id is read through `git`.
    id = read_id(root)
    try:
        delivery = delivery_directory(id) if id is not None else None
    except Failure:
        # A `HOME` that names no home holds no render and no composed store.
        delivery = None
    # The `info/exclude` block is found above the first withdrawal for the same reason: `git`
    # names the file and a region opened twice refuses, and both are knowable now.
    hidden = exclude.withdrawn_block(root)
    settings = _planned_settings(root, recorded)
    # What the main checkout's settings file names, which decides each `claude plugin` call: read
    # here, so a file that cannot be read refuses while nothing is withdrawn.
    plugin = None if main is None else (id, main, _plugin_keys(main))
    _refuse_unwithdrawable(root, recorded, settings)
    allow_removed = _withdraw_settings(root, settings)
    rules_removed: list[str] = []
    for rule in recorded.rules:
        if fsops.is_file(root / rule):
            fsops.remove_within(root, rule)
            rules_removed.append(rule)
    # Before the exclude block goes: Claude Code takes the plugin's entries, which name the id, out
    # of the settings file the block hides, and it does so after this run's own withdrawal from
    # that file, which would otherwise write them back. A file that still names the id stops the
    # run here, with the exclude block, the ledger and the render kept.
    if plugin is not None:
        _withdraw_plugin(*plugin, runner)
    removed = False
    if delivery is not None and (fsops.is_dir(delivery) or fsops.is_symlink(delivery)):
        _remove_render(delivery)
        removed = True
    # The composed store the pointer named, derived from the id as the render is: its links, then
    # the directory where nothing else is left.
    store_kept = False
    if id is not None and delivery is not None:
        store_kept = not withdraw_composed(id)
    if hidden is not None:
        exclude.write(hidden)
    fsops.remove_within(root, ATTACH_LEDGER)
    # Last, because the ledger lives in one of them.
    directories = _withdraw_directories(root, recorded)
    return Detached(
        allow_removed,
        entries,
        tuple(rules_removed),
        recorded.settings_keys,
        directories,
        hidden is not None,
        removed,
        store_kept,
    )
