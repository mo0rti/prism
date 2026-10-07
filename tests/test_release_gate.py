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
        # A manual run names a tag: the full ref makes the checkout fail for a branch of that name.
        self.assertEqual("${{ inputs.tag && format('refs/tags/{0}', inputs.tag) || github.ref }}", checkout["with"]["ref"])

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



def checkouts(job: dict) -> list[dict]:
    return [step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")]


class ReleaseIsBoundToOneCommitTests(unittest.TestCase):
    """The tag is a tag, its commit is resolved once, and every later job uses that commit."""

    def workflow(self) -> dict:
        return yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))

    def test_a_manual_run_checks_out_the_full_tag_ref_so_a_branch_of_that_name_fails(self) -> None:
        job = self.workflow()["jobs"]["verify-tag"]
        ref = checkouts(job)[0]["with"]["ref"]
        self.assertIn("format('refs/tags/{0}', inputs.tag)", ref)
        check = next(step for step in job["steps"] if step.get("id") == "check")
        self.assertIn('git rev-parse --verify --quiet "refs/tags/${TAG}^{commit}"', check["run"])
        self.assertIn("refs/tags/$TAG does not exist", check["run"])
        self.assertIn('echo "sha=${sha}" >> "$GITHUB_OUTPUT"', check["run"])
        self.assertEqual("${{ steps.check.outputs.sha }}", job["outputs"]["sha"])

    def test_every_later_checkout_uses_the_verified_sha_and_never_the_tag_again(self) -> None:
        jobs = self.workflow()["jobs"]
        later = [(name, step) for name, job in jobs.items() if name != "verify-tag" for step in checkouts(job)]
        self.assertTrue(later, "the build and the release check out the repository")
        for name, step in later:
            with self.subTest(job=name):
                self.assertEqual("${{ needs.verify-tag.outputs.sha }}", step["with"]["ref"])
                self.assertIn("verify-tag", jobs[name]["needs"])

    def test_the_release_is_refused_when_the_tag_moved_after_the_verification(self) -> None:
        job = self.workflow()["jobs"]["github-release"]
        step = next(step for step in job["steps"] if "no longer names the verified commit" in str(step.get("run", "")))
        self.assertEqual("${{ needs.verify-tag.outputs.sha }}", step["env"]["SHA"])
        self.assertIn('git ls-remote origin "refs/tags/${TAG}" "refs/tags/${TAG}^{}"', step["run"])
        names = [str(item.get("name", "")) for item in job["steps"]]
        self.assertLess(names.index(step["name"]), names.index("Create the release"))

    def test_the_npm_release_requires_the_tag_ref_too(self) -> None:
        job = yaml.safe_load((WORKFLOWS / "npm-release.yml").read_text(encoding="utf-8"))["jobs"]["publish-npm"]
        ref = checkouts(job)[0]["with"]["ref"]
        self.assertIn("github.event.workflow_run.head_sha", ref)
        self.assertIn("format('refs/tags/{0}', inputs.tag)", ref)
        self.assertNotIn("|| inputs.tag }}", ref)
        check = next(step for step in job["steps"] if step.get("id") == "check")
        self.assertIn('git rev-parse --verify --quiet "refs/tags/${TAG}^{commit}"', check["run"])
        self.assertIn('"$(git rev-parse "refs/tags/${TAG}^{commit}")" != "$(git rev-parse HEAD)"', check["run"])


