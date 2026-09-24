"""Structural safety checks for the provider-neutral connected BoardService."""

from __future__ import annotations

import hashlib
from io import BytesIO
import re
from contextlib import nullcontext
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService, _parse_markdown
from prism_cli.workflow_assets import asset_digest
from prism_cli.workflow_install import apply_install, plan_install
from tests.core_workflow_fixture import FEATURE_PATH, INTAKE_ITEM, create_core_workflow_fixture
from tests.test_core_workflow_fixture import CHECK_DATE, _feature_page, _write_index


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
                "knowledge/wiki/features/**",
                "knowledge/wiki/personas/**",
                "knowledge/wiki/business-rules/**",
                "knowledge/intake/processed/**/MANIFEST.md",
                "knowledge/intake/quarantined/**/CONFLICT.md",
            ],
            "design-intake": [
                "knowledge/wiki/features/**",
                "knowledge/wiki/design/**",
                "knowledge/intake/processed/**/MANIFEST.md",
                "knowledge/intake/quarantined/**/CONFLICT.md",
            ],
            "ask": ["knowledge/wiki/features/**"],
            "po-clarify": ["knowledge/wiki/features/**"],
            "design-clarify": ["knowledge/wiki/features/**", "knowledge/wiki/design/**"],
            "po-specify": ["knowledge/wiki/features/**"],
            "po-handoff": ["knowledge/wiki/features/**"],
            "design-start": ["knowledge/wiki/features/**"],
            "design-handoff": ["knowledge/wiki/features/**", "knowledge/wiki/platform-requirements/**"],
            "dev-start": ["knowledge/wiki/features/**"],
            "dev-done": [
                "knowledge/wiki/features/**",
                "knowledge/wiki/platform-requirements/**",
                "knowledge/wiki/api-contracts/**",
            ],
            "feature-reopen": [
                "knowledge/wiki/features/**",
                "knowledge/wiki/platform-requirements/**",
                "knowledge/wiki/api-contracts/**",
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
            ("design-handoff", "knowledge/wiki/platform-requirements/backend.md"),
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
            ("po-specify", "knowledge/wiki/platform-requirements/backend.md"),
            ("po-handoff", "knowledge/wiki/platform-requirements/backend.md"),
            ("design-start", "knowledge/wiki/platform-requirements/backend.md"),
            ("design-handoff", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("dev-start", "knowledge/wiki/api-contracts/F-002-review.md"),
            ("dev-done", "knowledge/wiki/design/F-002-review.md"),
            ("feature-reopen", "knowledge/wiki/design/F-002-review.md"),
        )
        for skill, path in rejected:
            with self.subTest(skill=skill, rejected_path=path), self.assertRaises(BoardError) as error:
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
        feature = _set_feature_stage(feature, "specified", "po").replace(
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
            "specified",
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
    response = service.read_workspace(actor, sorted(required)) if required else {"files": []}
    return {item["path"]: item["digest"] for item in response["files"]}


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
