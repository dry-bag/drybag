#!/usr/bin/env python3
"""Whether a pull request reaches code: what the `changes` job of `ci.yml` and `smoke.yml` writes.

    python3 -I scripts/ci_scope.py BASE HEAD

Prints `false` when every path that differs between the two commits is a document or a Python file
whose change is to comments alone, and `true` otherwise, an empty change included. `false` narrows
the run to one leg of the suite, which still runs ruff, mypy and coverage, so `# noqa`,
`# type: ignore` and `# pragma: no cover` are still judged there; the other legs, the oracle, the
demo and the plugin checks are skipped. Anything this script cannot read, or a failure of
its own, counts as code: the step it runs in fails under `bash -e`, writes no answer, and every job
reading it runs whole.

A document is a path under `docs/` or `changelog.d/`, or a Markdown file at the repository's root.
Markdown under `skills/` or `agents/` is not one: the plugin validator reads it. A Python change is
to comments alone when both sides tokenize to the same tokens once comments and blank lines are
dropped: a docstring is a string and counts as code, and a file added, deleted or that does not
tokenize counts as code.

Not a control: the script and the workflow that runs it come from the pull request, which can
rewrite either. It spares an honest change the full matrix; a reviewer reads the diff.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tokenize

DOCUMENT_DIRECTORIES = ("docs/", "changelog.d/")
DROPPED = frozenset({tokenize.COMMENT, tokenize.NL})


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], capture_output=True, check=False)  # noqa: S603, S607


def _changed(base: str, head: str) -> list[str]:
    # `--no-renames` lists a file moved into `docs/` under the name it left as well; `-z` keeps a
    # name git would otherwise quote as it is.
    done = _git("diff", "--no-renames", "--name-only", "-z", base, head)
    if done.returncode != 0:
        raise SystemExit(done.stderr.decode("utf-8", "replace"))
    return [name for name in done.stdout.decode("utf-8", "surrogateescape").split("\0") if name]


def is_document(path: str) -> bool:
    return path.startswith(DOCUMENT_DIRECTORIES) or ("/" not in path and path.endswith(".md"))


def _tokens(source: bytes) -> list[tuple[int, str]]:
    readline = io.BytesIO(source).readline
    return [(t.type, t.string) for t in tokenize.tokenize(readline) if t.type not in DROPPED]


def comments_alone(base: str, head: str, path: str) -> bool:
    before, after = _git("show", f"{base}:{path}"), _git("show", f"{head}:{path}")
    if before.returncode != 0 or after.returncode != 0:
        return False
    try:
        return _tokens(before.stdout) == _tokens(after.stdout)
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError):
        return False


def reaches_code(base: str, head: str) -> bool:
    changed = _changed(base, head)
    if not changed:
        return True
    return not all(
        is_document(path) or (path.endswith(".py") and comments_alone(base, head, path))
        for path in changed
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: ci_scope.py BASE HEAD")
    print("true" if reaches_code(*argv) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
