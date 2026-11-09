# tests/setup/test_setup.py
from __future__ import annotations

import errno
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from drybag.attach.api import read_binding
from drybag.config.overlay import overlay_root
from drybag.errors import Failure, Refusal
from drybag.jsonobject import LONG_NUMBER, NESTED
from drybag.overlay.layout import IDENTITY_RECORD
from drybag.presets import load_preset
from drybag.printed import quoted
from drybag.runner import Completed
from drybag.setup.api import USER_SETTINGS, setup
from drybag.setup.machine import read_machine, write_machine
from tests import parserlimits
from tests.gitfixture import needs_git
from tests.parserlimits import overflowing
from tests.pathfaults import (
    ROOT_SEARCHES_EVERYTHING,
    at_mode,
    read_only,
    unsearchable,
    write_only,
)
from tests.runners import Recorder, real_git

# The minimal `drybag.toml` `attach.read_binding` needs (a project name and nothing else),
# the same shape `tests/setup/test_machine.py::_initialised_project` uses for `load()`.
CONFIG = """
[drybag]
version = "0.1.0"
preset = "recommended"

[project]
name = "widget"
base_branch = "main"
"""


def _initialised_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "drybag.toml").write_text(CONFIG, encoding="utf-8")
    return project


# What `gh repo view <slug> --json isTemplate` answers (measured against gh 2.101.0): a template
# exits 0 with `{"isTemplate":true}`, and a repository that does not exist exits 1 with GraphQL's
# "Could not resolve to a Repository". `create:` asks it once to choose whose template to
# generate from, so a `create:` run has to have the probe answered.
PLUGINS = ("superpowers", "context7")
_OCTOS_PROBE = "gh repo view octo/drybag-overlay-template"
_A_TEMPLATE = Completed(0, '{"isTemplate":true}\n', "")
_NO_SUCH_REPOSITORY = Completed(
    1,
    "",
    "GraphQL: Could not resolve to a Repository with the name 'octo/drybag-overlay-template'."
    " (repository)\n",
)


def _populate_overlay(argv: list[str], cwd: Path) -> None:
    """Stand in for a successful template generation, the same probe `overlay.create` reads."""
    if argv[:3] != ["gh", "repo", "create"]:
        return
    _seed_overlay(cwd / argv[3].split("/")[-1])


def _seed_overlay(path: Path) -> None:
    """Give `path` the identity record `overlay.identity.overlay_fault` checks, as the shipped
    template writes it, without rendering the whole template — enough for a fixture to read as a
    real overlay's root."""
    path.mkdir(parents=True, exist_ok=True)
    (path / IDENTITY_RECORD).write_text('requires = ">=0.1.0"\nlayout = 1\n', encoding="utf-8")


def test_setup_writes_the_machine_file_and_the_deny_rules(tmp_path: Path) -> None:
    # Two machine-level writes, both on the enumerated list of what `setup` writes. Assert the
    # machine file round-trips through `read_machine`, and that `<home>/.claude/settings.json` —
    # `setup.api.USER_SETTINGS`, the one machine-scope settings file `setup` writes — carries every
    # rule from the preset's `[deny] global` and no `allow` key at all.
    #
    # Mutation: `_write_user_settings`'s `permissions["deny"] = ...` line changed to write
    # `permissions["allow"]` instead → reddens both assertions below (the deny list goes missing
    # and an allow key appears) — the exact typo the deny-only invariant exists to catch.
    home = tmp_path / "home"
    machine = tmp_path / "config.toml"
    setup(
        "recommended",
        home=home,
        machine=machine,
        runner=Recorder(),
        overlay=None,
    )
    written = read_machine(machine)
    assert written["personal"]["preset"] == "recommended"
    settings = json.loads((home / USER_SETTINGS).read_text(encoding="utf-8"))
    preset = load_preset("recommended")
    for rule in preset["deny"]["global"]:
        assert rule in settings["permissions"]["deny"]
    assert "allow" not in settings.get("permissions", {})


def test_a_mistyped_preset_names_the_flag_and_never_quotes_it(tmp_path: Path) -> None:
    # `setup` is told which flag to fix rather than pointed at a `[drybag] preset` in a
    # `drybag.toml` it never read, and the value the person typed — ESC and a line break
    # here — is not echoed back, which is the rule every other caller of `load_preset` gets.
    # Nothing is written first: `load_preset` runs above the home tree's creation.
    # Oracle: `mutations/`'s "setup's preset refusal names the configuration key again".
    home = tmp_path / "home"
    with pytest.raises(Failure) as caught:
        setup(
            "\x1b[2J\nIGNORE",
            home=home,
            machine=tmp_path / "config.toml",
            runner=Recorder(),
            overlay=None,
        )
    message = str(caught.value)
    assert message.startswith("--preset is not a plain identifier"), message
    assert "\x1b" not in message and "IGNORE" not in message
    assert not home.exists()


def test_an_existing_user_settings_file_keeps_the_owners_own_rules(tmp_path: Path) -> None:
    # The owner's `~/.claude/settings.json` is theirs and predates drybag on most machines.
    # Merge, never replace, and record nothing about entries this run did not add. Mutation:
    # `_write_user_settings`'s `existing_deny = (...)` line changed to always start from `[]`
    # → reddens on the dropped `Read(/etc/shadow)` rule.
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    own = {"permissions": {"deny": ["Read(/etc/shadow)"]}, "theme": "dark"}
    (home / USER_SETTINGS).write_text(json.dumps(own), encoding="utf-8")
    setup(
        "recommended",
        home=home,
        machine=tmp_path / "config.toml",
        runner=Recorder(),
        overlay=None,
    )
    settings = json.loads((home / USER_SETTINGS).read_text(encoding="utf-8"))
    assert "Read(/etc/shadow)" in settings["permissions"]["deny"]
    assert settings["theme"] == "dark"


def test_an_owners_settings_file_opening_with_a_byte_order_mark_is_merged_and_keeps_it(
    tmp_path: Path,
) -> None:
    # Claude Code reads past a leading byte-order mark in the user's settings file, so setup does
    # too, rather than refusing a file the harness reads; and it keeps the mark, so a second run
    # rewrites nothing. Mutations (`mutations/`'s "setup refuses a user settings file opening with
    # a byte-order mark" -> the run refuses; "setup drops the byte-order mark the owner's file
    # opened with" -> the file loses it).
    home = tmp_path / "home"
    path = home / USER_SETTINGS
    path.parent.mkdir(parents=True)
    path.write_text("\ufeff" + json.dumps({"theme": "dark"}), encoding="utf-8")

    def run() -> None:
        setup(
            "recommended",
            home=home,
            machine=tmp_path / "config.toml",
            runner=Recorder(),
            overlay=None,
        )

    run()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("\ufeff")
    assert json.loads(text.removeprefix("\ufeff"))["theme"] == "dark"
    before = path.read_bytes()
    run()
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("document", "clause"),
    [(parserlimits.NESTED, NESTED), ('{"n": ' + parserlimits.LONG_NUMBER + "}", LONG_NUMBER)],
    ids=["nested", "long-number"],
)
def test_a_user_settings_file_past_the_parsers_reach_is_a_failure_naming_it(
    tmp_path: Path, document: str, clause: str
) -> None:
    # Both documents are valid JSON, and `json.loads` meets neither with the `JSONDecodeError` the
    # reader caught: nesting past what it follows raises `RecursionError`, and an integer longer
    # than the interpreter converts (4,300 digits by default) a plain `ValueError`. Either ended
    # `drybag setup` in an internal error. The file is the owner's, and setup rewrites it, so it
    # is refused rather than read. Mutation (advisory): `_read_document` parses with `json.loads`
    # again -> the `Failure` is never raised and this reddens.
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / USER_SETTINGS).write_text(document, encoding="utf-8")
    with pytest.raises(Failure) as caught:
        setup(
            "recommended",
            home=home,
            machine=tmp_path / "config.toml",
            runner=Recorder(),
            overlay=None,
        )
    assert str(caught.value) == f"{home / USER_SETTINGS} {clause}"
    assert (home / USER_SETTINGS).read_text(encoding="utf-8") == document


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_a_user_settings_file_that_cannot_be_read_is_a_failure_saying_why_in_words(
    tmp_path: Path,
) -> None:
    # The failure quoted the error whole, `[Errno 13] Permission denied: '<the path again>'`,
    # where every other reader of a file says its reason in words, in parentheses (`fsops.said`).
    # A file at mode 000: a directory at that path is refused before the first write now. Mutation
    # (oracle): `mutations/`'s "a read refusal says an unreadable file in its error's own text".
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / USER_SETTINGS).write_text("{}\n", encoding="utf-8")
    with at_mode(home / USER_SETTINGS, 0, after=0o644), pytest.raises(Failure) as caught:
        setup(
            "recommended",
            home=home,
            machine=tmp_path / "config.toml",
            runner=Recorder(),
            overlay=None,
        )
    assert (
        str(caught.value) == f"{home / USER_SETTINGS} cannot be read ({os.strerror(errno.EACCES)})"
    )


