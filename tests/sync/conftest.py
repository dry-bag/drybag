"""Real git repositories for the note sync's tests: a bare remote and two clones of it.

git is never mocked here: the rules under test are about what git lists (renames, merges, the
pathspec magic), so a fake would only test the fake. Every repository lives under the test's
`tmp_path`, and `_sealed_git` closes what the root `conftest.py` leaves open (git's system
configuration, an identity, the variables a hook run would hand on), so the developer's own
settings cannot reach a test. The scanner is a stand-in script that answers as the real build
does, and pre-commit's database a SQLite file written here: no test runs `pre-commit` or
`gitleaks`.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stayfixed import binding
from stayfixed.config.machine import machine_config_path
from stayfixed.memory.api import build_composed, rerender_overlay_index
from stayfixed.sync.job import JobContext, Limits
from stayfixed.sync.render import remember_checkout
from stayfixed.sync.state import state_directory
from tests import gitfixture as fx

# A bound no test's own git call should reach under the load other sessions put on the machine;
# the tests about a bound running out pass a small one of their own.
SLOW = 120.0
GITLEAKS_REPO = "https://github.com/gitleaks/gitleaks"
GITLEAKS_REV = "83d9cd684c87d95d656c1458ef04895a7f1cbd8e"
LEAK = "FAKESECRET-0123456789abcdef"
DEFAULT_RULES = "# the build's own default rules\n"
# The variables a job started from inside a git hook would inherit, and the ones a test that
# reads the ssh command or the attributes must find unset.
_AMBIENT = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
    "GIT_SSH_COMMAND",
    "GIT_SSH",
    "GIT_ATTR_SOURCE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
)


@pytest.fixture(autouse=True)
def _sealed_git(monkeypatch: pytest.MonkeyPatch, _a_home_of_its_own: Path) -> None:
    """The sealed environment of `tests.gitfixture` for the `git` the product's runner starts
    too, in the per-test `HOME` of the root `conftest.py`, with none of the variables a hook run
    would hand on."""
    for name in _AMBIENT:
        monkeypatch.delenv(name, raising=False)
    for name, value in fx.env(_a_home_of_its_own).items():
        monkeypatch.setenv(name, value)


def git(repo: Path, *args: str) -> str:
    return fx.git(repo, *args)


def init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    fx.git(path, "init", "-q", "-b", "main")
    return path


def write(repo: Path, relative: str, text: str = "note\n") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def head(repo: Path, ref: str = "HEAD") -> str:
    return git(repo, "rev-parse", ref).strip()


def commit_all(repo: Path, message: str = "change") -> str:
    """Stage everything and commit, an empty commit included; the new sha."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return head(repo)


def rename(repo: Path, source: str, destination: str) -> None:
    """`git mv`: staged, committed by `commit_all`."""
    (repo / destination).parent.mkdir(parents=True, exist_ok=True)
    git(repo, "mv", source, destination)


