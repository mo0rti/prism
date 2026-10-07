"""The explicit scope edit through the board: `feature-scope`, from a retired app to an unblocked feature.

Retiring an app never changes a feature's scope. A feature before `done` that still lists it is blocked with
`app_retired_in_scope` until its `apps` and its `## App scope` are edited; a `done` feature keeps the retired app as
history and can still be reopened. The scope edit is the board-validated way through both.
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
from tests.test_core_workflow_fixture import CHECK_DATE

FEATURE_ONE = "knowledge/wiki/features/F-001-document-review.md"
FEATURE_TWO = "knowledge/wiki/features/F-002-document-summary.md"
SOURCE = "knowledge/intake/processed/2026-10-06-document-review-brief"
QUESTION = ["| 1 | Which points should a review summary highlight? | po | resolved: The key points. |"]
NO_API = {"has-ui": False, "serves-api": False}
ROW = "| {app} | Synthetic record `tests/fixtures/{app}.md` | Acceptance check `{app}` passed | release: https://example.test/releases/{app}-v1 |"


def requirement(feature_id: str, app: str, status: str) -> str:
    return _set_requirement_status(_journey_requirement_page("pending").replace("feature-id: F-001", f"feature-id: {feature_id}").replace("app: backend", f"app: {app}"), status)


def requirement_path(feature_id: str, app: str) -> str:
    return f"knowledge/wiki/app-requirements/{feature_id}-{app}.md"


def with_apps(content: str, apps: list[str]) -> str:
    """The page with a new `apps` list and an App scope section that lists those apps."""

    frontmatter, body = _parse_markdown(content)
    frontmatter["apps"] = apps
    scope = "\n".join(f"- **{app}**: Deliver the review summary in {app}." for app in apps)
    return _replace_body_section_text(f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}", "App scope", scope)


class ScopeEditBoardTests(unittest.TestCase):
    """Two features that list `legacy-batch`, one in development and one done, and the app retired afterwards."""

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
        done = with_apps(_journey_feature_page("F-002", "Document summary", "done", "none", [SOURCE], QUESTION), scope)
        evidence = "| App | Implementation | Tests | Release |\n|---|---|---|---|\n" + "\n".join(ROW.format(app=app) for app in scope)
        done = _replace_body_section(None, done, "Delivery evidence", evidence)  # type: ignore[arg-type]
        for relative, content in (
            (FEATURE_ONE, in_development),
            (FEATURE_TWO, done),
            *((requirement_path("F-001", app), requirement("F-001", app, "in-progress")) for app in scope),
            *((requirement_path("F-002", app), requirement("F-002", app, "done")) for app in scope),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        _write_index_rows(self.root, [("F-001", "Document review", "in-dev", "dev"), ("F-002", "Document summary", "done", "none")])

        code, _out, err = run_cli("app", "retire", "legacy-batch", str(self.root), "--apply", "--yes")
        self.assertEqual(0, code, err)
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Scope agent", "agent", True)["token"])

    # -- helpers ---------------------------------------------------------------------------------

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def preview(self, skill: str, changes: list[dict[str, str]]) -> dict:
        return self.service.preview_skill(self.agent, skill, changes, None, _read_revisions(self.service, self.agent, skill, changes))

    def apply(self, preview: dict) -> dict:
        self.assertTrue(preview["applicable"], preview["blockers"])
        receipt = self.service.apply(self.agent, preview["preview_id"], str(uuid4()))
        self.assertEqual("applied", receipt["state"], receipt)
        return receipt

    def rejected(self, skill: str, changes: list[dict[str, str]]) -> BoardError:
        with self.assertRaises(BoardError) as caught:
            self.preview(skill, changes)
        return caught.exception

    def flagged(self) -> list[str]:
        return sorted(item.feature_id for item in lint_wiki(self.root).diagnostics if item.code == "app-retired-in-scope")

    def scope_edit(self, apps: list[str], *, requirements: tuple[str, ...] = ()) -> list[dict[str, str]]:
        changes = [{"path": FEATURE_ONE, "content": with_apps(self.read(FEATURE_ONE), apps)}]
        changes.extend({"path": requirement_path("F-001", app), "content": requirement("F-001", app, "pending")} for app in requirements)
        return changes

    def log_operations(self) -> list[tuple[str, str]]:
        return re.findall(r"(?m)^## \d{4}-\d{2}-\d{2} (\S+) \| (.*)$", self.read("knowledge/wiki/log.md"))

    # -- the path through the board ---------------------------------------------------------------

    def test_retire_an_app_edit_the_scope_of_the_feature_in_progress_and_reopen_the_done_one(self) -> None:
        # 1. The app is retired. The feature in progress is flagged and blocked; the done feature keeps the app as history.
        self.assertEqual(["F-001"], self.flagged())
        current = self.read(FEATURE_ONE)
        finished = _set_feature_stage(current, "done", "none")
        blocked = self.rejected("dev-done", [{"path": FEATURE_ONE, "content": finished}])
        self.assertEqual(("app_retired_in_scope", 409), (blocked.code, blocked.status))
        self.assertEqual(["legacy-batch"], blocked.details["retired_apps"])

        # 2. The scope is edited through the new path: the retired app leaves, the active app that replaces it joins.
        before = self.read(FEATURE_ONE)
        receipt = self.apply(self.preview("feature-scope", self.scope_edit(["backend", "successor"], requirements=("successor",))))
        self.assertIn(FEATURE_ONE, receipt["applied_paths"])
        self.assertIn(requirement_path("F-001", "successor"), receipt["applied_paths"])
        self.assertIn("knowledge/wiki/index.md", receipt["applied_paths"])
        self.assertIn("knowledge/wiki/log.md", receipt["applied_paths"])
        self.assertNotIn("knowledge/wiki/status-board.md", receipt["applied_paths"], "a scope edit changes no status row")
        edited = _parse_markdown(self.read(FEATURE_ONE))
        previous = _parse_markdown(before)[0]
        self.assertEqual(["backend", "successor"], edited[0]["apps"])
        self.assertEqual({key: value for key, value in previous.items() if key != "apps"}, {key: value for key, value in edited[0].items() if key != "apps"})
        self.assertIn("**successor**", edited[1])
        self.assertNotIn("legacy-batch", edited[1])
        self.assertIn(("board-feature-scope", "F-001"), self.log_operations())
        self.assertEqual("pending", _parse_markdown(self.read(requirement_path("F-001", "successor")))[0]["status"])
        self.assertTrue((self.root / requirement_path("F-001", "legacy-batch")).is_file(), "the requirement page of the removed app stays as history")

        # 3. The feature is unblocked: lint no longer flags it, and the lifecycle checks no longer name the retired app.
        self.assertEqual([], self.flagged())
        self.service._require_no_retired_app_in_progress("F-001", _parse_markdown(self.read(FEATURE_ONE))[0])
        checks = build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]["checks"]
        self.assertFalse(any(item["code"] == "app-retired-in-scope" for item in checks))

        # 4. The done feature that lists the retired app is reopened: its requirement page of the retired app can be invalidated.
        self.assertEqual("done", _parse_markdown(self.read(FEATURE_TWO))[0]["status"])
        legacy_requirement = requirement_path("F-002", "legacy-batch")
        table = ["| App | Implementation | Tests | Release |", "|---|---|---|---|", *(ROW.format(app=app) for app in ("backend", "legacy-batch"))]
        record = "\n".join(
            [
                f"### {CHECK_DATE.isoformat()} - reopen-dev",
                "- Reason: The retired batch job's behavior moves into the successor app and its tests must run again.",
                "- Impact review: Recheck the implementation, the tests and the release evidence of the legacy batch requirement.",
                "- Affected apps: legacy-batch",
                f"- Affected artifacts: {FEATURE_TWO} and {legacy_requirement}",
                "- Prior completion/release evidence:",
                *(f"  {line}" for line in table),
                f"- Requirement/API invalidations: {legacy_requirement} done -> in-progress",
            ]
        )
        reopened = _set_stage_and_revalidation(self.service, self.read(FEATURE_TWO), "in-dev", "dev", ["implementation", "tests", "release"])
        reopened = _replace_body_section(self.service, reopened, "Delivery evidence", "| App | Implementation | Tests | Release |\n|---|---|---|---|")
        reopened = _append_body_section(self.service, reopened, "Reopen history", record)
        invalidated = _set_requirement_status(self.read(legacy_requirement), "in-progress")
        preview = self.preview("feature-reopen", [{"path": FEATURE_TWO, "content": reopened}, {"path": legacy_requirement, "content": invalidated}])
        self.assertEqual("ready", preview["classification"], preview["checks"])
        self.apply(preview)
        self.assertEqual(("in-dev", "dev"), tuple(_parse_markdown(self.read(FEATURE_TWO))[0][key] for key in ("status", "owner")))
        self.assertEqual("in-progress", _parse_markdown(self.read(legacy_requirement))[0]["status"])
        # The reopened feature is now in progress and still lists the retired app, so it is flagged until its scope is edited too.
        self.assertEqual(["F-002"], self.flagged())

    # -- what a scope edit refuses ----------------------------------------------------------------

    def test_a_retired_app_may_stay_or_leave_but_is_never_added_to_a_scope(self) -> None:
        # The feature already lists the retired app, so keeping it is not an addition.
        kept = self.preview("feature-scope", self.scope_edit(["backend", "legacy-batch", "successor"], requirements=("successor",)))
        self.assertTrue(kept["applicable"])
        self.apply(self.preview("feature-scope", self.scope_edit(["backend", "successor"], requirements=("successor",))))
        # Once it has left, naming it again is refused, on this feature and on any other that does not list it.
        error = self.rejected("feature-scope", self.scope_edit(["backend", "successor", "legacy-batch"]))
        self.assertEqual(("app_retired", 409), (error.code, error.status))
        self.assertEqual(["legacy-batch"], error.details["retired_apps"])

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
        self.assertEqual("lifecycle_action_required", self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": status_changed}]).code)

        frontmatter, body = _parse_markdown(edited)
        frontmatter["sources"] = []
        retitled = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        self.assertEqual("scope_frontmatter_change", self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": retitled}]).code)

        other_section = _replace_body_section(self.service, edited, "Summary", "A different summary.")
        self.assertEqual("scope_body_exceeded", self.rejected("feature-scope", [{"path": FEATURE_ONE, "content": other_section}]).code)

    def test_a_done_feature_keeps_its_scope_until_it_is_reopened(self) -> None:
        content = with_apps(self.read(FEATURE_TWO), ["backend", "successor"])
        error = self.rejected("feature-scope", [{"path": FEATURE_TWO, "content": content}])
        self.assertEqual("scope_stage_unavailable", error.code)

    def test_a_requirement_page_is_new_and_belongs_to_an_added_app(self) -> None:
        existing = {"path": requirement_path("F-001", "backend"), "content": requirement("F-001", "backend", "pending")}
        error = self.rejected("feature-scope", [*self.scope_edit(["backend", "successor"], requirements=("successor",)), existing])
        self.assertEqual("requirement_exists", error.code)
        wrong_app = self.scope_edit(["backend", "successor"])
        wrong_app.append({"path": requirement_path("F-001", "legacy-batch"), "content": requirement("F-001", "legacy-batch", "pending")})
        self.assertIn(self.rejected("feature-scope", wrong_app).code, {"requirement_exists", "requirement_scope_mismatch"})
        started = self.scope_edit(["backend", "successor"], requirements=("successor",))
        started[1]["content"] = requirement("F-001", "successor", "in-progress")
        self.assertEqual("requirement_initial_status", self.rejected("feature-scope", started).code)

    def test_the_skill_writes_only_features_and_requirements(self) -> None:
        for path in ("knowledge/wiki/design/F-001-document-review.md", "knowledge/wiki/api-contracts/F-001.md", "knowledge/wiki/topics/notes.md"):
            with self.subTest(path=path), self.assertRaises(BoardError) as caught:
                self.service._assert_skill_write_path("feature-scope", path)
            self.assertEqual("write_path_unavailable", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
