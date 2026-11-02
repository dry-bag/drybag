"""The owner's walkthrough, offline, in a temporary directory.

Every package is tested on its own against stubs. This is the one test that runs them in the
order a person does, and it exists because the four packages' seams — the machine file, the
overlay root, the project record, the composed store, the ignore region — are each written by one
package and read by another, and a stub on both sides of a seam agrees with itself.

**Every step runs the real launcher.** Each one used to call a library function, so the
argv wiring of eight commands — the flag names, the `--yes` gate reached through argparse, the
`--machine` refusal from a pipe, the JSON `doctor` prints — was exercised by nothing that ran
them in order. `_cli` below runs `scripts/stayfixed` in a subprocess, which is how a person and
how a skill reach these commands.

Nothing here touches the network, the real `~`, or any harness binary. `HOME` is a scratch
directory and every harness variable is dropped, and the binaries the CLI resolves through
`PATH` on purpose — `gh`, `claude`, `codex` and `pre-commit`, the owner's own — are answered by
a scratch `bin/` placed first on the subprocess's `PATH`. `pre-commit` there writes the commit
hook `doctor` later asks about, rather than only recording that it was called. `git` is real,
because a repository with no `origin` is not the thing being tested.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import stayfixed
from stayfixed.attach.hooks import NOT_ATTACHED
from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.doctor.api import OK, RED, SKIP, run_checks
from stayfixed.memory.api import DELIMITER, PROJECTS, markers
from tests.floor import developer_free_environ
from tests.gitfixture import git
from tests.runners import Recorder
from tests.snapshot import (
    assert_snapshot_changed,
    assert_snapshot_unchanged,
    snapshot,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "hooks" / "run-hook.sh"
OWNER = "owner"
PROJECT = "widget"
ORIGIN = f"git@github.com:{OWNER}/{PROJECT}.git"
# The rule the walkthrough puts in the overlay and then asks a session for. Distinctive enough
# that finding it in the wrapper's stdout cannot be an accident.
RULE_BODY = "NEVER FORCE-PUSH A SHARED BRANCH; open a pull request instead."

# The note the walkthrough asks a session for, as one spelling. `_install_path` writes it into
# the overlay on the path a fresh project takes, and `_project(initialised=True)` writes the same
# bytes into the repository so the owner's own hand-move is what puts it in the overlay.
NOTE = (
    "---\nname: no-force-push\ndescription: never force-push a shared branch\n"
    f"metadata:\n  type: rule\n  startup: 1\n---\n\n{RULE_BODY}\n"
)

CONFIG = """[stayfixed]
version = "{version}"
enforced = ["docs", "bugs", "plan", "commit", "trail"]

[project]
name = "{project}"

[memory]
mode = "{mode}"
groups = ["developer", "project-stable"]
"""


def _project(tmp_path: Path, *, mode: str, initialised: bool = False) -> Path:
    """The repository the walkthrough starts from; `initialised`, the shape the owner's has.

    **`initialised` does not run `init` here.** It builds the repository `init` is run *over*:
    notes already in `paths.memory` as real directories, `[ci] mode = "none"`, and one commit,
    so the history predates stayfixed. `stayfixed init --yes` is `_install_path`'s step 0, which
    is where the launcher environment lives. The flag keeps the name `_install_path` gives it,
    because renaming one of the pair would split them.

    `[ci] mode = "none"` because this repository wants no workflow — a `ci` mode that asked for one
    would have `init` reach for the release pin and a remote, which is a different test's subject.
    The commit matters because `init` then writes its footprint on top of a tree that was already
    committed, which is the order an adopting project meets it in, and the notes moved later are
    notes that were tracked before stayfixed arrived.
    """
    root = tmp_path / "project"
    root.mkdir(parents=True, exist_ok=True)
    document = CONFIG.format(version=stayfixed.__version__, project=PROJECT, mode=mode)
    if initialised:
        document += '[ci]\nmode = "none"\n'
    (root / CONFIG_FILE).write_text(document, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", ORIGIN)
    if initialised:
        note = root / "docs" / "memory" / "project-stable" / "no-force-push.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(NOTE, encoding="utf-8")
        git(root, "add", "-A")
        git(
            root,
            "-c",
            "user.email=a@b.c",
            "-c",
            "user.name=a",
            "commit",
            "-qm",
            "chore: before stayfixed",
        )
    return root


@dataclass(frozen=True)
class Walkthrough:
    """What the walkthrough's eleven steps leave behind, for each test to assert about one."""

    root: Path
    overlay: Path
    machine: Path
    home: Path
    data: Path
    store: Path
    bin: Path