def symlink(repo: Path, relative: str, target: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def merge_with_resolution(
    repo: Path, branch: str, edits: dict[str, str], message: str = "merge"
) -> str:
    """Merge `branch` into the current branch with `edits` written into the merge itself.

    An evil merge when `edits` names a path neither side changed: the change is in the merge
    commit's tree only, where `git log --name-only` does not show it.
    """
    fx.run_git(repo, "merge", "--no-ff", "--no-commit", branch)
    for relative, text in edits.items():
        write(repo, relative, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--no-edit", "-m", message)
    return head(repo)


def _tree(repo: Path, entries: list[tuple[str, str, str]]) -> str:
    """A tree of `(mode, name, sha)` entries, written byte for byte: git's own commands refuse
    the names this exists for (`..`, `.git`), `hash-object --literally` does not."""

    def order(entry: tuple[str, str, str]) -> bytes:  # git sorts a tree as "name/"
        return entry[1].encode() + (b"/" if entry[0] == "40000" else b"")

    data = b"".join(
        f"{mode} {name}".encode() + b"\0" + bytes.fromhex(sha)
        for mode, name, sha in sorted(entries, key=order)
    )
    return _bytes(repo, "hash-object", "-t", "tree", "--literally", "-w", "--stdin", data=data)


def _bytes(repo: Path, *args: str, data: bytes = b"") -> str:
    return fx.git_bytes(repo, *args, stdin=data).decode().strip()


def crafted_commit(repo: Path, parent: str, path: str, text: str = "note\n") -> str:
    """A commit on `parent` adding the regular file `path`, a name git would refuse to write.
    Not checked out; the rest of `parent`'s tree is kept."""

    def tree_with(tree: str | None, parts: list[str]) -> str:
        entries: list[tuple[str, str, str]] = []
        if tree is not None:
            for line in filter(None, _bytes(repo, "ls-tree", "-z", tree).split("\0")):
                meta, name = line.split("\t", 1)
                mode, _, sha = meta.split(" ")
                entries.append((mode.lstrip("0") if mode == "040000" else mode, name, sha))
        name = parts[0]
        existing = next((entry for entry in entries if entry[1] == name), None)
        entries = [entry for entry in entries if entry[1] != name]
        if len(parts) == 1:
            entries.append(
                ("100644", name, _bytes(repo, "hash-object", "-w", "--stdin", data=text.encode()))
            )
        else:
            below = existing[2] if existing and existing[0] == "40000" else None
            entries.append(("40000", name, tree_with(below, parts[1:])))
        return _tree(repo, entries)

    tree = tree_with(_bytes(repo, "rev-parse", f"{parent}^{{tree}}"), path.split("/"))
    return _bytes(repo, "commit-tree", tree, "-p", parent, "-m", "crafted")


@dataclass(frozen=True)
class World:
    """A bare remote with `main`, and two clones of it tracking `origin/main`."""

    bare: Path
    a: Path
    b: Path


@pytest.fixture
def world(tmp_path: Path) -> World:
    bare = tmp_path / "remote.git"
    bare.mkdir()
    fx.git(bare, "init", "-q", "--bare", "-b", "main")
    seed = init(tmp_path / "seed")
    write(seed, "README.md", "overlay\n")
    write(seed, "common/memory/first.md", "first note\n")
    write(seed, "common/claude/hooks/launch.sh", "#!/bin/sh\n")
    commit_all(seed, "seed")
    git(seed, "push", "-q", str(bare), "main")
    clones = []
    for name in ("a", "b"):
        clone = tmp_path / name
        fx.git(tmp_path, "clone", "-q", str(bare), str(clone))
        clones.append(clone)
    return World(bare, clones[0], clones[1])


def push_note(clone: Path, relative: str, text: str, message: str = "memory: upstream note") -> str:
    """Commit `relative` in `clone` and push it: another machine's sync, done by hand."""
    write(clone, relative, text)
    git(clone, "add", "--", relative)
    git(clone, "commit", "-q", "-m", message)
    git(clone, "push", "-q", "origin", "main")
    return head(clone)


def slow_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, slow: dict[str, float]) -> None:
    """A `git` first on PATH that sleeps before the subcommands named in `slow`, seconds each."""
    real = shutil.which("git")
    shim = tmp_path / "slow-shim"
    shim.mkdir()
    cases = "".join(f'    *" {name} "*) sleep {seconds} ;;\n' for name, seconds in slow.items())
    (shim / "git").write_text(f'#!/bin/sh\ncase " $* " in\n{cases}esac\nexec "{real}" "$@"\n')
    (shim / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")


# -- the scanner: the build pre-commit makes, as a script that answers like it ------------------

_GITLEAKS = r'''#!{python}
"""Stand-in gitleaks, answering as the real build does: a JSON report naming rule, file and
commit; exit 1 for a finding and for a failed scan alike (the failed one with an empty report).

Modes, from the file `mode` beside it: `scan` (default), `fail`, `sleep [seconds]` (then scan).
Its rules and ignores are found as the real one finds them: `--config`, else `$GITLEAKS_CONFIG`,
else the scanned directory's `.gitleaks.toml`; ignores from `--gitleaks-ignore-path` and from the
scanned directory's `.gitleaksignore`. Rules holding `allow-all`, or ignores holding
`ignore-all`, find nothing. What it saw is recorded in `argv.json`, `seen.json` and
`git_config.json` beside it.
"""
import json, os, subprocess, sys, time
from pathlib import Path

me = Path(__file__)
args = sys.argv[1:]
(me.parent / "argv.json").write_text(json.dumps(args))
(me.parent / "pid").write_text(str(os.getpid()))
(me.parent / "git_config.json").write_text(json.dumps({{key: subprocess.run(
    ["git", "config", "--get", key], capture_output=True, text=True).stdout.strip()
    for key in ("log.showSignature", "color.ui", "color.diff")}}))
mode_file = me.parent / "mode"
mode = mode_file.read_text().strip() if mode_file.exists() else "scan"
report = args[args.index("--report-path") + 1]
if mode.startswith("sleep"):
    time.sleep(float(mode.split()[1]) if len(mode.split()) > 1 else 30)
if mode == "fail":
    Path(report).write_text("[]")
    print("ERR failed to scan Git repository error=\"stderr is not empty\"", file=sys.stderr)
    sys.exit(1)
def value(flag) -> None:
    return args[args.index(flag) + 1] if flag in args else None
source = Path(args[-1]) if args[0] == "git" else Path(".")
rules = value("--config") or os.environ.get("GITLEAKS_CONFIG") or str(source / ".gitleaks.toml")
ignore = Path(value("--gitleaks-ignore-path") or ".")
ignore = ignore / ".gitleaksignore" if ignore.is_dir() else ignore
read = lambda path: Path(path).read_text() if Path(path).is_file() else None
(me.parent / "seen.json").write_text(json.dumps({{
    "rules": rules, "rules_text": read(rules), "ignore_text": read(ignore),
    "env": sorted(k for k in os.environ if k.startswith("GITLEAKS_")),
}}))
ignored = (read(ignore) or "") + (read(source / ".gitleaksignore") or "")
blind = "allow-all" in (read(rules) or "") or "ignore-all" in ignored
redact = "--redact" in args
findings = []
def found(path, commit) -> None:
    findings.append({{"RuleID": "fake-secret", "File": path, "Commit": commit,
                      "Secret": "REDACTED" if redact else "{secret}"}})
def scan(patch, commit) -> None:
    path = None
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("+") and "{secret}" in line:
            found(path, commit)
if blind:
    pass
elif args[0] == "stdin":
    for number, line in enumerate(sys.stdin.read().splitlines()):
        if "{secret}" in line:
            findings.append({{"RuleID": "fake-secret", "File": "", "Commit": "",
                              "StartLine": number, "Secret": "REDACTED" if redact else "{secret}"}})
elif "--pre-commit" in args and "--staged" in args:
    scan(subprocess.run(["git", "diff", "--cached", "--no-color", "-U0"], capture_output=True,
                        text=True, check=True).stdout, "")
else:
    rng = next(a.split("=", 1)[1] for a in args if a.startswith("--log-opts="))
    out = subprocess.run(["git", "log", "-p", "-U0", "--no-color", "--format=%x00%H", rng],
                         capture_output=True, text=True, check=True).stdout
    for chunk in out.split("\0")[1:]:
        sha, _, patch = chunk.partition("\n")
        scan(patch, sha)
Path(report).write_text(json.dumps(findings))
print("INF scan completed", file=sys.stderr)
sys.exit(1 if findings else 0)
'''


def build_gitleaks(directory: Path, environment: str = "default") -> Path:
    """A stand-in gitleaks where pre-commit would have built it, in `environment`, beside the
    source's `config/gitleaks.toml` (the default rules the real build embeds)."""
    (directory / "config").mkdir(parents=True, exist_ok=True)
    (directory / "config" / "gitleaks.toml").write_text(DEFAULT_RULES, encoding="utf-8")
    binary = directory / f"golangenv-{environment}" / "bin" / "gitleaks"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(_GITLEAKS.format(python=sys.executable, secret=LEAK), encoding="utf-8")
    binary.chmod(0o755)
    return binary


def pre_commit_store(cache: Path, rows: list[tuple[str, str, Path]]) -> Path:
    """pre-commit's `db.db` under `cache/pre-commit`, with `(repo, rev, path)` rows."""
    store = cache / "pre-commit"
    store.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(store / "db.db")) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS repos (repo TEXT NOT NULL, ref TEXT NOT NULL, "
            "path TEXT NOT NULL, PRIMARY KEY (repo, ref))"
        )
        db.executemany("INSERT INTO repos VALUES (?, ?, ?)", [(r, v, str(p)) for r, v, p in rows])
    return store


def environment_of(cache: Path) -> dict[str, str]:
    """The environment whose scratch cache holds the database `pre_commit_store` wrote."""
    return {"XDG_CACHE_HOME": str(cache), "PATH": os.environ.get("PATH", "")}


# -- an overlay the job runs on: notes, two bound checkouts, the scanner ------------------------

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)
HOST = "testhost"
TAG = "team"
PRE_COMMIT_CONFIG = (
    f"repos:\n  - repo: {GITLEAKS_REPO}\n    rev: {GITLEAKS_REV}\n"
    "    hooks:\n      - id: gitleaks\n"
)
PROJECT_CONFIG = """[stayfixed]
version = "0.1.0"
preset = "recommended"
profile = ""
agents = ["claude"]

[project]
name = "{name}"
base_branch = "main"
release_branch = "main"

[memory]
mode = "overlay"
groups = ["developer", "project-stable"]
index_extra = []
"""
# The projects with a checkout this machine's sessions opened, bound into the overlay; `gamma`
# has notes in the overlay and no checkout.
BOUND_PROJECTS = ("alpha", "beta")
PATHSPEC = [
    ":(top,glob)common/memory/**",
    ":(top,glob)groups/*/memory/**",
    ":(top,glob)projects/*/memory/**",
]


