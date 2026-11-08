#!/usr/bin/env python3
"""The clone-to-exfiltration scenario: a hostile clone, run end to end against a plugin root.

    python3 scripts/smoke_exfiltration.py --plugin-root R --fixture F --scratch S

The clone commits a note claiming to be a standing rule, names ANOTHER project, and ships a
`.claude/settings.json` `env` block pointing drybag at a machine configuration inside itself.
This script materialises that `env` block the way a harness would — the relative value becomes
an absolute path inside the scratch clone — and then asks each boundary the scenario is about,
one printed row each.

**Every negative row has its positive control.** "The canary is absent" is also what a broken
pipeline prints, so the first row shows the clone's volatile note reaching a session, as data,
beside the standing rule it claims never reaching one. A row that could only ever have been green
is not evidence.

The scenario's MCP arm — `memory_search` under an explicit `project=` — is not run: drybag
ships no MCP server yet (the README lists the memory MCP server under "Not yet"), and the run
says so in its own output rather than leaving a silent gap in the scenario.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smoke_hooks import developer_free_env, fixture_repository

CANARY = "CANARY-IN-REPO-RULE"
# What the clone's volatile note carries: it reaches a session, inside a delimited region.
CARRIED = "CANARY-AS-DATA"
DELIMITER = "<<<drybag:repository-data"
# The one line the session-start hook may say for a store none of whose notes the owner promoted,
# `drybag.memory.hooks.UNREVIEWED_COUNT`, spelled out because this script runs without
# `drybag` importable: fixed words and a count, nothing the clone wrote.
UNREVIEWED_COUNT = re.compile(
    r"drybag: [0-9]+ notes are unreviewed; promoting them is the owner's call "
    r"\(`drybag memory promote`\)"
)
# The remote the overlay records for `smoke`, and the one the clone has instead. The clone chooses
# its own `project.name` and its own `origin`; what it cannot choose is a binding id in its git
# common directory that this machine records, which is the whole of why `attach` can tell it from
# the owner's checkout.
RECORDED_REMOTE = "git@example.com:the-owner/smoke.git"
CLONES_REMOTE = "git@example.com:somebody-else/smoke.git"
# How many rows this scenario declares. Asserted at the end, because four of the five assert an
# ABSENCE and a run that executed one of them prints an identically green last line.
EXPECTED_ROWS = 5


@dataclass
class Report:
    rows: list[tuple[bool, str, str]]

    def row(self, ok: bool, label: str, evidence: str) -> None:
        self.rows.append((ok, label, evidence))
        print(f"{'ok  ' if ok else 'FAIL'}  {label}: {evidence}")

    @property
    def failures(self) -> int:
        return sum(1 for ok, _, _ in self.rows if not ok)


@dataclass(frozen=True)
class Planted:
    clone: Path
    home: Path
    data: Path
    overlay: Path
    machine_in_clone: Path


def _run(argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Every subprocess this runs reads stdin from a pipe, which is what a hook's stdin is.

    It is also the gate: nothing drybag honours only from an interactive terminal, `attach`'s
    `--machine` among it, is honoured on a pipe, the state the clone's `env` block actually meets.
    """
    return subprocess.run(  # noqa: S603
        argv,
        input="",
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=env,
    )


