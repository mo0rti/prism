"""Automated dependency updates: the bot configuration, the sync that follows an update, and the security-advisory gate."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

from prism_cli.packs import PACK_STACKS
from tests import real_temp  # noqa: F401
from tests.script_support import REPO_ROOT, WORKFLOWS, load_script

audit_gate = load_script("audit-gate.py")
sync_golden = load_script("sync-golden.py")

VERSIONS = REPO_ROOT / "packs" / "versions.yml"
# Pins that move by hand with a release: a toolchain version, a platform level or the database image.
BASELINE_PINS = {
    "spring-backend": {"java", "postgres"},
    "nextjs-web": {"node"},
    "android-compose": {"jdk", "build_tools", "min_sdk", "target_sdk", "compile_sdk"},
    "ios-swiftui": {"xcode", "swift", "ios_deployment_target", "fastlane"},
    "python-agent-service": {"python"},
}
DATASOURCES = {"maven", "gradle-version", "npm", "pypi"}
ANNOTATION = re.compile(
    r"^  # renovate: datasource=(?P<datasource>[a-z-]+) depName=(?P<depName>\S+)(?: registryUrl=(?P<registryUrl>\S+))? depType=(?P<depType>\S+)\n  (?P<key>[a-z_]+): \"(?P<value>[^\"]+)\"$",
    re.MULTILINE,
)


def renovate_config() -> dict:
    return json.loads((REPO_ROOT / "renovate.json").read_text(encoding="utf-8"))


def annotated_pins() -> dict[str, dict[str, dict[str, str]]]:
    """The pins that carry a ``# renovate:`` line: stack, then key, then the annotation's fields and the pin."""

    found: dict[str, dict[str, dict[str, str]]] = {}
    for match in ANNOTATION.finditer(VERSIONS.read_text(encoding="utf-8")):
        fields = match.groupdict()
        found.setdefault(fields["depType"], {})[fields["key"]] = fields
    return found


