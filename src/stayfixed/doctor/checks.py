"""The core's checks, the run that asks them, and the rows the areas contribute after them.

A row of the report is one check's answer under the check's name. The core's checks are `CHECKS`,
and their rows come first, in that order; every other row is an area's, contributed by its own
`doctor.py` (CONTRIBUTING.md, "Areas") and asked after the core's in area-name order. So nothing
here imports an area, and nothing here names or counts the rows an area contributes: which rows a
report has is `docs/cli.md`'s table, and `tests/doctor/test_checks.py`'s literal `REPORT`.
This module is the list and the run: how the areas' rows are found and guarded is
`registry.py`'s.

**A `Check` is not a `Finding`.** `findings.Finding` carries a rule, a path and a line, and its
docstring says the label carries "what the check computed" while the detail "may quote the
repository" and is for `--json`. A doctor row needs a fourth thing neither of those is — a
**remedy**, the command a reader is supposed to run next — and it has no path or line to carry.
Widening `Finding` would reach into three areas that depend on its current shape, so this area
defines its own record and reuses `findings.listed` for the summary line alone.

**What may be printed, and what may not.** Counts, labels, statuses and stayfixed's own
vocabulary are computed here and print freely. A repository-authored string does not: not
`[stayfixed] version`, not `[ci] ref`, not a hook command. The hook sink holds its diagnostics log
to that line in as many words — reasons, never payloads — and this module holds every other
row to it, as each area's `doctor.py` holds the rows it contributes, where a note's
filename and the reason a store does not resolve are repository-authored too.

**`diagnostics` follows the same ruling.** The sink's log has three fields that are stayfixed's
own vocabulary *for a log stayfixed wrote*. The log is found through `${CLAUDE_PLUGIN_DATA}`, so
this process never establishes that, and `error` is free text with no grammar and no cap on the
read side at all, so `diagnostics` prints a count and the reader opens the file. `_diagnostics`
says what quoting would let through.

**A value the environment names is not the same as a value this process chose**, and the two
checks that touch a plugin root say which they have: `plugin_root` is the one a variable named,
`own_root` is the only root anything executes.

**The sink's layout is read from `stayfixed.hooks.api`, where it is defined.** `DIRECTORY`,
`MARKERS`, `DIAGNOSTICS` and `DIAGNOSTICS_MAX_BYTES` are four strings this area and the hook area
must agree on, so they are shared vocabulary, *defined* on the hook area's surface, which
`sink.py` imports too — a re-export from `sink.py` would be a cycle, since `sink.py` imports
`api.py`. So this module imports another area through its published surface, as every module
does.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import stayfixed
from stayfixed import REPOSITORY_URL, fsops
from stayfixed.config.loader import CONFIG_FILE
from stayfixed.config.machine import (
    DEFAULT_CONFIG_DIR,
    machine_config_path,
    owner_home,
    passwd_home,
)
from stayfixed.config.schema import MEMORY_MODES, Config
from stayfixed.config.session import (
    SESSION_READ_LIMIT,
    TOO_LARGE_WARNING,
    SessionConfig,
    cause,
    session_config,
)
from stayfixed.doctor.model import (
    OK,
    RED,
    REPORT_THIS,
    SKIP,
    WARN,
    Check,
    Context,
    Contribution,
    Row,
    configured,
)
from stayfixed.doctor.registry import contributions
from stayfixed.findings import listed
from stayfixed.grammar import PATH_VALUE
from stayfixed.harnesses import CANONICAL, CLAUDE, HARNESSES
from stayfixed.hooks.api import (
    DIAGNOSTICS,
    DIAGNOSTICS_MAX_BYTES,
    DIRECTORY,
    MARKERS,
    data_root,
)
from stayfixed.printed import clipped
from stayfixed.release.api import is_released, released
from stayfixed.runner import Runner
from stayfixed.semver import later

# Where the harness reads stayfixed's wrapper from, relative to the plugin root. `hooks/` stays
# at the plugin root — `overlay/template.py` says why — so it is found by environment or by
# checkout probe and never through `importlib.resources`.
WRAPPER = "hooks/run-hook.sh"
# Wall-clock bound on the one subprocess this *module* launches. A report launches more, inside the
# areas whose rows it asks; `docs/cli.md` counts them, and `stayfixed.doctor` says which one leaves
# the machine.
#
# A named cap (CONTRIBUTING.md#named-caps), and no shipped file changes with it: this bounds
# `stayfixed --version` behind an interpreter probe, and nothing about it is a project's to tune.
# Wide enough for a cold interpreter start on a loaded machine, narrow enough that a hung probe does
# not hang `doctor`.
WRAPPER_TIMEOUT_SECONDS = 30
# Wall-clock bound on the one call this area makes that leaves the machine: the `ci-ref` row's
# `git ls-remote` over the public repository's tags, which `doctor/commands.py` builds the runner
# with. `runner.NETWORK_TIMEOUT_SECONDS` is 300 and is right for what it was written for — `gh
# repo create --clone` waiting on GitHub to instantiate a template, then a clone down the wire —
# but this row reads one tag listing, and once `init` records a ref, five minutes would be a block
# reachable from a command documented as a one-line diagnostic. The number is the wrapper probe's
# above, deliberately: both bound one bounded question that a hung peer must not turn into a hung
# `doctor`, and the report's other `git` calls go through `gitenv`'s five seconds. The shipped
# file that must change with it: none — nothing about it is a project's to tune.
CI_REF_TIMEOUT_SECONDS = 30
# The remedy of the plugin-root skip. A quiet `skip` row is what a machine with no findable
# plugin root looks like from here, and a `skip` with an empty remedy is what
# `skills/doctor/SKILL.md` tells the model not to treat as red — so it said nothing about the
# loudest fault `doctor` can meet. The two halves of it are not interchangeable: only the first
# gives a root `wrapper` will execute, which is why `wrapper`'s skip for a root the environment
# names carries that first half alone, and takes it from here rather than from a copy.
RUN_FROM_OWN_ROOT = (
    "run `stayfixed doctor` from the plugin's own launcher, so its root answers for itself"
)
PLUGIN_ROOT_REMEDY = (
    f"{RUN_FROM_OWN_ROOT}, or set CLAUDE_PLUGIN_ROOT to where the plugin is installed, which "
    "lets `wrapper` read the wrapper's executable bit without running it"
)
# Why `diagnostics` prints a count and no content. One constant because the reason is the row's
# whole substance, and a change that starts quoting the file has to delete this sentence to do it.
UNVOUCHED_LOG = (
    "the environment names where this file is, so nothing here can establish that stayfixed "
    "wrote it, and its fields are stayfixed's vocabulary only for a log stayfixed wrote"
)
# The variable, never its value: `${CLAUDE_PLUGIN_DATA}` is repository-reachable, so the path it
# expands to is as repository-authored as the file's contents.
DIAGNOSTICS_REMEDY = (
    "read ${CLAUDE_PLUGIN_DATA}/stayfixed/diagnostics.jsonl yourself; each line is one record, "
    "with its event, handler and error type: a hook failure, an answer the output cap cut, or a "
    "session that ran without some of its configuration (config-fallback)"
)


def _own_root() -> Path | None:
    """The plugin root **this** stayfixed is part of, derived from the running module's path.

    `scripts/stayfixed` puts `<plugin root>/src` on `sys.path`, so a stayfixed launched by the
    plugin — or out of a checkout — can name its own root without asking anything. A wheel
    cannot: `hooks/` is outside the module root by design, and `None` is the honest answer.
    """
    own = Path(stayfixed.__file__).resolve().parents[2]
    return own if fsops.is_file(own / WRAPPER) else None


# Every registered harness's name for the plugin root, `CANONICAL`'s first, read off the registry.
# Both names, because both reach this process: Codex exports `PLUGIN_ROOT` and also
# `CLAUDE_PLUGIN_ROOT`, as the spike record (`docs/plans/2026-09-05-agent-harness-p0-spikes.md`)
# measured in its *Codex plugin hooks* trial, so a rule written against one of them is
# `config/machine.py`'s own finding again — "gating one of a pair of equivalent inputs is not a
# partial defence, it is a redirect with a longer name". Neither is ever executed; see
# `_wrapper`.
NAMED_ROOTS = tuple(dict.fromkeys(harness.plugin_root_env for harness in (CANONICAL, *HARNESSES)))


def _named_root(env: Mapping[str, str]) -> Path | None:
    """The plugin root either of `NAMED_ROOTS` names, when it carries a wrapper."""
    for name in NAMED_ROOTS:
        named = env.get(name)
        if named and fsops.is_file(Path(named) / WRAPPER):
            return Path(named)
    return None


# A repository with no `stayfixed.toml`: what works there, and what adds the rest. A warning and
# never red, because it is the state of every repository the plugin is installed beside before
# anyone runs `init`, and the guards and this report work in it.
NOT_INITIALISED = (
    f"there is no {CONFIG_FILE} here; the session guards and `stayfixed doctor` work without one "
    "and memory stays the coding agent's own, and `stayfixed init` adds the rest"
)
NOT_INITIALISED_REMEDY = "run `stayfixed init --yes`"
# A `stayfixed.toml` that loads with keys ignored or put back to the preset's. Key names only: a
# note's sentence carries the loader's refusal. A key is repository-authored text, so it is
# printed bounded (`_noted_keys`).
NOTED = "{file} loads with {count} setting(s) ignored or put back to the preset's: {keys}"
# How many noted names a row prints before it counts the rest: `not-initialised`'s keys, and the
# machine file's notes on `preferences`. A named cap. A repository chooses how many keys its
# `stayfixed.toml` holds, the `doctor` skill relays this report to a model verbatim, and three say
# where to start; `stayfixed docs check` lists every one. `docs/cli.md` states the number in
# words, and `tests/test_documents.py` holds every sentence that does to this value.
NAMES_SHOWN = 3
NOTED_REMEDY = (
    f"`stayfixed docs check` refuses the file and prints why each one was; fix or remove them in "
    f"{CONFIG_FILE}"
)
# What this row prints in a key's place when the key is outside the path grammar: `_noted_keys`
# withholds it there, as `printed.printable` withholds such a key from a line a model reads.
UNPRINTABLE_KEY = "<a key that is not a plain name>"
FALLBACK_REMEDY = (
    f"`stayfixed docs check` prints why; run `stayfixed doctor` again after fixing {CONFIG_FILE}"
)
# A file longer than a session reads is not one a command refuses: `docs check` reads it to the
# command's own bound and loads it, so `FALLBACK_REMEDY` sent the owner to a command that exits 0.
# Formatted from the constant, which is the session's to move.
TOO_LARGE_REMEDY = (
    f"shorten {CONFIG_FILE} below {SESSION_READ_LIMIT:,} bytes, the most a session reads of it, "
    f"then run `stayfixed doctor` again"
)


def _not_initialised(context: Context) -> Row:
    """Whether there is a `stayfixed.toml`, and how much of it the session can use.

    Read the way a session reads it (`config.session`): none at all is a warning, a file that
    loads with notes is a warning listing their keys, and only a file the session drops whole is
    red, in the session's own words. The machine file's warning is the `preferences` row's.
    """
    session = context.session
    dropped = session.project_warnings
    if context.config is None:
        if dropped:
            remedy = TOO_LARGE_REMEDY if dropped[0] == TOO_LARGE_WARNING else FALLBACK_REMEDY
            return Row(RED, cause(dropped[0]), remedy)
        return Row(WARN, NOT_INITIALISED, NOT_INITIALISED_REMEDY)
    if session.noted:
        keys = _noted_keys(session.noted)
        detail = NOTED.format(file=CONFIG_FILE, count=len(session.noted), keys=keys)
        return Row(WARN, detail, NOTED_REMEDY)
    return Row(OK, f"{CONFIG_FILE} loads", "")


def _noted_keys(keys: Sequence[str]) -> str:
    """The first `NAMES_SHOWN` of `keys`, then how many more.

    A key is any text the repository chose, bounded in length by nothing. One outside the path
    grammar is withheld, as `printed.printable` withholds it from a line a model reads; one
    inside it prints through `printed.clipped`, so the row is as long as the cap allows, however
    long a name the file holds."""
    shown = [clipped(key) if PATH_VALUE.match(key) else UNPRINTABLE_KEY for key in keys]
    return _counted(shown[:NAMES_SHOWN], len(keys) - NAMES_SHOWN, ", ")


def _counted(shown: list[str], more: int, separator: str) -> str:
    """`shown` joined by `separator`, and how many more were left out when `more` is positive."""
    return separator.join(shown) + (f"{separator}and {more} more" if more > 0 else "")


VERSION_BEHIND = "run `stayfixed upgrade`, which moves it and refreshes the scaffold with it"
VERSION_AHEAD = (
    "update the stayfixed plugin: this project records a newer stayfixed than the one running, "
    "and `stayfixed upgrade` never moves a project backward"
)
VERSION_UNREADABLE = (
    "set [stayfixed] version to the X.Y.Z of the stayfixed release this project was last upgraded "
    "with: `stayfixed upgrade` refuses a version it cannot read rather than guess its direction"
)
VERSION_UNORDERED = (
    "the two share one X.Y.Z and differ after it in a way stayfixed does not order, such as two "
    "pre-releases, and `stayfixed upgrade` refuses rather than guess the direction; set "
    "[stayfixed] version to the version running here by hand if that is the one this project "
    "should move to"
)


def _versions(context: Context) -> Row:
    running = stayfixed.__version__
    if context.config is None:
        # The installation's half of the question still has an answer: which stayfixed runs.
        return Row(
            OK, f"stayfixed {running} is running; there is no project configuration to match"
        )
    recorded = context.config.stayfixed.version
    if recorded == running:
        return Row(OK, f"the project and this stayfixed are both {running}", "")
    # The project's own string is repository-authored and is not quoted back; what is printed
    # is the version that is actually running. The remedy follows the direction: `upgrade`
    # refuses a project that records a newer stayfixed, so sending that one to it is a dead end.
    # `later` is the reader `upgrade` refuses by, so the two agree: a leading `X.Y.Z` decides
    # the direction when the two differ in it, a release is newer than its own pre-release, and
    # a value without a leading `X.Y.Z`, or a pair `later` does not order, is sent to be written
    # by hand. `later(v, v)` is `None` exactly when `v` has no leading `X.Y.Z`.
    ahead = later(recorded, running)
    if ahead is None:
        readable = later(recorded, recorded) is not None
        remedy = VERSION_UNORDERED if readable else VERSION_UNREADABLE
    else:
        remedy = VERSION_AHEAD if ahead else VERSION_BEHIND
    return Row(
        WARN,
        f"{CONFIG_FILE} declares a different stayfixed version from the {running} running here",
        remedy,
    )


def _wrapper(context: Context) -> Row:
    """Execute the wrapper once, and report the fault it printed.

    This check closes a blind spot that no row reading a file can see. A fault the wrapper
    meets, such as no `python3` of 3.11 or newer on `PATH`, prints to stderr and exits **0**;
    the harness discards
    stderr on a 0; no Python ran, so nothing reached the sink; and `doctor` itself runs under
    whatever interpreter the user invoked it with.
    On a machine where the probe fails, every bundle is silently absent and all three diagnostic
    surfaces are blind. One subprocess closes it.

    `--version` and not a hook event: the point is whether the wrapper can reach stayfixed at
    all, and the cheapest question that proves it is the one that changes nothing.

    **Only a root this process derived for itself is ever executed.** `context.own_root` and
    not `context.plugin_root`: with a wheel install `_own_root()` answers `None`, and a project
    that commits `hooks/run-hook.sh` mode 100755 plus an `env` block naming its own tree would
    get that script *run* by `stayfixed doctor` under a named root, which would then report
    `wrapper: ok` — code execution and a false clean bill of health in one row. Requiring the named
    root to lie outside the project root is the weaker containment: it needs both sides resolved to
    survive a committed symlink, and it still admits a second attacker-controlled checkout on the
    same machine. A `skip` that names what it could not vouch for is the honest answer for a root
    this process did not choose, and the wrapper's executable bit is still read there.
    """
    # `own_root` and not `plugin_root`, on one line, so the whole rule is the single thing a
    # mutation flips: what is launched here is a root this process derived, never one a
    # variable named.
    root = context.own_root
    if root is None:
        if context.plugin_root is None:
            return Row(
                SKIP,
                "the plugin root is not readable from here, so there is nothing to run and "
                "nothing here can say whether a hook entry would reach stayfixed at all",
                PLUGIN_ROOT_REMEDY,
            )
        # The bit needs only the path: a wrapper without `+x` exits 126, and Claude Code reads
        # every non-2 exit as a non-blocking error, which is permission.
        wrapper = context.plugin_root / WRAPPER
        if not os.access(wrapper, os.X_OK):
            return Row(
                RED,
                f"{WRAPPER} is not executable, so every hook entry exits 126 and the harness "
                "reads that as a non-blocking error; this is the plugin root the environment "
                "names, read here and run nowhere",
                f"chmod +x {wrapper}",
            )
        return Row(
            SKIP,
            "the only plugin root here is one the environment names, and a root this process "
            "cannot vouch for is never executed: its wrapper would run before any stayfixed "
            "guard does",
            RUN_FROM_OWN_ROOT,
        )
    env = {
        key: value
        for key, value in context.env.items()
        if not key.startswith(("CLAUDE_", "PLUGIN_", "STAYFIXED_"))
    }
    # Under Claude Code's names for the two roots, as `hooks/hooks.json` runs the wrapper.
    for variable, value in ((CLAUDE.plugin_root_env, root), (CLAUDE.project_dir_env, context.root)):
        if variable is not None:
            env[variable] = str(value)
    try:
        done = subprocess.run(  # noqa: S603 - list form, never a shell; stayfixed's own wrapper
            [str(root / WRAPPER), "--version"],
            cwd=context.root,
            capture_output=True,
            text=True,
            # Never quoted: the wrapper echoes what it was handed, a project directory in latin-1
            # bytes included, and strictly that raised and lost the row.
            errors="replace",
            check=False,
            timeout=WRAPPER_TIMEOUT_SECONDS,
            env=env,
            # Closed, not inherited, so a child that decides to read stdin cannot hold the report
            # open behind `WRAPPER_TIMEOUT_SECONDS`.
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Row(
            RED,
            f"{WRAPPER} could not be run ({type(exc).__name__}), so no hook entry can fire",
            f"check that {root / WRAPPER} exists and is executable",
        )
    if done.stderr or done.returncode != 0:
        return Row(
            RED,
            f"{WRAPPER} exited {done.returncode} and wrote to stderr, so every hook entry "
            "answers nothing on this machine and nothing else reports it",
            "run `hooks/run-hook.sh --version` and read its stderr",
        )
    return Row(OK, f"{WRAPPER} reached stayfixed and exited 0", "")


def _budgets(context: Context, config: Config) -> Row:
    """Every budget set above the preset and every one set below it.

    The base branch's `stayfixed.toml` sets a gate's budget and the owner's machine file a
    session's, in either direction, and the value set is the value in force (`Budgets.effective`).
    No consumer applies a platform cap to a budget — `native_caps` are checked beside the budget,
    never folded into it — so the row names no clamp. Budget keys are `Budgets.NAMES` and the loader
    refuses any other, so these are stayfixed's own names rather than a repository's strings.
    """
    budgets = config.budgets
    raised = sorted(
        name for name, value in budgets.configured.items() if value > budgets.preset[name]
    )
    lowered = sorted(
        name for name, value in budgets.configured.items() if value < budgets.preset[name]
    )
    moved = [
        f"{len(names)} budget(s) {direction}: {listed(names)}"
        for names, direction in ((raised, "raised above the preset"), (lowered, "lowered below it"))
        if names
    ]
    return Row(OK, "; ".join(moved) or "every budget is the preset's")


# The keys whose value is one of stayfixed's own words, which the loader holds to this vocabulary,
# and so may be printed. Every other text value is the repository's or the owner's to write, and
# is not.
ENUMERATED: Mapping[str, tuple[str, ...]] = {"memory.mode": MEMORY_MODES}
PREFERENCES_REMEDY = "fix the machine file the detail names, then run `stayfixed doctor` again"
# What reading the overlay's two layers said (`SessionConfig.resolution.notes`), named in the
# `preferences` row as information.
OVERLAY_NOTES = "The overlay layers: {notes}"
# A machine file that does not load, in the words of its refusal (`Owner.unloaded`), which names
# the file and the parser's position and never its text. Red, as every red row is a statement that
# this installation is wrong: a session reads past the file, and every command refuses it.
MACHINE_UNLOADED = (
    "{error}, so every command refuses it, and a session runs on the preset's personal values and "
    "guards in its place"
)


def _shown(key: str, value: object) -> str | None:
    """`value` as the row may print it, or `None` where it is text somebody else wrote."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    vocabulary = ENUMERATED.get(key, ())
    return value if isinstance(value, str) and value in vocabulary else None


