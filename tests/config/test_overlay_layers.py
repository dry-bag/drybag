"""A session's preferences from one resolution over the overlay's layers
(`src/drybag/config/overlay_layers.py`, `src/drybag/config/session.py`).

`<overlay>/common/drybag.toml` is a layer for every checkout, and
`<overlay>/projects/<project>/drybag.toml` one for a checkout this machine binds to that project:
the project comes from the machine's binding record, never from the name the repository's
`drybag.toml` gives. A missing file, an unrecorded overlay or a machine file the overlay root
cannot be read from is no layer and one note, never an exception.
"""

from __future__ import annotations

from pathlib import Path

from drybag import binding
from drybag.config import overlay_layers
from drybag.config.classes import REFUSED_LAYER_NOTE, LayerName
from drybag.config.reading import MachineConfigError, read_machine_toml
from drybag.config.session import session_config
from drybag.presets import load_preset
from drybag.printed import quoted
from tests.gitfixture import git, needs_git
from tests.tagged import list_tags

pytestmark = needs_git

MINIMAL = '[drybag]\nversion = "0.1.0"\n\n[project]\nname = "sample"\n'
BUDGET = "budgets.startup_rules_words"
GATE_BUDGET = "agents_md_lines"


def project(tmp_path: Path) -> Path:
    """A git checkout whose `drybag.toml` names the project `sample`, bound to nothing."""
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "drybag.toml").write_text(MINIMAL, encoding="utf-8")
    return root


def overlay(tmp_path: Path, *, common: str = "", sample: str | None = None) -> Path:
    """An overlay whose common file holds `common` and, given, `projects/sample`'s `sample`."""
    root = tmp_path / "overlay"
    (root / "common").mkdir(parents=True)
    (root / "common" / "drybag.toml").write_text(common, encoding="utf-8")
    if sample is not None:
        (root / "projects" / "sample").mkdir(parents=True)
        (root / "projects" / "sample" / "drybag.toml").write_text(sample, encoding="utf-8")
    return root


def tagged(root: Path, listed: list[str], **files: str) -> None:
    """The project `sample`'s record listing `listed`, and `tags/<tag>/drybag.toml` for each
    tag in `files`, holding what it is given."""
    list_tags(root, "sample", listed)
    for tag, text in files.items():
        (root / "tags" / tag).mkdir(parents=True)
        (root / "tags" / tag / "drybag.toml").write_text(text, encoding="utf-8")


def mode(value: str) -> str:
    return f'[memory]\nmode = "{value}"\n'


def machine(tmp_path: Path, recorded: Path, extra: str = "") -> Path:
    path = tmp_path / "machine.toml"
    path.write_text(f'[overlay]\nroot = "{recorded}"\n{extra}', encoding="utf-8")
    return path


def budgets(words: int) -> str:
    return f"[budgets]\nstartup_rules_words = {words}\n"


def test_the_project_file_wins_over_the_common_file_for_a_bound_checkout(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "the overlay project file is read as the overlay common layer"):
    # the two layers then tie on rank, and the project's value stands under the common label.
    root = project(tmp_path)
    recorded = overlay(tmp_path, common=budgets(700), sample=budgets(900))
    binding.record(root, "sample", None)
    session = session_config(root, machine=machine(tmp_path, recorded))
    assert session.resolution.values.get(BUDGET) == 900
    assert session.resolution.provenance.get(BUDGET) is LayerName.OVERLAY_PROJECT
    assert session.config is not None
    assert session.config.budgets.effective("startup_rules_words") == 900


def test_the_machine_file_wins_over_both_overlay_files(tmp_path: Path) -> None:
    root = project(tmp_path)
    recorded = overlay(tmp_path, common=budgets(700), sample=budgets(900))
    binding.record(root, "sample", None)
    session = session_config(root, machine=machine(tmp_path, recorded, budgets(1100)))
    assert session.resolution.values.get(BUDGET) == 1100
    assert session.resolution.provenance.get(BUDGET) is LayerName.MACHINE_FILE
    assert session.config is not None
    assert session.config.budgets.effective("startup_rules_words") == 1100


