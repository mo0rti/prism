"""Run-time answers of the clarify prompts, built from the live open questions, and the installed-CLI script's text decoding."""

import ast
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import answers, config, workspace as ws  # noqa: E402
from prism_e2e.runner import build_preview_prompt, load_prompt  # noqa: E402

FEATURE_PAGE = "knowledge/wiki/features/F-001-review-summary-export.md"
CHECK_INSTALLED_CLI = config.REPO_ROOT / "scripts" / "check-installed-cli.py"

# A question set a live po-intake wrote, which differs from the recorded fixture.
LIVE_TABLE = """## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | In what format is the summary delivered (for example PDF, plain text or email body)? | po | open |
| 2 | What should the summary show when the reviewer left no comments? | po | open |
| 3 | Where in the review screen does the reviewer choose export? | designer | open |
| 4 | Does the platform record the decision, reviewer and per-reviewer comments in a form that supports this export? | dev | open |
| 5 | Does the summary have to be available in more than one language? | po | open |
| 6 | Who may see the summary? | po | resolved: The reviewer who wrote it. |
"""


def feature_with(table: str) -> ws.FeatureState:
    text = f"---\nid: F-001\nstatus: raw\nowner: po\n---\n\n## Summary\nText.\n\n{table}\n## App scope\n- **backend**: x\n"
    return ws.FeatureState("raw", "po", "raw", "po", ws.parse_questions(text), text)


def fixture_feature(step: str) -> ws.FeatureState:
    """The feature page recorded after ``step``."""

    text = (config.FIXTURES_DIR / step / FEATURE_PAGE).read_text(encoding="utf-8")
    return ws.FeatureState("", "", None, None, ws.parse_questions(text), text)


class AnswerForTests(unittest.TestCase):
    def test_each_recorded_question_gets_its_scripted_answer(self):
        cases = {
            "po": {
                "In what format and by what channel does the reviewer receive the summary (for example a downloaded file, text to copy, or an email)?": "A downloaded PDF file.",
                "If the comments do not fit on one page, what should happen?": "One page stays the limit.",
                "Should the summary include the date of the review or the document version?": "The header shows the date the review was finished.",
                "Does the summary have to be available in more than one language?": "No. English only",
            },
            "designer": {"Where does the export control appear and what does the summary look like?": 'One "Export summary" button'},
            "dev": {"Which app presents the export control, given that backend is the only app declared for this project?": "The backend serves the export"},
        }
        for role, questions in cases.items():
            for question, start in questions.items():
                with self.subTest(role=role, question=question):
                    self.assertTrue(answers.answer_for(role, question).startswith(start))

    def test_a_question_of_another_topic_gets_the_fallback_decision(self):
        for role, question in (
            ("po", "What should the summary show when the reviewer left no comments?"),
            ("po", "What is the fallback when the user is offline?"),
            ("po", "What date format should the header use?"),
            ("designer", "What does the empty state look like?"),
            ("dev", "Does the platform record the decision, reviewer and per-reviewer comments in a form that supports this export?"),
        ):
            with self.subTest(role=role, question=question):
                self.assertEqual(answers.answer_for(role, question), answers.FALLBACK)

    def test_the_fallback_is_a_plain_fixed_decision(self):
        self.assertEqual(answers.FALLBACK, "Not needed for this release; decide later.")

    def test_a_role_without_scripted_topics_gets_the_fallback(self):
        self.assertEqual(answers.answer_for("unknown", "Anything?"), answers.FALLBACK)