def _fake_binaries(bin_dir: Path) -> None:
    """The four binaries the CLI resolves through `PATH`, as the walkthrough may see them.

    `pre-commit install` writes the hook `doctor` later asks about, so the fake writes it too —
    a stub that answered 0 and wrote nothing would make two steps disagree for no reason a
    reader could see (the in-process runner these fakes replaced said the same). `gh` must never be
    reached on the `--local` path, so its fake exits 1 and the test asserts the log never names
    it. `claude` and `codex` are here because `setup` installs the preset's plugins through
    `subprocess_runner()`, which resolves them on `PATH`: without these the walkthrough would run
    the developer's real harness CLI, which no test may ever do. Nothing later reads their effect,
    so they record and exit 0.
    """
    bin_dir.mkdir()
    log = bin_dir / "calls.log"
    # The real one needs a repository and fails outside one. A bare `mkdir -p .git/hooks` left a
    # `.git` git does not read as a repository, which `setup`'s overlay guard rightly refuses as
    # a repository git will not describe; so the fake makes the repository the real one needs.
    (bin_dir / "pre-commit").write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "pre-commit $*" >> "{log}"\n'
        "git rev-parse --git-dir >/dev/null 2>&1 || git init -q . || exit 1\n"
        "mkdir -p .git/hooks && printf '#!/bin/sh\\nexit 0\\n' > .git/hooks/pre-commit\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "gh").write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "gh $*" >> "{log}"\nexit 1\n', encoding="utf-8"
    )
    for harness in ("claude", "codex"):
        (bin_dir / harness).write_text(
            f'#!/bin/sh\nprintf \'%s\\n\' "{harness} $*" >> "{log}"\nexit 0\n',
            encoding="utf-8",
        )
    for name in ("pre-commit", "gh", "claude", "codex"):
        (bin_dir / name).chmod(0o755)


