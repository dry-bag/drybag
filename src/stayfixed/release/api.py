"""The release package's import surface: everything code outside it may import from it.

What stays here is what an installed stayfixed reads about its own releases. The repository's
release tooling — the version check, the changelog and the pin — is `scripts/release.py`, which
is not shipped as a command and imports from here like any other consumer.

`Pin`, `Resolution`, `released`, `resolve_pin` and `is_released` are published for `init`, which
writes the pin, and `doctor`'s `ci-ref` row, which judges it — both ask this package because "which
commit is release X" is its own question. `released` is published so the row can ask the remote once
for the sha and the alias both. `tag_for` is published for the release script, whose `check --tag`
holds a tag to the tree's version by the same spelling the pin is looked up by, and for
`scripts/publish_plugin.py`, which holds the tag's `plugin.json` version to the tag by it. `PACKAGE`
is published with it: the name the platform's tag carries is the name the release script looks the
package up by in `uv.lock` and the marketplace entry by, and `scripts/plugin_tree.py` reads the pin
from the marketplace entry of that name, so one constant is how the three stay one name.
"""

from stayfixed.release.pins import (
    PACKAGE,
    Pin,
    Resolution,
    is_released,
    released,
    resolve_pin,
    tag_for,
)

__all__ = [
    "PACKAGE",
    "Pin",
    "Resolution",
    "is_released",
    "released",
    "resolve_pin",
    "tag_for",
]
