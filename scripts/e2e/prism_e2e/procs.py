"""Child processes: launch with a timeout, kill the whole tree, find the host executables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
from typing import Mapping, Sequence

IS_WINDOWS = os.name == "nt"
# Each child gets its own process group so Ctrl+C in the terminal reaches only this script, which then kills the tree.
# The board keeps the console it inherits, because the graceful stop is a console break event sent to its group.
HOST_FLAGS: dict[str, object] = (
    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {"start_new_session": True}
)
_BOARD_FLAGS: dict[str, object] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WINDOWS else {"start_new_session": True}
_LIVE: set[subprocess.Popen] = set()
_LIVE_LOCK = threading.Lock()


def kill_tree(process: subprocess.Popen) -> None:
    """Hard-kill a process and everything it started."""

    if process.poll() is not None and not IS_WINDOWS:
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, stdin=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover - a process that survives a hard kill
        pass


def register_live(process: subprocess.Popen) -> None:
    with _LIVE_LOCK:
        _LIVE.add(process)


def unregister_live(process: subprocess.Popen) -> None:
    with _LIVE_LOCK:
        _LIVE.discard(process)


def kill_all_live() -> int:
    """Kill every process this module started and that is still running."""

    with _LIVE_LOCK:
        live = [process for process in _LIVE if process.poll() is None]
    for process in live:
        kill_tree(process)
    return len(live)


def clean_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment for a child: no inherited board token or virtual environment."""

    env = dict(os.environ)
    for key in ("PRISM_BOARD_TOKEN", "PYTHONPATH", "VIRTUAL_ENV"):
        env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["NO_COLOR"] = "1"
    if extra:
        env.update(extra)
    return env


@dataclass
class ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    elapsed_s: float
    timed_out: bool


def run_captured(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdin_text: str | None = None,
    timeout: float | None = None,
) -> ProcessResult:
    """Run a command to completion. On timeout, or on Ctrl+C, the whole process tree is killed."""

    start = time.monotonic()
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=dict(env),
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **HOST_FLAGS,
    )
    with _LIVE_LOCK:
        _LIVE.add(process)
    timed_out = False
    try:
        try:
            stdout, stderr = process.communicate(input=stdin_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(process)
            stdout, stderr = process.communicate()
    except BaseException:
        kill_tree(process)
        raise
    finally:
        with _LIVE_LOCK:
            _LIVE.discard(process)
    return ProcessResult(None if timed_out else process.returncode, stdout or "", stderr or "", round(time.monotonic() - start, 1), timed_out)


def start_background(command: Sequence[str], *, cwd: Path, env: Mapping[str, str], output: Path) -> subprocess.Popen:
    """Start a long-running child (the board) with its output in a file."""

    handle = output.open("w", encoding="utf-8", newline="\n")
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            **_BOARD_FLAGS,
        )
    finally:
        handle.close()
    with _LIVE_LOCK:
        _LIVE.add(process)
    return process


def stop_background(process: subprocess.Popen, *, grace_s: float = 15.0) -> str:
    """Ask a background child to stop, then hard-kill its tree if it does not. Returns a short status."""

    if process.poll() is not None:
        with _LIVE_LOCK:
            _LIVE.discard(process)
        return f"already exited {process.returncode}"
    try:
        if IS_WINDOWS:
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGINT)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=grace_s)
        status = f"stopped on request, exit {process.returncode}"
    except subprocess.TimeoutExpired:
        kill_tree(process)
        status = f"killed after {grace_s:g} s"
    # A launcher that exits first can leave a child; the tree kill is harmless when nothing is left.
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, stdin=subprocess.DEVNULL, check=False)
    with _LIVE_LOCK:
        _LIVE.discard(process)
    return status


# --- host executables ---------------------------------------------------------


def _npm_global_dirs() -> list[Path]:
    dirs: list[Path] = []
    for name in ("claude", "codex"):
        found = shutil.which(name)
        if found:
            dirs.append(Path(found).resolve().parent)
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(Path(appdata) / "npm")
    return dirs


def find_claude() -> Path | None:
    """The Claude Code executable.

    On Windows the npm ``claude.cmd`` shim cuts multi-line prompts, so the npm package's own ``claude.exe`` is used.
    ``PRISM_E2E_CLAUDE`` overrides the search; a ``claude`` on PATH is the fallback.
    """

    override = os.environ.get("PRISM_E2E_CLAUDE")
    if override:
        return Path(override)
    for base in _npm_global_dirs():
        candidate = base / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if candidate.is_file():
            return candidate
    found = shutil.which("claude.exe") or (None if IS_WINDOWS else shutil.which("claude"))
    return Path(found) if found else None


def find_codex() -> Path | None:
    """The Codex executable: the npm package's ``codex.exe``, or ``codex`` on PATH. ``PRISM_E2E_CODEX`` overrides the search."""

    override = os.environ.get("PRISM_E2E_CODEX")
    if override:
        return Path(override)
    for base in _npm_global_dirs():
        package = base / "node_modules" / "@openai" / "codex"
        if package.is_dir():
            for candidate in sorted(package.rglob("codex.exe")):
                return candidate
    found = shutil.which("codex.exe") or (None if IS_WINDOWS else shutil.which("codex"))
    return Path(found) if found else None
