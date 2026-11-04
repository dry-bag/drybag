"""Where two of a project's tags hold one name, as `doctor` says it.

A later plate wins an item name or a value (`config.plates`), so two tags that both hold a rule, a
skill, an agent, a Codex rule file or a setting are settled by their order in the project's record
(`tags` in `projects/<name>/project.toml`), and the owner may not have meant that order to decide.
`collisions` names each such name, the tags that hold it in list order and the one that wins. A tag
and `common` or the project holding one name is precedence and is not named: it is how a plate
overrides the plate beneath it.

**A convenience and not a control.** The overlay and its record are the owner's own, and the
sentences are for the owner, so nothing here refuses and nothing is gated on it; `doctor` warns. The
names come off the overlay's disk and print through `printed.quoted`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from stayfixed import fsops
from stayfixed.attach.permissions import PROJECT_CLAUDE, PROJECT_CODEX
from stayfixed.attach.render import COPIED
from stayfixed.attach.rules import RULES, SUFFIX
from stayfixed.config.classes import Layer, LayerName
from stayfixed.config.plates import PlateKind, plates
from stayfixed.printed import quoted

HELD = "the {kind} {name} is held by the tags {tags}: the later, {winner}, wins"

# What each plate's directory holds by name: the kind as the sentence says it, the directory inside
# the plate, the suffix a name carries (`""` for any) and whether only files count. Rules and Codex
# rule files are the files `rules` and `permissions.codex_rules` read; a skill or an agent is named
# by the directory or file directly in `skills/` or `agents/`, which is how an owner names one.
_ITEMS: tuple[tuple[str, str, str, bool], ...] = (
    ("rule", f"{PROJECT_CLAUDE}/{RULES}", SUFFIX, True),
    ("Codex rule", PROJECT_CODEX, "", True),
    *(
        (kind, f"{PROJECT_CLAUDE}/{copied}", "", False)
        for kind, copied in zip(("skill", "agent"), COPIED, strict=True)
    ),
)


def collisions(overlay: Path, project: str, layers: Sequence[Layer]) -> tuple[str, ...]:
    """One sentence for each item name or dotted key two or more of `project`'s tags hold: the
    kind, the name, the tags in list order and the later one, which wins. `layers` are the overlay's
    value layers (`overlay_layers.read`), of which only the tag layers are asked."""
    used = [plate for plate in plates(overlay, project)[0] if plate.kind is PlateKind.TAG]
    found: list[str] = []
    for kind, inside, suffix, files in _ITEMS:
        held: dict[str, list[str]] = {}
        for plate in used:
            for name in _names(plate.directory / inside, suffix, files):
                held.setdefault(name, []).append(plate.name)
        found.extend(_sentence(kind, name, tags) for name, tags in held.items() if len(tags) > 1)
    keys: dict[str, list[str]] = {}
    for layer in layers:
        if layer.name is LayerName.OVERLAY_TAG:
            for key in layer.values:
                keys.setdefault(key, []).append(layer.label)
    found.extend(_sentence("setting", key, tags) for key, tags in keys.items() if len(tags) > 1)
    return tuple(found)


def _sentence(kind: str, name: str, tags: list[str]) -> str:
    return HELD.format(kind=kind, name=quoted(name), tags=", ".join(tags), winner=tags[-1])


def _names(directory: Path, suffix: str, files: bool) -> list[str]:
    """The undotted names in `directory` that end in `suffix`, files only where `files`, sorted;
    none where there is no such directory or it cannot be listed, which `attach` says itself."""
    try:
        if not fsops.is_dir(directory):
            return []
        return sorted(
            name
            for name in os.listdir(directory)
            if not name.startswith(".")
            and name.endswith(suffix)
            and (not files or fsops.is_file(directory / name))
        )
    except OSError:
        return []
