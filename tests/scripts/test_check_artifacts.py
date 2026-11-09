"""Nothing used to inspect a built artifact. `resources.files` resolves to the checkout under
`uv run`, so a `uv_build` change that dropped the template tree from the wheel would break
`setup --overlay <path>` for every installed user while every test stayed green."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from drybag.overlay.api import OVERLAY_FILES
from drybag.scaffold import MANIFEST_PATH
from tests.gitfixture import needs_git
from tests.runners import Recorder, real_git
from tests.scriptload import SCRIPTS, load

WHEEL_LAST = f"drybag/templates/overlay/{OVERLAY_FILES[-1]}"


def checker() -> ModuleType:
    return load(SCRIPTS / "check_artifacts.py", "check_artifacts_under_test")


def _wheel(path: Path, *, without: str | None = None) -> Path:
    """A synthetic wheel holding what `WHEEL_MUST` names; keep this list in step with it."""
    names = [
        "drybag/presets/recommended.toml",
        *(f"drybag/templates/overlay/{r}" for r in OVERLAY_FILES),
    ]
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            if name != without:
                archive.writestr(name, "x")
    return path


def _sdist(
    path: Path, module: ModuleType, *, wrapper_mode: int = 0o755, without: str | None = None
) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name in module.SDIST_MUST:
            if name == without:
                continue
            info = tarfile.TarInfo(f"drybag-0.0.0/{name}")
            info.size = 1
            info.mode = wrapper_mode if name in module.SDIST_EXECUTABLE else 0o644
            archive.addfile(info, io.BytesIO(b"x"))
    return path


def test_complete_artifacts_have_no_findings(tmp_path: Path) -> None:
    module = checker()
    assert module.check_wheel(_wheel(tmp_path / "k.whl")) == []
    assert module.check_sdist(_sdist(tmp_path / "k.tar.gz", module)) == []


def test_a_template_file_missing_from_the_wheel_is_named(tmp_path: Path) -> None:
    # Mutation: none of its own — the wheel check is a set difference; the sdist mode check
    # below carries the declared mutation.
    module = checker()
    missing = f"drybag/templates/overlay/{OVERLAY_FILES[-1]}"
    findings = module.check_wheel(_wheel(tmp_path / "k.whl", without=missing))
    assert findings == [f"wheel: missing {missing}"]


def test_a_wrapper_that_lost_its_executable_bit_in_the_sdist_is_named(tmp_path: Path) -> None:
    # `tar` preserves the mode, and a downstream packager unpacks it: a wrapper at 0644 exits
    # 126 for every hook entry, which Claude Code reads as permission.
    #
    # **The literal names, because the comparison this replaced was a tautology.** It built the
    # expected list out of `module.SDIST_EXECUTABLE` — the same tuple `_sdist` builds the
    # archive from — so `SDIST_EXECUTABLE = ()` made the fixture write every member at 0644,
    # `check_sdist` find nothing, and `[] == []` hold: measured, 5 passed with the executable
    # claim covering no file at all.
    #
    # Mutations (declared): drop the mode check; empty `SDIST_EXECUTABLE`.
    module = checker()
    findings = module.check_sdist(_sdist(tmp_path / "k.tar.gz", module, wrapper_mode=0o644))
    assert "sdist: hooks/run-hook.sh is not executable" in findings, findings
    assert "sdist: scripts/drybag is not executable" in findings, findings
    assert len(findings) == 2, findings


def test_a_member_missing_from_the_sdist_is_named(tmp_path: Path) -> None:
    # `_sdist`'s `without=` parameter existed and was passed by nothing, so the packager-facing
    # half of the gate — that `tests/`, `CHANGELOG.md`, `skills/` and `mutations/` actually
    # ship — was checked by no test.
    #
    # Mutation (declared): the missing-member finding is deleted.
    module = checker()
    findings = module.check_sdist(_sdist(tmp_path / "k.tar.gz", module, without="CHANGELOG.md"))
    assert findings == ["sdist: missing CHANGELOG.md"], findings


def test_the_sdist_must_carry_the_hook_wrapper_hooks_file_and_launcher() -> None:
    # The three files the harness runs with no interpreter of ours in front of them, spelled out
    # so a checker that drops one from its list reddens here.
    module = checker()
    assert {"hooks/run-hook.sh", "hooks/hooks.json", "scripts/drybag"} <= set(module.SDIST_MUST)
    assert "hooks/hashes.json" not in module.SDIST_MUST


def test_the_sdist_must_carry_every_mutation_group_file() -> None:
    # The group files are globbed rather than spelled, and a glob that matches nothing — a moved
    # directory, a mistyped pattern — drops the requirement without a sound: the sdist check stays
    # green over an artifact a packager cannot run the oracle from. So the checkout's own set is
    # the floor, and it is stated non-empty before it is compared.
    #
    # Mutation: the checker's pattern becomes `*.tom` -> no group file is required and the
    # comparison reddens.
    module = checker()
    required = {name for name in module.SDIST_MUST if name.startswith("mutations/")}
    declarations = SCRIPTS.parent / "mutations"
    carried = {f"mutations/{path.name}" for path in declarations.glob("*.toml")}
    assert carried  # a walk-based assertion states its walk is non-empty
    assert required == carried


def _rendered(root: Path, *, repository: bool = True) -> Path:
    """What `setup --overlay <path>` leaves: the shipped files, the manifest and a repository."""
    for relative in (*OVERLAY_FILES, str(MANIFEST_PATH)):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("x", encoding="utf-8")
    if repository:
        (root / ".git" / "hooks").mkdir(parents=True)
        (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (root / ".git" / "hooks" / "pre-commit.sample").write_text("x", encoding="utf-8")
    return root


def test_a_rendered_overlay_is_exactly_the_shipped_files_plus_the_manifest(tmp_path: Path) -> None:
    module = checker()
    root = _rendered(tmp_path / "rendered")
    # The walk is stated non-empty before anything is concluded from a difference of sets:
    # `check_render` reads `root.rglob("*")`, and a walk that found nothing is the one input
    # that can make a set comparison agree for the wrong reason.
    assert [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]
    assert module.check_render(root) == []
    (root / "extra.txt").write_text("x", encoding="utf-8")
    assert module.check_render(root) == ["rendered: unexpected extra.txt"]


@needs_git
def test_what_setup_renders_at_an_absent_overlay_path_is_what_the_check_expects(
    tmp_path: Path,
) -> None:
    # CI renders the overlay through the installed wheel's `setup --overlay <path>` and then runs
    # this check over it, so the two have to agree: rendered through `setup` here, with `git` run
    # for real and every other program recorded, the tree is exactly the shipped files, the
    # scaffold manifest and a repository on `main`.
    from drybag.setup.api import setup

    destination = tmp_path / "rendered"
    setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=Recorder(on_call=real_git),
        overlay=str(destination),
    )
    assert checker().check_render(destination) == []


def test_a_rendered_overlay_is_a_repository_and_a_tree_without_one_fails(tmp_path: Path) -> None:
    # `setup --overlay <path>` initialises a repository in what it renders, so the repository is
    # part of the contract: the check asks for `.git` and does not merely step over it. A tree
    # that is otherwise exact but has none is a render that stopped initialising.
    #
    # Mutation (declared): the missing-repository finding is deleted.
    module = checker()
    root = _rendered(tmp_path / "rendered", repository=False)
    assert module.check_render(root) == ["rendered: missing .git"]


def test_the_repository_directory_does_not_hide_an_unexpected_file_beside_it(
    tmp_path: Path,
) -> None:
    # Leaving `.git/` out of the walk must not leave out anything else: a stray file next to it,
    # or in a directory that only shares its prefix, is still an unexpected file.
    #
    # Mutation (declared): the walk skips any path whose first component starts with `.git`.
    module = checker()
    root = _rendered(tmp_path / "rendered")
    (root / ".gitx").mkdir()
    (root / ".gitx" / "stray.txt").write_text("x", encoding="utf-8")
    (root / "stray.txt").write_text("x", encoding="utf-8")
    findings = module.check_render(root)
    assert findings == ["rendered: unexpected .gitx/stray.txt", "rendered: unexpected stray.txt"]


@pytest.mark.parametrize(
    "head",
    [None, "ref: refs/heads/master\n", "0123456789abcdef0123456789abcdef01234567\n", b"\xff\n"],
    ids=["no-head", "another-branch", "detached", "not-utf8"],
)
def test_a_directory_named_git_is_not_enough_it_is_a_repository_on_main(
    tmp_path: Path, head: str | bytes | None
) -> None:
    # Any directory named `.git` passed, so an empty `mkdir .git` stood in for the repository
    # `--local` makes. `HEAD` naming `refs/heads/main` says both that it is a repository and that
    # it is on the branch the contract names, with no subprocess.
    #
    # Mutation: `mutations/`'s "the rendered-artifact check takes any directory named .git".
    module = checker()
    root = _rendered(tmp_path / "rendered", repository=False)
    (root / ".git").mkdir()
    # A `HEAD` that is not UTF-8 is a finding like any other, not a traceback out of the check.
    if isinstance(head, bytes):
        (root / ".git" / "HEAD").write_bytes(head)
    elif head is not None:
        (root / ".git" / "HEAD").write_text(head, encoding="utf-8")
    assert module.check_render(root) == ["rendered: .git is not a repository on main"]


def test_a_git_file_and_not_a_directory_is_not_the_repository(tmp_path: Path) -> None:
    # A worktree's `.git` is a file; `--local` makes a directory. A file there is a different
    # answer from the one the contract states.
    module = checker()
    root = _rendered(tmp_path / "rendered", repository=False)
    (root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert module.check_render(root) == ["rendered: missing .git", "rendered: unexpected .git"]


def test_rendered_without_a_directory_is_the_usage_message_and_not_a_dist_walk(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `rendered` on its own used to fall into the `dist` branch and be globbed as a directory
    # name, so the user was told "expected exactly one wheel and one sdist under rendered"
    # about an argument they had not given. The assertion is on which sentence comes back,
    # because both forms exit 2.
    # Mutation (declared): restore `and len(argv) == 2` in the arm's condition -> the bare
    # `rendered` falls into the `dist` branch again and the first assertion reddens.
    module = checker()
    assert module.main(["rendered"]) == 2
    printed = capsys.readouterr().err
    assert "expected exactly one wheel and one sdist" not in printed
    assert "check_artifacts.py rendered DIR" in printed


def test_the_dist_arm_reports_a_finding_and_is_clean_when_there_is_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The arm CI runs, reached by no test: `main`'s only exercised path was the usage error,
    # which returns 2 before the tail. Measured: `return 1 if findings else 0` replaced by
    # `return 0` left this module 5 passed, so both CI steps would have reported success while
    # printing their findings to stderr.
    #
    # Mutation (declared): `main`'s verdict is always 0.
    module = checker()
    dist = tmp_path / "dist"
    dist.mkdir()
    _wheel(dist / "drybag-0.0.0-py3-none-any.whl")
    _sdist(dist / "drybag-0.0.0.tar.gz", module)
    assert module.main([str(dist)]) == 0, capsys.readouterr()

    short = tmp_path / "short"
    short.mkdir()
    _wheel(short / "drybag-0.0.0-py3-none-any.whl", without=WHEEL_LAST)
    _sdist(short / "drybag-0.0.0.tar.gz", module)
    assert module.main([str(short)]) == 1
    assert f"wheel: missing {WHEEL_LAST}" in capsys.readouterr().err
