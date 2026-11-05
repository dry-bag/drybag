"""`setup --restore`: bring a machine back from the private overlay its machine file records.

Machine setup is `setup.run.setup`; this module is what `--restore` does around it. It checks the
tools (`missing_tools`), installs the plugins the overlay's machine settings enable
(`listed_plugins`, `install_listed`), and attaches each checkout the overlay's
`machine/projects.toml` lists (`listed_projects`, `restore`). The overlay is the owner's, so the
names, directories and plugin sources it holds are the owner's input; what a *checkout* holds is a
repository's, and `attach` judges it.

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

import json
import re
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
from stayfixed.harnesses import HARNESSES, lenient_settings
from stayfixed.jsonobject import json_object
from stayfixed.memory.api import project_notes, promote_share
from stayfixed.printed import answered, clipped, quoted
from stayfixed.runner import Completed, Runner

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
    """What a restored machine needs and `PATH` lacks: `git`, one of the harnesses' programs
    (`claude` and `codex`, as `harnesses.HARNESSES` names them), and a `python3` or a `uv` for the
    hooks. Said, never refused: a missing `git` makes each attach fail in attach's own words."""
    missing: list[str] = []
    if which("git") is None:
        missing.append("git")
    harnesses = [harness.name for harness in HARNESSES]
    if all(which(name) is None for name in harnesses):
        missing.append(" or ".join(harnesses))
    if which("python3") is None and which("uv") is None:
        missing.append("python3 or uv")
    return tuple(missing)


# The overlay's copy of Claude Code's user settings. Restore reads two keys of it,
# `extraKnownMarketplaces` and `enabledPlugins`, and writes nothing from it.
PLUGINS_FILE = Path("machine") / "claude" / "settings.json"
_PLUGINS_LABEL = PLUGINS_FILE.as_posix()
# What a value of the overlay's settings must look like to become an argv element of a `claude
# plugin` call, each led by a letter or a digit so none can read as an option: the owner wrote the
# file, but a synced overlay is edited from more than one machine, and a value that could read as an
# option is a note and not an argument. A plugin id is `<name>@<marketplace>`; a repository is
# `<owner>/<name>`, optionally `@<ref>`; a git URL is `https://` or `git@` and holds no space.
_PLUGIN_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_REPOSITORY = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_REF = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_GIT_URL = re.compile(r"\A(?:https://|git@)[^\s\x00-\x1f]+\Z")
# The two listings `install_listed` asks, `claude plugin marketplace list --json` and `claude plugin
# list --json`, are each a JSON array: of the marketplaces registered (`name`) and of the plugins
# installed (`id`, `scope`), measured under a scratch HOME on Claude Code 2.1.312. A plugin counts
# as installed here only at this scope, the one a bare `claude plugin install` writes.
USER_SCOPE = "user"


def _marketplace_argument(source: object) -> str | None:
    """The argument `claude plugin marketplace add` takes for an `extraKnownMarketplaces` source of
    a shape restore adds, or `None`: a GitHub repository with an optional ref, or an `https://` or
    `git@` git URL."""
    if not isinstance(source, dict):
        return None
    kind = source.get("source")
    if kind == "github":
        repo, ref = source.get("repo"), source.get("ref")
        if not isinstance(repo, str) or not _REPOSITORY.match(repo):
            return None
        if ref is None:
            return repo
        return f"{repo}@{ref}" if isinstance(ref, str) and _REF.match(ref) else None
    url = source.get("url")
    if kind == "git" and isinstance(url, str) and _GIT_URL.match(url):
        return url
    return None


def listed_plugins(
    overlay: Path,
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]]:
    """`(marketplaces as (name, add-argument), plugin ids, notes)` the overlay's copy of Claude
    Code's user settings names.

    `extraKnownMarketplaces.<name>.source` of a GitHub repository (with an optional `ref`) or of an
    `https://` or `git@` git URL gives the marketplace; any other shape, or a value that could read
    as an option, is a note and is not added. `enabledPlugins` entries whose value is `true` and
    whose id is `<name>@<marketplace>` are the ids. No file lists nothing; one that cannot be read
    as a JSON object, or whose two keys are not objects, is one note and lists nothing of what it
    could not read.
    """
    path = overlay / PLUGINS_FILE
    try:
        text = fsops.read_regular_text(path)
    except FileNotFoundError:
        return (), (), ()
    except (OSError, UnicodeDecodeError) as exc:
        return (), (), (f"{fsops.unreadable(_PLUGINS_LABEL, exc)}, so no plugin was installed",)
    try:
        document = json_object(lenient_settings(text), _PLUGINS_LABEL, error=Failure)
    except Failure as exc:
        return (), (), (f"{exc}, so no plugin was installed",)
    notes: list[str] = []
    marketplaces: list[tuple[str, str]] = []
    known = document.get("extraKnownMarketplaces", {})
    if not isinstance(known, dict):
        notes.append(f"`extraKnownMarketplaces` in {_PLUGINS_LABEL} is not an object")
        known = {}
    for name, entry in known.items():
        source = entry.get("source") if isinstance(entry, dict) else None
        argument = _marketplace_argument(source)
        if argument is None:
            notes.append(
                f"marketplace {clipped(name)} of {_PLUGINS_LABEL} has a source restore does not "
                "add (a GitHub repository, or an https or ssh git URL), so it was not added"
            )
        else:
            marketplaces.append((name, argument))
    enabled = document.get("enabledPlugins", {})
    if not isinstance(enabled, dict):
        notes.append(f"`enabledPlugins` in {_PLUGINS_LABEL} is not an object")
        enabled = {}
    ids = tuple(i for i, on in enabled.items() if on is True and _PLUGIN_ID.match(i))
    return tuple(marketplaces), ids, tuple(notes)


