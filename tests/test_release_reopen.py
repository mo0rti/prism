"""The reopen routes of a released feature through `feature-reopen`: `reopen-spec`, `reopen-design` and `reopen-dev` (CONTRACTS F23 to F25)."""

from __future__ import annotations

import unittest

import yaml

from prism_cli.board_service import _parse_markdown
from tests.qa_support import DELIVERY_HEADER, FEATURE, QA_HEADER, RELEASE_HEADER, append_history, history_entry, requirement_path
from tests.release_support import ReleaseTests, table
from tests.test_board_service import _set_requirement_status

ALL_DOMAINS = ["implementation", "tests", "qa", "release"]
TRACKS = {"ui": "not-applicable", "ui-reason": "No app in scope has a UI.", "technical": "done"}
APPS = ("backend", "worker")


def line(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


class ReopenBoard(ReleaseTests):
    """A board whose F-001 is released; the helpers build the proposals of the reopen routes."""

    def setUp(self) -> None:
        super().setUp()
        self.release()
        self.assertEqual(("released", "none"), self.status())

    def seed_tracks(self, tracks: dict | None = None) -> None:
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), **{"design-tracks": tracks or TRACKS, "design-reaffirm": []}))

    def rows(self) -> list[tuple[str, str]]:
        evidence = self.evidence()
        return (
            [("Delivery evidence", line(row.cells)) for row in evidence.delivery]
            + [("QA verification", line(row.cells)) for row in evidence.qa]
            + [("Release", line(row.cells)) for row in evidence.release]
        )

    def empty(self, page: str, keep: dict[str, list[str]] | None = None) -> str:
        keep = keep or {}
        for heading, header in (("Delivery evidence", DELIVERY_HEADER), ("QA verification", QA_HEADER), ("Release", RELEASE_HEADER)):
            page = self.with_section(heading, table(header, keep.get(heading, [])), page)
        return page

    def reopen_changes(self, action: str, *, tracks: str = "ui, technical", mutate=None) -> list[dict[str, str]]:
        spec = action == "reopen-spec"
        page = self.empty(self.read(FEATURE))
        invalidations = ", ".join(f"{requirement_path(app)}: done -> in-progress" for app in APPS)
        entry = history_entry(action, affected=", ".join(APPS), archived=self.rows(), tracks=tracks, invalidations=invalidations, reason="The specification missed the offline case.")
        page = append_history(page, entry)
        page = self.with_status(*(("specified", "po") if spec else ("in-design", "tech-lead")), page)
        frontmatter, body = _parse_markdown(page)
        frontmatter["revalidation"] = ["specification", "design", "technical-design"] if spec else ["design", "technical-design"]
        frontmatter["app-revalidation"] = {app: ALL_DOMAINS for app in APPS}
        if spec:
            frontmatter.pop("design-tracks", None)
            frontmatter.pop("design-reaffirm", None)
        else:
            affected = [item.strip() for item in tracks.split(",") if item.strip() in {"ui", "technical"}]
            old = dict(frontmatter["design-tracks"])
            new: dict = {}
            reaffirm: list[str] = []
            for track in ("ui", "technical"):
                if track in affected:
                    new[track] = "pending"
                else:
                    new[track] = old[track]
                    if old[track] == "done":
                        reaffirm.append(track)
            for track in ("ui", "technical"):
                if new[track] == "not-applicable" and f"{track}-reason" in old:
                    new[f"{track}-reason"] = old[f"{track}-reason"]
            frontmatter["design-tracks"] = new
            frontmatter["design-reaffirm"] = reaffirm
        page = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        changes = [{"path": FEATURE, "content": page}]
        changes += [{"path": requirement_path(app), "content": _set_requirement_status(self.read(requirement_path(app)), "in-progress")} for app in APPS]
        if mutate is not None:
            mutate(changes)
        return changes

    def dev_changes(self, apps: tuple[str, ...], *, reaffirm: bool = True, mutate=None) -> list[dict[str, str]]:
        """`reopen-dev` of `apps`: their rows (and the integration rows that name them) are archived; the rows of the other apps stay, quoted as reaffirmed."""

        evidence = self.evidence()
        wanted = set(apps)
        archived = [("Delivery evidence", line(row.cells)) for row in evidence.delivery if row.app in wanted]
        archived += [("QA verification", line(row.cells)) for row in evidence.qa if wanted & set(row.apps)]
        archived += [("Release", line(row.cells)) for row in evidence.release if row.app in wanted]
        kept = {
            "Delivery evidence": [line(row.cells) for row in evidence.delivery if row.app not in wanted],
            "QA verification": [line(row.cells) for row in evidence.qa if not wanted & set(row.apps)],
            "Release": [line(row.cells) for row in evidence.release if row.app not in wanted],
        }
        quoted = [f"  | {section} | {row.strip().strip('|').strip()} |" for section, rows in kept.items() for row in rows] if reaffirm else []
        invalidations = ", ".join(f"{requirement_path(app)}: done -> in-progress" for app in apps)
        entry = history_entry(
            "reopen-dev",
            affected=", ".join(apps),
            archived=archived,
            invalidations=invalidations,
            reaffirmed=("\n" + "\n".join(quoted)) if quoted else "none",
            reason="The renderer fails for right-to-left text.",
        )
        page = self.empty(self.read(FEATURE), kept)
        page = append_history(page, entry)
        page = self.with_status("in-dev", "dev", page)
        frontmatter, body = _parse_markdown(page)
        frontmatter["app-revalidation"] = {app: ALL_DOMAINS for app in apps}
        page = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        changes = [{"path": FEATURE, "content": page}]
        changes += [{"path": requirement_path(app), "content": _set_requirement_status(self.read(requirement_path(app)), "in-progress")} for app in apps]
        if mutate is not None:
            mutate(changes)
        return changes


