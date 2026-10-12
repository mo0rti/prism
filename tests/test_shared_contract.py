"""A feature changes and requires only its own API contract (F14): a contract it links and another feature owns is left alone.

The workspace is the QA board of feature F-001 (both apps delivered). F-009 is a released feature with an `implemented` contract
that the requirement pages of F-001 link, as `app-requirements/_FORMAT.md` instructs for a shared contract. F-001 reads that
contract for the binding check and answers for no other part of it.
"""

from __future__ import annotations

import unittest

from prism_cli.board_service import BoardError, _parse_markdown
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import contract_citation
from tests import test_qa_fail as qa_fail
from tests import test_qa_returns as qa_returns
from tests.qa_support import BOTH, FEATURE, QaBoard, app_row, integration_row, requirement_path
from tests.test_design_tracks import contract_page
from tests.test_lifecycle_model import DELIVERY_HEADER, delivery_row, table

OWNER_CONTRACT = "knowledge/wiki/api-contracts/F-009.md"
OWN_CONTRACT = "knowledge/wiki/api-contracts/F-001.md"


def contract_diagnostics(root, code: str) -> list:
    return [item for item in lint_wiki(root).diagnostics if item.code == code]


class SharedContractTests(QaBoard):
    # The helpers of the QA fail and return tests, which build their proposals from the page as it is.
    line = staticmethod(qa_fail.line)
    record_failure = qa_fail.QaFailTests.record_failure
    fail_changes = qa_fail.QaFailTests.fail_changes
    every_row = qa_returns.ReturnTests.every_row
    seed_tracks = qa_returns.ReturnTests.seed_tracks
    return_changes = qa_returns.ReturnTests.return_changes
    parts = qa_returns.ReturnTests.parts
    errors = qa_fail.QaFailTests.errors

    def setUp(self) -> None:
        super().setUp()
        self.contract = contract_page(feature_id="F-009", status="implemented")
        self.put(OWNER_CONTRACT, self.contract)
        for app in BOTH:
            path = requirement_path(app)
            note = "No separate API contract is needed for this backend-only feature."
            self.assertIn(note, self.read(path))
            self.put(path, self.read(path).replace(note, "The shared contract is [F-009](../api-contracts/F-009.md)."))
        # The delivery rows cite the contract they were built against, as the binding check requires of a linked contract.
        self.citation = contract_citation("F-009", 1, _parse_markdown(self.contract)[1])
        rows = [delivery_row(app, None, self.citation) for app in BOTH]
        self.put(FEATURE, self.with_section("Delivery evidence", table(DELIVERY_HEADER, rows)))

    def set_owner_status(self, status: str) -> None:
        self.put(OWNER_CONTRACT, contract_page(feature_id="F-009", status=status))

    def test_the_setup_is_consistent(self) -> None:
        self.assertEqual(set(), {code for code in self.errors() if code in {"delivered-api-contract", "stale-delivery-evidence", "api-contract-not-ready"}})

    def test_qa_fail_neither_requires_nor_allows_a_write_to_the_owners_contract(self) -> None:
        self.record_failure()
        changes = self.fail_changes(["worker"], linked="BUG-001")
        supplied = {item["path"]: item["content"] for item in changes}
        expected = self.service._d3_expected_pages({"feature_id": "F-001", "path": FEATURE}, "qa-fail", ("worker",), supplied)
        self.assertEqual({requirement_path("worker"): "in-progress"}, expected)
        agreed = contract_page(feature_id="F-009", status="agreed")
        refused = self.refused("qa-fail", [*changes, {"path": OWNER_CONTRACT, "content": agreed}])
        # The page belongs to another feature, so no proposal of F-001 can carry it.
        self.assertEqual("feature_context_mismatch", refused.code)
        self.apply("qa-fail", changes)
        self.assertEqual(("in-dev", "dev"), self.status())
        self.assertEqual(self.contract, self.read(OWNER_CONTRACT))
        self.assertEqual([], contract_diagnostics(self.root, "delivered-api-contract"))

    def test_qa_return_spec_neither_requires_nor_allows_a_write_to_the_owners_contract(self) -> None:
        self.apply("qa-verify", [{"path": FEATURE, "content": self.with_status("in-qa", "qa", self.qa_table([app_row("backend"), integration_row()]))}])
        self.seed_tracks()
        changes = self.return_changes("qa-return-spec")
        supplied = {item["path"]: item["content"] for item in changes}
        expected = self.service._d3_expected_pages({"feature_id": "F-001", "path": FEATURE}, "qa-return-spec", ("backend", "worker"), supplied)
        self.assertEqual({requirement_path("backend"): "in-progress", requirement_path("worker"): "in-progress"}, expected)
        draft = contract_page(feature_id="F-009", status="draft")
        self.assertEqual("feature_context_mismatch", self.refused("feature-reopen", [*changes, {"path": OWNER_CONTRACT, "content": draft}]).code)
        self.apply("feature-reopen", changes)
        self.assertEqual(("specified", "po"), self.status())
        self.assertEqual(self.contract, self.read(OWNER_CONTRACT))
        self.assertEqual([], contract_diagnostics(self.root, "delivered-api-contract"))
        self.assertEqual([], contract_diagnostics(self.root, "api-contract-not-ready"))

    def test_a_feature_returns_its_own_contract_with_the_requirement_pages(self) -> None:
        own = contract_page(feature_id="F-001", status="implemented")
        self.put(OWN_CONTRACT, own)
        self.record_failure()
        changes = self.fail_changes(["worker"], linked="BUG-001")
        supplied = {item["path"]: item["content"] for item in changes}
        expected = self.service._d3_expected_pages({"feature_id": "F-001", "path": FEATURE}, "qa-fail", ("worker",), supplied)
        self.assertEqual({requirement_path("worker"): "in-progress", OWN_CONTRACT: "agreed"}, expected)

    def test_dev_done_completes_while_the_owners_contract_is_still_agreed_and_the_binding_still_applies(self) -> None:
        self.set_owner_status("agreed")
        feature = {"id": "F-001", "path": FEATURE, "after": self.feature()[0]}
        supplied = {path: self.read(path) for path in (FEATURE, *(requirement_path(app) for app in BOTH))}
        self.service._assert_delivered_pages_complete(supplied, feature, tuple(BOTH))
        self.service._assert_contract_bindings(feature, supplied, tuple(BOTH))
        # The linked contract is still read for the binding: rows that cite `none` are stale.
        stale = self.with_section("Delivery evidence", table(DELIVERY_HEADER, [delivery_row(app) for app in BOTH]))
        with self.assertRaises(BoardError) as caught:
            self.service._assert_contract_bindings(feature, {**supplied, FEATURE: stale}, tuple(BOTH))
        self.assertEqual("contract_binding_stale", caught.exception.code)
        # The feature's own contract is still required to be implemented once every app is delivered.
        self.put(OWN_CONTRACT, contract_page(feature_id="F-001", status="agreed"))
        with self.assertRaises(BoardError) as own:
            self.service._assert_delivered_pages_complete(supplied, feature, tuple(BOTH))
        self.assertEqual(("api_contract_not_implemented", OWN_CONTRACT), (own.exception.code, own.exception.details["path"]))

    def test_lint_requires_the_implemented_status_of_the_features_own_contract_only(self) -> None:
        self.set_owner_status("agreed")
        self.assertEqual([], contract_diagnostics(self.root, "delivered-api-contract"))
        self.put(OWN_CONTRACT, contract_page(feature_id="F-001", status="agreed"))
        found = contract_diagnostics(self.root, "delivered-api-contract")
        self.assertEqual(["F-001.md"], [item.path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for item in found])
        self.assertEqual(["F-001"], [item.feature_id for item in found])


if __name__ == "__main__":
    unittest.main()
