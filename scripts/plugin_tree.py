#!/usr/bin/env python3
"""The plugin's tree: the nine paths it is published with, read from a commit of this repository.

    uv run python scripts/plugin_tree.py manifest --root DIR --rev REV [--exact]
                                         [--manifest-file FILE]
    uv run python scripts/plugin_tree.py render --root DIR --rev REV --out DIR
                                       [--manifest-file FILE]
    uv run python scripts/plugin_tree.py commit --root DIR --rev REV --git-dir DIR
                                       [--manifest-file FILE] [--no-parent] [--require-pin]

This repository is more than the plugin: its tests, documents, plans and tooling ship nowhere. The
plugin is published from a repository of its own whose root is the tree this script generates, and
`PLUGIN_PATHS` is the one place its paths are named: the release check, the payload test and the
workflows that build, install and attest the plugin all run this script, or, in a test, import it.

**Read from a commit, never from the disk.** The directory, the attestation and the plugin
repository each see a commit, so a file edited, deleted or only staged here is not in what they
see, and must not be in what this script reports either. Every byte comes from `git ls-tree` and
`git cat-file` at one commit, resolved once; no filter, attribute or line-ending conversion of a
working tree touches it.

**The manifest is the text a release attests.** One line naming its format, then one line per
file: its git mode, the sha256 of its bytes and its path. `publish_plugin.py` compares two of them
and nothing else, which is why a path holding a control character, or one that is not UTF-8, is
refused rather than written: a `\\n` in a name would forge a line, and a C1 control or a Unicode
line separator breaks the line a terminal or an editor shows.

**The plugin repository's commit is computed here,** as a function of the source commit alone: the
tree's objects, and a commit of them with a fixed author, committer and date, a message naming the
version, and as its parent the commit the marketplace pinned at the source commit's first parent.
So the release commit can name, in its marketplace entry, the commit the plugin repository will
hold, and anyone holding the source commit and its first parent can compute that commit again and
compare.

The commands go through the CLI frame's `run`, as `scripts/release.py`'s do: `--json` anywhere on
the line before a bare `--`, exit `0`, `1` when `commit --require-pin` finds the source commit
pinning another commit, and `2` for a refusal.
"""

from __future__ import annotations

import argparse
import hashlib
import operator
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

# Before the CLI frame exists, so said here: an interpreter without this repository's `stayfixed`
# would otherwise end in a traceback and exit `1`, which is `commit --require-pin`'s finding.
try:
    from stayfixed import fsops
    from stayfixed.cli import JSON_EPILOG, run
    from stayfixed.errors import Failure, Refusal
    from stayfixed.gitenv import (
        NO_ANSWER,
        QUERY_TIMEOUT_SECONDS,
        answer_bytes,
        git_run,
        pipe_encoding,
    )
    from stayfixed.jsonobject import json_object
    from stayfixed.printed import clipped, quoted
    from stayfixed.release.api import PACKAGE
    from stayfixed.result import Result
except ImportError as exc:
    sys.stderr.write(
        f"scripts/plugin_tree.py: refused: {exc}; run it with `uv run python "
        "scripts/plugin_tree.py`, which puts this repository's stayfixed on the path\n"
    )
    sys.exit(2)

# What the plugin's runtime reads, and nothing else: the two manifests, the hooks and their
# wrapper, the launcher and the package it puts on `sys.path`, the skills the harness
# loads, and the two files every published repository carries. One more path the runtime never
# reads: the icon the plugin directory takes for the listing, once, at the first submission.
PLUGIN_PATHS: tuple[str, ...] = (
    ".claude-plugin/plugin.json",
    ".claude-plugin/icon.png",
    ".codex-plugin/plugin.json",
    "hooks",
    "scripts/stayfixed",
    "src/stayfixed",
    "skills",
    "README.md",
    "LICENSE",
)
# The manifest's first line: a reader that meets another refuses to compare.
FORMAT = "stayfixed-plugin-tree 1"
# The only modes a member may have. A symlink (`120000`) and a submodule (`160000`) are what the
# plugin directory blocks where the plugin loads them, and every path here is one it loads.
REGULAR_MODES = frozenset({"100644", "100755"})
# The permission bits a rendered file gets for its git mode, whatever the umask says.
PERMISSIONS = {"100644": 0o644, "100755": 0o755}
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | os.O_CLOEXEC
# Before the subcommand on every git this script runs. `--no-replace-objects`: a `refs/replace/`
# ref makes git read one object as another, and the tree read here is the commit's own, not what
# a replacement says it is. `safe.bareRepository=all`: `--root` is the repository the caller
# names, and `publish_plugin.py` names its scratch bare repository, which an owner's
# `safe.bareRepository=explicit` would otherwise refuse, since `git -C` finds it rather than is
# given it.
GIT_OPTIONS = ("--no-replace-objects", "-c", "safe.bareRepository=all")
# A full object name as git prints one: SHA-1's 40 hex characters or SHA-256's 64, lower case.
OBJECT_NAME = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
# The two Unicode line breaks that are neither a C0 nor a C1 control: an editor or a terminal
# ends a line at each.
_LINE_SEPARATORS = frozenset({"\u2028", "\u2029"})


