"""Every file `templates/project/` ships; the tree and the list are two statements of one
thing, held each way round by a test.

A name here that no file answers to makes `read` refuse at runtime, and a file here that no
name covers ships in the wheel unseen — `tests/project/test_templates.py` walks the tree with
`rglob` and compares both directions, and `scripts/check_artifacts.py` reads this list to ask
the built wheel the same question.
"""

from __future__ import annotations

PROJECT_FILES: tuple[str, ...] = (
    "documentation.md",
    "adr-template.md",
    "bug-reports-runbook.md",
    "audits-readme.md",
    "roadmap.md",
    "roadmap-history.md",
    "trail.toml",
    "gitkeep",
    "agents-skeleton.md",
    "agents-region.md",
    "claude.md",
)
