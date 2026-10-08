"""The explicit scope edit through the board: `feature-scope`, from a retired app to an unblocked feature.

Retiring an app never changes a feature's scope. A feature before `released` that still lists it is blocked with
`app_retired_in_scope` until its `apps` and its `## App scope` are edited; a `released` feature keeps the retired app as
history. Before `ready-for-dev` a scope edit adds and removes apps; from there on it is the gated `scope-edit` action
(F26) that only removes apps and rewrites the acceptance criteria accordingly.
"""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService, _parse_markdown
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_transitions import build_transition_preflight
from prism_cli.workflow_install import apply_install, plan_install
from tests import real_temp  # noqa: F401
from tests.board_approval import apply_preview, human_with_roles
from tests.core_workflow_fixture import INTAKE_ITEM, create_core_workflow_fixture
from tests.test_apps_surfaces import run_cli
from tests.test_board_service import (
    _append_body_section,
    _journey_feature_page,
    _journey_requirement_page,
    _read_revisions,
    _replace_body_section,
    _replace_body_section_text,
    _set_feature_stage,
    _set_requirement_status,
    _set_stage_and_revalidation,
    _write_index_rows,
)
from tests.wiki_files import evidence_tables

FEATURE_ONE = "knowledge/wiki/features/F-001-document-review.md"
FEATURE_TWO = "knowledge/wiki/features/F-002-document-summary.md"
FEATURE_THREE = "knowledge/wiki/features/F-003-document-intake.md"
FEATURES = {"F-001": FEATURE_ONE, "F-002": FEATURE_TWO, "F-003": FEATURE_THREE}
CRITERION = "A reviewer can record the outcome and requested follow-up."
SOURCE = "knowledge/intake/processed/2026-10-06-document-review-brief"
QUESTION = ["| 1 | Which points should a review summary highlight? | po | resolved: The key points. |"]
NO_API = {"has-ui": False, "serves-api": False}


def requirement(feature_id: str, app: str, status: str) -> str:
    return _set_requirement_status(_journey_requirement_page("pending").replace("feature-id: F-001", f"feature-id: {feature_id}").replace("app: backend", f"app: {app}"), status)


def requirement_path(feature_id: str, app: str) -> str:
    return f"knowledge/wiki/app-requirements/{feature_id}-{app}.md"


def with_apps(content: str, apps: list[str]) -> str:
    """The page with a new `apps` list, an App scope section that lists those apps and one criterion that applies to all of them."""

    frontmatter, body = _parse_markdown(content)
    frontmatter["apps"] = apps
    frontmatter["criteria-high-water"] = 1
    scope = "\n".join(f"- **{app}**: Deliver the review summary in {app}." for app in apps)
    page = _replace_body_section_text(f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}", "App scope", scope)
    return _replace_body_section_text(page, "Acceptance criteria", f"- [ ] AC-1 [{', '.join(apps)}] {CRITERION}")


def released_page(feature_id: str, title: str, scope: list[str]) -> str:
    """A released feature: a delivery, a passing QA and a released Release row for each app of the scope."""

    page = with_apps(_journey_feature_page(feature_id, title, "released", "none", [SOURCE], QUESTION), scope)
    for chunk in evidence_tables(scope, feature_id=feature_id, criterion=CRITERION).strip().split("\n\n"):
        heading, rest = chunk.split("\n", 1)
        page = _replace_body_section_text(page, heading[3:], rest)
    return page


def delivery_table(scope: list[str], feature_id: str) -> str:
    chunk = evidence_tables(scope, stage="ready-for-qa", feature_id=feature_id, criterion=CRITERION).strip().split("\n\n")[0]
    return chunk.split("\n", 1)[1]


