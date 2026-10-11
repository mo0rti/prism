"""A review acknowledgement waits for the complete replacement preview before revocation or response interception."""

import unittest
from unittest.mock import MagicMock, patch

from tests.browser import scenario_support


class AcknowledgementTests(unittest.TestCase):
    def test_acknowledgement_waits_until_apply_is_enabled(self) -> None:
        board, dialog = MagicMock(), MagicMock()
        checks = {}

        def expect(target):
            return checks.setdefault(target, MagicMock())

        with patch.object(scenario_support, "expect", side_effect=expect):
            scenario_support.ScenarioCase.acknowledge(None, board, dialog)
        checks[board.acknowledgement.return_value].to_be_checked.assert_called_once()
        checks[dialog].to_contain_text.assert_called_once()
        self.assertIn(board.apply_button.return_value, checks, "the earlier ready label does not prove the new write set has arrived")
        checks[board.apply_button.return_value].to_be_enabled.assert_called_once()
