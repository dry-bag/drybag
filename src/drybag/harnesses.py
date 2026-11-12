"""Every harness drybag serves, as values in one registry.

A harness is a value, not a class: what this module states about a harness is one more value in
`HARNESSES`, and nothing that reads the registry changes. `settings` names the committed files in
which a harness reads hook entries. `drybag hook` asks `detect` which value it runs under and
shapes its stdout with that value's `render`, and nothing more: `detect` says why. A value's
`reach` gives each enforcement surface (`Surface`) its tier (`Tier`), or `None`, and the evidence
it rests on; a test holds the README's table of what each agent enforces equal to these values.

A new harness is a value with a positive `detects`, its project-root and plugin-root variables,
its `render`, its settings files and its `reach`. What follows still lives outside the registry,
spelled for Claude Code or Codex, and a harness that differs from both in any of it is an edit
there too. `tests/test_harnesses.py` holds the list to the code: every string in a module of the
package that names a harness is pardoned there, each pardon by one of these items or as prose.

- Each harness loads the plugin through a manifest of its own, `.claude-plugin/plugin.json` and
  `.codex-plugin/plugin.json`, which `scripts/release.py check` holds to one version.
- `hooks/hooks.json` keys its entries by Claude Code's event names and spells every command as
  `"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.sh"`: without that variable each command exits 127, a
  non-blocking error, and no guard runs.
- `hooks/run-hook.sh` takes the directory it enters from `CLAUDE_PROJECT_DIR`, else from `git`,
  before any Python runs (its `root=` line).
- `hooks.api.DATA_ROOT_VARIABLES` names the variables the sink and `doctor` find the harness's
  data root by.
- `doctor` runs the wrapper for its `wrapper` row under `CLAUDE`'s two root variables, with
  every variable under Claude Code's and Codex's prefixes taken out of its environment first;
  names `CLAUDE_PLUGIN_ROOT` in the remedy of the rows that find no plugin root and
  `${CLAUDE_PLUGIN_DATA}` in the `diagnostics` row's; and names Codex in the `cli-path` row.
- `setup` installs the plugin with each harness's own verbs, keyed by harness name:
  `_MARKETPLACE_ADD` and `_PLUGIN_INSTALL` in `setup/run.py`. `setup --restore` installs what the
  overlay's `machine/claude/settings.json` lists with Claude Code's verbs, by
  `install_listed` in `setup/restore.py`.
- `attach` renders the overlay's hooks, skills and agents as a Claude Code plugin and installs it
  with `PLUGIN_MARKETPLACE_ADD_LOCAL` and `PLUGIN_INSTALL_LOCAL` in `attach.render`, and `detach`
  withdraws it with `PLUGIN_UNINSTALL_LOCAL` and `PLUGIN_MARKETPLACE_REMOVE` beside them.
- `attach` delivers the overlay's MCP servers at Claude Code's local scope with
  `MCP_ADD_JSON_LOCAL` and `MCP_REMOVE_LOCAL` beside those, run by `attach.mcp`, switches outside
  servers off with `deniedMcpServers`, and `detach` names `claude mcp` where it could not take one
  back.
- The overlay spells each harness's half by name: `common/claude` and `common/codex`
  (`overlay.layout`, re-exported by `overlay.api`), and the per-project `claude` and `codex`
  directories, `.codex/rules` and the directories it creates in a project, which `attach` reads
  and writes (`attach.items`, `attach.permissions`, `attach.write`).
- `memory session-context` writes its bundle to stdout as it is, never through a `render`.
- One hook output cap, `native_caps.hook_output_chars`, is Claude Code's, applied under every one.
- `commit strip` gives way to Claude Code's `attribution.commit`, read off `CLAUDE.settings` under
  the owner's home (`guards.commit`), and its message names it.
- The advice `setup --approval-boundary` prints is Claude Code's alone: `trust.boundary` spells
  its managed-settings paths, its sandbox settings and its deny-rule grammar, and names it in the
  one sentence every writer gives a write its sandbox refused.
- The hook payload is read in Claude Code's schema (`CANONICAL`): its keys, the tool name `Bash`
  and its event names are spelled across the `hooks` package (`hooks.dispatch`, `hooks.api`,
  `hooks.sink`), in `guards` and in the areas' hook handlers.

Elsewhere, code that needs a harness fact asks this registry.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Surface(StrEnum):
    """Where drybag enforces something, by how it reaches a session."""

    # Hooks that add context and refuse nothing; the checks a project's CI runs; the skills.
    NOTICES = "session notices"
    GATES = "repository checks"
    METHOD = "skills"


class Tier(StrEnum):
    """How strongly a surface holds under a harness."""

    CONTEXT = "context only"
    CI = "CI only"
    INSTRUCTIONS = "instructions only"


@dataclass(frozen=True)
class Reach:
    """One surface under one harness."""

    # `None`: no tier is claimed, which the README's table prints as "not verified".
    tier: Tier | None
    # The observation the tier rests on and where its record is, or "unmeasured"; and the agent
    # and version it was made on, as the README cites it.
    evidence: str
    measured_on: str | None = None


@dataclass(frozen=True)
class Harness:
    name: str
    settings: tuple[str, ...]
    # Settings files a repository keeps out of git, which `doctor` walks beside `settings`.
    local_settings: tuple[str, ...]
    # The variable naming the project root, if any; every value's is asked (`detect`).
    project_dir_env: str | None
    # (event name, context for the model, notice for the person) -> stdout. Never a decision.
    render: Callable[[str, str, str], str]
    # Every `Surface` with its tier. Left out of the hash: a mapping has none.
    reach: Mapping[Surface, Reach] = field(hash=False)
    # The variable naming the plugin's own root, which `doctor` reads and sets for the wrapper.
    plugin_root_env: str
    # Positive detection, for every harness but the canonical one, which is the fallback.
    detects: Callable[[Mapping[str, str], Mapping[str, Any] | None], bool] | None = None


def hook_specific_output(event_name: str, context: str, notice: str) -> str:
    """The hook answer: the whole string a hook writes to stdout, which the harness caps.

    A hook with nothing to say answers `{}`, on every event. A context on `Stop` or `SessionEnd`
    is refused by both harnesses, and no shipped handler gives one there. `notice` goes out as
    `systemMessage`, which a person sees and the model never does
    (`hooks.dispatch.NOTICE_EVENT`); the model's copy is the caller's to put into `context`."""
    payload: dict[str, Any] = {}
    if context:
        payload["hookSpecificOutput"] = {"hookEventName": event_name, "additionalContext": context}
    if notice:
        payload["systemMessage"] = notice
    return json.dumps(payload)


def _codex_detects(env: Mapping[str, str], payload: Mapping[str, Any] | None) -> bool:
    """Codex sets `PLUGIN_ROOT` and `PLUGIN_DATA` and ALSO `CLAUDE_PLUGIN_ROOT`, so Claude Code's
    names identify nothing; its `SessionStart` stdin carries `model` and `permission_mode`. How
    far either signal can be trusted is `detect`'s to say."""
    if "PLUGIN_ROOT" in env:
        return True
    return payload is not None and {"model", "permission_mode"} <= set(payload)


