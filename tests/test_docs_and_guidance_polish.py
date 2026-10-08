"""Guidance and docs state the current product: no stale wording, and the rules the skills teach are written down.

These tests read sources and generated files only; they start no process and call no network.
"""

from __future__ import annotations

import dataclasses
import json
import re
import unittest
from pathlib import Path

from prism_cli.packs import stack_maturity
from prism_cli.presets import PRESETS, Preset

REPO_ROOT = Path(__file__).resolve().parents[1]
CLARIFY_SKILLS = ("po-clarify", "design-clarify", "dev-clarify")


def read(*parts: str) -> str:
    return REPO_ROOT.joinpath(*parts).read_text(encoding="utf-8")


class ShortAnswerRuleTests(unittest.TestCase):
    """A short answer such as `yes` becomes a complete sentence in the question's wording, never the whole text."""

    def test_each_clarify_skill_source_states_the_rule_with_its_example(self) -> None:
        for name in CLARIFY_SKILLS:
            with self.subTest(skill=name):
                text = " ".join(read("template-skills", name, "skill.md").split())
                self.assertIn("turn a short answer into a complete sentence", text)
                self.assertIn("the question's own wording", text)
                self.assertIn("keep the answer's words unchanged inside it", text)
                self.assertIn("is never the whole text of a bullet, cell or paragraph", text)
                self.assertIn("The export can run inside the request: yes.", text)

    def test_the_rule_reaches_the_codex_skill_and_the_claude_command_of_each_clarify_skill(self) -> None:
        for name in CLARIFY_SKILLS:
            for relative in (f"template/.agents/skills/{name}/SKILL.md.jinja", f"template/.claude/commands/{name}.md.jinja"):
                with self.subTest(file=relative):
                    self.assertIn("turn a short answer into a complete sentence", " ".join(read(*relative.split("/")).split()))

    def test_the_packaged_skill_and_the_connected_guide_carry_the_rule(self) -> None:
        asset = json.loads(read("prism_cli", "assets", "workflow-v1.json"))
        by_path = {item["path"]: item["content"] for item in asset["files"]}
        for name in CLARIFY_SKILLS:
            with self.subTest(skill=name):
                self.assertIn("turn a short answer into a complete sentence", " ".join(by_path[f".agents/skills/{name}/SKILL.md"].split()))
        connected = " ".join(read("template", "knowledge", "wiki", "CONNECTED.md").split())
        self.assertIn("a short answer such as `yes` is never the whole text of a bullet, cell or paragraph", connected)

    def test_the_unlinked_answer_rejection_asks_for_a_sentence_and_keeps_asking_for_the_answer_verbatim(self) -> None:
        from prism_cli.board_service import BoardService

        error = BoardService._unlinked_answer_error("clarify_answer_unlinked", "knowledge/wiki/features/F-001-x.md", ["Summary"], [("1", "yes")])
        self.assertIn("verbatim", error.message)
        self.assertIn("complete sentence", error.message)
        self.assertEqual({"1": "yes"}, error.details["resolved_answers"])

    def test_ask_and_the_clarify_skills_tell_the_agent_to_copy_every_other_line_unchanged(self) -> None:
        for name in ("ask", *CLARIFY_SKILLS):
            with self.subTest(skill=name):
                text = " ".join(read("template-skills", name, "skill.md").split())
                self.assertIn("copy every other line and section exactly as `read_workspace` returned it, including the file's final newline", text)


class CursorLoadsEachBoardReviewOnceTests(unittest.TestCase):
    def test_the_board_review_is_a_skill_and_has_no_cursor_rule(self) -> None:
        self.assertFalse((REPO_ROOT / "template" / ".cursor" / "rules" / "advisory-review.mdc.jinja").exists())
        self.assertNotIn("cursor", read("template-skills", "board-review", "skill.md").split("---")[1])
        for folder in (".agents/skills/board-review/SKILL.md.jinja", ".claude/skills/board-review/SKILL.md.jinja"):
            self.assertTrue((REPO_ROOT / "template" / folder).is_file(), folder)

    def test_the_docs_state_why_the_skill_folders_stay_and_the_rule_is_gone(self) -> None:
        text = " ".join(read("docs", "ai-surfaces.md").split())
        self.assertIn("The two skill folders stay.", text)
        self.assertIn("the board review is a skill and has no Cursor rule", text)


