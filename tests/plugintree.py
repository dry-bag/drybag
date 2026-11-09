"""The builders of a source repository holding the plugin's nine paths, for the tests reading one.

`scripts/plugin_tree.py`'s own tests, the payload walk (`tests/test_payload.py`) and the release
check's tag tests (`tests/scripts/test_release.py`) each built such a repository with a copy of
these, and the copies had drifted: three spellings of the paths, two of the files under them,
and a payload test importing its builder from another test module. Here once, as
`tests/gitfixture.py` is for the `git` they run.

The nine paths and the files under them are spelled out here and never read from the script's
`PLUGIN_PATHS`: an expectation read from the subject is the subject compared with itself. Every
`git` goes through `tests.gitfixture.git`, the sealed runner, so the developer's configuration
never shapes a fixture; a test that means the owner's configuration writes it into the test
`HOME`'s `.gitconfig`, which only the code under test reads.

The plugin commit a test expects is computed the same way in every module that expects one: its
text spelled out (`literal`), its tree and its id computed by git (`plugin_tree_id`, `hashed`),
and never by the script's `plugin_commit`.

`tool_source` is the publisher's source: a repository whose tag carries its own
`scripts/plugin_tree.py` and `src/drybag`, as a release's does, so the publisher can run the
tag's code; `released` adds a later release on top of one.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import EllipsisType

from tests.gitfixture import git, git_bytes

# The eight paths the runtime reads and the directory's listing icon, as the plugin's tree must
# hold them.
NINE = (
    ".claude-plugin/plugin.json",
    ".claude-plugin/icon.png",
    ".codex-plugin/plugin.json",
    "hooks",
    "scripts/drybag",
    "src/drybag",
    "skills",
    "README.md",
    "LICENSE",
)
# One file under each of the nine, with its git mode: the wrapper and the launcher are executable,
# and both manifests name the version a plugin commit's message carries.
PLUGIN_FILES: dict[str, tuple[bytes, str]] = {
    ".claude-plugin/plugin.json": (b'{"name": "drybag", "version": "1.2.3"}\n', "100644"),
    ".claude-plugin/icon.png": (b"\x89PNG\r\n\x1a\n\0", "100644"),
    ".codex-plugin/plugin.json": (b'{"name": "drybag", "version": "1.2.3"}\n', "100644"),
    "hooks/hooks.json": (b"{}\n", "100644"),
    "hooks/run-hook.sh": (b"#!/bin/sh\nexit 0\n", "100755"),
    "scripts/drybag": (b"#!/usr/bin/env python3\n", "100755"),
    "src/drybag/__init__.py": (b'__version__ = "1.2.3"\n', "100644"),
    "skills/close-bug/SKILL.md": (b"# close a bug\n", "100644"),
    "README.md": (b"# drybag\n", "100644"),
    "LICENSE": (b"MIT\n", "100644"),
}


def write(root: Path, files: dict[str, tuple[bytes, str]]) -> None:
    """Each file of `files` under `root`: its bytes, and the permissions its git mode names."""
    for path, (content, mode) in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o755 if mode == "100755" else 0o644)


def commit(root: Path, message: str = "a commit") -> str:
    """Everything under `root` committed, and the commit's id."""
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


def plugin_source(tmp_path: Path, files: dict[str, tuple[bytes, str]] | None = None) -> Path:
    """An initialised repository at `tmp_path / "source"` whose one commit holds `files`, or
    `PLUGIN_FILES` when none are given."""
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, files or PLUGIN_FILES)
    commit(root)
    return root


def plugin_tree_id(root: Path, rev: str = "HEAD", paths: tuple[str, ...] = NINE) -> str:
    """The tree git writes for `paths` (the nine) at `rev` and nothing else, through an index of
    its own: the tree a plugin commit of `rev` names, computed without the script."""
    with tempfile.TemporaryDirectory() as scratch:
        index = str(Path(scratch) / "index")
        git(root, "read-tree", "--empty", GIT_INDEX_FILE=index)
        git(root, "reset", "-q", rev, "--", *paths, GIT_INDEX_FILE=index)
        return git(root, "write-tree", GIT_INDEX_FILE=index).strip()


def literal(tree: str, parent: str | None, version: str = "1.2.3") -> str:
    """The plugin commit's text for `version`, spelled out."""
    lineage = f"parent {parent}\n" if parent is not None else ""
    return (
        f"tree {tree}\n"
        f"{lineage}"
        "author drybag <release@drybag.invalid> 0 +0000\n"
        "committer drybag <release@drybag.invalid> 0 +0000\n"
        "\n"
        f"drybag {version}\n"
        "\n"
        f"The plugin tree of dry-bag/drybag at v{version}.\n"
    )


def hashed(where: Path, text: str) -> str:
    """The id git gives `text` as a commit object, computed by git and written nowhere."""
    answer = git_bytes(where, "hash-object", "-t", "commit", "--stdin", stdin=text.encode())
    return answer.decode().strip()


# --- The publisher's source: a tag carrying its own code -----------------------------------------

