"""Skills are documents held to a contract: frontmatter, a line budget, action language rather
than tool or product names, and invocations that parse against the real parser or are
allow-listed by the area that will ship them."""

from __future__ import annotations

import io
import re
import shlex
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from stayfixed.areas import area_modules
from stayfixed.cli import build_parser, discover_registrars, split_json_flag
from stayfixed.overlay.template import template_root

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
# The plugin's own skill_lines lint: a SKILL.md is an entry point, and detail belongs in
# `references/`. Not a config key — it bounds a file this repository ships, not a project's.
SKILL_MAX_LINES = 80
# Harness tool names a skill body may not use: action language, never tool names.
# The per-harness mapping lives in skills/README.md and is held to this same list.
TOOL_NAMES = (
    "Read",
    "Grep",
    "Glob",
    "Bash",
    "Edit",
    "Write",
    "WebFetch",
    "WebSearch",
    "AskUserQuestion",
    "Agent",
    "LSP",
    "NotebookEdit",
    "TodoWrite",
    "request_user_input",
)
_TOOL = re.compile(r"\b(?:" + "|".join(TOOL_NAMES) + r")\b")
# Commands the wrapper skills describe against the CLI frame before the command exists, keyed to the
# area whose `commands.py` will register each — an area that already registers commands, so a
# command a new area will ship is listed once that area exists. The change that ships one DELETES
# its entry: a parsing command that is still listed here reddens
# `test_every_invocation_parses_or_is_allowlisted`. Empty since `uninstall` shipped; kept, with its
# check against the areas that register commands, for the next wrapper written ahead of its command.
NOT_YET_SHIPPED: dict[str, str] = {}
_INVOCATION = re.compile(r"`stayfixed ([^`\n]+)`")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def skills() -> list[Path]:
    return sorted(SKILLS.glob("*/SKILL.md"))


def documents() -> list[Path]:
    """Every skill document the invocation check reads: the `SKILL.md` entry points and the
    `references/` files beside them.

    A reference is skill content a model reads and copies, so an invocation that does not parse
    is as wrong there as in a procedure. `skills/README.md` is excluded because its table names
    harness tools rather than commands. The tool-name rule is deliberately *not* widened this
    way: a reference writes ordinary English about writing ("Write the rule, not the incident")
    that `_TOOL` would read as the harness tool of the same name.
    """
    return sorted(path for path in SKILLS.rglob("*.md") if path.name != "README.md")


def split(path: Path) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    assert match is not None, f"{path} has no frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, match.group(2)


def test_the_walk_finds_the_ported_skills() -> None:
    # The mutation guard for the parametrised tests below: an empty `skills/` passes them all.
    # Every skill `skills/` ships is named, not only the one ported one — deleting the three
    # wrappers would otherwise leave NOT_YET_SHIPPED describing commands no skill names, with
    # the suite still green. Subsets, not equalities: `skills-author` grows this directory.
    names = {path.parent.name for path in skills()}
    assert {"memory-sweep"} <= names
    assert {"attach", "setup", "doctor"} <= names
    # The same guard for the wider walk: a `references/` that goes quiet takes its own
    # invocation cases with it.
    walked = documents()
    assert SKILLS / "memory-sweep" / "references" / "protocol.md" in walked
    # The overlay template ships no skill since its copy of `attach` was retired for the
    # plugin's own, so the rules below walk only `skills/`. A skill added to the template again
    # reddens this, which makes it a decision: whoever adds one widens these walks to it.
    # No mutation entry: what breaks this is a directory added to the tree, not a line changed.
    assert not (template_root() / "skills").exists()


@pytest.mark.parametrize("path", skills(), ids=lambda p: p.parent.name)
def test_every_skill_has_a_name_matching_its_directory_and_a_description(path: Path) -> None:
    fields, _ = split(path)
    assert fields["name"] == path.parent.name
    assert len(fields["description"]) > 40, "a description is what the harness matches on"


