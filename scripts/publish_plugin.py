#!/usr/bin/env python3
"""Push the plugin commit a release pinned to the plugin's own repository, and nothing else.

    uv run python scripts/publish_plugin.py --tag vX.Y.Z [--remote URL] [--yes]

The plugin is published from `dry-bag/drybag-plugin`, a repository whose root is the plugin's
tree at a commit of this one. Its commit is a function of the release commit: the tree, a fixed
author, committer and date, a message naming the version, and as its parent the commit the
marketplace pinned at the release commit's first parent. So the release commit pins it
(`.claude-plugin/marketplace.json`'s `sha`), and this, the owner's one command after the release's
tags, builds that commit again and pushes it as `main` and as the tag, atomically. Without `--yes`
it does everything but the push and says which commit it would push; the commit is the same from
run to run, so a dry run names the commit a later run pushes.

**The tag's own code builds the commit.** `scripts/plugin_tree.py` and `src/drybag` are read out
of the tag's objects — `ls-tree` and `cat-file`, regular files only, never `git archive`, which
applies the owner's attributes and line endings — written into the scratch directory, and run as
`python -I`, the tag's `src` first on `sys.path`: the checkout's copy of either may be another
release's. Before any of it runs, the local tag's commit is compared with the one GitHub's
`dry-bag/drybag` holds under that tag, so the code run is the release's own, and the
attestation binds the same commit afterwards.

**What it trusts, and why.** Every answer it trusts is GitHub's, asked of `github.com` by name, so
`gh auth status --hostname github.com --active` must pass before the first is asked, and before it
`gh --version` must be a release at least 2.101.0, the gh every flag below and its exact identity
match were measured on, so an older gh is told so rather than left to fail the verify. The
attestation says which manifest a release vouches for: `gh attestation verify` binds the manifest's
bytes to the certificate identity of this repository's `release.yml` run for this tag
(`--cert-identity`, matched exactly, where `--signer-workflow` matched a prefix), for this tag's
ref (`--source-ref`) at this commit (`--source-digest`), on a GitHub-hosted runner
(`--deny-self-hosted-runners`). A verify that fails is a fact of this machine as much as of the
release, and the publisher never asks for a rejection on it alone: it refuses, and GitHub's listing
of attestations of the manifest's digest only chooses the advice — none yet, run again once the
release's `build` and `attest` jobs are green; one that does not verify here, run again with a
working gh and network; the same answer then is the owner's to reject. The commit is read back whole
and its manifest compared with that one byte for byte before anything leaves the machine. The plugin
repository's state is GitHub's: on the default remote, `main` and the tag are read through `gh api`
as well as `ls-remote`, and a disagreement is a redirect (a `url.*.insteadOf`, a `GIT_CONFIG_*`
variable) refused rather than classified, and after a push the tag is read back through the API,
which must name the commit pushed: a tag it does not list is listed once more by `ls-remote`, and
one that listing does not name at the commit either is a push that went elsewhere, through a
`url.*.pushInsteadOf` or a `remote.<url>.pushurl`, which moves a push and not a listing, where one
it names is GitHub not listing it yet. Another `--remote` (a test, a rehearsal) is read from
`ls-remote` alone, and the summary, and a rejection resting on it, says so. CI holds no
credential to the plugin repository: the owner's own git pushes, with the owner's own key.

**Commit ids are compared, never manifests.** A remote whose tag already names the pinned commit is
"already published": exit `0`, nothing fetched or pushed, wherever its `main` has moved since. A
tag naming another commit is a fact of the release no re-run changes. Without the tag, `main` must
be the commit's parent — both absent for the first release — because `main` moves only by
fast-forward: a release cut on the wrong base, or a patch release of an older line, is refused.

**Two exit codes after `0`:** `1` rejects the release's approval, for a fact of the release no
re-run changes (`Rejected`), and `2` says fix something and run again, for anything else. Which
outcome is which is said once, to the owner who acts on it: `RELEASING.md`, section 2, step 7.

The command goes through the CLI frame's `run`, as `scripts/release.py`'s do: `--json` anywhere on
the line before a bare `--`, and `Rejected` is the frame's `Failure`, exit `1`. Run without this
repository's `drybag`, it refuses with exit `2` before the frame exists, since a traceback would
exit `1`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

# Before the CLI frame exists, so said here: an interpreter without this repository's `drybag`
# would otherwise end in a traceback and exit `1`, which asks the owner to reject the release.
try:
    from drybag import fsops
    from drybag.cli import JSON_EPILOG, run
    from drybag.errors import Failure, Refusal
    from drybag.gitenv import (
        GIT_TIMEOUT_SECONDS,
        NO_ANSWER,
        QUERY_TIMEOUT_SECONDS,
        answer_bytes,
        git_run,
    )
    from drybag.printed import clipped, quoted
    from drybag.release.api import tag_for
    from drybag.result import Result
    from drybag.runner import Completed, Runner, subprocess_runner
except ImportError as exc:
    sys.stderr.write(
        f"scripts/publish_plugin.py: refused: {exc}; run it with `uv run python "
        "scripts/publish_plugin.py`, which puts this repository's drybag on the path; nothing "
        "was run\n"
    )
    sys.exit(2)

# The plugin's own repository: as the owner's git reaches it to push, as the marketplace fetches
# it, and as GitHub's API names it.
PLUGIN_REMOTE = "git@github.com:dry-bag/drybag-plugin.git"
PLUGIN_URL = "https://github.com/dry-bag/drybag-plugin.git"
PLUGIN_REPOSITORY = "dry-bag/drybag-plugin"
# The repository whose tag is published, and the certificate identity of the run that attests its
# manifest: `release.yml` run for the tag, as the certificate's SubjectAlternativeName spells it
# (measured for `v0.2.0`), which `gh attestation verify --cert-identity` matches exactly.
SOURCE_REPOSITORY = "dry-bag/drybag"
CERT_IDENTITY = (
    f"https://github.com/{SOURCE_REPOSITORY}/.github/workflows/release.yml@refs/tags/{{tag}}"
)
# The host every `gh` call names, so a second host the owner is logged in to answers none.
GITHUB = "github.com"
# The gh every flag handed to `gh attestation verify`, and its exact `--cert-identity` match, were
# measured on; an older one is refused, and `gh --version`'s first line is read for it.
GH_FLOOR = (2, 101, 0)
GH_VERSION = re.compile(r"gh version ([0-9]+)\.([0-9]+)\.([0-9]+)(-[^ ]*)?(?: .*)?")
# The repository this script lives in: the one whose tag is published.
ROOT = Path(__file__).resolve().parents[1]
# A release's tag: `v` and three dot-separated runs of ASCII digits, and nothing after them.
TAG_PATTERN = r"v[0-9]+\.[0-9]+\.[0-9]+"
MAIN = "refs/heads/main"
# Where the fetched `main` is kept in the scratch repository, beside nothing else.
FETCHED = "refs/drybag/main"
# A commit id of either repository: 40 lowercase hex characters.
SHA1 = r"[0-9a-f]{40}"
# A full object name, SHA-1's or SHA-256's, as `ls-remote` prints one.
OBJECT_NAME = r"[0-9a-f]{40}|[0-9a-f]{64}"
# The first line of the manifest `plugin_tree.py` writes, and the `format` its `commit` answers.
FORMAT = "drybag-plugin-tree 1"
# What the tag carries beside the plugin and this script runs: its own reader of the plugin's tree
# and the package that reader imports.
TOOL = "scripts/plugin_tree.py"
TOOL_PACKAGE = "src/drybag"
# The only modes a file of the tag's code may have: a symlink or a submodule is refused, not
# skipped, since the code would run without it.
TOOL_MODES = frozenset({"100644", "100755"})
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | os.O_CLOEXEC
# How the tag's `plugin_tree.py` is run: `python -I -c BOOT <src> <script> <args>`. `-I` keeps the
# owner's `PYTHONPATH` and user site out; the tag's `src` goes first on `sys.path`, so it is read
# before the venv's path to this checkout's; and the script runs as `__main__` with its own
# arguments, as `python <script> <args>` would run it.
BOOT = (
    "import runpy, sys; src = sys.argv[1]; sys.argv[:] = sys.argv[2:]; "
    "sys.path.insert(0, src); runpy.run_path(sys.argv[0], run_name='__main__')"
)
# How many annotated tags GitHub's answer for a ref is peeled through before it is refused.
PEELS = 8
# The answers `gh api` gives for a ref a repository does not hold (404), and for any ref of an
# empty repository (409): "absent", where every other failure is a refusal.
ABSENT = frozenset({"404", "409"})
HTTP_STATUS = re.compile(r"\(HTTP ([0-9]{3})\)")
# How many of a program's stderr lines a refusal quotes.
QUOTED_LINES = 6
# On every git that runs in the scratch repository: none of the owner's hooks runs there, a
# `pre-push` above all.
NO_HOOKS = ("-c", "core.hooksPath=/dev/null")


class Rejected(Failure):
    """A fact of this release that no re-run changes: exit `1`, reject the `pypi` approval."""


@dataclass(frozen=True)
class Published:
    tag: str
    files: int
    tree: str  # the commit's root tree
    commit: str  # the plugin commit the tag pins
    outcome: Literal["would-push", "pushed", "already"]
    confirmed: bool  # the remote's state was read through GitHub's API


@dataclass(frozen=True)
class Built:
    """What the tag's `plugin_tree.py commit` answered, checked for its shape."""

    version: str
    files: int
    tree: str
    parent: str | None
    commit: str


