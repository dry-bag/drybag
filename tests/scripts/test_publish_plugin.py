"""`scripts/publish_plugin.py`: the plugin commit a release pins, built with the tag's own code and
pushed to the plugin's own repository, and nothing else.

Every case starts from `tests/plugintree.py`'s `tool_source`: one commit holding a file under each
of the plugin's nine paths, this branch's `scripts/plugin_tree.py` and `src/stayfixed`, and a
marketplace pinning the plugin commit its tree makes, tagged `v1.2.3` (annotated). The default one
is built once per session and cloned per case; a case that changes the tag's own code patches its
clone, or builds its own when the pin has to change with it. A bare repository in `tmp_path` stands
for the plugin repository.

`gh` is never run. The runner is a composite that records every argv it is handed, answers `gh`
from `GitHub` — `gh api` read from the local repositories standing for GitHub's, its attestations
from one scripted answer, everything else (`gh auth status` and `gh attestation verify` exit `0`
unless a case says otherwise) from a script — and runs the rest for real: `git`'s network half and
the tag's `plugin_tree.py`.
Every commit id a case expects is computed by git from a literal text (`tests/plugintree.py`), never
by the script. Which exit each outcome is — `1` to reject the release's approval, `2` to fix
something and run again — is held in one place, the table at the end, through the command's `main`.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from stayfixed import gitenv
from stayfixed.errors import Refusal
from stayfixed.runner import Completed, subprocess_runner
from tests.gitfixture import git, git_bytes, needs_git, run_git
from tests.plugintree import (
    MARKETPLACE,
    NINE,
    PLUGIN_FILES,
    REPOSITORY,
    commit,
    hashed,
    literal,
    pinned_at,
    pinned_marketplace,
    plugin_source,
    plugin_tree_id,
    released,
    tool_source,
    write,
)
from tests.runners import Recorder
from tests.scriptload import plugin_tree as _tree_script
from tests.scriptload import publish_plugin as _script
from tests.scriptload import release as _release_script
from tests.scriptload import without_stayfixed

publish_plugin = _script()
plugin_tree = _tree_script()
release_script = _release_script()
Rejected = publish_plugin.Rejected

pytestmark = needs_git

TAG = "v1.2.3"
SOURCE_REPOSITORY = "stayfixed/stayfixed"
PLUGIN_REPOSITORY = "stayfixed/stayfixed-plugin"
# GitHub's answers to a ref it does not hold and to any ref of an empty repository, as `gh api`
# gives them (measured for a 404: exit 1, the body on stdout, the status on stderr).
NOT_FOUND = Completed(
    1,
    '{"message":"Not Found","documentation_url":"https://docs.github.com/rest","status":"404"}',
    "gh: Not Found (HTTP 404)\n",
)
EMPTY = Completed(
    1,
    '{"message":"Git Repository is empty.","documentation_url":"https://docs.github.com/rest",'
    '"status":"409"}',
    "gh: Git Repository is empty. (HTTP 409)\n",
)


@dataclass(kw_only=True)
class GitHub(Recorder):
    """`gh`: `gh api … git/ref/<ref>` and `… git/tags/<id>` answered from the repository that
    `repositories` names for the API's, as GitHub answers them; `… attestations/sha256:<digest>`
    of `stayfixed/stayfixed` answered `attestation`, whatever the digest, which a case asserts
    from the argv; and any other call, or one `answers` scripts, as the `Recorder` answers it.
    Read with `--no-replace-objects`: GitHub holds no replace refs. A private double rather than a
    `Recorder` alone because what it answers is a repository's state, which a case changes as it
    runs."""

    repositories: dict[str, Path] = field(default_factory=dict)
    attestation: Completed = NOT_FOUND

    def launch(self, argv: list[str], cwd: Path) -> Completed:
        answer = super().launch(argv, cwd)
        scripted = any(argv[: len(key.split(" "))] == key.split(" ") for key in self.answers)
        if scripted or argv[:2] != ["gh", "api"]:
            return answer
        return self._api(argv)

    def _api(self, argv: list[str]) -> Completed:
        assert argv[2:4] == ["--hostname", "github.com"], argv
        attested = re.fullmatch(r"repos/([^/]+/[^/]+)/attestations/sha256:[0-9a-f]{64}", argv[4])
        if attested is not None and len(argv) == 5:
            return self.attestation if attested.group(1) == SOURCE_REPOSITORY else NOT_FOUND
        found = re.fullmatch(r"repos/([^/]+/[^/]+)/git/(ref|tags)/(.+)", argv[4])
        assert found is not None and len(argv) == 5, argv
        name, kind, rest = found.groups()
        repository = self.repositories.get(name)
        if repository is None:
            return NOT_FOUND
        if kind == "tags":
            done = run_git(repository, "--no-replace-objects", "cat-file", "tag", rest)
            if done.returncode != 0:
                return NOT_FOUND
            header = dict(line.split(" ", 1) for line in done.stdout.split("\n\n")[0].split("\n"))
            target = {"sha": header["object"], "type": header["type"]}
            return Completed(0, json.dumps({"sha": rest, "object": target}), "")
        listing = "%(refname) %(objectname) %(objecttype)"
        rows = git(repository, "--no-replace-objects", "for-each-ref", f"--format={listing}")
        if not rows:
            return EMPTY
        for row in rows.splitlines():
            ref, obj, obj_type = row.split(" ")
            if ref == f"refs/{rest}":
                body = {"ref": ref, "object": {"sha": obj, "type": obj_type}}
                return Completed(0, json.dumps(body), "")
        return NOT_FOUND


@dataclass
class Composite:
    """The runner `publish` is handed: every argv recorded in `calls` before it is dispatched,
    `gh` answered by `gh`, every other program run for real, and `before` and `after` run on
    either side of each launch."""

    gh: Recorder = field(default_factory=GitHub)
    calls: list[list[str]] = field(default_factory=list)
    before: Callable[[list[str]], None] = lambda argv: None
    after: Callable[[list[str]], None] = lambda argv: None

    def launch(self, argv: list[str], cwd: Path) -> Completed:
        self.calls.append(argv)
        self.before(argv)
        if argv[:1] == ["gh"]:
            done = self.gh.launch(argv, cwd)
        else:
            done = subprocess_runner().launch(argv, cwd)
        self.after(argv)
        return done


# `gh --version` as gh 2.101.0 answers it, the version the publisher's flags were measured on: what
# every case's `gh` answers unless it scripts another.
GH_2_101 = Completed(
    0, "gh version 2.101.0 (2026-09-30)\nhttps://github.com/cli/cli/releases/tag/v2.101.0\n", ""
)


def runner_for(
    source: Path,
    plugin: Path | None = None,
    *,
    answers: dict[str, Completed] | None = None,
    attestation: Completed = NOT_FOUND,
    before: Callable[[list[str]], None] = lambda argv: None,
    after: Callable[[list[str]], None] = lambda argv: None,
) -> Composite:
    """A composite whose GitHub holds `source` as `stayfixed/stayfixed` and, when given, `plugin`
    as the plugin repository, and answers `attestation` for any attestation it is asked about and
    its `gh`
    is 2.101.0 unless `answers` scripts `gh --version`."""
    repositories = {SOURCE_REPOSITORY: source}
    if plugin is not None:
        repositories[PLUGIN_REPOSITORY] = plugin
    gh = GitHub(
        repositories=repositories,
        answers={"gh --version": GH_2_101, **(answers or {})},
        attestation=attestation,
    )
    return Composite(gh=gh, before=before, after=after)


@pytest.fixture(scope="session")
def _template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tool_source(tmp_path_factory.mktemp("tool-source"))


@pytest.fixture
def source(_template: Path, tmp_path: Path) -> Path:
    """The default tool source, cloned for this case."""
    root = tmp_path / "source"
    git(tmp_path, "clone", "-q", str(_template), str(root))
    return root


def _home() -> Path:
    return Path(os.environ["HOME"])


def _global_config(text: str) -> None:
    """Append `text` to the test `HOME`'s `.gitconfig`, which the product's `git` reads."""
    config = _home() / ".gitconfig"
    config.write_text(config.read_text(encoding="utf-8") + text, encoding="utf-8")


def tag_commit(root: Path, tag: str = TAG) -> str:
    return git(root, "rev-parse", f"{tag}^{{commit}}").strip()


def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    return remote


def refs(remote: Path) -> dict[str, str]:
    listing = git(remote, "for-each-ref", "--format=%(refname) %(objectname)")
    return dict(line.split(" ", 1) for line in listing.splitlines())


def remote_commit(remote: Path, message: str, parent: str | None = None) -> str:
    """A commit of the empty tree in `remote`, written there and named by no ref."""
    tree = git_bytes(remote, "mktree", stdin=b"").decode().strip()
    lineage = ("-p", parent) if parent is not None else ()
    return git(remote, "commit-tree", tree, *lineage, "-m", message).strip()


def advance(remote: Path) -> str:
    """`remote`'s `main` moved on by one commit, as someone else's push would move it."""
    main = git(remote, "rev-parse", "refs/heads/main").strip()
    later = remote_commit(remote, "pushed by someone else in the meantime", main)
    git(remote, "update-ref", "refs/heads/main", later, main)
    return later


def with_tool(root: Path, script: bytes, tag: str = TAG) -> None:
    """The tag's commit amended to carry `script` as its `scripts/plugin_tree.py`, and the tag
    moved onto it. No plugin path changes, so the marketplace's pin still holds."""
    write(root, {"scripts/plugin_tree.py": (script, "100755")})
    git(root, "commit", "-q", "-a", "--amend", "--no-edit")
    git(root, "tag", "-f", "-a", tag, "-m", tag)


def repinned(root: Path, sha: str, tag: str = TAG) -> None:
    """The tag's commit amended so its marketplace pins `sha`, and the tag moved onto it."""
    write(root, {MARKETPLACE: pinned_marketplace(sha)})
    git(root, "commit", "-q", "-a", "--amend", "--no-edit")
    git(root, "tag", "-f", "-a", tag, "-m", tag)


SCRIPT = (REPOSITORY / "scripts" / "plugin_tree.py").read_bytes()


def patched(old: bytes, new: bytes) -> bytes:
    """This branch's `scripts/plugin_tree.py` with `old`, which it holds once, made `new`."""
    assert SCRIPT.count(old) == 1, old
    return SCRIPT.replace(old, new)


def manifest_of(root: Path, tag: str = TAG, paths: tuple[str, ...] = NINE) -> str:
    """The manifest of `paths` at `tag`, computed by the test from git's own listing and blobs:
    the format line, then `<mode> <sha256> <path>` per file, by path."""
    rows = []
    for record in git(root, "ls-tree", "-r", "-z", "--full-tree", tag, "--", *paths).split("\0"):
        if record:
            meta, path = record.split("\t", 1)
            mode, _kind, obj = meta.split()
            digest = hashlib.sha256(git_bytes(root, "cat-file", "blob", obj)).hexdigest()
            rows.append((path, f"{mode} {digest} {path}\n"))
    return "stayfixed-plugin-tree 1\n" + "".join(line for _, line in sorted(rows))


def publish(
    source: Path,
    remote: Path | str,
    scratch: Path,
    *,
    yes: bool = True,
    tag: str = TAG,
    runner: Composite | None = None,
) -> tuple[Any, Composite]:
    runner = runner if runner is not None else runner_for(source)
    scratch.mkdir(parents=True, exist_ok=True)
    done = publish_plugin.publish(
        source, tag, remote=str(remote), yes=yes, runner=runner, scratch=scratch
    )
    return done, runner


def listed(root: Path, rev: str, **kwargs: bool) -> dict[str, tuple[bytes, str]]:
    return {m.path: (m.content, m.mode) for m in plugin_tree.read(root, rev, **kwargs).members}


def ran(runner: Composite, word: str) -> list[list[str]]:
    """The recorded argvs that ran `git <word>`, wherever the global options put it."""
    return [argv for argv in runner.calls if argv[:1] == ["git"] and word in argv]


def tool_command(argv: list[str]) -> str | None:
    """The `plugin_tree.py` command an argv runs the tag's copy for, or `None`."""
    return argv[6] if argv[1:3] == ["-I", "-c"] and len(argv) > 6 else None


def tool_runs(runner: Composite) -> list[list[str]]:
    return [argv for argv in runner.calls if tool_command(argv) is not None]


def gh_asked(runner: Composite, *words: str) -> list[list[str]]:
    return [argv for argv in runner.gh.calls if argv[: len(words)] == list(words)]


