# tests/setup/test_machine.py
from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

import pytest

from stayfixed.config.loader import load
from stayfixed.config.overlay import overlay_root
from stayfixed.errors import Refusal
from stayfixed.presets import load_preset
from stayfixed.setup.machine import read_machine, write_machine
from tests.parserlimits import LONG_HEX

# The minimal `stayfixed.toml` `load()` accepts: everything else comes from the preset's own
# defaults. `tests/hooks/test_hook_command.py::_initialised_project` carries the same shape for
# the same reason — a config load needs `[stayfixed]` and `[project]` and nothing more.
CONFIG = """
[stayfixed]
version = "0.1.0"
preset = "recommended"
agents = ["claude"]

[project]
name = "widget"
base_branch = "main"
release_branch = "main"
"""


def _initialised_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "stayfixed.toml").write_text(CONFIG, encoding="utf-8")
    return project


def test_the_file_written_is_the_file_both_readers_already_read(tmp_path: Path) -> None:
    # The whole point of writing the file both existing readers already read, asserted from the
    # readers' side rather than the writer's: a schema this writer invented would round-trip through
    # its own reader and fail in a hook.
    path = tmp_path / "config.toml"
    write_machine(path, personal={"preset": "ru"}, overlay_root=tmp_path / "ov", machine={})
    assert overlay_root(path) == tmp_path / "ov"
    project = _initialised_project(tmp_path)
    assert load(project, machine=path).personal.preset == "ru"


def test_writing_without_an_overlay_leaves_no_overlay_table(tmp_path: Path) -> None:
    # `overlay_root` answering None must keep meaning "not recorded, and nothing else" — its
    # docstring spells out that an empty or broken table used to collapse six states into one
    # and produced wrong advice for three of them.
    path = tmp_path / "config.toml"
    write_machine(path, personal={}, overlay_root=None, machine={})
    assert overlay_root(path) is None
    assert "overlay" not in tomllib.loads(path.read_text(encoding="utf-8"))


def test_a_rewrite_preserves_a_value_this_run_did_not_set(tmp_path: Path) -> None:
    # A second `setup` on a machine that already has one is the common case. Losing the overlay
    # root because this run only set a personal value is the shape this catches.
    path = tmp_path / "config.toml"
    write_machine(path, personal={}, overlay_root=tmp_path / "ov", machine={})
    write_machine(path, personal={"preset": "ru"}, overlay_root=None, machine={})
    assert overlay_root(path) == tmp_path / "ov"
    assert read_machine(path)["personal"]["preset"] == "ru"


def test_a_hostile_value_cannot_write_a_second_key(tmp_path: Path) -> None:
    # The machine file records the overlay root — the anchor of the whole trust model. It is a
    # path the owner typed rather than repository bytes, but it travels through the same
    # serialiser as `project.toml`'s remote URL, and one escaping rule for both is the reason
    # `tomlout` exists rather than two format strings.
    #
    # Why `.get(...)` and not a bracket lookup: `["injected"] != "zz"` raises `KeyError`
    # once the value is escaped correctly — nothing here ever asked for a second key, so none is
    # present at all, and a bracket lookup cannot tell "escaped safely" from "never happened" apart
    # from "the naive concatenation this guards against". `.get(...)` reads the same intent — no
    # working `injected = "zz"` key exists — without failing on the safe outcome the
    # escaping is supposed to produce. Mutation: format `preset` with an f-string instead of
    # `tomlout.dumps` → the naive concatenation closes the string early and this test reddens on
    # `== "zz"`.
    path = tmp_path / "config.toml"
    write_machine(
        path,
        personal={"preset": 'ru"\ninjected = "zz'},
        overlay_root=None,
        machine={},
    )
    assert read_machine(path)["personal"].get("injected") != "zz"


def test_the_preset_names_the_plugins_and_the_deny_rules() -> None:
    # superpowers is named because `README.md` says so: stayfixed is not a replacement for
    # superpowers, and the recommended preset recommends it.
    preset = load_preset("recommended")
    assert any("superpowers" in name for name in preset["plugins"]["recommended"])
    assert any(".env" in rule for rule in preset["deny"]["global"])