@dataclass(frozen=True)
class Member:
    path: str  # POSIX, relative to the plugin root, as git lists it
    mode: str  # "100644" or "100755"
    content: bytes


@dataclass(frozen=True)
class Tree:
    commit: str  # the full object name of the commit the tree was read at
    members: tuple[Member, ...]  # sorted by path


def _under(path: str, entry: str) -> bool:
    """Whether `path` is the plugin path `entry` or inside it: `hooksx` is not under `hooks`."""
    return path == entry or path.startswith(entry + "/")


def is_plugin_path(path: str) -> bool:
    """Whether `path` is one of `PLUGIN_PATHS` or inside one."""
    return any(_under(path, entry) for entry in PLUGIN_PATHS)


def _control(path: str) -> bool:
    """Whether `path` holds a C0 control, DEL, a C1 control or a Unicode line separator."""
    return any(
        ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F or char in _LINE_SEPARATORS for char in path
    )


def _answered(code: int, what: str) -> None:
    """Refuse a git that gave no answer in `NO_ANSWER`'s words, rather than as an exit code."""
    if code == -1:
        raise Refusal(f"{what} gave no answer: {NO_ANSWER}")


def _git(
    root: Path, *args: str, stdin: str | None = None, timeout: float = QUERY_TIMEOUT_SECONDS
) -> tuple[int, str]:
    """`git <args>` in the repository read, after `GIT_OPTIONS`: its exit code and answer, or a
    refusal in `NO_ANSWER`'s words when it gave none. Every read of `root` goes through here, and
    every write of the git dir through `_store`, so no caller can print `git_run`'s `-1` as an
    exit code: `tests/scripts/test_plugin_tree.py` holds that no other function calls `git_run`."""
    code, answer = git_run(root, *GIT_OPTIONS, *args, stdin=stdin, timeout=timeout)
    _answered(code, f"git {args[0]} in {root}")
    return code, answer


def peel(root: Path, rev: str, kind: str) -> str:
    """The `kind` (`commit` or `tree`) `rev` peels to in `root`, as git's full object name, or a
    refusal naming `rev`: where this script resolves a rev it is handed. `_first_parent` asks git
    only whether an id a commit object names is a commit this clone holds."""
    code, answer = _git(root, "rev-parse", "--verify", "--end-of-options", f"{rev}^{{{kind}}}")
    name = answer.removesuffix("\n")
    if code != 0:
        raise Refusal(f"{quoted(rev)} names no {kind} in {root} (git rev-parse exited {code})")
    if not OBJECT_NAME.fullmatch(name):
        raise Refusal(f"git rev-parse answered {quoted(name)} for {quoted(rev)} in {root}")
    return name


def _listing(root: Path, sha: str, *, exact: bool) -> list[tuple[str, str, str]]:
    """`(mode, object, path)` for every path git lists at `sha`: under the plugin's paths, or, when
    `exact`, the whole tree."""
    pathspec = () if exact else ("--", *PLUGIN_PATHS)
    code, answer = _git(root, "ls-tree", "-r", "-z", "--full-tree", sha, *pathspec)
    if code != 0:
        raise Refusal(f"git ls-tree of {sha} exited {code} in {root}")
    rows = []
    for record in answer.split("\0"):
        if not record:
            continue
        # `<mode> <type> <object>\t<path>`: the path is everything after the tab, unquoted under -z.
        meta, path = record.split("\t", 1)
        mode, _kind, obj = meta.split()
        rows.append((mode, obj, path))
    return rows


