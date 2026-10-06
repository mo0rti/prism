"""Recording a verification: `prism wiki verify` and the connected `verify-pages` skill.

Both append one `verify` entry to log.md in the log format and never edit a page. The direct path uses the board's
guarded append; the connected path is a normal preview and apply, bound to the digest of each page that was read.
"""

from __future__ import annotations

import io
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from prism_cli.board_service import BoardError, BoardService
from prism_cli.cli import build_parser
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_log import last_verifications
from tests import real_temp  # noqa: F401
from tests.test_board_evidence_workflows import BoardWorkspaceCase
from tests.wiki_files import write_index

LOG = "knowledge/wiki/log.md"
TOPIC = "knowledge/wiki/topics/payments.md"
RESEARCH = "knowledge/wiki/research/sync.md"
TOPIC_TEXT = (
    "---\nkind: topic\ntitle: Payments\nstatus: current\nsources: []\n---\n\n"
    "## Summary\nPayments settle in a day.\n\n## Key points\n- **Assumed:** Weekends are excluded.\n\n## Related pages\nNone yet.\n"
)
RESEARCH_TEXT = (
    "---\nkind: research\ntitle: Sync\nstatus: open\nsources: []\n---\n\n"
    "## Question\nWhich model?\n\n## Summary\nLast writer wins.\n\n## Findings\n- **Unknown:** Nothing yet.\n\n## Gaps\n- **Unknown:** Cost.\n"
)
DECISION = "knowledge/wiki/decisions/ADR-001-sessions.md"
DECISION_TEXT = (
    "---\nid: ADR-001\ntitle: Sessions\ndate: 2026-09-01\nstatus: accepted\n---\n\n"
    "## Context\nOne browser.\n\n## Decision\nUse sessions.\n\n## Rationale\nSimple.\n\n## Consequences\nThey expire.\n"
)
ENTRY = re.compile(
    r"^## (?P<day>\d{4}-\d{2}-\d{2}) verify \| (?P<subject>\S.*)\n- paths: (?P<paths>\S.*)\n- evidence: (?P<evidence>\S.*)\n- by: (?P<by>\S.*)$"
)


class VerifyCase(BoardWorkspaceCase):
    def setUp(self) -> None:
        super().setUp()
        for relative, text in ((TOPIC, TOPIC_TEXT), (RESEARCH, RESEARCH_TEXT), (DECISION, DECISION_TEXT)):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        write_index(self.root)

    def everything(self) -> dict[str, bytes]:
        return {path.relative_to(self.root).as_posix(): path.read_bytes() for path in sorted(self.root.rglob("*")) if path.is_file() and ".prism" not in path.parts}

    def new_entries(self, before: str) -> list[str]:
        after = self.read(LOG)
        self.assertTrue(after.startswith(before), "existing log text is never rewritten")
        return [block.rstrip("\n") for block in re.split(r"(?m)^(?=## )", after[len(before):]) if block.startswith("## ")]

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        args = build_parser().parse_args(argv)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = args.func(args)
        return code, stdout.getvalue(), stderr.getvalue()