def _named(key: str, value: object, layer: str) -> str:
    shown = _shown(key, value)
    return f"{key} ({layer})" if shown is None else f"{key} = {shown} ({layer})"


def _preferences(context: Context) -> Row:
    """Each key the session resolved, and the layer its value came from.

    The session's one resolution (`SessionConfig.resolution`) over the preset, the repository's
    file after the NOTE load, the overlay's common and project files and the machine file gives
    every value and its layer; the row derives none. The value is printed only where it is a
    boolean, a number or one of stayfixed's own words (`ENUMERATED`): a name list, a profile or a
    personal value is text a repository, an overlay or an owner wrote, and stays out of a row a
    model may read. Runs with no `stayfixed.toml` too, where nothing is the repository's.

    A machine file that does not load is red, in its refusal's words (`MACHINE_UNLOADED`): every
    command refuses it, and the report, which reads it as a session does, was otherwise the one
    run that exited 0 on it. What the owner's layer read past in a file that loads is a warning.
    Every note of the resolution — what the overlay's files could not give, and what `resolve`
    refused — is named after the values (`OVERLAY_NOTES`), and moves no status.
    """
    resolution = context.session.resolution
    named = [
        _named(key, resolution.values[key], str(layer))
        for key, layer in sorted(resolution.provenance.items())
    ]
    detail = "; ".join(named)
    if resolution.notes:
        # Information, never a status: a machine with no overlay, or a project with no file of its
        # own, is an ordinary state. Each note was composed through `stayfixed.printed` where it
        # was made (`config.overlay_layers`, `classes.resolve`), so nothing raw reaches the row.
        detail = f"{detail}. {OVERLAY_NOTES.format(notes='; '.join(resolution.notes))}"
    owner = context.session.owner
    if owner.unloaded is not None:
        return Row(
            RED, f"{detail}. {MACHINE_UNLOADED.format(error=owner.unloaded)}", PREFERENCES_REMEDY
        )
    notes = owner.notes
    if notes:
        return Row(
            WARN,
            f"{detail}. The machine file could not be used whole: "
            f"{_counted(list(notes[:NAMES_SHOWN]), len(notes) - NAMES_SHOWN, '; ')}",
            PREFERENCES_REMEDY,
        )
    return Row(OK, detail)


