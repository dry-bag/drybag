"""The plugin's tree held to the file rules the Claude plugin directory checks at submission.

The payload is the tree `scripts/plugin_tree.py` generates from `HEAD`: the files under the
plugin's paths and nothing else, because the plugin is published from a repository of its own whose
root is that tree (the marketplace entry is a `url` source naming it), and that tree is what the
directory scans. `test_the_payload_is_the_generated_plugin_tree` reddens if the walk reads anything
else. The commit and not the working tree, because the directory reads a commit: a local edit, a
line-ending conversion or a file deleted on disk is not what it scans.

Every rule holds the tree on every pull request, the file count included: the tree is the plugin
alone, so a pull request that carries it past `FILES_MAX` carries the plugin past it, and
`scripts/release.py check --tag` holds the same count again on the commit a release is cut from.

`docs/cli.md` and every other file outside the plugin's paths are not judged: the directory's
limits judge the files that ship, and these do not.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

import pytest

from tests.gitfixture import git, needs_git
from tests.plugintree import NINE, PLUGIN_FILES, plugin_source
from tests.scriptload import plugin_tree, release

ROOT = Path(__file__).resolve().parents[1]

# The directory's rules, as its pre-submission checklist states them
# (https://claude.com/docs/plugins/pre-submission-checklist, fetched 2026-10-02; the page carries
# no date), each with the result the page gives it: Held (the listing waits for a reviewer),
# Blocks, Validation stops, or, for a link, a submodule and a Git LFS pointer, "Blocks where the
# plugin loads the entry. Warning elsewhere." The tree the rules apply to is the plugin's, which
# `scripts/plugin_tree.py` generates, so every rule below reads every path of it.
#
# Held: a file that is not an image or a font at `FILE_MAX_BYTES` or more, and more than
# `FILES_MAX` files. The count is the release script's `PLUGIN_FILES_MAX`, read rather than
# restated: its `check --tag` refuses a release over it, and this rule and that refusal must not
# name two numbers.
FILE_MAX_BYTES = 256 * 1024
FILES_MAX: int = release().PLUGIN_FILES_MAX
# Held: a binary file other than the images and fonts the page names. It admits "text files, SVG
# included, complete PNG, JPEG, GIF, and WebP images, and font files" and names an `.ico`, a `.pdf`
# and a `.zip` file and a compiled executable as held. The same suffixes are the ones the size rule
# exempts, and a file is exempt only when it is what its suffix says: an image or a font opens with
# its format's signature, below, and an SVG is text.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
FONT_SUFFIXES = (".woff", ".woff2", ".ttf", ".otf")
EXEMPT_SUFFIXES = IMAGE_SUFFIXES + FONT_SUFFIXES
_JPEG = re.compile(rb"\xff\xd8\xff")
# `.ttf` and `.otf` are one container, sfnt, whatever outlines it carries: TrueType
# (`\x00\x01\x00\x00`, or Apple's `true`), CFF (`OTTO`) or PostScript Type 1 (`typ1`). The suffix
# does not decide which, so either suffix takes any of the four.
_SFNT = re.compile(rb"\x00\x01\x00\x00|OTTO|true|typ1")
SIGNATURES: dict[str, re.Pattern[bytes]] = {
    ".png": re.compile(rb"\x89PNG\r\n\x1a\n"),
    ".jpg": _JPEG,
    ".jpeg": _JPEG,
    ".gif": re.compile(rb"GIF8[79]a"),
    ".webp": re.compile(rb"RIFF.{4}WEBP", re.DOTALL),
    ".ttf": _SFNT,
    ".otf": _SFNT,
    ".woff": re.compile(rb"wOFF"),
    ".woff2": re.compile(rb"wOF2"),
}
# The three binaries the page names are held by their suffix, whatever their bytes: a `.pdf` can be
# all text and is still the file the page holds.
HELD_SUFFIXES = (".ico", ".pdf", ".zip")
# Binary is git's own test: a NUL byte in the first 8000 bytes (`buffer_is_binary`).
BINARY_PROBE_BYTES = 8000
# Blocks where loaded, Warning elsewhere: a symbolic link, a Git submodule (a gitlink entry) and a
# Git LFS pointer file. Any path here is one the plugin may load, so each is a finding wherever it
# is. The first two never reach this walk: `scripts/plugin_tree.py`'s `members` refuses a member
# that is not a regular file, and its tests hold that refusal. The third is text in a regular file.
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
# Blocks, "This is a macOS or Windows system file", at any depth and in any capitalization: both
# systems' default file systems fold case, so `thumbs.db` is the file Explorer writes. Held folded.
SYSTEM_FILES = frozenset(
    name.casefold() for name in (".DS_Store", "Thumbs.db", "desktop.ini", "__MACOSX")
)
# Validation stops: a name Windows or macOS cannot hold. The page's examples are a colon, a trailing
# dot or space, a Windows device name such as `con.md` or `prn`, and two names that differ only by
# capitalization. The characters below are the whole set Windows refuses in a name, the colon among
# them. The device names are the whole reserved list of "Naming Files, Paths, and Namespaces"
# (https://learn.microsoft.com/windows/win32/fileio/naming-a-file, fetched 2026-10-03, dated
# 2024-08-28): CON, PRN, AUX, NUL, COM1-9 and LPT1-9 and the superscript ¹, ² and ³ after COM and
# LPT, each reserved with any extension after it; and the console's `CONIN$` and `CONOUT$`, which
# `CreateFile` opens by name as devices.
INVALID_CHARACTERS = frozenset('<>:"\\|?*') | frozenset(map(chr, range(32)))
DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{port}{digit}" for port in ("COM", "LPT") for digit in "123456789\u00b9\u00b2\u00b3"}
)
# Validation stops: in any `.gitattributes`, the two export attributes, and the attributes that
# rewrite a file's content on its way out of git. The page names `filter`, Git LFS's included, and
# "other content-rewriting attributes" without listing them, so this reads every attribute git
# defines to rewrite content: `ident` and `working-tree-encoding`, and `text`, `eol` and the older
# `crlf`, which convert line endings. Failing closed costs this tree nothing, which has no
# `.gitattributes`, and `* text=auto` is a line the directory may well refuse.
EXPORT_ATTRIBUTES = ("export-ignore", "export-subst")
REWRITING_ATTRIBUTES = ("filter", "ident", "working-tree-encoding", "text", "eol", "crlf")
REFUSED_ATTRIBUTES = EXPORT_ATTRIBUTES + REWRITING_ATTRIBUTES
# What proves the walk read this repository: the manifest that makes the folder a plugin at all.
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"

# `(path, size in bytes)`, the path relative to the root with `/` between components. No mode: the
# directory's rules read none, and `scripts/plugin_tree.py` refuses every member that is not a
# regular file before an entry is made of it.
Entry = tuple[str, int]


def payload_findings(entries: Iterable[Entry], *, read: Callable[[str], bytes]) -> list[str]:
    """Every way `entries` falls outside the directory's rules, one finding per path and check.

    `read` returns a regular file's bytes: the signature, binary and Git LFS checks read its start,
    and the `.gitattributes` check its lines. An attribute is matched on any line that carries it, a
    comment included: the directory's check is stated over the file's lines, and this reads them
    no more kindly.
    """
    listed = list(entries)
    findings = []
    if len(listed) > FILES_MAX:
        findings.append(f"{len(listed)} files, over the {FILES_MAX} the directory lists unheld")
    findings.extend(_name_findings([path for path, _ in listed]))
    for path, size in listed:
        components = path.split("/")
        if SYSTEM_FILES.intersection(_folded(component) for component in components):
            findings.append(f"{path}: a macOS or Windows system file")
        content = read(path)
        suffix = PurePosixPath(path).suffix.lower()
        binary = b"\0" in content[:BINARY_PROBE_BYTES]
        signature = SIGNATURES.get(suffix)
        signed = signature.match(content) is not None if signature else not binary
        exempt = suffix in EXEMPT_SUFFIXES and signed
        if size >= FILE_MAX_BYTES and not exempt:
            findings.append(f"{path}: {size} bytes, at or over {FILE_MAX_BYTES}")
        if content.startswith(LFS_POINTER):
            findings.append(f"{path}: a Git LFS pointer")
        elif suffix in HELD_SUFFIXES:
            findings.append(f"{path}: a {suffix} file, which the directory holds by its kind")
        elif signature is not None and not signed:
            findings.append(f"{path}: named {suffix} and not one")
        elif binary and not exempt:
            findings.append(f"{path}: a binary file that is not an image or a font")
        if components[-1] == ".gitattributes":
            findings.extend(
                f"{path}:{number}: {attribute}"
                for number, line in enumerate(content.decode("utf-8", "replace").splitlines(), 1)
                for attribute in _attributes(line)
                if attribute in REFUSED_ATTRIBUTES
            )
    return findings


def _attributes(line: str) -> list[str]:
    """The attribute names a `.gitattributes` line sets, unsets or values: every word after the
    first, which is the pattern, with a leading `-` or `!` and any `=value` taken off."""
    return [word.lstrip("-!").split("=", 1)[0] for word in line.split()[1:]]


def _name_findings(paths: list[str]) -> list[str]:
    """Each path holding a component Windows or macOS cannot name, and each set of spellings,
    of files and directories alike, that differ only by capitalization."""
    findings = []
    spellings: dict[str, set[str]] = {}
    for path in paths:
        components = path.split("/")
        for depth, component in enumerate(components, 1):
            spelt = "/".join(components[:depth])
            spellings.setdefault(_folded(spelt), set()).add(spelt)
            if not _nameable(component):
                findings.append(f"{path}: {component!r} is not a name Windows or macOS holds")
    findings.extend(
        f"{' and '.join(sorted(spelt))}: names that differ only by capitalization"
        for spelt in spellings.values()
        if len(spelt) > 1
    )
    return findings


def _folded(name: str) -> str:
    """The key two spellings of one file share on a case-insensitive file system."""
    return name.casefold()


def _nameable(component: str) -> bool:
    if INVALID_CHARACTERS.intersection(component):
        return False
    if component.endswith((".", " ")):
        return False
    return component.split(".", 1)[0].upper() not in DEVICE_NAMES


def tracked_payload(root: Path = ROOT) -> tuple[list[Entry], dict[str, bytes]]:
    """Every file of the plugin tree at `root`'s `HEAD` and its bytes: what the directory reads.

    Read through `scripts/plugin_tree.py`'s `read`, the one reader of the plugin's paths, which
    refuses a symlink or a submodule among them outright.
    """
    members = plugin_tree().read(root, "HEAD").members
    entries = [(member.path, len(member.content)) for member in members]
    return entries, {member.path: member.content for member in members}


def _text(_: str) -> bytes:
    """A reader for cases about entries alone: every file a line of text."""
    return b"text\n"


def test_a_file_at_the_limit_is_a_finding() -> None:
    # Mutation (declared): the size comparison `>=` becomes `>` (a file of exactly 256 KiB passes).
    assert payload_findings([("big.toml", FILE_MAX_BYTES)], read=_text) != []
    assert payload_findings([("ok.toml", FILE_MAX_BYTES - 1)], read=_text) == []


# One opening each format's signature accepts, padded past it so that each is binary as git reads
# it: the exemption is what lets these through, not a lucky absence of NUL bytes.
SIGNED = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff\xe0",
    ".jpeg": b"\xff\xd8\xff\xdb",
    ".gif": b"GIF89a",
    ".webp": b"RIFF\x0a\x00\x00\x00WEBPVP8 ",
    ".ttf": b"\x00\x01\x00\x00",
    ".otf": b"OTTO",
    ".woff": b"wOFF",
    ".woff2": b"wOF2",
}


def test_every_exempt_binary_suffix_has_a_signature() -> None:
    # The SVG is text and has none; every other exempt suffix must, or it is exempt unread.
    # Mutation: a suffix added to `IMAGE_SUFFIXES` without a signature -> this reddens.
    assert set(SIGNATURES) == set(EXEMPT_SUFFIXES) - {".svg"} == set(SIGNED)


@pytest.mark.parametrize("suffix", sorted(SIGNED))
def test_an_image_or_a_font_that_is_one_is_exempt(suffix: str) -> None:
    # Exempt from the size limit and from the binary rule both. Mutation: `.png` dropped from
    # `IMAGE_SUFFIXES` -> its case reddens. Mutation: one signature narrowed (`GIF89a` only, or the
    # WebP pattern without `re.DOTALL`) -> the case it no longer reads reddens.
    content = SIGNED[suffix] + b"\0" * 16
    found = payload_findings([(f"art{suffix}", FILE_MAX_BYTES * 4)], read=lambda _: content)
    assert found == []


@pytest.mark.parametrize("suffix", [".ttf", ".otf"])
@pytest.mark.parametrize(
    "opening",
    [
        pytest.param(b"\x00\x01\x00\x00", id="truetype"),
        pytest.param(b"OTTO", id="cff"),
        pytest.param(b"true", id="apple"),
        pytest.param(b"typ1", id="type1"),
    ],
)
def test_a_font_is_read_as_sfnt_whatever_its_suffix_says_of_its_outlines(
    suffix: str, opening: bytes
) -> None:
    # A TrueType-outline `.otf` and a CFF `.ttf` are both valid fonts, and each was once a finding.
    # Mutation (declared): `.otf` given `OTTO` alone -> its other three cases redden. Mutation:
    # `.ttf` given the TrueType openings alone -> its `cff` and `type1` cases redden.
    content = opening + b"\0" * 16
    found = payload_findings([(f"font{suffix}", FILE_MAX_BYTES * 2)], read=lambda _: content)
    assert found == []


@pytest.mark.parametrize(
    ("path", "content"),
    [
        pytest.param("LOGO.PNG", SIGNED[".png"] + b"\0", id="upper-case"),
        pytest.param("diagram.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>\n", id="svg"),
    ],
)
def test_an_exempt_file_is_judged_by_its_suffix_in_any_case_and_an_svg_by_being_text(
    path: str, content: bytes
) -> None:
    # Mutation: `.lower()` dropped from the suffix -> `LOGO.PNG` is a finding and its case reddens.
    found = payload_findings([(path, FILE_MAX_BYTES * 4)], read=lambda _: content)
    assert found == []


@pytest.mark.parametrize(
    ("path", "content"),
    [
        pytest.param("icon.png", b"\x7fELF\x02\x01\x01\0", id="executable-as-png"),
        pytest.param("photo.jpg", b"GIF89a\0", id="gif-as-jpeg"),
        pytest.param("photo.webp", b"RIFF\x24\x00\x00\x00AVI \0", id="riff-not-webp"),
        pytest.param("fonts/body.woff2", b"wOFF\0", id="woff-as-woff2"),
        pytest.param("fonts/body.ttf", b"wOFF\0", id="woff-as-ttf"),
    ],
)
def test_a_file_that_is_not_the_image_or_font_its_suffix_names_is_a_finding(
    path: str, content: bytes
) -> None:
    # The page admits "complete PNG, JPEG, GIF, and WebP images", not a name: a 2 MiB executable
    # called `icon.png` passed both the size and the binary rule on its suffix alone. Mutation
    # (declared): the signature test dropped -> the size finding is left alone and every case
    # reddens. Mutation: `exempt` read from the suffix alone -> the size finding goes and every
    # case reddens.
    size = 2 * 1024 * 1024
    suffix = PurePosixPath(path).suffix
    assert payload_findings([(path, size)], read=lambda _: content) == [
        f"{path}: {size} bytes, at or over {FILE_MAX_BYTES}",
        f"{path}: named {suffix} and not one",
    ]


@pytest.mark.parametrize(
    ("path", "content"),
    [
        pytest.param("favicon.ico", b"\0\0\1\0\1\0\x10\x10", id="ico"),
        pytest.param("manual.pdf", b"%PDF-1.4\n1 0 obj << >> endobj\n%%EOF\n", id="text-only-pdf"),
        pytest.param("bundle.zip", b"PK\x05\x06" + b"\0" * 18, id="zip"),
        pytest.param("docs/Guide.PDF", b"%PDF-1.7\n", id="upper-case"),
    ],
)
def test_a_binary_kind_the_page_names_is_a_finding_whatever_its_bytes(
    path: str, content: bytes
) -> None:
    # The page names an `.ico`, a `.pdf` and a `.zip` file as held, and a text-only PDF has no NUL
    # for the binary rule to find. Mutation (declared): `HELD_SUFFIXES` emptied -> the text-only
    # PDF passes and the upper-case one with it, and those cases redden.
    suffix = PurePosixPath(path).suffix.lower()
    assert payload_findings([(path, len(content))], read=lambda _: content) == [
        f"{path}: a {suffix} file, which the directory holds by its kind"
    ]


def test_one_file_past_the_count_is_a_finding() -> None:
    # Mutation (declared): `>` becomes `>=` -> exactly `FILES_MAX` files is a finding, and the
    # second assertion reddens; `> FILES_MAX + 1` instead lets the first pass on nothing.
    entries = [(f"f{i}", 1) for i in range(FILES_MAX + 1)]
    assert any("files" in f for f in payload_findings(entries, read=_text))
    assert payload_findings(entries[:FILES_MAX], read=_text) == []


@pytest.mark.parametrize(
    "path",
    [
        ".DS_Store",
        "docs/.DS_Store",
        "__MACOSX/a.txt",
        "a/__MACOSX/b",
        "Thumbs.db",
        "docs/img/Thumbs.db",
        "desktop.ini",
        "skills/desktop.ini",
    ],
)
def test_a_system_file_is_a_finding_at_any_depth(path: str) -> None:
    # Mutation (declared): `components` becomes `components[:1]` -> only a top-level system file is
    # a finding, and the nested cases redden. Mutation: `Thumbs.db` or `desktop.ini` dropped from
    # `SYSTEM_FILES` -> its two cases redden.
    assert payload_findings([(path, 10)], read=_text) == [f"{path}: a macOS or Windows system file"]


@pytest.mark.parametrize("path", ["thumbs.db", "docs/Desktop.ini", ".ds_store", "__macosx/a.txt"])
def test_a_system_file_is_a_finding_in_any_capitalization(path: str) -> None:
    # Windows and macOS fold case by default, so `thumbs.db` is the very file Explorer writes.
    # Mutation (declared): the components compared unfolded -> every case reddens.
    assert payload_findings([(path, 10)], read=_text) == [f"{path}: a macOS or Windows system file"]


def test_a_name_that_only_contains_a_system_files_name_is_not_a_finding() -> None:
    # The match is on whole components: a substring match would refuse a file merely named after
    # one. Mutation: `SYSTEM_FILES.intersection(components)` becomes
    # `any(name in path for name in SYSTEM_FILES)` -> this reddens.
    assert payload_findings([("docs/about.DS_Store.md", 10)], read=_text) == []


@pytest.mark.parametrize(
    "path",
    [
        "docs/a:b.md",
        "notes.",
        "a /b.md",
        "docs/what?.md",
        "tab\there.md",
        "con.md",
        "PRN",
        "docs/aux.txt",
        "nul.tar.gz",
        "COM1",
        "lpt9.log",
        "CONIN$",
        "docs/conout$.txt",
        "COM\u00b9",
        "lpt\u00b3.log",
    ],
)
def test_a_name_windows_or_macos_cannot_hold_is_a_finding(path: str) -> None:
    # Mutations (declared): the device-name test answers yes -> the ten device cases redden; the
    # console names dropped from `DEVICE_NAMES` -> `CONIN$` and `conout$.txt` redden; the
    # superscript ports dropped -> `COM¹` and `lpt³.log` redden; the trailing dot or space test
    # dropped -> `notes.` and `a /b.md` redden. Mutation: the colon dropped from
    # `INVALID_CHARACTERS` -> `docs/a:b.md` reddens.
    found = payload_findings([(path, 10)], read=_text)
    assert len(found) == 1 and "is not a name Windows or macOS holds" in found[0], found


@pytest.mark.parametrize(
    "path", ["console.md", "COM10", "auxiliary/x.md", "nullable.py", "a.b", "CONIN", "COM\u2074"]
)
def test_a_name_that_only_resembles_a_device_name_is_not_a_finding(path: str) -> None:
    # A device name is the whole name before its first dot. Mutation: the comparison becomes a
    # `startswith` over `DEVICE_NAMES` -> the first four redden.
    assert payload_findings([(path, 10)], read=_text) == []


@pytest.mark.parametrize(
    ("paths", "spelt"),
    [
        pytest.param(["README.md", "readme.md"], "README.md and readme.md", id="files"),
        pytest.param(["Docs/a.md", "docs/b.md"], "Docs and docs", id="directories"),
    ],
)
def test_names_that_differ_only_by_capitalization_are_a_finding(
    paths: list[str], spelt: str
) -> None:
    # On the default macOS and Windows file systems the two are one file, or one directory: the
    # second case is two files whose directories collide. Mutation (declared): `_folded` answers
    # its name unchanged -> no two spellings meet and both cases redden.
    found = payload_findings([(path, 10) for path in paths], read=_text)
    assert found == [f"{spelt}: names that differ only by capitalization"]


@pytest.mark.parametrize(
    ("path", "content"),
    [
        pytest.param("data.sqlite", b"SQLite format 3\0", id="database"),
        pytest.param("scripts/tool", b"\x7fELF\x02\x01\x01\0", id="executable"),
        pytest.param("module.wasm", b"\0asm\x01\0\0\0", id="wasm"),
    ],
)
def test_a_binary_that_is_not_an_image_or_a_font_is_a_finding(path: str, content: bytes) -> None:
    # Mutation (declared): the NUL test dropped -> every case reddens.
    assert payload_findings([(path, len(content))], read=lambda _: content) == [
        f"{path}: a binary file that is not an image or a font"
    ]


def test_binary_is_judged_where_git_judges_it() -> None:
    # An image is a binary the page admits; a NUL past git's 8000-byte window is text to git.
    # Mutation: the window `[:BINARY_PROBE_BYTES]` dropped -> the late NUL is a finding and this
    # reddens. Mutation: `and not exempt` dropped from the binary test -> the PNG reddens it.
    png = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR"
    late = b"x" * BINARY_PROBE_BYTES + b"\0"
    assert payload_findings([("logo.png", len(png))], read=lambda _: png) == []
    assert payload_findings([("notes.txt", len(late))], read=lambda _: late) == []


def test_a_git_lfs_pointer_is_a_finding() -> None:
    # A pointer is text, so the binary test passes it, and what the directory would load in the
    # file's place is three lines of metadata. Mutation (declared): the pointer test dropped ->
    # this reddens.
    pointer = (
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393\n"
        b"size 12345\n"
    )
    found = payload_findings([("assets/demo.mp4", len(pointer))], read=lambda _: pointer)
    assert found == ["assets/demo.mp4: a Git LFS pointer"]


# Spelled out rather than parametrised over `EXPORT_ATTRIBUTES`, which would drop a case with the
# attribute it lost.
@pytest.mark.parametrize("attribute", ["export-ignore", "export-subst"])
def test_a_gitattributes_line_carrying_an_export_attribute_is_a_finding(attribute: str) -> None:
    # Mutation (declared): the `.gitattributes` test compares against `.gitattribute` -> no file
    # is read, and both cases redden. Mutation: either attribute dropped from
    # `EXPORT_ATTRIBUTES` -> its case reddens.
    text = f"*.md diff=markdown\ndocs/** {attribute}\n".encode()
    found = payload_findings([("sub/.gitattributes", len(text))], read=lambda _: text)
    assert found == [f"sub/.gitattributes:2: {attribute}"]


@pytest.mark.parametrize(
    ("line", "attributes"),
    [
        pytest.param("*.bin filter=lfs diff=lfs merge=lfs -text", ["filter", "text"], id="lfs"),
        pytest.param("*.c -filter", ["filter"], id="filter-unset"),
        pytest.param("*.c ident", ["ident"], id="ident"),
        pytest.param(
            "*.ps1 working-tree-encoding=UTF-16", ["working-tree-encoding"], id="encoding"
        ),
        pytest.param("*.sh text eol=crlf", ["text", "eol"], id="line-endings"),
        pytest.param("* text=auto", ["text"], id="text-auto"),
        pytest.param("*.bat crlf", ["crlf"], id="crlf"),
    ],
)
def test_a_gitattributes_line_rewriting_content_is_a_finding(
    line: str, attributes: list[str]
) -> None:
    # Mutations (declared): `filter` dropped from `REWRITING_ATTRIBUTES` -> the two `filter` cases
    # redden; `text` dropped -> the three cases carrying it redden. Mutation: `ident`,
    # `working-tree-encoding`, `eol` or `crlf` dropped -> its case reddens. The `-filter` case holds
    # the `lstrip("-!")` in `_attributes`: without it an unset reads as another name.
    text = f"{line}\n".encode()
    found = payload_findings([(".gitattributes", len(text))], read=lambda _: text)
    assert found == [f".gitattributes:1: {attribute}" for attribute in attributes]


@pytest.mark.parametrize("line", ["*.md diff=markdown", "filter diff", "*.txt diff=filtered"])
def test_a_gitattributes_line_carrying_no_refused_attribute_is_not_a_finding(line: str) -> None:
    # The file itself is allowed; only the attributes the page names are not. The second case is a
    # pattern, the files named `filter`, and the third a value that only contains an attribute.
    # Mutation: `_attributes` reads every word, the pattern included -> the second case reddens.
    # Mutation: a finding for every `.gitattributes` whatever its lines -> every case reddens.
    text = f"{line}\n".encode()
    assert payload_findings([(".gitattributes", len(text))], read=lambda _: text) == []


@needs_git
def test_the_payload_is_the_generated_plugin_tree() -> None:
    # The marketplace fetches the plugin from its own repository, whose root is the generated
    # tree, so the walk reads that tree and nothing beside it. Mutation (declared): the walk reads
    # `git ls-tree -r HEAD` of the whole repository -> `docs/` and `tests/` are walked and this
    # reddens.
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text("utf-8"))
    (entry,) = market["plugins"]
    assert entry["source"]["source"] == "url"
    assert entry["source"]["url"] == release().PLUGIN_URL
    entries, _ = tracked_payload()
    assert PLUGIN_MANIFEST in {path for path, _ in entries}, len(entries)
    outside = [
        path
        for path, _ in entries
        if not any(path == entry or path.startswith(entry + "/") for entry in NINE)
    ]
    assert outside == []


@needs_git
def test_the_walk_reads_the_committed_tree_and_not_the_disk(tmp_path: Path) -> None:
    # The directory scans a commit, so a size measured on disk is a different payload from the
    # one it reads. What this adds over `tests/scripts/test_plugin_tree.py`'s
    # `test_members_read_the_commit_and_not_the_disk`, which holds the bytes, the deleted file
    # and the staged one, is the size this walk observes alone. Mutation: the size read from
    # `(root / path).lstat()` instead of the commit's bytes -> the edited file's row reddens. A
    # symlink and a submodule are `members`' refusals (`tests/scripts/test_plugin_tree.py`), so
    # they are not planted here.
    root = plugin_source(tmp_path)
    (root / "README.md").write_text("an edit nobody committed\n", encoding="utf-8")
    (root / "LICENSE").unlink()
    (root / "skills" / "staged.md").write_text("staged\n", encoding="utf-8")
    git(root, "add", "skills/staged.md")

    entries, blobs = tracked_payload(root)

    assert sorted(entries) == sorted(
        (path, len(content)) for path, (content, _) in PLUGIN_FILES.items()
    )
    assert blobs == {path: content for path, (content, _) in PLUGIN_FILES.items()}


@needs_git
def test_the_tree_is_inside_the_directory_limits() -> None:
    # Every rule, the file count included. No mutation of the code: the subject is the tree. The
    # count's half cannot fail today, with the plugin tree some two hundred files under
    # `FILES_MAX`; `test_one_file_past_the_count_is_a_finding` carries that rule. Watched red on a
    # committed file of `FILE_MAX_BYTES` under `skills/`.
    entries, blobs = tracked_payload()
    # A walk-based assertion states its walk is non-empty, and this one that it walked this plugin.
    assert PLUGIN_MANIFEST in {path for path, _ in entries}, len(entries)
    assert payload_findings(entries, read=blobs.__getitem__) == []
