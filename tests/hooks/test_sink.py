from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# The layout the sink writes is `hooks.api`'s, because `doctor` reads the same tree and the two
# must name it with one set of strings; the sink's own bookkeeping stays in `hooks.sink`.
from drybag.hooks.api import DIAGNOSTICS, DIAGNOSTICS_MAX_BYTES, MARKERS, NullSink
from drybag.hooks.sink import (
    DIAGNOSTIC_FIELD_CHARS,
    ROTATED,
    UNKEYED_SESSION,
    _segment,
    sink_for,
)

HEX32 = re.compile(r"\A[0-9a-f]{32}\Z")


def test_no_plugin_data_means_a_sink_that_forgets() -> None:
    # The ordinary state outside a harness: `drybag hook` run by hand, or by a test. It must
    # degrade, not raise — a sink failure would take the whole dispatch with it.
    assert isinstance(sink_for("s1", {}), NullSink)


def test_a_marker_is_remembered_across_processes(tmp_path: Path) -> None:
    # The whole point: `NullSink.seen()` is always False, so `once_key` means "every
    # invocation" until this exists, and a once-per-context notice fires on every tool call.
    first = sink_for("s1", {"CLAUDE_PLUGIN_DATA": str(tmp_path)})
    assert first.seen("ledger-notes") is False
    first.mark("ledger-notes")
    second = sink_for("s1", {"CLAUDE_PLUGIN_DATA": str(tmp_path)})
    assert second.seen("ledger-notes") is True


def test_a_relative_data_root_is_no_sink_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `CLAUDE_PLUGIN_DATA` arrives through a committed `env` block, and `Path(".")` anchors the
    # contained walk on the process cwd — for a hook, the checkout. Measured: `CLAUDE_PLUGIN_DATA=.`
    # landed `drybag/.probe` and `drybag/diagnostics.jsonl` inside the repository. Traversal
    # and symlinks were still refused; *where the walk was anchored* was the repository's to
    # choose, and this is the half taken back. The cwd is `tmp_path` here so the assertion can
    # say what was not written and where.
    #
    # Mutation (`mutations/`'s "the sink accepts a relative data root"): the `is_absolute`
    # guard removed → a `DataSink` comes back and `drybag/` appears under the cwd.
    monkeypatch.chdir(tmp_path)
    for spelling in (".", "drybag-data", "./sub"):
        assert isinstance(sink_for("s1", {"CLAUDE_PLUGIN_DATA": spelling}), NullSink)
        assert isinstance(sink_for("s1", {"PLUGIN_DATA": spelling}), NullSink)
    assert not any(tmp_path.iterdir())


def test_codex_names_the_data_directory_differently_and_still_gets_a_durable_sink(
    tmp_path: Path,
) -> None:
    # `PLUGIN_DATA` is Codex's name for `CLAUDE_PLUGIN_DATA` (measured), and it was the arm nothing
    # asserted: every other row here passes the Claude Code name, so deleting the fallback
    # reddened nothing. Coverage could not see it either — the row above evaluates both operands
    # with `{}`, so the line and both its branch arms were already exercised. The consequence is
    # silent and is exactly the defect this module exists to fix: on Codex every `once_key`
    # handler would degrade back to "every invocation".
    first = sink_for("s1", {"PLUGIN_DATA": str(tmp_path)})
    assert not isinstance(first, NullSink)
    first.mark("ledger-notes")
    assert sink_for("s1", {"PLUGIN_DATA": str(tmp_path)}).seen("ledger-notes") is True


def test_a_marker_is_a_regular_file_and_not_merely_a_name_that_exists(tmp_path: Path) -> None:
    # `seen()` was `Path.exists()`, which follows a symlink and counts a directory — so anything
    # able to write the data root could silence a `once_key` handler with one `mkdir`: no
    # content, no permissions, no race. A marker is the regular file `mark()` writes.
    sink = sink_for("s1", {"CLAUDE_PLUGIN_DATA": str(tmp_path)})
    planted = tmp_path / "drybag" / MARKERS / _segment("s1") / _segment("ledger-notes")
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.mkdir()
    assert sink.seen("ledger-notes") is False
    # Non-vacuous: the real thing still reads as seen, so this is a narrowing and not a break.
    planted.rmdir()
    sink.mark("ledger-notes")
    assert sink.seen("ledger-notes") is True


def test_a_payload_with_no_session_id_gets_a_segment_nothing_can_precompute(
    tmp_path: Path,
) -> None:
    # `UNKEYED_SESSION` was `""`, so the session segment was `sha256("")` — a hex pair anything
    # can work out in advance. With a data root the environment names, that made the unkeyed
    # segment the one direction a read out of this tree could be used in: plant a file at the known
    # pair and a `once_key` handler is silenced before it ever runs.
    #
    # Per process now, so `once_key` degrades to "every invocation" for a payload with no
    # session id — `NullSink`'s own documented degradation, on the abnormal path, losing a
    # notice rather than a guard.
    data = {"CLAUDE_PLUGIN_DATA": str(tmp_path)}
    predictable = tmp_path / "drybag" / MARKERS / _segment("") / _segment("test-hygiene")
    predictable.parent.mkdir(parents=True, exist_ok=True)
    predictable.write_text("", encoding="utf-8")
    assert sink_for(None, data).seen("test-hygiene") is False
    # Non-vacuous: the unkeyed sink is a real one that still remembers within its own process,
    # which is the invocation `once_key` is about.
    unkeyed = sink_for(None, data)
    unkeyed.mark("test-hygiene")
    assert unkeyed.seen("test-hygiene") is True
    assert UNKEYED_SESSION != ""


