"""What `init` does with the footprint `project_templates` builds, before the engine plans it.

`project.templates` builds templates from a configuration and decides nothing about a manifest.
This module is the policy `init` applies to what it builds: where `[artifacts] local` may not move
an artifact, and the order of the footprint pass. `prepare` applies all of it in one sequence.
What it returns, `Passes`, is also the one way a command plans those passes: the ownership
relation and the ignore guard came to each command by hand, and a plan made without the first
passed every test but one command's.
"""

from __future__ import annotations

from collections.abc import Sequence
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
)
from stayfixed.scaffold import Plan, Template, plan

# Fixed text with a count: the ids `[artifacts] local` lists are repository-authored, and which
# of them matched is not printed, only how many.
LOCAL_PROFILE = (
    "[artifacts] local names {count} of the profile's artifacts, and the AGENTS.md pointer and "
    "each harness's rule read them at the path the project commits; take them out of the list"
)


def refuse_local_profile(prepared: Prepared, config: Config) -> None:
    """Refuse a footprint whose profile artifacts `[artifacts] local` would move out of git.

    The engine would write them under `.stayfixed/local/artifacts/`, while every reader of them
    names `rules_file`'s committed path, so each pointer would lead nowhere.
    """
    local = prepared.profiled & set(config.artifacts.local)
    if local:
        raise Refusal(LOCAL_PROFILE.format(count=len(local)))


# The artifacts that do their work only at the repository root: every command reads
# `stayfixed.toml` there, and the ignore block there is what keeps `.stayfixed/local/` out of git.
# A copy under `.stayfixed/local/artifacts/` is never read.
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

    `prepare` asks it before `init` plans, so nothing is written under a configuration that would
    keep `stayfixed.toml` or the ignore block out of git.
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


@dataclass(frozen=True)
class Passes:
    """The two passes a command plans under one configuration, and the one way to plan them.

    `once` is the write-once pass and `footprint` the footprint pass; `skipped` and
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
    skipped: dict[str, str]
    unknown_harnesses: int
    owners: Owners
    # Set once `predict`'s ignore guard has passed; out of `__init__`, `__repr__`, `__eq__` and
    # `__hash__`, so a predicted `Passes` compares and hashes as it did before.
    _predicted: bool = field(default=False, init=False, repr=False, compare=False)

    def predict(self, *passes: Sequence[Template]) -> tuple[Plan, ...]:
        """Each pass's templates planned, then refused as a whole when git ignores an
        existing file one of the plans would write or remove at a place a `[paths]` value chose.

        A command asks it before any write, dry run included, for every template it can apply:
        later passes re-plan the same templates at the same targets (`replan`), so these plans
        name every file the run can touch, and its refusal comes before any of them.
        """
        plans = tuple(self._plan(templates) for templates in passes)
        refuse_ignored(self.root, self.config, *plans)
        # Only after the guard passed, so a `predict` it refused leaves `replan` shut. `Passes`
        # is frozen, hence `object.__setattr__`.
        object.__setattr__(self, "_predicted", True)
        return plans

    def replan(self, templates: Sequence[Template]) -> Plan:
        """`templates` planned against the tree as it is now: after an earlier pass of the run
        wrote, what `predict` already asked the ignore guard about.

        Before `predict` has run on this `Passes` it raises `RuntimeError(REPLAN_FIRST)`: a plan
        made here asks no guard, so it is sound only for what a prediction already covered.
        """
        if not self._predicted:
            raise RuntimeError(REPLAN_FIRST)
        return self._plan(templates)

    def _plan(self, templates: Sequence[Template]) -> Plan:
        """The engine's plan with the ownership relation bound; the one call to it."""
        return plan(self.root, self.config, templates, owners=self.owners)


def prepare(root: Path, config: Config, *, document: str) -> Passes:
    """The two passes a command plans at `root` under `config`.

    **The refusals, in this order, before anything is planned.** `project_templates`' own (a
    profile this build does not ship, an artifact at another artifact's file); a profile artifact
    `[artifacts] local` would keep out of git (`refuse_local_profile`); and `stayfixed.toml` or the
    ignore block listed there (`refuse_local_root_only`).
    """
    prepared = project_templates(config, document=document)
    refuse_local_profile(prepared, config)
    refuse_local_root_only(config)
    return Passes(
        root,
        config,
        prepared.once,
        prepared.footprint,
        prepared.skipped,
        prepared.unknown_harnesses,
        prepared.owners,
    )
