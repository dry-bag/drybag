"""One writer for every file drybag replaces in place, and one way to reach it safely.

*Atomicity and durability.* A note, an index and a scaffolded artifact are each a file a person
may be editing, and a bare `write_text` truncates before it writes. `mkstemp` plus `os.replace`
makes the replacement atomic, and the replaced file's mode is carried over, since a fresh
temporary is 0600. The bytes are `fsync`ed before the rename and the directory after it, because
`os.replace` promises nothing about what survives power loss.

*Containment that survives the write.* `open_within` walks the path one component at a time with
`O_NOFOLLOW`, so a symlink anywhere along it fails the open rather than redirecting it, and
returns a directory descriptor the write happens relative to; the string is never resolved again.
It refuses `..`, an absolute path and git's control directory too (`checked_components`): every
area that puts a file into a repository calls it, and its name is the guarantee they read.
`contained()` in `config.paths` is the first call for a *configured* string, with a `Refusal` a
user can act on; this is the floor under it, not a replacement for it.

A leaf module: it imports nothing from `drybag`, so the hook path pays no area import to reach
it, and it raises `OSError` and `UnsafePath` rather than `drybag.errors.Refusal` — the area that
owns a user-facing verdict translates them.
"""

from __future__ import annotations

import contextlib
import errno
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

# The mode a file drybag creates asks for; the kernel subtracts the umask, as `open()` does for any
# program, so a `umask 077` the owner chose holds. A file that exists keeps its own (`_mode_of`).
NEW_FILE_MODE = 0o644
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_PARENT = ".."
_HERE = "."
# Git's control directory, reserved at every depth and in any case.
#
# The anchor is the root a person handed the CLI (`project.detect`, or the command line), and
# `.git` is git's own name inside it: the clone authors the path string and nothing else here, so
# it cannot move `.git` or choose the root. In any case, because macOS folds case and
# `.GIT/hooks/pre-commit` is the same file; at every depth, because a submodule's is as off-limits.
# The whole component and not "a leading dot": `.drybag/` is drybag's own and `.gitignore` is an
# ordinary file. `guards.githooks.install` writes inside `.git` without coming through here: git
# names the directory, and the write is `write_atomically` on a path this process computed.
CONTROL_DIRECTORY = ".git"


class UnsafePath(OSError):
    """A component of the path is a symlink, is not a directory, or leaves the root."""


def said(error: OSError) -> str:
    """What an `OSError` says about a file without naming it: its `strerror`, or its class's name,
    since `str(error)` carries the absolute path it was opened by. `UnsafePath` alone, drybag's own
    refusal naming the path relative to the root, is said whole, decided by its type."""
    if isinstance(error, UnsafePath):
        return str(error)
    return error.strerror or type(error).__name__


def unreadable(label: object, error: OSError | UnicodeDecodeError) -> str:
    """What a reader says of a file it could not read, named as `label` and never by the path it
    was opened by: that it cannot be read, and why in `said`'s words, or that it is not UTF-8."""
    if isinstance(error, UnicodeDecodeError):
        return f"{label} is not UTF-8 text"
    return f"{label} cannot be read ({said(error)})"


@contextmanager
def reading(label: object, refusal: Callable[[str], Exception]) -> Iterator[None]:
    """Raise `refusal` with `unreadable`'s sentence for a read inside it that fails, an `OSError`
    chained to it and a decoding error not: the frame around every read that refuses in its own
    words. An arm that answers a missing file goes inside it and re-raises what it does not."""
    try:
        yield
    except OSError as exc:
        raise refusal(unreadable(label, exc)) from exc
    except UnicodeDecodeError as exc:
        raise refusal(unreadable(label, exc)) from None


def names_component(relative: str, name: str) -> bool:
    """Whether any component of `relative` is `name` (lower-case), spelled in any case: the one
    test behind `names_control_directory` and `config.paths.names_drybag_directory`. Any case,
    because the default filesystems on macOS and Windows fold it."""
    return any(part.lower() == name for part in relative.split("/"))


def names_control_directory(relative: str) -> bool:
    """Whether any component of `relative` is git's control directory, spelled in any case.
    Public, so `checked_components` and `config.paths.validate_paths` (which names the key, never
    the value) ask one question; `CONTROL_DIRECTORY` holds the rule and its anchor."""
    return names_component(relative, CONTROL_DIRECTORY)


