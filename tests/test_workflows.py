"""`ci.yml`, `smoke.yml` and `release.yml`, held to their shape and their steps run as the
scripts they are.

The repository carries no YAML parser, so each file is read by `tests.workflow_yaml`, one strict
reader that returns the whole document or fails naming the line it cannot read, and a step's
script is taken from it by `step_script` and run with `bash`.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

import pytest

from tests import plugintree, scriptload
from tests.floor import developer_free_environ
from tests.gitfixture import git, needs_git
from tests.test_fixtures import (
    CI_WORKFLOW,
    RELEASE_WORKFLOW,
    RELEASING,
    ROOT,
    SMOKE_WORKFLOW,
    needs_bash,
    needs_ci_workflow,
    needs_release_workflow,
    needs_smoke_workflow,
    step_script,
)
from tests.workflow_yaml import Node, load


def _document(workflow: Path) -> dict[str, Node]:
    """A workflow, read at call time (the sdist carries no `.github/`) by the strict reader."""
    document = load(workflow.read_text(encoding="utf-8"))
    assert isinstance(document, dict), workflow
    return document


def _jobs(workflow: Path) -> dict[str, dict[str, Node]]:
    """A workflow's jobs, every one a mapping."""
    jobs = _document(workflow).get("jobs")
    assert isinstance(jobs, dict) and all(isinstance(job, dict) for job in jobs.values()), workflow
    return {name: job for name, job in jobs.items() if isinstance(job, dict)}


def _job(workflow: Path, name: str) -> dict[str, Node]:
    """The named job of a workflow."""
    return _jobs(workflow)[name]


def _steps_of(workflow: Path, job: str) -> list[dict[str, Node]]:
    """The named job's steps, every one a mapping."""
    steps = _job(workflow, job).get("steps")
    assert isinstance(steps, list) and all(isinstance(step, dict) for step in steps), steps
    return [step for step in steps if isinstance(step, dict)]


def _name(step: dict[str, Node]) -> str:
    name = step.get("name") or step.get("uses")
    assert isinstance(name, str), step
    return name.split("@")[0]


def _code(line: str) -> str:
    """`line` up to its comment, if it has one: a `#` that begins a word outside quotes."""
    quote = ""
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def _lines(script: str) -> list[str]:
    """The script's commands as bash reads them, one to a line: a line continued with `\\` joined
    to the next, and indentation, blank lines and comment lines dropped. The one reader of a
    script's lines, so a case holding a script and a case finding a command in it read the same
    commands. A comment ends at its line whatever it ends with, so neither a comment line nor a
    command with a comment after it continues onto the next line when the comment ends in `\\`;
    a comment line after a continued one is the end of that command, as bash reads it, and is
    kept with it. Quotes are read within a line only, which is all these workflows write."""
    lines: list[str] = []
    pending = ""
    for raw in script.splitlines():
        bare = raw.strip()
        line = f"{pending} {bare}" if pending else bare
        pending = ""
        if not line or line.startswith("#"):
            continue
        if _code(raw).endswith("\\"):
            pending = line[:-1].rstrip()
        else:
            lines.append(line)
    if pending:
        lines.append(pending)
    return lines


def _demanded_summary(step_name: str, output: str) -> str:
    """The one line the named smoke step's `grep -qx` demands of the script output it saved."""
    script = step_script(SMOKE_WORKFLOW, step_name)
    pattern = rf'^\s*grep -qx "([^"]*)" "\$RUNNER_TEMP/{re.escape(output)}"$'
    found = re.findall(pattern, script, re.MULTILINE)
    assert len(found) == 1, script
    return str(found[0])


@needs_smoke_workflow
def test_the_smoke_job_demands_the_summary_the_hook_script_prints_over_every_entry() -> None:
    # Each smoke script holds its own floor in constants and prints a summary that is green after
    # one row as after all of them; the job's `grep -qx` is the CI side of that floor, and a copy
    # of the counts written by hand stays behind when an entry is added or removed — the job then
    # fails on every pull request while the script and the suite agree. So the line is derived
    # from the script's constants; `tests/scripts/test_smoke_scripts.py` holds that a run prints
    # it. Mutation (declared, `mutations/`'s "the smoke job demands a hook summary the script no
    # longer prints").
    smoke = scriptload.load(scriptload.SCRIPTS / "smoke_hooks.py", "smoke_hooks")
    expected = f"{smoke.EXPECTED_ENTRIES} entries, {smoke.EXPECTED_ROWS} row(s), 0 failure(s)"
    step = "Every hook entry, fed its sample event through the installed wrapper"
    assert _demanded_summary(step, "hooks.out") == expected


@needs_smoke_workflow
def test_the_smoke_job_demands_the_summary_the_exfiltration_scenario_prints_over_every_row() -> (
    None
):
    # The same derivation for the other script. Mutation (declared, `mutations/`'s "the smoke job
    # demands an exfiltration summary the scenario no longer prints").
    exfil = scriptload.load(scriptload.SCRIPTS / "smoke_exfiltration.py", "smoke_exfiltration")
    expected = f"{exfil.EXPECTED_ROWS} row(s), 0 failure(s)"
    assert _demanded_summary("The clone-to-exfiltration scenario", "hostile.out") == expected


@pytest.mark.parametrize(
    ("script", "commands"),
    [
        # A continued line is one command with the line after it.
        ("a \\\n  --b c\n", ["a --b c"]),
        # A backslash followed by a space escapes the space and continues nothing.
        ("a \\ \nb\n", ["a \\", "b"]),
        # A comment ends at its line, whatever it ends with: neither a comment line nor a command
        # carrying a comment after it continues onto the next line.
        ("# note \\\nb\n", ["b"]),
        ("a # note \\\nb\n", ["a # note \\", "b"]),
        # A `#` inside quotes, or inside a word, begins no comment.
        ("echo '# not' \\\n  b\n", ["echo '# not' b"]),
        ('echo "x #y" \\\n  b\n', ['echo "x #y" b']),
        ("echo a#b \\\n  c\n", ["echo a#b c"]),
        # A comment line after a continued one ends that command, as bash reads it.
        ("a \\\n  # note\nb\n", ["a # note", "b"]),
        # A backslash escapes a double quote inside double quotes, so the quote goes on and the
        # `#` after it is still quoted.
        ('echo "a \\" #b" \\\n  c\n', ['echo "a \\" #b" c']),
    ],
    ids=[
        "continued",
        "escaped-space",
        "comment-line",
        "trailing-comment",
        "single-quoted",
        "double-quoted",
        "inside-a-word",
        "comment-after-continued",
        "escaped-quote",
    ],
)
def test_the_line_reader_reads_commands_as_bash_does(script: str, commands: list[str]) -> None:
    # Every case that holds a workflow script or finds a command in one reads it through
    # `_lines`, so a reader that joined a command onto a comment would hide the command from
    # all of them. Mutations (oracle): `mutations/`'s "the workflow line reader continues a line
    # whose comment ends in a backslash" and "the workflow line reader ends a quote at an escaped
    # quote".
    assert _lines(script) == commands