class DirectVerifyTests(VerifyCase):
    def test_it_appends_exactly_one_entry_in_the_log_format_and_touches_nothing_else(self) -> None:
        before_files = self.everything()
        before_log = self.read(LOG)

        code, output, error = self.run_cli("wiki", "verify", TOPIC, RESEARCH, "--path", str(self.root), "--evidence", "https://example.com/check", "--by", "Riley")

        self.assertEqual((0, ""), (code, error))
        entries = self.new_entries(before_log)
        self.assertEqual(1, len(entries))
        match = ENTRY.match(entries[0])
        self.assertIsNotNone(match, entries[0])
        self.assertEqual(date.today().isoformat(), match["day"])
        self.assertEqual("payments.md, sync.md", match["subject"])
        self.assertEqual(f"{TOPIC}, {RESEARCH}", match["paths"])
        self.assertEqual(("https://example.com/check", "Riley"), (match["evidence"], match["by"]))
        after_files = self.everything()
        changed = {path for path in after_files if before_files.get(path) != after_files[path]}
        self.assertEqual({LOG}, changed, "only log.md changes: no page, index line or status row")
        self.assertIn(LOG, output)
        self.assertEqual([], [item.to_dict() for item in lint_wiki(self.root).diagnostics if item.code == "malformed-log-entry"])

    def test_the_entry_makes_lint_read_the_pages_as_verified_until_they_are_overdue(self) -> None:
        def codes(today: date) -> dict[str, str]:
            return {Path(item.path).name: item.code for item in lint_wiki(self.root, today=today).all_diagnostics if item.code in {"stale-page", "never-verified"}}

        self.assertEqual("never-verified", codes(date.today())["payments.md"])
        self.run_cli("wiki", "verify", TOPIC, "--path", str(self.root))
        self.assertNotIn("payments.md", codes(date.today()))
        self.assertEqual("never-verified", codes(date.today())["sync.md"])
        # The core fixture sets the setting to 365 days.
        self.assertEqual("stale-page", codes(date.today() + timedelta(days=366))["payments.md"])
        self.assertEqual({TOPIC: date.today()}, last_verifications(self.read(LOG)))

    def test_pages_may_be_named_from_the_wiki_and_a_repeated_page_is_listed_once(self) -> None:
        before = self.read(LOG)
        code, _output, error = self.run_cli("wiki", "verify", "topics/payments.md", TOPIC, "./" + TOPIC, "--path", str(self.root))
        self.assertEqual((0, ""), (code, error))
        match = ENTRY.match(self.new_entries(before)[0])
        self.assertEqual(TOPIC, match["paths"])
        self.assertEqual("none", match["evidence"])

    def test_the_default_actor_is_the_local_user(self) -> None:
        with patch("prism_cli.board_service.getpass.getuser", return_value="riley"):
            self.service.record_verification([TOPIC])
        self.assertEqual("riley", ENTRY.match(self.new_entries("")[-1])["by"])

    def test_a_path_outside_the_wiki_an_unknown_page_and_an_exempt_page_are_refused_and_write_nothing(self) -> None:
        (self.root / "README.md").write_text("readme\n", encoding="utf-8")
        outside = self.root.parent / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        cases = {
            "../README.md": "verify_path_outside_wiki",
            "README.md": "verify_page_unknown",
            "docs/guide.md": "verify_path_outside_wiki",
            "knowledge/intake/pending/x.md": "verify_path_outside_wiki",
            "knowledge/wiki/../intake/x.md": "verify_path_outside_wiki",
            str(outside): "verify_path_outside_wiki",
            "topics/missing.md": "verify_page_unknown",
            "topics": "verify_page_unknown",
            "log.md": "verify_page_not_current_state",
            "index.md": "verify_page_not_current_state",
            "status-board.md": "verify_page_not_current_state",
            "SCHEMA.md": "verify_page_not_current_state",
            "WIKI_REPORT.md": "verify_page_unknown",
            "decisions/ADR-001-sessions.md": "verify_page_not_current_state",
        }
        for page, code in cases.items():
            with self.subTest(page=page):
                before = self.everything()
                with self.assertRaises(BoardError) as caught:
                    self.service.record_verification([page])
                self.assertEqual(code, caught.exception.code)
                self.assertEqual(before, self.everything())
        # One bad page refuses the whole call: the good page is not recorded either.
        before = self.everything()
        with self.assertRaises(BoardError):
            self.service.record_verification([TOPIC, "topics/missing.md"])
        self.assertEqual(before, self.everything())
        with self.assertRaises(BoardError) as caught:
            self.service.record_verification([])
        self.assertEqual("verify_pages_required", caught.exception.code)

    def test_the_cli_reports_a_refusal_and_exits_with_code_three(self) -> None:
        before = self.everything()
        code, output, error = self.run_cli("wiki", "verify", "../README.md", "--path", str(self.root))
        self.assertEqual((3, ""), (code, output))
        self.assertIn("outside knowledge/wiki", error)
        self.assertEqual(before, self.everything())

    def test_evidence_and_actor_stay_on_one_line(self) -> None:
        self.service.record_verification([TOPIC], evidence="[the check](https://example.com/a)\nand a second line", by="Claude (confirmed\nby Riley)")
        match = ENTRY.match(self.new_entries("")[-1])
        self.assertEqual(("[the check](https://example.com/a) and a second line", "Claude (confirmed by Riley)"), (match["evidence"], match["by"]))
        for field in ("evidence", "by"):
            with self.assertRaises(BoardError) as caught:
                self.service.record_verification([TOPIC], **{field: "   "})
            self.assertEqual("invalid_text", caught.exception.code)

    def test_a_log_that_changes_during_the_append_is_read_again_and_no_entry_is_lost(self) -> None:
        real_replace = BoardService._atomic_replace
        competing = "## 2026-10-06 po-clarify | F-009\n- paths: knowledge/wiki/features/F-009-x.md\n- evidence: none\n- by: Someone\n"
        calls: list[int] = []

        def replace(service, path, content, *, expected, actor=None):
            calls.append(1)
            if len(calls) == 1:
                path.write_text(path.read_text(encoding="utf-8") + "\n" + competing, encoding="utf-8", newline="\n")
            return real_replace(service, path, content, expected=expected, actor=actor)

        with patch.object(BoardService, "_atomic_replace", replace):
            self.service.record_verification([TOPIC])

        text = self.read(LOG)
        self.assertEqual(2, len(calls))
        self.assertIn(competing.splitlines()[0], text)
        self.assertEqual(1, len(re.findall(r"(?m)^## \S+ verify \|", text)))

    def test_a_log_that_keeps_changing_fails_instead_of_overwriting(self) -> None:
        def replace(service, path, content, *, expected, actor=None):
            raise BoardError("write_changed", "changed", 409)

        before = self.everything()
        with patch.object(BoardService, "_atomic_replace", replace):
            with self.assertRaises(BoardError) as caught:
                self.service.record_verification([TOPIC])
        self.assertEqual("write_changed", caught.exception.code)
        self.assertEqual(before, self.everything())

    def test_a_missing_log_is_not_invented(self) -> None:
        (self.root / LOG).unlink()
        with self.assertRaises(BoardError) as caught:
            self.service.record_verification([TOPIC])
        self.assertEqual("log_missing", caught.exception.code)
        self.assertFalse((self.root / LOG).exists())

    def test_a_symlinked_log_is_refused(self) -> None:
        real = self.root / "real-log.md"
        real.write_text(self.read(LOG), encoding="utf-8")
        (self.root / LOG).unlink()
        try:
            (self.root / LOG).symlink_to(real)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available")
        before = real.read_bytes()
        with self.assertRaises(BoardError):
            self.service.record_verification([TOPIC])
        self.assertEqual(before, real.read_bytes())

    def test_the_template_repository_is_never_written(self) -> None:
        (self.root / "copier.yml").write_text("{}\n", encoding="utf-8")
        (self.root / "template").mkdir()
        with self.assertRaises(BoardError) as caught:
            BoardService(self.root)
        self.assertEqual("template_workspace", caught.exception.code)
        code, _output, error = self.run_cli("wiki", "verify", TOPIC, "--path", str(self.root))
        self.assertEqual(3, code)
        self.assertIn("template", error.lower())


