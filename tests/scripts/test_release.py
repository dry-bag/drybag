"""`scripts/release.py`: this repository's own release discipline, driven through `main(argv)`.

The commands used to be the installed CLI's `release` group, and they only ever checked the
drybag repository itself; the exit codes and the `--json` shapes are the ones that group had,
and these tests are what holds them. towncrier is a development dependency and is *invoked*,
never imported; the argv is the contract, and a stub records it.

Every message that tells the reader which command to run again is asserted against the command
written out, `uv run python scripts/release.py …`, and never through the script's own
`COMMAND`: read from the script, the expectation was the script's text compared with itself,
and a script telling its reader to run a command that no longer exists stayed green.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from drybag.errors import Failure, Refusal
from drybag.jsonobject import DEPTH_CAP, NESTED
from drybag.runner import NOT_FOUND, Completed, subprocess_runner
from tests.cli import subparsers
from tests.gitfixture import git, git_bytes, needs_git
from tests.plugintree import (
    NINE,
    PLUGIN_FILES,
    PLUGIN_URL,
    commit,
    hashed,
    literal,
    plugin_tree_id,
    write,
)
from tests.runners import Recorder
from tests.scriptload import release as _script
from tests.scriptload import without_drybag

release = _script()
ROOT = Path(__file__).resolve().parents[2]

# The fragment predicate reads the types towncrier itself is configured with, so a fixture
# repository has to declare them exactly as the real one does.
PYPROJECT = """[project]
name = "drybag"
version = "{v}"

[[tool.towncrier.type]]
directory = "feature"

[[tool.towncrier.type]]
directory = "fix"

