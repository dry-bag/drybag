"""The reconcile of the overlay's MCP servers at Claude Code's local scope
(`src/drybag/attach/mcp.py`'s `reconcile`).

Every case hands a recording runner and a `save` that keeps each ledger it is given, and reads
what was launched, from where, and what was saved when. No `claude` is ever launched."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from drybag.attach.mcp import UNSETTLED, Reconciled, Served, digest, fold_mcp, reconcile
from drybag.config.plates import Plate, PlateKind
from drybag.printed import quoted
from drybag.runner import Completed
from tests.runners import Recorder

MARKER = "sekret-marker-5c1"
DEFINITION: Mapping[str, object] = {"command": "srv", "args": ["--stdio"]}
ADD = "claude mcp add-json --scope local --"
# What Claude Code 2.1.319 answered for a definition it refuses, measured on a scratch home.
INVALID = Completed(1, "", "Invalid configuration: : Invalid input")


def _served(tmp_path: Path, **definitions: Mapping[str, object]) -> dict[str, Served]:
    plate = Plate(PlateKind.COMMON, "common", tmp_path)
    return {
        name: Served(definition, digest(definition), plate, plate)
        for name, definition in definitions.items()
    }


class _Saves(list[dict[str, str | None]]):
    """Each ledger `save` was handed, copied, in order."""

    def __call__(self, owned: dict[str, str | None]) -> None:
        self.append(dict(owned))


def _run(
    tmp_path: Path,
    served: Mapping[str, Served],
    owned: Mapping[str, str | None],
    runner: Recorder,
) -> tuple[Reconciled, _Saves]:
    saves = _Saves()
    return reconcile(tmp_path, served, owned, runner, saves), saves


def test_new_name_is_removed_then_added_and_digested(tmp_path: Path) -> None:
    served = _served(tmp_path, m1=DEFINITION)
    runner = Recorder()
    done, saves = _run(tmp_path, served, {}, runner)
    assert runner.calls == [
        ["claude", "mcp", "remove", "--scope", "local", "--", "m1"],
        ["claude", "mcp", "add-json", "--scope", "local", "--", "m1", json.dumps(DEFINITION)],
    ]
    assert done.owned == {"m1": digest(DEFINITION)}
    assert (done.replaced, done.failed) == ((), ())
    assert saves == [{"m1": UNSETTLED}, {"m1": digest(DEFINITION)}]


def test_unchanged_digest_calls_nothing(tmp_path: Path) -> None:
    # Every `remove` of a remote server signs it out, so a name whose definition did not change is
    # never touched (the OAuth sign-out an `attach` on every session would otherwise cost).
    served = _served(tmp_path, m1=DEFINITION)
    runner = Recorder()
    done, saves = _run(tmp_path, served, {"m1": digest(DEFINITION)}, runner)
    assert runner.calls == []
    assert done.owned == {"m1": digest(DEFINITION)}
    assert saves == []


def test_moving_an_unchanged_definition_between_plates_calls_nothing(tmp_path: Path) -> None:
    def plate(name: str, kind: PlateKind, body: dict[str, object]) -> Plate:
        (tmp_path / name / "claude").mkdir(parents=True)
        text = json.dumps({"mcpServers": {"m1": body}})
        (tmp_path / name / "claude" / "mcp.json").write_text(text, encoding="utf-8")
        return Plate(kind, name, tmp_path / name)

    before = fold_mcp([plate("t1", PlateKind.TAG, {"command": "srv", "args": ["a"]})])
    # The same definition, its keys in another order, now in the project's plate.
    after = fold_mcp([plate("p", PlateKind.PROJECT, {"args": ["a"], "command": "srv"})])
    assert after.served["m1"].defined_in != before.served["m1"].defined_in
    runner = Recorder()
    done, _ = _run(tmp_path, after.served, {"m1": before.served["m1"].digest}, runner)
    assert runner.calls == []
    assert done.owned == {"m1": before.served["m1"].digest}


def test_changed_definition_is_re_added(tmp_path: Path) -> None:
    served = _served(tmp_path, m1=DEFINITION)
    runner = Recorder()
    done, _ = _run(tmp_path, served, {"m1": digest({"command": "old"})}, runner)
    assert [argv[2] for argv in runner.calls] == ["remove", "add-json"]
    assert done.owned == {"m1": digest(DEFINITION)}
    # Its own entry, delivered with a digest, so the `remove` replaced nothing of the owner's.
    assert done.replaced == ()


def test_failed_add_stays_unsettled_with_claude_codes_message(tmp_path: Path) -> None:
    served = _served(tmp_path, m1={"command": "srv", "env": {"TOKEN": MARKER}})
    runner = Recorder(answers={ADD: INVALID})
    done, saves = _run(tmp_path, served, {}, runner)
    assert done.owned == {"m1": UNSETTLED}
    assert saves[-1] == {"m1": UNSETTLED}
    assert [name for name, _ in done.failed] == ["m1"]
    message = done.failed[0][1]
    assert "Invalid configuration" in message
    assert MARKER not in message


def test_take_back_drops_on_exit_0_or_claude_codes_answer_that_the_name_is_absent(
    tmp_path: Path,
) -> None:
    runner = Recorder(local={"kept"})
    owned = {"kept": digest(DEFINITION), "m1": UNSETTLED}
    done, saves = _run(tmp_path, {}, owned, runner)
    assert sorted(argv[-1] for argv in runner.calls) == ["kept", "m1"]
    assert done.owned == {}
    assert done.failed == ()
    assert saves == [{"kept": UNSETTLED, "m1": UNSETTLED}, {}]


def test_take_back_keeps_a_name_whose_remove_exits_1_for_another_reason(tmp_path: Path) -> None:
    # Claude Code exits 1 for a name it could not remove too (measured on 2.1.316, a read-only
    # `~/.claude.json`), and for another name's absence: only its answer that this name is absent
    # drops the record, so a wording it changes leaves a name unsettled and never loses one.
    for said in ('MCP server "m1" was not removed from the file', 'No MCP server named "m10"'):
        done, saves = _run(tmp_path, {}, {"m1": digest(DEFINITION)}, Recorder(code=1, stderr=said))
        assert done.owned == {"m1": UNSETTLED}
        assert saves[-1] == {"m1": UNSETTLED}
        assert done.failed == (("m1", quoted(said)),)


class _CannotLaunch:
    """A runner whose launch itself fails, as a spawn error does."""

    def launch(self, argv: list[str], cwd: Path) -> Completed:
        raise FileNotFoundError(2, "No such file or directory", "claude")


@pytest.mark.parametrize("runner", [Recorder(code=127), _CannotLaunch()], ids=["127", "oserror"])
def test_take_back_keeps_unsettled_when_claude_is_missing(
    tmp_path: Path, runner: Recorder | _CannotLaunch
) -> None:
    # `remove` with no `claude` on `PATH` exits 127 and leaves the entry where it is (measured):
    # only Claude Code's own answer may drop the record, or the entry is orphaned.
    saves = _Saves()
    done = reconcile(tmp_path, {}, {"m1": digest(DEFINITION)}, runner, saves)
    assert done.owned == {"m1": UNSETTLED}
    assert saves[-1] == {"m1": UNSETTLED}
    assert [name for name, _ in done.failed] == ["m1"]


def test_replacement_is_reported_for_a_name_without_a_digest(tmp_path: Path) -> None:
    # `remove` exited 0, so an entry stood under the name: made by hand, or left by an interrupted
    # run. Said for a name with no digest at the start, and never for one this ledger delivered.
    served = _served(tmp_path, fresh=DEFINITION, unsettled=DEFINITION, changed=DEFINITION)
    owned = {"unsettled": UNSETTLED, "changed": digest({"command": "old"})}
    done, _ = _run(tmp_path, served, owned, Recorder(local={"fresh", "unsettled", "changed"}))
    assert done.replaced == ("fresh", "unsettled")


class _Killed(Exception):
    """The process stopping part-way, as a kill does."""


def test_interrupted_after_the_mark_settles_next_run(tmp_path: Path) -> None:
    served = _served(tmp_path, m1=DEFINITION)

    def kill_after_the_remove(argv: list[str], cwd: Path) -> None:
        if argv[2] == "add-json":
            raise _Killed

    saves = _Saves()
    with pytest.raises(_Killed):
        reconcile(tmp_path, served, {}, Recorder(on_call=kill_after_the_remove), saves)
    assert saves == [{"m1": UNSETTLED}]
    runner = Recorder()
    done = reconcile(tmp_path, served, saves[-1], runner, saves)
    assert [argv[2] for argv in runner.calls] == ["remove", "add-json"]
    assert done.owned == {"m1": digest(DEFINITION)}


def test_mark_is_saved_before_the_first_launch(tmp_path: Path) -> None:
    served = _served(tmp_path, m1=DEFINITION)
    runner = Recorder()
    seen: list[tuple[int, dict[str, str | None]]] = []
    reconcile(
        tmp_path,
        served,
        {"m2": digest(DEFINITION)},
        runner,
        lambda owned: seen.append((len(runner.calls), dict(owned))),
    )
    assert seen[0] == (0, {"m1": UNSETTLED, "m2": UNSETTLED})


def test_every_launch_runs_in_the_main_checkout(tmp_path: Path) -> None:
    main = tmp_path / "main"
    runner = Recorder()
    saves = _Saves()
    reconcile(main, _served(tmp_path, m1=DEFINITION), {"m2": UNSETTLED}, runner, saves)
    assert len(runner.cwds) == 3
    assert set(runner.cwds) == {main}


def test_option_shaped_name_follows_a_double_dash(tmp_path: Path) -> None:
    # Without `--`, `claude mcp add-json -h …` prints its usage and exits 0 having written nothing
    # (measured), which would record a digest for an entry that is not there.
    runner = Recorder()
    _run(tmp_path, _served(tmp_path, **{"-h": DEFINITION}), {"--scope": UNSETTLED}, runner)
    assert len(runner.calls) == 3
    for argv in runner.calls:
        options = argv[: argv.index("--")]
        assert options == ["claude", "mcp", argv[2], "--scope", "local"]
        assert argv[argv.index("--") + 1] in ("-h", "--scope")