def utf_8_name(name: str) -> bool:
    """Whether a name the filesystem gave is UTF-8 on disk, so a UTF-8 file can hold it. Asked of
    the bytes: a name in other bytes reaches Python with surrogate escapes, or with none under a
    latin-1 filesystem codec, and writing it into a UTF-8 file raises `UnicodeEncodeError`."""
    try:
        os.fsencode(name).decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# The faults of a `stat` that say its path reaches no file: nothing there, a component that is not
# a directory, a symbolic link loop, and a name or path longer than the system takes, which a clone
# reaches with a committed link to a long target. None names anything a reader can open.
REACHES_NO_FILE = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.ENAMETOOLONG})


def _reached_mode(path: Path, *, follow: bool) -> int | None:
    """The mode `stat` (or `lstat`, when not `follow`) finds at `path`, or `None` when the path
    reaches no file: one of `REACHES_NO_FILE`, or a NUL, which names no file anywhere. Any other
    fault is raised: a path that cannot be asked about is the caller's to classify."""
    try:
        return (os.stat(path) if follow else os.lstat(path)).st_mode
    except OSError as exc:
        if exc.errno in REACHES_NO_FILE:
            return None
        raise
    except ValueError:
        return None


# `Path.is_file()`, `is_dir()`, `exists()` and `is_symlink()`, answered alike on every interpreter
# (`pathlib` raises some faults up to 3.13 and answers `False` for all of them from 3.14):
# `REACHES_NO_FILE` is nothing there, and any other fault raises, because "cannot tell" is not
# "no". Each follows links as its `pathlib` namesake does.


def is_file(path: Path) -> bool:
    """Whether `path`, followed through links, reaches a regular file; see above."""
    mode = _reached_mode(path, follow=True)
    return mode is not None and stat.S_ISREG(mode)


def is_dir(path: Path) -> bool:
    """Whether `path`, followed through links, reaches a directory; see above."""
    mode = _reached_mode(path, follow=True)
    return mode is not None and stat.S_ISDIR(mode)


def exists(path: Path) -> bool:
    """Whether `path`, followed through links, reaches anything; see above."""
    return _reached_mode(path, follow=True) is not None


def is_symlink(path: Path) -> bool:
    """Whether `path` itself, not followed, is a symbolic link; see above."""
    mode = _reached_mode(path, follow=False)
    return mode is not None and stat.S_ISLNK(mode)


def stored_name(path: Path, listings: dict[Path, dict[str, int]]) -> tuple[str, int] | None:
    """The name `path`'s directory lists for what `lstat(path)` reaches (`path.name`, or a case or
    normalisation variant this volume answers for: the listed entry with that inode), and its
    mode; `None` when nothing is there. `listings` keeps each directory's listing for reuse."""
    found = _reached_mode(path, follow=False)
    if found is None:
        return None
    if path.parent not in listings:
        with os.scandir(path.parent) as listed:
            listings[path.parent] = {entry.name: entry.inode() for entry in listed}
    names = listings[path.parent]
    if path.name in names:
        return path.name, found
    inode = os.lstat(path).st_ino
    return next((name for name, each in names.items() if each == inode), path.name), found


def vacant(path: Path) -> bool:
    """Whether nothing is at `path`, or an empty directory that is no link: what a clone or a
    render may go into. A link, dangling or not, leads either wherever it points, so it is never
    vacant. Whether this user may write there is the caller's to ask; a directory that cannot be
    listed raises, as every predicate here does for a fault that leaves the question open."""
    if is_symlink(path):
        return False
    if not is_dir(path):
        return not exists(path)
    with os.scandir(path) as entries:
        return next(entries, None) is None


def linked_directory(path: Path) -> Path | None:
    """The directory a symbolic link at `path` leads its file into, or `None` where `path` is not
    one or that cannot be told: what a failed write through the link names, since the write went
    there and not beside the link."""
    try:
        return resolved(path).parent if is_symlink(path) else None
    except OSError:
        return None


def creation_directory(path: Path) -> Path:
    """The directory `path` would be made in: the one it lives in, or, while that is not there
    yet, the nearest one above it that is, where `mkdir(parents=True)` would start. What
    `creatable` asks about, and so what a refusal on its answer names."""
    directory = path.parent
    while not exists(directory) and directory != directory.parent:
        directory = directory.parent
    return directory


