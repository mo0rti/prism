"""Design tracks, technical design, the API contract and the returns from implementation (CONTRACTS 3, F3 to F6, F10, F11).

A disposable workspace has a backend that serves an API and a web app with a UI. One feature (F-001) goes through design with
the board service: an agent proposes each step, a human who holds the roles of that step approves it in a board session.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService, _parse_markdown
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import (
    DesignTracks,
    contract_citation,
    contract_digest,
    contract_sections,
    initial_design_tracks,
    parse_design_tracks,
    parse_test_strategy,
    read_feature_evidence,
    technical_design_problems,
)
from prism_cli.wiki_transitions import build_transition_preflight
from prism_cli.workflow_install import apply_install, plan_install
from tests import real_temp  # noqa: F401
from tests.board_approval import apply_preview, human_with_roles
from tests.core_workflow_fixture import INTAKE_ITEM, create_core_workflow_fixture
from tests.test_board_service import (
    _journey_feature_page,
    _journey_requirement_page,
    _read_revisions,
    _replace_body_section_text,
    _set_requirement_status,
    _write_index_rows,
)
from tests.test_core_workflow_fixture import CHECK_DATE

SOURCE = "knowledge/intake/processed/2026-10-06-document-review-brief"
FEATURE = "knowledge/wiki/features/F-001-document-review.md"
DESIGN = "knowledge/wiki/design/F-001-document-review.md"
TECH = "knowledge/wiki/technical-design/F-001-document-review.md"
CONTRACT = "knowledge/wiki/api-contracts/F-001.md"
BACKEND_REQ = "knowledge/wiki/app-requirements/F-001-backend.md"
WEB_REQ = "knowledge/wiki/app-requirements/F-001-web.md"
SURFACE = "A new endpoint `POST /api/v1/reviews/{id}/exports` returns the review summary as a PDF export for the signed-in reviewer."
CRITERIA = [
    "AC-1 [backend] A review summary can be exported as a PDF.",
    "AC-2 [web] A reviewer can download the export from the review panel.",
    "AC-3 [integration: backend, web] A downloaded export matches the saved review summary.",
]
CRITERION_IDS = ["AC-1", "AC-2", "AC-3"]
DELIVERY_HEADER = "| App | Artifact | Contract | Implementation | Tests | Basis |\n|---|---|---|---|---|---|"


def designs_page(apps: str = "[web]", title: str = "Document review") -> str:
    return (
        f"---\nfeature-id: F-001\ntitle: {title}\napps: {apps}\nfigma: reviewed-document-flow\n---\n\n"
        "## Summary\nThe reviewer sees the document title and review status.\n\n"
        "## Key design decisions\nKeep the review outcome beside the source document.\n\n"
        "## States covered\nThe page shows pending and completed reviews.\n\n"
        "## Component references\nUse the existing document summary panel.\n\n"
        "## Open design questions\nThe reviewer can scan the summary before saving.\n"
    )


def technical_page(*, strategy: list[str] | None = None, apps: str = "[backend, web]", summary: str | None = None, impact: list[str] | None = None) -> str:
    strategy = strategy if strategy is not None else [
        "| AC-1 | backend | automated | integration | The export is created for the signed-in reviewer |",
        "| AC-2 | web | manual | end-to-end | |",
        "| AC-3 | backend, web | manual | end-to-end | Compare the PDF with the saved summary |",
    ]
    impact = impact if impact is not None else [
        "| backend | reviews | A new export service behind the reviews module |",
        "| web | review panel | A download action that calls the export endpoint |",
    ]
    return (
        f"---\nfeature-id: F-001\ntitle: Document review technical design\napps: {apps}\ndecisions: []\n---\n\n"
        f"## Summary\n{summary or 'The review summary is exported by a new backend service that the web app calls.'}\n\n"
        "## Architecture impact\n| App | Modules | Change |\n|---|---|---|\n" + "\n".join(impact) + "\n\n"
        "## Data model and migrations\nNo migration is needed; the export is generated when it is requested.\n\n"
        "## Security and privacy\nOnly the signed-in reviewer of a review can export it.\n\n"
        "## Non-functional requirements\nAn export of a typical review is ready within five seconds.\n\n"
        "## Risks\nA very large review may exceed the export time limit.\n\n"
        "## Decisions\nThe export is generated on request and not stored.\n\n"
        "## API contract\nThe export endpoint is described in the API contract of this feature.\n\n"
        "## Test strategy\n| Criterion | Applies to | Method | Level | Notes |\n|---|---|---|---|---|\n" + "\n".join(strategy) + "\n"
    )


def contract_page(*, version: int = 1, status: str = "agreed", errors: str = "401, 404", feature_id: str = "F-001") -> str:
    return (
        f"---\nfeature-id: {feature_id}\nversion: {version}\nstatus: {status}\n---\n\n"
        f"## Endpoints\n- `POST /api/v1/reviews/{{reviewId}}/exports` creates a review export. Request body: none. Response body: `ReviewExport` (201). Errors: {errors}.\n\n"
        "## Data models\n### ReviewExport\n- `reviewId`: string\n- `url`: string\n\n"
        "## Authentication requirements\nBearer token of the signed-in reviewer.\n\n"
        "## Notes\nThe export is generated when it is requested.\n"
    )


def edit_frontmatter(content: str, updates: dict | None = None, remove: tuple[str, ...] = ()) -> str:
    frontmatter, body = _parse_markdown(content)
    frontmatter.update(updates or {})
    for key in remove:
        frontmatter.pop(key, None)
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"


def requirement_page(app: str, status: str = "pending", body_note: str | None = None) -> str:
    page = _set_requirement_status(_journey_requirement_page("pending").replace("app: backend", f"app: {app}"), status)
    if body_note:
        page = _replace_body_section_text(page, "What to build", body_note)
    return page


class TrackCase(unittest.TestCase):
    """One feature that touches a backend with an API and a web app with a UI, at `ready-for-design`."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        clock = Mock(wraps=date)
        clock.today.return_value = CHECK_DATE
        clock_patch = patch("prism_cli.board_service.date", clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "workspace")
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))["status"])
        (self.root / INTAKE_ITEM).parent.rename(self.root / SOURCE)
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["apps"].append({"id": "web", "name": "web", "stack": "nextjs-web", "repository": "workspace", "path": "web"})
        (self.root / "web").mkdir()
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        self.seed_feature("ready-for-design", "designer", None)
        self.start()

    def start(self) -> None:
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Workflow agent", "agent", True)["token"])
        self.human = human_with_roles(self.service, "Workflow owner")

    # -- pages -----------------------------------------------------------------------------------------------

    def page(
        self,
        status: str,
        owner: str,
        tracks: DesignTracks | None,
        *,
        apps: list[str] | None = None,
        surface: str = SURFACE,
        criteria: list[str] | None = None,
        delivery: list[str] | None = None,
        questions: list[str] | None = None,
        revalidation: list[str] | None = None,
    ) -> str:
        page = _journey_feature_page("F-001", "Document review", status, owner, [SOURCE], questions or [])
        frontmatter, body = _parse_markdown(page)
        apps = apps or ["backend", "web"]
        for key in ("design-tracks", "design-reaffirm"):
            frontmatter.pop(key, None)
        if tracks is not None:
            frontmatter.update(tracks.frontmatter())
        frontmatter["apps"] = apps
        frontmatter["revalidation"] = revalidation or []
        lines = criteria or [line for line in CRITERIA if all(app in apps for app in ("backend", "web")) or "web" not in line]
        frontmatter["criteria-high-water"] = len(lines)
        page = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        page = _replace_body_section_text(page, "App scope", "\n".join(f"- **{app}**: Deliver the review export in {app}." for app in apps))
        page = _replace_body_section_text(page, "Acceptance criteria", "\n".join(f"- [ ] {line}" for line in lines))
        page = _replace_body_section_text(page, "API surface", surface)
        if delivery is not None:
            page = _replace_body_section_text(page, "Delivery evidence", "\n".join([DELIVERY_HEADER.splitlines()[0], DELIVERY_HEADER.splitlines()[1], *delivery]))
        return page

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def seed_feature(self, status: str, owner: str, tracks: DesignTracks | None, **options) -> None:
        self.write(FEATURE, self.page(status, owner, tracks, **options))
        self.refresh_index(status, owner)

    def refresh_index(self, status: str, owner: str) -> None:
        _write_index_rows(self.root, [("F-001", "Document review", status, owner)])

    def frontmatter(self) -> dict:
        return _parse_markdown(self.read(FEATURE))[0]

    def tracks(self) -> DesignTracks | None:
        return parse_design_tracks(self.frontmatter())[0]

    # -- the board ---------------------------------------------------------------------------------------------

    def preview(self, skill: str, changes: list[dict[str, str]]) -> dict:
        return self.service.preview_skill(self.agent, skill, changes, None, _read_revisions(self.service, self.agent, skill, changes))

    def ready(self, skill: str, changes: list[dict[str, str]]) -> dict:
        preview = self.preview(skill, changes)
        self.assertEqual("ready", preview["classification"], f"{skill}: {[item for item in preview['checks'] if item['status'] != 'pass']}")
        self.assertTrue(preview["applicable"], f"{skill}: {preview['blockers']}")
        return preview

    def apply_as(self, preview: dict, approver=None) -> dict:
        receipt = apply_preview(self.service, self.agent, preview, str(uuid4()), approver=approver or self.human)
        self.assertEqual("applied", receipt["state"], receipt)
        self.refresh_index_from_page()
        return receipt

    def refresh_index_from_page(self) -> None:
        # The board keeps the index and the status board; nothing to do here, kept for symmetry with direct seeding.
        return None

    def run_skill(self, skill: str, changes: list[dict[str, str]], approver=None) -> dict:
        preview = self.ready(skill, changes)
        self.apply_as(preview, approver)
        return preview

    def rejected(self, skill: str, changes: list[dict[str, str]]) -> BoardError:
        with self.assertRaises(BoardError) as caught:
            self.preview(skill, changes)
        return caught.exception

    def blocked(self, skill: str, changes: list[dict[str, str]]) -> dict:
        preview = self.preview(skill, changes)
        self.assertNotEqual("ready", preview["classification"], preview["checks"])
        self.assertFalse(preview["applicable"])
        return preview

    @staticmethod
    def codes(preview: dict, *statuses: str) -> set[str]:
        return {item["code"] for item in preview["checks"] if item["status"] in (statuses or ("blocked", "unknown", "review"))}

    def start_design(self) -> None:
        preview = self.service.preview_transition(self.human, "F-001", "design-start", {"semantic_review_acknowledged": True})
        self.assertEqual("ready", preview["classification"], preview["checks"])
        self.assertEqual("applied", apply_preview(self.service, self.human, preview, str(uuid4()))["state"])

    def changes(self, content: str, *extra: tuple[str, str]) -> list[dict[str, str]]:
        return [{"path": FEATURE, "content": content}, *({"path": path, "content": text} for path, text in extra)]

    def in_design(self, tracks: DesignTracks | None = None) -> str:
        """Seed the feature in design with `tracks` (the initial ones by default) and return its page."""

        tracks = tracks or initial_design_tracks(["backend", "web"], self.service._model)
        self.seed_feature("in-design", "designer", tracks)
        return self.read(FEATURE)