@dataclass(frozen=True)
class RemoteState:
    main: str | None
    tag: str | None  # the commit the remote's tag names, peeled
    confirmed: bool


def _said(done: Completed, *, last: bool = False) -> str:
    """The first lines a program wrote to stderr (else stdout), or with `last` its last ones, as a
    traceback ends with what went wrong; each quoted, or its exit code.

    Each line through `clipped`: `gh` and `git` print what the remote says, and a line break
    followed by `::error::`, or an escape sequence, is not text this script prints raw."""
    lines = [line for line in done.stderr.split("\n") if line.strip()]
    lines = lines or [line for line in done.stdout.split("\n") if line.strip()]
    if not lines:
        return f"exit {done.code}, and nothing said"
    shown = lines[-QUOTED_LINES:] if last else lines[:QUOTED_LINES]
    return " / ".join(clipped(line.strip()) for line in shown)


def _shown(value: object) -> str:
    return clipped(value) if isinstance(value, str) else f"a {type(value).__name__}"


def _git(
    root: Path, *args: str, stdin: str | None = None, timeout: float = GIT_TIMEOUT_SECONDS
) -> tuple[int, str]:
    """`git <args>` asked locally in `root`: its exit code and answer, or a refusal in
    `NO_ANSWER`'s words when git gave none, which `git_run` answers as `-1` and a caller printing
    the code would say as "exited -1". Every local git here goes through this, and every one that
    reaches the remote through `_network`: `tests/scripts/test_publish_plugin.py` holds that no
    other function calls `git_run`."""
    code, answer = git_run(root, *args, stdin=stdin, timeout=timeout)
    if code == -1:
        raise Refusal(f"git {_subcommand(args)} in {root} gave no answer: {NO_ANSWER}")
    return code, answer