@pytest.mark.parametrize("path", skills(), ids=lambda p: p.parent.name)
def test_every_skill_stays_within_the_line_budget(path: Path) -> None:
    assert len(path.read_text(encoding="utf-8").splitlines()) <= SKILL_MAX_LINES


def test_the_tool_name_lint_matches_a_tool_name() -> None:
    # Every use of `_TOOL` below is a NEGATIVE assertion, so a pattern that matches the empty
    # set satisfies all of them. Measured: `_TOOL` replaced by `re.compile("ZZZNEVER")` left
    # `tests/skills/` at 83 passed with the no-tool-names rule checked against nothing.
    #
    # Mutation (declared): the pattern is made to match nothing.
    assert _TOOL.search("use the Grep tool"), "the lint cannot match a tool name"
    assert _TOOL.search("read it with Read first")
    # And it is a word boundary and not a substring: `Agent` must not fire on `Agentic`, which
    # is what the `\b` in the pattern is for and what a reader would otherwise have to assume.
    assert _TOOL.search("an Agentic workflow") is None


@pytest.mark.parametrize("path", skills(), ids=lambda p: p.parent.name)
def test_no_skill_body_names_a_harness_tool(path: Path) -> None:
    # Mutation: write "use the Grep tool" into a skill body — that skill's case reddens.
    _, body = split(path)
    assert _TOOL.search(body) is None, _TOOL.search(body)


@pytest.mark.parametrize("path", documents(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_invocation_parses_or_is_allowlisted(path: Path) -> None:
    parser = build_parser(discover_registrars())
    # The whole file, not `split`'s body: a reference carries no frontmatter, and a description
    # that named a command would have to parse too.
    body = path.read_text(encoding="utf-8")
    invocations = _INVOCATION.findall(body)
    if path.name == "SKILL.md":
        # Scoped to the entry points: a reference may be pure convention prose with no command
        # in it, and nothing is wrong with that.
        assert invocations, "a skill that names no command is not a wrapper"
    for invocation in invocations:
        argv, _ = split_json_flag(shlex.split(invocation))
        with redirect_stderr(io.StringIO()):
            try:
                parser.parse_args(argv)
                parsed = True
            except SystemExit:
                parsed = False
        if argv[0] in NOT_YET_SHIPPED:
            assert not parsed, (
                f"`stayfixed {invocation}` parses now; delete its NOT_YET_SHIPPED entry "
                f"({NOT_YET_SHIPPED[argv[0]]} shipped it) and re-read this skill against the "
                f"flags that actually shipped — this test proves the command parses, never "
                f"that the skill describes it correctly"
            )
        else:
            assert parsed, f"`stayfixed {invocation}` does not parse against the real parser"


def test_the_allowlist_names_only_areas_that_register_commands() -> None:
    # A command reaches the CLI through an area's `commands.py`, so the owner an entry names is one
    # of those areas, and the message the parse check prints names where the command shipped. The
    # anchor holds the derivation: an `areas` read wrong would otherwise refuse every entry, or
    # none, with the allowlist empty and the subset check unable to tell. No mutation is declared
    # for that check while the allowlist is empty, since an empty set is a subset of anything.
    # Mutation (declared): the area read from the wrong part of the module name -> this reddens.
    areas = {module.__name__.split(".")[1] for module in area_modules("commands")}
    assert {"setup", "attach"} <= areas
    assert set(NOT_YET_SHIPPED.values()) <= areas


def test_the_readme_maps_every_tool_name_for_both_harnesses() -> None:
    text = (SKILLS / "README.md").read_text(encoding="utf-8")
    for name in TOOL_NAMES:
        assert f"`{name}`" in text, name
    assert "Codex" in text and "Claude Code" in text


@pytest.mark.parametrize("path", skills(), ids=lambda p: p.parent.name)
def test_every_reference_file_is_linked_from_its_skill(path: Path) -> None:
    body = path.read_text(encoding="utf-8")
    for reference in sorted((path.parent / "references").glob("*.md")):
        assert f"references/{reference.name}" in body, reference
