"""The initialised repository `upgrade`'s and `uninstall`'s tests start from, and how they read it.

One module rather than a copy per test file: both commands are read against the same `init`, and
two copies of the fixture would drift the way the suite's twenty-three `git` helpers once did
(`tests/gitfixture.py` says how).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
from pathlib import Path

import stayfixed
from stayfixed.config.loader import preset_defaults
from stayfixed.project.init import init
from stayfixed.scaffold import Manifest
from tests.gitfixture import git

BEFORE = "# ours, from before stayfixed\n"
# The smallest `stayfixed.toml` a test writes by hand: this build's version and a name.
DOCUMENT = f'[stayfixed]\nversion = "{stayfixed.__version__}"\n\n[project]\nname = "widget"\n'
# Every `[paths]` value that defaults under `docs/`, moved off it, so a symlinked `docs` is on no
# path the configuration uses. Derived from the preset, so a key added there is moved too.
MOVED_OFF_DOCS = {
    key: "planning/" + value.removeprefix("docs/")
    for key, value in asdict(preset_defaults("widget").paths).items()
    if value.startswith("docs/")
}


def repository(
    tmp_path: Path,
    *,
    origin: str | None = "git@github.com:owner/widget.git",
    directory: str = "widget",
) -> Path:
    """A git repository at `tmp_path / directory` holding only a README, with `origin` as its
    origin remote, or none when `origin` is `None`."""
    root = tmp_path / directory
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    if origin is not None:
        git(root, "remote", "add", "origin", origin)
    (root / "README.md").write_text(BEFORE, encoding="utf-8")
    return root


def forge_record(root: Path, artifact_id: str, *, target: str, sha256: str | None = None) -> None:
    """Rewrite one manifest record's place, and its digest when `sha256` is given, the way a
    pulled commit can."""
    manifest = Manifest.read(root)
    record = manifest.get(artifact_id)
    assert record is not None, artifact_id
    forged = replace(record, target=target, sha256=record.sha256 if sha256 is None else sha256)
    manifest.with_record(forged).write(root)


def initialised(
    tmp_path: Path,
    *,
    document: str = "",
    files: Mapping[str, str] | None = None,
) -> Path:
    """`init --yes` over a repository that already held a README, `document` as its
    `stayfixed.toml` when one is given, and each of `files` (a root-relative path and its text)
    written before `init` runs."""
    root = repository(tmp_path)
    if document:
        (root / "stayfixed.toml").write_text(document, encoding="utf-8")
    for relative, text in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    init(root, machine=tmp_path / "absent.toml", yes=True, dry_run=False)
    return root


def tree(root: Path) -> set[str]:
    """Every path under `root` but git's own, directories included, so one a run emptied and
    left behind is seen."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts}
