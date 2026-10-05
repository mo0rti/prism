"""Process helpers: the environment a child gets, the timeout, and the tree kill."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import procs  # noqa: E402


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class EnvTests(unittest.TestCase):
    def test_clean_env_drops_the_board_token_and_the_virtual_environment(self):
        with mock.patch.dict(os.environ, {"PRISM_BOARD_TOKEN": "x" * 30, "VIRTUAL_ENV": "v", "PYTHONPATH": "p"}):
            env = procs.clean_env({"PRISM_BOARD_TOKEN": "y" * 30})
        self.assertEqual(env["PRISM_BOARD_TOKEN"], "y" * 30)
        self.assertNotIn("VIRTUAL_ENV", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["PYTHONUTF8"], "1")

    def test_clean_env_without_an_override_has_no_board_token(self):
        with mock.patch.dict(os.environ, {"PRISM_BOARD_TOKEN": "x" * 30}):
            self.assertNotIn("PRISM_BOARD_TOKEN", procs.clean_env())


class RunTests(unittest.TestCase):
    def test_a_finished_command_returns_its_output_and_the_prompt_goes_through_stdin(self):
        script = "import sys; data = sys.stdin.read(); print(data.upper()); print('err', file=sys.stderr)"
        result = procs.run_captured([sys.executable, "-c", script], cwd=Path.cwd(), env=procs.clean_env(), stdin_text="hello", timeout=60)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "HELLO")
        self.assertEqual(result.stderr.strip(), "err")
        self.assertFalse(result.timed_out)

    def test_a_timeout_kills_the_whole_process_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "child.pid"
            child = "import time; time.sleep(120)"
            parent = (
                "import pathlib, subprocess, sys, time\n"
                f"child = subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                f"pathlib.Path({str(marker)!r}).write_text(str(child.pid))\n"
                "time.sleep(120)\n"
            )
            result = procs.run_captured([sys.executable, "-c", parent], cwd=Path(folder), env=procs.clean_env(), timeout=5)
            self.assertTrue(result.timed_out)
            self.assertIsNone(result.exit_code)
            self.assertLess(result.elapsed_s, 60)
            self.assertTrue(marker.exists(), "the parent started its child before the timeout")
            child_pid = int(marker.read_text())
            deadline = time.monotonic() + 20
            while pid_alive(child_pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(pid_alive(child_pid), "the grandchild was killed with the tree")

    def test_kill_all_live_stops_a_background_process(self):
        with tempfile.TemporaryDirectory() as folder:
            process = procs.start_background([sys.executable, "-c", "import time; time.sleep(120)"], cwd=Path(folder), env=procs.clean_env(), output=Path(folder) / "out.txt")
            self.assertIsNone(process.poll())
            self.assertEqual(procs.kill_all_live(), 1)
            self.assertIsNotNone(process.poll())

    def test_stop_background_reports_a_process_that_already_exited(self):
        with tempfile.TemporaryDirectory() as folder:
            process = procs.start_background([sys.executable, "-c", "pass"], cwd=Path(folder), env=procs.clean_env(), output=Path(folder) / "out.txt")
            process.wait(timeout=60)
            self.assertIn("already exited", procs.stop_background(process))


if __name__ == "__main__":
    unittest.main()