# --- The plugin tree the workflows validate, install and attest -------------------------------
#
# The directory reads the plugin repository's commit, and that commit's root is the tree
# `scripts/plugin_tree.py render` writes, not this checkout, whose root also holds the tests, the
# plans and the tooling. So every job that judges the plugin judges a render: `ci.yml`'s
# validator, `smoke.yml`'s install and `release.yml`'s attestation. A job pointed back at the
# checkout stays green over a tree no user installs, so each case below is about where a job reads
# from, not whether it runs.

RENDER = "uv run python scripts/plugin_tree.py render"


def _run(step: dict[str, Node]) -> str:
    script = step.get("run")
    return script if isinstance(script, str) else ""


def _options(line: str) -> dict[str, str]:
    """Each `--option value` on a command line, its value unquoted as the shell would and its
    variables left as written."""
    return {word: value for word, value in pairwise(shlex.split(line)) if word.startswith("--")}


def _uses(step: dict[str, Node]) -> str:
    uses = step.get("uses")
    return uses.split("@")[0] if isinstance(uses, str) else ""


def _with(step: dict[str, Node], key: str) -> str:
    """An action input, with `${{ runner.temp }}` read as the `$RUNNER_TEMP` a script names."""
    given = step.get("with")
    assert isinstance(given, dict) and isinstance(given.get(key), str), step
    return str(given[key]).replace("${{ runner.temp }}", "$RUNNER_TEMP")


def _tree_command(workflow: Path, job: str, command: str) -> tuple[int, str]:
    """The one command of `job` that runs `scripts/plugin_tree.py <command>`: its step's index and
    the command line."""
    found = [
        (index, line)
        for index, step in enumerate(_steps_of(workflow, job))
        for line in _lines(_run(step))
        if f"scripts/plugin_tree.py {command} " in line
    ]
    assert len(found) == 1, (workflow.name, job, command, found)
    return found[0]


def _render_step(workflow: Path, job: str) -> tuple[int, dict[str, str]]:
    """The one step of `job` that renders the plugin tree: its index and its options."""
    index, line = _tree_command(workflow, job, "render")
    assert line.startswith(RENDER), line
    return index, _options(line)


def _install_id() -> str:
    """The id of the smoke step that installs the plugin, whose `root` output names the tree."""
    install = [
        step
        for step in _steps_of(SMOKE_WORKFLOW, "installed-plugin")
        if "claude plugin install" in _run(step)
    ]
    assert len(install) == 1, install
    ident = install[0].get("id")
    assert isinstance(ident, str) and "root=$root" in _run(install[0]), install[0]
    return ident


@needs_smoke_workflow
def test_the_smoke_installs_the_rendered_tree_and_never_the_checkout() -> None:
    # The install is the smoke's subject: every later step runs hooks, `doctor` and the
    # exfiltration scenario from what it installed. This repository's catalog names the plugin
    # repository by a `url` source, so adding the checkout as the marketplace fetches the
    # published tag over the network, or fails while there is none: either way the smoke judges
    # no tree this change wrote. This keeps it off the network and off any tree published before.
    # An allowlist rather than a list of bad spellings: `"$PWD"`, `${PWD}`, `$(pwd)`, `.`, `./`
    # and `$GITHUB_WORKSPACE` each name the checkout, and only a directory under the runner's
    # temporary directory, which the job writes from the render, passes. Mutation (oracle):
    # `mutations/`'s "the smoke installs the checkout again" puts back
    # `claude plugin marketplace add "$PWD"`.
    _, render = _render_step(SMOKE_WORKFLOW, "installed-plugin")
    # Mutation (oracle): `mutations/`'s "the smoke installs a render of another commit" renders
    # `HEAD^`.
    assert render["--rev"] == "HEAD", render
    # Mutation (declared): `--out "$PWD/plugin-repo"` renders into the checkout and reddens here.
    assert render["--out"].startswith("$RUNNER_TEMP/"), render
    text = "\n".join(_run(step) for step in _steps_of(SMOKE_WORKFLOW, "installed-plugin"))
    added = re.findall(r"claude plugin marketplace add\s+(\S+)", text)
    # The walk first: no `marketplace add` at all would satisfy the loop below by having nothing.
    assert added, text
    for argument in added:
        assert argument.startswith('"$RUNNER_TEMP/'), added


@needs_smoke_workflow
def test_the_smoke_runs_doctor_from_the_installed_tree() -> None:
    # `doctor` judges the checkout it was imported from (`_own_root`), and `PYTHONPATH: src`
    # imports it from this checkout, so the step reported on the repository and not on the
    # install: a runtime path the render omits would pass it. Mutation (oracle): `mutations/`'s
    # "the smoke's doctor imports the checkout again" puts back `PYTHONPATH: src`.
    doctor = [
        step
        for step in _steps_of(SMOKE_WORKFLOW, "installed-plugin")
        if "-m drybag doctor" in _run(step)
    ]
    assert len(doctor) == 1, doctor
    env = doctor[0].get("env")
    assert isinstance(env, dict), doctor[0]
    assert env.get("PYTHONPATH") == "${{ steps." + _install_id() + ".outputs.root }}/src", env


@needs_smoke_workflow
@pytest.mark.parametrize("script", ["smoke_hooks.py", "smoke_exfiltration.py"])
def test_the_smoke_runs_its_hook_and_exfiltration_scripts_on_the_installed_tree(
    script: str,
) -> None:
    # Each script runs the hook entries it finds under `--plugin-root`, so a root of `.` runs this
    # checkout's hooks and the step passes over a runtime path the render omitted. Mutations
    # (oracle): `mutations/`'s "the smoke's hook entries run from the checkout" and "the smoke's
    # exfiltration scenario runs from the checkout" each put `--plugin-root .` back in one step;
    # `mutations/`'s "the smoke's hook entries take the checkout as the installed tree" and
    # "the smoke's exfiltration scenario takes the checkout as the installed tree" each point that
    # step's `INSTALLED` at `${{ github.workspace }}`.
    invoked = [
        (step, line)
        for step in _steps_of(SMOKE_WORKFLOW, "installed-plugin")
        for line in _lines(_run(step))
        if line.startswith(f"python3 scripts/{script} ")
    ]
    assert len(invoked) == 1, invoked
    step, line = invoked[0]
    roots = re.findall(r"--plugin-root (\S+)", line)
    assert roots == ['"$INSTALLED"'], line
    env = step.get("env")
    assert isinstance(env, dict), step
    assert env.get("INSTALLED") == "${{ steps." + _install_id() + ".outputs.root }}", env


