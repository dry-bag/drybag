"""The pre-render: the overlay's indexes rendered from the checkouts this machine's sessions opened.

An index renders only from a checkout bound to its project, so the job renders through the newest
recorded checkout of each project whose notes changed, and through every recorded one when a shared
or a group note did. A project it cannot render keeps its `MEMORY.md` out of the commit, named; its
notes still travel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stayfixed.sync import job as J
from stayfixed.sync.render import (
    CHECKOUTS_KEPT,
    NO_CHECKOUT,
    checkouts,
    prerender,
    remember_checkout,
)
from stayfixed.sync.rules import dirty_memory
from stayfixed.sync.state import CHECKOUTS_FILE
from tests.sync.conftest import (
    SLOW,
    TAG,
    Overlays,
    committed,
    context,
    note_text,
    write,
)


def _dirty(clone: Path) -> list[str]:
    return dirty_memory(clone, timeout=SLOW)


def _index(clone: Path, project: str) -> str:
    return (clone / f"projects/{project}/memory/MEMORY.md").read_text(encoding="utf-8")


def test_a_recorded_checkout_list_keeps_the_newest_64(tmp_path: Path) -> None:
    roots = [tmp_path / f"checkout-{number}" for number in range(CHECKOUTS_KEPT + 6)]
    for root in roots:
        remember_checkout(root, tmp_path / "state")
    remember_checkout(roots[10], tmp_path / "state")  # opened again: first, and once

    kept = checkouts(tmp_path / "state")

    assert kept[0] == roots[10] and kept.count(roots[10]) == 1
    assert len(kept) == CHECKOUTS_KEPT
    assert kept[1:4] == [roots[-1], roots[-2], roots[-3]]
    assert roots[0] not in kept


def test_a_garbled_record_of_checkouts_is_none(tmp_path: Path) -> None:
    (tmp_path / CHECKOUTS_FILE).write_text('{"not": "a list"}', encoding="utf-8")
    assert checkouts(tmp_path) == []
    (tmp_path / CHECKOUTS_FILE).write_text('["relative/path", 3]', encoding="utf-8")
    assert checkouts(tmp_path) == []


def test_a_dirty_project_note_renders_that_project_only(overlays: Overlays) -> None:
    a = overlays.a
    beta = _index(a, "beta")
    write(a, "projects/alpha/memory/project-stable/new.md", note_text("new", index="New one"))

    assert prerender(a, _dirty(a), overlays.state_dir) == {}

    assert "- [New one](project-stable/new.md)" in _index(a, "alpha")
    assert _index(a, "beta") == beta


@pytest.mark.parametrize("scope", ["common", "group"])
def test_a_dirty_common_or_group_note_renders_every_recorded_project(
    overlays: Overlays, scope: str
) -> None:
    # A group note re-renders every recorded project, like a common one: which projects carry a
    # group is another reader's. Mutation (oracle): `mutations/`'s "a group note does not
    # re-render the recorded projects".
    a = overlays.a
    for project in ("alpha", "beta"):  # an index each, stale against its notes
        write(a, f"projects/{project}/memory/MEMORY.md", "# stale\n")
    git_path = "common/memory/shared.md" if scope == "common" else f"groups/{TAG}/memory/two.md"
    write(a, git_path, note_text("shared", index="Shared"))
    dirty = [path for path in _dirty(a) if not path.endswith("MEMORY.md")]

    assert prerender(a, dirty, overlays.state_dir) == {}

    for project in ("alpha", "beta"):
        assert f"- [{project} trigger](project-stable/{project}-one.md)" in _index(a, project)
    assert _index(a, "gamma") == "# gamma's index, rendered elsewhere\n"  # no checkout, not dirty


def test_a_project_with_no_recorded_checkout_keeps_its_index_out_and_says_so(
    overlays: Overlays,
) -> None:
    a = overlays.a
    write(a, "projects/gamma/memory/project-stable/new.md", note_text("new"))
    with open(a / "projects/gamma/memory/MEMORY.md", "a", encoding="utf-8") as index:
        index.write("- [An agent's line](project-stable/new.md)\n")
    write(a, "projects/delta/memory/project-stable/d.md", note_text("d"))
    ctx = context(overlays, a)

    assert prerender(a, _dirty(a), overlays.state_dir) == {
        "gamma": NO_CHECKOUT,
        "delta": NO_CHECKOUT,
    }
    assert J.commit_memory(ctx) is None

    paths = {path for _, path in committed(a)}
    assert {
        "projects/gamma/memory/project-stable/new.md",
        "projects/delta/memory/project-stable/d.md",
    } <= paths
    assert "projects/gamma/memory/MEMORY.md" not in paths
    assert any("projects/gamma/memory/MEMORY.md left out" in remark for remark in ctx.remarks)


def test_a_group_note_travels_without_any_recorded_checkout(overlays: Overlays) -> None:
    # A tag's note with no recorded checkout is still committed; only the
    # indexes are left out, and named.
    a = overlays.a
    (overlays.state_dir / CHECKOUTS_FILE).unlink()
    note = f"groups/{TAG}/memory/{TAG}-two.md"
    write(a, note, note_text(f"{TAG}-two", index="Team two"))
    with open(a / "projects/alpha/memory/MEMORY.md", "a", encoding="utf-8") as index:
        index.write("- [An agent's line](project-stable/alpha-one.md)\n")
    ctx = context(overlays, a)

    assert J.commit_memory(ctx) is None

    paths = {path for _, path in committed(a)}
    assert note in paths and "projects/alpha/memory/MEMORY.md" not in paths
    assert ctx.remarks == [f"projects/alpha/memory/MEMORY.md left out of the commit: {NO_CHECKOUT}"]


def test_the_newest_checkout_of_a_project_renders_it(overlays: Overlays, tmp_path: Path) -> None:
    # A checkout recorded and then removed is passed over for an older one of another project.
    a = overlays.a
    remember_checkout(tmp_path / "gone", overlays.state_dir)
    write(a, "projects/beta/memory/project-stable/new.md", note_text("new", index="Beta new"))

    assert prerender(a, _dirty(a), overlays.state_dir) == {}

    assert "- [Beta new](project-stable/new.md)" in _index(a, "beta")


def test_a_linked_project_directory_is_never_rendered_through(
    overlays: Overlays, tmp_path: Path
) -> None:
    # `projects/alpha` a link: the store the render reaches is not the overlay's, so nothing is
    # written there, and the reason says so.
    a = overlays.a
    outside = tmp_path / "outside-alpha"
    (a / "projects" / "alpha").rename(outside)
    (a / "projects" / "alpha").symlink_to(outside, target_is_directory=True)
    before = (outside / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    write(a, "common/memory/shared.md", note_text("shared"))

    reasons = prerender(a, _dirty(a), overlays.state_dir)

    assert set(reasons) == {"alpha"} and "link" in reasons["alpha"]
    assert (outside / "memory" / "MEMORY.md").read_text(encoding="utf-8") == before
    assert "developer/shared.md" in _index(a, "beta")


def test_an_index_that_is_a_link_is_not_rendered_through(
    overlays: Overlays, tmp_path: Path
) -> None:
    a = overlays.a
    outside = tmp_path / "outside-index.md"
    outside.write_text("# not the overlay's\n", encoding="utf-8")
    index = a / "projects/alpha/memory/MEMORY.md"
    index.unlink()
    index.symlink_to(outside)
    write(a, "projects/alpha/memory/project-stable/alpha-new.md", note_text("alpha-new"))
    ctx = context(overlays, a)

    assert J.commit_memory(ctx) is None

    assert outside.read_text(encoding="utf-8") == "# not the overlay's\n"
    assert any("MEMORY.md left out" in remark and "link" in remark for remark in ctx.remarks)
    assert ("A", "projects/alpha/memory/project-stable/alpha-new.md") in committed(a)


def test_nothing_renders_while_the_machine_file_records_another_overlay(
    overlays: Overlays,
) -> None:
    # The render writes into the overlay the machine file records, so a job on any other one
    # renders nothing and leaves the indexes out.
    a, b = overlays.a, overlays.b
    alpha = _index(a, "alpha")
    write(b, "projects/alpha/memory/project-stable/new.md", note_text("new"))

    reasons = prerender(b, _dirty(b), overlays.state_dir)

    assert set(reasons) == {"alpha"} and "another overlay" in reasons["alpha"]
    assert _index(a, "alpha") == alpha


def test_a_checkout_that_is_not_bound_is_passed_over(overlays: Overlays) -> None:
    a = overlays.a
    (overlays.checkouts["alpha"] / "stayfixed.toml").write_text(
        (overlays.checkouts["alpha"] / "stayfixed.toml")
        .read_text(encoding="utf-8")
        .replace('name = "alpha"', 'name = "renamed"'),
        encoding="utf-8",
    )
    write(a, "projects/alpha/memory/project-stable/new.md", note_text("new"))

    reasons = prerender(a, _dirty(a), overlays.state_dir)

    assert set(reasons) == {"alpha"} and reasons["alpha"].startswith("not pre-rendered: ")
