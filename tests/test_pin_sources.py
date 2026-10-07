"""One pin source for CI: the repository's workflows read the toolchain versions of every pack from packs/versions.yml."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from prism_cli.packs import PACK_STACKS
from tests import real_temp  # noqa: F401
from tests.script_support import REPO_ROOT, WORKFLOWS, load_script

read_pins = load_script("read-pins.py")

# Workflows that set up a pack's toolchain: every pinned input must come from read-pins.py.
PACK_WORKFLOWS = ("template-validation.yml", "dependency-sync.yml")
# Workflows about Prism's own toolchain (the CLI, its tests and the npm launcher): they pin no pack version.
PRISM_WORKFLOWS = ("cli-validation.yml", "release.yml", "npm-release.yml")
# The toolchain inputs of the setup actions that a pack pin feeds, by action.
PINNED_INPUTS = {
    "actions/setup-java@": ("java-version",),
    "actions/setup-node@": ("node-version",),
    "astral-sh/setup-uv@": ("version", "python-version"),
    "android-actions/setup-android@": ("packages",),
}
# A run step must not spell out an Android SDK package, a build-tools version, an Xcode path or a Gradle version.
HARD_CODED_IN_RUN = (
    r"platforms;android-\d",
    r"build-tools;\d",
    r"Xcode_?\d",
    r"xcode-select\s+(-s|--switch)",
    r"gradle-\d+\.\d+",
    r"--gradle-version",
)
READ_PINS_STEP = "scripts/read-pins.py"


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def hard_coded_pins(workflow: dict) -> list[str]:
    """Findings for a workflow: each pinned setup input or run text that is not read from the pins."""

    findings: list[str] = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        steps = job.get("steps") or []
        reads_pins = any(READ_PINS_STEP in str(step.get("run", "")) for step in steps)
        for step in steps:
            uses = str(step.get("uses", ""))
            for action, inputs in PINNED_INPUTS.items():
                if not uses.startswith(action):
                    continue
                if not reads_pins:
                    findings.append(f"{job_name}: uses {action[:-1]} but never runs {READ_PINS_STEP}")
                for name in inputs:
                    value = (step.get("with") or {}).get(name)
                    if value is not None and "${{" not in str(value):
                        findings.append(f"{job_name}: {action[:-1]} {name} is the literal {value!r}")
            for pattern in HARD_CODED_IN_RUN:
                if re.search(pattern, str(step.get("run", ""))):
                    findings.append(f"{job_name}: a run step matches /{pattern}/")
    return findings


class ReadPinsTests(unittest.TestCase):
    def pins(self) -> dict[str, dict[str, str]]:
        return read_pins.load_pins()

    def test_it_reads_exactly_what_the_yaml_parser_reads_with_every_value_a_string(self) -> None:
        data = yaml.safe_load((REPO_ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))
        self.assertEqual({stack: {key: str(value) for key, value in pins.items()} for stack, pins in data.items()}, self.pins())
        self.assertEqual("21", self.pins()["spring-backend"]["java"])

    def test_it_prints_one_key_value_line_per_pin_in_the_file_order(self) -> None:
        result = subprocess.run([sys.executable, "-B", str(REPO_ROOT / "scripts" / "read-pins.py"), "nextjs-web"], capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(0, result.returncode, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual([f"{key}={value}" for key, value in self.pins()["nextjs-web"].items()], lines)

    def test_the_android_packages_are_composed_from_the_pinned_platform_and_build_tools(self) -> None:
        values = read_pins.stack_values("android-compose", self.pins())
        pins = self.pins()["android-compose"]
        self.assertEqual(f"platform-tools platforms;android-{pins['compile_sdk']} build-tools;{pins['build_tools']}", values["android_packages"])

    def test_one_value_can_be_read_alone_and_an_unknown_stack_or_key_fails(self) -> None:
        script = str(REPO_ROOT / "scripts" / "read-pins.py")
        got = subprocess.run([sys.executable, "-B", script, "python-agent-service", "--get", "uv"], capture_output=True, text=True)
        self.assertEqual(f"{self.pins()['python-agent-service']['uv']}\n", got.stdout)
        for arguments in (["no-such-stack"], ["nextjs-web", "--get", "no_such_pin"]):
            result = subprocess.run([sys.executable, "-B", script, *arguments], capture_output=True, text=True)
            self.assertEqual(2, result.returncode, arguments)

    def test_every_stack_with_a_pack_has_pins_and_a_toolchain_pin_where_a_workflow_needs_one(self) -> None:
        pins = self.pins()
        self.assertEqual(sorted(PACK_STACKS), sorted(pins))
        for stack, key in (("spring-backend", "java"), ("android-compose", "jdk"), ("nextjs-web", "node"), ("python-agent-service", "uv"), ("ios-swiftui", "xcode")):
            self.assertIn(key, pins[stack])

    def test_the_xcode_baseline_check_is_exact_and_accepts_only_the_pin_and_its_patch_releases(self) -> None:
        output = "Xcode 26.0.1\nBuild version 17A400\n"
        self.assertEqual("26.0.1", read_pins.installed_xcode(output))
        self.assertIsNone(read_pins.installed_xcode("xcode-select: error: tool 'xcodebuild' requires Xcode"))
        for installed, pinned, expected in (
            ("26.0", "26.0", True),
            ("26.0.1", "26.0", True),
            ("26", "26.0", True),
            ("26.1", "26.0", False),
            ("27.0", "26.2", False),
            ("27.0", "26.0", False),
            ("16.4", "26.0", False),
            ("26.0", "26.1", False),
            ("26.0.1", "26.1", False),
            ("26.0", "26.0.1", False),
        ):
            with self.subTest(installed=installed, pinned=pinned):
                self.assertEqual(expected, read_pins.xcode_matches(installed, pinned))

    def test_the_installed_xcode_that_matches_the_pin_is_selected_latest_patch_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            applications = Path(temporary)
            for name in ("Xcode_26.0.app", "Xcode_26.0.1.app", "Xcode_26.1.app", "Xcode_16.4.app", "Xcode.app", "Xcode_26.0_beta.app", "Safari.app"):
                (applications / name).mkdir()
            self.assertEqual(applications / "Xcode_26.0.1.app" / "Contents" / "Developer", read_pins.find_xcode("26.0", applications))
            self.assertEqual(applications / "Xcode_26.1.app" / "Contents" / "Developer", read_pins.find_xcode("26.1", applications))
            self.assertIsNone(read_pins.find_xcode("27.0", applications))
            self.assertIsNone(read_pins.find_xcode("26.0", applications / "missing"))

class WorkflowPinTests(unittest.TestCase):
    def test_every_workflow_is_classified_so_a_new_one_cannot_skip_the_pin_rule(self) -> None:
        names = sorted(path.name for path in WORKFLOWS.glob("*.yml"))
        self.assertEqual(sorted(PACK_WORKFLOWS + PRISM_WORKFLOWS), names, "classify the new workflow in PACK_WORKFLOWS or PRISM_WORKFLOWS")

    def test_no_pack_workflow_hard_codes_a_pinned_version(self) -> None:
        for name in PACK_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertEqual([], hard_coded_pins(load_workflow(name)))

    def test_the_rule_flags_every_kind_of_hard_coded_toolchain_version(self) -> None:
        workflow = yaml.safe_load(
            """