@needs_smoke_workflow
def test_the_smoke_holds_the_install_to_the_render() -> None:
    # The harness copies what the marketplace's source names into its cache, and only a
    # comparison can say it copied all of it and added nothing: the hooks, `doctor` and the
    # scenario read some of the tree, and the skills, the agents, `README.md` and `LICENSE` have
    # no reader in this job. The step compares the render, by the `--out` it was written to,
    # against the installed root, by the install's own output. Mutation (oracle): `mutations/`'s
    # "the smoke stops holding the install to the render" replaces the step's `run:` with `"true"`.
    _, render = _render_step(SMOKE_WORKFLOW, "installed-plugin")
    # Each exclusion by name: `.git` is the render's repository, `.in_use` the harness's marker
    # (measured; the step's comment carries it). A pattern here would hide a plugin file.
    wanted = f'diff -r -x .git -x .in_use "{render["--out"]}" "$INSTALLED"'
    holding = [
        step
        for step in _steps_of(SMOKE_WORKFLOW, "installed-plugin")
        if wanted in _lines(_run(step))
    ]
    assert len(holding) == 1, wanted
    env = holding[0].get("env")
    assert isinstance(env, dict), holding[0]
    # Mutation (declared): `INSTALLED: ${{ runner.temp }}/plugin-repo` compares the render with
    # itself, always equal, and reddens here.
    assert env.get("INSTALLED") == "${{ steps." + _install_id() + ".outputs.root }}", env


@needs_ci_workflow
def test_the_validator_reads_the_rendered_manifests() -> None:
    # The validator judges the two manifests the plugin repository's root will hold, so it reads
    # them out of the render; the marketplace is this repository's catalog and is read where it
    # is, which validation does without fetching the source it names. An equality and not a
    # prefix test, so a manifest dropped from the step reddens as well. Mutation (oracle):
    # `mutations/`'s "the validator reads the checkout's manifest again" validates
    # `.claude-plugin/plugin.json`.
    _, render = _render_step(CI_WORKFLOW, "plugin")
    # Mutation (oracle): `mutations/`'s "the validator reads a render of another commit" renders
    # `HEAD^`.
    assert render["--rev"] == "HEAD", render
    validated: list[str] = []
    for step in _steps_of(CI_WORKFLOW, "plugin"):
        for line in _lines(_run(step)):
            words = shlex.split(line)
            if words[:3] == ["claude", "plugin", "validate"]:
                validated.extend(word for word in words[3:] if not word.startswith("--"))
    manifests = sorted(path for path in validated if path.endswith("plugin.json"))
    out = render["--out"]
    assert manifests == [f"{out}/.claude-plugin/plugin.json", f"{out}/.codex-plugin/plugin.json"]
    # Mutation (oracle): `mutations/`'s "the validator stops reading this repository's catalog"
    # drops its line.
    assert ".claude-plugin/marketplace.json" in validated, validated


@needs_release_workflow
def test_the_release_attests_the_plugin_tree_it_rendered_from_the_commit() -> None:
    # The `attest` job computes the plugin commit of the commit this run builds, writes the
    # manifest of its tree beside it, and attests that manifest at the same pinned action as
    # `dist/*`; `github-release` attaches it, so anyone can compare the plugin repository's tag
    # with the file this run attested. Mutation (oracle): `mutations/`'s "the release stops
    # attesting the plugin tree" points that attestation step at `dist/*`.
    #
    # `--rev "$GITHUB_SHA"` is a text pin with no behavioural mutation: on a tag push `HEAD` is
    # that commit, so a commit of `HEAD` is the same commit and no run can tell them apart. It is
    # pinned because `GITHUB_SHA` is the attestation's source digest, and the commit read, that
    # digest and the commit the publisher checks are then one value by construction.
    index, line = _tree_command(RELEASE_WORKFLOW, "attest", "commit")
    # The runner's own interpreter, and no `uv`: the job runs no suite and installs nothing.
    # Mutation (declared): `uv run python scripts/plugin_tree.py commit …` reddens here and in
    # `test_only_the_attest_job_can_attest`.
    assert line.startswith("python3 scripts/plugin_tree.py commit "), line
    options = _options(line)
    assert options["--rev"] == "$GITHUB_SHA", options
    written = options["--manifest-file"]
    steps = _steps_of(RELEASE_WORKFLOW, "attest")
    attests = [step for step in steps if _uses(step) == "actions/attest-build-provenance"]
    subjects = {_with(step, "subject-path"): steps.index(step) for step in attests}
    # The manifest is attested after it is written; `dist/*` keeps its own step, at the same pin
    # (dropping it, or moving one pin, reddens the two lines below: they are this case's walk).
    assert subjects.get(written, -1) > index, (written, subjects)
    packages = "$RUNNER_TEMP/dist/*"
    assert packages in subjects, subjects
    assert len({step.get("uses") for step in attests}) == 1, attests
    # And `dist/*` is the one `build` uploaded, fetched before it is attested, and fetched outside
    # the checkout: `build` ran the suite and the lock's dependencies, and this job runs the
    # checkout's script with its `src` on the path and can sign. Mutation (declared): the `dist`
    # download dropped, and the attestation names no file; reddens here. Mutation (declared):
    # `mutations/`'s "the attest job downloads build's packages into its checkout" -> the
    # download's path is `dist/` again.
    fetched = [
        index
        for index, step in enumerate(steps)
        if _uses(step) == "actions/download-artifact" and _with(step, "name") == "dist"
    ]
    assert len(fetched) == 1 and fetched[0] < subjects[packages], (fetched, subjects)
    assert _with(steps[fetched[0]], "path") == "$RUNNER_TEMP/dist", steps[fetched[0]]
    # Handed to `github-release` as the artifact `plugin-tree`, which attaches it beside
    # `dist/*`. Mutation (oracle): `mutations/`'s "the Release stops carrying the plugin's
    # manifest" drops it from `gh release create`.
    uploads = [
        step
        for step in steps
        if _uses(step) == "actions/upload-artifact" and _with(step, "name") == "plugin-tree"
    ]
    # Mutation (declared): the upload's path names the plugin repository, `${{ runner.temp
    # }}/plugin.git`, and not the manifest, and reddens here.
    assert [_with(step, "path") for step in uploads] == [written], uploads
    # The action only warns when its path matches nothing, and the release then stops at
    # `github-release`, behind the approval. Mutation (oracle): `mutations/`'s "a missing plugin
    # manifest uploads as a warning".
    assert [_with(step, "if-no-files-found") for step in uploads] == ["error"], uploads
    released = _steps_of(RELEASE_WORKFLOW, "github-release")
    downloads = [
        _with(step, "path")
        for step in released
        if _uses(step) == "actions/download-artifact" and _with(step, "name") == "plugin-tree"
    ]
    # Mutation (declared): drop the `plugin-tree` download, and the Release would attach a file
    # nothing fetched; reddens here.
    assert len(downloads) == 1, downloads
    creates = [
        shlex.split(line)
        for step in released
        for line in _lines(_run(step))
        if line.startswith("gh release create ")
    ]
    assert len(creates) == 1, creates
    assert f"{downloads[0]}/{Path(written).name}" in creates[0], creates[0]


