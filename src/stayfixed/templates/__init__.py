"""Where the shipped template tree is.

`setup --overlay <path>` renders `overlay/`, read at runtime, so the copy that answers is the one
an installed stayfixed carries under its module root (`overlay/template.py` records why there is
no checkout fallback).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

ROOT = "templates"


def tree(name: str) -> Path:
    """The directory `stayfixed/templates/<name>/` resolves to for this installation.

    Existing or not, so a caller that cannot find the tree can name where it looked.
    """
    package = resources.files("stayfixed").joinpath(ROOT, name)
    return package if isinstance(package, Path) else Path(str(package))