def _subcommand(args: tuple[str, ...]) -> str:
    """The git command among `args`: the first word that is neither an option nor a `-c`'s
    value."""
    words = iter(args)
    for word in words:
        if word == "-c":
            next(words, None)
        elif not word.startswith("-"):
            return word
    return "with no command"


# --- The tag ----------------------------------------------------------------------------------


def _tag_commit(root: Path, tag: str) -> str:
    """The commit `refs/tags/<tag>` names in `root`, peeled."""
    if not re.fullmatch(TAG_PATTERN, tag):
        raise Refusal(f"{quoted(tag)} is not a plain version tag, vX.Y.Z")
    # `--no-replace-objects`, as every read of the tag here: when the tag is annotated, its peel
    # reads the tag object, and a replacement of that object would make the answer another
    # commit; a lightweight tag names its commit directly, which a replacement does not move.
    code, answer = _git(
        root,
        "--no-replace-objects",
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"refs/tags/{tag}^{{commit}}",
    )
    sha = answer.removesuffix("\n")
    if code != 0 or not re.fullmatch(SHA1, sha):
        raise Refusal(f"no tag {tag} names a commit in {root} (git rev-parse exited {code})")
    return sha


# --- GitHub's API -------------------------------------------------------------------------------


def _api(runner: Runner, root: Path, path: str) -> dict[str, object] | None:
    """`gh api --hostname github.com <path>`'s JSON object, or `None` when GitHub answers that it
    holds no such object (404, or 409 for an empty repository); any other answer is a refusal."""
    done = runner.launch(["gh", "api", "--hostname", GITHUB, path], root)
    if done.code != 0:
        status = HTTP_STATUS.search(done.stderr)
        if status is not None and status.group(1) in ABSENT:
            return None
        raise Refusal(f"gh api {path} exited {done.code}: {_said(done)}")
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        raise Refusal(f"gh api {path} answered no JSON object: {_said(done)}")
    return answer