# --- The release's plugin commit: computed, attested and gated on ------------------------------
#
# The marketplace entry pins the plugin repository's commit by `sha`, and that commit is a function
# of the release commit alone, so the release workflow can compute it with no credential and no
# network: `attest` computes it, refuses a release commit whose pin is not it (`--require-pin`),
# attests its manifest and hands the id on; the two jobs behind the `pypi` approval each refuse
# to start until the plugin repository's tag names that id, which only the owner's run of
# `scripts/publish_plugin.py` can make true.

GATED = ("publish", "github-release")
PLUGIN_GATE = "The plugin repository holds this release's commit"
# The plugin repository, as every reader of it must name it.
PLUGIN_REPOSITORY = "dry-bag/drybag-plugin"
TAG = "v1.2.3"


@needs_release_workflow
@pytest.mark.parametrize("job", ["build", "attest"])
def test_build_fetches_the_first_parent(job: str) -> None:
    # `release.py check --tag` and the plugin commit both read the `sha` the release commit's
    # first parent pins, as the commit's parent; `actions/checkout` fetches one commit unless told
    # otherwise, and the reader then refuses, naming `fetch-depth: 2`, rather than read the parent
    # as none. Mutations (oracle): `mutations/`'s "the release build fetches the tag's commit
    # alone" and "the attest job fetches the tag's commit alone" drop `fetch-depth: 2` from each.
    checkouts = [
        step for step in _steps_of(RELEASE_WORKFLOW, job) if _uses(step) == "actions/checkout"
    ]
    # The walk's count, so the line below reads a checkout: no mutation, it guards the case.
    assert len(checkouts) == 1, checkouts
    assert _with(checkouts[0], "fetch-depth") == "2", checkouts[0]


@needs_release_workflow
def test_only_the_attest_job_can_attest() -> None:
    # An attestation is signed with the job's OIDC token, so a job holding `id-token: write` and
    # running the suite runs every test, and every dependency the lock installs, with the means to
    # sign. The suite stays in `build`, which holds `contents: read` and nothing else, and the
    # job that signs runs this repository's own script on the runner's interpreter and installs
    # nothing. `publish` holds `id-token: write` too, for Trusted Publishing, and attests nothing.
    # Mutations (oracle): `mutations/`'s "the release build can sign again" -> `id-token: write`
    # on `build`; "the attest job can write the repository" -> `contents: write` on `attest`; "the
    # Release job can sign" -> `id-token: write` on `github-release`; and "the environment gate
    # can record attestations" -> `attestations: write` on `environment-gate`.
    jobs = _jobs(RELEASE_WORKFLOW)
    attesting = sorted(
        name
        for name in jobs
        for step in _steps_of(RELEASE_WORKFLOW, name)
        if _uses(step) == "actions/attest-build-provenance"
    )
    assert attesting == ["attest", "attest"], attesting
    granted = {name: job.get("permissions") for name, job in jobs.items()}
    assert granted["build"] == {"contents": "read"}, granted["build"]
    assert granted["attest"] == {
        "id-token": "write",
        "attestations": "write",
        "contents": "read",
    }, granted["attest"]
    signing = sorted(
        name for name, given in granted.items() if isinstance(given, dict) and "id-token" in given
    )
    assert signing == ["attest", "publish"], granted
    recording = sorted(
        name
        for name, given in granted.items()
        if isinstance(given, dict) and "attestations" in given
    )
    assert recording == ["attest"], granted
    steps = _steps_of(RELEASE_WORKFLOW, "attest")
    # Installs nothing: its steps are these and no others, each action by name and the one script
    # by its step's name, so an installer of any kind added reddens, not only the one a list of
    # installers would name. Mutations (oracle): `mutations/`'s "the attest job installs uv" and
    # "the attest job sets up another interpreter".
    shapes = [_uses(step) or step.get("name") for step in steps]
    assert shapes == [
        "actions/checkout",
        "actions/download-artifact",
        "The plugin commit of the commit this run builds",
        "actions/attest-build-provenance",
        "actions/attest-build-provenance",
        "actions/upload-artifact",
    ], shapes
    # And that one script runs no suite. Mutation (oracle): `mutations/`'s "the attest job runs
    # the suite".
    running = [
        line
        for step in steps
        for line in _lines(_run(step))
        if re.search(r"(?<![\w.-])(uv|pytest)(?![\w.-])", line)
    ]
    assert running == [], running


@needs_release_workflow
def test_no_checkout_in_the_release_keeps_its_token() -> None:
    # `actions/checkout` writes the job's token into `.git/config` unless told not to, where every
    # later step of the job can read it, and no step of the release needs it there: `build` runs
    # the suite and pushes nothing, `attest` runs a script, and `github-release` authenticates `gh`
    # with `GH_TOKEN`. Held for every checkout rather than for the jobs judged able to write, so a
    # `permissions: write-all`, or a job inheriting a widened top-level block, is held too.
    # Mutations (oracle): `mutations/`'s "the release build keeps a token in its checkout", "the
    # attest job keeps a token in its checkout" and "the Release job keeps a token in its
    # checkout".
    checkouts = {
        name: [
            step for step in _steps_of(RELEASE_WORKFLOW, name) if _uses(step) == "actions/checkout"
        ]
        for name in _jobs(RELEASE_WORKFLOW)
    }
    # The walk's count, so the loop reads every checkout there is.
    assert {name: len(found) for name, found in checkouts.items() if found} == {
        "build": 1,
        "attest": 1,
        "github-release": 1,
    }, checkouts
    for name, found in checkouts.items():
        for checkout in found:
            assert _with(checkout, "persist-credentials") == "false", (name, checkout)


