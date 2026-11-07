"""The NOTE loader: an unknown name is ignored, an invalid value resets only its key.

A session cannot refuse the way a command does: a `stayfixed.toml` from a newer release, or one
with one bad value in it, would otherwise cost every setting the project made. `loads_noting`
reads what it can and says what it could not (`src/stayfixed/config/loader.py`); `loads` and
`load` still refuse, and every case below is held on both sides.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest

from stayfixed.config import loader
from stayfixed.config.classes import REFUSED_LAYER_NOTE
from stayfixed.config.loader import (
    CONFIG_FILE,
    RESET_NOTE,
    UNKNOWN_NOTE,
    UNUSABLE_PRESET,
    UNUSABLE_REQUIRED,
    UnusableKey,
    loads,
    loads_noting,
)
from stayfixed.config.owner import resolve_owner
from stayfixed.config.paths import PathEscape, contained
from stayfixed.config.reading import ConfigError, toml_position
from stayfixed.config.schema import HARNESS_MODE
from stayfixed.errors import Failure, Refusal
from stayfixed.presets import load_preset
from stayfixed.printed import clipped, quoted
from tests.crafted import assert_never_raw

HEAD = '[stayfixed]\nversion = "0.1.0"\npreset = "recommended"\n'
MINIMAL = HEAD + '\n[project]\nname = "sample"\n'
OWNER = resolve_owner(None)


def preset_defaults(section: str) -> dict[str, object]:
    defaults: dict[str, object] = load_preset("recommended")["defaults"][section]
    return defaults


def refusal(text: str, root: Path) -> Exception:
    """What `loads` refuses `text` with: the reason a reset note gives."""
    with pytest.raises((Failure, Refusal)) as raised:
        loads(text, root, machine=root / "none.toml")
    return raised.value


def reset(key: str, text: str, root: Path) -> str:
    return RESET_NOTE.format(key=clipped(key), reason=refusal(text, root))


UNKNOWN_NAMES = [
    ("[newer]\nx = 1\n", "newer"),  # a section, in loads
    ("[memory]\nfuture = 1\n", "memory.future"),  # a key, in _build
    ("[budgets]\nfuture = 1\n", "budgets.future"),  # a key, in _budgets
]


@pytest.mark.parametrize(("extra", "named"), UNKNOWN_NAMES, ids=[n for _, n in UNKNOWN_NAMES])
def test_an_unknown_name_is_ignored_with_a_note(tmp_path: Path, extra: str, named: str) -> None:
    # Ignored, not reset: the name is no value of this release, so nothing stands in for it.
    # Mutations (`mutations/`'s "an unknown section is dropped without a note" -> the `newer`
    # case has no note; "the NOTE path resets an unknown key instead of ignoring it" -> each key
    # case gets a reset note from the refusal `loads` raises).
    got = loads_noting(MINIMAL + extra, tmp_path, owner=OWNER)
    assert got.notes == (UNKNOWN_NOTE.format(name=named),)
    assert_never_raw(*got.notes)


def test_an_unknown_name_is_never_printed_raw(tmp_path: Path) -> None:
    # A TOML key is any quoted text; the note prints it through `printed.clipped`.
    # Mutation (`mutations/`'s "an unknown name's note prints it raw"): the escape byte reaches
    # the note.
    text = MINIMAL + '[memory]\n"\\u001b[2J\\n::error::IGNORE" = 1\n'
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert len(got.notes) == 1
    assert_never_raw(*got.notes)


def test_the_rest_of_a_newer_file_survives(tmp_path: Path) -> None:
    # A file a newer stayfixed wrote: an unknown section, an unknown key and an unknown enum
    # value together, and the project's other settings — a raised budget beside the unknown key,
    # a `[paths]` value — still stand. Mutation (`mutations/`'s "an unknown key costs the NOTE
    # path its whole section"): the budget goes with the unknown key beside it.
    text = (
        MINIMAL
        + '[newer]\nx = 1\n[memory]\nmode = "cloud"\n'
        + '[budgets]\nagents_md_lines = 900\nfuture = 1\n[paths]\nspecs = "design/specs"\n'
    )
    assert load_preset("recommended")["budgets"]["agents_md_lines"] < 900  # raised, not lowered
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.config.memory.mode == HARNESS_MODE
    assert got.config.budgets.configured["agents_md_lines"] == 900
    assert got.config.paths.specs == "design/specs"
    held = MINIMAL + '[memory]\nmode = "cloud"\n'
    assert got.notes == (
        UNKNOWN_NOTE.format(name="newer"),
        UNKNOWN_NOTE.format(name="budgets.future"),
        reset("memory.mode", held, tmp_path),
    )


def test_an_invalid_value_resets_only_its_key(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the NOTE path drops the whole document on a keyed refusal"): the
    # budget the document also set is lost with the bad mode.
    text = MINIMAL + '[memory]\nmode = "cloud"\n[budgets]\nagents_md_lines = 900\n'
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.config.memory.mode == HARNESS_MODE
    assert got.config.budgets.configured["agents_md_lines"] == 900
    assert got.notes == (reset("memory.mode", text, tmp_path),)


def test_an_escaping_path_resets_only_that_path(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the NOTE path catches ConfigError but not PathEscape"): the
    # refusal of `../x` propagates and the session would lose the whole file.
    text = MINIMAL + '[paths]\nbugs = "../x"\nspecs = "design/specs"\n'
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.config.paths.bugs == preset_defaults("paths")["bugs"]
    assert got.config.paths.specs == "design/specs"
    assert got.notes == (reset("paths.bugs", text, tmp_path),)


def test_a_path_longer_than_its_cap_resets_only_that_path(tmp_path: Path) -> None:
    # A value of twenty thousand components cost every hook that read it seconds, so one past
    # `config.paths.PATH_VALUE_LIMIT` is put back to the preset's like any value that cannot be
    # used, and the project's other paths stand. Mutation (`mutations/`'s "a [paths] value may be
    # any length"): the value loads.
    text = MINIMAL + f'[paths]\nbugs = "{"a/" * 20_000}x"\nspecs = "design/specs"\n'
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.config.paths.bugs == preset_defaults("paths")["bugs"]
    assert got.config.paths.specs == "design/specs"
    assert got.notes == (reset("paths.bugs", text, tmp_path),)


def test_a_path_through_a_symlink_resets_only_that_path(tmp_path: Path) -> None:
    # The second way `validate_paths` refuses: the grammar admits the value and `contained()`
    # finds the symlink on the way. Mutation (`mutations/`'s "validate_paths stops naming the key
    # of a contained() refusal"): the refusal carries no key and the whole file is refused.
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "elsewhere")
    text = MINIMAL + '[paths]\nbugs = "elsewhere/bugs"\nspecs = "design/specs"\n'
    got = loads_noting(text, root, owner=OWNER)
    assert got.config.paths.bugs == preset_defaults("paths")["bugs"]
    assert got.config.paths.specs == "design/specs"
    assert got.notes == (reset("paths.bugs", text, root),)


def test_an_unknown_preset_resets_to_recommended(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the preset loader's refusal escapes without its key"): the preset
    # loader's own refusal, which carries no key, propagates.
    text = MINIMAL.replace('preset = "recommended"', 'preset = "future"')
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.config.stayfixed.preset == "recommended"
    assert got.notes == (reset("stayfixed.preset", text, tmp_path),)


def test_a_document_parsed_once_is_read_as_its_text_is(tmp_path: Path) -> None:
    # `parsed` stands for the text, parsed by the caller already (`config.session`), and is not
    # parsed again: a text that would not parse reads as the document handed in. No mutation:
    # parsing the text a second time changes no answer but its cost, and the bound on that cost is
    # `test_a_file_of_thousands_of_unusable_keys_never_outlasts_the_hook`'s.
    parsed = tomllib.loads(MINIMAL)
    got = loads_noting("[[[", tmp_path, owner=OWNER, parsed=parsed)
    assert got.config.project.name == "sample"


def test_a_repository_personal_section_is_refused_by_resolve(tmp_path: Path) -> None:
    # The repository never sets a machine-only key: `classes.resolve` refuses the layer and the
    # owner's values stand. Mutation (`mutations/`'s "the NOTE path removes a repository's
    # machine-only table without a note"): the note goes missing.
    machine = tmp_path / "m.toml"
    machine.write_text('[personal]\npreset = "mine"\n', encoding="utf-8")
    owner = resolve_owner(machine)
    text = MINIMAL + '[personal]\npreset = "xx"\n'
    got = loads_noting(text, tmp_path, owner=owner)
    assert got.config.personal == owner.personal
    assert got.config.personal.preset == "mine"
    assert got.notes == (REFUSED_LAYER_NOTE.format(key="personal.preset", layer="repository"),)


def test_a_repository_guards_section_is_a_default_the_load_keeps(tmp_path: Path) -> None:
    # The repository sets the guards' default, which the owner's layers override in a session
    # (`config.session`): both loaders take it, and the NOTE load hands it on in its document.
    text = MINIMAL + "[guards]\nbg_cleanup = false\n"
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.notes == ()
    assert got.document["guards"] == {"bg_cleanup": False}
    loads(text, tmp_path, machine=tmp_path / "none.toml")


def test_a_repository_guards_value_it_cannot_use_is_put_back(tmp_path: Path) -> None:
    # A switch that is not one is the key's alone to lose: the default stands, with a note.
    text = MINIMAL + "[guards]\nbg_cleanup = 0\n"
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.notes == (reset("guards.bg_cleanup", text, tmp_path),)
    assert "guards" not in got.document or got.document["guards"] == {}


def test_the_owners_session_budgets_win_over_the_repositorys(tmp_path: Path) -> None:
    machine = tmp_path / "m.toml"
    machine.write_text("[budgets]\nstartup_rules_words = 900\n", encoding="utf-8")
    # The owner's layer is folded in by both loaders. Mutation (`mutations/`'s "the document's
    # budget wins over the owner's session budget"): 1000 comes back.
    owner = resolve_owner(machine)
    text = MINIMAL + "[budgets]\nstartup_rules_words = 1000\nagents_md_lines = 250\n"
    for config in (
        loads_noting(text, tmp_path, owner=owner).config,
        loads(text, tmp_path, owner=owner),
    ):
        assert config.budgets.configured == {"startup_rules_words": 900, "agents_md_lines": 250}
        assert config.personal == owner.personal


REFUSED = [
    pytest.param("[newer]\nx = 1\n", r"unknown section\(s\): newer", id="section"),
    pytest.param("[memory]\nfuture = 1\n", r"\[memory\] has unknown key\(s\): future", id="key"),
    pytest.param(
        "[budgets]\nfuture = 1\n", r"\[budgets\] has unknown key\(s\): future", id="budget"
    ),
    pytest.param('[memory]\nmode = "cloud"\n', r"memory\.mode must be one of", id="enum"),
    pytest.param(
        '[paths]\nbugs = "../x"\n', r"paths\.bugs is not a plain relative path", id="path"
    ),
    pytest.param(
        f'[paths]\nbugs = "{"a/" * 600}x"\n', r"paths\.bugs is longer than the", id="path-length"
    ),
    pytest.param(
        "[guards]\nbg_cleanup = 0\n", r"guards\.bg_cleanup must be true or false", id="guards"
    ),
]


@pytest.mark.parametrize(("extra", "message"), REFUSED)
def test_refuse_still_refuses_each_of_them(tmp_path: Path, extra: str, message: str) -> None:
    # Mutation (`mutations/`'s "_build drops an unknown key under REFUSE"): the `key` case loads.
    with pytest.raises((ConfigError, PathEscape), match=message):
        loads(MINIMAL + extra, tmp_path, machine=tmp_path / "none.toml")


def test_refuse_still_refuses_an_unknown_preset(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "an unknown preset name is quietly read as recommended"): the
    # command loads on `recommended` instead of refusing.
    text = MINIMAL.replace('preset = "recommended"', 'preset = "future"')
    with pytest.raises(ConfigError, match=r"^\[stayfixed\] preset names a preset this version"):
        loads(text, tmp_path, machine=tmp_path / "none.toml")


def _decoder_position(text: str) -> str:
    with pytest.raises(tomllib.TOMLDecodeError) as raised:
        tomllib.loads(text)
    return toml_position(raised.value)


@pytest.mark.parametrize(
    ("text", "refused"),
    [
        pytest.param("[[[", "{path} is not valid TOML {position}", id="not-toml"),
        pytest.param(
            '[project]\nname = "x"\n',
            "[stayfixed] is missing required key(s): version",
            id="no-version",
        ),
    ],
)
def test_a_document_level_refusal_propagates(tmp_path: Path, text: str, refused: str) -> None:
    # A refusal with no key is about the whole document: there is nothing to reset. Mutations
    # (`mutations/`'s "a missing required key is keyed as one value" -> the `no-version` refusal
    # carries `stayfixed.version`; "a document that is not TOML is keyed to a section" -> the
    # `not-toml` one carries `stayfixed`).
    with pytest.raises(ConfigError) as raised:
        loads_noting(text, tmp_path, owner=OWNER)
    position = _decoder_position(text) if "{position}" in refused else ""
    assert str(raised.value) == refused.format(
        path=quoted(str(tmp_path / CONFIG_FILE)), position=position
    )
    assert raised.value.key is None


def test_a_key_the_document_does_not_hold_is_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The retry removes a key the document holds; a validator naming any other refuses a value
    # the preset gave, so nothing can stand in for it, and the validator is asked once.
    # Mutations (`mutations/`'s "the NOTE retry takes a key the document does not hold for
    # removed" -> the load looks for a key that is not there; "the NOTE path relays the refusal
    # of a key it cannot remove" -> the validator's own refusal propagates).
    calls: list[object] = []

    def refuses(config: object, root: object) -> object:
        calls.append(config)
        raise ConfigError("held", key="paths.nowhere")

    monkeypatch.setattr(loader, "validate_paths", refuses)
    with pytest.raises(UnusableKey) as raised:
        loads_noting(MINIMAL, tmp_path, owner=OWNER)
    assert str(raised.value) == UNUSABLE_PRESET.format(key="paths.nowhere", reason="held")
    assert len(calls) == 1


def test_a_validator_that_keeps_refusing_spends_the_document_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each retry removes the one key it was handed; once that key is gone the next refusal of
    # it is a value the preset gave, so the attempts are the keys removed plus one, never a loop.
    # Mutation (`mutations/`'s "the NOTE retry takes a key the document does not hold for
    # removed"): the third refusal looks for a key that is not there.
    handed = ["stayfixed.preset", "paths.specs", "paths.specs"]
    calls: list[str] = []

    def refuses(config: object, root: object) -> object:
        calls.append(handed[len(calls)])
        raise ConfigError("held", key=calls[-1])

    monkeypatch.setattr(loader, "validate_paths", refuses)
    with pytest.raises(UnusableKey) as raised:
        loads_noting(MINIMAL + '[paths]\nspecs = "design/specs"\n', tmp_path, owner=OWNER)
    assert calls == handed
    assert str(raised.value) == UNUSABLE_PRESET.format(key="paths.specs", reason="held")


def test_a_section_that_is_not_a_table_is_the_presets(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "a section that is not a table is refused with no key"): the
    # refusal is the whole document's and the session loses every setting.
    text = "memory = 1\n" + MINIMAL  # before any header, so a top-level key
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.config.memory.mode == HARNESS_MODE
    assert got.notes == (reset("memory", text, tmp_path),)


def test_a_repository_personal_value_that_is_not_a_table_is_refused_too(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "a repository's machine-only value that is not a table is dropped
    # without a note"): the value goes and nothing says the repository tried.
    got = loads_noting("personal = false\n" + MINIMAL, tmp_path, owner=OWNER)
    assert got.notes == (REFUSED_LAYER_NOTE.format(key="personal", layer="repository"),)


def test_a_repository_guards_value_that_is_not_a_table_is_put_back(tmp_path: Path) -> None:
    text = "guards = false\n" + MINIMAL
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.notes == (reset("guards", text, tmp_path),)


REQUIRED_UNUSABLE = [
    pytest.param(
        MINIMAL.replace('name = "sample"', 'name = "has space"'), "project.name", id="project-name"
    ),
    pytest.param(
        MINIMAL.replace('version = "0.1.0"', "version = 1"), "stayfixed.version", id="version"
    ),
    # A section that is not a table, holding a key with no default: before any header, so a
    # top-level key.
    pytest.param("project = 1\n" + HEAD, "project", id="project-not-a-table"),
    pytest.param(
        'stayfixed = 1\n[project]\nname = "sample"\n', "stayfixed", id="stayfixed-not-a-table"
    ),
]


@pytest.mark.parametrize(("text", "key"), REQUIRED_UNUSABLE)
def test_a_required_key_it_cannot_use_is_named_and_never_called_missing(
    tmp_path: Path, text: str, key: str
) -> None:
    # A key with no default, or a section holding one, is never removed: removed, the next
    # attempt would refuse the document for missing a key it holds, `[project] is missing
    # required key(s): name` of a document whose name is right there. The load names the key the
    # document got wrong, with the refusal it got. Mutations (`mutations/`'s "a key with no
    # fallback is removed and retried" -> every case's misattributed refusal comes back; "a
    # section with no fallback resets" -> the two sections' does).
    with pytest.raises(UnusableKey) as raised:
        loads_noting(text, tmp_path, owner=OWNER)
    assert str(raised.value) == UNUSABLE_REQUIRED.format(key=key, reason=refusal(text, tmp_path))
    assert raised.value.key == key
    # The controls, which no mutation of the retry reddens and none needs to: the same document
    # with a usable value loads, and `loads` still refuses the value rather than a missing key.
    assert loads_noting(MINIMAL, tmp_path, owner=OWNER).notes == ()
    assert "missing" not in str(refusal(text, tmp_path))


def _symlinked_docs(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "docs")
    return root


@pytest.mark.parametrize(
    ("paths", "key"),
    [
        pytest.param("", "paths.specs", id="preset-value"),
        pytest.param('specs = "../x"\n', "paths.specs", id="reset-then-preset"),
        pytest.param('bugs = "../x"\n', "paths.bugs", id="reset-before-the-first-preset"),
    ],
)
def test_a_preset_value_a_committed_symlink_breaks_is_named(
    tmp_path: Path, paths: str, key: str
) -> None:
    # A committed `docs` symlink. With no `[paths]`, the preset's own `paths.specs`
    # passes through it and the document holds no value to remove, so nothing stands in for it.
    # With the document's own value refused, its preset value is asked before anything is
    # removed, and it fails too: the key named is the one the document wrote, never a preset
    # value it did not touch. Mutations (`mutations/`'s "the NOTE path relays the refusal of a key
    # it cannot remove" -> `preset-value`'s `PathEscape` propagates; "a preset value that fails
    # containment is reset to anyway" -> `reset-before-the-first-preset` names
    # `paths.specs`). The control below is the one no mutation reddens: it shows the link
    # is the fault.
    root = _symlinked_docs(tmp_path)
    text = MINIMAL + (f"[paths]\n{paths}" if paths else "")
    preset_value = str(preset_defaults("paths")[key.removeprefix("paths.")])
    with pytest.raises(UnusableKey) as raised:
        loads_noting(text, root, owner=OWNER)
    with pytest.raises(PathEscape) as preset_refusal:
        contained(root, preset_value)
    assert str(raised.value) == UNUSABLE_PRESET.format(key=key, reason=preset_refusal.value)
    assert raised.value.key == key
    # The control: a real `docs` directory, and the same document loads on the preset's value.
    (root / "docs").unlink()
    (root / "docs").mkdir()
    got = loads_noting(text, root, owner=OWNER).config.paths.as_dict()
    assert got[key.removeprefix("paths.")] == preset_value


FALLBACKS = [
    # An entry that may simply be absent: a budget is then the preset's.
    pytest.param("[budgets]\nagents_md_lines = 0\n", "budgets.agents_md_lines", id="absent-entry"),
]


@pytest.mark.parametrize(("extra", "key"), FALLBACKS)
def test_a_key_with_a_value_to_fall_back_to_resets_with_its_note(
    tmp_path: Path, extra: str, key: str
) -> None:
    # Each kind of value a key falls back to besides a preset value (`memory.mode` and
    # `stayfixed.preset` above): the key is removed with its note and the load goes on.
    # Mutation (`mutations/`'s "a budget is called unusable" -> `absent-entry` raises).
    text = MINIMAL + extra
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.notes == (reset(key, text, tmp_path),)
    assert "agents_md_lines" not in got.config.budgets.configured


def test_each_note_names_the_key_it_is_about(tmp_path: Path) -> None:
    # `doctor` lists a session's notes by key alone, never the sentence. Mutations
    # (`mutations/`'s "a reset key is not recorded beside its note" -> `memory.mode` goes
    # missing; "an unknown key is not recorded beside its note" -> `memory.future` does).
    text = MINIMAL + '[newer]\n[memory]\nfuture = 1\nmode = "cloud"\n[personal]\npreset = "x"\n'
    got = loads_noting(text, tmp_path, owner=OWNER)
    assert got.keys == ("newer", "memory.future", "personal.preset", "memory.mode")