def _blobs(root: Path, objects: list[str]) -> dict[str, bytes]:
    """Each object's bytes, from one `git cat-file --batch`."""
    if not objects:
        return {}
    code, answer = _git(root, "cat-file", "--batch", stdin="".join(obj + "\n" for obj in objects))
    if code != 0:
        raise Refusal(f"git cat-file --batch exited {code} in {root}")
    out, at, blobs = answer_bytes(answer), 0, {}
    for obj in objects:
        # `<object> <type> <size>\n<content>\n`, once per object asked, in the order asked.
        header_end = out.find(b"\n", at)
        header = out[at:header_end].split() if header_end != -1 else []
        if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
            raise Refusal(f"git cat-file did not answer {obj} as a blob in {root}")
        size = int(header[2])
        content = out[header_end + 1 : header_end + 1 + size]
        # A slice past the end is short, not an error: an answer cut off inside a blob would
        # otherwise be read as that blob's bytes.
        if len(content) != size:
            raise Refusal(f"git cat-file's answer in {root} ended inside {obj}")
        blobs[obj] = content
        at = header_end + 1 + size + 1
    return blobs


def read(root: Path, rev: str, *, exact: bool = False) -> Tree:
    """The commit `rev` names, resolved once, and every file under the plugin's paths at it,
    sorted by path.

    Refused: a rev that names no commit; a plugin path the commit does not hold; a member that is
    not a regular file, by its path and mode; a path that is not UTF-8 or that holds a control
    character; and, with `exact`, any path at the commit outside every plugin path.
    """
    sha = peel(root, rev, "commit")
    rows = []
    for mode, obj, raw in _listing(root, sha, exact=exact):
        if not fsops.utf_8_name(raw):
            raise Refusal(f"{quoted(raw)} at {sha} is not UTF-8; a plugin path must be")
        # The bytes git printed, read as the UTF-8 they were just shown to be, whatever the
        # filesystem's codec decoded them as.
        path = os.fsencode(raw).decode("utf-8")
        if _control(path):
            raise Refusal(f"{quoted(path)} at {sha} holds a control character")
        if not is_plugin_path(path):
            raise Refusal(f"{quoted(path)} at {sha} is outside every plugin path")
        if mode not in REGULAR_MODES:
            raise Refusal(f"{quoted(path)} at {sha} has mode {mode}, not a regular file's")
        rows.append((path, mode, obj))
    for entry in PLUGIN_PATHS:
        if not any(_under(path, entry) for path, _, _ in rows):
            raise Refusal(f"{entry} is missing at {sha}; the plugin cannot be built without it")
    blobs = _blobs(root, sorted({obj for _, _, obj in rows}))
    found = (Member(path, mode, blobs[obj]) for path, mode, obj in rows)
    return Tree(sha, tuple(sorted(found, key=operator.attrgetter("path"))))


def manifest(entries: Iterable[Member]) -> str:
    """`FORMAT` on the first line, then `<mode> <sha256> <path>` for each member, in the order
    given: `read` gives them sorted by path."""
    lines = [FORMAT]
    for member in entries:
        lines.append(f"{member.mode} {hashlib.sha256(member.content).hexdigest()} {member.path}")
    return "".join(line + "\n" for line in lines)


def _empty_or_absent(out: Path) -> bool:
    if not os.path.lexists(out):
        return True
    return fsops.is_dir(out) and not fsops.is_symlink(out) and not any(out.iterdir())


def render(entries: Iterable[Member], out: Path) -> None:
    """Write each member into `out`, which must be absent or an empty directory: its bytes as
    they are, and exactly the permissions its git mode names. Nothing else is written."""
    if not _empty_or_absent(out):
        raise Refusal(f"{out} is not an empty directory; the plugin tree is rendered into one")
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refusal(f"{out} cannot be made: {exc.strerror or exc}") from None
    for member in entries:
        try:
            fsops.mkdirs_within(out, member.path)
            with fsops.open_within(out, member.path) as (dir_fd, name):
                permissions = PERMISSIONS[member.mode]
                descriptor = os.open(name, _CREATE, permissions, dir_fd=dir_fd)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(member.content)
                    # The mode `open` is given passes through the umask; this does not.
                    os.fchmod(handle.fileno(), permissions)
        except fsops.UnsafePath as exc:
            raise Refusal(f"{quoted(member.path)} cannot be rendered: {exc}") from None
        except OSError as exc:
            # A full disk, a quota, a permission: said as the refusal it is, with the path it
            # stopped at, rather than escaping as an internal error.
            raise Refusal(
                f"{quoted(member.path)} could not be written into {out}: {exc.strerror or exc}"
            ) from None