def creatable(path: Path) -> bool:
    """Whether this user can create or replace `path`: `write_atomically` renames a new file in
    beside it, and `mkdir` makes it, so `creation_directory(path)` must be writable and
    searchable. `os.access` answers for the real uid, so under root it says yes whatever the mode:
    a caller that refuses on this answer keeps a floor under the write itself."""
    return os.access(creation_directory(path), os.W_OK | os.X_OK)


def _meets_a_loop(path: Path) -> None:
    """Raise the system's own `ELOOP` for `path`, naming it as given, when following it meets a
    symbolic-link loop; return otherwise, whatever else `stat` says."""
    try:
        os.stat(path)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise


def resolved(path: Path) -> Path:
    """`path.resolve()`, with a symbolic-link loop answered alike on every interpreter: as the
    `OSError` (`ELOOP`) `stat` raises for `path`, which every caller already answers.

    Python 3.11 and 3.12 raise `RuntimeError` for a loop met while resolving, which no
    `except OSError` catches, and 3.13 and later answer a path with the loop left in it; both are
    asked of `stat`, which meets the loop again. A `RuntimeError` `stat` cannot confirm is still
    `ELOOP`, in words of its own.
    """
    try:
        answer = path.resolve()
    except RuntimeError as exc:
        _meets_a_loop(path)
        raise OSError(errno.ELOOP, "a symbolic link loop", str(path)) from exc
    _meets_a_loop(path)
    return answer


class NotRegularFile(OSError):
    """A path a reader was handed names something other than a regular file. An `OSError`, so
    every reader's existing "could not be read" arm is its answer without a branch of its own."""


class TooLarge(OSError):
    """A regular file longer than `REGULAR_READ_LIMIT`, refused unread past the limit. An `OSError`
    for the reason `NotRegularFile` is one."""


# A named cap: the most bytes `read_regular_bytes` and `read_regular_text` read of one file. A
# regular file can be endless (`/proc/self/pagemap` is `S_ISREG` with a size of 0), and a committed
# link to one passes every check above the read, so the read asks for one byte past the cap and
# refuses a file that has it. Far above any file these readers take (`MEMORY.md`'s own budget is
# 25,600 bytes) and far under a machine's memory. A file drybag writes is held under it too
# (`jsonobject.json_text`, `attach`'s `permissions`). No shipped file states it.
REGULAR_READ_LIMIT = 64 * 1024 * 1024
# A named cap (CONTRIBUTING.md#named-caps): how many directory entries, in total, a walk over a
# repository's tree that looks for something lists before it says it could not tell: `doctor`'s
# walk of the note store (`memory.doctor`). `docs/cli.md` states it in `doctor`'s `memory` row.
WALK_ENTRIES = 500_000

# The open `open_regular` makes: it follows a link at the last component (overlay mode links each
# memory group and `MEMORY.md` into the overlay); it never waits, so a FIFO swapped in after the
# check cannot block it; and a terminal swapped in never becomes the controlling one.
_REGULAR_OPEN = os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC


def open_regular(path: Path) -> BinaryIO:
    """`path` opened for reading in binary, if it names a regular file, followed through
    symbolic links; `NotRegularFile` if it names anything else.

    For a reader of files a repository commits, where a link to `/dev/zero`, to `/dev/stdin` or to
    a FIFO would read for ever or wait. The path is asked with `stat` before anything is opened, so
    a device it names is never opened; one repointed between the check and the open is opened
    without blocking and refused unread, since the descriptor must be the file the check saw. The
    read is bounded by the caller (`read_bounded`, `REGULAR_READ_LIMIT`).
    """
    checked = os.stat(path)
    if not stat.S_ISREG(checked.st_mode):
        raise NotRegularFile(errno.EINVAL, "not a regular file", str(path))
    descriptor = os.open(path, _REGULAR_OPEN)
    try:
        # The file that was checked, and so a regular one: anything else opened in its place,
        # a device or another file, is a different `(st_dev, st_ino)`.
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (checked.st_dev, checked.st_ino):
            raise NotRegularFile(errno.EINVAL, "not a regular file", str(path))
    except BaseException:
        os.close(descriptor)
        raise
    # Outside the `try`: once `fdopen` has the descriptor it closes it on its own failure, and a
    # second close here would raise `EBADF` in place of the real error.
    return os.fdopen(descriptor, "rb")


