"""Host command lines, the MCP configuration and the fixed prompt files."""

import json
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import answers, config, hosts  # noqa: E402
from prism_e2e.runner import load_prompt, render_apply_prompt  # noqa: E402

EXE = Path("C:/tools/claude.exe")
UUID = "0b9a87c6-1111-4222-8333-444455556666"
OP = "7d1f1a58-2222-4333-8444-555566667777"


class ClaudeCommandTests(unittest.TestCase):
    def test_sonnet_at_medium_with_only_the_prism_tools(self):
        command = hosts.claude_command(EXE, config.TIERS["full"]["claude"], Path("cfg.json"))
        self.assertEqual(command[:4], [str(EXE), "-p", "--model", "claude-sonnet-5-5"])
        self.assertEqual(command[command.index("--effort") + 1], "medium")
        self.assertIn("--strict-mcp-config", command)
        self.assertEqual(command[command.index("--tools") + 1], "", "no built-in tool")
        self.assertEqual(command[command.index("--allowedTools") + 1], "mcp__prism__*")
        self.assertEqual(command[command.index("--output-format") + 1], "stream-json")
        self.assertNotIn("--max-budget-usd", command)
        self.assertFalse([part for part in command if "max" in part.lower() and "token" in part.lower()], "the output limit is never capped")

    def test_haiku_has_no_effort_flag(self):
        command = hosts.claude_command(EXE, config.TIERS["smoke"]["claude"], Path("cfg.json"))
        self.assertIn("claude-haiku-4-5", command)
        self.assertNotIn("--effort", command)

    def test_mcp_config_reads_the_token_from_the_environment(self):
        text = json.dumps(hosts.claude_mcp_config(8123))
        self.assertIn("http://127.0.0.1:8123/mcp", text)
        self.assertIn("${PRISM_BOARD_TOKEN}", text)
        self.assertEqual(json.loads(text)["mcpServers"]["prism"]["type"], "http")


class CodexCommandTests(unittest.TestCase):
    def test_luna_with_isolated_mcp_overrides_and_stdin_prompt(self):
        command = hosts.codex_command(Path("codex.exe"), config.TIERS["smoke"]["codex"], Path("ws"), Path("last.txt"), 8123)
        self.assertEqual(command[1:4], ["exec", "-m", "gpt-6-luna"])
        self.assertIn("model_reasoning_effort=medium", command)
        self.assertIn('mcp_servers.prism.url="http://127.0.0.1:8123/mcp"', command)
        self.assertIn('mcp_servers.prism.bearer_token_env_var="PRISM_BOARD_TOKEN"', command)
        self.assertEqual(command[-1], "-", "the prompt is read from stdin")
        self.assertEqual(command[command.index("-s") + 1], "read-only")
        self.assertIn("--json", command)

    def test_no_command_line_carries_a_token_or_a_config_file_path_of_the_user(self):
        for tier in config.TIERS.values():
            joined = " ".join(hosts.codex_command(Path("codex.exe"), tier["codex"], Path("ws"), Path("last.txt"), 1))
            self.assertNotIn(".codex", joined)
            self.assertNotIn("Bearer", joined)


class PromptTests(unittest.TestCase):
    def test_every_agent_step_has_a_prompt_and_no_human_step_does(self):
        for step in config.STEPS:
            exists = (config.PROMPTS_DIR / f"{step.id}.txt").is_file()
            self.assertEqual(exists, not step.is_human, step.id)

    def test_preview_prompts_stop_at_the_preview_and_ask_for_its_id(self):
        for step in config.STEPS:
            if step.is_human:
                continue
            text = load_prompt(step.id)
            with self.subTest(step=step.id):
                self.assertIn("Stop at the preview: do not apply it.", text)
                self.assertIn("preview ID", text)
                self.assertIn("Prism MCP tools", text)
                self.assertNotIn("{", text.replace(answers.PLACEHOLDER, ""), "preview prompts are fixed text; only a clarify prompt has the answers placeholder")
                self.assertFalse(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", text), "no ID is baked into a prompt")

    def test_prompts_do_not_name_a_host_or_a_model(self):
        for step in config.STEPS:
            if step.is_human:
                continue
            lowered = load_prompt(step.id).lower()
            for word in ("claude", "codex", "gpt", "anthropic", "openai"):
                self.assertNotIn(word, lowered, f"{step.id} is provider-neutral")

    def test_the_prompts_of_the_api_work_set_follow_the_same_rules(self):
        prompts = sorted((config.API_WORK_FIXTURES_DIR / "prompts").glob("*.txt"))
        self.assertTrue(prompts)
        for path in prompts:
            text = load_prompt(path.stem, config.API_WORK_FIXTURES_DIR)
            self.assertNotEqual(text, load_prompt(path.stem), f"{path.stem} overrides the default prompt")
            with self.subTest(prompt=path.stem):
                self.assertFalse(config.STEPS_BY_ID[path.stem].is_human)
                self.assertIn("Stop at the preview: do not apply it.", text)
                self.assertIn("preview ID", text)
                self.assertIn("Prism MCP tools", text)
                self.assertNotIn("{", text.replace(answers.PLACEHOLDER, ""))
                self.assertFalse(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", text))
                self.assertFalse(re.search(r"[A-Za-z0-9_-]{40,}", text))
                for word in ("claude", "codex", "gpt", "anthropic", "openai"):
                    self.assertNotIn(word, text.lower())

    def test_a_set_without_a_prompt_for_a_step_uses_the_default_prompt(self):
        self.assertEqual(load_prompt("ask", config.API_WORK_FIXTURES_DIR), load_prompt("ask"))
        self.assertIn("API contract page", load_prompt("dev-clarify", config.API_WORK_FIXTURES_DIR))
        self.assertIn("no API contract page", load_prompt("dev-clarify"))

    def test_only_the_clarify_prompts_hold_the_answers_placeholder_once(self):
        for step in config.STEPS:
            if step.is_human:
                continue
            with self.subTest(step=step.id):
                expected = 1 if step.id in answers.CLARIFY_ROLES else 0
                self.assertEqual(load_prompt(step.id).count(answers.PLACEHOLDER), expected)
        self.assertEqual(load_prompt("dev-clarify", config.API_WORK_FIXTURES_DIR).count(answers.PLACEHOLDER), 1)

    def test_the_clarify_prompts_name_no_scripted_answer_of_their_own(self):
        for step_id in answers.CLARIFY_ROLES:
            text = load_prompt(step_id)
            for topics in answers.TOPICS.values():
                for topic in topics:
                    self.assertNotIn(topic.answer, text, f"{step_id} gets its answers from the live questions")

    def test_the_apply_prompt_carries_the_preview_and_a_new_operation_id(self):
        text = render_apply_prompt(config.STEPS_BY_ID["po-specify"], UUID, OP)
        self.assertIn(f"Prism preview {UUID}", text)
        self.assertIn(f"operation ID {OP}", text)
        self.assertIn("Do not create any other preview.", text)
        self.assertNotIn("{", text)

    def test_the_prompts_carry_no_secret_shaped_value(self):
        for path in config.PROMPTS_DIR.glob("*.txt"):
            self.assertFalse(re.search(r"[A-Za-z0-9_-]{40,}", path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    unittest.main()
