"""Git and conflict helpers for layered generation and update.

A workspace is generated, and later updated, one layer at a time: the workspace layer and then each
scaffolded app, every layer from its own Copier answers file. Copier needs a clean git tree for each
update, so the CLI commits after each layer, on a branch of its own. Copier exits 0 when a layer
conflicts, so the CLI scans for ``.rej`` files and conflict markers after each layer and reports the
result per layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import subprocess

# Files larger than this are not scanned for conflict markers.
MAX_SCANNED_BYTES = 4 * 1024 * 1024

_CONFLICT_OPEN = re.compile(rb"^<{7}(?: |$)", re.MULTILINE)
_CONFLICT_CLOSE = re.compile(rb"^>{7}(?: |$)", re.MULTILINE)
# `git status --porcelain` codes of an unmerged path.
_UNMERGED = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


@dataclass(frozen=True)
class Layer:
    """One layer of a generated workspace: the workspace layer or the layer of one scaffolded app."""

    name: str
    answers_file: str
    app_id: str | None = None
    app_path: str | None = None

    @property
    def is_workspace(self) -> bool:
        return self.app_id is None


@dataclass
class LayerResult:
    """What one layer's update did."""

    layer: Layer
    outcome: str  # "updated", "unchanged", "conflicted" or "failed"
    conflicts: list[str] = field(default_factory=list)
    commit: str | None = None
    detail: str = ""


class GitError(RuntimeError):
    """A git command the CLI needs failed."""


def git(project: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in ``project``; with ``check``, a failure raises ``GitError`` carrying git's message."""

    try:
        result = subprocess.run(
            ["git", "-C", str(project), *arguments],
            capture_output=True,
            text=True,
            errors="replace",
        )
    except OSError as exc:
        raise GitError(f"git could not run: {exc}") from exc
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise GitError(f"`git {' '.join(arguments)}` failed: {message}")
    return result


def current_branch(project: Path) -> str | None:
    """The checked-out branch, or ``None`` on a detached head."""

    result = git(project, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    name = result.stdout.strip()
    return name if result.returncode == 0 and name else None


def has_commit_identity(project: Path) -> bool:
    """Whether git knows who commits: a configured name and email, or the environment's."""

    def configured(key: str, variable: str) -> bool:
        if os.environ.get(variable, "").strip():
            return True
        return bool(git(project, "config", "--get", key, check=False).stdout.strip())

    return configured("user.name", "GIT_COMMITTER_NAME") and configured("user.email", "GIT_COMMITTER_EMAIL")


def branch_exists(project: Path, name: str) -> bool:
    return git(project, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False).returncode == 0


def create_branch(project: Path, name: str) -> None:
    git(project, "switch", "--quiet", "-c", name)


def commit_layer(project: Path, message: str) -> str | None:
    """Stage everything except the ``.rej`` files of a conflict and commit it; ``None`` when the layer changed nothing.

    A ``.rej`` file is Copier's record of a hunk it could not apply. It belongs to the person resolving the conflict, so it is
    never committed: it stays in the working tree, where ``scan_conflicts`` finds it.
    """

    git(project, "add", "-A", "--", ".", ":(exclude,glob)**/*.rej")
    if git(project, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    git(project, "commit", "--quiet", "-m", message)
    return git(project, "rev-parse", "--short", "HEAD").stdout.strip()


def changed_paths(project: Path) -> list[tuple[str, str]]:
    """Every changed or untracked path as ``(status code, relative path)``, with each path of a new folder listed."""

    result = git(project, "status", "--porcelain=v1", "-z", "-uall")
    entries: list[tuple[str, str]] = []
    fields = result.stdout.split("\0")
    index = 0
    while index < len(fields):
        item = fields[index]
        index += 1
        if len(item) < 4:
            continue
        code, path = item[:2], item[3:]
        if code[0] in "RC":
            index += 1  # a rename or copy is followed by its source path
        entries.append((code, path))
    return entries


def scan_conflicts(project: Path) -> list[str]:
    """The paths of the working tree that hold an unresolved conflict of a Copier update.

    A conflict is an unmerged path, a ``.rej`` file or a file with a conflict marker block.
    """

    found: list[str] = []
    for code, relative in changed_paths(project):
        path = project / relative
        if code in _UNMERGED or relative.endswith(".rej"):
            found.append(relative)
            continue
        try:
            if not path.is_file() or path.stat().st_size > MAX_SCANNED_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data:
            continue
        if _CONFLICT_OPEN.search(data) and _CONFLICT_CLOSE.search(data):
            found.append(relative)
    return sorted(set(found))