CLAUDE_DIR = ".claude"
# The gates run in a project's own CI, where no agent takes part.
_IN_CI = Reach(
    Tier.CI, "unmeasured: the checks run in a project's own CI, where no agent takes part"
)
# The record the measurements below are kept in, named and not linked.
_DELIVERY_SPIKE = "the delivery spike of 2026-10-02"
# Codex's plugin hooks, which both hook surfaces rest on: no tier until drybag's own guards and
# notices are verified there end to end. An untrusted hook is skipped without a message, and
# Codex's `PostToolUse` carries no exit code for the red-run note.
_CODEX_HOOKS_UNVERIFIED = Reach(
    None,
    "a plugin hook ran once trusted in `/hooks`, and a blocking `PreToolUse` hook's reason reached "
    "the model (measured on Codex CLI 0.162.0-alpha.17.2 on 2026-10-13; the record of that "
    "measurement is not in this repository); drybag's guards and notices are not verified end "
    "to end there",
    measured_on="Codex CLI 0.162.0-alpha.17.2",
)

CLAUDE = Harness(
    name="claude",
    settings=(f"{CLAUDE_DIR}/settings.json",),
    # The file `attach` merges the overlay's hook entries into.
    local_settings=(f"{CLAUDE_DIR}/settings.local.json",),
    project_dir_env="CLAUDE_PROJECT_DIR",
    render=hook_specific_output,
    reach=MappingProxyType(
        {
            Surface.NOTICES: Reach(
                Tier.CONTEXT,
                "a SessionStart hook's output arrived as context "
                "(the spike record of 2026-09-05, the hook output cap trial)",
                measured_on="Claude Code 2.1.261",
            ),
            Surface.GATES: _IN_CI,
            Surface.METHOD: Reach(
                Tier.INSTRUCTIONS,
                f"the plugin's skills were listed ({_DELIVERY_SPIKE})",
                measured_on="Claude Code 2.1.285",
            ),
        }
    ),
    plugin_root_env="CLAUDE_PLUGIN_ROOT",
)
# Codex reads `AGENTS.md` and no other instruction file; `.codex/rules` is command-execution
# policy. drybag writes no instruction file for it.
CODEX = Harness(
    name="codex",
    settings=(".codex/hooks.json",),
    local_settings=(),
    # No variable of its own; an inherited `CLAUDE_PROJECT_DIR` names the root (`read_event`).
    project_dir_env=None,
    # Claude Code's shape, checked under Codex only as far as `_CODEX_HOOKS_UNVERIFIED` says. A
    # harness whose output differs is a different value, never a branch inside a shared one, and a
    # `render` of its own needs more
    # than a measured shape: `detect` says what.
    render=hook_specific_output,
    reach=MappingProxyType(
        {
            Surface.NOTICES: _CODEX_HOOKS_UNVERIFIED,
            Surface.GATES: _IN_CI,
            Surface.METHOD: Reach(
                Tier.INSTRUCTIONS,
                "the plugin's skills arrived, and instructions through AGENTS.md "
                f"({_DELIVERY_SPIKE})",
                measured_on="Codex CLI 0.160.0",
            ),
        }
    ),
    detects=_codex_detects,
    # Codex sets Claude Code's name for it too (`_codex_detects`).
    plugin_root_env="PLUGIN_ROOT",
)
# Claude Code's hook schema is the de-facto one, so it answers whatever no other value claims.
CANONICAL = CLAUDE
# The order the README's table and `setup` take the harnesses in.
HARNESSES: tuple[Harness, ...] = (CLAUDE, CODEX)