class RenovateConfigurationTests(unittest.TestCase):
    def test_the_configuration_is_valid_json_and_reads_only_the_pin_file(self) -> None:
        config = renovate_config()
        self.assertEqual(["custom.regex"], config["enabledManagers"])
        manager = config["customManagers"][0]
        self.assertEqual("regex", manager["customType"])
        self.assertEqual(["/^packs/versions\\.yml$/"], manager["managerFilePatterns"])

    def test_the_golden_workspace_is_never_updated_directly_because_it_is_regenerated(self) -> None:
        self.assertIn("golden/**", renovate_config()["ignorePaths"])

    def test_the_manager_pattern_matches_every_annotated_pin_and_reads_its_current_value(self) -> None:
        pattern = renovate_config()["customManagers"][0]["matchStrings"][0].replace("(?<", "(?P<")
        text = VERSIONS.read_text(encoding="utf-8")
        found = {match.group("depName"): match.groupdict() for match in re.finditer(pattern, text)}
        pins = yaml.safe_load(text)
        for stack, entries in annotated_pins().items():
            for key, fields in entries.items():
                with self.subTest(stack=stack, pin=key):
                    self.assertEqual(str(pins[stack][key]), fields["value"])
                    seen = [m for m in re.finditer(pattern, text) if m.group("depName") == fields["depName"] and m.group("depType") == stack]
                    self.assertTrue(seen, fields["depName"])
                    self.assertIn(str(pins[stack][key]), [m.group("currentValue") for m in seen])
        self.assertTrue(found)

    def test_every_pin_is_either_proposed_to_the_bot_or_a_named_baseline_decision(self) -> None:
        pins = yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))
        annotated = annotated_pins()
        for stack, entries in pins.items():
            with self.subTest(stack=stack):
                self.assertEqual(
                    sorted(entries),
                    sorted(set(annotated.get(stack, {})) | BASELINE_PINS.get(stack, set())),
                    "a pin needs a `# renovate:` line, or a place in BASELINE_PINS of this test",
                )
                self.assertFalse(set(annotated.get(stack, {})) & BASELINE_PINS.get(stack, set()))

    def test_each_annotation_names_a_known_datasource_a_dependency_and_the_stack_of_its_section(self) -> None:
        pins = yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))
        for stack, entries in annotated_pins().items():
            self.assertIn(stack, pins)
            for key, fields in entries.items():
                with self.subTest(stack=stack, pin=key):
                    self.assertIn(fields["datasource"], DATASOURCES)
                    self.assertTrue(fields["depName"])
                    if fields["datasource"] == "maven":
                        self.assertRegex(fields["depName"], r"^[\w.-]+:[\w.-]+$")

    def test_updates_are_grouped_per_pack(self) -> None:
        rules = {rule["matchDepTypes"][0]: rule for rule in renovate_config()["packageRules"] if rule.get("groupName")}
        self.assertEqual(sorted(annotated_pins()), sorted(rules))
        for stack, rule in rules.items():
            self.assertEqual(f"{stack} pack", rule["groupName"])
            self.assertEqual(["custom.regex"], rule["matchManagers"])
        self.assertTrue(set(rules) <= set(PACK_STACKS))

    def test_types_node_follows_the_node_major_that_the_baseline_pins(self) -> None:
        node = str(yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))["nextjs-web"]["node"])
        rule = next(rule for rule in renovate_config()["packageRules"] if rule.get("matchPackageNames") == ["@types/node"])
        self.assertEqual(f"/^{node}\\./", rule["allowedVersions"])
        types_node = str(yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))["nextjs-web"]["types_node"])
        self.assertTrue(types_node.startswith(f"{node}."))

    def test_a_commit_of_the_sync_workflow_is_not_taken_for_a_manual_edit_of_the_bot_branch(self) -> None:
        email = "41898282+github-actions[bot]@users.noreply.github.com"
        self.assertIn(email, renovate_config()["gitIgnoredAuthors"])
        self.assertIn(email, (WORKFLOWS / "dependency-sync.yml").read_text(encoding="utf-8"))


class DependencySyncWorkflowTests(unittest.TestCase):
    def workflow(self) -> dict:
        return yaml.safe_load((WORKFLOWS / "dependency-sync.yml").read_text(encoding="utf-8"))

    def test_it_runs_on_pull_requests_that_change_the_pins_and_only_for_the_bot_from_this_repository(self) -> None:
        workflow = self.workflow()
        trigger = workflow[True]  # PyYAML reads the key `on` as True
        self.assertEqual(["packs/versions.yml"], trigger["pull_request"]["paths"])
        condition = workflow["jobs"]["regenerate"]["if"]
        for part in ("github.actor == 'renovate[bot]'", "head.repo.full_name == github.repository", "startsWith(github.head_ref, 'renovate/')"):
            self.assertIn(part, condition)

    def test_it_syncs_against_the_base_branch_and_pushes_to_the_pull_request_branch(self) -> None:
        text = (WORKFLOWS / "dependency-sync.yml").read_text(encoding="utf-8")
        self.assertIn('python scripts/sync-golden.py --base "origin/$BASE_REF"', text)
        self.assertIn('git add -A packs golden', text)
        self.assertIn('git push origin "HEAD:$HEAD_REF"', text)
        # The branch name reaches the shell through the environment, never through the script text.
        run_text = "\n".join(str(step.get("run", "")) for job in self.workflow()["jobs"].values() for step in job["steps"])
        self.assertNotIn("github.head_ref", run_text)

    def test_the_toolchains_of_the_two_lockfile_scripts_come_from_the_pins(self) -> None:
        steps = self.workflow()["jobs"]["regenerate"]["steps"]
        node = next(step for step in steps if str(step.get("uses", "")).startswith("actions/setup-node@"))
        uv = next(step for step in steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"))
        self.assertEqual("${{ steps.web.outputs.node }}", node["with"]["node-version"])
        self.assertEqual("${{ steps.agent.outputs.uv }}", uv["with"]["version"])

    def test_a_push_with_the_default_token_starts_the_validation_workflows_explicitly(self) -> None:
        text = (WORKFLOWS / "dependency-sync.yml").read_text(encoding="utf-8")
        self.assertIn('gh workflow run template-validation.yml --ref "$HEAD_REF"', text)
        self.assertIn('gh workflow run cli-validation.yml --ref "$HEAD_REF"', text)
        for name in ("template-validation.yml", "cli-validation.yml"):
            self.assertIn("workflow_dispatch", yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))[True], name)