[[tool.towncrier.type]]
directory = "change"
"""
INIT = '__version__ = "{v}"\n'
LOCK = '[[package]]\nname = "drybag"\nversion = "{v}"\nsource = {{ editable = "." }}\n'
# The plugin directory's count, written out rather than read from the script: the number is the
# page's ("Keep the plugin to 512 files or fewer"), and `tests/test_payload.py` reads the script's.
FILES_LIMIT = 512


def marketplace_at(version: str) -> dict[str, object]:
    """The marketplace a release commit carries: one `url` entry pinned to `v<version>`."""
    source = {"source": "url", "url": PLUGIN_URL, "ref": f"v{version}"}
    return {"name": "drybag", "plugins": [{"name": "drybag", "source": source}]}


def repo(
    tmp_path: Path,
    *,
    pyproject: str,
    init: str,
    claude: str,
    codex: str,
    changelog: str,
    lock: str | None = None,
    fragments: int = 0,
    marketplace: str | None = None,
) -> Path:
    (tmp_path / "src" / "drybag").mkdir(parents=True)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".codex-plugin").mkdir()
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "pyproject.toml").write_text(PYPROJECT.format(v=pyproject))
    (tmp_path / "uv.lock").write_text(LOCK.format(v=pyproject if lock is None else lock))
    (tmp_path / "src" / "drybag" / "__init__.py").write_text(INIT.format(v=init))
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "drybag", "version": claude})
    )
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(marketplace_at(pyproject if marketplace is None else marketplace))
    )
    (tmp_path / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "drybag", "version": codex})
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n<!-- towncrier release notes start -->\n\n"
        f"## {changelog} (2026-09-05)\n"
    )
    for index in range(fragments):
        (tmp_path / "changelog.d" / f"{index}.feature.md").write_text("x\n")
    return tmp_path


def test_all_equal_is_clean(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="0.1.0", init="0.1.0", claude="0.1.0", codex="0.1.0", changelog="0.1.0"
    )
    assert release.check(root) == []


def test_each_mismatch_is_named(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="0.1.0", init="0.1.0", claude="0.1.1", codex="0.1.0", changelog="0.1.0"
    )
    problems = release.check(root)
    assert len(problems) == 1
    assert ".claude-plugin/plugin.json" in problems[0]
    assert "0.1.1" in problems[0]


def test_pending_fragments_allow_the_changelog_to_lag(tmp_path: Path) -> None:
    root = repo(
        tmp_path,
        pyproject="0.2.0",
        init="0.2.0",
        claude="0.2.0",
        codex="0.2.0",
        changelog="0.1.0",
        fragments=1,
    )
    assert release.check(root) == []


def test_without_fragments_the_changelog_must_match(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="0.2.0", init="0.2.0", claude="0.2.0", codex="0.2.0", changelog="0.1.0"
    )
    assert any("CHANGELOG.md" in problem for problem in release.check(root))


def test_collect_reads_every_source_value(tmp_path: Path) -> None:
    root = repo(
        tmp_path,
        pyproject="1.0.0",
        init="1.0.1",
        claude="1.0.2",
        codex="1.0.3",
        changelog="1.0.4",
        lock="1.0.5",
        marketplace="1.0.6",
    )
    assert release.collect(root) == {
        "pyproject.toml": "1.0.0",
        "uv.lock": "1.0.5",
        "src/drybag/__init__.py": "1.0.1",
        ".claude-plugin/plugin.json": "1.0.2",
        ".codex-plugin/plugin.json": "1.0.3",
        "CHANGELOG.md": "1.0.4",
        ".claude-plugin/marketplace.json": "1.0.6",
    }


def test_a_missing_version_key_reads_as_none(tmp_path: Path) -> None:
    root = repo(
        tmp_path, pyproject="1.0.0", init="1.0.0", claude="1.0.0", codex="1.0.0", changelog="1.0.0"
    )
    (root / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "drybag"}))
    assert release.collect(root)[".codex-plugin/plugin.json"] is None


def test_the_cli_command_exits_one_on_version_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # CI runs the success path on every build, so exit 1 — the version check's only
    # user-facing surface — is reached by nothing else.
    root = repo(
        tmp_path, pyproject="0.1.0", init="0.2.0", claude="0.1.0", codex="0.1.0", changelog="0.1.0"
    )
    assert release.main(["check", "--root", str(root)]) == 1
    # stdout, and that is the change rather than an accident: these commands used to report a
    # finding by raising `Failure`, which the frame prints to stderr under a `drybag: failed:`
    # prefix and which drops `Result.data`. Every drybag command returns its findings.
    assert "version drift" in capsys.readouterr().out


def test_the_json_object_has_the_same_shape_whether_or_not_there_is_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The whole of why these commands stopped raising. A `Failure` becomes
    # `{"error": "failed", "summary": "failed: ..."}` and `Result.data` never reaches the
    # output — so a consumer that read `versions` on a clean run had nothing to read on the run
    # it cared about, and the machine-readable shape flipped on exactly the condition being
    # tested for. Asserted as the key sets being equal AND as the drifted run carrying the
    # data: "both objects are empty" would satisfy the first on its own.
    #
    # Mutation (declared): the drift arm returns `{}` for its data, which is what raising
    # produced -> the key sets differ and this reddens naming them.
    clean = repo(
        tmp_path / "a",
        pyproject="0.1.0",
        init="0.1.0",
        claude="0.1.0",
        codex="0.1.0",
        changelog="0.1.0",
    )
    drifted = repo(
        tmp_path / "b",
        pyproject="0.1.0",
        init="0.2.0",
        claude="0.1.0",
        codex="0.1.0",
        changelog="0.1.0",
    )
    assert release.main(["check", "--root", str(clean), "--json"]) == 0
    on_success = json.loads(capsys.readouterr().out)
    assert release.main(["check", "--root", str(drifted), "--json"]) == 1
    on_drift = json.loads(capsys.readouterr().out)

    assert set(on_success) == set(on_drift) == {"summary", "problems", "versions"}
    assert on_success["problems"] == []
    assert on_drift["problems"] == [
        "src/drybag/__init__.py says '0.2.0'; pyproject.toml says '0.1.0'"
    ]
    assert on_drift["versions"]["src/drybag/__init__.py"] == "0.2.0"


def test_the_cli_command_reports_the_agreed_version_on_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        tmp_path, pyproject="0.1.0", init="0.1.0", claude="0.1.0", codex="0.1.0", changelog="0.1.0"
    )
    argv = ["check", "--root", str(root), "--json"]
    assert release.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["versions"]["pyproject.toml"] == "0.1.0"


def _repo(
    tmp_path: Path,
    *,
    pyproject: str = "0.1.0",
    init: str = "0.1.0",
    claude: str = "0.1.0",
    codex: str = "0.1.0",
    changelog: str = "0.1.0",
    lock: str | None = None,
    marketplace: str | None = None,
) -> Path:
    """`repo` with every version agreeing unless a test disagrees with one on purpose."""
    return repo(
        tmp_path,
        pyproject=pyproject,
        init=init,
        claude=claude,
        codex=codex,
        changelog=changelog,
        lock=lock,
        marketplace=marketplace,
    )


# --- The marketplace entry: the plugin repository, pinned to the release's tag and commit -------


def test_the_marketplace_ref_is_a_version_source(tmp_path: Path) -> None:
    # The release commit names the tag it releases in the plugin repository, so the entry's `ref`
    # is held to the version like any other source. Mutation (declared): the marketplace left out
    # of the sources -> a ref one release ahead passes and this reddens.
    root = _repo(tmp_path, marketplace="0.1.1")
    assert release.check(root) == [
        ".claude-plugin/marketplace.json says '0.1.1'; pyproject.toml says '0.1.0'"
    ]


def _with_entry(tmp_path: Path, *entries: dict[str, object]) -> Path:
    root = _repo(tmp_path)
    document = {"name": "drybag", "plugins": list(entries)}
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(document))
    return root


# The entry's own refusal, written out, for every source that is not the plugin repository's.
NOT_FETCHED = (
    ".claude-plugin/marketplace.json entry 'drybag' does not fetch the plugin from "
    f"{PLUGIN_URL}; the plugin is published from dry-bag/drybag-plugin, as a url source "
    "pinned to the release's tag by ref and to the plugin commit by sha"
)


def test_a_path_source_is_refused_as_the_plugin_folder_it_used_to_be(tmp_path: Path) -> None:
    # `./` was the repository root, which is more than the plugin. Said once, by the entry's rule,
    # and not again as a version the marketplace lacks. Mutation (declared): the drift loop stops
    # passing over a marketplace that pins no tag -> a second problem and this reddens.
    root = _with_entry(tmp_path, {"name": "drybag", "source": "./"})
    assert release.check(root) == [NOT_FETCHED]


def _url(**extra: object) -> dict[str, object]:
    return {"source": "url", "url": PLUGIN_URL, "ref": "v0.1.0", **extra}


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        pytest.param(
            {
                "name": "drybag",
                "source": _url(url="https://github.com/dry-bag/drybag.git"),
            },
            NOT_FETCHED,
            id="another-url",
        ),
        pytest.param(
            {
                "name": "drybag",
                "source": {"source": "github", "repo": "dry-bag/drybag-plugin"},
            },
            NOT_FETCHED,
            id="a-github-source",
        ),
        pytest.param(
            {"name": "drybag", "source": {"source": "url", "url": PLUGIN_URL}},
            ".claude-plugin/marketplace.json entry 'drybag' pins ref None, which is no "
            "release tag vX.Y.Z",
            id="no-ref",
        ),
        pytest.param(
            {"name": "drybag", "source": _url(ref="main")},
            ".claude-plugin/marketplace.json entry 'drybag' pins ref main, which is no "
            "release tag vX.Y.Z",
            id="a-branch-ref",
        ),
        pytest.param(
            {"name": "drybag", "source": _url(ref="v0.1.0-rc1")},
            ".claude-plugin/marketplace.json entry 'drybag' pins ref v0.1.0-rc1, which is "
            "no release tag vX.Y.Z",
            id="a-suffixed-ref",
        ),
        pytest.param(
            {"name": "drybag", "source": _url(ref="v0.1.\u0660")},
            ".claude-plugin/marketplace.json entry 'drybag' pins ref 'v0.1.\u0660', which is "
            "no release tag vX.Y.Z",
            id="a-non-ascii-digit",
        ),
        pytest.param(
            {"name": "drybag", "source": _url(), "version": "0.1.0"},
            ".claude-plugin/marketplace.json entry 'drybag' carries a version; plugin.json "
            "is the only source",
            id="a-version-on-the-entry",
        ),
    ],
)
def test_an_entry_naming_another_repository_or_no_ref_is_refused(
    tmp_path: Path, entry: dict[str, object], problem: str
) -> None:
    # Each case is one problem and that one. Mutations (declared): any `url` accepted ->
    # `another-url` reddens; the ref's shape unasked -> `no-ref` and `a-branch-ref` redden; the
    # shape matched at the start only -> `a-suffixed-ref` reddens; `\d` for the shape's digits ->
    # `a-non-ascii-digit` passes the shape and is reported as version drift instead, and reddens; a
    # `version` on the entry let through -> `a-version-on-the-entry` reddens. Mutation (declared):
    # `mutations/`'s "release check prints a marketplace string as its repr" -> `a-branch-ref`
    # says `'main'`.
    assert release.check(_with_entry(tmp_path, entry)) == [problem]


def test_a_sha_beside_the_ref_is_accepted(tmp_path: Path) -> None:
    # The release commit pins the plugin commit by `sha` beside the tag's `ref`, and `dev` pins
    # none until the first release with one. Mutation (declared): `mutations/`'s "release check
    # refuses every sha beside the ref" -> this reddens.
    assert release.check(_with_entry(tmp_path, {"name": "drybag", "source": _url()})) == []
    pinned: dict[str, object] = {
        "name": "drybag",
        "source": _url(sha="0123456789abcdef" * 2 + "01234567"),
    }
    assert release.check(_with_entry(tmp_path / "pinned", pinned)) == []


@pytest.mark.parametrize(
    ("sha", "shown"),
    [
        pytest.param("C" * 40, "C" * 40, id="upper-case"),
        pytest.param("c" * 39, "c" * 39, id="39-characters"),
        pytest.param("", "''", id="empty"),
        pytest.param(1, "1", id="a-number"),
    ],
)
def test_a_sha_that_is_not_a_commit_id_is_refused(tmp_path: Path, sha: object, shown: str) -> None:
    # A plugin commit's id is 40 lowercase hex characters: the plugin repository is SHA-1, and git
    # prints its ids in lower case. Mutations (declared): `mutations/`'s "release check accepts a
    # sha in upper case" -> `upper-case` reddens; "release check accepts any sha" -> every case
    # reddens.
    root = _with_entry(tmp_path, {"name": "drybag", "source": _url(sha=sha)})
    assert release.check(root) == [
        f".claude-plugin/marketplace.json entry 'drybag' pins sha {shown}, which is no commit id"
    ]


# What a repository may hand a finding: a line break that a CI runner reads a workflow command
# after, and a length no reader needs. Printed through `clipped`: its `repr`'s first 120
# characters, and the length.
HOSTILE = "v1\n::error::" + "x" * 200
CLIPPED = repr(HOSTILE[:120]) + f"\N{HORIZONTAL ELLIPSIS}({len(HOSTILE)} chars)"
# One line of what a program wrote to stderr, which is read line by line: an escape sequence that
# drives a terminal, and the length.
ESCAPED = "\x1b[2J" + "y" * 200
ESCAPED_CLIPPED = repr(ESCAPED[:120]) + f"\N{HORIZONTAL ELLIPSIS}({len(ESCAPED)} chars)"


def test_a_marketplace_value_is_printed_escaped_and_clipped(tmp_path: Path) -> None:
    # Mutations (declared): `mutations/`'s "release check prints the marketplace's ref as it is"
    # and "release check prints the marketplace's sha as it is" -> the line break and all 211
    # characters reach the finding.
    root = _with_entry(tmp_path, {"name": "drybag", "source": _url(ref=HOSTILE, sha=HOSTILE)})
    said = ".claude-plugin/marketplace.json entry 'drybag' pins"
    assert release.check(root) == [
        f"{said} ref {CLIPPED}, which is no release tag vX.Y.Z",
        f"{said} sha {CLIPPED}, which is no commit id",
    ]


@pytest.mark.parametrize("named", [0, 2], ids=["none", "two"])
def test_a_marketplace_without_the_plugin_entry_is_named(tmp_path: Path, named: int) -> None:
    # Mutation (declared): the first of several entries taken for the one -> `two` reddens.
    # Mutation (declared): a marketplace with no one entry passes -> both cases redden.
    entries: list[dict[str, object]] = [{"name": "drybag", "source": _url()}] * named
    root = _with_entry(tmp_path, {"name": "another", "source": _url()}, *entries)
    assert release.check(root) == [
        f".claude-plugin/marketplace.json has {named} entries named 'drybag'; it must have "
        f"exactly one, fetching the plugin from {PLUGIN_URL}"
    ]


@pytest.mark.parametrize(
    ("entry", "pending"),
    [
        ("x.feature.md", True),
        ("0.fix.md", True),
        ("a.b.change.md", True),
        (".gitkeep", False),
        (".DS_Store", False),
        ("notes.md", False),
        ("x.bogus.md", False),
        ("feature.md", False),
        ("x.feature.rst", False),
    ],
)
def test_only_a_towncrier_fragment_lets_the_changelog_lag(
    tmp_path: Path, entry: str, pending: bool
) -> None:
    # A stray .DS_Store — which Finder writes just by opening changelog.d — used to count as a
    # pending fragment and turn a genuine drift from exit 1 into exit 0.
    root = _repo(tmp_path, pyproject="0.2.0", init="0.2.0", claude="0.2.0", codex="0.2.0")
    (root / "changelog.d" / entry).write_text("x\n")
    assert release.pending_fragments(root) is pending
    assert (release.check(root) == []) is pending


def test_a_stray_file_beside_a_real_fragment_does_not_hide_it(tmp_path: Path) -> None:
    root = _repo(tmp_path, pyproject="0.2.0", init="0.2.0", claude="0.2.0", codex="0.2.0")
    (root / "changelog.d" / ".DS_Store").write_text("x\n")
    (root / "changelog.d" / "foundation.feature.md").write_text("x\n")
    assert release.pending_fragments(root) is True


def test_the_fragment_types_come_from_the_configuration_not_from_code(tmp_path: Path) -> None:
    # Hardcoding "feature", "fix", "change" here would drift from the [[tool.towncrier.type]]
    # blocks towncrier itself reads.
    root = _repo(tmp_path, pyproject="0.2.0", init="0.2.0", claude="0.2.0", codex="0.2.0")
    (root / "changelog.d" / "x.removal.md").write_text("x\n")
    assert release.pending_fragments(root) is False
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text() + '\n[[tool.towncrier.type]]\ndirectory = "removal"\n'
    )
    assert release.pending_fragments(root) is True


def test_a_disagreeing_lockfile_is_reported_by_name(tmp_path: Path) -> None:
    # `uv sync --locked` reds the install step on a stale lockfile with a dependency-shaped
    # message, ahead of the gate built to catch exactly this.
    root = _repo(tmp_path, lock="0.0.9")
    problems = release.check(root)
    assert len(problems) == 1
    assert "uv.lock says '0.0.9'" in problems[0]


def test_a_missing_lockfile_reads_as_none_and_is_reported_as_drift(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "uv.lock").unlink()
    assert release.collect(root)["uv.lock"] is None
    assert any("uv.lock says None" in problem for problem in release.check(root))


def test_a_lockfile_that_names_no_drybag_package_reads_as_none(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "uv.lock").write_text('[[package]]\nname = "pytest"\nversion = "8.0.0"\n')
    assert release.collect(root)["uv.lock"] is None


def test_the_four_root_conditions_get_four_different_messages(tmp_path: Path) -> None:
    # One shared message told a user who typoed --root, or ran the command in their own
    # project (--root defaults to "."), that their pyproject.toml lacked a version key. The
    # file case then inherited the missing-path message, so `--root ./pyproject.toml` was told
    # a file it had just been handed does not exist — the gate asserting something untrue
    # about the user's tree, which is the very thing these messages exist to stop.
    missing = tmp_path / "nope"
    not_a_directory = tmp_path / "pyproject.toml"
    not_a_directory.write_text('[project]\nname = "drybag"\nversion = "0.1.0"\n')
    empty = tmp_path / "empty"
    empty.mkdir()
    no_version = tmp_path / "no-version"
    no_version.mkdir()
    (no_version / "pyproject.toml").write_text('[project]\nname = "drybag"\n')

    absent = release.check(missing)
    a_file = release.check(not_a_directory)
    unrelated = release.check(empty)
    versionless = release.check(no_version)
    assert absent == [f"{missing} does not exist; --root must name a repository root"]
    assert a_file == [f"{not_a_directory} is not a directory; --root must name a repository root"]
    assert unrelated == [f"{empty} has no pyproject.toml; --root must name a repository root"]
    assert versionless == ["pyproject.toml has no [project].version"]
    assert len({tuple(absent), tuple(a_file), tuple(unrelated), tuple(versionless)}) == 4


def test_a_root_the_check_cannot_read_is_said_without_a_label_it_is_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A `--root` that is no repository root is no version disagreeing, and printed under "version
    # drift:" it read as one. Said alone, exit 1 as before. Mutation: `mutations/`'s "a root the
    # release check cannot read is reported as version drift".
    missing = tmp_path / "nope"
    assert release.main(["check", "--root", str(missing)]) == 1
    assert capsys.readouterr().out == (
        f"{missing} does not exist; --root must name a repository root\n"
    )


@pytest.mark.parametrize(
    ("name", "body", "kind"),
    [
        ("pyproject.toml", "not = = toml", "TOML"),
        ("uv.lock", "not = = toml", "TOML"),
        (".claude-plugin/plugin.json", "{not json", "JSON"),
        (".codex-plugin/plugin.json", "{not json", "JSON"),
    ],
)
def test_a_malformed_source_is_reported_with_its_filename(
    tmp_path: Path, name: str, body: str, kind: str
) -> None:
    # `_read` knows the filename and used to let the decoder's own error escape without it.
    root = _repo(tmp_path)
    (root / name).write_text(body)
    with pytest.raises(release.MalformedSource) as raised:
        release.check(root)
    assert name in str(raised.value)
    assert kind in str(raised.value)


@pytest.mark.parametrize("name", [".claude-plugin/plugin.json", ".codex-plugin/plugin.json"])
def test_a_manifest_nested_past_the_reader_is_refused_alike_on_every_platform(
    tmp_path: Path, name: str
) -> None:
    # `json` answers nesting past its depth with `RecursionError`, not `JSONDecodeError`, and the
    # arm that caught it was the TOML one: a deep `plugin.json` was "not valid TOML". Where that
    # depth is, is the interpreter's and the platform's: 3.11 to 3.13 stop short of
    # `jsonobject.DEPTH_CAP`, and 3.14 follows as deep as the C stack allows, past 100,000 levels on
    # Linux and not on macOS, so a case that asserted `json` raised at a fixed depth passed on one
    # and not the other. One level past the cap is refused by the product's own reader on all of
    # them, in the same words. Mutation (oracle): `mutations/`'s "release check reads a JSON source
    # past the shared reader".
    root = _repo(tmp_path)
    nested = "[" * DEPTH_CAP + "]" * DEPTH_CAP
    (root / name).write_text('{"version": ' + nested + "}")
    with pytest.raises(release.MalformedSource) as raised:
        release.check(root)
    assert str(raised.value) == f"{name} {NESTED}"


@pytest.mark.parametrize(
    "body",
    ['package = "not-a-list"\n', "package = [1, 2]\n"],
    ids=["not-a-list", "entries-not-tables"],
)
def test_a_wrongly_shaped_lockfile_is_reported_by_name(tmp_path: Path, body: str) -> None:
    # Valid TOML of the wrong shape decodes cleanly, so `_read`'s two decoder catches never see
    # it: iterating a string yields characters and `entry.get` raised AttributeError straight
    # past them, reaching the caller as an unlabelled internal error naming no file.
    root = _repo(tmp_path)
    (root / "uv.lock").write_text(body)
    with pytest.raises(release.MalformedSource) as raised:
        release.check(root)
    assert "uv.lock" in str(raised.value)


@pytest.mark.parametrize(
    ("name", "body", "shape"),
    [
        (".claude-plugin/plugin.json", "[]", "is not a JSON object"),
        (".codex-plugin/plugin.json", '"0.1.0"', "is not a JSON object"),
        ("pyproject.toml", 'project = "x"\n', "its project is not a table"),
        (".claude-plugin/marketplace.json", "[]", "is not a JSON object"),
        (".claude-plugin/marketplace.json", '{"plugins": ["version"]}', "not a list of objects"),
        (".claude-plugin/marketplace.json", '{"plugins": "x"}', "not a list of objects"),
        (".claude-plugin/marketplace.json", "{not json", "is not valid JSON"),
    ],
    ids=[
        "claude-manifest-list",
        "codex-manifest-string",
        "project-not-a-table",
        "marketplace-list",
        "marketplace-entry-string",
        "marketplace-plugins-string",
        "marketplace-not-json",
    ],
)
def test_a_version_source_of_the_wrong_shape_is_reported_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, body: str, shape: str
) -> None:
    # The lockfile's class, in every other source: valid JSON or TOML of the wrong shape decodes
    # cleanly and a `.get` on a list or a string raised AttributeError past the decoder's
    # catches, an internal error (exit 2) naming no file. A marketplace entry that is a string
    # was read with `in`, a substring test, and `{"plugins": "x"}` was a list of characters that
    # passed in silence. Mutations (oracle): `mutations/`'s "release check reads a JSON source past
    # the shared reader" and "the marketplace reads a plugins value that is not a list of objects".
    root = _repo(tmp_path)
    (root / name).write_text(body)
    with pytest.raises(release.MalformedSource) as raised:
        release.check(root)
    assert str(raised.value).startswith(name) and shape in str(raised.value), raised.value
    assert release.main(["check", "--root", str(root)]) == 1
    assert name in capsys.readouterr().err


def test_the_cli_command_exits_one_on_a_malformed_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `MalformedSource` derives from `Failure` on purpose: a source the gate cannot parse is a
    # finding, not a refusal. Nothing observed that through `run` — the unit tests catch the
    # class, which is base-class agnostic — so reverting it to `Refusal`, and exit 2 with it,
    # left every test green.
    root = _repo(tmp_path)
    (root / "uv.lock").write_text("not = = toml")
    assert release.main(["check", "--root", str(root)]) == 1
    assert "uv.lock is not valid TOML" in capsys.readouterr().err


def _at(tmp_path: Path, version: str) -> Path:
    """The module's `_repo` with every source at one version.

    There is no `_repository(tmp_path, version=…)` fixture in this module; `_repo` is the one
    that exists and it takes a keyword per source, so the two tests below say the version once
    through here rather than five times each.
    """
    return _repo(
        tmp_path,
        pyproject=version,
        init=version,
        claude=version,
        codex=version,
        changelog=version,
    )


# A file under each of the plugin's nine paths (`tests/plugintree.py`'s `NINE`) that `repo` does
# not already write: the two manifests and `src/drybag/__init__.py` are version sources it
# writes.
BESIDE_THE_SOURCES = {
    path: PLUGIN_FILES[path]
    for path in (
        ".claude-plugin/icon.png",
        "hooks/hooks.json",
        "scripts/drybag",
        "README.md",
        "LICENSE",
    )
}
# How many of the plugin tree's files `_with_plugin_paths` writes outside `skills/`: the three
# sources under the plugin's paths and the five files above.
OUTSIDE_SKILLS = 3 + len(BESIDE_THE_SOURCES)


def _with_plugin_paths(root: Path, *, skills: int = 1, pin: bool = True) -> Path:
    """`root` as a git checkout whose `HEAD` holds a file under each of the plugin's nine paths,
    `skills` of them under `skills/`, and everything else `root` holds; under `pin`, a commit on
    top whose marketplace pins the plugin commit its tree makes.

    `check --tag` computes the plugin commit at `HEAD`, which `scripts/plugin_tree.py` refuses to
    make without each of its paths, and compares the marketplace's pin with it, so a tag test that
    expects nothing wrong builds on this.
    """
    write(root, BESIDE_THE_SOURCES)
    write(root, {f"skills/s{index}/SKILL.md": (b"x\n", "100644") for index in range(skills)})
    assert all((root / path).exists() for path in NINE)
    if not (root / ".git").exists():
        git(root, "init", "-q", "-b", "main")
    commit(root, "tree")
    if pin:
        _pinning(root, _plugin_commit_of(root))
    return root


def _plugin_commit_of(root: Path, parent: str | None = None) -> str:
    """The plugin commit of `root`'s `HEAD` whose parent is `parent`: computed by git, over the
    tree of the nine paths and the commit's text spelled out, never by the script."""
    version = json.loads((root / ".claude-plugin" / "plugin.json").read_text())["version"]
    return hashed(root, literal(plugin_tree_id(root), parent, version))


