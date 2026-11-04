"""`config.layout`: every location derived from `[paths]`, spelled in one module."""

from __future__ import annotations

from pathlib import Path

import pytest

from stayfixed.config.loader import loads
from stayfixed.config.paths import PathEscape
from stayfixed.config.schema import Config

DOCUMENT = '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n'


def _config(tmp_path: Path, paths: str = "") -> Config:
    text = DOCUMENT + (f"\n[paths]\n{paths}\n" if paths else "")
    return loads(text, tmp_path, machine=tmp_path / "no-machine.toml")


def test_the_stayfixed_directory_is_contained_like_every_other_path(tmp_path: Path) -> None:
    # `validate_paths` walks every `Paths` field, so the new key needs no guard of its own; this
    # proves it reached the walk. `PATH_VALUE` refuses the spelling before `contained()` runs.
    with pytest.raises(PathEscape):
        _config(tmp_path, 'stayfixed = "../elsewhere"')