def plugin_api(runner: Composite) -> list[list[str]]:
    """The `gh api` calls about the plugin repository."""
    return [
        argv
        for argv in gh_asked(runner, "gh", "api")
        if argv[-1].startswith(f"repos/{PLUGIN_REPOSITORY}/")
    ]


# --- A publish that goes through ---------------------------------------------------------------


def test_the_commit_pushed_is_the_pinned_one(source: Path, tmp_path: Path) -> None:
    # Mutations (declared): `mutations/`'s "the plugin commit builds every file without its
    # executable bit" -> the tag's own `plugin_tree.py`, this branch's, makes another commit than
    # the pin and the run is rejected before anything is pushed; "the publisher fetches a main the
    # first release does not have" -> the fetch of the empty remote's `main` fails.
    remote = bare_remote(tmp_path)
    done, _ = publish(source, remote, tmp_path / "scratch")
    expected = hashed(source, literal(plugin_tree_id(source, TAG), None))
    assert pinned_at(source, TAG) == expected
    assert refs(remote) == {"refs/heads/main": expected, f"refs/tags/{TAG}": expected}
    assert (done.tag, done.commit, done.outcome, done.confirmed) == (TAG, expected, "pushed", False)
    assert git(remote, "cat-file", "commit", expected) == literal(done.tree, None)
    assert listed(remote, TAG, exact=True) == listed(source, TAG)
    assert done.files == len(listed(source, TAG))
    assert listed(remote, TAG)["hooks/run-hook.sh"][1] == "100755"
    assert listed(remote, TAG)["scripts/stayfixed"][1] == "100755"


def test_without_yes_the_remote_is_unchanged(source: Path, tmp_path: Path) -> None:
    # Mutations (declared): `mutations/`'s "the publisher pushes without --yes" -> the remote
    # gains both refs; "the publisher reports its commit's id as the tree it pushes" -> the tree
    # reported is not the commit's.
    remote, scratch = bare_remote(tmp_path), tmp_path / "scratch"
    done, runner = publish(source, remote, scratch, yes=False)
    assert refs(remote) == {}
    assert ran(runner, "push") == []
    assert (done.outcome, done.commit) == ("would-push", pinned_at(source, TAG))
    # The commit the dry run reports is the one the tag's code built, and the tree is its own.
    built = scratch / "plugin.git"
    assert git(built, "rev-parse", "--verify", f"{done.commit}^{{commit}}").strip() == done.commit
    assert git(built, "rev-parse", f"{done.commit}^{{tree}}").strip() == done.tree


def test_the_tree_a_dry_run_names_is_the_one_a_later_run_pushes(
    source: Path, tmp_path: Path
) -> None:
    # No mutation of its own: the commit is a function of the source commit, which
    # `test_the_commit_pushed_is_the_pinned_one` holds; this pins a dry run's answer to be the one
    # a later run pushes, the commit as well as the tree.
    remote = bare_remote(tmp_path)
    dry, _ = publish(source, remote, tmp_path / "dry", yes=False)
    pushed, _ = publish(source, remote, tmp_path / "pushed")
    assert (pushed.tree, pushed.commit) == (dry.tree, dry.commit)
    assert git(remote, "rev-parse", "refs/heads/main").strip() == dry.commit


def test_an_edit_on_disk_or_only_staged_is_not_in_the_commit_pushed(
    source: Path, tmp_path: Path
) -> None:
    # No mutation of its own: the commit is the tag's `plugin_tree.py`'s, which reads a commit and
    # nothing else (its own tests hold that); what this holds is that `publish` hands it the tag's
    # commit, as the next case does against a branch.
    remote = bare_remote(tmp_path)
    (source / "README.md").write_bytes(b"edited on disk\n")
    write(source, {"skills/staged/SKILL.md": (b"staged only\n", "100644")})
    git(source, "add", "skills/staged/SKILL.md")
    publish(source, remote, tmp_path / "scratch")
    pushed = listed(remote, TAG, exact=True)
    assert pushed["README.md"] == PLUGIN_FILES["README.md"]
    assert "skills/staged/SKILL.md" not in pushed


def test_a_branch_named_like_the_tag_does_not_stand_in_for_it(source: Path, tmp_path: Path) -> None:
    # git's own order reads a tag before a branch of one name, so resolving the bare name would
    # pass this too; the mutation that a branch standing in for an absent tag reddens is in
    # `test_an_unknown_tag_is_refused_before_anything_runs`.
    remote = bare_remote(tmp_path)
    write(source, {"README.md": (b"# on the branch\n", "100644")})
    git(source, "checkout", "-q", "-b", "elsewhere")
    branch_commit = commit(source, "the branch's commit")
    git(source, "branch", "-q", TAG, branch_commit)
    publish(source, remote, tmp_path / "scratch")
    assert listed(remote, TAG, exact=True)["README.md"] == PLUGIN_FILES["README.md"]


GH_VERSION = ["gh", "--version"]
GH_AUTH = ["gh", "auth", "status", "--hostname", "github.com", "--active"]


def test_the_attestation_is_asked_with_an_exact_identity(source: Path, tmp_path: Path) -> None:
    # Every `gh` call of a dry run to another remote, whole and in order. Mutations (declared),
    # one entry each: `--cert-identity` -> `--signer-workflow` with the old value; the identity
    # without its `@refs/tags/<tag>`; `--cert-identity` dropped; `--source-ref` dropped;
    # `--source-digest` dropped; `--deny-self-hosted-runners` dropped; the verify's `--hostname`
    # dropped; `gh auth status` without `--hostname`; `gh auth status` without `--active`; the
    # verify's `--repo` dropped; the manifest dropped from the verify; `mutations/`'s "the
    # publisher asks gh whether it is logged in before asking its version" (the order).
    scratch = tmp_path / "scratch"
    _, runner = publish(source, bare_remote(tmp_path), scratch, yes=False)
    sha = tag_commit(source)
    tag_object = git(source, "rev-parse", f"refs/tags/{TAG}").strip()
    assert len(sha) == 40 and tag_object != sha
    manifest = scratch / "plugin-tree.txt"
    assert runner.gh.calls == [
        GH_VERSION,
        GH_AUTH,
        ["gh", "api", "--hostname", "github.com", f"repos/stayfixed/stayfixed/git/ref/tags/{TAG}"],
        [
            "gh",
            "api",
            "--hostname",
            "github.com",
            f"repos/stayfixed/stayfixed/git/tags/{tag_object}",
        ],
        [
            "gh",
            "attestation",
            "verify",
            str(manifest),
            "--hostname",
            "github.com",
            "--repo",
            "stayfixed/stayfixed",
            "--cert-identity",
            "https://github.com/stayfixed/stayfixed/.github/workflows/release.yml@refs/tags/v1.2.3",
            "--source-ref",
            "refs/tags/v1.2.3",
            "--source-digest",
            sha,
            "--deny-self-hosted-runners",
        ],
    ]
    # The file it is asked about is the manifest of the plugin's files at the tag.
    assert manifest.read_text(encoding="utf-8") == manifest_of(source)
    assert manifest_of(source).startswith("stayfixed-plugin-tree 1\n")


def test_a_second_publish_of_the_same_tag_pushes_nothing(source: Path, tmp_path: Path) -> None:
    # Mutations (declared): `mutations/`'s "the publisher treats a tag already on the remote as
    # absent" -> the second run finds `main` at the commit, which is not its parent, and is
    # rejected; "the publisher asks for the attestation after listing the remote" -> the ordering
    # below.
    remote = bare_remote(tmp_path)
    first, _ = publish(source, remote, tmp_path / "first")
    before = refs(remote)
    second, runner = publish(source, remote, tmp_path / "second")
    assert (second.outcome, second.commit, second.tree) == ("already", first.commit, first.tree)
    assert refs(remote) == before
    assert ran(runner, "push") == ran(runner, "fetch") == []
    # The attestation is asked again before the remote is: a re-run trusts nothing it found.
    verify = next(i for i, argv in enumerate(runner.calls) if argv[:2] == ["gh", "attestation"])
    listing = next(i for i, argv in enumerate(runner.calls) if "ls-remote" in argv)
    assert verify < listing


def test_the_previous_release_is_replaced_whole(source: Path, tmp_path: Path) -> None:
    # No mutation of its own: the parent is the tag's `plugin_tree.py`'s, held by
    # `test_the_parent_is_the_sha_the_first_parent_pins` in its own tests, and `main` moving only
    # to a commit whose parent it is by `test_a_main_that_is_not_the_parent_is_rejected`. This
    # holds the fast-forward end to end: the earlier release's file is gone from the new tree.
    remote = bare_remote(tmp_path)
    first, _ = publish(source, remote, tmp_path / "first")
    (source / "skills" / "close-bug" / "SKILL.md").unlink()
    pin = released(source, "1.2.4", files={"skills/other/SKILL.md": (b"# other\n", "100644")})
    done, _ = publish(source, remote, tmp_path / "second", tag="v1.2.4")
    assert done.commit == pin
    assert git(remote, "rev-parse", f"{pin}^").strip() == first.commit
    assert listed(remote, "v1.2.4", exact=True) == listed(source, "v1.2.4")
    assert "skills/close-bug/SKILL.md" not in listed(remote, "v1.2.4", exact=True)
    assert refs(remote) == {
        "refs/heads/main": pin,
        f"refs/tags/{TAG}": first.commit,
        "refs/tags/v1.2.4": pin,
    }


# --- What the owner's own git configuration cannot change -----------------------------------------


def test_the_owners_hooks_do_not_run_in_the_scratch_repository(
    source: Path, tmp_path: Path
) -> None:
    # Mutation (declared): `mutations/`'s "the publisher lets the owner's hooks run on its push"
    # -> the owner's `pre-push` runs and refuses the push. The git dir's own gits are
    # `plugin_tree.py`'s, held by `test_the_owners_hooks_do_not_run_in_the_git_dir`.
    remote = bare_remote(tmp_path)
    hooks = _home() / "hooks"
    hooks.mkdir()
    (hooks / "pre-push").write_text("#!/bin/sh\necho refused by pre-push >&2\nexit 1\n")
    (hooks / "pre-push").chmod(0o755)
    _global_config(f"[core]\n\thooksPath = {hooks}\n")
    done, _ = publish(source, remote, tmp_path / "scratch")
    assert done.outcome == "pushed"
    assert refs(remote) == {"refs/heads/main": done.commit, f"refs/tags/{TAG}": done.commit}


def test_an_explicit_safe_bare_repository_does_not_refuse_the_scratch_repository(
    source: Path, tmp_path: Path
) -> None:
    # Mutations (declared): `mutations/`'s "the publisher finds its scratch repository from -C in
    # its network git" and "the publisher finds its scratch repository from -C in its local git"
    # -> `safe.bareRepository=explicit` refuses the bare repository `git -C` finds, at the listing
    # or at the read of the fetched `main`. The git dir's own gits are `plugin_tree.py`'s, held
    # by `test_an_explicit_safe_bare_repository_does_not_refuse_the_git_dir`.
    remote = bare_remote(tmp_path)
    first, _ = publish(source, remote, tmp_path / "first")
    pin = released(source, "1.2.4")
    _global_config("[safe]\n\tbareRepository = explicit\n")
    done, _ = publish(source, remote, tmp_path / "second", tag="v1.2.4")
    assert done.outcome == "pushed"
    assert refs(remote)["refs/heads/main"] == pin
    assert git(remote, "rev-parse", f"{pin}^").strip() == first.commit


