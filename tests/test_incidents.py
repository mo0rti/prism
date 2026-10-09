"""Incident records through `ingest`, and the status board they and the bug pages feed (CONTRACTS 6.2, 6.3, 8.2).

An incident is a dated record: ingest opens it, steps its status, appends Timeline lines, adds follow-ups and releases, and fills
its Cause while it is not `resolved`. The Operations table of the status board lists the open incidents of each app.
"""

from __future__ import annotations

import unittest

from unittest.mock import patch

from prism_cli.wiki_incidents import cause_is_unknown, timeline_items
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_operations import read_board_views
from prism_cli.wiki_releases import read_release_records
from tests import real_temp  # noqa: F401
from tests.release_pages import delivery, record_page
from tests.test_board_ingest import BOARD, IngestCase
from tests.test_board_operations import SimulatedCrash
from tests.test_board_service import _journey_feature_page, _read_revisions
from tests.wiki_files import refresh_status_board

INC = "incidents/INC-001-reservation-outage.md"
BUG = "bugs/BUG-001-reservation-fails.md"
RELEASE = "releases/REL-003.md"


def incident(
    *,
    status: str = "open",
    cause: str = "**Unknown:** The release changed reservation handling; the failing path is not known yet.",
    mitigation: str = "",
    resolution: str = "",
    follow_ups: str = "",
    timeline: tuple[str, ...] = (
        "- 2026-10-09 08:15: Reservations started failing after the release.",
        "- 2026-10-09 08:40: The release was rolled back.",
    ),
    releases: str = "[]",
    follow_up_ids: str = "[]",
    **overrides: str,
) -> str:
    fields = {
        "id": "INC-001",
        "title": "Reservation outage",
        "date": "2026-10-09",
        "status": status,
        "severity": "high",
        "apps": "[backend]",
        "releases": releases,
        "follow-ups": follow_up_ids,
        **overrides,
    }
    front = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return (
        f"---\n{front}\n---\n\n"
        "## Impact\nReaders could not reserve books for 25 minutes.\n\n"
        "## Timeline\n" + "\n".join(timeline) + "\n\n"
        f"## Cause\n{cause}\n\n"
        f"## Mitigation\n{mitigation}\n\n"
        f"## Resolution\n{resolution}\n\n"
        f"## Follow-ups\n{follow_ups}\n"
    )


def bug(feature: str = "none") -> str:
    return (
        "---\nid: BUG-001\ntitle: Reservation fails\nstatus: open\nowner: dev\nseverity: high\nblocking: true\napps: [backend]\n"
        f"feature: {feature}\nfound-in: release REL-003\nenvironment: production\nsources: []\n---\n\n"
        "## Summary\nA reservation request for an available copy fails.\n\n## Steps to reproduce\n1. Reserve an available copy.\n\n"
        "## Expected\nThe reservation is returned.\n\n## Actual\nThe request fails.\n\n## Impact\nReaders cannot reserve.\n\n"
        "## Fix\n\n## Verification\n\n## Release\n\n## Evidence history\n"
    )


def release_record(release_id: str = "REL-003", outcome: str = "released", row_outcome: str | None = None, app: str = "backend") -> str:
    """A release record in the format of `release_pages.record_page`, the one the release stage writes."""

    number = int(release_id.removeprefix("REL-"))
    rolled_back = outcome == "rolled-back"
    rows = [delivery("F-001", app, outcome=row_outcome or outcome, attempt=None if rolled_back else 1)]
    if rolled_back:
        return record_page(number, rows, rollback_of=f"REL-{number - 1:03d}", title=f"Rollback of REL-{number - 1:03d}", rollback="The service was rolled back.")
    return record_page(number, rows, outcome=outcome)


class IncidentCase(IngestCase):
    """The ingest workspace with helpers for incidents, bugs and seeded release records."""

    def plant_release(self, release_id: str = "REL-003", **kwargs: str) -> None:
        """Write a release record that delivers F-001; lint checks that the item exists, so the feature is ingested first."""

        if not (self.root / "knowledge/wiki/features/F-001-document-review.md").exists():
            page = _journey_feature_page("F-001", "Document review", "raw", "po", ["knowledge/intake/processed/NAME/note.md"], ["| 1 | Which details should the summary emphasize? | po | open |"])
            self.ingest("2026-10-08-review-brief", {"features/F-001-document-review.md": page})
        path = self.root / f"knowledge/wiki/releases/{release_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(release_record(release_id, **kwargs), encoding="utf-8")
        refresh_status_board(self.root)

    def open_incident(self, name: str = "2026-10-09-outage-report", **kwargs: str) -> dict:
        return self.ingest(name, {INC: incident(**kwargs)})

    def views(self):
        return read_board_views(self.read(BOARD))

    def errors(self) -> list[str]:
        return [f"{item.code}: {item.message}" for item in lint_wiki(self.root).diagnostics if item.severity == "error"]


