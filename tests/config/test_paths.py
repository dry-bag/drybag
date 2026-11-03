from __future__ import annotations

import errno
import os
from dataclasses import fields
from pathlib import Path

import pytest

from stayfixed.config import paths
from stayfixed.config.loader import CONFIG_FILE, load, loads
from stayfixed.config.paths import (
    PATH_RULE,
    PATH_VALUE_LIMIT,
    STAYFIXED_DIRECTORY,
    PathEscape,
    contained,
    validate_paths,
)
from stayfixed.config.schema import Config, Paths
from stayfixed.fsops import UnsafePath, checked_components, write_within
from stayfixed.grammar import PATH_VALUE
from tests.crafted import CRAFTED, assert_never_raw
from tests.pathfaults import (
    LSTAT_FAULT,
    lstat_fault,
    shaped,
    symlink_loop_at,
    unlock,
    unmet_here,
)

PATH_NAMES = tuple(f.name for f in fields(Paths))


def test_a_plain_relative_path_resolves_under_the_root(tmp_path: Path) -> None:
    assert contained(tmp_path, "docs/specs") == tmp_path / "docs" / "specs"


@pytest.mark.parametrize(
    "relative",
    [
        "../sibling",
        "docs/../../x",
        "/etc/stayfixed",
        "",
        ".",
        "./",
        "././",
        "./.",
        "docs/./../..",
    ],
)
def test_escapes_are_refused(tmp_path: Path, relative: str) -> None:
    with pytest.raises(PathEscape):
        contained(tmp_path, relative)