def _outputs(path: Path) -> dict[str, str]:
    """What a step wrote to `$GITHUB_OUTPUT`, as `key=value` lines."""
    if not path.is_file():
        return {}
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


def _interpreters(tmp_path: Path) -> Path:
    """A directory putting this interpreter on `PATH` as `python3` and `python`: a script that runs
    it by its own path, since a link elsewhere is an interpreter outside its environment."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    for name in ("python3", "python"):
        (stub / name).write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
        (stub / name).chmod(0o755)
    return stub


def _run_step(
    script: str, cwd: Path, stub: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """A step's script under `bash -e`, the runner's default shell, with `stub` first on `PATH`."""
    environ = developer_free_environ()
    return subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**environ, "PATH": f"{stub}:{environ.get('PATH', '/usr/bin:/bin')}", **env},
    )


def _attest(tmp_path: Path, source: Path) -> tuple[subprocess.CompletedProcess[str], str | None]:
    """The `attest` job's commit step, run on `source`'s `HEAD`: what it did, and the `commit`
    it handed on."""
    index, _ = _tree_command(RELEASE_WORKFLOW, "attest", "commit")
    step = _steps_of(RELEASE_WORKFLOW, "attest")[index]
    env = step.get("env")
    # The runner's interpreter has no `drybag` but the checkout's `src`; this one has its own
    # through its environment, so the run below cannot tell, and only this pin holds it.
    # Mutation (oracle): `mutations/`'s "the attest job runs the plugin script without the
    # checkout's package".
    assert env == {"PYTHONPATH": "src"}, env
    temp = tmp_path / "runner"
    temp.mkdir(parents=True)
    output = temp / "output"
    done = _run_step(
        _run(step),
        source,
        _interpreters(tmp_path),
        {
            "PYTHONPATH": str(env["PYTHONPATH"]),
            "RUNNER_TEMP": str(temp),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_SHA": git(source, "rev-parse", "HEAD").strip(),
        },
    )
    return done, _outputs(output).get("commit")


@needs_git
@needs_bash
@needs_release_workflow
def test_the_attest_job_hands_on_the_commit_its_source_pins(tmp_path: Path) -> None:
    # The gated jobs compare the plugin repository's tag with what `attest` hands on, so `attest`
    # hands on the commit the release commit's tree makes, and only when the release commit pins
    # that commit: a release commit pinning another fails here, before any approval is asked for.
    # The id is computed by git from the source's tree, never by the script. Mutations (oracle):
    # `mutations/`'s "the attest job hands on a commit the release commit does not pin" -> no
    # `--require-pin`; and "the attest job writes the commit under another name" -> nothing handed
    # on.
    source = plugintree.tool_source(tmp_path)
    expected = plugintree.hashed(
        source, plugintree.literal(plugintree.plugin_tree_id(source), None)
    )
    # The fixture's own premise, that its release commit pins that commit: no mutation, the
    # workflow is not read here.
    assert plugintree.pinned_at(source) == expected
    done, handed = _attest(tmp_path / "pinned", source)
    assert done.returncode == 0, done.stdout + done.stderr
    assert handed == expected
    # A release commit on top of it whose marketplace pins a commit no tree makes.
    plugintree.write(source, {plugintree.MARKETPLACE: plugintree.pinned_marketplace("f" * 40)})
    plugintree.commit(source, "a release commit pinning another commit")
    done, handed = _attest(tmp_path / "unpinned", source)
    assert done.returncode != 0, done.stdout + done.stderr
    assert handed is None
    # And the job says why: `--json` writes the refusal's sentence into the file the step reads,
    # so the step prints the file when the script fails, or the job that signs stops with an exit
    # code alone. Mutation (oracle): `mutations/`'s "the attest job hides why it computed no
    # commit".
    assert f"pins {'f' * 40}, and the plugin commit its tree makes is " in done.stderr, done.stderr


@needs_release_workflow
def test_the_gated_jobs_refuse_until_the_plugin_tag_names_the_pin() -> None:
    # Every job behind the `pypi` approval starts by asking the plugin repository whether its tag
    # names the commit `attest` computed: the step is first, before any checkout or download, so a
    # job whose plugin is not published yet does nothing irreversible, and it is in each gated job
    # rather than a job of its own, which would ask for a second approval. Its two values arrive
    # through `env:`, and the step holds no credential. Mutation (declared): the step moved after
    # `github-release`'s checkout; reddens here, at its name.
    jobs = _jobs(RELEASE_WORKFLOW)
    gated = sorted(name for name, job in jobs.items() if "environment" in job)
    # The walk's set, so the loop below reads both jobs: a third gated job reddens here and is
    # then held by the loop.
    assert gated == sorted(GATED), gated
    # `attest` hands on the id its commit step wrote, by that step's own id. Mutation (oracle):
    # `mutations/`'s "the attest job hands on another step's output".
    index, _ = _tree_command(RELEASE_WORKFLOW, "attest", "commit")
    ident = _steps_of(RELEASE_WORKFLOW, "attest")[index].get("id")
    assert isinstance(ident, str), ident
    assert jobs["attest"].get("outputs") == {"commit": "${{ steps." + ident + ".outputs.commit }}"}
    first = [_steps_of(RELEASE_WORKFLOW, name)[0] for name in GATED]
    # A job that does not wait for `attest` reads its output as empty, and a step reading
    # another job's output fails only at a release; these are held here, before one. Mutations
    # (oracle): `mutations/`'s "publish starts before attest finished", "the plugin gate reads the
    # commit build hands on" and "the plugin gate may fail and the job go on".
    for name, step in zip(GATED, first, strict=True):
        assert jobs[name].get("needs") == ["build", "environment-gate", "attest"], jobs[name]
        assert list(step) == ["name", "env", "run"], (name, step)
        assert step["name"] == PLUGIN_GATE, (name, step)
        assert step["env"] == {
            "TAG": "${{ github.ref_name }}",
            "PINNED": "${{ needs.attest.outputs.commit }}",
        }, (name, step)
    # One step, twice: a copy that drifted would gate one job on another question. Mutation
    # (oracle): `mutations/`'s "github-release's plugin gate drifts from publish's".
    assert first[0] == first[1], first


def _gate(
    tmp_path: Path, job: str, listing: list[tuple[str, str]] | None, pinned: str
) -> tuple[int, str, list[str]]:
    """The gated step's script, out of `job`, against a `git` whose `ls-remote` prints `listing`
    (or fails, for `None`): its exit status, what it printed, and the arguments `git` was given."""
    script = _run(_steps_of(RELEASE_WORKFLOW, job)[0])
    assert script and "${{" not in script, script
    stub = tmp_path / "bin"
    stub.mkdir()
    answer, asked = tmp_path / "listing", tmp_path / "asked"
    if listing is None:
        printed = 'echo "fatal: unable to access the repository" >&2\nexit 128\n'
    else:
        answer.write_text("".join(f"{sha}\t{ref}\n" for sha, ref in listing), encoding="utf-8")
        printed = f'cat "{answer}"\n'
    (stub / "git").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{asked}"\n{printed}')
    (stub / "git").chmod(0o755)
    done = subprocess.run(
        ["bash", "-e", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{stub}:/usr/bin:/bin", "TAG": TAG, "PINNED": pinned},
    )
    given = asked.read_text(encoding="utf-8").splitlines() if asked.is_file() else []
    return done.returncode, done.stdout + done.stderr, given


COMMIT, TAG_OBJECT, OTHER = "c" * 40, "d" * 40, "e" * 40
TAG_REF, PEELED_REF = f"refs/tags/{TAG}", f"refs/tags/{TAG}^{{}}"
# `ls-remote` matches a pattern against the tail of each ref name, so the two patterns also list
# `refs/tags/x/refs/tags/v1.2.3`, and its `^{}` line when it is annotated (measured, git 2.54).
DECOY_REF, DECOY_PEELED_REF = f"refs/tags/x/{TAG_REF}", f"refs/tags/x/{PEELED_REF}"


@needs_bash
@needs_release_workflow
@pytest.mark.parametrize("job", GATED)
@pytest.mark.parametrize(
    ("listing", "pinned", "code"),
    [
        # An annotated tag: the `^{}` line is the commit, the tag line the tag object.
        ([(TAG_OBJECT, TAG_REF), (COMMIT, PEELED_REF)], COMMIT, 0),
        ([(TAG_OBJECT, TAG_REF), (COMMIT, PEELED_REF)], TAG_OBJECT, 1),
        # A lightweight tag: the tag line is the commit, and there is no `^{}` line.
        ([(COMMIT, TAG_REF)], COMMIT, 0),
        ([(OTHER, TAG_REF)], COMMIT, 1),
        # Another tag whose name ends in this one's, naming the pinned commit, beside the real one.
        ([(OTHER, TAG_REF), (COMMIT, DECOY_REF)], COMMIT, 1),
        ([(OTHER, TAG_REF), (TAG_OBJECT, DECOY_REF), (COMMIT, DECOY_PEELED_REF)], COMMIT, 1),
        # No such tag yet: the plugin is not published.
        ([], COMMIT, 1),
        # `attest` handed on nothing, and nothing is listed: two empty strings are not a match.
        # Mutation (oracle): `mutations/`'s "the plugin gate takes an empty pin for a match".
        ([], "", 1),
        # The plugin repository could not be listed.
        (None, COMMIT, 1),
    ],
    ids=[
        "annotated",
        "annotated-tag-object",
        "lightweight",
        "lightweight-other",
        "decoy",
        "decoy-annotated",
        "absent",
        "nothing-pinned",
        "unreachable",
    ],
)
def test_the_gated_step_compares_the_peeled_id(
    tmp_path: Path, job: str, listing: list[tuple[str, str]] | None, pinned: str, code: int
) -> None:
    # The tag the publisher pushes is annotated or not, and either way what it names is the
    # commit: the `^{}` line's id when there is one, the tag line's otherwise, each selected by its
    # whole ref name. Mutations (oracle): `mutations/`'s "the plugin gate compares the tag object
    # of an annotated tag" and "the plugin gate selects the tag by the tail of its name".
    got, printed, given = _gate(tmp_path, job, listing, pinned)
    assert got == code, (got, printed)
    # One listing, of the plugin repository, by both of the tag's exact names.
    assert given == [
        "ls-remote",
        f"https://github.com/{PLUGIN_REPOSITORY}.git",
        TAG_REF,
        PEELED_REF,
    ], given
    # A refusal says what to do. Mutation (declared): the message stops naming the step of
    # `RELEASING.md` that publishes the plugin; reddens here on every refusing case.
    if code:
        assert "::error::" in printed and "RELEASING.md section 2, step 7" in printed, printed


def _github_repository(url: str) -> str:
    """`owner/name` out of a GitHub clone URL, over HTTPS or SSH."""
    found = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+)\.git", url)
    assert found is not None, url
    return found.group(1)


# The shape of a plugin commit id, as every reader of one spells it.
SHA1_PATTERN = "[0-9a-f]{40}"


def _pattern(value: object) -> str:
    """A pattern constant's text, whether the script compiled it or not; compiled, with no flag
    beyond the `UNICODE` every text pattern carries."""
    if isinstance(value, re.Pattern):
        assert value.flags == re.UNICODE, (value, value.flags)
    pattern = value.pattern if isinstance(value, re.Pattern) else value
    assert isinstance(pattern, str), value
    return pattern


@needs_release_workflow
@needs_smoke_workflow
def test_one_commit_id_shape_everywhere() -> None:
    # A `sha` is 40 lowercase hex characters, and each reader spells that itself: the scripts may
    # not import one another, and a workflow cannot import at all. `plugin_tree.py` checks the
    # pin it reads, `release.py` the entry it checks and writes, `publish_plugin.py` the ids it
    # is given, and the workflows the id `plugin_tree.py commit` printed and the id `attest`
    # handed on. Each copy is read from its own file and held to one spelling; a workflow's as
    # the whole of a bash `=~` pattern. The two workflow checks of the id `plugin_tree.py
    # commit` printed (`attest`'s and the smoke's) are reached by no test, because the script
    # prints no other shape; the gated steps' copy is run by
    # `test_the_gated_step_compares_the_peeled_id`'s `nothing-pinned` case. Mutation (oracle):
    # `mutations/`'s "the smoke checks the plugin commit's shape by another pattern". The
    # scripts' copies by their text and, compiled, by their flags, since `IGNORECASE` takes an
    # upper-case id the text refuses. Mutations (oracle): `mutations/`'s "the publisher spells
    # the commit id's shape another way than its siblings" and "the plugin tree compiles the
    # commit id's shape to ignore case".
    scripts = {
        "plugin_tree.py SHA1": _pattern(scriptload.plugin_tree().SHA1),
        "release.py SHA1": _pattern(scriptload.release().SHA1),
        "publish_plugin.py SHA1": _pattern(scriptload.publish_plugin().SHA1),
    }
    assert set(scripts.values()) == {SHA1_PATTERN}, scripts
    checks = {
        workflow.name: re.findall(r"\[\[ \S+ =~ (\S+) \]\]", workflow.read_text(encoding="utf-8"))
        for workflow in (RELEASE_WORKFLOW, SMOKE_WORKFLOW)
    }
    # `attest`'s, one in each gated job, and the smoke's: four, so the walk read something.
    assert {name: len(found) for name, found in checks.items()} == {
        "release.yml": 3,
        "smoke.yml": 1,
    }, checks
    for found in checks.values():
        assert set(found) == {f"^{SHA1_PATTERN}$"}, checks
    # The two other constants `plugin_tree.py` and the publisher each spell: the manifest's first
    # line, which the one writes and the other compares, and a full object name of either hash,
    # which each holds a git answer to. Mutations (oracle): `mutations/`'s "the publisher reads
    # another manifest format than plugin_tree.py writes", "plugin_tree.py writes another manifest
    # format than the publisher reads", "the publisher takes no 64-character object name for one"
    # and "the plugin tree takes no 64-character object name for one".
    tree, publisher = scriptload.plugin_tree(), scriptload.publish_plugin()
    formats = {"plugin_tree.py FORMAT": tree.FORMAT, "publish_plugin.py FORMAT": publisher.FORMAT}
    assert set(formats.values()) == {"drybag-plugin-tree 1"}, formats
    names = {
        "plugin_tree.py OBJECT_NAME": _pattern(tree.OBJECT_NAME),
        "publish_plugin.py OBJECT_NAME": _pattern(publisher.OBJECT_NAME),
    }
    assert set(names.values()) == {"[0-9a-f]{40}|[0-9a-f]{64}"}, names


@needs_release_workflow
def test_one_plugin_repository_everywhere() -> None:
    # The scripts may not import one another, so each spells the plugin repository itself: the
    # release check holds the marketplace entry's `url` to `release.py`'s `PLUGIN_URL`, the
    # publisher pushes to `PLUGIN_REMOTE` and asks GitHub's API about `PLUGIN_REPOSITORY`
    # (`repos/<it>/git/ref/…`), and the release workflow lists the tag the gated jobs wait for.
    # `RELEASING.md` names it to the owner, who creates it, sets its rulesets and lists its `main`
    # by hand. Each is read from its own file, and every one of them names the same repository.
    # Mutations (oracle): `mutations/`'s "the plugin gate asks another repository" -> `publish`'s
    # step lists another name; "RELEASING lists another plugin repository's main" -> step 1's
    # `git ls-remote` does; "RELEASING sets the rulesets of another plugin repository" -> the
    # `ruleset` helper asks another; "RELEASING creates another plugin repository" -> section 3's
    # `gh repo create` names another.
    release = scriptload.release()
    publisher = scriptload.publish_plugin()
    named = {
        "release.py PLUGIN_URL": _github_repository(release.PLUGIN_URL),
        "release.py PLUGIN_REPOSITORY": release.PLUGIN_REPOSITORY,
        "publish_plugin.py PLUGIN_REMOTE": _github_repository(publisher.PLUGIN_REMOTE),
        "publish_plugin.py PLUGIN_URL": _github_repository(publisher.PLUGIN_URL),
        "publish_plugin.py PLUGIN_REPOSITORY": publisher.PLUGIN_REPOSITORY,
    }
    for job in GATED:
        script = _run(_steps_of(RELEASE_WORKFLOW, job)[0])
        listed = re.findall(r"\bgit ls-remote (\S+)", script)
        assert len(listed) == 1, (job, listed)
        named[f"release.yml {job}"] = _github_repository(listed[0])
    # The document's commands, each read where the owner copies it from: every `git ls-remote` of
    # a GitHub repository, every `gh api repos/<it>/…` but this repository's own and the
    # `OWNER/REPO` placeholder of a sentence (lower case only), and the one `gh repo create`. Each
    # must be found, or the set below holds nothing of the document's. Mutations (oracle):
    # `mutations/`'s "RELEASING no longer creates the plugin repository" -> `created` is empty;
    # "the plugin repository test reads no git ls-remote from RELEASING" -> `listed` is; "the
    # plugin repository test reads no gh api path from RELEASING" -> `asked` is.
    releasing = RELEASING.read_text(encoding="utf-8")
    listed = re.findall(
        r"\bgit ls-remote\s+((?:https://github\.com/|git@github\.com:)\S+)", releasing
    )
    asked = {
        name
        for name in re.findall(r"\brepos/([a-z0-9._-]+/[a-z0-9._-]+)/", releasing)
        if name != "dry-bag/drybag"
    }
    created = re.findall(r"\bgh repo create (\S+)", releasing)
    assert listed and asked and len(created) == 1, (listed, asked, created)
    for number, url in enumerate(listed):
        named[f"RELEASING.md git ls-remote {number}"] = _github_repository(url)
    for name in asked:
        named[f"RELEASING.md repos/{name}"] = name
    named["RELEASING.md gh repo create"] = created[0]
    assert set(named.values()) == {PLUGIN_REPOSITORY}, named


SMOKE_JOB = "installed-plugin"


def _resolved(env: Node, outputs: dict[str, dict[str, str]]) -> dict[str, str]:
    """A step's `env:`, each `${{ steps.<id>.outputs.<key> }}` read from what that step wrote."""
    assert isinstance(env, dict), env
    resolved = {}
    for key, value in env.items():
        assert isinstance(value, str), (key, value)
        found = re.fullmatch(r"\$\{\{ steps\.([\w-]+)\.outputs\.([\w-]+) \}\}", value)
        assert found is not None, (key, value)
        resolved[key] = outputs[found.group(1)][found.group(2)]
    return resolved