class SyncGoldenTests(unittest.TestCase):
    def test_only_the_stacks_whose_pins_differ_are_reported(self) -> None:
        before = {"nextjs-web": {"next": "16.4.0"}, "python-agent-service": {"fastapi": "0.142.2"}, "spring-backend": {"kotlin": "2.2.0"}}
        after = {"nextjs-web": {"next": "16.4.1"}, "python-agent-service": {"fastapi": "0.142.2"}, "spring-backend": {"kotlin": "2.2.0"}}
        self.assertEqual(["nextjs-web"], sync_golden.changed_stacks(before, after))
        self.assertEqual([], sync_golden.changed_stacks(after, after))
        self.assertEqual(["ios-swiftui"], sync_golden.changed_stacks(after, {**after, "ios-swiftui": {"xcode": "26.0"}}))

    def test_the_pins_parse_the_same_whatever_their_annotations(self) -> None:
        parsed = sync_golden.parse_pins(VERSIONS.read_text(encoding="utf-8"))
        self.assertEqual(sorted(PACK_STACKS), sorted(parsed))

    def test_the_two_lockfile_scripts_that_exist_are_the_ones_it_runs(self) -> None:
        for stack, script in sync_golden.LOCK_SCRIPTS.items():
            self.assertTrue((REPO_ROOT / "scripts" / script).is_file(), stack)
        self.assertEqual({"nextjs-web", "python-agent-service"}, set(sync_golden.LOCK_SCRIPTS))


NPM_REPORT = {
    "auditReportVersion": 2,
    "vulnerabilities": {
        "braces": {
            "name": "braces",
            "severity": "high",
            "via": [
                {
                    "source": 1240992,
                    "name": "braces",
                    "title": "braces vulnerable to stack-exhaustion denial of service through deeply nested patterns",
                    "url": "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
                    "severity": "high",
                    "range": "<=3.0.3",
                }
            ],
        },
        "micromatch": {"name": "micromatch", "severity": "high", "via": ["braces"]},
        "left-pad": {
            "name": "left-pad",
            "severity": "moderate",
            "via": [{"source": 5, "name": "left-pad", "title": "minor", "url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc", "severity": "moderate"}],
        },
        "evil": {
            "name": "evil",
            "severity": "critical",
            "via": [{"source": 9, "name": "evil", "title": "bad", "url": "https://github.com/advisories/GHSA-1111-2222-3333", "severity": "critical"}],
        },
    },
    "metadata": {"vulnerabilities": {"high": 2, "critical": 1, "moderate": 1}},
}


