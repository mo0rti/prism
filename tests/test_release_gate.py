"""A broken slice blocks the release, and the golden workflows run in repository CI."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from tests import real_temp  # noqa: F401
from tests.script_support import REPO_ROOT, WORKFLOWS, load_script

check_ci = load_script("check-ci-green.py")
run_golden = load_script("run-golden-workflow.py")

GATED_WORKFLOWS = ["template-validation.yml", "cli-validation.yml"]


def run(status: str, conclusion: str, created: str, url: str = "https://example.test/run") -> dict:
    return {"status": status, "conclusion": conclusion, "createdAt": created, "url": url, "event": "push"}


class EvaluateTests(unittest.TestCase):
    def test_a_successful_newest_run_passes_and_no_run_is_missing(self) -> None:
        self.assertEqual("ok", check_ci.evaluate([run("completed", "success", "2026-10-07T10:00:00Z")])[0])
        self.assertEqual("missing", check_ci.evaluate([])[0])

    def test_the_newest_run_decides_so_a_rerun_that_passed_replaces_a_failure(self) -> None:
        failed_then_passed = [run("completed", "failure", "2026-10-07T09:00:00Z"), run("completed", "success", "2026-10-07T10:00:00Z")]
        passed_then_failed = [run("completed", "success", "2026-10-07T09:00:00Z"), run("completed", "failure", "2026-10-07T10:00:00Z")]
        self.assertEqual("ok", check_ci.evaluate(failed_then_passed)[0])
        self.assertEqual("failed", check_ci.evaluate(passed_then_failed)[0])

    def test_a_cancelled_or_timed_out_run_is_not_green_and_a_running_one_is_pending(self) -> None:
        for conclusion in ("cancelled", "timed_out", "failure", "skipped", ""):
            self.assertEqual("failed", check_ci.evaluate([run("completed", conclusion, "2026-10-07T10:00:00Z")])[0], conclusion)
        for status in ("queued", "in_progress", "waiting"):
            self.assertEqual("pending", check_ci.evaluate([run(status, "", "2026-10-07T10:00:00Z")])[0], status)


class CheckLoopTests(unittest.TestCase):
    def check(self, outcomes: dict[str, list[list[dict]]], wait_minutes: float = 10.0) -> tuple[int, list[str]]:
        """Runs the check with scripted answers per workflow (each call pops the next) and a clock that advances by the sleeps."""

        calls: dict[str, int] = {}
        slept: list[str] = []
        now = [0.0]

        def fetch(workflow: str, commit: str, repository: str | None) -> list[dict]:
            index = calls.get(workflow, 0)
            calls[workflow] = index + 1
            answers = outcomes[workflow]
            return answers[min(index, len(answers) - 1)]

        def sleep(seconds: float) -> None:
            slept.append(f"{seconds:g}")
            now[0] += seconds

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = check_ci.check(list(outcomes), "abc123", None, wait_minutes, fetch=fetch, sleep=sleep, interval_seconds=60, clock=lambda: now[0])
        return code, slept

    def test_green_workflows_pass_without_waiting(self) -> None:
        green = [run("completed", "success", "2026-10-07T10:00:00Z")]
        code, slept = self.check({"template-validation.yml": [green], "cli-validation.yml": [green]})
        self.assertEqual((0, []), (code, slept))

    def test_one_broken_workflow_fails_the_release_even_when_the_other_is_green(self) -> None:
        green = [run("completed", "success", "2026-10-07T10:00:00Z")]
        broken = [run("completed", "failure", "2026-10-07T10:00:00Z")]
        self.assertEqual(1, self.check({"template-validation.yml": [broken], "cli-validation.yml": [green]})[0])
        self.assertEqual(1, self.check({"template-validation.yml": [green], "cli-validation.yml": [broken]})[0])

    def test_a_missing_run_fails_it_too(self) -> None:
        green = [run("completed", "success", "2026-10-07T10:00:00Z")]
        self.assertEqual(1, self.check({"template-validation.yml": [[]], "cli-validation.yml": [green]})[0])

    def test_a_run_that_is_still_going_is_awaited_and_judged_when_it_finishes(self) -> None:
        going = [run("in_progress", "", "2026-10-07T10:00:00Z")]
        done = [run("completed", "success", "2026-10-07T10:00:00Z")]
        code, slept = self.check({"template-validation.yml": [going, going, done]})
        self.assertEqual((0, ["60", "60"]), (code, slept))
        failed = [run("completed", "failure", "2026-10-07T10:00:00Z")]
        self.assertEqual(1, self.check({"template-validation.yml": [going, failed]})[0])

    def test_a_run_that_never_finishes_fails_after_the_wait(self) -> None:
        going = [run("in_progress", "", "2026-10-07T10:00:00Z")]
        code, slept = self.check({"template-validation.yml": [going]}, wait_minutes=3)
        self.assertEqual(1, code)
        self.assertEqual(3, len(slept))


class ReleaseWorkflowTests(unittest.TestCase):
    def workflow(self) -> dict:
        return yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))

    def test_the_first_job_requires_green_ci_for_the_tagged_commit_of_both_validation_workflows(self) -> None:
        job = self.workflow()["jobs"]["verify-tag"]
        step = next(step for step in job["steps"] if "check-ci-green.py" in str(step.get("run", "")))
        text = step["run"]
        for name in GATED_WORKFLOWS:
            self.assertIn(f"--workflow {name}", text)
        self.assertIn('--commit "$(git rev-parse HEAD)"', text)
        self.assertEqual("${{ github.token }}", step["env"]["GH_TOKEN"])
        self.assertEqual("read", job["permissions"]["actions"])
        # The gate reads the checkout of the tag, so it judges the commit that is released.
        checkout = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@"))
        self.assertEqual("${{ inputs.tag || github.ref }}", checkout["with"]["ref"])

    def test_every_other_job_needs_the_first_one_directly_or_through_another(self) -> None:
        jobs = self.workflow()["jobs"]

        def needs(name: str) -> set[str]:
            direct = jobs[name].get("needs", [])
            direct = [direct] if isinstance(direct, str) else direct
            closure = set(direct)
            for parent in direct:
                closure |= needs(parent)
            return closure

        for name in jobs:
            if name != "verify-tag":
                with self.subTest(job=name):
                    self.assertIn("verify-tag", needs(name))

    def test_the_gated_workflows_are_the_ones_that_build_the_golden_apps_and_run_the_golden_check(self) -> None:
        template = (WORKFLOWS / "template-validation.yml").read_text(encoding="utf-8")
        for app in ("backend", "web", "mobile-android", "mobile-ios", "agent-service"):
            self.assertIn(f"python scripts/run-golden-workflow.py {app}", template, f"golden {app} runs in CI")
        self.assertIn("python scripts/build-golden.py --check", template)
        cli = (WORKFLOWS / "cli-validation.yml").read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover -s tests", cli)

    def test_the_golden_workflows_are_not_skipped_by_the_path_filters_of_the_files_that_change_them(self) -> None:
        template = yaml.safe_load((WORKFLOWS / "template-validation.yml").read_text(encoding="utf-8"))[True]
        for event in ("push", "pull_request"):
            paths = template[event]["paths"]
            for needed in ("golden/**", "packs/**", "scripts/build-golden.py", "scripts/golden-answers.yml", "scripts/read-pins.py", "scripts/run-golden-workflow.py", "scripts/audit-gate.py"):
                self.assertIn(needed, paths, f"{event} of template-validation.yml")


def bash_available() -> bool:
    try:
        run_golden.find_bash()
    except SystemExit:
        return False
    return True


WORKFLOW_TEXT = """
name: Demo CI
on: {push: {branches: [main]}}
jobs:
  verify:
    runs-on: ubuntu-latest
    env: {FROM_JOB: job}
    defaults:
      run:
        working-directory: app
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: "22"}
      - name: Write a marker and export a variable
        run: |
          echo "ran in $(basename "$PWD")" > ../marker.txt
          echo "EXPORTED=$FROM_JOB-and-step" >> "$GITHUB_ENV"
        env: {FROM_JOB: overridden}
      - name: Read the exported variable
        run: echo "$EXPORTED" > ../exported.txt
      - name: Fail
        run: exit 3
      - name: Skipped after the failure
        run: echo should-not-run > ../after.txt
      - name: Runs after a failure
        if: always()
        run: echo cleanup > ../always.txt
      - uses: actions/upload-artifact@v4
        if: always()
        with: {name: x, path: y}
