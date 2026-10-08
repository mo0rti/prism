"""The routes back from QA through `feature-reopen`: `qa-return-spec` and `qa-return-design` (CONTRACTS F16, F17)."""

from __future__ import annotations

import unittest

import yaml

from prism_cli.wiki_lint import lint_wiki
from tests.qa_support import (
    FEATURE,
    QaBoard,
    app_row,
    append_history,
    history_entry,
    integration_row,
    release_row,
    requirement_path,
)
from tests.test_board_service import _set_requirement_status
from tests.test_lifecycle_model import DELIVERY_HEADER, table

ALL_DOMAINS = ["implementation", "tests", "qa", "release"]
TRACKS = {"ui": "not-applicable", "ui-reason": "No app in scope has a UI.", "technical": "done"}


def line(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


class ReturnTests(QaBoard):
    def seed_tracks(self, tracks: dict | None = None, reaffirm: list[str] | None = None) -> None:
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), **{"design-tracks": tracks or TRACKS, "design-reaffirm": reaffirm or []}))

    def every_row(self) -> list[tuple[str, str]]:
        evidence = self.evidence()
        return (
            [("Delivery evidence", line(row.cells)) for row in evidence.delivery]
            + [("QA verification", line(row.cells)) for row in evidence.qa]
            + [("Release", line(row.cells)) for row in evidence.release]
        )

    def return_changes(self, action: str, *, tracks: str = "ui, technical", mutate=None) -> list[dict[str, str]]:
        spec = action == "qa-return-spec"
        page = self.read(FEATURE)
        for heading, headers in (("Delivery evidence", DELIVERY_HEADER),):
            page = self.with_section(heading, table(headers, []), page)
        page = self.qa_table([], page)
        page = self.release_table([], page)
        done = [app for app in ("backend", "worker") if "status: done" in self.read(requirement_path(app))]
        invalidations = ", ".join(f"{requirement_path(app)}: done -> in-progress" for app in done) or "No requirement or API page is invalidated."
        entry = history_entry(action, affected="backend, worker", archived=self.every_row(), tracks=tracks, invalidations=invalidations)
        page = append_history(page, entry)
        status, owner = ("specified", "po") if spec else ("in-design", "tech-lead")
        page = self.with_status(status, owner, page)
        frontmatter, body = self.parts(page)
        frontmatter["revalidation"] = ["specification", "design", "technical-design"] if spec else ["design", "technical-design"]
        frontmatter["app-revalidation"] = {"backend": ALL_DOMAINS, "worker": ALL_DOMAINS}
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
        changes += [{"path": requirement_path(app), "content": _set_requirement_status(self.read(requirement_path(app)), "in-progress")} for app in done]
        if mutate is not None:
            mutate(changes)
        return changes

    def history_text(self) -> str:
        from prism_cli.wiki_model import section_text

        return section_text(self.feature()[1], "Evidence history")

    def parts(self, content: str):
        from prism_cli.board_service import _parse_markdown

        return _parse_markdown(content)

    def errors(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def test_qa_return_spec_archives_every_row_and_sends_the_feature_to_the_product_owner(self) -> None:
        page = self.qa_table([app_row("backend"), integration_row()])
        self.apply("qa-verify", [{"path": FEATURE, "content": self.with_status("in-qa", "qa", page)}])
        self.seed_tracks()
        preview = self.apply("feature-reopen", self.return_changes("qa-return-spec"))
        self.assertEqual("qa-return-spec", preview["action"])
        self.assertEqual({"all_of": ["qa"], "any_of": []}, preview["approval"]["required_roles"])
        self.assertEqual(("specified", "po"), self.status())
        frontmatter = self.feature()[0]
        self.assertEqual(["specification", "design", "technical-design"], frontmatter["revalidation"])
        self.assertNotIn("design-tracks", frontmatter)
        evidence = self.evidence()
        self.assertEqual(([], [], []), (list(evidence.delivery), list(evidence.qa), list(evidence.release)))
        self.assertIn("status: in-progress", self.read(requirement_path("backend")))
        self.assertEqual(set(), {code for code in self.errors() if code != "unresolved-open-questions"})

    def test_qa_return_design_resets_the_affected_track_and_reaffirms_the_other(self) -> None:
        self.seed_tracks({"ui": "done", "technical": "done"})
        preview = self.apply("feature-reopen", self.return_changes("qa-return-design", tracks="technical"))
        self.assertEqual("qa-return-design", preview["action"])
        self.assertEqual(("in-design", "tech-lead"), self.status())
        frontmatter = self.feature()[0]
        self.assertEqual({"ui": "done", "technical": "pending"}, frontmatter["design-tracks"])
        self.assertEqual(["ui"], frontmatter["design-reaffirm"])
        self.assertEqual(["design", "technical-design"], frontmatter["revalidation"])
        self.assertEqual({"backend": ALL_DOMAINS, "worker": ALL_DOMAINS}, frontmatter["app-revalidation"])

    def test_a_track_that_is_not_applicable_stays_so_and_is_not_reaffirmed(self) -> None:
        self.seed_tracks(TRACKS)
        self.apply("feature-reopen", self.return_changes("qa-return-design", tracks="technical"))
        frontmatter = self.feature()[0]
        self.assertEqual({"ui": "not-applicable", "technical": "pending", "ui-reason": "No app in scope has a UI."}, frontmatter["design-tracks"])
        self.assertEqual([], frontmatter["design-reaffirm"])

    def test_the_design_route_names_the_tracks_it_sends_back(self) -> None:
        self.seed_tracks()
        error = self.refused("feature-reopen", self.return_changes("qa-return-design", tracks="none"))
        self.assertEqual("impact_review_required", error.code)

    def test_the_tracks_are_written_exactly(self) -> None:
        self.seed_tracks({"ui": "done", "technical": "done"})

        def wrong(changes):
            changes[0]["content"] = self.frontmatter_with(changes[0]["content"], **{"design-reaffirm": []})

        self.assertEqual("track_scope", self.refused("feature-reopen", self.return_changes("qa-return-design", tracks="technical", mutate=wrong)).code)

    def test_a_feature_without_tracks_cannot_return_to_design(self) -> None:
        self.seed_tracks()
        changes = self.return_changes("qa-return-design")
        frontmatter, body = self.parts(self.read(FEATURE))
        del frontmatter["design-tracks"], frontmatter["design-reaffirm"]
        self.put(FEATURE, f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}")
        self.assertEqual("design_tracks_missing", self.refused("feature-reopen", changes).code)

    def test_the_whole_evidence_is_archived(self) -> None:
        self.seed_tracks()
        changes = self.return_changes("qa-return-spec")
        # A row of the active tables that the entry does not copy is not archived.
        lines = changes[0]["content"].splitlines(keepends=True)
        kept = "".join(item for item in lines if not item.startswith("  | Delivery evidence | worker"))
        self.assertEqual("evidence_not_archived", self.refused("feature-reopen", [{"path": FEATURE, "content": kept}, *changes[1:]]).code)
        # A row that stays in its table while the entry archives it is still active.
        stays = self.with_section("Delivery evidence", table(DELIVERY_HEADER, [line(row.cells) for row in self.evidence().delivery[:1]]), changes[0]["content"])
        self.assertEqual("evidence_still_active", self.refused("feature-reopen", [{"path": FEATURE, "content": stays}, *changes[1:]]).code)
        entry_less = self.with_section("Evidence history", "", changes[0]["content"])
        self.assertEqual("history_entry_required", self.refused("feature-reopen", [{"path": FEATURE, "content": entry_less}, *changes[1:]]).code)

    def test_the_revalidation_domains_are_written_exactly(self) -> None:
        self.seed_tracks()

        def wrong(changes):
            changes[0]["content"] = self.frontmatter_with(changes[0]["content"], revalidation=["specification"])

        self.assertEqual("revalidation_required", self.refused("feature-reopen", self.return_changes("qa-return-spec", mutate=wrong)).code)

        def apps(changes):
            changes[0]["content"] = self.frontmatter_with(changes[0]["content"], **{"app-revalidation": {"backend": ALL_DOMAINS}})

        self.assertEqual("revalidation_required", self.refused("feature-reopen", self.return_changes("qa-return-spec", mutate=apps)).code)

    def test_every_done_requirement_page_goes_back(self) -> None:
        self.seed_tracks()
        changes = self.return_changes("qa-return-spec")
        self.assertEqual("reopen_invalidation_mismatch", self.refused("feature-reopen", changes[:2]).code)

    def test_a_feature_with_a_released_app_cannot_return(self) -> None:
        released = "| backend | production | `build:backend#1` | release-1 | released | [REL-001](https://records.example/REL-001) | checked |"
        page = self.release_table([released], self.qa_table([app_row("backend"), integration_row()]))
        self.put(FEATURE, self.frontmatter_with(self.with_status("ready-for-qa", "qa", page), **{"design-tracks": TRACKS, "design-reaffirm": []}))
        for action in ("qa-return-spec", "qa-return-design"):
            with self.subTest(action=action):
                self.assertEqual("partial_release_requires_new_feature", self.refused("feature-reopen", self.return_changes(action)).code)

    def test_a_feature_in_development_returns_by_qa_only_when_an_app_is_in_qa(self) -> None:
        # worker is sent back, so the feature is in-dev while backend is still ready-for-qa.
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}])
        self.apply("qa-fail", self.fail_worker_changes())
        self.assertEqual(("in-dev", "dev"), self.status())
        self.seed_tracks()
        self.apply("feature-reopen", self.return_changes("qa-return-spec"))
        self.assertEqual(("specified", "po"), self.status())

    def test_a_feature_in_development_with_no_app_in_qa_returns_through_the_development_route(self) -> None:
        page = self.with_section("Delivery evidence", table(DELIVERY_HEADER, []), self.with_status("in-dev", "dev"))
        self.put(FEATURE, self.frontmatter_with(page, **{"design-tracks": TRACKS, "design-reaffirm": []}))
        error = self.refused("feature-reopen", [{"path": FEATURE, "content": self.with_status("specified", "po", self.read(FEATURE))}])
        self.assertIn(error.code, {"app_stage_mismatch", "action_unavailable"})

    def fail_worker_changes(self) -> list[dict[str, str]]:
        evidence = self.evidence()
        archive = [("Delivery evidence", line(row.cells)) for row in evidence.delivery if row.app == "worker"]
        archive += [("QA verification", line(row.cells)) for row in evidence.qa if "worker" in row.apps]
        page = self.with_section("Delivery evidence", table(DELIVERY_HEADER, [line(row.cells) for row in evidence.delivery if row.app != "worker"]))
        page = self.qa_table([], page)
        entry = history_entry("qa-fail", affected="worker", archived=archive, invalidations=f"{requirement_path('worker')}: done -> in-progress")
        page = self.frontmatter_with(self.with_status("in-dev", "dev", append_history(page, entry)), **{"app-revalidation": {"worker": ALL_DOMAINS}})
        return [{"path": FEATURE, "content": page}, {"path": requirement_path("worker"), "content": _set_requirement_status(self.read(requirement_path("worker")), "in-progress")}]


if __name__ == "__main__":
    unittest.main()
