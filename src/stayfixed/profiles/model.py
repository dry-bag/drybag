"""A stack profile as data, and the three words its checks are written in.

A profile is what stayfixed knows about one stack: which files say a repository is written in it
(`detect`), which paths its rules are about (`scope`), the prose (`rules.md`), the lines every
agent must have before its first command (`essentials`, the bullets of one marked section of
that prose), and its static checks. Nothing here knows which stack.
Adding a language adds a directory beside the shipped ones.

A shipped profile is stayfixed's own data. A fault in one is a defect in the build: it raises
`ProfileError` naming what is wrong, and is never skipped. A check that silently vanished would
read as a repository passing it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stayfixed.config.schema import PROJECT_NAME
from stayfixed.errors import Refusal
from stayfixed.findings import Severity
from stayfixed.fsops import UnsafePath, checked_components

CHECK_ID = re.compile(r"^[a-z][a-z0-9-]*\Z")
# The heading whose bullets are the essentials. The section is part of the rules, so the lines
# the `AGENTS.md` region hands every harness are the rules' own words, never a second copy.
ESSENTIALS = "## Before the first command"
_KEYS = frozenset({"detect", "scope", "check"})
_CHECK_KEYS = frozenset({"id", "kind", "level", "remedy", "locators"})
_LOCATOR_KEYS = frozenset({"at", "toml", "ini", "match"})


class ProfileError(Refusal):
    """A shipped profile that does not parse: a defect in stayfixed, not in a repository.

    A `Refusal`, so it exits 2, which is where an internal error belongs: exit 1 means findings.
    """


class CheckKind(StrEnum):
    PRESENT = "present"  # must be present: a finding when no locator resolves
    ABSENT = "absent"  # must be absent: a finding when some locator resolves
    TRACKED = "tracked"  # must be tracked: a finding when a located file is untracked, unignored


@dataclass(frozen=True)
class Locator:
    at: str
    toml: str | None = None
    ini: tuple[str, ...] | None = None  # (section,) or (section, key)
    match: re.Pattern[str] | None = None


@dataclass(frozen=True)
class Check:
    id: str
    kind: CheckKind
    level: Severity
    locators: tuple[Locator, ...]
    remedy: str


@dataclass(frozen=True)
class Profile:
    name: str
    detect: tuple[str, ...]
    scope: tuple[str, ...]
    essentials: tuple[str, ...]
    checks: tuple[Check, ...]
    rules: str


def _strings(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ProfileError(f"{where} is not a non-empty list of strings")
    return tuple(value)


def _root_relative(at: object, where: str) -> str:
    """A root-level name or a glob under the root, spelled the way `contained()` accepts it.

    `fsops.checked_components` is the rule `contained()` applies, so a spelling it refuses
    (`./x`, `x/`, `..`, an absolute path, `.git`) is refused here, where it is the build's
    defect, rather than resolving to nothing forever at every run.
    """
    if not isinstance(at, str):
        raise ProfileError(f"{where}: at is not a string")
    try:
        checked_components(at)
    except UnsafePath:
        raise ProfileError(f"{where}: at is not a plain path under the repository root") from None
    return at


def _ini(value: object, where: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) not in (1, 2):
        raise ProfileError(f"{where}: ini is [section] or [section, key]")
    return _strings(value, f"{where}: ini")


def _locator(raw: object, where: str, kind: CheckKind) -> Locator:
    if not isinstance(raw, dict) or not set(raw) <= _LOCATOR_KEYS:
        raise ProfileError(f"{where}: a locator is a table of {sorted(_LOCATOR_KEYS)}")
    toml, pattern = raw.get("toml"), raw.get("match")
    ini = _ini(raw.get("ini"), where)
    if toml is not None and ini is not None:
        raise ProfileError(f"{where}: a locator reads toml or ini, not both")
    if toml is not None and not isinstance(toml, str):
        raise ProfileError(f"{where}: toml is a dotted key")
    if kind is CheckKind.ABSENT and pattern is None:
        raise ProfileError(f"{where}: an absent check needs a match on every locator")
    if kind is CheckKind.TRACKED and (toml is not None or ini is not None):
        raise ProfileError(f"{where}: a tracked check locates files, not keys")
    if pattern is not None and not isinstance(pattern, str):
        raise ProfileError(f"{where}: match is not a string")
    try:
        compiled = re.compile(pattern) if pattern is not None else None
    except re.error as exc:
        raise ProfileError(f"{where}: match is not a regular expression ({exc})") from None
    return Locator(_root_relative(raw.get("at"), where), toml, ini, compiled)


def _check(raw: object, index: int) -> Check:
    where = f"check {index}"
    if not isinstance(raw, dict) or set(raw) != _CHECK_KEYS:
        raise ProfileError(f"{where}: a check is a table of exactly {sorted(_CHECK_KEYS)}")
    check_id = raw["id"]
    if not isinstance(check_id, str) or not CHECK_ID.match(check_id):
        raise ProfileError(f"{where}: id must match {CHECK_ID.pattern}")
    try:
        kind = CheckKind(raw["kind"])
    except ValueError:
        raise ProfileError(f"{where}: kind is one of {[k.value for k in CheckKind]}") from None
    try:
        level = Severity(raw["level"])
    except ValueError:
        raise ProfileError(f"{where}: level is one of {[s.value for s in Severity]}") from None
    locators = raw["locators"]
    if not isinstance(locators, list) or not locators:
        raise ProfileError(f"{where}: locators is a non-empty list")
    if not isinstance(raw["remedy"], str) or not raw["remedy"]:
        raise ProfileError(f"{where}: remedy is a non-empty string")
    return Check(
        check_id,
        kind,
        level,
        tuple(_locator(item, where, kind) for item in locators),
        raw["remedy"],
    )


def essentials(rules: str) -> tuple[str, ...]:
    """The bullets under `ESSENTIALS`, each joined onto one line, up to the next heading."""
    lines = rules.split("\n")
    if ESSENTIALS not in lines:
        raise ProfileError(f"rules.md has no {ESSENTIALS!r} section")
    items: list[str] = []
    for line in lines[lines.index(ESSENTIALS) + 1 :]:
        if line.startswith("#"):
            break
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("  ") and items:
            items[-1] = f"{items[-1]} {line.strip()}"
        elif line.strip():
            raise ProfileError(f"the {ESSENTIALS!r} section holds a list and nothing else")
    if not items:
        raise ProfileError(f"the {ESSENTIALS!r} section is empty")
    return tuple(items)


def parse(name: str, document: Mapping[str, Any], rules: str) -> Profile:
    if not PROJECT_NAME.match(name):
        raise ProfileError("a profile directory's name is outside the profile grammar")
    unknown = set(document) - _KEYS
    if unknown:
        raise ProfileError(f"profile.toml carries unknown key(s): {sorted(unknown)}")
    checks = document.get("check", [])
    if not isinstance(checks, list):
        raise ProfileError("check is not an array of tables")
    parsed = tuple(_check(raw, index) for index, raw in enumerate(checks))
    ids = [c.id for c in parsed]
    if len(set(ids)) != len(ids):
        raise ProfileError("two checks share an id")
    return Profile(
        name,
        tuple(_root_relative(at, "detect") for at in _strings(document.get("detect"), "detect")),
        _strings(document.get("scope"), "scope"),
        essentials(rules),
        parsed,
        rules,
    )
