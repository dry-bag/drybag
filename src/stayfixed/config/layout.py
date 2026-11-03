"""Where stayfixed's own files sit inside a project, derived once from `[paths]`.

`[paths] stayfixed` is the directory stayfixed's own project files go under, so that a reader can
find them. The project's documents stay at their own
`[paths]` keys. Every other module asks this one for a derived location rather than spelling it.

A local run's default base is derived here too (`local_base`), because the three areas that
default one cannot import each other, and so are the `.gitignore` block `init` writes and the
attach ledger's path: the paths are the core's to name, and the core may not import `attach`;
the crossings still pinned are listed in `tests/boundaries/test_delivery.py`.
"""

from __future__ import annotations

from stayfixed.config.schema import Config

# Where `attach` records what it added to a project, among the local state the ignore block keeps
# out of git; `attach` itself hides it through the repository's `info/exclude`. The core names
# the path and never reads the ledger: `doctor` reports on it.
ATTACH_LEDGER = ".stayfixed/local/attach.json"
# The `.gitignore` block `init` writes as a scaffold artifact, spelled once. Its region name, the
# paths it keeps out of git — the local state, and the inventory an earlier stayfixed wrote — and
# the note above them.
IGNORE_REGION = "ignore"
LOCAL_STATE_PATHS = (".stayfixed/local/", ".stayfixed/assessment.json")
IGNORE_NOTE = "# stayfixed's local state: yours, never a collaborator's."
IGNORE_BODY = "\n".join((IGNORE_NOTE, *LOCAL_STATE_PATHS))


def rules_file(config: Config, profile: str) -> str:
    """The project-relative path of a profile's rules.

    Only a location: `scaffold.engine.validate_sources` holds `profile` to `PROJECT_NAME`, and
    `contained()` decides whether the result may be written, as it does for every target.
    """
    return f"{config.paths.stayfixed}/rules/{profile}.md"


def local_base(config: Config) -> str:
    """The base a local run compares against when none is given: the remote-tracking ref of
    `[project] base_branch`, named in full.

    One spelling for every command that defaults one — `plan check` and `test attribute` — because
    git resolves a short `origin/<b>` through `refs/tags/` first, so a tag of that spelling would
    stand in for the branch, and two spellings of one default would let two commands judge different
    commits. The loader holds the branch to `BRANCH_NAME`, so the name is one git can have.
    """
    return f"refs/remotes/origin/{config.project.base_branch}"
