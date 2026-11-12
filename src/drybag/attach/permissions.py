"""What attaching would add to this project's local settings, and where it may read it from.

The sources are the `claude/` directory of each plate of the overlay (`config.plates`), the
machine owner's own files in the repository the machine file anchors. `.claude/settings.json` is
committed, so repository-controlled, and is read for nothing: committed settings that would widen a
permission are never merged. `.claude/settings.local.json` is read only to subtract.

The diff is allow rules alone; the overlay's hook entries reach a session through the plugin
`attach.render` renders, for which this module reads the hook files (`hook_groups`). An allow
rule's one witness is the ledger `write.py` keeps. `added_allow` comes out of the overlay and may
be printed; `already_present` comes out of `.claude/settings.local.json`, which a hostile clone
can commit, so `attach.check` reports only how many there were.
"""

from __future__ import annotations

import stat
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from drybag import fsops
from drybag.attach.binding import Binding, cannot_exist
from drybag.attach.items import CODEX_RULE, PROJECT_CLAUDE, fold
from drybag.config.plates import Plate, PlateKind
from drybag.errors import Failure
from drybag.fsops import read_regular_text
from drybag.harnesses import CLAUDE
from drybag.jsonobject import WRITTEN_PAST
from drybag.scaffold import (
    EntriesError,
    ParserLimitError,
    settings_object,
    settings_text,
)

# The project-local file `attach` owns outright, as the harness registry names it: the one file
# Claude Code reads that a repository keeps out of git (`.claude/settings.json` is never read).
(LOCAL_SETTINGS,) = CLAUDE.local_settings
PERMISSIONS_FILE = "permissions.json"
HOOKS_FILE = "hooks.json"
# Where Codex reads standing instructions.
CODEX_RULES = ".codex/rules"


@dataclass(frozen=True)
class PermissionDiff:
    """What `attach` would add to the allow rules, what is already there, and what it would take
    back: `withdrawn_allow`, filled by `withdrawing`, is a rule the previous ledger recorded that
    the overlay no longer grants and the settings file still holds."""

    added_allow: tuple[str, ...]
    already_present: tuple[str, ...]
    withdrawn_allow: tuple[str, ...] = ()

    @property
    def granted(self) -> frozenset[str]:
        """Every rule the overlay grants, added or already present."""
        return frozenset((*self.added_allow, *self.already_present))


def settings_document(text: str) -> dict[str, Any]:
    """The local settings file as an object, refusing a shape the merge could not read back: what
    a filter would drop here is somebody's own setting, and nothing would say it went."""
    return settings_object(text, LOCAL_SETTINGS)


def _read(path: Path, *, share: Path | None = None, label: str | None = None) -> str:
    """A file's text, or an empty string when there is no such file. `label` is how a refusal
    names a file the project names (`.claude/settings.local.json`, never its absolute path).

    `share` is the overlay's `projects/<name>` for a source under it, and only then: a path its
    spelling rules out (`binding.cannot_exist`) is a file the overlay does not have when the name, a
    repository's choice, picks out no directory there (`_names_no_directory`). Every other fault
    stays a `Failure`, which `doctor` reports as a warning: a path ruled out *below* a share that is
    a directory is the owner's own state, and read as absent it would strip the owner's entries; so
    is any fault under `common/` or `tags/<tag>/`. The project's own `.claude/` is never read this
    way, so a `.claude` that is a file stops `attach` before it writes.
    """
    with fsops.reading(label or path, Failure):
        try:
            # A regular file only: `.claude/settings.local.json` is a path a clone can commit, and
            # a link there to `/dev/zero` or to a FIFO would read for ever or wait.
            return read_regular_text(path)
        except FileNotFoundError:
            return ""
        except OSError as exc:
            if share is not None and cannot_exist(exc) and _names_no_directory(share):
                return ""
            raise


