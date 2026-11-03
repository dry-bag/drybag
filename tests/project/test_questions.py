"""`stayfixed init --questions`' schema: nine questions, each default what `init --yes` alone
writes, each source one of `detect`'s phrases, and no byte a grammar rejected."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from stayfixed.cli import build_parser, discover_registrars
from stayfixed.config.loader import load, preset_defaults
from stayfixed.config.schema import MEMORY_MODES
from stayfixed.errors import Refusal
from stayfixed.presets import load_preset
from stayfixed.project import questions as questions_module
from stayfixed.project.init import init
from stayfixed.project.questions import (
    BRANCH_PATTERN,
    FLAGS,
    NAME_PATTERN,
    OVERLAY_NEXT,
    PLUGINS,
    PROPERTIES,
    TRADE_OFFS,
    card,
    questions,
)
from stayfixed.scaffold import MANIFEST_PATH
from tests.cli import cli
from tests.gitfixture import git, needs_git
from tests.project.repos import DOCUMENT, repository


def _schema(tmp_path: Path, root: Path) -> dict[str, Any]:
    return questions(root, machine=tmp_path / "absent.toml")


def _defaults(schema: dict[str, Any]) -> dict[str, tuple[object, str]]:
    return {
        key: (question.get("default"), question["x-stayfixed-source"])
        for key, question in schema["properties"].items()
    }


@needs_git
@pytest.mark.parametrize("key", [key for key in PROPERTIES if key != PLUGINS])
def test_each_default_is_what_init_yes_alone_writes(tmp_path: Path, key: str) -> None:
    # The card promises that each default is what `init --yes` would take, and the skill asks
    # the person to confirm the card, not the file. The two are computed in two places, so each
    # is held to the other over a repository where no default is the preset's: a `develop`
    # branch, a harness directory and a profile's markers. Mutation (by hand): the card's base
    # branch taken from the preset -> the `project.base_branch` case reddens.
    root = repository(tmp_path, origin=None)
    git(root, "symbolic-ref", "HEAD", "refs/heads/develop")
    (root / ".codex").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'widget'\n", encoding="utf-8")
    default = _schema(tmp_path, root)["properties"][key]["default"]
    written = init(root, machine=tmp_path / "absent.toml", yes=True, dry_run=False)
    assert not written.refused
    table, name = key.split(".")
    value = getattr(getattr(load(root, machine=tmp_path / "absent.toml"), table), name)
    assert (list(value) if isinstance(value, tuple) else value) == default


@needs_git
def test_the_schema_keys_are_the_stayfixed_toml_keys_the_answers_write(tmp_path: Path) -> None:
    # Mutation (by hand): the loop that sets `x-stayfixed-flag` dropped -> the last assertion
    # reddens on a `KeyError`.
    schema = _schema(tmp_path, repository(tmp_path))
    assert schema["type"] == "object"
    assert tuple(schema["properties"]) == PROPERTIES == tuple(schema["required"])
    assert len(PROPERTIES) == 8
    for key, question in schema["properties"].items():
        assert question["x-stayfixed-flag"] == FLAGS[key], key


@needs_git
def test_the_skill_reads_the_order_to_ask_in_from_required_in_the_json(tmp_path: Path) -> None:
    # The skill and docs/cli.md said each property under `questions.properties` came in the order
    # to ask it, but `--json` prints with sorted keys, so the properties arrive alphabetically and
    # a skill walking them asked about the agents first. `required` is a list, which keeps its
    # order through the printer, so that is where the skill reads the order: here as the skill
    # reads it, from the printed JSON, in the order the skill and the release notes name.
    root = repository(tmp_path)
    code, printed, _ = cli(root, tmp_path, "init", "--questions", "--json")
    assert code == 0, printed
    schema = json.loads(printed)["questions"]
    assert schema["required"] == [
        "project.name",
        "project.base_branch",
        "memory.mode",
        "stayfixed.profile",
        "commit_messages.attribution_check",
        "commit_messages.types",
        "stayfixed.agents",
        "plugins",
    ]
    assert sorted(schema["properties"]) == sorted(schema["required"])


@needs_git
def test_each_default_says_where_it_came_from(tmp_path: Path) -> None:
    # Each (default, source) pair is what `init --yes` alone takes, and says why: a default with
    # no source is one a person cannot check before accepting it. Mutation (by hand): the agents'
    # fallback reports `harness directories` -> the agents assertion reddens.
    defaults = _defaults(_schema(tmp_path, repository(tmp_path)))
    assert defaults["project.name"] == ("widget", "origin remote")
    # An `origin` with no `origin/HEAD`, as a repository created here and pushed has it: the
    # default, never the branch checked out, which may be the feature branch being adopted from.
    assert defaults["project.base_branch"] == ("main", "default")
    no_origin = _defaults(_schema(tmp_path / "b", repository(tmp_path / "b", origin=None)))
    assert no_origin["project.base_branch"] == ("main", "current branch")
    assert defaults["stayfixed.agents"] == (["claude", "codex"], "default")
    assert defaults["stayfixed.profile"] == ("", "no profile markers")


def test_the_free_text_patterns_are_anchored_for_ecma_262() -> None:
    # A JSON Schema `pattern` is ECMA-262, where Python's `\Z` is a literal `Z`: a client
    # validating against it would refuse every real name. Mutation (oracle): `ecma` returns the
    # Python pattern unchanged -> the `\Z` assertion reddens.
    for pattern in (NAME_PATTERN, BRANCH_PATTERN):
        assert pattern.endswith("$") and "\\Z" not in pattern, pattern
    # Not vacuous: the pattern still accepts a name and refuses what the grammar refuses.
    assert re.fullmatch(NAME_PATTERN, "widget")
    assert not re.fullmatch(NAME_PATTERN, "Not A Name")
    assert re.fullmatch(BRANCH_PATTERN, "release/2.x")


@needs_git
def test_the_memory_default_is_the_presets_whatever_the_machine_records(tmp_path: Path) -> None:
    # `init` takes `[memory] mode`'s default whatever the machine records, which is `harness` since
    # the preset chooses none; the machine only changes what the overlay option says.
    # (`overlay_root` does not check the directory exists.)
    # Mutation (by hand): default to `overlay` when the machine records one -> the first
    # assertion reddens.
    bare = questions(repository(tmp_path / "a"), machine=tmp_path / "absent.toml")
    machine = tmp_path / "machine.toml"
    machine.write_text(f'[overlay]\nroot = "{tmp_path / "overlay"}"\n', encoding="utf-8")
    recorded = questions(repository(tmp_path / "b"), machine=machine)
    modes = [bare["properties"]["memory.mode"], recorded["properties"]["memory.mode"]]
    assert [m["default"] for m in modes] == ["harness", "harness"]
    assert [[o["const"] for o in m["oneOf"]] for m in modes] == [list(MEMORY_MODES)] * 2
    titles = [{o["const"]: o["title"] for o in m["oneOf"]}["overlay"] for m in modes]
    assert titles[0] != titles[1], titles


@needs_git
def test_a_machine_file_that_does_not_parse_still_yields_the_questions(tmp_path: Path) -> None:
    # The machine file changes one title, so a broken one must not cost the questions; `init`
    # reports it when it loads it. Mutation (oracle): catch `KeyError` instead of `Failure` ->
    # the machine file's refusal escapes and this reddens.
    machine = tmp_path / "machine.toml"
    machine.write_text("[overlay", encoding="utf-8")
    schema = questions(repository(tmp_path), machine=machine)
    assert tuple(schema["properties"]) == PROPERTIES
    overlay = {o["const"]: o["title"] for o in schema["properties"]["memory.mode"]["oneOf"]}
    assert overlay["overlay"] == OVERLAY_NEXT


@needs_git
def test_a_name_outside_the_grammar_is_left_to_ask_and_never_printed(tmp_path: Path) -> None:
    # The remote's last segment is repository-authored; outside the grammar it is neither the
    # default nor printed. Mutation (oracle): leniency keeps the name -> it becomes the default
    # and the `not in` assertions redden.
    schema = _schema(tmp_path, repository(tmp_path, origin="git@github.com:owner/Not A Name.git"))
    name = schema["properties"]["project.name"]
    assert "default" not in name and name["x-stayfixed-source"] == "not derivable"
    shown = card(schema)
    assert "not a name" not in repr(schema).lower() and "not a name" not in shown.lower()
    assert "  project.name: none; asked (not derivable; --name)\n" in shown


@needs_git
def test_the_questions_are_refused_where_init_would_refuse(tmp_path: Path) -> None:
    # A `stayfixed.toml` already answers every question, and a manifest means `init` has run:
    # asking in either case would collect answers nothing could write. Mutation (oracle): the
    # `stayfixed.toml` check disabled -> the first `raises` reddens.
    root = repository(tmp_path)
    (root / "stayfixed.toml").write_text(DOCUMENT, encoding="utf-8")
    with pytest.raises(Refusal, match=re.escape("already has a stayfixed.toml")):
        _schema(tmp_path, root)
    (root / MANIFEST_PATH).parent.mkdir(parents=True)
    (root / MANIFEST_PATH).write_text("{}", encoding="utf-8")
    with pytest.raises(Refusal, match="`init` writes a scaffold once"):
        _schema(tmp_path, root)


# The order the guided walk asks in, after the name and the base branch it confirms first:
# memory, the profile, attribution and the commit types, the agents, and the recommended plugins
# last.
GUIDED = (
    "memory.mode",
    "stayfixed.profile",
    "commit_messages.attribution_check",
    "commit_messages.types",
    "stayfixed.agents",
    "plugins",
)


@needs_git
def test_every_question_carries_its_four_lines_in_the_guided_order(tmp_path: Path) -> None:
    # The skill relays each question with what the answer gives, what it costs, what it leaves
    # behind and how to take it back, and the texts are the command's, so a skill cannot drift
    # from what the command does. A question without them is one the person answers blind.
    schema = _schema(tmp_path, repository(tmp_path))
    assert tuple(schema["properties"]) == ("project.name", "project.base_branch", *GUIDED)
    for key, question in schema["properties"].items():
        lines = question["x-stayfixed-tradeoff"]
        assert tuple(lines) == ("get", "give_up", "trace", "undo"), key
        assert all(isinstance(line, str) and line.strip() for line in lines.values()), key


@needs_git
def test_the_skip_takes_attribution_off_the_preset_types_and_no_plugin(tmp_path: Path) -> None:
    # Taking every default is offered first, so each default is what a person gets without
    # reading a question: the attribution check off, the preset's commit types, and no plugin of
    # the ones it recommends.
    schema = _schema(tmp_path, repository(tmp_path))["properties"]
    assert schema["commit_messages.attribution_check"]["default"] is False
    preset = preset_defaults("widget")
    assert schema["commit_messages.types"]["default"] == list(preset.commit_messages.types)
    plugins = schema["plugins"]
    assert plugins["default"] == [] and set(plugins["items"]["enum"]) == {
        "superpowers",
        "context7",
    }


@needs_git
def test_the_plugins_question_names_the_plugins_the_preset_recommends_and_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The "what you get" line spelled out superpowers' and context7's while the options came from
    # the preset, so a preset that recommended another plugin would be offered under a line
    # describing two it no longer names. The line is filled from the same list as the options.
    monkeypatch.setattr(questions_module, "_recommended", lambda: ["alpha", "beta"])
    plugins = _schema(tmp_path, repository(tmp_path))["properties"][PLUGINS]
    assert plugins["items"]["enum"] == ["alpha", "beta"]
    get = plugins["x-stayfixed-tradeoff"]["get"]
    assert "alpha, beta" in get and "superpowers" not in get and "context7" not in get, get


def test_the_plugins_question_names_the_machine_setup_its_flag_runs() -> None:
    # The flag the question names is `stayfixed setup --plugin`, a whole machine setup: it writes
    # the machine file and merges deny rules and plugin options into the user settings, besides
    # the install. The trace named only the install.
    trace = TRADE_OFFS[PLUGINS][2]
    assert "machine configuration file" in trace and "~/.claude/settings.json" in trace, trace


def test_the_plugins_question_s_flag_is_one_setup_takes_for_each_plugin_it_offers() -> None:
    # The plugins are answered on the machine, not by `init`: the skill runs the flag the question
    # names with each chosen plugin, so that flag has to be one `setup`'s parser takes for every
    # plugin the question offers.
    parser = build_parser(discover_registrars())
    command = FLAGS[PLUGINS].removeprefix("stayfixed ").split()
    offered = load_preset("recommended")["plugins"]["recommended"]
    assert offered
    for name in offered:
        assert parser.parse_args([*command, name]).plugin == [name]
