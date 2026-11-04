#!/usr/bin/env python3
"""Check the built artifacts carry what an installed stayfixed needs.

    uv run python scripts/check_artifacts.py dist            # the one wheel and one sdist
    uv run python scripts/check_artifacts.py rendered DIR    # what `setup --overlay DIR` left

The checkout passes every test with the template tree in place; only an artifact can say
whether `uv_build` shipped it. Exit 0 with no findings, 1 with them.

Three things this looks at, each of which was an inline CI step or nothing at all:

* **The wheel.** CI installs from source, so a packaging regression that dropped the preset,
  the overlay template or the project footprint's templates would break every `uv tool install`
  while the workflow stayed green. `resources.files` resolves to the checkout under `uv run`,
  which is why no test in `tests/` can see this.
* **The sdist.** A packager for Homebrew, Debian or nixpkgs cannot run a single test against
  an sdist that ships only `src/`, which is the artefact they most need to verify for a
  security-sensitive tool. `skills/` and `agents/` are here because
  `tests/skills/test_skills.py` reads those trees directly. And `tar` preserves the mode: a
  wrapper unpacked at 0644 exits 126 for every hook entry, which Claude Code reads as a
  permission error rather than as a broken install.
* **A rendered overlay.** `setup --overlay <path>` at a path that names nothing is the one working
  source for a first overlay with no network call, and what it leaves behind has to be the files
  the package ships plus the scaffold ledger — no more and no less — inside a git repository, which
  the render initialises. CI renders it through the installed wheel under a `HOME` of its own.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

from stayfixed.overlay.api import OVERLAY_FILES
from stayfixed.project.api import PROJECT_FILES
from stayfixed.scaffold import MANIFEST_PATH

# The mutation declarations, one file per group. The sdist must carry the files this checkout
# carries, globbed rather than spelled: `GROUP_OF` in `scripts/mutation_oracle.py` is the one
# place the groups are named, so a group added there ships with no edit here.
DECLARATIONS = Path(__file__).resolve().parents[1] / "mutations"

WHEEL_MUST = (
    "stayfixed/presets/recommended.toml",
    *(f"stayfixed/templates/overlay/{relative}" for relative in OVERLAY_FILES),
    # The project footprint's own tree. `init` reads it at runtime through
    # `stayfixed.templates.tree`, exactly as `setup --overlay <path>` reads the tree above, so a
    # build that dropped it would leave every installed stayfixed unable to initialise anything
    # while the checkout's own suite stayed green.
    *(f"stayfixed/templates/project/{name}" for name in PROJECT_FILES),
    # The one shipped profile. `stayfixed.profiles` reads it at runtime through
    # `importlib.resources`, like the presets, so a build that dropped it would refuse
    # `[stayfixed] profile = "python"` as unshipped on every installed stayfixed.
    "stayfixed/profiles/python/profile.toml",
    "stayfixed/profiles/python/rules.md",
    # Its code. `stayfixed.profiles.hints` finds `hygiene.py` through `importlib.resources` and
    # imports it, so a build that dropped it would leave every installed stayfixed without the
    # Python note after a failed pytest run, silently. `__init__.py` with it, so the installed
    # profile is the regular package the checkout imports.
    "stayfixed/profiles/python/__init__.py",
    "stayfixed/profiles/python/hygiene.py",
    # Its runner adapter. `stayfixed.prove.adapters` finds `adapters.py` through the same walk and
    # imports it, so a build that dropped it would answer every `stayfixed prove -- pytest` with
    # `not proven`, no adapter recognising the command.
    "stayfixed/profiles/python/adapters.py",
    # The JavaScript stack's runner adapters, jest's, vitest's and `node --test`'s, which ship no
    # profile: found by the same walk, so a build that dropped them would answer every
    # `stayfixed prove -- npx jest` with `not proven`. `__init__.py` with them, as above.
    "stayfixed/profiles/javascript/__init__.py",
    "stayfixed/profiles/javascript/adapters.py",
    # The Go stack's runner adapter, `go test`'s, likewise with no profile.
    "stayfixed/profiles/go/__init__.py",
    "stayfixed/profiles/go/adapters.py",
)
# What a downstream packager needs to verify the sdist, plus the three files the harness runs
# without an interpreter of ours.
SDIST_MUST = (
    "tests/test_fsops.py",
    "CHANGELOG.md",
    "skills/README.md",
    "agents/code-navigator.md",
    # `pyproject.toml` carries these under `hooks/**` and `scripts/**`, so this is a claim about
    # the build and not a new packaging rule.
    "hooks/run-hook.sh",
    "hooks/hooks.json",
    "scripts/stayfixed",
    *(f"mutations/{path.name}" for path in sorted(DECLARATIONS.glob("*.toml"))),
)
SDIST_EXECUTABLE = ("hooks/run-hook.sh", "scripts/stayfixed")


def check_wheel(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    return [f"wheel: missing {name}" for name in WHEEL_MUST if name not in names]


def check_sdist(path: Path) -> list[str]:
    with tarfile.open(path) as archive:
        members = {"/".join(m.name.split("/")[1:]): m for m in archive.getmembers()}
    findings = [f"sdist: missing {name}" for name in SDIST_MUST if name not in members]
    for name in SDIST_EXECUTABLE:
        member = members.get(name)
        if member is not None and member.mode & 0o111 == 0:
            findings.append(f"sdist: {name} is not executable")
    return findings


# What `git init` followed by `git symbolic-ref HEAD refs/heads/main` leaves in `.git/HEAD`.
MAIN_HEAD = b"ref: refs/heads/main\n"


def check_render(root: Path) -> list[str]:
    """The rendered tree minus its repository must be the expected files exactly.

    `setup --overlay <path>` initialises a git repository on `main` in what it renders, so
    `.git/` is part of the contract and is asked for, not merely stepped over: only a `.git` that
    is a directory is set aside from the comparison, a tree without one is a finding, and so is
    one whose `HEAD` does not name `refs/heads/main`, which is how a directory that merely has the
    name (an empty `mkdir .git`) or a repository on another branch is told apart with no
    subprocess. Anything else, a stray file beside it or in a directory that only shares its
    prefix, is compared as before.
    """
    expected = {*OVERLAY_FILES, str(MANIFEST_PATH)}
    repository = root / ".git"
    inside = repository.is_dir()
    head = repository / "HEAD"
    # Bytes, compared: a `HEAD` that is not text is a finding like any other, never a traceback.
    on_main = inside and head.is_file() and head.read_bytes() == MAIN_HEAD
    found = {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and not (inside and p.is_relative_to(repository))
    }
    return (
        ([] if inside else ["rendered: missing .git"])
        + ([] if on_main or not inside else ["rendered: .git is not a repository on main"])
        + [f"rendered: missing {n}" for n in sorted(expected - found)]
        + [f"rendered: unexpected {n}" for n in sorted(found - expected)]
    )


def main(argv: list[str]) -> int:
    if argv[:1] == ["rendered"]:
        # The length is checked inside this arm and not as part of its condition: with
        # `and len(argv) == 2` a bare `rendered` fell through to the `dist` branch, where it
        # was globbed as a directory name and answered "expected exactly one wheel and one
        # sdist under rendered" — a report about an argument the user never gave.
        if len(argv) != 2:
            print(__doc__, file=sys.stderr)
            return 2
        findings = check_render(Path(argv[1]))
    elif len(argv) == 1:
        dist = Path(argv[0])
        wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            print(
                f"expected exactly one wheel and one sdist under {dist}, "
                f"found {len(wheels)} and {len(sdists)}",
                file=sys.stderr,
            )
            return 2
        wheel, sdist = wheels[0], sdists[0]
        findings = check_wheel(wheel) + check_sdist(sdist)
        print(f"checked {wheel.name} and {sdist.name}")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for finding in findings:
        print(finding, file=sys.stderr)
    print("no findings" if not findings else f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
