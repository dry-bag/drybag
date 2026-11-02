"""`setup --restore`: bring a machine back from the private overlay its machine file records.

Machine setup is `setup.run.setup`; this module is what `--restore` does around it. It checks the
tools (`missing_tools`), and attaches each checkout the overlay's `machine/projects.toml` lists
(`listed_projects`, `restore`). The overlay is the owner's, so the names and directories it holds
are the owner's input; what a *checkout* holds is a repository's, and `attach` judges it.

**A checkout cannot choose the store it is attached under.** A listed checkout's tracked
`stayfixed.toml` can claim another of the owner's projects. The store `restore` hands `attach`
comes from the table key in `<overlay>/machine/projects.toml`, which no repository writes, and
`attach` refuses a store that is not the checkout's own project's, so such a checkout is refused
rather than given another project's notes, rules and delivery. The adversary is a clone that names
itself after a project it does not belong to; the anchor is the key, which only the owner's file
holds, checked against the project the checkout's own file names by `attach.binding.read_binding`.

One project failing never ends the others: each outcome is its own, and a re-run completes what a
failure left.
"""

from __future__ import annotations

import shutil
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple

from stayfixed import fsops
from stayfixed.attach.api import attach
from stayfixed.command import command_owner
from stayfixed.config.reading import UNPARSEABLE, toml_position
from stayfixed.errors import Failure, Refusal
from stayfixed.memory.api import permitted_roots
from stayfixed.printed import clipped, quoted
from stayfixed.runner import Runner

# The owner's list of the checkouts of the projects this overlay serves, one `[projects.<name>]`
# table each, under the overlay root. `docs/cli.md` documents it as a product input.
PROJECTS_FILE = Path("machine") / "projects.toml"
_LABEL = PROJECTS_FILE.as_posix()


class Listed(NamedTuple):
    """One table of the projects file: the overlay project it names and where its checkout is."""

    name: str
    dir: Path


def _table(name: str) -> str:
    return f"[projects.{clipped(name)}] of {_LABEL}"


def listed_projects(overlay: Path, *, home: Path) -> tuple[Listed, ...]:
    """The `[projects.<name>]` tables of `<overlay>/machine/projects.toml` in file order.

    `dir` is required and is absolute or led by `~/`, which is read under `home`; every other key
    is ignored, because an overlay's own scripts may read them. `()` when the file is not there.
    A file that cannot be read, is not TOML, whose `projects` is not a table or holds a table
    whose `dir` is missing, not a string or relative is a `Refusal` naming it. Asked before
    anything is written, so an input error in the owner's file costs nothing.
    """
    path = overlay / PROJECTS_FILE
    with fsops.reading(_LABEL, Refusal):
        try:
            text = fsops.read_regular_text(path)
        except FileNotFoundError:
            return ()
    try:
        document = tomllib.loads(text)
    except UNPARSEABLE as exc:
        raise Refusal(f"{_LABEL} is not valid TOML {toml_position(exc)}") from None
    projects = document.get("projects", {})
    if not isinstance(projects, dict):
        raise Refusal(f"`projects` in {_LABEL} is not a table")
    found: list[Listed] = []
    for name, table in projects.items():
        if not isinstance(table, dict):
            raise Refusal(f"{_table(name)} is not a table")
        value = table.get("dir")
        if not isinstance(value, str) or not value:
            raise Refusal(f"{_table(name)} has no `dir`, or it is not a string")
        if "\0" in value:
            raise Refusal(f"`dir` of {_table(name)} is not a path")
        if value.startswith("~/"):
            directory = home / value[2:]
        elif Path(value).is_absolute():
            directory = Path(value)
        else:
            raise Refusal(
                f"`dir` of {_table(name)} is relative: name it by its whole path or `~/…`"
            )
        found.append(Listed(name, directory))
    return tuple(found)