def _cli(walk: Walkthrough, *argv: str) -> subprocess.CompletedProcess[str]:
    """One command, the way a person or a skill runs it: the launcher and argv, from no terminal.

    Nothing here reads the developer's own `~`: `HOME` is the scratch home and every harness
    variable is dropped.
    """
    env = developer_free_environ()
    env["HOME"] = str(walk.home)
    env["PATH"] = f"{walk.bin}{os.pathsep}{env.get('PATH', '')}"
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    env["CLAUDE_PLUGIN_DATA"] = str(walk.data)
    command = [sys.executable, str(ROOT / "scripts" / "stayfixed"), *argv]
    return subprocess.run(
        command,
        cwd=walk.root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _doctor(walk: Walkthrough, *, root: Path | None = None) -> list[dict[str, str]]:
    """The fourteen rows, read back out of what `doctor --json` printed on the launcher's
    stdout."""
    done = _cli(
        walk,
        "doctor",
        "--json",
        "--root",
        str(walk.root if root is None else root),
        "--home",
        str(walk.home),
        "--machine",
        str(walk.machine),
    )
    assert done.stdout, done.stderr
    rows: list[dict[str, str]] = json.loads(done.stdout)["checks"]
    assert len(rows) == 14, rows
    return rows


def _install_path(
    tmp_path: Path,
    *,
    initialised: bool = False,
    attach: bool = True,
) -> Walkthrough:
    """Steps 1-6: the overlay, the machine layer, a repository, attach, and a note in it, promoted.

    Every step is the real launcher with the real argv. Step 1's overlay is rendered **outside** the
    project root, where an owner keeps it: `setup` refuses no place for it, and `doctor` warns when
    another repository's work tree holds it, since that repository can put files into it.

    `initialised` walks the same steps over a repository that already has its notes in
    `paths.memory` and has had `stayfixed init` run over it, which is the shape the owner's own
    repository is in. Step 4 then has one more beat before it: the notes are moved by hand into
    the overlay — the owner's act, which no command performs — since the composed store reads
    the overlay and never `paths.memory`. Step 5 is skipped there, because the moved note is the
    standing rule.

    `attach=False` stops before step 4 and answers the unattached state, which is what a
    session's first `SessionStart` sees on a project nobody has bound yet.

    `init` runs here rather than in `_project`, which has no launcher environment: `_cli` needs
    the scratch home, the fake `PATH` and the plugin data root, and those are built from this
    function's locals. It runs before step 1 because it is the state the repository arrives in.
    """
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    machine = tmp_path / "config" / "stayfixed" / "config.toml"
    machine.parent.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    _fake_binaries(bin_dir)

    root = _project(tmp_path, mode="overlay", initialised=initialised)
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    # Where `setup --overlay <path>` renders it: a path that names nothing yet.
    overlay = overlays / "stayfixed-private"
    store = overlay / PROJECTS / PROJECT / "memory"
    walk = Walkthrough(root, overlay, machine, home, data, store, bin_dir)

    def step(*argv: str) -> subprocess.CompletedProcess[str]:
        done = _cli(walk, *argv)
        assert done.returncode == 0, f"`{' '.join(argv)}`: {done.stderr}"
        return done

    # 0. the project footprint, on the repository that came with notes and a history. `init`
    # adopts the `stayfixed.toml` already there without rewriting it (a `Kind.ONCE` artifact
    # whose file is present is skipped), so the document above is still the document below,
    # and the manifest is the witness that the footprint pass ran.
    if initialised:
        step("init", "--yes", "--root", str(root), "--machine", str(machine))
        assert (root / ".stayfixed" / "manifest.json").is_file(), "`init` recorded no manifest"
    # 1-3. the machine layer, into a scratch machine file and a scratch home. **Two runs**, as
    # the walkthrough had before it was converted: the first writes the machine file with no
    # overlay in it, the second renders the overlay from the shipped template with no network
    # call and records it into a file that already exists. "A second `setup`
    # records an overlay the first did not" is a merge seam between two areas, and collapsing
    # the two runs into one would have left it to `tests/setup/` alone -- which is the shape of
    # gap this whole module exists to close. The assertion between them is what makes it a
    # seam rather than two commands that happened to run.
    step(
        "setup",
        "--preset",
        "recommended",
        "--home",
        str(home),
        "--machine",
        str(machine),
    )
    assert str(overlay) not in machine.read_text(encoding="utf-8"), (
        "the first `setup` named no overlay and must have recorded none"
    )
    step(
        "setup",
        "--preset",
        "recommended",
        "--home",
        str(home),
        "--machine",
        str(machine),
        "--overlay",
        str(overlay),
    )
    assert str(overlay) in machine.read_text(encoding="utf-8"), (
        "the second `setup` recorded the overlay into the file the first one wrote"
    )
    assert (overlay / ".git" / "HEAD").is_file(), "`setup` rendered no repository at the overlay"
    if not attach:
        return walk
    # 4. attach: the diff first, then the write. `--check` writes nothing and prints what the
    # `--yes` run is consenting to, which is the order the attach skill walks.
    if initialised:
        # The owner's own act: the notes move into this project's share of the overlay, which the
        # composed store reads. No command does this.
        store.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root / "docs" / "memory" / "project-stable"), str(store / "project-stable"))
    previewed = step("attach", "--store", str(store), "--check", "--machine", str(machine))
    assert previewed.stdout.strip(), "`attach --check` printed no diff to consent to"
    step("attach", "--store", str(store), "--machine", str(machine))
    if initialised:
        # Step 5 already happened, by the owner's hand: the moved note *is* the standing rule,
        # once promoted, as step 6 promotes it below.
        step("memory", "promote", "--changed", "--machine", str(machine))
        return walk

    # 5. a standing rule in this project's own share of the overlay.
    #
    # `project-stable` and not `developer`: `memory.store.COMMON_GROUP` is `developer`, so that
    # name resolves to `<overlay>/common/memory`, which is shared across every project. A note
    # written under `projects/<name>/memory/developer/` is linked by nothing and arrives
    # nowhere — which is the seam this walkthrough found first.
    note = store / "project-stable" / "no-force-push.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(NOTE, encoding="utf-8")
    # 6. the owner promotes it: a note counts as a standing rule only once promoted.
    step("memory", "promote", "--changed", "--machine", str(machine))
    return walk