def test_a_preference_in_the_common_file_reaches_the_session(tmp_path: Path) -> None:
    # The repository's file says nothing of `[memory]`, so the preset's `local-only` is beneath.
    root = project(tmp_path)
    recorded = overlay(tmp_path, common='[memory]\nmode = "overlay"\n')
    session = session_config(root, machine=machine(tmp_path, recorded))
    assert session.config is not None
    assert session.config.memory.mode == "overlay"
    assert session.resolution.provenance.get("memory.mode") is LayerName.OVERLAY_COMMON


def test_an_unbound_checkout_naming_the_project_gets_no_project_layer(tmp_path: Path) -> None:
    # A clone that commits `[project] name = "sample"` has no binding id, so nothing on this
    # machine binds it to the overlay's `sample`, and only the common layer applies.
    root = project(tmp_path)
    recorded = overlay(tmp_path, common=budgets(700), sample=budgets(900))
    session = session_config(root, machine=machine(tmp_path, recorded))
    assert session.resolution.values.get(BUDGET) == 700
    assert session.resolution.provenance.get(BUDGET) is LayerName.OVERLAY_COMMON


def test_a_gate_parameter_in_either_overlay_file_never_reaches_the_config(tmp_path: Path) -> None:
    # What a pull request is judged by is the base branch's file alone: `resolve` refuses both
    # overlay layers for a gate's budget, and says so for each.
    root = project(tmp_path)
    gate = f"[budgets]\n{GATE_BUDGET} = 999\n"
    recorded = overlay(tmp_path, common=gate, sample=gate)
    binding.record(root, "sample", None)
    session = session_config(root, machine=machine(tmp_path, recorded))
    preset = load_preset("recommended")["budgets"][GATE_BUDGET]
    assert session.config is not None
    assert session.config.budgets.effective(GATE_BUDGET) == preset
    assert REFUSED_LAYER_NOTE.format(key=f"budgets.{GATE_BUDGET}", layer="overlay common") in (
        session.resolution.notes
    )
    assert REFUSED_LAYER_NOTE.format(key=f"budgets.{GATE_BUDGET}", layer="overlay project") in (
        session.resolution.notes
    )


def test_a_broken_machine_file_is_a_note_and_a_session(tmp_path: Path) -> None:
    root = project(tmp_path)
    broken = tmp_path / "machine.toml"
    broken.write_text("[overlay\n", encoding="utf-8")
    try:
        read_machine_toml(broken)
    except MachineConfigError as exc:
        refused = str(exc)
    session = session_config(root, machine=broken)
    assert session.config is not None
    assert overlay_layers.MACHINE_UNREAD.format(error=refused) in session.resolution.notes


