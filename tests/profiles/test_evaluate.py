"""The three check kinds against a repository, and what a repository's bytes may not do."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from stayfixed.findings import Severity
from stayfixed.profiles.evaluate import detects, evaluate
from stayfixed.profiles.model import Check, CheckKind, Locator, Profile
from tests.gitfixture import git, needs_git


def _profile(*checks: Check, detect: tuple[str, ...] = ("manifest.cfg",)) -> Profile:
    return Profile("demo", detect, ("**/*",), ("line",), checks, "")


def _check(kind: CheckKind, *locators: Locator) -> Check:
    return Check(f"{kind}-check", kind, Severity.ADVICE, locators, "do the thing")


def test_detection_reads_root_level_names_and_globs(tmp_path: Path) -> None:
    assert not detects(_profile(detect=("lock-*.txt",)), tmp_path)
    (tmp_path / "lock-dev.txt").write_text("", encoding="utf-8")
    assert detects(_profile(detect=("lock-*.txt",)), tmp_path)


def test_present_reports_only_when_no_locator_resolves(tmp_path: Path) -> None:
    # Advisory output, so the mutation stays here rather than in `mutations/`: the
    # `present` arm's `hits = [] if any(...) else locators` -> `hits = []` reddens the first
    # assertion, and `_names` without `dict.fromkeys` reddens it too.
    check = _check(
        CheckKind.PRESENT,
        Locator("a.toml", toml="tool.checker"),
        Locator("b.ini", ini=("checker",)),
        Locator("a.toml", toml="tool.other"),
    )
    outcomes = evaluate(_profile(check), tmp_path)
    # Each `at` once, in the profile's order, however many locators share it.
    assert [(o.check.id, o.located) for o in outcomes] == [("present-check", ("a.toml", "b.ini"))]
    (tmp_path / "b.ini").write_text("[checker]\nstrict = true\n", encoding="utf-8")
    assert evaluate(_profile(check), tmp_path) == []


def test_a_file_at_the_text_cap_is_read_and_one_past_it_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A profile reads configuration files, each held to `_TEXT_CAP`: one at the cap is read, one
    # past it reads as no file. The cap is lowered so the files are small. Mutations (oracle):
    # `mutations/`'s "a profile reads a configuration file past its cap" -> the longer one is
    # read; "a profile refuses a configuration file at its cap" -> the shorter one is not.
    check = _check(CheckKind.PRESENT, Locator("a.toml", toml="tool.checker"))
    text = "[tool]\nchecker = 1\n"
    (tmp_path / "a.toml").write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        importlib.import_module("stayfixed.profiles.evaluate"), "_TEXT_CAP", len(text)
    )
    assert evaluate(_profile(check), tmp_path) == []
    (tmp_path / "a.toml").write_text(text + "#", encoding="utf-8")
    assert [o.check.id for o in evaluate(_profile(check), tmp_path)] == ["present-check"]


def test_absent_reports_the_locators_whose_value_matches(tmp_path: Path) -> None:
    check = _check(
        CheckKind.ABSENT,
        Locator("a.toml", toml="project.floor", match=re.compile("<")),
        Locator("b.ini", ini=("project", "floor"), match=re.compile("<")),
    )
    (tmp_path / "a.toml").write_text('[project]\nfloor = ">=3,<4"\n', encoding="utf-8")
    (tmp_path / "b.ini").write_text("[project]\nfloor = >=3\n", encoding="utf-8")
    outcomes = evaluate(_profile(check), tmp_path)
    assert [(o.check.id, o.located) for o in outcomes] == [("absent-check", ("a.toml",))]


def test_an_ini_section_whose_name_holds_a_dot_is_addressed_whole(tmp_path: Path) -> None:
    check = _check(CheckKind.PRESENT, Locator("setup.cfg", ini=("mypy-pkg.mod",)))
    (tmp_path / "setup.cfg").write_text("[mypy-pkg.mod]\nstrict = true\n", encoding="utf-8")
    assert evaluate(_profile(check), tmp_path) == []


def test_a_list_value_is_matched_as_the_words_it_holds(tmp_path: Path) -> None:
    check = _check(
        CheckKind.ABSENT, Locator("a.toml", toml="lint.select", match=re.compile(r"^E F$"))
    )
    (tmp_path / "a.toml").write_text('[lint]\nselect = ["E", "F"]\n', encoding="utf-8")
    assert len(evaluate(_profile(check), tmp_path)) == 1


def test_a_boolean_is_matched_as_toml_spells_it(tmp_path: Path) -> None:
    check = _check(
        CheckKind.PRESENT, Locator("a.toml", toml="tool.strict", match=re.compile("^true$"))
    )
    (tmp_path / "a.toml").write_text("[tool]\nstrict = true\n", encoding="utf-8")
    assert evaluate(_profile(check), tmp_path) == []


@pytest.mark.parametrize(
    "text",
    [
        "[tool\nchecker = 1\n",
        "checker = " + "[" * 1000 + "]" * 1000 + "\n",
        "[tool]\nchecker = 0x" + "f" * 5_000 + "\n",
    ],
    ids=["malformed", "nested-past-the-stack", "hex-past-str"],
)
def test_a_file_that_does_not_parse_resolves_to_nothing(tmp_path: Path, text: str) -> None:
    # A repository chooses these bytes. About a kilobyte of nested arrays is enough for
    # `tomllib` to raise `RecursionError` rather than `TOMLDecodeError` (measured on 3.13.0 at a
    # depth of 500), and a raise here would end the whole evaluation, not one locator. A hex
    # literal of any length parses, and `str()` of it past 4,300 digits raises `ValueError` when
    # the locator reads its text: the `assess` command ended in an internal error. Mutations: drop
    # `RecursionError` from `_toml_document`'s catch (declared) or from `_toml_value`'s (by hand;
    # advisory output) -> `nested-past-the-stack` reddens; `mutations/`'s "a profile locator
    # stringifies a number past the conversion limit" -> `hex-past-str` reddens.
    check = _check(CheckKind.PRESENT, Locator("a.toml", toml="tool.checker"))
    (tmp_path / "a.toml").write_text(text, encoding="utf-8")
    assert [o.check.id for o in evaluate(_profile(check), tmp_path)] == ["present-check"]


@pytest.mark.parametrize(
    "text",
    ["addopts = -ra\n", "[pytest]\nno value here\n", "[pytest]\n  a continuation first\n"],
    ids=["no-section-header", "line-without-a-value", "continuation-without-a-key"],
)
def test_an_ini_file_that_does_not_parse_resolves_to_nothing(tmp_path: Path, text: str) -> None:
    # `configparser` refuses each of these with an error of its own (`MissingSectionHeaderError`
    # or `ParsingError`); the locator resolves to nothing rather than the error ending the
    # evaluation. Advisory output, so the mutation stays here: drop `_ini_value`'s
    # `except configparser.Error` -> every case reddens.
    check = _check(CheckKind.PRESENT, Locator("pytest.ini", ini=("pytest", "addopts")))
    (tmp_path / "pytest.ini").write_text(text, encoding="utf-8")
    assert [o.check.id for o in evaluate(_profile(check), tmp_path)] == ["present-check"]


def test_a_locator_through_a_symlink_out_of_the_root_resolves_to_nothing(tmp_path: Path) -> None:
    # A bare locator: no key is read, so `_read`'s own containment is never asked, and
    # `_files`' is the only guard between the planted link and a "present" answer.
    outside = tmp_path / "outside.ini"
    outside.write_text("[checker]\n", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "checker.ini").symlink_to(outside)
    check = _check(CheckKind.PRESENT, Locator("checker.ini"))
    assert [o.check.id for o in evaluate(_profile(check), root)] == ["present-check"]


@needs_git
def test_tracked_reports_a_located_file_git_neither_tracks_nor_ignores(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "lock.txt").write_text("", encoding="utf-8")
    check = _check(CheckKind.TRACKED, Locator("lock.txt"), Locator("other.txt"))
    # Only the locator whose file is untracked is named.
    assert [o.located for o in evaluate(_profile(check), tmp_path)] == [("lock.txt",)]
    git(tmp_path, "add", "lock.txt")
    assert evaluate(_profile(check), tmp_path) == []


@needs_git
def test_tracked_leaves_a_file_the_repository_ignores_on_purpose(tmp_path: Path) -> None:
    # A library that runs unlocked ignores its lock, and a package manager writes the lock again
    # on the next run, so "untracked" alone would be a warning that never clears. Advisory
    # output, so the mutation stays here: drop `--exclude-standard` from `_untracked` -> reddens.
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / ".gitignore").write_text("lock.txt\n", encoding="utf-8")
    (tmp_path / "lock.txt").write_text("", encoding="utf-8")
    assert evaluate(_profile(_check(CheckKind.TRACKED, Locator("lock.txt"))), tmp_path) == []


def test_tracked_says_nothing_outside_a_git_repository(tmp_path: Path) -> None:
    # A behaviour pin, not a guard's own test, and no mutation reddens it: outside a work tree
    # `git ls-files` exits 128 and writes nothing to stdout, so `_untracked` answers False by its
    # `code == 0` check and by its empty output alike; dropping either one alone leaves this
    # green. No separate "is this a repository" probe runs first, because none would be
    # load-bearing.
    (tmp_path / "lock.txt").write_text("", encoding="utf-8")
    check = _check(CheckKind.TRACKED, Locator("lock.txt"))
    assert evaluate(_profile(check), tmp_path) == []


@needs_git
def test_tracked_names_a_located_file_git_gave_no_answer_for_rather_than_passing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `git_run`'s `(-1, "")` — git could not be run or ran past its bound — read as "not
    # untracked" and the check passed without having looked. It is its own answer now: the
    # outcome names the locator under `unanswered`, and `located` stays what git did say.
    # Mutation (advisory): `_untracked` answering `False` for `-1` again — no outcome comes back
    # and this reddens.
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "lock.txt").write_text("", encoding="utf-8")
    # The package re-exports the function `evaluate` under the submodule's name, so the module
    # is taken from the import system rather than by attribute.
    module = importlib.import_module("stayfixed.profiles.evaluate")
    monkeypatch.setattr(module, "git_run", lambda *args, **kwargs: (-1, ""))
    check = _check(CheckKind.TRACKED, Locator("lock.txt"), Locator("other.txt"))
    outcomes = evaluate(_profile(check), tmp_path)
    assert [(o.located, o.unanswered) for o in outcomes] == [((), ("lock.txt",))]


def test_tracked_names_a_located_file_in_a_repository_git_refuses_rather_than_passing_it(
    tmp_path: Path,
) -> None:
    # A worktree whose git directory is gone: git exits 128 exactly as it does outside a
    # repository, and "not untracked" passed the check without looking, where every other probe
    # reports `could-not-look` for the same checkout. Read off the disk, as trail and the ledger
    # read it. Mutation (declared): `_untracked` answering only `-1` as no answer -> no outcome.
    (tmp_path / ".git").write_text(f"gitdir: {tmp_path / 'gone'}\n", encoding="utf-8")
    (tmp_path / "lock.txt").write_text("", encoding="utf-8")
    check = _check(CheckKind.TRACKED, Locator("lock.txt"))
    outcomes = evaluate(_profile(check), tmp_path)
    assert [(o.located, o.unanswered) for o in outcomes] == [((), ("lock.txt",))]