def _cli_path(context: Context) -> Row:
    """Whether `stayfixed` resolves by name on this machine.

    Codex performs no `${CLAUDE_PLUGIN_ROOT}` substitution in skill content, as the spike record's
    *plugin-root substitution and executable bits* trial measured, so a skill that says
    `stayfixed …` needs the name to resolve on PATH there.

    **Asked of `context.env`, like every other check that reads the environment**, and never of
    `os.environ["PATH"]` directly, which a bare `shutil.which("stayfixed")` reads. `run_checks`
    defaults that mapping to `os.environ`, so a real run reads the same `PATH` either way; what
    asking the context buys is an answer that is a function of the context rather than of
    whichever shell the caller happens to be in, so a test can state the answer it expects — read
    from the process, the row says `ok` on a developer machine with the tool installed and `warn`
    in a container without it, and a body hardcoded to `WARN` would pass the whole suite.

    The default is `""` and not `None`, which is the difference between the sentence above being
    true and being true of every environment but one: `shutil.which(path=None)` falls back to
    `os.environ["PATH"]`, so an `env` carrying no `PATH` would reach the process environment
    through the very call that exists to stop doing that. An environment with no `PATH` resolves
    nothing, which is the honest answer and the one the row's own remedy addresses.

    **The resolved path is never printed.** `PATH` is read from `context.env` precisely because
    it is repository-authored, and a POSIX path component is unbounded and may hold a newline --
    `shutil.which` round-trips one -- so the value is the same class of input `_diagnostics`
    refuses to print. The row says
    the name resolves; the reader's own `command -v stayfixed` says where.
    """
    found = shutil.which("stayfixed", path=context.env.get("PATH", ""))
    if found is None:
        return Row(
            WARN,
            "`stayfixed` does not resolve on PATH, so a skill that invokes it by name fails on "
            "Codex, which performs no plugin-root substitution in skill content",
            # `REPOSITORY_URL` and not the address written out: a URL is spelled once. A second
            # spelling of a URL is a second thing to move when the repository does, and `doctor`
            # is the command whose whole job is finding the two halves of something that has
            # stopped agreeing.
            f"run `uv tool install git+{REPOSITORY_URL}`",
        )
    return Row(OK, "`stayfixed` resolves on PATH")


