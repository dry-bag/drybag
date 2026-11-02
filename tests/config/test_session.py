"""What a session runs on (`src/stayfixed/config/session.py`): the project's configuration read the
way a session must, the owner's layer, and one warning about each file it could not use whole.

`session_config` never raises for anything a repository or a machine file holds, so every case
below is a document a command refuses and a session reads anyway, or drops with a warning."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

import pytest

from stayfixed import __version__, binding
from stayfixed.config.classes import LayerName
from stayfixed.config.loader import NOTE_REBUILT_LIMIT, NOTE_REMOVAL_LIMIT
from stayfixed.config.owner import resolve_owner
from stayfixed.config.paths import data_directory
from stayfixed.config.schema import Paths
from stayfixed.config.session import (
    FALLBACK_WARNING,
    MACHINE_FILE_WARNING,
    NEWER_RELEASE_WARNING,
    NOTED_WARNING,
    SESSION_READ_LIMIT,
    TOO_LARGE_WARNING,
    TOO_MANY_WARNING,
    UNUSABLE_WARNING,
    SessionConfig,
    bound_config,
    session_config,
)
from stayfixed.doctor.checks import VERSION_AHEAD
from tests.config import test_overlay_layers as overlays
from tests.config.test_loader import HEAD, MINIMAL
from tests.gitfixture import needs_git

_MAJOR, _MINOR, _ = (int(part) for part in __version__.split(".")[:3])
# `HEAD` with a `version` one minor above the running one.
HEAD_LATER = HEAD.replace('version = "0.1.0"', f'version = "{_MAJOR}.{_MINOR + 1}.0"')


def write(root: Path, text: str) -> None:
    (root / "stayfixed.toml").write_text(text, encoding="utf-8")


def none(root: Path) -> Path:
    """A machine file that is not there: no owner's values but the preset's."""
    return root / "none.toml"


def broken_machine(root: Path) -> Path:
    path = root / "machine.toml"
    path.write_text("[personal\n", encoding="utf-8")
    return path


def unparseable(root: Path) -> None:
    write(root, "[[[")


def not_utf8(root: Path) -> None:
    (root / "stayfixed.toml").write_bytes(MINIMAL.encode("utf-8") + b"\xff\n")


def symlink_to_loadable(root: Path) -> None:
    (root / "real.toml").write_text(MINIMAL, encoding="utf-8")
    os.symlink(root / "real.toml", root / "stayfixed.toml")


def symlink_to_dev_zero(root: Path) -> None:
    os.symlink("/dev/zero", root / "stayfixed.toml")


def test_a_session_parses_its_preset_once(tmp_path: Path) -> None:
    # A hook resolves the owner's layer over the preset and then loads the project over it, and
    # each asked the package to parse the same TOML again, on every hook: the preset is asked for
    # at least twice and parsed once. Mutation (`mutations/`'s "the preset is parsed on every
    # load"): every load parses past the cache, which then records no parse at all.
    from stayfixed import presets

    write(tmp_path, MINIMAL)
    presets._parsed.cache_clear()
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is not None
    asked = presets._parsed.cache_info()
    assert asked.misses == 1
    assert asked.hits >= 1


def test_no_file_is_no_config_and_no_warning(tmp_path: Path) -> None:
    # No mutation of its own: nothing here is decided, the file is simply absent; the cases below
    # are what each arm reddens.
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is None and got.warnings == ()


def test_no_project_root_still_has_the_owners_layer(tmp_path: Path) -> None:
    # A hook with no project root runs the guards on the owner's layer all the same. Mutation
    # (`mutations/`'s "a session with no project root reads no machine file"): the guard is on.
    machine = tmp_path / "machine.toml"
    machine.write_text("[guards]\nbg_cleanup = false\n", encoding="utf-8")
    got = session_config(None, machine=machine)
    assert got.config is None and got.warnings == ()
    assert got.owner.guards.bg_cleanup is False


@pytest.mark.parametrize(
    "make",
    [unparseable, not_utf8, symlink_to_loadable, symlink_to_dev_zero],
    ids=lambda f: f.__name__,
)
def test_a_file_that_cannot_be_read_as_toml_falls_back_whole(
    tmp_path: Path, make: Callable[[Path], None]
) -> None:
    # A link meets the rule before anything follows it, so one to a loadable file and one to
    # `/dev/zero` get the same answer. Mutations (`mutations/`'s "a session lets a symlinked
    # stayfixed.toml raise" -> both links raise; "a session lets a file that is not TOML raise"
    # -> `unparseable` raises).
    make(tmp_path)
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is None and got.warnings == (FALLBACK_WARNING,)


def test_a_newer_release_keeps_every_other_setting(tmp_path: Path) -> None:
    # A `stayfixed.toml` a newer release wrote: an unknown section and an unknown enum value
    # together, and the raised budget beside them stands. Mutation (`mutations/`'s "session_config
    # answers no configuration for a file that loads with notes"): the budget goes with the file.
    write(
        tmp_path,
        HEAD_LATER + '[project]\nname = "p"\n[newer]\n[memory]\nmode = "cloud"\n'
        "[budgets]\nagents_md_lines = 900\n",
    )
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is not None
    assert got.config.budgets.configured["agents_md_lines"] == 900
    assert got.warnings == (NEWER_RELEASE_WARNING.format(count=2),)
    # Mutation (`mutations/`'s "a session lists no key it noted"): `noted` is empty.
    assert got.noted == ("newer", "memory.mode")


def test_a_file_from_this_release_with_notes_is_not_called_newer(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the session warns of a newer release for every file with notes"):
    # this one is called newer too.
    write(tmp_path, MINIMAL + '[memory]\nmode = "cloud"\n')
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is not None
    assert got.warnings == (NOTED_WARNING.format(count=1),)


def test_the_newer_release_warning_gives_doctors_remedy() -> None:
    # One way out of a file a later release wrote, in both places that name it. No mutation: a
    # wording held equal across two constants.
    assert VERSION_AHEAD.split(":")[0] in NEWER_RELEASE_WARNING


def test_a_broken_machine_file_keeps_the_project(tmp_path: Path) -> None:
    # A machine file that is not TOML costs the session nothing of the project's, and is named.
    # Mutation (`mutations/`'s "a session says nothing of a machine file it could not use"): the
    # warning goes.
    write(tmp_path, MINIMAL)
    machine = broken_machine(tmp_path)
    got = session_config(tmp_path, machine=machine)
    assert got.config is not None
    assert got.warnings == (MACHINE_FILE_WARNING.format(path=machine),)


@pytest.mark.parametrize("root", ["no-file", "no-root"])
def test_a_broken_machine_file_is_named_with_no_project_configuration(
    tmp_path: Path, root: str
) -> None:
    # A machine file that is not TOML, with nothing of the project's to read: no `stayfixed.toml`,
    # or a hook with no project root. The guards still run on the preset's owner values, and the
    # warning still names the machine file. Mutation (`mutations/`'s "a session with no project
    # configuration says nothing of a machine file it could not use"): the warning goes.
    machine = broken_machine(tmp_path)
    got = session_config(tmp_path if root == "no-file" else None, machine=machine)
    assert got.config is None
    assert got.owner.guards.bg_cleanup is True
    assert got.owner.personal == resolve_owner(None).personal
    assert got.warnings == (MACHINE_FILE_WARNING.format(path=machine),)
    assert got.project_warnings == ()


@pytest.mark.parametrize("root", ["no-file", "no-root"])
def test_a_usable_machine_file_with_no_project_configuration_says_nothing(
    tmp_path: Path, root: str
) -> None:
    # The control for the case above: a machine file that loads whole is no warning. No mutation
    # of its own: the warning appearing here would be the case above's arm firing on every file.
    machine = tmp_path / "machine.toml"
    machine.write_text('[personal]\npreset = "fr"\n', encoding="utf-8")
    got = session_config(tmp_path if root == "no-file" else None, machine=machine)
    assert got.config is None and got.warnings == ()
    assert got.owner.personal.preset == "fr"


def test_both_broken(tmp_path: Path) -> None:
    # One warning about each file, the project's first. Mutation: as above, the machine file's
    # warning goes.
    unparseable(tmp_path)
    machine = broken_machine(tmp_path)
    got = session_config(tmp_path, machine=machine)
    assert got.config is None
    assert got.warnings == (FALLBACK_WARNING, MACHINE_FILE_WARNING.format(path=machine))
    assert got.project_warnings == (FALLBACK_WARNING,)


def _docs_symlink(root: Path) -> str:
    (root.parent / "outside").mkdir()
    os.symlink(root.parent / "outside", root / "docs")
    return MINIMAL


UNUSABLE = [
    pytest.param(
        lambda root: MINIMAL.replace('name = "sample"', 'name = "has space"'),
        "project.name",
        id="project-name",
    ),
    pytest.param(
        lambda root: MINIMAL.replace('version = "0.1.0"', "version = 1"),
        "stayfixed.version",
        id="version",
    ),
    pytest.param(_docs_symlink, "paths.architecture", id="docs-symlink"),
    pytest.param(lambda root: "project = 1\n" + HEAD, "project", id="project-not-a-table"),
]


def test_more_unusable_keys_than_the_note_path_reads_drop_the_project(tmp_path: Path) -> None:
    # One past `NOTE_REMOVAL_LIMIT`: the floor, with a warning in stayfixed's own words, and the
    # owner's layer still read. Mutation (`mutations/`'s "the NOTE path removes every key it cannot
    # use, however many"): the project loads with 65 notes.
    gates = "".join(f"g{n} = {{ run = [] }}\n" for n in range(NOTE_REMOVAL_LIMIT + 1))
    write(tmp_path, MINIMAL + "[gates.custom]\n" + gates)
    got = session_config(tmp_path, machine=none(tmp_path))
    warning = TOO_MANY_WARNING.format(limit=NOTE_REMOVAL_LIMIT)
    assert got.config is None and got.warnings == (warning,)
    assert got.project_warnings == (warning,) and got.machine_warnings == ()


def test_a_long_file_says_how_few_unusable_settings_it_is_read_past(tmp_path: Path) -> None:
    # A long file is read past fewer unusable keys than a short one (`loader.NOTE_REBUILT_LIMIT`),
    # and the warning says how many. No mutation of its own: the bound is held by
    # `tests/config/test_loader_note.py::test_a_long_document_is_read_past_fewer_unusable_keys`;
    # by hand, the warning formatted with `NOTE_REMOVAL_LIMIT` says 64 here.
    runnable = "".join(f'v{n} = {{ run = ["true"] }}\n' for n in range(3_000))
    text = MINIMAL + "[gates.custom]\n" + runnable
    limit = NOTE_REBUILT_LIMIT // len(text)
    assert limit < NOTE_REMOVAL_LIMIT
    write(tmp_path, text + "".join(f"g{n} = {{ run = [] }}\n" for n in range(limit + 1)))
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is None and got.warnings == (TOO_MANY_WARNING.format(limit=limit),)


def _padded(size: int) -> str:
    """`MINIMAL`, then a comment that makes the file exactly `size` bytes long."""
    return MINIMAL + "#" + "x" * (size - len(MINIMAL) - 2) + "\n"


def test_a_file_longer_than_a_session_reads_is_read_no_further(tmp_path: Path) -> None:
    # The parse and every build of the NOTE load cost in proportion to the file, and a hook that
    # runs past its timeout loses the call, so a session reads `SESSION_READ_LIMIT` bytes
    # at most and drops a longer file whole, in words of its own. Mutation (`mutations/`'s "a
    # session reads stayfixed.toml as far as a command does"): the longer file loads. By hand, the
    # `TooLargeDocument` arm taken out: the warning is `FALLBACK_WARNING`, which sends the owner
    # to `stayfixed docs check`, where the file loads.
    write(tmp_path, _padded(SESSION_READ_LIMIT + 1))
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is None and got.warnings == (TOO_LARGE_WARNING,)
    # The control: a file of exactly the cap is read and loads.
    write(tmp_path, _padded(SESSION_READ_LIMIT))
    assert (tmp_path / "stayfixed.toml").stat().st_size == SESSION_READ_LIMIT
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is not None and got.warnings == ()


# Custom gates that run, every one of them enforced, in a file just under what a session reads,
# beside `[paths]` values that fail containment: each of those is refused after the enforced list
# is checked, so each removal builds the whole file again, every gate and its enforcement included.
ENFORCED_GATES = 6_500
UNCONTAINED = [field.name for field in fields(Paths)][:4]


def long_file_of_gates_that_run() -> str:
    """`ENFORCED_GATES` enforced gates that run and the `UNCONTAINED` paths, under the read cap;
    `tests/hooks/test_floor.py` times a hook over the same file."""
    names = [f"v{n}" for n in range(ENFORCED_GATES)]
    enforced = ", ".join(f'"{name}"' for name in names)
    head = HEAD.replace("\n", f"\nenforced = [{enforced}]\n", 1)
    gates = "".join(f'{name} = {{ run = ["true"] }}\n' for name in names)
    paths = "".join(f'{name} = "../x"\n' for name in UNCONTAINED)
    return head + '[project]\nname = "sample"\n[paths]\n' + paths + "[gates.custom]\n" + gates


def test_a_long_file_of_gates_that_run_is_read_past_every_removal_its_length_allows(
    tmp_path: Path,
) -> None:
    # The file the hook's timing test reads (`tests/hooks/test_floor.py`'s
    # `test_a_long_file_of_gates_that_run_never_outlasts_the_hook`), held to the shape that test
    # is about: under the read cap, read past exactly as many removals as its length allows, each
    # one a rebuild of every gate and of its enforcement, and still loaded. It is not the costliest
    # file a session reads, since a gate spelled out and enforced takes more than twice the bytes of
    # the densest one; `densest_file` below is.
    text = long_file_of_gates_that_run()
    assert len(text.encode()) <= SESSION_READ_LIMIT
    assert NOTE_REBUILT_LIMIT // len(text) == len(UNCONTAINED)  # every removal the length allows
    write(tmp_path, text)
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is not None and len(got.config.stayfixed.enforced) == ENFORCED_GATES
    assert got.noted == tuple(f"paths.{name}" for name in UNCONTAINED)


# Keys the densest file holds that the NOTE load cannot use: the `UNCONTAINED` paths, and custom
# gates that cannot run, as many as the NOTE load would remove were its removals bounded by their
# count alone.
UNRUNNABLE_GATES = NOTE_REMOVAL_LIMIT - len(UNCONTAINED)


def densest_file(*, unusable: bool = True) -> str:
    """The costliest file a session reads: dotted custom gates that run, `g<hex>.run=[""]`, the
    most gates to the byte, up to the read cap, beside `NOTE_REMOVAL_LIMIT` keys the NOTE load
    cannot use, each refused only once every gate before it is built: the `UNRUNNABLE_GATES` named
    to sort after every gate that runs, then the `UNCONTAINED` paths, refused after every gate.
    Not `unusable`, the same gates fill it alone, and it is built once.
    `tests/hooks/test_floor.py` times a hook over both."""
    paths = "".join(f'{name} = "../x"\n' for name in UNCONTAINED) if unusable else ""
    count = UNRUNNABLE_GATES if unusable else 0
    unrunnable = "".join(f"zz{n}.run=[]\n" for n in range(count))
    text = MINIMAL + "[paths]\n" + paths + "[gates.custom]\n" + unrunnable
    gates: list[str] = []
    room = SESSION_READ_LIMIT - len(text)
    while room >= len(gate := f'g{len(gates):x}.run=[""]\n'):
        gates.append(gate)
        room -= len(gate)
    return text + "".join(gates)


def test_the_densest_file_a_session_reads_is_built_as_often_as_its_length_allows(
    tmp_path: Path,
) -> None:
    # The file the hook's timing test reads (`tests/hooks/test_floor.py`'s
    # `test_the_densest_file_a_session_reads_never_outlasts_the_hook`), held to the shape that
    # makes it the costliest: filled to the read cap, so its length allows the fewest removals,
    # with more unusable keys than that, each a rebuild of every gate, and so dropped whole after
    # the last removal its length allows. Mutation (`mutations/`'s "the NOTE path's removals are
    # bounded by their count alone"): the file loads with 64 notes.
    text = densest_file()
    assert SESSION_READ_LIMIT - len('g10000.run=[""]\n') < len(text.encode()) <= SESSION_READ_LIMIT
    limit = NOTE_REBUILT_LIMIT // len(text)
    assert 0 < limit < NOTE_REMOVAL_LIMIT  # bounded by its length, and not by the count
    write(tmp_path, text)
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is None and got.warnings == (TOO_MANY_WARNING.format(limit=limit),)


@pytest.mark.parametrize(("make", "key"), UNUSABLE)
def test_a_key_nothing_can_stand_in_for_drops_the_project_and_names_it(
    tmp_path: Path, make: Callable[[Path], str], key: str
) -> None:
    # A key nothing can stand in for drops the project configuration whole, and the warning
    # names the key the document got wrong, never one it calls missing. The owner's layer still
    # stands, so the guards run. Mutation (`mutations/`'s "a session names no key it could not
    # use"): the warning says "a setting".
    root = tmp_path / "root"
    root.mkdir()
    write(root, make(root))
    machine = root / "machine.toml"
    machine.write_text("[guards]\nbg_cleanup = false\n", encoding="utf-8")
    got = session_config(root, machine=machine)
    assert got.config is None
    assert got.warnings == (UNUSABLE_WARNING.format(key=key),)
    assert got.owner.guards.bg_cleanup is False


def test_a_required_key_the_document_never_wrote_drops_the_project_and_names_it(
    tmp_path: Path,
) -> None:
    # No `[project] name` at all: a command refuses the document whole, and a session still
    # goes on. Mutation (`mutations/`'s "a session names no key a document is missing"): the
    # warning says "a setting".
    write(tmp_path, HEAD)
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is None
    assert got.warnings == (UNUSABLE_WARNING.format(key="project.name"),)


@pytest.mark.parametrize("value", ['"future"', "1"], ids=["unshipped", "not-a-string"])
def test_a_preset_this_build_cannot_use_is_one_note(tmp_path: Path, value: str) -> None:
    # The loader resets the key with its note, and the owner's layer stands on the fallback
    # preset without a note of its own, which would have read as the machine file's fault.
    # Mutation (`mutations/`'s "the owner's layer is handed a preset the loader resets"): the
    # owner's layer is asked to load a preset this build cannot, and the session raises.
    write(tmp_path, MINIMAL.replace('preset = "recommended"', f"preset = {value}"))
    got = session_config(tmp_path, machine=none(tmp_path))
    assert got.config is not None and got.config.stayfixed.preset == "recommended"
    assert got.owner.notes == ()
    assert got.warnings == (NOTED_WARNING.format(count=1),)


def test_a_repository_sets_the_guards_default_and_the_machine_file_overrides_it(
    tmp_path: Path,
) -> None:
    # The repository's `[guards]` is a default: with no machine-file `[guards]` it switches the
    # background hint off, and the machine file's `true` switches it back on.
    write(tmp_path, MINIMAL + "[guards]\nbg_cleanup = false\n")
    assert session_config(tmp_path, machine=none(tmp_path)).guards.bg_cleanup is False
    machine = tmp_path / "machine.toml"
    machine.write_text("[guards]\nbg_cleanup = true\n", encoding="utf-8")
    assert session_config(tmp_path, machine=machine).guards.bg_cleanup is True


def _guarded(tmp_path: Path, given: dict[LayerName, bool]) -> SessionConfig:
    """A bound checkout's session where each layer of `given` sets `bg_cleanup` to its value."""

    def guard(layer: LayerName) -> str:
        return f"[guards]\nbg_cleanup = {str(given[layer]).lower()}\n" if layer in given else ""

    root = overlays.project(tmp_path)
    write(root, overlays.MINIMAL + guard(LayerName.REPOSITORY))
    recorded = overlays.overlay(
        tmp_path,
        common=guard(LayerName.OVERLAY_COMMON),
        sample=guard(LayerName.OVERLAY_PROJECT),
    )
    binding.record(root, "sample", None)
    machine = overlays.machine(tmp_path, recorded, guard(LayerName.MACHINE_FILE))
    return session_config(root, machine=machine)