# The leading UTF-8 byte-order mark Claude Code reads past in its settings files.
BYTE_ORDER_MARK = "\ufeff"


def lenient_settings(text: str) -> str:
    """The text of a Claude Code settings file as Claude Code reads it: past a leading UTF-8
    byte-order mark. The one reading of it for `setup`'s merge and the commit guard alike."""
    return text.removeprefix(BYTE_ORDER_MARK)


def project_root_variables() -> tuple[str, ...]:
    """The variables a hook's project root is read from, in the order they are asked.

    `CANONICAL`'s first, then every other value's in registry order, each once: the registry's
    order is presentation, not precedence. Every value's is asked whichever was detected.
    """
    ordered = (CANONICAL, *(harness for harness in HARNESSES if harness is not CANONICAL))
    return tuple(dict.fromkeys(h.project_dir_env for h in ordered if h.project_dir_env))


def detect(env: Mapping[str, str], payload: Mapping[str, Any] | None) -> Harness:
    """The first non-canonical harness whose `detects` answers yes, else `CANONICAL`.

    Asked once, in `drybag hook`, and handed to `dispatch` alone.

    **Detection is repository-steerable, so it decides only the shape of stdout.** A committed
    `.claude/settings.json` `env` block can set `PLUGIN_ROOT`, and Claude Code's `PreToolUse`
    stdin already carries `permission_mode`. So the answer decides nothing a handler sees: every
    payload is read by the one `hooks.dispatch.read_event`, the project root comes from
    `project_root_variables` whichever value was detected, and no handler refuses a call.

    **A harness gets a `render` of its own only together with a detection signal a repository
    cannot steer**, such as the wrapper's argv: otherwise a repository could choose a shape its
    harness does not read and drop every notice. `tests/test_harnesses.py` holds every value to
    the canonical `render` until then.
    """
    for harness in HARNESSES:
        if harness.detects is not None and harness.detects(env, payload):
            return harness
    return CANONICAL
