"""Helpers for the tests that run real Copier against a disposable, tagged copy of this template.

The template contract and the Copier tests render the working tree, tracked or not. A test that needs
committed state (an update across a tag, a recorded `_commit`) builds a snapshot repository under a
temporary folder instead: the files of the template, one commit and one tag per version.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from prism_cli import cli
from prism_cli.app_model import GENERATION_SCAFFOLDED, apps_from_platforms

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ITEMS = ("copier.yml", "template", "packs")
GIT_IDENTITY = ("-c", "user.name=Prism test", "-c", "user.email=test@example.invalid", "-c", "core.autocrlf=false")


def git(cwd: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *GIT_IDENTITY, *arguments], cwd=cwd, check=check, capture_output=True, text=True)


def no_background_gc(repo: Path) -> None:
    """Keep git from repacking loose objects in the background while a test copies or reads the repository."""

    git(repo, "config", "gc.auto", "0")
    git(repo, "config", "maintenance.auto", "false")


def build_template_repo(destination: Path, tag: str = "v1.0.0") -> Path:
    """A git repository holding this template's working tree as one commit, tagged ``tag``."""

    destination.mkdir(parents=True)
    for item in TEMPLATE_ITEMS:
        source = REPO_ROOT / item
        if source.is_dir():
            shutil.copytree(source, destination / item)
        else:
            shutil.copy2(source, destination / item)
    git(destination, "init", "-q")
    no_background_gc(destination)
    git(destination, "add", "-A")
    git(destination, "commit", "-qm", f"Template {tag}")
    git(destination, "tag", tag)
    return destination


def tag_template_change(repo: Path, tag: str, *edits: tuple[str, str, str]) -> None:
    """Commit edits of template files and tag them. An edit is ``(relative path, "append" | "first-line", text)``."""

    for relative, kind, text in edits:
        path = repo / relative
        raw = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        content = raw.replace("\r\n", "\n")
        if kind == "append":
            content += text
        elif kind == "first-line":
            lines = content.split("\n")
            lines[0] = text
            content = "\n".join(lines)
        else:
            raise ValueError(kind)
        path.write_bytes((content.replace("\n", "\r\n") if crlf else content).encode("utf-8"))
    git(repo, "commit", "-qam", f"Template {tag}")
    git(repo, "tag", tag)


def template_url(repo: Path) -> str:
    """The remote-style URL of a local template repository, so the CLI treats it as a versioned template."""

    return "git+" + repo.resolve().as_uri()


def quiet_generation_process(command: list[str], cwd: Path, *, capture_stderr: bool = False) -> dict[str, Any]:
    """`cli.run_copier_generation_process` with the child's output captured, so a test run stays readable."""

    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, errors="replace")
    lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    return {"returncode": result.returncode, "event_count": 0, "tail": lines[-8:], "stderr": result.stderr if capture_stderr else ""}


def run_cli(*arguments: str) -> tuple[int, str, str]:
    """Run the Prism CLI in-process, returning the exit code and what it printed."""

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.object(cli, "run_copier_generation_process", quiet_generation_process):
        code = cli.main(list(arguments))
    return code, out.getvalue(), err.getvalue()


def remove_tree(path: Path) -> None:
    """Delete a folder even when it holds read-only files, as a git object store does on Windows."""

    def make_writable(function, target, _excinfo):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onerror=make_writable)


def write_answers(path: Path, answers: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump({"schema_version": 1, "answers": answers}, sort_keys=False), encoding="utf-8")
    return path


def generate_workspace(repo: Path, destination: Path, answers: dict[str, Any], scratch: Path) -> tuple[int, str, str]:
    """`prism new` from the template repository with an answers file."""

    answers_file = write_answers(scratch / f"{destination.name}-answers.yml", answers)
    return run_cli("new", "--template", template_url(repo), "--trust-template", "--answers", str(answers_file), "--dest", str(destination), "--yes")


def commit_workspace(workspace: Path) -> None:
    """Make a generated workspace a git repository with its generated state committed."""

    git(workspace, "init", "-q", "-b", "main")
    no_background_gc(workspace)
    # The CLI's update and scaffold commits run without the helper's `-c` identity, like a user's
    # own repository, so the workspace carries a local identity (CI runners have no global one).
    git(workspace, "config", "user.name", "Prism test")
    git(workspace, "config", "user.email", "test@example.invalid")
    git(workspace, "add", "-A")
    git(workspace, "commit", "-qm", "Generated workspace")


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def generate_default_apps(
    destination: Path,
    app_ids: list[str],
    scratch: Path,
    project_name: str = "Scope Check",
    extra_apps: list[dict[str, Any]] | None = None,
    **answers: Any,
) -> Path:
    """Generate a workspace from this checkout's working tree with the default apps of these IDs.

    This is what the template tests need in place of a raw `copier copy --data platforms=...`: the CLI
    runs the workspace layer and each app's pack, and a full sample comes from the workspace layer.
    ``extra_apps`` are further app entries, such as a second app of a stack, listed after the defaults.
    """

    apps = apps_from_platforms(app_ids, generation=GENERATION_SCAFFOLDED) + list(extra_apps or [])
    answers_file = write_answers(scratch / f"{destination.name}-answers.yml", {"project_name": project_name, "apps": apps, **answers})
    code, out, err = run_cli("new", "--answers", str(answers_file), "--dest", str(destination), "--yes")
    if code != 0:
        raise AssertionError(f"prism new failed for {app_ids} with exit code {code}:\n{out[-1500:]}\n{err[-1500:]}")
    return destination