class AuditGateTests(unittest.TestCase):
    def test_an_advisory_is_reported_once_on_its_own_package_and_below_the_level_is_ignored(self) -> None:
        findings = audit_gate.npm_findings(NPM_REPORT, "high")
        self.assertEqual(["GHSA-1111-2222-3333", "GHSA-vfj7-8cjw-p6xm"], [finding["advisory"] for finding in findings])
        self.assertEqual(["evil", "braces"], [finding["package"] for finding in sorted(findings, key=lambda f: f["severity"] != "critical")])
        everything = audit_gate.npm_findings(NPM_REPORT, "moderate")
        self.assertEqual(3, len(everything))

    def test_a_listed_advisory_passes_an_unlisted_one_blocks_and_an_unmatched_entry_is_stale(self) -> None:
        findings = audit_gate.npm_findings(NPM_REPORT, "high")
        allowed = [{"advisory": "GHSA-VFJ7-8CJW-P6XM"}, {"advisory": "GHSA-0000-0000-0000"}]
        blocked, accepted, stale = audit_gate.classify(findings, allowed)
        self.assertEqual(["GHSA-1111-2222-3333"], [finding["advisory"] for finding in blocked])
        self.assertEqual(["GHSA-vfj7-8cjw-p6xm"], [finding["advisory"] for finding in accepted])
        self.assertEqual(["GHSA-0000-0000-0000"], [entry["advisory"] for entry in stale])

    def test_an_empty_report_has_no_finding(self) -> None:
        self.assertEqual([], audit_gate.npm_findings({"vulnerabilities": {}}, "high"))
        self.assertEqual([], audit_gate.npm_findings({}, "high"))

    def test_advisory_identifiers_compare_regardless_of_case(self) -> None:
        self.assertEqual("GHSA-vfj7-8cjw-p6xm", audit_gate.normalize_id("ghsa-VFJ7-8CJW-P6XM"))
        self.assertEqual("CVE-2026-1", audit_gate.normalize_id("cve-2026-1"))