class DesignStartTests(TrackCase):
    """F3: `design-start` writes the initial tracks."""

    def test_the_direct_pickup_writes_both_tracks_pending_for_a_scope_with_a_ui(self) -> None:
        self.start_design()
        self.assertEqual(("in-design", "designer"), (self.frontmatter()["status"], self.frontmatter()["owner"]))
        self.assertEqual(DesignTracks("pending", "pending"), self.tracks())
        self.assertEqual([], self.frontmatter()["design-reaffirm"])
        self.assertEqual(0, lint_wiki(self.root).error_count)

    def test_a_scope_with_no_ui_starts_with_the_ui_track_not_applicable(self) -> None:
        self.seed_feature("ready-for-design", "tech-lead", None, apps=["backend"], criteria=[CRITERIA[0]])
        self.start_design()
        tracks = self.tracks()
        self.assertEqual(("not-applicable", "pending", "No app in scope has a UI."), (tracks.ui, tracks.technical, tracks.ui_reason))

    def test_the_agent_proposal_of_the_pickup_must_write_exactly_the_initial_tracks(self) -> None:
        current = self.read(FEATURE)
        wrong = edit_frontmatter(current, {"status": "in-design", "design-tracks": {"ui": "done", "technical": "pending"}, "design-reaffirm": []})
        error = self.rejected("design-start", self.changes(wrong))
        self.assertEqual(("track_scope", 409), (error.code, error.status))
        right = edit_frontmatter(current, {"status": "in-design", **DesignTracks("pending", "pending").frontmatter()})
        preview = self.ready("design-start", self.changes(right))
        self.assertEqual("design-start", preview["action"])
        self.assertEqual({"all_of": ["designer"], "any_of": []}, preview["approval"]["required_roles"])

    def test_design_started_without_tracks_is_a_lint_error(self) -> None:
        self.write(FEATURE, self.page("in-design", "designer", None))
        self.refresh_index("in-design", "designer")
        self.assertIn("design-tracks-missing", {item.code for item in lint_wiki(self.root).diagnostics})
        broken = edit_frontmatter(self.page("in-design", "designer", DesignTracks("pending", "pending")), {"design-tracks": {"ui": "finished", "technical": "pending"}})
        self.write(FEATURE, broken)
        self.assertIn("design-tracks-invalid", {item.code for item in lint_wiki(self.root).diagnostics})
        reason = edit_frontmatter(self.page("in-design", "designer", DesignTracks("pending", "pending")), {"design-tracks": {"ui": "pending", "technical": "pending", "ui-reason": "x"}})
        self.write(FEATURE, reason)
        self.assertIn("design-tracks-invalid", {item.code for item in lint_wiki(self.root).diagnostics})