def _smoke_programs(tmp_path: Path, source: Path) -> tuple[Path, Path]:
    """`source` given this branch's `scripts/plugin_tree.py`, beside the tree it reads and outside
    it, so the commit read is `HEAD`'s; and the smoke's programs: this interpreter, a `uv` that
    runs its command and a `claude` that installs nothing. The directory they are on, and the
    runner's temporary directory."""
    tool = source / "scripts" / "plugin_tree.py"
    tool.parent.mkdir(exist_ok=True)
    tool.write_bytes((scriptload.SCRIPTS / "plugin_tree.py").read_bytes())
    stub = _interpreters(tmp_path)
    (stub / "uv").write_text(
        '#!/bin/sh\ncase "$1" in\n  sync) exit 0 ;;\n  run) shift; exec "$@" ;;\nesac\nexit 9\n'
    )
    (stub / "claude").write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "plugin install" ]; then\n'
        '  mkdir -p "$CLAUDE_CONFIG_DIR/plugins/cache/drybag/drybag/1.2.3"\n'
        "fi\n"
    )
    for name in ("uv", "claude"):
        (stub / name).chmod(0o755)
    temp = tmp_path / "runner"
    temp.mkdir()
    return stub, temp


@needs_git
@needs_bash
@needs_smoke_workflow
def test_the_smoke_installs_by_ref_and_sha(tmp_path: Path) -> None:
    # A user's harness clones the plugin repository at the marketplace entry's `ref` and checks out
    # its `sha`, so the smoke installs the same way: from a scratch repository holding the commit
    # `plugin_tree.py commit` builds from this one, by `ref` and `sha` both. `--no-parent`, because
    # the scratch repository holds no earlier plugin commit, and a commit naming a parent it lacks
    # would break the clone once the first parent pins a `sha`. Both steps run here as shipped,
    # the second with the `env:` the first's outputs give it, against a `uv` that runs its command
    # and a `claude` that installs nothing; the id is computed by git, never by the script.
    # Mutations (oracle): `mutations/`'s "the smoke installs by ref alone" and "the smoke's plugin
    # commit names the first parent's pin as its parent".
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    pinned = {plugintree.MARKETPLACE: plugintree.pinned_marketplace("a" * 40)}
    plugintree.write(source, {**plugintree.PLUGIN_FILES, **pinned})
    plugintree.commit(source, "a commit whose marketplace pins a plugin commit")
    plugintree.write(source, {plugintree.MARKETPLACE: plugintree.pinned_marketplace("b" * 40)})
    plugintree.commit(source, "the commit the smoke runs on")
    stub, temp = _smoke_programs(tmp_path, source)
    steps = _steps_of(SMOKE_WORKFLOW, SMOKE_JOB)
    index, line = _tree_command(SMOKE_WORKFLOW, SMOKE_JOB, "commit")
    assert "--no-parent" in shlex.split(line), line
    built = steps[index]
    ident = built.get("id")
    assert isinstance(ident, str), built
    outputs: dict[str, dict[str, str]] = {}
    for step in (built, *(step for step in steps if "claude plugin install" in _run(step))):
        written = temp / f"output-{len(outputs)}"
        given = _resolved(step.get("env", {}), outputs)
        done = _run_step(
            _run(step),
            source,
            stub,
            {**given, "RUNNER_TEMP": str(temp), "GITHUB_OUTPUT": str(written)},
        )
        assert done.returncode == 0, (_name(step), done.stdout + done.stderr)
        outputs[str(step.get("id"))] = _outputs(written)
    expected = plugintree.hashed(
        source, plugintree.literal(plugintree.plugin_tree_id(source), None)
    )
    repository = temp / "plugin-repo.git"
    catalog = json.loads((temp / "market" / ".claude-plugin" / "marketplace.json").read_text())
    assert catalog["plugins"][0]["source"] == {
        "source": "url",
        "url": f"file://{repository}",
        "ref": "v1.2.3",
        "sha": expected,
    }, catalog
    # And the scratch repository's `main` is that commit. Mutation (oracle): `mutations/`'s "the
    # smoke's scratch repository has no main".
    assert git(repository, "rev-parse", "refs/heads/main").strip() == expected
    # Its tag is a decoy: one commit past the built one, whose one parent it is, holding one file
    # more, so only the entry's `sha` names the commit the install is compared with, and a harness
    # that installed by the `ref` would install a tree the comparison with the render refuses.
    # Mutations (oracle): `mutations/`'s "the smoke tags the pinned commit and not a decoy" and
    # "the smoke's decoy holds the pinned commit's tree".
    decoy = git(repository, "rev-parse", "refs/tags/v1.2.3^{commit}").strip()
    assert git(repository, "rev-list", "--parents", "-n", "1", decoy).split() == [decoy, expected]
    assert git(repository, "diff-tree", "-r", "--name-status", expected, decoy) == "A\tdecoy\n"