jobs:
  literal:
    steps:
      - uses: actions/setup-java@v4
        with: {java-version: "21"}
      - uses: actions/setup-node@v4
        with: {node-version: "22"}
      - uses: astral-sh/setup-uv@v6
        with: {version: "0.11.26", python-version: "3.12"}
      - uses: android-actions/setup-android@v3
        with: {packages: "platforms;android-36 build-tools;35.0.0"}
      - run: sdkmanager "platforms;android-36"
      - run: sudo xcode-select -s /Applications/Xcode_26.0.app
      - run: ./gradlew wrapper --gradle-version 8.14.3
  read:
    steps:
      - run: python scripts/read-pins.py spring-backend >> "$GITHUB_OUTPUT"
        id: pins
      - uses: actions/setup-java@v4
        with: {java-version: "${{ steps.pins.outputs.java }}"}
  unread:
    steps:
      - uses: actions/setup-java@v4
        with: {java-version: "${{ steps.other.outputs.java }}"}
"""
        )
        findings = hard_coded_pins(workflow)
        self.assertEqual(
            [
                "literal: uses actions/setup-java but never runs scripts/read-pins.py",
                "literal: actions/setup-java java-version is the literal '21'",
                "literal: uses actions/setup-node but never runs scripts/read-pins.py",
                "literal: actions/setup-node node-version is the literal '22'",
                "literal: uses astral-sh/setup-uv but never runs scripts/read-pins.py",
                "literal: astral-sh/setup-uv version is the literal '0.11.26'",
                "literal: astral-sh/setup-uv python-version is the literal '3.12'",
                "literal: uses android-actions/setup-android but never runs scripts/read-pins.py",
                "literal: android-actions/setup-android packages is the literal 'platforms;android-36 build-tools;35.0.0'",
                "literal: a run step matches /platforms;android-\\d/",
                "literal: a run step matches /Xcode_?\\d/",
                "literal: a run step matches /xcode-select\\s+(-s|--switch)/",
                "literal: a run step matches /--gradle-version/",
                "unread: uses actions/setup-java but never runs scripts/read-pins.py",
            ],
            findings,
        )

    def test_each_toolchain_comes_from_the_stack_that_the_job_builds(self) -> None:
        """A job reads the pins of the stack it sets up, so the Java of the backend is not the JDK of Android by accident."""

        workflow = load_workflow("template-validation.yml")
        expected = {
            "backend-smoke": "spring-backend",
            "web-smoke": "nextjs-web",
            "agent-service": "python-agent-service",
            "android-build": "android-compose",
            "ios-build": "ios-swiftui",
        }
        for job_name, stack in expected.items():
            with self.subTest(job=job_name):
                text = "\n".join(str(step.get("run", "")) for step in workflow["jobs"][job_name]["steps"])
                self.assertIn(f"{READ_PINS_STEP} {stack}", text)
        self.assertIn("--check-xcode", "\n".join(str(step.get("run", "")) for step in workflow["jobs"]["ios-build"]["steps"]))

    def test_the_android_job_sets_up_the_sdk_from_the_composed_packages_output(self) -> None:
        steps = load_workflow("template-validation.yml")["jobs"]["android-build"]["steps"]
        sdk = next(step for step in steps if str(step.get("uses", "")).startswith("android-actions/setup-android@"))
        self.assertEqual("${{ steps.pins.outputs.android_packages }}", sdk["with"]["packages"])
        java = next(step for step in steps if str(step.get("uses", "")).startswith("actions/setup-java@"))
        self.assertEqual("${{ steps.pins.outputs.jdk }}", java["with"]["java-version"])

    def test_the_pins_are_read_after_prism_is_installed_so_pyyaml_is_there(self) -> None:
        """A fresh runner's Python has no PyYAML; Prism's install brings it."""

        for name in PACK_WORKFLOWS:
            workflow = load_workflow(name)
            for job_name, job in workflow["jobs"].items():
                runs = [str(step.get("run", "")) for step in job.get("steps", [])]
                read = [index for index, run in enumerate(runs) if READ_PINS_STEP in run and "read-pins.py" in run]
                if not read:
                    continue
                install = [index for index, run in enumerate(runs) if "pip install" in run and ("." in run)]
                self.assertTrue(install and min(install) < min(read), f"{name}:{job_name} reads the pins before it installs Prism")


if __name__ == "__main__":
    unittest.main()
