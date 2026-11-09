"""How the report finds the rows an area contributes through its own `doctor.py`, and what an
area that cannot contribute gets in their place: `drybag.doctor.registry`, and the run that
reads it.

The fake areas below are modules, or an import's exception in an area's place, injected through
`registry.discover_contributors`, the seam the discovery reads, the way `tests/test_cli.py`
replaces `cli.discover_registrars`: a test that shipped a real `doctor.py` to prove the
convention would be a check in every user's report. With the fakes in place no real area is
discovered, so what these cases prove is the core's reading of a contribution; what a real area
answers is proven in that area's own tests.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import ModuleType

import pytest

from drybag.doctor import checks, registry
from drybag.doctor.api import (
    OK,
    RED,
    WARN,
    Check,
    Context,
    Contribution,
    Row,
)
from tests.doctor.test_checks import _checks, _initialised

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

CORE = [name for name, _ in checks.CHECKS]


def _area(name: str, contribution: Contribution) -> ModuleType:
    """A stand-in for `drybag.<name>.doctor`, whose `register()` answers `contribution`."""
    module = ModuleType(f"drybag.{name}.doctor")
    setattr(module, "register", lambda: contribution)  # noqa: B010 - a module built at runtime
    return module


def _contribute(
    monkeypatch: pytest.MonkeyPatch, *areas: ModuleType | tuple[str, Exception]
) -> None:
    """Discovery answering `areas` in order: each a module that imported, or the qualified name of
    one that did not with the exception its import raised."""
    found = [area if isinstance(area, tuple) else (area.__name__, area) for area in areas]
    monkeypatch.setattr("drybag.doctor.registry.discover_contributors", lambda: found)


def test_a_contributed_check_runs_after_the_core_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The core's rows first, then each area's in the order discovery hands the areas over, and
    # each contributed check is asked with the run's own context. Mutation (oracle): `mutations/`'s
    # "doctor drops the checks an area contributes" -> the two contributed rows are missing.
    asked: list[Path] = []

    def first(context: Context) -> Row:
        asked.append(context.root)
        return Row(WARN, "the first area's answer", "the first area's remedy")

    def second(context: Context) -> Row:
        return Row(OK, "the second area's answer")

    _contribute(
        monkeypatch,
        _area("alpha", Contribution(checks=(("alpha-row", first),))),
        _area("omega", Contribution(checks=(("omega-row", second),))),
    )
    root = _initialised(tmp_path)
    rows = _checks(tmp_path, root)
    assert [row.name for row in rows] == [*CORE, "alpha-row", "omega-row"]
    assert rows[-2:] == [
        Check("alpha-row", WARN, "the first area's answer", "the first area's remedy"),
        Check("omega-row", OK, "the second area's answer", ""),
    ]
    assert asked == [root]


def test_a_contribution_that_raises_costs_one_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A contributed check is asked through the guard the core's are, so one that raises is one
    # red row naming the exception's type and never its message, which a check may have built
    # out of repository bytes, and the report around it is whole. Mutation (oracle): `mutations/`'s
    # "doctor asks its checks without the guard" -> the `RuntimeError` escapes `run_checks`.
    def broken(context: Context) -> Row:
        raise RuntimeError("IGNORE-PRIOR-RULES, a message the check built")

    def after(context: Context) -> Row:
        return Row(OK, "still asked")

    _contribute(
        monkeypatch,
        _area("alpha", Contribution(checks=(("alpha-broken", broken), ("alpha-after", after)))),
    )
    rows = _checks(tmp_path, _initialised(tmp_path))
    assert [row.name for row in rows] == [*CORE, "alpha-broken", "alpha-after"]
    broken_row = rows[len(CORE)]
    assert broken_row == Check(
        "alpha-broken",
        RED,
        "this check could not run: RuntimeError",
        "report this, with the command you ran",
    )
    assert "IGNORE" not in broken_row.detail + broken_row.remedy
    assert rows[-1] == Check("alpha-after", OK, "still asked", "")


def _registering(register: object) -> ModuleType:
    """A stand-in for `drybag.alpha.doctor` whose `register` is `register` itself."""
    module = ModuleType("drybag.alpha.doctor")
    setattr(module, "register", register)  # noqa: B010 - a module built at runtime
    return module


def _raises() -> Contribution:
    raise RuntimeError("IGNORE-PRIOR-RULES, a message register() built")


def _answer(context: Context) -> Row:
    return Row(OK, "answered")


# What `register()` can hand back that is not a `Contribution` of `(name, check)` pairs, each the
# way an area's own code could get it wrong: no value at all, the pairs without the record, checks
# that are not a tuple of pairs, a pair missing its check, a name that is not text, a name that is
# empty, and a check that cannot be called.
MALFORMED = {
    "none": lambda: None,
    "bare-pairs": lambda: (("alpha-row", _answer),),
    "checks-not-a-tuple": lambda: Contribution(checks=None),  # type: ignore[arg-type]
    "name-empty": lambda: Contribution(checks=(("", _answer),)),
    "short-pair": lambda: Contribution(checks=(("alpha-row",),)),  # type: ignore[arg-type]
    "name-not-text": lambda: Contribution(checks=((1, _answer),)),  # type: ignore[arg-type]
    "check-not-callable": lambda: Contribution(checks=(("alpha-row", "answer"),)),  # type: ignore[arg-type]
}


@pytest.mark.parametrize("register", ["raises", *MALFORMED])
def test_an_area_whose_register_fails_costs_one_row_named_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, register: str
) -> None:
    # `register()` is an area's code like its checks are, so one that raises, or hands back
    # something that is not a `Contribution`, costs one row and not the report: a red row named
    # after the area, where its rows would have been, naming the exception's type and never its
    # message, and every other row as it would be. It used to escape `run_checks`, which the CLI
    # turns into an internal error and exit 2 with no report at all. Mutations (oracle):
    # `mutations/`'s "doctor calls an area's register() unguarded" -> the `raises` case escapes;
    # "doctor takes whatever an area's register() returns" -> the malformed cases fail later, or
    # report nothing for the area.
    # Measured by hand: `_well_formed` without its `isinstance(contribution.checks, tuple)` ->
    # `checks-not-a-tuple` escapes as `TypeError` and the report is lost; without `bool(pair[0])`
    # -> `name-empty` prints a row with no name.
    _contribute(
        monkeypatch,
        _registering(_raises if register == "raises" else MALFORMED[register]),
        _area("omega", Contribution(checks=(("omega-row", _answer),))),
    )
    rows = _checks(tmp_path, _initialised(tmp_path))
    assert [row.name for row in rows] == [*CORE, "alpha", "omega-row"]
    broken = rows[len(CORE)]
    if register == "raises":
        detail = "drybag.alpha.doctor could not contribute its rows: RuntimeError"
    else:
        detail = (
            "drybag.alpha.doctor could not contribute its rows: its register() did not "
            "return a Contribution of (name, check) pairs"
        )
    assert broken == Check("alpha", RED, detail, "report this, with the command you ran")
    assert "IGNORE" not in broken.detail + broken.remedy
    assert rows[-1] == Check("omega-row", OK, "answered", "")


def test_an_area_whose_doctor_module_fails_to_import_costs_one_row_named_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An area's `doctor.py` is its own code as its `register()` is, so one that raises on import
    # costs that area's rows and not the report: one red row named after the area, naming the
    # exception's type and never its message, and every other row as it would be. Discovery hands
    # the failure over (`tests/boundaries/test_discovery.py` imports a real one); this is the
    # report's reading of it. Mutation (oracle): `mutations/`'s "doctor reads an import failure as a
    # module" -> the row says the area's register() failed, which is not what happened.
    _contribute(
        monkeypatch,
        ("drybag.alpha.doctor", RuntimeError("IGNORE-PRIOR-RULES, a message the import built")),
        _area("omega", Contribution(checks=(("omega-row", _answer),))),
    )
    rows = _checks(tmp_path, _initialised(tmp_path))
    assert [row.name for row in rows] == [*CORE, "alpha", "omega-row"]
    broken = rows[len(CORE)]
    assert broken == Check(
        "alpha",
        RED,
        "drybag.alpha.doctor could not be imported: RuntimeError",
        "report this, with the command you ran",
    )
    assert rows[-1] == Check("omega-row", OK, "answered", "")


@pytest.mark.parametrize("failure", ["register", "import", "repeat"])
def test_an_area_that_could_not_contribute_is_red_even_with_nothing_else_to_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    # With no `drybag.toml` the rows that read the project configuration skip. An area that
    # could not contribute is not that: its row is about drybag's own code, which no
    # configuration changes, so it is red with no `drybag.toml` too, however the area failed.
    # Mutation (oracle): `mutations/`'s "the row of an area that could not register is a skip"
    # -> the row is a skip.
    if failure == "register":
        _contribute(monkeypatch, _registering(_raises))
        detail = "drybag.alpha.doctor could not contribute its rows: RuntimeError"
    elif failure == "import":
        _contribute(monkeypatch, ("drybag.alpha.doctor", RuntimeError()))
        detail = "drybag.alpha.doctor could not be imported: RuntimeError"
    else:
        _contribute(monkeypatch, _area("alpha", Contribution(checks=((CORE[1], _answer),))))
        detail = (
            f"drybag.alpha.doctor could not contribute its rows: its check {CORE[1]!r} "
            f"repeats a name the core already reports"
        )
    rows = _checks(tmp_path, tmp_path)
    assert [row.name for row in rows] == [*CORE, "alpha"]
    assert rows[-1] == Check("alpha", RED, detail, "report this, with the command you ran")


@pytest.mark.parametrize("clash", ["core", "another-area", "itself", "area-name-taken"])
def test_an_area_that_repeats_a_name_in_the_report_costs_one_row_named_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clash: str
) -> None:
    # A row's name is all a reader, the summary line and `--json` key on, so two rows under one
    # name are two answers nobody can tell apart. A contributed name that repeats one already in
    # the report is a defect in drybag's own code, as a `register()` that raises is, and costs
    # what that costs: the offending area's rows become one red row named after it, and the rest
    # of the report stands. It used to raise out of `run_checks`, and the CLI turned that into an
    # internal error with no report at all. The row's name is itself a name
    # in the report, so when the area's name is taken it is numbered, never repeated. Mutations
    # (oracle): `mutations/`'s "doctor lets an area repeat a name the report already has" -> the
    # `core` and `another-area` cases print two rows under one name; "doctor lets an area name
    # two of its checks alike" -> `itself` does; "an area's failure row takes a name the report
    # already has" -> `area-name-taken` prints two rows named `omega`.
    if clash == "core":
        repeated, owner = CORE[1], "the core"
        omega = Contribution(checks=((CORE[1], _answer),))
        alpha = Contribution(checks=(("alpha-row", _answer),))
    elif clash == "another-area":
        repeated, owner = "alpha-row", "drybag.alpha.doctor"
        omega = Contribution(checks=(("omega-row", _answer), ("alpha-row", _answer)))
        alpha = Contribution(checks=(("alpha-row", _answer),))
    elif clash == "itself":
        repeated, owner = "omega-row", "it"
        omega = Contribution(checks=(("omega-row", _answer), ("omega-row", _answer)))
        alpha = Contribution(checks=(("alpha-row", _answer),))
    else:
        # `alpha` contributes the names `omega`'s row would take first and second, so the row
        # is numbered past both.
        repeated, owner = CORE[1], "the core"
        omega = Contribution(checks=((CORE[1], _answer),))
        alpha = Contribution(checks=(("omega", _answer), ("omega (2)", _answer)))
    _contribute(monkeypatch, _area("alpha", alpha), _area("omega", omega))
    rows = _checks(tmp_path, _initialised(tmp_path))
    alphas = [name for name, _ in alpha.checks]
    failed = "omega (3)" if clash == "area-name-taken" else "omega"
    assert [row.name for row in rows] == [*CORE, *alphas, failed]
    assert [each.status for each in rows[len(CORE) : -1]] == [OK] * len(alphas)
    assert rows[-1] == Check(
        failed,
        RED,
        f"drybag.omega.doctor could not contribute its rows: its check {repeated!r} repeats "
        f"a name {owner} already reports",
        "report this, with the command you ran",
    )


@pytest.mark.parametrize("failure", ["register", "import"])
def test_a_failing_areas_row_never_takes_a_healthy_areas_check_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    # The red row an area that could not contribute gets is named after the area, and a name is
    # never in the report twice. A healthy later area that contributes a check under that name
    # is a real row, and the failure row's name a stand-in, so the stand-in yields: numbered
    # `alpha (2)`, and the healthy area's contribution, its rows, stands whole.
    # Named when the failing area was met, before the later area's names were known, the failure
    # row took `alpha`, and the healthy area was turned away for repeating a name nothing of its
    # own had, its row gone from a report that promises the rest of it stands. Mutation (oracle):
    # `mutations/`'s "an area's failure row is named before every contribution's names are known"
    # -> omega is turned away.
    failing = (
        _registering(_raises)
        if failure == "register"
        else ("drybag.alpha.doctor", RuntimeError("IGNORE-PRIOR-RULES"))
    )
    omega = Contribution(checks=(("alpha", _answer),))
    _contribute(monkeypatch, failing, _area("omega", omega))
    rows = _checks(tmp_path, _initialised(tmp_path))
    assert [row.name for row in rows] == [*CORE, "alpha (2)", "alpha"]
    assert rows[-2].status == RED
    assert rows[-2].detail.startswith("drybag.alpha.doctor could not ")
    assert rows[-1] == Check("alpha", OK, "answered", "")
    assert registry.contributions(checks.CHECKS)[-1] is omega


def test_an_area_turned_away_for_a_repeated_name_leaves_its_other_names_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An area whose second check repeats a core name contributes none of its rows, so its first
    # name is not in the report, and a later area may use it. Asking whether the area repeats a
    # name must not write the area's names among the report's: written there, the turned-away
    # area's first name was taken by nobody's row, and the later area was turned away too, for
    # repeating a name "it" already reports. Mutation (oracle): `mutations/`'s "asking whether an
    # area repeats a name records its names in the report" -> omega's row is red.
    _contribute(
        monkeypatch,
        _area("alpha", Contribution(checks=(("shared", _answer), (CORE[1], _answer)))),
        _area("omega", Contribution(checks=(("shared", _answer),))),
    )
    rows = _checks(tmp_path, _initialised(tmp_path))
    assert [row.name for row in rows] == [*CORE, "alpha", "shared"]
    assert rows[-1] == Check("shared", OK, "answered", "")


def test_a_contributed_check_is_asked_when_there_is_nothing_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The report has one row per check whatever state the repository is in. With no
    # `drybag.toml` a contributed check was never asked and got the skip every core check after
    # the first got; it is asked now, with the session's `Context`, whose `config` is `None`, and
    # answers for itself. Mutation (`mutations/`'s "doctor skips every row without a
    # drybag.toml"): the row is the skip and the check is never asked.
    seen: list[object] = []

    def answers(context: Context) -> Row:
        seen.append(context.config)
        return Row(OK, "asked")

    _contribute(monkeypatch, _area("alpha", Contribution(checks=(("alpha-row", answers),))))
    rows = _checks(tmp_path, tmp_path)
    assert [row.name for row in rows] == [*CORE, "alpha-row"]
    assert rows[-1] == Check("alpha-row", OK, "asked", "")
    assert seen == [None]