REPOSITORY, COMMON, PROJECT, MACHINE = (
    LayerName.REPOSITORY,
    LayerName.OVERLAY_COMMON,
    LayerName.OVERLAY_PROJECT,
    LayerName.MACHINE_FILE,
)


@needs_git
@pytest.mark.parametrize(
    ("given", "on", "layer"),
    [
        pytest.param({}, True, LayerName.PRESET, id="unset"),
        pytest.param({REPOSITORY: False}, False, REPOSITORY, id="repository"),
        pytest.param({COMMON: False}, False, COMMON, id="overlay-common"),
        pytest.param({PROJECT: False}, False, PROJECT, id="overlay-project"),
        pytest.param({MACHINE: False}, False, MACHINE, id="machine-file"),
        pytest.param({REPOSITORY: False, COMMON: True}, True, COMMON, id="common-over-repository"),
        pytest.param({COMMON: False, PROJECT: True}, True, PROJECT, id="project-over-common"),
        pytest.param({PROJECT: False, MACHINE: True}, True, MACHINE, id="machine-over-project"),
        pytest.param(
            {REPOSITORY: False, COMMON: False, PROJECT: False, MACHINE: True},
            True,
            MACHINE,
            id="machine-last",
        ),
    ],
)
def test_each_layer_sets_changes_and_unsets_the_guards_with_the_machine_file_last(
    tmp_path: Path, given: dict[LayerName, bool], on: bool, layer: LayerName
) -> None:
    # Every layer the key's class admits, set alone, changed by the layer above it, and unset;
    # the preset's default stands where no layer sets it, and the machine file wins over all.
    session = _guarded(tmp_path, given)
    assert session.guards.bg_cleanup is on
    assert session.resolution.provenance["guards.bg_cleanup"] is layer