def _pinning(root: Path, sha: str | None, message: str = "pin") -> str:
    """A commit on `root`'s `HEAD` whose marketplace entry pins `sha` beside its `ref`, or no
    `sha` when it is `None`."""
    path = root / ".claude-plugin" / "marketplace.json"
    document = json.loads(path.read_text())
    source = document["plugins"][0]["source"]
    source.pop("sha", None)
    if sha is not None:
        source["sha"] = sha
    path.write_text(json.dumps(document))
    return commit(root, message)


def _beside_the_plugin(root: Path, files: int) -> Path:
    """`root` with `files` one-line files under `docs/`, which is no part of the plugin."""
    (root / "docs").mkdir()
    for index in range(files):
        (root / "docs" / f"{index}.md").write_text("x\n", encoding="utf-8")
    return root


def _over(count: int) -> str:
    """The count's refusal, written out."""
    return (
        f"the plugin tree (scripts/plugin_tree.py) holds {count} files, over the {FILES_LIMIT} "
        "the plugin directory lists unheld"
    )


@needs_git
def test_a_tag_that_names_another_version_is_drift(tmp_path: Path) -> None:
    # The release workflow used to compare the tag to the package in shell; the gate that
    # exists to say "one version everywhere" now holds the tag against its seven sources. Both
    # tag shapes are accepted — `vX.Y.Z` (the workflow's trigger) and the platform's
    # `drybag--vX.Y.Z` — because either may be the one the run was created from.
    # Mutation (declared): accept any tag -> the first assertion reddens.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"))
    assert release.check(root, tag="v1.2.4") == [
        "tag v1.2.4 is neither v1.2.3 nor drybag--v1.2.3; pyproject.toml says '1.2.3'"
    ]
    assert release.check(root, tag="v1.2.3") == []
    assert release.check(root, tag="drybag--v1.2.3") == []


