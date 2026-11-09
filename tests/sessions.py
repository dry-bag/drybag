"""A `SessionConfig` for a handler or `dispatch` called in this process, the way `drybag hook`
hands one over (`src/drybag/config/session.py`): the project's configuration, or none, over the
preset's owner's layer, with no warnings. A test about the session itself builds one with
`session_config`."""

from __future__ import annotations

from pathlib import Path

from drybag.config.owner import resolve_owner
from drybag.config.schema import Config
from drybag.config.session import SessionConfig

# The owner's layer with no machine file: the preset's personal values, every guard on. A path
# where no file is, and not `None`: `None` is a machine with no home, whose reading a mutation of
# `resolve_owner` breaks, and a module every hook test imports must still import under it.
OWNER = resolve_owner(Path(__file__).with_name("no-machine-file.toml"))
# A session with no project configuration.
NO_CONFIG = SessionConfig(None, OWNER, ())


def session_of(config: Config | None) -> SessionConfig:
    """`config` as a session hands it to a handler."""
    return SessionConfig(config, OWNER, ())