# The open `read_bounded_within` makes of the last component under a root: `_REGULAR_OPEN`'s, and a
# link there is refused as every component above it is.
_WITHIN_OPEN = _REGULAR_OPEN | getattr(os, "O_NOFOLLOW", 0)


@contextmanager
def open_directory(path: Path) -> Iterator[int]:
    """A descriptor for the directory `path`, its last component not followed if it is a link,
    closed when the block ends: the `root` `read_bounded_within` reads several files under with
    one open."""
    descriptor = os.open(path, _DIR_FLAGS)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _opened_within(root: Path | int, relative: str) -> int:
    """A descriptor for `root/relative` opened for reading, no component of it followed if it is a
    symbolic link, the file included; `NotRegularFile` if it is anything else. `root` an open
    directory descriptor takes one name and no path below it."""
    if isinstance(root, int):
        parts = checked_components(relative)
        if len(parts) != 1:
            raise UnsafePath(f"{relative!r} is not one name in the directory it is read from")
        descriptor = os.open(parts[0], _WITHIN_OPEN, dir_fd=root)
    else:
        with open_within(root, relative) as (dir_fd, name):
            descriptor = os.open(name, _WITHIN_OPEN, dir_fd=dir_fd)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise NotRegularFile(errno.EINVAL, "not a regular file", relative)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_upto(descriptor: int, size: int) -> bytes:
    """Up to `size` bytes from `descriptor`, fewer only at its end: unbuffered, since a header of a
    few bytes costs a buffer's allocation per file otherwise, and looped, since one `read` may
    return less than it was asked for."""
    chunks: list[bytes] = []
    while size > 0:
        chunk = os.read(descriptor, size)
        if not chunk:
            break
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)


def _bounded(content: bytes, limit: int) -> tuple[bytes, bool]:
    """`content`, read to one byte past `limit`, cut to `limit`, and whether it ran past it."""
    return content[:limit], len(content) > limit


def read_bounded(path: Path, limit: int) -> tuple[bytes, bool]:
    """At most `limit` bytes of a regular file reached by `open_regular`'s rules, and whether it
    holds more: one byte past `limit` is asked for and no more, so an endless file costs
    `limit + 1`. The one reader of a file held to a bound; `read_bounded_within` is the one under a
    root."""
    with open_regular(path) as stream:
        return _bounded(stream.read(limit + 1), limit)


def read_bounded_within(root: Path | int, relative: str, limit: int) -> tuple[bytes, bool]:
    """`read_bounded` of `relative` under `root`, reached as `open_within` reaches a file: no
    component followed if it is a link, the file included, and a regular file only. `root` may be a
    directory `open_directory` opened and `relative` one name in it, so it is opened once."""
    descriptor = _opened_within(root, relative)
    try:
        return _bounded(_read_upto(descriptor, limit + 1), limit)
    finally:
        os.close(descriptor)


def read_regular_bytes(path: Path, *, limit: int | None = None) -> bytes:
    """The bytes of a regular file, reached as `read_bounded` reaches it, and `TooLarge` for one
    longer than `limit`, or than `REGULAR_READ_LIMIT` where a reader holds its files to no cap of
    its own."""
    content, over = read_bounded(path, REGULAR_READ_LIMIT if limit is None else limit)
    if over:
        raise TooLarge(errno.EFBIG, "larger than this reader reads", str(path))
    return content


