"""The floor the suite puts under every `git` the product runs, in a test's own process and in
every `drybag` a test starts as a separate one.

`tests/conftest.py` sets `gitenv.FLOOR_VARIABLE` in this process's environment for every test.
A spawner that starts from `os.environ` takes `developer_free_environ()`, which drops the
developer's own harness and drybag variables and keeps the floor, so it cannot get the one
without the other. A spawner that builds its child's environment from nothing adds
`floor_env()`. A test about a bound running out removes the variable, and its children then get
none either.
"""

from __future__ import annotations

import os

from drybag import gitenv

SUITE_GIT_FLOOR_SECONDS = 60.0

# The developer's own variables: a harness's (`CLAUDE_`, and Codex's `PLUGIN_`), drybag's, and
# the XDG base directories that move `git`'s and drybag's configuration. A child must not read
# any of them, because the machine running the suite is not the one the test is about.
DEVELOPERS = ("CLAUDE_", "PLUGIN_", "DRYBAG_", "XDG_")


def is_developers(name: str) -> bool:
    """Whether a test strips `name` from what it runs: every developer variable but the floor."""
    return name.startswith(DEVELOPERS) and name != gitenv.FLOOR_VARIABLE


def developer_free_environ() -> dict[str, str]:
    """This process's environment without the developer's own variables, floor included."""
    return {key: value for key, value in os.environ.items() if not is_developers(key)}


def floor_env() -> dict[str, str]:
    """The floor as the one environment entry a spawned `drybag` needs to inherit it."""
    value = os.environ.get(gitenv.FLOOR_VARIABLE)
    return {} if value is None else {gitenv.FLOOR_VARIABLE: value}