# --- The plugin repository's commit -------------------------------------------------------------

# The repository the plugin's tree is read from, as the commit message names it.
SOURCE_REPOSITORY = "stayfixed/stayfixed"
# Where, at a source commit, the marketplace names the plugin commit it pins; the entry is the one
# named `PACKAGE`, as `scripts/release.py` reads it.
MARKETPLACE = ".claude-plugin/marketplace.json"
# The manifest whose `version` the commit message names, and the only shape that version may take:
# ASCII digits, as the release's tag spells them, since `\d` also takes every other script's.
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# The author and the committer of every plugin commit, with its date: fixed, so the commit is the
# same whoever computes it and whenever. Its message names the version and not the source commit,
# so the release commit can carry the result.
IDENTITY = "stayfixed <release@stayfixed.invalid> 0 +0000"
# A commit id of the plugin repository, which is SHA-1 whatever the owner's configuration says.
SHA1 = re.compile(r"[0-9a-f]{40}")
# On every git that runs in the git dir, `init` included: none of the owner's hooks runs there.
# `core.hooksPath` is read before any repository exists, so a `reference-transaction` hook would
# otherwise run as `init` writes `HEAD`.
NO_HOOKS = ("-c", "core.hooksPath=/dev/null")


@dataclass(frozen=True)
class PluginCommit:
    rev: str  # the source commit
    version: str  # .claude-plugin/plugin.json's version at rev
    files: int
    tree: str
    parent: str | None  # the sha the marketplace pins at rev^1, or None
    commit: str
    pinned: str | None  # the sha the marketplace pins at rev


def commit_text(tree: str, parent: str | None, version: str) -> str:
    """The plugin commit's object text: the tree, the parent when there is one, the fixed
    identity, and a message naming the version."""
    lineage = f"parent {parent}\n" if parent is not None else ""
    return (
        f"tree {tree}\n{lineage}author {IDENTITY}\ncommitter {IDENTITY}\n\n"
        f"stayfixed {version}\n\nThe plugin tree of {SOURCE_REPOSITORY} at v{version}.\n"
    )


def _json_file(root: Path, sha: str, path: str, content: bytes) -> dict[str, object]:
    said = f"{path} at {sha} in {root}"
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal(f"{said} is not UTF-8 text") from None
    return json_object(text, said, error=Refusal)


def pinned_sha(root: Path, rev: str) -> str | None:
    """The `sha` the marketplace's plugin entry pins at the commit `rev` names, or `None` when
    the commit holds no marketplace or its entry pins no `sha`.

    Read as `scripts/release.py` reads the entry: `plugins` a list of objects, exactly one of them
    named `stayfixed`, and its `source` an object. Refused, each in its own words naming the commit
    and the marketplace: a marketplace that is not JSON, a `plugins` that is not a list of
    objects, not that one entry, a `source` that is no object, or a `sha` that is not 40 lowercase
    hex characters.
    """
    sha = peel(root, rev, "commit")
    said = f"{MARKETPLACE} at {sha} in {root}"
    code, answer = _git(root, "ls-tree", "-z", "--full-tree", sha, "--", MARKETPLACE)
    if code != 0:
        raise Refusal(f"git ls-tree of {sha} exited {code} in {root}")
    record = answer.split("\0", 1)[0]
    if not record:
        return None
    mode, kind, obj = record.split("\t", 1)[0].split()
    if kind != "blob" or mode not in REGULAR_MODES:
        raise Refusal(f"{said} has mode {mode}, not a regular file's")
    data = _json_file(root, sha, MARKETPLACE, _blobs(root, [obj])[obj])
    # As `scripts/release.py` reads `plugins`: an absent one is no entries, and one that is not a
    # list of objects is refused, never skipped over to an entry behind it.
    plugins = data.get("plugins", [])
    if not isinstance(plugins, list) or not all(isinstance(entry, dict) for entry in plugins):
        raise Refusal(f"{said} is valid JSON but its plugins is not a list of objects")
    named = [entry for entry in plugins if entry.get("name") == PACKAGE]
    if len(named) != 1:
        raise Refusal(
            f"{said} has {len(named)} entries named {PACKAGE!r}; the pin is read from exactly one"
        )
    source = named[0].get("source")
    if not isinstance(source, dict):
        raise Refusal(
            f"{said} gives the entry {PACKAGE!r} a source that is no object; the pin is read from "
            "the source object's sha"
        )
    if "sha" not in source:
        return None
    pin = source["sha"]
    if not isinstance(pin, str) or SHA1.fullmatch(pin) is None:
        shown = clipped(pin) if isinstance(pin, str) else f"a {type(pin).__name__}"
        raise Refusal(f"{said} pins sha {shown}, which is no commit id of 40 lowercase hex digits")
    return pin


