"""The attach area's import surface: everything another area may import from it.

A name is added when a consumer needs it, in a commit that says which; a name nothing imports may
go. No other area imports a private module of this one.

No module under `src/` outside this area imports from here; `doctor`'s `attached` row is this
area's own (`attach/doctor.py`). What is left is what the suite reads from outside the area:

- the ledger (`ledger`) and `AttachLedger`, because `ledger` returns it: a return
  type absent from this list is a value a consumer can hold and cannot declare, and
  `tests/test_surfaces.py` derives that rule rather than restating it; `Rendered`, the type of
  its `render`, for the same rule;
- the binding (`read_binding`, `Binding`). `Binding.state` is one of `memory.api`'s
  `BINDING_STATES`: the vocabulary and the one classifier that decides between its members are
  the memory area's, so this area publishes neither a copy of the set nor its own members;
- `LOCAL_SETTINGS`, the settings file the doctor area's tests write hook entries into;
- `attach` and `Attached`, which `setup --restore` runs on each checkout the overlay's projects
  file lists (`setup.restore`), and the type it returns, with `Carried`, the type of two of its
  fields (`added` and `removed`), which `tests/test_surfaces.py` derives that a surface carries.

`check` and `detach` are this area's own command module's, and their results are read where they
are returned.

The ledger's place is the core's (`binding.LEDGER_FILE`, beside the binding id), because `doctor`
reads it too; nothing outside delivery imports this area but through the crossings pinned in
`tests/boundaries/test_delivery.py`.
"""

from drybag.attach.binding import Binding, read_binding
from drybag.attach.permissions import LOCAL_SETTINGS
from drybag.attach.render import Rendered
from drybag.attach.write import Attached, AttachLedger, Carried, attach, ledger

__all__ = [
    "LOCAL_SETTINGS",
    "AttachLedger",
    "Attached",
    "Binding",
    "Carried",
    "Rendered",
    "attach",
    "ledger",
    "read_binding",
]
