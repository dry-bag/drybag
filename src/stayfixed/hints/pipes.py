"""The pipe hint: a test run piped into a reader loses the run's exit status.

A pipeline's exit status is its last command's unless `pipefail` is set, so
`pytest | tail -20` exits 0 whatever pytest returned, and a red run reads as green. The agent
writes the command, so the hint names the remedy and never refuses: a refusal would be a
convenience it could spell around, and a hint costs a legitimate command nothing.

`notice_for` reads the command's TEXT alone, through `bashscan`. The notice is fixed text and
names no part of the command, so nothing a repository wrote reaches the context. It speaks when
some pipeline holds a test run (`runners.names_a_test_run`, behind `uv run` and assignments as
every hint reads a command) that is not its last command, a later command of that pipeline is
`tail`, `head` or `grep`, and the command's text names neither `pipefail` nor `PIPESTATUS`.

DEGRADES TOWARD SILENCE at every seam: a command `bashscan.tokenize` cannot read and one longer
than `bgcleanup.MAX_COMMAND_CHARS` get no hint. The bounds, recorded rather than implied:

- `|&` reads as a pipe followed by `&`, which ends the pipeline, so `pytest |& tail` gets no hint
  (`bashscan.pipelines`).
- The text is searched for `pipefail` and `PIPESTATUS`, not parsed: a mention in a comment or in
  an unrelated string silences the hint.
- A pipe inside `$(...)`, a subshell or a function body is read as part of the command's own
  pipelines, and a run launched by a program this module does not unwrap (`timeout 60 pytest`)
  is not seen.
"""

from __future__ import annotations

from pathlib import Path

from stayfixed.hints import bashscan
from stayfixed.hints.bgcleanup import MAX_COMMAND_CHARS
from stayfixed.hints.runners import names_a_test_run

# The commands that read a run's output and answer with their own status.
READERS = frozenset({"tail", "head", "grep"})

# What a command names when it keeps the run's status: the option, and the array bash fills.
_KEEPS_THE_STATUS = ("pipefail", "PIPESTATUS")

NOTICE = (
    "stayfixed: this test run is piped into tail, head or grep. Without pipefail a pipeline's "
    "exit status is its last command's, so a red run reads as green. Put `set -o pipefail;` in "
    "front of the command, or write the output to a file and read the file."
)


def _is_reader(words: list[str]) -> bool:
    return bool(words) and Path(words[0]).name in READERS


def notice_for(command: str) -> str | None:
    """`NOTICE` when `command` pipes a test run into a reader without keeping the status;
    otherwise `None`, a command that cannot be read included."""
    if len(command) > MAX_COMMAND_CHARS or any(name in command for name in _KEEPS_THE_STATUS):
        return None
    tokens = bashscan.tokenize(command)
    if tokens is None:
        return None
    for pipeline in bashscan.pipelines(tokens):
        words = [bashscan.command_words(segment, names_a_test_run) for segment in pipeline]
        for at, command_words in enumerate(words):
            if names_a_test_run(command_words) and any(_is_reader(w) for w in words[at + 1 :]):
                return NOTICE
    return None
