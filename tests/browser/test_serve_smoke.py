"""Smoke test: the real ``prism board serve`` process serves the board to a real browser."""

from __future__ import annotations

import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from tests.browser.board_page import expect
from tests.browser.harness import BrowserCase, build_workspace, e2e_directory, free_port, requires_browser_e2e

REPOSITORY = Path(__file__).resolve().parents[2]
START_TIMEOUT_SECONDS = 60
STOP_TIMEOUT_SECONDS = 30


@requires_browser_e2e
class ServeCommandSmokeTests(BrowserCase):
    serve_in_process = False

    def test_board_serve_subprocess_loads_in_a_browser_and_stops_cleanly(self) -> None:
        with self.scenario("S-board-serve-smoke") as run:
            work = e2e_directory() / "work"
            work.mkdir(parents=True, exist_ok=True)
            parent = Path(tempfile.mkdtemp(prefix="serve-", dir=work))
            self.addCleanup(shutil.rmtree, parent, True)
            root = build_workspace(parent / "document-review")
            port = free_port()

            options: dict = {}
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", "prism_cli", "board", "serve", str(root), "--port", str(port), "--no-open"],
                cwd=REPOSITORY,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **options,
            )
            self.addCleanup(lambda: process.poll() is None and process.kill())
            lines: "queue.Queue[str]" = queue.Queue()
            output: list[str] = []

            def drain() -> None:
                for line in process.stdout:
                    output.append(line)
                    lines.put(line)

            reader = threading.Thread(target=drain, name="prism-serve-output", daemon=True)
            reader.start()

            url = None
            deadline = time.monotonic() + START_TIMEOUT_SECONDS
            while url is None:
                try:
                    line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    self.fail("`prism board serve` printed no URL: " + "".join(output)[-500:])
                match = re.search(r"Prism board: (http://127\.0\.0\.1:\d+/)", line)
                url = match.group(1) if match else None
            self.assertEqual(f"http://127.0.0.1:{port}/", url)

            while True:  # Poll until the listener answers; the URL is printed before startup completes.
                try:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        self.assertEqual(200, response.status)
                    break
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    self.assertIsNone(process.poll(), "`prism board serve` exited early: " + "".join(output)[-500:])
                    self.assertLess(time.monotonic(), deadline, "The board never answered.")
                    time.sleep(0.1)

            self.start_trace()
            self.page.goto(url)
            expect(self.page.get_by_role("heading", name="Connect to your Prism board")).to_be_visible()
            expect(self.page.get_by_label("Participant token")).to_be_visible()
            run.effect("`prism board serve --no-open` served the sign-in page to a clean Chromium")

            # Stop it the way a terminal would. POSIX gets SIGINT (Ctrl+C). A Windows
            # child in its own process group cannot receive Ctrl+C, so it gets a
            # console break; uvicorn shuts down gracefully on it and then re-raises
            # the signal, which ends the process with the console-break status 3.
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            try:
                code = process.wait(timeout=STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                self.fail("`prism board serve` did not stop after an interrupt: " + "".join(output)[-500:])
            reader.join(timeout=5)
            process.stdout.close()
            transcript = "".join(output)
            self.assertIn(code, (0, 3) if os.name == "nt" else (0,), transcript[-500:])
            self.assertNotIn("Traceback", transcript)
            with self.assertRaises((urllib.error.URLError, ConnectionError, TimeoutError)):
                urllib.request.urlopen(url, timeout=2)
            # The serving lock was released: a new service can take it again.
            from prism_cli.board_service import BoardService

            with BoardService(root) as service:
                service.start()
            run.effect("the serve process stopped on an interrupt, stopped listening and released the workspace lock")

if __name__ == "__main__":
    unittest.main()