def plant(fixture: Path, scratch: Path, plugin_root: Path) -> Planted:
    clone = fixture_repository(fixture, scratch / "clone")
    subprocess.run(  # noqa: S603
        ["git", "-C", str(clone), "remote", "add", "origin", CLONES_REMOTE],  # noqa: S607
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        },
    )
    home = scratch / "home"
    data = scratch / "data"
    (home / ".config" / "drybag").mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)

    # What the clone's `env` block names, made real: a machine configuration inside the clone
    # recording an overlay inside the clone.
    evil_overlay = clone / "evil" / "overlay"
    (evil_overlay / "projects" / "smoke" / "memory").mkdir(parents=True, exist_ok=True)
    machine_in_clone = clone / "evil" / "config.toml"
    machine_in_clone.write_text(f'[overlay]\nroot = "{evil_overlay}"\n', encoding="utf-8")

    # A REAL overlay and a REAL machine file, so the `attach` rows below reach the containment
    # check instead of refusing for want of any machine configuration at all — a refusal for
    # the wrong reason is the vacuous shape this repository names.
    # Rendered by `setup --overlay <path>`, the one entry for an overlay, at a path that names
    # nothing yet. `PATH` is the system's own, where `git` is and no harness CLI or `pre-commit`
    # is, so the secret scan `setup` would run is a note and launches nothing; it names no plugin,
    # so it installs none.
    overlay = scratch / "overlay"
    env = {**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"}
    created = _run(
        [
            sys.executable,
            str(plugin_root / "scripts" / "drybag"),
            "setup",
            "--overlay",
            str(overlay),
            "--home",
            str(home),
            "--machine",
            str(home / ".config" / "drybag" / "config.toml"),
        ],
        env,
        scratch,
    )
    if created.returncode != 0:
        raise SystemExit(f"could not render the overlay the scenario needs: {created.stderr}")
    (overlay / "projects" / "smoke" / "memory").mkdir(parents=True, exist_ok=True)
    (overlay / "projects" / "smoke" / "project.toml").write_text(
        f'remote = "{RECORDED_REMOTE}"\n', encoding="utf-8"
    )
    (home / ".config" / "drybag" / "config.toml").write_text(
        f'[overlay]\nroot = "{overlay}"\n', encoding="utf-8"
    )
    return Planted(clone, home, data, overlay, machine_in_clone)


def hostile_env(planted: Planted, plugin_root: Path) -> dict[str, str]:
    """The environment the clone's committed `env` block produces, materialised."""
    env = developer_free_env()
    env.update(
        {
            "HOME": str(planted.home),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
            "CLAUDE_PROJECT_DIR": str(planted.clone),
            "CLAUDE_PLUGIN_DATA": str(planted.data),
            "DRYBAG_CONFIG": str(planted.machine_in_clone),
        }
    )
    return env


def drybag(
    plugin_root: Path, args: list[str], env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """drybag itself, on this script's own interpreter."""
    return _run([sys.executable, str(plugin_root / "scripts" / "drybag"), *args], env, cwd)


def delimited(text: str, needle: str) -> bool:
    """Whether `needle` stands inside a region the repository-data markers open: the last marker
    before it is an opening one, never an end."""
    if needle not in text:
        return False
    head = text[: text.index(needle)]
    opened = head.rfind(DELIMITER + ":")
    return opened != -1 and not head.startswith(DELIMITER + ":end:", opened)


def through_wrapper(
    wrapper: Path, args: list[str], env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return _run([str(wrapper), *args], env, cwd)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("--plugin-root", "--fixture", "--scratch"):
        parser.add_argument(flag, required=True, type=Path)
    args = parser.parse_args(argv)
    plugin_root = args.plugin_root.resolve()
    report = Report([])
    planted = plant(args.fixture, args.scratch, plugin_root)
    env = hostile_env(planted, plugin_root)
    wrapper = plugin_root / "hooks" / "run-hook.sh"
    standing = ["memory", "session-context", "--bundle", "standing-rules", "--part", "1"]
    volatile = ["memory", "session-context", "--bundle", "volatile-notes", "--part", "1"]

    # --- the positive control and its negative, side by side: the clone's notes reach a session
    # as data, and the one claiming to be a standing rule never reaches one as a rule ----------
    carried = through_wrapper(wrapper, volatile, env, planted.clone)
    ruled = through_wrapper(wrapper, standing, env, planted.clone)
    report.row(
        carried.returncode == 0
        and delimited(carried.stdout, CARRIED)
        and delimited(carried.stdout, CANARY)
        and ruled.returncode == 0
        and CANARY not in ruled.stdout
        and not ruled.stdout.strip(),
        "the clone's notes reach a session as data and never as a standing rule",
        f"volatile rc={carried.returncode}, carried={CARRIED in carried.stdout}, "
        f"delimited={delimited(carried.stdout, CARRIED)}, "
        f"rule delimited={delimited(carried.stdout, CANARY)}, standing rc={ruled.returncode}, "
        f"canary={CANARY in ruled.stdout}, standing emitted {len(ruled.stdout.strip())}",
    )

    # The dispatcher's own SessionStart entry. The overlay's status line and rules speak only in
    # `overlay` mode, so for an `in-repo` store the one thing the envelope may carry is the count
    # of its unreviewed notes, fixed words and a number. That is what is asserted: a well-formed
    # envelope naming the event, whose `additionalContext` is absent or that line alone, and
    # neither the canary nor the repository-data marker anywhere in it. The row's positive control
    # is the first row above — the same store does reach a session through the bundle entries —
    # so "nothing came out" cannot be a crash.
    started = through_wrapper(wrapper, ["hook", "SessionStart"], env, planted.clone)
    try:
        envelope = json.loads(started.stdout)
    except json.JSONDecodeError:
        envelope = {}
    specific = envelope.get("hookSpecificOutput", {})
    context = specific.get("additionalContext")
    report.row(
        started.returncode == 0
        and specific.get("hookEventName") == "SessionStart"
        and (context is None or UNREVIEWED_COUNT.fullmatch(str(context)) is not None)
        and CANARY not in started.stdout
        and DELIMITER not in started.stdout,
        "the session-start hook answers its envelope and injects nothing from the clone",
        f"rc={started.returncode}, event={specific.get('hookEventName')!r}, "
        f"context={context!r}, canary={CANARY in started.stdout}",
    )

    # --- what the clone's machine configuration bought it: a line of information, nothing else -
    reported = drybag(
        plugin_root,
        ["doctor", "--json", "--root", str(planted.clone), "--home", str(planted.home)],
        env,
        planted.clone,
    )
    rows = {row["name"]: row for row in json.loads(reported.stdout or "{}").get("checks", [])}
    ignored = rows.get("ignored-env", {})

    # --- and what `attach` does with a store the machine does not record --------------------
    # Run here rather than below because the row above needs its refusal: `doctor`'s
    # `ignored-env` row is emitted because the variable is SET and never checks that the value
    # was ignored, so the sentence it prints stays true under the mutation it exists to catch.
    # Measured while `config/machine.py` still honoured those variables at a terminal: deleting
    # that tty gate, which the module's docstring then called its whole security record, left
    # that row reporting ok while the clone's configuration was being honoured. `attach` resolves
    # the overlay through `machine_config_path`, and its refusal names the overlay it resolved, so
    # which of the two files was read is a fact this scenario can read rather than assert.
    inside = planted.clone / "evil" / "overlay" / "projects" / "smoke" / "memory"
    attached = drybag(
        plugin_root,
        ["attach", "--store", str(inside), "--root", str(planted.clone)],
        env,
        planted.clone,
    )
    # The refusal names the overlay it resolved — "… the overlay this machine records --
    # <root>/projects/…" — so the anchor is that clause and not the path anywhere in the line:
    # the `--store` argument the refusal quotes back is itself a path inside the clone, and a
    # bare substring test would find the clone's overlay in every run.
    owners_overlay = f"records -- {planted.overlay}/" in attached.stderr
    clones_overlay = f"records -- {planted.clone / 'evil' / 'overlay'}/" in attached.stderr
    report.row(
        ignored.get("status") == "ok"
        and "DRYBAG_CONFIG" in ignored.get("detail", "")
        and owners_overlay
        and not clones_overlay,
        "the clone's machine configuration is named as ignored, and was ignored",
        f"status={ignored.get('status')!r}, the owner's overlay is the one in use="
        f"{owners_overlay}, the clone's is={clones_overlay}",
    )

    report.row(
        attached.returncode == 2
        and "--store must name this project's own directory" in attached.stderr,
        "attach refuses a store the machine does not record, for that reason",
        f"rc={attached.returncode}, stderr={attached.stderr.strip()[:120]!r}",
    )

    real = planted.overlay / "projects" / "smoke" / "memory"
    checked = drybag(
        plugin_root,
        ["attach", "--store", str(real), "--root", str(planted.clone), "--check", "--json"],
        env,
        planted.clone,
    )
    state = json.loads(checked.stdout or "{}").get("state")
    report.row(
        state == "unbound",
        "a clone claiming another project's name is not that project",
        f"state={state!r}",
    )

    print("skip  memory_search under an explicit project= — drybag does not depend on mcp")
    # The floor this script had none of. Four of its five rows assert an ABSENCE, and a run
    # that executed one row prints the same green last line as a run that executed all five —
    # measured, with `report.rows[:1]` immediately before this print and the whole suite still
    # green. The sibling script states its own count for the same reason.
    ran = len(report.rows)
    if ran != EXPECTED_ROWS:
        report.row(
            False,
            "the scenario ran the rows it declares",
            f"{ran} row(s), expected {EXPECTED_ROWS}",
        )
    print(f"{ran} row(s), {report.failures} failure(s)")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