class SetupProjectNamesTheCurrentCommandsTests(unittest.TestCase):
    def test_setup_project_runs_after_prism_new_or_workflow_install_not_after_copier_copy(self) -> None:
        for relative in (
            ("template-skills", "setup-project", "skill.md"),
            ("template", ".agents", "skills", "setup-project", "SKILL.md.jinja"),
            ("template", ".claude", "commands", "setup-project.md.jinja"),
        ):
            with self.subTest(file="/".join(relative)):
                text = read(*relative)
                self.assertNotIn("copier copy", text)
                self.assertNotIn("Platforms included", text)
                self.assertIn("`prism new`", text)
                self.assertIn("`prism workflow install`", text)


class PackGuidanceMatchesThePackTests(unittest.TestCase):
    """The guidance of a pack states what the pack does."""

    IOS = ("packs", "ios-swiftui", "{{ app_path }}")
    ANDROID = ("packs", "android-compose")
    BACKEND = ("packs", "spring-backend", "{{ app_path }}")

    def test_ios_guidance_names_the_generated_fake_client_not_its_template_file(self) -> None:
        self.assertNotIn(".swift.jinja", read(*self.IOS, "AGENTS.md.jinja"))
        self.assertIn("`Tests/Support/FakeAPIClient.swift`", read(*self.IOS, "AGENTS.md.jinja"))
        self.assertTrue((REPO_ROOT / "golden" / "mobile-ios" / "Tests" / "Support" / "FakeAPIClient.swift").is_file(), "the generated file has no template suffix")

    def test_ios_guidance_does_not_claim_generate_clients_regenerates_the_ios_client(self) -> None:
        for name in ("AGENTS.md.jinja", "CLAUDE.md.jinja"):
            with self.subTest(file=name):
                text = read(*self.IOS, name)
                self.assertNotIn("regenerate typed clients", text)
                self.assertNotIn("regenerate API clients", text)
                self.assertIn("hand-written", text)
                self.assertIn("generate-clients", text)

    def test_android_guidance_prints_the_compile_sdk_as_the_compile_sdk(self) -> None:
        for relative in ((*self.ANDROID, ".cursor", "rules", "{{ app_id }}.mdc.jinja"), (*self.ANDROID, "{{ app_path }}", "AGENTS.md.jinja")):
            with self.subTest(file=relative[-1]):
                text = read(*relative)
                self.assertNotIn("target and compile SDK {{ versions.target_sdk }}", text)
                self.assertIn("compile SDK {{ versions.compile_sdk }}", text)

    def test_the_backend_has_no_task_that_presents_gradle_check_as_a_linter(self) -> None:
        taskfile = read(*self.BACKEND, "Taskfile.yml.jinja")
        self.assertNotIn("\n  lint:", taskfile)
        self.assertIn("\n  check:", taskfile)
        self.assertIn("no Kotlin style linter", taskfile)
        self.assertNotIn(":lint", read(*self.BACKEND, "docs", "guide.md.jinja"))
        root = read("template", "Taskfile.yml.jinja")
        lint = root.split("  lint:")[1].split("  test:")[0]
        self.assertNotIn('app.stack == "spring-backend"', lint)


