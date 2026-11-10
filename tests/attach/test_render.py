"""The overlay's hooks, skills and agents, rendered into a local plugin named by the binding id.

What is checked here is the directory a session runs in place: `claude plugin install` keeps a
cache copy, but the plugin runs from the marketplace's own directory, so these bytes are what a
session executes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from drybag.attach.binding import Binding
from drybag.attach.permissions import codex_rules
from drybag.attach.render import RenderRecord, read_parts, write
from drybag.attach.rules import read as rules_read
from drybag.attach.tags import collisions
from drybag.config.plates import plates
from tests.tagged import with_tags


def render(overlay: Path, project: str, id: str) -> RenderRecord:
    return write(id, read_parts(plates(overlay, project, machine=None)[0]))


ID = "0123456789abcdef0123456789abcdef"
COMMON = {"type": "command", "command": "common.sh"}
PROJECT = {"type": "command", "command": "project.sh"}
GUARD = {"type": "command", "command": "guard.sh"}


def _delivery(id: str = ID) -> Path:
    # Spelled out rather than asked of the module: the directory is the contract, and the test
    # suite gives every test a `HOME` of its own (`tests/conftest.py`).
    return Path(os.environ["HOME"]) / ".local" / "share" / "drybag" / "delivery" / id


def _overlay(tmp_path: Path) -> Path:
    overlay = tmp_path / "overlay"
    common = overlay / "common" / "claude"
    project = overlay / "projects" / "p" / "claude"
    (common / "skills" / "review").mkdir(parents=True)
    (project / "agents").mkdir(parents=True)
    (common / "hooks.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [COMMON]}]}}), encoding="utf-8"
    )
    (project / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"hooks": [PROJECT]}],
                    "PreToolUse": [{"matcher": "Bash", "hooks": [GUARD]}],
                }
            }
        ),
        encoding="utf-8",
    )
    (common / "skills" / "review" / "SKILL.md").write_text("review\n", encoding="utf-8")
    (common / "skills" / "review" / "check.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (common / "skills" / "review" / "check.sh").chmod(0o750)
    # Dot-named files and directories are the editor's and the system's, never delivered.
    (common / "skills" / ".cache").mkdir()
    (common / "skills" / ".cache" / "index.md").write_text("cache\n", encoding="utf-8")
    (common / "skills" / ".DS_Store").write_text("finder\n", encoding="utf-8")
    (project / "agents" / "helper.md").write_text("helper\n", encoding="utf-8")
    return overlay


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(directory: Path) -> str:
    # The digest's definition, restated: sha256 over every rendered file's path relative to the
    # render directory and its bytes, in path order, each framed by its length.
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(directory).as_posix()
        content = path.read_bytes()
        digest.update(f"{relative}\0{len(content)}\0".encode())
        digest.update(content)
    return digest.hexdigest()


def test_render_writes_the_marketplace_and_the_plugin_under_names_carrying_the_whole_id(
    tmp_path: Path,
) -> None:
    # The names are the delivery's only defence: a clone can commit an `enabledPlugins` entry,
    # and it cannot name an id it never saw. Mutation: the marketplace named without the id ->
    # this reddens (`mutations/attach.toml`).
    record = render(_overlay(tmp_path), "p", ID)
    delivery = _delivery()
    marketplace = _json(delivery / ".claude-plugin" / "marketplace.json")
    assert isinstance(marketplace, dict)
    assert marketplace["name"] == f"drybag-delivery-{ID}"
    assert [(p["name"], p["source"]) for p in marketplace["plugins"]] == [
        (f"overlay-{ID}", "./plugin")
    ]
    plugin = _json(delivery / "plugin" / ".claude-plugin" / "plugin.json")
    assert isinstance(plugin, dict) and plugin["name"] == f"overlay-{ID}"
    # The union, common first and this project's second, every entry as the overlay wrote it.
    assert _json(delivery / "plugin" / "hooks" / "hooks.json") == {
        "hooks": {
            "SessionStart": [{"hooks": [COMMON]}, {"hooks": [PROJECT]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [GUARD]}],
        }
    }
    assert (delivery / "plugin" / "skills" / "review" / "SKILL.md").read_text() == "review\n"
    assert (delivery / "plugin" / "agents" / "helper.md").read_text() == "helper\n"
    # A copied file keeps its mode: a skill's script stays executable.
    assert (delivery / "plugin" / "skills" / "review" / "check.sh").stat().st_mode & 0o777 == 0o750
    assert record.id == ID
    assert len([p for p in delivery.rglob("*") if p.is_file()]) == 6
    assert record.digest == _digest(delivery)


def test_a_second_render_replaces_the_files_in_the_same_directory(tmp_path: Path) -> None:
    # What runs is the render directory's bytes, so a re-render must change them in place: an
    # edited hook file reaches the next session with no reinstall, and a skill taken out of the
    # overlay stops being delivered.
    overlay = _overlay(tmp_path)
    first = render(overlay, "p", ID)
    (overlay / "common" / "claude" / "hooks.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [COMMON]}]}}), encoding="utf-8"
    )
    (overlay / "common" / "claude" / "skills" / "review" / "SKILL.md").unlink()
    # A mode changed in the overlay reaches the render too, over the file already there.
    (overlay / "common" / "claude" / "skills" / "review" / "check.sh").chmod(0o640)
    # Rendered whole beside the directory and swapped in, so no record of the first render's
    # parts is needed, and nothing is left beside the directory.
    second = render(overlay, "p", ID)
    delivery = _delivery()
    hooks = _json(delivery / "plugin" / "hooks" / "hooks.json")
    assert isinstance(hooks, dict)
    assert hooks["hooks"]["Stop"] == [{"hooks": [COMMON]}]
    assert hooks["hooks"]["SessionStart"] == [{"hooks": [PROJECT]}]
    assert not (delivery / "plugin" / "skills" / "review" / "SKILL.md").exists()
    assert (delivery / "plugin" / "skills" / "review" / "check.sh").stat().st_mode & 0o777 == 0o640
    assert second.digest != first.digest
    assert second.digest == _digest(delivery)
    assert [p.name for p in delivery.parent.iterdir()] == [ID]


def _scoped_rule(overlay: Path) -> None:
    rules = overlay / "projects" / "p" / "claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "generated.md").write_text(
        '---\npaths: ["scoped/**"]\n---\nEdit the generator.\n', encoding="utf-8"
    )


def _scoped_entry() -> object:
    hooks = _json(_delivery() / "plugin" / "hooks" / "hooks.json")
    assert isinstance(hooks, dict)
    return hooks["hooks"].get("PostToolUse")


def _entry(command: str) -> list[object]:
    return [
        {
            "matcher": "Read|Edit|Write",
            "hooks": [{"type": "command", "timeout": 10, "command": command}],
        }
    ]


def test_run_from_the_plugin_the_entry_runs_the_plugins_own_hook_wrapper(tmp_path: Path) -> None:
    # This checkout is a plugin root, `hooks/run-hook.sh` beside `src/`, so the entry runs the
    # wrapper the core plugin's own entries run, with `-I` and a fault being exit 0, quoted as
    # those entries quote it.
    overlay = _overlay(tmp_path)
    _scoped_rule(overlay)
    render(overlay, "p", ID)
    wrapper = Path(__file__).resolve().parents[2] / "hooks" / "run-hook.sh"
    assert _scoped_entry() == _entry(f'"{wrapper}" hook PostToolUse')


def test_run_from_an_installed_package_the_entry_runs_its_interpreter_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No plugin root beside the module: the entry runs the interpreter this drybag runs under,
    # by its absolute path, with `-I -m drybag`. A path a shell would read into is quoted so
    # that `sh` hands it back as it is.
    import drybag

    module = tmp_path / "site-packages" / "drybag" / "__init__.py"
    interpreter = str(tmp_path / 'py "$HOME" `x` \\ 3' / "python3")
    monkeypatch.setattr(drybag, "__file__", str(module))
    monkeypatch.setattr(sys, "executable", interpreter)
    overlay = _overlay(tmp_path)
    _scoped_rule(overlay)
    render(overlay, "p", ID)
    entry = _scoped_entry()
    assert isinstance(entry, list)
    command = entry[0]["hooks"][0]["command"]
    assert command.endswith(" -I -m drybag hook PostToolUse")
    assert entry == _entry(command)
    quoted = command.removesuffix(" -I -m drybag hook PostToolUse")
    said = subprocess.run(
        ["/bin/sh", "-c", f"printf '%s' {quoted}"], capture_output=True, text=True, check=True
    )
    assert said.stdout == interpreter


def test_an_overlay_with_no_path_scoped_rule_renders_no_post_tool_use_entry(
    tmp_path: Path,
) -> None:
    overlay = _overlay(tmp_path)
    rules = overlay / "common" / "claude" / "rules"
    rules.mkdir()
    (rules / "standing.md").write_text("Always.\n", encoding="utf-8")
    render(overlay, "p", ID)
    assert _scoped_entry() is None


def test_a_fault_under_the_rendered_entry_is_exit_0(tmp_path: Path) -> None:
    # The entry's command, run as the harness runs it, under a `python3` that passes the wrapper's
    # version probe (printing its own path, as the probe asks) and then fails as drybag: the
    # wrapper answers exit 0 with one line, where a launcher run bare would hand its non-zero exit,
    # and on `PostToolUse` an exit 2's stderr, to the session.
    overlay = _overlay(tmp_path)
    _scoped_rule(overlay)
    render(overlay, "p", ID)
    entry = _scoped_entry()
    assert isinstance(entry, list)
    command = entry[0]["hooks"][0]["command"]
    bin = tmp_path / "bin"
    bin.mkdir()
    python = bin / "python3"
    python.write_text(
        '#!/bin/sh\ncase "$2" in -c) echo "$0"; exit 0 ;; esac\nexit 3\n', encoding="utf-8"
    )
    python.chmod(0o755)
    done = subprocess.run(
        ["/bin/sh", "-c", command],
        input='{"hook_event_name": "PostToolUse"}',
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": str(bin), "CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert (done.returncode, done.stdout) == (0, "")
    assert done.stderr == "drybag: drybag exited 3; continuing open\n"


def test_a_tag_hook_group_is_rendered_between_common_and_the_project(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    with_tags(overlay, "p", ["a"], "claude")
    tagged = {"type": "command", "command": "tag.sh"}
    (overlay / "tags" / "a" / "claude" / "hooks.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [tagged]}]}}), encoding="utf-8"
    )
    render(overlay, "p", ID)
    hooks = _json(_delivery() / "plugin" / "hooks" / "hooks.json")
    assert isinstance(hooks, dict)
    assert hooks["hooks"]["SessionStart"] == [
        {"hooks": [COMMON]},
        {"hooks": [tagged]},
        {"hooks": [PROJECT]},
    ]


def test_a_tag_skill_is_rendered_and_a_later_plate_wins_it_whole(tmp_path: Path) -> None:
    # A skill is the item its directory names: b's `review` replaces a's and common's whole, so no
    # file of theirs reaches the render, which is what the collision sentence says. Mutation
    # (oracle): `mutations/`'s "a skill is merged file by file across plates" -> a's `helper.sh`
    # and common's `check.sh` arrive beside b's `SKILL.md`.
    overlay = _overlay(tmp_path)
    with_tags(overlay, "p", ["a", "b"], "claude")
    for tag in ("a", "b"):
        skills = overlay / "tags" / tag / "claude" / "skills"
        (skills / "review").mkdir(parents=True)
        (skills / "review" / "SKILL.md").write_text(f"review from {tag}\n", encoding="utf-8")
        (skills / f"only-{tag}.md").write_text(f"{tag}\n", encoding="utf-8")
    (overlay / "tags" / "a" / "claude" / "skills" / "review" / "helper.sh").write_text(
        "from a only\n", encoding="utf-8"
    )
    render(overlay, "p", ID)
    skills = _delivery() / "plugin" / "skills"
    assert sorted(path.name for path in (skills / "review").iterdir()) == ["SKILL.md"]
    assert (skills / "review" / "SKILL.md").read_text() == "review from b\n"
    assert (skills / "only-a.md").read_text() == "a\n" and (skills / "only-b.md").is_file()
    assert collisions(plates(overlay, "p", machine=None)[0], ()) == (
        "the skill review is held by the tags a, b: the later, b, wins",
    )


def test_a_rule_a_codex_file_and_a_skill_take_one_winner_and_one_order(tmp_path: Path) -> None:
    # Each kind is folded alike: the later plate wins the whole item and takes that plate's place,
    # so the common-only `y` comes before the tag's `x`, and common's `x/extra.md` is not copied.
    overlay = _overlay(tmp_path)
    with_tags(overlay, "p", ["a"], "claude")
    for plate, name in (("common", "x"), ("common", "y"), ("tags/a", "x")):
        for relative in ("claude/rules/{}.md", "codex/{}.rules", "claude/skills/{}/SKILL.md"):
            (overlay / plate / relative.format(name)).parent.mkdir(parents=True, exist_ok=True)
            (overlay / plate / relative.format(name)).write_text(f"{plate}\n", encoding="utf-8")
    (overlay / "common" / "claude" / "skills" / "x" / "extra.md").write_text("", encoding="utf-8")
    held = plates(overlay, "p", machine=None)[0]
    binding = Binding("p", overlay, tmp_path, None, None, "", plates=held)
    rules = [(rule.name, rule.body) for rule in rules_read(held)]
    codex = [(target, source.read_text()) for target, source in codex_rules(binding)]
    skills = [(name, part.text) for name, part in read_parts(held).items() if "skills/" in name]
    assert rules == [("y.md", "common"), ("x.md", "tags/a")]
    assert codex == [(".codex/rules/y.rules", "common\n"), (".codex/rules/x.rules", "tags/a\n")]
    assert skills[2:] == [("skills/y/SKILL.md", "common\n"), ("skills/x/SKILL.md", "tags/a\n")]
