"""Where `uv run` stops and the command it launches starts, for `bashscan.read_launch`, and the
directory uv runs that command in, for `prove`.

uv is one stack's launcher, and this module is where the shared scanner keeps it, so the scanner
itself names no stack (`tests/test_language_neutral.py` pardons this file for that reason). None
of uv's option grammar is read but `--directory`: the command starts at the first word after
`run` that the caller recognises (`bashscan.read_launch`), and every word before it is the
launcher's, handed to uv as typed. It never runs uv.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

_UV = "uv"
_UV_RUN = "run"
# The global option that moves the directory uv runs the program in, and the variable it reads
# where no option names one (`run_directory`).
_DIRECTORY = "--directory"
WORKING_DIR = "UV_WORKING_DIR"


def is_launcher(name: str) -> bool:
    """Whether a command's program, by its bare name, is uv."""
    return name == _UV


def past_run(segment: Sequence[str], index: int) -> int | None:
    """Where the words after `run` start in `segment`, read from `index`, just past the word `uv`
    (`is_launcher`); `None` where no `run` follows, a uv command that launches nothing."""
    if _UV_RUN not in segment[index:]:
        return None
    return segment.index(_UV_RUN, index) + 1


def run_directory(launcher: Sequence[str], cwd: Path, environ: Mapping[str, str]) -> Path:
    """The directory the command behind `launcher` runs in, typed in `cwd` under `environ`.

    `launcher` is the launcher's words a reading of a command found (`bashscan.Launch`): each
    `uv` and the words up to the next. Each `uv` in turn changes to the directory its
    `--directory` names, else to the run's `UV_WORKING_DIR`, read from the directory the one
    before it left (measured on uv 0.12.19: either moves the program's working directory, the
    option winning over the variable, a relative one read from where uv starts, and a `uv run`
    that a `uv run` launches reads its own from where the outer one moved to; `--project` and
    `UV_PROJECT` move no directory). `cwd` where none moves it. The path is joined and never
    looked at: whether it names a directory is the caller's to ask, and where it names none uv
    runs nothing.
    """
    here = cwd
    starts = [at for at, word in enumerate(launcher) if is_launcher(Path(word).name)]
    for start, end in zip(starts, [*starts[1:], len(launcher)], strict=False):
        words = launcher[start:end]
        directory = None
        for at, word in enumerate(words):
            name, equals, value = word.partition("=")
            if name == _DIRECTORY:
                directory = value if equals else _value(words, at)
        moved = directory if directory is not None else environ.get(WORKING_DIR)
        if moved is not None:
            here = here / moved
    return here


def _value(words: Sequence[str], index: int) -> str | None:
    """The word after `words[index]`, an option's spaced value; `None` at the end."""
    return words[index + 1] if index + 1 < len(words) else None
