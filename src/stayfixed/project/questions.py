"""What `stayfixed init` would ask, as a JSON Schema: `stayfixed init --questions`.

Ten questions, each keyed by the `stayfixed.toml` key its answer writes, but the last, `plugins`,
which `stayfixed setup` answers on the machine rather than in the repository. Each carries the
value `stayfixed init --yes` takes when it is not answered, where that value came from, the flag
that answers it, and four lines (`TRADE_OFFS`): what the answer gives, what it gives up, what it
leaves behind and how to take it back. The texts are the command's, so the `init` skill relays
them rather than writing its own. The schema is modelled on MCP elicitation's flat form schema, so
a client that drops `pattern` and the `x-stayfixed-*` keys can send it as a requested schema; an
agent harness's ask tool takes questions and options instead, so the `init` skill turns the
properties into questions: taking every default first, then the name and the base branch as one
confirmation, then the rest one at a time, in `PROPERTIES`' order, within each harness's limits.

**Nothing here carries a byte a grammar rejected.** Every default comes from `detect`, which
bounds the three repository-authored strings before it returns them, from stayfixed's own
registries, or from the preset. A name outside `[project] name`'s grammar has no default at all:
it is asked, never suggested. The machine file changes one option's title and nothing else.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from stayfixed.config.schema import (
    BRANCH_NAME,
    COMMIT_TYPE,
    HARNESS_MODE,
    IN_REPO_MODE,
    LOCAL_ONLY_MODE,
    MEMORY_MODES,
    OVERLAY_MODE,
    PROJECT_NAME,
    Config,
)
from stayfixed.project.templates import LOCAL_ELIGIBLE

# The recommended plugins' question, which no `stayfixed.toml` key answers: they are installed on
# the machine, by the command its flag names.
PLUGINS = "plugins"
# Each question's `stayfixed.toml` key, in the order the `init` skill asks them, and the flag that
# answers it: on `stayfixed init --yes`, but the plugins'.
FLAGS = {
    "project.name": "--name",
    "project.base_branch": "--base-branch",
    "memory.mode": "--memory-mode",
    "stayfixed.profile": "--profile",
    "commit_messages.attribution_check": "--attribution-check",
    "commit_messages.types": "--commit-type",
    "artifacts.local": "--local",
    "stayfixed.agents": "--agent",
    PLUGINS: "stayfixed setup --plugin",
}
PROPERTIES = tuple(FLAGS)
# What each answer gives, what it gives up, what it leaves behind and how to take it back, in that
# order: the four lines the `init` skill relays with each question. Fixed text, and stayfixed's own,
# but for the plugins' `{plugins}`, which `questions` fills with the names the question offers, so
# the line cannot name a plugin the preset no longer recommends.
TRADE_OFFS: dict[str, tuple[str, str, str, str]] = {
    "project.name": (
        "the name stayfixed calls this project by: the heading of AGENTS.md and the overlay "
        "project a later attach binds",
        "nothing",
        "[project] name in stayfixed.toml",
        "edit [project] name in stayfixed.toml",
    ),
    "project.base_branch": (
        "the branch the workflow gates and the gates compare a change against",
        "a pull request into any other branch is not gated",
        "[project] base_branch and release_branch in stayfixed.toml",
        "edit both in stayfixed.toml",
    ),
    "memory.mode": (
        "notes an agent keeps about this repository, read back at the start of a session",
        "in-repo notes are committed and read in every clone; the agent's own memory and "
        "local-only stay on this machine; an overlay is one more repository to keep",
        "[memory] mode in stayfixed.toml, and the notes wherever the mode keeps them",
        "change [memory] mode in stayfixed.toml; notes already written stay where they are",
    ),
    "stayfixed.profile": (
        "the stack's rules, in AGENTS.md and a rules file every agent reads before its first "
        "command",
        "nothing a gate enforces; the rules file is yours to edit, and an edited one is no "
        "longer refreshed",
        "[stayfixed] profile in stayfixed.toml and the profile's rules files",
        'set [stayfixed] profile = "" and run `stayfixed upgrade`, which removes the rules files '
        "you have not edited",
    ),
    "commit_messages.attribution_check": (
        "`stayfixed commit check` fails a range whose commit messages end in an AI tool's "
        "attribution trailer or footer",
        "every such trailer has to come out before a merge; the git hook `stayfixed setup "
        "--git-hooks` installs strips it as you commit, except where your own harness settings "
        "set attribution.commit to text, which the hook then leaves for `commit check` to fail",
        "[commit_messages] attribution_check in stayfixed.toml",
        "set it to false in stayfixed.toml",
    ),
    "commit_messages.types": (
        "the list records the commit types this project uses; no command reads it",
        "nothing is refused",
        "[commit_messages] types in stayfixed.toml",
        "edit the list in stayfixed.toml",
    ),
    "artifacts.local": (
        "the documents you choose stay on this machine, under .stayfixed/local/artifacts/",
        "no one else sees them: not a teammate, not CI, not another clone",
        "[artifacts] local in stayfixed.toml and the copies under .stayfixed/local/artifacts/",
        "take the id out of [artifacts] local and run `stayfixed upgrade`",
    ),
    "stayfixed.agents": (
        "each agent you use gets its own pointer at AGENTS.md and the profile's rules",
        "nothing; an agent left out still reads AGENTS.md",
        "[stayfixed] agents in stayfixed.toml and each agent's pointer files",
        "edit [stayfixed] agents and run `stayfixed upgrade`",
    ),
    PLUGINS: (
        "the plugins the recommended preset names, {plugins}, in every Claude Code session",
        "each is third-party and unpinned: whatever it ships, hooks included, runs in every "
        "session",
        "a whole machine setup outside this repository: the machine configuration file, the "
        "preset's deny rules and plugin options merged into ~/.claude/settings.json, and a "
        "user-scope plugin install in Claude Code",
        "`claude plugin uninstall <name>`",
    ),
}
TRADE_OFF_KEYS = ("get", "give_up", "trace", "undo")
SCHEMA = "https://json-schema.org/draft/2020-12/schema"
# The source of a default that nothing in the repository chose.
PRESET = "the preset's default"
MEMORY_TITLES = {
    HARNESS_MODE: "In the coding agent's own memory, which stayfixed leaves alone",
    IN_REPO_MODE: "In this repository, committed with the code",
    LOCAL_ONLY_MODE: "On this machine only, under .stayfixed/local/",
}
OVERLAY_RECORDED = "In your private overlay, which this machine records"
OVERLAY_NEXT = "In a private overlay, which the setup skill creates or records next"
# How the card shows a question with no default: one whose value could not be derived.
UNANSWERED = "none; asked"
TAIL = (
    "each is answered by the flag its line names, on `stayfixed init --yes` but the plugins'; "
    "`stayfixed init --questions --json` carries them as a JSON Schema, each with what it gives, "
    "what it gives up, what it leaves and how to undo it"
)


def ecma(pattern: re.Pattern[str]) -> str:
    """`pattern` as ECMA-262 reads it: Python's `\\Z` is a literal `Z` there, so the end anchor
    becomes `$`, which matches only at the end of the input without the multiline flag."""
    return pattern.pattern.removesuffix("\\Z") + "$"


NAME_PATTERN = ecma(PROJECT_NAME)
BRANCH_PATTERN = ecma(BRANCH_NAME)


def _overlay_recorded(machine: Path | None) -> bool:
    """Whether the machine file records an overlay; one that cannot be read or parsed reads as
    not recorded, because it only changes a title and `init` reports it when it loads it."""
    from stayfixed.config.overlay import overlay_root
    from stayfixed.errors import Failure

    try:
        return overlay_root(machine) is not None
    except Failure:
        return False


def _recommended() -> list[str]:
    """The plugins the default preset recommends, which the plugins question offers."""
    from stayfixed.presets import DEFAULT_PRESET, load_preset

    listed = load_preset(DEFAULT_PRESET).get("plugins", {}).get("recommended", [])
    return [name for name in listed if isinstance(name, str)]


def questions(root: Path, *, machine: Path | None) -> dict[str, Any]:
    """The nine questions `init` asks at `root`, as a JSON Schema object (draft 2020-12).

    Refused where `init --yes` with an answer would be (`init.precheck`): a manifest, or a
    `stayfixed.toml` that already answers them. Detection is lenient, so a name outside the
    grammar leaves `project.name` with no `default` rather than refusing the questions.
    """
    from stayfixed.config.loader import preset_defaults
    from stayfixed.harnesses import HARNESSES
    from stayfixed.profiles import shipped
    from stayfixed.project.detect import DEFAULT, detect
    from stayfixed.project.init import precheck

    precheck(root, answering=True)
    found = detect(root, lenient=True)
    preset = preset_defaults(found.name or "project")
    offered = _recommended()
    titles = {
        **MEMORY_TITLES,
        OVERLAY_MODE: OVERLAY_RECORDED if _overlay_recorded(machine) else OVERLAY_NEXT,
    }
    name: dict[str, Any] = {"type": "string", "title": "Project name", "pattern": NAME_PATTERN}
    if found.name:
        name["default"] = found.name
    properties: dict[str, dict[str, Any]] = {
        "project.name": {**name, "x-stayfixed-source": found.sources["name"]},
        "project.base_branch": {
            "type": "string",
            "title": "The branch pull requests merge into",
            "pattern": BRANCH_PATTERN,
            "default": found.base_branch,
            "x-stayfixed-source": found.sources["base_branch"],
        },
        "memory.mode": {
            "type": "string",
            "title": "Where the notes live",
            # A mode with no title is a `KeyError` here: loud, and caught by every test.
            "oneOf": [{"const": mode, "title": titles[mode]} for mode in MEMORY_MODES],
            # The preset chooses no mode, so the default is the schema's own, `harness`.
            "default": preset.memory.mode,
            "x-stayfixed-source": DEFAULT,
        },
        "stayfixed.profile": {
            "type": "string",
            "title": "Stack profile",
            "oneOf": [
                {"const": "", "title": "No profile"},
                *({"const": n, "title": n} for n in shipped()),
            ],
            "default": found.profile,
            "x-stayfixed-source": found.sources["profile"],
        },
        "commit_messages.attribution_check": {
            "type": "boolean",
            "title": "Fail a pull request whose commit messages carry an AI tool's attribution",
            "default": preset.commit_messages.attribution_check,
            "x-stayfixed-source": PRESET,
        },
        "commit_messages.types": {
            "type": "array",
            "title": "Commit types a subject may start with",
            "items": {"type": "string", "pattern": ecma(COMMIT_TYPE)},
            "minItems": 1,
            "default": list(preset.commit_messages.types),
            "x-stayfixed-source": PRESET,
        },
        "artifacts.local": {
            "type": "array",
            "title": "Files kept out of git",
            "items": {"type": "string", "enum": list(LOCAL_ELIGIBLE)},
            "default": list(preset.artifacts.local),
            "x-stayfixed-source": PRESET,
        },
        "stayfixed.agents": {
            "type": "array",
            "title": "Coding agents",
            "items": {"type": "string", "enum": [h.name for h in HARNESSES]},
            "minItems": 1,
            "default": list(found.agents),
            "x-stayfixed-source": found.sources["agents"],
        },
        PLUGINS: {
            "type": "array",
            "title": "Recommended plugins to install on this machine",
            "items": {"type": "string", "enum": offered},
            # None unasked: a third-party plugin runs in every session, so it is installed only
            # when a person names it.
            "default": [],
            "x-stayfixed-source": DEFAULT,
        },
    }
    for key, flag in FLAGS.items():
        properties[key]["x-stayfixed-flag"] = flag
        texts = TRADE_OFFS[key]
        if key == PLUGINS:
            texts = (texts[0].format(plugins=", ".join(offered)), *texts[1:])
        lines = zip(TRADE_OFF_KEYS, texts, strict=True)
        properties[key]["x-stayfixed-tradeoff"] = dict(lines)
    return {
        "$schema": SCHEMA,
        "title": "stayfixed init",
        "type": "object",
        "properties": properties,
        "required": list(PROPERTIES),
    }


def picked(config: Config) -> dict[str, Any]:
    """What a run of `init --yes` took for each question, in `PROPERTIES`' order, read off the
    configuration it wrote or adopted: `init` installs no plugin, and the agents are the harnesses
    stayfixed serves among those listed, since a name none answers to is counted, never printed."""
    from stayfixed.harnesses import select

    values: dict[str, Any] = {}
    for key in PROPERTIES:
        if key == PLUGINS:
            values[key] = []
            continue
        table, name = key.split(".")
        value = getattr(getattr(config, table), name)
        values[key] = list(value) if isinstance(value, tuple) else value
    served, _ = select(config.stayfixed.agents)
    values["stayfixed.agents"] = [harness.name for harness in served]
    return values


def _shown(question: dict[str, Any]) -> str:
    if "default" not in question:
        return UNANSWERED
    return shown(question["default"])


def shown(value: object) -> str:
    """A default or a picked value as one line prints it: a list joined, a switch on or off, and
    `none` for nothing. Every value is stayfixed's own or bounded by a grammar."""
    if isinstance(value, bool):
        return "on" if value else "off"
    text = ", ".join(map(str, value)) if isinstance(value, list | tuple) else str(value)
    return text or "none"


def card(schema: dict[str, Any]) -> str:
    """The questions as `init --questions` prints them: each default, where it came from, and
    the flag on `init --yes` that answers it."""
    lines = ["detected:"]
    for key, question in schema["properties"].items():
        source, flag = question["x-stayfixed-source"], question["x-stayfixed-flag"]
        lines.append(f"  {key}: {_shown(question)} ({source}; {flag})")
    lines.append(TAIL)
    return "\n".join(lines)