def read_regular_text(path: Path, *, newline: str | None = None, limit: int | None = None) -> str:
    """`read_regular_bytes(path, limit=limit)` decoded as UTF-8, a `UnicodeDecodeError` where it
    is not. `newline` as `open` takes it: `None` translates every CRLF and lone CR to LF, as
    `Path.read_text` does, and `""` keeps the file's own line endings."""
    text = read_regular_bytes(path, limit=limit).decode("utf-8")
    if newline is None:
        return text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def checked_components(relative: str) -> tuple[str, ...]:
    """The path's components, or `UnsafePath` for any spelling that could leave the root.

    Public, and the one place this rule lives: `config.paths.contained()` calls it, so a configured
    path `plan()` accepts is one the write accepts. Split on the raw string, never on
    `PurePosixPath(relative).parts`, which drops `.`, empty segments and a trailing slash, so a
    guard on those parts sees only what pathlib kept. Refused:

    * the empty path, and any path that is only separators;
    * an absolute path — `openat` ignores its `dir_fd` for one, so the walk would restart at
      the filesystem root;
    * `..`, which walks out one component at a time; and `.` and an empty segment (`a//b`, a
      trailing slash), refused because a surface that quietly rewrites its argument has to
      restate its guarantee per caller;
    * a component holding a NUL, which names no file and which every path call meets with a
      `ValueError` rather than an `OSError`;
    * and git's control directory, at any depth and in any case (`CONTROL_DIRECTORY`): staying
      inside the root is not the whole of containment, since `.git/hooks/pre-commit` is inside
      every root and an existing file's 0755 is carried onto its replacement (`_mode_of`). This
      covers the callers with no configured string for `contained()`: `attach`, `overlay`,
      `hooks`.
    """
    if relative.startswith("/"):
        raise UnsafePath(f"{relative!r} is absolute; a path here must stay inside the root")
    if not relative:
        raise UnsafePath(f"{relative!r} names no file")
    parts = tuple(relative.split("/"))
    for part in parts:
        if part == "":
            raise UnsafePath(f"{relative!r} has an empty path component")
        if "\x00" in part:
            raise UnsafePath(f"{relative!r} holds a NUL, which no path can")
        if part in (_PARENT, _HERE):
            raise UnsafePath(
                f"{relative!r} contains {part!r}; a path here must stay inside the root"
            )
    if names_control_directory(relative):
        raise UnsafePath(
            f"{relative!r} names {CONTROL_DIRECTORY!r}; git's control directory is not a "
            "repository-scoped tool's to write into"
        )
    return parts


@contextmanager
def open_within(root: Path, relative: str) -> Iterator[tuple[int, str]]:
    """Yield `(directory descriptor, final name)` for `root/relative`, following no symlink. The
    caller writes through the descriptor, so nothing between this walk and the write can redirect
    it. `relative` must stay inside `root` by its own spelling (`checked_components`)."""
    parts = checked_components(relative)
    fd = os.open(root, _DIR_FLAGS)
    opened = [fd]
    try:
        for part in parts[:-1]:
            try:
                nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except OSError as exc:
                # O_NOFOLLOW on a symlink reports ELOOP on Linux and ENOTDIR on macOS when the
                # link points at a directory; both mean the same thing here.
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise UnsafePath(
                        f"{relative!r}: {part!r} is a symlink or not a directory"
                    ) from exc
                raise
            opened.append(nxt)
            fd = nxt
        yield fd, parts[-1]
    finally:
        for handle in reversed(opened):
            os.close(handle)


def check_within(root: Path, relative: str) -> None:
    """Walk to `root/relative` as every write and removal here does, and touch nothing: the same
    `UnsafePath` the write or removal would raise, from the same walk, before a caller's first
    write. A component that is not there is not an error: a removal through it removes nothing."""
    with contextlib.suppress(FileNotFoundError), open_within(root, relative):
        pass


def _mode_of(dir_fd: int, name: str) -> int | None:
    """The mode to carry over, and `None` for a file that is not there to carry one, so the caller
    tells "keep this file's mode" from a new file, whose mode the umask decides.

    `lstat` of a symlink reports `0o777`, which carried over would make the replacement
    world-writable; `contained()` refuses a final symlink before any caller here runs, and this is
    the floor under it: anything but a regular file is `None`.
    """
    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return stat.S_IMODE(info.st_mode) if stat.S_ISREG(info.st_mode) else None


def _sync_directory(dir_fd: int) -> None:
    """Make the rename itself durable, and never fail a completed write because it was not: a
    filesystem that refuses `fsync` on a directory (`EINVAL`) costs the durability guarantee alone.
    """
    with contextlib.suppress(OSError):
        os.fsync(dir_fd)