@needs_git
def test_the_drift_message_says_what_was_checked_rather_than_inventing_a_version(
    tmp_path: Path,
) -> None:
    # The message used to be derived with `tag.split("v", 1)[-1]` — a split on the first `v`
    # anywhere in the string, not a parse — so it named a version the tag does not carry.
    # Measured on this repository before the fix:
    #
    #   --tag 0.1.0          -> tag 0.1.0 names 0.1.0; pyproject.toml says '0.1.0'
    #   --tag drybag-v0.1.0 -> tag drybag-v0.1.0 names 0.1.0; …says '0.1.0'
    #   --tag dev-v0.1.0     -> tag dev-v0.1.0 names -v0.1.0; …says '0.1.0'
    #
    # The first asserts that two identical strings disagree, which is the failure the comment
    # above `check` was written to end. Both of the first two are the slips `RELEASING.md`
    # invites: a human types this flag by hand right after a tool prints `drybag--vX.Y.Z`.
    # The tags the older case exercised (`v1.2.4`, `v9.9.9`) all begin with `v` and carry no
    # earlier one, so the split happened to be right and the tests passed for that reason.
    #
    # Mutation (declared): the derived `named` comes back -> all three assertions redden.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"))
    # A bare version, which is the tag `git tag 1.2.3` makes and the one that read as agreeing
    # with itself.
    assert release.check(root, tag="1.2.3") == [
        "tag 1.2.3 is neither v1.2.3 nor drybag--v1.2.3; pyproject.toml says '1.2.3'"
    ]
    # One hyphen short of the platform's own tag.
    assert release.check(root, tag="drybag-v1.2.3") == [
        "tag drybag-v1.2.3 is neither v1.2.3 nor drybag--v1.2.3; pyproject.toml says '1.2.3'"
    ]
    # And a prefix carrying an earlier `v`, where the split produced `-v1.2.3` — a string that
    # is not a version at all.
    assert release.check(root, tag="dev-v1.2.3") == [
        "tag dev-v1.2.3 is neither v1.2.3 nor drybag--v1.2.3; pyproject.toml says '1.2.3'"
    ]