class ReopenTests(ReopenBoard):
    def test_reopen_spec_archives_every_row_and_sends_the_feature_to_the_product_owner(self) -> None:
        self.seed_tracks()
        preview = self.apply("feature-reopen", self.reopen_changes("reopen-spec"), approver=self.owner)
        self.assertEqual("reopen-spec", preview["action"])
        self.assertEqual({"all_of": ["po"], "any_of": []}, preview["approval"]["required_roles"])
        self.assertEqual(("specified", "po"), self.status())
        frontmatter = self.feature()[0]
        self.assertEqual(["specification", "design", "technical-design"], frontmatter["revalidation"])
        self.assertNotIn("design-tracks", frontmatter)
        evidence = self.evidence()
        self.assertEqual(([], [], []), (list(evidence.delivery), list(evidence.qa), list(evidence.release)))
        self.assertIn("reopen-spec", self.read(FEATURE))
        self.assertIn("status: in-progress", self.read(requirement_path("backend")))
        self.assertEqual(set(), {code for code in self.errors() if code != "unresolved-open-questions"})

    def test_reopen_design_resets_the_affected_track_and_reaffirms_the_other(self) -> None:
        self.seed_tracks({"ui": "done", "technical": "done"})
        preview = self.apply("feature-reopen", self.reopen_changes("reopen-design", tracks="technical"), approver=self.owner)
        self.assertEqual("reopen-design", preview["action"])
        self.assertEqual(("in-design", "tech-lead"), self.status())
        frontmatter = self.feature()[0]
        self.assertEqual({"ui": "done", "technical": "pending"}, frontmatter["design-tracks"])
        self.assertEqual(["ui"], frontmatter["design-reaffirm"])
        self.assertEqual({app: ALL_DOMAINS for app in APPS}, frontmatter["app-revalidation"])

    def test_the_design_route_names_the_tracks_it_sends_back(self) -> None:
        self.seed_tracks()
        error = self.refused("feature-reopen", self.reopen_changes("reopen-design", tracks="none"), approver=self.owner)
        self.assertEqual("impact_review_required", error.code)

    def test_reopen_dev_of_both_apps_archives_everything_and_returns_to_development(self) -> None:
        preview = self.apply("feature-reopen", self.dev_changes(APPS), approver=self.owner)
        self.assertEqual("reopen-dev", preview["action"])
        self.assertEqual({"all_of": ["dev"], "any_of": []}, preview["approval"]["required_roles"])
        self.assertEqual(("in-dev", "dev"), self.status())
        evidence = self.evidence()
        self.assertEqual(([], [], []), (list(evidence.delivery), list(evidence.qa), list(evidence.release)))
        self.assertEqual({app: ALL_DOMAINS for app in APPS}, self.feature()[0]["app-revalidation"])
        self.assertEqual(["REL-001.md"], self.records(), "the record of the reopened release stays as history")
        self.assertEqual(set(), {code for code in self.errors() if code != "unresolved-open-questions"})

    def test_reopen_dev_of_one_app_reaffirms_the_rows_of_the_other(self) -> None:
        self.apply("feature-reopen", self.dev_changes(("backend",)), approver=self.owner)
        self.assertEqual(("in-dev", "dev"), self.status())
        evidence = self.evidence()
        self.assertEqual(["worker"], [row.app for row in evidence.delivery])
        self.assertEqual(["worker"], [row.app for row in evidence.release])
        self.assertEqual({"backend": ALL_DOMAINS}, self.feature()[0]["app-revalidation"])
        self.assertEqual("released", evidence.authoritative_release("worker").outcome)
        self.assertIn("backend: in-dev; worker: released", self.read("knowledge/wiki/status-board.md"))
        self.assertEqual(set(), {code for code in self.errors() if code != "unresolved-open-questions"})

    def test_reopen_dev_quotes_the_rows_that_stay(self) -> None:
        error = self.refused("feature-reopen", self.dev_changes(("backend",), reaffirm=False), approver=self.owner)
        self.assertEqual(("delivery_evidence_not_reaffirmed", 409), (error.code, error.status))

    def test_reopen_dev_gives_the_reopened_apps_all_four_domains(self) -> None:
        def narrow(changes: list[dict[str, str]]) -> None:
            frontmatter, body = _parse_markdown(changes[0]["content"])
            frontmatter["app-revalidation"] = {"backend": ["implementation"]}
            changes[0]["content"] = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"

        error = self.refused("feature-reopen", self.dev_changes(("backend",), mutate=narrow), approver=self.owner)
        self.assertEqual(("revalidation_required", 409), (error.code, error.status))

    def test_the_reopen_needs_an_evidence_history_entry_that_archives_the_rows(self) -> None:
        def drop_entry(changes: list[dict[str, str]]) -> None:
            page = changes[0]["content"]
            changes[0]["content"] = page[: page.index("### ")]

        error = self.refused("feature-reopen", self.reopen_changes("reopen-spec", mutate=drop_entry), approver=self.owner)
        self.assertIn(error.code, {"history_entry_required", "reopen_route_required"})
        self.assertEqual(409, error.status)

    def test_a_reopen_is_requested_by_a_human_with_the_role_of_its_destination(self) -> None:
        preview = self.ready("feature-reopen", self.dev_changes(APPS))
        self.assertEqual({"all_of": ["dev"], "any_of": []}, preview["approval"]["required_roles"])
        error = self.refused("feature-reopen", self.dev_changes(APPS), approver=self.pat)
        self.assertIn(error.status, {403, 404, 409})
        self.assertEqual(("released", "none"), self.status())


class ReopenRouteTests(ReleaseTests):
    def test_a_feature_that_is_not_released_has_no_reopen_route(self) -> None:
        # The feature waits for release; a reopen route needs `released`.
        page = self.with_status("in-dev", "dev")
        error = self.refused("feature-reopen", [{"path": FEATURE, "content": page}], approver=self.owner)
        self.assertEqual(409, error.status)
        self.assertNotEqual("action_unavailable", error.code)


if __name__ == "__main__":
    unittest.main()