def test_setup_with_no_plugin_named_runs_no_plugin_command(tmp_path: Path) -> None:
    # A third-party plugin runs in every session of its harness, hooks and all, so `setup`
    # installs one only when a person names it: an unasked run registers no marketplace and
    # installs nothing, on any harness, and has nothing to say about plugins.
    runner = Recorder()
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay=None,
    )
    assert [argv for argv in runner.calls if argv[1:2] == ["plugin"]] == [], runner.calls
    assert report.plugins_installed == ()
    assert not [note for note in report.notes if "plugin" in note or "marketplace" in note]


def test_every_plugin_install_is_one_recorded_argv(tmp_path: Path) -> None:
    # The Runner seam again. Two things could be wrong here that only an argv assertion can see: the
    # marketplace must be registered *before* anything is installed from it (a fresh machine cannot
    # install a plugin from a marketplace it never added), and the install call itself must carry
    # none of the unmeasured `--scope`/`-y` flags the first draft guessed.
    runner = Recorder()
    preset = load_preset("recommended")
    setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay=None,
        plugins=PLUGINS,
    )
    claude = preset["plugins"]["claude"]
    add = ["claude", "plugin", "marketplace", "add", claude["source"]]
    installs = [
        ["claude", "plugin", "install", f"{selector}@{claude['marketplace']}"]
        for selector in PLUGINS
    ]
    # **Order, not membership.** `… in runner.calls` is a set question, and the thing this test is
    # named for is a sequence: the reviewer swapped the two loops in `_install_plugins` so every
    # install ran before its marketplace was registered -- the exact defect the first draft shipped
    # -- and both assertions still passed, because both calls were still made. `mutations/`'s
    # "a plugin is installed before its marketplace is registered" carries the swap.
    assert installs, "the preset recommends nothing, so the ordering below measures nothing"
    assert add in runner.calls
    for install in installs:
        assert install in runner.calls
        assert runner.calls.index(add) < runner.calls.index(install), runner.calls
    # Codex has no verified marketplace for these two plugins: nothing is attempted.
    assert not any(argv and argv[0] == "codex" for argv in runner.calls)


def test_a_run_that_names_no_plugin_asks_no_harness_anything(tmp_path: Path) -> None:
    # A third-party plugin runs in every session of its harness, so none is installed unasked, and
    # a run that names none registers no marketplace and says nothing of one: a harness with no
    # declared marketplace is noted only for a plugin somebody asked for. Mutation: `mutations/`'s
    # "setup reaches the plugin commands with no plugin named".
    runner = Recorder()
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay=None,
    )
    assert runner.calls == []
    assert report.plugins_installed == ()
    assert not [note for note in report.notes if "marketplace" in note], report.notes


def test_a_selector_the_marketplace_does_not_carry_is_a_note_naming_the_argv(
    tmp_path: Path,
) -> None:
    # `_install_plugins`' install-failure branch, which no test in this file could reach: with
    # `answers` keyed on `argv[0]`, `"claude"` answered the `marketplace add` too, so the run
    # `continue`d and never attempted an install at all. This is the likelier of the two real
    # failures -- the marketplace is registered and simply does not carry the selector the
    # preset names -- and `setup` must report it and finish, not raise and not claim it
    # installed.
    #
    # Mutation: `_install_plugins`' `notes.append(f"{agent}: `{' '.join(argv)}` did not
    # succeed ({detail})")` replaced by `pass` -> reddens on the missing note, while
    # `plugins_installed` stays empty, which is what makes the two assertions different
    # questions rather than one asked twice.
    preset = load_preset("recommended")
    claude = preset["plugins"]["claude"]
    selector = PLUGINS[0]
    full = f"{selector}@{claude['marketplace']}"
    runner = Recorder(
        answers={
            f"claude plugin install {full}": Completed(1, "", f"no plugin named {selector} here")
        }
    )
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay=None,
        plugins=PLUGINS,
    )
    assert ["claude", "plugin", "marketplace", "add", claude["source"]] in runner.calls
    assert ["claude", "plugin", "install", full] in runner.calls
    assert selector not in report.plugins_installed
    # The other selector still installs: one failure is one note, never an abandoned run.
    assert PLUGINS[1] in report.plugins_installed
    assert any(f"claude plugin install {full}" in note for note in report.notes), report.notes
    assert any("no plugin named" in note for note in report.notes), report.notes


@pytest.mark.parametrize("step", ["marketplace add", "install"])
def test_what_a_plugin_command_prints_cannot_drive_a_terminal(tmp_path: Path, step: str) -> None:
    # A plugin command's answer was quoted raw in the note: a line break followed by `::error::`
    # is a workflow command in a CI log, and an escape sequence drives a terminal.
    #
    # Mutation: `mutations/`'s "a subprocess's answer is quoted raw".
    runner = Recorder(
        answers={f"claude plugin {step}": Completed(1, "", "boom\n::error::forged\x1b[2J")}
    )
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay=None,
        plugins=["superpowers"],
    )
    said = " ".join(report.notes)
    assert "forged" in said
    assert "\n::error::" not in said and "\x1b" not in said


def test_codex_gets_a_note_naming_the_unverified_plugins_rather_than_silence(
    tmp_path: Path,
) -> None:
    # A harness this preset cannot install for on a verified path is a reported note, never silence
    # and never a failure. `setup` installs for every registered harness, so an ordinary run
    # reaches this for every machine that has Codex configured.
    load_preset("recommended")
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=Recorder(),
        overlay=None,
        plugins=PLUGINS,
    )
    expected = (
        f"codex: no verified marketplace for {', '.join(PLUGINS)}; "
        f"install manually if this harness supports it (see README)"
    )
    assert expected in report.notes


def test_a_harness_that_is_not_installed_is_a_note_not_a_failure(tmp_path: Path) -> None:
    # A missing `claude` binary must never turn a fresh-machine `setup` into a traceback — the
    # marketplace-add call is the first one this harness makes, and it is where a missing
    # binary would surface (`Runner` turns it into `Completed(127, ...)`).
    #
    # No mutation: this is `Runner`'s own fail-soft convention (a non-zero result is a note,
    # per `drybag.runner.Runner`'s own docstring), exercised here through the `Recorder`'s
    # script rather than guarding one line of this module's own whose removal would look like
    # a plausible bug — the "non-zero becomes a note" shape is `_install_plugins`' whole
    # structure, not a single guardable line.
    runner = Recorder(answers={"claude": Completed(127, "", "claude: command not found")})
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay=None,
        plugins=["superpowers"],
    )
    assert any("claude" in note for note in report.notes)
    assert report.plugins_installed == ()


def test_the_overlay_offer_is_never_taken_without_being_asked(tmp_path: Path) -> None:
    # `create:` runs `gh repo create` only when it is named. A default that creates a GitHub
    # repository is the one default this command may not have.
    #
    # Mutation: `setup`'s `if overlay is not None:` changed to `if True:` → reddens (the call
    # then reaches `_apply_overlay(None, ...)`, which is exactly the "taken without being
    # asked" shape this test exists to catch — `overlay=None` runs anyway).
    runner = Recorder()
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay=None,
    )
    assert report.overlay is None
    assert not any(argv[:2] == ["gh", "repo"] for argv in runner.calls)


def test_pointing_at_an_existing_overlay_records_its_root_and_creates_nothing(
    tmp_path: Path,
) -> None:
    # The second of the three answers to where the overlay is — create one, record an existing one,
    # or pass no `--overlay` — and the answer a second machine gives: the overlay already exists
    # and is cloned, and `setup` only records it.
    existing = tmp_path / "overlay"
    existing.mkdir()
    _seed_overlay(existing)
    machine = tmp_path / "config.toml"
    runner = Recorder()
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=machine,
        runner=runner,
        overlay=str(existing),
    )
    assert report.overlay == existing
    assert not any(argv[:2] == ["gh", "repo"] for argv in runner.calls)
    assert overlay_root(machine) == existing


def test_an_overlay_missing_the_layout_is_refused(tmp_path: Path) -> None:
    # The overlay root is the machine's trust anchor, so a directory that merely happens to exist
    # and hold something must not become one. `existing` here holds a note and no identity record,
    # which is the shape a careless `--overlay ~/notes` would have; an empty one is rendered into.
    #
    # Mutation (`mutations/`'s "the overlay probe stops asking for the identity record"): the
    # record's absence is read as an unreadable record, and the refusal names the wrong fault.
    from drybag.overlay.identity import NO_RECORD
    from drybag.setup.run import _RECORDING

    existing = tmp_path / "not-an-overlay"
    existing.mkdir()
    (existing / "notes.md").write_text("mine\n", encoding="utf-8")
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=tmp_path / "home",
            machine=tmp_path / "config.toml",
            runner=Recorder(),
            overlay=str(existing),
        )
    shown = quoted(str(existing.resolve()))
    assert str(refused.value) == f"{NO_RECORD.format(root=shown)}; {_RECORDING}"