@needs_git
def test_a_tag_with_pending_fragments_is_refused(tmp_path: Path) -> None:
    # Without `--tag`, pending fragments let CHANGELOG.md lag, because a change's fragment is
    # written before the release assembles it. AT a tag there is nothing left to assemble:
    # a fragment still pending means the changelog the users read is not the one the tag
    # claims. Mutation (declared): skip the fragment check under `tag` -> reddens.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"))
    (root / "changelog.d" / "late.feature.md").write_text("late\n", encoding="utf-8")
    assert release.check(root) == []
    problems = release.check(root, tag="v1.2.3")
    assert problems == [
        "changelog.d still holds 1 fragment(s); run "
        "`uv run python scripts/release.py notes --version 1.2.3` before tagging"
    ]


@needs_git
def test_a_tag_refuses_a_plugin_tree_over_the_directory_count(tmp_path: Path) -> None:
    # The plugin directory holds a plugin past 512 files for a reviewer. The tree is the plugin's
    # paths and nothing else: the 600 files under `docs/` are not in it. Plain `check` does not
    # count; `tests/test_payload.py` holds the same count on every pull request. Mutation
    # (declared): the count never refuses -> the first assertion reddens.
    root = _beside_the_plugin(_at(tmp_path, "1.2.3"), 600)
    _with_plugin_paths(root, skills=FILES_LIMIT + 1 - OUTSIDE_SKILLS)
    assert release.check(root, tag="v1.2.3") == [_over(FILES_LIMIT + 1)]
    assert release.check(root) == []


@needs_git
def test_a_tag_passes_a_plugin_tree_at_the_count(tmp_path: Path) -> None:
    # 512 files is inside the limit, beside 600 that are no part of the plugin, and the count is
    # `HEAD`'s, as the directory reads a commit: a file only staged under `skills/` and one only on
    # disk are not in it. Mutations (declared): `>` becomes `>=` -> this reddens; the whole
    # repository counted -> the 600 count and this reddens; the listing read from the index -> the
    # staged file counts and this reddens.
    root = _beside_the_plugin(_at(tmp_path, "1.2.3"), 600)
    _with_plugin_paths(root, skills=FILES_LIMIT - OUTSIDE_SKILLS)
    (root / "skills" / "staged").mkdir()
    (root / "skills" / "staged" / "SKILL.md").write_text("x\n", encoding="utf-8")
    git(root, "add", "skills/staged/SKILL.md")
    (root / "skills" / "loose.md").write_text("x\n", encoding="utf-8")
    assert release.check(root, tag="v1.2.3") == []


@needs_git
def test_a_tag_whose_plugin_tree_cannot_be_read_is_a_count_finding(tmp_path: Path) -> None:
    # `scripts/plugin_tree.py` refuses a symlink among the plugin's files, and that refusal is one
    # count problem quoting it: returned, never raised, so `--json` keeps its object. Mutation
    # (declared): a tree that could not be counted read as nought files -> no problem and this
    # reddens. Mutation (declared): `mutations/`'s "release reads no summary from the plugin tree
    # script" -> the refusal's sentence is lost, and the problem says only how it exited.
    # Mutation (declared): the count asked without `--tag` too -> the last assertion reddens.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"))
    os.symlink("../README.md", root / "skills" / "link")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "a symlink")
    kinds, _ = release.checked_by_kind(root, tag="v1.2.3")
    (problem,) = kinds["plugin tree count"]
    assert problem.startswith("the plugin tree could not be read: "), problem
    assert "skills/link" in problem and "120000" in problem, problem
    assert [p for kind, found in kinds.items() if kind != "plugin tree count" for p in found] == []
    assert release.check(root) == []


def test_a_tag_outside_a_git_checkout_is_refused_for_want_of_a_count(tmp_path: Path) -> None:
    # A release gate that cannot count does not pass: release.yml runs it in the checkout the tag
    # names, and anywhere else there is no committed tree to read. Mutation (declared): a tree
    # that could not be counted read as nought files -> this reddens. Mutation (declared): the
    # count asked without `--tag` too -> the last assertion reddens.
    root = _at(tmp_path, "1.2.3")
    problems = release.check(root, tag="v1.2.3")
    assert len(problems) == 1, problems
    assert problems[0].startswith("the plugin tree could not be read: "), problems
    assert "HEAD names no commit" in problems[0], problems
    assert problems[0].endswith("; run the check in the git checkout the tag names"), problems
    assert release.check(root) == []


@needs_git
def test_a_tag_whose_entry_is_malformed_reports_it_once(tmp_path: Path) -> None:
    # `scripts/plugin_tree.py` refuses a `sha` that is no commit id as well, and its refusal was
    # reported a second time under the tree count, with "run the check in the git checkout the tag
    # names" as the remedy. The entry's own finding is the one problem. Mutation (declared):
    # `mutations/`'s "release check computes the pin from an entry it found malformed" -> the
    # count problem comes back and this reddens.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"), pin=False)
    _pinning(root, "C" * 40)
    assert release.check(root, tag="v1.2.3") == [
        f".claude-plugin/marketplace.json entry 'drybag' pins sha {'C' * 40}, which is no commit id"
    ]


# --- `check --tag`: the marketplace pins the plugin commit its tree makes ------------------------


def _said_pin(pinned: str, made: str) -> str:
    """The pin's finding when the marketplace pins another commit, written out."""
    return (
        f".claude-plugin/marketplace.json entry 'drybag' pins sha {pinned}; the plugin commit "
        f"of this tree is {made}"
    )