def test_no_recorded_overlay_is_no_layer_and_one_note(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert overlay_layers.read(root, machine=tmp_path / "none.toml") == (
        (),
        (overlay_layers.NO_OVERLAY,),
        None,
    )


def test_a_missing_file_is_no_layer_and_one_note(tmp_path: Path) -> None:
    root = project(tmp_path)
    recorded = tmp_path / "overlay"
    recorded.mkdir()
    binding.record(root, "sample", None)
    layers, notes, _ = overlay_layers.read(root, machine=machine(tmp_path, recorded))
    assert layers == ()
    common = quoted(str(recorded / "common" / "drybag.toml"))
    own = quoted(str(recorded / "projects" / "sample" / "drybag.toml"))
    assert notes == (
        overlay_layers.NOT_THERE.format(path=common, layer="overlay common"),
        overlay_layers.NOT_THERE.format(path=own, layer="overlay project"),
    )


def test_a_later_tag_wins_a_value_and_the_project_wins_over_every_tag(tmp_path: Path) -> None:
    # Mutation (`mutations/`'s "tag layers rank above the project layer"): the tags then outrank
    # the project, and the project's `overlay` loses to `local-only`.
    root = project(tmp_path)
    recorded = overlay(tmp_path, common=mode("harness"), sample="")
    tagged(recorded, ["a", "b"], a=mode("overlay"), b=mode("local-only"))
    binding.record(root, "sample", None)
    session = session_config(root, machine=machine(tmp_path, recorded))
    assert session.resolution.values["memory.mode"] == "local-only"
    assert session.resolution.provenance["memory.mode"] is LayerName.OVERLAY_TAG
    assert session.resolution.said("memory.mode") == "overlay tag b"
    (recorded / "projects" / "sample" / "drybag.toml").write_text(mode("overlay"), "utf-8")
    session = session_config(root, machine=machine(tmp_path, recorded))
    assert session.resolution.values["memory.mode"] == "overlay"
    assert session.resolution.said("memory.mode") == "overlay project"


def test_reordering_the_tags_reorders_the_win(tmp_path: Path) -> None:
    root = project(tmp_path)
    recorded = overlay(tmp_path, common=mode("harness"))
    tagged(recorded, ["b", "a"], a=mode("overlay"), b=mode("local-only"))
    binding.record(root, "sample", None)
    session = session_config(root, machine=machine(tmp_path, recorded))
    assert session.resolution.values["memory.mode"] == "overlay"
    assert session.resolution.said("memory.mode") == "overlay tag a"


def test_an_unbound_checkout_reads_no_tag_layer(tmp_path: Path) -> None:
    # The record lists tags, but the checkout is not bound to the project: only the owner's
    # machine binds a checkout, so only the common layer applies.
    root = project(tmp_path)
    recorded = overlay(tmp_path, common=mode("harness"))
    tagged(recorded, ["a"], a=mode("overlay"))
    layers, _, _ = overlay_layers.read(root, machine=machine(tmp_path, recorded))
    assert [layer.name for layer in layers] == [LayerName.OVERLAY_COMMON]


def test_a_tag_file_that_is_not_toml_is_a_note_and_no_layer(tmp_path: Path) -> None:
    root = project(tmp_path)
    recorded = overlay(tmp_path, common="", sample="")
    tagged(recorded, ["a"], a="[memory\n")
    binding.record(root, "sample", None)
    layers, notes, _ = overlay_layers.read(root, machine=machine(tmp_path, recorded))
    assert LayerName.OVERLAY_TAG not in [layer.name for layer in layers]
    path = quoted(str(recorded / "tags" / "a" / "drybag.toml"))
    assert any(
        path in note and "is not valid TOML" in note and "overlay tag a" in note for note in notes
    )


def test_a_tag_the_record_lists_without_a_directory_is_the_plates_note(tmp_path: Path) -> None:
    root = project(tmp_path)
    recorded = overlay(tmp_path, common="", sample="")
    tagged(recorded, ["gone"])
    binding.record(root, "sample", None)
    layers, notes, _ = overlay_layers.read(root, machine=machine(tmp_path, recorded))
    assert [layer.name for layer in layers] == [LayerName.OVERLAY_COMMON, LayerName.OVERLAY_PROJECT]
    assert len(notes) == 1 and "gone" in notes[0]


def test_a_gate_parameter_in_a_tag_file_never_reaches_the_config(tmp_path: Path) -> None:
    # A tag is the owner's like the common file: what a pull request is judged by is the base
    # branch's alone, and the note names the tag that tried.
    root = project(tmp_path)
    recorded = overlay(tmp_path, common="", sample="")
    tagged(recorded, ["a"], a=f"[budgets]\n{GATE_BUDGET} = 999\n")
    binding.record(root, "sample", None)
    session = session_config(root, machine=machine(tmp_path, recorded))
    preset = load_preset("recommended")["budgets"][GATE_BUDGET]
    assert session.config is not None
    assert session.config.budgets.effective(GATE_BUDGET) == preset
    assert REFUSED_LAYER_NOTE.format(key=f"budgets.{GATE_BUDGET}", layer="overlay tag a") in (
        session.resolution.notes
    )


def sub_plate(root: Path, plate: str, text: str | None) -> None:
    """`plate`'s (`tags/t1`, `common`) `machines/m1/drybag.toml`, holding `text` where given."""
    directory = root / plate / "machines" / "m1"
    directory.mkdir(parents=True)
    if text is not None:
        (directory / "drybag.toml").write_text(text, encoding="utf-8")


def test_sub_plate_value_beats_its_parent_and_loses_to_the_next_tag(tmp_path: Path) -> None:
    # Mutation: sorting the reversed stack puts `t2` beneath `t1 on m1`, and the winner and its
    # label change.
    root = project(tmp_path)
    recorded = overlay(tmp_path, common="", sample="")
    tagged(recorded, ["t1", "t2"], t1=mode("harness"), t2=mode("harness"))
    sub_plate(recorded / "tags", "t1", mode("overlay"))
    binding.record(root, "sample", None)
    named = machine(tmp_path, recorded, '[machine]\nname = "m1"\n')
    session = session_config(root, machine=named)
    assert session.resolution.values["memory.mode"] == "harness"
    assert session.resolution.said("memory.mode") == "overlay tag t2"
    tagged(recorded, ["t1"])
    session = session_config(root, machine=named)
    assert session.resolution.values["memory.mode"] == "overlay"
    assert session.resolution.said("memory.mode") == "overlay tag t1 on m1"
    other = machine(tmp_path, recorded, '[machine]\nname = "m2"\n')
    assert session_config(root, machine=other).resolution.values["memory.mode"] == "harness"


def test_absent_sub_plate_file_says_nothing(tmp_path: Path) -> None:
    root = project(tmp_path)
    recorded = overlay(tmp_path, common="", sample="")
    tagged(recorded, ["t1"], t1="")
    sub_plate(recorded / "tags", "t1", None)
    sub_plate(recorded, "common", None)
    sub_plate(recorded / "projects", "sample", None)
    binding.record(root, "sample", None)
    layers, notes, _ = overlay_layers.read(
        root, machine=machine(tmp_path, recorded, '[machine]\nname = "m1"\n')
    )
    assert [layer.name for layer in layers] == [
        LayerName.OVERLAY_COMMON,
        LayerName.OVERLAY_TAG,
        LayerName.OVERLAY_PROJECT,
    ]
    assert notes == ()


def test_sub_plate_may_set_only_its_parents_keys(tmp_path: Path) -> None:
    root = project(tmp_path)
    recorded = overlay(tmp_path, common="", sample="")
    tagged(recorded, ["t1"], t1="")
    sub_plate(recorded / "tags", "t1", f"[budgets]\n{GATE_BUDGET} = 999\n")
    binding.record(root, "sample", None)
    session = session_config(root, machine=machine(tmp_path, recorded, '[machine]\nname = "m1"\n'))
    preset = load_preset("recommended")["budgets"][GATE_BUDGET]
    assert session.config is not None
    assert session.config.budgets.effective(GATE_BUDGET) == preset
    assert REFUSED_LAYER_NOTE.format(
        key=f"budgets.{GATE_BUDGET}", layer="overlay tag t1 on m1"
    ) in (session.resolution.notes)


def test_a_tag_named_on_and_its_sub_plate_are_one_tag(tmp_path: Path) -> None:
    # A sub-plate's layer carries its machine as a field, not inside its label, so a tag named
    # `on` is told from its sub-plate by no parse of its label. Mutation (oracle): `mutations/`'s
    # "a tag's sub-plate layer is counted as a tag of its own".
    from drybag.attach.tags import collisions
    from drybag.config.plates import plates

    root = project(tmp_path)
    recorded = overlay(tmp_path, common="", sample="")
    tagged(recorded, ["on"], on=mode("harness"))
    sub_plate(recorded / "tags", "on", mode("overlay"))
    binding.record(root, "sample", None)
    named = machine(tmp_path, recorded, '[machine]\nname = "m1"\n')
    layers, _, _ = overlay_layers.read(root, machine=named)
    assert collisions(plates(recorded, "sample", machine="m1")[0], layers) == ()
    session = session_config(root, machine=named)
    assert session.resolution.said("memory.mode") == "overlay tag on on m1"
