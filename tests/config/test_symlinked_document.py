"""A `stayfixed.toml` that is a symlink, met by every command family that loads the configuration.

There were two readers of the file: `init` went through `read_document`, which refuses a symlink,
and every other command through a plain `read_text`, which follows one. A clone's `stayfixed.toml ->
/dev/zero` then kept `bugs check` and `plan check` reading until the machine ran out of memory.
`load` now reads through `read_document`, so each family below is refused before anything is read.
The link here points at a valid document, so a reader that follows it would load it and go on: the
refusal is the only thing that can make these cases pass, and a regression cannot hang the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.config.paths import PathEscape
from tests.cli import cli
from tests.gitfixture import git, needs_git

pytestmark = needs_git

DOCUMENT = '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n'


def _linked(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    outside = tmp_path / "outside.toml"
    outside.write_text(DOCUMENT, encoding="utf-8")
    (root / CONFIG_FILE).symlink_to(outside)
    return root


def test_load_refuses_a_symlinked_stayfixed_toml(tmp_path: Path) -> None:
    # Mutation (declared): `load` reading the file with a plain `read_text` again -> it follows
    # the link and loads the document outside.
    with pytest.raises(PathEscape):
        load(_linked(tmp_path), machine=tmp_path / "absent.toml")


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["bugs", "check"], id="bugs-check"),
        pytest.param(["plan", "check"], id="plan-check"),
        pytest.param(["docs", "check"], id="docs-check"),
        pytest.param(["docs", "trail", "--check"], id="docs-trail"),
    ],
)
def test_every_command_family_refuses_a_symlinked_stayfixed_toml(
    tmp_path: Path, argv: list[str]
) -> None:
    code, out, err = cli(_linked(tmp_path), tmp_path, *argv)
    assert code == 2, err
    assert f"{CONFIG_FILE!r} passes through a symlink" in err
    assert out == ""


@pytest.mark.parametrize("target", ["regular-file", "/dev/zero"])
@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["init", "--questions"], id="init-questions"),
        pytest.param(["init", "--yes", "--dry-run", "--name", "widget"], id="init-answering"),
    ],
)
def test_init_refuses_a_symlinked_stayfixed_toml_whatever_it_points_at(
    tmp_path: Path, argv: list[str], target: str
) -> None:
    # `init`'s answer-sheet check asked `is_file()`, which follows the link: a link to a regular
    # file was refused as an answer sheet, and `--questions` over a link to `/dev/zero` read it
    # as no file and asked its questions, exit 0. Mutation (declared): the bare `is_file()`
    # again -> the regular file is refused in the answer sheet's words, `/dev/zero` exits 0.
    root = _linked(tmp_path)
    if target != "regular-file":
        (root / CONFIG_FILE).unlink()
        (root / CONFIG_FILE).symlink_to(target)
    code, out, err = cli(root, tmp_path, *argv)
    assert code == 2, err
    assert f"{CONFIG_FILE!r} passes through a symlink" in err
    assert out == ""
