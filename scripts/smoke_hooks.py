#!/usr/bin/env python3
"""Feed every `hooks/hooks.json` entry the event it is filed under, through the wrapper.

    python3 scripts/smoke_hooks.py --plugin-root R --fixture F --scratch S

`R` is a plugin root — the checkout, or the copy the harness installed. One row per
entry and sample; exit 1 on any row whose exit code, stderr or stdout shape is not the one
the dispatcher's contract requires.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"
# What the wrapper and the dispatcher end a fault of their own with, and exit 0 after: a row that
# carries it is drybag failing to answer, not answering.
FAULT = "; continuing open"
DELIMITER = "<<<drybag:repository-data"
# What `tests/fixtures/smoke-project`'s own store puts in front of the model: its volatile note.
# Its standing rule is the repository's, and no repository note is a standing rule, so the
# standing-rules bundle renders nothing on it.
VOLATILE_NOTE = "SMOKE-VOLATILE-NOTE"
# The one `DRYBAG_*` variable an entry keeps: the floor a test runner puts under the product's
# own bounds on `git` (`drybag.gitenv.FLOOR_VARIABLE`, which can only raise them). Spelled out
# rather than imported, because this script runs without `drybag` importable.
FLOOR_VARIABLE = "DRYBAG_GIT_FLOOR_SECONDS"
# Counted against the shipped `hooks/hooks.json` and this fixture: twelve entries, thirteen rows
# (`PreToolUse` carries two samples), unchanged by the overlay's delivery, since its rules reach a
# session through `hook SessionStart` and its path-scoped ones through the rendered plugin, neither
# an entry of `hooks/hooks.json`. Both are asserted because a run that executes fewer rows
# prints an identically green summary — the shape `unsampled` and `unentered` close for events
# and nothing closed for rows.
EXPECTED_ENTRIES = 12
EXPECTED_ROWS = 13
# What the red-run note opens with, `drybag.hints.hygiene.LEAD`, spelled out for the reason
# `FLOOR_VARIABLE` is. The note is all a `PostToolUseFailure` entry is for, so its row asks for it
# by its words and not only for an envelope naming the event, which an entry whose handler said
# nothing also prints.
RED_RUN_NOTE = "Before calling this red a flake, pre-existing, or caused by the branch:"
# The note speaks only of something in the tree that could have falsified the run, and the
# fixture's tree is clean as committed, so the rows run over one uncommitted file: the dirty-tree
# line is then the note's, as it is after a red run in the middle of a change.
UNCOMMITTED = "uncommitted-by-the-smoke.txt"


@dataclass(frozen=True)
class Sample:
    payload: dict[str, object]
    expected_code: int
    label: str
    # What the stderr must never say: a fault the wrapper or the dispatcher degraded to exit 0.
    stderr_never: tuple[str, ...] = ()
    # What the `additionalContext` a dispatched entry prints must say. Empty asks nothing of it.
    context_says: tuple[str, ...] = ()


SAMPLES: dict[str, tuple[Sample, ...]] = {
    "SessionStart": (Sample({"source": "startup"}, 0, "a session starts"),),
    "PreToolUse": (
        Sample(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "sleep 300 &", "run_in_background": True},
            },
            0,
            "a backgrounded sleep is hinted, never blocked",
            stderr_never=(FAULT,),
            context_says=("backgrounded",),
        ),
        Sample(
            {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            0,
            "an ordinary command is allowed",
            stderr_never=(FAULT,),
        ),
    ),
    "PostToolUse": (
        Sample(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "uv run pytest -q"},
                "tool_response": {"exit_code": 1},
            },
            0,
            "a failed test run is annotated, never blocked",
            stderr_never=(FAULT,),
        ),
    ),
    # The shape Claude Code delivers a Bash command that exited non-zero in, measured on Claude
    # Code 2.1.296 for `false`: no `tool_response`, and `error` the exit code alone.
    "PostToolUseFailure": (
        Sample(
            {
                # A session of its own: the note is delivered once per session whichever event
                # carried it, and the `PostToolUse` row above has spent the shared session's.
                "session_id": "smoke-failure",
                "tool_name": "Bash",
                "tool_input": {"command": "uv run pytest -q"},
                "error": "Exit code 1",
            },
            0,
            "a red run Claude Code reports as a failure is annotated, never blocked",
            stderr_never=(FAULT,),
            context_says=(RED_RUN_NOTE,),
        ),
    ),
    # The note sync's triggers. The scratch `HOME` has no machine file, so the sync is off: the
    # handler reads that and says nothing, and the envelope carries no `decision` that would keep
    # a turn from ending.
    "Stop": (Sample({"stop_hook_active": False}, 0, "a turn ends", stderr_never=(FAULT,)),),
    "SessionEnd": (Sample({"reason": "other"}, 0, "a session ends", stderr_never=(FAULT,)),),
}

# What each `memory session-context` entry must have put in front of the model, by the part of
# its command after the wrapper. An empty tuple is the other claim and not an absence: that
# part renders nothing on this fixture, so anything at all in its stdout is a finding.
#
# **Why this registry exists.** Before it, every one of these rows ran against a project with no
# memory store: `drybag` answered "no memory store", the wrapper degraded that to 0, and each
# row asserted an exit code it would have had if `session-context` were
# `/bin/false`. Measured 2026-09-19 on the storeless fixture: ten rows, 0 bytes of stdout, all
# green. These are the entries that carry repository bytes toward the model, which is the one
# thing the smoke scenario exists to watch.
#
# Measured 2026-09-19 against the fixture's store: volatile-notes part 1 993, every other part
# empty — so the second and third part of the volatile bundle assert that a store which fits one
# part says nothing in the slots after it, and every standing-rules part asserts that a note the
# repository committed, `startup` rank and all, is never delivered as a standing rule.
INJECTED: dict[str, tuple[str, ...]] = {
    "memory session-context --bundle standing-rules --part 1": (),
    "memory session-context --bundle standing-rules --part 2": (),
    "memory session-context --bundle standing-rules --part 3": (),
    "memory session-context --bundle volatile-notes --part 1": (DELIMITER, VOLATILE_NOTE),
    "memory session-context --bundle volatile-notes --part 2": (),
    "memory session-context --bundle volatile-notes --part 3": (),
}


def tail_of(command: str) -> str:
    """The part of a `hooks.json` command after the wrapper — what the entry actually asks."""
    return command.split("run-hook.sh")[-1].strip().lstrip('" ')


def entries(plugin_root: Path) -> list[tuple[str, str]]:
    document = json.loads((plugin_root / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return [
        (event, entry["command"])
        for event, groups in document["hooks"].items()
        for group in groups
        for entry in group["hooks"]
    ]


def fixture_repository(fixture: Path, into: Path) -> Path:
    """A copy of the fixture as a committed repository, which is what the wrapper resolves."""
    shutil.copytree(fixture, into)
    env = {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "fixture"],
    ):
        subprocess.run(["git", "-C", str(into), *args], check=True, capture_output=True, env=env)  # noqa: S603, S607
    return into


def developer_free_env() -> dict[str, str]:
    """This process's environment with this developer's own harness and drybag stripped out,
    and the floor a test runner set kept: the base both smoke scripts build a session on.
    """
    return {
        k: v
        for k, v in os.environ.items()
        if k == FLOOR_VARIABLE or not k.startswith(("DRYBAG_", "XDG_", "CLAUDE_", "PLUGIN_"))
    }


def session_env(*, plugin_root: Path, project: Path, home: Path, data: Path) -> dict[str, str]:
    """The environment a hook entry meets, with this developer's own drybag stripped out."""
    env = developer_free_env()
    env.update(
        {
            "HOME": str(home),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
            "CLAUDE_PROJECT_DIR": str(project),
            "CLAUDE_PLUGIN_DATA": str(data),
        }
    )
    return env


