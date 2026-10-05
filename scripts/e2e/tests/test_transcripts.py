"""Transcript parsing: tool calls, error codes, preview IDs, model, effort and usage."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import transcripts as t  # noqa: E402

PREVIEW_ID = "e2b978ce-89b3-4afa-a0cd-027a8886e5fc"
OTHER_ID = "774c1df9-64e5-4eab-b7ff-49f5c9fcdd2d"


def lines(*events):
    return "\n".join(json.dumps(event) for event in events) + "\n"


def tool_use(identifier, name):
    return {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [{"type": "tool_use", "id": identifier, "name": name, "input": {}}]}}


def claude_stream():
    error_text = "Error executing tool preview_skill: missing_read_revisions: Preview requires current digests for the reviewed sources: a.md"
    ok_content = [{"type": "text", "text": json.dumps({"preview_id": PREVIEW_ID, "applicable": True})}]
    return lines(
        {"type": "system", "subtype": "init", "session_id": "sess-1", "model": "claude-sonnet-5-5"},
        tool_use("u1", "mcp__prism__discover"),
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1", "content": '{"ok": true}'}]}},
        tool_use("u2", "mcp__prism__preview_skill"),
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u2", "is_error": True, "content": error_text}]}},
        tool_use("u3", "mcp__prism__preview_skill"),
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u3", "content": ok_content}]}},
        {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": f"Preview {PREVIEW_ID} is ready."}]}},
        {
            "type": "result", "subtype": "success", "is_error": False, "result": f"Preview {PREVIEW_ID} is ready.", "total_cost_usd": 0.5,
            "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 40,
                      "output_tokens_details": {"thinking_tokens": 7}},
            "modelUsage": {"claude-sonnet-5-5": {}, "claude-haiku-4-5": {}},
        },
    )


def codex_stream():
    path_error = "Error executing tool read_workspace: path_not_approved: Read access is limited."
    return lines(
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "tool": "read_workspace", "status": "failed", "error": None,
                                            "result": {"content": [{"type": "text", "text": path_error}], "structured_content": None}}},
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "tool": "preview_skill", "status": "completed", "error": None,
                                            "result": {"content": [{"type": "text", "text": "summary line"}], "structured_content": {"preview_id": OTHER_ID}}}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": f"Done. Preview ID {OTHER_ID}"}},
        {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 900, "cache_write_input_tokens": 0,
                                             "output_tokens": 50, "reasoning_output_tokens": 5}},
    )


class ClaudeTests(unittest.TestCase):
    def test_tool_calls_errors_and_the_preview_id(self):
        parsed = t.parse_claude_stream(claude_stream())
        self.assertEqual([call.name for call in parsed.calls], ["discover", "preview_skill", "preview_skill"])
        self.assertEqual([call.ok for call in parsed.preview_calls], [False, True])
        self.assertEqual(parsed.preview_calls[0].error_code, "missing_read_revisions")
        self.assertEqual(parsed.successful_preview_ids(), [PREVIEW_ID])
        self.assertEqual(t.first_reported_preview_id(parsed.final_message, parsed.successful_preview_ids()), PREVIEW_ID)

    def test_models_come_from_messages_and_billed_models_stay_separate(self):
        parsed = t.parse_claude_stream(claude_stream())
        self.assertEqual(parsed.models, {"claude-sonnet-5-5"})
        self.assertEqual(parsed.billed_models, ["claude-haiku-4-5", "claude-sonnet-5-5"])
        self.assertEqual(parsed.session_id, "sess-1")

    def test_usage_and_cost_are_the_hosts_own_report(self):
        parsed = t.parse_claude_stream(claude_stream())
        self.assertEqual(parsed.cost_usd, 0.5)
        self.assertEqual(
            parsed.usage.as_dict(),
            {"input_tokens": 10, "cached_input_tokens": 300, "cache_creation_tokens": 40, "output_tokens": 20, "reasoning_tokens": 7},
        )
        self.assertTrue(parsed.complete)

    def test_a_killed_run_has_no_closing_event_and_keeps_the_last_text(self):
        partial = "\n".join(claude_stream().splitlines()[:-1])
        parsed = t.parse_claude_stream(partial)
        self.assertFalse(parsed.complete)
        self.assertIsNone(parsed.usage)
        self.assertIn(PREVIEW_ID, parsed.final_message)

    def test_non_json_lines_are_ignored(self):
        parsed = t.parse_claude_stream("warning: something\n" + claude_stream())
        self.assertEqual(len(parsed.calls), 3)


class CodexTests(unittest.TestCase):
    def test_calls_errors_ids_and_final_message(self):
        parsed = t.parse_codex_stream(codex_stream())
        self.assertEqual([call.name for call in parsed.calls], ["read_workspace", "preview_skill"])
        self.assertEqual(parsed.calls[0].error_code, "path_not_approved")
        self.assertEqual(parsed.successful_preview_ids(), [OTHER_ID])
        self.assertIn(OTHER_ID, parsed.final_message)
        self.assertEqual(parsed.session_id, "thread-1")

    def test_the_last_message_file_wins_over_the_stream(self):
        parsed = t.parse_codex_stream(codex_stream(), last_message="From the file")
        self.assertEqual(parsed.final_message, "From the file")

    def test_usage_has_no_cost(self):
        parsed = t.parse_codex_stream(codex_stream())
        self.assertIsNone(parsed.cost_usd)
        self.assertEqual(parsed.usage.input_tokens, 1000)
        self.assertEqual(parsed.usage.cached_input_tokens, 900)
        self.assertEqual(parsed.usage.reasoning_tokens, 5)


class ErrorCodeTests(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(t.error_code("Error executing tool apply: stale_read_revision: changed"), "stale_read_revision")
        self.assertEqual(t.error_code("something else"), "error")
        self.assertEqual(t.error_code(None), "error")


class SessionRecordTests(unittest.TestCase):
    def test_claude_effort_and_models_are_read_from_the_session_file(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            project = base / "projects" / "some-project"
            project.mkdir(parents=True)
            records = [
                {"type": "user", "message": {"role": "user", "content": "hi"}, "effort": "medium"},
                {"type": "assistant", "message": {"model": "claude-sonnet-5-5-20260901"}, "perTurnEffort": "medium"},
            ]
            (project / "sess-1.jsonl").write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            self.assertEqual(t.claude_session_efforts("sess-1", base), {"medium"})
            self.assertEqual(t.claude_session_models("sess-1", base), {"claude-sonnet-5-5-20260901"})
            self.assertEqual(t.claude_session_efforts("missing", base), set())
            self.assertEqual(t.claude_session_efforts(None, base), set())

    def test_a_claude_session_without_effort_records_none(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "projects" / "p").mkdir(parents=True)
            record = {"type": "assistant", "message": {"model": "claude-haiku-4-5-20251001"}}
            (base / "projects" / "p" / "s.jsonl").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(t.claude_session_efforts("s", base), set())

    def test_codex_model_and_effort_are_read_from_turn_context(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            day = base / "sessions" / "2026" / "10" / "05"
            day.mkdir(parents=True)
            settings = {"settings": {"reasoning_effort": "medium"}}
            context = {"type": "turn_context", "payload": {"model": "gpt-6-luna", "effort": "medium", "collaboration_mode": settings}}
            other = {"type": "event_msg", "payload": {"model": "ignored"}}
            (day / "rollout-2026-10-05T11-00-00-thread-1.jsonl").write_text(json.dumps(other) + "\n" + json.dumps(context) + "\n", encoding="utf-8")
            self.assertEqual(t.codex_rollout_model_effort("thread-1", base), ({"gpt-6-luna"}, {"medium"}))
            self.assertEqual(t.codex_rollout_model_effort("nope", base), (set(), set()))


class ModelMatchTests(unittest.TestCase):
    def test_exact_and_dated_builds_match(self):
        self.assertTrue(t.model_matches("claude-haiku-4-5", ["claude-haiku-4-5-20251001", "claude-haiku-4-5"]))
        self.assertTrue(t.model_matches("gpt-6-luna", ["gpt-6-luna"]))

    def test_another_model_or_none_does_not_match(self):
        self.assertFalse(t.model_matches("claude-haiku-4-5", ["claude-haiku-4-5-20251001", "claude-sonnet-5-5"]))
        self.assertFalse(t.model_matches("gpt-6-luna", ["gpt-6.1-sol"]))
        self.assertFalse(t.model_matches("gpt-6-luna", []))
        self.assertFalse(t.model_matches("claude-haiku-4-5", ["claude-haiku-4-5-latest"]))


class CollapseModelsTests(unittest.TestCase):
    def test_an_alias_is_dropped_when_its_dated_build_is_present(self):
        self.assertEqual(t.collapse_models(["claude-haiku-4-5", "claude-haiku-4-5-20251001"]), ["claude-haiku-4-5-20251001"])
        self.assertEqual(t.collapse_models(["claude-haiku-4-5"]), ["claude-haiku-4-5"])
        self.assertEqual(t.collapse_models(["gpt-6-luna", "", "gpt-6-luna"]), ["gpt-6-luna"])
        self.assertEqual(t.collapse_models(["claude-sonnet-5-5", "claude-haiku-4-5-20251001"]), ["claude-haiku-4-5-20251001", "claude-sonnet-5-5"])


class ReportedIdTests(unittest.TestCase):
    def test_only_an_id_from_the_agents_own_preview_calls_counts(self):
        message = f"Old {OTHER_ID} and new {PREVIEW_ID}"
        self.assertEqual(t.first_reported_preview_id(message, [PREVIEW_ID]), PREVIEW_ID)
        self.assertIsNone(t.first_reported_preview_id("no id here", [PREVIEW_ID]))
        self.assertIsNone(t.first_reported_preview_id(f"made up {OTHER_ID}", [PREVIEW_ID]))


if __name__ == "__main__":
    unittest.main()
