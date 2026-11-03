"""What `init`, `upgrade` and `uninstall` do with the footprint `project_templates` builds, before
the engine plans it.

`project.templates` builds templates from a configuration and decides nothing about a manifest.
This module is the lifecycle policy the three commands apply to what it builds: where
`[artifacts] local` may not move an artifact, which recorded artifacts a configuration retires,
and the order of the footprint pass. `prepare` applies all of it in one sequence, because the
rules arrived one entry point at a time and a command that spelled the sequence out again could
leave one behind. What it returns, `Passes`, is also the one way a command plans those passes,
for the same reason: the ownership relation and the ignore guard came to each command by hand,
and a plan made without the first passed every test but one command's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from pathlib import Path

from stayfixed.config.schema import Config
from stayfixed.errors import Refusal
from stayfixed.project.ignored import refuse_ignored
from stayfixed.project.templates import (
    CONFIG_ARTIFACT,
    IGNORE_ARTIFACT,
    Owners,
    Prepared,
    project_templates,
    retired_stub,
)
from stayfixed.scaffold import (
    Kind,
    LocalDigests,
    Plan,
    Record,
    Template,
    left_copies,
    local_copies,
    plan,
)

# Fixed text with a count: the ids `[artifacts] local` lists are repository-authored, and which
# of them matched is not printed, only how many.
LOCAL_PROFILE = (
    "[artifacts] local names {count} of the profile's artifacts, and the AGENTS.md pointer and "
    "each harness's rule read them at the path the project commits; take them out of the list"
)


def refuse_local_profile(prepared: Prepared, config: Config) -> None:
    """Refuse a footprint whose profile artifacts `[artifacts] local` would move out of git.

    The engine would write them under `.stayfixed/local/artifacts/`, while every reader of them
    names `rules_file`'s committed path, so each pointer would lead nowhere. `prepare` asks it for
    `init` and `upgrade`; not for `uninstall`, so a configuration written before the rule can
    still be taken back.
    """
    local = prepared.profiled & set(config.artifacts.local)
    if local:
        raise Refusal(LOCAL_PROFILE.format(count=len(local)))


# The artifacts that do their work only at the repository root: every command reads
# `stayfixed.toml` there, and the ignore block there is what keeps `.stayfixed/local/` out of git.
# A copy under `.stayfixed/local/artifacts/` is never read, and `uninstall` could not remove either
# one before it checks what is left under `.stayfixed/local/`, because both go after that check.
ROOT_ONLY = (CONFIG_ARTIFACT, IGNORE_ARTIFACT)
# Fixed text: the names interpolated are drawn from `ROOT_ONLY`, artifact ids this build produces,
# never from the repository-authored list.
# `can work` and `take {names} out` rather than `work` and `take them out`: one sentence that
# is grammatical for one id and for two.
LOCAL_ROOT_ONLY = (
    "[artifacts] local names {names}, which can work only at the repository root: every command "
    "reads stayfixed.toml there, and the ignore block there is what keeps .stayfixed/local/ out of "
    "git; take {names} out of [artifacts] local"
)


def refuse_local_root_only(config: Config) -> None:
    """Refuse an `[artifacts] local` list naming an artifact that only works at the root.

    `prepare` asks it for `init`, `upgrade` and `uninstall` alike, before any of them plans, so
    none of them writes or removes anything under a configuration that would keep `stayfixed.toml`
    or the ignore block out of git. For `uninstall` that is the difference between a refusal
    before any write and one part-way, since both are removed after the check of what is left
    under `.stayfixed/local/`.
    """
    named = [artifact_id for artifact_id in ROOT_ONLY if artifact_id in config.artifacts.local]
    if named:
        raise Refusal(LOCAL_ROOT_ONLY.format(names=" and ".join(named)))


# Fixed text. Raised as a `RuntimeError` rather than a stayfixed error: only a command written out
# of order reaches it, and no repository byte can.
REPLAN_FIRST = (
    "Passes.replan runs only after predict on the same Passes: predict is where the ignore "
    "guard is asked about what a command will write"
)

# The kinds that live inside a file somebody else owns.
IN_FILE = frozenset({Kind.MANAGED_REGION, Kind.KEYED_ENTRIES})


def retired_templates(
    could_write: Mapping[str, frozenset[str]], records: Mapping[str, Record], produced: Set[str]
) -> tuple[tuple[Template, ...], int]:
    """The recorded artifacts this configuration no longer produces, and how many are orphans.

    `records` is the committed manifest's. A record is retired only when its target is one
    `could_write` lists for its id: which ids exist, and which targets each could have, are this
    build's. Any other record is an orphan, counted and never touched; its id is
    repository-authored, so only the count is ever printed.

    The engine judges a retired whole file by its record (`templates.retired_stub`). **A region
    leaves as a region**, so a record whose kind says it lived inside a host file is never
    retired this way: the stub names no region, and forced, it would delete the host file and
    everything a person wrote in it. Such a record is an orphan too. A region comes out only
    through the template this build produces for it, which carries its name and comment style.
    The kind is committed, and all it can do here is turn a removal into an orphan.

    `uninstall` and `upgrade` both retire every listed one, through this one function.
    """
    retired = tuple(
        retired_stub(artifact_id, records[artifact_id].target)
        for artifact_id in sorted(records)
        if artifact_id not in produced
        and records[artifact_id].kind not in IN_FILE
        # Exact: a record at a case variant of a place is an orphan, never touched, which only
        # ever keeps a file.
        and records[artifact_id].target in could_write.get(artifact_id, frozenset())
    )
    orphans = sum(1 for artifact_id in records if artifact_id not in produced) - len(retired)
    return retired, orphans


@dataclass(frozen=True)
class Passes:
    """The two passes a command plans under one configuration, and the one way to plan them.

    `once` is the write-once pass and `footprint` the footprint pass, retirements included;
    `orphans` counts the records neither touches, and `skipped` and
    `unknown_harnesses` are what the build said about this configuration. Every plan is made
    with the ownership relation bound (`templates.Owners`), so no ledger entry under one id
    reaches another artifact's copy kept out of git in any command's plan; `predict` also asks
    the ignore guard (`ignored.refuse_ignored`) about everything it planned, and `replan` refuses
    to run on a `Passes` that `predict` has not, so every plan a command applies was predicted.
    A command that plans through this cannot leave either guard behind, which is what the next
    one to plan the footprint needs.
    """

    root: Path
    config: Config
    once: tuple[Template, ...]
    footprint: tuple[Template, ...]
    orphans: int
    skipped: dict[str, str]
    unknown_harnesses: int
    owners: Owners
    removing: bool
    # Set once `predict`'s ignore guard has passed; out of `__init__`, `__repr__`, `__eq__` and
    # `__hash__`, so a predicted `Passes` compares and hashes as it did before.
    _predicted: bool = field(default=False, init=False, repr=False, compare=False)

    def predict(self, *passes: tuple[Sequence[Template], Sequence[str]]) -> tuple[Plan, ...]:
        """Each `(templates, force)` planned, then refused as a whole when git ignores an
        existing file one of the plans would write or remove at a place a `[paths]` value chose
        (with `uninstall`'s remedy when `removing`).

        A command asks it before any write, dry run included, for every template it can apply:
        later passes re-plan the same templates at the same targets (`replan`), so these plans
        name every file the run can touch, and its refusal comes before any of them.
        """
        plans = tuple(self._plan(templates, force=force) for templates, force in passes)
        refuse_ignored(self.root, self.config, *plans, removing=self.removing)
        # Only after the guard passed, so a `predict` it refused leaves `replan` shut. `Passes`
        # is frozen, hence `object.__setattr__`.
        object.__setattr__(self, "_predicted", True)
        return plans

    def replan(self, templates: Sequence[Template], *, force: Sequence[str] = ()) -> Plan:
        """`templates` planned against the tree as it is now: after an earlier pass of the run
        wrote, what `predict` already asked the ignore guard about.

        Before `predict` has run on this `Passes` it raises `RuntimeError(REPLAN_FIRST)`: a plan
        made here asks no guard, so it is sound only for what a prediction already covered.
        """
        if not self._predicted:
            raise RuntimeError(REPLAN_FIRST)
        return self._plan(templates, force=force)

    def _plan(self, templates: Sequence[Template], *, force: Sequence[str]) -> Plan:
        """The engine's plan with the ownership relation bound; the one call to it."""
        return plan(self.root, self.config, templates, force=force, owners=self.owners)

    def left_copies(self, template: Template, digests: LocalDigests) -> tuple[str, ...]:
        """`scaffold.left_copies` under this configuration and relation."""
        return left_copies(template, self.config, digests, self.owners)

    def local_copies(self, template: Template, digests: LocalDigests) -> tuple[str, ...]:
        """`scaffold.local_copies` under this configuration and relation."""
        return local_copies(template, self.config, digests, self.owners)


def prepare(
    root: Path,
    config: Config,
    records: Mapping[str, Record],
    *,
    document: str,
    removing: bool = False,
) -> Passes:
    """The two passes a command plans at `root` under `config`, against the manifest's
    `records`.

    **The refusals, in this order, before anything is planned.** `project_templates`' own (a
    profile this build does not ship, an artifact at another artifact's file); a profile artifact
    `[artifacts] local` would keep out of git (`refuse_local_profile`), except when `removing`;
    and `stayfixed.toml` or the ignore block listed there (`refuse_local_root_only`).

    **Retirement.** Every record `retired_templates` lists is retired.
    """
    prepared = project_templates(config, document=document)
    if not removing:
        refuse_local_profile(prepared, config)
    refuse_local_root_only(config)
    produced = {t.id for t in (*prepared.once, *prepared.footprint)}
    retired, orphans = retired_templates(prepared.could_write, records, produced)
    return Passes(
        root,
        config,
        prepared.once,
        (*prepared.footprint, *retired),
        orphans,
        prepared.skipped,
        prepared.unknown_harnesses,
        prepared.owners,
        removing,
    )