def _github_ref(runner: Runner, root: Path, repository: str, ref: str) -> str | None:
    """The commit `ref` names in GitHub's `repository`, peeled through annotated tags, or `None`
    when GitHub holds no such ref."""
    answer = _api(runner, root, f"repos/{repository}/git/ref/{ref.removeprefix('refs/')}")
    for _ in range(PEELS):
        if answer is None:
            return None
        target = answer.get("object")
        sha = target.get("sha") if isinstance(target, dict) else None
        kind = target.get("type") if isinstance(target, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(SHA1, sha):
            raise Refusal(f"GitHub answered {_shown(sha)} for {ref} in {repository}")
        if kind == "commit":
            return sha
        if kind != "tag":
            raise Refusal(f"GitHub's {repository} names a {_shown(kind)} under {ref}, at {sha}")
        answer = _api(runner, root, f"repos/{repository}/git/tags/{sha}")
        if answer is None:
            raise Refusal(
                f"GitHub's {repository} names the tag object {sha} under {ref}, and "
                "then holds no such tag"
            )
    raise Refusal(f"GitHub's {repository} names {ref} through more than {PEELS} tags")


def _gh_recent(runner: Runner, root: Path) -> None:
    """Refuse a gh older than `GH_FLOOR`, a pre-release, or one whose version cannot be read: each
    may lack a flag `_verify` hands it, and its failed verify would not say so plainly."""
    done = runner.launch(["gh", "--version"], root)
    found = GH_VERSION.fullmatch(done.stdout.split("\n", 1)[0]) if done.code == 0 else None
    if found is None:
        raise Refusal(
            f"could not read gh's version: gh --version exited {done.code}: {_said(done)}; run "
            "again; nothing was run"
        )
    floor = ".".join(str(part) for part in GH_FLOOR)
    numbers, pre = found.groups()[:3], found.group(4)
    if pre is not None:
        raise Refusal(
            f"gh {'.'.join(numbers)}{pre} is a pre-release; install a released gh at {floor} or "
            "later and run again; nothing was run"
        )
    if tuple(int(part) for part in numbers) < GH_FLOOR:
        raise Refusal(
            f"gh {'.'.join(numbers)} is older than {floor}, the version this publisher's "
            "attestation flags were measured on; upgrade gh and run again; nothing was run"
        )


def _logged_in(runner: Runner, root: Path) -> None:
    """Refuse a `gh` that is not logged in to github.com: every answer after this is GitHub's."""
    argv = ["gh", "auth", "status", "--hostname", GITHUB, "--active"]
    done = runner.launch(argv, root)
    if done.code != 0:
        raise Refusal(
            f"{' '.join(argv)} exited {done.code}: {_said(done)}. Every answer this trusts is "
            f"GitHub's: log in (gh auth login --hostname {GITHUB}) if gh says you are not, or fix "
            "what it names, a network or a token it cannot use, and run again; nothing was run"
        )


def _source_anchor(runner: Runner, root: Path, tag: str, sha: str) -> None:
    """Refuse a local tag that is not GitHub's: its code is about to run."""
    found = _github_ref(runner, root, SOURCE_REPOSITORY, f"refs/tags/{tag}")
    if found != sha:
        # A tag GitHub lacks was not pushed. One it holds at another commit may not be the owner's:
        # whoever can create a tag there can make the owner's push fail, and a fetch over the
        # local tag would run that tag's code here next. So it is investigated first, and fetched
        # over the local one only when the local one is the stale one, by `--force`, since a plain
        # `git fetch --tags` refuses to clobber an existing tag.
        advice = (
            "Push the tags (RELEASING.md section 2, step 6) and run again"
            if found is None
            else f"If you did not push GitHub's {tag}, investigate it before you fetch or run "
            "anything; if yours is the stale one, fetch GitHub's over it "
            "(git fetch --tags --force) and run again"
        )
        held = f"names {found}" if found is not None else "holds no such tag"
        raise Refusal(
            f"your local {tag} names {sha}, and GitHub's {SOURCE_REPOSITORY} {held}: your local "
            f"{tag} is not GitHub's. {advice}; nothing was run"
        )


# --- The tag's own code -------------------------------------------------------------------------


def _blobs(root: Path, objects: list[str]) -> dict[str, bytes]:
    """Each object's bytes, from one `git cat-file --batch`."""
    given = "".join(obj + "\n" for obj in objects)
    code, answer = _git(
        root,
        "--no-replace-objects",
        "cat-file",
        "--batch",
        stdin=given,
        timeout=QUERY_TIMEOUT_SECONDS,
    )
    if code != 0:
        raise Refusal(f"git cat-file --batch exited {code} in {root}")
    out, at, blobs = answer_bytes(answer), 0, {}
    for obj in objects:
        # `<object> <type> <size>\n<content>\n`, once per object asked, in the order asked.
        header_end = out.find(b"\n", at)
        header = out[at:header_end].split() if header_end != -1 else []
        if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
            raise Refusal(f"git cat-file did not answer {obj} as a blob in {root}")
        content = out[header_end + 1 : header_end + 1 + int(header[2])]
        if len(content) != int(header[2]):
            raise Refusal(f"git cat-file's answer in {root} ended inside {obj}")
        blobs[obj] = content
        at = header_end + 1 + len(content) + 1
    return blobs


def _tool(root: Path, tag: str, sha: str, scratch: Path) -> Path:
    """The tag's `scripts/plugin_tree.py` and `src/drybag`, read out of its objects and
    written under `scratch / "tool"`: the directory to run them from."""
    code, answer = _git(
        root,
        "--no-replace-objects",
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        sha,
        "--",
        TOOL,
        TOOL_PACKAGE,
        timeout=QUERY_TIMEOUT_SECONDS,
    )
    if code != 0:
        raise Refusal(f"git ls-tree of {sha} exited {code} in {root}")
    rows = []
    for record in answer.split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        mode, _kind, obj = meta.split()
        if mode not in TOOL_MODES:
            raise Refusal(
                f"{quoted(path)} at {tag} ({sha}) has mode {mode}, not a regular file's; the "
                "tag's code is run from regular files only"
            )
        rows.append((path, obj))
    paths = [path for path, _ in rows]
    if TOOL not in paths or not any(path.startswith(f"{TOOL_PACKAGE}/") for path in paths):
        raise Refusal(
            f"{tag} ({sha}) holds no {TOOL} or no {TOOL_PACKAGE}: {tag} predates the plugin "
            "repository, and is not published to it"
        )
    blobs = _blobs(root, [obj for _, obj in rows])
    tool = scratch / "tool"
    try:
        tool.mkdir()
    except OSError as exc:
        raise Refusal(f"{tool} cannot be made: {fsops.said(exc)}") from None
    for path, obj in rows:
        try:
            fsops.mkdirs_within(tool, path)
            with fsops.open_within(tool, path) as (dir_fd, name):
                descriptor = os.open(name, _CREATE, 0o644, dir_fd=dir_fd)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(blobs[obj])
        except OSError as exc:
            raise Refusal(
                f"{quoted(path)} cannot be written into {tool}: {fsops.said(exc)}"
            ) from None
    return tool


def _run_tool(runner: Runner, tool: Path, root: Path, *args: str) -> tuple[int, dict[str, object]]:
    """The tag's `plugin_tree.py <args> --json`: its exit code and the JSON object it printed,
    which the CLI frame prints whatever the outcome; a run that printed none is a refusal."""
    script = tool / "scripts" / "plugin_tree.py"
    argv = [sys.executable, "-I", "-c", BOOT, str(tool / "src"), str(script), *args, "--json"]
    done = runner.launch(argv, root)
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        raise Refusal(
            f"the tag's {TOOL} {args[0]} exited {done.code} and printed no JSON object: "
            f"{_said(done, last=True)}"
        )
    return done.code, answer


def _built(answer: dict[str, object]) -> Built:
    """`answer` as a `Built`, or a refusal naming the first field that is not what `commit`
    answers."""
    said = f"the tag's {TOOL} commit answered"
    if answer.get("format") != FORMAT:
        raise Refusal(f"{said} in format {_shown(answer.get('format'))}, not {FORMAT!r}")
    for name in ("commit", "tree"):
        value = answer.get(name)
        if not isinstance(value, str) or not re.fullmatch(SHA1, value):
            raise Refusal(f"{said} {_shown(value)} for {name}, which is no commit id")
    # `pinned` is not read: `--require-pin` has compared it with `commit` in the tag's code.
    parent, files, version = answer.get("parent"), answer.get("files"), answer.get("version")
    if parent is not None and (not isinstance(parent, str) or not re.fullmatch(SHA1, parent)):
        raise Refusal(f"{said} {_shown(parent)} for parent, which is neither null nor an id")
    if not isinstance(files, int) or isinstance(files, bool):
        raise Refusal(f"{said} a {type(files).__name__} for files, which is no count")
    if not isinstance(version, str):
        raise Refusal(f"{said} {_shown(version)} for version, which is no version")
    return Built(
        version=version,
        files=files,
        tree=str(answer["tree"]),
        parent=parent if isinstance(parent, str) else None,
        commit=str(answer["commit"]),
    )


def _build(runner: Runner, tool: Path, root: Path, tag: str, sha: str, scratch: Path) -> Built:
    """The plugin commit of `sha`, written by the tag's own code into `scratch / "plugin.git"`,
    its manifest into `scratch / "plugin-tree.txt"`; rejected when the tag's pin is not it or its
    version is not the tag's."""
    code, answer = _run_tool(
        runner,
        tool,
        root,
        "commit",
        "--root",
        str(root),
        "--rev",
        sha,
        "--git-dir",
        str(scratch / "plugin.git"),
        "--manifest-file",
        str(scratch / "plugin-tree.txt"),
        "--require-pin",
    )
    summary = quoted(str(answer.get("summary")))
    # Exit 1 with an object printed is the frame's `Failure`, which only `--require-pin` raises. A
    # traceback before the frame runs exits 1 too, and `_run_tool` has refused it already: it
    # printed no object.
    if code == 1:
        raise Rejected(
            f"{tag}'s marketplace does not pin the plugin commit its own tree makes, so no "
            f"publish of {tag} matches its pin: {summary}. Reject the release's approval"
        )
    if code != 0:
        raise Refusal(f"the tag's {TOOL} commit exited {code}: {summary}")
    built = _built(answer)
    if tag_for(built.version)[0] != tag:
        raise Rejected(
            f"{tag} names {sha}, whose .claude-plugin/plugin.json says {quoted(built.version)}. "
            "Reject the release's approval"
        )
    return built


def _first_difference(want: bytes, found: bytes) -> str:
    """Where `found` parts from `want`, as the first differing line of the two manifests."""
    expected = want.decode("utf-8", "replace").split("\n")
    seen = found.decode("utf-8", "replace").split("\n")
    for number in range(max(len(expected), len(seen))):
        line = expected[number] if number < len(expected) else "<no line>"
        other = seen[number] if number < len(seen) else "<no line>"
        if line != other:
            return f"line {number + 1} is {clipped(other)} where the attested has {clipped(line)}"
    raise AssertionError("_first_difference was handed two equal manifests; its caller compares")


def _read_back(
    runner: Runner, tool: Path, root: Path, tag: str, commit: str, scratch: Path
) -> None:
    """Reject a commit whose tree, read back whole, is not the attested manifest's."""
    git_dir, readback = scratch / "plugin.git", scratch / "readback.txt"
    exact = ("manifest", "--exact", "--root", str(git_dir), "--rev", commit)
    code, answer = _run_tool(runner, tool, root, *exact, "--manifest-file", str(readback))
    if code != 0:
        said = quoted(str(answer.get("summary")))
        raise Refusal(f"the tag's {TOOL} could not read {commit} back: exit {code}, {said}")
    try:
        expected, found = (scratch / "plugin-tree.txt").read_bytes(), readback.read_bytes()
    except OSError as exc:
        raise Refusal(f"the manifests in {scratch} cannot be read: {fsops.said(exc)}") from None
    if found != expected:
        raise Rejected(
            f"the commit built for {tag} reads back as another tree: "
            f"{_first_difference(expected, found)}; nothing was pushed. Reject the release's "
            "approval"
        )


def _verify(runner: Runner, root: Path, attested: Path, tag: str, sha: str) -> None:
    """Ask `gh` whether this repository's release workflow, run for this tag, attested exactly this
    manifest, for this tag at this commit, on a GitHub-hosted runner. A verify that fails is a fact
    of this machine as much as of the release, so it is never a rejection on its own: it is
    refused, with the advice GitHub's listing of attestations of the manifest chooses."""
    argv = [
        "gh",
        "attestation",
        "verify",
        str(attested),
        "--hostname",
        GITHUB,
        "--repo",
        SOURCE_REPOSITORY,
        "--cert-identity",
        CERT_IDENTITY.format(tag=tag),
        "--source-ref",
        f"refs/tags/{tag}",
        "--source-digest",
        sha,
        "--deny-self-hosted-runners",
    ]
    verified = runner.launch(argv, root)
    if verified.code != 0:
        # gh exits non-zero both for "no attestation vouches for this" and for "I could not
        # verify here"; GitHub's listing of the manifest's digest says which advice fits.
        said = f"gh attestation verify exited {verified.code}: {_said(verified)}"
        try:
            digest = hashlib.sha256(attested.read_bytes()).hexdigest()
        except OSError as exc:
            raise Refusal(f"{said}; and {attested} cannot be read: {fsops.said(exc)}") from None
        if _attested(runner, root, digest, said):
            raise Refusal(
                f"{said}; GitHub holds an attestation of this manifest (sha256:{digest}) that "
                f"does not verify on this machine against {SOURCE_REPOSITORY}'s release.yml at "
                f"{tag} ({sha}). Nothing was fetched or pushed; run again, and if it says the "
                "same with a working gh and network once the release's build and attest jobs are "
                "green, reject the release's approval"
            )
        raise Refusal(
            f"{said}; GitHub holds no attestation of this manifest yet (sha256:{digest}). Nothing "
            "was fetched or pushed; once the release's build and attest jobs are green, run "
            "again; if it says the same then, reject the release's approval"
        )


def _attested(runner: Runner, root: Path, digest: str, said: str) -> bool:
    """Whether GitHub holds an attestation of the manifest whose sha256 is `digest`: `200` listing
    one is yes, and an answer of no such object (`_api`'s `404` and `409`; a `409` from this API is
    not measured, and is read as `_api` reads it for a ref, as absent) is no; any other answer is
    a refusal, since nothing tells a wrong attestation from a GitHub that could not be asked."""
    path = f"repos/{SOURCE_REPOSITORY}/attestations/sha256:{digest}"
    try:
        answer = _api(runner, root, path)
    except Refusal as exc:
        raise Refusal(
            f"{said}; and whether GitHub holds an attestation of it: {exc}; run again"
        ) from None
    if answer is None:
        return False
    listed = answer.get("attestations")
    if not isinstance(listed, list) or not listed:
        raise Refusal(
            f"{said}; and gh api {path} answered, but lists no attestation: "
            f"{_shown(listed) if listed is not None else 'no attestations'}; run again"
        )
    return True


# --- The plugin repository ------------------------------------------------------------------------


def _network(runner: Runner, git_dir: Path, *args: str) -> Completed:
    """`git <args>` in the scratch repository through the `Runner`, which keeps the environment
    the remote needs. Named by `--git-dir`, not found from `-C`: an owner's
    `safe.bareRepository=explicit` refuses a bare repository git finds rather than is given."""
    argv = ["git", "-C", str(git_dir), f"--git-dir={git_dir}", *NO_HOOKS, *args]
    return runner.launch(argv, git_dir)


def _listed(runner: Runner, git_dir: Path, remote: str, *wanted: str) -> dict[str, str]:
    """The `wanted` refs on the remote, by their exact names: `ls-remote` matches a pattern
    against a ref's tail, so a `refs/heads/x/refs/heads/main` would answer `main` too."""
    listed = _network(runner, git_dir, "ls-remote", "--end-of-options", remote, *wanted)
    if listed.code != 0:
        raise Refusal(f"git ls-remote {remote} exited {listed.code}: {_said(listed)}")
    found = {}
    for line in listed.stdout.split("\n"):
        sha, _, ref = line.partition("\t")
        if ref not in wanted:
            continue
        # An object name and nothing else: it is handed on to `fetch` and compared, and the
        # remote chose it.
        if not re.fullmatch(OBJECT_NAME, sha):
            raise Refusal(f"git ls-remote {remote} answered {clipped(sha)} for {ref}")
        found[ref] = sha
    return found


def _tag_refs(tag: str) -> tuple[str, str]:
    """The tag's two names in a listing: the tag, and its peel, which an annotated tag lists."""
    return f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"


def _tagged(listed: dict[str, str], tag: str) -> str | None:
    """The commit a listing says the tag names: an annotated tag lists its object, then its peel;
    the lightweight tag this pushes, one line."""
    ref, peel = _tag_refs(tag)
    peeled = listed.get(peel)
    return peeled if peeled is not None else listed.get(ref)


def _remote_state(runner: Runner, root: Path, git_dir: Path, remote: str, tag: str) -> RemoteState:
    """The remote's `main` and the commit its tag names: from `ls-remote`, and on the default
    remote from GitHub's API as well, which must agree."""
    listed = _listed(runner, git_dir, remote, MAIN, *_tag_refs(tag))
    tagged, main = _tagged(listed, tag), listed.get(MAIN)
    if remote not in (PLUGIN_REMOTE, PLUGIN_URL):
        return RemoteState(main, tagged, confirmed=False)
    github_main = _github_ref(runner, root, PLUGIN_REPOSITORY, MAIN)
    github_tag = _github_ref(runner, root, PLUGIN_REPOSITORY, f"refs/tags/{tag}")
    if (github_main, github_tag) != (main, tagged):
        raise Refusal(
            f"git ls-remote {remote} answers main {main or 'absent'} and {tag} "
            f"{tagged or 'absent'}, where GitHub's {PLUGIN_REPOSITORY} has main "
            f"{github_main or 'absent'} and {tag} {github_tag or 'absent'}: your git reaches "
            "another repository, through a redirect (a url.*.insteadOf in your git "
            "configuration, or a GIT_CONFIG_* variable), or main moved while this ran. Remove "
            "the redirect, and any url.*.pushInsteadOf or remote.<url>.pushurl that sends the "
            "push elsewhere the same way, or run again"
        )
    return RemoteState(main, tagged, confirmed=True)


def _unconfirmed(state: RemoteState) -> str:
    """What a finding about the remote adds when only `ls-remote` read it, as the summary does."""
    return "" if state.confirmed else " (not confirmed through GitHub's API)"


def _follows(runner: Runner, git_dir: Path, remote: str, built: Built, state: RemoteState) -> None:
    """Reject a commit `main` does not fast-forward to; then fetch `main`, the commit's parent,
    and refuse a `main` that moved since it was listed."""
    main = state.main
    if main != built.parent:
        follows = f"parent {built.parent}" if built.parent is not None else "no parent"
        holds = f"main at {main}" if main is not None else "no main"
        raise Rejected(
            f"the plugin commit {built.commit} has {follows}, and {remote} has {holds}"
            f"{_unconfirmed(state)}; the plugin repository's main moves only by fast-forward. "
            "Reject the release's approval"
        )
    if main is None:
        return
    refspec = f"+{MAIN}:{FETCHED}"
    fetched = _network(
        runner, git_dir, "fetch", "--quiet", "--no-tags", "--end-of-options", remote, refspec
    )
    if fetched.code != 0:
        raise Refusal(f"git fetch {remote} {MAIN} exited {fetched.code}: {_said(fetched)}")
    code, answer = _git(
        git_dir,
        f"--git-dir={git_dir}",
        *NO_HOOKS,
        "rev-parse",
        "--verify",
        "--end-of-options",
        FETCHED,
    )
    if code != 0:
        raise Refusal(
            f"git rev-parse of {FETCHED} in {git_dir} exited {code} after the fetch of {remote}'s "
            "main; nothing was pushed; run again"
        )
    if answer.removesuffix("\n") != main:
        raise Refusal(
            f"{remote}'s main was {main} when it was listed, and the fetch that followed brought "
            "another: main moved while this ran. Nothing was pushed; run again"
        )


def _landed(runner: Runner, root: Path, git_dir: Path, remote: str, tag: str, built: Built) -> None:
    """Refuse a push GitHub's API does not show: its plugin repository's tag, read back, must name
    the commit pushed. A tag the API does not list is told apart by one `ls-remote` of the tag:
    one the listing names at the commit is GitHub not listing it yet, and one it does not is a
    push that went elsewhere, since `url.*.pushInsteadOf` and `remote.<url>.pushurl` move a push
    and not a listing, and `ls-remote` and the API agreed before the push."""
    commit = built.commit
    found = _github_ref(runner, root, PLUGIN_REPOSITORY, f"refs/tags/{tag}")
    pushed = f"git pushed {commit} to {remote} as main and {tag}"
    if found is None:
        if _tagged(_listed(runner, git_dir, remote, *_tag_refs(tag)), tag) != commit:
            raise Refusal(
                f"{pushed}, and neither GitHub's {PLUGIN_REPOSITORY} nor git ls-remote {remote} "
                f"lists {tag} at it: the push went elsewhere, through a url.*.pushInsteadOf or a "
                "remote.<url>.pushurl in your git configuration, or a GIT_CONFIG_* variable, "
                "which moves a push and not a listing. Remove it and run again"
            )
        raise Refusal(
            f"{pushed}, and git ls-remote {remote} lists {tag} at it, but GitHub's "
            f"{PLUGIN_REPOSITORY} does not list {tag} yet; run again, which says already "
            "published once GitHub lists it"
        )
    if found != commit:
        raise Refusal(
            f"{pushed}, and GitHub's {PLUGIN_REPOSITORY} names {found} under {tag}: someone "
            f"else published {tag} at the same moment, or the push went elsewhere, through a "
            "url.*.insteadOf, a url.*.pushInsteadOf or a remote.<url>.pushurl in your git "
            "configuration or a GIT_CONFIG_* variable; find which, fix it and run again"
        )


def publish(
    root: Path, tag: str, *, remote: str, yes: bool, runner: Runner, scratch: Path
) -> Published:
    """Publish the plugin commit `tag` pins in `root` to `remote`'s `main` and `tag`, under `yes`.

    Each step refuses or rejects before the next runs, and everything before the push is local to
    `scratch`: the tag resolved to one commit, `gh` held to be recent and logged in, the tag held to
    GitHub's; the tag's own code read out of it; the commit built with that code and held to the
    pin and the version; the attestation verified; the commit read back; the remote's state read
    (already published, or rejected, when the tag is there); `main` held to the commit's parent
    and fetched; and only then, with `yes`, the atomic push, and on the default remote the pushed
    tag read back through GitHub's API.
    """
    sha = _tag_commit(root, tag)
    _gh_recent(runner, root)
    _logged_in(runner, root)
    _source_anchor(runner, root, tag, sha)
    tool = _tool(root, tag, sha, scratch)
    built = _build(runner, tool, root, tag, sha, scratch)
    _verify(runner, root, scratch / "plugin-tree.txt", tag, sha)
    _read_back(runner, tool, root, tag, built.commit, scratch)
    git_dir = scratch / "plugin.git"
    state = _remote_state(runner, root, git_dir, remote, tag)
    outcome: Literal["would-push", "pushed", "already"]
    if state.tag is not None:
        if state.tag != built.commit:
            raise Rejected(
                f"{remote} holds {tag} at {state.tag}{_unconfirmed(state)}, and the plugin "
                f"commit {tag} pins is {built.commit}: a tag is not moved. Reject the release's "
                "approval"
            )
        outcome = "already"
    else:
        _follows(runner, git_dir, remote, built, state)
        outcome = "would-push"
        if yes:
            pushed = _network(
                runner,
                git_dir,
                "push",
                "--atomic",
                "--quiet",
                "--end-of-options",
                remote,
                f"{built.commit}:{MAIN}",
                f"{built.commit}:refs/tags/{tag}",
            )
            if pushed.code != 0:
                raise Refusal(
                    f"git push to {remote} exited {pushed.code}, and the push is atomic, so "
                    f"neither main nor {tag} moved: {_said(pushed)}"
                )
            if state.confirmed:
                _landed(runner, root, git_dir, remote, tag, built)
            outcome = "pushed"
    return Published(tag, built.files, built.tree, built.commit, outcome, state.confirmed)


# --- The command --------------------------------------------------------------------------------


def remote_argument(remote: str) -> str:
    """`remote` as git should be given it from the scratch repository, which is where every git
    that reaches it runs (`git -C`): a relative path to a local repository made absolute against
    the directory the command was run in, and anything else — a URL, an scp-like `host:path` —
    as it was given. git reads a colon before the first slash as scp-like, so this does too."""
    if "://" in remote or ":" in remote.split("/", 1)[0]:
        return remote
    path = Path(remote)
    return str(path.resolve()) if path.exists() and not path.is_absolute() else remote


def run_publish(args: argparse.Namespace) -> Result:
    remote = remote_argument(args.remote)
    with tempfile.TemporaryDirectory(prefix="drybag-publish-") as scratch:
        done = publish(
            ROOT,
            args.tag,
            remote=remote,
            yes=args.yes,
            runner=subprocess_runner(),
            scratch=Path(scratch),
        )
    data = {**asdict(done), "remote": remote}
    where = (
        f"{done.files} files as tree {done.tree}, commit {done.commit}, to {remote}: main and "
        f"{done.tag}"
    )
    if not done.confirmed:
        where += " (not confirmed through GitHub's API)"
    if done.outcome == "already":
        return Result(f"already published: {where}; nothing was pushed", data)
    if done.outcome == "pushed":
        return Result(f"pushed {where}", data)
    return Result(f"would push {where}; run again with --yes to push", data)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="scripts/publish_plugin.py",
        description="Push the plugin commit a release pinned to the plugin's own repository.",
        epilog=JSON_EPILOG,
    )
    top.add_argument("--tag", required=True, help="the release's tag, vX.Y.Z")
    top.add_argument(
        "--remote", default=PLUGIN_REMOTE, help=f"the plugin repository (default {PLUGIN_REMOTE})"
    )
    top.add_argument(
        "--yes", action="store_true", help="push; without it, build and compare, and say what"
    )
    top.set_defaults(func=run_publish)
    return top


def main(argv: list[str] | None = None) -> int:
    return run(sys.argv[1:] if argv is None else argv, parser=parser())


if __name__ == "__main__":
    sys.exit(main())