def note_text(name: str, *, index: str | None = None, body: str = "") -> str:
    """A note with frontmatter, as the store writes one."""
    lines = ["---", f"name: {name}", f'description: "the {name} note"']
    if index:
        lines.append(f'index: "{index}"')
    lines += ["metadata:", "  type: project", "---", "", body or f"Body of {name}.", ""]
    return "\n".join(lines)


@dataclass
class Overlays:
    """Two machines' clones of one overlay remote, `a` and `b`, with what the job reads: the
    checkouts bound into `a` and recorded as opened (`checkouts`), the scanner's stand-in
    (`gitleaks`) where pre-commit's database finds it, and the state directory."""

    bare: Path
    a: Path
    b: Path
    home: Path
    checkouts: dict[str, Path]
    gitleaks: Path
    state_dir: Path = field(default_factory=state_directory)
    # Whether the machine file `use` writes switches the sync on: the job's `main` and the hooks
    # read it, the steps under test never do.
    sync: bool = False

    def mode(self, mode: str | None) -> None:
        """Set the scanner stand-in's mode (`None`: scan)."""
        target = self.gitleaks.parent / "mode"
        if mode is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(mode, encoding="utf-8")

    def use(self, clone: Path) -> None:
        """Make `clone` the overlay this machine records, and bind the checkouts into it."""
        machine = machine_config_path()
        assert machine is not None
        machine.parent.mkdir(parents=True, exist_ok=True)
        switch = "\n[sync]\nenabled = true\n" if self.sync else ""
        machine.write_text(f'[overlay]\nroot = "{clone}"\n{switch}', encoding="utf-8")
        for name, root in self.checkouts.items():
            build_composed(clone, name, binding.ensure_id(root))

    def render(self, clone: Path, project: str) -> None:
        """`stayfixed memory index` from `project`'s checkout into `clone`, as its machine would."""
        self.use(clone)
        done = rerender_overlay_index(self.checkouts[project], machine=None)
        assert done.reason is None, done.reason
        self.use(self.a)