@pytest.mark.parametrize(
    ("probe", "template"),
    [
        pytest.param(_A_TEMPLATE, "octo/drybag-overlay-template", id="the-owners-own"),
        pytest.param(
            _NO_SUCH_REPOSITORY,
            "github.com/dry-bag/drybag-overlay-template",
            id="the-publishers",
        ),
    ],
)
def test_create_generates_from_the_owners_template_or_else_the_publishers(
    tmp_path: Path, probe: Completed, template: str
) -> None:
    # `--overlay create:` calls `overlay.create`, so a user with no template of their own reaches
    # the publisher's through the one resolution there: a second copy of it here would be the
    # place two answers drift. Mutation: the `setup` call passes a
    # template of its own → one of the two cases reddens.
    home = tmp_path / "home"
    runner = Recorder(answers={_OCTOS_PROBE: probe}, on_call=_populate_overlay)
    setup(
        "recommended",
        home=home,
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay="create:octo/drybag-private",
    )
    creating = next(argv for argv in runner.calls if argv[:3] == ["gh", "repo", "create"])
    assert creating[creating.index("--template") + 1] == template


def test_overlay_create_that_cannot_ask_gh_whose_template_creates_nothing(
    tmp_path: Path,
) -> None:
    # A probe that failed for a reason other than "not found" never becomes a repository on the
    # publisher's template: `gh repo create` is the one irreversible act `setup` performs.
    home = tmp_path / "home"
    runner = Recorder(
        answers={_OCTOS_PROBE: Completed(1, "", "HTTP 401: Bad credentials")},
        on_call=_populate_overlay,
    )
    with pytest.raises(Failure, match="Bad credentials"):
        setup(
            "recommended",
            home=home,
            machine=tmp_path / "config.toml",
            runner=runner,
            overlay="create:octo/drybag-private",
        )
    assert not any(argv[:3] == ["gh", "repo", "create"] for argv in runner.calls)


def test_rerunning_overlay_create_over_an_existing_overlay_creates_nothing_and_names_no_template(
    tmp_path: Path,
) -> None:
    # Re-running `setup --overlay create:` after the first run is the ordinary case, and `create`
    # answers a populated destination with no `gh` call and no template. The report used to say
    # "generated from None". Mutation: drop the `created.template is None` branch in
    # `_apply_overlay` and the report reads "created the overlay ... generated from None".
    home = tmp_path / "home"
    machine = tmp_path / "config.toml"
    destination = home / "drybag-private"
    _seed_overlay(destination)
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    report = setup(
        "recommended",
        home=home,
        machine=machine,
        runner=runner,
        overlay="create:octo/drybag-private",
    )
    assert not any(argv[:3] == ["gh", "repo", "create"] for argv in runner.calls)
    assert not any(argv[:3] == ["gh", "repo", "view"] for argv in runner.calls)
    text = " ".join(str(value) for value in vars(report).values() if value is not None)
    assert "None" not in text
    assert "already" in " ".join(report.notes)
    assert overlay_root(machine) == destination


def test_the_recorded_overlay_root_is_accepted_inside_and_refused_outside_by_attach(
    tmp_path: Path,
) -> None:
    # The seam between `setup` and `attach`, asserted rather than assumed — and asserted through
    # both halves, which is what makes it the seam and not a guess: `setup --overlay <path>` records
    # a root, and `attach.read_binding` must accept a `--store` that is that root's own share for
    # this project and refuse, by the specific "own directory inside the overlay" guard, one that is
    # not. A bare `pytest.raises(Refusal)` with no message match could not tell that guard apart
    # from any other refusal `read_binding` might raise for an unrelated reason.
    #
    # No new entry in `mutations/`: the guard both arms exercise is `binding.py`'s own
    # store-must-match-`permitted_roots` check, already load-bearing as `mutations/`'s "attach takes
    # the overlay root from its argument instead of the machine file" — this test proves the two
    # ends of the seam agree, not a new line to mutate.
    existing = tmp_path / "overlay"
    existing.mkdir()
    _seed_overlay(existing)
    machine = tmp_path / "config.toml"
    setup(
        "recommended",
        home=tmp_path / "home",
        machine=machine,
        runner=Recorder(),
        overlay=str(existing),
    )
    project = _initialised_project(tmp_path)

    good_store = existing / "projects" / "widget" / "memory"
    binding = read_binding(project, store=good_store, machine=machine)
    assert binding.overlay == existing

    wrong_store = tmp_path / "elsewhere" / "memory"
    with pytest.raises(Refusal, match="own directory inside the overlay"):
        read_binding(project, store=wrong_store, machine=machine)


def test_a_second_run_is_idempotent(tmp_path: Path) -> None:
    # Two runs, one report each; the second installs no plugin twice and leaves the deny list
    # the same length.
    #
    # No mutation: idempotence here is an emergent property of guards this file already tests on
    # their own (the deny merge's `existing_deny`, and `write_machine`'s overlay-preserving
    # read-back) run twice, not a separate line of its own.
    home = tmp_path / "home"
    machine = tmp_path / "config.toml"
    runner = Recorder()
    first = setup(
        "recommended",
        home=home,
        machine=machine,
        runner=runner,
        overlay=None,
    )
    second = setup(
        "recommended",
        home=home,
        machine=machine,
        runner=runner,
        overlay=None,
    )
    assert sorted(first.plugins_installed) == sorted(second.plugins_installed)
    settings = json.loads((home / USER_SETTINGS).read_text(encoding="utf-8"))
    preset = load_preset("recommended")
    assert len(settings["permissions"]["deny"]) == len(preset["deny"]["global"])


def test_a_second_run_does_not_reset_a_personal_value_the_owner_set(tmp_path: Path) -> None:
    # `[personal]` is the preset's `[defaults.personal]` overlaid by anything the caller passed — a
    # preset default must never win over a value already recorded, whether that value came from the
    # owner's own hand or from an earlier `setup` run.
    #
    # Mutation: `_new_personal_values`'s `return {k: v for k, v in ... if k not in existing}`
    # changed to `return _personal_defaults(preset)` → reddens (the owner's "ru" is overwritten
    # back to the preset's own "").
    home = tmp_path / "home"
    machine = tmp_path / "config.toml"
    runner = Recorder()
    setup(
        "recommended",
        home=home,
        machine=machine,
        runner=runner,
        overlay=None,
    )
    # The owner sets a personal value by hand between two runs.
    write_machine(machine, personal={"preset": "mine"}, overlay_root=None, machine={})
    setup(
        "recommended",
        home=home,
        machine=machine,
        runner=runner,
        overlay=None,
    )
    assert read_machine(machine)["personal"]["preset"] == "mine"


def test_a_malformed_overlay_spec_is_refused(tmp_path: Path) -> None:
    # `--overlay create:` with no slash, or a missing owner or name, is a typo — not a path to
    # try to interpret and not a repository to create somewhere unexpected.
    #
    # No mutation: this is ordinary input validation on a value only the operator types
    # (`owner, sep, name = spec.partition("/")`), not a trust-boundary guard something
    # downstream reads as permission — the guards the oracle curates for are the overlay-layout
    # and destination checks, which this same branch also runs.
    with pytest.raises(Refusal):
        setup(
            "recommended",
            home=tmp_path / "home",
            machine=tmp_path / "config.toml",
            runner=Recorder(),
            overlay="create:no-slash-here",
        )


def test_a_missing_drybag_on_path_is_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `uv tool install` has no `--from`, so the positional git URL form pinned to a release tag
    # (principle 9: the CLI installs from a git tag) is what the note must name; asserted here
    # rather than left to eyeballing, since it is the one line a typo in the URL or the tag would
    # hide from every other test in this module.
    monkeypatch.setattr("shutil.which", lambda name: None)
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=Recorder(),
        overlay=None,
    )
    assert report.cli_on_path is False
    assert any("uv tool install git+https://github.com/dry-bag/drybag@v" in n for n in report.notes)


# --- everything structural, above the first write ---


def _wrote_anything(home: Path, machine: Path) -> list[str]:
    """What a run left behind on this machine: the two files `setup` writes, by name.

    A list rather than a boolean so a failing assertion says *which* file survived a refusal,
    and asserted non-empty by a companion test below — a check that a refused run wrote nothing
    proves nothing unless the same fixture, unrefused, writes something.
    """
    return [str(path) for path in (machine, home / USER_SETTINGS) if path.is_file()]


