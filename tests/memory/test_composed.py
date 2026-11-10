"""The composed store: the one directory under this machine's data directory that the harness
reads its memory from, named by the binding id and holding links into the overlay."""

from __future__ import annotations

import shutil
from pathlib import Path

from drybag.config.paths import data_directory
from drybag.memory.composed import build, withdraw
from drybag.memory.store import composed_directory as store_directory
from tests.tagged import with_tags

# A binding id as `secrets.token_hex(16)` draws one; the store is named by it and nothing else.
ID = "0123456789abcdef0123456789abcdef"


def an_overlay(tmp_path: Path) -> tuple[Path, Path]:
    """An overlay with the common notes, two groups of project `p` and its rendered index."""
    overlay = tmp_path / "overlay"
    (overlay / "common" / "memory").mkdir(parents=True)
    share = overlay / "projects" / "p" / "memory"
    (share / "project-stable").mkdir(parents=True)
    (share / "project-volatile").mkdir()
    (share / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    return overlay, share


def test_the_store_links_each_group_and_the_index_into_the_overlay(tmp_path: Path) -> None:
    # `developer` is the overlay's `common/memory` itself, as the link tree routes it, and every
    # other group is this project's own directory in the overlay; the index is the one
    # `memory index` renders in the project's share.
    overlay, share = an_overlay(tmp_path)
    store = build(overlay, "p", ID)
    assert store == data_directory() / "stores" / ID == store_directory(ID)
    assert store.is_dir()
    entries = sorted(store.iterdir())
    assert all(entry.is_symlink() for entry in entries)
    assert {entry.name: entry.resolve() for entry in entries} == {
        "developer": (overlay / "common" / "memory").resolve(),
        "project-stable": (share / "project-stable").resolve(),
        "project-volatile": (share / "project-volatile").resolve(),
        "MEMORY.md": (share / "MEMORY.md").resolve(),
    }


def test_a_rebuild_follows_the_overlay_and_keeps_a_note_the_harness_wrote(tmp_path: Path) -> None:
    # The harness writes into the directory it is pointed at, so a file there that is not a link
    # is a note, and a rebuild never removes it; a link to a group the overlay no longer holds goes,
    # and a group it gained is linked.
    overlay, share = an_overlay(tmp_path)
    store = build(overlay, "p", ID)
    assert store.is_dir()
    (store / "topic.md").write_text("the harness's note", encoding="utf-8")
    shutil.rmtree(share / "project-volatile")
    (share / "specs").mkdir()
    build(overlay, "p", ID)
    assert sorted(entry.name for entry in store.iterdir()) == [
        "MEMORY.md",
        "developer",
        "project-stable",
        "specs",
        "topic.md",
    ]
    assert (store / "topic.md").read_text(encoding="utf-8") == "the harness's note"


def a_tagged_overlay(tmp_path: Path, *tags: str, memory: bool = True) -> tuple[Path, Path]:
    """`an_overlay` whose record of `p` lists `tags`, each with a `tags/<tag>/` directory and,
    where `memory`, its `memory/` too."""
    overlay, share = an_overlay(tmp_path)
    return with_tags(overlay, "p", list(tags), *(("memory",) if memory else ())), share


def test_a_tags_memory_is_linked_under_its_tag_name(tmp_path: Path) -> None:
    overlay, _share = a_tagged_overlay(tmp_path, "a")
    store = build(overlay, "p", ID)
    assert (store / "tag-a").is_symlink()
    assert (store / "tag-a").resolve() == (overlay / "tags" / "a" / "memory").resolve()


def test_a_tag_without_memory_gets_no_link(tmp_path: Path) -> None:
    # A link at no directory would take a note the harness writes through it into nowhere; the
    # next attach picks the directory up once it exists.
    overlay, _share = a_tagged_overlay(tmp_path, "a", memory=False)
    store = build(overlay, "p", ID)
    assert "tag-a" not in sorted(entry.name for entry in store.iterdir())
    (overlay / "tags" / "a" / "memory").mkdir()
    build(overlay, "p", ID)
    assert (store / "tag-a").is_symlink()


def test_untagging_takes_the_link_and_keeps_a_note_the_harness_wrote(tmp_path: Path) -> None:
    overlay, _share = a_tagged_overlay(tmp_path, "a")
    store = build(overlay, "p", ID)
    (store / "topic.md").write_text("the harness's note", encoding="utf-8")
    (overlay / "projects" / "p" / "project.toml").write_text("tags = []\n", encoding="utf-8")
    build(overlay, "p", ID)
    assert not (store / "tag-a").is_symlink() and not (store / "tag-a").exists()
    assert (store / "topic.md").read_text(encoding="utf-8") == "the harness's note"
    assert (overlay / "tags" / "a" / "memory").is_dir()


def test_a_project_memory_directory_in_the_tag_namespace_is_not_linked(tmp_path: Path) -> None:
    # The project side gives up the `tag-` prefix: the directory would otherwise take the name
    # the tag's own link needs. Mutation (oracle): `mutations/`'s "the composed store links a
    # project directory in the tag namespace".
    overlay, share = a_tagged_overlay(tmp_path, "a")
    (share / "tag-a").mkdir()
    (share / "tag-b").mkdir()
    store = build(overlay, "p", ID)
    assert (store / "tag-a").resolve() == (overlay / "tags" / "a" / "memory").resolve()
    assert not (store / "tag-b").exists() and not (store / "tag-b").is_symlink()


def test_a_tag_and_a_project_group_of_one_name_both_link(tmp_path: Path) -> None:
    overlay, share = a_tagged_overlay(tmp_path, "specs")
    (share / "specs").mkdir()
    store = build(overlay, "p", ID)
    assert (store / "specs").resolve() == (share / "specs").resolve()
    assert (store / "tag-specs").resolve() == (overlay / "tags" / "specs" / "memory").resolve()


def test_withdraw_removes_the_links_and_the_store_and_never_a_note(tmp_path: Path) -> None:
    # The links go and the overlay they point into stays; a note the harness wrote keeps the
    # directory, since nothing drybag placed it there.
    overlay, share = an_overlay(tmp_path)
    store = build(overlay, "p", ID)
    assert withdraw(ID) is True
    assert not store.exists() and (share / "project-stable").is_dir()
    build(overlay, "p", ID)
    (store / "topic.md").write_text("kept", encoding="utf-8")
    assert withdraw(ID) is False
    assert [entry.name for entry in store.iterdir()] == ["topic.md"]
    # No store at all is no store left.
    assert withdraw("f" * 32) is True


def _never_the_whole_id(root: Path, tmp_path: Path, machine: Path, id: str, *argv: str) -> str:
    """What `drybag <argv>` printed, asserted to name the binding id by its short form alone."""
    from tests.cli import cli

    code, out, err = cli(root, tmp_path, *argv, machine=machine)
    assert id not in out + err, (argv, code, out, err)
    return out + err


def test_no_memory_command_prints_the_whole_binding_id_through_a_store_path(
    tmp_path: Path,
) -> None:
    # The composed store's path ends in the whole binding id, the secret a hostile clone would
    # need, and it was printed: after an ordinary `detach`, by every memory command and six times
    # per session; after a pull request set the mode to `overlay`; in `memory index`'s line about
    # `memory.index_extra`, which the sweep skill relays; and with the store deleted under the
    # pointer. Each prints the store under its short id now. Mutation (oracle): `mutations/`'s
    # "a store path is printed with the whole binding id".
    from drybag import binding
    from drybag.attach.write import attach, detach
    from drybag.binding import short
    from tests.attach.test_detach import _bound, _grant
    from tests.runners import Recorder

    root, own, machine = _bound(tmp_path)
    _grant(own.parents[1])
    toml = root / "drybag.toml"
    overlay_mode = toml.read_text(encoding="utf-8")
    attach(root, store=None, machine=machine, runner=Recorder())
    id = binding.read_id(root)
    assert id is not None
    # A pull request lists a pointer the overlay's shared index may not carry.
    toml.write_text(overlay_mode.replace("index_extra = []", 'index_extra = ["drybag.toml"]'))
    said = _never_the_whole_id(root, tmp_path, machine, id, "memory", "index")
    assert f"stores/{short(id)}…/MEMORY.md" in said
    toml.write_text(overlay_mode)
    # The store deleted under the pointer, then an ordinary detach.
    shutil.rmtree(store_directory(id))
    _never_the_whole_id(root, tmp_path, machine, id, "memory", "index")
    attach(root, store=None, machine=machine, runner=Recorder())
    detach(root, runner=Recorder())
    for argv in (("memory", "index"), ("memory", "inventory"), ("memory", "promote", "--changed")):
        said = _never_the_whole_id(root, tmp_path, machine, id, *argv)
        assert f"stores/{short(id)}…" in said
    session = ("memory", "session-context", "--bundle", "volatile-notes")
    _never_the_whole_id(root, tmp_path, machine, id, *session)


def test_a_bound_checkout_whose_composed_store_is_gone_hears_it_once(tmp_path: Path) -> None:
    # The pointer names a store that is gone, so the harness reads no memory and the session heard
    # nothing: the standing-rules entry says so on one line, naming the store by its short id and
    # `drybag attach` as the way back; every other entry stays quiet.
    from drybag import binding
    from drybag.attach.write import attach
    from drybag.binding import short
    from tests.attach.test_detach import _bound, _grant
    from tests.cli import cli
    from tests.runners import Recorder

    root, own, machine = _bound(tmp_path)
    _grant(own.parents[1])
    attach(root, store=None, machine=machine, runner=Recorder())
    id = binding.read_id(root)
    assert id is not None
    shutil.rmtree(store_directory(id))
    entry = ("memory", "session-context", "--bundle")
    code, out, err = cli(root, tmp_path, *entry, "standing-rules", machine=machine)
    assert (code, err) == (0, "")
    assert len(out.splitlines()) == 1 and "drybag attach" in out
    assert f"{short(id)}…" in out and id not in out
    for bundle, part in (("standing-rules", "2"), ("volatile-notes", "1")):
        assert cli(root, tmp_path, *entry, bundle, "--part", part, machine=machine) == (0, "\n", "")


def a_machine_overlay(tmp_path: Path) -> tuple[Path, Path]:
    """`a_tagged_overlay` for tag `t1` where `common`, `t1` and project `p` each hold a
    `machines/m1/memory/` and a `machines/m2/memory/` too."""
    overlay, share = a_tagged_overlay(tmp_path, "t1")
    for plate in (overlay / "common", overlay / "tags" / "t1", overlay / "projects" / "p"):
        for machine in ("m1", "m2"):
            (plate / "machines" / machine / "memory").mkdir(parents=True)
    return overlay, share


def test_sub_plate_memory_links_under_machine_prefix(tmp_path: Path) -> None:
    overlay, _share = a_machine_overlay(tmp_path)
    store = build(overlay, "p", ID, "m1")
    links = {entry.name: entry.resolve() for entry in store.iterdir() if entry.is_symlink()}
    sub = {name: path for name, path in links.items() if name.startswith("machine-")}
    assert sub == {
        "machine-m1-developer": (overlay / "common" / "machines" / "m1" / "memory").resolve(),
        "machine-m1-tag-t1": (overlay / "tags" / "t1" / "machines" / "m1" / "memory").resolve(),
        "machine-m1-project": (overlay / "projects" / "p" / "machines" / "m1" / "memory").resolve(),
    }
    # A machine with no name has no sub-plate link.
    bare = build(overlay, "p", ID, None)
    assert not any(entry.name.startswith("machine-") for entry in bare.iterdir())


def test_a_project_group_shaped_like_a_machine_link_is_reserved(tmp_path: Path) -> None:
    # The project side gives up the three link shapes, on any machine, as it gives up `tag-`, so
    # a share directory cannot take the name a sub-plate's link needs; any other `machine-...` is
    # the project's own. Mutation (oracle): `mutations/`'s "the machine namespace is not
    # reserved", "the reserved project groups leave out the machine namespace" and "the whole
    # machine- prefix is a link name".
    from drybag.memory.store import reserved, reserved_project_groups

    overlay, share = a_machine_overlay(tmp_path)
    for name in ("machine-x", "machine-m1-developer", "machine-m2-tag-t9"):
        (share / name).mkdir()
    store = build(overlay, "p", ID, "m1")
    assert (store / "machine-x").resolve() == (share / "machine-x").resolve()
    assert not (store / "machine-m2-tag-t9").is_symlink()
    assert (store / "machine-m1-developer").resolve() == (
        overlay / "common" / "machines" / "m1" / "memory"
    ).resolve()
    assert not reserved("machine-x") and reserved("machine-m2-project")
    assert reserved_project_groups(overlay, "p") == ("machine-m1-developer", "machine-m2-tag-t9")


def test_a_note_written_to_a_machine_link_lands_in_the_sub_plate(tmp_path: Path) -> None:
    overlay, _share = a_machine_overlay(tmp_path)
    store = build(overlay, "p", ID, "m1")
    (store / "machine-m1-tag-t1" / "n.md").write_text("note", encoding="utf-8")
    assert (overlay / "tags" / "t1" / "machines" / "m1" / "memory" / "n.md").read_text(
        encoding="utf-8"
    ) == "note"
    assert not (overlay / "tags" / "t1" / "memory" / "n.md").exists()