def _first_parent(root: Path, sha: str) -> str | None:
    """The first parent the commit `sha`'s object names, or `None` when it names none; refused
    when the repository does not hold it, as a shallow clone does not."""
    code, answer = _git(root, "cat-file", "commit", sha)
    if code != 0:
        raise Refusal(f"git cat-file of {sha} exited {code} in {root}")
    header = answer.split("\n\n", 1)[0].split("\n")
    parents = [line.removeprefix("parent ") for line in header if line.startswith("parent ")]
    if not parents:
        return None
    first = parents[0]
    code, _ = _git(root, "cat-file", "-e", f"{first}^{{commit}}")
    if code != 0:
        raise Refusal(
            f"the commit before {sha} is not in this clone; fetch it (fetch-depth: 2): the plugin "
            f"commit's parent is the sha {MARKETPLACE} pins there"
        )
    return first


def _version(root: Path, tree: Tree) -> str:
    """`plugin.json`'s `version` among the members, which the commit message names: `X.Y.Z`, three
    runs of ASCII digits and nothing else.

    The one input to the commit text that is not an object name, so the one that could vary it:
    the text reaches `hash-object` in the pipe's codec, where a character outside ASCII becomes
    other bytes under another locale, and a line break would add lines to the message."""
    found = [member for member in tree.members if member.path == PLUGIN_MANIFEST]
    if not found:
        raise Refusal(f"{PLUGIN_MANIFEST} at {tree.commit} in {root} is no file")
    version = _json_file(root, tree.commit, PLUGIN_MANIFEST, found[0].content).get("version")
    if not isinstance(version, str):
        raise Refusal(f"{PLUGIN_MANIFEST} at {tree.commit} in {root} names no version string")
    if not VERSION.fullmatch(version):
        raise Refusal(
            f"{PLUGIN_MANIFEST} at {tree.commit} in {root} names version {clipped(version)}, "
            "which is not X.Y.Z in ASCII digits"
        )
    return version


def _store(git_dir: Path, *args: str, stdin: str | None = None) -> tuple[int, str]:
    """`git --git-dir=<git_dir>` with no hooks, `args` after it: named, never found, so the
    owner's `safe.bareRepository = explicit` has nothing to refuse. A git that gave no answer is
    refused in `NO_ANSWER`'s words."""
    code, answer = git_run(
        git_dir,
        f"--git-dir={git_dir}",
        *NO_HOOKS,
        *args,
        stdin=stdin,
        timeout=QUERY_TIMEOUT_SECONDS,
    )
    _answered(code, f"git {args[0]} in {git_dir}")
    return code, answer


def _prepared(git_dir: Path) -> None:
    """`git_dir` as a bare SHA-1 repository: made when absent or an empty directory, and
    otherwise refused unless it already is one."""
    if _empty_or_absent(git_dir):
        try:
            git_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Refusal(f"{git_dir} cannot be made: {exc.strerror or exc}") from None
        # No template: `init` copies the owner's `init.templateDir` into the repository, its
        # `config` among it, which every later git here would read as this repository's own. The
        # object format is forced: the owner's `init.defaultObjectFormat` would choose it.
        code, _ = _store(
            git_dir, "init", "--bare", "--quiet", "--template=", "--object-format=sha1"
        )
        if code != 0:
            raise Refusal(f"git init --bare exited {code} in {git_dir}")
        return
    code, answer = _store(git_dir, "rev-parse", "--is-bare-repository", "--show-object-format")
    if code != 0 or answer.split() != ["true", "sha1"]:
        raise Refusal(
            f"{git_dir} is neither absent, an empty directory, nor a bare SHA-1 repository; the "
            "plugin commit is written into one"
        )


