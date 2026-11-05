"""What a user reads before saying yes.

The count line names every outcome including the zeros, so "nothing was skipped" is something
the report says rather than something the reader has to notice is missing.

**Every target is printed through `printable`.** A plan reports an artifact whose record names a
target it cannot produce at the target `.stayfixed/manifest.json` recorded, and that file is
committed, so the string is repository-authored and may hold a line break or an escape sequence.
A target the path grammar accepts prints as itself; any other prints as `<artifact id>`, which is
this build's own vocabulary. The plan `apply` consumes is untouched: only what a person or an
agent reads is bounded, here, so no caller of this renderer can forget to.
"""

from __future__ import annotations

from stayfixed.grammar import PATH_VALUE
from stayfixed.scaffold.model import WRITING, Action, Plan, Refused, Verb


def printable(item: Action | Refused) -> str:
    """The target as it may be printed: itself inside the path grammar, its artifact id outside."""
    return item.target if PATH_VALUE.match(item.target) else f"<{item.artifact_id}>"


def render_report(planned: Plan) -> str:
    lines = [
        f"{action.verb:<14} {printable(action)}  ({action.reason})" for action in planned.actions
    ]
    if planned.unchanged:
        lines.append(f"{'unchanged':<14} {', '.join(sorted(planned.unchanged))}")
    if planned.refusals:
        lines.append("")
        lines.append("REFUSED — nothing will be written while any of these stands:")
        lines += [f"  {printable(r)}  ({r.reason})" for r in planned.refusals]
    created = sum(1 for a in planned.actions if a.verb is Verb.CREATE)
    updated = sum(1 for a in planned.actions if a.verb in WRITING and a.verb is not Verb.CREATE)
    skipped = sum(1 for a in planned.actions if a.verb is Verb.SKIP_MODIFIED)
    lines.append("")
    lines.append(
        f"{created} to create, {updated} to update, "
        f"{skipped} skipped, {len(planned.unchanged)} unchanged, {len(planned.refusals)} refused"
    )
    return "\n".join(lines)