def test_the_preset_denies_reading_env_files_by_value() -> None:
    # This preset table is where the `.env` deny rules actually fire: `setup._write_user_settings`
    # merges `[deny] global` into `<home>/.claude/settings.json`, which the harness reads for
    # every project on the machine. The overlay template used to ship a second, smaller copy of
    # the same idea in `common/claude/permissions.json`, asserted by value over there — dead,
    # because `attach.permissions` reads only `permissions.allow`, and already one rule behind
    # this list. That copy is gone and its by-value assertion is here, on the live one.
    #
    # By value and not `any(".env" in rule)`, which the case above already does: `["Read(.env)"]`
    # satisfies a substring test and leaves `.env.local` and every nested `.env` readable.
    #
    # By name and never by a mask: a deny rule outranks every allow rule, so `.env*` refused the
    # `.env.example` a project commits for an agent to edit, with no way to let it through. The
    # `env-reads` session guard refuses the names this list does not hold.
    #
    # Mutation: `mutations/`'s "the preset stops denying the env files".
    names = [
        ".env",
        ".env.local",
        ".env.*.local",
        ".env.dev",
        ".env.development",
        ".env.prod",
        ".env.production",
        ".env.stage",
        ".env.staging",
        ".env.test",
    ]
    deny = load_preset("recommended")["deny"]
    # One spelling per name: a bare name matches at any depth in Claude Code's rules, so
    # `Read(.env)` beside `Read(**/.env)` was a second line saying the same thing.
    assert deny["global"] == [f"Read(**/{n})" for n in names]


def test_the_preset_has_no_retired_deny_rules() -> None:
    # `setup` takes nothing back out of the user settings file, so the preset names nothing for it.
    assert set(load_preset("recommended")["deny"]) == {"global"}


@pytest.mark.parametrize(
    "template",
    [".env.example", ".env.prod.example", ".env.sample", ".env.dist", ".env.defaults", ".env.tpl"],
)
def test_no_preset_deny_rule_reaches_a_template(template: str) -> None:
    # The defect this list was rewritten for, read the way the rules are written: a `*` is any run
    # of characters inside one name. A rule that matches a template refuses it for good.
    # Mutation: `mutations/`'s "the preset denies the env files by a mask again" -> reddens.
    for rule in load_preset("recommended")["deny"]["global"]:
        pattern = rule.removeprefix("Read(").removesuffix(")").removeprefix("**/")
        assert not fnmatch.fnmatchcase(template, pattern), rule


# --- the file this writer shares with a human ---


def test_a_table_this_writer_does_not_know_survives_a_rewrite(tmp_path: Path) -> None:
    # The docstring promised "a rewrite merges, table by table, key by key"; the merge covered
    # exactly three hard-coded names and then replaced the whole file, so a `[trust]` table and
    # a key at the top level were gone after one `setup`. `README.md` lists this file under
    # "Written by: **you**, or `stayfixed setup`", which makes a hand-written table the ordinary
    # case rather than the exotic one.
    #
    # Mutation (`mutations/`'s "a table the machine writer does not own is dropped on a
    # rewrite"): the carry-through arm stops copying the table → `[trust]` disappears and this
    # reddens.
    path = tmp_path / "config.toml"
    path.write_text(
        "# my machine file\n"
        'schema = "mine"\n'
        "\n"
        "[personal]\n"
        'preset = "ru"\n'
        "\n"
        "[trust]\n"
        'mode = "strict"\n'
        'hosts = ["example.com"]\n',
        encoding="utf-8",
    )
    write_machine(path, personal={}, overlay_root=None, machine={"version": "9.9.9"})
    written = read_machine(path)
    assert written["trust"] == {"mode": "strict", "hosts": ["example.com"]}
    assert written["schema"] == "mine"
    assert written["personal"]["preset"] == "ru"
    assert written["machine"]["version"] == "9.9.9"