# This repository, whose `scripts/plugin_tree.py` and `src/drybag` a tool source carries.
REPOSITORY = Path(__file__).resolve().parents[1]
MARKETPLACE = ".claude-plugin/marketplace.json"
# The plugin repository's URL, spelled once for every test module that builds or expects a
# marketplace entry, and never read from a script: the scripts' copies are held to it.
PLUGIN_URL = "https://github.com/dry-bag/drybag-plugin.git"
# What a release's tag carries beside the plugin and the publisher runs: the tag's own code.
TOOL_PATHS = ("scripts/plugin_tree.py", "src/drybag")


def pinned_marketplace(
    sha: object, version: str = "1.2.3", *, entries: int = 1
) -> tuple[bytes, str]:
    """The marketplace's file: `entries` entries `drybag` (one unless a case means more), each a
    url source at `v<version>` pinning `sha` beside its `ref`, whatever `sha` is, or no `sha` when
    it is `None`."""
    source: dict[str, object] = {"source": "url", "url": PLUGIN_URL, "ref": f"v{version}"}
    if sha is not None:
        source["sha"] = sha
    plugins = [{"name": "drybag", "source": source} for _ in range(entries)]
    text = json.dumps({"name": "drybag", "plugins": plugins}, indent=2) + "\n"
    return text.encode("utf-8"), "100644"


def tool_files(where: Path) -> dict[str, tuple[bytes, str]]:
    """This branch's `scripts/plugin_tree.py` and every file `git ls-files src/drybag` lists:
    each its working-tree bytes at the mode the index gives it. `where` is the `HOME` the listing
    runs under, inside the test's own directory."""
    listing = git(REPOSITORY, "ls-files", "-s", "-z", "--", *TOOL_PATHS, home=where)
    files = {}
    for record in listing.split("\0"):
        if record:
            meta, path = record.split("\t", 1)
            files[path] = ((REPOSITORY / path).read_bytes(), meta.split()[0])
    return files


def _pin_and_tag(root: Path, version: str, parent: str | None, paths: tuple[str, ...]) -> str:
    """`HEAD` amended so its marketplace pins the plugin commit of its tree over `paths`, whose
    parent is `parent`, and tagged `v<version>` by an annotated tag; the pin."""
    pin = hashed(root, literal(plugin_tree_id(root, paths=paths), parent, version))
    write(root, {MARKETPLACE: pinned_marketplace(pin, version)})
    git(root, "commit", "-q", "-a", "--amend", "--no-edit")
    git(root, "tag", "-a", f"v{version}", "-m", f"v{version}")
    return pin


def tool_source(
    tmp_path: Path,
    *,
    plugin_tree: bytes | None = None,
    extra: dict[str, tuple[bytes, str]] | None = None,
    paths: tuple[str, ...] = NINE,
) -> Path:
    """A release's source at `tmp_path / "source"`: `PLUGIN_FILES`, this branch's own
    `scripts/plugin_tree.py` (or `plugin_tree`) and `src/drybag`, and `extra`, in one commit
    whose marketplace pins the plugin commit its tree over `paths` makes, with no parent: the
    first release. Tagged `v1.2.3`, annotated, as `plugin.json` says."""
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q", "-b", "dev")
    files = {**PLUGIN_FILES, **tool_files(tmp_path)}
    if plugin_tree is not None:
        files["scripts/plugin_tree.py"] = (plugin_tree, files["scripts/plugin_tree.py"][1])
    write(root, {**files, **(extra or {}), MARKETPLACE: pinned_marketplace(None)})
    commit(root, "the release commit")
    _pin_and_tag(root, "1.2.3", None, paths)
    return root


def pinned_at(root: Path, rev: str = "HEAD") -> str | None:
    """The `sha` the marketplace pins at `rev`, read by the test from the file git holds."""
    text = git(root, "show", f"{rev}:{MARKETPLACE}")
    pin = json.loads(text)["plugins"][0]["source"].get("sha")
    return pin if isinstance(pin, str) else None


def released(
    root: Path,
    version: str,
    *,
    before: str | EllipsisType | None = ...,
    files: dict[str, tuple[bytes, str]] | None = None,
) -> str:
    """A release at `version` on `root`'s `HEAD`: both manifests at `version`, `files` written,
    its marketplace pinning the plugin commit its tree makes, tagged `v<version>` (annotated);
    the pin. The commit's parent is the `sha` its first parent pins: `HEAD`'s as it is, or, when
    `before` is given, `before`'s, committed first (`None`: a commit pinning no sha)."""
    if not isinstance(before, EllipsisType):
        write(root, {MARKETPLACE: pinned_marketplace(before)})
        commit(root, "the release before")
    parent = pinned_at(root)
    manifest = (f'{{"name": "drybag", "version": "{version}"}}\n'.encode(), "100644")
    write(root, {".claude-plugin/plugin.json": manifest, ".codex-plugin/plugin.json": manifest})
    write(root, {**(files or {}), MARKETPLACE: pinned_marketplace(None, version)})
    commit(root, f"release {version}")
    return _pin_and_tag(root, version, parent, NINE)