@needs_git
def test_a_tag_whose_pin_is_the_plugin_commit_passes(tmp_path: Path) -> None:
    # The pin is the plugin commit `scripts/plugin_tree.py commit` computes at `HEAD`, which this
    # computes again with git over the literal text. Twice: nothing in the check reads a clock or
    # leaves a git dir behind for the next run. Mutation (declared): `mutations/`'s "release check
    # holds the pin to the plugin commit's parent" -> the pin is not the parent and this reddens.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"))
    for _ in range(2):
        kinds, _ = release.checked_by_kind(root, tag="v1.2.3")
        assert kinds == {
            "version drift": [],
            "plugin tree count": [],
            "plugin pin": [],
        }


@needs_git
def test_a_tag_whose_pin_is_not_the_plugin_commit_is_a_finding(tmp_path: Path) -> None:
    # The release after one, cut with the pin left as it was: the pin is the previous release's
    # plugin commit, which is now the parent, and the commit this tree makes follows it. Mutations
    # (declared): `mutations/`'s "release check holds the pin to the plugin commit's parent" ->
    # the stale pin is the parent and passes; "release check passes any pin" -> this reddens.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"))
    previous = _plugin_commit_of(root)
    git(root, "commit", "-q", "--allow-empty", "-m", "a release that did not pin")
    made = _plugin_commit_of(root, previous)
    assert made != previous
    kinds, _ = release.checked_by_kind(root, tag="v1.2.3")
    assert kinds["plugin pin"] == [_said_pin(previous, made)]
    assert release.check(root, tag="v1.2.3") == [_said_pin(previous, made)]


@needs_git
def test_a_tag_without_a_pin_is_a_finding_naming_the_commit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Mutation (declared): `mutations/`'s "release check passes a marketplace pinning no sha" ->
    # this reddens.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"), pin=False)
    made = _plugin_commit_of(root)
    problem = (
        ".claude-plugin/marketplace.json entry 'drybag' pins no sha; the plugin commit of this "
        f"tree is {made}: run `uv run python scripts/release.py pin`"
    )
    assert release.check(root, tag="v1.2.3") == [problem]
    assert release.main(["check", "--root", str(root), "--tag", "v1.2.3"]) == 1
    assert capsys.readouterr().out == f"plugin pin: {problem}\n"


@needs_git
def test_plain_check_does_not_compute_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Plain `check` runs on every pull request, where `dev` pins no sha and a stale one is no
    # finding: the pin is the release commit's, held at the tag. Nothing is run to compute it.
    # Mutation (declared): `mutations/`'s "release check counts the plugin tree without a tag" ->
    # the runner is asked for and this reddens.
    root = _with_plugin_paths(_at(tmp_path, "1.2.3"))
    git(root, "commit", "-q", "--allow-empty", "-m", "a pin gone stale")

    def unused() -> object:
        raise AssertionError("plain check ran a subprocess")

    monkeypatch.setattr(release, "subprocess_runner", unused)
    assert release.check(root) == []


# --- `pin`: the plugin commit written into the marketplace entry --------------------------------


def _remote(tmp_path: Path, main: str | None = None, **refs: str) -> Path:
    """A bare plugin repository at `tmp_path / "plugin.git"`: its `main` a commit whose message is
    `main`, or no `main` when it is `None`, and each of `refs`, a full ref name, a commit whose
    message is its value."""
    remote = tmp_path / "plugin.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    wanted = {"refs/heads/main": main} if main is not None else {}
    for ref, message in {**wanted, **refs}.items():
        tree = git_bytes(remote, "mktree", stdin=b"").decode().strip()
        stamp = "t <t@example.com> 1 +0000"
        text = f"tree {tree}\nauthor {stamp}\ncommitter {stamp}\n\n{message}\n"
        made = git_bytes(
            remote, "hash-object", "-t", "commit", "-w", "--stdin", stdin=text.encode()
        )
        git(remote, "update-ref", ref, made.decode().strip())
    return remote


def _tip(remote: Path, ref: str = "refs/heads/main") -> str:
    return git(remote, "rev-parse", ref).strip()


def _released(tmp_path: Path, previous: str | None) -> Path:
    """A release commit at 1.2.3 whose marketplace pins no sha, on a first parent pinning
    `previous`, or none when it is `None`."""
    root = _with_plugin_paths(_at(tmp_path / "source", "1.2.3"), pin=False)
    if previous is not None:
        _pinning(root, previous, "the release before")
        _pinning(root, None, "the release commit")
    return root


def _marketplace(root: Path) -> Path:
    return root / ".claude-plugin" / "marketplace.json"