def _names_no_directory(share: Path) -> bool:
    """Whether `share`, the overlay's `projects/<name>`, is no directory, so nothing below it is
    the owner's and a path through it that cannot exist is one the overlay has no file at.

    Asked of the share itself, because `cannot_exist` does not say which component failed and only
    the share's answer is about the name; an absent `projects/` counts as an absent share. Every
    caller reaches this past a share that is absent or a directory (`attach` and `--check` refuse
    any other first, `binding.refuse_unless_share_can_exist`), so those are the answers that decide.
    """
    try:
        mode = share.stat().st_mode
    except FileNotFoundError:
        # No share, or no `projects/` above it: the overlay has no directory for this project.
        return True
    except OSError as exc:
        return cannot_exist(exc)
    return not stat.S_ISDIR(mode)


def allow_list(raw: dict[str, Any], label: str) -> list[str]:
    """The `permissions.allow` list of a settings document `settings_object` read, or a refusal.

    The one reader of that list, for `--check` and the real run alike, so `--check` refuses exactly
    the documents the real run refuses. An absent key is no rules; a present one must hold an
    object, then a list of strings, and `null` is neither. A shape this cannot read is a refusal,
    never a filter. `label` names the file in the refusal.
    """
    if "permissions" not in raw:
        return []
    permissions = raw["permissions"]
    if not isinstance(permissions, dict):
        raise EntriesError(f"{label}: 'permissions' is not an object")
    if "allow" not in permissions:
        return []
    allow = permissions["allow"]
    if not isinstance(allow, list) or not all(isinstance(rule, str) for rule in allow):
        raise EntriesError(f"{label}: 'permissions.allow' is not a list of strings")
    return list(allow)


DENIED_KEY = "deniedMcpServers"


DENIED_NOT_A_LIST = (
    f"{LOCAL_SETTINGS}: {DENIED_KEY} is not a list, so drybag writes and takes back no entry there"
)


def denied_list(raw: dict[str, Any]) -> list[Any] | None:
    """The `deniedMcpServers` list of a settings document: an absent key is no entries, and one
    holding anything but a list is `None`, a note (`DENIED_NOT_A_LIST`) under which no entry is
    written or taken back. Its entries stay as they are: what the owner wrote is never read for
    what it means."""
    denied = raw.get(DENIED_KEY, [])
    return list(denied) if isinstance(denied, list) else None


def _allow_rules(document: str, path: Path) -> tuple[str, ...]:
    """The `permissions.allow` list of one settings-shaped document, read by `allow_list`."""
    label = str(path)
    return tuple(allow_list(settings_object(document, label), label))


def hook_groups(path: Path, *, share: Path | None) -> dict[str, list[dict[str, Any]]]:
    """`event -> groups` out of a `hooks.json`-shaped document, refusing a shape it cannot read:
    each group's `hooks` a list, when it is there, of entries that each carry a command. A refusal
    and never a filter, since what a filter drops is an entry the owner put there on purpose.
    `share` is `_read`'s."""
    hooks = settings_object(_read(path, share=share), str(path)).get("hooks", {})
    if not isinstance(hooks, dict):
        raise EntriesError(f"{path}: 'hooks' is not an object")
    found: dict[str, list[dict[str, Any]]] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
            raise EntriesError(f"{path}: 'hooks.{event}' is not a list of entry groups")
        for group in groups:
            # Absent is no entries; `null`, or any other value that is not a list, is refused, as
            # `allow_list` refuses one where its list goes.
            entries = group.get("hooks", [])
            if not isinstance(entries, list):
                raise EntriesError(f"{path}: an entry group's 'hooks' is not a list")
            for entry in entries:
                if not (isinstance(entry, dict) and isinstance(entry.get("command"), str)):
                    raise EntriesError(f"{path}: an entry under {event} has no command")
        found[str(event)] = [dict(g) for g in groups]
    return found


