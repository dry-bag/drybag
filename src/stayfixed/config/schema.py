"""Typed sections of stayfixed.toml. Numbers come from the preset, never from code."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

# The future import above is load-bearing for the loader: it turns every annotation here into
# a string, which `config.reading.schema_types` resolves with `typing.get_type_hints` to decide
# how to coerce a value. Every name an annotation uses must stay resolvable from this module's
# globals at runtime, so a type imported only under `TYPE_CHECKING` would break the loader.

# The one grammar for a name stayfixed answers to: a project, a profile, an overlay owner, a
# custom gate. Each is one lowercase path segment whose leading class keeps it out of an option's
# position in an argv. Every other module derives from this spelling rather than keeping its own.
PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\Z")
# `PROJECT_NAME` in words, for every refusal a person reads: the pattern itself ends in Python's
# `\Z`, which means nothing to a reader and something else to every other regex dialect.
NAME_RULE = (
    "one lowercase path segment: lowercase letters, digits, '.', '_' and '-', led by a letter "
    "or digit"
)
# The grammar an unknown *name* in a `stayfixed.toml` must match before a refusal may print it —
# a top-level section's, and a key's inside a known table. Both are repository-authored the same
# way a `[paths]` value is, and a refusal that echoed one back would print it whole, newlines
# and all. A TOML key is arbitrary quoted
# text, so the two are one grammar and not two: every name stayfixed itself answers to — every
# schema field, every `Budgets.NAMES` entry, every section — is lowercase words joined by
# underscores, and anything else is counted rather than quoted.
SECTION_NAME = re.compile(r"^[a-z][a-z_]*\Z")
# The one grammar for a branch name stayfixed reads or writes: `[project] base_branch` and
# `release_branch`, which the loader holds to it, `[ci] gate_branch`, which a rendered workflow
# is withheld over, `--base-branch`, and a detected base branch. Each is repository-authored or
# typed, and each reaches a git ref, an output line or a YAML file GitHub executes, where quoting
# alone would still admit a newline. Inside that character set it refuses what git's own
# branch-name rules refuse (`git check-ref-format --branch`), so nothing names a branch no
# repository can have: `..`, `//`, a component starting with `.`, a component ending in `.lock`,
# a trailing `/` or `.`, and the name `HEAD` itself. `@{` and `-` at the start are outside the
# set already. The lookaheads end on `$`, which ECMA-262 reads as the end too, so
# `init --questions` can hand the pattern to a JSON Schema client.
BRANCH_NAME = re.compile(
    r"^(?!HEAD$)(?!.*\.\.)(?!.*//)(?!.*/\.)(?!.*\.lock(?:/|$))(?!.*[./]$)"
    r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z"
)
# `BRANCH_NAME` in words, for a refusal a person reads; a change to the grammar changes this.
BRANCH_RULE = (
    "letters, digits, '.', '_', '-' and '/', led by a letter or digit, and one git accepts "
    "(no '..' or '//', no component starting with '.' or ending in '.lock', no trailing '/' or "
    "'.', and not HEAD)"
)
# The built-in gates, in the order every report lists them. `[gates] builtin` chooses among them
# and `[gates.custom]` adds a project's own. The loader needs the names without importing an
# area, which is why they live here; the area that runs them pins its objects to this tuple.
BUILTIN_GATES = ("docs", "bugs", "plan", "commit", "trail")
# The configuration check: a gate runner's other verdict, and never a gate's name.
CONFIG_CHECK = "config"
# The memory modes, each spelled here and nowhere else, since the areas that read the store branch
# on them: the agent harness's own memory, where stayfixed delivers nothing, which is the mode
# where no layer chooses one; notes in the private overlay, the one mode `attach` binds; notes
# committed with the code; and notes on this machine only, under `.stayfixed/local/`.
HARNESS_MODE = "harness"
OVERLAY_MODE = "overlay"
IN_REPO_MODE = "in-repo"
LOCAL_ONLY_MODE = "local-only"
MEMORY_MODES = (HARNESS_MODE, OVERLAY_MODE, IN_REPO_MODE, LOCAL_ONLY_MODE)
CI_MODES = ("reusable", "uvx", "none")
# A commit type, the word a conventional subject starts with (`feat` in `feat(scope): …`), spelled
# once for `init`'s `--commit-type` grammar and the loader; and the same rule in words for the
# parser's refusal.
COMMIT_TYPE_WORD = "[a-z]+"
COMMIT_TYPE = re.compile(rf"\A{COMMIT_TYPE_WORD}\Z")
COMMIT_TYPE_RULE = "lowercase ASCII letters"


@dataclass(frozen=True)
class Stayfixed:
    version: str
    preset: str
    profile: str
    agents: tuple[str, ...]
    enforced: tuple[str, ...]

    @property
    def enforcing(self) -> frozenset[str]:
        """The gates that fail a run rather than annotate it: exactly the ones `enforced` names.

        Nothing fills the list, so a gate the list does not name never enforces, however the
        project configures it.
        """
        return frozenset(self.enforced)


@dataclass(frozen=True)
class Project:
    name: str
    base_branch: str
    release_branch: str


@dataclass(frozen=True)
class Paths:
    agents_md: str
    architecture: str
    runbooks: str
    adr: str
    specs: str
    plans: str
    bugs: str
    bug_index: str
    roadmap: str
    roadmap_history: str
    memory: str
    stayfixed: str

    def as_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Memory:
    """`[memory]`. `mode` is `HARNESS_MODE` where no layer sets it: the preset chooses no store, so
    a repository that never chose one keeps the harness's own memory."""

    groups: tuple[str, ...]
    index_extra: tuple[str, ...]
    mode: str = HARNESS_MODE


