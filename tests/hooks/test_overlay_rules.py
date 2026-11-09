"""The overlay's rules through `drybag hook`, end to end: a standing rule on `SessionStart` from
the core plugin, and a path-scoped one on the `PostToolUse` entry the rendered plugin carries.

Each case spawns the hook with a home of its own, which is where the machine file records the
overlay and where the binding record and the once-per-file record live.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drybag.attach.rules import SCOPED_LEAD, STANDING_LEAD
from tests.gitfixture import git
from tests.hooks.test_hook_command import hook, needs_git

STANDING = "Always say which test proves a change."
SCOPED = "Files under scoped/ are generated; edit the generator instead."


def _attached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, bound: bool) -> tuple[Path, Path]:
    """A checkout, an overlay with one standing and one scoped rule, and the home the hook runs
    under; the checkout bound to the overlay's project when `bound`."""
    from drybag import binding

    home = tmp_path / "home"
    machine = home / ".config" / "drybag" / "config.toml"
    machine.parent.mkdir(parents=True)
    overlay = tmp_path / "overlay"
    common = overlay / "common" / "claude" / "rules"
    project = overlay / "projects" / "widget" / "claude" / "rules"
    common.mkdir(parents=True)
    project.mkdir(parents=True)
    (common / "proof.md").write_text(f"{STANDING}\n", encoding="utf-8")
    (project / "generated.md").write_text(
        f'---\npaths: ["scoped/**"]\n---\n{SCOPED}\n', encoding="utf-8"
    )
    machine.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    if bound:
        # The record goes under the hook's home, as `attach` run there would write it.
        monkeypatch.setenv("HOME", str(home))
        binding.record(root, "widget", None)
    return root, home


def _context(stdout: str) -> str | None:
    context = json.loads(stdout).get("hookSpecificOutput", {}).get("additionalContext")
    assert context is None or isinstance(context, str)
    return context


@needs_git
def test_a_bound_checkouts_session_start_carries_the_standing_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home = _attached(tmp_path, monkeypatch, bound=True)
    payload = {"hook_event_name": "SessionStart", "session_id": "s1", "source": "startup"}
    completed = hook("SessionStart", json.dumps(payload), root, home=home)
    assert (completed.returncode, completed.stderr) == (0, "")
    assert _context(completed.stdout) == f"{STANDING_LEAD}\n\n{STANDING}"


@needs_git
def test_an_unbound_checkouts_session_start_carries_no_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home = _attached(tmp_path, monkeypatch, bound=False)
    payload = {"hook_event_name": "SessionStart", "session_id": "s1", "source": "startup"}
    completed = hook("SessionStart", json.dumps(payload), root, home=home)
    assert (completed.returncode, completed.stderr) == (0, "")
    assert _context(completed.stdout) is None


@needs_git
def test_a_read_of_a_scoped_file_carries_its_rule_once_per_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home = _attached(tmp_path, monkeypatch, bound=True)

    def read(tool: str, session: str) -> str | None:
        payload = {
            "hook_event_name": "PostToolUse",
            "session_id": session,
            "tool_name": tool,
            "tool_input": {"file_path": str(root / "scoped" / "a.txt")},
        }
        completed = hook("PostToolUse", json.dumps(payload), root, home=home)
        assert (completed.returncode, completed.stderr) == (0, "")
        return _context(completed.stdout)

    said = f"{SCOPED_LEAD.format(path='scoped/a.txt')}\n\n{SCOPED}"
    assert read("Read", "s1") == said
    assert read("Edit", "s1") is None
    assert read("Write", "s2") == said
    # The core plugin's own `PostToolUse` entry matches `Bash`, whose input names no file.
    assert read("Bash", "s3") is None
