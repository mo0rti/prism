"""Run-time answers of the clarify prompts, built from the live open questions, and the installed-CLI script's text decoding."""

import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import answers, config, report as reports, workspace as ws  # noqa: E402
from prism_e2e.runner import Journey, Options, build_preview_prompt, load_prompt  # noqa: E402

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


def topic_answer(role: str, name: str) -> str:
    return next(topic.answer for topic in answers.TOPICS[role] if topic.name == name)


class AnswerForTests(unittest.TestCase):
    def test_each_recorded_question_gets_its_scripted_answer(self):
        cases = {
            "po": {
                "In what format and by what channel does the reviewer receive the summary (for example a downloaded file, text to copy, or an email)?": "A downloaded PDF file.",
                "If the comments do not fit on one page, what should happen?": "One page stays the limit.",
                "Should the summary include the date of the review or the document version?": "The header shows the date the review was finished,",
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
            ("po", "What is the fallback when the user is offline?"),
            ("designer", "What does the empty state look like?"),
            ("designer", "How should the dashboard layout look?"),
            ("po", "What format should the billing report use?"),
            ("po", "In which order should invoices be paid?"),
            ("dev", "How should the billing service deliver invoices?"),
            ("dev", "How should the backend deliver invoices?"),
        ):
            with self.subTest(role=role, question=question):
                self.assertEqual(answers.answer_for(role, question), answers.fallback_for(role))

    def test_po_and_designer_fallbacks_remain_out_of_scope(self):
        self.assertEqual(answers.FALLBACK, "Out of scope for this release: the feature does not include it.")
        self.assertEqual(answers.fallback_for("po"), answers.FALLBACK)
        self.assertEqual(answers.fallback_for("designer"), answers.FALLBACK)

    def test_dev_fallback_names_the_technical_design_page(self):
        self.assertEqual(answers.fallback_for("dev"), "The technical design page settles this; build it as that page says.")

    def test_every_role_fallback_contains_no_deferral(self):
        for role in answers.CLARIFY_ROLES.values():
            fallback = answers.fallback_for(role)
            with self.subTest(role=role):
                for word in ("later", "defer", "decide", "TBD"):
                    self.assertNotIn(word.lower(), fallback.lower())

    def test_every_real_host_question_gets_the_intended_topic(self):
        cases = (
            ("po", "What export file format should the reviewer receive?", "format and channel"),
            ("po", "How should a review with comments too long for one page meet the one-page summary requirement?", "overflow"),
            ("po", "Does the summary have to be available in more than one language?", "language"),
            ("designer", "What should the one-page summary layout and export interaction look like?", "export control and summary layout"),
            ("dev", "How should the backend deliver the export to the reviewer, and what technical constraints affect generation?", "delivery and generation"),
            ("po", "What file format should the exported summary use?", "format and channel"),
            ("po", "Which review states count as finished and permit export?", "finished review and export eligibility"),
            ("po", "Does the summary have to be available in more than one language?", "language"),
            ("po", "What file format must the exported summary use?", "format and channel"),
            ("po", "What determines that a review is finished and eligible for export?", "finished review and export eligibility"),
            ("po", "How must the one-page summary handle comments that exceed one page without losing the reviewer's comments?", "overflow"),
            ("po", "Does the summary have to be available in more than one language?", "language"),
            ("designer", "How should the document title, reviewer, decision and comments be arranged on the one-page summary?", "export control and summary layout"),
        )
        self.assert_topics(cases)

    def assert_topics(self, cases):
        for role, question, name in cases:
            with self.subTest(role=role, question=question):
                answer = answers.answer_for(role, question)
                self.assertNotEqual(answer, answers.FALLBACK)
                self.assertEqual(answer, topic_answer(role, name))

    def test_domain_variants_go_to_the_intended_topic(self):
        self.assert_topics((
            ("po", "When may a review be exported?", "finished review and export eligibility"),
            ("po", "Can we export reviews still in progress?", "finished review and export eligibility"),
            ("po", "Which decisions permit export?", "finished review and export eligibility"),
            ("po", "Who may export a finished review?", "export access and comment ownership"),
            ("po", "Whose comments does the one-page summary contain?", "export access and comment ownership"),
            ("po", "What should the header of a finished review summary show?", "header"),
            ("po", "What date format should the header use?", "header"),
            ("po", "Should the header show the review completion date?", "header"),
            ("po", "Should the document title in the summary be translated?", "language"),
            ("po", "Should comments be sorted by severity or in the order they were left?", "comment order"),
            ("po", "What should the one-page summary show when the reviewer left no comments?", "no comments"),
            ("po", "Can a review without comments be exported?", "no comments"),
            ("po", "How do we fit very long comments in the summary?", "overflow"),
            ("designer", "Where should the export button appear?", "export control and summary layout"),
            ("designer", "How should we arrange the summary?", "export control and summary layout"),
            ("designer", "What should the summary look like?", "export control and summary layout"),
            ("designer", "How should the summary appear?", "export control and summary layout"),
            ("designer", "What structure and order should the summary use?", "export control and summary layout"),
            ("dev", "How is the PDF generated?", "delivery and generation"),
            ("dev", "How should we deliver the summary?", "delivery and generation"),
            ("dev", "Is the PDF stored or generated on request?", "delivery and generation"),
            ("dev", "Does PDF generation need a new service or the existing stack?", "delivery and generation"),
            ("dev", "What time and size limits apply to PDF generation?", "generation constraints"),
            ("dev", "What timeout applies to PDF generation?", "generation constraints"),
            ("dev", "What happens when generation fails?", "generation failure"),
            ("dev", "How should errors during export be handled?", "generation failure"),
            ("dev", "What happens if PDF generation times out?", "generation failure"),
            ("dev", "How should we handle a PDF generation timeout?", "generation failure"),
            ("dev", "Does the platform record the decision, reviewer and per-reviewer comments in a form that supports this export?", "review data and eligibility"),
            ("dev", "How does the backend identify a finished review and the requesting reviewer's comments for export?", "review data and eligibility"),
            ("dev", "How do we authorize export of a finished review?", "review data and eligibility"),
            ("dev", "Whose comments are read when the PDF is generated?", "review data and eligibility"),
            ("dev", "How do permissions affect the PDF download?", "review data and eligibility"),
            ("dev", "How does the backend generate a PDF for a finished review?", "delivery and generation"),
        ))

    def test_eligibility_and_ownership_answers_preserve_the_brief(self):
        eligibility = topic_answer("po", "finished review and export eligibility")
        self.assertIn("once its reviewer records a decision: approved, changes requested or rejected", eligibility)
        self.assertIn("never offered while the review is in progress", eligibility)
        ownership = topic_answer("po", "export access and comment ownership")
        self.assertIn("Only the signed-in reviewer", ownership)
        self.assertIn("only that reviewer's comments", ownership)

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
                self.assertNotIn(answers.fallback_for(role), prompt, "every recorded question has a scripted answer")
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
                '- Question 1 ("In what format is the summary delivered (for example PDF, plain text or email body)?"): ' + topic_answer("po", "format and channel"),
                '- Question 2 ("What should the summary show when the reviewer left no comments?"): ' + topic_answer("po", "no comments"),
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
            '- Question 4 ("Does the platform record the decision, reviewer and per-reviewer comments in a form that supports this export?"): ' + topic_answer("dev", "review data and eligibility"),
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


class FallbackNoteTests(unittest.TestCase):
    def test_each_fallback_is_noted_before_launch_even_when_the_launch_fails(self):
        for step_id, role in answers.CLARIFY_ROLES.items():
            with self.subTest(step=step_id):
                feature = feature_with(
                    "## Open questions\n| # | Question | Owner | Status |\n|---|----------|-------|--------|\n"
                    f"| 9 | What about billing? | {role} | open |\n"
                    f"| 13 | Do we need notifications? | {role} | open |\n"
                    f"| 15 | What about reporting? | {role} | resolved: No. |\n"
                    "| 21 | What about subscriptions? | qa | open |\n"
                )
                journey = Journey(Options(tier="smoke", out=Path("."), steps=[step_id], hosts=["claude"]))
                journey.env = SimpleNamespace(workspace=Path("."))
                journey.board = object()
                result = reports.StepResult(step=step_id, kind="agent", host="claude")
                expected = [
                    f'{step_id}: fallback answer for question 9 ("What about billing?"): {answers.fallback_for(role)}',
                    f'{step_id}: fallback answer for question 13 ("Do we need notifications?"): {answers.fallback_for(role)}',
                ]

                def failed_launch(*args):
                    self.assertEqual(result.notes, expected)
                    self.assertEqual(args[2].count(answers.fallback_for(role)), 2)
                    raise RuntimeError("host launch failed")

                with patch.object(ws, "read_feature", return_value=feature), patch.object(Journey, "_launch", side_effect=failed_launch) as launch:
                    with self.assertRaisesRegex(RuntimeError, "host launch failed"):
                        journey.run_agent_step(config.STEPS_BY_ID[step_id], 3, "claude", result)
                launch.assert_called_once()
                report = reports.build_report({}, [result], [], "smoke")
                self.assertEqual(report["steps"][0]["notes"], expected)

    def test_scripted_answers_add_no_fallback_note(self):
        for step_id, role, state in (("po-clarify", "po", "ask"), ("design-clarify", "designer", "design-start"), ("dev-clarify", "dev", "design-handoff")):
            with self.subTest(step=step_id):
                journey = Journey(Options(tier="smoke", out=Path("."), steps=[step_id], hosts=["claude"]))
                journey.env = SimpleNamespace(workspace=Path("."))
                journey.board = object()
                result = reports.StepResult(step=step_id, kind="agent", host="claude")
                feature = fixture_feature(state)
                self.assertTrue(feature.open_questions(role))
                with patch.object(ws, "read_feature", return_value=feature), patch.object(Journey, "_launch", side_effect=RuntimeError("host launch failed")):
                    with self.assertRaisesRegex(RuntimeError, "host launch failed"):
                        journey.run_agent_step(config.STEPS_BY_ID[step_id], 3, "claude", result)
                self.assertEqual(result.notes, [])


class TechLeadDecisionTests(unittest.TestCase):
    def test_both_fixture_sets_receive_the_technical_decisions(self):
        for fixture_set in (None, config.API_WORK_FIXTURES_DIR):
            with self.subTest(fixture_set=fixture_set):
                prompt = load_prompt("tech-design-done", fixture_set)
                for decision in (
                    "My technical decisions:",
                    "generates the PDF on request from the stored review",
                    "same response as a file download",
                    "No generated file is stored or cached",
                    "approved, changes requested or rejected",
                    "an in-progress review cannot be exported",
                    "only the requesting reviewer's comments",
                    "backend's existing stack, with no new service",
                    "5 seconds and a PDF of at most 1 MiB",
                    "no PDF or partial download",
                    "every acceptance criterion at unit and service level",
                ):
                    self.assertIn(decision, prompt)


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
