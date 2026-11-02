"""Budgets and links over the always-loaded documents: the enforced half of `docs check`."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from stayfixed.config.loader import load
from stayfixed.config.schema import Config
from stayfixed.docs.hygiene import (
    TRAIL_MARKER,
    check_budgets,
    check_links,
    local_markdown_targets,
    read_document,
    roadmap_prose,
)
from stayfixed.errors import Failure
from stayfixed.findings import Finding

CONFIG = """
[stayfixed]
version = "0.1.0"
enforced = ["docs", "bugs", "plan", "commit", "trail"]
preset = "recommended"
profile = ""
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
release_branch = "main"
"""

AGENTS = """# AGENTS.md

## Current status

- Current frontier.

## Rules

- Read the [guide](docs/guide.md).
"""


def project(tmp_path: Path, extra: str = "", agents: str = AGENTS) -> tuple[Path, Config]:
    root = tmp_path / "widget"
    (root / "docs").mkdir(parents=True)
    (root / "stayfixed.toml").write_text(CONFIG + extra, encoding="utf-8")
    (root / "AGENTS.md").write_text(agents, encoding="utf-8")
    (root / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    return root, load(root, machine=tmp_path / "m.toml")


def rules(findings: list[Finding]) -> list[str]:
    return [f.rule for f in findings]


def test_a_compliant_project_has_no_findings(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    assert check_budgets(root, config) == [] and check_links(root, config) == []


def test_a_link_through_a_symlink_out_of_the_tree_is_not_asked_of_the_filesystem(
    tmp_path: Path,
) -> None:
    # The link check is lexical before it asks `exists()`, which follows symlinks: a committed
    # `docs/l` pointing out of the tree made it an existence oracle for the machine, a present
    # file passing and an absent one reported. A symlink that stays inside the tree is still
    # followed. Oracle: `mutations/`'s "the AGENTS.md link check follows a symlink out of the
    # tree", "a path claim is followed through a symlink out of the tree".
    agents = AGENTS + "- [a](docs/l/secret.md)\n- [b](docs/l/absent.md)\n- [c](docs/in/gone.md)\n"
    root, config = project(tmp_path, agents=agents)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("", encoding="utf-8")
    (root / "docs" / "l").symlink_to(outside)
    (root / "docs" / "in").symlink_to(".")
    assert [(f.rule, f.detail) for f in check_links(root, config)] == [
        ("missing-link", "docs/in/gone.md")
    ]


def test_a_link_the_filesystem_cannot_name_is_missing_rather_than_a_crash(tmp_path: Path) -> None:
    # A name `exists()` raised on up to Python 3.13 and answered on 3.14; `fsops.exists` answers
    # it on every interpreter, unforced. No entry of its own, for the reason
    # `tests/docs/test_plans.py`'s case of it gives.
    long = "docs/" + "a" * 5000 + ".md"
    root, config = project(tmp_path, agents=AGENTS + f"- [x]({long})\n")
    assert [(f.rule, f.detail) for f in check_links(root, config)] == [("missing-link", long)]


def test_a_link_below_a_directory_that_cannot_be_searched_is_missing_rather_than_a_crash(
    tmp_path: Path,
) -> None:
    # Oracle: `mutations/`'s "a path the filesystem cannot answer for crashes the reference checks".
    if os.geteuid() == 0:
        pytest.skip("root searches every directory")
    root, config = project(tmp_path, agents=AGENTS + "- [x](docs/locked/child/x.md)\n")
    (root / "docs" / "locked" / "child").mkdir(parents=True)
    (root / "docs" / "locked").chmod(0o600)
    try:
        found = [(f.rule, f.detail) for f in check_links(root, config)]
    finally:
        (root / "docs" / "locked").chmod(0o700)
    assert found == [("missing-link", "docs/locked/child/x.md")]


def test_a_missing_agents_file_is_a_finding(tmp_path: Path) -> None:
    root, config = project(tmp_path)
    (root / "AGENTS.md").unlink()
    assert rules(check_budgets(root, config)) == ["missing-document"]
    assert check_links(root, config) == []


def test_the_agents_line_and_word_budgets_are_the_effective_ones(tmp_path: Path) -> None:
    # Read from the configuration, never spelled here: a raised preset budget would otherwise
    # leave this test asserting the old number and testing nothing.
    root, config = project(tmp_path)
    lines = config.budgets.effective("agents_md_lines")
    head = "# A\n\n## Current status\n\n- x\n\n## Next\n\n"
    (root / "AGENTS.md").write_text(head + "line\n" * lines, encoding="utf-8")
    assert rules(check_budgets(root, config)) == ["agents-lines"]
    words = config.budgets.effective("agents_md_words")
    (root / "AGENTS.md").write_text(head + ("w " * (words + 1)) + "\n", encoding="utf-8")
    assert rules(check_budgets(root, config)) == ["agents-words"]


def test_a_project_may_lower_a_budget_and_the_lower_one_applies(tmp_path: Path) -> None:
    # Mutation: read `config.budgets.preset[...]` instead of `effective(...)` — this reddens.
    root, config = project(tmp_path, "\n[budgets]\nagents_md_lines = 4\n")
    assert rules(check_budgets(root, config)) == ["agents-lines"]  # AGENTS above is 9 lines


def test_the_current_status_section_is_required_and_budgeted(tmp_path: Path) -> None:
    root, config = project(tmp_path, agents="# A\n\n## Rules\n\n- x\n")
    assert rules(check_budgets(root, config)) == ["status-missing"]
    root, config = project(tmp_path / "two", "\n[budgets]\nstatus_lines = 2\n")
    assert rules(check_budgets(root, config)) == ["status-lines"]


def test_the_agents_file_path_comes_from_configuration(tmp_path: Path) -> None:
    root, config = project(tmp_path, '\n[paths]\nagents_md = "CONTEXT.md"\n')
    (root / "AGENTS.md").rename(root / "CONTEXT.md")
    assert check_budgets(root, config) == [] and check_links(root, config) == []


def test_a_missing_local_link_target_is_a_finding_and_external_links_are_not(
    tmp_path: Path,
) -> None:
    root, config = project(
        tmp_path,
        agents=AGENTS
        + "- [gone](docs/gone.md) [a](#x) [b](/abs) [c](https://e.com/x.md) [d](mailto:a@b.c)\n",
    )
    found = check_links(root, config)
    assert [(f.rule, f.detail) for f in found] == [("missing-link", "docs/gone.md")]


def test_a_link_inside_a_fence_is_an_example_not_a_claim(tmp_path: Path) -> None:
    # The other prose reader (`docs.plans`) blanks fences; this one must too.
    # Mutation: scan the raw text instead of the blanked one — this reddens.
    root, config = project(tmp_path, agents=AGENTS + "```\n[x](docs/example.md)\n```\n")
    assert check_links(root, config) == []


def test_the_roadmap_prose_is_budgeted_up_to_the_trail_marker(tmp_path: Path) -> None:
    root, config = project(tmp_path, "\n[budgets]\nroadmap_prose_lines = 3\n")
    (root / "docs" / "roadmap.md").write_text(
        "# R\n\nprose\n" + f"{TRAIL_MARKER}\n" + "row\n" * 10, encoding="utf-8"
    )
    assert check_budgets(root, config) == []
    (root / "docs" / "roadmap.md").write_text(
        "# R\n\nprose\nmore\n" + f"{TRAIL_MARKER}\n", encoding="utf-8"
    )
    assert rules(check_budgets(root, config)) == ["roadmap-lines"]


def test_a_deeper_heading_containing_the_marker_does_not_split_the_prose(tmp_path: Path) -> None:
    # Mutation: split on a substring instead of the anchored line — this reddens.
    text = f"# R\n\n### {TRAIL_MARKER[3:]}\n" + "p\n" * 5 + f"{TRAIL_MARKER}\nrow\n"
    assert roadmap_prose(text).count("\n") == 8


def test_a_roadmap_without_the_marker_is_measured_whole_and_an_absent_one_is_not_a_finding(
    tmp_path: Path,
) -> None:
    root, config = project(tmp_path, "\n[budgets]\nroadmap_prose_lines = 2\n")
    assert check_budgets(root, config) == []
    (root / "docs" / "roadmap.md").write_text("a\nb\nc\n", encoding="utf-8")
    assert rules(check_budgets(root, config)) == ["roadmap-lines"]


def test_a_non_utf8_document_is_the_projects_file_being_wrong_not_an_internal_error(
    tmp_path: Path,
) -> None:
    # `cli.run` maps a `Failure` to 1 and everything else to 2, and 2 is the code a caller is
    # told never to read as permission. One latin-1 byte in either always-loaded document used
    # to reach the frame as `internal error: UnicodeDecodeError`. Mutation: drop the
    # `UnicodeDecodeError` arm of `read_document` — all three cases redden.
    root, config = project(tmp_path)
    (root / "docs" / "roadmap.md").write_bytes("# R\n\ncaf\xe9\n".encode("latin-1"))
    with pytest.raises(Failure, match=r"docs/roadmap\.md: is not valid UTF-8"):
        check_budgets(root, config)
    (root / "AGENTS.md").write_bytes(AGENTS.encode("utf-8") + b"caf\xe9\n")
    with pytest.raises(Failure, match=r"AGENTS\.md: is not valid UTF-8"):
        check_budgets(root, config)
    with pytest.raises(Failure, match=r"AGENTS\.md: is not valid UTF-8"):
        check_links(root, config)


def test_a_link_out_of_the_root_is_never_settled_against_this_disk(tmp_path: Path) -> None:
    # `_normalise_target` already drops an absolute link; a `..` one walked out of the project
    # and was settled against the developer's disk, which is an existence oracle and makes the
    # verdict depend on the machine. The assertion is that the answer does not change with the
    # file. Mutation: drop `resolves_within`'s containment — the second call reddens.
    root, config = project(tmp_path, agents=AGENTS + "\n- [out](../outside/secret.md)\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("", encoding="utf-8")
    assert check_links(root, config) == []
    (outside / "secret.md").unlink()
    assert check_links(root, config) == []


def test_a_link_out_of_the_documents_own_directory_but_inside_the_root_still_resolves(
    tmp_path: Path,
) -> None:
    # Containment is judged against the project root, not against the document's directory: a
    # link from `docs/AGENTS.md` into `src/` is inside the project. Mutation: contain against
    # `agents_path.parent` — the first assertion reddens.
    root, _config = project(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "boot.py").write_text("", encoding="utf-8")
    (root / "docs" / "AGENTS.md").write_text(
        AGENTS + "\n- [b](../src/boot.py)\n- [g](../src/gone.py)\n", encoding="utf-8"
    )
    (root / "stayfixed.toml").write_text(
        CONFIG + '\n[paths]\nagents_md = "docs/AGENTS.md"\n', encoding="utf-8"
    )
    config = load(root, machine=tmp_path / "m.toml")
    # `docs/guide.md` too: from `docs/` that link names `docs/docs/guide.md`, which is the
    # point — a link is read from its own document's directory, and only the containment
    # boundary is the root.
    assert [f.detail for f in check_links(root, config)] == ["docs/guide.md", "../src/gone.py"]


def test_the_link_reader_reads_the_links_it_always_read() -> None:
    # The pattern was rewritten to stop backtracking; these are the shapes it has to keep.
    text = "[a](b.md) ![img](x.png) [x](y.md) and [z](w.md#h) [a](x[1].md)"
    assert local_markdown_targets(text) == ["b.md", "y.md", "w.md", "x[1].md"]


def test_a_text_of_unclosed_links_is_read_in_linear_time() -> None:
    # `[a](` repeated made every opening bracket scan to the end of the text: quadratic, 0.55 s
    # at 20,000 characters and four times as long per doubling. Measured as a RATIO against well
    # formed links of the same length, which run the same reader to the same place, not against
    # a clock: whatever load inflates one call inflates the other. Measured: 0.4 with the
    # linear pattern and 200 with the old one. Mutation (declared): the old pattern back ->
    # this reddens.
    size = 20_000

    def cpu(text: str) -> float:
        start = time.process_time()
        local_markdown_targets(text)
        return time.process_time() - start

    benign = cpu("[a](b)" * (size // 6))
    assert cpu("[a](" * (size // 4)) < 20 * max(benign, 0.001)


def test_a_document_linked_to_a_device_is_a_failure_naming_it(tmp_path: Path) -> None:
    # `plan check` outside a git repository globs `docs/plans/` and reads each match, and a link
    # there to `/dev/stdin` hung it. Only a regular file is read; `/dev/null` is the case that
    # cannot hang and still tells the guard apart, since unguarded it reads as an empty plan.
    # Mutation (declared): `read_document` reads with `read_text` again -> this reddens.
    (tmp_path / "plan.md").symlink_to("/dev/null")
    with pytest.raises(Failure, match="could not be read \\(not a regular file\\)"):
        read_document(tmp_path / "plan.md", "docs/plans/plan.md")