# `init` records `[ci] ref` as a commit, and the documented opt-in, from 1.0.0 on, is the mutable
# `v1` alias; before the first 1.x release the public repository carries no such tag, and the row
# is red. Both are judged against the public repository's own tags, which is why neither ever
# reaches a subprocess: a sha cannot be asked for by name, so the row asks `git ls-remote` about a
# constant URL and a constant pattern (`release.pins`) and compares in Python.
_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
ALIAS = "v1"
# The rendered workflow, which is the pin GitHub actually acts on.
WORKFLOW = ".github/workflows/stayfixed.yml"
# Bound on the read of that file, which a repository authors. `DIAGNOSTICS_MAX_BYTES` is the same
# number for the same reason one function down. A named cap (CONTRIBUTING.md#named-caps), and the
# shipped file that changes with it is `templates/project/stayfixed.yml`, which renders to well
# under 2 KiB. Two orders of magnitude above it leaves room for a project that adds jobs of its own
# around the call, and still refuses to read a file no `init` could have written into a one-line
# diagnostic.
WORKFLOW_MAX_BYTES = 256 * 1024
# Its `uses:` ref is the word after `@`; a trailing ` # v0.1.0` version comment is not part of it.
# The word after `uses:` is read once, and its ref found in it by `_pinned_refs`: a pattern that
# ran on past the word's first character to the last call in it read the word again from every
# `uses:` inside it, ten seconds over a file at the cap holding nothing else.
_USES_KEY = "uses:"
_USES = re.compile(rf"{_USES_KEY}\s*+(\S++)")
_CALL = "/.github/workflows/check.yml@"
# Said of a path that is there and is not a regular file: a directory, a device, a FIFO, or a
# symlink to any of those. Fixed text, and the file's own bytes are never reached.
WORKFLOW_NOT_A_FILE = (
    f"{WORKFLOW} is there and is not a regular file, so whether it pins the same ref as [ci] ref "
    f"was not checked"
)
CI_REF_REMEDY = (
    f"set [ci] ref in {CONFIG_FILE} to a released commit and rewrite the workflow's uses: line "
    f"to match, or run `stayfixed upgrade` once a release exists and it moves both"
)
# `git` itself having failed is a fact about this machine, not about `[ci] ref`, so it warns --
# the same split `_guarded` makes and for the same reason: red gates the exit code.
CI_REF_UNASKABLE = "[ci] ref could not be checked against the public repository's tags"
# A recorded ref and no workflow at all. Fixed text carrying this module's own `WORKFLOW`
# constant and nothing else: no byte of any repository-authored path reaches it.
NO_WORKFLOW = (
    f'[ci] mode is "reusable" and [ci] ref is recorded, and {WORKFLOW} is not there at all, so '
    f"no stayfixed gate runs on this repository"
)
NO_WORKFLOW_REMEDY = (
    f'write {WORKFLOW} with a uses: line pinned to [ci] ref, or set [ci] mode = "none" if this '
    f"repository is not meant to run the stayfixed gate; `stayfixed upgrade` renders it for you"
)