def test_a_refused_overlay_path_is_refused_before_the_first_write(tmp_path: Path) -> None:
    # `--overlay /typo` used to be validated at the very bottom of `setup`: a stub runner recorded
    # the marketplace add and both plugin installs, the machine file and `~/.claude/settings.json`
    # were both on disk, and only then did `Refusal: /typo is not a directory` propagate — with the
    # `SetupReport` discarded, so the caller saw only the refusal and never a word about what had
    # already happened. A purely structural check on a caller-supplied path belongs above the first
    # write.
    #
    # Mutation (`mutations/`'s "setup asks whether --overlay is an overlay after it has
    # already written"): the hoisted `_requested_overlay` call is replaced by one that trusts
    # the path, leaving only `_apply_overlay`'s floor → the refusal still arrives, in the floor's
    # words, and this reddens on the refusal, the two files and the argv. A plugin is named, as in
    # the companion below, so a run that went on to install it is in the argv.
    from drybag.setup.run import NO_PLACE_TO_RENDER

    home = tmp_path / "home"
    machine = tmp_path / "config.toml"
    runner = Recorder()
    # Under a directory that is not there: a path that names nothing is rendered at, and one whose
    # parent is missing has nowhere to be rendered.
    typo = tmp_path.resolve() / "no-such-directory" / "typo"
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=runner,
            overlay=str(typo),
            plugins=["superpowers"],
        )
    assert str(refused.value) == NO_PLACE_TO_RENDER.format(
        path=quoted(str(typo)), parent=quoted(str(typo.parent))
    )
    assert _wrote_anything(home, machine) == []
    assert runner.calls == [], "no plugin was installed for a run that refuses its own arguments"


@pytest.mark.parametrize(
    "overlay",
    [
        pytest.param(os.fsdecode(b"/overlays/caf\xe9"), id="path"),
        pytest.param("create:octo/drybag-private", id="create"),
    ],
)
def test_an_overlay_root_a_utf_8_file_cannot_record_is_refused_before_the_first_write(
    tmp_path: Path, overlay: str
) -> None:
    # The machine file is UTF-8 TOML, and the overlay root is written into it last: on Linux an
    # overlay under a directory named in latin-1 bytes ended `setup --overlay` as `internal
    # error: UnicodeEncodeError`, after the machine file's other tables and the settings file
    # were already written (reproduced in a Linux container). Refused with the tree checks,
    # above every write, and before `gh repo create` for a created one, whose root lies under
    # `home`. Built from the path alone, because APFS refuses such a name. Mutation (declared):
    # drop the check -> the other refusals answer, or the write crashes, and this reddens.
    home = Path(os.fsdecode(os.fsencode(tmp_path) + b"/home-caf\xe9"))
    machine = tmp_path / "config.toml"
    runner = Recorder()
    with pytest.raises(Refusal, match="not UTF-8"):
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=runner,
            overlay=overlay,
        )
    assert _wrote_anything(home, machine) == []
    assert runner.calls == []


def test_the_same_fixture_without_the_typo_writes_both_files(tmp_path: Path) -> None:
    # The non-vacuity guard under the test above: the assertions there are about a *refused*
    # run, and they would pass just as well if `setup` wrote nothing under any circumstances.
    home = tmp_path / "home"
    machine = tmp_path / "config.toml"
    existing = tmp_path / "overlay"
    existing.mkdir()
    _seed_overlay(existing)
    runner = Recorder()
    setup(
        "recommended",
        home=home,
        machine=machine,
        runner=runner,
        overlay=str(existing),
        plugins=["superpowers"],
    )
    assert _wrote_anything(home, machine) == [str(machine), str(home / USER_SETTINGS)]
    assert runner.calls != []


def test_a_created_overlays_destination_that_is_a_link_is_recorded_where_it_leads(
    tmp_path: Path,
) -> None:
    # A repository can commit `<home>/<name>` as a link: `create:` was judged at the link's
    # target and recorded the link, which the repository can later point into its own tree.
    # `create:` records what `--overlay <path>` records, the destination resolved. Mutation
    # (`mutations/`'s "setup records a created overlay at its link and not where it leads") -> the
    # link is recorded and this reddens.
    outside = tmp_path / "outside-ov"
    _seed_overlay(outside)
    repository = tmp_path / "A"
    repository.mkdir()
    link = repository / "drybag-private"
    link.symlink_to(outside)
    machine = tmp_path / "config.toml"
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    setup(
        "recommended",
        home=repository,
        machine=machine,
        runner=runner,
        overlay="create:octo/drybag-private",
    )
    assert overlay_root(machine) == outside.resolve()
    # The repository points the link into its own tree; the record does not move with it.
    (repository / "evil").mkdir()
    link.unlink()
    link.symlink_to(repository / "evil")
    assert overlay_root(machine) == outside.resolve()


def test_a_created_overlays_destination_that_is_a_dangling_link_is_refused_before_anything(
    tmp_path: Path,
) -> None:
    # A link at `<home>/<name>` whose target is not there: read as absent, `gh repo create` made a
    # repository and then cloned through the link to wherever it pointed, or failed on it. It is
    # there and is not a directory, and refused before anything is written or run.
    from drybag.setup.run import DESTINATION_NOT_A_DIRECTORY

    home = tmp_path / "home"
    home.mkdir()
    destination = home / "drybag-private"
    destination.symlink_to(tmp_path / "later" / "ov")
    machine = tmp_path / "config.toml"
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=runner,
            overlay="create:octo/drybag-private",
        )
    assert str(refused.value) == DESTINATION_NOT_A_DIRECTORY.format(
        destination=quoted(str(destination))
    )
    assert runner.calls == [] and _wrote_anything(home, machine) == []


_DRIVES_A_TERMINAL = "x\x1b]0;owned\x07"


@pytest.mark.parametrize("printed", ["not-an-overlay", "the-floor", "the-note", "the-summary"])
def test_an_overlay_path_a_repository_spells_is_printed_quoted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    printed: str,
) -> None:
    # `--overlay`'s path, resolved through a link a repository commits, is spelled in the
    # repository's bytes, and the refusal that it is not an overlay, the floor's refusal of a path
    # it could not ask about (a link that loops, here), the note that it was recorded and `setup`'s
    # own report line printed it raw. Mutations (`mutations/`'s "the overlay probe prints the path
    # it judged raw" -> `not-an-overlay`; "the floor prints the path it could not ask about raw" ->
    # `the-floor`; "setup notes a recorded overlay's path raw" -> `the-note`; "setup reports the
    # recorded overlay's path raw" -> `the-summary`).
    from drybag.cli import build_parser, discover_registrars, run

    overlay = tmp_path / _DRIVES_A_TERMINAL
    refused = printed in ("not-an-overlay", "the-floor")
    if printed == "the-floor":
        overlay.symlink_to(overlay)
    else:
        overlay.mkdir()
    if not refused:
        _seed_overlay(overlay)
    elif printed == "not-an-overlay":
        # Holding something: an empty directory is rendered into, not refused.
        (overlay / "notes.md").write_text("mine\n", encoding="utf-8")
    runner = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: runner)
    argv = ["setup", "--preset", "recommended", "--home", str(tmp_path / "home")]
    argv += ["--machine", str(tmp_path / "config.toml"), "--overlay", str(overlay)]
    if printed == "the-note":
        argv.append("--json")
    code = run(argv, parser=build_parser(discover_registrars()))
    captured = capsys.readouterr()
    said = captured.err if refused else captured.out
    if printed == "the-note":
        said = "\n".join(json.loads(captured.out)["notes"])
    assert code == (2 if refused else 0), captured
    assert "\x1b" not in said and "\x07" not in said, said
    assert "\\x1b]0;owned\\x07" in said, said


def test_a_directory_whose_record_names_another_layout_is_not_an_overlay(tmp_path: Path) -> None:
    # The probe was once two manifest *files* existing, which the drybag checkout itself
    # satisfied, and any Claude Code plugin repository with them. The identity record is read now,
    # and has to name layout 1.
    #
    # Mutation (`mutations/`'s "the overlay probe takes any record for an overlay"): the layout is
    # not compared → this directory is accepted and the refusal never fires.
    from drybag.overlay.identity import NOT_A_RECORD
    from drybag.setup.run import _RECORDING

    impostor = tmp_path / "some-plugin"
    impostor.mkdir()
    (impostor / IDENTITY_RECORD).write_text("layout = 2\n", encoding="utf-8")
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=tmp_path / "home",
            machine=tmp_path / "config.toml",
            runner=Recorder(),
            overlay=str(impostor),
        )
    shown = quoted(str(impostor.resolve()))
    assert str(refused.value) == f"{NOT_A_RECORD.format(root=shown)}; {_RECORDING}"


