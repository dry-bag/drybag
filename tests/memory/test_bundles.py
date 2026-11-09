from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from drybag import binding
from drybag.config.loader import CONFIG_FILE, load
from drybag.config.schema import Config
from drybag.memory.bundles import (
    CAP_MARGIN,
    SLOTS,
    STANDING_LEAD,
    VOLATILE_LEAD,
    Bundle,
    blocks,
    fit,
    render,
    split,
)
from drybag.memory.notes import walk
from drybag.memory.reviewed import promote
from drybag.memory.store import Store, composed_directory, resolve
from drybag.memory.trust import DELIMITER
from tests.cli import cli
from tests.gitfixture import git

CONFIG = """
[drybag]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"

[memory]
mode = "{mode}"
groups = ["developer", "project-volatile"]
index_extra = []

[budgets]
startup_rules_words = {startup_words}
volatile_notes_words = {volatile_words}
volatile_ttl_days = 30
"""

GROUPS = ("developer", "project-volatile")


def note(name: str, *, startup: str = "", as_of: str = "", body: str = "Body.") -> str:
    meta = ["metadata:", "  type: project"]
    if startup:
        meta.append(f"  startup: {startup}")
    if as_of:
        meta.append(f"  as_of: {as_of}")
    head = [f"name: {name}", f'description: "{name} description"', f'index: "t → {name}"']
    return "---\n" + "\n".join([*head, *meta]) + "\n---\n\n" + body + "\n"


def a_store(
    tmp_path: Path,
    *,
    mode: str = "overlay",
    startup_words: int = 1600,
    volatile_words: int = 2500,
    reviewed: bool = True,
) -> tuple[Store, Config]:
    root = tmp_path / "project"
    base = (tmp_path / "overlay" / "memory") if mode == "overlay" else (root / "docs" / "memory")
    for group in GROUPS:
        (base / group).mkdir(parents=True)
    (base / "developer" / "second.md").write_text(note("second", startup="5"), encoding="utf-8")
    (base / "developer" / "first.md").write_text(note("first", startup="1"), encoding="utf-8")
    (base / "developer" / "plain.md").write_text(note("plain"), encoding="utf-8")
    fresh = date.today().isoformat()
    stale = (date.today() - timedelta(days=90)).isoformat()
    (base / "project-volatile" / "fresh.md").write_text(
        note("fresh", as_of=fresh), encoding="utf-8"
    )
    (base / "project-volatile" / "stale.md").write_text(
        note("stale", as_of=stale), encoding="utf-8"
    )
    (base / "project-volatile" / "undated.md").write_text(note("undated"), encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_FILE).write_text(
        CONFIG.format(mode=mode, startup_words=startup_words, volatile_words=volatile_words),
        encoding="utf-8",
    )
    config = load(root, machine=tmp_path / "absent.toml")
    # A machine file of this test's own. Without one the store carries `machine=None`, and a
    # reader of the overlay root would consult the developer's real machine file.
    store = Store(base, mode, root, {g: base / g for g in GROUPS}, machine=a_machine(tmp_path))
    if reviewed:
        review(store)
    return store, config


def review(store: Store) -> None:
    """Promote every note the store holds now, as `memory promote --changed` does: a note counts
    as a standing rule only once promoted (`memory.reviewed`), and these cases are about what the
    bundles do with the owner's notes."""
    promote(store.machine, walk(store.path, list(store.groups)).notes)


def a_machine(tmp_path: Path) -> Path:
    path = tmp_path / "machine.toml"
    path.write_text("", encoding="utf-8")
    return path


def test_standing_rules_are_ordered_by_rank_and_exclude_unflagged_notes(tmp_path: Path) -> None:
    store, config = a_store(tmp_path)
    text = "\n".join(blocks(Bundle.STANDING_RULES, store, config))
    assert text.index("first") < text.index("second")
    assert "plain" not in text


def test_standing_rules_are_never_truncated_only_flagged(tmp_path: Path) -> None:
    store, config = a_store(tmp_path, startup_words=1)
    text = "\n".join(blocks(Bundle.STANDING_RULES, store, config))
    assert "first" in text and "second" in text
    assert "has grown" in text