def _ref_is_released(context: Context, ref: str) -> Row:
    """What the public repository's tags say about `[ci] ref`, in one `git ls-remote`.

    The alias arm asks for the tag listing and the sha arm asks the `release` package's own rule
    (`is_released`, which filters to `vX.Y.Z` so the mutable alias cannot make a commit look
    released); the two arms are exclusive, so either way the row launches `git` exactly once.
    """
    if ref == ALIAS:
        tags = released(context.runner, cwd=context.root)
        if tags is None:
            return Row(WARN, CI_REF_UNASKABLE, CI_REF_REMEDY)
        if ALIAS not in tags:
            return Row(
                RED,
                f"[ci] ref is the {ALIAS} alias and the public repository carries no such tag",
                CI_REF_REMEDY,
            )
        return Row(
            WARN,
            f"[ci] ref is the {ALIAS} alias, a mutable opt-in; a released commit is the "
            f"immutable form",
            CI_REF_REMEDY,
        )
    if _SHA.match(ref):
        is_a_release = is_released(ref, context.runner, cwd=context.root)
        if is_a_release is None:
            return Row(WARN, CI_REF_UNASKABLE, CI_REF_REMEDY)
        if not is_a_release:
            return Row(
                RED, "[ci] ref is not the commit of any released stayfixed tag", CI_REF_REMEDY
            )
        return Row(OK, "[ci] ref is a released stayfixed commit")
    return Row(
        RED,
        f"[ci] ref is neither a 40-character commit sha nor the {ALIAS} alias, so it was not "
        f"checked against anything",
        CI_REF_REMEDY,
    )


