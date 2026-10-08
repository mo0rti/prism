"""The one resolver for every path a wiki page names: Markdown links, `sources` entries and `repo:` links.

A page is untrusted text. A link such as `%2F%2Fhost%2Fshare%2Fx.md` or `..%5C..%5Cx.md` must never reach
the filesystem before it is known to be a plain path below the workspace, because on Windows a UNC path
or a drive-qualified path makes `Path.resolve()` or `Path.exists()` touch a network share or another volume.
So the resolver works in three steps and stops at the first that rejects:

1. **Decode and check lexically.** Percent escapes are decoded first, then the path is rejected when it has a
   control character, a backslash, a root (`/x`, `//host/share`), a drive or stream colon (`C:x`, `x.md:s`), or
   decodes again into any of those (double encoding). No filesystem call happens in this step.
2. **Confine lexically.** The path is joined to the directory it is relative to and normalized as a string.
   A result outside the boundary is rejected. No filesystem call happens in this step either.
3. **Look at the components.** Only now is the filesystem read, one `lstat` per component below the boundary,
   and a symlink, a junction or any other reparse point is rejected. The walk never opens a file.

Everything that resolves a wiki path calls `resolve_confined`: the lint of links, `sources` and `repo:` links,
the API-contract and requirement references, the graph and the transitions.
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from prism_cli.fs_safety import reparse_kind

MAX_DECODE_ROUNDS = 4

UNSAFE = "unsafe"
OUTSIDE = "outside"
REPARSE = "reparse"


def unsafe_path_problem(path: str) -> str | None:
    """Why one decoded path is not a plain relative path, or ``None``. Looks only at the text."""

    if not path:
        return "is empty."
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        return "contains a control character."
    if "\\" in path:
        return "contains a backslash; write links with `/`."
    if path.startswith("/"):
        return "is rooted or a network path; write a path relative to the page."
    for segment in path.split("/"):
        if ":" in segment:
            return "contains a drive letter or a stream name (`:`) in a segment."
    return None


def decoded_link_path(raw: str, *, percent_encoded: bool = True) -> tuple[str | None, str | None]:
    """The path a link names as `(path, problem)`; the path is ``None`` when the problem is set.

    ``percent_encoded`` says whether ``raw`` is still percent-encoded (a link as written) or was decoded
    already (a target an earlier step returned). Either way every further decoding of the path is checked
    too, so a double-encoded UNC or drive path is refused no matter which step decodes it next.
    """

    path = unquote(raw) if percent_encoded else raw
    problem = unsafe_path_problem(path)
    if problem is not None:
        return None, problem
    current = path
    for _ in range(MAX_DECODE_ROUNDS):
        following = unquote(current)
        if following == current:
            return path, None
        problem = unsafe_path_problem(following)
        if problem is not None:
            return None, f"is encoded twice, and then {problem[:1].lower()}{problem[1:]}"
        current = following
    return None, "is percent-encoded too many times."


@dataclass(frozen=True)
class Resolution:
    """The outcome of `resolve_confined`.

    ``path`` is the lexical path below the boundary (not resolved through links, and not checked for existence)
    when the outcome has no ``kind``. ``kind`` is `unsafe`, `outside` or `reparse` when the path was refused, with
    the sentence in ``problem``. ``exists`` says whether every component exists; it is only meaningful without a ``kind``.
    """

    path: Path | None = None
    kind: str | None = None
    problem: str | None = None
    exists: bool = False

    @property
    def ok(self) -> bool:
        return self.kind is None


def lexical_join(base: Path, path: str, boundary: Path) -> Path | None:
    """`base` plus the decoded relative `path`, normalized as a string, or ``None`` when it leaves `boundary`. No filesystem call."""

    boundary_text = os.path.abspath(str(boundary))
    joined = os.path.abspath(os.path.join(str(base), *path.split("/")))
    try:
        common = os.path.commonpath([os.path.normcase(boundary_text), os.path.normcase(joined)])
    except ValueError:  # another drive
        return None
    if common != os.path.normcase(boundary_text):
        return None
    return Path(joined)


def inspect_components(boundary: Path, candidate: Path) -> tuple[bool, bool]:
    """`(passes through a link, exists)` for the components of `candidate` below `boundary`. Only `lstat` calls; nothing is opened."""

    relative = os.path.relpath(str(candidate), str(boundary))
    current = Path(os.path.abspath(str(boundary)))
    if relative in {".", ""}:
        return False, True
    for part in relative.split(os.sep):
        current = current / part
        try:
            info = current.lstat()
        except (OSError, ValueError):
            return False, False
        if reparse_kind(info) != "none":
            return True, True
    return False, True


def resolve_confined(boundary: Path, base: Path, raw: str, *, percent_encoded: bool = True) -> Resolution:
    """Resolve `raw` (a path relative to the directory `base`) to a plain path below `boundary`, or say why not.

    ``boundary`` and ``base`` are the caller's own trusted absolute paths (the workspace or wiki root and the
    directory of the page); only ``raw`` comes from a page. See the module docstring for the three steps.
    """

    path, problem = decoded_link_path(raw, percent_encoded=percent_encoded)
    if path is None:
        return Resolution(kind=UNSAFE, problem=problem or "is not a plain relative path.")
    candidate = lexical_join(base, path, boundary)
    if candidate is None:
        return Resolution(kind=OUTSIDE, problem="leaves the workspace.")
    linked, exists = inspect_components(boundary, candidate)
    if linked:
        return Resolution(kind=REPARSE, problem="passes through a symlink or reparse point, which lint does not follow.")
    return Resolution(path=candidate, exists=exists)


class RefusedPath(ValueError):
    """A path `read_confined_bytes` refused; ``resolution`` says why."""

    def __init__(self, resolution: Resolution) -> None:
        super().__init__(resolution.problem or "The path is refused.")
        self.resolution = resolution


def read_confined_bytes(boundary: Path, raw: str, *, percent_encoded: bool = False) -> bytes | None:
    """The bytes of the file `raw` names below `boundary`, read once and never through a link; ``None`` when it does not exist.

    The path is checked by `resolve_confined` first. The file is then opened without following a link (`O_NOFOLLOW`
    where the platform has it), and the open handle is compared with the path: the path must still be free of links
    and must name the very file the handle holds. A link swapped in between the check and the open is refused as
    `RefusedPath`, never read. A file that cannot be read, or is not a regular file, raises `OSError`.
    """

    resolution = resolve_confined(boundary, boundary, raw, percent_encoded=percent_encoded)
    if not resolution.ok or resolution.path is None:
        raise RefusedPath(resolution)
    if not resolution.exists:
        return None
    swapped = Resolution(kind=REPARSE, problem="was replaced by a link while it was being opened.")
    try:
        descriptor = os.open(resolution.path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise RefusedPath(swapped) from exc
        raise
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(errno.EINVAL, "not a regular file", str(resolution.path))
        again = resolve_confined(boundary, boundary, raw, percent_encoded=percent_encoded)
        try:
            listed = os.lstat(again.path) if again.ok and again.path is not None else None
        except OSError:
            listed = None
        if listed is None or reparse_kind(listed) != "none" or not os.path.samestat(opened, listed):
            raise RefusedPath(again if not again.ok else swapped)
        return handle.read()


def resolve_to_path(boundary: Path, base: Path, raw: str, *, percent_encoded: bool = False) -> Path | None:
    """The canonical path `raw` names below `boundary`, or ``None`` when it is refused or cannot be resolved.

    The path is checked by `resolve_confined` first; `Path.resolve()` (which maps case and short names to what is on
    disk) only runs on a path that is already known to be a plain path below the boundary, and its result must stay
    there. Use it where the caller compares the result with the resolved path of a page it already read.
    """

    resolution = resolve_confined(boundary, base, raw, percent_encoded=percent_encoded)
    if not resolution.ok or resolution.path is None:
        return None
    try:
        resolved = resolution.path.resolve()
        resolved.relative_to(boundary.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved
