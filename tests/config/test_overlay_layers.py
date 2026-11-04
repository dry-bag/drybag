"""A session's preferences from one resolution over the overlay's layers
(`src/stayfixed/config/overlay_layers.py`, `src/stayfixed/config/session.py`).

`<overlay>/common/stayfixed.toml` is a layer for every checkout, and
`<overlay>/projects/<project>/stayfixed.toml` one for a checkout this machine binds to that project:
the project comes from the machine's binding record, never from the name the repository's
`stayfixed.toml` gives. A missing file, an unrecorded overlay or a machine file the overlay root
cannot be read from is no layer and one note, never an exception.
"""

from __future__ import annotations

from pathlib import Path

from stayfixed import binding
from stayfixed.config import overlay_layers
from stayfixed.config.classes import REFUSED_LAYER_NOTE, LayerName
from stayfixed.config.reading import MachineConfigError, read_machine_toml
from stayfixed.config.session import session_config
from stayfixed.presets import defaults_of, load_preset
from stayfixed.printed import quoted
from tests.gitfixture import git, needs_git

pytestmark = needs_git

MINIMAL = '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "sample"\n'
BUDGET = "budgets.startup_rules_words"


def project(tmp_path: Path) -> Path:
    """A git checkout whose `stayfixed.toml` names the project `sample`, bound to nothing."""
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "stayfixed.toml").write_text(MINIMAL, encoding="utf-8")
    return root


def overlay(tmp_path: Path, *, common: str = "", sample: str | None = None) -> Path:
    """An overlay whose common file holds `common` and, given, `projects/sample`'s `sample`."""
    root = tmp_path / "overlay"
    (root / "common").mkdir(parents=True)
    (root / "common" / "stayfixed.toml").write_text(common, encoding="utf-8")
    if sample is not None:
        (root / "projects" / "sample").mkdir(parents=True)
        (root / "projects" / "sample" / "stayfixed.toml").write_text(sample, encoding="utf-8")
    return root


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
    # overlay layers for `ledger.code_roots`, and says so for each.
    root = project(tmp_path)
    gate = '[ledger]\ncode_roots = ["elsewhere"]\n'
    recorded = overlay(tmp_path, common=gate, sample=gate)
    binding.record(root, "sample", None)
    session = session_config(root, machine=machine(tmp_path, recorded))
    preset = defaults_of(load_preset("recommended"))["ledger"]["code_roots"]
    assert session.config is not None
    assert session.config.ledger.code_roots == tuple(preset)
    assert REFUSED_LAYER_NOTE.format(key="ledger.code_roots", layer="overlay common") in (
        session.resolution.notes
    )
    assert REFUSED_LAYER_NOTE.format(key="ledger.code_roots", layer="overlay project") in (
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
    )


def test_a_missing_file_is_no_layer_and_one_note(tmp_path: Path) -> None:
    root = project(tmp_path)
    recorded = tmp_path / "overlay"
    recorded.mkdir()
    binding.record(root, "sample", None)
    layers, notes = overlay_layers.read(root, machine=machine(tmp_path, recorded))
    assert layers == ()
    common = quoted(str(recorded / "common" / "stayfixed.toml"))
    own = quoted(str(recorded / "projects" / "sample" / "stayfixed.toml"))
    assert notes == (
        overlay_layers.NOT_THERE.format(path=common, layer="overlay common"),
        overlay_layers.NOT_THERE.format(path=own, layer="overlay project"),
    )
