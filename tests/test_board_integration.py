"""The identity half and the lifecycle half of the board meet: one registry answers roles, availability and policy.

D1a's approval flow asks `required_roles` for the predicate of every gated action; D1b's registry answers it, with the
design owner resolved from the scope. These tests run the real registry (nothing is patched): the predicate is the same at
preview and apply for an unchanged feature and differs, so the preview is stale, once the scope changes; discovery,
availability and the workflow policy come from the same registry and the same `workflow_policy`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from prism_cli import board_service, wiki_transitions
from prism_cli.board_service import BoardError, BoardService
from prism_cli.roles import RolePredicate, required_roles
from prism_cli.workflow_install import apply_install, plan_install
from tests import real_temp  # noqa: F401
from tests.board_approval import approve, give_apps_a_ui, human_with_roles
from tests.test_board_service import _read_revisions
from tests.test_core_workflow_fixture import _feature_page, _write_index

FEATURE = "knowledge/wiki/features/F-001-document-review.md"
SETTINGS = "knowledge/wiki/SETTINGS.md"


class _IntegratedBoard(unittest.TestCase):
    """An adopted workspace whose one app has no UI (so the design owner is the tech lead), F-001 ready for design."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))
        source = self.root / "knowledge/intake/processed/2026-10-06-document-review-brief/brief.md"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"# Document review\nRecord a summary and outcome.\n")
        page = (
            _feature_page()
            .replace("status: raw", "status: ready-for-design")
            .replace("owner: po", "owner: tech-lead")
            .replace("| po | open |", "| po | resolved: Summarize key points. |")
        )
        self.put(FEATURE, page)
        _write_index(self.root, "ready-for-design", "tech-lead")
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.lead = human_with_roles(self.service, "Theo", "tech-lead")
        self.designer = human_with_roles(self.service, "Dana", "designer")
        self.agent = self.service.authenticate(self.service.create_participant("Coding agent", "agent", True)["token"])

    def put(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def read(self, relative: str) -> str:
        return (self.root / relative).read_bytes().decode("utf-8")

    def code(self, call) -> str:
        with self.assertRaises(BoardError) as raised:
            call()
        return raised.exception.code

    def design_start(self, actor):
        return self.service.preview_transition(actor, "F-001", "design-start", {"semantic_review_acknowledged": True})

    def agent_proposal(self):
        content = self.read(FEATURE).replace("status: ready-for-design", "status: in-design")
        changes = [{"path": FEATURE, "content": content}]
        revisions = _read_revisions(self.service, self.agent, "design-start", changes)
        return self.service.preview_skill(self.agent, "design-start", changes, read_revisions=revisions)


class RoleContextTests(_IntegratedBoard):
    def test_the_predicate_is_the_same_at_preview_and_apply_with_the_design_owner_resolved_from_the_scope(self) -> None:
        # The scope has no UI, so the design owner is the tech lead: the designer is refused, the tech lead approves.
        self.assertEqual("role_required", self.code(lambda: self.design_start(self.designer)))
        preview = self.design_start(self.lead)
        predicate = preview["approval"]["required_roles"]
        self.assertEqual({"all_of": ["tech-lead"], "any_of": []}, predicate)
        # The registry gives that answer for the same facts, and the preview recorded the facts it asked with.
        context = preview["approval"]["context"]
        self.assertEqual({"feature_path": FEATURE, "apps": ["backend"], "status": "ready-for-design"}, context)
        asked = {"action": "design-start", "root": self.root, **context}
        self.assertEqual(predicate, required_roles("design-start", asked).as_json())
        receipt = approve(self.service, self.lead, preview, "design-start-1")
        self.assertEqual("applied", receipt["state"], receipt)
        intent = self.service.store.connection.execute("SELECT intent_json FROM operations WHERE operation_id = 'design-start-1'").fetchone()[0]
        self.assertEqual(predicate, yaml.safe_load(intent)["approval"]["required_roles"], "apply recorded the predicate the preview carried")

    def test_an_agent_proposal_carries_the_same_predicate_and_a_reviewer_holding_it_approves(self) -> None:
        proposal = self.agent_proposal()
        self.assertEqual({"all_of": ["tech-lead"], "any_of": []}, proposal["approval"]["required_roles"])
        self.assertEqual("preview_not_found", self.code(lambda: self.service.get_preview(self.designer, proposal["preview_id"])), "only a holder of the roles reads it")
        self.assertEqual("role_required", self.code(lambda: self.service.apply(self.designer, proposal["preview_id"], "wrong-role", "any", True)))
        self.assertEqual("applied", approve(self.service, self.lead, proposal, "right-role")["state"])

    def test_a_change_of_the_scope_between_preview_and_apply_makes_the_preview_stale(self) -> None:
        preview = self.design_start(self.lead)
        self.assertEqual({"all_of": ["tech-lead"], "any_of": []}, preview["approval"]["required_roles"])
        # The app gains a UI: the design owner of the same scope is now the designer. The reviewer reads the preview again.
        give_apps_a_ui(self.root)
        review = self.service.get_preview(self.lead, preview["preview_id"])["approval"]["review_revision"]
        self.assertEqual("stale_preview", self.code(lambda: self.service.apply(self.lead, preview["preview_id"], "after-scope-change", review, True)))
        self.assertIn("status: ready-for-design", self.read(FEATURE), "nothing was written")

    def test_scope_edit_is_gated_for_po_only_from_ready_for_dev_on(self) -> None:
        for status in ("raw", "specified", "ready-for-design", "in-design"):
            self.assertIsNone(self.service._predicate_for("scope-edit", FEATURE, ["backend"], status=status), status)
        for status in ("ready-for-dev", "in-dev", "ready-for-qa", "in-qa", "ready-for-release", "released"):
            self.assertEqual(RolePredicate(all_of=("po",)), self.service._predicate_for("scope-edit", FEATURE, ["backend"], status=status), status)

    def test_a_repair_needs_the_predicate_of_the_original_action(self) -> None:
        predicate = self.service._predicate_for("operation-repair", FEATURE, ["backend"], original_action="design-start", status="ready-for-design")
        self.assertEqual(RolePredicate(all_of=("tech-lead",)), predicate)
        self.assertIsNone(self.service._predicate_for("operation-repair", FEATURE, ["backend"]), "an ungated original needs any writable human")


class RegistryTests(_IntegratedBoard):
    def test_discovery_availability_and_roles_come_from_the_one_registry(self) -> None:
        actions = {item["action"]: item for item in self.service.discover(self.lead)["capability"]["actions"]}
        self.assertEqual(set(wiki_transitions.ACTION_BY_ID), set(actions))
        for name, spec in wiki_transitions.ACTION_BY_ID.items():
            self.assertEqual(spec.available, actions[name]["available"], name)
            self.assertEqual(list(spec.modes), actions[name]["modes"], name)
        # Without a feature the design owner is open, so either design role approves.
        self.assertEqual({"all_of": [], "any_of": ["designer", "tech-lead"]}, actions["design-start"]["required_roles"])
        self.assertEqual({"all_of": ["po"], "any_of": []}, actions["po-handoff"]["required_roles"])
        self.assertTrue(actions["design-start"]["available_to_participant"])
        self.assertTrue(actions["qa-pass"]["available"])
        self.assertFalse(actions["release-done"]["available"])
        self.assertIn("work package D4", actions["release-done"]["unavailable_reason"])

    def test_an_action_of_a_package_that_has_not_landed_is_refused_with_the_registry_reason(self) -> None:
        spec = dataclasses.replace(wiki_transitions.lookup_action("design-start"), package="D9")
        with patch.dict(wiki_transitions.ACTION_BY_ID, {"design-start": spec}):
            with self.assertRaises(BoardError) as raised:
                self.design_start(self.lead)
        self.assertEqual(("action_unavailable", 409), (raised.exception.code, raised.exception.status))
        self.assertEqual("D9", raised.exception.details["package"])
        self.assertIn(spec.unavailable_reason, raised.exception.message)


class PolicyTests(_IntegratedBoard):
    SETTINGS_TEXT = "---\nwiki-stale-after-days: 14\n{extra}---\n\n# Wiki Settings\n"

    def settings(self, extra: str = "") -> None:
        self.put(SETTINGS, self.SETTINGS_TEXT.format(extra=extra))

    def test_the_policy_is_the_workflow_policy_of_the_registry_settings(self) -> None:
        self.settings("qa-separate-from-dev: true\ndelivery-targets:\n  backend: { kind: deployment, target: staging }\n")
        policy = self.service._read_policy()
        self.assertTrue(policy["qa_separate_from_dev"])
        self.assertEqual({"backend": {"kind": "deployment", "target": "staging", "environments": []}}, policy["delivery_targets"])
        self.assertEqual(policy["revision"], self.service._policy_revision(policy))
        self.assertEqual({"qa_separate_from_dev": True, "revision": policy["revision"]}, self.service.discover(self.lead)["capability"]["policy"])

    def test_a_malformed_policy_is_refused_and_never_read_as_the_default(self) -> None:
        for extra in ("qa-separate-from-dev: maybe\n", "delivery-targets:\n  ghost: { kind: deployment }\n", "delivery-targets: nonsense\n"):
            with self.subTest(extra=extra):
                self.settings(extra)
                self.assertEqual("invalid_policy", self.code(lambda: self.design_start(self.lead)))
                self.assertEqual("invalid_policy", self.code(lambda: self.agent_proposal()))
                self.assertEqual(
                    {"qa_separate_from_dev": None, "revision": None, "error": "invalid_policy"},
                    self.service.discover(self.lead)["capability"]["policy"],
                )

    def test_a_change_of_a_delivery_target_after_the_review_is_a_stale_policy(self) -> None:
        self.settings()
        preview = self.design_start(self.lead)
        review = self.service.get_preview(self.lead, preview["preview_id"])["approval"]["review_revision"]
        self.settings("delivery-targets:\n  backend: { kind: deployment, target: staging }\n")
        self.assertEqual("stale_policy", self.code(lambda: self.service.apply(self.lead, preview["preview_id"], "policy-changed", review, True)))

    def test_a_separation_pending_warning_never_blocks_the_proposal(self) -> None:
        self.settings("qa-separate-from-dev: true\n")
        subject = {"kind": "delivery", "item_id": "F-001", "app": "backend", "generation": 1, "row_digest": "sha256:row"}
        real = self.service._validate_skill_semantics

        def with_subjects(*arguments, **keywords):
            operation = real(*arguments, **keywords)
            return {**operation, "separation_subjects": [subject]}

        with patch.object(self.service, "_validate_skill_semantics", side_effect=with_subjects):
            proposal = self.agent_proposal()
        self.assertEqual(("ready", True, []), (proposal["classification"], proposal["applicable"], proposal["blockers"]))
        self.assertEqual(["separation-pending"], [item["code"] for item in proposal["warnings"]])
        self.assertEqual("warning", proposal["warnings"][0]["status"])
        self.assertIn(proposal["warnings"][0], proposal["checks"])
        self.assertEqual([subject], proposal["separation_subjects"])


if __name__ == "__main__":
    unittest.main()
