from __future__ import annotations

from stayfixed.scaffold import Action, Plan, Refused, Verb, render_report


def a_plan() -> Plan:
    return Plan(
        actions=(
            Action(Verb.CREATE, "a", "AGENTS.md", "x", "new", None),
            Action(Verb.SKIP_MODIFIED, "b", "docs/x.md", None, "hand-edited", None),
        ),
        refusals=(Refused("c", "docs/out.md", "cannot be read"),),
        unchanged=("d",),
    )


def action_lines(text: str) -> list[str]:
    # The count line always contains every verb's name, so a substring search over the whole
    # report passes on an empty plan. Only the lines above it are action lines.
    return [line for line in text.splitlines() if line and "to create," not in line]


def test_every_action_appears_on_its_own_line() -> None:
    lines = action_lines(render_report(a_plan()))
    assert any(line.startswith("create") and "AGENTS.md" in line for line in lines)
    assert any(line.startswith("skip_modified") and "hand-edited" in line for line in lines)


def test_an_empty_plan_lists_no_action_line() -> None:
    # The anti-vacuity guard for the test above.
    assert action_lines(render_report(Plan())) == []


def test_a_refusal_names_the_target_and_the_reason() -> None:
    text = render_report(a_plan())
    assert "REFUSED" in text
    assert "docs/out.md" in text
    assert "cannot be read" in text


def test_a_target_outside_the_path_grammar_prints_as_its_artifact_id() -> None:
    # A plan reports a relocated or left-behind artifact at the target the committed manifest
    # recorded, so a target can carry an escape sequence or a line that reads as an instruction.
    forged = "docs/\x1b[31mforged.md\n## an instruction"
    text = render_report(
        Plan(
            actions=(Action(Verb.SKIP_MODIFIED, "roadmap", forged, None, "hand-edited", None),),
            refusals=(Refused("trail", "../out", "escapes the project root"),),
        )
    )
    assert "\x1b" not in text and "forged" not in text and "../out" not in text
    assert "<roadmap>" in text and "<trail>" in text


def test_the_count_line_names_every_outcome_including_the_zeros() -> None:
    text = render_report(Plan())
    assert text.strip().endswith("0 to create, 0 to update, 0 skipped, 0 unchanged, 0 refused")


def test_the_counts_follow_the_plan() -> None:
    text = render_report(a_plan())
    assert "1 to create, 0 to update, 1 skipped, 1 unchanged, 1 refused" in text