def missing_tools(which: Callable[[str], str | None] = shutil.which) -> tuple[str, ...]:
    """What a restored machine needs and `PATH` lacks: `git`, one of `claude` and `codex`, and a
    `python3` or a `uv` for the hooks. Said, never refused: a missing `git` makes each attach fail
    in attach's own words."""
    missing: list[str] = []
    if which("git") is None:
        missing.append("git")
    if which("claude") is None and which("codex") is None:
        missing.append("claude or codex")
    if which("python3") is None and which("uv") is None:
        missing.append("python3 or uv")
    return tuple(missing)


class Outcome(NamedTuple):
    """What one listed project came to. `name` and `dir` are the owner's file's; `detail` is
    attach's own words, printed through `stayfixed.printed`."""

    name: str
    dir: Path
    state: Literal["attached", "absent", "refused", "failed"]
    detail: str
    promoted: int


@dataclass(frozen=True)
class RestoreReport:
    """What `restore` did, beyond the machine setup that ran before it."""

    missing: tuple[str, ...]
    plugins: tuple[str, ...]
    notes: tuple[str, ...]
    projects: tuple[Outcome, ...]


def restore(
    overlay: Path,
    listed: Sequence[Listed],
    *,
    home: Path,
    machine: Path,
    runner: Runner,
    yes: bool,
) -> RestoreReport:
    """Attach each listed checkout that exists, each under the store its table key names.

    **Adversary and anchor:** a listed checkout's tracked `stayfixed.toml` can claim another of
    the owner's projects; the store handed to `attach` comes from the table key in
    `<overlay>/machine/projects.toml`, which no repository writes, and attach refuses a store that
    is not the checkout's own project's, so such a checkout is refused rather than given another
    project's notes, rules and delivery.

    A `dir` that is not there is `absent`, reported and skipped; attach's `Refusal` is `refused`
    and its `Failure` `failed`, each with the message as `detail`, and the next project goes on.
    """
    outcomes: list[Outcome] = []
    owner = None
    for item in listed:
        try:
            if not fsops.exists(item.dir):
                outcomes.append(Outcome(item.name, item.dir, "absent", "not there", 0))
                continue
            owner = command_owner(machine) if owner is None else owner
            attached = attach(
                item.dir,
                store=permitted_roots(overlay, item.name)[1],
                machine=machine,
                runner=runner,
                owner=owner,
                project=None,
            )
        except Refusal as exc:
            outcomes.append(Outcome(item.name, item.dir, "refused", str(exc), 0))
        except Failure as exc:
            outcomes.append(Outcome(item.name, item.dir, "failed", str(exc), 0))
        except OSError as exc:
            outcomes.append(Outcome(item.name, item.dir, "failed", fsops.said(exc), 0))
        else:
            recorded = "recorded" if attached.binding_recorded else "already recorded"
            detail = "; ".join((f"binding {attached.binding} {recorded}", *attached.notes))
            outcomes.append(Outcome(item.name, item.dir, "attached", detail, 0))
    return RestoreReport(missing_tools(), (), (), tuple(outcomes))


def line(outcome: Outcome) -> str:
    """One project's line of the summary."""
    said = f"{quoted(outcome.name)} at {quoted(str(outcome.dir))}: {outcome.state}"
    return f"{said} ({outcome.detail})" if outcome.detail else said


def overlay_to_restore(overlay: str | None, *, machine: Path) -> Path | None:
    """The overlay root a restore reads before `setup` has written anything: `--overlay`'s path
    when it names one that holds an overlay, else, with no `--overlay`, the machine file's recorded
    root. `None` for `--overlay create:…` and for a path that holds no overlay, which `setup` makes
    or refuses, and for a machine that records none."""
    from stayfixed.config.machine import in_owner_home
    from stayfixed.config.overlay import overlay_root
    from stayfixed.overlay.api import overlay_fault

    if overlay is None:
        return overlay_root(machine)
    named = None if overlay.startswith("create:") else in_owner_home(overlay)
    if named is None:
        return None
    try:
        candidate = fsops.resolved(named)
    except OSError:
        return None  # `setup` refuses a path it cannot resolve, in its own words, before writing
    return candidate if overlay_fault(candidate) is None else None