"""


@unittest.skipUnless(bash_available(), "bash is needed to run workflow steps")
class RunGoldenWorkflowTests(unittest.TestCase):
    def workspace(self, workflow_text: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="prism-run-golden-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / "app").mkdir()
        (root / ".github" / "workflows" / "demo.yml").write_text(workflow_text, encoding="utf-8")
        return root

    def run_script(self, root: Path, *arguments: str) -> subprocess.CompletedProcess:
        env = {key: value for key, value in os.environ.items() if key not in ("GITHUB_ENV", "GITHUB_PATH")}
        return subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "run-golden-workflow.py"), "demo", "--workspace", str(root), *arguments],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def test_steps_run_in_order_in_their_directory_with_the_env_and_a_failure_stops_the_rest(self) -> None:
        root = self.workspace(WORKFLOW_TEXT)
        result = self.run_script(root)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("ran in app", (root / "marker.txt").read_text(encoding="utf-8").strip())
        self.assertEqual("overridden-and-step", (root / "exported.txt").read_text(encoding="utf-8").strip(), "GITHUB_ENV and the step env apply to later steps")
        self.assertFalse((root / "after.txt").exists(), "a step after the failure does not run")
        self.assertEqual("cleanup", (root / "always.txt").read_text(encoding="utf-8").strip(), "if: always() still runs")
        self.assertIn("skipped, set up by the repository job: actions/setup-node@v4", result.stdout)

    def test_a_workflow_whose_steps_pass_exits_zero(self) -> None:
        root = self.workspace(WORKFLOW_TEXT.replace("run: exit 3", "run: echo fine"))
        result = self.run_script(root)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("should-not-run", (root / "after.txt").read_text(encoding="utf-8").strip())

    def test_an_action_the_repository_job_does_not_set_up_is_an_error(self) -> None:
        root = self.workspace(WORKFLOW_TEXT.replace("actions/setup-node@v4", "some/new-action@v1"))
        result = self.run_script(root, "--dry-run")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("some/new-action@v1", result.stdout + result.stderr)

    def test_an_expression_or_an_unknown_condition_is_an_error_not_a_silent_skip(self) -> None:
        for text in (
            WORKFLOW_TEXT.replace('echo "$EXPORTED" > ../exported.txt', 'echo "${{ github.sha }}" > ../exported.txt'),
            WORKFLOW_TEXT.replace("if: always()\n        run: echo cleanup", "if: github.ref == 'refs/heads/main'\n        run: echo cleanup"),
        ):
            result = self.run_script(self.workspace(text), "--dry-run")
            self.assertNotEqual(0, result.returncode, result.stdout)

    def test_every_golden_workflow_is_runnable_by_the_script(self) -> None:
        """A pack workflow that gains an unsupported action, expression or condition fails here, not in CI."""

        golden = REPO_ROOT / "golden"
        for workflow in sorted((golden / ".github" / "workflows").glob("*.yml")):
            if workflow.stem == "api-contracts":
                continue  # the workspace's own contract workflow, not an app's
            with self.subTest(app=workflow.stem):
                result = subprocess.run(
                    [sys.executable, "-B", str(REPO_ROOT / "scripts" / "run-golden-workflow.py"), workflow.stem, "--dry-run"],
                    capture_output=True,
                    text=True,
                    cwd=REPO_ROOT,
                    timeout=120,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
