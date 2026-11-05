"""What every test runs under: a `HOME` of its own, so the product's own `git` reads no developer
configuration.

`tests/gitfixture.py` seals the `git` a fixture runs (`GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM`
at `os.devnull`, `GIT_CONFIG_NOSYSTEM` set, `HOME` under `tmp_path`). The `git` the product
runs is another matter: `stayfixed.gitenv.scrubbed_env` keeps `HOME` on purpose, because a real
user's global excludes and configuration are theirs to have honoured, and it drops every
`GIT_CONFIG_*` variable. So
under test that `git` read the developer's `~/.gitconfig` and `~/.config/git/ignore`: with
`CLAUDE.md` in a global excludes file, `check-ignore` answered differently and the project
tests failed by the dozen on one machine and passed on the next.

Here, rather than in the product, because the product's behaviour for a real user is right; it
is the suite that must not depend on whose machine it runs on. `HOME` points at a fresh
directory for each test and `XDG_CONFIG_HOME`, which `git` reads before `HOME/.config`, is
dropped. A test that needs a global configuration writes one into that directory. What `HOME`
cannot seal is git's system configuration, which `scrubbed_env` gives no variable to redirect;
no shipped system file carries an excludes rule.

The directory is empty but for one file: a `.gitconfig` that turns git's automatic maintenance
off, with the two keys and for the reason `tests/gitfixture.py` gives the fixture's `git`.
`scrubbed_env` drops the variables that carry them there, and `HOME` is how the same two reach
the product's `git` — a ledger `fetch` starts maintenance like a `commit` does — and every
`stayfixed` and `Runner` launch a test starts, which inherit this `HOME`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from stayfixed import gitenv
from tests.floor import SUITE_GIT_FLOOR_SECONDS
from tests.gitfixture import MAINTENANCE_OFF, gitconfig


@pytest.fixture(autouse=True)
def _git_outlasts_the_machines_load(monkeypatch: pytest.MonkeyPatch) -> None:
    # The floor under every `git` the product runs, in this process and in every `stayfixed` a
    # test starts (`tests/floor.py` says why it is an environment variable). A test about a bound
    # running out removes it and passes a small bound of its own.
    monkeypatch.setenv(gitenv.FLOOR_VARIABLE, str(SUITE_GIT_FLOOR_SECONDS))


@pytest.fixture(autouse=True)
def _a_home_of_its_own(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    home = tmp_path_factory.mktemp("home")
    (home / ".gitconfig").write_text(gitconfig(MAINTENANCE_OFF), encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    # The password database agrees with `HOME`, as on most machines (`doctor`'s `ignored-env`).
    monkeypatch.setattr("stayfixed.doctor.checks.passwd_home", lambda: home)
    return home


def _is_latin_1(name: str) -> bool:
    probe = subprocess.run(
        [sys.executable, "-c", "import locale; print(locale.getpreferredencoding(False))"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "LC_ALL": name, "PYTHONUTF8": "0"},
    )
    return probe.stdout.strip().replace("-", "").upper() in {"ISO88591", "LATIN1"}


@pytest.fixture(scope="session")
def latin1_locale() -> str:
    """A latin-1 locale name a child process can run under, or the test is skipped.

    Asked once per session and only by a test that wants it: finding one starts a child
    interpreter per candidate, which is no cost to put on every collection. macOS ships one; a
    stock Linux runner does not, so each such test is the real-locale half of a case whose
    oracle entry names a simulated one.
    """
    for name in ("en_US.ISO8859-1", "en_US.ISO-8859-1", "C.ISO-8859-1"):
        if _is_latin_1(name):
            return name
    pytest.skip("no latin-1 locale is installed here")