class ReleasePublishesWhatWasBuiltTests(unittest.TestCase):
    """The smoke test runs the wheel this run built, and the registry copy must be byte-identical to it."""

    def workflow(self) -> dict:
        return yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))

    def needs(self, name: str, jobs: dict) -> set[str]:
        direct = jobs[name].get("needs", [])
        direct = [direct] if isinstance(direct, str) else direct
        closure = set(direct)
        for parent in direct:
            closure |= self.needs(parent, jobs)
        return closure

    def test_the_built_wheel_is_smoke_tested_before_any_publication_in_both_paths(self) -> None:
        jobs = self.workflow()["jobs"]
        install = next(step for step in jobs["smoke-wheel"]["steps"] if step.get("name") == "Install the built wheel")
        self.assertIn('"dist/prism_kit-${VERSION}-py3-none-any.whl"', install["run"])
        self.assertNotIn("index", install["run"], "the built file is installed, not a version from an index")
        for publisher in ("publish-testpypi", "publish-pypi"):
            with self.subTest(job=publisher):
                self.assertIn("smoke-wheel", self.needs(publisher, jobs))

    def test_the_registry_check_downloads_the_package_from_one_index_and_compares_its_hash(self) -> None:
        jobs = self.workflow()["jobs"]
        for job_name, index in (("smoke-test", "https://test.pypi.org/simple/"), ("pypi-smoke-test", "https://pypi.org/simple/")):
            with self.subTest(job=job_name):
                steps = {step["name"]: str(step.get("run", "")) for step in jobs[job_name]["steps"] if "name" in step}
                download = next(text for name, text in steps.items() if name.startswith("Download the published wheel"))
                self.assertIn(f"--index-url {index}", download)
                self.assertIn("--no-deps", download)
                self.assertIn("--only-binary=:all:", download)
                compare = steps["Require the published wheel to equal the built wheel"]
                self.assertIn('sha256sum "dist/${wheel}"', compare)
                self.assertIn('test "$built" = "$published"', compare)
                install = steps["Install the published wheel and its dependencies"]
                self.assertIn("registry/prism_kit-${VERSION}-py3-none-any.whl", install)
                self.assertNotIn('"prism-kit==', install, "the package is the verified file, never a version looked up in an index")
        self.assertNotIn("--extra-index-url", (WORKFLOWS / "release.yml").read_text(encoding="utf-8"))

    def test_pypi_publication_waits_for_the_registry_check_unless_testpypi_is_skipped(self) -> None:
        condition = self.workflow()["jobs"]["publish-pypi"]["if"]
        self.assertIn("needs.smoke-wheel.result == 'success'", condition)
        self.assertIn("needs.smoke-test.result == 'success'", condition)
        self.assertIn("inputs.skip_testpypi && needs.smoke-test.result == 'skipped'", condition)


def inline_python(step: dict) -> str:
    """The Python program a workflow step feeds to `python - <<'PY'`."""

    lines = str(step["run"]).splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip().startswith("python - <<'PY'")) + 1
    end = next(index for index in range(start, len(lines)) if lines[index].strip() == "PY")
    return "\n".join(lines[start:end]) + "\n"


