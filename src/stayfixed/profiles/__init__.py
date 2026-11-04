"""Stack profiles: data under this package, read the way an installed wheel can read it.

Each directory here that holds a `profile.toml` is one profile, and its `rules.md` is required
beside it. `shipped()` is the listing `scaffold.validate_sources` checks `[stayfixed] profile`
against, and `load_profile` is the one reader. A name outside the listing is refused with fixed
text: the name arrives from a repository's `stayfixed.toml`, so it is never printed.

A stack's directory may also carry code, with a profile or without one: an optional `hygiene.py`
whose `HINT` is the stack's advice after its test runner failed (`stayfixed.profiles.hints` says
what a hint answers; the command that failed decides which of them speak, and `[stayfixed]
profile` plays no part), and an optional `adapters.py` whose `ADAPTERS` are its test runners'
adapters for `prove` (`stayfixed.profiles.runners`). One walk finds all three kinds of file,
`stack_directories`, and one import loads a stack's module, `stack_module`: the listing goes
through `importlib.resources` over this package, never over a repository path, so only code
stayfixed itself ships is ever imported.

`detects` is what `init` asks: which profile a repository looks like. `evaluate` and the
`Outcome` it returns run a profile's checks against a repository. They live here because the
checks are this package's data, and a reader of them elsewhere would be a second one.
"""

from __future__ import annotations

import importlib
import tomllib
from importlib import resources
from importlib.resources.abc import Traversable
from types import ModuleType

from stayfixed.config.schema import PROJECT_NAME
from stayfixed.profiles.evaluate import Outcome, detects, evaluate
from stayfixed.profiles.model import Check, Profile, ProfileError, parse

PROFILE_FILE = "profile.toml"
RULES_FILE = "rules.md"
NOT_SHIPPED = "[stayfixed] profile names no profile this stayfixed ships"

__all__ = [
    "PROFILE_FILE",
    "RULES_FILE",
    "Check",
    "Outcome",
    "Profile",
    "ProfileError",
    "detects",
    "evaluate",
    "load_profile",
    "shipped",
    "stack_directories",
    "stack_module",
]


def _source(source: Traversable | None) -> Traversable:
    return source if source is not None else resources.files(__package__)


def stack_directories(file: str, *, source: Traversable | None = None) -> tuple[str, ...]:
    """Every directory of this package (or of `source`) that holds `file`, by name in order: the
    one walk, for a stack's profile, its red-run hint and its runner adapters alike. A directory is
    a stack's whether or not it holds a `profile.toml`; one whose name no project could have,
    `__pycache__` among them, is none."""
    root = _source(source)
    return tuple(
        sorted(
            entry.name
            for entry in root.iterdir()
            if entry.is_dir() and PROJECT_NAME.match(entry.name) and entry.joinpath(file).is_file()
        )
    )


def stack_module(name: str, module: str) -> ModuleType:
    """`stayfixed.profiles.<name>.<module>`, imported, for a `name` `stack_directories` listed.
    Importing a module runs its code, so whatever it raises reaches the caller, who decides what
    a module that does not import costs."""
    return importlib.import_module(f"{__package__}.{name}.{module}")


def shipped(*, source: Traversable | None = None) -> tuple[str, ...]:
    return stack_directories(PROFILE_FILE, source=source)


def load_profile(name: str, *, source: Traversable | None = None) -> Profile:
    if name not in shipped(source=source):
        raise ProfileError(NOT_SHIPPED)
    directory = _source(source).joinpath(name)
    try:
        document = tomllib.loads(directory.joinpath(PROFILE_FILE).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{name}/{PROFILE_FILE} is not valid TOML: {exc}") from None
    rules = directory.joinpath(RULES_FILE)
    if not rules.is_file():
        raise ProfileError(f"{name}/{RULES_FILE} is missing")
    return parse(name, document, rules.read_text(encoding="utf-8"))