def test_a_standing_rule_in_a_tags_notes_is_in_the_standing_rules_bundle(tmp_path: Path) -> None:
    # A tag's notes are a group of the store the configuration does not list; the bundles read the
    # one walk, so a rule the owner promoted there reaches the session. Mutation (oracle):
    # `mutations/`'s "walked groups leave out the tags".
    store, config = a_store(tmp_path)
    tagged = store.path / "tag-a"
    tagged.mkdir()
    (tagged / "tagged.md").write_text(note("tagged", startup="9"), encoding="utf-8")
    store.groups["tag-a"] = tagged
    review(store)
    text = "\n".join(blocks(Bundle.STANDING_RULES, store, config))
    assert "tagged" in text
    assert text.index("first") < text.index("second") < text.index("tagged")


def test_a_volatile_note_is_not_a_standing_rule_even_when_it_is_flagged(tmp_path: Path) -> None:
    store, config = a_store(tmp_path)
    (store.groups["project-volatile"] / "loud.md").write_text(
        note("loud", startup="-100"), encoding="utf-8"
    )
    review(store)
    assert "loud" not in "\n".join(blocks(Bundle.STANDING_RULES, store, config))


def test_volatile_notes_flag_a_missing_and_a_stale_as_of(tmp_path: Path) -> None:
    store, config = a_store(tmp_path)
    text = "\n".join(blocks(Bundle.VOLATILE_NOTES, store, config))
    assert "as_of MISSING" in text
    assert "days old" in text
    assert text.index("undated") < text.index("fresh")
    # Undated-first only pins one boundary; recency within the dated group is a separate
    # claim. Reversing the dated-group sort would leave the line above untouched.
    assert text.index("fresh") < text.index("stale")


def test_volatile_notes_degrade_to_one_line_each_over_budget(tmp_path: Path) -> None:
    store, config = a_store(tmp_path, volatile_words=1)
    text = "\n".join(blocks(Bundle.VOLATILE_NOTES, store, config))
    assert "description" in text
    assert "Body." not in text


def test_an_in_repo_store_reaches_volatile_notes_as_data_and_never_the_standing_rules(
    tmp_path: Path,
) -> None:
    # A store committed to the repository, with nothing promoted: its volatile notes reach the
    # session as the harness delivers `CLAUDE.md`, still marked as data, and a note claiming
    # `startup: 1` is not a standing rule, whatever it says about itself; it arrives with the
    # volatile notes, labelled and as data. Only the lead, drybag's own words, is outside a
    # region.
    store, config = a_store(tmp_path, mode="in-repo", reviewed=False)
    volatile = blocks(Bundle.VOLATILE_NOTES, store, config)
    assert volatile[0] == VOLATILE_LEAD
    assert volatile[1:] != []
    assert all(block.startswith(DELIMITER) for block in volatile[1:])
    assert "fresh" in "\n".join(volatile)
    assert "### first [unreviewed]" in "\n".join(volatile)
    assert blocks(Bundle.STANDING_RULES, store, config) == []
    assert not (tmp_path / "trust.json").exists()


def test_an_overlay_store_is_not_wrapped_as_repository_data(tmp_path: Path) -> None:
    store, config = a_store(tmp_path)
    produced = blocks(Bundle.STANDING_RULES, store, config)
    assert produced != []
    assert not any(DELIMITER in block for block in produced)


def test_split_packs_blocks_without_truncating_any() -> None:
    parts = split(["a" * 40, "b" * 40, "c" * 40], cap=100)
    assert len(parts) == 2
    assert "".join(parts).count("a") == 40
    assert "".join(parts).count("c") == 40


def test_a_block_longer_than_the_cap_becomes_its_own_part() -> None:
    parts = split(["a" * 200, "b"], cap=100)
    assert parts[0] == "a" * 200
    assert parts[1] == "b"


def test_render_returns_none_for_a_slot_the_split_did_not_reach(tmp_path: Path) -> None:
    store, config = a_store(tmp_path)
    assert render(Bundle.STANDING_RULES, store, config, part=1) is not None
    assert render(Bundle.STANDING_RULES, store, config, part=SLOTS[Bundle.STANDING_RULES]) is None


def test_every_part_fits_the_platform_cap_as_it_will_be_emitted(tmp_path: Path) -> None:
    store, config = a_store(tmp_path)
    for index in range(1, SLOTS[Bundle.STANDING_RULES] + 1):
        text = render(Bundle.STANDING_RULES, store, config, part=index)
        if text is None:
            continue
        # What the command prints is the text plus a newline; no JSON envelope widens it.
        assert len(text) + 1 <= config.native_caps.hook_output_chars