def a_bound_checkout_with_no_file(tmp_path: Path) -> tuple[Path, Path]:
    """A checkout this machine binds to the overlay's project `sample`, with no `stayfixed.toml`;
    the project's layer sets a startup budget. Returns the checkout and the machine file."""
    root = overlays.project(tmp_path)
    recorded = overlays.overlay(tmp_path, sample=overlays.budgets(900))
    binding.record(root, "sample", None)
    (root / "stayfixed.toml").unlink()
    return root, overlays.machine(tmp_path, recorded)


@needs_git
def test_a_bound_checkout_with_no_file_gets_the_configuration_of_its_project(
    tmp_path: Path,
) -> None:
    # The binding record names the project and the overlay's layers give its values. Mutation:
    # `mutations/`'s "bound_config answers for an unbound checkout" is the other side of this.
    root, machine = a_bound_checkout_with_no_file(tmp_path)
    config = bound_config(root, machine=machine, owner=None)
    assert config is not None
    assert config.project.name == "sample"
    assert config.budgets.effective("startup_rules_words") == 900


@needs_git
def test_an_unbound_checkout_with_no_file_has_no_bound_config(tmp_path: Path) -> None:
    # A clone carries no binding id, so no overlay layer and no project name reach it: the
    # configuration comes only through this machine's record. Mutation: `mutations/`'s
    # "bound_config answers for an unbound checkout".
    root, machine = a_bound_checkout_with_no_file(tmp_path)
    id = binding.read_id(root)
    assert id is not None
    (data_directory() / binding.BINDINGS / f"{id}.toml").unlink()
    assert bound_config(root, machine=machine, owner=None) is None


@needs_git
def test_a_checkout_with_its_own_file_reads_it_first(tmp_path: Path) -> None:
    # The file names `sample`, the binding record another project: the file's resolution is the
    # one `command_config` gives as before, and the record is not consulted for the name.
    root = overlays.project(tmp_path)
    recorded = overlays.overlay(tmp_path)
    binding.record(root, "other", None)
    config = bound_config(root, machine=overlays.machine(tmp_path, recorded), owner=None)
    assert config is not None and config.project.name == "sample"


@needs_git
def test_methodology_hooks_still_answer_nothing_without_a_file(tmp_path: Path) -> None:
    # `session_config` is the hooks' reading and is not `bound_config`: the guards of the
    # methodology side have a project configuration only where the repository has a file.
    root, machine = a_bound_checkout_with_no_file(tmp_path)
    assert bound_config(root, machine=machine, owner=None) is not None
    got = session_config(root, machine=machine)
    assert got.config is None and got.warnings == ()