def test_a_home_that_is_a_link_to_a_directory_is_followed_once_and_written_where_it_leads(
    tmp_path: Path,
) -> None:
    # `--home` is the machine owner's own directory, and one that is a link — a home on another
    # volume — is that owner's layout: every write under it lands where it leads.
    real = tmp_path / "volume" / "me"
    real.mkdir(parents=True)
    home = tmp_path / "home"
    home.symlink_to(real)
    machine = tmp_path / "config.toml"
    setup(
        "recommended",
        home=home,
        machine=machine,
        runner=Recorder(),
        overlay=None,
    )
    assert machine.is_file()
    assert (real / USER_SETTINGS).is_file()
    assert home.is_symlink()


# For a test that needs a directory its owner may not write into: root writes into every one,
# and `os.access` answers yes for root whatever the mode says.
_ROOT_WRITES_EVERYWHERE = pytest.mark.skipif(
    os.geteuid() == 0, reason="root writes into every directory"
)


def _setup_through_the_cli(
    monkeypatch: pytest.MonkeyPatch, home: Path, machine: Path
) -> tuple[int, Recorder]:
    """`drybag setup --preset recommended --home H --machine M`, through `cli.run`, with
    the runner a recorder: the frame is what turns an `OSError` into `internal error`, so a test
    about what the owner reads has to go through it."""
    from drybag.cli import build_parser, discover_registrars, run

    runner = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: runner)
    argv = ["setup", "--preset", "recommended", "--home", str(home)]
    code = run([*argv, "--machine", str(machine)], parser=build_parser(discover_registrars()))
    return code, runner


@_ROOT_WRITES_EVERYWHERE
@pytest.mark.parametrize("locked", ["above-home", "home", "claude"])
def test_a_home_that_cannot_take_the_write_is_refused_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    locked: str,
) -> None:
    # Where the settings file lands, at mode 555: the directory a home that is not there yet
    # would be made in, the home, or the `.claude` already in it. Under a read-only parent
    # `home.mkdir(parents=True)` raised `PermissionError` into the frame as `internal error`; a
    # read-only home or `.claude` had the machine file written, and only then did the settings
    # write refuse, in words about a symlink that was not there. Each is refused naming the
    # directory, with nothing written and nothing run. Mutations (`mutations/`'s "setup stops
    # asking whether --home can be used before its first write" -> `above-home` and `home`;
    # "setup stops asking whether an existing .claude can be written" -> `claude`, asked of the
    # writable home instead).
    home = tmp_path / "home"
    directory = {"above-home": tmp_path / "locked", "home": home, "claude": home / ".claude"}[
        locked
    ]
    directory.mkdir(parents=True)
    if locked == "above-home":
        home = directory / "home"
    machine = tmp_path / "config.toml"
    with read_only(directory):
        code, runner = _setup_through_the_cli(monkeypatch, home, machine)
    out = capsys.readouterr().err
    assert code == 2 and out.startswith("drybag: refused:"), out
    assert f"--home {home} cannot be used: {directory} is not writable" in out
    assert "symlink" not in out
    assert not machine.exists()
    assert runner.calls == []


@_ROOT_WRITES_EVERYWHERE
def test_a_directory_the_settings_write_opens_to_read_and_cannot_is_refused_before_any_write(
    tmp_path: Path,
) -> None:
    # The settings write opens its file's directory `O_RDONLY`, and a directory at mode 300 takes
    # a new name and refuses that open: the question whether a name can be made there passed it,
    # the machine file was written, and the settings write then refused. Mutation (`mutations/`'s
    # "setup stops asking whether the settings write can read its directory").
    home, machine = tmp_path / "home", tmp_path / "config.toml"
    directory = home / ".claude"
    directory.mkdir(parents=True)
    runner = Recorder()
    with write_only(directory), pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=runner,
            overlay=None,
        )
    said = str(refused.value)
    assert f"{directory} is not readable, and the settings write opens it to read" in said, said
    assert not machine.exists() and runner.calls == []


@ROOT_SEARCHES_EVERYTHING
def test_a_home_mkdir_that_fails_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The floor under the check above, and not dead: `os.access` answers for the real uid and
    # says yes to root whatever the mode, and a directory can change between the question and
    # the `mkdir`. Patching `mkdir` is how that interval is reached without a race. Mutation
    # (`mutations/`'s "setup lets a failed --home mkdir reach the frame"): the `except OSError`
    # around `home.mkdir` dropped -> `PermissionError` leaves `setup` and this reddens.
    home = tmp_path / "home"
    machine = tmp_path / "config.toml"

    def refused_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError(errno.EACCES, "Permission denied", str(self))

    monkeypatch.setattr(Path, "mkdir", refused_mkdir)
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=Recorder(),
            overlay=None,
        )
    assert str(refused.value) == f"--home {home} could not be created (Permission denied)"
    assert not machine.exists()


@_ROOT_WRITES_EVERYWHERE
def test_a_read_only_home_whose_claude_directory_is_writable_is_set_up(tmp_path: Path) -> None:
    # Nothing is written into a home that holds a writable `.claude` already: the settings file
    # lands in `.claude`, and the `mkdir` of a home that is there is a no-op. Asking whether
    # `home` itself could be written refused this layout, which worked before the question was
    # asked, saying "<home> is not writable" about a directory no write touches. Mutation
    # (`mutations/`'s "setup stops asking whether an existing .claude can be written"): the
    # question asked of `home` instead of where the settings file lands -> refused, and this
    # reddens.
    home = tmp_path / "home"
    claude = home / ".claude"
    claude.mkdir(parents=True)
    machine = tmp_path / "config.toml"
    with read_only(home):
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=Recorder(),
            overlay=None,
        )
    assert machine.is_file()
    assert (home / USER_SETTINGS).is_file()


@_ROOT_WRITES_EVERYWHERE
def test_a_created_overlay_already_in_a_read_only_home_is_set_up(tmp_path: Path) -> None:
    # Run again over the overlay it made, `create:` clones nothing, so `<home>/<name>` being there
    # is the end of what the home has to take. Mutation (`mutations/`'s "setup asks whether --home
    # can take a created overlay that is already there"): asked whether or not it is there ->
    # refused, and this reddens.
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    _seed_overlay(home / "drybag-private")
    machine = tmp_path / "config.toml"
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    with read_only(home):
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=runner,
            overlay="create:octo/drybag-private",
        )
    assert not any(argv[:3] == ["gh", "repo", "create"] for argv in runner.calls)
    assert machine.is_file()


@pytest.mark.parametrize("below", [False, True], ids=["home", "above-home"])
def test_a_home_that_is_a_regular_file_is_refused_as_one(tmp_path: Path, below: bool) -> None:
    # A regular file where `--home`, or a directory above it, has to be: the `mkdir` names it
    # ("File exists", "Not a directory"). The question about where the settings file lands walks
    # up to that file, and asking it whether a name can be made in it answered "is not writable",
    # a cause the path does not have. Mutation (`mutations/`'s "setup calls a regular file in
    # --home's place not writable"): the directory test dropped -> this reddens.
    blocker = tmp_path / "file"
    blocker.write_text("not a directory\n")
    home = blocker / "home" if below else blocker
    machine = tmp_path / "config.toml"
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=Recorder(),
            overlay=None,
        )
    reason = "Not a directory" if below else "File exists"
    assert str(refused.value) == f"--home {home} could not be created ({reason})"
    assert not machine.exists()


@_ROOT_WRITES_EVERYWHERE
def test_a_created_overlay_in_a_read_only_home_is_refused_before_gh_runs(tmp_path: Path) -> None:
    # `--overlay create:<owner>/<name>` clones into `<home>/<name>`, so a home with a writable
    # `.claude` still has to take that one directory — and finding out from the clone is finding
    # out after `gh repo create` made a repository on somebody's account. Mutation
    # (`mutations/`'s "setup stops asking whether --home can take a created overlay"): the question
    # dropped -> `gh repo create` runs, and this reddens.
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    machine = tmp_path / "config.toml"
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    with read_only(home), pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=runner,
            overlay="create:octo/drybag-private",
        )
    assert str(refused.value) == f"--home {home} cannot be used: {home} is not writable"
    assert runner.calls == []
    assert not machine.exists()


@ROOT_SEARCHES_EVERYTHING
def test_a_created_overlay_under_a_home_nobody_may_search_is_refused_before_anything(
    tmp_path: Path,
) -> None:
    # `--overlay create:` with `--home` below a directory nobody may search: asking what is at the
    # destination raised `PermissionError`, which reached the frame as `drybag: internal
    # error`. The phase's floor names the destination it could not ask about. Mutation
    # (`mutations/`'s "setup lets a path it cannot ask about before its first write reach the
    # frame") -> `PermissionError` leaves `setup`, and this reddens.
    locked = tmp_path / "locked"
    locked.mkdir()
    home = locked / "home"
    machine = tmp_path / "config.toml"
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    with unsearchable(locked), pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=runner,
            overlay="create:octo/drybag-private",
        )
    assert str(refused.value) == (
        f"{quoted(str(home / 'drybag-private'))} cannot be checked (Permission denied), so "
        "nothing was written"
    )
    assert runner.calls == []
    assert not machine.exists()