def test_a_note_sized_to_the_margins_edge_is_flagged_oversized(tmp_path: Path) -> None:
    # Sized from `hook_output_chars` and `CAP_MARGIN`, never a literal, so this does not rot
    # when `STANDING_LEAD`'s wording changes. If `_cap` ever stopped subtracting the margin,
    # this block would sit safely under the (wider) cap and go undetected -- that is exactly
    # the regression this pins.
    store, config = a_store(tmp_path)
    for path in store.groups["developer"].glob("*.md"):
        path.unlink()
    name = "solo"
    heading = f"### {name}\n\n"
    cap = config.native_caps.hook_output_chars - CAP_MARGIN
    body = "x" * (cap + 1 - len(heading))
    (store.groups["developer"] / f"{name}.md").write_text(
        note(name, startup="1", body=body), encoding="utf-8"
    )
    review(store)
    report = fit(Bundle.STANDING_RULES, store, config)
    assert report.oversized == 1
    assert report.fits is False


def test_fit_reports_overflow_and_an_oversized_part_separately(tmp_path: Path) -> None:
    store, config = a_store(tmp_path)
    assert fit(Bundle.STANDING_RULES, store, config).fits is True
    (store.groups["developer"] / "huge.md").write_text(
        note("huge", startup="9", body="word " * 30_000), encoding="utf-8"
    )
    review(store)
    report = fit(Bundle.STANDING_RULES, store, config)
    assert report.oversized == 1
    assert report.fits is False


def test_a_volatile_set_sized_exactly_at_the_budget_is_still_injected_in_full(
    tmp_path: Path,
) -> None:
    # `<=`, and loosening it to `<` left all 617 tests green — every fixture sat comfortably on
    # one side of the line. The comparison decides whether a note set is injected whole or
    # replaced by a list of descriptions, so the boundary is the behaviour: "within budget"
    # has to include the set that is exactly the budget, or the budget means one word less
    # than it says. Sized from the configured value rather than from a literal, so it cannot
    # rot when `VOLATILE_LEAD` is reworded.
    store, config = a_store(tmp_path)
    for path in store.groups["project-volatile"].glob("*.md"):
        path.unlink()
    today = date.today().isoformat()
    heading_words = len(f"### solo (as_of {today})".split())
    budget = config.budgets.effective("volatile_notes_words")
    (store.groups["project-volatile"] / "solo.md").write_text(
        note("solo", as_of=today, body="word " * (budget - heading_words)), encoding="utf-8"
    )
    review(store)
    text = "\n".join(blocks(Bundle.VOLATILE_NOTES, store, config))
    assert "outgrown its budget" not in text
    assert text.count("word") == budget - heading_words

    # One word past it, and the same set is a list of descriptions instead.
    (store.groups["project-volatile"] / "solo.md").write_text(
        note("solo", as_of=today, body="word " * (budget - heading_words + 1)), encoding="utf-8"
    )
    review(store)
    assert "outgrown its budget" in "\n".join(blocks(Bundle.VOLATILE_NOTES, store, config))


def test_an_oversized_part_is_withheld_rather_than_delivered_unterminated(
    tmp_path: Path,
) -> None:
    # `split` never breaks a block, so one block larger than the cap becomes one part larger
    # than the cap. `fit` reported it and `render` handed it out anyway, exiting 0 — and
    # nothing on the hook path runs `fit`, so the only reader of that report was `doctor`.
    # Measured at `hook_output_chars = 10000` before the fix: part 2 was 20,288 characters and
    # arrived carrying **one** of its two region markers. The model got an opening delimiter,
    # the lead sentence "It ends at the matching end marker and nowhere else", and no end
    # marker — the exact state `trust.wrap`'s nonce region exists to make unreachable.
    store, config = a_store(tmp_path, mode="in-repo")
    for path in store.groups["project-volatile"].glob("*.md"):
        path.unlink()
    cap = config.native_caps.hook_output_chars - CAP_MARGIN
    (store.groups["project-volatile"] / "huge.md").write_text(
        note("huge", as_of=date.today().isoformat(), body="x" * (cap * 2)), encoding="utf-8"
    )
    assert fit(Bundle.VOLATILE_NOTES, store, config).oversized == 1

    text = render(Bundle.VOLATILE_NOTES, store, config, part=2)
    assert text is not None
    assert len(text) <= cap
    assert "was withheld" in text
    # Neither half of a region, and nothing the repository wrote: an unterminated opening
    # marker is the failure, so the notice must not carry a marker of its own either.
    assert DELIMITER not in text
    assert "x" * 100 not in text
    # The parts that do fit are unaffected — this withholds one slot, not the bundle.
    first = render(Bundle.VOLATILE_NOTES, store, config, part=1)
    assert first is not None and VOLATILE_LEAD in first