def _ci_ref(context: Context, config: Config) -> Row:
    """Whether `[ci] ref` is the commit of a released stayfixed, and whether the rendered workflow
    pins the same ref.

    **The value never reaches a subprocess.** `init` records it as a sha, and a sha cannot be
    asked for by name, so the row asks the `release` package which commits the public repository's
    `v*` tags name -- a constant URL, a constant pattern -- and compares in Python. The alias is
    reported as what it is, a mutable opt-in; and the rendered workflow is read because the pin
    GitHub acts on is the file, not the configuration beside it.

    `init` is the command that writes both, so an empty value is `skip` rather than red: a
    repository that has not been initialised has had no chance to set one, and calling that a
    fault would make `doctor` red on every correct installation.

    **Three ways the workflow can fail to agree, and none of them is `ok`.** It can disagree
    (red), be unreadable or unrecognisable (warn), or not be there at all — and that last one,
    answered with the ref's own verdict, would have a repository with a released sha recorded
    and no workflow report "[ci] ref is a released stayfixed commit", which a reader takes for
    "my gate is pinned correctly". `[ci] mode` is what makes the absent file a finding rather than
    the configuration working: only `reusable` renders one.

    The value is repository-authored and is never printed -- not in the detail, not in the
    remedy, and not in an argument list.
    """
    ref = config.ci.ref
    if not ref:
        return Row(SKIP, "no [ci] ref is recorded, so there is nothing to resolve", "")
    row = _ref_is_released(context, ref)
    if row.status == RED:
        return row
    workflow = context.root / WORKFLOW
    # **A regular file, and a bounded read of it.** `_diagnostics` reads its log to a cap, and
    # this path is repository-authored in the same sense: a clone chooses what sits at
    # `.github/workflows/stayfixed.yml`. A committed symlink to a FIFO there makes an unguarded
    # `read_text` block with nothing to read, so `doctor` — one line, documented as a diagnostic —
    # never returns at all; measured on a real FIFO, the row did not come back.
    #
    # None of the file's bytes is printed on any arm, so this is containment hygiene rather than a
    # leak, which is why it is a guard here and not a refusal. A directory reaches the same arm
    # rather than the `OSError` one below, which would name `IsADirectoryError`; the arm's own
    # sentence says what a reader needs and carries no platform's spelling of the fault.
    if not fsops.is_file(workflow):
        if fsops.exists(workflow) or fsops.is_symlink(workflow):
            return Row(WARN, WORKFLOW_NOT_A_FILE, CI_REF_REMEDY)
        # No file at all, which is not agreement either. `return row` here alone would report
        # `ok` — "[ci] ref is a released stayfixed commit" — for a repository with no gate in it,
        # and a reader takes that for "my gate is pinned correctly". It is the same false green the
        # `not pinned` arm below refuses by name, and this is the state `init` itself leaves
        # whenever it reports `ci-workflow` under `skipped`, and the state anyone reaches by
        # deleting the file. `mode` is what tells the cases apart: under `none` or `uvx` this build
        # renders no workflow, so an absent one is the configuration working.
        if config.ci.mode == "reusable":
            return Row(WARN, NO_WORKFLOW, NO_WORKFLOW_REMEDY)
        return row
    try:
        # Through `fsops.read_bounded`, so what is opened is asked again: a FIFO swapped in after
        # the check above is refused unread rather than waited on.
        raw, over = fsops.read_bounded(workflow, WORKFLOW_MAX_BYTES)
    except OSError as exc:
        return Row(
            WARN,
            f"{WORKFLOW} is there and could not be read ({fsops.said(exc)}), so whether it "
            f"pins the same ref as [ci] ref was not checked",
            CI_REF_REMEDY,
        )
    if over:
        # Over the cap is itself an answer, the way it is for the hook sink's log: this is not a
        # file `init` rendered, and a `uses:` line past the cap would be compared against bytes
        # that were never read. Never the ref's own verdict, for the reason the arms around it
        # give.
        return Row(
            WARN,
            f"{WORKFLOW} is larger than {WORKFLOW_MAX_BYTES} bytes, so whether it pins the same "
            f"ref as [ci] ref was not checked",
            CI_REF_REMEDY,
        )
    # `errors="replace"` and not a strict decode: a stray byte in a repository-authored file used
    # to raise `UnicodeDecodeError`, which is a `ValueError` and so escaped to `_guarded` as a red
    # row saying the check could not run — a red a clone could force, on a row whose own rule is
    # that a file it cannot account for is named and never absolved. A replaced byte cannot forge
    # a sha: `_USES` bounds what is compared, and nothing read here is printed.
    rendered = raw.decode("utf-8", errors="replace")
    # `finditer` and not `search`: the first `uses:` in the file may belong to another job, and
    # a recognisable pin after it is still the pin GitHub acts on. Every recognisable one is
    # compared, so a second job pinning something else is a finding too.
    pinned = _pinned_refs(rendered)
    if not pinned:
        # Read and not recognised. Returning the ref's own verdict here would read as "the
        # workflow agrees", which is the false green the `OSError` arm beside it already refuses
        # to produce. None of the file's bytes is printed -- it is a repository-authored file.
        return Row(
            WARN,
            f"{WORKFLOW} is there and carries no `uses:` line this build recognises, so whether "
            f"it pins the same ref as [ci] ref was not checked",
            CI_REF_REMEDY,
        )
    if pinned != {ref}:
        return Row(
            RED,
            "the workflow pins a different ref from [ci] ref, so the gate that runs is not the "
            "one recorded",
            CI_REF_REMEDY,
        )
    return row


