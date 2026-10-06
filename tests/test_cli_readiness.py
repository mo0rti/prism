from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from prism_cli import cli
from tests.core_workflow_fixture import FEATURE_PATH, INTAKE_ITEM, PROCESSED_INTAKE_ITEM, create_core_workflow_fixture
from tests.test_core_workflow_fixture import CHECK_DATE, _feature_page
from tests import real_temp  # noqa: F401


class ValidateReadinessTests(unittest.TestCase):
    def test_blocked_workflow_validation_succeeds_and_reports_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _blocked_workspace(Path(temporary) / "workflow")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = cli.main(["validate", str(root), "--kind", "workflow-project"])

        self.assertEqual(0, result)
        self.assertIn("Workflow readiness", stdout.getvalue())
        self.assertIn("pending-board-review", stdout.getvalue())
        self.assertIn("readiness blockers are reported above", stdout.getvalue())

    def test_blocked_generated_project_validation_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _blocked_workspace(Path(temporary) / "generated")
            for relative, content in (
                ("README.md", "# Fixture\n"),
                ("CONTEXT.md", "# Context\n"),
                ("Taskfile.yml", "version: '3'\n"),
                (".github/workflows/backend.yml", "name: backend\n"),
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = cli.main(["validate", str(root), "--kind", "generated-project"])

        self.assertEqual(0, result)
        self.assertIn("Workflow readiness", stdout.getvalue())
        self.assertIn("Validation passed with", stdout.getvalue())

    def test_malformed_wiki_evidence_remains_a_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _blocked_workspace(Path(temporary) / "workflow")
            feature = root / FEATURE_PATH
            text = feature.read_text(encoding="utf-8")
            feature.write_text(
                text.replace("| po | open |", "| qa | maybe |"),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = cli.main(["validate", str(root), "--kind", "workflow-project"])

        self.assertEqual(cli.EXIT_VALIDATION, result)
        self.assertIn("Integrity errors", stdout.getvalue())
        self.assertIn("invalid-open-question-owner", stdout.getvalue())
        self.assertIn("invalid-open-question-status", stdout.getvalue())

    def test_wiki_lint_json_contract_and_exit_code_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _blocked_workspace(Path(temporary) / "workflow")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = cli.main(["wiki", "lint", str(root), "--json"])

        document = json.loads(stdout.getvalue())
        self.assertEqual(cli.EXIT_VALIDATION, result)
        self.assertEqual(1, document["schema_version"])
        self.assertEqual(
            {
                "schema_version", "experimental", "command", "confidence", "root", "workspace",
                "facts", "blocker_facts", "required_obligations", "sources", "diagnostics",
            },
            set(document),
        )
        self.assertFalse(document["facts"]["clean"])
        self.assertIn("pending-board-review", {item["code"] for item in document["diagnostics"]})

    def test_blocked_transition_preflight_still_exits_three(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _blocked_workspace(Path(temporary) / "workflow")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = cli.main([
                    "wiki", "transition-preflight", "F-001", str(root),
                    "--action", "dev-done", "--json",
                ])

        document = json.loads(stdout.getvalue())
        self.assertEqual(3, result)
        self.assertEqual("blocked", document["facts"]["transition"]["classification"])


def _blocked_workspace(root: Path) -> Path:
    create_core_workflow_fixture(root)
    pending = root / INTAKE_ITEM
    processed = root / PROCESSED_INTAKE_ITEM
    processed.parent.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pending.parent), str(processed.parent))

    feature = root / FEATURE_PATH
    page = _feature_page()
    frontmatter_text = page.split("---", 2)[1]
    frontmatter = yaml.safe_load(frontmatter_text)
    frontmatter.update({
        "status": "in-dev",
        "owner": "dev",
        "advisory-review": "pending",
    })
    body = page.split("---", 2)[2]
    feature.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False).rstrip() + "\n---" + body,
        encoding="utf-8",
    )
    (root / "knowledge/wiki/index.md").write_text(
        "# Feature Status Board\n\n"
        "| ID | Feature | Status | Owner | Board Review |\n"
        "|----|---------|--------|-------|--------------|\n"
        f"| F-001 | Document review | in-dev | dev | pending |\n",
        encoding="utf-8",
    )
    return root


if __name__ == "__main__":
    unittest.main()