class AuditGateFailsClosedTests(unittest.TestCase):
    """An audit that did not run, or whose answer is inconsistent, never passes as "no unlisted advisory"."""

    def run_gate(self, tool: str, stdout: str, returncode: int, *, stack: str = "nextjs-web") -> tuple[int, str]:
        import contextlib
        import io
        import subprocess
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / ("package-lock.json" if tool == "npm" else "uv.lock")).write_text("{}", encoding="utf-8")
            completed = subprocess.CompletedProcess(args=[tool], returncode=returncode, stdout=stdout, stderr="")
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(audit_gate.shutil, "which", return_value=tool), patch.object(audit_gate.subprocess, "run", return_value=completed):
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    code = audit_gate.main([tool, str(app), "--stack", stack])
            return code, output.getvalue() + errors.getvalue()

    def clean_report(self) -> dict:
        return {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {"vulnerabilities": {"total": 0}}}

    def test_an_empty_object_with_an_operational_exit_status_is_not_a_clean_audit(self) -> None:
        # The case that passed before: npm failed with status 2 and a report of `{}`.
        code, text = self.run_gate("npm", "{}", 2)
        self.assertEqual(1, code)
        self.assertNotIn("No unlisted advisory", text)
        self.assertIn("exited with status 2", text)

    def test_a_report_without_the_expected_structure_fails_whatever_the_exit_status(self) -> None:
        for label, report in {
            "an empty object": {},
            "no metadata": {"auditReportVersion": 2, "vulnerabilities": {}},
            "an old report version": {"auditReportVersion": 1, "vulnerabilities": {}, "metadata": {"vulnerabilities": {}}},
            "vulnerabilities as a list": {"auditReportVersion": 2, "vulnerabilities": [], "metadata": {"vulnerabilities": {}}},
            "an entry that is not a mapping": {"auditReportVersion": 2, "vulnerabilities": {"x": "high"}, "metadata": {"vulnerabilities": {}}},
            "a list": [],
        }.items():
            for status in (0, 1):
                with self.subTest(label=label, status=status):
                    code, text = self.run_gate("npm", json.dumps(report), status)
                    self.assertEqual(1, code)
                    self.assertNotIn("No unlisted advisory", text)

    def test_an_exit_status_that_disagrees_with_the_report_fails(self) -> None:
        code, text = self.run_gate("npm", json.dumps(self.clean_report()), 1)
        self.assertEqual(1, code)
        self.assertIn("lists no advisory", text)
        code, text = self.run_gate("npm", json.dumps(NPM_REPORT), 0)
        self.assertEqual(1, code)
        self.assertIn("exited with status 0", text)

    def test_a_clean_report_with_a_clean_exit_passes_and_a_listed_finding_passes_with_status_one(self) -> None:
        code, text = self.run_gate("npm", json.dumps(self.clean_report()), 0)
        self.assertEqual(0, code, text)
        self.assertIn("No unlisted advisory", text)
        only_listed = {
            **NPM_REPORT,
            "vulnerabilities": {name: entry for name, entry in NPM_REPORT["vulnerabilities"].items() if name in {"braces", "micromatch"}},
            "metadata": {"vulnerabilities": {"high": 2, "total": 2}},
        }
        code, text = self.run_gate("npm", json.dumps(only_listed), 1)
        self.assertEqual(0, code, text)
        self.assertIn("allowed: GHSA-vfj7-8cjw-p6xm", text)

    def test_a_report_whose_totals_disagree_with_its_entries_fails_whatever_the_exit_status(self) -> None:
        # Astra's case: exit 0, no advisory, and a high vulnerability only in the metadata.
        declared_only = {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {"vulnerabilities": {"high": 1, "total": 1}}}
        code, text = self.run_gate("npm", json.dumps(declared_only), 0)
        self.assertEqual(1, code, text)
        self.assertNotIn("No unlisted advisory", text)
        self.assertIn("declares 1 high vulnerability(ies), but its report lists 0", text)
        entry = NPM_REPORT["vulnerabilities"]["braces"]
        for label, report in {
            "a critical count with no entry": {"auditReportVersion": 2, "vulnerabilities": {"braces": entry}, "metadata": {"vulnerabilities": {"high": 1, "critical": 1, "total": 1}}},
            "an entry the metadata leaves out": {"auditReportVersion": 2, "vulnerabilities": {"braces": entry}, "metadata": {"vulnerabilities": {"high": 0, "total": 0}}},
            "a total that differs": {"auditReportVersion": 2, "vulnerabilities": {"braces": entry}, "metadata": {"vulnerabilities": {"high": 1, "total": 3}}},
            "a count that is not a number": {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {"vulnerabilities": {"high": "0"}}},
        }.items():
            for exit_status in (0, 1):
                with self.subTest(label=label, status=exit_status):
                    code, text = self.run_gate("npm", json.dumps(report), exit_status)
                    self.assertEqual(1, code, text)
                    self.assertNotIn("No unlisted advisory", text)

    def test_an_entry_or_an_advisory_without_the_fields_the_gate_reports_fails(self) -> None:
        entry = NPM_REPORT["vulnerabilities"]["braces"]
        advisory = entry["via"][0]
        metadata = {"vulnerabilities": {"high": 1, "total": 1}}
        for label, vulnerabilities in {
            "an entry without a severity": {"braces": {k: v for k, v in entry.items() if k != "severity"}},
            "an entry with an unknown severity": {"braces": {**entry, "severity": "severe"}},
            "an advisory without its link": {"braces": {**entry, "via": [{k: v for k, v in advisory.items() if k != "url"}]}},
            "an advisory without its title": {"braces": {**entry, "via": [{k: v for k, v in advisory.items() if k != "title"}]}},
            "an advisory without its package": {"braces": {**entry, "via": [{k: v for k, v in advisory.items() if k != "name"}]}},
            "an advisory without a severity": {"braces": {**entry, "via": [{k: v for k, v in advisory.items() if k != "severity"}]}},
            "a via item that is neither": {"braces": {**entry, "via": [7]}},
        }.items():
            with self.subTest(label=label):
                report = {"auditReportVersion": 2, "vulnerabilities": vulnerabilities, "metadata": metadata}
                code, text = self.run_gate("npm", json.dumps(report), 1)
                self.assertEqual(1, code, text)
                self.assertNotIn("allowed:", text)
                self.assertNotIn("No unlisted advisory", text)
                self.assertIn("::error::npm audit", text)

    def test_a_clean_exit_with_an_entry_at_the_level_fails_even_when_the_totals_agree(self) -> None:
        transitive = {"auditReportVersion": 2, "vulnerabilities": {"micromatch": {"name": "micromatch", "severity": "high", "via": ["braces"]}}, "metadata": {"vulnerabilities": {"high": 1, "total": 1}}}
        code, text = self.run_gate("npm", json.dumps(transitive), 0)
        self.assertEqual(1, code, text)
        self.assertIn("exited with status 0", text)

    def test_an_unlisted_finding_still_blocks(self) -> None:
        code, text = self.run_gate("npm", json.dumps(NPM_REPORT), 1)
        self.assertEqual(1, code)
        self.assertIn("GHSA-1111-2222-3333", text)

    def test_uv_passes_only_on_status_zero_and_an_operational_status_is_an_error_not_a_finding(self) -> None:
        self.assertEqual(0, self.run_gate("uv", "", 0, stack="python-agent-service")[0])
        code, text = self.run_gate("uv", "", 1, stack="python-agent-service")
        self.assertEqual(1, code)
        self.assertIn("reported a finding", text)
        code, text = self.run_gate("uv", "", 2, stack="python-agent-service")
        self.assertEqual(2, code)
        self.assertIn("neither a clean audit (0) nor findings (1)", text)
        self.assertEqual(1, self.run_gate("uv", "", -9, stack="python-agent-service")[0])