def _pinned_refs(text: str) -> set[str]:
    r"""Every ref a `uses:` word in `text` pins: what follows the last call in the word that has a
    character before it and one after, as `uses:\s*\S+/\.github/workflows/check\.yml@(\S+)`
    read it. A word that pins nothing is passed over whole, since a `uses:` inside it reaches no
    call the word does not, except one that ends the word, which reads the word after it."""
    pinned = set()
    at = 0
    while (match := _USES.search(text, at)) is not None:
        word = match.group(1)
        call = word.rfind(_CALL)
        if call >= 0 and call + len(_CALL) == len(word):
            call = word.rfind(_CALL, 0, call)
        at = match.end()
        if call > 0:
            pinned.add(word[call + len(_CALL) :])
        elif word.endswith(_USES_KEY):
            at -= len(_USES_KEY)
    return pinned


def _is_record(line: bytes) -> bool:
    """Whether one line of the sink's log is a JSON object, which is all this check asks of it.

    Bytes and not text: the file may be anything, and `json.loads` raising `UnicodeDecodeError`
    on a line that is not UTF-8 is the same answer as raising `JSONDecodeError` on one that is
    not JSON — this is not a record. So is a line the parser cannot read although it is valid
    JSON: an integer literal longer than the interpreter converts raises a plain `ValueError`, and
    nesting past what the parser follows raises `RecursionError`. The log is wherever a committed
    `env` block points, and either one let through ended this row in `_guarded`'s red.
    """
    try:
        record = json.loads(line)
    except (ValueError, RecursionError):
        return False
    return isinstance(record, dict)


def _diagnostics(context: Context) -> Row:
    """How many reasons the hook sink recorded. A count, and not one byte of the file.

    **Nothing in this file is quoted, because nothing here can establish who wrote it.** The log
    is `${CLAUDE_PLUGIN_DATA}/stayfixed/diagnostics.jsonl`, and that variable is the same class
    as `NAMED_ROOTS`: a committed `.claude/settings.json` `env` block reaches this process without
    a trust prompt. `event`,
    `handler` and `error` are stayfixed's own vocabulary *for a log stayfixed wrote*; for a log a
    repository committed they are three free-text fields, and `skills/doctor/SKILL.md` tells the
    model to relay this detail verbatim: quoted, a committed log whose `handler` is an
    instruction-shaped string and whose `error` is 5,000 characters gives a `warn` detail of more
    than 5,000 characters carrying both.

    So no field is allowed through, however few. What is left is a count, which is this check's
    own answer, and a remedy that names the file by the variable rather than by its value — the
    value is repository-authored too.

    **The read is bounded here, because the cap the sink documents is enforced on write.**
    `DIAGNOSTICS_MAX_BYTES` bounds what `DataSink.diagnostic` appends; a file this process did
    not write has no cap at all, and one byte past it is itself an answer — this is not a file
    the sink produced, and the count below is a floor rather than a total.
    """
    # The rule the sink found the root by, so this row reads the tree the sink wrote.
    data = data_root(context.env)
    if not data:
        return Row(
            SKIP,
            "no harness data root is set in this environment, so the hook sink cannot be read",
            "",
        )
    base = Path(data) / DIRECTORY
    try:
        sessions = len(list((base / MARKERS).iterdir())) if fsops.is_dir(base / MARKERS) else 0
    except OSError as exc:
        # The harness data root is somebody else's directory on somebody else's filesystem, and
        # an unreadable one is a fact about this machine rather than a fault in the
        # installation. Unguarded it would reach `_guarded`, which renders any exception but an
        # `OSError` red and an `OSError` as a warning about the whole row — so it is answered here,
        # where the row can still say what it could and could not count.
        return Row(
            WARN,
            f"the hook sink's session markers could not be listed ({fsops.said(exc)}), so "
            f"neither the session count nor the record count below can be given",
            DIAGNOSTICS_REMEDY,
        )
    log = base / DIAGNOSTICS
    if not fsops.is_file(log):
        return Row(OK, f"no hook records are logged; {sessions} session(s) seen")
    try:
        raw, over = fsops.read_bounded(log, DIAGNOSTICS_MAX_BYTES)
    except OSError as exc:
        return Row(
            WARN,
            f"the hook sink's log is there and could not be read ({fsops.said(exc)})",
            DIAGNOSTICS_REMEDY,
        )
    count = sum(1 for line in raw.splitlines() if _is_record(line))
    if not count and not over:
        return Row(OK, f"no hook records are logged; {sessions} session(s) seen")
    # Records, and never told apart: which kind a line is lies in its `error` field, which is
    # stayfixed's vocabulary only for a log stayfixed wrote (`UNVOUCHED_LOG`).
    counted = f"{'at least ' if over else ''}{count} hook record(s) logged"
    return Row(
        WARN,
        f"{counted}; {sessions} session(s) seen. Not one line is quoted: {UNVOUCHED_LOG}",
        DIAGNOSTICS_REMEDY,
    )


# The two variables that could name the machine configuration file, and that no command reads.
# `config/machine.py` nominates this check by name: a machine owner who sets one "really does lose
# it rather than getting a wrong answer quietly".
IGNORED_ENV = ("STAYFIXED_CONFIG", "XDG_CONFIG_HOME")
# Information and not a warning: stayfixed follows `HOME`, as the harness does (`config.machine`).
# The value of `HOME` is not printed: `doctor` may be run by an agent whose environment a
# repository chose.
HOME_DIFFERS = (
    "HOME is not the home directory the password database records for this user; stayfixed "
    "follows HOME, as the harness does"
)