def _below_a_locked_directory(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    """`setup`'s keyword arguments with `--overlay` below `tmp_path/locked`, and the path below it
    that cannot be asked about once it is locked."""
    locked = tmp_path / "locked"
    locked.mkdir()
    asked = locked / "overlay"
    _seed_overlay(asked)
    return {"home": tmp_path / "home", "overlay": str(asked)}, asked


@ROOT_SEARCHES_EVERYTHING
def test_a_path_setup_cannot_ask_about_before_its_first_write_is_a_refusal_naming_it(
    tmp_path: Path,
) -> None:
    # This ended in `drybag: internal error: PermissionError`, with the path in a traceback's
    # words, from the overlay probe's `is_dir`. The step does not word that fault itself, so the
    # phase's floor does, naming the path the predicate was handed. Mutation (`mutations/`'s
    # "setup lets a path it cannot ask about before its first write reach the frame"): the floor's
    # `except` dropped -> `PermissionError` leaves `setup`, and this reddens.
    arguments, asked = _below_a_locked_directory(tmp_path)
    machine = tmp_path / "config.toml"
    runner = Recorder()
    with unsearchable(tmp_path / "locked"), pytest.raises(Refusal) as refused:
        setup("recommended", machine=machine, runner=runner, **arguments)
    assert str(refused.value) == (
        f"{quoted(str(asked))} cannot be checked (Permission denied), so nothing was written"
    )
    assert runner.calls == []
    assert not machine.exists()


@ROOT_SEARCHES_EVERYTHING
@pytest.mark.parametrize("mode", [0o000, 0o600], ids=["no-access", "readable-only"])
@pytest.mark.parametrize("form", ["create", "path"])
def test_a_directory_this_user_cannot_search_is_refused_naming_that_before_anything(
    tmp_path: Path, mode: int, form: str
) -> None:
    # What is in a directory nobody may search cannot be told, and nothing can be rendered or
    # cloned into it. `create:` once looked inside its `<home>/<name>` for an overlay and raised
    # `PermissionError` as `internal error`, after the machine file and the plugin installs; it
    # then refused in words blaming `--home` for a directory below it, printed raw, while
    # `--overlay <path>` named a file inside the directory it could not check. One rule judges
    # both now, in one sentence. Looking inside asks the search bit alone, so a directory that can
    # be read and not searched is refused too. Mutations (`mutations/`'s "setup stops asking
    # whether the place --overlay names can be searched" -> a file inside it cannot be checked;
    # "setup asks whether the place --overlay names can be read, not searched" -> `readable-only`).
    from drybag.setup.run import UNUSABLE_DIRECTORY

    home = tmp_path / "home"
    destination = home / "drybag-private"
    destination.mkdir(parents=True)
    machine = tmp_path / "config.toml"
    overlay = "create:octo/drybag-private" if form == "create" else str(destination)
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    with at_mode(destination, mode, after=0o755), pytest.raises(Refusal) as refused:
        setup("recommended", home=home, machine=machine, runner=runner, overlay=overlay)
    assert str(refused.value) == UNUSABLE_DIRECTORY.format(destination=quoted(str(destination)))
    assert runner.calls == []
    assert not machine.exists()


# `_before_the_first_write`'s steps, in its documented order, for a `create:` run.
_THE_PHASE = (
    "_requested_overlay",
    "load_preset",
    "_check_home_usable",
)


def test_every_question_before_the_first_write_is_asked_in_the_documented_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The order is what makes "refused before anything was written" true of every step: a step
    # that ran after a write or a program would have that write behind its refusal. Each step,
    # each write and each program run is logged as it happens.
    from drybag.setup import run

    events: list[str] = []

    def logged(name: str) -> None:
        original = getattr(run, name)

        def step(*args: Any, **kwargs: Any) -> Any:
            events.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(run, name, step)

    for name in (*_THE_PHASE, "write_machine", "_write_user_settings"):
        logged(name)
    real_mkdir = Path.mkdir

    def mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        events.append("mkdir")
        real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)

    def ran(argv: list[str], cwd: Path) -> None:
        events.append("run")
        _populate_overlay(argv, cwd)

    setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=ran),
        overlay="create:octo/drybag-private",
    )
    phase = len(_THE_PHASE)
    assert tuple(events[:phase]) == _THE_PHASE, events
    assert events[phase] == "mkdir", events
    assert {"write_machine", "_write_user_settings", "run"} <= set(events[phase:]), events


@pytest.mark.parametrize("place", ["claude", "home", "overlay"])
def test_a_symlink_loop_at_any_path_setup_is_given_is_a_refusal_naming_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    place: str,
) -> None:
    # Python 3.11 and 3.12 raise `RuntimeError` resolving a path through a symlink loop, which the
    # floor under `setup`'s questions before its first write, an `except OSError`, did not catch:
    # a loop at `~/.claude`, `--home` or `--overlay` was `drybag: internal error: RuntimeError`
    # there, while 3.13 refused some in other words. Every resolve in `setup` goes through
    # `fsops.resolved`, so each is the floor's refusal, naming the path, on every interpreter, with
    # nothing written and nothing run. Mutations (`mutations/`'s "setup resolves --overlay past
    # fsops" -> `overlay`; "fsops.resolved answers a loop with a path where the interpreter does"
    # -> `home`).
    from drybag.cli import build_parser, discover_registrars, run

    home, machine = tmp_path / "home", tmp_path / "config.toml"
    overlay = tmp_path / "overlay"
    home.mkdir()
    _seed_overlay(overlay)
    looped = {"claude": home / ".claude", "home": home, "overlay": overlay}[place]
    if looped.is_dir():
        shutil.rmtree(looped)
    looped.parent.mkdir(parents=True, exist_ok=True)
    looped.symlink_to(looped)
    argv = ["setup", "--preset", "recommended", "--home", str(home)]
    argv += ["--machine", str(machine), "--overlay", str(overlay)]
    runner = Recorder()
    monkeypatch.setattr("drybag.setup.commands.subprocess_runner", lambda: runner)
    code = run(argv, parser=build_parser(discover_registrars()))
    said = capsys.readouterr().err
    assert code == 2, said
    assert said.startswith("drybag: refused: "), said
    # A loop at `~/.claude` or `--home` is met resolving the settings file below it, named.
    asked = home / USER_SETTINGS if place in ("claude", "home") else looped
    assert f"{quoted(str(asked))} cannot be checked (" in said, said
    assert not machine.exists() and runner.calls == []


def test_a_created_tree_that_is_not_an_overlay_says_the_repository_now_exists(
    tmp_path: Path,
) -> None:
    # The one refusal that cannot precede a write, and what it owes the owner. `--overlay
    # create:` asks GitHub to generate from a template repository this project does not publish,
    # so what arrives is whatever is on that account — and if it is not an overlay, the run has
    # to say so *and* say that a private repository may now exist, with the remedy that works,
    # because the `SetupReport` is discarded on a refusal and nothing else would ever tell them.
    from drybag.overlay.create import UNRECORDED
    from drybag.overlay.identity import NOT_A_RECORD

    def _wrong_tree(argv: list[str], cwd: Path) -> None:
        if argv[:3] != ["gh", "repo", "create"]:
            return
        target = cwd / argv[3].split("/")[-1]
        target.mkdir(parents=True, exist_ok=True)
        (target / IDENTITY_RECORD).write_text("layout = 2\n", encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=tmp_path / "config.toml",
            runner=Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_wrong_tree),
            overlay="create:octo/drybag-private",
        )
    shown = quoted(str(home / "drybag-private"))
    assert str(refused.value) == (
        f"{NOT_A_RECORD.format(root=shown)}. "
        f"{UNRECORDED.format(slug='octo/drybag-private', path=shown)}"
    )
    assert overlay_root(tmp_path / "config.toml") is None


@pytest.mark.parametrize("per_file", [False, True])
def test_a_symlinked_settings_file_or_claude_directory_is_written_through(
    tmp_path: Path, per_file: bool
) -> None:
    # `stow` links the file where `~/.claude` is already there, and the directory where it is not:
    # either is the owner's layout, so the file the link leads to gains the rules and the link
    # stays. Mutation (`mutations/`'s "setup writes the settings file without resolving it") ->
    # the link becomes a regular file.
    home = tmp_path / "home"
    home.mkdir()
    leads_to = tmp_path / "dotfiles" / ".claude" / "settings.json"
    leads_to.parent.mkdir(parents=True)
    if per_file:
        leads_to.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        (home / ".claude").mkdir()
        (home / USER_SETTINGS).symlink_to(leads_to)
    else:
        (home / ".claude").symlink_to(leads_to.parent)
    setup(
        "recommended",
        home=home,
        machine=tmp_path / "config.toml",
        runner=Recorder(),
        overlay=None,
    )
    assert "permissions" in json.loads(leads_to.read_text(encoding="utf-8"))
    assert (home / (USER_SETTINGS if per_file else ".claude")).is_symlink()