def check_entry(
    event: str,
    command: str,
    sample: Sample,
    *,
    plugin_root: Path,
    project: Path,
    home: Path,
    data: Path,
) -> str | None:
    argv = shlex.split(command.replace(PLACEHOLDER, str(plugin_root)))
    env = session_env(plugin_root=plugin_root, project=project, home=home, data=data)
    payload = {
        "session_id": "smoke",
        "cwd": str(project),
        "hook_event_name": event,
        **sample.payload,
    }
    done = subprocess.run(  # noqa: S603
        argv,
        input=json.dumps(payload),
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if done.returncode != sample.expected_code:
        return (
            f"exited {done.returncode}, expected {sample.expected_code}; "
            f"stderr: {done.stderr.strip()[:200]}"
        )
    for phrase in sample.stderr_never:
        if phrase in done.stderr:
            return f"stderr reports a fault ({phrase!r}): {done.stderr.strip()[:200]}"
    wanted = INJECTED.get(tail_of(command))
    if wanted is not None:
        for phrase in wanted:
            if phrase not in done.stdout:
                return f"injected nothing carrying {phrase!r} ({len(done.stdout)} characters)"
        if not wanted and done.stdout.strip():
            return f"this part renders nothing on the fixture, yet emitted {len(done.stdout)}"
    # Only the dispatcher's own entries (`… hook <event>`) speak JSON; the six
    # `memory session-context` entries print a bundle as prose, which is how they inject it.
    context = ""
    if "hook" in argv and done.stdout.strip():
        try:
            emitted = json.loads(done.stdout)
        except json.JSONDecodeError:
            return "stdout is not JSON"
        specific = emitted.get("hookSpecificOutput", {})
        # The one event Claude Code refuses the field on (`hook_specific_output`).
        if event == "SessionEnd" and "hookSpecificOutput" in emitted:
            return "stdout carries a hookSpecificOutput, which Claude Code refuses on SessionEnd"
        if event != "SessionEnd" and specific.get("hookEventName") != event:
            return f"stdout names {specific.get('hookEventName')!r}, not {event!r}"
        context = str(specific.get("additionalContext", ""))
    for phrase in sample.context_says:
        if phrase not in context:
            return f"the context does not say {phrase!r} ({len(context)} characters)"
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("--plugin-root", "--fixture", "--scratch"):
        parser.add_argument(flag, required=True, type=Path)
    args = parser.parse_args(argv)
    # Resolved, because every subprocess below runs with `cwd=project`: a relative plugin root
    # would be looked for inside the fixture, which is the one tree it is never in.
    args.plugin_root = args.plugin_root.resolve()
    args.fixture = args.fixture.resolve()
    args.scratch = args.scratch.resolve()
    project = fixture_repository(args.fixture, args.scratch / "project")
    home, data = args.scratch / "home", args.scratch / "data"
    home.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    wrapper = args.plugin_root / "hooks" / "run-hook.sh"
    failures = 0
    if not os.access(wrapper, os.X_OK):
        print(f"FAIL  {wrapper} is not executable")
        failures += 1
    found = entries(args.plugin_root)
    if not found:
        print("FAIL  no hook entries at all")
        return 1
    # An event with no sample would contribute zero rows and a green summary — the vacuous
    # shape this repository names; a sixth event fails here until it has a sample.
    events = {event for event, _ in found}
    unsampled = events - SAMPLES.keys()
    if unsampled:
        print(f"FAIL  no sample event for {sorted(unsampled)}")
        return 1
    # And the converse, which is the direction that fails silently. The check above catches
    # `hooks.json` GAINING an event; `hooks.json` LOSING one shrinks `found`, empties
    # `unsampled`, runs fewer rows and prints a green summary — the entry stopped being
    # tested and nothing said so. Both directions, so the set of events this run covers is
    # exactly the set the samples describe.
    unentered = SAMPLES.keys() - events
    if unentered:
        print(f"FAIL  no hook entry for {sorted(unentered)}; hooks.json lost an event")
        return 1
    # The same two directions for the entries that inject. An injection entry with no registry
    # line would be checked for its exit code alone, which is what every one of them was;
    # a registry line with no entry means `hooks.json` dropped a bundle and the run would
    # simply stop testing it.
    injecting = {tail_of(command) for _, command in found if "session-context" in command}
    unregistered = injecting - INJECTED.keys()
    if unregistered:
        print(f"FAIL  no injection registered for {sorted(unregistered)}")
        return 1
    ungathered = INJECTED.keys() - injecting
    if ungathered:
        print(f"FAIL  no hook entry for {sorted(ungathered)}; hooks.json lost a bundle")
        return 1
    (project / UNCOMMITTED).write_text("a change nobody has committed\n", encoding="utf-8")
    rows = 0
    for event, command in found:
        for sample in SAMPLES.get(event, ()):
            problem = check_entry(
                event,
                command,
                sample,
                plugin_root=args.plugin_root,
                project=project,
                home=home,
                data=data,
            )
            rows += 1
            mark = "ok  " if problem is None else "FAIL"
            why = f" -> {problem}" if problem else ""
            print(f"{mark}  {event:<13} {sample.label}: {tail_of(command)}{why}")
            failures += problem is not None
    # The floor, in both quantities, and after the rows so the summary reports it. A run that
    # executed fewer rows prints the same green last line as a run that executed all of them,
    # which is how a report proves less than it claims without anybody reading it wrong.
    if (len(found), rows) != (EXPECTED_ENTRIES, EXPECTED_ROWS):
        print(
            f"FAIL  {len(found)} entries and {rows} rows, expected "
            f"{EXPECTED_ENTRIES} and {EXPECTED_ROWS}"
        )
        failures += 1
    print(f"{len(found)} entries, {rows} row(s), {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