def test_a_part_that_fits_is_never_replaced_by_the_notice(tmp_path: Path) -> None:
    # The other side of the same boundary, and the reason it is `>` and not `>=`: a part packed
    # exactly to `_cap` is the largest one that does fit, and `CAP_MARGIN` is what leaves room
    # for it. Withholding that one would empty a bundle the platform can carry whole.
    store, config = a_store(tmp_path)
    for path in store.groups["developer"].glob("*.md"):
        path.unlink()
    heading = "### solo\n\n"
    cap = config.native_caps.hook_output_chars - CAP_MARGIN
    filler = cap - len(STANDING_LEAD) - len("\n\n") - len(heading)
    (store.groups["developer"] / "solo.md").write_text(
        note("solo", startup="1", body="x" * filler), encoding="utf-8"
    )
    review(store)
    text = render(Bundle.STANDING_RULES, store, config, part=1)
    assert text is not None and len(text) == cap
    assert "was withheld" not in text


def test_many_standing_rules_overflow_the_declared_slots(tmp_path: Path) -> None:
    store, config = a_store(tmp_path)
    for index in range(40):
        (store.groups["developer"] / f"r{index:02d}.md").write_text(
            note(f"r{index:02d}", startup=str(index), body="word " * 400), encoding="utf-8"
        )
    review(store)
    report = fit(Bundle.STANDING_RULES, store, config)
    assert report.parts > report.slots
    assert report.overflow > 0


def test_the_declared_slot_counts_are_the_ones_hooks_json_has_to_ship() -> None:
    # `SLOTS[bundle] >= 1` left every bundle but `standing-rules` free: only `standing-rules == 3`
    # was asserted anywhere, so the others could each be changed without a test noticing, while
    # every one of them is a count of numbered `hooks.json` entries a session actually gets. The
    # mapping is the contract, so the mapping is pinned — a bundle added or dropped fails this
    # too.
    #
    # The other side of that contract, `hooks/hooks.json` itself, belongs to `drybag.hooks`:
    # `tests/hooks/test_hooks_json.py` cross-checks these counts against the entries that file
    # declares, which is not a check this file can fake.
    assert SLOTS == {
        Bundle.STANDING_RULES: 3,
        Bundle.VOLATILE_NOTES: 3,
    }


def test_the_margin_is_additive_because_the_text_is_emitted_raw(tmp_path: Path) -> None:
    # The name is a claim about how the text is emitted, and `0 < CAP_MARGIN < 100` — a range
    # check on a constant — demonstrated neither half of it. What makes a margin this small
    # sufficient is that `memory session-context` prints the bundle and one newline: a part
    # packed right up to `_cap` still lands inside `hook_output_chars`, with the rest of the
    # margin as headroom. Through `--json` it does not, and that is the point of the name —
    # `cli._emit` wraps the same string in `json.dumps({"summary": ...}, indent=2)`, whose
    # envelope and escaping alone carry a cap-length bundle past the platform cap.
    # **So the `hooks.json` entries must not pass `--json`** — recorded here because `bundles`
    # defines the `SLOTS` those entries are counted against.
    # (`test_a_note_sized_to_the_margins_edge_is_flagged_oversized` pins the subtraction
    # itself; this pins what the remainder of the margin is for.)
    store, config = a_store(tmp_path)
    for path in store.groups["developer"].glob("*.md"):
        path.unlink()
    heading = "### solo\n\n"
    cap = config.native_caps.hook_output_chars - CAP_MARGIN
    filler = cap - len(STANDING_LEAD) - len("\n\n") - len(heading)
    (store.groups["developer"] / "solo.md").write_text(
        note("solo", startup="1", body="x" * filler), encoding="utf-8"
    )
    review(store)
    text = render(Bundle.STANDING_RULES, store, config, part=1)
    assert text is not None and len(text) == cap
    # Raw: the bundle plus one newline, and the margin is what is left over.
    assert len(text) + 1 <= config.native_caps.hook_output_chars
    assert len(text) + 1 < config.native_caps.hook_output_chars  # headroom, not a dead heat
    # Through the JSON envelope the same text no longer fits, margin and all.
    envelope = json.dumps({"summary": text}, indent=2, sort_keys=True)
    assert len(envelope) > config.native_caps.hook_output_chars


