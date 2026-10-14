"""`release-done` and the API contracts that apply to a feature: the contract a requirement on disk links, and the templates the wiki readers skip (CONTRACTS 3.4, 5.3)."""

from __future__ import annotations

import unittest

from prism_cli.board_service import BoardError, _parse_markdown
from prism_cli.wiki_model import contract_citation
from prism_cli.wiki_releases import format_snapshot
from tests.qa_support import DELIVERY_HEADER as FEATURE_DELIVERY_HEADER
from tests.release_support import FEATURE, ReleaseTests, delivery, record_page, table

SHARED = "knowledge/wiki/api-contracts/SHARED.md"
TEMPLATE = "knowledge/wiki/api-contracts/_example.md"
OWN = "knowledge/wiki/api-contracts/F-001.md"
BACKEND_REQ = "knowledge/wiki/app-requirements/F-001-backend.md"
OVER_LONG_ID = "F-" + "0" * 30 + "9"
LINK = "\n\nThe shared contract is [SHARED](../api-contracts/SHARED.md).\n"


def contract(*, feature_id: str = "F-001", version: int | str = 1, status: str = "agreed") -> str:
    return (
        f"---\nfeature-id: {feature_id}\nversion: {version}\nstatus: {status}\n---\n\n"
        "## Endpoints\n- `POST /api/v1/reviews/{reviewId}/exports` creates a review export. Request body: none. Response body: `ReviewExport` (201). Errors: 401, 404.\n\n"
        "## Data models\n### ReviewExport\n- `reviewId`: string\n- `url`: string\n\n"
        "## Authentication requirements\nBearer token of the signed-in reviewer.\n\n"
        "## Notes\nThe export is generated when it is requested.\n"
    )


MALFORMED = "---\nfeature-id: [F-009\nversion: 1\nstatus: agreed\n---\n\n## Endpoints\n- `POST /api/v1/exports` creates an export.\n"


class ReleaseContractTests(ReleaseTests):
    """The release of F-001, which delivered both apps citing `none`, while a contract applies to it."""

    def link_shared(self, text: str) -> None:
        """A shared contract that only the requirement of `backend` on disk links (the release proposal carries neither page)."""

        self.put(SHARED, text)
        self.put(BACKEND_REQ, self.read(BACKEND_REQ).rstrip("\n") + LINK)

    def untouched(self, before: dict[str, str]) -> None:
        """Nothing was written: the feature page, the status and the release records are as they were."""

        self.assertEqual(before, {path: self.read(path) for path in before})
        self.assertEqual(("ready-for-release", "release"), self.status())
        self.assertEqual([], self.records())

    def snapshot(self) -> dict[str, str]:
        return {path: self.read(path) for path in (FEATURE, BACKEND_REQ, "knowledge/wiki/status-board.md", "knowledge/wiki/log.md")}

    def test_a_release_is_refused_at_preview_while_a_shared_contract_a_requirement_links_has_no_citation(self) -> None:
        self.link_shared(contract(feature_id=OVER_LONG_ID))
        before = self.snapshot()
        with self.assertRaises(BoardError) as caught:
            self.propose("release-done", self.release_changes())
        self.assertEqual(("contract_binding_stale", 409), (caught.exception.code, caught.exception.status), caught.exception.message)
        self.assertEqual([SHARED], caught.exception.details["unusable"])
        self.assertIn(f"`{SHARED}`", caught.exception.message)
        self.assertIn("no citation", caught.exception.message)
        self.untouched(before)

    def test_a_release_of_one_app_is_refused_the_same_way(self) -> None:
        self.link_shared(contract(feature_id=OVER_LONG_ID))
        before = self.snapshot()
        feature, record = self.one_app("backend")
        self.assertEqual(("contract_binding_stale", 409), self.refuse(feature, record))
        self.untouched(before)

    def test_a_release_is_refused_while_a_shared_contract_a_requirement_links_has_malformed_front_matter(self) -> None:
        self.link_shared(MALFORMED)
        before = self.snapshot()
        with self.assertRaises(BoardError) as caught:
            self.propose("release-done", self.release_changes())
        self.assertEqual(("invalid_frontmatter", 409), (caught.exception.code, caught.exception.status), caught.exception.message)
        self.assertIn(SHARED, caught.exception.message)
        self.untouched(before)

    def test_a_release_is_refused_while_a_usable_shared_contract_a_requirement_links_and_a_row_cites_none(self) -> None:
        self.link_shared(contract(feature_id="F-009"))
        before = self.snapshot()
        with self.assertRaises(BoardError) as caught:
            self.propose("release-done", self.release_changes())
        self.assertEqual(("contract_binding_stale", 409), (caught.exception.code, caught.exception.status), caught.exception.message)
        citation = contract_citation("F-009", 1, _parse_markdown(contract(feature_id="F-009"))[1])
        self.assertEqual([citation], caught.exception.details["current"])
        self.assertNotIn("unusable", caught.exception.details)
        self.untouched(before)

    def test_a_template_with_the_feature_id_does_not_block_a_release_that_cites_none(self) -> None:
        self.put(TEMPLATE, contract(version=0))
        self.release()
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(["REL-001.md"], self.records())
        self.assertEqual(set(), self.errors())

    def test_a_template_beside_a_valid_contract_does_not_block_a_release_that_cites_it(self) -> None:
        text = contract(status="implemented")
        citation = contract_citation("F-001", 1, _parse_markdown(text)[1])
        self.put(OWN, text)
        self.put(TEMPLATE, contract(version=0))
        cited = [f"| {row.cells[0]} | {row.cells[1]} | {citation} | {' | '.join(row.cells[3:])} |" for row in self.evidence().delivery]
        self.put(FEATURE, self.with_section("Delivery evidence", table(FEATURE_DELIVERY_HEADER, cited)))
        feature, _record = self.all_released()
        snapshots = "\n".join(format_snapshot("F-001", app, citation, text) for app in ("backend", "worker"))
        record = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker")], contracts=snapshots)
        self.settle(feature, record)
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(["REL-001.md"], self.records())
        self.assertEqual(set(), self.errors())


if __name__ == "__main__":
    unittest.main()