@needs_git
@pytest.mark.parametrize("after", [False, True], ids=["the-first-release", "after-a-release"])
def test_pin_writes_the_commit_into_the_entry(
    tmp_path: Path, after: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    # The first release follows no commit and the plugin repository has no `main`; a later one
    # follows the previous release's plugin commit, which is `main`. The file is rewritten in one
    # format, the `sha` after the `ref`. Mutation (declared): `mutations/`'s "pin refuses a main
    # it should follow" -> `after-a-release` reddens.
    remote = _remote(tmp_path, "some" if after else None)
    parent = _tip(remote) if after else None
    root = _released(tmp_path, parent)
    made = _plugin_commit_of(root, parent)
    argv = ["pin", "--root", str(root), "--remote", str(remote), "--json"]
    assert release.main(argv) == 0, capsys.readouterr()
    assert json.loads(capsys.readouterr().out)["sha"] == made
    expected = marketplace_at("1.2.3")
    plugins = expected["plugins"]
    assert isinstance(plugins, list)
    plugins[0]["source"]["sha"] = made
    assert _marketplace(root).read_text(encoding="utf-8") == json.dumps(expected, indent=2) + "\n"
    assert list(plugins[0]["source"]) == ["source", "url", "ref", "sha"]
    # And the tag's check passes once the pin is committed into the release commit, whose first
    # parent is still the release before.
    git(root, "commit", "-q", "-a", "--amend", "--no-edit")
    assert release.check(root, tag="v1.2.3") == []


@needs_git
def test_pin_writes_text_outside_ascii_as_it_is(tmp_path: Path) -> None:
    # `pin` rewrites the whole marketplace, and a character outside ASCII written back as a `\u`
    # escape changes a line the pin is not about, which a reviewer of the release commit then
    # has to read past. Mutation (declared): `mutations/`'s "pin escapes text outside ASCII" ->
    # the description is written as escapes and this reddens.
    remote = _remote(tmp_path)
    root = _released(tmp_path, None)
    document = json.loads(_marketplace(root).read_text(encoding="utf-8"))
    document["description"] = "na\u00efve \u2014 a description"
    _marketplace(root).write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    release.pin(root, remote=str(remote), runner=subprocess_runner())
    assert '"description": "na\u00efve \u2014 a description"' in _marketplace(root).read_text(
        encoding="utf-8"
    )


def test_pin_reads_the_plugin_repository_by_default() -> None:
    # Read only: `pin` lists the remote's `main` and pushes nothing. Mutation (declared):
    # `mutations/`'s "pin's default remote is another repository" -> this reddens.
    groups = subparsers(release.parser())
    assert groups is not None
    assert groups.choices["pin"].parse_args([]).remote == PLUGIN_URL


@needs_git
@pytest.mark.parametrize(
    ("main", "previous"),
    [
        pytest.param(None, "c" * 40, id="no-main"),
        pytest.param("some", None, id="no-parent"),
        pytest.param("some", "c" * 40, id="another-main"),
    ],
)
def test_pin_refuses_when_the_plugin_main_is_not_the_parent(
    tmp_path: Path, main: str | None, previous: str | None
) -> None:
    # The plugin repository's `main` moves only by fast-forward, so the commit this release pins
    # must follow it: refused before any tag is pushed, naming both and the likely cause, and the
    # file left as it was, byte for byte. Mutations (declared): `mutations/`'s "pin skips the main
    # comparison" -> every case writes and reddens; "pin writes before it compares" -> the file
    # changes and every case reddens; "pin says a first release's commit has a parent" ->
    # `no-parent` says `parent None`; "pin says a plugin repository with no main has one" ->
    # `no-main` says `main at None`; "pin's refusal stops naming the stopped release the restore
    # commit answers" -> every case reddens.
    remote = _remote(tmp_path, main)
    root = _released(tmp_path, previous)
    before = _marketplace(root).read_bytes()
    made = _plugin_commit_of(root, previous)
    with pytest.raises(Refusal) as refused:
        release.pin(root, remote=str(remote), runner=subprocess_runner())
    follows = f"parent {previous}" if previous is not None else "no parent"
    holds = f"main at {_tip(remote)}" if main is not None else "no main"
    assert str(refused.value) == (
        f"the plugin commit {made} has {follows}, and {remote} has {holds}; the plugin "
        "repository's main moves only by fast-forward. The likely cause: the plugin repository "
        "was never seeded (RELEASING.md, section 3); this release commit was cut on the wrong "
        "base; a merge into main dropped the sha .claude-plugin/marketplace.json "
        "pinned at the release before; or a release that stopped after its plugin was pushed left "
        "main at a commit nothing here pins, which the restore commit puts back (RELEASING.md, "
        "section 5)"
    )
    assert _marketplace(root).read_bytes() == before


@needs_git
def test_pin_reads_main_by_its_exact_name(tmp_path: Path) -> None:
    # `ls-remote` matches a pattern by its tail, so `refs/heads/main` also lists
    # `refs/heads/x/refs/heads/main`, a branch anyone with push access can make. Mutation
    # (declared): `mutations/`'s "pin takes ls-remote's first line for main" -> that branch is
    # read as `main`, which the first release must not have, and this reddens.
    remote = _remote(tmp_path, None, **{"refs/heads/x/refs/heads/main": "other"})
    listed = git(tmp_path, "ls-remote", str(remote), "refs/heads/main")
    assert listed.strip().endswith("\trefs/heads/x/refs/heads/main"), listed
    root = _released(tmp_path, None)
    assert release.pin(root, remote=str(remote), runner=subprocess_runner()) == _plugin_commit_of(
        root
    )


@needs_git
def test_pin_refuses_an_unreachable_remote(tmp_path: Path) -> None:
    # The first release, so a `main` read as absent would pass: only the failure check refuses.
    # Mutation (declared): `mutations/`'s "pin reads a remote it could not list as empty" -> the
    # file is written and this reddens.
    root = _released(tmp_path, None)
    before = _marketplace(root).read_bytes()
    absent = tmp_path / "absent.git"
    with pytest.raises(Refusal) as refused:
        release.pin(root, remote=str(absent), runner=subprocess_runner())
    said = str(refused.value)
    # git's line quotes the path, so it is printed as its `repr`, clipped.
    assert said.startswith(f'git ls-remote of {absent} exited 128: "fatal: '), said
    assert _marketplace(root).read_bytes() == before


def test_pin_refuses_a_tree_it_cannot_make_the_commit_of(tmp_path: Path) -> None:
    # Outside a git checkout `scripts/plugin_tree.py commit` refuses, and `pin` quotes it before
    # it lists any remote. Mutation (declared): `mutations/`'s "pin reads a commit it could not
    # make" -> an internal error, not this refusal, and this reddens.
    root = _at(tmp_path, "1.2.3")
    with pytest.raises(Refusal) as refused:
        release.pin(root, remote=str(tmp_path / "unread.git"), runner=subprocess_runner())
    said = str(refused.value)
    assert said.startswith("the plugin commit could not be made: "), said
    assert "HEAD names no commit" in said, said


@needs_git
@pytest.mark.parametrize(
    ("edited", "wording"),
    [
        pytest.param(
            '{"plugins": "x"}',
            "cannot be pinned: .claude-plugin/marketplace.json is valid JSON but its plugins is "
            "not a list of objects",
            id="plugins-a-string",
        ),
        pytest.param(
            '{"plugins": [{"name": "drybag", "source": "./"}]}',
            "cannot be pinned: its entry 'drybag' has a source that is no object",
            id="a-string-source",
        ),
        pytest.param(
            '{"plugins": []}',
            "cannot be pinned: it has 0 entries named 'drybag'; the sha is written into "
            "exactly one",
            id="no-entry",
        ),
        pytest.param(
            json.dumps({"plugins": [{"name": "drybag", "source": {}}] * 2}),
            "cannot be pinned: it has 2 entries named 'drybag'; the sha is written into "
            "exactly one",
            id="two-entries",
        ),
    ],
)
def test_pin_refuses_a_marketplace_edited_out_of_shape_since_head(
    tmp_path: Path, edited: str, wording: str
) -> None:
    # The commit is made of `HEAD`, whose marketplace `plugin_tree.py` read; the file `pin` writes
    # is the one on disk, edited since. Refused, as `pin` refuses, and left as it was. Mutations
    # (declared): `mutations/`'s "pin lets a marketplace it cannot read out as a finding" ->
    # `plugins-a-string` exits as a `Failure`; "pin writes a sha into a source that is no object"
    # -> `a-string-source` is an internal error; "pin reads the source of an entry that is not
    # there" -> `no-entry` and `two-entries` are internal errors. The count and the shape are
    # said apart: one sentence for both named neither.
    remote = _remote(tmp_path)
    root = _released(tmp_path, None)
    _marketplace(root).write_text(edited, encoding="utf-8")
    with pytest.raises(Refusal) as refused:
        release.pin(root, remote=str(remote), runner=subprocess_runner())
    assert str(refused.value) == f".claude-plugin/marketplace.json {wording}"
    assert _marketplace(root).read_text(encoding="utf-8") == edited


@pytest.mark.parametrize(
    "failed",
    [
        pytest.param(Completed(2, json.dumps({"summary": HOSTILE}), ""), id="its-summary"),
        pytest.param(Completed(1, "", f"Traceback\n{ESCAPED}\n"), id="a-traceback"),
        pytest.param(Completed(1, "", ""), id="nothing"),
    ],
)
def test_what_the_plugin_tree_script_said_is_quoted_clipped(
    tmp_path: Path, failed: Completed
) -> None:
    # `plugin_tree.py`'s refusal quotes the repository's names and paths, and a traceback's last
    # line quotes anything. Mutations (declared): `mutations/`'s "release quotes the plugin tree
    # script's summary as it is" -> `its-summary` carries the line break; "release quotes the
    # plugin tree script's last stderr line as it is" -> `a-traceback` carries the escape; "release
    # quotes a plugin tree script that said nothing as its last line" -> `nothing` is an internal
    # error; "release lets a plugin tree script that printed no JSON out as an internal error" ->
    # `a-traceback` and `nothing` are.
    runner = Recorder(code=failed.code, stdout=failed.stdout, stderr=failed.stderr)
    with pytest.raises(Refusal) as refused:
        release.pin(_at(tmp_path, "1.2.3"), remote=str(tmp_path / "unread.git"), runner=runner)
    shown = "it exited 1 and said nothing"
    if failed.stdout:
        shown = CLIPPED
    elif failed.stderr:
        shown = ESCAPED_CLIPPED
    assert str(refused.value) == f"the plugin commit could not be made: {shown}"


@needs_git
@pytest.mark.parametrize(
    ("stderr", "said"),
    [
        pytest.param(f"{ESCAPED}\nfatal: the second line\n", ESCAPED_CLIPPED, id="escaped"),
        pytest.param("", "it said nothing", id="nothing"),
    ],
)
def test_a_remote_s_refusal_is_quoted_clipped(tmp_path: Path, stderr: str, said: str) -> None:
    # git prints what the remote said, its first line quoted. Mutations (declared):
    # `mutations/`'s "pin quotes the remote's refusal as it is" -> the escape sequence and all 204
    # characters reach the refusal; "pin quotes a remote that said nothing as its first line" ->
    # `nothing` is an internal error.
    root = _released(tmp_path, None)
    report = {"files": 10, "commit": "c" * 40, "pinned": None, "parent": None}
    refused_listing = Completed(128, "", stderr)
    runner = Recorder(stdout=json.dumps(report), answers={"git ls-remote": refused_listing})
    with pytest.raises(Refusal) as refused:
        release.pin(root, remote="some-remote", runner=runner)
    assert str(refused.value) == f"git ls-remote of some-remote exited 128: {said}"


@needs_git
def test_pin_twice_writes_the_same_file(tmp_path: Path) -> None:
    # No mutation of its own: the commit is a function of the source commit, which
    # `test_a_tag_whose_pin_is_the_plugin_commit_passes` holds, and the file is written in one
    # format. This pins a re-run after an interrupted release against a write that is not.
    remote = _remote(tmp_path)
    root = _released(tmp_path, None)
    first = release.pin(root, remote=str(remote), runner=subprocess_runner())
    written = _marketplace(root).read_bytes()
    assert release.pin(root, remote=str(remote), runner=subprocess_runner()) == first
    assert _marketplace(root).read_bytes() == written


def test_every_command_opens_its_own_help_with_what_it_does() -> None:
    # The installed CLI's frame copies each command's `help=` into its description; this script
    # has its own parser and no frame, so `notes --help` opened with `usage:` and went straight
    # to the options. Mutation (declared): a command registered without `description=` ->
    # reddens naming it.
    groups = subparsers(release.parser())
    assert groups is not None
    listed = {action.dest: action.help for action in groups._choices_actions}
    assert sorted(groups.choices) == ["check", "notes", "pin"]
    for name, sub in groups.choices.items():
        # Not vacuous: a command registered with neither sentence has `None` for both, and the
        # equality below holds. Mutation (declared): `mutations/`'s "the release script
        # registers a command with no sentence at all".
        assert listed[name], name
        assert sub.description == listed[name], name
        assert "--json" in sub.format_help(), name


def test_the_cli_passes_the_tag_through_to_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # That the flag exists and that its value reaches `check` is held here and nowhere else.
    # Mutation: `check(root, tag=args.tag)` -> `check(root)` -> exit 0 and this reddens.
    root = _at(tmp_path, "1.2.3")
    argv = ["check", "--root", str(root), "--tag", "v9.9.9"]
    assert release.main(argv) == 1
    assert "tag v9.9.9 is neither v1.2.3 nor" in capsys.readouterr().out


def test_the_cli_refuses_notes_under_a_version_that_is_not_the_projects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Exit 2, the refusal code, and no towncrier anywhere: the comparison is above the runner,
    # so this walks the command end to end without shelling out, which no test does —
    # CONTRIBUTING.md's Tests section routes such calls through a stub runner, and the write
    # path stays a unit test over the stub, under `notes` below.
    root = _at(tmp_path, "1.2.3")
    argv = ["notes", "--version", "1.3.0", "--root", str(root)]
    assert release.main(argv) == 2
    assert "set the version everywhere first" in capsys.readouterr().err


def test_collect_still_reads_the_package_version_beside_the_repository_constants() -> None:
    # `drybag.REPOSITORY_SLUG` and `drybag.REPOSITORY_URL` sit in
    # `src/drybag/__init__.py` beside `__version__`; `_INIT`'s regex is anchored on
    # `__version__` alone, so the two new lines must not change what this reads.
    from drybag import __version__

    assert release.collect(ROOT)["src/drybag/__init__.py"] == __version__


# --- `notes`: the towncrier wrapper, driven through the runner seam ------------------------------

# What the stubbed towncrier prints for a draft, and what `build` returns for one.
NOTES = "## 1.2.3\n\n- a note\n"


def _root(tmp_path: Path, version: str = "1.2.3") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "drybag"\nversion = "{version}"\n', encoding="utf-8"
    )
    return tmp_path