def _write_blobs(git_dir: Path, entries: Sequence[Member]) -> list[str]:
    """Each member's blob, written by one `git fast-import` from its bytes in memory: no file is
    hashed, so no filter, attribute or line-ending conversion touches one, and no filesystem
    folds two names into one."""
    stream = b"".join(
        b"blob\nmark :%d\ndata %d\n%s\n" % (number, len(member.content), member.content)
        for number, member in enumerate(entries, 1)
    )
    with tempfile.TemporaryDirectory() as scratch:
        marks = Path(scratch) / "marks"
        code, _ = _store(
            git_dir,
            "fast-import",
            "--quiet",
            f"--export-marks={marks}",
            stdin=stream.decode(pipe_encoding(), "surrogateescape"),
        )
        if code != 0:
            raise Refusal(f"git fast-import exited {code} in {git_dir}")
        try:
            listed = marks.read_text(encoding="ascii").split()
        except (OSError, UnicodeDecodeError) as exc:
            raise Refusal(f"git fast-import's marks in {git_dir} cannot be read: {exc}") from None
    named = dict(zip(listed[::2], listed[1::2], strict=False))
    blobs = [named.get(f":{number}", "") for number in range(1, len(entries) + 1)]
    if not all(SHA1.fullmatch(blob) for blob in blobs):
        raise Refusal(f"git fast-import in {git_dir} did not name a blob for every member")
    return blobs


def _mktree(git_dir: Path, entries: list[tuple[str, str, str, str]]) -> str:
    """One tree object from `(mode, kind, object, name)` entries; `mktree` sorts them itself."""
    # Each name goes to git as its UTF-8 bytes, whatever the pipe's codec: `git_run` encodes
    # `stdin` with that codec and `surrogateescape`, which this decoding undoes exactly.
    given = "".join(
        f"{mode} {kind} {obj}\t{name.encode('utf-8').decode(pipe_encoding(), 'surrogateescape')}\0"
        for mode, kind, obj, name in entries
    )
    code, answer = _store(git_dir, "mktree", "-z", stdin=given)
    tree = answer.removesuffix("\n")
    if code != 0 or not SHA1.fullmatch(tree):
        raise Refusal(f"git mktree exited {code} in {git_dir}")
    return tree


def _write_trees(git_dir: Path, entries: Sequence[Member], blobs: list[str]) -> str:
    """The root tree holding each member at its mode, and nothing else: one `mktree` per
    directory, the deepest first, so each directory's tree exists before its parent names it."""
    directories: dict[str, list[tuple[str, str, str, str]]] = {"": []}
    for member, blob in zip(entries, blobs, strict=True):
        directory, _, name = member.path.rpartition("/")
        directories.setdefault(directory, []).append((member.mode, "blob", blob, name))
        while directory:
            directory = directory.rpartition("/")[0]
            directories.setdefault(directory, [])
    for directory in sorted(directories, key=lambda d: d.count("/") + bool(d), reverse=True):
        if directory:
            above, _, name = directory.rpartition("/")
            tree = _mktree(git_dir, directories[directory])
            directories[above].append(("040000", "tree", tree, name))
    return _mktree(git_dir, directories[""])


def plugin_commit(
    root: Path, rev: str, git_dir: Path, *, root_commit: bool = False
) -> tuple[PluginCommit, Tree]:
    """The plugin repository's commit of the source commit `rev` names, written into `git_dir`,
    and the tree it was made of.

    Its tree is `read(root, rev)`'s members; its parent the `sha` the marketplace pins at `rev`'s
    first parent, or none when that pins none or `root_commit` says so; its text `commit_text`'s.
    `git_dir` is made a bare SHA-1 repository when it is absent or empty, and must be one
    otherwise. Refused: a first parent the clone does not hold, a malformed pin at either commit,
    a `plugin.json` naming no `X.Y.Z` version, and every git that fails or gives no answer.
    """
    tree = read(root, rev)
    version = _version(root, tree)
    first = None if root_commit else _first_parent(root, tree.commit)
    parent = None if first is None else pinned_sha(root, first)
    pinned = pinned_sha(root, tree.commit)
    # Absolute: every git here runs `-C <git_dir>`, and a relative `--git-dir` after it would be
    # read from there.
    git_dir = git_dir.absolute()
    _prepared(git_dir)
    root_tree = _write_trees(git_dir, tree.members, _write_blobs(git_dir, tree.members))
    text = commit_text(root_tree, parent, version)
    code, answer = _store(git_dir, "hash-object", "-t", "commit", "-w", "--stdin", stdin=text)
    made = answer.removesuffix("\n")
    if code != 0 or not SHA1.fullmatch(made):
        raise Refusal(f"git hash-object of the plugin commit exited {code} in {git_dir}")
    found = PluginCommit(
        rev=tree.commit,
        version=version,
        files=len(tree.members),
        tree=root_tree,
        parent=parent,
        commit=made,
        pinned=pinned,
    )
    return found, tree


