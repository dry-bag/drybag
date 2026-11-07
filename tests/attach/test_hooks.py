"""What a session hears about the overlay it is bound to, and what it never hears.

Every case asserts the whole of `HookResult.context` against the module's own fixed lines, so
a repository-authored byte reaching the model would have to arrive as a line this file spells.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import stayfixed
from stayfixed.attach.hooks import (
    NO_OVERLAY,
    NO_UPSTREAM,
    NOT_ASKABLE,
    NOT_ATTACHED,
    REQUIRES,
    REQUIRES_UNREADABLE,
    UNPUSHED,
    register,
)
from stayfixed.config.loader import CONFIG_FILE, load
from stayfixed.config.session import session_config
from stayfixed.hooks.api import EVENTS, Handler, HookEvent, HookResult
from stayfixed.hooks.registry import discover
from tests.boundaries.test_discovery import LIST_IMPORTS, ROOT
from tests.gitfixture import git, needs_git
from tests.overlay.test_requires import overlay_with
from tests.sessions import NO_CONFIG, session_of

ORIGIN = "git@github.com:owner/widget.git"
CONFIG = (
    '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
    '[memory]\nmode = "{mode}"\ngroups = ["developer", "project-stable"]\n'
)


def _event(root: Path, source: str | None = None) -> HookEvent:
    """A `SessionStart` event, optionally carrying the `source` the matcher keys on.

    `raw` is where the harness's `source` arrives and where `hooks.dispatch` hands the handler its
    own deep copy of the payload, so a case that wants to be a resume says so there and nowhere
    else. `None` is the payload that carries no `source` at all, which is the shape every case
    written before the sync was gated already used.
    """
    raw: dict[str, object] = {"hook_event_name": "SessionStart"}
    if source is not None:
        raw["source"] = source
    return HookEvent("SessionStart", "s1", None, None, {}, root, root, raw)


def _machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The hook path reads `<home>/.config/stayfixed/config.toml` and nothing else; HOME is
    pinned so nothing of the developer's is read. `tests/doctor/test_command.py` pins it the same
    way, for the same reason and with the same one call."""
    home = tmp_path / "home"
    (home / ".config" / "stayfixed").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home / ".config" / "stayfixed" / "config.toml"