def test_a_hand_written_key_in_a_table_this_writer_owns_survives_a_rewrite(
    tmp_path: Path,
) -> None:
    # The gap between the two rows above it: one covers a table this writer has never heard of,
    # the other covers the one key of `[overlay]` it writes itself. Nothing covered a table it
    # *does* own carrying a key it does not -- and that is where the defect was. `[personal]`
    # and `[machine]` were spread over what the file held; `[overlay]` was replaced outright,
    # so `[overlay] note` was gone after every `setup`, silently, on the owner's own file.
    #
    # Mutation (`mutations/`'s "write_machine replaces the overlay table instead of merging
    # over it"): the `**_table(existing, "overlay")` spread is dropped → `note` disappears.
    path = tmp_path / "config.toml"
    path.write_text(
        '[overlay]\nroot = "/tmp/ov"\nnote = "hand-written"\nextra_flag = true\n',
        encoding="utf-8",
    )
    write_machine(path, personal={}, overlay_root=None, machine={"version": "9.9.9"})
    written = read_machine(path)
    assert written["overlay"] == {"root": "/tmp/ov", "note": "hand-written", "extra_flag": True}


def test_an_overlay_table_with_no_root_is_not_deleted(tmp_path: Path) -> None:
    # The same defect's other face: with no `root` to write, the replacement was `{}`, the
    # "only a non-empty table is written" guard then dropped it, and the whole `[overlay]` table
    # the owner wrote was gone -- not one key of it. Same mutation as the row above.
    path = tmp_path / "config.toml"
    path.write_text('[overlay]\nnote = "no root here"\n', encoding="utf-8")
    write_machine(path, personal={}, overlay_root=None, machine={})
    assert read_machine(path)["overlay"] == {"note": "no root here"}


def test_a_hand_written_float_or_sub_table_does_not_wedge_every_future_run(
    tmp_path: Path,
) -> None:
    # `[personal] scale = 1.5` or `[personal.editor] name = "nvim"` made every future run of
    # `stayfixed setup` exit 2 with `Refusal: personal.scale holds a float, which this serialiser
    # does not emit` — naming a module the owner has never heard of, with no path and no remedy,
    # for a value they were invited to write. Twice, because the wedge is about *every future*
    # run: the file is read back at the top of each one.
    #
    # Mutation: `tomlout._scalar`'s float arm removed → the first call below raises again. Not an
    # entry in `mutations/`: this is value coverage in a serialiser, not a guard something
    # downstream reads as permission; the entry there is on the table carry-through above.
    path = tmp_path / "config.toml"
    path.write_text(
        '[personal]\nscale = 1.5\n\n[personal.editor]\nname = "nvim"\n', encoding="utf-8"
    )
    for version in ("1.0.0", "1.0.1"):
        write_machine(path, personal={}, overlay_root=None, machine={"version": version})
    written = read_machine(path)
    assert written["personal"]["scale"] == 1.5
    assert written["personal"]["editor"] == {"name": "nvim"}
    assert written["machine"]["version"] == "1.0.1"


def test_a_key_that_cannot_be_rewritten_names_the_file_and_the_remedy(tmp_path: Path) -> None:
    # What is left after the value types are covered: a quoted key, which TOML allows and this
    # serialiser will not write bare. It is still a refusal — but one that names the file the
    # owner has to edit and what to do to it, rather than one that names `tomlout`.
    path = tmp_path / "config.toml"
    path.write_text('[personal]\n"my key" = 1\n', encoding="utf-8")
    with pytest.raises(Refusal) as refused:
        write_machine(path, personal={}, overlay_root=None, machine={})
    assert str(path) in str(refused.value)
    assert "run the command again" in str(refused.value)


def test_a_hand_written_hex_integer_of_any_length_survives_the_rewrite(tmp_path: Path) -> None:
    # The owner's machine file is theirs to write, and `tomllib` reads a hex literal of any
    # length; the rewrite spelled it with `str`, which raises past 4,300 digits, so every
    # `stayfixed setup` on that machine ended in an internal error. It is kept, written back in
    # hexadecimal. Mutation (declared): `mutations/`'s "the TOML writer spells every integer in
    # decimal".
    path = tmp_path / "config.toml"
    large = LONG_HEX
    path.write_text(f"[notes]\nkept = {large}\n", encoding="utf-8")
    write_machine(path, personal={"preset": "ru"}, overlay_root=None, machine={})
    assert read_machine(path)["notes"]["kept"] == int(large, 16)