class IncidentIngestTests(IncidentCase):
    def test_an_incident_is_opened_through_ingest_with_its_index_line_and_an_operations_row(self) -> None:
        self.open_incident()
        self.assertEqual([], self.errors())
        lines = self.index_lines()
        self.assertEqual(
            "- [INC-001 Reservation outage](incidents/INC-001-reservation-outage.md): Readers could not reserve books for 25 minutes.",
            lines[INC],
        )
        self.assertIn("## Incidents", self.headings())
        operations = self.views().operations
        self.assertEqual(["backend"], list(operations))
        self.assertEqual("INC-001", operations["backend"]["open_incidents"])
        self.assertEqual("—", operations["backend"]["latest_release"])
        # A record keeps its own date and is not a current-state page: no freshness finding names it.
        self.assertFalse([item for item in lint_wiki(self.root).diagnostics if item.code == "never-verified" and "INC-001" in item.path])

    def test_a_cause_that_is_unknown_is_accepted_and_filled_later_with_a_timeline_line_that_cites_the_intake_item(self) -> None:
        self.open_incident()
        self.assertTrue(cause_is_unknown(self.read(f"knowledge/wiki/{INC}").split("---", 2)[2]))
        name = "2026-10-10-postmortem"
        link = f"../../intake/processed/{name}/note.md"
        filled = incident(
            cause="The reservation query ignored the copy status after the release ([post-mortem](" + link + ")).",
            timeline=(
                "- 2026-10-09 08:15: Reservations started failing after the release.",
                "- 2026-10-09 08:40: The release was rolled back.",
                f"- 2026-10-10: Cause recorded ([post-mortem]({link}))",
            ),
        )
        uncited = incident(cause="The reservation query ignored the copy status after the release.")
        error = self.reject(name, {INC: uncited})
        self.assertEqual("incident_cause_uncited", error.code)
        self.ingest(name, {INC: filled})
        self.assertEqual([], self.errors())
        _lines, malformed = timeline_items(self.read(f"knowledge/wiki/{INC}").split("---", 2)[2])
        self.assertEqual([], malformed)
        self.assertIn("ignored the copy status", self.read(f"knowledge/wiki/{INC}"))

    def test_a_follow_up_bug_is_linked_and_both_show_on_the_status_board(self) -> None:
        self.plant_release()
        self.open_incident(releases="[REL-003]")
        self.assertEqual([], self.errors())
        operations = self.views().operations["backend"]
        self.assertEqual(("REL-003", "released", "INC-001"), (operations["latest_release"], operations["latest_outcome"], operations["open_incidents"]))
        self.ingest("2026-10-10-defect", {BUG: bug()})
        self.assertEqual("BUG-001", self.views().operations["backend"]["open_bugs"])
        self.assertEqual("BUG-001", self.views().bugs["BUG-001"]["id"])
        link = "../../intake/processed/2026-10-11-update/note.md"
        updated = incident(
            status="mitigated",
            mitigation="The release was rolled back at 08:40.",
            follow_ups="- [BUG-001](../bugs/BUG-001-reservation-fails.md): the defect behind the outage",
            follow_up_ids="[BUG-001]",
            releases="[REL-003]",
            timeline=(
                "- 2026-10-09 08:15: Reservations started failing after the release.",
                "- 2026-10-09 08:40: The release was rolled back.",
                f"- 2026-10-11: Follow-up BUG-001 linked ([update]({link}))",
            ),
        )
        self.ingest("2026-10-11-update", {INC: updated})
        self.assertEqual([], self.errors())
        text = self.read(f"knowledge/wiki/{INC}")
        self.assertIn("status: mitigated", text)
        self.assertIn("follow-ups: [BUG-001]", text)
        # A mitigated incident is still open for the apps it names.
        self.assertEqual("INC-001", self.views().operations["backend"]["open_incidents"])

    def test_resolving_the_incident_leaves_the_operations_table_and_the_row_goes_with_it(self) -> None:
        self.open_incident()
        link = "../../intake/processed/2026-10-11-resolved/note.md"
        resolved = incident(
            status="resolved",
            mitigation="Rolled back.",
            resolution="The corrected release shipped and the reservation checks pass.",
            timeline=(
                "- 2026-10-09 08:15: Reservations started failing after the release.",
                "- 2026-10-09 08:40: The release was rolled back.",
                f"- 2026-10-11: Resolved ([note]({link}))",
            ),
        )
        self.ingest("2026-10-11-resolved", {INC: resolved})
        self.assertEqual({}, self.views().operations)
        self.assertEqual([], self.errors())

    def test_a_resolved_incident_changes_only_by_timeline_lines_follow_ups_and_releases(self) -> None:
        resolved = incident(status="resolved", mitigation="Rolled back.", resolution="Fixed in the next release.")
        self.open_incident(status="resolved", mitigation="Rolled back.", resolution="Fixed in the next release.")
        cases = {
            "incident_resolved_final": incident(status="open", mitigation="Rolled back.", resolution="Fixed in the next release."),
            "incident_body_scope": resolved.replace("Fixed in the next release.", "Fixed another way."),
        }
        for code, content in cases.items():
            with self.subTest(code=code):
                self.assertEqual(code, self.reject("2026-10-12-late", {INC: content}).code)
        extra = incident(
            status="resolved",
            mitigation="Rolled back.",
            resolution="Fixed in the next release.",
            timeline=(
                "- 2026-10-09 08:15: Reservations started failing after the release.",
                "- 2026-10-09 08:40: The release was rolled back.",
                "- 2026-10-12: A related report arrived.",
            ),
        )
        self.ingest("2026-10-12-late", {INC: extra})
        self.assertEqual([], self.errors())

    def test_the_record_rules_refuse_each_change_outside_them(self) -> None:
        self.open_incident()
        first = "- 2026-10-09 08:15: Reservations started failing after the release."
        cases = {
            "incident_frontmatter_scope": incident(title="Renamed outage"),
            "incident_timeline_not_append_only": incident(timeline=("- 2026-10-09 08:15: Edited line.", "- 2026-10-09 08:40: The release was rolled back.")),
            "incident_body_scope": incident().replace("Readers could not reserve books for 25 minutes.", "Readers were fine."),
        }
        for code, content in cases.items():
            with self.subTest(code=code):
                self.assertEqual(code, self.reject("2026-10-12-bad", {INC: content}).code)
        self.assertEqual("incident_frontmatter_scope", self.reject("2026-10-12-bad", {INC: incident(severity="low")}).code)
        self.assertIn(first, self.read(f"knowledge/wiki/{INC}"))

    def test_a_new_incident_is_checked_for_its_shape_its_id_and_its_releases(self) -> None:
        base = incident()
        cases = {
            "invalid_incident": [
                base.replace("status: open", "status: broken"),
                base.replace("severity: high", "severity: urgent"),
                base.replace("date: 2026-10-09", "date: soon"),
                base.replace("apps: [backend]", "apps: [ghost]"),
                base.replace("apps: [backend]", "apps: []"),
                base.replace("releases: []", "releases: [REL-x]"),
                base.replace("follow-ups: []", "follow-ups: [INC-002]"),
                base.replace("title: Reservation outage", "title: Reservation outage\nowner: dev"),
                base.replace("## Timeline", "## Notes\nNone.\n\n## Timeline"),
                base.replace("- 2026-10-09 08:15:", "- yesterday:"),
                incident(status="mitigated"),
                incident(status="resolved"),
                incident(cause=""),
            ],
            "incident_release_unknown": [incident(releases="[REL-009]")],
        }
        for code, pages in cases.items():
            for index, content in enumerate(pages):
                with self.subTest(code=code, index=index):
                    self.assertEqual(code, self.reject("2026-10-09-shape", {INC: content}).code)
        # The file name carries the ID.
        misnamed = {"incidents/INC-002-other.md": base}
        self.assertEqual("invalid_incident", self.reject("2026-10-09-shape", misnamed).code)

    def test_an_incident_id_is_taken_once(self) -> None:
        self.open_incident()
        other = "incidents/INC-001-second-outage.md"
        self.assertEqual("incident_id_taken", self.reject("2026-10-12-second", {other: incident(title="Second outage")}).code)

    def test_any_participant_may_ingest_an_incident_and_an_incident_is_not_asked_for_review(self) -> None:
        self.open_incident()
        codes = {item.code for item in lint_wiki(self.root).diagnostics if INC.split("/")[1] in item.path}
        self.assertFalse(codes & {"stale-page", "never-verified", "history-date-on-page"})