class DependencySyncSplitTests(unittest.TestCase):
    """The tooling that nobody reviewed runs without a write token; the job with the token runs none of it."""

    def workflow(self) -> dict:
        return yaml.safe_load((WORKFLOWS / "dependency-sync.yml").read_text(encoding="utf-8"))

    def test_the_regenerating_job_has_a_read_only_token_that_is_not_persisted_and_no_secret(self) -> None:
        workflow = self.workflow()
        self.assertEqual({"contents": "read"}, workflow["permissions"])
        job = workflow["jobs"]["regenerate"]
        self.assertEqual({"contents": "read"}, job["permissions"])
        checkout = checkouts(job)[0]
        self.assertIs(False, checkout["with"]["persist-credentials"])
        self.assertEqual("${{ github.event.pull_request.head.sha }}", checkout["with"]["ref"], "the input is pinned to a SHA")
        self.assertNotIn("token", checkout["with"])
        self.assertNotIn("secrets.", yaml.safe_dump(job), "no secret reaches the job that runs the tools")

    def test_only_the_pushing_job_has_write_permissions_and_it_needs_the_regenerating_one(self) -> None:
        workflow = self.workflow()
        job = workflow["jobs"]["push"]
        self.assertEqual("regenerate", job["needs"])
        self.assertEqual({"contents": "write", "actions": "write"}, job["permissions"])
        runs = "\n".join(str(step.get("run", "")) for step in job["steps"])
        for tool in ("sync-golden", "scripts/", "uv ", "npm ", "pip ", "npx "):
            self.assertNotIn(tool, runs.replace("python - <<'PY'", ""), f"the job with the write token does not run `{tool}`")
        uses = [str(step.get("uses", "")) for step in job["steps"]]
        self.assertFalse(any(item.startswith(("astral-sh/setup-uv", "actions/setup-node")) for item in uses))

    def test_the_patch_is_validated_before_it_is_applied(self) -> None:
        job = self.workflow()["jobs"]["push"]
        names = [step.get("name", "") for step in job["steps"]]
        validate = names.index("Check that the patch touches only the lockfiles, the pins and golden/")
        self.assertLess(validate, names.index("Commit and push what changed"))
        push = next(step for step in job["steps"] if step.get("name") == "Commit and push what changed")
        self.assertIn("steps.validate.outputs.apply == 'true'", push["if"])

    def validate(self, patch_text: str, *, recorded: str = "a" * 40, input_sha: str = "a" * 40) -> subprocess.CompletedProcess:
        job = self.workflow()["jobs"]["push"]
        program = inline_python(next(step for step in job["steps"] if step.get("id") == "validate"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "regenerated").mkdir()
            (root / "regenerated" / "regenerated.patch").write_bytes(patch_text.encode("utf-8"))
            (root / "regenerated" / "input-sha.txt").write_text(recorded, encoding="utf-8")
            output = root / "github-output"
            output.write_text("", encoding="utf-8")
            env = {**os.environ, "RUNNER_TEMP": str(root), "INPUT_SHA": input_sha, "GITHUB_OUTPUT": str(output)}
            result = subprocess.run([sys.executable, "-B", "-c", program], capture_output=True, text=True, env=env, cwd=root, timeout=60)
            result.applied = "apply=true" in output.read_text(encoding="utf-8")  # type: ignore[attr-defined]
            return result

    def make_patch(self, files: dict[str, str | None]) -> str:
        """A `git diff --cached --binary` of new files, the way the regenerating job writes it."""

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "base"], cwd=repo, check=True)
            for relative, content in files.items():
                target = repo / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content or "", encoding="utf-8", newline="\n")
                subprocess.run(["git", "-c", "core.autocrlf=false", "add", "-f", relative], cwd=repo, check=True)
            return subprocess.run(["git", "-c", "core.autocrlf=false", "diff", "--cached", "--binary"], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8").stdout

    @unittest.skipUnless(shutil.which("git"), "git is needed to build patches")
    def test_a_patch_of_lockfiles_pins_and_golden_is_accepted(self) -> None:
        patch = self.make_patch(
            {
                "packs/versions.yml": "x: 1\n",
                "packs/nextjs-web/{{ app_path }}/package-lock.json.jinja": "{}\n",
                "packs/python-agent-service/{{ app_path }}/uv.lock.jinja": "x\n",
                "golden/web/package.json": "{}\n",
                "golden/backend/gradlew": "#!/bin/sh\n",
            }
        )
        result = self.validate(patch)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(result.applied)  # type: ignore[attr-defined]

    @unittest.skipUnless(shutil.which("git"), "git is needed to build patches")
    def test_a_patch_that_touches_anything_else_is_refused(self) -> None:
        for label, files in {
            "a workflow": {".github/workflows/release.yml": "name: x\n"},
            "a script": {"scripts/sync-golden.py": "print()\n"},
            "the CLI": {"prism_cli/cli.py": "x = 1\n"},
            "another pack file": {"packs/spring-backend/{{ app_path }}/build.gradle.kts.jinja": "x\n"},
            "a lockfile of another stack": {"packs/android-compose/{{ app_path }}/uv.lock.jinja": "x\n"},
            "a path that only starts like golden": {"golden-extra/x": "x\n"},
            "a good file next to a bad one": {"golden/web/package.json": "{}\n", ".github/workflows/x.yml": "x\n"},
        }.items():
            with self.subTest(label):
                result = self.validate(self.make_patch(files))
                self.assertNotEqual(0, result.returncode, result.stdout)
                self.assertFalse(result.applied)  # type: ignore[attr-defined]

    @unittest.skipUnless(shutil.which("git"), "git is needed to build patches")
    def test_a_symlink_or_a_patch_made_against_another_commit_is_refused(self) -> None:
        patch = self.make_patch({"golden/web/link": "../../outside"})
        symlink = patch.replace("new file mode 100644", "new file mode 120000", 1)
        self.assertNotEqual(0, self.validate(symlink).returncode)
        self.assertNotEqual(0, self.validate(self.make_patch({"golden/web/a": "x\n"}), recorded="b" * 40).returncode)

    def test_an_empty_patch_applies_nothing(self) -> None:
        result = self.validate("")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(result.applied)  # type: ignore[attr-defined]


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