def test_a_machine_file_linked_into_a_directory_that_cannot_be_written_names_that_directory(
    tmp_path: Path,
) -> None:
    # The write goes where the link leads, and the failure named the link's own directory, which
    # could be written. Mutation (oracle): `mutations/`'s "setup's write-through failure names the
    # link's directory".
    leads_to = tmp_path / "dotfiles" / "config.toml"
    leads_to.parent.mkdir()
    leads_to.write_text('[personal]\nscale = "x"\n', encoding="utf-8")
    machine = tmp_path / "drybag" / "config.toml"
    machine.parent.mkdir()
    machine.symlink_to(leads_to)
    home = tmp_path / "home"
    home.mkdir()
    leads_to.parent.chmod(0o555)
    try:
        with pytest.raises(Failure) as failed:
            setup(
                "recommended",
                home=home,
                machine=machine,
                runner=Recorder(),
                overlay=None,
            )
    finally:
        leads_to.parent.chmod(0o755)
    assert str(failed.value).startswith(f"{leads_to.parent} cannot be written (")


def test_a_symlinked_machine_file_is_written_through_and_stays_a_link(tmp_path: Path) -> None:
    # The machine file is the owner's as the settings file is: a dotfiles link at it gains the
    # tables `setup` writes and stays a link. Mutation (`mutations/`'s "setup writes the machine
    # file without resolving it"): the link becomes a regular file and the copy goes stale.
    leads_to = tmp_path / "dotfiles" / "config.toml"
    leads_to.parent.mkdir()
    leads_to.write_text('[personal]\nscale = "x"\n', encoding="utf-8")
    machine = tmp_path / "drybag" / "config.toml"
    machine.parent.mkdir()
    machine.symlink_to(leads_to)
    home = tmp_path / "home"
    home.mkdir()
    setup(
        "recommended",
        home=home,
        machine=machine,
        runner=Recorder(),
        overlay=None,
    )
    assert machine.is_symlink()
    written = read_machine(leads_to)
    assert written["personal"]["scale"] == "x"
    assert "machine" in written


def test_a_user_settings_file_the_encoder_cannot_write_back_is_a_failure_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python 3.12's indenting encoder stops near 994 levels, under what its parser reads, so a
    # deep `~/.claude/settings.json` was read and then ended `drybag setup` in
    # `RecursionError` while the merge was encoded. Forced on every interpreter: it is the
    # failure a file nested past the parser gets, and the file is left as it was. Mutation
    # (declared): setup encodes the merged settings with a bare `json.dumps` again.
    from drybag import jsonobject

    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / USER_SETTINGS).write_text('{"theme": "dark"}', encoding="utf-8")
    monkeypatch.setattr(jsonobject, "_encode", overflowing)
    with pytest.raises(Failure) as caught:
        setup(
            "recommended",
            home=home,
            machine=tmp_path / "config.toml",
            runner=Recorder(),
            overlay=None,
        )
    assert str(caught.value) == f"{home / USER_SETTINGS} {NESTED}"
    assert (home / USER_SETTINGS).read_text(encoding="utf-8") == '{"theme": "dark"}'


# --- an overlay rendered here ------------------------------------------------------------------


@needs_git
@pytest.mark.parametrize("empty", [False, True], ids=["absent", "empty"])
def test_setup_renders_an_overlay_at_an_absent_or_empty_path_and_records_it(
    tmp_path: Path, empty: bool
) -> None:
    # One entry for an overlay: `--overlay <path>` naming nothing renders the shipped template
    # there, makes it a git repository on `main`, installs the commit-time secret scan and records
    # it, as two commands of an earlier release did between them. An empty directory holds
    # nothing to keep, so it is a place to render too, where it was refused as not an overlay.
    from drybag.overlay.api import overlay_fault

    destination = tmp_path / "overlays" / "mine"
    destination.mkdir(parents=True) if empty else destination.parent.mkdir()
    machine = tmp_path / "config.toml"
    runner = Recorder(on_call=real_git)
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=machine,
        runner=runner,
        overlay=str(destination),
    )
    assert overlay_fault(destination) is None
    head = (destination / ".git" / "HEAD").read_text(encoding="utf-8")
    assert head == "ref: refs/heads/main\n"
    assert ["pre-commit", "install"] in runner.calls
    assert not [argv for argv in runner.calls if argv[0] == "gh"], runner.calls
    assert overlay_root(machine) == destination
    assert report.overlay == destination


# --- the sync switch an overlay made here is born with ------------------------------------------

_FOREIGN = '[foreign]\nkeep = 1\n\n[personal]\npreset = "mine"\n'


def _sync_table(machine: Path) -> object:
    return read_machine(machine).get("sync")


def _kept(machine: Path) -> None:
    """What a switch written beside the rest must leave alone."""
    raw = read_machine(machine)
    assert raw["foreign"] == {"keep": 1}
    assert raw["personal"]["preset"] == "mine"
    assert "version" in raw["machine"]
    assert "root" in raw["overlay"]


@needs_git
def test_setup_rendering_an_overlay_switches_sync_on(tmp_path: Path) -> None:
    # A new overlay is one this machine's sync should keep; the switch is the machine file's
    # `[sync] enabled`, written in the write that records `[overlay] root`. Mutation (`mutations/`'s
    # "recording an existing overlay switches sync on") is the other direction; here dropping the
    # `sync` argument from that write reddens.
    machine = tmp_path / "config.toml"
    machine.write_text(_FOREIGN, encoding="utf-8")
    setup(
        "recommended",
        home=tmp_path / "home",
        machine=machine,
        runner=Recorder(on_call=real_git),
        overlay=str(tmp_path / "mine"),
    )
    assert _sync_table(machine) == {"enabled": True}
    _kept(machine)


def test_setup_creating_an_overlay_switches_sync_on(tmp_path: Path) -> None:
    machine = tmp_path / "config.toml"
    machine.write_text(_FOREIGN, encoding="utf-8")
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    setup(
        "recommended",
        home=tmp_path / "home",
        machine=machine,
        runner=runner,
        overlay="create:octo/drybag-private",
    )
    assert any(argv[:3] == ["gh", "repo", "create"] for argv in runner.calls)
    assert _sync_table(machine) == {"enabled": True}
    _kept(machine)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param("", None, id="absent-stays-absent"),
        pytest.param("[sync]\nenabled = false\n", {"enabled": False}, id="false-stays-false"),
    ],
)
def test_setup_recording_an_overlay_leaves_sync_alone(
    tmp_path: Path, before: str, after: object
) -> None:
    # A second machine records the overlay the first one made. Whether it syncs is that machine's
    # owner's to say by hand, so recording writes the root and touches no `[sync]`.
    # Mutation: `mutations/`'s "recording an existing overlay switches sync on".
    existing = tmp_path / "overlay"
    _seed_overlay(existing)
    machine = tmp_path / "config.toml"
    machine.write_text(_FOREIGN + before, encoding="utf-8")
    setup(
        "recommended",
        home=tmp_path / "home",
        machine=machine,
        runner=Recorder(),
        overlay=str(existing),
    )
    assert overlay_root(machine) == existing
    assert _sync_table(machine) == after
    _kept(machine)


def test_recording_an_existing_overlay_arms_its_commit_time_secret_scan(tmp_path: Path) -> None:
    # A second machine records the overlay the first one made, from a clone: the `pre-commit` hook
    # lives in the clone's own `.git`, which no clone carries, so a recorded overlay had no
    # commit-time scan until the owner ran `pre-commit install` by hand, and only `doctor` warned.
    # Recording installs it, as making one does, in the overlay and nowhere else.
    #
    # Mutation: `mutations/`'s "setup records an existing overlay without its secret scan".
    existing = tmp_path / "overlay"
    _seed_overlay(existing)
    runner = Recorder()
    report = setup(
        "recommended",
        home=tmp_path / "home",
        machine=tmp_path / "config.toml",
        runner=runner,
        overlay=str(existing),
    )
    assert runner.calls == [["pre-commit", "install"]]
    assert runner.cwds == [existing.resolve()]
    assert "installed the commit-time secret scan with `pre-commit install`" in " ".join(
        report.notes
    )


# --- the destination `create:` clones into, asked before GitHub is -------------------------------