class StatusBoardViewTests(IncidentCase):
    def test_a_bug_row_follows_the_bug_and_leaves_the_table_when_the_bug_closes(self) -> None:
        self.ingest("2026-10-10-defect", {BUG: bug()})
        row = self.views().bugs["BUG-001"]
        self.assertEqual(("open", "dev", "backend", "none", "yes"), (row["status"], row["owner"], row["apps"], row["feature"], row["blocking"]))
        self.assertEqual([], self.errors())

    def test_lint_reports_each_row_that_disagrees_with_the_pages(self) -> None:
        self.open_incident()
        self.ingest("2026-10-10-defect", {BUG: bug()})
        board = self.read(BOARD)
        for name, broken in {
            "bug row": board.replace("| BUG-001 | Reservation fails | open |", "| BUG-001 | Reservation fails | fixed |"),
            "operations row": board.replace("| INC-001 |", "| — |"),
            "missing bug row": "\n".join(line for line in board.splitlines() if not line.startswith("| BUG-001")) + "\n",
            "extra operations row": board + "| ghost | — | — | — | — | — | — |\n",
        }.items():
            with self.subTest(name=name):
                (self.root / BOARD).write_text(broken, encoding="utf-8")
                self.assertIn("status-board-frontmatter-drift", {item.code for item in lint_wiki(self.root).diagnostics}, name)
        (self.root / BOARD).write_text(board, encoding="utf-8")
        self.assertEqual([], self.errors())

    def test_a_delivery_target_edited_by_hand_is_not_drift(self) -> None:
        self.open_incident()
        board = self.read(BOARD)
        (self.root / BOARD).write_text(board.replace("| backend | production |", "| backend | staging |"), encoding="utf-8")
        self.assertEqual([], self.errors())

    def test_the_release_reader_lists_the_records_by_number_with_the_outcome_of_each_app(self) -> None:
        self.plant_release("REL-010", outcome="released")
        self.plant_release("REL-004", outcome="rolled-back", row_outcome="rolled-back")
        self.plant_release("REL-005", outcome="failed")
        records = read_release_records(self.root / "knowledge" / "wiki")
        self.assertEqual(["REL-004", "REL-005", "REL-010"], [record.record_id for record in records])
        self.assertEqual(["rolled-back", "failed", "released"], [record.outcome_for("backend") for record in records])
        self.assertIsNone(records[0].outcome_for("elsewhere"))

    def test_an_incident_that_names_an_unrecorded_release_fails_lint(self) -> None:
        self.open_incident()
        path = self.root / "knowledge/wiki" / INC
        path.write_text(path.read_text(encoding="utf-8").replace("releases: []", "releases: [REL-007]"), encoding="utf-8")
        self.assertTrue(any("incident-record-invalid" in item for item in self.errors()))

    def test_a_follow_up_that_names_no_page_is_a_warning(self) -> None:
        self.open_incident()
        path = self.root / "knowledge/wiki" / INC
        path.write_text(path.read_text(encoding="utf-8").replace("follow-ups: []", "follow-ups: [BUG-004]"), encoding="utf-8")
        found = [item for item in lint_wiki(self.root).diagnostics if item.code == "incident-follow-up-missing"]
        self.assertEqual(["warning"], [item.severity for item in found])




class StatusBoardRecoveryTests(IncidentCase):
    def test_an_interrupted_ingest_that_adds_status_rows_rolls_forward_once(self) -> None:
        name = "2026-10-09-outage-report"
        changes, moves = self.proposal(name, {INC: incident()})
        agent = self.agent
        preview = self.service.preview_skill(agent, "ingest", changes, moves, _read_revisions(self.service, agent, "ingest", changes, moves))
        self.assertTrue(preview["applicable"], preview["blockers"])
        original = self.service._apply_write

        def interrupted(write, **kwargs):
            if write["role"] == "log":
                raise SimulatedCrash()
            return original(write, **kwargs)

        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(SimulatedCrash):
                self.service.apply(agent, preview["preview_id"], "outage-1")
        self.assertEqual(["backend"], list(self.views().operations))
        receipt = self.service.apply(agent, preview["preview_id"], "outage-1")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(["backend"], list(self.views().operations))
        self.assertEqual(1, self.read(BOARD).count("| backend |"))
        self.assertEqual([], self.errors())


if __name__ == "__main__":
    unittest.main()