class ScopeEditBoardTests(unittest.TestCase):
    """Three features that list `legacy-batch` (in development, released and ready for design) and the app retired afterwards."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "generated-project")
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))["status"])
        (self.root / INTAKE_ITEM).parent.rename(self.root / SOURCE)
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        for app in ("legacy-batch", "successor"):
            manifest["apps"].append({"id": app, "name": app, "stack": "other", "repository": "workspace", "path": f"tools/{app}", "capabilities": NO_API})
            (self.root / "tools" / app).mkdir(parents=True)
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        scope = ["backend", "legacy-batch"]
        in_development = with_apps(_journey_feature_page("F-001", "Document review", "in-dev", "dev", [SOURCE], QUESTION), scope)
        released = released_page("F-002", "Document summary", scope)
        in_design = with_apps(_journey_feature_page("F-003", "Document intake", "ready-for-design", "tech-lead", [SOURCE], QUESTION), scope)
        for relative, content in (
            (FEATURE_ONE, in_development),
            (FEATURE_TWO, released),
            (FEATURE_THREE, in_design),
            *((requirement_path("F-001", app), requirement("F-001", app, "in-progress")) for app in scope),
            *((requirement_path("F-002", app), requirement("F-002", app, "done")) for app in scope),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        _write_index_rows(
            self.root,
            [("F-001", "Document review", "in-dev", "dev"), ("F-002", "Document summary", "released", "none"), ("F-003", "Document intake", "ready-for-design", "tech-lead")],
        )

        code, _out, err = run_cli("app", "retire", "legacy-batch", str(self.root), "--apply", "--yes")
        self.assertEqual(0, code, err)
        _write_index_rows(
            self.root,
            [("F-001", "Document review", "in-dev", "dev"), ("F-002", "Document summary", "released", "none"), ("F-003", "Document intake", "ready-for-design", "tech-lead")],
        )
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Scope agent", "agent", True)["token"])
        # From `ready-for-dev` on a scope edit is gated: a human who holds `po` approves it in a board session.
        self.human = human_with_roles(self.service, "Scope owner", "po")

    # -- helpers ---------------------------------------------------------------------------------

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def preview(self, skill: str, changes: list[dict[str, str]]) -> dict:
        return self.service.preview_skill(self.agent, skill, changes, None, _read_revisions(self.service, self.agent, skill, changes))

    def apply(self, preview: dict) -> dict:
        self.assertTrue(preview["applicable"], preview["blockers"])
        receipt = apply_preview(self.service, self.agent, preview, str(uuid4()), approver=self.human)
        self.assertEqual("applied", receipt["state"], receipt)
        return receipt

    def rejected(self, skill: str, changes: list[dict[str, str]]) -> BoardError:
        with self.assertRaises(BoardError) as caught:
            self.preview(skill, changes)
        return caught.exception

    def flagged(self) -> list[str]:
        return sorted(item.feature_id for item in lint_wiki(self.root).diagnostics if item.code == "app-retired-in-scope")

    def scope_edit(self, apps: list[str], *, feature_id: str = "F-001", requirements: tuple[str, ...] = ()) -> list[dict[str, str]]:
        changes = [{"path": FEATURES[feature_id], "content": with_apps(self.read(FEATURES[feature_id]), apps)}]
        changes.extend({"path": requirement_path(feature_id, app), "content": requirement(feature_id, app, "pending")} for app in requirements)
        return changes

    def log_operations(self) -> list[tuple[str, str]]:
        return re.findall(r"(?m)^## \d{4}-\d{2}-\d{2} (\S+) \| (.*)$", self.read("knowledge/wiki/log.md"))

    # -- the path through the board ---------------------------------------------------------------

    def test_retire_an_app_edit_the_scope_of_the_feature_in_progress_and_keep_the_released_one(self) -> None:
        # 1. The app is retired. The features before release are flagged and blocked; the released feature keeps the app as history.
        self.assertEqual(["F-001", "F-003"], self.flagged())
        current = self.read(FEATURE_ONE)
        finished = _set_feature_stage(current, "ready-for-qa", "qa")
        finished = _replace_body_section_text(finished, "Delivery evidence", delivery_table(["backend", "legacy-batch"], "F-001"))
        blocked = self.rejected("dev-done", [{"path": FEATURE_ONE, "content": finished}])
        self.assertEqual(("app_retired_in_scope", 409), (blocked.code, blocked.status))
        self.assertEqual(["legacy-batch"], blocked.details["retired_apps"])

        # 2. The scope is edited through the gated scope edit: the retired app leaves, the criteria follow.
        before = self.read(FEATURE_ONE)
        receipt = self.apply(self.preview("feature-scope", self.scope_edit(["backend"])))
        self.assertIn(FEATURE_ONE, receipt["applied_paths"])
        self.assertIn("knowledge/wiki/log.md", receipt["applied_paths"])
        self.assertNotIn("knowledge/wiki/status-board.md", receipt["applied_paths"], "a scope edit changes no status row")
        edited = _parse_markdown(self.read(FEATURE_ONE))
        previous = _parse_markdown(before)[0]
        self.assertEqual(["backend"], edited[0]["apps"])
        self.assertEqual({key: value for key, value in previous.items() if key != "apps"}, {key: value for key, value in edited[0].items() if key != "apps"})
        self.assertIn("**backend**", edited[1])
        self.assertNotIn("legacy-batch", edited[1])
        self.assertIn("AC-1 [backend]", edited[1])
        self.assertIn(("board-feature-scope", "F-001"), self.log_operations())
        self.assertTrue((self.root / requirement_path("F-001", "legacy-batch")).is_file(), "the requirement page of the removed app stays as history")

        # 3. The feature is unblocked: lint no longer flags it, and the lifecycle checks no longer name the retired app.
        self.assertEqual(["F-003"], self.flagged())
        self.service._require_no_retired_app_in_progress("F-001", _parse_markdown(self.read(FEATURE_ONE))[0])
        checks = build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]["checks"]
        self.assertFalse(any(item["code"] == "app-retired-in-scope" for item in checks))

        # 4. The released feature that lists the retired app keeps it as history and is not flagged; its reopen route is a later package's.
        self.assertEqual("released", _parse_markdown(self.read(FEATURE_TWO))[0]["status"])
        self.assertNotIn("F-002", self.flagged())
        with self.assertRaises(BoardError) as no_route:
            self.preview("feature-reopen", [{"path": FEATURE_TWO, "content": self.read(FEATURE_TWO)}])
        self.assertEqual(("reopen_route_required", 409), (no_route.exception.code, no_route.exception.status))
        with self.assertRaises(BoardError) as unavailable:
            self.preview("feature-reopen", [{"path": FEATURE_TWO, "content": _set_feature_stage(self.read(FEATURE_TWO), "in-dev", "dev")}])
        self.assertEqual(("action_unavailable", 409), (unavailable.exception.code, unavailable.exception.status))

    # -- what a scope edit refuses ----------------------------------------------------------------

    def test_a_retired_app_may_stay_or_leave_but_is_never_added_to_a_scope(self) -> None:
        # The feature in design already lists the retired app, so keeping it is not an addition.
        kept = self.preview("feature-scope", self.scope_edit(["backend", "legacy-batch", "successor"], feature_id="F-003", requirements=("successor",)))
        self.assertTrue(kept["applicable"])
        self.apply(self.preview("feature-scope", self.scope_edit(["backend", "successor"], feature_id="F-003", requirements=("successor",))))
        # Once it has left, naming it again is refused.
        error = self.rejected("feature-scope", self.scope_edit(["backend", "successor", "legacy-batch"], feature_id="F-003"))
        self.assertEqual(("app_retired", 409), (error.code, error.status))
        self.assertEqual(["legacy-batch"], error.details["retired_apps"])

    def test_a_feature_past_design_only_loses_apps(self) -> None:
        error = self.rejected("feature-scope", self.scope_edit(["backend", "legacy-batch", "successor"], requirements=("successor",)))
        self.assertEqual(("scope_stage_unavailable", 409), (error.code, error.status))
        self.assertEqual(["successor"], error.details["added_apps"])

    def test_the_apps_list_and_the_app_scope_section_change_together(self) -> None:
        current = self.read(FEATURE_ONE)
        only_list = current.replace("- legacy-batch\n", "", 1) if "- legacy-batch\n" in current else None
        frontmatter, body = _parse_markdown(current)
        frontmatter["apps"] = ["backend"]
        only_list = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        error = self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": only_list}])
        self.assertEqual("scope_text_unchanged", error.code)

        unchanged = self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": _replace_body_section(self.service, current, "App scope", "- **backend**: Deliver it. Again.")}])
        self.assertEqual("scope_unchanged", unchanged.code)

    def test_a_scope_edit_changes_nothing_but_the_scope(self) -> None:
        edited = with_apps(self.read(FEATURE_ONE), ["backend"])
        status_changed = _set_feature_stage(edited, "ready-for-dev", "dev")
        self.assertEqual("app_stage_mismatch", self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": status_changed}]).code)
        raw = _set_feature_stage(edited, "raw", "po")
        self.assertEqual("app_stage_mismatch", self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": raw}]).code)

        frontmatter, body = _parse_markdown(edited)
        frontmatter["sources"] = []
        retitled = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        self.assertEqual("scope_frontmatter_change", self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": retitled}]).code)

        other_section = _replace_body_section(self.service, edited, "Summary", "A different summary.")
        self.assertEqual("scope_body_exceeded", self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": other_section}]).code)

    def test_a_released_feature_never_gains_an_app(self) -> None:
        content = with_apps(self.read(FEATURE_TWO), ["backend", "successor"])
        error = self.rejected("feature-scope", [{"path": FEATURE_TWO, "content": content}])
        self.assertEqual("scope_stage_unavailable", error.code)

    def test_a_requirement_page_is_new_and_belongs_to_an_added_app(self) -> None:
        existing = {"path": requirement_path("F-003", "backend"), "content": requirement("F-003", "backend", "pending")}
        (self.root / existing["path"]).write_bytes(existing["content"].encode("utf-8"))
        error = self.rejected("feature-scope", [*self.scope_edit(["backend", "successor"], feature_id="F-003", requirements=("successor",)), existing])
        self.assertEqual("requirement_exists", error.code)
        wrong_app = self.scope_edit(["backend", "successor"], feature_id="F-003")
        wrong_app.append({"path": requirement_path("F-003", "legacy-batch"), "content": requirement("F-003", "legacy-batch", "pending")})
        self.assertIn(self.rejected("feature-scope", wrong_app).code, {"requirement_exists", "requirement_scope_mismatch"})
        started = self.scope_edit(["backend", "successor"], feature_id="F-003", requirements=("successor",))
        started[1]["content"] = requirement("F-003", "successor", "in-progress")
        self.assertEqual("requirement_initial_status", self.rejected("feature-scope", started).code)

    def test_the_skill_writes_only_features_and_requirements(self) -> None:
        for path in ("knowledge/wiki/design/F-001-document-review.md", "knowledge/wiki/api-contracts/F-001.md", "knowledge/wiki/topics/notes.md"):
            with self.subTest(path=path), self.assertRaises(BoardError) as caught:
                self.service._assert_skill_write_path("feature-scope", path)
            self.assertEqual("write_path_unavailable", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
