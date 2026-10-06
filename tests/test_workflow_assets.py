"""The packaged workflow catalog is complete, self-contained, and reproducible."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from prism_cli.workflow_assets import asset_digest, bootstrap_files, get_skill, guidance_pointer, list_skills, previous_digests
from tests import real_temp  # noqa: F401


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = {
    "ask", "audit-feature", "board-review", "design-clarify", "design-handoff",
    "design-intake", "design-start", "dev-clarify", "dev-done", "dev-start", "feature-reopen",
    "feature-status", "ingest", "lint-wiki", "po-clarify", "po-handoff", "po-intake",
    "po-specify", "prep-sprint", "setup-project", "wiki-blockers", "wiki-owner",
    "wiki-app", "wiki-query", "wiki-show",
}


class WorkflowAssetsTests(unittest.TestCase):
    def test_skill_catalog_and_feature_reopen_actions_are_distinct(self):
        skills = list_skills()
        by_name = {item["name"]: item for item in skills}
        self.assertEqual(EXPECTED_SKILLS, set(by_name))
        self.assertEqual(["reopen-spec", "reopen-design", "reopen-dev"], by_name["feature-reopen"]["actions"])
        self.assertEqual("1", by_name["po-intake"]["version"])
        self.assertEqual(64, len(asset_digest()))

    def test_skill_instructions_and_references_are_complete_content_with_digests(self):
        skill = get_skill("po-intake")
        self.assertIn("##", skill["instructions"])
        self.assertIn("knowledge/wiki/CONNECTED.md", {item["path"] for item in skill["references"]})
        self.assertIn("knowledge/intake/README.md", {item["path"] for item in skill["references"]})
        self.assertNotIn("knowledge/wiki/index.md", {item["path"] for item in skill["references"]})
        for item in skill["references"]:
            self.assertEqual(hashlib.sha256(item["content"].encode("utf-8")).hexdigest(), item["digest"])

    def test_canonical_format_references_are_written_as_the_listed_reference_paths(self):
        for item in list_skills():
            name = item["name"]
            with self.subTest(skill=name):
                skill = get_skill(name)
                references = {reference["path"] for reference in skill["references"]}
                self.assertIn(f".claude/commands/{name}.md", references)
                instructions = skill["instructions"]
                self.assertNotIn("`/.claude/commands/", instructions)
                if "## Canonical format reference" in instructions:
                    section = instructions.split("## Canonical format reference", 1)[1].split("\n## ", 1)[0]
                    named = [line[3:-1] for line in section.splitlines() if line.startswith("- `") and line.endswith("`")]
                    self.assertTrue(named)
                    self.assertLessEqual(set(named), references)

    def test_connected_guide_teaches_reference_fetching_cursors_and_digests(self):
        guide = {item["path"]: item for item in get_skill("po-intake")["references"]}["knowledge/wiki/CONNECTED.md"]["content"]
        for term in ("get_skill_reference", "next_cursor", "total_chars", "digest", "32,000", "required_workspace_reads"):
            self.assertIn(term, guide)
        template = (REPO_ROOT / "template/knowledge/wiki/CONNECTED.md").read_text(encoding="utf-8")
        self.assertEqual(template.splitlines(), guide.splitlines())

    def test_connected_guide_allows_a_bounded_retry_with_the_fix_the_error_names(self):
        guide = {item["path"]: item for item in get_skill("po-intake")["references"]}["knowledge/wiki/CONNECTED.md"]["content"]
        text = " ".join(guide.split())
        for term in ("exactly the fix the error names", "at most 2 more times", "Never widen the change", "stop and report"):
            self.assertIn(term, text)
        self.assertNotIn("shrinking the proposed write set", text)
        schema = {item["path"]: item for item in get_skill("po-intake")["references"]}["knowledge/wiki/SCHEMA.md"]["content"]
        self.assertIn("at most 2 more times", " ".join(schema.split()))

    def test_dev_clarify_follows_the_other_clarify_skills(self):
        skill = get_skill("dev-clarify")
        references = {item["path"] for item in skill["references"]}
        self.assertEqual({"knowledge/wiki/features/_FORMAT.md", "knowledge/wiki/app-requirements/_FORMAT.md"}, {path for path in references if path.endswith("_FORMAT.md")})
        self.assertIn(".claude/commands/dev-clarify.md", references)
        self.assertEqual([], skill["actions"])
        self.assertIn("$dev-clarify", skill["instructions"])
        self.assertIn("owner = `dev`", skill["instructions"])
        for sibling in ("po-clarify", "design-clarify"):
            self.assertEqual(
                [line for line in get_skill(sibling)["instructions"].splitlines() if line.startswith("#")],
                [line.replace("Dev", {"po-clarify": "PO", "design-clarify": "Design"}[sibling]) for line in skill["instructions"].splitlines() if line.startswith("#")],
            )

    def test_intake_and_delivery_guidance_state_raw_features_and_evidence_as_input(self):
        intake = get_skill("po-intake")
        self.assertIn("status: raw", intake["instructions"])
        claude = {item["path"]: item["content"] for item in intake["references"]}[".claude/commands/po-intake.md"]
        self.assertIn("Set status: `raw`, owner: `po`", claude)
        self.assertNotIn("Set status: `specified`", claude)
        done = get_skill("dev-done")
        self.assertIn("Delivery evidence is an input to this action", done["instructions"])
        self.assertNotIn("must already be recorded", done["instructions"])
        lifecycle = {item["path"]: item["content"] for item in done["references"]}["knowledge/wiki/LIFECYCLE.md"]
        self.assertIn("Delivery evidence is an input to `dev-done`", lifecycle)

    def test_skill_references_never_substitute_template_workspace_state(self):
        workspace_state = {
            "knowledge/wiki/SETTINGS.md",
            "knowledge/wiki/WIKI_REPORT.md",
            "knowledge/wiki/index.md",
            "knowledge/wiki/status-board.md",
            "knowledge/wiki/direction.md",
            "knowledge/wiki/roadmap.md",
            "knowledge/wiki/log.md",
            "knowledge/wiki/advisory/BOARD.md",
            "knowledge/wiki/advisory/PROJECT_FOUNDATION.md",
        }
        for listed in list_skills():
            with self.subTest(skill=listed["name"]):
                references = {item["path"] for item in get_skill(listed["name"])["references"]}
                self.assertFalse(workspace_state.intersection(references))

    def test_bootstrap_contains_only_non_application_knowledge_sources(self):
        files = bootstrap_files()
        paths = {item["path"] for item in files}
        self.assertIn("knowledge/wiki/SCHEMA.md", paths)
        self.assertIn("knowledge/wiki/CONNECTED.md", paths)
        self.assertIn("knowledge/wiki/index.md", paths)
        self.assertIn("knowledge/wiki/status-board.md", paths)
        self.assertIn("knowledge/wiki/topics/_FORMAT.md", paths)
        self.assertIn("knowledge/wiki/direction.md", paths)
        self.assertIn("knowledge/intake/README.md", paths)
        self.assertTrue(all(path.startswith("knowledge/") for path in paths))
        self.assertGreaterEqual(len(files), 20)

    def test_pointer_states_the_one_retry_rule_the_connected_guide_gives(self):
        for name in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(pointer=name):
                text = " ".join(guidance_pointer(name).split())
                for term in ("exactly the fix the error names", "at most 2 more times", "never widen the change", "then stop and report"):
                    self.assertIn(term, text)
                self.assertNotIn("Stop on denied or unavailable connected writes", text)

    def test_design_handoff_keeps_open_questions_out_of_requirement_dependencies(self):
        skill = get_skill("design-handoff")
        guidance = [skill["instructions"]] + [
            item["content"] for item in skill["references"]
            if item["path"] in (".claude/commands/design-handoff.md", "knowledge/wiki/app-requirements/_FORMAT.md")
        ]
        self.assertEqual(3, len(guidance))
        for text in guidance:
            flat = " ".join(text.split())
            self.assertIn("Dependencies", flat)
            self.assertIn("open question", flat.lower())
            self.assertIn("Open questions table", flat)
        instructions = " ".join(skill["instructions"].split())
        self.assertIn("lists only real dependencies", instructions)
        self.assertIn("`ask`", instructions)

    def test_the_asset_records_no_earlier_shipped_digests(self):
        asset = json.loads((REPO_ROOT / "prism_cli/assets/workflow-v1.json").read_text(encoding="utf-8"))
        self.assertEqual({}, asset["previous_digests"])
        for item in bootstrap_files():
            self.assertEqual((), previous_digests(item["path"]))
        self.assertEqual((), previous_digests("knowledge/wiki/never-shipped.md"))

    def test_the_build_script_writes_exactly_the_declared_history(self):
        build = _load_build_script()
        self.assertEqual({}, build.PREVIOUS_DIGESTS)
        self.assertEqual({}, build.build_asset()["previous_digests"])
        connected = "knowledge/wiki/CONNECTED.md"
        digests = ["a" * 64, "b" * 64]
        with patch.object(build, "PREVIOUS_DIGESTS", {connected: digests, "AGENTS.md": ["c" * 64]}):
            history = build.build_asset()["previous_digests"]
        self.assertEqual({"AGENTS.md": ["c" * 64], connected: digests}, history)
        self.assertEqual(sorted(history), list(history))

    def test_ingest_is_a_canonical_skill_in_both_layers_and_the_asset(self):
        template = REPO_ROOT / "template"
        codex = template / ".agents" / "skills" / "ingest"
        self.assertTrue((codex / "SKILL.md.jinja").is_file())
        self.assertTrue((template / ".claude" / "commands" / "ingest.md.jinja").is_file())
        self.assertIn("allow_implicit_invocation: false", (codex / "agents" / "openai.yaml").read_text(encoding="utf-8"))

        skill = get_skill("ingest")
        self.assertEqual("ingest", skill["name"])
        self.assertEqual([], next(item for item in list_skills() if item["name"] == "ingest")["actions"])
        references = {item["path"] for item in skill["references"]}
        for path in (
            "knowledge/wiki/SCHEMA.md",
            "knowledge/wiki/LIFECYCLE.md",
            "knowledge/wiki/topics/_FORMAT.md",
            "knowledge/wiki/research/_FORMAT.md",
            "knowledge/wiki/plans/_FORMAT.md",
            "knowledge/wiki/personas/_FORMAT.md",
            "knowledge/wiki/business-rules/_FORMAT.md",
            "knowledge/wiki/decisions/_FORMAT.md",
            "knowledge/wiki/features/_FORMAT.md",
            "knowledge/intake/README.md",
            ".claude/commands/ingest.md",
        ):
            self.assertIn(path, references)
        self.assertTrue(references.isdisjoint({"knowledge/wiki/index.md", "knowledge/wiki/status-board.md", "knowledge/wiki/direction.md"}))
        instructions = skill["instructions"]
        for needle in (
            "any role",
            "knowledge/wiki/index.md",
            "knowledge/wiki/status-board.md",
            "CONFLICT.md",
            "MANIFEST.md",
            "status: raw",
            "never rewrite an existing feature, persona, business rule or decision",
            "**Decided:**",
        ):
            self.assertIn(needle, instructions)
        command = {item["path"]: item["content"] for item in skill["references"]}[".claude/commands/ingest.md"]
        for needle in ("/ingest [folder-name]", "Any role", "knowledge/wiki/index.md", "CONFLICT.md", "MANIFEST.md"):
            self.assertIn(needle, command)

    def test_the_query_skills_read_the_index_first_in_both_layers(self):
        skill = get_skill("wiki-query")
        command = {item["path"]: item["content"] for item in skill["references"]}[".claude/commands/wiki-query.md"]
        for text in (skill["instructions"], command):
            flat = " ".join(text.split())
            self.assertIn("reads `knowledge/wiki/index.md` first", flat)
            self.assertIn("index_line", text)
            self.assertIn("`knowledge/wiki/topics/`", text)
        fallback = " ".join(skill["instructions"].split()).split("## Fallback path", 1)[1]
        self.assertLess(fallback.index("`knowledge/wiki/index.md` first"), fallback.index("`knowledge/wiki/features/`"))

    def test_the_lifecycle_skills_read_the_status_board_and_the_writing_skills_maintain_the_index(self):
        for name in ("po-handoff", "design-start", "dev-start", "dev-done", "feature-status"):
            with self.subTest(skill=name):
                text = get_skill(name)["instructions"]
                self.assertIn("status-board.md", text.replace("status board", "status-board.md"))
        for name in ("po-intake", "design-intake", "ingest", "po-specify", "design-handoff", "board-review"):
            with self.subTest(skill=name):
                self.assertIn("index.md", get_skill(name)["instructions"])

    def test_checked_in_asset_matches_maintained_template_sources(self):
        result = subprocess.run(
            [sys.executable, "scripts/build-workflow-assets.py", "--check"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertIn("matches maintained template skill and knowledge sources", result.stdout)


def _load_build_script():
    spec = importlib.util.spec_from_file_location("build_workflow_assets_under_test", REPO_ROOT / "scripts/build-workflow-assets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