class ConnectedVerifyTests(VerifyCase):
    """`verify-pages` through the board: the agent names each page it read, and the human confirms the preview."""

    def digests(self, *pages: str) -> dict[str, str]:
        response = self.service.read_workspace(self.agent, list(pages))
        return {item["path"]: item["digest"] for item in response["files"]}

    def preview(self, *pages: str, changes=None, moves=None, revisions=None) -> dict:
        return self.service.preview_skill(self.agent, "verify-pages", changes or [], moves, revisions if revisions is not None else self.digests(*pages))

    def test_the_skill_is_a_connected_write_skill_for_agents_only(self) -> None:
        listed = {item["name"]: item for item in self.service.list_skills(self.agent)["skills"]}
        self.assertTrue(listed["verify-pages"]["write_supported"])
        self.assertEqual({"preview_skill": ["agent"]}, listed["verify-pages"]["write_tools"])
        self.assertEqual([], listed["verify-pages"]["write_scopes"])
        human = self.service.authenticate(self.service.create_participant("Human", "human", True)["token"])
        with self.assertRaises(BoardError) as caught:
            self.service.preview_skill(human, "verify-pages", [], None, self.digests(TOPIC))
        self.assertEqual("participant_kind_required", caught.exception.code)

    def test_a_preview_writes_only_the_log_and_apply_appends_one_verify_entry(self) -> None:
        before_files = self.everything()
        before_log = self.read(LOG)

        preview = self.preview(TOPIC, RESEARCH)

        self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]))
        self.assertEqual([LOG], [write["path"] for write in preview["writes"]])
        self.assertEqual(before_files, self.everything(), "a preview writes nothing")
        receipt = self.service.apply(self.agent, preview["preview_id"], str(uuid4()))
        self.assertEqual(("applied", [LOG]), (receipt["state"], receipt["applied_paths"]))
        entries = self.new_entries(before_log)
        self.assertEqual(1, len(entries))
        heading, paths, evidence, by, *rest = entries[0].splitlines()
        self.assertRegex(heading, rf"^## {date.today().isoformat()} verify \| payments\.md, sync\.md$")
        self.assertEqual(f"- paths: {TOPIC}, {RESEARCH}", paths)
        self.assertEqual(f"- evidence: board preview {preview['preview_id']}", evidence)
        self.assertRegex(by, r"^- by: Workflow agent \(agent\)$")
        self.assertTrue(all(line.startswith("<!--") for line in rest), rest)
        after_files = self.everything()
        self.assertEqual({LOG}, {path for path in after_files if before_files.get(path) != after_files[path]})
        self.assertEqual({TOPIC: date.today(), RESEARCH: date.today()}, last_verifications(self.read(LOG)))
        self.assertEqual([], [item.to_dict() for item in lint_wiki(self.root).diagnostics if item.code == "malformed-log-entry"])

    def test_applying_again_with_the_same_operation_returns_the_same_receipt_and_adds_nothing(self) -> None:
        preview = self.preview(TOPIC)
        operation = str(uuid4())
        first = self.service.apply(self.agent, preview["preview_id"], operation)
        log = self.read(LOG)
        self.assertEqual(first, self.service.apply(self.agent, preview["preview_id"], operation))
        self.assertEqual(log, self.read(LOG))

    def test_a_page_that_changed_after_the_preview_makes_the_apply_stale(self) -> None:
        preview = self.preview(TOPIC)
        (self.root / TOPIC).write_text(TOPIC_TEXT.replace("a day", "two days"), encoding="utf-8", newline="\n")
        before = self.everything()
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.agent, preview["preview_id"], str(uuid4()))
        self.assertEqual("stale_preview", caught.exception.code)
        self.assertEqual(before, self.everything())

    def test_a_digest_that_does_not_match_the_page_is_rejected_at_preview(self) -> None:
        stale = self.digests(TOPIC)
        (self.root / TOPIC).write_text(TOPIC_TEXT.replace("a day", "two days"), encoding="utf-8", newline="\n")
        with self.assertRaises(BoardError) as caught:
            self.preview(revisions=stale)
        self.assertEqual("stale_read_revision", caught.exception.code)
        with self.assertRaises(BoardError) as caught:
            self.preview(revisions={TOPIC: "sha256:" + "0" * 64})
        self.assertEqual("read_digest_mismatch", caught.exception.code)

    def test_refusals_leave_the_workspace_as_it_was(self) -> None:
        digests = self.digests(TOPIC)
        decision = self.digests(DECISION)
        before = self.everything()
        cases = {
            "no pages": (dict(revisions={}), "verify_pages_required"),
            "a change is supplied": (dict(changes=[{"path": TOPIC, "content": TOPIC_TEXT}], revisions=digests), "verify_writes_nothing"),
            "a move is supplied": (dict(moves=[{"source": "a", "destination": "b"}], revisions=digests), "verify_writes_nothing"),
            "outside the wiki": (dict(revisions={"../README.md": "sha256:x"}), "verify_path_outside_wiki"),
            "unknown page": (dict(revisions={"knowledge/wiki/topics/missing.md": "sha256:x"}), "verify_page_unknown"),
            "a record": (dict(revisions=decision), "verify_page_not_current_state"),
            "the index": (dict(revisions=self.digests("knowledge/wiki/index.md")), "verify_page_not_current_state"),
            "the page twice": (dict(revisions={TOPIC: digests[TOPIC], "topics/payments.md": digests[TOPIC]}), "duplicate_read_revision"),
        }
        for name, (arguments, code) in cases.items():
            with self.subTest(name):
                with self.assertRaises(BoardError) as caught:
                    self.preview(**arguments)
                self.assertEqual(code, caught.exception.code)
        self.assertEqual(before, self.everything())

    def test_the_recorded_verification_does_not_block_a_later_lifecycle_write(self) -> None:
        self.ingest_feature()
        self.submit_verification(TOPIC)
        self.specify_feature()
        self.assertIn("status: specified", self.read("knowledge/wiki/features/F-001-document-review.md"))

    def submit_verification(self, *pages: str) -> dict:
        preview = self.preview(*pages)
        return self.service.apply(self.agent, preview["preview_id"], str(uuid4()))


if __name__ == "__main__":
    unittest.main()