class UiTrackTests(TrackCase):
    """F4: `design-ui-done`."""

    def ui_done(self, content: str, **updates) -> str:
        return edit_frontmatter(content, {"status": "in-design", **updates})

    def test_it_settles_the_ui_track_with_design_pages_that_cover_the_apps_with_a_ui(self) -> None:
        base = self.read(FEATURE)
        proposed = self.ui_done(base, **DesignTracks("done", "pending").frontmatter())
        proposed = _replace_body_section_text(proposed, "Design", "The review panel design is in [the design page](../design/F-001-document-review.md).")
        preview = self.run_skill("design-ui-done", self.changes(proposed, (DESIGN, designs_page())))
        self.assertEqual("design-ui-done", preview["action"])
        # The implicit pickup started design and wrote the initial tracks; the UI track is `done`.
        self.assertEqual(("in-design", "designer"), (self.frontmatter()["status"], self.frontmatter()["owner"]))
        self.assertEqual(DesignTracks("done", "pending"), self.tracks())
        self.assertEqual(0, lint_wiki(self.root).error_count, [item.message for item in lint_wiki(self.root).diagnostics if item.severity == "error"])

    def test_it_is_approved_by_the_designer_and_not_by_the_tech_lead(self) -> None:
        proposed = self.ui_done(self.read(FEATURE), **DesignTracks("done", "pending").frontmatter())
        preview = self.ready("design-ui-done", self.changes(proposed, (DESIGN, designs_page())))
        self.assertEqual({"all_of": ["designer"], "any_of": []}, preview["approval"]["required_roles"])
        tech_lead = human_with_roles(self.service, "Theo", "tech-lead")
        with self.assertRaises(BoardError) as caught:
            self.service.apply(tech_lead, preview["preview_id"], str(uuid4()), "unreviewed", True)
        self.assertEqual("role_required", caught.exception.code)
        designer = human_with_roles(self.service, "Dana", "designer")
        self.assertEqual("applied", apply_preview(self.service, designer, preview, str(uuid4()))["state"])

    def test_design_pages_must_cover_every_app_with_a_ui(self) -> None:
        proposed = self.ui_done(self.read(FEATURE), **DesignTracks("done", "pending").frontmatter())
        # No design page at all, and a page that lists the wrong app.
        self.assertIn("design-coverage-incomplete", self.codes(self.blocked("design-ui-done", self.changes(proposed))))
        self.assertIn("design-coverage-incomplete", self.codes(self.blocked("design-ui-done", self.changes(proposed, (DESIGN, designs_page("[backend]"))))))

    def test_an_exemption_needs_a_reason_and_a_pending_track_is_a_blocker(self) -> None:
        base = self.read(FEATURE)
        without_reason = self.ui_done(base, **DesignTracks("not-applicable", "pending", " ", None).frontmatter())
        self.assertIn("ui-exemption-reason-required", self.codes(self.blocked("design-ui-done", self.changes(without_reason))))
        with_reason = self.ui_done(base, **DesignTracks("not-applicable", "pending", "The export reuses the existing review panel unchanged.", None).frontmatter())
        self.run_skill("design-ui-done", self.changes(with_reason))
        self.assertEqual("not-applicable", self.tracks().ui)
        # A proposal that leaves the track pending settles nothing.
        self.in_design()
        pending = self.ui_done(self.read(FEATURE), **DesignTracks("pending", "pending").frontmatter())
        self.assertIn("design-tracks-incomplete", self.codes(self.blocked("design-ui-done", self.changes(pending, (DESIGN, designs_page())))))

    def test_an_app_with_an_unknown_ui_needs_the_designers_explicit_exemption(self) -> None:
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["apps"].append(
            {"id": "tool", "name": "tool", "stack": "other", "repository": "workspace", "path": "tools/tool", "capabilities": {"has-ui": "unknown", "serves-api": False}}
        )
        (self.root / "tools" / "tool").mkdir(parents=True)
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        self.service.close()
        self.start()
        self.seed_feature("ready-for-design", "designer", None, apps=["tool"], criteria=["AC-1 [tool] A tool command prints the export."], surface="None.")
        proposed = edit_frontmatter(self.read(FEATURE), {"status": "in-design", **initial_design_tracks(["tool"], self.service._model).frontmatter()})
        self.assertEqual("pending", parse_design_tracks(_parse_markdown(proposed)[0])[0].ui)
        exempt = edit_frontmatter(proposed, DesignTracks("not-applicable", "pending", "The tool prints text and has no screen.", None).frontmatter())
        self.assertEqual("ready", self.preview("design-ui-done", self.changes(exempt))["classification"])

    def test_it_writes_the_pages_of_its_own_track_only(self) -> None:
        proposed = self.ui_done(self.read(FEATURE), **DesignTracks("done", "pending").frontmatter())
        error = self.rejected("design-ui-done", self.changes(proposed, (DESIGN, designs_page()), (TECH, technical_page())))
        self.assertEqual("write_path_unavailable", error.code)
        other = self.ui_done(self.read(FEATURE), **DesignTracks("done", "done").frontmatter())
        error = self.rejected("design-ui-done", self.changes(other, (DESIGN, designs_page())))
        self.assertEqual("track_scope", error.code)

    def test_it_is_open_only_while_the_track_is_pending_or_awaits_reaffirmation(self) -> None:
        self.in_design(DesignTracks("done", "pending"))
        self.write(DESIGN, designs_page())
        proposed = self.ui_done(self.read(FEATURE), **DesignTracks("done", "pending").frontmatter())
        error = self.rejected("design-ui-done", self.changes(proposed))
        self.assertEqual(("design_track_not_open", 409), (error.code, error.status))