class AllowListTests(unittest.TestCase):
    def allowlist(self) -> dict[str, list[dict[str, str]]]:
        return yaml.safe_load((REPO_ROOT / "packs" / "audit-allowlist.yml").read_text(encoding="utf-8"))

    def test_it_lists_only_stacks_with_a_pack(self) -> None:
        self.assertTrue(set(self.allowlist()) <= set(PACK_STACKS))

    def test_every_entry_has_an_advisory_its_link_and_a_reason_and_is_recorded_in_the_current_status(self) -> None:
        status = (REPO_ROOT / "docs" / "current-status.md").read_text(encoding="utf-8")
        self.assertTrue("Known dependency advisories" in status, "docs/current-status.md needs its Known dependency advisories section")
        for stack, entries in self.allowlist().items():
            for entry in entries or []:
                with self.subTest(stack=stack, advisory=entry.get("advisory")):
                    self.assertRegex(entry["advisory"], r"^(GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|CVE-\d+-\d+|PYSEC-\d+-\d+)$")
                    self.assertEqual(f"https://github.com/advisories/{entry['advisory']}", entry["url"])
                    self.assertTrue(entry.get("package"))
                    self.assertIn(entry.get("severity"), {"high", "critical"})
                    self.assertGreater(len(str(entry.get("reason", "")).strip()), 80, "the reason says why accepting it is safe")
                    self.assertTrue(entry["advisory"] in status, "docs/current-status.md must record the advisory")
                    self.assertTrue(entry["url"] in status, "docs/current-status.md must link the advisory")

    def test_the_script_reads_the_file_that_the_workflow_documents(self) -> None:
        self.assertEqual(REPO_ROOT / "packs" / "audit-allowlist.yml", audit_gate.ALLOWLIST)
        loaded = audit_gate.load_allowlist(audit_gate.ALLOWLIST, "nextjs-web")
        self.assertEqual(self.allowlist()["nextjs-web"], loaded)
        self.assertEqual([], audit_gate.load_allowlist(audit_gate.ALLOWLIST, "ios-swiftui"))

    def test_the_ci_jobs_that_audit_run_the_gate_with_their_stack(self) -> None:
        text = (WORKFLOWS / "template-validation.yml").read_text(encoding="utf-8")
        self.assertIn("python scripts/audit-gate.py npm golden/web --stack nextjs-web", text)
        self.assertIn("python scripts/audit-gate.py uv golden/agent-service --stack python-agent-service", text)


if __name__ == "__main__":
    unittest.main()