def test_a_different_session_does_not_inherit_markers(tmp_path: Path) -> None:
    sink_for("s1", {"CLAUDE_PLUGIN_DATA": str(tmp_path)}).mark("ledger-notes")
    assert sink_for("s2", {"CLAUDE_PLUGIN_DATA": str(tmp_path)}).seen("ledger-notes") is False


def test_a_marker_lands_at_two_hashed_segments_and_nowhere_else(tmp_path: Path) -> None:
    # The POSITIVE shape, asserted rather than "nothing escaped". An earlier draft asserted
    # only that every written path stayed under tmp_path, which holds with the hash deleted:
    # `../../escape` from `<data>/drybag/markers/<session>/` lands back inside `<data>`, just
    # not under `markers/`. All three of its assertions passed with the guard broken.
    data = {"CLAUDE_PLUGIN_DATA": str(tmp_path)}
    sink_for("../../session", data).mark("../../escape")
    markers = tmp_path / "drybag" / MARKERS
    written = [p for p in markers.rglob("*") if p.is_file()]
    assert len(written) == 1
    marker = written[0]
    assert marker.parent.parent == markers
    assert HEX32.match(marker.parent.name) and HEX32.match(marker.name)


def test_a_hostile_segment_never_reaches_the_filesystem_walk(tmp_path: Path) -> None:
    # The backstop under the hash, asserted separately so that removing either control is
    # visible. `fsops._checked` refuses `..`, an absolute path and an empty component by
    # construction, so a future edit that stops hashing cannot silently start traversing.
    data = {"CLAUDE_PLUGIN_DATA": str(tmp_path)}
    sink_for("s1", data).mark("../../escape")
    assert not (tmp_path.parent / "escape").exists()
    assert not (tmp_path / "drybag" / "escape").exists()


def test_a_diagnostic_never_carries_a_payload_verbatim(tmp_path: Path) -> None:
    # The never-raw-stdin rule. A handler's exception message can quote a repository's bytes, so
    # every FIELD is capped before serialisation — capping the serialised line instead cuts
    # inside whichever field sorts first, and `json.loads` then raises on the record `doctor`
    # is supposed to read.
    sink = sink_for("s1", {"CLAUDE_PLUGIN_DATA": str(tmp_path)})
    sink.diagnostic({"event": "PreToolUse", "handler": "bg-cleanup", "error": "X" * 50_000})
    line = (tmp_path / "drybag" / DIAGNOSTICS).read_text(encoding="utf-8").splitlines()[0]
    record = json.loads(line)
    assert record["handler"] == "bg-cleanup"
    assert len(record["error"]) < 50_000


def test_the_session_a_record_is_filed_under_is_capped_like_any_other_field(
    tmp_path: Path,
) -> None:
    # The session id is off the hook's stdin, type-checked by `read_event` as `str` and no
    # more, so it is payload-controlled exactly as a handler's reason string is. Merged into the
    # record after the cap — which is where it started — it was the one field a repository could
    # write to this log at any length it liked.
    sink = sink_for("S" * 50_000, {"CLAUDE_PLUGIN_DATA": str(tmp_path)})
    sink.diagnostic({"event": "PreToolUse", "handler": "bg-cleanup", "error": "boom"})
    line = (tmp_path / "drybag" / DIAGNOSTICS).read_text(encoding="utf-8").splitlines()[0]
    assert len(json.loads(line)["session"]) == DIAGNOSTIC_FIELD_CHARS


def test_the_log_is_rotated_rather_than_grown(tmp_path: Path) -> None:
    sink = sink_for("s1", {"CLAUDE_PLUGIN_DATA": str(tmp_path)})
    for _ in range(4_000):
        sink.diagnostic({"event": "PreToolUse", "handler": "bg-cleanup", "error": "Y" * 200})
    live = tmp_path / "drybag" / DIAGNOSTICS
    assert live.stat().st_size <= DIAGNOSTICS_MAX_BYTES
    assert (tmp_path / "drybag" / ROTATED).exists()


def test_old_sessions_are_pruned_and_the_newest_survives(tmp_path: Path) -> None:
    # Sessions are unbounded in number and a marker is worthless once its session ends, so
    # without a prune the directory grows for the life of the machine. The assertion is that
    # the prune keeps the RIGHT ones: a prune that dropped the newest would still bound growth.
    data = {"CLAUDE_PLUGIN_DATA": str(tmp_path)}
    for index in range(60):
        sink_for(f"s{index}", data).mark("k")
    kept = list((tmp_path / "drybag" / MARKERS).iterdir())
    assert len(kept) <= 50
    assert sink_for("s59", data).seen("k") is True


def test_an_unwritable_data_directory_degrades_instead_of_raising(tmp_path: Path) -> None:
    # A hook runs on every tool call; a read-only ${CLAUDE_PLUGIN_DATA} must cost a lost
    # marker, never a refused Bash command.
    blocked = tmp_path / "ro"
    blocked.mkdir(mode=0o500)
    assert isinstance(sink_for("s1", {"CLAUDE_PLUGIN_DATA": str(blocked)}), NullSink)