class TechnicalTrackTests(TrackCase):
    """F5: `tech-design-done`, the technical design page and the API contract."""

    def tech_done(self, content: str, **updates) -> str:
        return edit_frontmatter(content, {"status": "in-design", **updates})

    def settle(self, *, with_contract: bool = True) -> dict:
        proposed = self.tech_done(self.read(FEATURE), **DesignTracks("pending", "done").frontmatter())
        changes = self.changes(proposed, (TECH, technical_page()), *([(CONTRACT, contract_page())] if with_contract else []))
        return self.run_skill("tech-design-done", changes)

    def test_it_authors_the_contract_at_agreed_version_one_and_settles_the_track(self) -> None:
        preview = self.settle()
        self.assertEqual("tech-design-done", preview["action"])
        self.assertEqual({"all_of": ["tech-lead"], "any_of": []}, preview["approval"]["required_roles"])
        contract_fm = _parse_markdown(self.read(CONTRACT))[0]
        self.assertEqual(("F-001", 1, "agreed"), (contract_fm["feature-id"], contract_fm["version"], contract_fm["status"]))
        self.assertEqual("done", self.tracks().technical)
        self.assertEqual(0, lint_wiki(self.root).error_count, [item.message for item in lint_wiki(self.root).diagnostics if item.severity == "error"])

    def test_the_index_lists_the_technical_design_page_in_its_own_group(self) -> None:
        self.settle()
        index = self.read("knowledge/wiki/index.md")
        self.assertIn("## Technical design", index)
        self.assertIn("(technical-design/F-001-document-review.md)", index)

    def test_it_needs_a_complete_page_whose_test_strategy_names_every_criterion(self) -> None:
        proposed = self.tech_done(self.read(FEATURE), **DesignTracks("pending", "done").frontmatter())
        missing_ac3 = technical_page(strategy=["| AC-1 | backend | automated | integration | |", "| AC-2 | web | manual | end-to-end | |"])
        preview = self.blocked("tech-design-done", self.changes(proposed, (TECH, missing_ac3), (CONTRACT, contract_page())))
        self.assertIn("test-strategy-incomplete", self.codes(preview))
        no_impact = technical_page(impact=["| backend | reviews | A new export service |"])
        preview = self.blocked("tech-design-done", self.changes(proposed, (TECH, no_impact), (CONTRACT, contract_page())))
        self.assertIn("technical-design-incomplete", self.codes(preview))
        preview = self.blocked("tech-design-done", self.changes(proposed, (CONTRACT, contract_page())))
        self.assertIn("technical-design-incomplete", self.codes(preview))

    def test_api_work_needs_the_contract_and_an_app_that_serves_an_api(self) -> None:
        proposed = self.tech_done(self.read(FEATURE), **DesignTracks("pending", "done").frontmatter())
        error = self.rejected("tech-design-done", self.changes(proposed, (TECH, technical_page())))
        self.assertEqual(("api_contract_required", 409), (error.code, error.status))
        self.seed_feature("ready-for-design", "designer", None, apps=["web"], criteria=[CRITERIA[1]])
        web_only = edit_frontmatter(self.read(FEATURE), {"status": "in-design", **DesignTracks("pending", "done").frontmatter()})
        web_page = technical_page(
            apps="[web]",
            strategy=["| AC-2 | web | manual | end-to-end | |"],
            impact=["| web | review panel | A download action |"],
        )
        error = self.rejected("tech-design-done", self.changes(web_only, (TECH, web_page)))
        self.assertEqual(("api_surface_without_api_app", 409), (error.code, error.status))

    def test_a_contract_is_created_agreed_and_only_when_api_work_is_declared(self) -> None:
        proposed = self.tech_done(self.read(FEATURE), **DesignTracks("pending", "done").frontmatter())
        draft = self.rejected("tech-design-done", self.changes(proposed, (TECH, technical_page()), (CONTRACT, contract_page(status="draft"))))
        self.assertEqual(("api_contract_initial_status", 409), (draft.code, draft.status))
        second = self.rejected("tech-design-done", self.changes(proposed, (TECH, technical_page()), (CONTRACT, contract_page(version=2))))
        self.assertEqual("api_contract_initial_status", second.code)
        elsewhere = self.rejected("tech-design-done", self.changes(proposed, (TECH, technical_page()), (CONTRACT, contract_page(feature_id="F-002"))))
        self.assertEqual("feature_context_mismatch", elsewhere.code)
        self.seed_feature("ready-for-design", "designer", None, surface="None.")
        proposed = self.tech_done(self.read(FEATURE), **DesignTracks("pending", "done").frontmatter())
        error = self.rejected("tech-design-done", self.changes(proposed, (TECH, technical_page()), (CONTRACT, contract_page())))
        self.assertEqual(("api_contract_not_applicable", 409), (error.code, error.status))

    def test_not_applicable_needs_a_reason_and_no_api_work(self) -> None:
        reasoned = self.tech_done(self.read(FEATURE), **DesignTracks("pending", "not-applicable", None, "The feature changes no architecture.").frontmatter())
        self.assertIn("technical-track-required", self.codes(self.blocked("tech-design-done", self.changes(reasoned))))
        self.seed_feature("ready-for-design", "designer", None, surface="None.")
        reasoned = self.tech_done(self.read(FEATURE), **DesignTracks("pending", "not-applicable", None, "The feature changes no architecture.").frontmatter())
        self.run_skill("tech-design-done", self.changes(reasoned))
        self.assertEqual("not-applicable", self.tracks().technical)
        self.seed_feature("ready-for-design", "designer", None, surface="None.")
        blank = self.tech_done(self.read(FEATURE), **DesignTracks("pending", "not-applicable", None, "  ").frontmatter())
        self.assertIn("technical-track-required", self.codes(self.blocked("tech-design-done", self.changes(blank))))

    def test_a_contract_revision_raises_the_version_and_changes_the_digest(self) -> None:
        self.settle()
        before = self.read(CONTRACT)
        old_fm, old_body = _parse_markdown(before)
        # design-clarify changed the technical design page: the technical track returned to pending and the UI track awaits reaffirmation.
        self.write(DESIGN, designs_page())
        self.seed_feature("in-design", "designer", DesignTracks("done", "pending", None, None, ("ui",)))
        self.refresh_index("in-design", "designer")
        revised_body = contract_page(version=2, errors="401, 403, 404")
        settled = edit_frontmatter(self.read(FEATURE), DesignTracks("done", "done", None, None, ("ui",)).frontmatter())
        # The revision without the version bump is refused.
        error = self.rejected("tech-design-done", self.changes(settled, (TECH, technical_page(summary="The export runs in a worker.")), (CONTRACT, contract_page(version=1, errors="401, 403, 404"))))
        self.assertEqual(("contract_revision_required", 409), (error.code, error.status))
        self.run_skill("tech-design-done", self.changes(settled, (TECH, technical_page(summary="The export runs in a worker.")), (CONTRACT, revised_body)))
        new_fm, new_body = _parse_markdown(self.read(CONTRACT))
        self.assertEqual(2, new_fm["version"])
        self.assertNotEqual(contract_digest("F-001", 1, old_body), contract_digest("F-001", 2, new_body))
        self.assertEqual(["ui"], self.frontmatter()["design-reaffirm"])

    def test_a_revision_is_refused_while_another_feature_that_links_the_contract_is_in_development(self) -> None:
        self.settle()
        before = self.read(CONTRACT)
        other = _journey_feature_page("F-002", "Other feature", "in-dev", "dev", [SOURCE], [])
        other = _replace_body_section_text(other, "API surface", "See [the shared contract](../api-contracts/F-001.md).")
        other = edit_frontmatter(other, {"apps": ["backend"], "criteria-high-water": 1, **DesignTracks("not-applicable", "not-applicable", "No UI.", "No design.").frontmatter()})
        other = _replace_body_section_text(other, "Acceptance criteria", "- [ ] AC-1 [backend] The other feature exports too.")
        other = _replace_body_section_text(other, "App scope", "- **backend**: Deliver the other export in backend.")
        self.write("knowledge/wiki/features/F-002-other-feature.md", other)
        _write_index_rows(self.root, [("F-001", "Document review", "in-design", "designer"), ("F-002", "Other feature", "in-dev", "dev")])
        self.seed_feature("in-design", "designer", DesignTracks("done", "pending", None, None, ("ui",)))
        _write_index_rows(self.root, [("F-001", "Document review", "in-design", "designer"), ("F-002", "Other feature", "in-dev", "dev")])
        self.write(DESIGN, designs_page())
        proposed = edit_frontmatter(self.read(FEATURE), DesignTracks("done", "done", None, None, ("ui",)).frontmatter())
        error = self.rejected("tech-design-done", self.changes(proposed, (TECH, technical_page()), (CONTRACT, contract_page(version=2, errors="401, 403, 404"))))
        self.assertEqual(("shared_contract_in_use", 409), (error.code, error.status))
        self.assertEqual(["F-002"], error.details["consumers"])
        self.assertEqual(before, self.read(CONTRACT))

    def test_the_digest_ignores_front_matter_other_than_the_version(self) -> None:
        body = _parse_markdown(contract_page())[1]
        implemented_body = _parse_markdown(contract_page(status="implemented"))[1]
        self.assertEqual(contract_digest("F-001", 1, body), contract_digest("F-001", 1, implemented_body))
        self.assertNotEqual(contract_digest("F-001", 1, body), contract_digest("F-001", 2, body))
        spaced = body.replace("creates a review export", "creates   a review\nexport")
        self.assertEqual(contract_digest("F-001", 1, body), contract_digest("F-001", 1, spaced))
        self.assertNotEqual(contract_digest("F-001", 1, body), contract_digest("F-001", 1, body.replace("401", "402")))
        self.assertEqual("F-001@v1:" + contract_digest("F-001", 1, body), contract_citation("F-001", 1, body))
        self.assertEqual(["Endpoints", "Data models", "Authentication requirements", "Notes"], [heading for heading, _text in contract_sections(body)])

    def test_the_board_reports_the_citation_beside_the_contract_page(self) -> None:
        self.settle()
        page = self.service.read_workspace(self.agent, [CONTRACT])["files"][0]
        fm, body = _parse_markdown(self.read(CONTRACT))
        self.assertEqual(contract_citation("F-001", 1, body), page["annotations"]["contract"]["citation"])
        self.assertEqual(1, page["annotations"]["contract"]["version"])