def _names_home_config(value: str, home: Path) -> bool:
    """Whether `value`, an `XDG_CONFIG_HOME`, names `home`'s `.config`, the directory the machine
    file is read under, so ignoring it loses nothing; a value that does not resolve names none."""
    if not os.path.isabs(value):
        return False
    try:
        return fsops.resolved(Path(value)) == fsops.resolved(home / DEFAULT_CONFIG_DIR)
    except OSError:
        return False


def _ignored_env(context: Context) -> Row:
    """The variables that could name the machine file and that no command reads, and a `HOME` that
    is not the password database's: information, never a status. Each is a choice of the person
    who set it, which no command of stayfixed's can undo, so a warning about it would be a row that
    never clears."""
    # The home every command reads under, and none for a `HOME` that names none (`owner_home`).
    home, recorded = owner_home(), passwd_home()
    set_here = [
        name
        for name in IGNORED_ENV
        if context.env.get(name)
        and not (
            name == "XDG_CONFIG_HOME"
            and home is not None
            and _names_home_config(context.env[name], home)
        )
    ]
    differs = home is not None and recorded is not None and home.resolve() != recorded.resolve()
    if not set_here:
        return Row(OK, HOME_DIFFERS if differs else "no environment variable is being ignored")
    detail = (
        f"{listed(set_here)} is set and is not honoured: every command reads the machine "
        f"configuration at ~/.config/stayfixed/config.toml and nothing else, or the file --machine "
        f"names"
    )
    if differs:
        detail = f"{detail}; {HOME_DIFFERS}"
    return Row(OK, detail)


# The core's checks, in the order the `doctor` table in `docs/cli.md` lists them, ahead of every
# row an area contributes. The list is the report's order and the core's only registry: a check
# added here needs no other edit, and a check missing from it is a check nothing runs. An area adds
# rows after these through its own `doctor.py` (`registry.contributions`), never by an edit here.
CHECKS: tuple[tuple[str, Callable[[Context], Row]], ...] = (
    ("not-initialised", _not_initialised),
    ("versions", _versions),
    ("wrapper", _wrapper),
    ("budgets", configured(_budgets)),
    ("preferences", _preferences),
    ("cli-path", _cli_path),
    ("ci-ref", configured(_ci_ref)),
    ("diagnostics", _diagnostics),
    ("ignored-env", _ignored_env),
)


def _guarded(name: str, check: Callable[[Context], Row], context: Context) -> Check:
    """One check's answer, or a red row naming the exception type it died of.

    Never a traceback out of `run_checks`. The report is the thing the user has left when
    everything else is broken, so a check that raises costs one row and not the diagnosis — and
    the exception's *message* is not printed, because a `Failure` built out of `memory.groups`
    or a note's path is repository-authored, and a repository is untrusted input (principle 5).

    `Exception` and not `BaseException`: what was asked for is that a check which *raises*
    becomes a red row. `KeyboardInterrupt` and `SystemExit` are not that — catching them turns
    one `Ctrl-C` into a report of red rows, instead of stopping.

    **An `OSError` is a `warn` and everything else is a `red`, and the split is the point.**
    `red` is what gates the exit code, so a red row is a statement that this installation is
    wrong. A file that could not be opened is not that: the directories these checks read live
    on the machine, not in the installation — an unreadable `${CLAUDE_PLUGIN_DATA}` read as red
    would give `diagnostics: red` and exit 1 with nothing wrong anywhere. Every other exception
    is a defect in this module and keeps its red, because that is what the row is for.
    """
    try:
        row = check(context)
    except OSError as exc:  # the machine, not the installation
        return Check(
            name,
            WARN,
            f"this check could not read something it needed: {type(exc).__name__}",
            "check that the files and directories this check reads are readable here",
        )
    except Exception as exc:  # a broken check must cost one row, never the whole report
        return Check(name, RED, f"this check could not run: {type(exc).__name__}", REPORT_THIS)
    return Check(name, row.status, row.detail, row.remedy)


def _report_checks(
    contributed: list[Contribution],
) -> tuple[tuple[str, Callable[[Context], Row]], ...]:
    """The report's checks in the report's order: the core's, then each area's."""
    return CHECKS + tuple(check for contribution in contributed for check in contribution.checks)


def _context(
    root: Path,
    *,
    home: Path | None,
    machine: Path | None,
    runner: Runner,
    env: Mapping[str, str],
    session: SessionConfig,
) -> Context:
    """The report's `Context`, whole, with both plugin roots."""
    return Context(
        root,
        home,
        machine,
        runner,
        env,
        session.config,
        own_root=_own_root(),
        plugin_root=_named_root(env),
        session=session,
    )


def run_checks(
    root: Path,
    *,
    home: Path | None,
    machine: Path | None,
    runner: Runner,
    env: Mapping[str, str] | None = None,
) -> list[Check]:
    """One row per check, the core's and every area's, whatever state the machine is in.

    Four keyword parameters, which is the published signature. None chooses the interpreter the
    `wrapper` check's probe runs under: the wrapper takes the `python3` on `PATH`. A test fails
    the probe the way a machine does — with a plugin root whose launcher is not there.

    `env` defaults to the process environment because two checks are *about* the environment —
    `ignored-env` reads it, and `diagnostics` finds the harness data root in it.
    """
    env = os.environ if env is None else env
    # Every check is asked whatever the repository holds: the configuration is read the way a
    # session reads it (`config.session`), which never raises for anything the repository or the
    # machine file holds, so a repository with no `stayfixed.toml`, or one that does not load, has
    # every row the installation can answer, and a row that reads the project configuration skips
    # without one (`NO_CONFIG_SKIP`). The machine file is resolved once, the one no variable
    # moves, so every row that names it names the file that was read.
    read = machine_config_path() if machine is None else machine
    session = session_config(root, machine=read)
    contributed = contributions(CHECKS)
    context = _context(
        root,
        home=home,
        machine=machine,
        runner=runner,
        env=env,
        session=session,
    )
    return [_guarded(name, check, context) for name, check in _report_checks(contributed)]
