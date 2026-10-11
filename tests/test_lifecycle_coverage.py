"""The table that maps every case of CONTRACTS 10.2 and 10.3 to the tests that assert it (`tests/lifecycle_coverage.py`)."""

from __future__ import annotations

import unittest

from tests import real_temp  # noqa: F401
from tests.lifecycle_coverage import DENIED_CASES, ROUTE_CASES


class CoverageTableTests(unittest.TestCase):
    def test_the_table_holds_every_route_case_and_every_denied_case_of_the_contract(self) -> None:
        # CONTRACTS 10.2 lists 31 route and edge cases; 10.3 numbers 53 denied and stale cases.
        self.assertEqual([f"10.2-{number:02d}" for number in range(1, 32)], list(ROUTE_CASES))
        self.assertEqual(list(range(1, 54)), list(DENIED_CASES))

    def test_every_case_names_at_least_one_test_and_every_named_test_exists(self) -> None:
        listed = [(case, test) for case, (_text, tests) in ROUTE_CASES.items() for test in tests]
        listed += [(f"10.3-{number}", test) for number, tests in DENIED_CASES.items() for test in tests]
        self.assertTrue(all(tests for _text, tests in ROUTE_CASES.values()))
        self.assertTrue(all(tests for tests in DENIED_CASES.values()))
        loader = unittest.TestLoader()
        missing = []
        for case, name in listed:
            suite = loader.loadTestsFromName(name)
            tests = list(_flatten(suite))
            if len(tests) != 1 or type(tests[0]).__name__ == "_FailedTest":
                missing.append(f"{case}: {name}")
        self.assertEqual([], missing)


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


if __name__ == "__main__":
    unittest.main()
