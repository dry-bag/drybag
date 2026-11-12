#!/usr/bin/env python3
"""Check the built artifacts carry what an installed drybag needs.

    uv run python scripts/check_artifacts.py dist            # the one wheel and one sdist
    uv run python scripts/check_artifacts.py rendered DIR    # what `setup --overlay DIR` left

The checkout passes every test with the template tree in place; only an artifact can say
whether `uv_build` shipped it. Exit 0 with no findings, 1 with them.

Three things this looks at, each of which was an inline CI step or nothing at all:

* **The wheel.** CI installs from source, so a packaging regression that dropped the preset,
  the overlay template or the project footprint's templates would break every `uv tool install`
  while the workflow stayed green. `resources.files` resolves to the checkout under `uv run`,
  which is why no test in `tests/` can see this.
* **The sdist.** It carries the plugin's static files and the documents beside `src/`, and no
  `tests/`, `scripts/`, `mutations/` or plans: the suite runs from a checkout of the tag. And
  `tar` preserves the mode: a wrapper unpacked at 0644 exits 126 for every hook entry.
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

from drybag.overlay.api import OVERLAY_FILES
from drybag.scaffold import MANIFEST_PATH

WHEEL_MUST = (
    "drybag/presets/recommended.toml",
    *(f"drybag/templates/overlay/{relative}" for relative in OVERLAY_FILES),
)
# What `pyproject.toml`'s `source-include` names, one file of each tree.
SDIST_MUST = ("CHANGELOG.md", "skills/README.md", "hooks/run-hook.sh", "hooks/hooks.json")
SDIST_EXECUTABLE = ("hooks/run-hook.sh",)
# Kept out by `pyproject.toml`, because PyPI keeps its copy of an sdist for good.
SDIST_MUST_NOT = ("docs/plans/", "mutations/", "tests/", "scripts/")


def check_wheel(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    return [f"wheel: missing {name}" for name in WHEEL_MUST if name not in names]


def check_sdist(path: Path) -> list[str]:
    with tarfile.open(path) as archive:
        members = {"/".join(m.name.split("/")[1:]): m for m in archive.getmembers()}
    findings = [f"sdist: missing {name}" for name in SDIST_MUST if name not in members]
    findings += [
        f"sdist: carries {tree}"
        for tree in SDIST_MUST_NOT
        if any(n.startswith(tree) for n in members)
    ]
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