PINNED_CATALOG = "A catalog whose entry pins a commit by sha validates"


@needs_bash
@needs_ci_workflow
def test_the_validator_reads_a_catalog_whose_entry_pins_a_sha(tmp_path: Path) -> None:
    # Once a release commit pins the plugin commit, this repository's catalog carries a `sha`
    # beside its `ref`, and on `dev` it may carry none; the validator is asked about that shape
    # on every change, by `--strict`, on a scratch copy of the catalog whose entry carries one.
    # The step runs here as shipped against a `claude` that records what it was asked. Mutation
    # (oracle): `mutations/`'s "the validator reads a catalog that pins no sha".
    stub = _interpreters(tmp_path)
    asked = tmp_path / "asked"
    (stub / "claude").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{asked}"\n')
    (stub / "claude").chmod(0o755)
    temp = tmp_path / "runner"
    temp.mkdir()
    root = ROOT
    done = _run_step(
        step_script(CI_WORKFLOW, PINNED_CATALOG), root, stub, {"RUNNER_TEMP": str(temp)}
    )
    assert done.returncode == 0, done.stdout + done.stderr
    words = asked.read_text(encoding="utf-8").splitlines()
    # Mutation (oracle): `mutations/`'s "the validator checks the pinned catalog without
    # --strict".
    assert words[:2] == ["plugin", "validate"] and words[3:] == ["--strict"], words
    expected = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
    expected["plugins"][0]["source"]["sha"] = "0" * 40
    assert json.loads(Path(words[2]).read_text()) == expected, words[2]