# --- The commands -------------------------------------------------------------------------------


def _write_manifest(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def run_manifest(args: argparse.Namespace) -> Result:
    tree = read(Path(args.root), args.rev, exact=args.exact)
    if args.manifest_file is not None:
        _write_manifest(Path(args.manifest_file), manifest(tree.members))
    files = len(tree.members)
    return Result(
        f"the plugin tree at {tree.commit} holds {files} files",
        {"rev": tree.commit, "files": files},
    )


def run_render(args: argparse.Namespace) -> Result:
    root, out = Path(args.root), Path(args.out)
    written = None if args.manifest_file is None else Path(args.manifest_file)
    if written is not None and written.resolve().is_relative_to(out.resolve()):
        raise Refusal(f"--manifest-file {written} is inside --out {out}; it describes the tree")
    tree = read(root, args.rev)
    render(tree.members, out)
    # Last, after every member: a manifest on disk says its tree was written whole.
    if written is not None:
        _write_manifest(written, manifest(tree.members))
    files = len(tree.members)
    return Result(
        f"rendered the plugin tree at {tree.commit} into {out}: {files} files",
        {"rev": tree.commit, "files": files},
    )


def run_commit(args: argparse.Namespace) -> Result:
    found, tree = plugin_commit(
        Path(args.root), args.rev, Path(args.git_dir), root_commit=args.no_parent
    )
    if args.manifest_file is not None:
        # Last, after every object: a manifest on disk says its commit was written whole.
        _write_manifest(Path(args.manifest_file), manifest(tree.members))
    pinned = found.pinned or "no sha"
    if args.require_pin and found.pinned != found.commit:
        raise Failure(
            f"{MARKETPLACE} at {found.rev} pins {pinned}, and the plugin commit its tree makes "
            f"is {found.commit}"
        )
    return Result(
        f"the plugin commit of {found.rev} is {found.commit} ({found.files} files); "
        f"{MARKETPLACE} there pins {pinned}",
        {"format": FORMAT, **asdict(found)},
    )


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="scripts/plugin_tree.py",
        description="The plugin's tree, read from a commit of this repository.",
        epilog=JSON_EPILOG,
    )
    sub = top.add_subparsers(dest="command", metavar="<command>")

    def command(name: str, sentence: str) -> argparse.ArgumentParser:
        cmd = sub.add_parser(name, help=sentence, description=sentence, epilog=JSON_EPILOG)
        cmd.add_argument("--root", required=True, help="the repository to read")
        cmd.add_argument("--rev", required=True, help="the commit to read the tree from")
        return cmd

    listing = command("manifest", "count the plugin tree at a commit, and write its manifest")
    listing.add_argument(
        "--exact", action="store_true", help="refuse a commit holding any path outside the plugin"
    )
    listing.add_argument("--manifest-file", default=None, help="where to write the manifest")
    listing.set_defaults(func=run_manifest)
    rendering = command("render", "write the plugin tree at a commit into an empty directory")
    rendering.add_argument("--out", required=True, help="an absent or empty directory")
    rendering.add_argument(
        "--manifest-file", default=None, help="where to write the manifest, outside --out"
    )
    rendering.set_defaults(func=run_render)
    committing = command("commit", "write the plugin repository's commit of a source commit")
    committing.add_argument(
        "--git-dir", required=True, help="an absent or empty directory, or a bare SHA-1 repository"
    )
    committing.add_argument("--manifest-file", default=None, help="where to write the manifest")
    committing.add_argument(
        "--no-parent",
        action="store_true",
        help="give the commit no parent, whatever the first parent's marketplace pins",
    )
    committing.add_argument(
        "--require-pin",
        action="store_true",
        help="exit 1 unless the source commit's marketplace pins this commit",
    )
    committing.set_defaults(func=run_commit)
    return top


def main(argv: list[str] | None = None) -> int:
    return run(sys.argv[1:] if argv is None else argv, parser=parser())


if __name__ == "__main__":
    sys.exit(main())
