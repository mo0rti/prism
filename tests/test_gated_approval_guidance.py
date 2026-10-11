"""The standard guidance describes one approval flow: an agent proposes a gated action, a role-holding human approves it in the board.

No standard wiki file, skill or instruction file may say the board has no approval queue for agents, and none may tell an
agent to apply a gated preview. The text the MCP service sends agrees with `CONNECTED.md`, `SCHEMA.md` and `ACTIONS.md`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from prism_cli.board_mcp import SERVER_INSTRUCTIONS

ROOT = Path(__file__).resolve().parents[1]
# The wording that denies the proposal queue, in the forms the guidance used.
NO_QUEUE = re.compile(r"(?i)\b(?:is\s+not\s+a|isn't\s+a|no|adds?\s+no|has\s+no|not\s+a|without\s+a|or\s+create\s+a)\s+(?:second\s+|extra\s+)?(?:board\s+)?approval\s+(?:queue|stage)")
GATED_APPLY = re.compile(r"(?i)\bgated\b[^.\n]*\bapply\b|\bapply\b[^.\n]*\bgated\b")
REFUSAL_WORDS = re.compile(r"(?i)\b(never|not|refus|cannot|waits?|approval_required)")


def guidance_files() -> list[Path]:
    wiki = sorted((ROOT / "template/knowledge/wiki").glob("*.md"))
    skills = sorted((ROOT / "template-skills").glob("*/*.md"))
    instructions = [
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "template/AGENTS.md.jinja",
        ROOT / "template/docs/ai-agents.md.jinja",
        ROOT / "docs/agent-hosts.md",
        ROOT / "docs/prism-core-workflow-plan.md",
    ]
    return [path for path in [*wiki, *skills, *instructions] if path.is_file()]


class GatedApprovalGuidanceTests(unittest.TestCase):
    def test_no_guidance_denies_the_proposal_queue(self) -> None:
        offenders = []
        for path in guidance_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if NO_QUEUE.search(line):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()[:120]}")
        self.assertEqual([], offenders)

    def test_no_guidance_tells_an_agent_to_apply_a_gated_preview(self) -> None:
        offenders = []
        for path in guidance_files():
            text = path.read_text(encoding="utf-8")
            for sentence in re.split(r"(?<=[.!?])\s+|\n\s*\n", text):
                if GATED_APPLY.search(sentence) and not REFUSAL_WORDS.search(sentence):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}: {' '.join(sentence.split())[:140]}")
        self.assertEqual([], offenders)

    def test_the_connected_guide_the_schema_and_the_actions_describe_the_same_flow(self) -> None:
        connected = " ".join((ROOT / "template/knowledge/wiki/CONNECTED.md").read_text(encoding="utf-8").split())
        self.assertIn("The agent proposes it with `preview_skill` and stops there", connected)
        self.assertIn("approves or declines it in the board's Proposals list, in a browser session", connected)
        self.assertIn("Never call `apply` for a gated preview", connected)
        self.assertIn("`approval_required`", connected)
        for relative in ("SCHEMA.md", "ACTIONS.md"):
            text = " ".join((ROOT / "template/knowledge/wiki" / relative).read_text(encoding="utf-8").split())
            with self.subTest(file=relative):
                self.assertIn("Proposals list", text)
                self.assertIn("never applies a gated preview (`approval_required`)", text)

    def test_the_mcp_instructions_agree(self) -> None:
        text = " ".join(SERVER_INSTRUCTIONS.split())
        self.assertIn("A gated preview carries approval.required_roles", text)
        self.assertIn("an agent never applies it", text)
        self.assertIn("approves it in the board", text)


if __name__ == "__main__":
    unittest.main()