def test_dotdot_is_refused_even_when_it_resolves_inside_the_root(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    with pytest.raises(PathEscape, match=r"'\.\.'"):
        contained(tmp_path, "docs/../docs/specs")


def test_a_symlinked_intermediate_directory_is_refused(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "docs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathEscape, match="symlink"):
        contained(tmp_path, "docs/specs")


def test_a_crafted_symlink_on_the_way_is_named_escaped_never_raw(tmp_path: Path) -> None:
    # The refusal names the symlinked ancestor, and in a checkout that directory's name is the
    # repository's. `relative` was quoted and the ancestor was not, so a caller that shows the
    # refusal — the memory store records it as a group's reason — printed a line break and an
    # escape sequence raw. Mutation: format `ancestor` unquoted in `contained` — this reddens.
    # And by its place under the root, never by where this machine keeps the root: mutation
    # (`mutations/`'s "contained names the symlinked ancestor by its absolute path").
    (tmp_path / "real").mkdir()
    (tmp_path / CRAFTED).symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(PathEscape, match="passes through a symlink at") as raised:
        contained(tmp_path, f"{CRAFTED}/sub")
    assert_never_raw(str(raised.value))
    assert str(raised.value).endswith(f"passes through a symlink at {CRAFTED!r}")
    assert str(tmp_path) not in str(raised.value)


# What `contained` answers when an ancestor's `lstat` meets each fault: the path, or the refusal's
# ending. Only the shapes whose path an `lstat` cannot find something at, since the ones it can are
# the link and no-link cases above.
CONTAINED_ANSWERS: dict[str, str | None] = {
    "nothing-there": None,
    "below-a-file": None,
    "a-name-longer-than-a-name": None,
    "past-the-longest-path": None,
    # The link is still found: an `lstat` of the link itself does not follow it.
    "through-a-link-loop": "passes through a symlink at 'loop'",
    "through-a-link-to-a-name-longer-than-a-name": "passes through a symlink at 'far'",
    "below-a-directory-that-cannot-be-searched": (
        "cannot be checked for a symlink at 'locked/child' (Permission denied)"
    ),
    # The link above the ancestor no `lstat` can ask is the cause, so it is the one named.
    "through-a-link-into-a-directory-that-cannot-be-searched": (
        "passes through a symlink at 'into-locked'"
    ),
}


@pytest.mark.parametrize("shape", sorted(CONTAINED_ANSWERS))
def test_each_fault_an_ancestor_meets_has_one_answer_on_every_interpreter(
    tmp_path: Path, shape: str
) -> None:
    # `Path.is_symlink()` raised `ENAMETOOLONG` up to Python 3.13 and answered `False` from 3.14,
    # so `attach` over a group directory that fits, with its placeholder name inside past the
    # longest path, was an internal error on one interpreter and attached on the other. A path
    # that reaches no file holds no link to follow; a fault that leaves the question open is a
    # refusal in words, by the ancestor's place under the root and never its absolute path.
    #
    # Mutations (oracle): `mutations/`'s "the path predicates read a name longer than the system
    # takes as a fault" -> the two over-long shapes refuse; "contained reads an ancestor it cannot
    # ask about as no link" -> the unsearchable directory is contained.
    if unmet_here(shape):
        pytest.skip("root searches every directory")
    relative = shaped(tmp_path, shape)
    try:
        assert lstat_fault(tmp_path / relative) == LSTAT_FAULT[shape]
        refused = CONTAINED_ANSWERS[shape]
        if refused is None:
            assert contained(tmp_path, relative) == tmp_path / relative
        else:
            with pytest.raises(PathEscape) as raised:
                contained(tmp_path, relative)
            assert str(raised.value) == f"{relative!r} {refused}"
    finally:
        unlock(tmp_path)


def test_a_link_inside_a_tree_past_the_longest_path_is_missed_by_contained_and_refused_by_the_write(
    tmp_path: Path,
) -> None:
    # `contained`'s own comment makes this argument, and nothing held it: an ancestor whose
    # `lstat` meets `ENAMETOOLONG` is read as no link, so a link inside a real tree past the
    # longest path is not seen there. The descriptor walk every write goes through reaches it one
    # component at a time and refuses it of its own accord, and that is the safety. Built by
    # descriptor, as only such a walk can. Mutations (oracle): `mutations/`'s "the path predicates
    # read a name longer than the system takes as a fault" -> `contained` refuses instead; "the
    # containment walk follows a symlinked directory" -> the write lands outside.
    longest = os.pathconf(tmp_path, "PC_PATH_MAX")
    outside = tmp_path / "outside"
    outside.mkdir()
    parts: list[str] = []
    descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        while len(str(tmp_path / "/".join(parts))) <= longest:
            os.mkdir("d" * 200, dir_fd=descriptor)
            below = os.open("d" * 200, os.O_RDONLY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = below
            parts.append("d" * 200)
        os.symlink(outside, "link", dir_fd=descriptor)
    finally:
        os.close(descriptor)
    # The premise: the link's own path is one no `lstat` can be handed.
    assert lstat_fault(tmp_path.joinpath(*parts, "link")) == errno.ENAMETOOLONG
    relative = "/".join([*parts, "link", "note.md"])
    assert contained(tmp_path, relative) == tmp_path / relative
    with pytest.raises(UnsafePath):
        write_within(tmp_path, relative, "text\n")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("interpreter", ["this-one", "as-3-11"])
def test_a_root_through_a_symlink_loop_is_an_oserror_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interpreter: str
) -> None:
    # `contained` resolves the root last, and on Python 3.11 and 3.12 a loop there raised
    # `RuntimeError` past every caller's `except OSError`: `setup --home <a loop>` was an
    # internal error. Through `fsops.resolved` it is the system's `ELOOP`, naming the root, on
    # every interpreter. Mutation (`mutations/`'s "contained resolves its root past fsops") ->
    # `as-3-11` raises `RuntimeError`.
    root = tmp_path / "loop"
    if interpreter == "as-3-11":
        symlink_loop_at(monkeypatch, root)
    else:
        root.symlink_to(root)
    with pytest.raises(OSError) as raised:
        contained(root, "a")
    assert raised.value.errno == errno.ELOOP
    assert raised.value.filename == str(root)


def test_a_symlink_pointing_inside_the_root_is_still_refused(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "docs").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(PathEscape, match="symlink"):
        contained(tmp_path, "docs/specs")


def test_a_final_symlink_is_refused_unless_allowed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-store"
    outside.mkdir()
    (tmp_path / "docs").mkdir()
    os.symlink(outside, tmp_path / "docs" / "notes", target_is_directory=True)
    with pytest.raises(PathEscape, match="symlink"):
        contained(tmp_path, "docs/notes")
    allowed = contained(tmp_path, "docs/notes", allow_final_symlink=True)
    assert allowed == tmp_path / "docs" / "notes"


def test_a_symlinked_root_does_not_confuse_containment(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert contained(link, "docs") == link / "docs"


def test_allow_final_symlink_does_not_relax_an_intermediate_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "docs").symlink_to(real, target_is_directory=True)
    with pytest.raises(PathEscape, match="symlink"):
        contained(tmp_path, "docs/notes", allow_final_symlink=True)


def test_a_supplied_resolved_root_is_the_one_compared(tmp_path: Path) -> None:
    # `validate_paths` resolves the root once and passes it down. Nothing else reaches the
    # containment comparison — the guards above it refuse every escape a path string can
    # express — so the parameter that feeds it is pinned here rather than through a config.
    (tmp_path / "docs").mkdir()
    assert contained(tmp_path, "docs", resolved_root=tmp_path.resolve()) == tmp_path / "docs"
    with pytest.raises(PathEscape, match="resolves outside the project root"):
        contained(tmp_path, "docs", resolved_root=tmp_path / "elsewhere")


def test_validate_paths_allows_a_final_symlink_only_for_the_memory_path(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILE).write_text(
        '[stayfixed]\nversion = "0.1.0"\npreset = "recommended"\n\n[project]\nname = "sample"\n',
        encoding="utf-8",
    )
    config = load(tmp_path, machine=tmp_path / "no-machine.toml")

    outside = tmp_path / "outside"
    outside.mkdir()

    accepted_root = tmp_path / "accepted"
    (accepted_root / "docs").mkdir(parents=True)
    (accepted_root / "docs" / "memory").symlink_to(outside, target_is_directory=True)
    result = validate_paths(config, accepted_root)
    assert result["memory"] == accepted_root / "docs" / "memory"

    refused_root = tmp_path / "refused"
    (refused_root / "docs").mkdir(parents=True)
    (refused_root / "docs" / "specs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathEscape, match="symlink"):
        validate_paths(config, refused_root)


def _sample_config(tmp_path: Path) -> Config:
    (tmp_path / CONFIG_FILE).write_text(
        '[stayfixed]\nversion = "0.1.0"\npreset = "recommended"\n\n[project]\nname = "sample"\n',
        encoding="utf-8",
    )
    return load(tmp_path, machine=tmp_path / "no-machine.toml")


_NOT_EXEMPT = {
    "agents_md",
    "architecture",
    "runbooks",
    "adr",
    "specs",
    "plans",
    "bugs",
    "bug_index",
    "roadmap",
    "roadmap_history",
    "stayfixed",
}


def test_every_configured_path_is_parametrised_here() -> None:
    # The exemption below is checked per field, so a path added to `Paths` without a row here
    # would inherit whatever `validate_paths` decides for it, untested.
    assert set(PATH_NAMES) == _NOT_EXEMPT | {"memory"}


@pytest.mark.parametrize("name", PATH_NAMES)
def test_the_final_symlink_exemption_holds_for_memory_and_for_no_other_path(
    tmp_path: Path, name: str
) -> None:
    # One negative example cannot tell "only memory" from "anything but that one example":
    # widening the exemption to any other path must fail here, on each of them.
    config = _sample_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    root = tmp_path / f"root-{name}"
    relative = Path(config.paths.as_dict()[name])
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, root / relative, target_is_directory=True)

    if name == "memory":
        assert validate_paths(config, root)[name] == root / relative
        return
    with pytest.raises(PathEscape, match="symlink"):
        validate_paths(config, root)


def test_a_paths_value_outside_the_grammar_is_refused_and_never_quoted(tmp_path: Path) -> None:
    # A repository-authored value is never printed raw. A multi-line value loads today and
    # `render_report` would print it raw. Mutation (oracle): drop the `PATH_VALUE` check from
    # `validate_paths` -> this reddens.
    text = (
        '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
        '[paths]\nspecs = """docs/\n\n=== NOTICE ===\nspecs"""\n'
    )
    with pytest.raises(PathEscape) as caught:
        loads(text, tmp_path, machine=tmp_path / "absent.toml")
    assert "paths.specs" in str(caught.value) and "NOTICE" not in str(caught.value)
    for value in ("docs/specs", "design/specs.v2", ".stayfixed/local/x", "AGENTS.md"):
        assert PATH_VALUE.match(value), value
    for value in ("docs/ specs", "docs/spécs", "-docs", "docs/`x`", "docs/x\n"):
        assert PATH_VALUE.match(value) is None, value


def test_a_paths_value_longer_than_its_cap_is_refused_naming_the_key(tmp_path: Path) -> None:
    # Every reader of a `[paths]` value pays for its length and every `PreToolUse` hook reads every
    # value, so one past `PATH_VALUE_LIMIT` is refused before anything else reads it, by its key
    # and never by the value; one of exactly the cap, sound otherwise, loads. Mutations
    # (`mutations/`'s "a [paths] value may be any length" -> the longer value loads; "the [paths]
    # length cap refuses a value of its own length" -> the one at the cap is refused).
    head = '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n[paths]\n'
    segments = "/".join(["a" * 99] * 10)
    at_cap = f"{segments}/{'b' * (PATH_VALUE_LIMIT - len(segments) - 1)}"
    assert len(at_cap) == PATH_VALUE_LIMIT
    machine = tmp_path / "absent.toml"
    assert loads(f'{head}specs = "{at_cap}"\n', tmp_path, machine=machine).paths.specs == at_cap
    with pytest.raises(PathEscape) as caught:
        loads(f'{head}specs = "{at_cap}b"\n', tmp_path, machine=machine)
    assert caught.value.key == "paths.specs"
    assert "paths.specs" in str(caught.value) and "aaa" not in str(caught.value)


class _Asking:
    """`os` as `config.paths` sees it, with every `lstat` it asks recorded."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def lstat(self, path: Path) -> os.stat_result:
        self.asked.append(os.fspath(path))
        return os.lstat(path)

    def __getattr__(self, name: str) -> object:
        return getattr(os, name)


def test_contained_asks_no_ancestor_below_the_first_that_is_not_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every path below an ancestor that reaches no file reaches none either, so the walk down from
    # the root stops there. Walked up from the target, `contained()` built, compared with the root
    # and asked every ancestor, and twenty thousand components cost it two and a half seconds;
    # here it asks the two that are there and the first that is not. Counted rather than timed, so
    # no load moves it. Mutation (`mutations/`'s "contained asks every ancestor of a value that
    # reaches no file"): it asks all 2,001.
    (tmp_path / "a" / "a").mkdir(parents=True)
    asking = _Asking()
    monkeypatch.setattr(paths, "os", asking)
    deep = "a/" * 2_000 + "AGENTS.md"
    assert contained(tmp_path, deep) == tmp_path.joinpath(*deep.split("/"))
    assert len(asking.asked) == 3, len(asking.asked)
    assert asking.asked == [str(tmp_path.joinpath(*["a"] * depth)) for depth in (1, 2, 3)]


# Every spelling the two readers of a path could have disagreed about, and the plain ones they
# never did. Shared by the three assertions below so one list of spellings answers all of them.
ADMITTED = ("docs/specs", "design/specs.v2", ".stayfixed/local/x", "AGENTS.md", "docs/.hidden")
REFUSED = (
    "docs//roadmap-history.md",  # an empty component
    "design/handbooks/",  # a trailing slash
    "./docs",  # a leading './'
    "docs/./x.md",  # a '.' component anywhere
    "docs/../x.md",  # a '..' component the charset spells out of ordinary letters
    "docs/..",  # a '..' component that ends the value
    ".",
    "..",
    "/etc/stayfixed",
    "",
)


def test_the_grammar_admits_exactly_what_the_component_rule_accepts() -> None:
    # The shape of the defect: `PATH_VALUE` and `fsops.checked_components` are the two readers
    # of a `[paths]` value, and they have to answer the same question. They did not. The charset
    # form admitted an empty component, a trailing slash and a leading `./`, every one of which
    # `checked_components` refuses — so a value could clear the grammar, clear `contained()`
    # (which normalised it away through `Path(relative).parts`) and still be refused by the walk
    # at the write. Asserted as an equivalence rather than as two lists, because two lists that
    # agree today are what shipped.
    #
    # `-docs` is the one deliberate asymmetry: the charset refuses a leading `-`, which the
    # component rule has no opinion about. So the implication is stated in the direction that
    # matters — grammar implies component rule — and the reverse is asserted only for the
    # spellings the charset admits.
    for value in ADMITTED:
        assert PATH_VALUE.match(value), value
        assert checked_components(value), value
    for value in REFUSED:
        assert PATH_VALUE.match(value) is None, value
        with pytest.raises(UnsafePath):
            checked_components(value)


def test_a_value_the_grammar_admits_is_one_the_write_can_reach(tmp_path: Path) -> None:
    # The round trip the suite was missing, at the level of the two functions: everything the
    # grammar lets through is something `contained()` accepts and `fsops` actually writes. The
    # defect was exactly the absence of this — `plan` said yes, `apply` raised.
    for value in ADMITTED:
        root = tmp_path / value.replace("/", "-").replace(".", "_")
        root.mkdir()
        assert contained(root, value) == root.joinpath(*value.split("/"))
        write_within(root, value, "body\n")
        assert (root / value).read_text(encoding="utf-8") == "body\n"


def test_contained_refuses_every_spelling_the_write_would_refuse(tmp_path: Path) -> None:
    # The other half, and the one that closes the half-write: `contained()` is what `plan()`
    # asks, so a spelling the walk refuses has to be refused here — before `apply()` has put a
    # single artifact on disk. It was not: `Path('docs//x.md').parts` is `('docs', 'x.md')`.
    #
    # Mutation (oracle): `parts = checked_components(relative)` ->
    # `parts = Path(relative).parts` -> this reddens.
    for value in REFUSED:
        with pytest.raises(PathEscape):
            contained(tmp_path, value)


def test_a_paths_value_naming_gits_control_directory_is_refused_and_never_quoted(
    tmp_path: Path,
) -> None:
    # `.git` was reserved by nothing: the grammar admits a leading dot, and `contained()`
    # refused an absolute path, `..` and a symlink but not a control directory. The `agents-md`
    # artifact is a `MANAGED_REGION`, so it is exempt from the engine's "exists and stayfixed did
    # not write it" guard and takes the `region_update` path — and `fsops._mode_of` carries the
    # existing 0755 onto the replacement, so a clone got the developer's own pre-commit hook
    # rewritten in place by choosing one string in its own `stayfixed.toml`.
    #
    # The refusal names the key and never the value, which is the rule `validate_paths` already
    # follows for the charset. Mutation (oracle): drop the check from `validate_paths`.
    text = (
        '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
        '[paths]\nagents_md = ".git/hooks/pre-commit"\n'
    )
    with pytest.raises(PathEscape) as caught:
        loads(text, tmp_path, machine=tmp_path / "absent.toml")
    assert "paths.agents_md" in str(caught.value)
    assert "pre-commit" not in str(caught.value) and "hooks" not in str(caught.value)


@pytest.mark.parametrize(
    "value",
    [".git/hooks/pre-commit", ".GIT/config", "vendor/lib/.git/hooks/pre-commit", ".git"],
)
def test_contained_refuses_gits_control_directory_at_any_depth_and_in_any_case(
    tmp_path: Path, value: str
) -> None:
    # `contained()` is the function every configured path and every area-supplied path goes
    # through above the first write, so the rule has to hold here and not only in the grammar
    # loop: `ledger`, `memory` and `docs` all call it with strings `validate_paths` never sees.
    # The case arm is not decoration — the default filesystem on macOS is case-insensitive, so
    # `.GIT` reaches the same directory — and the depth arm is a submodule's control directory.
    with pytest.raises(PathEscape, match="control directory"):
        contained(tmp_path, value)


@pytest.mark.parametrize(
    "value",
    [
        ".stayfixed/local/attach.json",
        ".stayfixed/manifest.json",
        ".stayfixed/local/memory/developer/x.md",
        "packages/api/.stayfixed/local/attach.json",
        ".stayfixed",
    ],
)
def test_a_paths_value_inside_stayfixeds_own_directory_is_refused_and_never_quoted(
    tmp_path: Path, value: str
) -> None:
    # `.stayfixed/local/` holds attach's ledger and the local-only notes, state git never sees.
    # `agents-md` is a `MANAGED_REGION` inserted into whatever file `agents_md` names, so a
    # committed `agents_md = ".stayfixed/local/attach.json"` had `upgrade` rewrite the ledger.
    # Case and depth for the reasons `.git` has them: a case-folding filesystem, and a nested
    # package initialised on its own. The refusal names the key, never the value.
    # Mutation (oracle): `mutations/`'s "a [paths] value may name stayfixed's own directory".
    text = (
        '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
        f'[paths]\nagents_md = "{value}"\n'
    )
    with pytest.raises(PathEscape) as caught:
        loads(text, tmp_path, machine=tmp_path / "absent.toml")
    assert "paths.agents_md" in str(caught.value) and "stayfixed's own directory" in str(
        caught.value
    )
    assert "attach" not in str(caught.value) and "packages" not in str(caught.value)


def test_a_name_that_merely_resembles_stayfixeds_directory_is_admitted(tmp_path: Path) -> None:
    # The preset's own `[paths] stayfixed = "docs/stayfixed"` and any other near-miss load.
    for value in ("docs/stayfixed", ".stayfixed-notes/x.md", "docs/.stayfixedrc"):
        text = (
            '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
            f'[paths]\nroadmap = "{value}"\n'
        )
        assert loads(text, tmp_path, machine=tmp_path / "absent.toml").paths.roadmap == value


def test_every_file_stayfixed_keeps_in_its_own_directory_is_under_the_reserved_name() -> None:
    # `config` spells `.stayfixed` because it imports no area; the areas that keep files there
    # spell their own paths. This holds each of them under the reserved name, so a rename on
    # either side reddens here instead of leaving an area's state unprotected.
    from stayfixed.config.layout import ATTACH_LEDGER as LEDGER
    from stayfixed.memory.store import LOCAL_STORE
    from stayfixed.scaffold import LOCAL_ARTIFACTS, LOCAL_DIGESTS, LOCAL_ROOT, MANIFEST_PATH

    for path in (
        LEDGER,
        LOCAL_ROOT,
        LOCAL_ARTIFACTS,
        LOCAL_DIGESTS,
        MANIFEST_PATH.as_posix(),
        LOCAL_STORE.as_posix(),
    ):
        assert path.split("/")[0] == STAYFIXED_DIRECTORY, path


def test_stayfixeds_own_dotted_footprint_is_not_refused(tmp_path: Path) -> None:
    # The ruling this rule is narrow for: `.github/workflows/stayfixed.yml` is an artifact this
    # branch ships and `.stayfixed/` holds the manifest, so "refuse a leading dot" would refuse
    # stayfixed's own footprint. Pinned so a later widening of the rule fails here rather than in
    # a user's repository.
    for value in (".github/workflows/stayfixed.yml", ".stayfixed/manifest.json", ".gitignore"):
        assert contained(tmp_path, value) == tmp_path.joinpath(*value.split("/"))


def test_a_paths_value_outside_the_grammar_is_refused_in_words(tmp_path: Path) -> None:
    # The refusal named the key and then printed `PATH_VALUE.pattern` — a per-segment lookahead
    # that is correct and that no person reading a refusal can act on. The value itself is still
    # never quoted.
    (tmp_path / CONFIG_FILE).write_text(
        '[stayfixed]\nversion = "0.1.0"\n\n[project]\nname = "widget"\n\n'
        '[paths]\nroadmap = "docs//roadmap.md"\n',
        encoding="utf-8",
    )
    with pytest.raises(PathEscape) as caught:
        load(tmp_path, machine=tmp_path / "absent.toml")
    message = str(caught.value)
    assert message == f"paths.roadmap is not a plain relative path: {PATH_RULE}"
    assert PATH_VALUE.pattern not in message and "docs//" not in message