class HandoffTests(TrackCase):
    """F6: `design-handoff` with its track checks."""

    def handoff_changes(self, content: str, *, with_pages: bool = False, tracks: DesignTracks | None = None, status: str = "ready-for-dev") -> list[dict[str, str]]:
        updates = {"status": status, "owner": "dev", **(tracks.frontmatter() if tracks else {}), "revalidation": []}
        proposed = edit_frontmatter(content, updates)
        extra = [(BACKEND_REQ, requirement_page("backend")), (WEB_REQ, requirement_page("web"))]
        if with_pages:
            extra += [(DESIGN, designs_page()), (TECH, technical_page()), (CONTRACT, contract_page())]
        return self.changes(proposed, *extra)

    def settled_pages(self) -> None:
        self.write(DESIGN, designs_page())
        self.write(TECH, technical_page())
        self.write(CONTRACT, contract_page())
        self.refresh_index("in-design", "designer")

    def test_it_completes_both_tracks_in_one_confirmation_for_the_designer_and_the_tech_lead(self) -> None:
        self.in_design()
        changes = self.handoff_changes(self.read(FEATURE), with_pages=True, tracks=DesignTracks("done", "done"))
        preview = self.ready("design-handoff", changes)
        self.assertEqual(["ui", "technical"], preview["completes"])
        self.assertEqual({"designer", "tech-lead"}, set(preview["approval"]["required_roles"]["all_of"]))
        # The designer alone cannot approve it (CONTRACTS 10.3 case 9).
        designer = human_with_roles(self.service, "Dana", "designer")
        with self.assertRaises(BoardError) as caught:
            self.service.apply(designer, preview["preview_id"], str(uuid4()), "unreviewed", True)
        self.assertEqual("role_required", caught.exception.code)
        both = human_with_roles(self.service, "Dana and Theo", "designer,tech-lead")
        self.assertEqual("applied", apply_preview(self.service, both, preview, str(uuid4()))["state"])
        self.assertEqual(("ready-for-dev", "dev"), (self.frontmatter()["status"], self.frontmatter()["owner"]))
        self.assertEqual(DesignTracks("done", "done"), self.tracks())
        self.assertEqual(0, lint_wiki(self.root).error_count, [item.message for item in lint_wiki(self.root).diagnostics if item.severity == "error"])

    def test_it_after_the_two_track_actions_needs_only_the_design_owner(self) -> None:
        self.in_design(DesignTracks("done", "done"))
        self.settled_pages()
        preview = self.ready("design-handoff", self.handoff_changes(self.read(FEATURE)))
        self.assertEqual([], preview["completes"])
        self.assertEqual({"all_of": ["designer"], "any_of": []}, preview["approval"]["required_roles"])

    def test_a_pending_track_or_a_pending_reaffirmation_blocks_the_handoff(self) -> None:
        self.in_design(DesignTracks("done", "pending"))
        self.write(DESIGN, designs_page())
        blocked = self.blocked("design-handoff", self.handoff_changes(self.read(FEATURE)))
        self.assertIn("design-tracks-incomplete", self.codes(blocked))
        self.in_design(DesignTracks("done", "done", None, None, ("ui",)))
        self.settled_pages()
        blocked = self.blocked("design-handoff", self.handoff_changes(self.read(FEATURE)))
        self.assertIn("design-reaffirm-pending", self.codes(blocked))

    def test_it_writes_the_pages_of_a_track_only_when_it_completes_the_track(self) -> None:
        self.in_design(DesignTracks("done", "pending"))
        self.write(DESIGN, designs_page())
        # The contract of the technical track without completing the technical track (CONTRACTS 10.3 case 25).
        changes = self.handoff_changes(self.read(FEATURE), tracks=DesignTracks("done", "pending"))
        changes.append({"path": CONTRACT, "content": contract_page()})
        error = self.rejected("design-handoff", changes)
        self.assertEqual(("lifecycle_write_scope", 403), (error.code, error.status))

    def test_it_may_settle_the_technical_track_with_the_tech_lead_while_the_ui_track_was_settled_before(self) -> None:
        self.in_design(DesignTracks("done", "pending"))
        self.write(DESIGN, designs_page())
        changes = self.handoff_changes(self.read(FEATURE), tracks=DesignTracks("done", "done"))
        changes += [{"path": TECH, "content": technical_page()}, {"path": CONTRACT, "content": contract_page()}]
        preview = self.ready("design-handoff", changes)
        self.assertEqual(["technical"], preview["completes"])
        self.assertEqual({"designer", "tech-lead"}, set(preview["approval"]["required_roles"]["all_of"]))

    def test_the_requirement_pages_follow_the_handoff_rules(self) -> None:
        self.in_design(DesignTracks("done", "done"))
        self.settled_pages()
        self.write(BACKEND_REQ, requirement_page("backend", "done"))
        self.write(WEB_REQ, requirement_page("web", "in-progress"))
        base = self.read(FEATURE)
        # A `done` page stays; the page that was lowered to `in-progress` comes back `pending`.
        proposed = edit_frontmatter(base, {"status": "ready-for-dev", "owner": "dev"})
        web_pending = requirement_page("web", "pending", "Download the export from the review panel.")
        error = self.rejected("design-handoff", self.changes(proposed, (BACKEND_REQ, requirement_page("backend", "done", "Store the export in a changed way.")), (WEB_REQ, web_pending)))
        self.assertEqual("requirement_body_change", error.code)
        error = self.rejected("design-handoff", self.changes(proposed, (BACKEND_REQ, requirement_page("backend", "done"))))
        self.assertEqual("requirements_incomplete", error.code)
        error = self.rejected("design-handoff", self.changes(proposed, (WEB_REQ, requirement_page("web", "in-progress"))))
        self.assertEqual("requirements_incomplete", error.code)
        ready = self.ready("design-handoff", self.changes(proposed, (WEB_REQ, requirement_page("web", "pending", "Download the export from the review panel."))))
        self.assertEqual("design-handoff", ready["action"])

    def test_the_feature_without_any_requirement_page_is_refused(self) -> None:
        self.in_design(DesignTracks("done", "done"))
        self.settled_pages()
        proposed = edit_frontmatter(self.read(FEATURE), {"status": "ready-for-dev", "owner": "dev"})
        error = self.rejected("design-handoff", self.changes(proposed, (BACKEND_REQ, requirement_page("backend"))))
        self.assertEqual("requirements_incomplete", error.code)