@pytest.mark.parametrize("shape", ["a-file", "not-an-overlay", "a-link-to-an-empty-directory"])
def test_create_refuses_a_destination_it_cannot_clone_into_before_github_is_called(
    tmp_path: Path, shape: str
) -> None:
    # `create:` clones into `<home>/<name>`, and the destination was asked only whether it could
    # be searched: a file there, or a directory holding something else, was met by the clone,
    # after `gh repo create` had made a repository on the owner's account that nothing recorded.
    # Both refuse before any `gh` argv now, naming what is there; an empty directory is cloned
    # into, as `git clone` does. A link to an empty directory is not one: read as empty, the clone
    # went through it into wherever it leads. Mutations: `mutations/`'s "setup asks about the
    # create: destination after GitHub" -> the `gh` calls come first; "setup takes a link to an
    # empty directory at a created overlay's destination for no destination" ->
    # `a-link-to-an-empty-directory`.
    from drybag.setup.run import DESTINATION_NOT_A_DIRECTORY, DESTINATION_NOT_AN_OVERLAY

    home = tmp_path / "home"
    home.mkdir()
    destination = home / "drybag-private"
    if shape == "a-file":
        destination.write_text("mine\n", encoding="utf-8")
    elif shape == "a-link-to-an-empty-directory":
        (tmp_path / "elsewhere").mkdir()
        destination.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    else:
        destination.mkdir()
        (destination / "notes.md").write_text("mine\n", encoding="utf-8")
    machine = tmp_path / "config.toml"
    # The template probe is answered and `gh repo create` succeeds, so under the mutation the
    # repository is really created and the floor's refusal follows it, as it did for the owner.
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE})
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=home,
            machine=machine,
            runner=runner,
            overlay="create:octo/drybag-private",
        )
    sentence = DESTINATION_NOT_A_DIRECTORY if shape == "a-file" else DESTINATION_NOT_AN_OVERLAY
    assert str(refused.value) == sentence.format(destination=quoted(str(destination)))
    assert not [argv for argv in runner.calls if argv[0] == "gh"], runner.calls
    assert not machine.exists()


@_ROOT_WRITES_EVERYWHERE
@pytest.mark.parametrize("mode", [0o555, 0o300], ids=["cannot-be-written", "cannot-be-listed"])
@pytest.mark.parametrize("form", ["create", "path"])
def test_an_empty_directory_this_user_cannot_list_and_write_is_refused_naming_that_before_github(
    tmp_path: Path, mode: int, form: str
) -> None:
    # An empty directory read as nothing there whatever its mode: at 555, or another user's,
    # `create:` ran `gh repo create`, whose clone could not write into it, and left a repository
    # nothing recorded; `--overlay <path>` said it "is not there". At 300 neither form can list
    # it, and each said what it holds. Refused before any `gh` argv, naming the cause. Mutation
    # (`mutations/`'s "an empty directory this user cannot write reads as vacant") ->
    # `cannot-be-written` under `create:` reaches `gh repo create`.
    from drybag.setup.run import UNUSABLE_DIRECTORY

    home = tmp_path / "home"
    destination = home / "drybag-private"
    destination.mkdir(parents=True)
    machine = tmp_path / "config.toml"
    overlay = "create:octo/drybag-private" if form == "create" else str(destination)
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    with at_mode(destination, mode, after=0o755), pytest.raises(Refusal) as refused:
        setup("recommended", home=home, machine=machine, runner=runner, overlay=overlay)
    assert str(refused.value) == UNUSABLE_DIRECTORY.format(destination=quoted(str(destination)))
    assert not [argv for argv in runner.calls if argv[0] == "gh"], runner.calls
    assert not machine.exists()


@pytest.mark.parametrize("empty", [False, True], ids=["absent", "empty"])
def test_create_needs_no_yes_and_makes_an_absent_or_empty_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty: bool
) -> None:
    # `--yes` stood in front of `create:` as a consent a model-written command line types as
    # easily as the command itself. Naming `create:<owner>/<name>` is the request. An empty
    # directory at the destination is one `git clone` fills, and was refused as if it held
    # something the clone would meet.
    #
    # The overlay is made under `home` and never `Path.cwd()`: a machine command runs from
    # wherever the owner sits, and `root=Path.cwd()` once made a real `drybag-private/` inside
    # this checkout the first time a test ran the branch. Mutation: `mutations/`'s "setup creates a
    # new overlay under the caller's cwd instead of --home". The `chdir` keeps that mutation's own
    # run from making it there again: its clone lands in `tmp_path` instead.
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    if empty:
        (home / "drybag-private").mkdir(parents=True)
    machine = tmp_path / "config.toml"
    runner = Recorder(answers={_OCTOS_PROBE: _A_TEMPLATE}, on_call=_populate_overlay)
    report = setup(
        "recommended",
        home=home,
        machine=machine,
        runner=runner,
        overlay="create:octo/drybag-private",
    )
    assert report.overlay == overlay_root(machine) == home / "drybag-private"
    assert [argv[:3] for argv in runner.calls if argv[0] == "gh"][-1] == ["gh", "repo", "create"]


# --- one rule for what an overlay is -------------------------------------------------------------


def test_a_render_cut_short_is_not_an_overlay_the_next_run_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A tree is an overlay exactly when its identity record parses, so a render writes the record
    # last. It wrote it first: a render a full disk cut short left the record behind, and the next
    # `setup --overlay` at the same path recorded half a tree, with no `.gitignore` and no secret
    # scan, as "the existing overlay". Mutation (`mutations/`'s "a render writes the identity
    # record first") -> the second run records it and this reddens.
    from drybag import fsops
    from drybag.overlay.identity import NO_RECORD
    from drybag.setup.run import _RECORDING

    real = fsops.write_within
    written: list[str] = []

    def full_disk(root: Path, relative: str, *args: Any, **kwargs: Any) -> None:
        written.append(relative)
        if len(written) == 2:
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), relative)
        real(root, relative, *args, **kwargs)

    monkeypatch.setattr("drybag.scaffold.engine.write_within", full_disk)
    destination = tmp_path.resolve() / "overlay"
    home, machine = tmp_path / "home", tmp_path / "config.toml"
    with pytest.raises(Refusal):
        setup(
            "recommended", home=home, machine=machine, runner=Recorder(), overlay=str(destination)
        )
    monkeypatch.setattr("drybag.scaffold.engine.write_within", real)
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended", home=home, machine=machine, runner=Recorder(), overlay=str(destination)
        )
    shown = quoted(str(destination))
    assert str(refused.value) == f"{NO_RECORD.format(root=shown)}; {_RECORDING}"
    assert overlay_root(machine) is None


def test_setup_says_when_it_records_an_overlay_root_other_than_the_recorded_one(
    tmp_path: Path,
) -> None:
    # `--overlay <path>` naming nothing renders an overlay there, so a mistyped path is a new
    # overlay and not a refusal, and the machine's root moved to it without a word: every later
    # `attach` then read an empty overlay. The run that moves it says so, naming the root it
    # replaced; the run that records the same root again says nothing of it.
    from drybag.setup.run import REPLACED_ROOT

    first, second = tmp_path.resolve() / "overlay", tmp_path.resolve() / "overlai"
    _seed_overlay(first)
    _seed_overlay(second)
    home, machine = tmp_path / "home", tmp_path / "config.toml"
    setup("recommended", home=home, machine=machine, runner=Recorder(), overlay=str(first))
    again = setup("recommended", home=home, machine=machine, runner=Recorder(), overlay=str(first))
    moved = setup("recommended", home=home, machine=machine, runner=Recorder(), overlay=str(second))
    said = REPLACED_ROOT.format(previous=quoted(str(first)))
    assert said not in again.notes
    assert said in moved.notes


@pytest.mark.parametrize("value", ["", "relative-home"], ids=["empty", "relative"])
def test_an_overlay_under_a_home_that_names_none_is_refused_and_never_read_against_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # `--overlay '~/x'` was expanded with `Path.expanduser`, which reads an empty `HOME` as `/` and
    # a relative one against whatever directory the command ran from: with `HOME=relative-home`,
    # `setup` rendered an overlay under the working directory and recorded it as the machine's
    # trust anchor. A leading `~` is read as `config.machine.owner_home` reads it, as the machine
    # file's own `[overlay] root` is, and a home that names none is refused.
    from drybag.setup.run import NO_HOME_FOR_OVERLAY

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", value)
    machine = tmp_path / "config.toml"
    with pytest.raises(Refusal) as refused:
        setup(
            "recommended",
            home=tmp_path / "home",
            machine=machine,
            runner=Recorder(),
            overlay="~/x",
        )
    assert str(refused.value) == NO_HOME_FOR_OVERLAY.format(overlay=quoted("~/x"))
    assert sorted(path.name for path in tmp_path.iterdir()) == []