def _session(
    walk: Walkthrough, *argv: str, machine: bool = True
) -> subprocess.CompletedProcess[str]:
    """One `hooks.json` entry, run the way a harness runs it: through the wrapper, raw.

    `HOME` and `--machine` both point into the scratch tree, so nothing here can read the
    developer's own `~/.claude` or `~/.config/stayfixed`.

    `machine=False` for `stayfixed hook <event>`, which takes no such flag: the dispatcher hands
    every handler `machine=None` on purpose, so a handler reads `<HOME>/.config/stayfixed/` and
    nothing a session can name. `HOME` above is what keeps that inside the scratch tree, and a
    caller that wants the hook path to see a machine file puts one there.
    """
    env = developer_free_environ()
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(walk.root)
    env["CLAUDE_PLUGIN_DATA"] = str(walk.data)
    env["HOME"] = str(walk.home)
    flags = ["--machine", str(walk.machine)] if machine else []
    return subprocess.run(
        [str(WRAPPER), *argv, *flags],
        cwd=walk.root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _bundle(walk: Walkthrough, bundle: str, part: int = 1) -> subprocess.CompletedProcess[str]:
    return _session(walk, "memory", "session-context", "--bundle", bundle, "--part", str(part))


def _doctor_env(walk: Walkthrough) -> dict[str, str]:
    """The environment a harness session has: a data root, and neither ignored variable."""
    # `HOME` is here because `doctor`'s `wrapper` check hands this environment to a real
    # subprocess: without it the wrapper's `stayfixed --version` builds the default machine path
    # out of the developer's own home directory, which is a read this suite does not make.
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(walk.home),
        "CLAUDE_PLUGIN_ROOT": str(ROOT),
        "CLAUDE_PLUGIN_DATA": str(walk.data),
    }


def test_setup_then_overlay_then_attach_then_a_session_sees_memory(tmp_path: Path) -> None:
    # The whole path, in the order a person walks it, ending where it is supposed to end: the
    # rule the owner wrote in their overlay arrives in a session's context.
    #
    # RAW, with no JSON envelope, which is the invariant the bundle's cap margin turns on: `memory
    # session-context` prints the text itself, so `bundles.CAP_MARGIN` is additive rather than
    # fighting an envelope's own escaping.
    walk = _install_path(tmp_path)
    done = _bundle(walk, "standing-rules")
    assert done.returncode == 0, done.stderr
    assert RULE_BODY in done.stdout
    assert not done.stdout.lstrip().startswith("{")
    assert '"summary"' not in done.stdout
    # The fakes on `PATH` were what ran, and `gh` was not among them: `--local` renders the
    # shipped template and touches no network, so a `gh` line here would mean the walkthrough
    # took the `--template` branch and only looked as if it had not.
    calls = (walk.bin / "calls.log").read_text(encoding="utf-8").splitlines()
    assert "pre-commit install" in calls
    assert not [line for line in calls if line.startswith("gh ")], calls