def test_the_argv_is_towncriers_build_with_the_version_and_yes(tmp_path: Path) -> None:
    stub = Recorder(stdout=NOTES)
    release.build(_root(tmp_path), version="1.2.3", draft=False, runner=stub)
    assert stub.calls == [["towncrier", "build", "--version", "1.2.3", "--yes"]]
    assert stub.cwds == [tmp_path]


def test_a_draft_adds_the_flag_and_returns_towncriers_stdout(tmp_path: Path) -> None:
    stub = Recorder(stdout=NOTES)
    assert release.build(_root(tmp_path), version="1.2.3", draft=True, runner=stub) == stub.stdout
    assert stub.calls[0][-1] == "--draft"


def test_a_version_that_is_not_the_projects_is_refused_before_anything_runs(tmp_path: Path) -> None:
    # `check` requires the changelog's first heading to equal pyproject's version, so
    # assembling under another number writes a changelog the gate then refuses. Refused here,
    # above the write. Mutation (declared): drop the comparison -> the stub is called and the
    # `calls == []` assertion reddens. The refusal names the command that lists the places to
    # change, spelled out for the reason the module docstring gives.
    stub = Recorder(stdout=NOTES)
    named = "set the version everywhere first — `uv run python scripts/release.py check` names"
    with pytest.raises(Refusal, match=re.escape(named)):
        release.build(_root(tmp_path, version="1.2.3"), version="1.3.0", draft=False, runner=stub)
    assert stub.calls == []


def test_a_missing_towncrier_names_the_dependency_group(tmp_path: Path) -> None:
    with pytest.raises(Failure, match="uv sync"):
        release.build(
            _root(tmp_path),
            version="1.2.3",
            draft=False,
            runner=Recorder(code=NOT_FOUND, stderr="boom"),
        )


def test_run_without_its_package_it_refuses_with_exit_2_and_says_to_use_uv(tmp_path: Path) -> None:
    # An interpreter without this repository's `drybag` fails on the script's first import,
    # before the CLI frame exists, and a traceback exits `1`, which `check` gives its findings.
    # Mutations (declared): `mutations/`'s "release.py exits 1 when its package cannot be imported"
    # and "release.py refuses a missing package without saying to run it through uv".
    done = without_drybag("release.py", tmp_path, "check")
    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stdout == "", done.stdout
    assert "refused: No module named 'drybag'" in done.stderr, done.stderr
    assert "uv run python scripts/release.py" in done.stderr, done.stderr
    assert "Traceback" not in done.stderr, done.stderr


def test_run_on_a_python_without_tomllib_it_refuses_with_exit_2(tmp_path: Path) -> None:
    # `tomllib` is new in Python 3.11, and a `python3` older than that fails on it before the CLI
    # frame exists, as one without `drybag` does: exit `1`, `check`'s findings, unless the
    # import is guarded with the package's. Mutation (declared): `mutations/`'s "release.py imports
    # tomllib outside its guarded imports".
    done = without_drybag("release.py", tmp_path, "check", missing=("tomllib",))
    assert done.returncode == 2, done.stdout + done.stderr
    assert "refused: import of tomllib halted" in done.stderr, done.stderr
    assert "uv run python scripts/release.py" in done.stderr, done.stderr
    assert "Traceback" not in done.stderr, done.stderr
