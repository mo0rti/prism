"""The browser in its own process.

Playwright's synchronous API can deadlock when Ctrl+C lands inside one of its calls. The browser
therefore runs in ``browser_worker.py``, which this module talks to over JSON lines. The worker is
tracked with every other child, so a hang, a timeout or Ctrl+C ends with its whole process tree killed.
"""

from __future__ import annotations

import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
from typing import Any

from . import config
from .browser import BrowserUnavailable
from .procs import HOST_FLAGS, clean_env, kill_tree, register_live, unregister_live

WORKER_SCRIPT = Path(__file__).with_name("browser_worker.py")
START_TIMEOUT_S = 90.0
ACTION_TIMEOUT_S = 180.0
CLOSE_TIMEOUT_S = 20.0


class BrowserClient:
    """The parent's handle on the browser worker. Same surface the runner needs from ``HumanBrowser``."""

    def __init__(self, base_url: str, human_token: str, log_path: Path) -> None:
        self._base_url = base_url
        self._token = human_token
        self._log_path = log_path
        self._process: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self.version = "unknown"

    def start(self) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self._log_path.open("w", encoding="utf-8", newline="\n")
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-B", str(WORKER_SCRIPT)],
                cwd=str(config.REPO_ROOT),
                env=clean_env({"PRISM_BOARD_TOKEN": self._token, "PRISM_E2E_BASE_URL": self._base_url}),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                encoding="utf-8",
                **HOST_FLAGS,
            )
        finally:
            log.close()
        register_live(self._process)
        threading.Thread(target=self._read_lines, daemon=True).start()
        reply = self._call({"op": "start"}, START_TIMEOUT_S)
        if not reply.get("ok"):
            self.close()
            raise BrowserUnavailable(reply.get("error", "the browser worker did not start"))
        self.version = reply.get("version", "unknown")

    def _read_lines(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _call(self, request: dict, timeout_s: float) -> dict:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return {"ok": False, "error": "the browser worker is not running"}
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        except OSError:
            return {"ok": False, "error": "the browser worker closed its input"}
        try:
            line = self._lines.get(timeout=timeout_s)
        except queue.Empty:
            kill_tree(process)
            return {"ok": False, "error": f"the browser did not answer within {timeout_s:g} s; the worker was killed"}
        if line is None:
            return {"ok": False, "error": "the browser worker exited"}
        try:
            return json.loads(line)
        except ValueError:
            return {"ok": False, "error": "the browser worker sent an unreadable reply"}

    def perform(self, action: str, feature_id: str, workspace: Path, screenshot_dir: Path) -> dict[str, Any]:
        request = {"op": "perform", "action": action, "feature_id": feature_id, "workspace": str(workspace), "screenshot_dir": str(screenshot_dir)}
        reply = self._call(request, ACTION_TIMEOUT_S)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "the browser step failed"))
        return reply["outcome"]

    def failure_screenshot(self, path: Path) -> bool:
        return bool(self._call({"op": "screenshot", "path": str(path)}, 30.0).get("ok"))

    def recover(self) -> None:
        self._call({"op": "recover"}, 30.0)

    def close(self) -> str:
        process = self._process
        if process is None:
            return "not started"
        status = "closed"
        if process.poll() is None:
            reply = self._call({"op": "close"}, CLOSE_TIMEOUT_S)
            status = reply.get("status", "closed") if reply.get("ok") else f"closed after a forced kill ({reply.get('error', 'no answer')})"
        kill_tree(process)
        unregister_live(process)
        self._process = None
        return status