@dataclass(frozen=True)
class Budgets:
    """The preset's budgets and the ones a layer set (`configured`): the base branch's
    `stayfixed.toml` sets a gate's budget and the owner's machine file a session's, either way
    above the preset or below it."""

    NAMES: ClassVar[tuple[str, ...]] = (
        "agents_md_lines",
        "agents_md_words",
        "status_lines",
        "roadmap_prose_lines",
        "roadmap_prose_words",
        "memory_index_words",
        "startup_rules_words",
        "volatile_notes_words",
        "volatile_ttl_days",
    )

    preset: dict[str, int]
    configured: dict[str, int] = field(default_factory=dict)

    def effective(self, name: str) -> int:
        """The configured value when a layer set one, else the preset's."""
        if name not in self.NAMES:
            raise KeyError(name)
        if name in self.configured:
            return self.configured[name]
        return self.preset[name]


@dataclass(frozen=True)
class NativeCaps:
    """Platform limits in their own units; consumers of a bounded thing read them."""

    NAMES: ClassVar[tuple[str, ...]] = (
        "memory_index_lines",
        "memory_index_bytes",
        "hook_output_chars",
    )

    memory_index_lines: int
    memory_index_bytes: int
    hook_output_chars: int


@dataclass(frozen=True)
class Ledger:
    id_prefix: str
    code_roots: tuple[str, ...]
    evidence_boundary_required_for: tuple[str, ...]


@dataclass(frozen=True)
class Artifacts:
    local: tuple[str, ...]


@dataclass(frozen=True)
class Ci:
    mode: str
    ref: str
    gate_branch: str


@dataclass(frozen=True)
class CustomGate:
    """A project's own gate: an argv run from the project root, never a shell string."""

    run: tuple[str, ...]


@dataclass(frozen=True)
class Gates:
    """`[gates]`: which built-in gates run, and the project's own.

    `custom` has a default because the loader fills it itself, table by table, after `_build`
    has held the rest; it is the one schema field `_build` leaves out when it is absent.
    """

    builtin: tuple[str, ...]
    custom_timeout_seconds: int
    custom: Mapping[str, CustomGate] = field(default_factory=dict)


@dataclass(frozen=True)
class CommitMessages:
    attribution_check: bool
    types: tuple[str, ...]


@dataclass(frozen=True)
class Personal:
    """Machine-level parameters; never read from a repository."""

    preset: str


@dataclass(frozen=True)
class Config:
    stayfixed: Stayfixed
    project: Project
    paths: Paths
    memory: Memory
    budgets: Budgets
    native_caps: NativeCaps
    ledger: Ledger
    artifacts: Artifacts
    ci: Ci
    gates: Gates
    commit_messages: CommitMessages
    personal: Personal

    @property
    def gate_names(self) -> tuple[str, ...]:
        """The gates this project runs: its built-ins in `BUILTIN_GATES` order, then its own."""
        kept = tuple(name for name in BUILTIN_GATES if name in self.gates.builtin)
        return kept + tuple(sorted(self.gates.custom))