def _rows(done: Completed, key: str) -> list[dict[str, object]] | None:
    """The rows of a `claude plugin … list --json` answer, or `None` when it did not answer a JSON
    array of objects each holding `key`."""
    if done.code != 0:
        return None
    try:
        rows = json.loads(done.stdout)
    except ValueError:
        return None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and key in r for r in rows):
        return None
    return rows


def install_listed(
    marketplaces: Sequence[tuple[str, str]],
    ids: Sequence[str],
    *,
    home: Path,
    runner: Runner,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`(installed ids, notes)`: add each listed marketplace Claude Code does not have registered
    (`claude plugin marketplace add <argument>`) and install each id it does not have installed at
    user scope (`claude plugin install <id>`), after asking its two listings. A non-zero exit is a
    note naming the argv, never a refusal; so is a listing that answers no array, which stops the
    installs rather than guess what is there. Nothing listed launches nothing, and without `claude`
    on `PATH` there is one note. The overlay's list is Claude Code's, so Codex, where it is on
    `PATH`, gets one note.
    """
    if not marketplaces and not ids:
        return (), ()
    if shutil.which("claude") is None:
        return (), ("the overlay lists plugins for Claude Code and `claude` is not on PATH",)
    known = _rows(
        runner.launch(["claude", "plugin", "marketplace", "list", "--json"], home), "name"
    )
    held = _rows(runner.launch(["claude", "plugin", "list", "--json"], home), "id")
    if known is None or held is None:
        return (), ("`claude plugin` listed no marketplaces or plugins, so none was installed",)
    registered = {row["name"] for row in known}
    installed_here = {row["id"] for row in held if row.get("scope") == USER_SCOPE}
    done: list[str] = []
    notes: list[str] = []
    for name, argument in marketplaces:
        if name not in registered:
            added = runner.launch(["claude", "plugin", "marketplace", "add", argument], home)
            if added.code != 0:
                notes.append(_did_not_succeed(f"marketplace add {argument}", added))
    for plugin in ids:
        if plugin not in installed_here:
            ran = runner.launch(["claude", "plugin", "install", plugin], home)
            if ran.code == 0:
                done.append(plugin)
            else:
                notes.append(_did_not_succeed(f"install {plugin}", ran))
    if shutil.which("codex") is not None:
        notes.append(
            "the overlay's plugin list is Claude Code's, so nothing was installed for Codex"
        )
    return tuple(done), tuple(notes)


def _did_not_succeed(verb: str, done: Completed) -> str:
    return f"`claude plugin {verb}` did not succeed ({answered(done)})"


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

    With `yes`, each attached project's unreviewed notes are then recorded as reviewed on this
    machine (`promote_share`), counted in the outcome's `promoted`; a project whose notes cannot be
    recorded is `failed`, attached all the same. **The notes recorded come from the overlay's share
    for the table key of the owner's projects file, which no repository writes; nothing a checkout
    holds is read.** Without `yes` nothing is recorded as reviewed, whatever the overlay holds.
    """
    marketplaces, ids, listing_notes = listed_plugins(overlay)
    installed, install_notes = install_listed(marketplaces, ids, home=home, runner=runner)
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
                store=project_notes(overlay, item.name),
                machine=machine,
                runner=runner,
                owner=owner,
                project=None,
            )
        except Refusal as exc:
            outcomes.append(Outcome(item.name, item.dir, "refused", str(exc), 0))
            continue
        except Failure as exc:
            outcomes.append(Outcome(item.name, item.dir, "failed", str(exc), 0))
            continue
        except OSError as exc:
            outcomes.append(Outcome(item.name, item.dir, "failed", fsops.said(exc), 0))
            continue
        recorded = "recorded" if attached.binding_recorded else "already recorded"
        detail = "; ".join((f"binding {attached.binding} {recorded}", *attached.notes))
        if yes:
            try:
                promoted = len(promote_share(overlay, item.name, machine=machine))
            except (Failure, Refusal) as exc:
                said = f"{detail}; its notes were not recorded as reviewed: {exc}"
                outcomes.append(Outcome(item.name, item.dir, "failed", said, 0))
                continue
            outcomes.append(Outcome(item.name, item.dir, "attached", detail, promoted))
        else:
            outcomes.append(Outcome(item.name, item.dir, "attached", detail, 0))
    notes = (*listing_notes, *install_notes)
    return RestoreReport(missing_tools(), installed, notes, tuple(outcomes))


def line(outcome: Outcome) -> str:
    """One project's line of the summary."""
    said = f"{quoted(outcome.name)} at {quoted(str(outcome.dir))}: {outcome.state}"
    said = f"{said} ({outcome.detail})" if outcome.detail else said
    return f"{said}; {outcome.promoted} note(s) recorded as reviewed" if outcome.promoted else said


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
