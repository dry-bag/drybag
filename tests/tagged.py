"""The overlay fixture every tag test builds on: a project's record listing tags, and the
`tags/<tag>/` directories they name."""

from __future__ import annotations

from pathlib import Path

from drybag.tomlout import dumps


def list_tags(overlay: Path, project: str, tags: list[str]) -> None:
    """`project`'s record in `overlay` listing `tags`, in place of any list it held and after the
    rest of what it holds."""
    record = overlay / "projects" / project / "project.toml"
    record.parent.mkdir(parents=True, exist_ok=True)
    held = record.read_text(encoding="utf-8").splitlines(keepends=True) if record.exists() else []
    kept = "".join(line for line in held if not line.startswith("tags = "))
    record.write_text(kept + dumps({"": {"tags": tags}}), encoding="utf-8")


def with_tags(overlay: Path, project: str, tags: list[str], *inside: str) -> Path:
    """`list_tags`, and for each tag `tags/<tag>/<name>` for each name in `inside` (`tags/<tag>`
    alone given none); the overlay's root."""
    list_tags(overlay, project, tags)
    for tag in tags:
        for name in inside or ("",):
            (overlay / "tags" / tag / name).mkdir(parents=True, exist_ok=True)
    return overlay