class CrossTrackTests(TrackCase):
    """CONTRACTS 3.3: a change to a settled track's page resets it; the other track is reaffirmed."""

    def clarify_changes(self, feature: str, page_path: str, page: str) -> list[dict[str, str]]:
        return self.changes(feature, (page_path, page))

    def answered(self, content: str, answer: str = "Only reviewers who own the review may export it.") -> str:
        return content.replace("| 3 | Where should the next steps appear? | designer | open |", f"| 3 | Where should the next steps appear? | designer | resolved: {answer} |")

    def setUp(self) -> None:
        super().setUp()
        self.write(DESIGN, designs_page())
        self.write(TECH, technical_page())
        self.write(CONTRACT, contract_page())
        question = ["| 3 | Where should the next steps appear? | designer | open |"]
        self.seed_feature("in-design", "designer", DesignTracks("done", "done"), questions=question)
        _write_index_rows(self.root, [("F-001", "Document review", "in-design", "designer")])
        self.service.close()
        self.start()

    def test_a_technical_page_change_without_the_reset_is_refused_and_with_it_the_ui_track_awaits_reaffirmation(self) -> None:
        feature = self.answered(self.read(FEATURE))
        tech = technical_page(summary="The export is generated for the reviewer: Only reviewers who own the review may export it.")
        error = self.rejected("design-clarify", self.clarify_changes(feature, TECH, tech))
        self.assertEqual(("track_reset_required", 409), (error.code, error.status))
        reset = edit_frontmatter(feature, DesignTracks("done", "pending", None, None, ("ui",)).frontmatter())
        self.run_skill("design-clarify", self.clarify_changes(reset, TECH, tech))
        self.assertEqual(DesignTracks("done", "pending", None, None, ("ui",)), self.tracks())

    def test_a_design_page_change_resets_the_ui_track_and_lists_the_technical_track(self) -> None:
        feature = self.answered(self.read(FEATURE))
        design = designs_page().replace("The page shows pending and completed reviews.", "The page shows pending and completed reviews: Only reviewers who own the review may export it.")
        reset = edit_frontmatter(feature, DesignTracks("pending", "done", None, None, ("technical",)).frontmatter())
        self.run_skill("design-clarify", self.clarify_changes(reset, DESIGN, design))
        self.assertEqual(DesignTracks("pending", "done", None, None, ("technical",)), self.tracks())

    def test_a_clarify_that_changes_no_page_leaves_the_tracks_alone(self) -> None:
        feature = self.answered(self.read(FEATURE))
        error = self.rejected("design-clarify", self.changes(edit_frontmatter(feature, DesignTracks("pending", "done").frontmatter())))
        self.assertEqual("track_scope", error.code)

    def test_the_other_track_action_with_no_page_change_removes_its_entry(self) -> None:
        self.seed_feature("in-design", "designer", DesignTracks("done", "pending", None, None, ("ui",)))
        self.write(DESIGN, designs_page())
        proposed = edit_frontmatter(self.read(FEATURE), {"status": "in-design", **DesignTracks("done", "pending").frontmatter()})
        self.run_skill("design-ui-done", self.changes(proposed))
        self.assertEqual(DesignTracks("done", "pending"), self.tracks())

    def test_a_page_of_a_track_cannot_change_from_ready_for_dev_on(self) -> None:
        self.seed_feature("ready-for-dev", "dev", DesignTracks("done", "done"), questions=["| 3 | Where should the next steps appear? | designer | open |"])
        _write_index_rows(self.root, [("F-001", "Document review", "ready-for-dev", "dev")])
        feature = self.answered(self.read(FEATURE))
        design = designs_page().replace("The page shows pending and completed reviews.", "The page shows pending and completed reviews: Only reviewers who own the review may export it.")
        error = self.rejected("design-clarify", self.clarify_changes(feature, DESIGN, design))
        self.assertEqual(("track_page_locked", 409), (error.code, error.status))

    def test_a_scope_change_in_design_sends_every_settled_track_back(self) -> None:
        self.write("knowledge/wiki/app-requirements/.keep.md", "x") if False else None
        feature = self.read(FEATURE)
        frontmatter, body = _parse_markdown(feature)
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["apps"].append({"id": "worker", "name": "worker", "stack": "other", "repository": "workspace", "path": "tools/worker", "capabilities": {"has-ui": False, "serves-api": False}})
        (self.root / "tools" / "worker").mkdir(parents=True)
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        self.service.close()
        self.start()
        frontmatter["apps"] = ["backend", "web", "worker"]
        frontmatter["criteria-high-water"] = 4
        edited = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        edited = _replace_body_section_text(edited, "App scope", "\n".join(f"- **{app}**: Deliver the review export in {app}." for app in frontmatter["apps"]))
        edited = _replace_body_section_text(edited, "Acceptance criteria", "\n".join(f"- [ ] {line}" for line in [*CRITERIA, "AC-4 [worker] The worker prepares the export data."]))
        requirement = requirement_page("worker")
        unchanged = self.rejected("feature-scope", [{"path": FEATURE, "content": edited}, {"path": "knowledge/wiki/app-requirements/F-001-worker.md", "content": requirement}])
        self.assertEqual(("track_reset_required", 409), (unchanged.code, unchanged.status))
        reset = edit_frontmatter(edited, DesignTracks("pending", "pending").frontmatter())
        changes = [{"path": FEATURE, "content": reset}, {"path": "knowledge/wiki/app-requirements/F-001-worker.md", "content": requirement}]
        preview = self.service.preview_skill(self.agent, "feature-scope", changes, None, _read_revisions(self.service, self.agent, "feature-scope", changes))
        self.assertEqual("ready", preview["classification"], preview["checks"])
        self.assertEqual("applied", apply_preview(self.service, self.agent, preview, str(uuid4()))["state"])
        self.assertEqual(DesignTracks("pending", "pending"), self.tracks())


class IngestTests(TrackCase):
    """CONTRACTS 6.3: ingest writes a technical design page while the technical track is pending or absent."""

    def ingest(self, content: str) -> list[dict[str, str]]:
        folder = "2026-10-07-export-design-notes"
        pending = self.root / "knowledge" / "intake" / "pending" / folder
        pending.mkdir(parents=True, exist_ok=True)
        (pending / "notes.md").write_text("# Export design notes\n\nThe export runs in the backend.\n", encoding="utf-8")
        processed = f"knowledge/intake/processed/{folder}"
        manifest = f"# Processed intake\n\nPages: {TECH}\n"
        return [{"path": TECH, "content": content}, {"path": f"{processed}/MANIFEST.md", "content": manifest}], folder

    def propose(self, content: str):
        changes, folder = self.ingest(content)
        moves = [{"source": f"knowledge/intake/pending/{folder}", "destination": f"knowledge/intake/processed/{folder}"}]
        revisions = _read_revisions(self.service, self.agent, "ingest", changes, moves)
        return self.service.preview_skill(self.agent, "ingest", changes, moves, revisions)

    def test_a_technical_design_page_is_ingested_while_the_track_is_pending(self) -> None:
        self.in_design()
        preview = self.propose(technical_page())
        self.assertEqual("ready", preview["classification"], preview["checks"])
        self.assertIsNone(preview["action"])

    def test_it_is_refused_when_the_track_is_settled_or_the_feature_is_past_design(self) -> None:
        self.in_design(DesignTracks("pending", "done"))
        with self.assertRaises(BoardError) as caught:
            self.propose(technical_page())
        self.assertEqual("track_reset_required", caught.exception.code)
        self.seed_feature("ready-for-dev", "dev", DesignTracks("done", "done"))
        with self.assertRaises(BoardError) as caught:
            self.propose(technical_page())
        self.assertEqual("track_page_locked", caught.exception.code)