def codex_rules(binding: Binding) -> tuple[tuple[str, Path], ...]:
    """Every standing-rule file `attach` would place under `.codex/rules/`, as (target, source).

    Enumerated here and copied in `write.py`, so `--check` names every file `attach` would place.
    Reporting and not gating: the overlay is the owner's own. The files are the winners of the
    plates' fold (`attach.items`), returned as pairs so the caller cannot pair them differently
    from the write. A directory this user cannot list, or whose entries cannot be asked about,
    fails as an unreadable rule file does in `write._codex_rule_texts`. The project's directory
    carries `project.name`, so its path prints through `quoted`.
    """
    winners = fold(binding.plates, CODEX_RULE, _unlisted).winners
    return tuple((f"{CODEX_RULES}/{name}", source) for name, source in winners.items())


def _unlisted(sentence: str) -> Failure:
    return Failure(f"{sentence}, so nothing was written")


def claude_sources(held: Sequence[Plate], name: str) -> tuple[tuple[Path, Path | None], ...]:
    """The per-harness file `name` of each of the plates `held`, in plate order, each with
    `_read`'s `share` where the project's plate has one: the sources of the permission diff and of
    the render's hook union."""
    return tuple(
        (
            plate.directory / PROJECT_CLAUDE / name,
            plate.directory if plate.kind is PlateKind.PROJECT else None,
        )
        for plate in held
    )


def local_document(root: Path) -> str:
    """The project's own `settings.local.json`, or an empty string when it has none."""
    return _read(root / LOCAL_SETTINGS, label=LOCAL_SETTINGS)


# Room for the one key `attach` adds to the text it writes back after the merge, the
# `autoMemoryDirectory` pointer at the composed store: the key's name and a path, and no path a
# filesystem resolves passes 4,096 bytes.
_FALLBACK_ROOM = 8 * 1024


def _refuse_unless_written_back(document: str) -> None:
    """Refuse a settings document whose write-back the next read would refuse: `attach` writes the
    file back indented, and a short document many levels deep grows by its depth on every line,
    past `fsops.REGULAR_READ_LIMIT`. Asked where `attach` and `--check` both read the file, before
    the first write, and of every document, since a later run that adds one rule writes it back.
    """
    text = settings_text(settings_document(document), LOCAL_SETTINGS)
    if len(text) + _FALLBACK_ROOM > fsops.REGULAR_READ_LIMIT:
        raise ParserLimitError(f"{LOCAL_SETTINGS} {WRITTEN_PAST}")


def diff_permissions(root: Path, binding: Binding) -> PermissionDiff:
    """What attaching `binding` would add to `root`, without writing a byte."""
    # This line is the whole of the committed-settings rule in the module docstring:
    # `.claude/settings.json` sits one name away from both sources and is not on it.
    sources = claude_sources(binding.plates, PERMISSIONS_FILE)
    granted = [
        rule
        for source, share in sources
        for rule in _allow_rules(_read(source, share=share), source)
    ]
    document = local_document(root)
    _refuse_unless_written_back(document)
    # Named by its project path, as every refusal of the project's own settings file is.
    held = set(_allow_rules(document, Path(LOCAL_SETTINGS)))
    added_allow = tuple(dict.fromkeys(rule for rule in granted if rule not in held))
    already = tuple(dict.fromkeys(rule for rule in granted if rule in held))
    return PermissionDiff(added_allow, already)


def withdrawing(
    diff: PermissionDiff, recorded: Iterable[str], held: Collection[str]
) -> PermissionDiff:
    """`diff` with the rules to take back: those `recorded` (the previous ledger's `allow`, the one
    witness of which rules are `attach`'s) that the overlay no longer grants
    (`PermissionDiff.granted`) and the settings file still `held`. A rule the owner added by hand
    is not recorded and stays.

    The ledger is a checkout file a branch can write, so it is no anchor against one: the worst a
    committed `allow` achieves is taking a permission away, one the owner typed included. `detach`
    accepts the same bound."""
    granted = diff.granted
    taken = tuple(dict.fromkeys(rule for rule in recorded if rule in held and rule not in granted))
    return replace(diff, withdrawn_allow=taken)