# --- an overlay store built the way overlay mode really builds one ----------------------------
#
# `a_store` above hand-builds a `Store`. In overlay mode the store is the composed store under the
# machine's data directory, a directory of links whose groups resolve out into the overlay, and a
# note promoted there is the owner's: one record, under the note's resolved path in the overlay.
# This fixture goes through `resolve()` so the shape is the real one.

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

OVERLAY_CONFIG = """
[drybag]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"

[memory]
mode = "overlay"
groups = ["developer"]
index_extra = []
"""


def a_resolved_overlay_store(tmp_path: Path) -> tuple[Store, Config, Path, Path]:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", "git@example.com:acme/widget.git")
    overlay = tmp_path / "overlay"
    (overlay / "common" / "memory").mkdir(parents=True)
    (overlay / "common" / "memory" / "keep.md").write_text(
        note("keep", startup="1"), encoding="utf-8"
    )
    (overlay / "projects" / "widget").mkdir(parents=True)
    (overlay / "projects" / "widget" / "project.toml").write_text(
        'remote = "git@example.com:acme/widget.git"\n', encoding="utf-8"
    )
    binding.record(root, "widget", "git@example.com:acme/widget.git")
    id = binding.read_id(root)
    assert id is not None
    memory = composed_directory(id)
    memory.mkdir(parents=True)
    (memory / "developer").symlink_to(overlay / "common" / "memory", target_is_directory=True)
    (root / CONFIG_FILE).write_text(OVERLAY_CONFIG, encoding="utf-8")
    machine = tmp_path / "overlay-machine.toml"
    machine.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    config = load(root, machine=machine)
    store = resolve(root, config, machine=machine)
    assert store is not None
    assert store.path == memory  # the composed store, outside the repository
    review(store)
    return store, config, machine, overlay


@needs_git
def test_the_overlay_groups_themselves_are_neither_gated_nor_wrapped(tmp_path: Path) -> None:
    # The machine owner's overlay notes are not repository content, and wrapping them as data
    # would defeat every standing rule in the mode this project actually ships.
    store, config, _machine, _ = a_resolved_overlay_store(tmp_path)
    produced = blocks(Bundle.STANDING_RULES, store, config)
    assert produced != []
    assert not any(DELIMITER in block for block in produced)


LOCAL_CONFIG = """
[drybag]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
{memory}
"""


def test_with_no_mode_chosen_session_context_prints_no_bundle(tmp_path: Path) -> None:
    # The same local-only store twice: chosen explicitly it is delivered as today, and with no
    # layer choosing a mode memory is the harness's own, so not one bundle is printed.
    root = tmp_path / "project"
    (root / ".drybag" / "local" / "memory" / "project-volatile").mkdir(parents=True)
    (root / ".drybag" / "local" / "memory" / "project-volatile" / "now.md").write_text(
        note("now", as_of=date.today().isoformat(), body="Volatile body."), encoding="utf-8"
    )
    machine = a_machine(tmp_path)
    chosen = '[memory]\nmode = "local-only"\ngroups = ["project-volatile"]\n'
    (root / CONFIG_FILE).write_text(LOCAL_CONFIG.format(memory=chosen), encoding="utf-8")
    argv = ("memory", "session-context", "--bundle", "volatile-notes")
    code, out, _ = cli(root, tmp_path, *argv, machine=machine)
    assert (code, "Volatile body." in out) == (0, True)
    unchosen = '[memory]\ngroups = ["project-volatile"]\n'
    (root / CONFIG_FILE).write_text(LOCAL_CONFIG.format(memory=unchosen), encoding="utf-8")
    assert cli(root, tmp_path, *argv, machine=machine) == (0, "\n", "")


@needs_git
@pytest.mark.parametrize("with_file", [True, False])
def test_the_standing_rules_bundle_carries_a_reviewed_note_with_no_file(
    tmp_path: Path, with_file: bool
) -> None:
    # A checkout this machine binds, whose overlay's project layer chooses the overlay as the
    # memory: with no `drybag.toml` the bundle printed nothing, though the same checkout with
    # a file naming the same project printed the note. Both read the one store.
    _store, _config, machine, overlay = a_resolved_overlay_store(tmp_path)
    root = tmp_path / "project"
    (overlay / "projects" / "widget" / "drybag.toml").write_text(
        '[memory]\nmode = "overlay"\n', encoding="utf-8"
    )
    if not with_file:
        (root / CONFIG_FILE).unlink()
    argv = ("memory", "session-context", "--bundle", "standing-rules", "--part", "1")
    code, out, err = cli(root, tmp_path, *argv, machine=machine)
    assert (code, err) == (0, "")
    assert "keep" in out