class DevReturnTests(TrackCase):
    """F10 and F11: the returns from implementation."""

    BACKEND_ROW = "| backend | `build:backend#7` | {contract} | Pull request 7 | CI run 7: 31 tests passed | checked |"

    def settled_pages(self) -> None:
        self.write(DESIGN, designs_page())
        self.write(TECH, technical_page())
        self.write(CONTRACT, contract_page())

    def in_dev(self, *, delivered: bool = False, status: str = "in-dev", tracks: DesignTracks | None = None) -> None:
        self.settled_pages()
        body = _parse_markdown(contract_page())[1]
        row = self.BACKEND_ROW.format(contract=contract_citation("F-001", 1, body))
        self.seed_feature(status, "dev", tracks or DesignTracks("done", "done"), delivery=[row] if delivered else None)
        self.write(BACKEND_REQ, requirement_page("backend", "done" if delivered else "pending"))
        self.write(WEB_REQ, requirement_page("web"))
        _write_index_rows(self.root, [("F-001", "Document review", status, "dev")])
        self.service.close()
        self.start()

    def entry(self, action: str, *, tracks: str, archived: str = "none", invalidations: str = "No requirement or API page is invalidated.", apps: str = "backend, web") -> str:
        archive = f"- Archived evidence:\n  {archived}" if archived != "none" else "- Archived evidence: none"
        return "\n".join(
            [
                f"### {CHECK_DATE.isoformat()} - {action}",
                "- Reason: The specification of the export changed after the design.",
                f"- Affected apps: {apps}",
                "- Participants: none",
                f"- Affected tracks: {tracks}",
                archive,
                "- Reaffirmed evidence: none",
                f"- Requirement/API invalidations: {invalidations}",
                "- Linked bugs: none",
            ]
        )

    def returned(self, route: str, *, tracks: DesignTracks | None, affected: str, archived: str = "none", invalidations: str = "No requirement or API page is invalidated.", extra=()) -> list[dict[str, str]]:
        action = "dev-return-spec" if route == "specified" else "dev-return-design"
        content = self.read(FEATURE)
        frontmatter, body = _parse_markdown(content)
        domains = ["specification", "design", "technical-design"] if route == "specified" else ["design", "technical-design"]
        frontmatter.update(
            {
                "status": "specified" if route == "specified" else "in-design",
                "owner": "po" if route == "specified" else "designer",
                "revalidation": domains,
                "app-revalidation": {"backend": ["implementation", "tests", "qa", "release"], "web": ["implementation", "tests", "qa", "release"]},
            }
        )
        for key in ("design-tracks", "design-reaffirm"):
            frontmatter.pop(key, None)
        if tracks is not None:
            frontmatter.update(tracks.frontmatter())
        page = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        page = _replace_body_section_text(page, "Delivery evidence", "\n".join([DELIVERY_HEADER.splitlines()[0], DELIVERY_HEADER.splitlines()[1]]))
        page = _replace_body_section_text(page, "Evidence history", self.entry(action, tracks=affected, archived=archived, invalidations=invalidations))
        return self.changes(page, *extra)

    def test_a_return_to_specified_from_ready_for_dev_removes_the_tracks_and_sets_every_domain(self) -> None:
        self.in_dev(status="ready-for-dev")
        preview = self.ready("feature-reopen", self.returned("specified", tracks=None, affected="ui, technical"))
        self.assertEqual("dev-return-spec", preview["action"])
        self.assertEqual({"all_of": ["dev"], "any_of": []}, preview["approval"]["required_roles"])
        self.apply_as(preview)
        frontmatter = self.frontmatter()
        self.assertEqual(("specified", "po"), (frontmatter["status"], frontmatter["owner"]))
        self.assertNotIn("design-tracks", frontmatter)
        self.assertNotIn("design-reaffirm", frontmatter)
        self.assertEqual(["specification", "design", "technical-design"], frontmatter["revalidation"])
        self.assertEqual(0, lint_wiki(self.root).error_count, [item.message for item in lint_wiki(self.root).diagnostics if item.severity == "error"])

    def test_a_return_to_design_from_in_dev_archives_every_row_and_resets_the_affected_track(self) -> None:
        self.in_dev(delivered=True, status="ready-for-qa")
        # `ready-for-qa` is not a source of the return from implementation.
        error = self.rejected("feature-reopen", self.returned("in-design", tracks=DesignTracks("done", "pending", None, None, ("ui",)), affected="technical"))
        self.assertIn(error.code, {"lifecycle_action_required"})
        self.in_dev()
        body = _parse_markdown(contract_page())[1]
        archived = self.BACKEND_ROW.format(contract=contract_citation("F-001", 1, body))
        self.assertEqual([], list(read_feature_evidence(_parse_markdown(self.read(FEATURE))[1]).delivery))
        changes = self.returned("in-design", tracks=DesignTracks("done", "pending", None, None, ("ui",)), affected="technical")
        preview = self.ready("feature-reopen", changes)
        self.assertEqual("dev-return-design", preview["action"])
        self.apply_as(preview)
        self.assertEqual(DesignTracks("done", "pending", None, None, ("ui",)), self.tracks())
        self.assertEqual(["design", "technical-design"], self.frontmatter()["revalidation"])
        self.assertNotEqual("", archived)

    def test_the_tracks_must_match_the_affected_tracks_of_the_entry(self) -> None:
        self.in_dev()
        wrong = self.returned("in-design", tracks=DesignTracks("pending", "pending"), affected="technical")
        error = self.rejected("feature-reopen", wrong)
        self.assertEqual("track_reset_required", error.code)
        none = self.returned("in-design", tracks=DesignTracks("done", "done"), affected="none")
        self.assertEqual("impact_review_required", self.rejected("feature-reopen", none).code)

    def test_a_return_with_delivered_evidence_archives_the_row_verbatim(self) -> None:
        self.in_dev(delivered=True)
        # One app delivered and one not: the status is the minimum, `in-dev`.
        body = _parse_markdown(contract_page())[1]
        row = self.BACKEND_ROW.format(contract=contract_citation("F-001", 1, body))
        archived = "| Delivery evidence " + row
        wrong = self.returned("in-design", tracks=DesignTracks("done", "pending", None, None, ("ui",)), affected="technical")
        self.assertEqual("evidence_not_archived", self.rejected("feature-reopen", wrong).code)
        changes = self.returned(
            "in-design",
            tracks=DesignTracks("done", "pending", None, None, ("ui",)),
            affected="technical",
            archived=archived,
            invalidations=f"{BACKEND_REQ}: done -> in-progress",
            extra=((BACKEND_REQ, requirement_page("backend", "in-progress")),),
        )
        preview = self.ready("feature-reopen", changes)
        self.apply_as(preview)
        self.assertEqual("in-progress", _parse_markdown(self.read(BACKEND_REQ))[0]["status"])
        self.assertIn("Delivery evidence", self.read(FEATURE).split("## Evidence history", 1)[1])
        self.assertEqual(0, lint_wiki(self.root).error_count, [item.message for item in lint_wiki(self.root).diagnostics if item.severity == "error"])

    def test_a_partly_released_feature_cannot_return_to_spec_or_design(self) -> None:
        self.in_dev(delivered=True)
        page = self.read(FEATURE)
        release = "| backend | production | `build:backend#7` | release-1 | released | [REL-001](https://records.example/REL-001) | checked |"
        header = "| App | Target | Version | Attempt | Outcome | Record | Basis |\n|---|---|---|---|---|---|---|"
        qa = (
            "| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |\n|---|---|---|---|---|---|---|---|---|\n"
        )
        page = _replace_body_section_text(page, "Release", f"{header}\n{release}")
        self.write(FEATURE, page)
        for route, tracks, affected in (("specified", None, "ui, technical"), ("in-design", DesignTracks("pending", "done", None, None, ()), "ui")):
            with self.subTest(route=route):
                error = self.rejected("feature-reopen", self.returned(route, tracks=tracks, affected=affected))
                self.assertEqual(("partial_release_requires_new_feature", 409), (error.code, error.status))

    def test_the_return_is_listed_as_available_with_the_dev_role(self) -> None:
        discovered = {item["action"]: item for item in self.service.discover(self.agent)["capability"]["actions"]}
        for action in ("dev-return-spec", "dev-return-design", "design-ui-done", "tech-design-done"):
            with self.subTest(action=action):
                self.assertTrue(discovered[action]["available"])
        self.assertEqual({"all_of": ["dev"], "any_of": []}, discovered["dev-return-spec"]["required_roles"])
        self.assertEqual({"all_of": ["designer"], "any_of": []}, discovered["design-ui-done"]["required_roles"])
        self.assertEqual({"all_of": ["tech-lead"], "any_of": []}, discovered["tech-design-done"]["required_roles"])


class DeliveryBindingTests(TrackCase):
    """CONTRACTS 3.4: the Contract cell of the delivery evidence."""

    def at_dev(self, tracks: DesignTracks | None = None) -> str:
        self.write(DESIGN, designs_page())
        self.write(TECH, technical_page())
        self.write(CONTRACT, contract_page())
        self.seed_feature("ready-for-dev", "dev", tracks or DesignTracks("done", "done"))
        self.write(BACKEND_REQ, requirement_page("backend"))
        self.write(WEB_REQ, requirement_page("web"))
        _write_index_rows(self.root, [("F-001", "Document review", "ready-for-dev", "dev")])
        self.service.close()
        self.start()
        return self.read(FEATURE)

    def deliver(self, contract: str, status: str = "in-dev") -> list[dict[str, str]]:
        page = self.read(FEATURE)
        row = f"| backend | `build:backend#7` | {contract} | Pull request 7 | CI run 7: 31 tests passed | checked |"
        page = _replace_body_section_text(page, "Delivery evidence", "\n".join([*DELIVERY_HEADER.splitlines(), row]))
        page = edit_frontmatter(page, {"status": status, "owner": "dev"})
        return self.changes(page, (BACKEND_REQ, requirement_page("backend", "done")))

    def citation(self) -> str:
        return contract_citation("F-001", 1, _parse_markdown(self.read(CONTRACT))[1])

    def test_the_current_citation_is_accepted_and_none_or_a_stale_one_is_refused(self) -> None:
        self.at_dev()
        for stale in ("none", f"F-001@v1:c1:{'0' * 64}", f"F-001@v2:{contract_digest('F-001', 2, _parse_markdown(contract_page())[1])}"):
            with self.subTest(contract=stale[:30]):
                error = self.rejected("dev-done", self.deliver(stale))
                self.assertEqual(("contract_binding_stale", 409), (error.code, error.status))
        preview = self.ready("dev-done", self.deliver(self.citation()))
        self.assertEqual("dev-done", preview["action"])

    def test_a_feature_with_no_contract_cites_none(self) -> None:
        self.at_dev()
        (self.root / CONTRACT).unlink()
        self.seed_feature("ready-for-dev", "dev", DesignTracks("done", "done"), surface="None.")
        self.service.close()
        self.start()
        error = self.rejected("dev-done", self.deliver(f"F-001@v1:c1:{'a' * 64}"))
        self.assertEqual("contract_binding_stale", error.code)
        self.ready("dev-done", self.deliver("none"))

    def test_a_citation_survives_the_contract_becoming_implemented_and_goes_stale_with_a_revision(self) -> None:
        self.at_dev()
        citation = self.citation()
        self.apply_as(self.ready("dev-done", self.deliver(citation)))
        self.assertEqual(0, lint_wiki(self.root).error_count, [item.message for item in lint_wiki(self.root).diagnostics if item.severity == "error"])
        fm, body = _parse_markdown(self.read(CONTRACT))
        self.write(CONTRACT, contract_page(status="implemented"))
        self.assertEqual(citation, self.citation())
        self.assertNotIn("stale-delivery-evidence", {item.code for item in lint_wiki(self.root).diagnostics})
        self.write(CONTRACT, contract_page(version=2, errors="401, 403"))
        self.assertIn("stale-delivery-evidence", {item.code for item in lint_wiki(self.root).diagnostics})

    def test_dev_done_needs_both_tracks_settled(self) -> None:
        self.at_dev(DesignTracks("done", "pending"))
        preview = self.blocked("dev-done", self.deliver(self.citation()))
        self.assertIn("workflow:design-track-pending", self.codes(preview))


