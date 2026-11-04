"""stayfixed's real command line, run in this process as a person types it.

One runner for every test that drives a command through the parser, where each module carried a
copy of its own: the argv as typed, then `--root` and a `--machine` file that is not there
unless the case wrote it, so no case reads the developer's own machine configuration.
"""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from stayfixed.cli import SubParsers, build_parser, discover_registrars, run


def cli(
    root: Path, tmp_path: Path, *argv: str, machine: Path | None = None
) -> tuple[int, str, str]:
    """The exit code, standard output and standard error of `stayfixed <argv>` against `root`."""
    parser = build_parser(discover_registrars())
    flags = ["--root", str(root), "--machine", str(machine or tmp_path / "absent.toml")]
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
        code = run([*argv, *flags], parser=parser)
    return code, out.getvalue(), err.getvalue()


def subparsers(parser: argparse.ArgumentParser) -> SubParsers | None:
    """The action `parser` dispatches its commands through, or `None` for a command with none.

    Every walk over a parser's commands reaches for this, and argparse names its type privately
    (`_SubParsersAction`), so the reach is made here once: the day argparse renames it, this is
    the one line to change.
    """
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
