"""The setup area's import surface: everything another area may import from it.

No module imports from here but the tests.

An area that needs something absent from this list grows it deliberately, in a commit that says
which area and why — it does not import a private module of this area.

**`setup` and `SetupReport` have no importer outside this area** (`tests/test_install_path.py`
drives the argument parser), and they stay: `USER_SETTINGS` alone would leave a surface with no
exported callable or record on it, which `tests/test_surfaces.py` refuses. `SetupReport` is here
because `setup` is: a return type absent from this list is a value a caller can hold and cannot
declare.
"""

from drybag.setup.machine import USER_SETTINGS
from drybag.setup.run import SetupReport, setup

__all__ = [
    "USER_SETTINGS",
    "SetupReport",
    "setup",
]