class TrackLintTests(TrackCase):
    """CONTRACTS 3.1 and 6.2: the lint of tracks and of the technical design page."""

    def codes_of(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def test_a_feature_from_ready_for_dev_on_needs_both_tracks_settled(self) -> None:
        self.write(DESIGN, designs_page())
        self.write(TECH, technical_page())
        self.write(CONTRACT, contract_page())
        self.seed_feature("ready-for-dev", "dev", DesignTracks("done", "pending"))
        self.write(BACKEND_REQ, requirement_page("backend"))
        self.write(WEB_REQ, requirement_page("web"))
        _write_index_rows(self.root, [("F-001", "Document review", "ready-for-dev", "dev")])
        self.assertIn("design-track-pending", self.codes_of())
        self.seed_feature("ready-for-dev", "dev", DesignTracks("done", "done", None, None, ("technical",)))
        self.assertIn("design-track-pending", self.codes_of())
        _write_index_rows(self.root, [("F-001", "Document review", "ready-for-dev", "dev")])

    def test_a_done_ui_track_needs_design_pages_that_cover_the_apps_with_a_ui(self) -> None:
        self.write(TECH, technical_page())
        self.write(CONTRACT, contract_page())
        self.seed_feature("in-design", "designer", DesignTracks("done", "pending"))
        self.assertIn("design-coverage-incomplete", self.codes_of())
        self.write(DESIGN, designs_page())
        self.refresh_index("in-design", "designer")
        self.assertNotIn("design-coverage-incomplete", self.codes_of())

    def test_a_done_technical_track_needs_a_complete_page_a_contract_and_matching_names(self) -> None:
        self.write(DESIGN, designs_page())
        self.seed_feature("in-design", "designer", DesignTracks("pending", "done"))
        self.assertIn("missing-technical-design", self.codes_of())
        self.write(TECH, technical_page(strategy=["| AC-1 | backend | automated | integration | |"]))
        self.refresh_index("in-design", "designer")
        codes = self.codes_of()
        self.assertIn("test-strategy-incomplete", codes)
        self.assertIn("api-contract-required", codes)
        misnamed = "knowledge/wiki/technical-design/export-design.md"
        self.write(misnamed, technical_page())
        self.assertIn("technical-design-feature-mismatch", self.codes_of())

    def test_a_not_applicable_technical_track_needs_a_reason_and_no_api_work(self) -> None:
        self.seed_feature("in-design", "designer", DesignTracks("pending", "not-applicable", None, "No architecture change."))
        self.assertIn("technical-track-required", self.codes_of())
        self.seed_feature("in-design", "designer", DesignTracks("pending", "not-applicable", None, "No architecture change."), surface="None.")
        self.assertNotIn("technical-track-required", self.codes_of())

    def test_the_old_design_exemption_fields_are_not_feature_fields(self) -> None:
        self.write(FEATURE, edit_frontmatter(self.page("ready-for-design", "designer", None), {"design": "not-applicable", "design-exemption-reason": "No screens."}))
        self.assertIn("unsupported-feature-field", self.codes_of())


class ModelTests(unittest.TestCase):
    """The parsers of the track front matter and of the technical design page."""

    def test_the_tracks_round_trip_and_the_shape_is_checked(self) -> None:
        tracks = DesignTracks("not-applicable", "done", "No app in scope has a UI.", None, ())
        parsed, problems = parse_design_tracks(tracks.frontmatter())
        self.assertEqual((tracks, []), (parsed, problems))
        self.assertEqual({"ui": "not-applicable", "technical": "done", "ui-reason": "No app in scope has a UI."}, tracks.frontmatter()["design-tracks"])
        self.assertEqual((None, []), parse_design_tracks({}))
        bad = {
            "unknown state": {"design-tracks": {"ui": "finished", "technical": "done"}, "design-reaffirm": []},
            "reason with done": {"design-tracks": {"ui": "done", "technical": "done", "ui-reason": "x"}, "design-reaffirm": []},
            "unknown key": {"design-tracks": {"ui": "done", "technical": "done", "extra": "x"}, "design-reaffirm": []},
            "reaffirm of a pending track": {"design-tracks": {"ui": "pending", "technical": "done"}, "design-reaffirm": ["ui"]},
            "reaffirm alone": {"design-reaffirm": ["ui"]},
            "unknown reaffirm": {"design-tracks": {"ui": "done", "technical": "done"}, "design-reaffirm": ["both"]},
        }
        for name, frontmatter in bad.items():
            with self.subTest(case=name):
                self.assertTrue(parse_design_tracks(frontmatter)[1])

    def test_the_test_strategy_and_the_page_problems(self) -> None:
        rows, problems = parse_test_strategy(technical_page())
        self.assertEqual(([], ["AC-1", "AC-2", "AC-3"]), (problems, [row.criterion for row in rows]))
        _fm, body = _parse_markdown(technical_page())
        frontmatter = _parse_markdown(technical_page())[0]
        self.assertEqual([], technical_design_problems(frontmatter, body, feature_id="F-001", scope=["backend", "web"], criteria_ids=CRITERION_IDS))
        codes = {code for code, _message in technical_design_problems(frontmatter, body, feature_id="F-001", scope=["backend", "web"], criteria_ids=[*CRITERION_IDS, "AC-4"])}
        self.assertEqual({"test-strategy-incomplete"}, codes)
        bad_method = body.replace("| automated |", "| guesswork |")
        self.assertIn("test-strategy-incomplete", {code for code, _ in technical_design_problems(frontmatter, bad_method, feature_id="F-001", scope=["backend", "web"], criteria_ids=CRITERION_IDS)})
        empty = body.replace("An export of a typical review is ready within five seconds.", "")
        self.assertIn("technical-design-incomplete", {code for code, _ in technical_design_problems(frontmatter, empty, feature_id="F-001", scope=["backend", "web"], criteria_ids=CRITERION_IDS)})

    def test_the_initial_tracks_follow_the_scope(self) -> None:
        self.assertEqual(DesignTracks("pending", "pending"), initial_design_tracks(["a"], None))


if __name__ == "__main__":
    unittest.main()
