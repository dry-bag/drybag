"""The enumerated-writes rule (CONTRIBUTING.md#enumerated-writes) for `scaffold`: `apply` touches
the project root and nothing else.

Two instruments, because a tree diff and a syscall trace fail on different things. The diff answers
"did exactly the planned paths change"; it is blind to a write anywhere it does not walk, which is
the thing the enumerated-writes rule actually forbids. The trace answers "was any absolute path
outside the root opened for writing at all", and it sees `$HOME`, a created directory, a symlink and
a mode change.
"""

from __future__ import annotations

import builtins
import io
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.scaffold import Kind, Style, Template, apply, plan
from stayfixed.scaffold.manifest import MANIFEST_PATH

CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"
"""

WRITING_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def snapshot(base: Path) -> dict[str, str]:
    return {
        str(path.relative_to(base)): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


class Trace:
    """Every absolute path the process opened for writing, created or removed."""

    def __init__(self) -> None:
        self.paths: list[Path] = []

    def note(self, candidate: Any) -> None:
        if isinstance(candidate, int) or candidate is None:
            return  # a descriptor-relative call; `open_within` proved where that descriptor is
        self.paths.append(Path(os.fsdecode(candidate)))

    def outside(self, root: Path) -> list[str]:
        resolved = root.resolve()
        return sorted(
            {
                str(path)
                for path in self.paths
                if not (path.resolve() == resolved or resolved in path.resolve().parents)
            }
        )


@pytest.fixture
def trace(monkeypatch: pytest.MonkeyPatch) -> Iterator[Trace]:
    recorder = Trace()
    originals: dict[str, Callable[..., Any]] = {
        name: getattr(os, name)
        for name in (
            "open",
            "replace",
            "rename",
            "unlink",
            "remove",
            "mkdir",
            "makedirs",
            "symlink",
        )
    }
    # `io.open` and not only `builtins.open`: they are the same function object, but
    # `pathlib.Path.open` resolves it through the `io` module at call time, so patching
    # `builtins` alone leaves every `Path.write_text` invisible. Measured — the $HOME
    # mutation below passed against a `builtins`-only recorder.
    real_open = builtins.open

    def wrap(name: str) -> Callable[..., Any]:
        original = originals[name]

        def call(*args: Any, **kwargs: Any) -> Any:
            if name == "open":
                flags = args[1] if len(args) > 1 else kwargs.get("flags", 0)
                if flags & WRITING_FLAGS and kwargs.get("dir_fd") is None:
                    recorder.note(args[0])
            elif kwargs.get("dir_fd") is None and kwargs.get("src_dir_fd") is None:
                recorder.note(args[-1] if name in ("replace", "rename", "symlink") else args[0])
            return original(*args, **kwargs)

        return call

    def builtin_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in "wxa+"):
            recorder.note(file)
        return real_open(file, mode, *args, **kwargs)

    for name in originals:
        monkeypatch.setattr(os, name, wrap(name))
    monkeypatch.setattr(builtins, "open", builtin_open)
    monkeypatch.setattr(io, "open", builtin_open)
    yield recorder


def templates() -> list[Template]:
    return [
        Template(
            id="agents", kind=Kind.TEMPLATE, target="AGENTS.md", source="t", render=lambda: "A\n"
        ),
        Template(
            id="ignore",
            kind=Kind.MANAGED_REGION,
            target=".gitignore",
            source="t",
            render=lambda: ".stayfixed/local/",
            region="ignores",
            style=Style.HASH,
        ),
        Template(
            id="doc",
            kind=Kind.TEMPLATE,
            target="docs/specs/README.md",
            source="t",
            render=lambda: "S\n",
        ),
    ]


def a_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
    return root


def test_apply_touches_exactly_the_paths_the_plan_named(tmp_path: Path) -> None:
    root = a_project(tmp_path)
    (tmp_path / "sibling").mkdir()
    (tmp_path / "sibling" / "untouched.txt").write_text("keep\n", encoding="utf-8")

    before = snapshot(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    planned = plan(root, config, templates())
    apply(root, planned)
    after = snapshot(tmp_path)

    # The three targets `templates()` names, spelled out. Deriving them from `planned.writes`
    # made this assertion agree with a planner that produced no actions at all: `apply` would
    # write only the manifest, and `changed` and `expected` would both be that one path.
    targets = {"AGENTS.md", ".gitignore", "docs/specs/README.md"}
    assert set(planned.writes) == targets
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    expected = {f"project/{target}" for target in targets} | {f"project/{MANIFEST_PATH}"}
    assert changed == expected


def test_no_absolute_path_outside_the_project_root_is_opened_for_writing(
    tmp_path: Path, trace: Trace
) -> None:
    root = a_project(tmp_path)
    config = load(root, machine=tmp_path / "absent.toml")
    apply(root, plan(root, config, templates()))
    assert trace.outside(root) == []


def test_the_trace_sees_a_write_the_tree_diff_cannot(tmp_path: Path, trace: Trace) -> None:
    # The anti-vacuity guard for the test above, and the demonstration that this instrument is
    # strictly stronger than the diff: a write to $HOME is invisible to a walk of tmp_path.
    root = a_project(tmp_path)
    outside = tmp_path.parent / "stayfixed-trace-probe.log"
    outside.write_text("x\n", encoding="utf-8")
    outside.unlink()
    assert trace.outside(root) == [str(outside)]


def test_the_walk_sees_something(tmp_path: Path) -> None:
    # The two diff assertions pass vacuously if `snapshot` ever returns nothing; this fails
    # exactly under that condition.
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert snapshot(tmp_path) == {"a.txt": "x"}
