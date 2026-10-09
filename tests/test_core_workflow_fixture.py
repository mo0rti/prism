from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import NO_UI_TRACK_REASON, DesignTracks, parse_design_tracks
from prism_cli.wiki_query import wiki_show
from prism_cli.wiki_transitions import build_board_transition_preflight, build_transition_preflight
from tests.core_workflow_fixture import (
    FEATURE_ID,
    FEATURE_PATH,
    INTAKE_ITEM,
    PROCESSED_INTAKE_ITEM,
    create_core_workflow_fixture,
)
from tests.design_tracks import apply_tracks, technical_design_page, with_tracks
from tests import real_temp  # noqa: F401
from tests.wiki_files import write_index, write_status_board


CHECK_DATE = date(2026, 9, 22)


class CoreWorkflowFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Mock(wraps=date)
        self.clock.today.return_value = CHECK_DATE
        for module in ("wiki_lint", "wiki_transitions"):
            date_patch = patch(f"prism_cli.{module}.date", self.clock)
            date_patch.start()
            self.addCleanup(date_patch.stop)
        # The board evaluation also checks the identity of a connected board; this fixture has none.
        identity = patch("prism_cli.wiki_transitions._board_workspace_identity_checks", return_value=[])
        identity.start()
        self.addCleanup(identity.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = create_core_workflow_fixture(Path(self.temp_dir.name) / "document-review")
        self.feature_path = self.root / FEATURE_PATH

    def test_neutral_scenario_covers_intake_handoff_blockers_delivery_and_the_reopen_route(self) -> None:
        # The fixture begins at the intake queue, with no generated app or
        # Copier answers. The empty backend directory only records declared
        # scope for today's shared workspace identity contract.
        self.assertFalse((self.root / ".copier-answers.yml").exists())
        self.assertEqual([".gitkeep"], [path.name for path in (self.root / "backend").iterdir()])
        self.assertFalse((self.root / "backend" / "src").exists())
        self.assertEqual(
            ["2026-10-06-document-review-brief"],
            build_graph(self.root)["facts"]["intake"]["pending"],
        )

        # Model intake processing in the isolated workspace, then query the
        # resulting feature and confirm its unanswered question is visible.
        pending_brief = self.root / INTAKE_ITEM
        processed_brief = self.root / PROCESSED_INTAKE_ITEM
        processed_brief.parent.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pending_brief.parent), str(processed_brief.parent))
        self.feature_path.parent.mkdir(parents=True, exist_ok=True)
        self.feature_path.write_text(_feature_page(), encoding="utf-8")
        _write_index(self.root, "raw", "po")

        show = wiki_show(self.root, FEATURE_ID)
        feature = show["facts"]["feature"]
        self.assertEqual("Document review", feature["title"])
        self.assertEqual("raw", feature["status"])
        self.assertEqual("open", feature["open_questions"][0]["status"])
        self.assertEqual(
            ["knowledge/intake/processed/2026-10-06-document-review-brief/brief.md"],
            feature["frontmatter"]["sources"],
        )
        self.assertFalse(lint_wiki(self.root).error_count)

        specify = _transition(self.root, "po-specify")
        self.assertEqual("ready", specify["classification"])
        self.assertEqual("specified", specify["target_status"])

        # After the spec is recorded, the unanswered PO question blocks the
        # handoff. A fresh read after the answer changes the snapshot and lifts
        # the same prerequisite without any persisted preview or write API.
        _set_stage(self.root, "specified", "po")
        blocked_handoff = _transition(self.root, "po-handoff")
        self.assertEqual("blocked", blocked_handoff["classification"])
        self.assertEqual("blocked", _check(blocked_handoff, "open-questions")["status"])
        before_answer = _snapshot(self.root, "po-handoff")

        source = self.feature_path.read_text(encoding="utf-8")
        source = source.replace(
            "| 1 | Which points should a review summary highlight? | po | open |",
            "| 1 | Which points should a review summary highlight? | po | resolved: Capture key points and requested follow-up. |",
        )
        self.feature_path.write_text(source, encoding="utf-8")
        handoff = _transition(self.root, "po-handoff")
        self.assertEqual("ready", handoff["classification"])
        self.assertEqual("ready-for-design", handoff["target_status"])
        self.assertNotEqual(before_answer, _snapshot(self.root, "po-handoff"))

        # Walk the existing backend-only lifecycle mappings using their named
        # preflights. These edits model accepted states only in this temp tree.
        _set_stage(self.root, "ready-for-design", "tech-lead")
        self.assertEqual("ready", _transition(self.root, "design-start")["classification"])
        _set_stage(self.root, "in-design", "tech-lead")
        # Design starts with the no-UI initialization: the UI track is not applicable and the technical track is pending, so
        # the handoff is blocked until the technical track is settled by its page.
        started = _transition(self.root, "design-handoff")
        self.assertEqual("blocked", started["classification"])
        self.assertEqual("blocked", _check(started, "technical-design-incomplete")["status"])
        _settle_technical_track(self.root)
        self.assertEqual("ready", _transition(self.root, "design-handoff")["classification"])
        _set_stage(self.root, "ready-for-dev", "dev")

        requirement = self.root / "knowledge/wiki/app-requirements/F-001-backend.md"
        requirement.write_text(_requirement_page("pending"), encoding="utf-8")
        self.assertEqual("ready", _transition(self.root, "dev-start")["classification"])
        _set_stage(self.root, "in-dev", "dev")
        requirement.write_text(_requirement_page("in-progress"), encoding="utf-8")

        # Delivery remains blocked until the proposal carries substantive
        # evidence for the app it delivers. Adding the row and completing the
        # app requirement changes the source snapshot and makes the same
        # preflight ready.
        blocked_done = build_board_transition_preflight(self.root, FEATURE_ID, "dev-done", named_apps=["backend"])
        self.assertEqual("blocked", blocked_done["classification"])
        self.assertEqual("blocked", _check(blocked_done, "delivery-evidence")["status"])
        before_evidence = _snapshot(self.root, "dev-done")
        source = self.feature_path.read_text(encoding="utf-8")
        source += (
            "\n## Delivery evidence\n"
            "| App | Artifact | Contract | Implementation | Tests | Basis |\n"
            "|---|---|---|---|---|---|\n"
            "| backend | `build:backend#1` | none | Synthetic fixture reference `evidence/review-summary.md` | Synthetic fixture check `review-summary` passed | attested |\n"
            "\n## QA verification\n"
            "| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "\n## Release\n"
            "| App | Target | Version | Attempt | Outcome | Record | Basis |\n"
            "|---|---|---|---|---|---|---|\n"
            "\n## Evidence history\n"
        )
        self.feature_path.write_text(source, encoding="utf-8")
        requirement.write_text(_requirement_page("done"), encoding="utf-8")
        done_preflight = build_board_transition_preflight(self.root, FEATURE_ID, "dev-done", named_apps=["backend"])
        # Ready means the observable checks pass. These fixture-only
        # references are not real implementation or test claims.
        self.assertEqual("ready", done_preflight["classification"], done_preflight["reason"])
        self.assertEqual("ready-for-qa", done_preflight["target_status"])
        self.assertEqual("qa", done_preflight["target_owner"])
        self.assertNotEqual(before_evidence, _snapshot(self.root, "dev-done"))

        _set_stage(self.root, "ready-for-qa", "qa")
        lint = lint_wiki(self.root)
        self.assertEqual([], [item.code for item in lint.diagnostics if item.severity == "error"])
        completed_graph = build_graph(self.root)
        node = next(node for node in completed_graph["facts"]["nodes"] if node["id"] == FEATURE_ID)
        self.assertEqual("ready-for-qa", node["status"])
        self.assertEqual([{"app": "backend", "stage": "ready-for-qa"}], node["app_stages"])

        # The release actions are offered once an app is ready for release, and the reopen routes only from `released`.
        self.assertEqual("unknown", build_board_transition_preflight(self.root, FEATURE_ID, "reopen-dev")["classification"])
        _set_stage(self.root, "released", "none")
        reopen = build_board_transition_preflight(self.root, FEATURE_ID, "reopen-dev")
        self.assertEqual("in-dev", reopen["target_status"])
        self.assertEqual("dev", reopen["target_owner"])
        self.assertEqual("pass", _check(reopen, "reopen-impact-review")["status"])