def a_checkout(root: Path, name: str) -> Path:
    """A repository whose `stayfixed.toml` keeps its notes in the overlay, bound to `name`."""
    init(root)
    remote = f"git@example.com:acme/{name}.git"
    git(root, "remote", "add", "origin", remote)
    write(root, "stayfixed.toml", PROJECT_CONFIG.format(name=name))
    binding.record(root, name, remote)
    return root


@pytest.fixture
def overlays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _a_home_of_its_own: Path) -> Overlays:
    home = _a_home_of_its_own
    monkeypatch.delenv("PRE_COMMIT_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    scanner = build_gitleaks(tmp_path / "pre-commit" / "repo")
    pre_commit_store(
        home / ".cache", [(GITLEAKS_REPO, GITLEAKS_REV, tmp_path / "pre-commit" / "repo")]
    )
    bare = tmp_path / "remote.git"
    bare.mkdir()
    fx.git(bare, "init", "-q", "--bare", "-b", "main")
    seed = init(tmp_path / "seed")
    write(seed, "README.md", "overlay\n")
    write(seed, ".pre-commit-config.yaml", PRE_COMMIT_CONFIG)
    write(seed, "common/claude/hooks/launch.sh", "#!/bin/sh\n")
    write(seed, "common/claude/hooks/x.py", "print('x')\n")
    write(seed, "common/memory/first.md", note_text("first", index="First trigger"))
    write(seed, f"groups/{TAG}/memory/{TAG}-one.md", note_text(f"{TAG}-one", index="Team trigger"))
    for project in ("alpha", "beta", "gamma"):
        relative = f"projects/{project}/memory/project-stable/{project}-one.md"
        write(seed, relative, note_text(f"{project}-one", index=f"{project} trigger"))
    write(seed, "projects/gamma/memory/MEMORY.md", "# gamma's index, rendered elsewhere\n")
    commit_all(seed, "seed")
    git(seed, "push", "-q", str(bare), "main")
    clones = []
    for name in ("a", "b"):
        fx.git(tmp_path, "clone", "-q", str(bare), str(tmp_path / name))
        clones.append(tmp_path / name)
    checkouts = {name: a_checkout(tmp_path / "checkouts" / name, name) for name in BOUND_PROJECTS}
    world = Overlays(bare, clones[0], clones[1], home, checkouts, scanner)
    world.use(world.a)
    for name in reversed(BOUND_PROJECTS):
        remember_checkout(checkouts[name], world.state_dir)
        assert rerender_overlay_index(checkouts[name], machine=None).reason is None
    commit_all(world.a, "memory: the first render")
    git(world.a, "push", "-q", "origin", "main")
    git(world.b, "pull", "-q", "--ff-only")
    return world


def context(world: Overlays, clone: Path, *, pending: object = None, **limits: float) -> JobContext:
    """A `JobContext` for `clone`, owing `pending`, with any step limit overridden."""
    return JobContext(
        overlay=clone,
        state_dir=world.state_dir,
        home=world.home,
        host=HOST,
        now=lambda: NOW,
        pending=pending,  # type: ignore[arg-type]
        limits=Limits(**limits),
    )


def committed(repo: Path, rev: str = "HEAD") -> list[tuple[str, str]]:
    """`[(status, path)]` the commit `rev` made, renames off."""
    out = git(repo, "show", "--no-renames", "--name-status", "-z", "--format=", rev)
    fields = [item for item in out.strip("\n").split("\0") if item]
    return sorted(zip(fields[0::2], fields[1::2], strict=True))


def memory_status(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--no-renames", "--", *PATHSPEC)


def staged(repo: Path, *pathspec: str) -> str:
    return git(repo, "diff", "--cached", "--name-only", "--", *pathspec)


def ssh_signing(tmp_path: Path, clone: Path) -> None:
    """Sign every commit in `clone` with an ssh key, and make `git log` show signatures."""
    key = tmp_path / "signing-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "sync", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    allowed = tmp_path / "allowed_signers"
    allowed.write_text(f"t@example.com {(tmp_path / 'signing-key.pub').read_text()}")
    for name, value in (
        ("gpg.format", "ssh"),
        ("user.signingkey", str(key)),
        ("gpg.ssh.allowedSignersFile", str(allowed)),
        ("commit.gpgsign", "true"),
        ("log.showSignature", "true"),
    ):
        git(clone, "config", name, value)