def test_the_machine_file_is_the_only_thing_that_says_where_the_overlay_is(
    tmp_path: Path,
) -> None:
    # The machine file is the only record of the overlay root, end to end. `setup` wrote the root
    # and `attach` read it back; nothing on a command line chose it. The vacuity guard for the
    # walkthrough above: a session that resolved a store without the machine file would pass that
    # test for the wrong reason.
    walk = _install_path(tmp_path)
    assert str(walk.overlay) in walk.machine.read_text(encoding="utf-8")
    env = developer_free_environ()
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(walk.root)
    env["HOME"] = str(walk.home)
    without = subprocess.run(
        [str(WRAPPER), "memory", "session-context", "--bundle", "standing-rules"],
        cwd=walk.root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert RULE_BODY not in without.stdout
    # Non-vacuous: the run has to fail for *this* reason, and not for any other. The
    # wrapper degrades open, so the exit code says nothing and stderr says everything.
    assert "no overlay root is recorded" in without.stderr


def test_the_bundle_arrives_whole_and_within_the_platform_cap(tmp_path: Path) -> None:
    # The end-to-end form of the bundle's invariant: what one `hooks.json` entry emits must fit the
    # platform's own cap, because anything above it is truncated by the harness and a truncated
    # block is a block that arrives half-said.
    #
    # `trust.wrap`'s two region markers are not asserted here. On a standing rule there are none
    # and there must not be: the note is the owner's own, promoted in step 6, and
    # `bundles.blocks` wraps only an unreviewed note — so that assertion cannot hold on this
    # walkthrough, and the shape where it does hold is the test below.
    walk = _install_path(tmp_path)
    done = _bundle(walk, "standing-rules")
    config = load(walk.root, machine=walk.machine)
    assert done.stdout
    assert len(done.stdout) <= config.native_caps.hook_output_chars
    assert DELIMITER not in done.stdout


def test_a_wrapped_bundle_arrives_with_both_of_its_region_markers(tmp_path: Path) -> None:
    # `trust.wrap` puts the closing nonce at the very end, so any truncation of the emitted
    # string drops it — and a region that opens and never closes is the defeat of the one
    # delimiter this project built as its boundary. It was measured arriving that way once, and
    # this is the end-to-end assertion that it does not.
    #
    # `in-repo` mode, because that is the mode in which a store is repository data and a region
    # is what wraps it: its volatile notes reach the session with no approval, as data. Same
    # wrapper, same command, same scratch machine file.
    root = _project(tmp_path, mode="in-repo")
    config_file = root / "stayfixed.toml"
    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace('"project-stable"', '"project-volatile"'),
        encoding="utf-8",
    )
    machine = tmp_path / "config" / "stayfixed" / "config.toml"
    machine.parent.mkdir(parents=True)
    notes = root / "docs" / "memory" / "project-volatile"
    notes.mkdir(parents=True)
    (notes / "no-force-push.md").write_text(NOTE, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _fake_binaries(bin_dir)
    walk = Walkthrough(root, root, machine, tmp_path / "home", tmp_path / "data", notes, bin_dir)
    done = _bundle(walk, "volatile-notes")
    assert done.returncode == 0, done.stderr
    assert RULE_BODY in done.stdout
    found = re.search(rf"{re.escape(DELIMITER)}:([0-9a-f]+)>>>", done.stdout)
    assert found is not None, done.stdout
    begin, end = markers(found.group(1))
    assert begin in done.stdout
    assert end in done.stdout
    config = load(root, machine=machine)
    assert len(done.stdout) <= config.native_caps.hook_output_chars


def test_detach_returns_the_project_to_where_it_started(tmp_path: Path) -> None:
    # The round trip over the whole path rather than over `attach`'s own ledger: snapshot every
    # file under the project root before the attach and compare after the detach. What the
    # overlay records is deliberately not on this list — `projects/<name>/project.toml` is the
    # owner's consent and outlives a detach on purpose.
    #
    # The walkthrough's own steps are repeated here rather than reused, because the snapshot has
    # to be taken between `setup` and `attach` and `_install_path` runs both.
    home = tmp_path / "home"
    machine = tmp_path / "config" / "stayfixed" / "config.toml"
    machine.parent.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    _fake_binaries(bin_dir)
    root = _project(tmp_path, mode="overlay")
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    overlay = overlays / "stayfixed-private"
    store = overlay / PROJECTS / PROJECT / "memory"
    walk = Walkthrough(root, overlay, machine, home, tmp_path / "plugin-data", store, bin_dir)

    def step(*argv: str) -> None:
        done = _cli(walk, *argv)
        assert done.returncode == 0, f"`{' '.join(argv)}`: {done.stderr}"

    step(
        "setup",
        "--preset",
        "recommended",
        "--home",
        str(home),
        "--machine",
        str(machine),
        "--overlay",
        str(overlay),
    )
    before = snapshot(root)
    # The walk's own non-vacuity guard: `snapshot` is a walk, so the comparison below passes
    # vacuously the day the walk stops finding anything.
    assert before
    step("attach", "--store", str(store), "--machine", str(machine))
    assert_snapshot_changed(root, before)
    step("detach")
    assert_snapshot_unchanged(root, before)


def test_doctor_is_green_on_the_attached_fixture(tmp_path: Path) -> None:
    # Green meaning: no `red`, and the only `skip` is `ci-ref`, which skips on a state this
    # fixture is in rather than on a limit of the build: it records no `[ci] ref`, because no
    # released tag matches the stayfixed running here for `init` to have pinned.
    walk = _install_path(tmp_path)
    rows = _doctor(walk)
    assert [row["name"] for row in rows if row["status"] == RED] == []
    assert [row["name"] for row in rows if row["status"] == SKIP] == ["ci-ref"]


# What `docs/cli.md` says `stayfixed doctor` launches on a green attached installation *besides*
# the `ci-ref` row, which the stub runner below answers in process rather than launching — so one
# more in production on a repository that records a `[ci] ref`, which is what `docs/cli.md` says.
# Written as a number rather than as a set of argv lists so the failure reads as "the count
# moved", which is the claim.
#
# Fourteen: the wrapper probe and the thirteen `git` questions the `attached`, note-store, `memory`
# and `preferences` rows ask of a bound checkout, as `docs/cli.md`'s doctor section lists them.
DOCTOR_LAUNCHES = 14


def test_doctor_launches_the_number_of_subprocesses_it_says_it_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `doctor/__init__.py` used to say "exactly two" and the true answer was four: one launch is
    # this area's own — the wrapper probe — and three more come from inside the areas its rows
    # call, where nobody counting `subprocess.run` in `doctor/` would see them. The number had
    # already moved twice during this branch's review before anyone measured it.
    #
    # This case is deliberately brittle. A row that starts asking `git` one more question moves
    # it, and that is the point: the number moving *silently* is the defect this exists for, and
    # a reader who has to update a constant has read the paragraph that states it.
    #
    # `Popen` and not `subprocess.run`: `run` is a wrapper around it, so patching the lower of
    # the two counts a caller that reached past `run` as well. `ci-ref` is not among these — it
    # goes through `stayfixed.runner.Runner`, which the stub below answers, and it is the only
    # one that would leave the machine.
    #
    # **The one test here that keeps the library seam**, and the reason is the measurement
    # itself: this counts launches through a `Popen` patched in *this* process, and a `doctor`
    # run as a subprocess launches its eight in a process no patch of ours can see. Everything
    # else in this module runs the launcher; this cannot, and says so.
    walk = _install_path(tmp_path)
    launched: list[list[str]] = []
    real = subprocess.Popen

    def spy(argv, *args, **kwargs):  # type: ignore[no-untyped-def]
        launched.append([str(part) for part in argv])
        return real(argv, *args, **kwargs)

    # The binding record and the render live under `HOME`, which the walkthrough's commands ran
    # under; this process reads them under its own.
    monkeypatch.setenv("HOME", str(walk.home))
    monkeypatch.setattr(subprocess, "Popen", spy)
    # The one call in this module that runs `run_checks` in this process, so it needs a runner to
    # hand it; `ci-ref`, the only row that would use one, skips on this fixture. Everything else
    # here reaches the CLI's own `subprocess_runner()` through the launcher, and the fakes
    # `_fake_binaries` writes are what answer it.
    checks = run_checks(
        walk.root,
        home=walk.home,
        machine=walk.machine,
        runner=Recorder(),
        env=_doctor_env(walk),
    )
    monkeypatch.undo()
    # The report is green first, and the checkout attached and delivered to, so a count taken
    # from a run that fell over early, or read the checkout as unbound, cannot pass.
    assert [check.name for check in checks if check.status == RED] == []
    attached = next(check for check in checks if check.name == "attached")
    assert (attached.status, attached.detail.startswith("attached; the delivery is in place;")) == (
        OK,
        True,
    ), attached
    assert len(launched) == DOCTOR_LAUNCHES, launched
    # And they are the fourteen the paragraph names, not fourteen of something else: one wrapper
    # probe, and thirteen `git` questions. Asserted by shape rather than by full argv, because
    # each `git` call carries the temporary checkout or overlay it asks about.
    assert sum(1 for argv in launched if argv[0] == str(WRAPPER)) == 1
    assert sum(1 for argv in launched if argv[0] == "git") == 13


def test_init_then_the_walkthrough_ends_with_the_rule_in_a_session(tmp_path: Path) -> None:
    # The whole slice, in the order the owner walks it and on the repository shape they
    # actually have: a project with notes already in it, `stayfixed init` run over it, the notes
    # moved by hand into the overlay, the attach taken, and a session reading the moved note back
    # through the wrapper.
    #
    # What would break it: leave the composed store unread and `RULE_BODY` never reaches the
    # bundle; remove `init`'s footprint and the manifest assertion fails; let any row go red —
    # `overlay-requires`, the last, is the one this branch added and it is answered here against
    # a real overlay rather than a stub.
    walk = _install_path(tmp_path, initialised=True)
    done = _bundle(walk, "standing-rules")
    assert done.returncode == 0, done.stderr
    assert RULE_BODY in done.stdout
    rows = _doctor(walk)
    assert not [row for row in rows if row["status"] == RED]
    assert (walk.root / ".stayfixed" / "manifest.json").is_file()


def test_a_session_before_the_attach_is_told_what_is_missing(tmp_path: Path) -> None:
    # The handler through the wrapper, on the one state it exists for: initialised, not yet
    # attached. It reads the machine file the hook path reads —
    # `<home>/.config/stayfixed/config.toml` — and not the walkthrough's own, so the walkthrough's
    # file is copied there for the hook alone.
    #
    # The envelope is raw JSON with `additionalContext` inside; both constants are single lines
    # with no JSON-escaped characters, so `in` over the text is enough. Imported and never
    # respelled: a session line is the one string a reader compares against what they saw.
    #
    # What would break it: drop the line from the handler, or let the binding read as bound, and
    # the `in` fails.
    walk = _install_path(tmp_path, initialised=True, attach=False)
    hook_machine = walk.home / ".config" / "stayfixed" / "config.toml"
    hook_machine.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(walk.machine, hook_machine)
    done = _session(walk, "hook", "SessionStart", machine=False)
    assert done.returncode == 0, done.stderr
    assert NOT_ATTACHED in done.stdout


def test_detach_on_an_initialised_project_leaves_the_footprint(tmp_path: Path) -> None:
    # The ignore region's ownership, end to end. `init` recorded the `stayfixed:ignore` region as
    # the footprint's, so the detach that takes back everything `attach` added leaves that block
    # where it is — and the manifest with it, because `detach` never touches the scaffold ledger.
    #
    # What would break it: withdraw the region unconditionally and `.gitignore` loses its
    # block, so the byte comparison fails.
    walk = _install_path(tmp_path, initialised=True)
    ignore_before = (walk.root / ".gitignore").read_text(encoding="utf-8")
    # Non-vacuous: the block this asserts survives has to be there before the detach.
    assert "stayfixed:ignore" in ignore_before
    done = _cli(walk, "detach", "--root", str(walk.root))
    assert done.returncode == 0, done.stderr
    assert (walk.root / ".gitignore").read_text(encoding="utf-8") == ignore_before
    assert (walk.root / ".stayfixed" / "manifest.json").is_file()
