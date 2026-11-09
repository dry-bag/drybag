#!/usr/bin/env python3
"""This repository's own release discipline: one version everywhere, the changelog, the pin.

    uv run python scripts/release.py check [--tag TAG]            # one version everywhere
    uv run python scripts/release.py notes --version X.Y.Z [--draft]  # assemble CHANGELOG.md
    uv run python scripts/release.py pin [--remote URL]            # the plugin commit, pinned

These commands only ever checked or wrote the drybag repository itself, so they live beside it
rather than in the installed CLI. What shipped code does read stays in `drybag.release`: the
tag a version is released under. `RELEASING.md` is the process these commands
serve.

The commands go through the CLI frame's `run`, so they keep its contract: `--json` anywhere on
the line before a bare `--`, exit `0`, `1` for findings and `2` for a refusal or an internal error.

**`check --tag` holds the release commit to what it releases:** the seven version sources and the
tag agree, no fragment is left to assemble, the plugin tree holds no more files than the plugin
directory lists unheld, and the marketplace entry's `sha` is the plugin commit that tree makes,
which `scripts/plugin_tree.py commit` computes from the commit alone. `pin` writes that `sha`, once
it has read that the plugin repository's `main` is the commit's parent: `main` moves only by
fast-forward, so a release commit cut on the wrong base is refused before any tag is pushed.

**Findings are returned, not raised.** These commands once reported a finding by raising
`Failure`, and the cost was in `--json`: the frame turns a `Failure` into
`{"error": "failed", "summary": "failed: ..."}` and drops `Result.data` entirely, so the
machine-readable object changed *shape* between a clean run and a drifted one -- a consumer that
read `versions` on success had nothing to read on the run it actually cared about. `Failure` is
still raised for what it is for: a source this gate cannot parse at all (`MalformedSource`) and
a towncrier that cannot be run.

**`notes --draft` prints more than one line**, and it is deliberate: every drybag command
gets one summary line because a line is what a caller reads, and a draft's whole purpose is that
a person reads the section towncrier *would* write before it is written. Under `--json` it keeps
the one-line contract.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

# Before the CLI frame exists, so said here: an interpreter without this repository's `drybag`,
# or older than the 3.11 that brought `tomllib`, would otherwise end in a traceback and exit `1`,
# which `check` gives its findings.
try:
    import tomllib

    from drybag import fsops
    from drybag.cli import JSON_EPILOG, run
    from drybag.command import ROOT_HELP
    from drybag.config.reading import UNPARSEABLE
    from drybag.errors import Failure, Refusal
    from drybag.jsonobject import json_object
    from drybag.printed import clipped
    from drybag.release.api import PACKAGE, tag_for
    from drybag.result import Result
    from drybag.runner import NOT_FOUND, Completed, Runner, subprocess_runner
except ImportError as exc:
    sys.stderr.write(
        f"scripts/release.py: refused: {exc}; run it with `uv run python scripts/release.py`, "
        "which runs it on the project's Python with this repository's drybag on the path\n"
    )
    sys.exit(2)

# How a message tells the reader to run one of these commands again.
COMMAND = "uv run python scripts/release.py"

PYPROJECT = "pyproject.toml"
LOCKFILE = "uv.lock"
MARKETPLACE = ".claude-plugin/marketplace.json"
SOURCES = (
    PYPROJECT,
    LOCKFILE,
    "src/drybag/__init__.py",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "CHANGELOG.md",
    MARKETPLACE,
)
# Where the marketplace fetches the plugin from: a repository of its own, whose root is the tree
# `scripts/plugin_tree.py` generates from this one. The marketplace entry is a `url` source pinned
# to the release's tag by `ref` and to the plugin commit by `sha`. The `ref` is a version source
# (`_released_ref`): the release commit names the tag it releases, which is the only marketplace a
# user reads, since `README.md` installs `dry-bag/drybag@vX.Y.Z` and `main` moves only at a
# release. The `sha` is the commit `scripts/plugin_tree.py commit` computes from the release commit
# alone, so the release commit can name it before the plugin repository holds it (`pin`).
PLUGIN_URL = "https://github.com/dry-bag/drybag-plugin.git"
# The same repository as `owner/name`, as a refusal names it.
PLUGIN_REPOSITORY = PLUGIN_URL.removeprefix("https://github.com/").removesuffix(".git")
# A release's tag, as the marketplace entry's `ref` names it: ASCII digits, as the publisher's
# tag pattern spells them, since `\d` also takes every other script's digits.
_RELEASE_REF = re.compile(r"v([0-9]+\.[0-9]+\.[0-9]+)")
# A commit id of the plugin repository, as the marketplace entry's `sha` pins it: SHA-1, which
# `scripts/plugin_tree.py` forces whatever the owner's configuration says, in git's lower case.
SHA1 = re.compile(r"[0-9a-f]{40}")
# The script that names the plugin's paths, run as a program and never imported.
PLUGIN_TREE = Path(__file__).resolve().with_name("plugin_tree.py")
# The most files a plugin holds without the Claude plugin directory holding the listing for a
# reviewer: "Keep the plugin to 512 files or fewer", its pre-submission checklist says
# (https://claude.com/docs/plugins/pre-submission-checklist, read 2026-10-05). The number is the
# page's and no file's here; `tests/test_payload.py` reads it as its `FILES_MAX`.
PLUGIN_FILES_MAX = 512
START = "<!-- towncrier release notes start -->"
_INIT = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
_HEADING = re.compile(r"^## (\S+)", re.MULTILINE)

TAG_HELP = (
    "the tag this run was created from; the seven sources and the changelog must agree with it, "
    "the plugin tree must hold no more files than the plugin directory lists unheld, and the "
    "marketplace entry must pin by sha the plugin commit that tree makes"
)
REMOTE_HELP = (
    "the plugin repository whose main the plugin commit must follow; only listed, never written "
    f"(default: {PLUGIN_URL})"
)


# --- One version string everywhere --------------------------------------------------------------


class MalformedSource(Failure):
    """A version source that exists but cannot be parsed; the message names which one."""


def _object(name: str, text: str) -> dict[str, Any]:
    """A JSON source's top level, which is read with `.get` and so must be an object.

    Read through `jsonobject.json_object`, the product's own reader, so every way the parse can
    fail is refused by the source's name, and a document nested past `jsonobject.DEPTH_CAP` is
    refused at that depth on every interpreter and platform. `json` itself stops short of it up to
    Python 3.13 and on 3.14 follows as deep as the C stack allows, which differs by platform: a
    manifest 100,000 levels deep was a parse error on macOS and parsed on Linux, and what parsed
    went on to `str()` and the version comparison.
    """
    return json_object(text, name, error=MalformedSource)


def _parse(name: str, text: str) -> str | None:
    # Valid TOML or JSON of the wrong shape decodes cleanly, so `_read`'s decoder catches never
    # see it: a `.get` on a list or a string raises AttributeError, which reaches the caller as
    # an unlabelled internal error naming no file. Each shape a source is read in is asked first.
    if name == PYPROJECT:
        project = tomllib.loads(text).get("project", {})
        if not isinstance(project, dict):
            raise MalformedSource(f"{name} is valid TOML but its project is not a table")
        version = project.get("version")
        return str(version) if version is not None else None
    if name == LOCKFILE:
        # `uv sync --locked` fails the install step on a stale lockfile with a
        # dependency-shaped message, before this gate — built to catch exactly this — can speak.
        packages = tomllib.loads(text).get("package", [])
        if not isinstance(packages, list) or not all(isinstance(e, dict) for e in packages):
            raise MalformedSource(f"{name} is valid TOML but its package is not a list of tables")
        for entry in packages:
            if entry.get("name") == PACKAGE:
                version = entry.get("version")
                return str(version) if version is not None else None
        return None
    if name.endswith("__init__.py"):
        match = _INIT.search(text)
        return match.group(1) if match else None
    # Ahead of the `.json` rule below: the marketplace carries no `version`, and its version is the
    # tag its plugin entry pins.
    if name == MARKETPLACE:
        return _released_ref(_plugin_entries(text))
    if name.endswith(".json"):
        version = _object(name, text).get("version")
        return str(version) if version is not None else None
    released = text.split(START, 1)[1] if START in text else text
    match = _HEADING.search(released)
    return match.group(1) if match else None


def _read(root: Path, name: str) -> str | None:
    path = root / name
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise MalformedSource(f"{name} is not UTF-8 text") from None
    # A JSON source refuses in `_object`'s words, so what reaches this arm is TOML's: a deep
    # `plugin.json` once reached it, and was reported as "not valid TOML".
    try:
        return _parse(name, text)
    except UNPARSEABLE as exc:
        raise MalformedSource(f"{name} is not valid TOML: {exc}") from None


def collect(root: Path) -> dict[str, str | None]:
    return {name: _read(root, name) for name in SOURCES}


def fragment_types(root: Path) -> frozenset[str]:
    """The types `[[tool.towncrier.type]]` declares, read rather than hardcoded here.

    A predicate that spelled the types out would drift from the configuration towncrier
    itself reads, and the drift would show up as a release gate that is wrong in silence.
    """
    tool = _pyproject(root).get("tool", {})
    towncrier = tool.get("towncrier", {}) if isinstance(tool, dict) else {}
    declared = towncrier.get("type", []) if isinstance(towncrier, dict) else []
    return frozenset(
        str(entry["directory"])
        for entry in declared
        if isinstance(entry, dict) and "directory" in entry
    )


def _pyproject(root: Path) -> dict[str, Any]:
    path = root / PYPROJECT
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise MalformedSource(f"{PYPROJECT} is not UTF-8 text") from None
    except UNPARSEABLE as exc:
        raise MalformedSource(f"{PYPROJECT} is not valid TOML: {exc}") from None


def _is_fragment(name: str, types: frozenset[str]) -> bool:
    """towncrier's own shape: `<something>.<type>.md`."""
    stem, _, extension = name.rpartition(".")
    if extension != "md" or not stem:
        return False
    prefix, _, kind = stem.rpartition(".")
    return bool(prefix) and kind in types


