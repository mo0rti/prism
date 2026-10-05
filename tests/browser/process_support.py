"""Run a real ``prism`` server process for a browser scenario and stop it like a terminal would."""

from __future__ import annotations

import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

REPOSITORY = Path(__file__).resolve().parents[2]
START_TIMEOUT_SECONDS = 60

# Opening the system browser is the one thing a scenario must not do, so the
# graph server's launcher is replaced for this process only. Everything else
# (argument parsing, the command, the server) is the product's own code.
GRAPH_COMMAND_WITHOUT_BROWSER = (
    "import sys, webbrowser; webbrowser.open = lambda *args, **kwargs: True; "
    "from prism_cli.cli import main; sys.exit(main(sys.argv[1:]))"
)


class ServedProcess:
    def __init__(self, arguments: list[str], url_pattern: str) -> None:
        self._arguments = arguments
        self._url_pattern = re.compile(url_pattern)
        self._process: subprocess.Popen[str] | None = None
        self._lines: "queue.Queue[str]" = queue.Queue()
        self.output: list[str] = []
        self.url = ""

    def start(self) -> str:
        options: dict = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self._process = subprocess.Popen(
            [sys.executable, "-B", *self._arguments],
            cwd=REPOSITORY,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            **options,
        )

        def drain() -> None:
            assert self._process is not None and self._process.stdout is not None
            for line in self._process.stdout:
                self.output.append(line)
                self._lines.put(line)

        threading.Thread(target=drain, name="prism-browser-e2e-output", daemon=True).start()
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while not self.url:
            try:
                line = self._lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                raise AssertionError("The server printed no URL: " + "".join(self.output)[-500:]) from None
            match = self._url_pattern.search(line)
            if match:
                self.url = match.group(1)
        while True:  # The URL is printed before the listener answers.
            try:
                with urllib.request.urlopen(self.url, timeout=5):
                    return self.url
            except urllib.error.HTTPError:
                return self.url  # It answered; a status code is an answer.
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if self._process.poll() is not None:
                    raise AssertionError("The server exited early: " + "".join(self.output)[-500:]) from None
                if time.monotonic() > deadline:
                    raise AssertionError("The server never answered.") from None
                time.sleep(0.1)

    def stop(self, timeout: float) -> int | None:
        """Interrupt it as a terminal does; return its exit code, or None if it did not stop within ``timeout``."""

        process = self._process
        if process is None or process.poll() is not None:
            return None if process is None else process.returncode
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def kill(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if process is not None and process.stdout is not None:
            try:
                process.stdout.close()
            except OSError:
                pass

    @property
    def transcript(self) -> str:
        return "".join(self.output)
