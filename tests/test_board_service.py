"""Structural safety checks for the provider-neutral connected BoardService."""

from __future__ import annotations

import hashlib
from io import BytesIO
import os
import re
import shutil
import subprocess
from contextlib import contextmanager, nullcontext
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator
from unittest.mock import patch
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService, _parse_markdown
from prism_cli.fs_safety import CLOUD_SYNC_MESSAGE
from prism_cli.workflow_assets import asset_digest
from prism_cli.workflow_install import apply_install, plan_install
from tests.core_workflow_fixture import FEATURE_PATH, INTAKE_ITEM, PROCESSED_INTAKE_ITEM, create_core_workflow_fixture
from tests.test_core_workflow_fixture import CHECK_DATE, _feature_page, _write_index
from tests.test_fs_safety import CLOUD_TAG, JUNCTION_TAG, fake_reparse
from tests import real_temp  # noqa: F401


class BoardServiceValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "board")
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["workflow"] = {
            "version": "1",
            "board_id": "3a8db764-f386-461e-bb0b-165de1dcf3a9",
            "mode": "workflow",
            "asset_digest": asset_digest("1"),
        }
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        grant = self.service.create_participant("Validator", "agent", writable=True)
        self.actor = self.service.authenticate(grant["token"])

    def test_skill_capabilities_match_enforced_write_path_scopes(self) -> None:
        expected = {
            "po-intake": [
                "knowledge/wiki/features/*.md",
                "knowledge/wiki/personas/*.md",
                "knowledge/wiki/business-rules/*.md",
                "knowledge/intake/processed/**/MANIFEST.md",
                "knowledge/intake/quarantined/**/CONFLICT.md",
            ],
            "design-intake": [
                "knowledge/wiki/features/*.md",
                "knowledge/wiki/design/*.md",
                "knowledge/intake/processed/**/MANIFEST.md",
                "knowledge/intake/quarantined/**/CONFLICT.md",
            ],
            "ask": ["knowledge/wiki/features/*.md"],
            "po-clarify": ["knowledge/wiki/features/*.md"],
            "design-clarify": ["knowledge/wiki/features/*.md", "knowledge/wiki/design/*.md"],
            "dev-clarify": ["knowledge/wiki/features/*.md", "knowledge/wiki/platform-requirements/*.md"],
            "po-specify": ["knowledge/wiki/features/*.md"],
            "po-handoff": ["knowledge/wiki/features/*.md"],
            "design-start": ["knowledge/wiki/features/*.md"],
            "design-handoff": [
                "knowledge/wiki/features/*.md",
                "knowledge/wiki/platform-requirements/*.md",
                "knowledge/wiki/api-contracts/*.md",
            ],
            "dev-start": ["knowledge/wiki/features/*.md"],
            "dev-done": [
                "knowledge/wiki/features/*.md",
                "knowledge/wiki/platform-requirements/*.md",
                "knowledge/wiki/api-contracts/*.md",
            ],
            "feature-reopen": [
                "knowledge/wiki/features/*.md",
                "knowledge/wiki/platform-requirements/*.md",
                "knowledge/wiki/api-contracts/*.md",
            ],
        }
        discovered = {item["name"]: item for item in self.service.list_skills(self.actor)["skills"]}
        self.assertEqual(set(expected), {name for name, item in discovered.items() if item["write_supported"]})
        for name, item in discovered.items():
            if name not in expected:
                with self.subTest(read_only_skill=name):
                    self.assertFalse(item["write_supported"])
                    self.assertEqual([], item["write_scopes"])
        for name, scopes in expected.items():
            with self.subTest(skill=name):
                self.assertEqual(scopes, discovered[name]["write_scopes"])
                self.assertTrue(any("index.md" in item and "service-managed" in item for item in discovered[name]["limitations"]))

        accepted = (
            ("po-intake", "knowledge/wiki/personas/P-001-reviewer.md"),
            ("po-intake", "knowledge/intake/processed/review/MANIFEST.md"),
            ("design-intake", "knowledge/wiki/design/F-002-review.md"),
            ("design-intake", "knowledge/intake/quarantined/review/CONFLICT.md"),
            ("design-clarify", "knowledge/wiki/design/F-002-review.md"),
            ("dev-clarify", "knowledge/wiki/platform-requirements/F-002-backend.md"),
            ("design-handoff", "knowledge/wiki/platform-requirements/backend.md"),
            ("design-handoff", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("dev-done", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("feature-reopen", "knowledge/wiki/platform-requirements/backend.md"),
        )
        for skill, path in accepted:
            with self.subTest(skill=skill, accepted_path=path):
                self.service._assert_skill_write_path(skill, path)

        rejected = (
            ("po-intake", "knowledge/wiki/design/F-002-review.md"),
            ("design-intake", "knowledge/wiki/business-rules/BR-001-review.md"),
            ("ask", "knowledge/wiki/design/F-002-review.md"),
            ("po-clarify", "knowledge/wiki/design/F-002-review.md"),
            ("design-clarify", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("design-clarify", "knowledge/wiki/platform-requirements/F-002-backend.md"),
            ("po-clarify", "knowledge/wiki/platform-requirements/F-002-backend.md"),
            ("dev-clarify", "knowledge/wiki/design/F-002-review.md"),
            ("dev-clarify", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("po-specify", "knowledge/wiki/platform-requirements/backend.md"),
            ("po-handoff", "knowledge/wiki/platform-requirements/backend.md"),
            ("design-start", "knowledge/wiki/platform-requirements/backend.md"),
            ("po-specify", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("po-handoff", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("design-start", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("dev-start", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("dev-done", "knowledge/wiki/design/F-002-review.md"),
            ("feature-reopen", "knowledge/wiki/design/F-002-review.md"),
        )
        for skill, path in rejected:
            with self.subTest(skill=skill, rejected_path=path), self.assertRaises(BoardError) as error:
                self.service._assert_skill_write_path(skill, path)
            self.assertEqual("write_path_unavailable", error.exception.code)

        for skill, scopes in expected.items():
            for pattern in scopes:
                if "/**/" in pattern:
                    # Intake manifests and conflict notes sit one folder below their queue, at any depth of folder name.
                    prefix, _, leaf = pattern.partition("/**/")
                    matching = [f"{prefix}/{leaf.replace('*', 'sample')}", f"{prefix}/nested/deeper/{leaf.replace('*', 'sample')}"]
                    non_markdown = [f"{prefix}/notes.txt", f"{prefix}/nested/notes.yaml"]
                else:
                    # Wiki pages sit directly in their directory: the wiki reads no sub-folders.
                    prefix, _, leaf = pattern.rpartition("/")
                    sample = leaf.replace("*", "sample")
                    matching = [f"{prefix}/{sample}"]
                    non_markdown = [f"{prefix}/notes.txt", f"{prefix}/nested/{sample}", f"{prefix}/nested/deeper/{sample}"]
                for path in matching:
                    with self.subTest(skill=skill, pattern=pattern, advertised_match=path):
                        self.service._assert_skill_write_path(skill, path)
                for path in non_markdown:
                    with self.subTest(skill=skill, pattern=pattern, non_markdown=path), self.assertRaises(BoardError) as error:
                        self.service._assert_skill_write_path(skill, path)
                    self.assertEqual("write_path_unavailable", error.exception.code)

        for skill in expected:
            for managed in ("knowledge/wiki/index.md", "knowledge/wiki/log.md"):
                with self.subTest(skill=skill, managed_path=managed), self.assertRaises(BoardError) as error:
                    self.service._assert_skill_write_path(skill, managed)
                self.assertEqual("write_path_unavailable", error.exception.code)
            if skill in {"po-intake", "design-intake"}:
                self.assertNotIn("knowledge/intake/pending/**", discovered[skill]["write_scopes"])
                self.assertTrue(any("read-only move source" in item for item in discovered[skill]["limitations"]))

    def test_workspace_reads_preserve_utf8_bom_and_crlf_digest(self) -> None:
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = b"\xef\xbb\xbf" + _feature_page().replace("\n", "\r\n").encode("utf-8")
        path.write_bytes(raw)

        result = self.service.read_workspace(self.actor, [FEATURE_PATH.as_posix()])["files"][0]
        self.assertEqual(raw.decode("utf-8"), result["content"])
        self.assertEqual(f"sha256:{hashlib.sha256(raw).hexdigest()}", result["digest"])
        frontmatter, _body = _parse_markdown(result["content"])
        self.assertEqual("F-001", frontmatter["id"])

    def test_text_and_intake_reads_stay_bounded_if_files_grow_after_stat(self) -> None:
        limit = 512 * 1024
        oversized = b"x" * (limit + 1)
        observed_sizes: list[int] = []

        class GrowingStream(BytesIO):
            def read(self, size: int = -1) -> bytes:
                observed_sizes.append(size)
                return super().read(size)

        original_open = Path.open

        def growing_open(candidate, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            target = self.root / "knowledge/wiki/SCHEMA.md"
            if candidate == target and mode == "rb":
                return GrowingStream(oversized)
            return original_open(candidate, *args, **kwargs)

        schema = self.root / "knowledge/wiki/SCHEMA.md"
        schema.write_bytes(b"small before concurrent growth")
        with patch.object(Path, "open", growing_open):
            with self.assertRaises(BoardError) as text_error:
                self.service._read_text(schema)
        self.assertEqual("text_file_limit", text_error.exception.code)
        self.assertEqual([limit + 1], observed_sizes)

        observed_sizes.clear()
        source = self.root / INTAKE_ITEM.parent
        brief = self.root / INTAKE_ITEM

        def growing_intake_open(candidate, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if candidate == brief and mode == "rb":
                return GrowingStream(oversized)
            return original_open(candidate, *args, **kwargs)

        with patch.object(Path, "open", growing_intake_open):
            with self.assertRaises(BoardError) as intake_error:
                self.service._validate_intake_source_tree(source)
        self.assertEqual("intake_source_unsupported", intake_error.exception.code)
        self.assertIn("over 512 KiB", intake_error.exception.message)
        self.assertEqual([limit + 1], observed_sizes)

    def test_parse_markdown_normalizes_only_known_yaml_date_scalars(self) -> None:
        content = (
            "---\nintroduced: 2026-09-22\nlast-updated: 2026-09-22\n"
            "date: 2026-09-22\nunrelated-value: 2026-09-22\n---\nBody\n"
        )
        frontmatter, _body = _parse_markdown(content)
        self.assertEqual("2026-09-22", frontmatter["introduced"])
        self.assertEqual("2026-09-22", frontmatter["last-updated"])
        self.assertEqual("2026-09-22", frontmatter["date"])
        self.assertEqual("date", type(frontmatter["unrelated-value"]).__name__)

    def test_schema_boolean_cannot_reuse_an_integer_schema_grant(self) -> None:
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = True
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        with self.assertRaises(BoardError) as error:
            self.service.discover(self.actor)
        self.assertEqual("workspace_identity_changed", error.exception.code)

    def test_invalid_or_unmet_minimum_cli_blocks_grants_and_state_creation(self) -> None:
        for minimum in ("not-a-version", "99.0.0"):
            with self.subTest(minimum=minimum):
                root = create_core_workflow_fixture(self.root.parent / f"minimum-{minimum.replace('.', '-').replace('/', '-')}")
                manifest_path = root / "prism.workspace.yml"
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                manifest["workflow"] = {
                    "version": "1",
                    "board_id": str(uuid4()),
                    "mode": "workflow",
                    "asset_digest": asset_digest("1"),
                }
                manifest["min_prism_cli_version"] = minimum
                manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

                service = BoardService(root)
                self.addCleanup(service.close)
                compatibility = service.compatibility()
                self.assertTrue(compatibility["read_only"])
                self.assertIsNotNone(compatibility["reason"])
                with self.assertRaises(BoardError) as error:
                    service.create_participant("Should not be granted", "agent", writable=True)
                self.assertEqual("workspace_read_only", error.exception.code)
                self.assertIsNone(service.store)
                self.assertFalse((root / ".prism" / "state" / "board.sqlite3").exists())

    def test_unmet_minimum_cli_invalidates_existing_grant_identity(self) -> None:
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["min_prism_cli_version"] = "99.0.0"
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        with self.assertRaises(BoardError) as error:
            self.service.discover(self.actor)
        self.assertEqual("workspace_identity_changed", error.exception.code)

    def test_noncanonical_fixed_path_invalidates_an_active_grant(self) -> None:
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["paths"] = {"wiki_root": "customer-wiki"}
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        with self.assertRaises(BoardError) as error:
            self.service.discover(self.actor)
        self.assertEqual("workspace_identity_changed", error.exception.code)

    def test_discover_and_list_skills_report_contract_2_and_state_read_support_once(self) -> None:
        discovered = self.service.discover(self.actor)
        listed = self.service.list_skills(self.actor)
        self.assertEqual(2, discovered["mcp_contract"])
        self.assertEqual(2, listed["mcp_contract"])
        self.assertEqual(listed["read_support"], discovered["capability"]["read_support"])
        self.assertTrue(discovered["skills"])
        for item in discovered["skills"]:
            self.assertEqual({"name", "description"}, set(item))
            self.assertTrue(item["description"])
        self.assertIn("list_skills", discovered["skills_detail"])
        self.assertIn("get_skill", discovered["skills_detail"])
        self.assertEqual({item["name"] for item in listed["skills"]}, {item["name"] for item in discovered["skills"]})
        for item in listed["skills"]:
            self.assertNotIn("read_support", item)
            self.assertIn("limitations", item)
            self.assertIn("write_scopes", item)

    def test_unknown_skill_and_reference_errors_are_typed(self) -> None:
        for call in (
            lambda: self.service.get_skill(self.actor, "no-such-skill"),
            lambda: self.service.get_skill_reference(self.actor, "no-such-skill", "knowledge/wiki/SCHEMA.md"),
        ):
            with self.assertRaises(BoardError) as error:
                call()
            self.assertEqual(("skill_not_found", 404), (error.exception.code, error.exception.status))
        with self.assertRaises(BoardError) as outside:
            self.service.get_skill_reference(self.actor, "po-intake", "knowledge/wiki/log.md")
        self.assertEqual(("reference_not_found", 404), (outside.exception.code, outside.exception.status))
        # A reference of another skill is outside this skill's reference paths.
        other_only = set(
            item["path"] for item in self.service.get_skill(self.actor, "design-intake")["skill"]["references"]
        ) - set(item["path"] for item in self.service.get_skill(self.actor, "wiki-show")["skill"]["references"])
        self.assertTrue(other_only)
        with self.assertRaises(BoardError) as foreign:
            self.service.get_skill_reference(self.actor, "wiki-show", sorted(other_only)[0])
        self.assertEqual("reference_not_found", foreign.exception.code)

    def test_unrelated_unknown_manifest_metadata_does_not_invalidate_grant(self) -> None:
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["customer_extension"] = {"owner": "review-team", "note": "keep"}
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        discovered = self.service.discover(self.actor)
        self.assertEqual(self.actor.participant_id, discovered["participant"]["participant_id"])

    def test_ask_requires_reviewed_sources_and_adds_one_open_question(self) -> None:
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_feature_page(), encoding="utf-8")
        original = self.service._read_text(path)
        proposed = original.replace(
            "| 1 | Which points should a review summary highlight? | po | open |",
            "| 1 | Which points should a review summary highlight? | po | open |\n"
            "| 2 | How should the review be organized? | designer | open |",
        )
        changes = [{"path": FEATURE_PATH.as_posix(), "content": proposed}]

        with self.assertRaises(BoardError) as missing:
            self.service.preview_skill(self.actor, "ask", changes)
        self.assertEqual("missing_read_revisions", missing.exception.code)
        self.assertIn(FEATURE_PATH.as_posix(), missing.exception.message)

        revisions = _read_revisions(self.service, self.actor, "ask", changes)
        preview = self.service.preview_skill(self.actor, "ask", changes, read_revisions=revisions)
        self.assertEqual("ready", preview["classification"])
        self.assertTrue(preview["applicable"])
        self.assertEqual("F-001", preview["feature_id"])

    def test_a_wrong_digest_is_told_apart_from_a_source_that_changed_after_it_was_read(self) -> None:
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_feature_page(), encoding="utf-8")
        relative = FEATURE_PATH.as_posix()
        original = self.service._read_text(path)
        proposed = original.replace(
            "| 1 | Which points should a review summary highlight? | po | open |",
            "| 1 | Which points should a review summary highlight? | po | open |\n"
            "| 2 | How should the review be organized? | designer | open |",
        )
        changes = [{"path": relative, "content": proposed}]
        revisions = _read_revisions(self.service, self.actor, "ask", changes)
        current = revisions[relative]

        # One mistyped character: the file did not change, the digest is wrong.
        mistyped = {**revisions, relative: current[:-1] + ("0" if current[-1] != "0" else "1")}
        with self.assertRaises(BoardError) as wrong:
            self.service.preview_skill(self.actor, "ask", changes, read_revisions=mistyped)
        self.assertEqual(("read_digest_mismatch", 409), (wrong.exception.code, wrong.exception.status))
        self.assertIn(current, wrong.exception.message)
        self.assertIn("is wrong", wrong.exception.message)
        self.assertIn("read_workspace", wrong.exception.message)
        self.assertNotIn("changed after", wrong.exception.message)
        self.assertEqual({"path": relative, "supplied": mistyped[relative], "expected": current}, wrong.exception.details)

        # A digest that was never returned for the file is wrong in the same way.
        invented = {**revisions, relative: "sha256:" + "ab" * 32}
        with self.assertRaises(BoardError) as unknown:
            self.service.preview_skill(self.actor, "ask", changes, read_revisions=invented)
        self.assertEqual("read_digest_mismatch", unknown.exception.code)

        # The right digest is accepted.
        self.assertTrue(self.service.preview_skill(self.actor, "ask", changes, read_revisions=revisions)["applicable"])

        # A digest the board returned, for text that has since changed, is a stale read.
        path.write_text(original + "\nEdited after the read.\n", encoding="utf-8")
        edited = self.service._read_text(path)
        with self.assertRaises(BoardError) as stale:
            self.service.preview_skill(self.actor, "ask", changes, read_revisions=revisions)
        self.assertEqual(("stale_read_revision", 409), (stale.exception.code, stale.exception.status))
        self.assertIn("changed after you read it", stale.exception.message)
        self.assertIn(current, stale.exception.message)
        self.assertEqual("sha256:" + hashlib.sha256(edited.encode("utf-8")).hexdigest(), stale.exception.details["expected"])

    def test_a_feature_outside_the_board_platforms_is_rejected_with_the_board_platforms(self) -> None:
        relative = FEATURE_PATH.as_posix()
        content = _feature_page().replace("platforms:\n- backend\n", "platforms:\n- web-user-app\n- backend\n")
        self.assertIn("web-user-app", content)
        with self.assertRaises(BoardError) as outside:
            self.service._validate_feature_output(relative, content, "po-intake")
        error = outside.exception
        self.assertEqual(("invalid_feature_output", 409), (error.code, error.status))
        self.assertIn("`web-user-app`", error.message)
        self.assertIn("this board's platforms are `backend`", error.message)
        self.assertEqual({"platforms": ["backend", "web-user-app"], "board_platforms": ["backend"]}, error.details)
        with self.assertRaises(BoardError) as empty:
            self.service._validate_feature_output(relative, content.replace("platforms:\n- web-user-app\n- backend\n", "platforms: []\n"), "po-intake")
        self.assertIn("nonempty `platforms` list", empty.exception.message)
        self.assertIn("`backend`", empty.exception.message)

    def test_discover_reports_the_board_platforms(self) -> None:
        self.assertEqual(["backend"], self.service.discover(self.actor)["board"]["platforms"])

    def test_a_section_that_differs_only_in_its_final_newline_is_named_as_whitespace(self) -> None:
        old = "## Open questions\nrow\n\n## Post-ship notes\nNot shipped yet.\n"
        new = "## Open questions\nrow\n\n## Post-ship notes\nNot shipped yet."
        with self.assertRaises(BoardError) as whitespace:
            BoardService._assert_only_body_sections_changed(old, new, {"Open questions"}, "clarify_scope_exceeded", "Clarify may update the question table only.")
        error = whitespace.exception
        self.assertEqual(("clarify_scope_exceeded", 409), (error.code, error.status))
        self.assertIn("`Post-ship notes`", error.message)
        self.assertIn("differ only in whitespace", error.message)
        self.assertIn("final newline", error.message)
        self.assertEqual({"sections": ["Post-ship notes"], "whitespace_only": ["Post-ship notes"]}, error.details)

        with self.assertRaises(BoardError) as content:
            BoardService._assert_only_body_sections_changed(old, old.replace("Not shipped yet.", "Shipped."), {"Open questions"}, "clarify_scope_exceeded", "Clarify may update the question table only.")
        self.assertNotIn("differ only in whitespace", content.exception.message)
        self.assertEqual({"sections": ["Post-ship notes"]}, content.exception.details)

    def test_an_ask_proposal_that_drops_the_final_newline_names_the_section_and_the_whitespace(self) -> None:
        _path, _original, changes = self._ask_proposal()
        trimmed = [{"path": changes[0]["path"], "content": changes[0]["content"].rstrip("\r\n")}]
        _read_revisions(self.service, self.actor, "ask", trimmed)
        with self.assertRaises(BoardError) as error:
            self.service.preview_skill(self.actor, "ask", trimmed)
        self.assertEqual(("ask_scope_exceeded", 409), (error.exception.code, error.exception.status))
        self.assertIn("`API surface`", error.exception.message)
        self.assertIn("differ only in whitespace", error.exception.message)
        self.assertEqual({"sections": ["API surface"], "whitespace_only": ["API surface"]}, error.exception.details)

    def test_a_body_scope_rejection_names_the_first_line_that_differs(self) -> None:
        old = "## Open questions\n| # | Q | O | S |\n|---|----------|-------|--------|\n\n## Post-ship notes\nNot shipped yet.\n"
        table = old.replace("|---|----------|-------|--------|", "|---|---|---|---|")
        with self.assertRaises(BoardError) as changed:
            BoardService._assert_only_body_sections_changed(old, table, set(), "lifecycle_body_scope", "Action `design-handoff` changes only lifecycle metadata on the feature page.")
        self.assertEqual({"sections": ["Open questions"]}, changed.exception.details)
        self.assertIn("`Open questions`", changed.exception.message)
        self.assertIn("current line `|---|----------|-------|--------|`, proposed line `|---|---|---|---|`", changed.exception.message)

        # A section heading that the proposal adds changes no named section, so the message quotes the heading.
        added = old + "\n## Reopen history\n"
        with self.assertRaises(BoardError) as heading:
            BoardService._assert_only_body_sections_changed(old, added, {"Delivery evidence", "Post-ship notes"}, "lifecycle_body_scope", "Dev done may update delivery evidence and post-ship notes only.")
        self.assertIn("the proposal adds the line `## Reopen history`", heading.exception.message)
        self.assertIn("add or remove no section heading", heading.exception.message)
        self.assertEqual({"current_line": "", "proposed_line": "## Reopen history"}, {key: heading.exception.details[key] for key in ("current_line", "proposed_line")})

        # A missing final newline tells the agent to end the content with one.
        with self.assertRaises(BoardError) as newline:
            BoardService._assert_only_body_sections_changed(old, old.rstrip("\n"), {"Open questions"}, "clarify_scope_exceeded", "Clarify may update the question table only.")
        self.assertIn("end `content` with one", newline.exception.message)

    def test_a_status_change_by_a_clarify_skill_names_the_skill_rule(self) -> None:
        error = BoardService._lifecycle_change_error("po-clarify", "knowledge/wiki/features/F-001-x.md", {"status": "raw", "owner": "po"}, {"status": "specified", "owner": "po"})
        self.assertEqual(("lifecycle_action_required", 409), (error.code, error.status))
        self.assertIn("`raw` / `po` to `specified` / `po`", error.message)
        self.assertIn("`po-clarify` never changes status or owner", error.message)
        lifecycle = BoardService._lifecycle_change_error("po-specify", "knowledge/wiki/features/F-001-x.md", {"status": "raw", "owner": "po"}, {"status": "done", "owner": "none"})
        self.assertIn("`po-specify` moves a feature only from `raw` / `po` to `specified` / `po`", lifecycle.message)

    def test_a_question_that_is_not_in_the_table_is_named_as_new_and_must_be_open(self) -> None:
        path, original, _changes = self._ask_proposal()
        invented = original.replace(
            "| 1 | Which points should a review summary highlight? | po | open |",
            "| 1 | Which points should a review summary highlight? | po | open |\n"
            "| 2 | Where does the export control appear? | designer | resolved: On the review page. |",
        )
        self.assertNotEqual(original, invented)
        with self.assertRaises(BoardError) as error:
            self.service._validate_question_change("design-clarify", FEATURE_PATH.as_posix(), original, invented)
        self.assertEqual(("new_question_must_be_open", 409), (error.exception.code, error.exception.status))
        self.assertIn("Question 2", error.exception.message)
        self.assertIn("its numbers are 1", error.exception.message)
        self.assertIn("ask skill", error.exception.message)
        self.assertEqual({"path": FEATURE_PATH.as_posix(), "question": "2", "existing_questions": ["1"]}, error.exception.details)

    def test_every_listed_reference_of_every_skill_resolves_through_get_skill_reference(self) -> None:
        names = [item["name"] for item in self.service.list_skills(self.actor)["skills"]]
        self.assertEqual(24, len(names))
        for name in names:
            with self.subTest(skill=name):
                page = self.service.get_skill(self.actor, name)
                instructions = page["skill"]["instructions"]
                while page["next_cursor"] is not None:
                    page = self.service.get_skill(self.actor, name, page["next_cursor"])
                    instructions += page["skill"]["instructions"]
                index = {item["path"]: item for item in page["skill"]["references"]}
                self.assertTrue(index)
                listed = set(index)
                # A path the instructions list as a canonical reference must be one of the skill's references, written the same way.
                marker = instructions.find("## Canonical format reference")
                if marker >= 0:
                    section = instructions[marker:].split("\n## ")[0]
                    named = re.findall(r"^- `([^`]+)`\s*$", section, flags=re.MULTILINE)
                    self.assertTrue(named, section)
                    listed.update(named)
                for path in sorted(listed):
                    with self.subTest(skill=name, reference=path):
                        chunk = self.service.get_skill_reference(self.actor, name, path)
                        text = chunk["content"]
                        while chunk["next_cursor"] is not None:
                            chunk = self.service.get_skill_reference(self.actor, name, path, chunk["next_cursor"])
                            text += chunk["content"]
                        self.assertEqual(len(text), chunk["total_chars"])
                        self.assertEqual("sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(), chunk["digest"])
                        if path in index:
                            self.assertEqual(index[path]["digest"], chunk["digest"])

    def _ask_proposal(self) -> tuple[Path, str, list[dict[str, str]]]:
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_feature_page(), encoding="utf-8")
        original = self.service._read_text(path)
        proposed = original.replace(
            "| 1 | Which points should a review summary highlight? | po | open |",
            "| 1 | Which points should a review summary highlight? | po | open |\n"
            "| 2 | How should the review be organized? | designer | open |",
        )
        return path, original, [{"path": FEATURE_PATH.as_posix(), "content": proposed}]

    def test_omitted_read_revisions_are_filled_from_the_participants_own_reads(self) -> None:
        _path, _original, changes = self._ask_proposal()
        explicit = _read_revisions(self.service, self.actor, "ask", changes)

        filled = self.service.preview_skill(self.actor, "ask", changes)
        self.assertEqual("ready", filled["classification"])
        self.assertTrue(filled["applicable"])
        self.assertEqual(explicit, filled["read_revisions"])

        supplied = self.service.preview_skill(self.actor, "ask", changes, read_revisions=explicit)
        self.assertEqual(supplied["read_revisions"], filled["read_revisions"])
        self.assertEqual(supplied["source_revision"], filled["source_revision"])

        # A supplied digest still wins over the recorded one and is checked on its own.
        relative = FEATURE_PATH.as_posix()
        wrong = {relative: "sha256:" + "ab" * 32}
        with self.assertRaises(BoardError) as mismatch:
            self.service.preview_skill(self.actor, "ask", changes, read_revisions=wrong)
        self.assertEqual("read_digest_mismatch", mismatch.exception.code)

        # The filled preview applies like any other.
        applied = self.service.apply(self.actor, filled["preview_id"], str(uuid4()))
        self.assertEqual("applied", applied["state"])

    def test_another_participants_reads_are_never_used_to_fill_revisions(self) -> None:
        _path, _original, changes = self._ask_proposal()
        other = self.service.authenticate(self.service.create_participant("Other agent", "agent", writable=True)["token"])
        _read_revisions(self.service, other, "ask", changes)

        with self.assertRaises(BoardError) as missing:
            self.service.preview_skill(self.actor, "ask", changes)
        self.assertEqual(("missing_read_revisions", 409), (missing.exception.code, missing.exception.status))

        # The participant that read is served, the one that did not is not.
        self.assertTrue(self.service.preview_skill(other, "ask", changes)["applicable"])
        with self.assertRaises(BoardError) as still_missing:
            self.service.preview_skill(self.actor, "ask", changes)
        self.assertEqual("missing_read_revisions", still_missing.exception.code)

    def test_an_unread_path_is_still_rejected_and_the_error_lists_what_to_read(self) -> None:
        _path, original, changes = self._ask_proposal()
        relative = FEATURE_PATH.as_posix()
        required = sorted(self.service._required_skill_revision_paths("ask", {c["path"]: c["content"] for c in changes}, {relative: original}, []))
        self.assertGreater(len(required), 1)
        unread = relative
        # Read every required source except the feature page.
        self.service.read_workspace(self.actor, [path for path in required if path != unread])

        with self.assertRaises(BoardError) as missing:
            self.service.preview_skill(self.actor, "ask", changes)
        error = missing.exception
        self.assertEqual(("missing_read_revisions", 409), (error.code, error.status))
        self.assertEqual([unread], error.details["paths"])
        self.assertEqual(1, error.details["total"])
        self.assertEqual("read_workspace", error.details["read_with"])
        self.assertIn(unread, error.message)
        self.assertIn("read_workspace", error.message)
        self.assertIn("read them", error.message.lower())

        # Reading it supplies the last digest.
        self.service.read_workspace(self.actor, [unread])
        self.assertTrue(self.service.preview_skill(self.actor, "ask", changes)["applicable"])

    def test_a_large_missing_list_keeps_the_message_and_details_short(self) -> None:
        error = BoardService._missing_read_revisions_error([f"knowledge/wiki/features/F-{number:03d}-" + "x" * 60 + ".md" for number in range(60)])
        self.assertEqual("missing_read_revisions", error.code)
        self.assertLess(len(error.message), 1500)
        self.assertIsNotNone(error.details)
        self.assertEqual(60, error.details["total"])
        self.assertLess(len(error.details["paths"]), 60)
        self.assertRegex(error.message, r"and \d+ more")

    def test_a_file_changed_after_the_participants_read_is_rejected_as_stale(self) -> None:
        path, original, changes = self._ask_proposal()
        read = _read_revisions(self.service, self.actor, "ask", changes)
        path.write_bytes((original + "\nEdited after the read.\n").encode("utf-8"))

        with self.assertRaises(BoardError) as stale:
            self.service.preview_skill(self.actor, "ask", changes)
        self.assertEqual(("stale_read_revision", 409), (stale.exception.code, stale.exception.status))
        self.assertIn("changed after you read it", stale.exception.message)
        self.assertEqual(read[FEATURE_PATH.as_posix()], stale.exception.details["supplied"])

        # The same rejection as when the digest is supplied by hand.
        with self.assertRaises(BoardError) as supplied:
            self.service.preview_skill(self.actor, "ask", changes, read_revisions=read)
        self.assertEqual(stale.exception.code, supplied.exception.code)
        self.assertEqual(stale.exception.details, supplied.exception.details)

        # Reading again recovers.
        edited = self.service._read_text(path)
        self.assertNotEqual(edited, original)
        proposed = [{"path": changes[0]["path"], "content": changes[0]["content"] + "\nEdited after the read.\n"}]
        _read_revisions(self.service, self.actor, "ask", proposed)
        self.assertTrue(self.service.preview_skill(self.actor, "ask", proposed)["applicable"])

    def test_a_service_restart_clears_the_recorded_reads(self) -> None:
        _path, _original, changes = self._ask_proposal()
        _read_revisions(self.service, self.actor, "ask", changes)
        self.assertTrue(self.service.preview_skill(self.actor, "ask", changes)["applicable"])
        token = self.service.create_participant("Restart agent", "agent", writable=True)["token"]
        before = self.service.authenticate(token)
        _read_revisions(self.service, before, "ask", changes)
        self.service.close()

        restarted = BoardService(self.root).start()
        self.addCleanup(restarted.close)
        after = restarted.authenticate(token)
        with self.assertRaises(BoardError) as missing:
            restarted.preview_skill(after, "ask", changes)
        self.assertEqual("missing_read_revisions", missing.exception.code)
        _read_revisions(restarted, after, "ask", changes)
        self.assertTrue(restarted.preview_skill(after, "ask", changes)["applicable"])

    def test_only_a_file_received_in_full_counts_as_read(self) -> None:
        relative = FEATURE_PATH.as_posix()
        digest = "sha256:" + "cd" * 32
        self.service._remember_participant_reads(
            self.actor,
            [{"path": relative, "content": "a" * 10, "offset": 0, "total_chars": 25, "digest": digest}],
        )
        self.assertEqual({}, self.service._participant_read_digests(self.actor))
        self.service._remember_participant_reads(
            self.actor,
            [{"path": relative, "content": "a" * 15, "offset": 10, "total_chars": 25, "digest": digest}],
        )
        self.assertEqual({relative.casefold(): digest}, self.service._participant_read_digests(self.actor))

    def test_po_clarify_cannot_resolve_a_designer_owned_question(self) -> None:
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_feature_page().replace("| po | open |", "| designer | open |"), encoding="utf-8")
        original = self.service._read_text(path)
        proposed = original.replace(
            "| 1 | Which points should a review summary highlight? | designer | open |",
            "| 1 | Which points should a review summary highlight? | designer | resolved: Capture key points. |",
        )
        changes = [{"path": FEATURE_PATH.as_posix(), "content": proposed}]

        with self.assertRaises(BoardError) as error:
            self.service.preview_skill(
                self.actor,
                "po-clarify",
                changes,
                read_revisions=_read_revisions(self.service, self.actor, "po-clarify", changes),
            )
        self.assertEqual("question_owner_mismatch", error.exception.code)

    def test_design_clarify_rejects_unrelated_design_edits(self) -> None:
        feature_path = self.root / FEATURE_PATH
        feature_path.parent.mkdir(parents=True, exist_ok=True)
        feature_path.write_text(_feature_page().replace("| po | open |", "| designer | open |"), encoding="utf-8")
        original_feature = self.service._read_text(feature_path)

        design_relative = "knowledge/wiki/design/F-001-document-review.md"
        design_path = self.root / design_relative
        design_path.parent.mkdir(parents=True, exist_ok=True)
        design_path.write_text(_design_page(), encoding="utf-8")
        original_design = self.service._read_text(design_path)

        proposed_feature = original_feature.replace(
            "| 1 | Which points should a review summary highlight? | designer | open |",
            "| 1 | Which points should a review summary highlight? | designer | resolved: Use a concise bulleted summary. |",
        )
        proposed_design = original_design.replace(
            "The reviewer sees the document title and review status.",
            "The reviewer opens a modal panel for every document.",
        )
        changes = [
            {"path": FEATURE_PATH.as_posix(), "content": proposed_feature},
            {"path": design_relative, "content": proposed_design},
        ]

        with self.assertRaises(BoardError) as error:
            self.service.preview_skill(
                self.actor,
                "design-clarify",
                changes,
                read_revisions=_read_revisions(self.service, self.actor, "design-clarify", changes),
            )
        self.assertEqual("design_answer_unlinked", error.exception.code)

    # Rejected proposals: every rejection keeps its code and names the place and the fix.

    def _write_feature_page(self, page: str | None = None) -> str:
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page if page is not None else _feature_page(), encoding="utf-8")
        return self.service._read_text(path)

    def _rejected_preview(self, skill: str, changes: list, moves: list | None = None, **kwargs) -> BoardError:
        with self.assertRaises(BoardError) as caught:
            self.service.preview_skill(self.actor, skill, changes, moves, **kwargs)
        return caught.exception

    def _assert_error_is_small(self, error: BoardError) -> None:
        import json

        self.assertLess(len(error.message) + len(json.dumps(error.details)), 2000)

    def test_unlinked_clarify_answer_names_section_questions_and_answer_start(self) -> None:
        original = self._write_feature_page()
        answer = "Capture key points. " * 15
        proposed = original.replace(
            "| 1 | Which points should a review summary highlight? | po | open |",
            f"| 1 | Which points should a review summary highlight? | po | resolved: {answer.strip()} |",
        ).replace(
            "Review a document, summarize its key points, and record the review outcome.",
            "A different wording of the same idea.",
        )
        changes = [{"path": FEATURE_PATH.as_posix(), "content": proposed}]

        error = self._rejected_preview(
            "po-clarify", changes, read_revisions=_read_revisions(self.service, self.actor, "po-clarify", changes)
        )

        self.assertEqual("clarify_answer_unlinked", error.code)
        self.assertEqual(409, error.status)
        self.assertIn("`Summary`", error.message)
        self.assertIn(FEATURE_PATH.as_posix(), error.message)
        self.assertIn("question(s) 1", error.message)
        self.assertIn("verbatim", error.message)
        self.assertEqual("Summary", error.details["section"])
        self.assertEqual(FEATURE_PATH.as_posix(), error.details["path"])
        self.assertEqual(["1"], error.details["resolved_questions"])
        start = error.details["resolved_answers"]["1"]
        self.assertLessEqual(len(start), 160)
        self.assertTrue(start.startswith("Capture key points. Capture key points."))
        self._assert_error_is_small(error)

    def test_unlinked_design_answer_names_section_and_designer_questions(self) -> None:
        original_feature = self._write_feature_page(_feature_page().replace("| po | open |", "| designer | open |"))
        design_relative = "knowledge/wiki/design/F-001-document-review.md"
        design_path = self.root / design_relative
        design_path.parent.mkdir(parents=True, exist_ok=True)
        design_path.write_text(_design_page(), encoding="utf-8")
        proposed_feature = original_feature.replace(
            "| 1 | Which points should a review summary highlight? | designer | open |",
            "| 1 | Which points should a review summary highlight? | designer | resolved: Use a concise bulleted summary. |",
        )
        proposed_design = self.service._read_text(design_path).replace(
            "The reviewer sees the document title and review status.",
            "The reviewer opens a modal panel for every document.",
        )
        changes = [
            {"path": FEATURE_PATH.as_posix(), "content": proposed_feature},
            {"path": design_relative, "content": proposed_design},
        ]

        error = self._rejected_preview(
            "design-clarify", changes, read_revisions=_read_revisions(self.service, self.actor, "design-clarify", changes)
        )

        self.assertEqual("design_answer_unlinked", error.code)
        self.assertEqual(409, error.status)
        self.assertIn("`Summary`", error.message)
        self.assertIn(design_relative, error.message)
        self.assertIn("designer-owned question(s) 1", error.message)
        self.assertEqual("Summary", error.details["section"])
        self.assertEqual(design_relative, error.details["path"])
        self.assertEqual(["1"], error.details["resolved_questions"])
        self.assertEqual({"1": "Use a concise bulleted summary."}, error.details["resolved_answers"])

    def test_invalid_yaml_names_path_line_column_and_problem(self) -> None:
        original = self._write_feature_page()
        proposed = original.replace(
            "| 1 | Which points should a review summary highlight? | po | open |",
            "| 1 | Which points should a review summary highlight? | po | open |\n"
            "| 2 | How should the review be organized? | designer | open |",
        ).replace("title: Document review", "title: Document review: bad", 1)
        line = proposed.splitlines().index("title: Document review: bad") + 1
        changes = [{"path": FEATURE_PATH.as_posix(), "content": proposed}]

        error = self._rejected_preview(
            "ask", changes, read_revisions=_read_revisions(self.service, self.actor, "ask", changes)
        )

        self.assertEqual("invalid_frontmatter", error.code)
        self.assertEqual(409, error.status)
        self.assertIn(FEATURE_PATH.as_posix(), error.message)
        self.assertIn(f"line {line}, column 23", error.message)
        self.assertIn("mapping values are not allowed here", error.message)
        self.assertEqual(
            {
                "path": FEATURE_PATH.as_posix(),
                "line": line,
                "column": 23,
                "problem": "mapping values are not allowed here",
            },
            error.details,
        )

    def test_page_without_frontmatter_explains_the_required_shape(self) -> None:
        self._write_feature_page()
        changes = [{"path": FEATURE_PATH.as_posix(), "content": "## Summary\nNo frontmatter here.\n"}]

        error = self._rejected_preview(
            "ask", changes, read_revisions=_read_revisions(self.service, self.actor, "ask", changes)
        )

        self.assertEqual("invalid_markdown", error.code)
        self.assertEqual(409, error.status)
        self.assertIn(FEATURE_PATH.as_posix(), error.message)
        self.assertIn("`---`", error.message)
        self.assertIn("YAML mapping", error.message)
        self.assertIn("closing `---`", error.message)
        self.assertEqual(FEATURE_PATH.as_posix(), error.details["path"])

    def test_malformed_change_and_move_items_name_index_and_fields(self) -> None:
        good = {"path": FEATURE_PATH.as_posix(), "content": "x"}

        error = self._rejected_preview("ask", [good, {"path": "knowledge/wiki/features/F-002.md", "body": "x"}])
        self.assertEqual(("invalid_change", 400), (error.code, error.status))
        self.assertIn("`changes[1]`", error.message)
        self.assertIn("`content`", error.message)
        self.assertIn("`body`", error.message)
        self.assertEqual(
            {"index": 1, "missing": ["content"], "unexpected": ["body"], "expected": ["path", "content"]},
            error.details,
        )

        error = self._rejected_preview("po-intake", [good], [{"source": "knowledge/intake/pending/a"}])
        self.assertEqual(("invalid_move", 400), (error.code, error.status))
        self.assertIn("`moves[0]`", error.message)
        self.assertEqual(
            {"index": 0, "missing": ["destination"], "unexpected": [], "expected": ["source", "destination"]},
            error.details,
        )

        error = self._rejected_preview("po-intake", [good], [{"source": "a", "destination": "b", "extra": "c"}])
        self.assertEqual("invalid_move", error.code)
        self.assertEqual(["extra"], error.details["unexpected"])

        error = self._rejected_preview("po-intake", [good], [{"source": "a", "destination": "b"}] * 2)
        self.assertEqual(("invalid_moves", 400), (error.code, error.status))
        self.assertIn("`moves[1]`", error.message)
        self.assertEqual({"index": 1, "maximum": 1, "received": 2}, error.details)

        error = self._rejected_preview("ask", [good] * 129)
        self.assertEqual(("invalid_changes", 400), (error.code, error.status))
        self.assertIn("`changes[128]`", error.message)
        self.assertEqual({"index": 128, "maximum": 128, "received": 129}, error.details)

    def test_lifecycle_scope_error_lists_path_and_offending_fields(self) -> None:
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_feature_page(), encoding="utf-8")
        original = _set_feature_stage(self.service._read_text(path), "specified", "po", self.service)
        path.write_bytes(original.encode("utf-8"))
        _write_index(self.root, "specified", "po")
        proposed = _set_feature_stage(original, "ready-for-design", "designer", self.service).replace(
            "title: Document review", "title: Renamed review", 1
        )
        changes = [{"path": FEATURE_PATH.as_posix(), "content": proposed}]

        error = self._rejected_preview(
            "po-handoff", changes, read_revisions=_read_revisions(self.service, self.actor, "po-handoff", changes)
        )

        self.assertEqual(("lifecycle_frontmatter_scope", 409), (error.code, error.status))
        self.assertIn(FEATURE_PATH.as_posix(), error.message)
        self.assertIn("title", error.message)
        self.assertEqual(FEATURE_PATH.as_posix(), error.details["path"])
        self.assertEqual(["title"], error.details["fields"])
        self.assertIn("status", error.details["allowed"])

    def test_unknown_and_clarify_frontmatter_errors_list_fields(self) -> None:
        original = self._write_feature_page()
        question_row = "| 1 | Which points should a review summary highlight? | po | open |"
        added = question_row + "\n| 2 | How should the review be organized? | designer | open |"

        with_unknown = original.replace(question_row, added).replace(
            "advisory-review: not-needed", "advisory-review: not-needed\nreviewer: Alex", 1
        )
        changes = [{"path": FEATURE_PATH.as_posix(), "content": with_unknown}]
        error = self._rejected_preview(
            "ask", changes, read_revisions=_read_revisions(self.service, self.actor, "ask", changes)
        )
        self.assertEqual(("unknown_frontmatter_fields", 409), (error.code, error.status))
        self.assertIn(FEATURE_PATH.as_posix(), error.message)
        self.assertIn("reviewer", error.message)
        self.assertEqual(FEATURE_PATH.as_posix(), error.details["path"])
        self.assertEqual(["reviewer"], error.details["fields"])

        retitled = original.replace(question_row, added).replace("title: Document review", "title: Renamed review", 1)
        changes = [{"path": FEATURE_PATH.as_posix(), "content": retitled}]
        error = self._rejected_preview(
            "ask", changes, read_revisions=_read_revisions(self.service, self.actor, "ask", changes)
        )
        self.assertEqual(("clarify_frontmatter_change", 409), (error.code, error.status))
        self.assertIn(FEATURE_PATH.as_posix(), error.message)
        self.assertIn("title", error.message)
        self.assertEqual({"path": FEATURE_PATH.as_posix(), "fields": ["title"]}, error.details)

    def test_design_clarify_frontmatter_change_lists_design_path_and_fields(self) -> None:
        original_feature = self._write_feature_page(_feature_page().replace("| po | open |", "| designer | open |"))
        design_relative = "knowledge/wiki/design/F-001-document-review.md"
        design_path = self.root / design_relative
        design_path.parent.mkdir(parents=True, exist_ok=True)
        design_path.write_text(_design_page(), encoding="utf-8")
        proposed_feature = original_feature.replace(
            "| 1 | Which points should a review summary highlight? | designer | open |",
            "| 1 | Which points should a review summary highlight? | designer | resolved: Use a concise bulleted summary. |",
        )
        proposed_design = self.service._read_text(design_path).replace("designer: Reviewer", "designer: Someone Else", 1)
        changes = [
            {"path": FEATURE_PATH.as_posix(), "content": proposed_feature},
            {"path": design_relative, "content": proposed_design},
        ]

        error = self._rejected_preview(
            "design-clarify", changes, read_revisions=_read_revisions(self.service, self.actor, "design-clarify", changes)
        )

        self.assertEqual(("design_frontmatter_change", 409), (error.code, error.status))
        self.assertIn(design_relative, error.message)
        self.assertEqual({"path": design_relative, "fields": ["designer"]}, error.details)

    def test_error_details_are_json_safe_and_small(self) -> None:
        self.assertIsNone(BoardError("x", "m", 400).details)
        self.assertIsNone(BoardError("x", "m", 400, {}).details)
        self.assertIsNone(BoardError("x", "m", 400, {"bad": object()}).details)
        self.assertIsNone(BoardError("x", "m", 400, {"long": "a" * 5000}).details)
        self.assertEqual({"a": [1, "b"]}, BoardError("x", "m", 400, {"a": (1, "b")}).details)

    def test_po_handoff_cannot_rewrite_feature_body(self) -> None:
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_feature_page(), encoding="utf-8")
        original = _set_feature_stage(self.service._read_text(path), "specified", "po", self.service)
        path.write_bytes(original.encode("utf-8"))
        _write_index(self.root, "specified", "po")
        proposed = _set_feature_stage(
            original.replace(
                "Review a document, summarize its key points, and record the review outcome.",
                "Replace the document-review workflow with a different product behavior.",
                1,
            ),
            "ready-for-design",
            "designer",
            self.service,
        )
        changes = [{"path": FEATURE_PATH.as_posix(), "content": proposed}]

        with self.assertRaises(BoardError) as error:
            self.service.preview_skill(
                self.actor,
                "po-handoff",
                changes,
                read_revisions=_read_revisions(self.service, self.actor, "po-handoff", changes),
            )
        self.assertEqual("lifecycle_body_scope", error.exception.code)

    def test_reopen_requires_every_substantive_impact_record_field(self) -> None:
        old = _set_feature_stage(_feature_page(), "done", "none")
        old += (
            "\n## Delivery evidence\n"
            "| Platform | Implementation | Tests | Release |\n"
            "|---|---|---|---|\n"
            "| backend | Reviewed source record | Review check passed | Review release record |\n"
            "\n## Reopen history\n"
        )
        proposed = _set_feature_stage(old, "in-dev", "dev")
        proposed = proposed.replace(
            "revalidation: []",
            "revalidation:\n- implementation\n- tests\n- release",
        )
        proposed += (
            "\n### 2026-09-22 - reopen-dev\n"
            "- Reason: A new review requirement changes the outcome.\n"
            "- Impact review: The backend outcome and test need renewed review.\n"
            "- Affected platforms: backend\n"
        )
        old_frontmatter, _body = _parse_markdown(old)

        with self.assertRaises(BoardError) as error:
            self.service._validate_reopen_record("reopen-dev", old, proposed, old_frontmatter, {}, {})
        self.assertEqual("impact_review_required", error.exception.code)
        self.assertIn("Affected artifacts", error.exception.message)

    def test_proposed_duplicate_persona_ids_are_rejected(self) -> None:
        source = INTAKE_ITEM.as_posix().rsplit("/", 1)[0]
        pending_dir = self.root / source
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "empty" / "nested").mkdir(parents=True)

        feature_relative = "knowledge/wiki/features/F-002-document-review.md"
        feature = _feature_page().replace("F-001", "F-002").replace("Document review", "Second document review")
        feature = _set_feature_stage(feature, "raw", "po").replace(
            "knowledge/intake/processed/document-review-brief/brief.md",
            "knowledge/intake/processed/document-review-brief/brief.md",
        )
        persona_one = _persona_page("Reviewer")
        persona_two = _persona_page("Reader")
        persona_paths = [
            "knowledge/wiki/personas/P-001-reviewer.md",
            "knowledge/wiki/personas/P-001-reader.md",
        ]
        manifest_relative = "knowledge/intake/processed/document-review-brief/MANIFEST.md"
        manifest = (
            "# Processed intake\n\n"
            f"- {feature_relative} (F-002)\n"
            f"- {persona_paths[0]} (P-001)\n"
            f"- {persona_paths[1]} (P-001)\n"
        )
        changes = [
            {"path": feature_relative, "content": feature},
            {"path": persona_paths[0], "content": persona_one},
            {"path": persona_paths[1], "content": persona_two},
            {"path": manifest_relative, "content": manifest},
        ]
        moves = [{"source": source, "destination": source.replace("pending", "processed", 1)}]

        with self.assertRaises(BoardError) as error:
            self.service.preview_skill(
                self.actor,
                "po-intake",
                changes,
                moves,
                read_revisions=_read_revisions(self.service, self.actor, "po-intake", changes, moves),
            )
        self.assertEqual("duplicate_wiki_id", error.exception.code)

        directories = self.service._tree_directories(pending_dir)
        self.assertEqual(["empty", "empty/nested"], directories)

    def test_intake_rejects_every_unsupported_oversized_or_non_utf8_source(self) -> None:
        source = INTAKE_ITEM.parent.as_posix()
        source_dir = self.root / source
        moves = [{"source": source, "destination": source.replace("pending", "processed", 1)}]
        cases = (
            ("scan.pdf", b"%PDF synthetic attachment"),
            ("large.md", b"x" * (512 * 1024 + 1)),
            ("invalid.txt", b"\xff not UTF-8"),
        )

        for name, payload in cases:
            with self.subTest(name=name):
                path = source_dir / name
                path.write_bytes(payload)
                try:
                    if name == "scan.pdf":
                        open_file = Path.open

                        def reject_attachment_content(candidate, *args, **kwargs):
                            if candidate == path:
                                raise AssertionError("intake preview attempted to open the unsupported attachment")
                            return open_file(candidate, *args, **kwargs)

                        content_guard = patch.object(Path, "open", reject_attachment_content)
                    else:
                        content_guard = nullcontext()
                    with content_guard:
                        for skill, feature_path in (
                            ("po-intake", "knowledge/wiki/features/F-002-document-review.md"),
                            ("design-intake", "knowledge/wiki/features/F-001-document-review.md"),
                        ):
                            proposed = [{"path": feature_path, "content": "---\n---\n"}]
                            with self.subTest(name=name, skill=skill), self.assertRaises(BoardError) as error:
                                self.service.preview_skill(self.actor, skill, proposed, moves, read_revisions={})
                            self.assertEqual("intake_source_unsupported", error.exception.code)
                            self.assertIn(name, error.exception.message)
                finally:
                    path.unlink(missing_ok=True)

    def _po_intake_proposal(self, sources: list[str]) -> tuple[list[dict[str, str]], list[dict[str, str]], str]:
        pending = INTAKE_ITEM.parent.as_posix()
        processed = pending.replace("pending", "processed", 1)
        feature_path = "knowledge/wiki/features/F-002-document-review.md"
        feature = _unquote_yaml_date_fields(
            _journey_feature_page(
                "F-002", "Document review", "raw", "po", sources,
                ["| 1 | Which details should the summary emphasize? | po | open |"],
            )
        )
        manifest = f"# Processed intake\n\n- {feature_path} (F-002)\n"
        changes = [
            {"path": feature_path, "content": feature},
            {"path": processed + "/MANIFEST.md", "content": manifest},
        ]
        return changes, [{"source": pending, "destination": processed}], feature_path

    def _preview_po_intake(self, sources: list[str]) -> dict[str, Any]:
        changes, moves, _feature_path = self._po_intake_proposal(sources)
        return self.service.preview_skill(
            self.actor, "po-intake", changes, moves, read_revisions=_read_revisions(self.service, self.actor, "po-intake", changes, moves)
        )

    def test_po_intake_rejects_a_pending_source_and_writes_nothing(self) -> None:
        pending = INTAKE_ITEM.parent.as_posix()
        processed = pending.replace("pending", "processed", 1)
        cases = (
            (pending, processed),
            (pending + "/", processed),
            (INTAKE_ITEM.as_posix(), PROCESSED_INTAKE_ITEM.as_posix()),
            ("intake/pending/document-review-brief", processed),
            ("knowledge/intake/pending/other-folder", "knowledge/intake/processed/other-folder"),
        )
        for entry, expected in cases:
            with self.subTest(entry=entry):
                changes, moves, feature_path = self._po_intake_proposal([entry])
                error = self._rejected_preview(
                    "po-intake", changes, moves, read_revisions=_read_revisions(self.service, self.actor, "po-intake", changes, moves)
                )
                self.assertEqual(("intake_source_not_processed", 409), (error.code, error.status))
                self.assertEqual({"path": feature_path, "source": entry, "expected": expected}, error.details)
                self.assertIn(feature_path, error.message)
                self.assertIn(entry, error.message)
                self.assertIn(expected, error.message)
                self.assertTrue((self.root / pending).is_dir())
                self.assertFalse((self.root / processed).exists())
                self.assertFalse((self.root / feature_path).exists())

    def test_po_intake_accepts_a_processed_source_from_its_own_move(self) -> None:
        pending = INTAKE_ITEM.parent.as_posix()
        processed = pending.replace("pending", "processed", 1)
        (self.root / pending / "notes").mkdir()
        (self.root / pending / "notes" / "context.md").write_text("Reviewer context.\n", encoding="utf-8")
        for entry in (
            processed,
            processed + "/",
            PROCESSED_INTAKE_ITEM.as_posix(),
            processed + "/notes",
            processed + "/notes/context.md",
            processed + "/MANIFEST.md",
            "intake/processed/document-review-brief/brief.md",
        ):
            with self.subTest(entry=entry):
                preview = self._preview_po_intake([entry])
                self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]), preview["checks"])
        preview = self._preview_po_intake([])
        self.assertTrue(preview["applicable"])
        self.assertTrue((self.root / pending).is_dir())
        self.assertFalse((self.root / processed).exists())

    def test_po_intake_rejects_a_source_that_will_not_exist(self) -> None:
        pending = INTAKE_ITEM.parent.as_posix()
        processed = pending.replace("pending", "processed", 1)
        for entry in (
            processed + "/absent.md",
            processed + "/notes",
            "knowledge/intake/processed/other-folder",
            "knowledge/intake/quarantined/document-review-brief",
            "knowledge/wiki/features/F-099-absent.md",
            "brief.md",
        ):
            with self.subTest(entry=entry):
                changes, moves, feature_path = self._po_intake_proposal([entry])
                error = self._rejected_preview(
                    "po-intake", changes, moves, read_revisions=_read_revisions(self.service, self.actor, "po-intake", changes, moves)
                )
                self.assertEqual(("source_link_missing", 409), (error.code, error.status))
                self.assertEqual({"path": feature_path, "source": entry}, error.details)
                self.assertIn(entry, error.message)
                self.assertFalse((self.root / feature_path).exists())

        # A source that exists on disk, or is not a workspace path, stays accepted.
        for entry in ("knowledge/wiki/SCHEMA.md", "https://example.com/review-brief"):
            with self.subTest(entry=entry):
                self.assertTrue(self._preview_po_intake([entry])["applicable"])

    def test_source_link_rule_covers_every_page_that_writes_sources(self) -> None:
        pending = INTAKE_ITEM.parent.as_posix()
        processed = pending.replace("pending", "processed", 1)
        move = [{"source": pending, "destination": processed, "source_files": {"brief.md": "digest"}, "source_directories": []}]
        feature_path = "knowledge/wiki/features/F-002-document-review.md"
        feature = _unquote_yaml_date_fields(
            _journey_feature_page(
                "F-002", "Document review", "specified", "po", [PROCESSED_INTAKE_ITEM.as_posix()], ["| 1 | Which details? | po | open |"]
            )
        )
        persona = _unquote_yaml_date_fields(_journey_persona_page())
        persona_path = "knowledge/wiki/personas/P-001-reviewer.md"
        rule = _journey_business_rule_page()
        rule_path = "knowledge/wiki/business-rules/BR-001-review-record.md"

        def with_sources(page: str, field_name: str, value: Any) -> str:
            frontmatter, _body = _parse_markdown(page)
            frontmatter[field_name] = value
            return self.service._replace_frontmatter(page, frontmatter)

        def rejected(path: str, page: str, before: str | None, code: str, moves: list | None = None) -> None:
            with self.assertRaises(BoardError) as error:
                self.service._validate_source_links({path: page}, {path: before}, moves or [])
            self.assertEqual(code, error.exception.code)

        # Any skill that writes a feature page: a new pending source is rejected, an unchanged one is not.
        # The processed source already on the page predates this proposal, so it is not re-checked.
        pending_page = with_sources(feature, "sources", [PROCESSED_INTAKE_ITEM.as_posix(), INTAKE_ITEM.as_posix()])
        rejected(feature_path, pending_page, feature, "intake_source_not_processed")
        self.service._validate_source_links({feature_path: pending_page}, {feature_path: pending_page}, [])
        stale_page = with_sources(feature, "sources", ["knowledge/intake/processed/gone"])
        self.service._validate_source_links({feature_path: stale_page}, {feature_path: stale_page}, [])
        rejected(feature_path, stale_page, feature, "source_link_missing")
        moved_page = with_sources(feature, "sources", [PROCESSED_INTAKE_ITEM.as_posix(), processed + "/MANIFEST.md"])
        self.service._validate_source_links({feature_path: moved_page, processed + "/MANIFEST.md": "# Processed intake"}, {feature_path: feature}, move)
        rejected(feature_path, moved_page, feature, "source_link_missing", [])

        # A persona or business rule is checked only when the entry is a workspace path.
        for page_path, page, field_name, entry_value in (
            (persona_path, persona, "sources", [INTAKE_ITEM.as_posix()]),
            (rule_path, rule, "source", INTAKE_ITEM.as_posix()),
        ):
            with self.subTest(page=page_path):
                rejected(page_path, with_sources(page, field_name, entry_value), None, "intake_source_not_processed")
        self.service._validate_source_links({persona_path: with_sources(persona, "sources", ["Interview with the review team"])}, {}, [])
        self.service._validate_source_links({rule_path: with_sources(rule, "source", "Board review, March")}, {}, [])
        self.service._validate_source_links({persona_path: with_sources(persona, "sources", [PROCESSED_INTAKE_ITEM.as_posix()])}, {}, move)
        rejected(persona_path, with_sources(persona, "sources", [PROCESSED_INTAKE_ITEM.as_posix()]), None, "source_link_missing")

    def test_design_intake_cannot_add_a_pending_source(self) -> None:
        feature_path = FEATURE_PATH.as_posix()
        specified = _set_feature_stage(self._write_feature_page(), "specified", "po", self.service)
        (self.root / FEATURE_PATH).write_bytes(specified.encode("utf-8"))
        _write_index(self.root, "specified", "po")
        design_source = "knowledge/intake/pending/design-notes"
        (self.root / design_source).mkdir(parents=True)
        (self.root / design_source / "notes.md").write_text("Make the saved outcome easy to find.\n", encoding="utf-8")
        frontmatter, _body = _parse_markdown(specified)
        frontmatter["sources"] = [*frontmatter["sources"], design_source]
        proposed = self.service._replace_frontmatter(specified, frontmatter)
        changes = [
            {"path": feature_path, "content": proposed},
            {"path": "knowledge/wiki/design/F-001-document-review.md", "content": _design_page()},
        ]
        moves = [{"source": design_source, "destination": design_source.replace("pending", "processed", 1)}]
        error = self._rejected_preview(
            "design-intake", changes, moves, read_revisions=_read_revisions(self.service, self.actor, "design-intake", changes, moves)
        )
        self.assertEqual("design_intake_frontmatter_scope", error.code)
        self.assertTrue((self.root / design_source).is_dir())