def fragments(root: Path) -> list[str]:
    """The real towncrier fragments `changelog.d` holds, by name, the types read once."""
    directory = root / "changelog.d"
    if not directory.is_dir():
        return []
    types = fragment_types(root)
    return sorted(entry.name for entry in directory.iterdir() if _is_fragment(entry.name, types))


def pending_fragments(root: Path) -> bool:
    """Whether `changelog.d` holds a real towncrier fragment, letting CHANGELOG.md lag.

    Asking instead "any entry not literally named .gitkeep" meant a stray `.DS_Store` — which
    Finder writes merely by opening the directory — silenced a genuine version drift and turned
    a red release gate green.
    """
    return bool(fragments(root))


def _marketplace_entries(root: Path) -> list[dict[str, Any]]:
    """The marketplace's `plugins` entries, each an object, or none when there is no file."""
    marketplace = root / MARKETPLACE
    if not marketplace.is_file():
        return []
    try:
        text = marketplace.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise MalformedSource(f"{MARKETPLACE} is not UTF-8 text") from None
    return _plugin_entries(text)


def _plugin_entries(text: str) -> list[dict[str, Any]]:
    """The `plugins` entries of the marketplace's text, each an object."""
    return _entries_of(_object(MARKETPLACE, text))


def _entries_of(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The `plugins` entries of the marketplace's parsed document, each an object."""
    entries = document.get("plugins", [])
    # A string entry was read with `in`, a substring test, and a string `plugins` as a list of
    # its characters, so the rule passed over both in silence.
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise MalformedSource(
            f"{MARKETPLACE} is valid JSON but its plugins is not a list of objects"
        )
    return entries


def _the_plugin_entry(entries: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, int]:
    """The one entry named for the package, or `None` when there is not exactly one, and how many
    entries are named for it."""
    named = [entry for entry in entries if entry.get("name") == PACKAGE]
    return (named[0] if len(named) == 1 else None), len(named)


def _released_ref(entries: list[dict[str, Any]]) -> str | None:
    """The version the plugin entry's `ref` pins, `X.Y.Z` of a `vX.Y.Z` tag, or `None` when the
    entry pins none of that shape: `marketplace_problems` says why, in its own words."""
    entry, _ = _the_plugin_entry(entries)
    source = entry.get("source") if entry is not None else None
    ref = source.get("ref") if isinstance(source, dict) else None
    match = _RELEASE_REF.fullmatch(ref) if isinstance(ref, str) else None
    return match.group(1) if match else None


def _shown(value: object) -> str:
    """A value the marketplace holds, as a finding prints it: through `clipped`, a string as
    itself and anything else as its `repr`. The repository chose it, so a line break followed by
    `::error::`, an escape sequence or a length past any name is not printed as it is."""
    return clipped(value if isinstance(value, str) else repr(value))


def marketplace_problems(root: Path) -> list[str]:
    """Every way the marketplace's plugin entry is not the one a release publishes: exactly one
    entry named for the package, fetching the plugin repository as a `url` source pinned to a
    `vX.Y.Z` tag by `ref`, carrying no `version` of its own, and pinning a commit by `sha` only as
    a commit id of 40 lowercase hex characters.

    The `sha` is optional here: `dev` pins none before the first release that carries one, and
    whether it is the plugin commit is asked at the tag (`plugin_commit_problems`).
    """
    entry, named = _the_plugin_entry(_marketplace_entries(root))
    if entry is None:
        return [
            f"{MARKETPLACE} has {named} entries named {PACKAGE!r}; it must have exactly one, "
            f"fetching the plugin from {PLUGIN_URL}"
        ]
    said = f"{MARKETPLACE} entry {PACKAGE!r}"
    problems = []
    if "version" in entry:
        problems.append(f"{said} carries a version; plugin.json is the only source")
    source = entry.get("source")
    if (
        not isinstance(source, dict)
        or source.get("source") != "url"
        or source.get("url") != PLUGIN_URL
    ):
        problems.append(
            f"{said} does not fetch the plugin from {PLUGIN_URL}; the plugin is published from "
            f"{PLUGIN_REPOSITORY}, as a url source pinned to the release's tag by ref and to the "
            "plugin commit by sha"
        )
        return problems
    ref = source.get("ref")
    if not isinstance(ref, str) or _RELEASE_REF.fullmatch(ref) is None:
        problems.append(f"{said} pins ref {_shown(ref)}, which is no release tag vX.Y.Z")
    sha = source.get("sha")
    if "sha" in source and not _is_sha(sha):
        problems.append(f"{said} pins sha {_shown(sha)}, which is no commit id")
    return problems


# The words `check` reports each kind of problem under. The plugin tree's count and the
# marketplace's pin of the plugin commit are a second and a third kind, found only at a tag.
VERSION_DRIFT = "version drift"
TREE_COUNT = "plugin tree count"
PLUGIN_PIN = "plugin pin"
# A `--root` that is no repository root is none of them, and is said with no word in front of it.
NOT_A_ROOT = ""


def _unusable_root(root: Path) -> str | None:
    """Why `root` is not a repository root `check` can read, or `None`.

    Four different conditions used to share one wrong message, so a user who typoed --root, or
    ran the command in their own project (--root defaults to "."), was told their pyproject.toml
    lacked a version key. A path that exists but is not a directory needs its own line rather
    than the missing-path one: `--root ./pyproject.toml` was told the file does not exist, and a
    gate that exists to stop asserting untrue things about the user's tree must not assert one
    itself.
    """
    if not root.exists():
        return f"{root} does not exist; --root must name a repository root"
    if not root.is_dir():
        return f"{root} is not a directory; --root must name a repository root"
    if not (root / PYPROJECT).is_file():
        return f"{root} has no {PYPROJECT}; --root must name a repository root"
    return None


def check(root: Path, *, tag: str | None = None) -> list[str]:
    """What stops this tree from being released as one version, at `tag` when one is given."""
    return checked(root, tag=tag)[0]


def checked(root: Path, *, tag: str | None = None) -> tuple[list[str], dict[str, str | None]]:
    """`check`'s problems, and the version each source carried as it read them, so a caller that
    reports both reads the tree once."""
    kinds, found = checked_by_kind(root, tag=tag)
    return [problem for problems in kinds.values() for problem in problems], found


def checked_by_kind(
    root: Path, *, tag: str | None = None
) -> tuple[dict[str, list[str]], dict[str, str | None]]:
    """`checked`'s problems under the word each kind is reported under, in the order `checked`
    lists them: the versions', the tree count's, then the pin's."""
    found = collect(root)
    unusable = _unusable_root(root)
    if unusable is not None:
        return {NOT_A_ROOT: [unusable]}, found
    canonical = found[PYPROJECT]
    if canonical is None:
        return {VERSION_DRIFT: [f"{PYPROJECT} has no [project].version"]}, found
    pending = fragments(root)
    problems: list[str] = []
    if tag is not None:
        if tag not in tag_for(canonical):
            # **Say what was checked, do not re-derive a version from the tag.** This used to
            # be `tag.split("v", 1)[-1]` — a split on the first `v` anywhere in the string and
            # not a parse — so `--tag 1.2.3` reported `tag 1.2.3 names 1.2.3; pyproject.toml
            # says '1.2.3'`, two identical strings asserted to disagree, and `--tag dev-v1.2.3`
            # reported `names -v1.2.3`. The membership test above is exact and was always
            # right; only the sentence was invented. Both slips are the ones `RELEASING.md`
            # invites, because a human types this flag by hand right after a tool prints
            # `drybag--vX.Y.Z`. The existing cases passed by accident: every tag they
            # exercised began with `v` and carried no earlier one.
            workflow_tag, platform_tag = tag_for(canonical)
            problems.append(
                f"tag {tag} is neither {workflow_tag} nor {platform_tag}; "
                f"{PYPROJECT} says {canonical!r}"
            )
        if pending:
            problems.append(
                f"changelog.d still holds {len(pending)} fragment(s); run `{COMMAND} notes "
                f"--version {canonical}` before tagging"
            )
    for name, value in found.items():
        if name == "CHANGELOG.md" and tag is None and pending:
            continue
        # A marketplace that pins no release tag has no version to compare, and
        # `marketplace_problems` names what it pins instead.
        if name == MARKETPLACE and value is None:
            continue
        if value != canonical:
            problems.append(f"{name} says {value!r}; {PYPROJECT} says {canonical!r}")
    entry_problems = marketplace_problems(root)
    problems += entry_problems
    kinds = {VERSION_DRIFT: problems, TREE_COUNT: [], PLUGIN_PIN: []}
    # At a tag, on the commit the tag names: `tests/test_payload.py` holds the same count on every
    # pull request, and this holds it again where the release is cut; the pin is the release
    # commit's, and `dev` pins none before the first release that carries one, and the last
    # release's after it, which is no pin of the commit `dev` is at. Only from an entry with no
    # problem above, of any kind: `scripts/plugin_tree.py` refuses a malformed `sha`, entry or
    # source too, and its refusal reported again under the tree count would name the same problem
    # twice, with a remedy for a missing checkout. A bad `ref` or a stray `version`, which it does
    # not refuse, holds the count and the pin back as well: one condition rather than a second
    # list of what the script refuses, at the cost of a second red run at the tag.
    if tag is not None and not entry_problems:
        kinds.update(plugin_commit_problems(root))
    return kinds, found


def _plugin_commit(root: Path, runner: Runner) -> tuple[dict[str, Any] | None, Completed]:
    """`scripts/plugin_tree.py commit --json` of `HEAD`, into a git dir made for this run and gone
    after it, and its report when it succeeded with one: the plugin commit, the files its tree
    holds, and the `sha` the marketplace pins there."""
    with tempfile.TemporaryDirectory() as scratch:
        argv = [sys.executable, str(PLUGIN_TREE), "commit", "--root", str(root.resolve())]
        git_dir = str(Path(scratch) / "plugin.git")
        done = runner.launch([*argv, "--rev", "HEAD", "--git-dir", git_dir, "--json"], root)
    return _reported(done), done


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and SHA1.fullmatch(value) is not None


def _reported(done: Completed) -> dict[str, Any] | None:
    """The report a successful `plugin_tree.py commit --json` printed, or `None` when it failed or
    printed no report of that shape."""
    if done.code != 0:
        return None
    try:
        report = json.loads(done.stdout)
    except ValueError:
        return None
    if not isinstance(report, dict):
        return None
    files = report.get("files")
    if not isinstance(files, int) or isinstance(files, bool):
        return None
    made, pinned, parent = (report.get(key) for key in ("commit", "pinned", "parent"))
    if not _is_sha(made) or not all(sha is None or _is_sha(sha) for sha in (pinned, parent)):
        return None
    return report


def plugin_commit_problems(root: Path) -> dict[str, list[str]]:
    """At a tag, the plugin tree at `HEAD` and the commit it makes, under the kind each problem is
    reported under: a tree holding more files than the plugin directory lists without holding the
    listing for a reviewer, or one that cannot be read, under `TREE_COUNT`; a marketplace entry
    that pins no `sha`, or another commit than the one the tree makes, under `PLUGIN_PIN`.

    Computed by running `scripts/plugin_tree.py commit`, which names the plugin's paths and reads
    them from the commit, as the directory and the plugin repository see it: a file on disk or only
    staged is not in it. A tree that script cannot read -- no checkout, a missing plugin path, a
    symlink, a name holding a control character, a first parent the clone lacks -- is a problem
    quoting what it said, and never nought files, no pin, or an exception out of `check`: the gate
    that cannot compute does not pass.
    """
    report, done = _plugin_commit(root, subprocess_runner())
    if report is None:
        return {
            TREE_COUNT: [
                f"the plugin tree could not be read: {_said(done)}; "
                "run the check in the git checkout the tag names"
            ],
            PLUGIN_PIN: [],
        }
    count, made, pinned = report["files"], report["commit"], report["pinned"]
    counted = []
    if count > PLUGIN_FILES_MAX:
        counted.append(
            f"the plugin tree (scripts/plugin_tree.py) holds {count} files, over the "
            f"{PLUGIN_FILES_MAX} the plugin directory lists unheld"
        )
    said = f"{MARKETPLACE} entry {PACKAGE!r}"
    pins = []
    if pinned is None:
        pins.append(
            f"{said} pins no sha; the plugin commit of this tree is {made}: run `{COMMAND} pin`"
        )
    elif pinned != made:
        pins.append(f"{said} pins sha {pinned}; the plugin commit of this tree is {made}")
    return {TREE_COUNT: counted, PLUGIN_PIN: pins}


def _said(done: Completed) -> str:
    """What `plugin_tree.py` said as it failed: under `--json` the frame prints a refusal's
    sentence as the object's `summary` on stdout, and anything that dies before the frame speaks
    leaves its last word on stderr. Through `clipped` either way: the sentence quotes the
    repository's names and paths, and a traceback's last line quotes anything."""
    try:
        report = json.loads(done.stdout)
    except ValueError:
        report = None
    if isinstance(report, dict) and isinstance(report.get("summary"), str):
        return clipped(str(report["summary"]))
    lines = [line for line in done.stderr.splitlines() if line.strip()]
    return clipped(lines[-1]) if lines else f"it exited {done.code} and said nothing"


def _main_at(remote: str, runner: Runner, cwd: Path) -> str | None:
    """The commit `remote`'s `refs/heads/main` names, or `None` when it has no `main`.

    `ls-remote` matches its pattern by the ref's tail, so `refs/heads/x/refs/heads/main` answers
    `refs/heads/main` too: the line read is the one whose ref is exactly that name. A failure
    quotes git's first line through `clipped`, since it prints what the remote said."""
    done = runner.launch(["git", "ls-remote", "--end-of-options", remote, "refs/heads/main"], cwd)
    if done.code != 0:
        lines = [line for line in done.stderr.splitlines() if line.strip()]
        raise Refusal(
            f"git ls-remote of {remote} exited {done.code}: "
            + (clipped(lines[0]) if lines else "it said nothing")
        )
    for line in done.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/main":
            return sha
    return None


def _pinned(root: Path, made: str) -> str:
    """The marketplace on disk with `made` as its plugin entry's `sha`, as the text `pin` writes:
    one format, so a later `pin` changes the `sha` line and nothing else.

    `plugin_tree.py commit` read the entry at `HEAD` and refused every shape this refuses; a file
    edited since is refused here, in a refusal's words, rather than written into."""
    try:
        text = (root / MARKETPLACE).read_text(encoding="utf-8")
        document = _object(MARKETPLACE, text)
        entry, named = _the_plugin_entry(_entries_of(document))
    except (OSError, UnicodeDecodeError, MalformedSource) as exc:
        raise Refusal(f"{MARKETPLACE} cannot be pinned: {exc}") from None
    if entry is None:
        raise Refusal(
            f"{MARKETPLACE} cannot be pinned: it has {named} entries named {PACKAGE!r}; the sha is "
            "written into exactly one"
        )
    source = entry.get("source")
    if not isinstance(source, dict):
        raise Refusal(
            f"{MARKETPLACE} cannot be pinned: its entry {PACKAGE!r} has a source that is no object"
        )
    source["sha"] = made
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def pin(root: Path, *, remote: str, runner: Runner) -> str:
    """Write the plugin commit of `HEAD` into the marketplace entry's `sha`, and return it.

    Refused before anything is written: a tree `scripts/plugin_tree.py commit` cannot make the
    commit of, a marketplace on disk that cannot take the `sha`, a `remote` that cannot be listed,
    and a `remote` whose `main` is not the commit's parent -- absent when there is a parent,
    present when there is none, or another commit. The plugin repository's `main` moves only by
    fast-forward, so a release commit pinning a commit that does not follow it is refused here
    rather than by the publisher, after the tags.
    """
    report, done = _plugin_commit(root, runner)
    if report is None:
        raise Refusal(f"the plugin commit could not be made: {_said(done)}")
    made, parent = str(report["commit"]), report["parent"]
    body = _pinned(root, made)
    main = _main_at(remote, runner, root)
    if main != parent:
        follows = f"parent {parent}" if parent is not None else "no parent"
        holds = f"main at {main}" if main is not None else "no main"
        raise Refusal(
            f"the plugin commit {made} has {follows}, and {remote} has {holds}; the plugin "
            "repository's main moves only by fast-forward. The likely cause: the plugin "
            "repository was never seeded (RELEASING.md, section 3); this release commit "
            f"was cut on the wrong base; a merge into main dropped the sha {MARKETPLACE} pinned "
            "at the release before; or a release that stopped after its plugin was pushed left "
            "main at a commit nothing here pins, which the restore commit puts back (RELEASING.md, "
            "section 5)"
        )
    fsops.write_within(root, MARKETPLACE, body)
    return made


# --- The changelog ------------------------------------------------------------------------------


def build(root: Path, *, version: str, draft: bool, runner: Runner) -> str:
    """Assemble `CHANGELOG.md` from `changelog.d/` through towncrier, or render it under `draft`.

    A wrapper and nothing more: towncrier owns the rendering, `pyproject.toml`'s
    `[tool.towncrier]` owns the format, and this function owns two refusals — the version must
    be the project's, and a missing towncrier is named as the development dependency it is.
    """
    current = collect(root)["pyproject.toml"]
    if version != current:
        raise Refusal(
            f"--version {version} is not the project's ({current!r}); set the version "
            f"everywhere first — `{COMMAND} check` names the seven places — and then "
            "assemble the changelog under it"
        )
    argv = ["towncrier", "build", "--version", version, "--yes"] + (["--draft"] if draft else [])
    done = runner.launch(argv, root)
    if done.code == NOT_FOUND:
        raise Failure(
            "towncrier could not be run; it is a development dependency, and `uv sync` installs it"
        )
    if done.code != 0:
        raise Failure(f"towncrier exited {done.code}: {done.stderr.strip()}")
    return done.stdout


# --- The commands -------------------------------------------------------------------------------


def run_check(args: argparse.Namespace) -> Result:
    root = Path(args.root)
    kinds, versions = checked_by_kind(root, tag=args.tag)
    problems = [problem for found in kinds.values() for problem in found]
    data = {"problems": problems, "versions": versions}
    if problems:
        summary = "; ".join(
            (f"{kind}: " if kind else "") + "; ".join(found)
            for kind, found in kinds.items()
            if found
        )
        return Result(summary, data, exit_code=1)
    return Result(f"one version everywhere: {versions['pyproject.toml']}", data)


def run_notes(args: argparse.Namespace) -> Result:
    root = Path(args.root)
    rendered = build(root, version=args.version, draft=args.draft, runner=subprocess_runner())
    if args.draft:
        return Result(rendered.rstrip("\n"), {"draft": rendered})
    return Result(f"CHANGELOG.md carries {args.version}")


def run_pin(args: argparse.Namespace) -> Result:
    root = Path(args.root)
    made = pin(root, remote=args.remote, runner=subprocess_runner())
    return Result(
        f"{MARKETPLACE} pins {made}, the plugin commit of HEAD; commit it into the release commit",
        {"sha": made},
    )


def parser() -> argparse.ArgumentParser:
    """The script's parser. Each command's one sentence is both its line in the listing and the
    description its own `--help` opens with: argparse keeps `help=` for the parent's listing
    only, which the installed CLI's frame fills in for every command and this script does by
    hand."""
    top = argparse.ArgumentParser(
        prog="scripts/release.py",
        description="Release discipline for the drybag repository itself.",
        epilog=JSON_EPILOG,
    )
    sub = top.add_subparsers(dest="command", metavar="<command>")

    def command(name: str, sentence: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=sentence, description=sentence, epilog=JSON_EPILOG)

    cmd = command("check", "every version string agrees")
    cmd.add_argument("--root", default=".", help=ROOT_HELP)
    cmd.add_argument("--tag", default=None, help=TAG_HELP)
    cmd.set_defaults(func=run_check)
    notes = command("notes", "assemble CHANGELOG.md from changelog.d through towncrier")
    notes.add_argument("--version", required=True, help="the version to assemble the section under")
    notes.add_argument("--draft", action="store_true", help="render without writing")
    notes.add_argument("--root", default=".", help=ROOT_HELP)
    notes.set_defaults(func=run_notes)
    pinning = command("pin", "pin the plugin commit of HEAD in the marketplace entry")
    pinning.add_argument("--remote", default=PLUGIN_URL, help=REMOTE_HELP)
    pinning.add_argument("--root", default=".", help=ROOT_HELP)
    pinning.set_defaults(func=run_pin)
    return top


def main(argv: list[str] | None = None) -> int:
    return run(sys.argv[1:] if argv is None else argv, parser=parser())


if __name__ == "__main__":
    sys.exit(main())
