"""Report building: per-step rows, totals per host and tier, redaction of the rendered files."""

import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import report  # noqa: E402
from prism_e2e.tokens import TokenRegistry  # noqa: E402

USAGE_A = {"input_tokens": 10, "cached_input_tokens": 100, "cache_creation_tokens": 5, "output_tokens": 20, "reasoning_tokens": 3}
USAGE_B = {"input_tokens": 1, "cached_input_tokens": 2, "cache_creation_tokens": 0, "output_tokens": 4, "reasoning_tokens": 0}


def sample_results():
    one = report.StepResult(step="po-intake", kind="agent", host="claude", status="passed", expected_model="claude-haiku-4-5")
    one.models, one.efforts = ["claude-haiku-4-5-20251001"], []
    one.preview_attempts, one.first_attempt_success = 1, True
    one.apply_state, one.elapsed_s = "applied", 40.0
    one.add_usage(USAGE_A, 0.25)
    one.add_usage(USAGE_B, 0.05)
    two = report.StepResult(step="po-clarify", kind="agent", host="claude", status="failed", reason="check failed: stage_and_owner")
    two.preview_attempts, two.preview_error_codes, two.first_attempt_success = 3, ["missing_read_revisions", "clarify_scope_exceeded"], False
    two.add_check("stage_and_owner", False, "expected raw/po, found raw/designer")
    two.elapsed_s = 100.0
    two.add_usage(USAGE_B, 0.1)
    three = report.StepResult(step="po-specify", kind="agent", host="codex", status="passed")
    three.models, three.efforts = ["gpt-6-luna"], ["medium"]
    three.preview_attempts, three.first_attempt_success, three.elapsed_s = 1, True, 60.0
    three.add_usage(USAGE_A, None)
    four = report.StepResult(step="po-handoff", kind="human", host="browser", status="passed", apply_state="applied", elapsed_s=3.0)
    five = report.StepResult(step="design-start", kind="human", host="browser", status="skipped", reason="dependency failed: po-clarify")
    return [one, two, three, four, five]


class TotalsTests(unittest.TestCase):
    def test_totals_group_by_host_and_sum_usage_and_cost(self):
        rows = {row["host"]: row for row in report.compute_totals(sample_results(), "smoke")}
        claude = rows["claude"]
        self.assertEqual((claude["steps"], claude["passed"], claude["failed"], claude["skipped"]), (2, 1, 1, 0))
        self.assertEqual(claude["preview_attempts"], 4)
        self.assertEqual(claude["first_attempt_successes"], 1)
        self.assertEqual(claude["elapsed_s"], 140.0)
        self.assertEqual(claude["usage"]["input_tokens"], 10 + 1 + 1)
        self.assertEqual(claude["usage"]["cached_input_tokens"], 100 + 2 + 2)
        self.assertAlmostEqual(claude["cost_usd"], 0.4)
        self.assertEqual(claude["tier"], "smoke")

    def test_a_host_that_reports_no_cost_has_none(self):
        rows = {row["host"]: row for row in report.compute_totals(sample_results(), "smoke")}
        self.assertIsNone(rows["codex"]["cost_usd"])
        self.assertFalse(rows["codex"]["cost_reported"])
        self.assertEqual(rows["codex"]["usage"]["output_tokens"], 20)

    def test_browser_steps_have_no_usage(self):
        rows = {row["host"]: row for row in report.compute_totals(sample_results(), "smoke")}
        self.assertEqual((rows["browser"]["steps"], rows["browser"]["passed"], rows["browser"]["skipped"]), (2, 1, 1))
        self.assertIsNone(rows["browser"]["usage"])


class RenderTests(unittest.TestCase):
    def build(self):
        run = {"tier": "smoke", "verdict": "failed", "verdict_reason": "steps not passed: po-clarify", "steps_selected": ["po-intake"], "hosts": ["claude", "codex"],
               "timeout_s": 600, "started": "2026-10-05T09:00:00+00:00", "elapsed_s": 300.0, "prism_version": "0.2.0", "wheel": "w.whl", "wheel_sha256": "abc",
               "claude_version": "2.1.286 (Claude Code)", "codex_version": "codex-cli 0.159.0", "token_scan": "clean (3 tokens checked in every saved file)", "cleanup": "done"}
        seeds = [{"through": "po-intake", "files": ["a", "b"], "lint_errors": 0, "lint_ok": True}]
        return report.build_report(run, sample_results(), seeds, "smoke")

    def test_markdown_has_the_per_step_table_failures_seeds_and_totals(self):
        text = report.render_markdown(self.build())
        self.assertIn("| 1 | po-intake | claude | claude-haiku-4-5-20251001 |", text)
        self.assertIn("none set", text, "an agent step with no effort setting says so")
        self.assertIn("missing_read_revisions, clarify_scope_exceeded", text)
        self.assertIn("check `stage_and_owner` failed: expected raw/po, found raw/designer", text)
        self.assertIn("dependency failed: po-clarify", text)
        self.assertIn("State after `po-intake` from the recorded fixtures: 2 file(s)", text)
        self.assertIn("## Totals", text)
        self.assertIn("$0.4000", text)
        self.assertIn("not reported", text)
        self.assertIn("Verdict: **failed** (steps not passed: po-clarify)", text)
        self.assertIn("- Fixtures: default", text)

    def test_the_report_names_a_fixture_set(self):
        data = self.build()
        data["run"]["fixtures"] = "D:\\sets\\api-work"
        self.assertIn("- Fixtures: D:\\sets\\api-work", report.render_markdown(data))

    def test_skipped_steps_show_no_effort_previews_time_or_cost(self):
        text = report.render_markdown(self.build())
        row = next(line for line in text.splitlines() if "| design-start |" in line)
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        self.assertEqual(cells[1], "design-start")
        self.assertEqual(cells[5], "skipped (dependency failed: po-clarify)")
        self.assertEqual(cells[4], "-")
        self.assertEqual(cells[6], "n/a", "a human step has no previews")
        self.assertEqual(cells[10], "-")

    def test_json_round_trips_with_one_entry_per_step(self):
        data = json.loads(report.render_json(self.build()))
        self.assertEqual([step["step"] for step in data["steps"]], ["po-intake", "po-clarify", "po-specify", "po-handoff", "design-start"])
        self.assertEqual(data["steps"][1]["checks"][0]["name"], "stage_and_owner")
        self.assertEqual({row["host"] for row in data["totals"]}, {"claude", "codex", "browser"})

    def test_rendered_files_pass_through_the_redactor(self):
        tokens = TokenRegistry()
        secret = "S" * 12 + "-secret-token-" + "7" * 8
        tokens.add("human", secret)
        data = self.build()
        data["steps"][0]["notes"] = [f"host said {secret}"]
        data["steps"][0]["status"] = "failed"
        for text in (report.render_markdown(data, tokens.redact), report.render_json(data, tokens.redact)):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