def write_atomically_at(
    dir_fd: int,
    name: str,
    text: str,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    mode: int | None = None,
) -> None:
    """Replace `name` inside the already-opened directory, keeping the mode it had, or giving it
    `mode` where the caller names one. `errors` is the codec's: `surrogateescape` writes back
    exactly the bytes a file was read with under the same handler."""
    mode = _mode_of(dir_fd, name) if mode is None else mode
    temporary = f".drybag-{os.getpid()}-{name}.tmp"
    create = NEW_FILE_MODE if mode is None else 0o600
    handle = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, create, dir_fd=dir_fd)
    try:
        with os.fdopen(handle, "w", encoding=encoding, errors=errors) as stream:
            stream.write(text)
            if mode is not None:
                # On the descriptor: the temporary was created O_CREAT|O_EXCL, so it is no link,
                # and `os.chmod(..., follow_symlinks=False)` is supported only on some platforms.
                # A new file is not chmod-ed: it was created `NEW_FILE_MODE`, under the umask.
                os.fchmod(stream.fileno(), mode)
            # Userspace to kernel, then kernel to disk: `flush` alone leaves it in the page cache.
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        _sync_directory(dir_fd)
    except BaseException:
        _unlink_quietly(dir_fd, temporary)
        raise


def _unlink_quietly(dir_fd: int, name: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(name, dir_fd=dir_fd)


def write_atomically(
    path: Path, text: str, *, encoding: str = "utf-8", errors: str = "strict"
) -> None:
    """Replace `path` with `text` in one step, keeping the mode it already had: the plain-path
    form, for a caller that already holds a trusted absolute path, such as the memory store's notes
    and index. The same write as `write_atomically_at`, through a descriptor on `path.parent`, so
    the mode rule, the `fsync` pair and the temporary's lifetime are one implementation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        write_atomically_at(dir_fd, path.name, text, encoding=encoding, errors=errors)
    finally:
        os.close(dir_fd)


# The flags of the one appending write: a regular file created 0600 where none is, written at its
# end, never through a link at its last component, and `O_NONBLOCK`, so a FIFO left at the path
# with no reader is `ENXIO` rather than a wait for ever.
_APPEND_FLAGS = (
    os.O_WRONLY
    | os.O_APPEND
    | os.O_CREAT
    | getattr(os, "O_NOFOLLOW", 0)
    | os.O_CLOEXEC
    | os.O_NONBLOCK
)
APPENDED_FILE_MODE = 0o600


def append_at(dir_fd: int, name: str, payload: bytes) -> None:
    """Append `payload` to the file `name` in the directory `dir_fd` (one `open_within` yielded),
    in one `O_APPEND` write, creating it `APPENDED_FILE_MODE` where it is not there: the one
    appending write, which the hook sink's diagnostics reach. One `write` of the whole line, so two
    processes appending at once never interleave inside a line on a local filesystem. Raises
    `OSError` as the open or the write does."""
    handle = os.open(name, _APPEND_FLAGS, APPENDED_FILE_MODE, dir_fd=dir_fd)
    try:
        os.write(handle, payload)
    finally:
        os.close(handle)


def mkdirs_within(root: Path, target: str) -> None:
    """Create `target`'s parent directories without ever leaving the root.

    `Path.mkdir(parents=True)` follows symlinks, so a component that became a link after
    `contained()` passed would make it create directories outside the root before the
    `O_NOFOLLOW` walk could refuse. Each component here is created relative to a descriptor the
    walk just opened, so a symlink anywhere along the path refuses with nothing created. Public,
    because every area that puts a file into a repository needs it, and getting it wrong is silent.
    """
    # `checked_components`, so the whole target is refused by its own spelling before any
    # directory is created, rather than one branch at a time.
    parts = checked_components(target)[:-1]
    for depth in range(len(parts)):
        branch = "/".join(parts[: depth + 1])
        with open_within(root, branch) as (dir_fd, name), contextlib.suppress(FileExistsError):
            os.mkdir(name, dir_fd=dir_fd)


def write_within(
    root: Path, target: str, text: str, *, encoding: str = "utf-8", mode: int | None = None
) -> None:
    """Create the parents and replace `root/target`, reaching it through the `O_NOFOLLOW` walk;
    `mode` is `write_atomically_at`'s."""
    mkdirs_within(root, target)
    with open_within(root, target) as (dir_fd, name):
        write_atomically_at(dir_fd, name, text, encoding=encoding, mode=mode)


# The flags of the one exclusive create: `O_CREAT | O_EXCL` fails with `EEXIST` on any existing
# name, a dangling link included, and follows no link at the last component.
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC


def create_within(root: Path, target: str, data: bytes, *, mode: int) -> bool:
    """Create `root/target` holding `data` with exactly `mode`'s bits, and say whether it did.

    Through `open_within`'s walk with `O_CREAT | O_EXCL`, so a name already there — a file, a
    directory or a link, dangling or not — is left and answers `False`, and nothing is written
    through a link. The parents are not created. `mode` is set on the descriptor, which the umask
    does not narrow; a write that fails after the create removes the file and raises.
    """
    with open_within(root, target) as (dir_fd, name):
        try:
            handle = os.open(name, _CREATE_FLAGS, 0o600, dir_fd=dir_fd)
        except FileExistsError:
            return False
        try:
            with os.fdopen(handle, "wb") as stream:
                os.fchmod(stream.fileno(), mode)
                stream.write(data)
        except BaseException:
            _unlink_quietly(dir_fd, name)
            raise
    return True


def remove_within(root: Path, target: str) -> None:
    """Unlink `root/target` through the same walk; an absent file is not an error."""
    with open_within(root, target) as (dir_fd, name), contextlib.suppress(FileNotFoundError):
        os.unlink(name, dir_fd=dir_fd)


def rmdir_within(root: Path, target: str) -> None:
    """Remove the empty directory `root/target` through the same walk; an absent one is not an
    error. `remove_within` cannot: `unlink` of a directory is `EPERM` on macOS and `EISDIR` on
    Linux. One walk for both, so a hardening of it reaches this too."""
    with open_within(root, target) as (dir_fd, name), contextlib.suppress(FileNotFoundError):
        os.rmdir(name, dir_fd=dir_fd)


def keep_newest(root: Path, directory: str, kept: int) -> None:
    """Remove every subdirectory of `root/directory` but the `kept` newest by `st_mtime_ns`, each
    file through `remove_within` and then the directory through `rmdir_within`. A removal a listing
    drives (CONTRIBUTING.md#enumerated-writes), so `directory` is one only drybag writes, under its
    own data root. A listing that fails removes nothing."""
    base = root / directory
    try:
        found = sorted(
            (path for path in base.iterdir() if is_dir(path)),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return
    for stale in found[kept:]:
        for child in stale.iterdir():
            remove_within(root, f"{directory}/{stale.name}/{child.name}")
        rmdir_within(root, f"{directory}/{stale.name}")


class NotASymlink(OSError):
    """A real file or directory was found where a symlink was asked about; it is left alone."""


def _type_of(dir_fd: int, name: str) -> int | None:
    """`S_IFMT` of the entry, or `None` when nothing is there — the link questions' `lstat`. Not
    `_mode_of`, which strips the type bits and answers `None` for anything but a regular file."""
    try:
        return stat.S_IFMT(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode)
    except FileNotFoundError:
        return None


def readlink_within(root: Path, target: str) -> Path | None:
    """The target of the symlink at `root/target`; `None` when nothing is there. Asked of the
    entry the walk's descriptor names, never of a re-resolved path. A real entry raises
    `NotASymlink`: the callers treat it as somebody else's and never remove it."""
    with open_within(root, target) as (dir_fd, name):
        kind = _type_of(dir_fd, name)
        if kind is None:
            return None
        if kind != stat.S_IFLNK:
            raise NotASymlink(f"{target!r} is not a symlink")
        return Path(os.readlink(name, dir_fd=dir_fd))


def symlink_within(root: Path, target: str, source: Path) -> None:
    """Create `root/target -> source` through the walk; parents are created the same way.
    `FileExistsError` when anything is already there: the caller reads first (`readlink_within`)
    and removes first (`unlink_within`); this never replaces."""
    mkdirs_within(root, target)
    with open_within(root, target) as (dir_fd, name):
        os.symlink(str(source), name, dir_fd=dir_fd)


def unlink_within(root: Path, target: str, *, pointing_at: Path | None = None) -> bool:
    """Remove the symlink at `root/target`; report whether anything was removed. A real entry
    raises `NotASymlink`; with `pointing_at`, only a link to exactly that path is removed, since a
    link pointing anywhere else is somebody else's."""
    with open_within(root, target) as (dir_fd, name):
        kind = _type_of(dir_fd, name)
        if kind is None:
            return False
        if kind != stat.S_IFLNK:
            raise NotASymlink(f"{target!r} is not a symlink")
        if pointing_at is not None and Path(os.readlink(name, dir_fd=dir_fd)) != pointing_at:
            return False
        os.unlink(name, dir_fd=dir_fd)
        return True
