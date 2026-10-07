"""Every generated pack workflow is hygienic: read-only token, one run per app and branch, a display name unique per app."""

from __future__ import annotations

import unittest

import yaml

from prism_cli.packs import PACK_STACKS, ci_workflow_name, pack_answers
from tests import real_temp  # noqa: F401
from tests.test_hostile_values import PINS, REPO_ROOT, hostile_app, render, workflow_context

PROJECT = {"project_name": "Demo", "project_slug": "demo", "package_identifier": "com.example.demo"}


def workflow(stack: str, **fields: str) -> dict:
    template = REPO_ROOT / "packs" / stack / ".github" / "workflows" / "{{ app_id }}.yml.jinja"
    return yaml.safe_load(render(template, workflow_context(stack, **fields)))


class PackWorkflowHygieneTests(unittest.TestCase):
    def test_every_workflow_reads_the_repository_with_a_read_only_token(self) -> None:
        for stack in PACK_STACKS:
            with self.subTest(stack=stack):
                self.assertEqual({"contents": "read"}, workflow(stack)["permissions"])

    def test_every_workflow_runs_once_per_app_and_branch_and_cancels_the_run_it_replaces(self) -> None:
        for stack in PACK_STACKS:
            for app_id in ("web", "partner-app"):
                with self.subTest(stack=stack, app=app_id):
                    self.assertEqual({"group": f"{app_id}-${{{{ github.ref }}}}", "cancel-in-progress": True}, workflow(stack, id=app_id)["concurrency"])

    def test_two_apps_of_one_stack_with_one_name_get_two_workflow_names(self) -> None:
        for stack in PACK_STACKS:
            names = {
                workflow(stack, id=app_id, name="Customer App", path=app_id)["name"]
                for app_id in ("customer-app", "customer-app-two")
            }
            with self.subTest(stack=stack):
                self.assertEqual({"Customer App CI (customer-app)", "Customer App CI (customer-app-two)"}, names)

    def test_the_name_is_the_apps_name_alone_when_that_is_its_id(self) -> None:
        self.assertEqual("backend CI", ci_workflow_name("backend", "backend"))
        self.assertEqual("Spring Boot Backend CI (backend)", ci_workflow_name("Spring Boot Backend", "backend"))
        answers = pack_answers(PROJECT, hostile_app("nextjs-web", id="web-two", name="Web App", path="web-two"), port=3001)
        self.assertEqual("Web App CI (web-two)", answers["ci_workflow_name"])

    def test_the_cli_and_the_questionnaire_agree_on_the_default(self) -> None:
        config = yaml.safe_load((REPO_ROOT / "copier.yml").read_text(encoding="utf-8"))
        default = config["ci_workflow_name"]["default"]
        self.assertIn("app_name ~ ' CI'", default)
        self.assertIn("' (' ~ app_id ~ ')'", default)
        self.assertEqual(sorted(PACK_STACKS), sorted(PINS), "every pack stack has pins and a workflow")


if __name__ == "__main__":
    unittest.main()