@needs_git
@needs_bash
@needs_smoke_workflow
def test_the_smoke_says_why_it_built_no_plugin_commit(tmp_path: Path) -> None:
    # `--json` writes a refusal's sentence into the file the step reads, so the step prints the
    # file when the script fails; without it the job stops with an exit code and no reason. A
    # `plugin.json` naming no `X.Y.Z` version renders, and is refused by `commit` alone. Mutation
    # (oracle): `mutations/`'s "the smoke hides why it built no plugin commit".
    manifest = (b'{"name": "drybag", "version": "1.2"}\n', "100644")
    source = plugintree.plugin_source(
        tmp_path, {**plugintree.PLUGIN_FILES, ".claude-plugin/plugin.json": manifest}
    )
    stub, temp = _smoke_programs(tmp_path, source)
    index, _ = _tree_command(SMOKE_WORKFLOW, SMOKE_JOB, "commit")
    step = _steps_of(SMOKE_WORKFLOW, SMOKE_JOB)[index]
    written = temp / "output"
    done = _run_step(
        _run(step), source, stub, {"RUNNER_TEMP": str(temp), "GITHUB_OUTPUT": str(written)}
    )
    assert done.returncode != 0, done.stdout + done.stderr
    assert "which is not X.Y.Z in ASCII digits" in done.stderr, done.stderr
    assert _outputs(written) == {}
