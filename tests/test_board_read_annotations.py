"""A feature page's criteria annotations stay within the size of one MCP tool result.

A long feature page is read in pieces and each piece carries the criteria whose list item starts in its content range. The
tests read pages with hundreds and thousands of criteria through the real service, MCP server and SDK client, measure every
result on the wire (`_Client.call` checks the 48,000-character limit) and compare the reassembled content and criteria with
the file on disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import tempfile
from typing import Any
import unittest

from prism_cli import board_reads
from prism_cli.board_reads import criteria_facts, criteria_starts, read_annotations
from prism_cli.wiki_model import contract_page_citation, parse_markdown_text
from tests.test_board_mcp_size_budget import RESULT_BUDGET, _Client, _digest, _feature_page, build_workspace, connected
from tests import real_temp  # noqa: F401


FEATURES = "knowledge/wiki/features"
CRITERION_LINE = re.compile(r"^- \[ \] AC-([0-9]+) ", re.MULTILINE)


def feature_text(number: int, criteria: list[str], pad: int = 0) -> str:
    """A feature page whose `## Acceptance criteria` section holds exactly the given list items."""

    page = _feature_page(number)
    page = page.replace("record the review outcome.\n", "record the review outcome." + "p" * pad + "\n", 1)
    head, rest = page.split("## Acceptance criteria\n", 1)
    return head + "## Acceptance criteria\n" + "\n".join(criteria) + "\n" + rest[rest.index("\n## Open questions"):]


def plain_criteria(count: int) -> list[str]:
    return [f"- [ ] AC-{number} [backend] Criterion {number} is recorded." for number in range(1, count + 1)]


def write_feature(root: Path, number: int, text: str) -> str:
    relative = f"{FEATURES}/F-{number:03d}-document-review.md"
    (root / relative).write_bytes(text.encode("utf-8"))
    return relative


def expected_facts(relative: str, text: str) -> list[dict[str, Any]]:
    page = parse_markdown_text(Path(relative), text)
    return criteria_facts(page.frontmatter["id"], page.body)


class ReadAnnotationsTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary.cleanup)
        cls.root = Path(cls._temporary.name) / "board"
        build_workspace(cls.root, 0)

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def check_pieces(self, pages: list[dict[str, Any]], relative: str, text: str, expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reassemble one file from its pieces and check content, digest, offsets and the criteria of every piece."""

        records = [record for page in pages for record in page["files"] if record["path"] == relative]
        joined = ""
        criteria: list[dict[str, Any]] = []
        starts = {int(match.group(1)): match.start() for match in CRITERION_LINE.finditer(text)}
        for record in records:
            self.assertEqual(len(joined), record["offset"])
            self.assertEqual(len(text), record["total_chars"])
            self.assertEqual(_digest(text), record["digest"])
            self.assertIn("criteria", record["annotations"], "every piece of a feature page has its criteria list")
            end = record["offset"] + len(record["content"])
            listed = [item["id"] for item in record["annotations"]["criteria"]]
            self.assertEqual(
                [f"AC-{number}" for number, begin in starts.items() if record["offset"] <= begin < end],
                listed,
                "a piece lists the criteria whose list item starts in its content range",
            )
            joined += record["content"]
            criteria.extend(record["annotations"]["criteria"])
        self.assertEqual(text, joined)
        self.assertEqual(expected, criteria)
        return records

    async def read_pages(self, client: _Client, paths: list[str]) -> list[dict[str, Any]]:
        return await client.paged("read_workspace", {"paths": paths})

    async def check_long_page(self, number: int, count: int) -> tuple[int, int]:
        text = feature_text(number, plain_criteria(count))
        relative = write_feature(self.root, number, text)
        async with connected(self, self.root) as client:
            pages = await self.read_pages(client, [relative])
            records = self.check_pieces(pages, relative, text, expected_facts(relative, text))
            self.assertEqual(count, sum(len(record["annotations"]["criteria"]) for record in records))
            self.assertGreater(len(pages), 1)
            self.assertTrue(all(len(page["files"]) == 1 for page in pages))
            self.assertIsNone(pages[-1]["next_cursor"])
            self.assertTrue(all(page["next_cursor"] is not None for page in pages[:-1]))
            return len(pages), max(len(json.dumps(page, ensure_ascii=False, separators=(",", ":"))) for page in pages)

    async def test_a_feature_page_with_500_criteria_arrives_in_pieces_that_carry_their_own_criteria(self) -> None:
        pieces, largest = await self.check_long_page(500, 500)
        self.assertGreater(pieces, 1)
        self.assertLessEqual(largest, RESULT_BUDGET)

    async def test_a_feature_page_with_2000_criteria_arrives_in_pieces_that_carry_their_own_criteria(self) -> None:
        pieces, largest = await self.check_long_page(501, 2000)
        self.assertGreater(pieces, 4)
        self.assertLessEqual(largest, RESULT_BUDGET)

    async def test_a_criterion_that_starts_exactly_at_a_piece_boundary_belongs_to_the_next_piece(self) -> None:
        number = 530
        async with connected(self, self.root) as client:
            found = None
            for pad in range(0, 400):
                text = feature_text(number, plain_criteria(500), pad)
                relative = write_feature(self.root, number, text)
                first = client.service.read_workspace(client.actor, [relative])["files"][0]
                end = len(first["content"])
                if text.startswith("- [ ] AC-", end) and text[end - 1] == "\n":
                    found = (pad, text, relative, end)
                    break
            self.assertIsNotNone(found, "some padding puts a criterion exactly at the end of the first piece")
            _pad, text, relative, end = found
            pages = await self.read_pages(client, [relative])
            records = self.check_pieces(pages, relative, text, expected_facts(relative, text))
            boundary = int(CRITERION_LINE.match(text, end).group(1))
            self.assertEqual(end, records[1]["offset"])
            self.assertNotIn(f"AC-{boundary}", [item["id"] for item in records[0]["annotations"]["criteria"]])
            self.assertEqual(f"AC-{boundary}", records[1]["annotations"]["criteria"][0]["id"])

    async def test_a_small_feature_page_is_one_piece_with_all_its_criteria(self) -> None:
        text = feature_text(540, plain_criteria(5))
        relative = write_feature(self.root, 540, text)
        async with connected(self, self.root) as client:
            pages = await self.read_pages(client, [relative])
        self.assertEqual(1, len(pages))
        self.assertIsNone(pages[0]["next_cursor"])
        record = pages[0]["files"][0]
        self.assertEqual((0, text, len(text)), (record["offset"], record["content"], record["total_chars"]))
        self.assertEqual(read_annotations(relative, text), record["annotations"])
        self.assertEqual([f"AC-{number}" for number in range(1, 6)], [item["id"] for item in record["annotations"]["criteria"]])

    async def test_a_criterion_with_an_oversized_applies_to_keeps_its_exact_revision_and_drops_the_list(self) -> None:
        apps = ", ".join(f"app-{number:05d}" for number in range(6000))
        criteria = plain_criteria(2) + [f"- [ ] AC-3 [{apps}] Criterion 3 names many apps."] + plain_criteria(6)[3:]
        text = feature_text(550, criteria)
        relative = write_feature(self.root, 550, text)
        full = expected_facts(relative, text)
        self.assertEqual(6, len(full))
        self.assertGreater(len(json.dumps(full[2])), board_reads.STRUCTURED_BUDGET_CHARS)
        async with connected(self, self.root) as client:
            pages = await self.read_pages(client, [relative])
        omitted = {
            "id": "AC-3",
            "revision": full[2]["revision"],
            "applies_to_count": 6000,
            "applies_to_omitted": True,
            "integration": False,
        }
        expected = [*full[:2], omitted, *full[3:]]
        records = self.check_pieces(pages, relative, text, expected)
        self.assertGreater(len(records), 1)
        listed = [item for record in records for item in record["annotations"]["criteria"]]
        self.assertTrue(full[2]["revision"].startswith("v1:"))
        self.assertEqual(1, sum("applies_to_omitted" in item for item in listed))
        self.assertNotIn("applies_to", listed[2])

    async def test_a_long_feature_page_after_a_short_file_starts_on_its_own_page(self) -> None:
        short_text = feature_text(560, plain_criteria(3))
        long_text = feature_text(561, plain_criteria(500))
        short = write_feature(self.root, 560, short_text)
        long = write_feature(self.root, 561, long_text)
        async with connected(self, self.root) as client:
            pages = await self.read_pages(client, [short, long])
        self.assertEqual([short], [record["path"] for record in pages[0]["files"]])
        whole = pages[0]["files"][0]
        self.assertEqual((0, short_text), (whole["offset"], whole["content"]))
        self.assertEqual(read_annotations(short, short_text), whole["annotations"])
        self.assertIsNotNone(pages[0]["next_cursor"])
        self.assertEqual(long, pages[1]["files"][0]["path"])
        self.assertEqual(0, pages[1]["files"][0]["offset"])
        self.assertTrue(all([long] == [record["path"] for record in page["files"]] for page in pages[1:]))
        self.check_pieces(pages[1:], long, long_text, expected_facts(long, long_text))

    async def test_a_contract_page_keeps_its_one_annotation_on_the_first_piece(self) -> None:
        contract = "knowledge/wiki/api-contracts/F-570-contract.md"
        body = "## Endpoints\n" + "\n".join(f"- GET /resource-{number} returns the record {number}." for number in range(2500)) + "\n"
        text = "---\nfeature-id: F-570\nversion: 3\n---\n\n" + body
        (self.root / "knowledge/wiki/api-contracts").mkdir(parents=True, exist_ok=True)
        (self.root / contract).write_bytes(text.encode("utf-8"))
        expected = read_annotations(contract, text)
        self.assertEqual({"contract"}, set(expected))
        async with connected(self, self.root) as client:
            pages = await self.read_pages(client, [contract])
        records = [record for page in pages for record in page["files"]]
        self.assertGreater(len(records), 1)
        self.assertEqual(expected, records[0]["annotations"])
        self.assertTrue(all("annotations" not in record for record in records[1:]))
        self.assertEqual(text, "".join(record["content"] for record in records))

    async def test_a_contract_with_an_over_long_feature_id_has_no_citation_and_no_annotation(self) -> None:
        contract = "knowledge/wiki/api-contracts/F-571-contract.md"
        (self.root / "knowledge/wiki/api-contracts").mkdir(parents=True, exist_ok=True)
        async with connected(self, self.root) as client:
            for feature_id, annotated in (
                ("F-571", True),
                ("F-" + "9" * 18, True),
                ("F-" + "9" * 19, False),
                ("F-" + "0" * 40 + "571", False),
                ("F-" + "0" * 100000 + "1", False),
            ):
                with self.subTest(feature_id=len(feature_id)):
                    text = f"---\nfeature-id: {feature_id}\nversion: 1\n---\n\n## Endpoints\nNone\n"
                    (self.root / contract).write_bytes(text.encode("utf-8"))
                    page = parse_markdown_text(Path(contract), text)
                    citation = contract_page_citation(page.frontmatter, page.body)
                    self.assertEqual(annotated, citation is not None)
                    record = client.service.read_workspace(client.actor, [contract])["files"][0]
                    if annotated:
                        self.assertEqual(citation, record["annotations"]["contract"]["citation"])
                        self.assertEqual(read_annotations(contract, text), record["annotations"])
                    else:
                        self.assertNotIn("annotations", record)

    def test_criteria_start_offsets_point_at_each_list_item_whatever_the_page_looks_like(self) -> None:
        relative = f"{FEATURES}/F-580-document-review.md"
        criteria = [
            "<!-- - [ ] AC-9 [backend] A commented item is not a criterion. -->",
            "- [ ] AC-1 [backend] First.",
            "  continuation of the first criterion",
            "    - a sub-bullet of the first criterion",
            "```",
            "- [ ] AC-8 [backend] An item in a code fence is not a criterion.",
            "```",
            "- [ ] AC-2 [backend, web] Second.",
            "- [ ] no id yet",
            "- [x] AC-3 [integration: backend, web] Third.",
        ]
        text = feature_text(580, criteria)
        for label, variant in (
            ("plain", text),
            ("byte order mark", "﻿" + text),
            ("carriage returns", text.replace("\n", "\r\n")),
            ("both", "﻿" + text.replace("\n", "\r\n")),
        ):
            with self.subTest(variant=label):
                found = criteria_starts(relative, variant)
                self.assertEqual(["AC-1", "AC-2", "AC-3"], [fact["id"] for _, fact in found])
                self.assertEqual([fact for _, fact in found], read_annotations(relative, variant)["criteria"])
                for begin, fact in found:
                    self.assertTrue(variant.startswith(("- [ ] " if fact["id"] != "AC-3" else "- [x] ") + fact["id"] + " ", begin), (label, fact["id"]))
                    self.assertTrue(begin == 0 or variant[begin - 1] == "\n")

    def test_a_page_without_criteria_has_an_empty_list_and_no_starts(self) -> None:
        relative = f"{FEATURES}/F-581-document-review.md"
        text = feature_text(581, [])
        self.assertEqual([], criteria_starts(relative, text))
        self.assertEqual({"criteria": []}, read_annotations(relative, text))
        self.assertIsNone(criteria_starts("knowledge/wiki/design/F-581-design.md", text))


if __name__ == "__main__":
    unittest.main()