def test_a_replace_ref_does_not_stand_in_for_the_tags_version(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the plugin tree reads an object through a replace ref"
    # -> the tag's own `plugin_tree.py` reads the replaced `plugin.json`, whose tree is not the one
    # the marketplace pinned, and the run is rejected for the pin rather than for the version.
    git(source, "tag", "v1.2.4")
    plugin_json = git(source, "rev-parse", "HEAD:.claude-plugin/plugin.json").strip()
    write(source, {"replacement.json": (b'{"version": "1.2.4"}\n', "100644")})
    replacement = git(source, "hash-object", "-w", "replacement.json").strip()
    git(source, "replace", plugin_json, replacement)
    remote = bare_remote(tmp_path)
    with pytest.raises(Rejected, match=r"plugin\.json says 1\.2\.3") as rejected:
        publish(source, remote, tmp_path / "scratch", tag="v1.2.4")
    assert "v1.2.4" in str(rejected.value)
    assert refs(remote) == {}


def test_a_replace_ref_on_the_tag_object_does_not_move_the_tags_commit(
    source: Path, tmp_path: Path
) -> None:
    # Mutation (declared): `mutations/`'s "the publisher peels the tag through a replace ref" ->
    # the annotated tag's object is read as its replacement, which points at another commit, and
    # GitHub's tag, which no replacement moves, is not that commit.
    remote = bare_remote(tmp_path)
    tagged = tag_commit(source)
    write(source, {"README.md": (b"# another tree under the same version\n", "100644")})
    other = commit(source, "another commit")
    git(source, "tag", "-a", "elsewhere", "-m", "elsewhere", other)
    tag_object = git(source, "rev-parse", f"refs/tags/{TAG}").strip()
    elsewhere = git(source, "rev-parse", "refs/tags/elsewhere").strip()
    git(source, "replace", "-f", tag_object, elsewhere)
    # The premise: through the replacement, the tag peels to the other commit.
    assert git(source, "rev-parse", f"refs/tags/{TAG}^{{commit}}").strip() == other
    done, runner = publish(source, remote, tmp_path / "scratch")
    asked = gh_asked(runner, "gh", "attestation", "verify")
    assert len(asked) == 1, runner.gh.calls
    assert asked[0][asked[0].index("--source-digest") + 1] == tagged
    assert done.outcome == "pushed"
    assert listed(remote, TAG, exact=True)["README.md"] == PLUGIN_FILES["README.md"]


# --- Refusals before anything runs ------------------------------------------------------------


def test_an_unknown_tag_is_refused_before_anything_runs(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher lets a branch stand in for an absent tag"
    # -> the branch `v2.0.0` stands in for the tag that does not exist.
    write(source, {".claude-plugin/plugin.json": (b'{"version": "2.0.0"}\n', "100644")})
    git(source, "branch", "-q", "v2.0.0", commit(source, "two"))
    runner, scratch = runner_for(source), tmp_path / "scratch"
    with pytest.raises(Refusal, match=r"v2\.0\.0"):
        publish(source, bare_remote(tmp_path), scratch, tag="v2.0.0", runner=runner)
    assert runner.calls == []
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("tag", ["v1.2.3\n", "v1.2.3-rc1", "v\N{ARABIC-INDIC DIGIT ONE}.2.3"])
def test_a_tag_that_is_not_a_plain_version_is_refused(
    source: Path, tmp_path: Path, tag: str
) -> None:
    # Mutations (declared): `re.fullmatch` -> `re.match` admits `v1.2.3-rc1`; `[0-9]` -> `\d`
    # admits the Arabic-Indic digit. Each tag git can name is made to exist, with a `plugin.json`
    # whose version spells it, so only the pattern stands between it and the run.
    if "\n" not in tag:
        version = tag.removeprefix("v")
        body = f'{{"version": "{version}"}}\n'.encode()
        write(source, {".claude-plugin/plugin.json": (body, "100644")})
        git(source, "tag", tag, commit(source, "a version that is not plain"))
    runner = runner_for(source)
    with pytest.raises(Refusal, match="plain version"):
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", tag=tag, runner=runner)
    assert runner.calls == []


OTHER = "e" * 40
ANOTHER_ID = Completed(
    0, json.dumps({"ref": f"refs/tags/{TAG}", "object": {"sha": OTHER, "type": "commit"}}), ""
)


@pytest.mark.parametrize(
    ("answer", "named", "advice"),
    [
        pytest.param(
            ANOTHER_ID,
            f"names {OTHER}",
            f"If you did not push GitHub's {TAG}, investigate it before you fetch or run anything; "
            "if yours is the stale one, fetch GitHub's over it (git fetch --tags --force) and run "
            "again; nothing was run",
            id="another-id",
        ),
        pytest.param(
            NOT_FOUND,
            "holds no such tag",
            "Push the tags (RELEASING.md section 2, step 6) and run again",
            id="no-such-tag",
        ),
    ],
)
def test_a_local_tag_github_does_not_hold_is_refused(
    source: Path, tmp_path: Path, answer: Completed, named: str, advice: str
) -> None:
    # A tag GitHub holds at another commit may not be the owner's, and a fetch over the local one
    # would run its code next, so it is investigated first, and fetched over the local one only
    # when that is the stale one, with `--force`, without which git 2.54 refuses ("would clobber
    # existing tag"); one GitHub lacks was not pushed. Mutations (declared): `mutations/`'s "the
    # publisher runs a tag GitHub does not hold" -> the tag's code is extracted and run, and the
    # publish goes on; "the publisher advises fetching over the local tag without investigating
    # GitHub's" -> `another-id` is told to fetch at once; "the publisher advises a fetch git
    # refuses for a tag that differs" -> `another-id` is told `git fetch --tags`; "the publisher
    # advises a fetch for a tag GitHub does not hold" -> `no-such-tag` is told to fetch what is
    # not there.
    asked = f"gh api --hostname github.com repos/{SOURCE_REPOSITORY}/git/ref/tags/{TAG}"
    runner, scratch = runner_for(source, answers={asked: answer}), tmp_path / "scratch"
    with pytest.raises(Refusal, match="is not GitHub's") as refused:
        publish(source, bare_remote(tmp_path), scratch, runner=runner)
    assert tag_commit(source) in str(refused.value)
    assert named in str(refused.value)
    assert advice in str(refused.value), str(refused.value)
    assert not (scratch / "tool").exists()
    assert tool_runs(runner) == gh_asked(runner, "gh", "attestation") == []


SERVER_ERROR = Completed(
    1, '{"message":"Server Error","status":"500"}', "gh: Server Error (HTTP 500)\n"
)
NOT_JSON = Completed(0, "<html>a proxy's page</html>\n", "")
NO_OBJECT_NAME = Completed(
    0, json.dumps({"ref": f"refs/tags/{TAG}", "object": {"sha": "+main", "type": "commit"}}), ""
)


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        pytest.param(SERVER_ERROR, "exited 1: 'gh: Server Error (HTTP 500)'", id="a-server-error"),
        pytest.param(NOT_JSON, "answered no JSON object", id="not-json"),
        pytest.param(NO_OBJECT_NAME, "GitHub answered '+main' for", id="no-object-name"),
    ],
)
def test_an_api_answer_that_is_neither_a_ref_nor_its_absence_is_refused(
    source: Path, tmp_path: Path, answer: Completed, said: str
) -> None:
    # Mutations (declared): `mutations/`'s "the publisher reads any failed API call as absent" ->
    # the server error reads as GitHub holding no such tag; "the publisher reads a failed API
    # call's body as its answer" -> the error's body is read for an object it does not hold;
    # "the publisher takes an API answer that is no JSON object as no ref" -> the proxy's page
    # reads as no such tag; "the publisher takes GitHub's answer that is no object name" ->
    # `+main` is compared with the tag's commit. Each refusal then names another cause.
    asked = f"gh api --hostname github.com repos/{SOURCE_REPOSITORY}/git/ref/tags/{TAG}"
    runner = runner_for(source, answers={asked: answer})
    with pytest.raises(Refusal) as refused:
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", runner=runner)
    assert said in str(refused.value), str(refused.value)
    assert "is not GitHub's" not in str(refused.value)
    assert tool_runs(runner) == []