def _feature_page() -> str:
    frontmatter = {
        "id": FEATURE_ID,
        "title": "Document review",
        "status": "raw",
        "owner": "po",
        "apps": ["backend"],
        "sources": [PROCESSED_INTAKE_ITEM.as_posix()],
        "advisory-review": "not-needed",
        "criteria-high-water": 2,
    }
    body = """## Summary
Review a document, summarize its key points, and record the review outcome.

## User story
As a reviewer, I want to record a document review, so that the outcome and follow-up are clear.

## Acceptance criteria
- [ ] AC-1 [backend] A review summary records the document's key points.
- [ ] AC-2 [backend] A reviewer can record the outcome and requested follow-up.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Which points should a review summary highlight? | po | open |

## App scope
- **backend**: Store the review summary and recorded outcome.

## API surface
None
"""
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n{body}"


def _requirement_page(status: str) -> str:
    return (
        "---\nfeature-id: F-001\napp: backend\n"
        f"status: {status}\n---\n\n"
        "## What to build\nStore a document review summary and outcome.\n\n"
        "## Acceptance criteria\n- The saved summary and outcome can be read back.\n"
    )


def _set_stage(root: Path, status: str, owner: str) -> None:
    text = (root / FEATURE_PATH).read_text(encoding="utf-8")
    _, frontmatter_and_body = text.split("---", 1)
    frontmatter_text, body = frontmatter_and_body.split("---", 1)
    frontmatter = yaml.safe_load(frontmatter_text)
    frontmatter["status"] = status
    frontmatter["owner"] = owner
    apply_tracks(frontmatter, status, parse_design_tracks(frontmatter)[0])
    updated = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False).rstrip()
        + "\n---"
        + body
    )
    (root / FEATURE_PATH).write_text(updated, encoding="utf-8")
    _write_index(root, status, owner)


def _settle_technical_track(root: Path) -> None:
    """Model `tech-design-done` in the temp tree: the technical design page, and the track `done`."""

    page = root / "knowledge/wiki/technical-design/F-001-document-review.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(technical_design_page(FEATURE_ID, ("backend",), ("AC-1", "AC-2")), encoding="utf-8")
    feature = root / FEATURE_PATH
    feature.write_text(with_tracks(feature.read_text(encoding="utf-8"), DesignTracks("not-applicable", "done", NO_UI_TRACK_REASON, None)), encoding="utf-8")
    _write_index(root, "in-design", "tech-lead")


def _write_index(root: Path, status: str, owner: str) -> None:
    write_status_board(root, f"| {FEATURE_ID} | Document review | {status} | {owner} | not-needed |\n")
    write_index(root)


def _transition(root: Path, action: str) -> dict:
    return build_transition_preflight(root, FEATURE_ID, action=action)["facts"]["transition"]


def _snapshot(root: Path, action: str) -> str:
    result = build_transition_preflight(root, FEATURE_ID, action=action)
    return result["facts"]["transition_capability"]["snapshot"]["fingerprint"]


def _check(transition: dict, code: str) -> dict:
    return next(item for item in transition["checks"] if item["code"] == code)


if __name__ == "__main__":
    unittest.main()
