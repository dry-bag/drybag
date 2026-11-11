"""The recording `drybag.runner.Runner` doubles the suite hands the code under test.

`Recorder` answers any program from a script. A module states what its runner answers at the
call site, as keyword arguments, and keeps no private runner class of its own unless the question
it asks is not "record the argv and answer from a script":
`tests/scripts/test_publish_template.py`'s `_GitHub` (models a repository's state) is the one
that is not, and says why.

`git_that_cannot_run` is here too, though it is no `Runner`: the product runs `git` through
`gitenv.git_run` rather than a `Runner`, and a `git` that cannot be launched is a double every
module asking about one needs alike.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from drybag.runner import Completed


@dataclass(kw_only=True)
class Recorder:
    """Records every argv and working directory, and answers from a script or else the default.

    `answers` maps an argv prefix, written as its words joined by single spaces, to its answer;
    the longest key whose words equal the argv's leading elements wins, so a key of `gh` means
    "this binary" and a longer key scripts a single question — script one call by naming enough
    of its argv to tell it from its neighbours. The comparison is word for word, so an argv
    element that itself holds a space is never matched by a key. An argv no key matches gets
    `Completed(code, stdout, stderr)`.

    `on_call` runs before the answer is chosen, for a fixture that must exist by the time the code
    under test reads it — a template's files where `gh repo create --clone` would have put them.

    `local` is the names Claude Code's local scope holds: unless a key matches or `code` is set,
    `claude mcp remove` and `add-json` answer as Claude Code 2.1.319 was measured to, `remove` of
    a name it does not hold and `add-json` of one it does each with exit 1, and change it.

    `calls` and `cwds` are what the double observed, in call order, and are not parameters.
    """

    code: int = 0
    stdout: str = ""
    stderr: str = ""
    answers: dict[str, Completed] = field(default_factory=dict)
    local: set[str] = field(default_factory=set)
    on_call: Callable[[list[str], Path], None] | None = None
    calls: list[list[str]] = field(default_factory=list, init=False)
    cwds: list[Path] = field(default_factory=list, init=False)

    def launch(self, argv: list[str], cwd: Path) -> Completed:
        self.calls.append(argv)
        self.cwds.append(cwd)
        if self.on_call is not None:
            self.on_call(argv, cwd)
        chosen: tuple[int, Completed] | None = None
        for key, answer in self.answers.items():
            words = key.split(" ")
            if argv[: len(words)] == words and (chosen is None or len(words) > chosen[0]):
                chosen = (len(words), answer)
        if chosen is not None:
            return chosen[1]
        if argv[:2] == ["claude", "mcp"] and self.code == 0:
            return self._local(argv[2], argv[-1] if argv[2] == "remove" else argv[-2])
        return Completed(self.code, self.stdout, self.stderr)

    def _local(self, verb: str, name: str) -> Completed:
        if verb == "remove" and name not in self.local:
            return Completed(1, "", f'No MCP server named "{name}" in local scope')
        if verb == "add-json" and name in self.local:
            return Completed(1, "", f"MCP server {name} already exists in local config")
        (self.local.discard if verb == "remove" else self.local.add)(name)
        return Completed(0, "", "")


def git_that_cannot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `git` that cannot be launched at all, the state `gitenv.GitUnavailable` is about: a `PATH`
    with no `git` on it for `gitenv._ask`, which `git_run`, `git_answer` and `origin_remote` all
    reach it through — the one seam where a `git` is started, so every reader sees the same machine.

    Patched rather than arranged, because the alternative is removing `git` from `PATH` for the
    whole process. A repository with no `origin` remote is a different state — `git` ran and
    answered nothing — and it is the ordinary "not bound" one rather than a machine fault.
    """
    monkeypatch.setattr("drybag.gitenv.scrubbed_env", lambda: {"PATH": os.devnull})


def claude_code(main: Path, *, ignoring: tuple[str, ...] = ()) -> Callable[[list[str], Path], None]:
    """A `Recorder.on_call` that writes what Claude Code 2.1.301's local-scope plugin calls were
    measured to write into the main checkout's `.claude/settings.local.json`: `marketplace add
    <dir>` the `extraKnownMarketplaces` entry, `install <p>@<m>` the `enabledPlugins` entry,
    `uninstall` taking the latter out and `marketplace remove` both. `ignoring` names the verbs
    (`marketplace add`, `uninstall`, `marketplace remove`) whose calls change nothing, as a call
    that failed does.

    The facts `detach` reads, rather than the exit codes the `Recorder` answers: `detach` decides
    each call, and whether it may withdraw, by what the file names.
    """
    path = main / ".claude" / "settings.local.json"

    def on_call(argv: list[str], cwd: Path) -> None:
        verb = " ".join(argv[2:4]) if argv[2] == "marketplace" else argv[2]
        if argv[:2] != ["claude", "plugin"] or verb in ignoring:
            return
        document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        plugins = document.setdefault("enabledPlugins", {})
        known = document.setdefault("extraKnownMarketplaces", {})
        name = argv[4] if argv[2] == "marketplace" else argv[3]
        if verb == "marketplace add":
            source = {"source": "directory", "path": name}
            known[f"drybag-delivery-{Path(name).name}"] = {"source": source}
        elif verb == "install":
            plugins[name] = True
        elif verb == "uninstall":
            plugins.pop(name, None)
        elif verb == "marketplace remove":
            known.pop(name, None)
            for plugin in [plugin for plugin in plugins if plugin.endswith(f"@{name}")]:
                del plugins[plugin]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    return on_call


def real_git(argv: list[str], cwd: Path) -> None:
    """A `Recorder.on_call` that runs each `git` argv for real, for a case about the repository a
    command leaves behind; every other program stays recorded and answered from the script, so
    `pre-commit`, `gh` and `claude` are never launched.

    In `tests.gitfixture.env`'s sealed environment, as every fixture `git` is: inherited, the
    developer's global configuration (an `init.defaultBranch`, a template directory with hooks in
    it) shaped the repository the case judges, and a credential prompt could block the run."""
    from tests.gitfixture import env

    if argv[0] == "git":
        subprocess.run(
            argv,
            cwd=cwd,
            check=True,
            capture_output=True,
            env=env(cwd.parent),
            stdin=subprocess.DEVNULL,
        )
