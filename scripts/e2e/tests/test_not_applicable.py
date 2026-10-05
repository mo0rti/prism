"""A clarify step with no open question for its role passes as nothing to do and launches no host."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import config, report as reports, workspace as ws  # noqa: E402
from prism_e2e.runner import Journey  # noqa: E402


def feature(questions: list[ws.Question]) -> ws.FeatureState:
    return ws.FeatureState(status="ready-for-dev", owner="dev", index_status=None, index_owner=None, questions=questions, text="")


class _Env:
    workspace = Path(".")


class NotApplicableClarifyTests(unittest.TestCase):
    def _journey(self) -> Journey:
        journey = Journey.__new__(Journey)
        journey.env = _Env()
        journey.board = object()
        journey.options = type("Options", (), {"tier": "smoke", "fixtures": None})()
        return journey

    def _run(self, step_id: str, questions: list[ws.Question]) -> tuple[reports.StepResult, list]:
        journey = self._journey()
        launched: list = []
        result = reports.StepResult(step=step_id, kind="agent", host="claude")
        with patch.object(ws, "read_feature", return_value=feature(questions)), patch.object(
            Journey, "_launch", side_effect=lambda *args, **kwargs: launched.append(args) or (_ for _ in ()).throw(RuntimeError("launched"))
        ):
            try:
                journey.run_agent_step(config.STEPS_BY_ID[step_id], 9, "claude", result)
            except RuntimeError:
                pass
        return result, launched

    def test_no_open_dev_question_passes_without_launching_a_host(self) -> None:
        result, launched = self._run("dev-clarify", [ws.Question("1", "Format?", "po", "resolved: PDF.")])
        self.assertEqual("passed", result.status)
        self.assertTrue(result.not_applicable)
        self.assertEqual([], launched)
        self.assertIn("no open dev-owned question", result.notes[0])
        self.assertIsNone(result.first_attempt_success)

    def test_an_open_question_for_the_role_still_launches_the_host(self) -> None:
        _result, launched = self._run("dev-clarify", [ws.Question("4", "Data support?", "dev", "open")])
        self.assertEqual(1, len(launched))

    def test_a_non_clarify_step_is_never_skipped_this_way(self) -> None:
        _result, launched = self._run("dev-done", [])
        self.assertEqual(1, len(launched))


if __name__ == "__main__":
    unittest.main()