class BoardServiceConnectedJourneyTests(unittest.TestCase):
    """Exercise accepted wiki writes through preview, confirmation, and apply."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "generated-project")
        initial_install = plan_install(self.root, name="Document review", platforms=["backend"])
        self.assertEqual("workflow", initial_install["mode"])
        self.assertEqual([], initial_install["conflicts"])
        self.assertEqual("applied", apply_install(self.root, initial_install)["status"])

        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["generated_by"] = {"tool": "fixture"}
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        install = plan_install(self.root, name="Document review", platforms=["backend"])
        self.assertEqual("generated", install["mode"])
        self.assertEqual([], install["conflicts"])
        self.assertEqual("applied", apply_install(self.root, install)["status"])

        # A raw feature is the one legitimate source for po-specify; intake
        # separately creates the specified document-review feature below.
        raw_path = self.root / "knowledge/wiki/features/F-002-review-follow-up.md"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_page = _unquote_yaml_date_fields(_journey_feature_page("F-002", "Review follow-up", "raw", "po", [], []))
        raw_path.write_bytes(raw_page.encode("utf-8"))
        _write_index_rows(self.root, [("F-002", "Review follow-up", "raw", "po")])

        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Workflow agent", "agent", True)["token"])
        self.human = self.service.authenticate(self.service.create_participant("Workflow owner", "human", True)["token"])

    def test_generated_workspace_accepts_complete_confirmed_core_workflow(self) -> None:
        # Cover the separate raw-specification path with a real confirmation.
        raw_path = "knowledge/wiki/features/F-002-review-follow-up.md"
        raw_text = self.service._read_text(self.root / raw_path)
        specified = _set_feature_stage(raw_text, "specified", "po", self.service)
        self._submit_skill("po-specify", [{"path": raw_path, "content": specified}])

        pending_folder = INTAKE_ITEM.as_posix().rsplit("/", 1)[0]
        processed_folder = pending_folder.replace("pending", "processed", 1)
        feature_path = "knowledge/wiki/features/F-001-document-review.md"
        persona_path = "knowledge/wiki/personas/P-001-reviewer.md"
        rule_path = "knowledge/wiki/business-rules/BR-001-review-record.md"
        intake_manifest_path = processed_folder + "/MANIFEST.md"
        intake_manifest = (
            "# Processed intake\n\n"
            f"- {feature_path} (F-001)\n"
            f"- {persona_path} (P-001)\n"
            f"- {rule_path} (BR-001)\n"
        )
        feature = _journey_feature_page(
            "F-001",
            "Document review",
            "raw",
            "po",
            [processed_folder + "/brief.md"],
            ["| 1 | Which details should the summary emphasize? | po | open |"],
        )
        feature = _unquote_yaml_date_fields(feature)
        self._submit_skill(
            "po-intake",
            [
                {"path": feature_path, "content": feature},
                {"path": persona_path, "content": _unquote_yaml_date_fields(_journey_persona_page())},
                {"path": rule_path, "content": _journey_business_rule_page()},
                {"path": intake_manifest_path, "content": intake_manifest},
            ],
            [{"source": pending_folder, "destination": processed_folder}],
        )

        # Record one designer-owned question through ask and resolve the PO
        # question with an answer grounded in a changed acceptance criterion.
        current = self.service._read_text(self.root / feature_path)
        asked = current.replace(
            "| 1 | Which details should the summary emphasize? | po | open |",
            "| 1 | Which details should the summary emphasize? | po | open |\n"
            "| 2 | Where should next steps appear? | designer | open |",
        )
        self._submit_skill("ask", [{"path": feature_path, "content": asked}])

        current = self.service._read_text(self.root / feature_path)
        po_answer = "The summary lists the key points and requested follow-up."
        clarified = current.replace(
            "| 1 | Which details should the summary emphasize? | po | open |",
            f"| 1 | Which details should the summary emphasize? | po | resolved: {po_answer} |",
        )
        clarified = _replace_body_section(
            self.service,
            clarified,
            "Acceptance criteria",
            "- [ ] A reviewer can record the outcome and requested follow-up.\n"
            f"- [ ] {po_answer}",
        )
        self._submit_skill("po-clarify", [{"path": feature_path, "content": clarified}])

        # po-intake created F-001 as raw; po-specify completes it and moves it
        # to specified, which design intake and the PO handoff require.
        current = self.service._read_text(self.root / feature_path)
        self.assertEqual("raw", _parse_markdown(current)[0]["status"])
        self._submit_skill("po-specify", [{"path": feature_path, "content": _set_feature_stage(current, "specified", "po", self.service)}])
        self.assertEqual("specified", self.service.query(self.agent, "show", "F-001")["facts"]["feature"]["status"])

        # Process a design note in a folder with an empty nested directory; the
        # journal must preserve both file and directory membership at apply.
        design_source = "knowledge/intake/pending/design-notes"
        design_destination = "knowledge/intake/processed/design-notes"
        source_dir = self.root / design_source / "references" / "unused"
        source_dir.mkdir(parents=True, exist_ok=True)
        (self.root / design_source / "notes.md").write_bytes(
            b"The review layout should make the saved outcome easy to find.\n"
        )
        design_path = "knowledge/wiki/design/F-001-document-review.md"
        current = self.service._read_text(self.root / feature_path)
        design_intake_feature = current.replace(
            "| 2 | Where should next steps appear? | designer | open |",
            "| 2 | Where should next steps appear? | designer | open |\n"
            "| 3 | How should the recorded outcome be shown? | designer | open |",
        )
        design_intake_feature = _replace_body_section(
            self.service,
            design_intake_feature,
            "Design",
            f"[Document review design](../design/F-001-document-review.md)",
        )
        self._submit_skill(
            "design-intake",
            [
                {"path": feature_path, "content": design_intake_feature},
                {"path": design_path, "content": _unquote_yaml_date_fields(_journey_design_page())},
            ],
            [{"source": design_source, "destination": design_destination}],
        )

        # Resolve the designer-owned questions and reflect both answers in the
        # linked design page before the design handoff.
        current = self.service._read_text(self.root / feature_path)
        design_answers = current.replace(
            "| 2 | Where should next steps appear? | designer | open |",
            "| 2 | Where should next steps appear? | designer | resolved: Present next steps below the recorded outcome. |",
        ).replace(
            "| 3 | How should the recorded outcome be shown? | designer | open |",
            "| 3 | How should the recorded outcome be shown? | designer | resolved: Keep the saved outcome beside the summary. |",
        )
        current_design = self.service._read_text(self.root / design_path)
        updated_design = _replace_body_section(
            self.service,
            current_design,
            "Key design decisions",
            "Present next steps below the recorded outcome. Keep the saved outcome beside the summary.",
        )
        self._submit_skill(
            "design-clarify",
            [
                {"path": feature_path, "content": design_answers},
                {"path": design_path, "content": updated_design},
            ],
        )

        # Complete all registered lifecycle routes for the primary feature.
        current = self.service._read_text(self.root / feature_path)
        po_handoff = _set_feature_stage(current, "ready-for-design", "designer", self.service)
        self._submit_skill("po-handoff", [{"path": feature_path, "content": po_handoff}])
        self._submit_transition("design-start")

        requirement_path = "knowledge/wiki/platform-requirements/F-001-backend.md"
        current = self.service._read_text(self.root / feature_path)
        design_handoff = _set_feature_stage(current, "ready-for-dev", "dev", self.service)
        self._submit_skill(
            "design-handoff",
            [
                {"path": feature_path, "content": design_handoff},
                {"path": requirement_path, "content": _journey_requirement_page("pending")},
            ],
        )
        self._submit_transition("dev-start")

        current = self.service._read_text(self.root / feature_path)
        dev_done = _set_feature_stage(current, "done", "none", self.service)
        dev_done = _replace_body_section(
            self.service,
            dev_done,
            "Delivery evidence",
            "| Platform | Implementation | Tests | Release |\n"
            "|---|---|---|---|\n"
            "| backend | Synthetic review record `tests/fixtures/review.md` | Acceptance check `document-review` passed | Synthetic release label `review-v1` |",
        )
        dev_done = _replace_body_section(self.service, dev_done, "Post-ship notes", "No deviations were recorded in this fixture.")
        self._submit_skill(
            "dev-done",
            [
                {"path": feature_path, "content": dev_done},
                {"path": requirement_path, "content": _set_requirement_status(self.service._read_text(self.root / requirement_path), "done")},
            ],
        )

        # Reopen dev route must archive the prior evidence and invalidate only
        # the linked platform requirement that changes status.
        current = self.service._read_text(self.root / feature_path)
        prior_row = "| backend | Synthetic review record `tests/fixtures/review.md` | Acceptance check `document-review` passed | Synthetic release label `review-v1` |"
        reopened = _set_feature_stage(current, "in-dev", "dev", self.service)
        reopened = _replace_body_section(
            self.service,
            reopened,
            "Delivery evidence",
            "| Platform | Implementation | Tests | Release |\n|---|---|---|---|",
        )
        reopened = _replace_body_section(
            self.service,
            reopened,
            "Reopen history",
            "### 2026-09-22 - reopen-dev\n"
            "- Reason: A confirmed reviewer needs a revised outcome summary.\n"
            "- Impact review: Recheck implementation, tests, release evidence, and the linked backend requirement.\n"
            "- Affected platforms: backend\n"
            f"- Affected artifacts: {feature_path} and {requirement_path}\n"
            f"- Prior completion/release evidence: {prior_row}\n"
            f"- Requirement/API invalidations: {requirement_path} done -> in-progress",
        )
        reopened_fm, _body = _parse_markdown(reopened)
        reopened_fm["revalidation"] = ["implementation", "tests", "release"]
        reopened = self.service._replace_frontmatter(reopened, reopened_fm)
        invalidated_requirement = _set_requirement_status(self.service._read_text(self.root / requirement_path), "in-progress")
        self._submit_skill(
            "feature-reopen",
            [
                {"path": feature_path, "content": reopened},
                {"path": requirement_path, "content": invalidated_requirement},
            ],
        )

        final = self.service.query(self.agent, "show", "F-001")
        self.assertEqual("in-dev", final["facts"]["feature"]["status"])
        self.assertEqual("dev", final["facts"]["feature"]["owner"])
        self.assertEqual(["implementation", "tests", "release"], final["facts"]["feature"]["frontmatter"]["revalidation"])

        # Complete again, then exercise the two remaining registered reopen
        # routes from done. Each route is followed through its required lifecycle
        # gates so the service accepts all nine action definitions end to end.
        self._complete_to_done("in-dev")
        self._submit_reopen("reopen-spec")
        self._complete_to_done("specified")
        self._submit_reopen("reopen-design")
        self._complete_to_done("in-design")

        final = self.service.query(self.agent, "show", "F-001")
        self.assertEqual("done", final["facts"]["feature"]["status"])
        self.assertEqual("none", final["facts"]["feature"]["owner"])
        self.assertEqual([], final["facts"]["feature"]["frontmatter"]["revalidation"])
        self.assertEqual("generated", self.service.discover(self.agent)["board"]["mode"])

    def _submit_skill(self, skill: str, changes: list[dict[str, str]], moves: list[dict[str, str]] | None = None) -> dict:
        preview = self.service.preview_skill(
            self.agent,
            skill,
            changes,
            moves,
            _read_revisions(self.service, self.agent, skill, changes, moves),
        )
        self.assertEqual("ready", preview["classification"], f"{skill}: {preview['checks']}")
        self.assertTrue(preview["applicable"], f"{skill}: {preview['blockers']}")
        receipt = self.service.apply(self.agent, preview["preview_id"], str(uuid4()))
        self.assertEqual("applied", receipt["state"], f"{skill}: {receipt}")
        return receipt

    def _submit_transition(self, action: str) -> dict:
        preview = self.service.preview_transition(
            self.human,
            "F-001",
            action,
            {"semantic_review_acknowledged": True},
        )
        self.assertEqual("ready", preview["classification"], f"{action}: {preview['checks']}")
        self.assertTrue(preview["applicable"], f"{action}: {preview['blockers']}")
        receipt = self.service.apply(self.human, preview["preview_id"], str(uuid4()))
        self.assertEqual("applied", receipt["state"], f"{action}: {receipt}")
        return receipt

    def _complete_to_done(self, starting_status: str) -> None:
        feature_path = "knowledge/wiki/features/F-001-document-review.md"
        requirement_path = "knowledge/wiki/platform-requirements/F-001-backend.md"
        if starting_status == "specified":
            current = self.service._read_text(self.root / feature_path)
            frontmatter, _body = _parse_markdown(current)
            self._submit_skill(
                "po-handoff",
                [{
                    "path": feature_path,
                    "content": _set_feature_stage(
                        current,
                        "ready-for-design",
                        "designer",
                        self.service,
                    ) if not frontmatter.get("revalidation") else _set_stage_and_revalidation(
                        self.service,
                        current,
                        "ready-for-design",
                        "designer",
                        [item for item in frontmatter["revalidation"] if item != "specification"],
                    ),
                }],
            )
            self._submit_transition("design-start")
            starting_status = "in-design"
        if starting_status == "in-design":
            current = self.service._read_text(self.root / feature_path)
            frontmatter, _body = _parse_markdown(current)
            remaining = [item for item in frontmatter.get("revalidation", []) if item != "design"]
            handoff_feature = _set_stage_and_revalidation(
                self.service,
                current,
                "ready-for-dev",
                "dev",
                remaining,
            )
            requirement = self.service._read_text(self.root / requirement_path)
            self._submit_skill(
                "design-handoff",
                [
                    {"path": feature_path, "content": handoff_feature},
                    {"path": requirement_path, "content": requirement},
                ],
            )
            self._submit_transition("dev-start")
        current = self.service._read_text(self.root / feature_path)
        completed = _set_stage_and_revalidation(
            self.service,
            current,
            "done",
            "none",
            [],
        )
        evidence = (
            "| Platform | Implementation | Tests | Release |\n"
            "|---|---|---|---|\n"
            "| backend | Synthetic review record `tests/fixtures/review.md` | Acceptance check `document-review` passed | Synthetic release label `review-v1` |"
        )
        completed = _replace_body_section(self.service, completed, "Delivery evidence", evidence)
        completed = _replace_body_section(
            self.service,
            completed,
            "Post-ship notes",
            "No deviations were recorded in this fixture.",
        )
        requirement = _set_requirement_status(
            self.service._read_text(self.root / requirement_path),
            "done",
        )
        self._submit_skill(
            "dev-done",
            [
                {"path": feature_path, "content": completed},
                {"path": requirement_path, "content": requirement},
            ],
        )

    def _submit_reopen(self, action: str) -> None:
        feature_path = "knowledge/wiki/features/F-001-document-review.md"
        requirement_path = "knowledge/wiki/platform-requirements/F-001-backend.md"
        target = {
            "reopen-spec": ("specified", "po", ["specification", "design", "implementation", "tests", "release"]),
            "reopen-design": ("in-design", "designer", ["design", "implementation", "tests", "release"]),
        }[action]
        current = self.service._read_text(self.root / feature_path)
        reopened = _set_stage_and_revalidation(
            self.service,
            current,
            target[0],
            target[1],
            target[2],
        )
        prior_row = (
            "| backend | Synthetic review record `tests/fixtures/review.md` | "
            "Acceptance check `document-review` passed | Synthetic release label `review-v1` |"
        )
        reopened = _replace_body_section(
            self.service,
            reopened,
            "Delivery evidence",
            "| Platform | Implementation | Tests | Release |\n|---|---|---|---|",
        )
        reopened = _append_body_section(
            self.service,
            reopened,
            "Reopen history",
            "\n".join(
                [
                    f"### {CHECK_DATE.isoformat()} - {action}",
                    "- Reason: A confirmed reviewer needs a revised outcome summary.",
                    "- Impact review: Recheck implementation, tests, release evidence, and the linked backend requirement.",
                    "- Affected platforms: backend",
                    f"- Affected artifacts: {feature_path} and {requirement_path}",
                    f"- Prior completion/release evidence: {prior_row}",
                    f"- Requirement/API invalidations: {requirement_path} done -> in-progress",
                ]
            ),
        )
        requirement = _set_requirement_status(
            self.service._read_text(self.root / requirement_path),
            "in-progress",
        )
        self._submit_skill(
            "feature-reopen",
            [
                {"path": feature_path, "content": reopened},
                {"path": requirement_path, "content": requirement},
            ],
        )


class BoardServiceReopenRecordTests(unittest.TestCase):
    """The archived evidence of a reopen record may follow its label in the layouts an agent writes."""

    FEATURE = "knowledge/wiki/features/F-001-document-review.md"
    REQUIREMENT = "knowledge/wiki/platform-requirements/F-001-backend.md"
    DESIGN = "knowledge/wiki/design/F-001-document-review.md"
    PRIOR_ROW = "| backend | Synthetic review record `tests/fixtures/review.md` | Acceptance check `document-review` passed | Synthetic release label `review-v1` |"
    TABLE = ["| Platform | Implementation | Tests | Release |", "|---|---|---|---|", PRIOR_ROW]

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "generated-project")
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Document review", platforms=["backend"]))["status"])
        (self.root / INTAKE_ITEM).parent.rename(self.root / "knowledge/intake/processed/document-review-brief")
        for relative, content in (
            (self.FEATURE, _journey_feature_page("F-001", "Document review", "in-dev", "dev", ["knowledge/intake/processed/document-review-brief"], ["| 1 | Which points should a review summary highlight? | po | resolved: The key points. |"])),
            (self.REQUIREMENT, _journey_requirement_page("in-progress")),
            (self.DESIGN, _journey_design_page()),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        feature = (self.root / self.FEATURE).read_text(encoding="utf-8")
        (self.root / self.FEATURE).write_bytes(feature.replace("No design has been recorded yet.", "The design is recorded in [F-001 design](../design/F-001-document-review.md).").encode("utf-8"))
        _write_index_rows(self.root, [("F-001", "Document review", "in-dev", "dev")])
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Workflow agent", "agent", True)["token"])
        self.in_dev = {path: (self.root / path).read_bytes() for path in (self.FEATURE, self.REQUIREMENT)}
        self.complete()

    def submit(self, skill: str, changes: list[dict[str, str]]) -> dict:
        preview = self.service.preview_skill(self.agent, skill, changes, None, _read_revisions(self.service, self.agent, skill, changes))
        return preview

    def complete(self, table: list[str] | None = None) -> None:
        current = self.service._read_text(self.root / self.FEATURE)
        done = _set_feature_stage(current, "done", "none", self.service)
        done = _replace_body_section(self.service, done, "Delivery evidence", "\n".join(table or self.TABLE))
        done = _replace_body_section(self.service, done, "Post-ship notes", "No deviations were recorded in this fixture.")
        requirement = _set_requirement_status(self.service._read_text(self.root / self.REQUIREMENT), "done")
        preview = self.submit("dev-done", [{"path": self.FEATURE, "content": done}, {"path": self.REQUIREMENT, "content": requirement}])
        self.assertTrue(preview["applicable"], preview["checks"])
        self.assertEqual("applied", self.service.apply(self.agent, preview["preview_id"], str(uuid4()))["state"])

    def record(self, archive: list[str], trailer: list[str] | None = None) -> str:
        lines = [
            f"### {CHECK_DATE.isoformat()} - reopen-dev",
            "- Reason: A confirmed reviewer needs a revised outcome summary.",
            "- Impact review: Recheck implementation, tests, release evidence, and the linked backend requirement.",
            "- Affected platforms: backend",
            f"- Affected artifacts: {self.FEATURE} and {self.REQUIREMENT}",
            *archive,
            f"- Requirement/API invalidations: {self.REQUIREMENT} done -> in-progress",
            *(trailer or []),
        ]
        return "\n".join(lines)

    def reopen(self, record: str) -> dict:
        current = self.service._read_text(self.root / self.FEATURE)
        reopened = _set_stage_and_revalidation(self.service, current, "in-dev", "dev", ["implementation", "tests", "release"])
        reopened = _replace_body_section(self.service, reopened, "Delivery evidence", "| Platform | Implementation | Tests | Release |\n|---|---|---|---|")
        reopened = _append_body_section(self.service, reopened, "Reopen history", record)
        requirement = _set_requirement_status(self.service._read_text(self.root / self.REQUIREMENT), "in-progress")
        return self.submit("feature-reopen", [{"path": self.FEATURE, "content": reopened}, {"path": self.REQUIREMENT, "content": requirement}])

    def test_the_archived_row_is_accepted_on_the_label_line_or_below_it_in_a_table_or_a_list(self) -> None:
        label = "- Prior completion/release evidence:"
        compact_row = "|backend|Synthetic review record `tests/fixtures/review.md`|Acceptance check `document-review` passed|Synthetic release label `review-v1`|"
        layouts = {
            "same line": [f"{label} {self.PRIOR_ROW}"],
            "sentence then table, no indent": [f"{label} Archived unchanged in the table below.", "", *self.TABLE, ""],
            "label alone, indented table": [label, *(f"  {line}" for line in self.TABLE)],
            "sentence then indented table": [f"{label} Archived as it was.", "", *(f"  {line}" for line in self.TABLE)],
            "list item": [label, f"  - {self.PRIOR_ROW}"],
            "row without spaces around pipes": [label, compact_row],
        }
        for name, archive in layouts.items():
            with self.subTest(layout=name):
                preview = self.reopen(self.record(archive))
                self.assertEqual("ready", preview["classification"], preview["checks"])
                self.assertTrue(preview["applicable"], preview["blockers"])

    def evidence_layouts(self) -> dict[str, list[str]]:
        cells = ["Synthetic review record `tests/fixtures/review.md`", "Acceptance check `document-review` passed", "Synthetic release label `review-v1`"]
        separator = "|---|---|---|---|"
        return {
            "canonical": self.TABLE,
            "platform capitalised": ["| Platform | Implementation | Tests | Release |", separator, "| Backend | " + " | ".join(cells) + " |"],
            "columns reordered": ["| Implementation | Platform | Tests | Release |", separator, f"| {cells[0]} | backend | {cells[1]} | {cells[2]} |"],
            "release first": ["| Release | Tests | Implementation | Platform |", separator, f"| {cells[2]} | {cells[1]} | {cells[0]} | backend |"],
            "header case and emphasis": ["| **PLATFORM** | implementation | _Tests_ | Release |", separator, "| backend | " + " | ".join(cells) + " |"],
            "release cell says Release": ["| Platform | Implementation | Tests | Release |", separator, f"| backend | {cells[0]} | {cells[1]} | Release |"],
            "compact pipes": ["|Platform|Implementation|Tests|Release|", separator, "|backend|" + "|".join(cells) + "|"],
        }

    def restore_in_dev(self) -> None:
        for relative, content in self.in_dev.items():
            (self.root / relative).write_bytes(content)
        _write_index_rows(self.root, [("F-001", "Document review", "in-dev", "dev")])

    def test_every_evidence_table_dev_done_accepts_can_be_archived_by_a_reopen(self) -> None:
        for name, table in self.evidence_layouts().items():
            with self.subTest(layout=name):
                self.restore_in_dev()
                self.complete(table)
                archive = ["- Prior completion/release evidence:", *(f"  {line}" for line in table)]
                preview = self.reopen(self.record(archive))
                self.assertEqual("ready", preview["classification"], preview["checks"])
                self.assertTrue(preview["applicable"], preview["blockers"])

    def test_a_reopen_archives_each_row_in_the_column_order_of_its_table(self) -> None:
        table = self.evidence_layouts()["columns reordered"]
        self.restore_in_dev()
        self.complete(table)
        canonical_order = self.record(["- Prior completion/release evidence:", *(f"  {line}" for line in self.TABLE)])
        error = self.reopen_error(canonical_order)
        self.assertEqual(("delivery_evidence_not_archived", 409), (error.code, error.status))
        self.assertIn("Missing row: | Synthetic review record", error.message)
        self.assertEqual(table[2], error.details["missing_row"])

    def test_a_row_kept_active_must_equal_the_prior_row_whatever_its_column_order(self) -> None:
        table = self.evidence_layouts()["columns reordered"]
        self.restore_in_dev()
        self.complete(table)
        archive = ["- Prior completion/release evidence:", *(f"  {line}" for line in table)]
        current = self.service._read_text(self.root / self.FEATURE)
        reopened = _set_stage_and_revalidation(self.service, current, "in-dev", "dev", ["implementation", "tests", "release"])
        reopened = _replace_body_section(self.service, reopened, "Delivery evidence", "\n".join(table))
        reopened = _append_body_section(self.service, reopened, "Reopen history", self.record(archive))
        requirement = _set_requirement_status(self.service._read_text(self.root / self.REQUIREMENT), "in-progress")
        with self.assertRaises(BoardError) as error:
            self.submit("feature-reopen", [{"path": self.FEATURE, "content": reopened}, {"path": self.REQUIREMENT, "content": requirement}])
        self.assertEqual(("delivery_evidence_still_active", 409), (error.exception.code, error.exception.status))

    def test_a_row_outside_the_label_block_or_changed_is_rejected_with_the_expected_layout(self) -> None:
        label = "- Prior completion/release evidence:"
        rejected = {
            "table after the next label": self.reopen_error(self.record([f"{label} Archived below."], ["", *self.TABLE])),
            "table under a later heading": self.reopen_error(self.record([f"{label} Archived below."], ["", "#### Archived delivery evidence", *self.TABLE])),
            "row changed": self.reopen_error(self.record([f"{label} {self.PRIOR_ROW.replace('review-v1', 'review-v2')}"])),
        }
        for name, error in rejected.items():
            with self.subTest(case=name):
                self.assertEqual(("delivery_evidence_not_archived", 409), (error.code, error.status))
                self.assertIn("- Prior completion/release evidence:", error.message)
                self.assertIn("next `- Label:` line or heading", error.message)
                self.assertIn("Missing row: | backend | Synthetic review record", error.message)
                self.assertEqual("Prior completion/release evidence", error.details["label"])
                self.assertEqual(self.FEATURE, error.details["path"])
        empty = self.reopen_error(self.record(["- Prior completion/release evidence:"]))
        self.assertEqual("impact_review_required", empty.code)

    def test_reopen_rejections_name_the_exact_format_of_the_invalidation_line(self) -> None:
        archive = ["- Prior completion/release evidence:", *(f"  {line}" for line in self.TABLE)]
        arrow_line = f"- Requirement/API invalidations: {self.REQUIREMENT} done -> in-progress"
        good = self.record(archive)
        self.assertIn(arrow_line, good)

        sentence = self.reopen_error(good.replace(arrow_line, f"- Requirement/API invalidations: {self.REQUIREMENT} status changed from `done` to `in-progress`"))
        self.assertEqual(("reopen_invalidation_mismatch", 409), (sentence.code, sentence.status))
        self.assertIn(f"`{self.REQUIREMENT}: done -> in-progress`", sentence.message)
        self.assertEqual({"path": self.REQUIREMENT, "from": "done", "to": "in-progress"}, sentence.details)

        unnamed = self.reopen_error(good.replace(f"- Affected artifacts: {self.FEATURE} and {self.REQUIREMENT}", f"- Affected artifacts: {self.FEATURE} and the backend renderer"))
        self.assertEqual(("reopen_artifact_missing", 409), (unnamed.code, unnamed.status))
        self.assertIn(self.REQUIREMENT, unnamed.message)
        self.assertIn("Affected artifacts", unnamed.message)

        none = self.reopen_error(good.replace(arrow_line, "- Requirement/API invalidations: None"))
        self.assertEqual(("impact_review_required", 409), (none.code, none.status))
        self.assertIn("Requirement/API invalidations", none.message)
        self.assertIn("done -> in-progress", none.message)
        self.assertIn("No requirement or API page is invalidated.", none.message)
        self.assertEqual({"label": "Requirement/API invalidations"}, none.details)

    def reopen_error(self, record: str) -> BoardError:
        with self.assertRaises(BoardError) as error:
            self.reopen(record)
        return error.exception


def _read_revisions(
    service: BoardService,
    actor: object,
    skill: str,
    changes: list[dict[str, str]],
    moves: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    supplied = {item["path"]: item["content"] for item in changes}
    before = {
        relative: service._optional_text(service._safe_path(relative, allow_missing=True))
        for relative in supplied
    }
    normalized_moves = []
    for item in moves or []:
        source_path = service._safe_path(item["source"])
        normalized_moves.append(
            {
                "source": item["source"],
                "destination": item["destination"],
                "source_files": service._tree_snapshot(source_path),
            }
        )
    required = service._required_skill_revision_paths(skill, supplied, before, normalized_moves)
    digests: dict[str, str] = {}
    cursor = None
    while required:
        response = service.read_workspace(actor, sorted(required), cursor)
        digests.update({item["path"]: item["digest"] for item in response["files"]})
        cursor = response["next_cursor"]
        if cursor is None:
            break
    return digests


def _set_feature_stage(content: str, status: str, owner: str, service: BoardService | None = None) -> str:
    frontmatter, body = _parse_markdown(content)
    frontmatter["status"] = status
    frontmatter["owner"] = owner
    frontmatter["last-updated"] = CHECK_DATE.isoformat()
    if service is not None:
        return service._replace_frontmatter(content, frontmatter)
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"


def _design_page() -> str:
    return (
        "---\nfeature-id: F-001\ntitle: Document review\ndesigner: Reviewer\n"
        f"date: '{CHECK_DATE.isoformat()}'\nfigma: reviewed-document-flow\n---\n\n"
        "## Summary\nThe reviewer sees the document title and review status.\n\n"
        "## Key design decisions\nKeep the review outcome beside the source document.\n\n"
        "## States covered\nThe page shows pending and completed reviews.\n\n"
        "## Component references\nUse the existing document summary panel.\n\n"
        "## Open design questions\nThe reviewer can scan the summary before saving.\n"
    )


def _persona_page(name: str) -> str:
    return (
        "---\nid: P-001\n"
        f"name: {name}\nintroduced: '{CHECK_DATE.isoformat()}'\n"
        "sources:\n- knowledge/intake/processed/document-review-brief/brief.md\n"
        "---\n\n"
        "## Who they are\nA person assigned to review a document.\n\n"
        "## Goals\nRecord key points, an outcome, and follow-up.\n\n"
        "## Pain points\nImportant decisions can be lost in informal notes.\n\n"
        "## Features that serve this persona\n- F-002 records a review outcome.\n"
    )


def _journey_feature_page(
    feature_id: str,
    title: str,
    status: str,
    owner: str,
    sources: list[str],
    questions: list[str],
) -> str:
    frontmatter, body = _parse_markdown(_feature_page())
    frontmatter.update(
        {
            "id": feature_id,
            "title": title,
            "status": status,
            "owner": owner,
            "sources": sources,
            "revalidation": [],
        }
    )
    question_table = (
        "| # | Question | Owner | Status |\n"
        "|---|----------|-------|--------|\n"
        + "\n".join(questions)
    )
    body = _replace_body_section_text(body, "Open questions", question_table)
    body += (
        "\n## Design\nNo design has been recorded yet.\n"
        "\n## Related features\nNo related feature is required for this workflow.\n"
        "\n## Board review summary\nThe existing acceptance checks cover the scoped review workflow.\n"
        "\n## Delivery evidence\n"
        "| Platform | Implementation | Tests | Release |\n"
        "|---|---|---|---|\n"
        "\n## Reopen history\n"
        "\n## Post-ship notes\nThe fixture has no post-ship deviations.\n"
    )
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n{body}"


def _write_index_rows(root: Path, rows: list[tuple[str, str, str, str]]) -> None:
    index = root / "knowledge/wiki/index.md"
    content = (
        "# Feature Status Board\n\n"
        "| ID | Feature | Status | Owner | Board Review | Introduced |\n"
        "|----|---------|--------|-------|--------------|------------|\n"
    )
    for feature_id, title, status, owner in rows:
        content += f"| {feature_id} | {title} | {status} | {owner} | not-needed | {CHECK_DATE.isoformat()} |\n"
    index.write_text(content, encoding="utf-8")


def _replace_body_section(service: BoardService, content: str, heading: str, replacement: str) -> str:
    marker = re.compile(r"(?m)^(\ufeff?---\r?\n.*?\r?\n---\r?\n)", re.DOTALL)
    match = marker.match(content)
    if not match:
        raise ValueError("Expected a Markdown page with YAML frontmatter")
    return match.group(1) + _replace_body_section_text(content[match.end():], heading, replacement)


def _replace_body_section_text(body: str, heading: str, replacement: str) -> str:
    pattern = re.compile(rf"(?ms)(^## {re.escape(heading)}\s*\r?\n).*?(?=^## |\Z)")
    match = pattern.search(body)
    if not match:
        raise ValueError(f"Required section {heading!r} is missing")
    section = match.group(1) + replacement.rstrip() + "\n\n"
    return body[:match.start()] + section + body[match.end():]


def _append_body_section(service: BoardService, content: str, heading: str, addition: str) -> str:
    marker = re.compile(r"(?m)^(\ufeff?---\r?\n.*?\r?\n---\r?\n)", re.DOTALL)
    match = marker.match(content)
    if not match:
        raise ValueError("Expected a Markdown page with YAML frontmatter")
    body = content[match.end():]
    pattern = re.compile(rf"(?ms)(^## {re.escape(heading)}\s*\r?\n)(.*?)(?=^## |\Z)")
    section = pattern.search(body)
    if not section:
        raise ValueError(f"Required section {heading!r} is missing")
    old_value = section.group(2).rstrip()
    combined = "\n\n".join(value for value in (old_value, addition.strip()) if value)
    updated = body[:section.start()] + section.group(1) + combined + "\n\n" + body[section.end():]
    return match.group(1) + updated


def _set_stage_and_revalidation(
    service: BoardService,
    content: str,
    status: str,
    owner: str,
    domains: list[str],
) -> str:
    frontmatter, _body = _parse_markdown(content)
    frontmatter["status"] = status
    frontmatter["owner"] = owner
    frontmatter["last-updated"] = CHECK_DATE.isoformat()
    frontmatter["revalidation"] = domains
    return service._replace_frontmatter(content, frontmatter)


def _journey_persona_page() -> str:
    return (
        "---\nid: P-001\nname: Reviewer\n"
        f"introduced: '{CHECK_DATE.isoformat()}'\n"
        "sources:\n- knowledge/intake/processed/document-review-brief/brief.md\n"
        "---\n\n"
        "## Who they are\nA person assigned to review a document.\n\n"
        "## Goals\nRecord key points, an outcome, and follow-up.\n\n"
        "## Pain points\nImportant decisions can be lost in informal notes.\n\n"
        "## Features that serve this persona\n- F-001 records a review outcome.\n"
    )


def _journey_business_rule_page() -> str:
    return (
        "---\nid: BR-001\ntitle: Retain review outcome\n"
        f"introduced: '{CHECK_DATE.isoformat()}'\n"
        "source: knowledge/intake/processed/document-review-brief/brief.md\n"
        "---\n\n"
        "## Rule\nA recorded review keeps its outcome and requested follow-up together.\n\n"
        "## Rationale\nReviewers need to find the decision after the review is complete.\n\n"
        "## Affected features\n- F-001 Document review\n\n"
        "## Exceptions\nThe rule applies only to documents that enter the review workflow.\n"
    )


def _journey_design_page() -> str:
    return (
        "---\nfeature-id: F-001\ntitle: Document review\ndesigner: Reviewer\n"
        f"date: '{CHECK_DATE.isoformat()}'\nfigma: reviewed-document-flow\n---\n\n"
        "## Summary\nThe reviewer sees the document title and review status.\n\n"
        "## Key design decisions\nKeep the review outcome beside the source document.\n\n"
        "## States covered\nThe page shows pending and completed reviews.\n\n"
        "## Component references\nUse the existing document summary panel.\n\n"
        "## Open design questions\nThe reviewer can scan the summary before saving.\n"
    )


def _journey_requirement_page(status: str) -> str:
    return (
        "---\nfeature-id: F-001\nplatform: backend\n"
        f"status: {status}\n---\n\n"
        "## What to build\nStore a document review summary and recorded outcome.\n\n"
        "## Technical constraints\nUse the existing workspace storage and authenticated write path.\n\n"
        "## Design reference\nknowledge/wiki/design/F-001-document-review.md describes the review panel.\n\n"
        "## API contract reference\nNo separate API contract is needed for this backend-only feature.\n\n"
        "## Acceptance criteria\n- A saved summary and outcome can be read back.\n\n"
        "## Dependencies\nThe document review record is available to the assigned reviewer.\n"
    )


def _set_requirement_status(content: str, status: str) -> str:
    frontmatter, _body = _parse_markdown(content)
    frontmatter["status"] = status
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{_parse_markdown(content)[1]}"


def _unquote_yaml_date_fields(content: str) -> str:
    return re.sub(
        r"(?m)^(introduced|last-updated|date): '(\d{4}-\d{2}-\d{2})'$",
        r"\1: \2",
        content,
    )


if __name__ == "__main__":
    unittest.main()


class BoardServiceCloudSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "synced" / "board"
        self.root.mkdir(parents=True)
        self.assertEqual(
            "applied",
            apply_install(self.root, plan_install(self.root, name="Cloud board", platforms=["backend"]))["status"],
        )

    def test_cloud_ancestor_is_rejected_with_cloud_guidance(self) -> None:
        with fake_reparse(self.base / "synced", CLOUD_TAG):
            with self.assertRaises(BoardError) as raised:
                BoardService(self.root)

        self.assertEqual("cloud_sync_path", raised.exception.code)
        self.assertEqual(403, raised.exception.status)
        self.assertEqual(CLOUD_SYNC_MESSAGE, raised.exception.message)
        self.assertNotIn(str(self.base), raised.exception.message)

    def test_cloud_workspace_root_is_rejected_with_cloud_guidance(self) -> None:
        with fake_reparse(self.root, 0x9000701A):
            with self.assertRaises(BoardError) as raised:
                BoardService(self.root)

        self.assertEqual("cloud_sync_path", raised.exception.code)

    def test_non_cloud_reparse_keeps_the_generic_rejection(self) -> None:
        for tag in (JUNCTION_TAG, 0x80000021, None):
            with self.subTest(tag=tag), fake_reparse(self.base / "synced", tag):
                with self.assertRaises(BoardError) as raised:
                    BoardService(self.root)

                self.assertEqual("reparse_path", raised.exception.code)
                self.assertEqual(403, raised.exception.status)
                self.assertEqual("Symlinks and reparse points are not allowed in BoardService paths.", raised.exception.message)

    def test_cloud_state_directory_surfaces_cloud_guidance_when_state_opens(self) -> None:
        service = BoardService(self.root)
        self.addCleanup(service.close)
        with fake_reparse(self.root / ".prism", CLOUD_TAG):
            with self.assertRaises(BoardError) as started:
                service.start()
            with self.assertRaises(BoardError) as lazy:
                service.create_participant("Reader", "agent", writable=False)

        for raised in (started, lazy):
            self.assertEqual("cloud_sync_path", raised.exception.code)
            self.assertEqual(403, raised.exception.status)
            self.assertEqual(CLOUD_SYNC_MESSAGE, raised.exception.message)


def _legacy_validate_graph_inputs(service: BoardService) -> None:
    """The per-entry ancestor walk that ``validate_graph_inputs`` replaced; the oracle for equivalence."""

    from prism_cli.wiki_transitions import _capability_paths
    from prism_cli.workspace import COPIER_ANSWERS_FILE, PLATFORM_DIRS

    root = service.root
    roots = [
        root / "knowledge",
        root / "knowledge" / "wiki",
        root / "knowledge" / "intake" / "pending",
        root / "knowledge" / "intake" / "processed",
        root / "knowledge" / "intake" / "quarantined",
    ]
    files = [
        root / "prism.workspace.yml",
        root / COPIER_ANSWERS_FILE,
        *(root / directory for directory in PLATFORM_DIRS.values()),
        *(root / relative for relative in _capability_paths()),
    ]
    for path in files:
        BoardService._reject_reparse(path, include_leaf=True)
    for tree in roots:
        BoardService._reject_reparse(tree, include_leaf=True)
        if not tree.is_dir():
            continue
        pending = [tree]
        while pending:
            current = pending.pop()
            BoardService._reject_reparse(current, include_leaf=True)
            try:
                children = list(current.iterdir())
            except OSError as exc:
                raise BoardError("graph_path_unavailable", "Graph input tree cannot be traversed safely.", 409) from exc
            for child in children:
                BoardService._reject_reparse(child, include_leaf=True)
                if child.is_dir():
                    pending.append(child)


def _legacy_tree_children(path: Path) -> list[Path]:
    return sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix())


def _legacy_tree_digest(path: Path) -> str:
    from prism_cli.board_service import _revision, _sha256

    BoardService._reject_reparse(path, include_leaf=True)
    entries: list[tuple[str, str]] = []
    for child in _legacy_tree_children(path):
        BoardService._reject_reparse(child, include_leaf=True)
        if child.is_file():
            entries.append((child.relative_to(path).as_posix(), _sha256(child.read_bytes())))
        elif child.is_dir():
            entries.append((child.relative_to(path).as_posix() + "/", "directory"))
        else:
            raise BoardError("unsupported_path_type", "Intake trees may contain only regular files and directories.", 409)
    return _revision({name: digest for name, digest in entries})


def _legacy_tree_snapshot(path: Path) -> dict[str, str]:
    from prism_cli.board_service import _sha256

    BoardService._reject_reparse(path, include_leaf=True)
    result: dict[str, str] = {}
    for child in _legacy_tree_children(path):
        BoardService._reject_reparse(child, include_leaf=True)
        if child.is_file():
            result[child.relative_to(path).as_posix()] = _sha256(child.read_bytes())
        elif not child.is_dir():
            raise BoardError("unsupported_path_type", "Intake trees may contain only regular files and directories.", 409)
    return result


def _legacy_tree_directories(path: Path) -> list[str]:
    BoardService._reject_reparse(path, include_leaf=True)
    result: list[str] = []
    for child in _legacy_tree_children(path):
        BoardService._reject_reparse(child, include_leaf=True)
        if child.is_dir():
            result.append(child.relative_to(path).as_posix())
        elif not child.is_file():
            raise BoardError("unsupported_path_type", "Intake trees may contain only regular files and directories.", 409)
    return result


def _legacy_copy_tree_safely(source: Path, destination: Path) -> None:
    import os

    BoardService._reject_reparse(source, include_leaf=True)
    destination.mkdir(parents=True, exist_ok=True)
    pending = [(source, destination)]
    while pending:
        current_source, current_destination = pending.pop()
        BoardService._reject_reparse(current_source, include_leaf=True)
        try:
            with os.scandir(current_source) as entries:
                children = sorted(list(entries), key=lambda entry: entry.name)
        except OSError as exc:
            raise BoardError("candidate_copy_failed", "A candidate wiki/intake tree cannot be inspected safely.", 409) from exc
        for entry in children:
            source_child = Path(entry.path)
            target_child = current_destination / entry.name
            BoardService._reject_reparse(source_child, include_leaf=True)
            try:
                if entry.is_dir(follow_symlinks=False):
                    target_child.mkdir(parents=True, exist_ok=True)
                    pending.append((source_child, target_child))
                elif entry.is_file(follow_symlinks=False):
                    BoardService._reject_reparse(source_child, include_leaf=True)
                    target_child.parent.mkdir(parents=True, exist_ok=True)
                    target_child.write_bytes(source_child.read_bytes())
                else:
                    raise BoardError("candidate_copy_failed", "Candidate trees may contain only regular files and directories.", 409)
            except OSError as exc:
                raise BoardError("candidate_copy_failed", "A candidate wiki/intake tree cannot be copied safely.", 409) from exc


class _FakeReparseEntry:
    """A ``DirEntry`` that reports one chosen path as a reparse point from ``stat``."""

    def __init__(self, entry: Any, target: Path, tag: int | None) -> None:
        self._entry = entry
        self._target = target
        self._tag = tag

    def __getattr__(self, name: str) -> Any:
        return getattr(self._entry, name)

    def stat(self, *, follow_symlinks: bool = True) -> Any:
        info = self._entry.stat(follow_symlinks=follow_symlinks)
        if Path(self._entry.path) != self._target:
            return info
        fields = {"st_mode": info.st_mode, "st_size": info.st_size, "st_file_attributes": 0x400}
        if self._tag is not None:
            fields["st_reparse_tag"] = self._tag
        return SimpleNamespace(**fields)


class _FakeReparseListing:
    def __init__(self, listing: Any, target: Path, tag: int | None) -> None:
        self._listing = listing
        self._target = target
        self._tag = tag

    def __enter__(self) -> "_FakeReparseListing":
        self._listing.__enter__()
        return self

    def __exit__(self, *exc_info: Any) -> Any:
        return self._listing.__exit__(*exc_info)

    def __iter__(self) -> Any:
        return (_FakeReparseEntry(entry, self._target, self._tag) for entry in self._listing)


@contextmanager
def _fake_reparse_in_tree(target: Path, tag: int | None) -> Iterator[None]:
    """Report ``target`` as a reparse point with ``tag`` to ``Path.lstat`` and to directory listings."""

    real_scandir = os.scandir

    def scandir(path: Any = ".") -> _FakeReparseListing:
        return _FakeReparseListing(real_scandir(path), target, tag)

    with fake_reparse(target, tag), patch("prism_cli.board_service.os.scandir", scandir):
        yield


def _link_directory(link: Path, target: Path) -> bool:
    """Create a junction on Windows or a directory symlink elsewhere; False when the OS refuses."""

    try:
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False)
            return result.returncode == 0
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def _outcome(call: Callable[[], Any]) -> tuple[Any, ...]:
    try:
        value = call()
    except BoardError as error:
        return ("rejected", error.code, error.status, error.message)
    return ("accepted", value)


class BoardServiceTreeWalkEquivalenceTests(unittest.TestCase):
    """The single-walk checks reject exactly what the per-entry ancestor walk rejected."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.outside = self.base / "outside"
        self.outside.mkdir()
        (self.outside / "x.md").write_text("outside\n", encoding="utf-8")
        self.parent = self.base / "synced"
        self.root = create_core_workflow_fixture(self.parent / "board")
        self.service = BoardService(self.root)
        self.addCleanup(self.service.close)
        self.features = self.root / "knowledge" / "wiki" / "features"
        self.intake = self.root / INTAKE_ITEM.parent
        (self.intake / "nested" / "empty").mkdir(parents=True)
        (self.intake / "nested" / "notes.md").write_text("nested notes\n", encoding="utf-8")

    def assert_validate_matches(self, expected_code: str | None) -> None:
        legacy = _outcome(lambda: _legacy_validate_graph_inputs(self.service))
        current = _outcome(self.service.validate_graph_inputs)
        self.assertEqual(legacy, current)
        if expected_code is None:
            self.assertEqual("accepted", current[0])
        else:
            self.assertEqual(("rejected", expected_code), current[:2])

    def assert_tree_helpers_match(self, tree: Path, expected_code: str | None) -> None:
        pairs = (
            (lambda: _legacy_tree_digest(tree), lambda: self.service._tree_digest(tree)),
            (lambda: _legacy_tree_snapshot(tree), lambda: self.service._tree_snapshot(tree)),
            (lambda: _legacy_tree_directories(tree), lambda: self.service._tree_directories(tree)),
        )
        for legacy_call, current_call in pairs:
            legacy = _outcome(legacy_call)
            current = _outcome(current_call)
            self.assertEqual(legacy, current)
            if expected_code is None:
                self.assertEqual("accepted", current[0])
            else:
                self.assertEqual(("rejected", expected_code), current[:2])

    def assert_copy_matches(self, tree: Path, expected_code: str | None) -> None:
        legacy_destination = self.base / f"legacy-copy-{uuid4().hex[:8]}"
        current_destination = self.base / f"current-copy-{uuid4().hex[:8]}"
        legacy = _outcome(lambda: _legacy_copy_tree_safely(tree, legacy_destination))
        current = _outcome(lambda: self.service._copy_tree_safely(tree, current_destination))
        self.assertEqual(legacy, current)
        if expected_code is None:
            self.assertEqual("accepted", current[0])
            self.assertEqual(_legacy_tree_snapshot(legacy_destination), _legacy_tree_snapshot(current_destination))
            self.assertEqual(_legacy_tree_directories(legacy_destination), _legacy_tree_directories(current_destination))
            self.assertEqual(_legacy_tree_snapshot(tree), _legacy_tree_snapshot(current_destination))
        else:
            self.assertEqual(("rejected", expected_code), current[:2])

    def test_clean_tree_is_accepted_the_same_way(self) -> None:
        self.assert_validate_matches(None)
        self.assert_tree_helpers_match(self.intake, None)
        self.assert_copy_matches(self.intake, None)
        self.assert_copy_matches(self.root / "knowledge" / "wiki", None)

    def test_tree_digest_matches_for_a_populated_tree(self) -> None:
        self.assertEqual(_legacy_tree_digest(self.intake), self.service._tree_digest(self.intake))
        self.assertEqual(_legacy_tree_snapshot(self.intake), self.service._tree_snapshot(self.intake))
        self.assertEqual(["nested", "nested/empty"], self.service._tree_directories(self.intake))
        self.assertEqual({"brief.md", "nested/notes.md"}, set(self.service._tree_snapshot(self.intake)))

    def test_missing_trees_match(self) -> None:
        missing = self.root / "knowledge" / "intake" / "pending" / "absent"
        self.assert_tree_helpers_match(missing, None)

    def test_junction_inside_the_wiki_is_rejected_the_same_way(self) -> None:
        if not _link_directory(self.features / "linked-dir", self.outside):
            self.skipTest("Directory links are not available here.")
        self.assert_validate_matches("reparse_path")
        self.assert_tree_helpers_match(self.root / "knowledge" / "wiki", "reparse_path")
        self.assert_copy_matches(self.root / "knowledge" / "wiki", "reparse_path")

    def test_junction_inside_an_intake_queue_is_rejected_the_same_way(self) -> None:
        if not _link_directory(self.intake / "linked-dir", self.outside):
            self.skipTest("Directory links are not available here.")
        self.assert_validate_matches("reparse_path")
        self.assert_tree_helpers_match(self.intake, "reparse_path")
        self.assert_copy_matches(self.intake, "reparse_path")

    def test_junction_replacing_a_capability_directory_is_rejected_the_same_way(self) -> None:
        shutil.rmtree(self.root / ".claude")
        if not _link_directory(self.root / ".claude", self.outside):
            self.skipTest("Directory links are not available here.")
        self.assert_validate_matches("reparse_path")

    def test_file_symlink_is_rejected_the_same_way(self) -> None:
        link = self.features / "linked.md"
        try:
            os.symlink(self.outside / "x.md", link)
        except (OSError, NotImplementedError):
            self.skipTest("File symlinks are not available here.")
        self.assert_validate_matches("reparse_path")
        self.assert_tree_helpers_match(self.root / "knowledge" / "wiki", "reparse_path")

    def test_cloud_placeholder_inside_the_tree_is_rejected_the_same_way(self) -> None:
        placeholder = self.features / "placeholder.md"
        placeholder.write_text("placeholder\n", encoding="utf-8")
        with _fake_reparse_in_tree(placeholder, CLOUD_TAG):
            self.assert_validate_matches("cloud_sync_path")
            self.assert_tree_helpers_match(self.root / "knowledge" / "wiki", "cloud_sync_path")
            self.assert_copy_matches(self.root / "knowledge" / "wiki", "cloud_sync_path")
        self.assert_validate_matches(None)

    def test_cloud_placeholder_directory_inside_the_tree_is_rejected_the_same_way(self) -> None:
        with _fake_reparse_in_tree(self.intake / "nested", 0x9000701A):
            self.assert_validate_matches("cloud_sync_path")
            self.assert_tree_helpers_match(self.intake, "cloud_sync_path")
            self.assert_copy_matches(self.intake, "cloud_sync_path")

    def test_other_reparse_tags_inside_the_tree_keep_the_generic_rejection(self) -> None:
        target = self.features / "tagged.md"
        target.write_text("tagged\n", encoding="utf-8")
        for tag in (JUNCTION_TAG, 0x80000021, None):
            with self.subTest(tag=tag), _fake_reparse_in_tree(target, tag):
                self.assert_validate_matches("reparse_path")
                self.assert_tree_helpers_match(self.root / "knowledge" / "wiki", "reparse_path")

    def test_cloud_and_reparse_ancestors_of_the_root_are_rejected_the_same_way(self) -> None:
        with fake_reparse(self.parent, CLOUD_TAG):
            self.assert_validate_matches("cloud_sync_path")
        with fake_reparse(self.base, JUNCTION_TAG):
            self.assert_validate_matches("reparse_path")
        with fake_reparse(self.root, 0x9000701A):
            self.assert_validate_matches("cloud_sync_path")

    def test_cloud_placeholder_on_a_checked_file_or_the_knowledge_folder_is_rejected_the_same_way(self) -> None:
        for target in (self.root / "prism.workspace.yml", self.root / ".claude" / "commands", self.root / "knowledge"):
            with self.subTest(target=target.relative_to(self.root).as_posix()), fake_reparse(target, CLOUD_TAG):
                self.assert_validate_matches("cloud_sync_path")

    def test_ancestor_chain_is_checked_on_every_call(self) -> None:
        self.service.validate_graph_inputs()
        with fake_reparse(self.parent, CLOUD_TAG):
            with self.assertRaises(BoardError) as raised:
                self.service.validate_graph_inputs()
        self.assertEqual("cloud_sync_path", raised.exception.code)
        self.service.validate_graph_inputs()

    def test_ancestors_are_not_rechecked_for_every_entry(self) -> None:
        for number in range(40):
            (self.features / f"F-{number + 100:03d}-extra.md").write_text("extra\n", encoding="utf-8")
        lstat_calls = []
        real_lstat = Path.lstat

        def counting_lstat(path: Path, *args: Any, **kwargs: Any) -> Any:
            lstat_calls.append(path)
            return real_lstat(path, *args, **kwargs)

        with patch.object(Path, "lstat", counting_lstat):
            self.service.validate_graph_inputs()
        feature_entries = [path for path in lstat_calls if path.parent == self.features]
        self.assertEqual([], feature_entries)
        self.assertLess(len(lstat_calls), 120)
