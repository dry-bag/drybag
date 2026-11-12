from __future__ import annotations

import pytest

from drybag.findings import LISTED_LIMIT, Finding, labels, listed
from drybag.printed import UNPRINTABLE
from tests.crafted import CRAFTED, assert_never_raw


def test_a_label_is_the_path_the_line_and_the_rule_and_never_the_detail() -> None:
    # The summary line carries labels; `detail` may quote the repository and stays in `--json`.
    assert Finding("dead-link", "docs/a.md", 12, "quoted text").label == "docs/a.md:12 [dead-link]"
    assert (
        Finding("stale-index", "docs/bug-reports.md", None, "x").label
        == "docs/bug-reports.md [stale-index]"
    )
    assert Finding("base-unresolvable", "", None, "x").label == "- [base-unresolvable]"


def test_listed_caps_the_tail_and_says_how_many_it_dropped() -> None:
    # A check over a neglected tree reports findings by the hundred and the remediation is one
    # command for the whole set; the tail is length, not information, and printing it pushes that
    # command off the end of the line. Mutation: drop the cap — the first assertion reddens.
    items = [f"item-{n}" for n in range(LISTED_LIMIT + 3)]
    assert listed(items).endswith(", and 3 more")
    assert listed(items[:LISTED_LIMIT]).count(",") == LISTED_LIMIT - 1
    assert listed([]) == ""


def test_labels_renders_findings_through_the_same_cap() -> None:
    findings = [Finding("r", f"p{n}.md", n, "d") for n in range(LISTED_LIMIT + 1)]
    assert labels(findings).startswith("p0.md:0 [r], ") and labels(findings).endswith(
        ", and 1 more"
    )


def test_a_path_outside_the_grammar_never_reaches_a_label_raw() -> None:
    # The label is printed on stdout by `docs check` and `plan check`, and in CI a line that starts
    # `::error::` is an instruction to the runner.
    # Mutation: print `self.path` in `label` — this reddens.
    label = Finding("dead-link", f"docs/{CRAFTED}.md", 3, "d").label
    assert_never_raw(label)
    assert label == f"{UNPRINTABLE}:3 [dead-link]"
    assert labels([Finding("dead-link", CRAFTED, None, "d")]) == f"{UNPRINTABLE} [dead-link]"


@pytest.mark.parametrize("path", ["docs/Design Notes.md", "docs/заметки.md"])
def test_an_ordinary_name_outside_the_ascii_grammar_is_withheld_too(path: str) -> None:
    # The grammar is ASCII-only on purpose: a summary line is read by CI and by agents, and a
    # name that holds spaces can carry readable prose into it. So these print as the stand-in,
    # and `--json` names them. Pinned, because it is a choice and not an accident.
    assert Finding("dead-link", path, None, "d").label == f"{UNPRINTABLE} [dead-link]"
