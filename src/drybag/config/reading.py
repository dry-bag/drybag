"""What every reader of a configuration file shares: the refusals, the words for a document that
does not parse, the machine file's reader, and the checks of a value both layers apply.

`config.loader` reads a repository's `drybag.toml` and `config.owner` the owner's layer out of the
machine file; they meet here, below both, so a refusal is one type, a document that does not parse
is said in one set of words (`toml_position`), the machine file is read once, and a value is held
to its schema type by one rule (`coerced`) whichever layer wrote it.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import fields
from functools import cache
from pathlib import Path
from typing import Any, cast, get_origin, get_type_hints

from drybag import fsops
from drybag.config.schema import Budgets
from drybag.errors import Failure
from drybag.fsops import said

# Where `tomllib` stopped, and nothing else it had to say. Every `TOMLDecodeError` here is about a
# document somebody else wrote, and `tomllib`'s message embeds the source for several faults
# (`Cannot declare ('x',) twice`, `Duplicate inline table key 'k'`): a TOML key is arbitrary text,
# so the exception whole would put repository bytes into a refusal a skill relays to a model. The
# position suffix `tomllib` appends is drybag-shaped: two integers, or the end-of-document form.
_TOML_POSITION = re.compile(r"\((?:at line \d+, column \d+|at end of document)\)\Z")
NO_POSITION = "(at a position tomllib did not report)"
# `tomllib` reads nested arrays and inline tables by recursion, so a document nested a few
# thousand levels deep raises `RecursionError`, and an integer literal longer than the interpreter
# converts (`sys.get_int_max_str_digits`) a plain `ValueError`: neither is drybag's own defect, so
# every reader of a document somebody else wrote catches all three. `ValueError` is caught whole:
# no reader's `try` holds anything else that raises it but a decode, which it answers first.
UNPARSEABLE = (tomllib.TOMLDecodeError, RecursionError, ValueError)
TOO_DEEP = "(nested deeper than the parser reads)"
TOO_LONG = "(holds a number longer than the parser converts)"

# A named cap: every integer a configuration key holds is below it. `tomllib` converts a hex, octal
# or binary literal of any length, so a key checked only for `<= 0` could hand its reader a number
# no `str` prints or no `float` holds. 2**31, a signed 32-bit count, is far above any budget, cap
# or timeout a project writes (the preset's largest integer is `memory_index_bytes = 25600`) and
# below what every reader of one handles. No shipped file states it.
INTEGER_LIMIT = 2**31


class ConfigError(Failure):
    """A drybag.toml that cannot be trusted as written. `key` is the dotted key a refusal of one
    key is about (`memory.mode`, a section's name), `None` for the whole document: the key the NOTE
    path removes or names (`loads_noting`). Never printed, so it may be any text the document chose.
    """

    def __init__(self, message: str, *, key: str | None = None) -> None:
        super().__init__(message)
        self.key = key


# Fixed text and a path drybag chose or the owner typed, never the decoder's message.
NOT_UTF8 = "{path} is not UTF-8 text; drybag reads it only as UTF-8"
# What the error says, in `fsops.said`'s words: not its message, which repeats the path, and not
# its class's name, which names drybag's internals (`fsops.TooLarge`) and no condition.
UNREADABLE = "{path} cannot be read ({error})"


class MachineConfigError(ConfigError):
    """The **machine** file could not be read, which is not `drybag.toml`'s doing. A subclass, so
    `doctor`, which never quotes a loader message (it carries the file's own keys and values),
    tells the two files apart by type and never sends the owner to a `drybag.toml` with nothing
    wrong with it."""


def toml_position(exc: tomllib.TOMLDecodeError | RecursionError | ValueError) -> str:
    """The `(at line N, column M)` suffix `tomllib` appends, with its message text dropped: one
    extractor for every caller that reports a document it did not write (`_TOML_POSITION`).

    A suffix this cannot find is reported as absent, never as the message, so a `tomllib` that
    stopped appending one cannot take the guard with it. A document nested past the parser's
    recursion, or holding a number past the conversion limit, has no position and says so.
    """
    if isinstance(exc, RecursionError):
        return TOO_DEEP
    if not isinstance(exc, tomllib.TOMLDecodeError):
        return TOO_LONG
    found = _TOML_POSITION.search(str(exc))
    return found.group(0) if found is not None else NO_POSITION


def read_fault(
    shown: str,
    exc: OSError | tomllib.TOMLDecodeError | RecursionError | ValueError,
    effect: str,
) -> str:
    """What a file the owner wrote and a reader could not give says: `shown` (already printed),
    that it is not UTF-8, cannot be read (`fsops.said`) or is not TOML (`toml_position`), then
    `effect`, what that means to the reader, e.g. "so the project lists no tags"."""
    if isinstance(exc, UnicodeDecodeError):
        what = "is not UTF-8 text"
    elif isinstance(exc, OSError):
        what = f"cannot be read ({said(exc)})"
    else:
        what = f"is not valid TOML {toml_position(exc)}"
    return f"{shown} {what}, {effect}"


def read_machine_toml(path: Path) -> dict[str, Any] | None:
    """The machine file at `path` as `tomllib` parses it, or `None` when no file is there.

    The one reader of the file — `[personal]` here, `[overlay] root` in `config.overlay` — so every
    failure is `MachineConfigError` in one set of words, naming the error or the parser's position
    and never the parser's message. An absent file is the ordinary state before `drybag setup`.
    """
    if not fsops.is_file(path):
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise MachineConfigError(NOT_UTF8.format(path=path)) from None
    except OSError as exc:
        raise MachineConfigError(UNREADABLE.format(path=path, error=said(exc))) from None
    try:
        return tomllib.loads(text)
    except UNPARSEABLE as exc:
        raise MachineConfigError(f"{path} is not valid TOML {toml_position(exc)}") from None


@cache
def schema_types(cls: type[Any]) -> dict[str, Any]:
    """Real type objects for a schema class, resolved once per process: under
    `from __future__ import annotations` `field.type` is only the source string, and dispatching on
    it would make `float`, `int | None` or an alias "must be a string". Resolving costs an `eval`
    per annotation, hence the cache."""
    hints = get_type_hints(cls)
    return {f.name: hints[f.name] for f in fields(cls)}


def table_types(cls: type[Any]) -> dict[str, Any]:
    """The keys a table of the schema class `cls` holds and the type `coerced` holds each value to:
    `Budgets` is a table of named integers (`Budgets.NAMES`), and every other class's keys are its
    fields. One answer for both layers, so a budget the project file may set and one the machine
    file may set are the same names."""
    if cls is Budgets:
        return dict.fromkeys(Budgets.NAMES, int)
    return schema_types(cast(Any, cls))


# What `coerced` says of a value its schema type does not take: the key, never the layer's value.
NOT_A_LIST = "{key} must be a list of strings"
NOT_A_SWITCH = "{key} must be true or false"
NOT_A_STRING = "{key} must be a string"
UNSUPPORTED_TYPE = (
    "{key} has an unsupported schema type: {label}; the loader coerces tuple[str, ...], bool, int "
    "and str"
)


def coerced(key: str, annotation: Any, value: object) -> Any:
    """`value` as the schema type `annotation` holds it; a `ConfigError` naming `key` otherwise.
    Keyed on the type `schema_types` resolved, never on the table the key sits in, so both layers
    hold a value to one rule. An annotation none of the four branches spells is drybag's own
    defect, and its refusal is the whole document's, so it carries no key."""
    if get_origin(annotation) is tuple:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(NOT_A_LIST.format(key=key), key=key)
        return tuple(value)
    if annotation is bool:
        if not isinstance(value, bool):
            raise ConfigError(NOT_A_SWITCH.format(key=key), key=key)
        return value
    if annotation is int:
        return positive(key, value)
    if annotation is str:
        if not isinstance(value, str):
            raise ConfigError(NOT_A_STRING.format(key=key), key=key)
        return value
    label = getattr(annotation, "__name__", None) or str(annotation)
    raise ConfigError(UNSUPPORTED_TYPE.format(key=key, label=label))


def positive(key: str, value: object) -> int:
    """`value` when it is a positive integer below `INTEGER_LIMIT`; a `ConfigError` naming `key`
    otherwise. Never the value: a number that large is the one no message could print."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key} must be a positive integer", key=key)
    if value >= INTEGER_LIMIT:
        raise ConfigError(f"{key} must be a positive integer below {INTEGER_LIMIT:,}", key=key)
    return value