class PreviewPromptTests(unittest.TestCase):
    def test_the_clarify_roles_are_the_three_clarify_steps(self):
        self.assertEqual(answers.CLARIFY_ROLES, {"po-clarify": "po", "design-clarify": "designer", "dev-clarify": "dev"})
        for step_id in answers.CLARIFY_ROLES:
            self.assertFalse(config.STEPS_BY_ID[step_id].is_human)

    def test_the_recorded_questions_are_answered_with_their_scripted_answers(self):
        for step_id, role, state in (("po-clarify", "po", "ask"), ("design-clarify", "designer", "design-start"), ("dev-clarify", "dev", "design-handoff")):
            feature = fixture_feature(state)
            prompt = build_preview_prompt(step_id, None, feature)
            open_questions = feature.open_questions(role)
            with self.subTest(step=step_id):
                self.assertTrue(open_questions)
                self.assertNotIn("{", prompt)
                self.assertNotIn(answers.FALLBACK, prompt, "every recorded question has a scripted answer")
                for question in open_questions:
                    self.assertIn(f'- Question {question.number} ("{question.text}"): {answers.answer_for(role, question.text)}', prompt)

    def test_a_different_question_set_lists_each_open_question_of_the_role_with_its_answer(self):
        feature = feature_with(LIVE_TABLE)
        prompt = build_preview_prompt("po-clarify", None, feature)
        self.assertNotIn("{", prompt)
        lines = [line for line in prompt.split("\n") if line.startswith("- Question")]
        self.assertEqual(
            lines,
            [
                '- Question 1 ("In what format is the summary delivered (for example PDF, plain text or email body)?"): ' + answers.TOPICS["po"][0].answer,
                '- Question 2 ("What should the summary show when the reviewer left no comments?"): ' + answers.FALLBACK,
                '- Question 5 ("Does the summary have to be available in more than one language?"): No. English only; no other language is needed for this feature.',
            ],
        )
        self.assertNotIn("Question 3", prompt, "the designer's question is not the product owner's")
        self.assertNotIn("Question 4", prompt)
        self.assertNotIn("Question 6", prompt, "a resolved question is not listed")

    def test_the_designer_and_developer_questions_of_a_different_set(self):
        feature = feature_with(LIVE_TABLE)
        designer = build_preview_prompt("design-clarify", None, feature)
        self.assertIn('- Question 3 ("Where in the review screen does the reviewer choose export?"): One "Export summary" button', designer)
        developer = build_preview_prompt("dev-clarify", None, feature)
        self.assertIn(
            '- Question 4 ("Does the platform record the decision, reviewer and per-reviewer comments in a form that supports this export?"): ' + answers.FALLBACK,
            developer,
        )
        self.assertNotIn("Question 1", developer)

    def test_a_role_without_an_open_question_gets_a_note_and_no_answer(self):
        feature = feature_with("## Open questions\n| # | Question | Owner | Status |\n|---|----------|-------|--------|\n| 1 | Done? | po | resolved: yes |\n| 2 | Design? | designer | open |\n")
        prompt = build_preview_prompt("po-clarify", None, feature)
        self.assertNotIn("{", prompt)
        self.assertIn(answers.NO_QUESTIONS, prompt)
        self.assertNotIn("- Question", prompt)
        self.assertEqual(build_preview_prompt("dev-clarify", None, None).count(answers.NO_QUESTIONS), 1, "no feature page means no open question")

    def test_the_answers_are_the_owners_reply_and_the_prompt_keeps_its_fixed_text(self):
        prompt = build_preview_prompt("po-clarify", None, feature_with(LIVE_TABLE))
        template = load_prompt("po-clarify")
        before, after = template.split(answers.PLACEHOLDER)
        self.assertTrue(prompt.startswith(before))
        self.assertTrue(prompt.endswith(after))
        self.assertIn("Paste it exactly as written", prompt)
        self.assertIn("Stop at the preview: do not apply it.", prompt)

    def test_the_api_work_set_prompt_is_filled_the_same_way(self):
        prompt = build_preview_prompt("dev-clarify", config.API_WORK_FIXTURES_DIR, fixture_feature("design-handoff"))
        self.assertIn("This feature already has its API contract page", prompt)
        self.assertIn("- Question 5", prompt)
        self.assertNotIn("{", prompt)

    def test_a_step_that_is_not_a_clarify_step_is_unchanged(self):
        feature = feature_with(LIVE_TABLE)
        for step_id in ("po-intake", "ask", "po-specify", "design-handoff", "dev-done"):
            with self.subTest(step=step_id):
                self.assertEqual(build_preview_prompt(step_id, None, feature), load_prompt(step_id))


class InstalledCliScriptTests(unittest.TestCase):
    """The pre-release script decodes child output as UTF-8, so a Windows cp1252 console does not drop it."""

    def test_every_text_mode_subprocess_run_passes_encoding_and_errors(self):
        tree = ast.parse(CHECK_INSTALLED_CLI.read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
        ]
        self.assertTrue(calls)
        for call in calls:
            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            if "text" not in keywords and "universal_newlines" not in keywords:
                continue
            with self.subTest(line=call.lineno):
                self.assertIsInstance(keywords.get("encoding"), ast.Constant)
                self.assertEqual(keywords["encoding"].value, "utf-8")
                self.assertIsInstance(keywords.get("errors"), ast.Constant)
                self.assertEqual(keywords["errors"].value, "replace")


if __name__ == "__main__":
    unittest.main()