class StaleTextIsGoneTests(unittest.TestCase):
    def test_the_ios_caveat_says_the_macos_ci_job_builds_and_tests_it(self) -> None:
        caveat = stack_maturity("ios-swiftui")["caveat"]
        self.assertEqual("experimental", stack_maturity("ios-swiftui")["level"])
        self.assertIn("macOS CI job builds and tests", caveat)
        self.assertNotIn("requires local macOS", caveat)

    def test_no_preset_carries_an_answers_field(self) -> None:
        self.assertNotIn("answers", {field.name for field in dataclasses.fields(Preset)})
        self.assertTrue(all(preset.apps for preset in PRESETS))

    def test_the_docs_use_the_current_names_and_counts(self) -> None:
        stale = (
            "four generated app IDs",
            "four default app IDs",
            "all four stacks",
            "reference-platforms",
            'in platforms %}',
            "local macOS/Xcode validation",
            "validating locally on macOS comes before",
            "prism workflow upgrade . --apply` to apply",
        )
        for path in sorted((REPO_ROOT / "docs").glob("*.md")) + [REPO_ROOT / "README.md", REPO_ROOT / "CLAUDE.md", REPO_ROOT / "AGENTS.md"]:
            text = path.read_text(encoding="utf-8")
            for phrase in stale:
                with self.subTest(file=path.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_the_status_page_states_each_packs_maturity_and_that_the_claude_adapter_never_ran_live(self) -> None:
        text = " ".join(read("docs", "current-status.md").split())
        for stack, level in (("spring-backend", "baseline"), ("nextjs-web", "provisional"), ("android-compose", "baseline"), ("ios-swiftui", "experimental"), ("python-agent-service", "provisional")):
            self.assertEqual(level, stack_maturity(stack)["level"], stack)
            self.assertIn(f"`{stack}` | {level} |", text)
        self.assertIn("The Claude adapter is tested against a stub only. No call to the live API has been made", text)
        self.assertIn("task <app-id>:eval-live", text)


class SetupIsNotAPreconditionTests(unittest.TestCase):
    """`setup-project` initializes the wiki and the advisory board; no lifecycle action waits for it."""

    PRECONDITION = re.compile(r"(?i)\b(before|first|prior|required?|requires|must|until|precondition)\b[^.\n]{0,80}\bsetup\b|\bsetup\b[^.\n]{0,40}\b(first|required|before)\b")

    def skill_sources(self) -> dict[str, str]:
        return {path.parent.name: path.read_text(encoding="utf-8") for path in sorted((REPO_ROOT / "template-skills").glob("*/skill.md"))}

    def test_no_lifecycle_skill_mentions_setup_or_its_marker(self) -> None:
        for name, text in self.skill_sources().items():
            if name in {"setup-project", "board-review"}:
                continue
            with self.subTest(skill=name):
                self.assertNotIn("setup-project", text)
                self.assertNotIn("setup-required", text)

    def test_the_connected_guide_and_the_lifecycle_protocol_make_no_action_wait_for_setup(self) -> None:
        for relative in ("CONNECTED.md", "LIFECYCLE.md"):
            with self.subTest(file=relative):
                text = read("template", "knowledge", "wiki", relative)
                self.assertIsNone(self.PRECONDITION.search(text), relative)
                self.assertNotIn("setup-required", text)

    def test_only_the_board_review_skill_stops_for_the_unset_board_and_it_changes_nothing(self) -> None:
        text = " ".join(read("template-skills", "board-review", "skill.md").split())
        self.assertIn("If it still carries `<!-- prism:setup-required -->`, the advisory board is not set up", text)
        self.assertIn("change nothing and leave the feature's `advisory-review` as it is", text)

    def test_the_rule_is_stated_once_where_it_lives(self) -> None:
        agents = " ".join(read("template", "AGENTS.md.jinja").split())
        self.assertNotIn("before anything else", agents)
        self.assertIn("Lifecycle work does not wait for setup.", agents)
        self.assertIn("It runs in the agent host on the files (the direct-file workflow), never through a connected board.", agents)
        self.assertIn("Until setup runs, the advisory board is not set up, so `board-review` is unavailable, and a feature that needs a review keeps `advisory-review: pending`.", agents)
        setup = " ".join(read("template-skills", "setup-project", "skill.md").split())
        for stale in ("Required before any other wiki operation", "Run before any other wiki command", "immediately after"):
            self.assertNotIn(stale, setup)
        self.assertIn("Setup runs in the agent host on the files (the direct-file workflow), not through a connected board", setup)
        self.assertIn("Lifecycle work does not wait for setup", setup)
        self.assertIn("keeps `advisory-review: pending`", setup)

    def test_the_placeholder_pages_do_not_tell_the_reader_to_run_setup_first(self) -> None:
        for relative in ("BOARD.md", "PROJECT_FOUNDATION.md"):
            with self.subTest(file=relative):
                text = " ".join(read("template", "knowledge", "wiki", "advisory", relative).split())
                self.assertNotIn("Run that operation first", text)
                self.assertIn("Lifecycle work does not wait", text)
        self.assertIn("<!-- prism:setup-required -->", read("template", "knowledge", "wiki", "advisory", "BOARD.md"))

    def test_the_generated_layers_and_the_packaged_asset_carry_the_setup_statement(self) -> None:
        asset = json.loads(read("prism_cli", "assets", "workflow-v1.json"))
        by_path = {item["path"]: item["content"] for item in asset["files"]}
        for relative in (".agents/skills/setup-project/SKILL.md", ".claude/commands/setup-project.md"):
            with self.subTest(file=relative):
                self.assertIn("Lifecycle work does not wait for setup", " ".join(by_path[relative].split()))
        for relative in (
            "template/.agents/skills/setup-project/SKILL.md.jinja",
            "template/.claude/commands/setup-project.md.jinja",
        ):
            with self.subTest(file=relative):
                self.assertIn("Lifecycle work does not wait for setup", " ".join(read(*relative.split("/")).split()))


class PoIntakeConnectedConfirmationTests(unittest.TestCase):
    """On the connected board the preview is where the human confirms; the direct-file path keeps its stop."""

    def test_the_skill_shows_the_interpretation_with_the_preview_and_keeps_the_direct_file_stop(self) -> None:
        text = " ".join(read("template-skills", "po-intake", "skill.md").split())
        self.assertIn("**Direct-file workflow: STOP.**", text)
        self.assertIn("**Connected board (a Prism MCP connection): do not stop before the preview.**", text)
        self.assertIn("The preview is where the human confirms.", text)
        self.assertIn("show the summary together with the complete preview in one message", text)
        self.assertIn("Call `apply` only after that confirmation", text)
        self.assertNotIn("**STOP. Show the user a summary of your interpretation:**", text)

    def test_the_generated_layers_and_the_packaged_skill_carry_the_rule(self) -> None:
        asset = json.loads(read("prism_cli", "assets", "workflow-v1.json"))
        by_path = {item["path"]: item["content"] for item in asset["files"]}
        for relative in (".agents/skills/po-intake/SKILL.md", ".claude/commands/po-intake.md"):
            with self.subTest(file=relative):
                self.assertIn("do not stop before the preview", " ".join(by_path[relative].split()))
        for relative in ("template/.agents/skills/po-intake/SKILL.md.jinja", "template/.claude/commands/po-intake.md.jinja"):
            with self.subTest(file=relative):
                self.assertIn("do not stop before the preview", " ".join(read(*relative.split("/")).split()))


class ConnectedPreviewConfirmationSkillsTests(unittest.TestCase):
    """Every skill that confirmed before writing confirms at the preview on the connected board, and keeps its stop in the direct-file workflow."""

    INTERPRETATION = {
        "ingest": "**Connected board (a Prism MCP connection): do not stop before the preview.**",
        "design-intake": "**Connected board (a Prism MCP connection): do not stop before the preview.**",
    }
    CONFIRM_AT_PREVIEW = {
        "feature-scope": "Connected board: do not stop before the preview",
        "verify-pages": "On the connected board, do not stop before the preview",
        "ask": "Connected board: do not stop before the preview",
    }

    def normalized(self, *parts: str) -> str:
        return " ".join(read(*parts).split())

    def test_ingest_and_design_intake_split_the_interpretation_stop_by_workflow(self) -> None:
        for name, connected in self.INTERPRETATION.items():
            with self.subTest(skill=name):
                text = self.normalized("template-skills", name, "skill.md")
                self.assertIn("**Direct-file workflow: STOP.**", text)
                self.assertIn(connected, text)
                self.assertIn("The preview is where the human confirms.", text)
                self.assertIn("show the summary together with the complete preview in one message", text)
                self.assertIn("Call `apply` only after that confirmation", text)
                self.assertNotIn("STOP. Show the user a summary of your interpretation", text)

    def test_a_conflict_still_stops_in_both_workflows(self) -> None:
        ingest = self.normalized("template-skills", "ingest", "skill.md")
        self.assertIn("**STOP. Conflict check (before any writes):**", ingest)
        self.assertIn("**Stop - do not write or modify any wiki files.**", ingest)
        design = self.normalized("template-skills", "design-intake", "skill.md")
        self.assertIn("A conflict stops the operation in both workflows", design)
        self.assertIn("do not preview", design)
        self.assertIn("if conflicts require quarantine, stop after reporting them", design)

    def test_the_other_confirming_skills_confirm_at_the_preview_on_the_connected_board(self) -> None:
        for name, phrase in self.CONFIRM_AT_PREVIEW.items():
            with self.subTest(skill=name):
                self.assertIn(phrase, self.normalized("template-skills", name, "skill.md"))

    def test_the_generated_layers_and_the_packaged_skills_carry_the_split(self) -> None:
        asset = json.loads(read("prism_cli", "assets", "workflow-v1.json"))
        by_path = {item["path"]: item["content"] for item in asset["files"]}
        phrases = {**self.INTERPRETATION, **self.CONFIRM_AT_PREVIEW}
        for name, phrase in phrases.items():
            key = "do not stop before the preview"
            for relative in (f".agents/skills/{name}/SKILL.md", f".claude/commands/{name}.md"):
                with self.subTest(file=relative):
                    self.assertIn(key, " ".join(by_path[relative].split()).lower().replace("**", ""))
            for relative in (f"template/.agents/skills/{name}/SKILL.md.jinja", f"template/.claude/commands/{name}.md.jinja"):
                with self.subTest(file=relative):
                    self.assertIn(key, " ".join(read(*relative.split("/")).split()).lower().replace("**", ""))


if __name__ == "__main__":
    unittest.main()
