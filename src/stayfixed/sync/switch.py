"""The per-machine switch: `[sync] enabled = true` in the machine file, and nothing else.

Read by the hooks on every turn and by the job when it starts, so it never raises: a file that
cannot be read or parsed, a table that is not one and a value that is not the bool `true` all read
as off. The machine file is the owner's own, in their home; `[sync]` is machine-only
(`config.classes`), so a repository's `stayfixed.toml` cannot set it. `setup --overlay` writes it
for an overlay it makes (`setup.machine.write_machine`'s `sync`); recording an existing one leaves
it to the owner.
"""

from __future__ import annotations

from pathlib import Path

from stayfixed.config.machine import machine_config_path
from stayfixed.config.reading import MachineConfigError, read_machine_toml

SECTION = "sync"
KEY = "enabled"


def enabled(machine: Path | None = None) -> bool:
    """Whether the machine file at `machine` (the default one when `None`) switches sync on."""
    path = machine_config_path() if machine is None else machine
    if path is None:
        return False
    try:
        raw = read_machine_toml(path)
    except (MachineConfigError, OSError):
        # `fsops.is_file` raises, for a directory that cannot be searched, what the reader leaves.
        return False
    table = (raw or {}).get(SECTION)
    return isinstance(table, dict) and table.get(KEY) is True