def test_a_tag_without_the_plugin_tree_script_is_refused(tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher runs a tag that predates it" -> the tag's
    # `src/stayfixed` is extracted without a script to run, and the run fails in Python's words.
    source = plugin_source(tmp_path)
    git(source, "tag", "-a", TAG, "-m", TAG)
    runner, scratch = runner_for(source), tmp_path / "scratch"
    with pytest.raises(Refusal, match="predates") as refused:
        publish(source, bare_remote(tmp_path), scratch, runner=runner)
    assert "scripts/plugin_tree.py" in str(refused.value)
    assert tool_runs(runner) == []
    assert not (scratch / "tool").exists()


def test_a_tag_without_the_package_its_tool_imports_is_refused(
    source: Path, tmp_path: Path
) -> None:
    # A tag holding `scripts/plugin_tree.py` and no `src/stayfixed`: run, the script would import
    # this checkout's `stayfixed` through the venv's path (`-I` keeps site-packages). Mutation
    # (declared): `mutations/`'s "the publisher runs a tag's tool without the tag's package" -> the
    # tag's script runs, on the checkout's package, and refuses the tree for its missing
    # `src/stayfixed` (a plugin path) in its own words rather than the publisher's.
    git(source, "rm", "-r", "-q", "src/stayfixed")
    git(source, "commit", "-q", "--amend", "--no-edit")
    git(source, "tag", "-f", "-a", TAG, "-m", TAG)
    assert git(source, "ls-tree", "-r", "--name-only", TAG, "--", "src") == ""
    runner, scratch = runner_for(source), tmp_path / "scratch"
    with pytest.raises(Refusal, match="predates") as refused:
        publish(source, bare_remote(tmp_path), scratch, runner=runner)
    assert "no src/stayfixed" in str(refused.value)
    assert tool_runs(runner) == []
    assert not (scratch / "tool").exists()


def test_a_tool_file_that_is_not_regular_is_refused(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher runs the tag's code from a file that is
    # not regular" -> the symlink is written as a file holding its target's name, and the tag's
    # code runs.
    os.symlink("__init__.py", source / "src" / "stayfixed" / "linked.py")
    commit(source, "a symlink among the tag's code")
    git(source, "tag", "-f", "-a", TAG, "-m", TAG)
    runner, scratch = runner_for(source), tmp_path / "scratch"
    with pytest.raises(Refusal, match=r"src/stayfixed/linked\.py") as refused:
        publish(source, bare_remote(tmp_path), scratch, runner=runner)
    assert "120000" in str(refused.value)
    assert tool_runs(runner) == []
    assert not (scratch / "tool").exists()


# --- The tag's own code ---------------------------------------------------------------------------


def test_the_tag_s_own_plugin_tree_builds_the_commit(tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher runs the checkout's plugin_tree.py" ->
    # the checkout's copy reads nine paths, so its commit is not the pin and the run is rejected
    # when the commit is built, before any manifest is compared.
    ten = (*NINE, "commands")
    script = patched(b'    "LICENSE",\n)', b'    "LICENSE",\n    "commands",\n)')
    extra = {"commands/a.md": (b"# a command\n", "100644")}
    source = tool_source(tmp_path, plugin_tree=script, extra=extra, paths=ten)
    scratch = tmp_path / "scratch"
    done, _ = publish(source, bare_remote(tmp_path), scratch, yes=False)
    assert (done.outcome, done.commit) == ("would-push", pinned_at(source, TAG))
    expected = manifest_of(source, TAG, ten)
    assert (scratch / "plugin-tree.txt").read_text(encoding="utf-8") == expected
    line = "100644 dcf4a2ae11e48a937801393a5a5521068b50366476f099740f5576f081a659a2 commands/a.md\n"
    assert line in expected
    assert done.files == expected.count("\n") - 1


def test_the_tag_s_tool_imports_the_tag_s_stayfixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mutation (declared): `mutations/`'s "the publisher puts the tag's src after the checkout's"
    # -> the venv's path to this checkout's `src` is read first, and the tag's code runs on this
    # checkout's `stayfixed`.
    marker = b"from __future__ import annotations\n"
    line = (
        b"import os, stayfixed; "
        b'open(os.environ["PUBLISH_TEST_IMPORTED"], "w").write(stayfixed.__file__)\n'
    )
    imported = tmp_path / "imported.txt"
    monkeypatch.setenv("PUBLISH_TEST_IMPORTED", str(imported))
    source = tool_source(tmp_path, plugin_tree=patched(marker, marker + line))
    scratch = tmp_path / "scratch"
    publish(source, bare_remote(tmp_path), scratch, yes=False)
    written = Path(imported.read_text(encoding="utf-8")).resolve()
    assert written == (scratch / "tool" / "src" / "stayfixed" / "__init__.py").resolve()


@pytest.mark.parametrize(
    ("name", "value", "shown"),
    [
        pytest.param("commit", '"+main"', "'+main'", id="commit"),
        pytest.param("tree", '"+main"', "'+main'", id="tree"),
        pytest.param("parent", '"+main"', "'+main'", id="parent"),
        pytest.param("files", '"10"', "a str", id="files"),
        pytest.param("version", "123", "a int", id="version"),
    ],
)
def test_a_tool_answer_that_is_not_an_object_name_is_refused(
    source: Path, tmp_path: Path, name: str, value: str, shown: str
) -> None:
    # Mutations (declared), one per field: `mutations/`'s "the publisher takes a tool's commit
    # that is no object name" -> `+main` reaches the read-back, which refuses it in the tool's
    # words; "the publisher takes a tool's tree that is no object name" and "the publisher takes
    # a tool's file count that is no integer" -> the run goes through; "the publisher takes a
    # tool's parent that is no object name" -> `+main` is compared with `main` and rejected;
    # "the publisher takes a tool's version that is no string" -> the integer reaches the
    # version's wording and escapes as an internal error. `value` is the Python the tag's script
    # writes into its answer.
    data = b'{"format": FORMAT, **asdict(found)}'
    with_tool(source, patched(data, data[:-1] + f', "{name}": {value}}}'.encode()))
    remote = bare_remote(tmp_path)
    runner = runner_for(source)
    with pytest.raises(Refusal) as refused:
        publish(source, remote, tmp_path / "scratch", runner=runner)
    assert f"commit answered {shown} for {name}," in str(refused.value), str(refused.value)
    assert ran(runner, "push") == []
    assert refs(remote) == {}


def test_a_tool_answering_in_another_format_is_refused(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher reads a tool answer in another format" ->
    # both manifests are in the other format, they agree, and the run pushes.
    old = b'FORMAT = "stayfixed-plugin-tree 1"'
    with_tool(source, patched(old, b'FORMAT = "stayfixed-plugin-tree 2"'))
    remote = bare_remote(tmp_path)
    runner = runner_for(source)
    with pytest.raises(Refusal, match="stayfixed-plugin-tree 2"):
        publish(source, remote, tmp_path / "scratch", runner=runner)
    assert gh_asked(runner, "gh", "attestation") == []
    assert refs(remote) == {}


# --- Rejections: facts of the release no re-run changes -------------------------------------------


def test_a_pin_other_than_the_commit_is_rejected(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher refuses a pin it should reject" -> the
    # pin's difference is a refusal, exit 2, which says to run again.
    made = pinned_at(source, TAG)
    repinned(source, "c" * 40)
    remote = bare_remote(tmp_path)
    runner = runner_for(source)
    with pytest.raises(Rejected) as rejected:
        publish(source, remote, tmp_path / "scratch", runner=runner)
    assert "c" * 40 in str(rejected.value)
    assert str(made) in str(rejected.value)
    assert gh_asked(runner, "gh", "attestation") == []
    assert refs(remote) == {}


def test_a_tag_whose_version_is_another_is_rejected(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher stops holding the tag to the version it
    # releases" -> the run goes on and pushes `v1.2.4` holding 1.2.3.
    git(source, "tag", "v1.2.4")
    remote = bare_remote(tmp_path)
    runner = runner_for(source)
    with pytest.raises(Rejected, match=r"1\.2\.3") as rejected:
        publish(source, remote, tmp_path / "scratch", tag="v1.2.4", runner=runner)
    assert "v1.2.4" in str(rejected.value)
    assert gh_asked(runner, "gh", "attestation") == []
    assert refs(remote) == {}


@pytest.mark.parametrize("annotated", [False, True], ids=["lightweight", "annotated"])
def test_another_commit_under_the_tag_is_rejected(
    source: Path, tmp_path: Path, annotated: bool
) -> None:
    # Mutations (declared): `mutations/`'s "the publisher treats a tag already on the remote as
    # absent" -> the run goes on to push, and the remote refuses the tag that exists, with git's
    # sentence and exit 2; "the publisher calls another commit under the tag published" -> the
    # run says "already" of another commit. Mutation (declared): `mutations/`'s "the publisher
    # rejects a tag it read from ls-remote alone without saying so" -> the rejection rests on a
    # listing nothing confirmed, and does not say it.
    remote = bare_remote(tmp_path)
    some = remote_commit(remote, "another commit under the tag")
    if annotated:
        git(remote, "tag", "-a", TAG, "-m", TAG, some)
    else:
        git(remote, "update-ref", f"refs/tags/{TAG}", some)
    before = refs(remote)
    runner = runner_for(source)
    with pytest.raises(Rejected) as rejected:
        publish(source, remote, tmp_path / "scratch", runner=runner)
    assert some in str(rejected.value)
    assert str(pinned_at(source, TAG)) in str(rejected.value)
    assert "(not confirmed through GitHub's API)" in str(rejected.value), str(rejected.value)
    assert ran(runner, "fetch") == ran(runner, "push") == []
    assert refs(remote) == before


def test_an_annotated_tag_peeling_to_the_pin_is_already_published(
    source: Path, tmp_path: Path
) -> None:
    # Mutation (declared): `mutations/`'s "the publisher compares the tag object where the remote
    # lists its peel" -> the tag object's id is not the commit, and the run is rejected.
    remote = bare_remote(tmp_path)
    first, _ = publish(source, remote, tmp_path / "first")
    git(remote, "tag", "-f", "-a", TAG, "-m", "annotated on the remote", first.commit)
    assert refs(remote)[f"refs/tags/{TAG}"] != first.commit
    before = refs(remote)
    done, runner = publish(source, remote, tmp_path / "second")
    assert (done.outcome, done.commit) == ("already", first.commit)
    assert ran(runner, "fetch") == ran(runner, "push") == []
    assert refs(remote) == before


def test_a_published_tag_with_main_moved_on_is_already_published(
    source: Path, tmp_path: Path
) -> None:
    # No mutation exists: no line compares `main` once the tag names the commit. This pins a
    # re-run after the plugin repository moved on against such a comparison coming back, which
    # would refuse a release that was published.
    remote = bare_remote(tmp_path)
    first, _ = publish(source, remote, tmp_path / "first")
    later = advance(remote)
    done, runner = publish(source, remote, tmp_path / "second")
    assert (done.outcome, done.commit) == ("already", first.commit)
    assert refs(remote) == {"refs/heads/main": later, f"refs/tags/{TAG}": first.commit}
    assert ran(runner, "push") == []


@pytest.mark.parametrize(
    ("main", "previous"),
    [
        pytest.param(False, "c" * 40, id="no-main"),
        pytest.param(True, None, id="no-parent"),
        pytest.param(True, "c" * 40, id="another-main"),
    ],
)
def test_a_main_that_is_not_the_parent_is_rejected(
    source: Path, tmp_path: Path, main: bool, previous: str | None
) -> None:
    # The plugin repository's `main` moves only by fast-forward, so the commit this release pins
    # must follow it: rejected, naming both, before anything is fetched or pushed. Mutation
    # (declared): `mutations/`'s "the publisher builds on a main that is not the parent" -> each
    # case goes on, to a fetch of a `main` the remote lacks or a push the remote refuses, exit 2;
    # "the publisher rejects a main it read from ls-remote alone without saying so" -> the
    # rejection rests on a listing nothing confirmed, and does not say it.
    remote = bare_remote(tmp_path)
    if main:
        git(remote, "update-ref", "refs/heads/main", remote_commit(remote, "some"))
    before = refs(remote)
    pin = released(source, "1.2.4", before=previous)
    runner = runner_for(source)
    with pytest.raises(Rejected) as rejected:
        publish(source, remote, tmp_path / "scratch", tag="v1.2.4", runner=runner)
    said = str(rejected.value)
    assert pin in said
    assert (f"parent {previous}" if previous else "no parent") in said, said
    assert (f"main at {before['refs/heads/main']}" if main else "no main") in said, said
    # Read from `ls-remote` alone, on a remote that is not the default, and said so.
    assert "(not confirmed through GitHub's API)" in said, said
    assert ran(runner, "fetch") == ran(runner, "push") == []
    assert refs(remote) == before


def test_a_rejection_on_the_default_remote_is_not_said_to_be_unconfirmed(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On the default remote GitHub's API read `main` as well, so the rejection rests on it and
    # says nothing of a listing alone. Mutation (declared): `mutations/`'s "the publisher says a
    # rejection GitHub's API confirmed is not confirmed" -> the clause is added here too.
    github = bare_remote(tmp_path)
    git(github, "update-ref", "refs/heads/main", remote_commit(github, "some"))
    default = publish_plugin.PLUGIN_REMOTE
    _global_config(f'[url "{github}"]\n\tinsteadOf = {default}\n')
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    with pytest.raises(Rejected) as rejected:
        publish(source, default, tmp_path / "scratch", runner=runner_for(source, github))
    said = str(rejected.value)
    assert "moves only by fast-forward" in said, said
    assert "not confirmed" not in said, said


def test_publishing_an_older_line_never_rewinds_main(source: Path, tmp_path: Path) -> None:
    # No mutation of its own: the rejection is `main`'s comparison with the parent, whose entry
    # reddens `test_a_main_that_is_not_the_parent_is_rejected`. This holds the case a patch
    # release of an older line makes.
    remote = bare_remote(tmp_path)
    publish(source, remote, tmp_path / "first")
    newer = released(source, "1.3.0")
    publish(source, remote, tmp_path / "second", tag="v1.3.0")
    assert refs(remote)["refs/heads/main"] == newer
    git(source, "checkout", "-q", "-b", "line-1.2", TAG)
    released(source, "1.2.4", before=None)
    with pytest.raises(Rejected, match="no parent"):
        publish(source, remote, tmp_path / "third", tag="v1.2.4")
    assert refs(remote)["refs/heads/main"] == newer
    assert "refs/tags/v1.2.4" not in refs(remote)


def test_a_manifest_changed_after_the_commit_is_rejected_by_the_read_back(
    source: Path, tmp_path: Path
) -> None:
    # Mutation (declared): `mutations/`'s "the publisher pushes without reading its commit back"
    # -> the commit is pushed under a manifest it does not hold. The edit lands just after the
    # tag's code wrote the commit and its manifest: the one window in which the two can part.
    def edit(argv: list[str]) -> None:
        if tool_command(argv) == "commit":
            manifest = Path(argv[argv.index("--manifest-file") + 1])
            manifest.write_bytes(manifest.read_bytes().replace(b"\n100644 ", b"\n100755 ", 1))

    remote = bare_remote(tmp_path)
    runner = runner_for(source, after=edit)
    with pytest.raises(Rejected, match=r"\.claude-plugin/icon\.png") as rejected:
        publish(source, remote, tmp_path / "scratch", runner=runner)
    assert "nothing was pushed" in str(rejected.value)
    assert refs(remote) == {}
    assert ran(runner, "push") == []


# `gh attestation verify` failing as the pre-flight measured it for an identity that did not match.
UNVERIFIED = Completed(1, "", 'Error: verifying with issuer "sigstore.dev"\n')
# What GitHub answers about the manifest's digest: an attestation exists (200, a list holding one),
# a 200 that lists none, a 200 whose list is no list, and a 200 with no list at all.
ATTESTED = Completed(
    0, json.dumps({"attestations": [{"bundle": {}, "repository_id": 1, "bundle_url": None}]}), ""
)
NONE_LISTED = Completed(0, json.dumps({"attestations": []}), "")
NO_LIST = Completed(0, json.dumps({"attestations": "one"}), "")
NO_KEY = Completed(0, json.dumps({"message": "OK"}), "")
# The advice each answer chooses: an attestation that does not verify here, none yet, and an
# answer that says neither.
DOES_NOT_VERIFY_HERE = (
    "does not verify on this machine against stayfixed/stayfixed's release.yml at v1.2.3",
    "run again, and if it says the same with a working gh and network once the release's build "
    "and attest jobs are green, reject the release's approval",
)
NONE_YET = (
    "GitHub holds no attestation of this manifest yet",
    "once the release's build and attest jobs are green, run again; if it says the same then, "
    "reject the release's approval",
)


@pytest.mark.parametrize(
    ("attestation", "said", "advice"),
    [
        pytest.param(ATTESTED, *DOES_NOT_VERIFY_HERE, id="200"),
        pytest.param(NOT_FOUND, *NONE_YET, id="404"),
        pytest.param(SERVER_ERROR, "Server Error (HTTP 500)", "run again", id="500"),
        pytest.param(NONE_LISTED, "lists no attestation", "run again", id="200-listing-none"),
        pytest.param(NO_LIST, "lists no attestation", "run again", id="200-listing-no-list"),
        pytest.param(NO_KEY, "lists no attestation", "run again", id="200-no-listing"),
    ],
)
def test_a_failed_verify_is_refused_with_the_advice_github_s_listing_chooses(
    source: Path, tmp_path: Path, attestation: Completed, said: str, advice: str
) -> None:
    # `gh auth status` answers 0 and only `gh attestation verify` answers 1. A verify that fails is
    # a fact of this machine as much as of the release, so every case is a refusal (2), never a
    # rejection; whether GitHub holds an attestation of the manifest only chooses the advice.
    # Mutations (declared): `mutations/`'s "the publisher goes on past a refused attestation" ->
    # the run lists the remote; `mutations/`'s "the publisher asks for a rejection on a failed
    # verify" -> the 200 is rejected; `mutations/`'s "the publisher reads a missing attestation as
    # a wrong one" (the two pieces of advice swapped) -> 200 and 404 each get the other's;
    # `mutations/`'s "the publisher takes an empty attestation list for one", `mutations/`'s "the
    # publisher takes an attestation answer that is no list for one" and `mutations/`'s "the
    # publisher takes an answer with no attestations key for one" -> the listing reads as an
    # attestation; `mutations/`'s "the publisher reads any failed API call as absent" -> the 500
    # reads as no attestation yet; `mutations/`'s "the publisher classifies a failed verify without
    # its words" -> the summary loses gh's words; `mutations/`'s "the publisher stops advising a
    # rejection when no attestation appears once the jobs are green", `mutations/`'s "the publisher
    # stops advising a rejection when an attestation keeps failing to verify", `mutations/`'s "the
    # publisher refuses an unanswered attestation query without saying to run again" and
    # `mutations/`'s "the publisher refuses an attestation listing it cannot read without saying
    # to run again" -> the advice goes.
    remote, scratch = bare_remote(tmp_path), tmp_path / "scratch"
    answers = {"gh auth status": Completed(0, "", ""), "gh attestation verify": UNVERIFIED}
    runner = runner_for(source, answers=answers, attestation=attestation)
    with pytest.raises((Rejected, Refusal)) as stopped:
        publish(source, remote, scratch, runner=runner)
    assert type(stopped.value) is Refusal, stopped.value
    message = str(stopped.value)
    assert said in message, message
    assert advice in message, message
    assert "verifying with issuer" in message, message
    digest = hashlib.sha256(manifest_of(source).encode("utf-8")).hexdigest()
    assert digest in message, message
    assert gh_asked(runner, "gh", "api")[-1] == [
        "gh",
        "api",
        "--hostname",
        "github.com",
        f"repos/stayfixed/stayfixed/attestations/sha256:{digest}",
    ]
    assert len(gh_asked(runner, "gh", "attestation", "verify")) == 1
    for word in ("ls-remote", "fetch", "push"):
        assert ran(runner, word) == [], word
    assert refs(remote) == {}


def test_a_gh_that_is_not_logged_in_is_refused_before_verify(source: Path, tmp_path: Path) -> None:
    # Mutations (declared): `mutations/`'s "the publisher goes on with a gh that is not logged in"
    # -> GitHub's API is asked, the tag's code runs and the attestation is asked for;
    # `mutations/`'s "the publisher refuses a gh that is not logged in without gh's words" -> the
    # refusal no longer says why. `gh auth status` fails for a network or a token it cannot use as
    # well, so the advice is not "log in" alone. Mutation (declared): `mutations/`'s "the publisher
    # advises only a login whatever gh auth status said" -> reddens below.
    said = "You are not logged into any GitHub hosts. To log in, run: gh auth login"
    runner = runner_for(source, answers={"gh auth status": Completed(1, "", f"{said}\n")})
    scratch = tmp_path / "scratch"
    with pytest.raises(Refusal) as refused:
        publish(source, bare_remote(tmp_path), scratch, runner=runner)
    assert "gh auth status --hostname github.com --active exited 1" in str(refused.value)
    assert said in str(refused.value)
    assert "if gh says you are not, or fix what it names" in str(refused.value)
    assert runner.gh.calls == [GH_VERSION, GH_AUTH]
    assert gh_asked(runner, "gh", "api") == gh_asked(runner, "gh", "attestation") == []
    assert tool_runs(runner) == []
    assert not (scratch / "tool").exists()


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        pytest.param(
            Completed(0, "gh version 2.100.9 (2026-08-01)\n", ""),
            "gh 2.100.9 is older than 2.101.0",
            id="2.100.9",
        ),
        pytest.param(
            Completed(0, "gh version 2.99.0 (2026-05-01)\n", ""),
            "gh 2.99.0 is older than 2.101.0",
            id="2.99.0",
        ),
        pytest.param(
            Completed(0, "gh version 2.101 (2026-09-30)\n", ""),
            "could not read gh's version",
            id="two-parts",
        ),
        pytest.param(
            Completed(0, "GitHub CLI, the next one\n", ""),
            "could not read gh's version",
            id="no-version-line",
        ),
        pytest.param(
            Completed(0, "gh version 2.101.0.1 (2026-09-30)\n", ""),
            "could not read gh's version",
            id="four-parts",
        ),
        pytest.param(
            Completed(0, "gh version 2.101.0-rc.1 (2026-09-20)\n", ""),
            "gh 2.101.0-rc.1 is a pre-release",
            id="a-pre-release",
        ),
        pytest.param(
            Completed(1, "gh version 2.101.0 (2026-09-30)\n", "gh: something failed\n"),
            "could not read gh's version",
            id="a-failed-answer",
        ),
    ],
)
def test_a_gh_older_than_the_one_measured_is_refused_first(
    source: Path, tmp_path: Path, answer: Completed, said: str
) -> None:
    # Every flag `gh attestation verify` is handed, and the exact identity match, were measured on
    # gh 2.101.0; an older gh, or a pre-release, may lack one, so it is refused before any other gh
    # call with a message that says so. Mutations (declared): `mutations/`'s "the publisher runs
    # any gh" -> the old gh goes on to `gh auth status`; `mutations/`'s "the publisher compares
    # gh's version as text" -> 2.99.0 reads as newer than 2.101.0; `mutations/`'s "the publisher
    # reads gh's version from an answer it cannot parse" -> the unparsed answer escapes as an
    # internal error; `mutations/`'s "the publisher reads gh's version from a gh that failed" ->
    # the failed gh's version is taken; `mutations/`'s "the publisher refuses an old gh without
    # saying what to do" -> the advice goes; `mutations/`'s "the publisher reads a pre-release's
    # version as the release's" -> 2.101.0-rc.1 goes on; `mutations/`'s "the publisher refuses a
    # pre-release gh without saying what to install" -> the advice goes; `mutations/`'s "the
    # publisher reads gh's version from a line's prefix" -> 2.101.0.1 reads as 2.101.0;
    # `mutations/`'s "the publisher refuses an unreadable gh version without saying to run again"
    # -> the advice goes.
    runner, scratch = runner_for(source, answers={"gh --version": answer}), tmp_path / "scratch"
    with pytest.raises(Refusal) as refused:
        publish(source, bare_remote(tmp_path), scratch, runner=runner)
    message = str(refused.value)
    assert said in message, message
    if "older" in said:
        assert "upgrade gh and run again" in message, message
    elif "pre-release" in said:
        assert "install a released gh at 2.101.0 or later and run again" in message, message
    else:
        assert "could not read" in said and "run again" in message, message
    assert runner.gh.calls == [GH_VERSION]
    assert tool_runs(runner) == []
    assert not (scratch / "tool").exists()


@pytest.mark.parametrize("version", ["2.101.0", "2.110.3", "3.0.0", "10.0.0"])
def test_a_gh_at_or_past_the_one_measured_goes_on(
    source: Path, tmp_path: Path, version: str
) -> None:
    # The floor admits the measured version and any later one, compared as numbers: `10.0.0` reads
    # as older than `2.101.0` as text. Mutation: `mutations/`'s "the publisher compares gh's version
    # as text" also refuses 10.0.0 here.
    answer = Completed(0, f"gh version {version} (2026-10-01)\nhttps://github.com/cli/cli\n", "")
    runner = runner_for(source, answers={"gh --version": answer})
    done, _ = publish(source, bare_remote(tmp_path), tmp_path / "scratch", yes=False, runner=runner)
    assert done.outcome == "would-push"
    assert runner.gh.calls[:2] == [GH_VERSION, GH_AUTH]


def test_a_manifest_that_cannot_be_read_after_a_failed_verify_is_refused(
    source: Path, tmp_path: Path
) -> None:
    # Mutation (declared): `mutations/`'s "the publisher hashes the manifest without catching a
    # failed read" -> the missing file escapes as an internal error.
    def remove(argv: list[str]) -> None:
        if argv[:3] == ["gh", "attestation", "verify"]:
            Path(argv[3]).unlink()

    runner = runner_for(
        source, answers={"gh attestation verify": UNVERIFIED}, attestation=ATTESTED, after=remove
    )
    with pytest.raises(Refusal, match="cannot be read") as refused:
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", runner=runner)
    # `_verify`'s words, not `_read_back`'s, which also says "cannot be read".
    assert "gh attestation verify exited 1" in str(refused.value), str(refused.value)
    assert [argv for argv in gh_asked(runner, "gh", "api") if "attestations" in argv[-1]] == []


# --- Refusals: run again once the cause is fixed --------------------------------------------------


@dataclass
class _Listing(Composite):
    """The composite, with `ls-remote` answered from `listing` rather than by a remote."""

    listing: str = ""

    def launch(self, argv: list[str], cwd: Path) -> Completed:
        if "ls-remote" in argv:
            self.calls.append(argv)
            return Completed(0, self.listing, "")
        return super().launch(argv, cwd)


def test_a_listing_that_names_no_object_is_refused(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher takes a listing that names no object" ->
    # the listing is taken for a `main`, compared with the parent and rejected rather than
    # refused, where a remote that names no object is a remote to fix.
    gh = runner_for(source).gh
    runner = _Listing(gh=gh, listing="--upload-pack=x\trefs/heads/main\n")
    with pytest.raises(Refusal, match="answered '--upload-pack=x' for refs/heads/main"):
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", runner=runner)
    assert ran(runner, "fetch") == []


def test_a_main_that_moves_between_list_and_fetch_is_refused(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher builds on a main the fetch did not bring"
    # -> the run goes on past the fetch and says what it would push onto a `main` that moved.
    remote = bare_remote(tmp_path)
    first, _ = publish(source, remote, tmp_path / "first")
    released(source, "1.2.4")
    moved: list[str] = []

    def race(argv: list[str]) -> None:
        if argv[:1] == ["git"] and "ls-remote" in argv and not moved:
            moved.append(advance(remote))

    runner = runner_for(source, after=race)
    with pytest.raises(Refusal, match="main moved while this ran") as refused:
        publish(source, remote, tmp_path / "second", yes=False, tag="v1.2.4", runner=runner)
    assert "run again" in str(refused.value)
    assert refs(remote) == {"refs/heads/main": moved[0], f"refs/tags/{TAG}": first.commit}


def test_a_fetched_main_that_cannot_be_read_back_is_not_called_moved(
    source: Path, tmp_path: Path
) -> None:
    # The fetch went through and the ref it wrote cannot be read: that is no `main` that moved,
    # and saying so would send the owner looking for a push that never happened. Mutation
    # (declared): `mutations/`'s "the publisher reads a failed rev-parse of the fetched main as a
    # main that moved" -> reddens at the message.
    remote = bare_remote(tmp_path)
    publish(source, remote, tmp_path / "first")
    released(source, "1.2.4")
    scratch = tmp_path / "second"

    def lose(argv: list[str]) -> None:
        if argv[:1] == ["git"] and "fetch" in argv:
            git_dir = scratch / "plugin.git"
            git(git_dir, f"--git-dir={git_dir}", "update-ref", "-d", "refs/stayfixed/main")

    runner = runner_for(source, after=lose)
    with pytest.raises(Refusal, match="git rev-parse of refs/stayfixed/main") as refused:
        publish(source, remote, scratch, yes=False, tag="v1.2.4", runner=runner)
    assert "moved" not in str(refused.value), str(refused.value)
    assert "run again" in str(refused.value)


@pytest.mark.parametrize(
    ("words", "later"),
    [
        pytest.param(("rev-parse", f"refs/tags/{TAG}^{{commit}}"), False, id="the-tag"),
        pytest.param(("ls-tree",), False, id="the-tag-s-code"),
        pytest.param(("cat-file", "--batch"), False, id="the-tag-s-blobs"),
        pytest.param(("rev-parse", "refs/stayfixed/main"), True, id="the-fetched-main"),
    ],
)
def test_a_local_git_that_gave_no_answer_is_refused_in_no_answer_s_words(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    words: tuple[str, ...],
    later: bool,
) -> None:
    # `git_run` answers `-1` for a git that could not run, ran out of time or could not be given
    # its input, and a refusal that formats the code says "exited -1", which tells the owner
    # nothing. Each local git the publisher runs, the post-fetch read of `main` among them.
    # Mutation (declared): `mutations/`'s "the publisher says a local git that gave no answer
    # exited" -> every case says `-1`.
    remote = bare_remote(tmp_path)
    tag = TAG
    if later:
        publish(source, remote, tmp_path / "first")
        released(source, "1.2.4")
        tag = "v1.2.4"
    real = publish_plugin.git_run

    def silent(where: Path, *args: str, **options: Any) -> tuple[int, str]:
        if all(word in args for word in words):
            return -1, ""
        code, answer = real(where, *args, **options)
        return code, answer

    monkeypatch.setattr(publish_plugin, "git_run", silent)
    with pytest.raises(Refusal) as refused:
        publish(source, remote, tmp_path / "second", yes=False, tag=tag)
    said = str(refused.value)
    assert f"gave no answer: {gitenv.NO_ANSWER}" in said, said
    assert "exited -1" not in said, said


def test_only_the_wrapper_runs_a_local_git() -> None:
    # The guard above holds only while every local git goes through `_git`: four did not, and
    # one of them was written in the same pull request that fixed the class next door. Mutation
    # (declared): `mutations/`'s "the publisher runs a local git outside its wrapper" ->
    # `_tag_commit` calls `git_run` itself, and this reddens.
    tree = ast.parse((REPOSITORY / "scripts" / "publish_plugin.py").read_text(encoding="utf-8"))
    callers = sorted(
        function.name
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "git_run"
    )
    assert callers == ["_git"], callers


def test_a_rejected_push_moves_no_ref(source: Path, tmp_path: Path) -> None:
    # Mutations (declared): `mutations/`'s "the publisher's push is not atomic" -> the remote takes
    # `main` and refuses only the tag; "the publisher reports a refused push as pushed" -> no
    # refusal at all.
    remote = bare_remote(tmp_path)
    hook = remote / "hooks" / "update"
    hook.write_text(
        '#!/bin/sh\ncase "$1" in refs/tags/*) echo "tags are refused here" >&2; exit 1;; esac\n'
    )
    hook.chmod(0o755)
    with pytest.raises(Refusal, match="git push") as refused:
        publish(source, remote, tmp_path / "scratch")
    assert "tags are refused here" in str(refused.value)
    assert refs(remote) == {}


def test_a_main_that_moved_before_the_push_is_not_overwritten(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher forces main over a commit pushed after its
    # fetch" -> the commit built on the fetched `main` replaces the one pushed in between, and the
    # tag lands with it.
    remote = bare_remote(tmp_path)
    first, _ = publish(source, remote, tmp_path / "first")
    released(source, "1.2.4")
    moved: list[str] = []

    def race(argv: list[str]) -> None:
        if argv[:1] == ["git"] and "push" in argv:
            moved.append(advance(remote))

    runner = runner_for(source, before=race)
    with pytest.raises(Refusal, match="git push"):
        publish(source, remote, tmp_path / "second", tag="v1.2.4", runner=runner)
    assert refs(remote) == {"refs/heads/main": moved[0], f"refs/tags/{TAG}": first.commit}


# --- GitHub's API, the remote's anchor on the default remote --------------------------------------


def test_the_api_decides_on_the_default_remote(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mutation (declared): `mutations/`'s "the publisher classifies the default remote from
    # ls-remote alone" -> the redirected listing's tag is taken for GitHub's, and the run says
    # "already published" of a release GitHub does not hold. Mutation (declared): `mutations/`'s
    # "the publisher names no push rewrite beside the redirect" -> the refusal leaves a rewrite of
    # the push in place.
    bare = bare_remote(tmp_path)
    _global_config(f'[url "{bare}"]\n\tinsteadOf = {publish_plugin.PLUGIN_REMOTE}\n')
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    default = publish_plugin.PLUGIN_REMOTE
    dry, runner = publish(
        source, default, tmp_path / "dry", yes=False, runner=runner_for(source, bare)
    )
    assert (dry.outcome, dry.confirmed) == ("would-push", True)
    assert sorted(argv[-1] for argv in plugin_api(runner)) == [
        f"repos/{PLUGIN_REPOSITORY}/git/ref/heads/main",
        f"repos/{PLUGIN_REPOSITORY}/git/ref/tags/{TAG}",
    ]
    pushed, _ = publish(source, default, tmp_path / "pushed", runner=runner_for(source, bare))
    assert (pushed.outcome, pushed.confirmed) == ("pushed", True)
    assert refs(bare) == {"refs/heads/main": pushed.commit, f"refs/tags/{TAG}": pushed.commit}
    # GitHub holds no such tag, while the repository the owner's git reaches does.
    tag_api = f"gh api --hostname github.com repos/{PLUGIN_REPOSITORY}/git/ref/tags/{TAG}"
    hidden = runner_for(source, bare, answers={tag_api: NOT_FOUND})
    with pytest.raises(Refusal, match="redirect") as refused:
        publish(source, default, tmp_path / "hidden", runner=hidden)
    assert "insteadOf" in str(refused.value)
    assert "url.*.pushInsteadOf or remote.<url>.pushurl" in str(refused.value), str(refused.value)
    assert "or main moved while this ran" in str(refused.value)
    assert ran(hidden, "push") == []


TAG_API = f"gh api --hostname github.com repos/{PLUGIN_REPOSITORY}/git/ref/tags/{TAG}"


def redirected_runner(source: Path, bare: Path, after_push: Completed | None) -> Composite:
    """A composite whose GitHub holds `bare` as the plugin repository and, once a `git push` has
    run, answers `after_push` for the tag when given: GitHub's view parting from the remote's."""
    runner = runner_for(source, bare)

    def pushed(argv: list[str]) -> None:
        if after_push is not None and argv[:1] == ["git"] and "push" in argv:
            runner.gh.answers[TAG_API] = after_push

    runner.after = pushed
    return runner


@pytest.mark.parametrize(
    ("after_push", "said"),
    [
        pytest.param(None, None, id="the-commit"),
        pytest.param(
            NOT_FOUND,
            f"lists {TAG} at it, but GitHub's {PLUGIN_REPOSITORY} does not list",
            id="404",
        ),
        pytest.param(
            ANOTHER_ID,
            f"names {OTHER} under {TAG}: someone else published {TAG} at the same moment, or the "
            "push went elsewhere",
            id="another-id",
        ),
    ],
)
def test_the_pushed_tag_is_read_back_on_the_default_remote(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_push: Completed | None,
    said: str | None,
) -> None:
    # The default remote redirected to a bare repository, as in the case above, so ls-remote and
    # GitHub agree before the push; after it, GitHub's tag is read back through the API.
    # Mutations (declared): `mutations/`'s "the publisher does not read the pushed tag back" ->
    # the 404 and another id both report "pushed"; `mutations/`'s "the publisher takes a pushed
    # tag GitHub does not list for one elsewhere" -> the 404 is worded as a redirect;
    # `mutations/`'s "the publisher takes any pushed tag GitHub lists for its own" -> another id
    # reports "pushed"; `mutations/`'s "the publisher says a pushed tag went elsewhere without
    # naming a publish at the same moment" -> the likelier cause goes unsaid; `mutations/`'s "the
    # publisher says a pushed tag went elsewhere without naming the redirect" -> the refusal names
    # no cause to remove. After the 404, the tag is listed once by `ls-remote`, by both its exact
    # names: the listing names the pushed commit, so the push landed and GitHub has not listed the
    # tag yet. Mutation (declared): `mutations/`'s "the publisher lists the pushed tag by a
    # pattern" -> the listing is asked for the tag's tail, which another ref's name can end in.
    bare = bare_remote(tmp_path)
    _global_config(f'[url "{bare}"]\n\tinsteadOf = {publish_plugin.PLUGIN_REMOTE}\n')
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    runner = redirected_runner(source, bare, after_push)
    pin = pinned_at(source, TAG)
    default = publish_plugin.PLUGIN_REMOTE
    if said is None:
        done, _ = publish(source, default, tmp_path / "scratch", runner=runner)
        assert (done.outcome, done.commit, done.confirmed) == ("pushed", pin, True)
    else:
        with pytest.raises(Refusal) as refused:
            publish(source, default, tmp_path / "scratch", runner=runner)
        message = str(refused.value)
        assert said in message, message
        assert "run again" in message, message
        if after_push is ANOTHER_ID:
            assert "url.*.insteadOf" in message and "GIT_CONFIG_*" in message, message
            assert "url.*.pushInsteadOf or a remote.<url>.pushurl" in message, message
    # The push landed where the owner's git sent it, either way.
    assert refs(bare) == {"refs/heads/main": pin, f"refs/tags/{TAG}": pin}
    push = next(i for i, argv in enumerate(runner.calls) if argv[:1] == ["git"] and "push" in argv)
    after = [argv for argv in runner.calls[push + 1 :] if argv[:1] == ["gh"]]
    assert after == [TAG_API.split(" ")]
    listings = [argv for argv in runner.calls[push + 1 :] if "ls-remote" in argv]
    wanted = [f"refs/tags/{TAG}", f"refs/tags/{TAG}^{{}}"]
    tails = [argv[argv.index("ls-remote") + 1 :] for argv in listings]
    assert tails == ([["--end-of-options", default, *wanted]] if after_push is NOT_FOUND else [])


# A rewrite of the push alone: `url.*.pushInsteadOf`, or `remote.<url>.pushurl` for the URL the
# publisher is given, which git applies to that URL as to a configured remote's name (measured on
# git 2.54). `ls-remote` and the API read the repository GitHub stands for; the push goes to
# `elsewhere`.
PUSH_REWRITES = {
    "push-instead-of": '[url "{elsewhere}"]\n\tpushInsteadOf = {remote}\n',
    "pushurl": '[remote "{remote}"]\n\tpushurl = {elsewhere}\n',
}


@pytest.mark.parametrize("later", [False, True], ids=["the-first-release", "a-later-release"])
@pytest.mark.parametrize("rewrite", PUSH_REWRITES.values(), ids=PUSH_REWRITES)
def test_a_push_sent_elsewhere_is_refused_naming_the_rewrite(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rewrite: str, later: bool
) -> None:
    # Before the push, `ls-remote` and GitHub's API agree; after it, GitHub lists no tag and
    # neither does `ls-remote` of the repository it reads, for the first release and for one after
    # it: the push went elsewhere, and a run again would send it there again. Mutations
    # (declared): `mutations/`'s "the publisher reads a push that went elsewhere as one GitHub has
    # not listed yet" -> the refusal says to run again; "the publisher says every pushed tag
    # GitHub does not list went elsewhere" ->
    # `test_the_pushed_tag_is_read_back_on_the_default_remote[404]` reddens.
    github, elsewhere = bare_remote(tmp_path), tmp_path / "elsewhere.git"
    git(tmp_path, "init", "-q", "--bare", str(elsewhere))
    default = publish_plugin.PLUGIN_REMOTE
    _global_config(f'[url "{github}"]\n\tinsteadOf = {default}\n')
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    tag = TAG
    if later:
        publish(source, default, tmp_path / "first", runner=runner_for(source, github))
        tag = "v1.2.4"
        released(source, "1.2.4")
    _global_config(rewrite.format(elsewhere=elsewhere, remote=default))
    before = refs(github)
    with pytest.raises(Refusal) as refused:
        publish(source, default, tmp_path / "scratch", tag=tag, runner=runner_for(source, github))
    message = str(refused.value)
    neither = f"neither GitHub's {PLUGIN_REPOSITORY} nor git ls-remote {default} lists {tag} at it"
    assert f"{neither}: the push went elsewhere" in message, message
    assert "url.*.pushInsteadOf or a remote.<url>.pushurl" in message, message
    assert "Remove it and run again" in message, message
    pin = pinned_at(source, tag)
    assert refs(elsewhere) == {"refs/heads/main": pin, f"refs/tags/{tag}": pin}
    assert refs(github) == before


def test_a_push_rewritten_to_the_same_repository_is_published(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The common rewrite, `url."git@github.com:".pushInsteadOf = "https://github.com/"`, sends the
    # push for the https URL to the same repository by another URL; here `file://` for the path
    # the listing reads. Not refused: GitHub lists the tag the push wrote. No mutation of its own:
    # every refusal after a push needs GitHub not to list the commit pushed.
    github = bare_remote(tmp_path)
    url = publish_plugin.PLUGIN_URL
    _global_config(f'[url "{github}"]\n\tinsteadOf = {url}\n')
    _global_config(f'[url "file://{github}"]\n\tpushInsteadOf = {url}\n')
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    done, _ = publish(source, url, tmp_path / "scratch", runner=runner_for(source, github))
    pin = pinned_at(source, TAG)
    assert (done.outcome, done.commit, done.confirmed) == ("pushed", pin, True)
    assert refs(github) == {"refs/heads/main": pin, f"refs/tags/{TAG}": pin}


def test_another_remote_is_not_confirmed(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher confirms another remote through GitHub's
    # API" -> the plugin repository's API is asked about a remote it does not stand for.
    done, runner = publish(source, bare_remote(tmp_path), tmp_path / "scratch", yes=False)
    assert (done.outcome, done.confirmed) == ("would-push", False)
    assert plugin_api(runner) == []


@pytest.mark.parametrize("replaced", ["blob", "tree"])
def test_a_replace_ref_does_not_change_the_tag_s_code(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replaced: str
) -> None:
    # The commit `_source_anchor` held to GitHub's stays the same under a `refs/replace/` entry,
    # so the code read out of it must be that commit's own. Mutations (declared): `mutations/`'s
    # "the publisher lists the tag's code through a replace ref" -> the replaced `scripts` tree
    # names the planted script; "the publisher reads the tag's code through a replace ref" -> the
    # replaced blob is the planted script. Either way the planted script runs.
    marker = b"from __future__ import annotations\n"
    line = b'import os; open(os.environ["PUBLISH_TEST_PLANTED"], "w").write("ran")\n'
    planted = tmp_path / "planted.txt"
    monkeypatch.setenv("PUBLISH_TEST_PLANTED", str(planted))
    pin = pinned_at(source, TAG)
    write(source.parent, {"planted.py": (patched(marker, marker + line), "100755")})
    blob = git(source, "hash-object", "-w", str(source.parent / "planted.py")).strip()
    original = git(source, "rev-parse", f"{TAG}:scripts/plugin_tree.py").strip()
    if replaced == "blob":
        git(source, "replace", original, blob)
    else:
        scripts = git(source, "rev-parse", f"{TAG}:scripts").strip()
        listing = git(source, "ls-tree", scripts).replace(original, blob)
        tree = git_bytes(source, "mktree", stdin=listing.encode()).decode().strip()
        git(source, "replace", scripts, tree)
    # The premise: through the replacement, git reads the planted script at the tag.
    assert b"PUBLISH_TEST_PLANTED" in git_bytes(source, "show", f"{TAG}:scripts/plugin_tree.py")
    done, _ = publish(source, bare_remote(tmp_path), tmp_path / "scratch", yes=False)
    assert (done.outcome, done.commit) == ("would-push", pin)
    assert not planted.exists()


def test_a_tool_that_prints_no_json_object_is_refused(source: Path, tmp_path: Path) -> None:
    # A tag whose code fails before the CLI frame runs exits 1 with a traceback, which is not the
    # frame's `Failure`: refused, not rejected. Mutation (declared): `mutations/`'s "the publisher
    # reads a tool that printed no JSON object" -> the missing object escapes as an internal error.
    with_tool(source, b"import stayfixed.no_such_module\n")
    runner = runner_for(source)
    with pytest.raises(Refusal) as refused:
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", runner=runner)
    said = str(refused.value)
    assert "commit exited 1 and printed no JSON object" in said, said
    assert "no_such_module" in said, said
    assert gh_asked(runner, "gh", "attestation") == []


def test_a_tool_that_refuses_is_refused(source: Path, tmp_path: Path) -> None:
    # The tag's own `plugin_tree.py` refusing is exit 2 (Ruling 8: CI ran the same code green).
    # Mutation (declared): `mutations/`'s "the publisher reads a tool that refused as an answer"
    # -> the refusal's object is read as `commit`'s, and refused for its format instead.
    git(source, "rm", "-r", "-q", "skills")
    git(source, "commit", "-q", "--amend", "--no-edit")
    git(source, "tag", "-f", "-a", TAG, "-m", TAG)
    with pytest.raises(Refusal) as refused:
        publish(source, bare_remote(tmp_path), tmp_path / "scratch")
    said = str(refused.value)
    assert "commit exited 2" in said, said
    assert "skills is missing" in said, said


@pytest.mark.parametrize("gone", ["git-dir", "manifest"])
def test_a_read_back_that_cannot_be_made_is_refused(
    source: Path, tmp_path: Path, gone: str
) -> None:
    # Mutations (declared): `mutations/`'s "the publisher compares a read-back that failed" -> the
    # read-back's refusal is passed over and the run stops at a manifest that was never written;
    # "the publisher reads the manifests without catching a failed read" -> the missing manifest
    # escapes as an internal error.
    def remove(argv: list[str]) -> None:
        if tool_command(argv) == "commit":
            if gone == "git-dir":
                shutil.rmtree(argv[argv.index("--git-dir") + 1])
            else:
                Path(argv[argv.index("--manifest-file") + 1]).unlink()

    remote = bare_remote(tmp_path)
    with pytest.raises(Refusal) as refused:
        publish(source, remote, tmp_path / "scratch", runner=runner_for(source, after=remove))
    said = str(refused.value)
    wording = "could not read" if gone == "git-dir" else "cannot be read"
    assert wording in said, said
    assert refs(remote) == {}


def test_a_sha256_source_is_refused_before_anything_runs(tmp_path: Path) -> None:
    # The plugin repository is SHA-1, and a SHA-256 source commit is no id `--source-digest` or
    # GitHub names. Mutation (declared): `mutations/`'s "the publisher takes a tag commit that is
    # no SHA-1 id" -> the 64-character id is asked of GitHub.
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "--object-format=sha256", "-b", "dev")
    write(source, PLUGIN_FILES)
    commit(source)
    git(source, "tag", "-a", TAG, "-m", TAG)
    runner = runner_for(source)
    with pytest.raises(Refusal, match=f"no tag {TAG} names a commit"):
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", runner=runner)
    assert runner.calls == []


def test_a_tool_directory_already_there_is_refused(source: Path, tmp_path: Path) -> None:
    # The tag's code is written only into a directory this run made. Mutation (declared):
    # `mutations/`'s "the publisher writes the tag's code into a directory it did not make" -> the
    # existing directory is written into and the run goes through, refusing nothing.
    scratch = tmp_path / "scratch"
    (scratch / "tool").mkdir(parents=True)
    runner = runner_for(source)
    with pytest.raises(Refusal, match="cannot be made"):
        publish(source, bare_remote(tmp_path), scratch, runner=runner)
    assert tool_runs(runner) == []


@pytest.mark.parametrize("answer", ["an-exit", "not-a-blob", "cut-short"])
def test_a_cat_file_answer_that_is_not_the_tag_s_code_is_refused(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    # Mutations (declared): `mutations/`'s "the publisher reads the tag's code from a cat-file that
    # failed" -> an empty answer is refused as no blob instead; "the publisher reads the tag's code
    # from an answer that is no blob" -> the tree-typed answer is written and run; "the publisher
    # writes the tag's code from an answer cut short" -> the last file is written short.
    real = publish_plugin.git_run

    def answered(where: Path, *args: str, **options: Any) -> tuple[int, str]:
        code, said = real(where, *args, **options)
        if "--batch" not in args:
            return code, said
        if answer == "an-exit":
            return 128, ""
        if answer == "not-a-blob":
            return code, said.replace(" blob ", " tree ", 1)
        return code, said[:-50]

    monkeypatch.setattr(publish_plugin, "git_run", answered)
    runner = runner_for(source)
    wording = {
        "an-exit": "git cat-file --batch exited 128",
        "not-a-blob": "did not answer",
        "cut-short": "ended inside",
    }[answer]
    with pytest.raises(Refusal, match=wording):
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", runner=runner)
    assert tool_runs(runner) == []


ASKED_TAG = f"gh api --hostname github.com repos/{SOURCE_REPOSITORY}/git/ref/tags/{TAG}"


def _object(sha: str, kind: str) -> Completed:
    return Completed(0, json.dumps({"sha": sha, "object": {"sha": sha, "type": kind}}), "")


@pytest.mark.parametrize(
    ("answers", "said", "asked"),
    [
        pytest.param({ASKED_TAG: _object("b" * 40, "blob")}, "names a blob under", 1, id="a-blob"),
        pytest.param(
            {ASKED_TAG: _object("d" * 40, "tag")},
            f"names the tag object {'d' * 40}",
            2,
            id="a-missing-tag-object",
        ),
        pytest.param(
            {
                ASKED_TAG: _object("a" * 40, "tag"),
                f"gh api --hostname github.com repos/{SOURCE_REPOSITORY}/git/tags/{'a' * 40}": (
                    _object("a" * 40, "tag")
                ),
            },
            "through more than 8 tags",
            9,
            id="a-cycle",
        ),
    ],
)
def test_a_github_ref_that_peels_to_no_commit_is_refused(
    source: Path, tmp_path: Path, answers: dict[str, Completed], said: str, asked: int
) -> None:
    # Mutations (declared): `mutations/`'s "the publisher peels GitHub's ref through an object that
    # is no tag" -> the blob is asked for as a tag object, which GitHub does not hold;
    # "the publisher reads a tag object GitHub does not hold as no tag" -> the tag reads as absent;
    # "the publisher peels GitHub's tags past its bound" -> the cycle is asked about far more often.
    runner = runner_for(source, answers=answers)
    with pytest.raises(Refusal) as refused:
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", runner=runner)
    assert said in str(refused.value), str(refused.value)
    assert len(gh_asked(runner, "gh", "api")) == asked
    assert tool_runs(runner) == []


def test_an_unreachable_remote_is_refused(source: Path, tmp_path: Path) -> None:
    # Mutation (declared): `mutations/`'s "the publisher reads a remote it could not list as empty"
    # -> the absent remote reads as a first release's, and the dry run says it would push.
    absent = tmp_path / "absent.git"
    with pytest.raises(Refusal, match=f"git ls-remote {re.escape(str(absent))} exited 128"):
        publish(source, absent, tmp_path / "scratch", yes=False)


def test_a_fetch_that_fails_is_refused(source: Path, tmp_path: Path) -> None:
    # The listing names the parent as `main`, and the remote holds no `main` to fetch. Mutation
    # (declared): `mutations/`'s "the publisher goes on past a failed fetch" -> the failure is
    # reported as a `main` that moved.
    parent = pinned_at(source, TAG)
    released(source, "1.2.4")
    gh = runner_for(source).gh
    runner = _Listing(gh=gh, listing=f"{parent}\trefs/heads/main\n")
    with pytest.raises(Refusal, match="git fetch") as refused:
        publish(source, bare_remote(tmp_path), tmp_path / "scratch", tag="v1.2.4", runner=runner)
    assert "moved" not in str(refused.value)
    assert ran(runner, "push") == []


# --- The command line -----------------------------------------------------------------------------


def test_the_publisher_pushes_to_the_repository_the_marketplace_fetches_from() -> None:
    # Mutations (declared): `mutations/`'s "the publisher pushes to another repository than the
    # marketplace fetches from", "the publisher confirms through another repository than the
    # marketplace fetches from" and "the publisher asks GitHub about another plugin repository"
    # -> it no longer agrees with `scripts/release.py`'s `PLUGIN_URL` or `PLUGIN_REPOSITORY`,
    # which the marketplace entry is held to. Two spellings of one repository, one for the owner's
    # git to push over SSH and one for the harness to fetch over HTTPS; this keeps them one.
    remote = re.fullmatch(r"git@github\.com:([^/]+/[^/]+)\.git", publish_plugin.PLUGIN_REMOTE)
    url = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)\.git", release_script.PLUGIN_URL)
    assert remote is not None and url is not None
    assert remote.group(1) == url.group(1) == "stayfixed/stayfixed-plugin"
    assert publish_plugin.PLUGIN_URL == release_script.PLUGIN_URL
    assert publish_plugin.PLUGIN_REPOSITORY == release_script.PLUGIN_REPOSITORY
    assert release_script.PLUGIN_REPOSITORY == "stayfixed/stayfixed-plugin"


def test_the_cli_refuses_a_tag_that_is_not_a_plain_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No mutation: the refusal is the CLI frame's (`stayfixed.cli.run`), whose own tests hold how
    # a `Refusal` prints under `--json`, and the pattern's two entries redden
    # `test_a_tag_that_is_not_a_plain_version_is_refused`. What this holds is that the script's
    # `main` goes through that frame, and no one line of the script can stop it without also
    # breaking the dry-run case below.
    assert publish_plugin.main(["--tag", "v1.2", "--json"]) == 2
    out = capsys.readouterr().out
    assert '"error": "refused"' in out
    assert "plain version" in out


def test_the_cli_says_what_a_dry_run_would_push(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Mutations (declared): `mutations/`'s "the publisher says a remote it read only through
    # ls-remote is confirmed" -> the summary drops its last parenthesis; "the publisher pushes
    # without --yes" -> the dry run pushes, and says "pushed" rather than "would push".
    remote = bare_remote(tmp_path)
    monkeypatch.setattr(publish_plugin, "ROOT", source)
    monkeypatch.setattr(publish_plugin, "subprocess_runner", lambda: runner_for(source))
    assert publish_plugin.main(["--tag", TAG, "--remote", str(remote)]) == 0
    said = capsys.readouterr().out
    files = len(listed(source, TAG))
    pin = pinned_at(source, TAG)
    assert said.startswith(f"would push {files} files as tree "), said
    assert f", commit {pin}, to {remote}: main and {TAG}" in said
    assert "(not confirmed through GitHub's API)" in said
    assert said.endswith("; run again with --yes to push\n"), said
    assert refs(remote) == {}


def test_a_relative_remote_is_the_one_beside_the_owner_and_not_the_scratch_repository(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Mutation: `remote_argument` returning its argument unchanged -> git, run with `-C` in the
    # scratch repository, looks for `remote.git` there, and the listing is refused.
    remote = bare_remote(tmp_path)
    monkeypatch.setattr(publish_plugin, "ROOT", source)
    monkeypatch.setattr(publish_plugin, "subprocess_runner", lambda: runner_for(source))
    monkeypatch.chdir(tmp_path)
    assert publish_plugin.main(["--tag", TAG, "--remote", "remote.git"]) == 0
    said = capsys.readouterr().out
    assert f"to {remote.resolve()}: main and {TAG}" in said
    assert refs(remote) == {}


@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:stayfixed/stayfixed-plugin.git",
        "https://github.com/stayfixed/stayfixed-plugin.git",
        "file:///srv/plugin.git",
        "host:remote.git",
        "absent.git",
    ],
)
def test_a_url_an_scp_like_remote_or_an_absent_path_is_given_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: str
) -> None:
    # Mutation: the scp-like rule dropped -> `host:remote.git`, which exists here as a directory,
    # is made absolute, and git would read a local path where the owner named a host.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "host:remote.git").mkdir()
    assert publish_plugin.remote_argument(remote) == remote


# --- The exit classes: 1 rejects the release's approval, 2 says fix and run again ---------------

# What each case arranges, given the source, the bare remote and the test's `monkeypatch`: the
# runner the command is handed, the tag, and the remote it is given.
Arranged = tuple[Composite, str, str]


def _pins_another(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    repinned(source, "c" * 40)
    return runner_for(source), TAG, str(remote)


def _names_another_version(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    git(source, "tag", "v1.2.4")
    return runner_for(source), "v1.2.4", str(remote)


def _another_commit_under_the_tag(
    source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch
) -> Arranged:
    git(remote, "update-ref", f"refs/tags/{TAG}", remote_commit(remote, "another"))
    return runner_for(source), TAG, str(remote)


def _main_not_the_parent(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    git(remote, "update-ref", "refs/heads/main", remote_commit(remote, "some"))
    return runner_for(source), TAG, str(remote)


def _attestation_does_not_verify(
    source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch
) -> Arranged:
    answers = {"gh attestation verify": UNVERIFIED}
    return runner_for(source, answers=answers, attestation=ATTESTED), TAG, str(remote)


def _no_attestation_yet(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    answers = {"gh attestation verify": UNVERIFIED}
    return runner_for(source, answers=answers, attestation=NOT_FOUND), TAG, str(remote)


def _gh_too_old(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    answers = {"gh --version": Completed(0, "gh version 2.100.9 (2026-08-01)\n", "")}
    return runner_for(source, answers=answers), TAG, str(remote)


def _not_logged_in(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    answers = {"gh auth status": Completed(1, "", "You are not logged into any GitHub hosts.\n")}
    return runner_for(source, answers=answers), TAG, str(remote)


def _pushed_tag_not_listed(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    _global_config(f'[url "{remote}"]\n\tinsteadOf = {publish_plugin.PLUGIN_REMOTE}\n')
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    return redirected_runner(source, remote, NOT_FOUND), TAG, publish_plugin.PLUGIN_REMOTE


def _pushed_tag_listed_at_another_commit(
    source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch
) -> Arranged:
    """GitHub's API lists no tag after the push, and `ls-remote` lists it at another commit than
    the one pushed: moved there by someone else at once, or a push that went elsewhere."""
    runner, tag, given = _pushed_tag_not_listed(source, remote, monkeypatch)
    hidden = runner.after

    def moved(argv: list[str]) -> None:
        hidden(argv)
        if argv[:1] == ["git"] and "push" in argv:
            other = remote_commit(remote, "another commit under the tag")
            git(remote, "update-ref", f"refs/tags/{TAG}", other)

    runner.after = moved
    return runner, tag, given


def _pushed_elsewhere(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    elsewhere = remote.parent / "elsewhere.git"
    git(remote.parent, "init", "-q", "--bare", str(elsewhere))
    default = publish_plugin.PLUGIN_REMOTE
    _global_config(f'[url "{remote}"]\n\tinsteadOf = {default}\n')
    _global_config(f'[url "{elsewhere}"]\n\tpushInsteadOf = {default}\n')
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    return runner_for(source, remote), TAG, default


def _read_back_differs(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    def edit(argv: list[str]) -> None:
        if tool_command(argv) == "commit":
            manifest = Path(argv[argv.index("--manifest-file") + 1])
            manifest.write_bytes(manifest.read_bytes().replace(b"\n100644 ", b"\n100755 ", 1))

    return runner_for(source, after=edit), TAG, str(remote)


def _not_plain(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    return runner_for(source), "v1.2", str(remote)


def _not_github_s(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    return runner_for(source, answers={ASKED_TAG: NOT_FOUND}), TAG, str(remote)


def _predates(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    git(source, "rm", "-q", "scripts/plugin_tree.py")
    git(source, "commit", "-q", "--amend", "--no-edit")
    git(source, "tag", "-f", "-a", TAG, "-m", TAG)
    return runner_for(source), TAG, str(remote)


def _no_object_name(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    data = b'{"format": FORMAT, **asdict(found)}'
    with_tool(source, patched(data, data[:-1] + b', "commit": "+main"}'))
    return runner_for(source), TAG, str(remote)


def _another_format(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    old = b'FORMAT = "stayfixed-plugin-tree 1"'
    with_tool(source, patched(old, b'FORMAT = "stayfixed-plugin-tree 2"'))
    return runner_for(source), TAG, str(remote)


def _main_moves(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    publish(source, remote, source.parent / "first")
    released(source, "1.2.4")
    moved: list[str] = []

    def race(argv: list[str]) -> None:
        if argv[:1] == ["git"] and "ls-remote" in argv and not moved:
            moved.append(advance(remote))

    return runner_for(source, after=race), "v1.2.4", str(remote)


def _redirected(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    _global_config(f'[url "{remote}"]\n\tinsteadOf = {publish_plugin.PLUGIN_REMOTE}\n')
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    default = publish_plugin.PLUGIN_REMOTE
    publish(source, default, source.parent / "first", runner=runner_for(source, remote))
    tag_api = f"gh api --hostname github.com repos/{PLUGIN_REPOSITORY}/git/ref/tags/{TAG}"
    return runner_for(source, remote, answers={tag_api: NOT_FOUND}), TAG, default


def _push_refused(source: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> Arranged:
    hook = remote / "hooks" / "update"
    hook.write_text("#!/bin/sh\necho refused >&2\nexit 1\n")
    hook.chmod(0o755)
    return runner_for(source), TAG, str(remote)


@pytest.mark.parametrize(
    ("arrange", "code", "said"),
    [
        pytest.param(
            _pins_another,
            1,
            "does not pin the plugin commit its own tree makes",
            id="the-pin-is-another-commit",
        ),
        pytest.param(
            _names_another_version, 1, "plugin.json says 1.2.3", id="the-tag-names-another-version"
        ),
        pytest.param(
            _another_commit_under_the_tag,
            1,
            "a tag is not moved",
            id="another-commit-under-the-tag",
        ),
        pytest.param(
            _main_not_the_parent, 1, "moves only by fast-forward", id="main-is-not-the-parent"
        ),
        pytest.param(
            _attestation_does_not_verify,
            2,
            "does not verify on this machine",
            id="the-attestation-does-not-verify",
        ),
        pytest.param(
            _read_back_differs,
            1,
            "reads back as another tree",
            id="the-commit-reads-back-as-another-tree",
        ),
        pytest.param(_not_plain, 2, "plain version", id="a-tag-that-is-not-plain"),
        pytest.param(_gh_too_old, 2, "is older than 2.101.0", id="a-gh-older-than-measured"),
        pytest.param(_not_logged_in, 2, "gh auth status", id="a-gh-that-is-not-logged-in"),
        pytest.param(
            _no_attestation_yet,
            2,
            "no attestation of this manifest yet",
            id="no-attestation-of-the-manifest-yet",
        ),
        pytest.param(_not_github_s, 2, "is not GitHub's", id="a-local-tag-github-does-not-hold"),
        pytest.param(_predates, 2, "predates", id="a-tag-that-predates-the-publisher"),
        pytest.param(
            _no_object_name,
            2,
            "answered '+main' for commit",
            id="a-tool-answer-that-is-no-object-name",
        ),
        pytest.param(_another_format, 2, "in format", id="a-tool-answer-in-another-format"),
        pytest.param(
            _main_moves, 2, "main moved while this ran", id="main-moves-between-list-and-fetch"
        ),
        pytest.param(_redirected, 2, "through a redirect", id="a-redirected-default-remote"),
        pytest.param(_push_refused, 2, "git push to", id="a-refused-push"),
        pytest.param(
            _pushed_tag_not_listed, 2, "does not list", id="a-pushed-tag-github-does-not-list"
        ),
        pytest.param(_pushed_elsewhere, 2, "the push went elsewhere", id="a-push-sent-elsewhere"),
        # Not "does not list it yet": the listing names the tag, but at another commit. Mutation
        # (declared): `mutations/`'s "the publisher reads a pushed tag listed at another commit as
        # one GitHub has not listed yet".
        pytest.param(
            _pushed_tag_listed_at_another_commit,
            2,
            f"nor git ls-remote {publish_plugin.PLUGIN_REMOTE} lists {TAG} at it: the push went "
            "elsewhere",
            id="a-pushed-tag-listed-at-another-commit",
        ),
    ],
)
def test_every_rejection_exits_1_and_every_refusal_exits_2(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[Path, Path, pytest.MonkeyPatch], Arranged],
    code: int,
    said: str,
) -> None:
    # The classification's one home. Each row's summary names its own cause, so a row whose check
    # is dropped and that still exits as it should for another reason (the main-moves row, whose
    # push the remote refuses anyway under `--yes`) reddens here. Mutation: none of its own: each
    # row's entry reddens the row's own test above, and `Rejected` and `Refusal` are the frame's
    # exit 1 and 2.
    remote = bare_remote(tmp_path)
    runner, tag, given = arrange(source, remote, monkeypatch)
    monkeypatch.setattr(publish_plugin, "ROOT", source)
    monkeypatch.setattr(publish_plugin, "subprocess_runner", lambda: runner)
    argv = ["--tag", tag, "--remote", given, "--yes", "--json"]
    assert publish_plugin.main(argv) == code, capsys.readouterr()
    report = json.loads(capsys.readouterr().out)
    assert report["error"] == {1: "failed", 2: "refused"}[code], report
    assert said in report["summary"], report


def test_run_without_its_package_it_refuses_with_exit_2_and_says_to_use_uv(tmp_path: Path) -> None:
    # An owner who runs the publisher with a bare `python3` has no `stayfixed` to import, and the
    # traceback that ends such a run exits `1`, which `RELEASING.md` reads as "reject the
    # release's approval". The script says so itself, before the CLI frame exists, and exits `2`.
    # Mutations (declared): `mutations/`'s "the publisher exits 1 when its package cannot be
    # imported" and "the publisher refuses a missing package without saying to run it through
    # uv".
    done = without_stayfixed("publish_plugin.py", tmp_path, "--tag", TAG)
    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stdout == "", done.stdout
    assert "refused: No module named 'stayfixed'" in done.stderr, done.stderr
    assert "uv run python scripts/publish_plugin.py" in done.stderr, done.stderr
    assert "Traceback" not in done.stderr, done.stderr


def test_two_equal_manifests_have_no_first_difference() -> None:
    # Called only once the two manifests differ, so two equal ones are a caller's bug, raised
    # rather than worded as a difference in a rejection. Mutation (declared): `mutations/`'s "the
    # publisher words two equal manifests as a difference".
    manifest = b"stayfixed-plugin-tree 1\n100644 " + b"a" * 64 + b" README.md\n"
    with pytest.raises(AssertionError):
        publish_plugin._first_difference(manifest, manifest)
    assert publish_plugin._first_difference(manifest, manifest + b"x\n").startswith("line 3 is ")