def _project(tmp_path: Path, *, mode: str = "overlay") -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    (root / CONFIG_FILE).write_text(CONFIG.format(mode=mode), encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", ORIGIN)
    return root


def _bind(overlay: Path, remote: str = ORIGIN) -> None:
    """What `attach` records for the checkout beside `overlay`: the overlay's project record and
    this machine's binding, both with `remote`."""
    from stayfixed import binding

    record = overlay / "projects" / "widget" / "project.toml"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(f'remote = "{remote}"\n', encoding="utf-8")
    binding.record(overlay.parent / "project", "widget", remote)


def _moved(origin: str | None, recorded: str | None) -> str:
    """The line a bound checkout whose `origin` is not the recorded one hears."""
    from stayfixed.memory.api import origin_note

    said = origin_note(recorded, origin)
    assert said is not None
    return f"stayfixed: {said}"


def _status() -> Handler:
    """`overlay-status`, the one handler of this area's three that this file is about; the
    overlay's rules have theirs in `tests/attach/test_rules.py`."""
    (handler,) = (h for h in register() if h.name == "overlay-status")
    return handler


def _run(
    root: Path, machine: Path, machine_text: str | None, *, source: str | None = None
) -> str | None:
    if machine_text is not None:
        machine.write_text(machine_text, encoding="utf-8")
    config = load(root, machine=root / "absent.toml")
    handler = _status()
    return handler.run(_event(root, source), session_of(config)).context


def _recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, requires: str = ">=0.0.1"
) -> tuple[Path, Path, Path]:
    machine = _machine_home(tmp_path, monkeypatch)
    overlay = overlay_with(tmp_path / "overlay", requires)
    machine.write_text(f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8")
    return _project(tmp_path), overlay, machine


def test_the_handler_is_discovered_once_per_session_and_only_on_session_start() -> None:
    handler = _status()
    assert handler.event == "SessionStart" and handler.event in EVENTS
    assert handler.once_key == "overlay-status"
    assert "overlay-status" in {h.name for h in discover()}


@needs_git
def test_an_unattached_overlay_project_is_told_to_attach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mutation (comment): `== UNBOUND` -> `!= UNBOUND` — one substring, no import; this
    # reddens and the silent case below prints NOT_ATTACHED.
    root, _, machine = _recorded(tmp_path, monkeypatch)
    assert _run(root, machine, None) == NOT_ATTACHED


@needs_git
def test_a_bound_checkout_whose_origin_moved_hears_one_line_naming_both_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The remote no longer decides the binding, so a moved `origin` is a hint and never the
    # mismatch it was; both URLs are named through `printed`, which escapes what a terminal or a
    # runner would act on.
    from stayfixed import binding
    from stayfixed.printed import quoted

    root, overlay, machine = _recorded(tmp_path, monkeypatch)
    _bind(overlay)
    binding.record(root, "widget", ORIGIN)
    assert _run(root, machine, None) is None
    moved = "https://example.com/someone/fork"
    git(root, "remote", "set-url", "origin", moved)
    assert _run(root, machine, None) == (
        f"stayfixed: this checkout's `origin` is {quoted(moved)}, and its binding was recorded "
        f"with {quoted(ORIGIN)}; `stayfixed attach` records the new one"
    )


def test_the_session_start_line_names_the_attach_command_every_remedy_names() -> None:
    # One spelling of `stayfixed attach` serves the session-start line and every row of
    # `attached`, so the line is pinned as bytes here: built from the shared
    # constant, a change to it would otherwise reach the session unread. It names no `--store`:
    # the store is derived, and the placeholder spelling an agent ran as written exited 2. No
    # mutation: a changed spelling on either side reddens one of the two lines.
    from stayfixed.attach import ATTACH_COMMAND

    assert ATTACH_COMMAND == "stayfixed attach"
    assert NOT_ATTACHED == (
        "stayfixed: this repository is not attached to the overlay this machine records; "
        "run `stayfixed attach --check`"
    )


def test_hook_discovery_in_a_clean_interpreter_loads_no_doctor_module() -> None:
    # `hooks/registry.py` imports every area's `hooks` module with no guard, because a hook fails
    # fast. So whatever `hooks.py` imports at module level is on every hook's path: a defect
    # confined to `attach/doctor.py` would stop discovery for every event, and every hook run would
    # load the report's code. Asked in a clean interpreter, because in this one the suite has
    # already imported everything. Mutation (oracle): `mutations/`'s "attach's hooks import the
    # area's doctor module".
    completed = subprocess.run(
        [sys.executable, "-c", LIST_IMPORTS],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")},
    )
    assert completed.returncode == 0, completed.stderr
    loaded = completed.stdout.split()
    assert "stayfixed.attach.hooks" in loaded, "the probe discovered nothing"
    assert [name for name in loaded if name.split(".")[-1] == "doctor"] == []


@needs_git
def test_a_moved_origin_and_a_missing_overlay_each_get_their_own_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, overlay, machine = _recorded(tmp_path, monkeypatch)
    _bind(overlay, "git@github.com:someone/else.git")
    assert _run(root, machine, None) == _moved(ORIGIN, "git@github.com:someone/else.git")
    assert _run(root, machine, "") == NO_OVERLAY


@needs_git
def test_a_bound_checkout_whose_origin_was_removed_hears_the_moved_line_and_stays_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A removed `origin` read as its own refusing state on every surface. The binding is the id
    # now, so the session hears the one moved-`origin` line and never that it is not attached.
    root, overlay, machine = _recorded(tmp_path, monkeypatch)
    _bind(overlay)
    git(root, "remote", "remove", "origin")
    assert _run(root, machine, None) == _moved(None, ORIGIN)


@needs_git
def test_a_bound_pushed_and_satisfied_project_hears_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, overlay, machine = _recorded(tmp_path, monkeypatch)
    _bind(overlay)
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(overlay, "init", "-q", "-b", "main")
    git(overlay, "add", "-A")
    git(overlay, "commit", "-qm", "chore: overlay")
    git(overlay, "remote", "add", "origin", str(bare))
    git(overlay, "push", "-q", "-u", "origin", "main")
    assert _run(root, machine, None) is None


@needs_git
def test_unpushed_work_is_named_by_its_counts_and_only_when_nothing_else_is_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A branch with no upstream is one line, and it is not the line that says zero.

    `Sync.ahead` is `None` when `git rev-list @{upstream}..HEAD` could not be answered, which on a
    branch with no upstream means every commit on it is unpushed -- the count is unknown, not
    zero. The two lines used to be appended by two independent `if`s with `ahead=sync.ahead or 0`
    under the second, so this exact state produced "nothing backs it up" immediately followed by
    "0 unpushed commit(s)": the sentence carrying the number said the opposite of the one above
    it. They are mutually exclusive now, and `NO_UPSTREAM` carries the dirty count, which is the
    half that is knowable here.

    Mutation: `mutations/`'s "a session with no upstream is told it has 0 unpushed commits".
    """
    root, overlay, machine = _recorded(tmp_path, monkeypatch)
    git(overlay, "init", "-q", "-b", "main")
    git(overlay, "add", "-A")
    git(overlay, "commit", "-qm", "chore: overlay")
    _bind(overlay)  # written after the commit, so the binding record is untracked: dirty 1
    context = _run(root, machine, None)
    assert context == NO_UPSTREAM.format(dirty=1)
    # The half the old condition got wrong, said as the assertion it is: no count of unpushed
    # commits is reported for a branch whose unpushed count is unknown.
    assert "unpushed commit(s)" not in (context or "")
    _bind(overlay, "git@github.com:someone/else.git")
    # The sync half is skipped.
    assert _run(root, machine, None) == _moved(ORIGIN, "git@github.com:someone/else.git")


@needs_git
def test_a_bound_checkout_with_no_file_hears_the_overlay_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The overlay's layers set the mode, so the notes are the overlay's and the session hears about
    # their backup as it does in a checkout with a file.
    root, overlay, _ = _recorded(tmp_path, monkeypatch)
    (root / CONFIG_FILE).unlink()
    layer = overlay / "projects" / "widget" / "stayfixed.toml"
    layer.parent.mkdir(parents=True)
    layer.write_text('[memory]\nmode = "overlay"\n', encoding="utf-8")
    git(overlay, "init", "-q", "-b", "main")
    git(overlay, "add", "-A")
    git(overlay, "commit", "-qm", "chore: overlay")
    _bind(overlay)
    assert _status().run(_event(root), session_config(root)).context == NO_UPSTREAM.format(dirty=1)


@needs_git
def test_an_upstream_that_is_behind_still_reports_both_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other side of the `elif`: with an upstream, `ahead` is a real number and `UNPUSHED` is
    # the line -- so making the two exclusive did not cost the case that reports both counts.
    root, overlay, machine = _recorded(tmp_path, monkeypatch)
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(overlay, "init", "-q", "-b", "main")
    git(overlay, "add", "-A")
    git(overlay, "commit", "-qm", "chore: overlay")
    git(overlay, "remote", "add", "origin", str(bare))
    git(overlay, "push", "-q", "-u", "origin", "main")
    _bind(overlay)  # untracked after the push: dirty 1, ahead 0
    (overlay / "later.md").write_text("more\n", encoding="utf-8")
    git(overlay, "add", "later.md")
    git(overlay, "commit", "-qm", "chore: later")  # ahead 1
    assert _run(root, machine, None) == UNPUSHED.format(ahead=1, dirty=1)


@needs_git
def test_an_overlay_that_requires_a_newer_stayfixed_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, overlay, machine = _recorded(tmp_path, monkeypatch, requires=">=99.0.0")
    _bind(overlay)
    assert _run(root, machine, None) == REQUIRES.format(
        spec=">=99.0.0", running=stayfixed.__version__
    )


@needs_git
def test_a_requirement_this_stayfixed_cannot_read_is_its_own_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unreadable is not unsatisfied: a spec `satisfies` answers `None` for is a declaration this
    # stayfixed has no verdict on, so it is named as unreadable and — this is the half that
    # matters — the declaration itself is never quoted into the context.
    # Mutation (comment): `if verdict is None` -> `if verdict is not None` -> this reddens.
    root, overlay, machine = _recorded(tmp_path, monkeypatch, requires="~=1.0")
    _bind(overlay)
    context = _run(root, machine, None)
    assert context == REQUIRES_UNREADABLE
    assert "~=1.0" not in (context or "")


@needs_git
def test_other_modes_no_config_and_a_broken_machine_file_are_silence_or_one_fixed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = _machine_home(tmp_path, monkeypatch)
    handler = _status()
    assert handler.run(_event(tmp_path), NO_CONFIG).context is None
    assert _run(_project(tmp_path, mode="local-only"), machine, None) is None
    root = _project(tmp_path / "two")
    # No machine file at all is "no overlay recorded", which is the ordinary state before
    # `stayfixed setup` has run and is not the same event as a file that will not parse.
    assert (
        handler.run(_event(root), session_of(load(root, machine=root / "absent.toml"))).context
        == NO_OVERLAY
    )
    machine.write_text("[overlay\n", encoding="utf-8")
    result = handler.run(_event(root), session_of(load(root, machine=root / "absent.toml")))
    assert result.context == NOT_ASKABLE


@needs_git
def test_an_unreadable_floor_costs_its_own_line_and_never_the_whole_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler's backstop is a floor, not a filter: a line it swallows takes every other
    line of the same result with it.

    `satisfies` used to raise `ValueError` for a floor whose components are past CPython's
    4300-digit `int()` cap — a string an owner can mistype into the overlay's own manifest, and
    one no repository can write. `except Exception` then returned an empty `HookResult`, so the
    session was told nothing at all: not the unreadable requirement, and not `NOT_ATTACHED`,
    which is the one line that says this project is not bound to the overlay it is reading.

    The assertion is the two lines, in order, and never the exception.
    """
    root, _, machine = _recorded(tmp_path, monkeypatch, requires=">=" + "9" * 5000 + ".0.0")
    assert _run(root, machine, None) == NOT_ATTACHED + "\n" + REQUIRES_UNREADABLE


@needs_git
def test_the_budget_this_module_documents_is_the_one_it_pays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `git` calls fall on the healthy path, and both documents used to say the reverse.

    This module's docstring and `docs/cli.md` both said the sync calls were "skipped whenever an
    earlier line already asks for an action". The skip is real and it is the other way round:
    `overlay_sync` sits under `if not lines:`, so it is reached exactly when nothing above it
    found anything wrong. The repository that pays `origin_remote` (five seconds) plus `git
    status` and `git rev-list` (two each) -- nine against the entry's ten -- is the bound,
    pushed, satisfied one that then hears nothing.

    A false statement about a budget is worse than the budget, so the measurement is the test and
    the two documents are held to it. The handler still *runs* on every event the matcher covers —
    that is `hooks/dispatch.py`'s `once_key` semantics and every area's handlers share them — but
    the two `git` calls it used to re-pay are gated on the event's own `source` now, which
    `test_a_context_that_has_already_been_asked_does_not_re_pay_the_sync` holds. This case carries
    no `source` at all, which is the invocation that pays.
    """
    from stayfixed.attach import hooks as attach_hooks
    from stayfixed.overlay import api as overlay_api

    asked: list[Path] = []
    real = overlay_api.overlay_sync

    def counted(overlay: Path, **kwargs: object) -> object:
        asked.append(overlay)
        return real(overlay, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(overlay_api, "overlay_sync", counted)

    root, overlay, machine = _recorded(tmp_path, monkeypatch)
    # A finding above the sync: the two extra `git` calls are the ones NOT paid here.
    assert _run(root, machine, None) == NOT_ATTACHED
    assert asked == []

    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(overlay, "init", "-q", "-b", "main")
    _bind(overlay)
    git(overlay, "add", "-A")
    git(overlay, "commit", "-qm", "chore: overlay")
    git(overlay, "remote", "add", "origin", str(bare))
    git(overlay, "push", "-q", "-u", "origin", "main")
    # Nothing to say, and the sync is exactly what it paid to find that out.
    assert _run(root, machine, None) is None
    assert asked == [overlay]

    claim = "skipped whenever an earlier line already asks for an action"
    assert attach_hooks.__doc__ is not None and claim not in attach_hooks.__doc__
    reference = Path(__file__).resolve().parents[2] / "docs" / "cli.md"
    assert claim not in reference.read_text(encoding="utf-8")


@needs_git
def test_a_context_that_has_already_been_asked_does_not_re_pay_the_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate the budget above buys, and the cost it accepts.

    A healthy repository delivers nothing, so `dispatch` banks no `once_key` marker and this
    handler is asked again on every `startup`, `resume`, `clear`, `compact` and `fork` the matcher
    covers. Re-asking is cheap for the lines that are already known and costs two more `git` calls
    at two seconds each for the last two — four of the nine seconds in an entry whose `timeout` is
    ten.

    So the sync is gated on the event's own `source`, here and not in `dispatch.py`, whose
    `once_key` semantics belong to every area's handlers. `compact` is one context asking again;
    `startup`, `resume`, `fork`, `clear` and a payload with no `source` are new ones and pay.
    `resume` used to be gated too, and it is the launch — often days later — at which an overlay
    the conversation wrote to is most likely to be dirty or unpushed.
    The `git` calls are counted rather than timed: a wall-clock assertion in a suite that runs
    beside other work measures the machine, not the gate.

    Mutation: `mutations/`'s "a compacted session re-pays the overlay sync".
    """
    from stayfixed.overlay import api as overlay_api

    asked: list[Path] = []
    real = overlay_api.overlay_sync

    def counted(overlay: Path, **kwargs: object) -> object:
        asked.append(overlay)
        return real(overlay, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(overlay_api, "overlay_sync", counted)
    root, overlay, machine = _recorded(tmp_path, monkeypatch)
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(overlay, "init", "-q", "-b", "main")
    _bind(overlay)
    git(overlay, "add", "-A")
    git(overlay, "commit", "-qm", "chore: overlay")
    git(overlay, "remote", "add", "origin", str(bare))
    git(overlay, "push", "-q", "-u", "origin", "main")
    # A context that has already been asked: silence, and nothing paid for it.
    assert _run(root, machine, None, source="compact") is None
    assert asked == []
    # A context that has not: the same silence, and the two calls are what found that out.
    fresh: tuple[str | None, ...] = ("startup", "resume", "fork", "clear", None)
    for source in fresh:
        assert _run(root, machine, None, source=source) is None, source
    assert asked == [overlay] * len(fresh)
    # The cost, asserted rather than only documented: work that arrives mid-session is not
    # reported to that session's own compaction. `stayfixed doctor` is what answers on demand.
    (overlay / "later.md").write_text("more\n", encoding="utf-8")
    assert _run(root, machine, None, source="compact") is None
    # And the case the gate used to swallow: the conversation resumed later hears it. The overlay
    # has an upstream here and is level with it, so the knowable half is the dirty count.
    assert _run(root, machine, None, source="resume") == UNPUSHED.format(ahead=0, dirty=1)


@needs_git
def test_a_failure_with_no_except_of_its_own_is_silence_not_an_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The blanket backstop, which every other case in this module leaves standing.

    `except Exception` is what keeps an open handler from costing a session, and every case
    above reaches a path with an explicit `except` of its own — `Failure` and `Refusal` — so the
    blanket one could be deleted with this module green: the call the handler makes has to be
    forced to fail outright.

    `requires_of` is that call here. Nothing is caught around it, and the handler imports it from
    `stayfixed.overlay.api` inside its own body, so the module attribute is the seam a monkeypatch
    reaches. The assertion is silence, and this is deliberately the case where
    the backstop *loses* a line: `NOT_ATTACHED` is already in `lines` and goes with the result,
    which is the cost an open handler accepts and the reason this is a floor and not a filter — the
    same repository is told `NOT_ATTACHED` by `test_an_unattached_overlay_project_is_told_to_attach`
    when nothing raises.

    Mutation: `mutations/`'s "an open session handler lets an unforeseen failure out".
    """
    from stayfixed.overlay import api as overlay_api

    def raising(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("something no except of its own covers")

    root, _, _ = _recorded(tmp_path, monkeypatch)
    monkeypatch.setattr(overlay_api, "requires_of", raising)
    handler = _status()
    result = handler.run(_event(root), session_of(load(root, machine=root / "absent.toml")))
    assert result.context is None


def test_the_registration_is_what_the_dispatcher_acts_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`event` through the dispatcher, rather than read back off the same literal.

    `test_the_handler_is_discovered_once_per_session_and_only_on_session_start` compares
    `Handler.event` with the constant `register()` passes, which holds whatever that constant is —
    so what it buys is asserted here instead, against the real `dispatch`.

    A failure of this handler is recorded and named on stderr and the run is not a refusal.
    `_overlay_status` is patched to raise, because with the module's own backstop in place the
    handler cannot fail from inside; that backstop has its own case above, and this one is about
    what happens when something gets past it.

    **`event`**: no other event in `EVENTS` reaches the handler at all. Asserted rather than given
    an oracle entry, because `event` is a name the dispatcher matches and not a guard —
    `registry.discover` already refuses a value outside `EVENTS`, and a valid-but-wrong one is
    what this assertion is for.
    """
    from stayfixed.attach import hooks as attach_hooks
    from stayfixed.harnesses import CLAUDE
    from stayfixed.hooks.dispatch import Recorder, dispatch

    seen: list[str] = []

    def failing(event: HookEvent, config: object) -> HookResult:
        seen.append(event.name)
        raise RuntimeError("past every except in the module")

    monkeypatch.setattr(attach_hooks, "_overlay_status", failing)
    handlers = register()
    sink = Recorder()
    outcome = dispatch(_event(tmp_path), handlers, NO_CONFIG, harness=CLAUDE, sink=sink)
    assert seen == ["SessionStart"]
    assert outcome.exit_code == 0
    assert "overlay-status: RuntimeError" in outcome.stderr
    assert sink.records == [
        {"event": "SessionStart", "handler": "overlay-status", "error": "RuntimeError"}
    ]
    for name in (event for event in EVENTS if event != "SessionStart"):
        other = replace(_event(tmp_path), name=name)
        assert (
            dispatch(other, handlers, NO_CONFIG, harness=CLAUDE, sink=Recorder()).exit_code == 0
        ), name
    assert seen == ["SessionStart"]
