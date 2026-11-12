"""What a `doctor` row is made of, and what an area hands the report to add rows of its own.

Two kinds of module speak it: the core's checks in `checks.py`, and an area's own `doctor.py`,
which `registry.contributions` discovers by name and which reaches this module through
`doctor/api.py`. So it imports nothing of any area. `REPORT_THIS` is a remedy, part of a row.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Final, Literal

from drybag.binding import main_checkout_or_none
from drybag.config.loader import read_document
from drybag.config.overlay import MachineRecord
from drybag.config.overlay import machine_record as recorded_machine_record
from drybag.config.reading import MachineConfigError
from drybag.config.schema import Config
from drybag.config.session import SessionConfig, bound_config
from drybag.errors import Failure, Refusal, resolved_or_none

OK: Final = "ok"
WARN: Final = "warn"
RED: Final = "red"
SKIP: Final = "skip"
Status = Literal["ok", "warn", "red", "skip"]
STATUSES: tuple[Status, ...] = (OK, WARN, RED, SKIP)
# The remedy of a row that is red because drybag's own code broke: nothing the reader did can
# clear it, and the command they ran is what a fix starts from.
REPORT_THIS = "report this, with the command you ran"
# The skip of a row that reads the project configuration, in a repository with none to read: no
# remedy of its own, since `not-initialised` says why there is none and what to do.
NO_CONFIG_SKIP = "there is no project configuration to check this against"


@dataclass(frozen=True)
class Check:
    """One row of the report: what was asked, what the answer was, and what to do about it.

    `remedy` is empty for a row nothing can be done about, and a `skip` is not entitled to an
    empty remedy merely for being a skip: one that reports something wrong no other row will say
    (a plugin root nothing can find, a recorded path that is not there) says what to do, and one
    that reports a measurement simply not available carries nothing. One row may have both kinds
    of arm; which rows skip, and which arms carry a remedy, is `docs/cli.md`'s census.
    """

    name: str
    status: Status
    detail: str
    remedy: str = ""


@dataclass(frozen=True)
class Row:
    """What one check answers. The name is the registry's, stamped by `checks._guarded`."""

    status: Status
    detail: str
    remedy: str = ""


@dataclass(frozen=True)
class MachineUnread:
    """`Context.overlay_root`'s answer when the machine file could not be read: whether this
    machine records an overlay is not known, which is not "it records none". `reason` is
    `config.reading.read_machine_toml`'s refusal, which never quotes the file's text; the
    `preferences` row is red on it, and a row that reads the overlay root skips without claiming
    that nothing is recorded."""

    reason: str


@dataclass(frozen=True)
class Context:
    """Everything a check may read for one report, built whole by `checks.run_checks` and never
    changed after.

    `session` is the configuration read the way a session reads it (`config.session`), and
    `config` its project configuration, `None` where there is none or it does not load: a check
    that reads it then skips with `NO_CONFIG_SKIP`. The fields are the core's; `overlay_root` is
    resolved here once because more than one area reads it. What an area owns is resolved in that
    area's own `doctor.py`, so building this imports nothing of any area.
    """

    root: Path
    home: Path | None
    machine: Path | None
    env: Mapping[str, str]
    config: Config | None
    plugin_root: Path | None = None
    # The plugin root this process can vouch for, the only one anything here executes;
    # `plugin_root` is the one the environment named. Two fields and not a flag, so the check that
    # runs the wrapper cannot reach the other answer.
    own_root: Path | None = None
    # Keyword-only and required: a report built without the session would have no owner's layer
    # to name and no way to tell a repository with no `drybag.toml` from one that fell back.
    session: SessionConfig = field(kw_only=True)

    @cached_property
    def machine_record(self) -> MachineRecord | MachineUnread | None:
        """What the machine file records, from one read: the overlay root and this machine's name
        (`config.overlay.machine_record`); `MachineUnread` when the file cannot be read or parsed,
        and `None` for any other failure (as `errors.resolved_or_none` reads one). Cached, so a
        report reads the file once however many rows ask."""
        try:
            return recorded_machine_record(self.machine)
        except MachineConfigError as exc:
            return MachineUnread(str(exc))
        except (Failure, Refusal, OSError):
            return None

    @property
    def overlay_root(self) -> Path | MachineUnread | None:
        """The overlay root the machine file records, whether or not anything is there; `None`
        when it records none or it cannot be resolved; `MachineUnread` when the machine file
        cannot be read or parsed.

        Read through `machine_record`, whose `cached_property` keeps the answer in the instance's
        `__dict__` without `__setattr__`, so a frozen dataclass can carry it, and a fresh
        `Context` is a fresh answer per report. A resolution that fails is a row's skip, never a
        red "could not run", told apart by the exception's type and never by its text.
        """
        record = self.machine_record
        if isinstance(record, MachineUnread):
            return record
        return None if record is None else record.overlay

    @property
    def machine_name(self) -> str | None:
        """This machine's name, `None` where the machine file records none or cannot be read
        (`overlay_root` says the latter); from the same read as `overlay_root`."""
        record = self.machine_record
        return None if record is None or isinstance(record, MachineUnread) else record.name

    @cached_property
    def attach_config(self) -> Config | None:
        """`config`, or, where this machine binds a checkout whose main checkout has no
        `drybag.toml`, the configuration `attach` acts on there (`config.session.bound_config`):
        the rows about what `attach` delivered judge such a checkout on what `attach` used. Every
        other case is `None`, as `config` is, and so is a resolution that fails
        (`errors.resolved_or_none`)."""
        if self.config is not None:
            return self.config

        def built() -> Config | None:
            main = main_checkout_or_none(self.root)
            if main is None or read_document(main) is not None:
                return None
            return bound_config(main, machine=self.machine, owner=self.session.owner)

        return resolved_or_none(built)


@dataclass(frozen=True)
class Contribution:
    """What an area's `doctor.py` hands the report from its `register()`: `(name, check)` pairs,
    asked after the core's own in area-name order, each through the core's guard, so one that
    raises costs its own row. A name repeated in the report costs the area its rows, as one red
    row named after the area."""

    checks: tuple[tuple[str, Callable[[Context], Row]], ...]


def configured(
    check: Callable[[Context, Config], Row], *, attach: bool = False
) -> Callable[[Context], Row]:
    """`check`, a row that reads the project configuration, asked with it where the report has one;
    where it has none the row skips with `NO_CONFIG_SKIP`, and `not-initialised` says why. With
    `attach`, a row about what `attach` delivered, the configuration is `Context.attach_config`."""

    def row(context: Context) -> Row:
        config = context.attach_config if attach else context.config
        if config is None:
            return Row(SKIP, NO_CONFIG_SKIP)
        return check(context, config)

    return row
