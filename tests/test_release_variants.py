"""The variants of `release-done`: the return to development, the rollback and the redeploy (CONTRACTS F20 to F22; cases 10.1 to 10.3)."""

from __future__ import annotations

import unittest

from prism_cli.wiki_releases import read_release_records, record_kinds, release_attempt_of
from tests.qa_support import DELIVERY_HEADER, QA_HEADER, RELEASE_HEADER, append_history, history_entry, requirement_path
from tests.release_support import (
    FEATURE,
    FEATURE_TWO,
    ReleaseTests,
    ReleaseTwoFeatures,
    delivery,
    record_page,
    record_path,
    table,
)
from tests.test_board_service import _set_requirement_status

ALL_DOMAINS = ["implementation", "tests", "qa", "release"]
FAILED_EVIDENCE = "deployment: https://ci.example/deploy/aborted-9"


def line(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


class ReleaseReturnTests(ReleaseTests):
    def return_changes(self, apps: list[str], *, participants: list[str] | None = None, mutate=None, rows: list[str] | None = None) -> list[dict[str, str]]:
        """`release-return-dev` for `apps`: the failed delivery in a record, the apps' rows archived and the feature back in development."""

        evidence = self.evidence()
        named = set(apps)
        lost = set(participants or [])
        archive = [("Delivery evidence", line(row.cells)) for row in evidence.delivery if row.app in named]
        archive += [("QA verification", line(row.cells)) for row in evidence.qa if named & set(row.apps)]
        archive += [("Release", line(row.cells)) for row in evidence.release if row.app in named or row.app in lost]
        page = self.read(FEATURE)
        page = self.with_section("Delivery evidence", table(DELIVERY_HEADER, [line(row.cells) for row in evidence.delivery if row.app not in named]), page)
        page = self.qa_table([line(row.cells) for row in evidence.qa if not named & set(row.apps)], page)
        page = self.release_table([line(row.cells) for row in evidence.release if row.app not in named and row.app not in lost], page)
        invalidations = ", ".join(f"{requirement_path(app)}: done -> in-progress" for app in apps)
        entry = history_entry(
            "release-return-dev",
            affected=", ".join(apps),
            archived=archive,
            participants=", ".join(participants) if participants else "none",
            invalidations=invalidations,
            reason="The deployment of the rebuilt service was aborted by the health check.",
        )
        page = append_history(page, entry)
        domains = {app: list(ALL_DOMAINS) for app in apps}
        domains.update({app: ["qa", "release"] for app in participants or []})
        page = self.frontmatter_with(self.with_status("in-dev", "dev", page), **{"app-revalidation": domains})
        failed = rows if rows is not None else [delivery("F-001", app, outcome="failed", evidence=FAILED_EVIDENCE) for app in apps]
        changes = [{"path": FEATURE, "content": page}, {"path": record_path(1), "content": record_page(1, failed)}]
        changes += [{"path": requirement_path(app), "content": _set_requirement_status(self.read(requirement_path(app)), "in-progress")} for app in apps]
        if mutate is not None:
            mutate(changes)
        return changes

    def test_a_failed_release_returns_both_apps_to_development_with_a_record_of_the_failure(self) -> None:
        preview = self.apply("release-done", self.return_changes(["backend", "worker"]), approver=self.owner)
        self.assertEqual("release-return-dev", preview["action"])
        self.assertEqual(("in-dev", "dev"), self.status())
        evidence = self.evidence()
        self.assertEqual(([], [], []), (list(evidence.delivery), list(evidence.qa), list(evidence.release)))
        self.assertEqual("failed", self.record(1)[0]["outcome"])
        self.assertEqual({app: ALL_DOMAINS for app in ("backend", "worker")}, self.feature()[0]["app-revalidation"])
        self.assertIn("status: in-progress", self.read(requirement_path("backend")))
        self.assertEqual(set(), {code for code in self.errors() if code != "unresolved-open-questions"})

    def test_returning_one_app_takes_the_release_row_of_its_integration_partner(self) -> None:
        preview = self.apply("release-done", self.return_changes(["backend"], participants=["worker"]), approver=self.owner)
        self.assertEqual("release-return-dev", preview["action"])
        self.assertEqual(("in-dev", "dev"), self.status())
        self.assertEqual({"backend": ALL_DOMAINS, "worker": ["qa", "release"]}, self.feature()[0]["app-revalidation"])
        self.assertEqual(["worker"], [row.app for row in self.evidence().delivery])
        self.assertEqual([], [row.app for row in self.evidence().release])

    def test_a_retry_after_the_return_starts_at_attempt_two(self) -> None:
        self.apply("release-done", self.return_changes(["backend", "worker"]), approver=self.owner)
        records = read_release_records(self.root / "knowledge" / "wiki")
        kinds = record_kinds(records)
        self.assertEqual({"backend": 2, "worker": 2}, {app: release_attempt_of(records, kinds, "F-001", app) for app in ("backend", "worker")})

    def test_the_record_lists_the_failed_delivery_of_the_returned_apps_and_nothing_else(self) -> None:
        extra = [delivery("F-001", "backend", outcome="failed", evidence=FAILED_EVIDENCE), delivery("F-001", "worker", outcome="failed", evidence=FAILED_EVIDENCE)]
        error = self.refused("release-done", self.return_changes(["backend"], participants=["worker"], rows=extra), approver=self.owner)
        self.assertEqual(("release_record_mismatch", 409), (error.code, error.status))
        released = [delivery("F-001", "backend")]
        error = self.refused("release-done", self.return_changes(["backend"], participants=["worker"], rows=released), approver=self.owner)
        self.assertEqual(409, error.status)
        self.assertIn(error.code, {"release_record_mismatch", "release_record_invalid"})

    def test_the_return_needs_apps_that_are_ready_for_release(self) -> None:
        self.release()
        error = self.refused("release-done", self.return_changes(["backend"]), approver=self.owner)
        self.assertEqual(409, error.status)

    def test_the_return_keeps_the_fixed_destination(self) -> None:
        def to_qa(changes: list[dict[str, str]]) -> None:
            changes[0]["content"] = self.with_status("in-qa", "qa", changes[0]["content"])

        error = self.refused("release-done", self.return_changes(["backend", "worker"], mutate=to_qa), approver=self.owner)
        self.assertEqual(409, error.status)


class RollbackTests(ReleaseTests):
    def rollback_page(self, number: int, of: int, rows: list[str] | None = None, **kwargs: object) -> str:
        rows = rows if rows is not None else [delivery("F-001", "backend", outcome="rolled-back", attempt=None), delivery("F-001", "worker", outcome="rolled-back", attempt=None)]
        return record_page(
            number, rows, rollback_of=f"REL-{of:03d}", title=f"Rollback of REL-{of:03d}", summary="The release is rolled back.", rollback="The service was rolled back to the previous build after errors.", **kwargs  # type: ignore[arg-type]
        )

    def test_a_rollback_is_a_record_alone_and_leaves_the_feature_released(self) -> None:
        self.release()
        before = self.read(FEATURE)
        preview = self.apply("release-done", [{"path": record_path(2), "content": self.rollback_page(2, 1)}], approver=self.owner)
        self.assertEqual("release-rollback", preview["action"])
        self.assertEqual(before, self.read(FEATURE), "a feature row records its own delivery and is not rewritten by a rollback")
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual("rolled-back", self.record(2)[0]["outcome"])
        self.assertEqual("REL-001", self.record(2)[0]["rollback-of"])
        self.assertEqual(set(), self.errors())

    def test_a_rollback_binds_to_the_current_delivery(self) -> None:
        self.release()
        self.assertEqual(("rollback_target_invalid", 409), self.refusal([{"path": record_path(2), "content": self.rollback_page(2, 7)}]))
        self.apply("release-done", [{"path": record_path(2), "content": self.rollback_page(2, 1)}], approver=self.owner)
        # REL-001 is rolled back already, and a rollback is not rolled back.
        self.assertEqual(("rollback_target_invalid", 409), self.refusal([{"path": record_path(3), "content": self.rollback_page(3, 1)}]))
        self.assertEqual(("rollback_target_invalid", 409), self.refusal([{"path": record_path(3), "content": self.rollback_page(3, 2)}]))

    def test_a_rollback_may_roll_back_one_app_of_the_delivery(self) -> None:
        self.release()
        only_backend = self.rollback_page(2, 1, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)])
        self.apply("release-done", [{"path": record_path(2), "content": only_backend}], approver=self.owner)
        # The worker still has REL-001 as its current delivery; the backend has none, so it can be rolled back no further.
        worker = self.rollback_page(3, 1, [delivery("F-001", "worker", outcome="rolled-back", attempt=None)])
        self.apply("release-done", [{"path": record_path(3), "content": worker}], approver=self.owner)
        again = self.rollback_page(4, 1, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)])
        self.assertEqual(("rollback_target_invalid", 409), self.refusal([{"path": record_path(4), "content": again}]))

    def test_a_rollback_names_the_version_the_delivery_carried(self) -> None:
        self.release()
        wrong_version = self.rollback_page(
            2, 1, [delivery("F-001", "backend", outcome="rolled-back", attempt=None, version="build:backend#9"), delivery("F-001", "worker", outcome="rolled-back", attempt=None)]
        )
        code, status = self.refusal([{"path": record_path(2), "content": wrong_version}])
        self.assertEqual(409, status)
        self.assertIn(code, {"rollback_target_invalid", "release_record_invalid"})

    def test_a_rollback_says_what_it_rolled_back_and_why(self) -> None:
        self.release()
        blank = self.rollback_page(2, 1).replace("The service was rolled back to the previous build after errors.", "None.")
        error = self.refused("release-done", [{"path": record_path(2), "content": blank}], approver=self.owner)
        self.assertEqual(("release_record_invalid", 409), (error.code, error.status))

    def test_a_rollback_record_never_snapshots_a_contract(self) -> None:
        self.release()
        page = self.rollback_page(2, 1, contracts="### F-001 backend\n\n- Contract: `F-001@v1:c1:" + "0" * 64 + "`\n\n````markdown\ntext\n````")
        self.assertEqual(("release_contract_snapshot_invalid", 409), self.refusal([{"path": record_path(2), "content": page}]))

    def test_a_rollback_changes_no_page_besides_its_record(self) -> None:
        self.release()
        changes = [{"path": record_path(2), "content": self.rollback_page(2, 1)}, {"path": FEATURE, "content": self.read(FEATURE)}]
        self.assertEqual(("lifecycle_write_scope", 409), self.refusal(changes))

    def test_a_rollback_rows_are_rolled_back_and_carry_no_attempt(self) -> None:
        self.release()
        released = self.rollback_page(
            2, 1, [delivery("F-001", "backend", outcome="released", attempt=None), delivery("F-001", "worker", outcome="released", attempt=None)]
        )
        code, status = self.refusal([{"path": record_path(2), "content": released}])
        self.assertEqual(409, status)
        self.assertIn(code, {"release_record_invalid", "rollback_target_invalid"})
        counted = self.rollback_page(2, 1, [delivery("F-001", "backend", outcome="rolled-back", attempt=1), delivery("F-001", "worker", outcome="rolled-back", attempt=1)])
        self.assertEqual(("release_record_invalid", 409), self.refusal([{"path": record_path(2), "content": counted}]))


class RedeployTests(ReleaseTests):
    def rollback(self, number: int = 2, of: int = 1) -> None:
        rows = [delivery("F-001", "backend", outcome="rolled-back", attempt=None), delivery("F-001", "worker", outcome="rolled-back", attempt=None)]
        page = record_page(number, rows, rollback_of=f"REL-{of:03d}", title="Rollback", summary="The release is rolled back.", rollback="Rolled back after errors.")
        self.apply("release-done", [{"path": record_path(number), "content": page}], approver=self.owner)

    def redeploy_page(self, number: int, of: int, outcome: str = "released", version: str | None = None, apps: tuple[str, ...] = ("backend", "worker")) -> str:
        rows = [delivery("F-001", app, outcome=outcome, attempt=None, version=None if app != "backend" else version) for app in apps]
        return record_page(number, rows, retry_of=f"REL-{of:03d}", title="Redeploy", summary="The delivery is redeployed.")

    def test_a_redeploy_follows_the_rollback_of_the_current_delivery(self) -> None:
        self.release()
        self.rollback()
        preview = self.apply("release-done", [{"path": record_path(3), "content": self.redeploy_page(3, 2)}], approver=self.owner)
        self.assertEqual("release-redeploy", preview["action"])
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(["REL-001.md", "REL-002.md", "REL-003.md"], self.records())
        self.assertEqual("released", self.record(3)[0]["outcome"])
        self.assertEqual(set(), self.errors())

    def test_a_redeploy_needs_a_rollback_or_a_failed_redeploy_to_retry(self) -> None:
        self.release()
        self.assertEqual(("app_stage_mismatch", 409), self.refusal([{"path": record_path(2), "content": self.redeploy_page(2, 1)}]))
        self.rollback()
        self.apply("release-done", [{"path": record_path(3), "content": self.redeploy_page(3, 2)}], approver=self.owner)
        # A redeploy that succeeded is not retried.
        self.assertEqual(("app_stage_mismatch", 409), self.refusal([{"path": record_path(4), "content": self.redeploy_page(4, 3)}]))

    def test_a_redeploy_delivers_the_version_of_the_current_delivery(self) -> None:
        self.release()
        self.rollback()
        self.assertEqual(("redeploy_version_mismatch", 409), self.refusal([{"path": record_path(3), "content": self.redeploy_page(3, 2, version="build:backend#9")}]))

    def test_a_redeploy_may_redeploy_one_app_of_the_rollback(self) -> None:
        self.release()
        self.rollback()
        self.apply("release-done", [{"path": record_path(3), "content": self.redeploy_page(3, 2, apps=("backend",))}], approver=self.owner)
        self.assertEqual("released", self.record(3)[0]["outcome"])

    def test_a_failed_redeploy_is_retried_by_another_redeploy(self) -> None:
        self.release()
        self.rollback()
        failed = [delivery("F-001", app, outcome="failed", attempt=None, evidence=FAILED_EVIDENCE) for app in ("backend", "worker")]
        self.apply("release-done", [{"path": record_path(3), "content": record_page(3, failed, retry_of="REL-002", title="Redeploy", summary="The delivery is redeployed.")}], approver=self.owner)
        self.assertEqual("failed", self.record(3)[0]["outcome"])
        self.apply("release-done", [{"path": record_path(4), "content": self.redeploy_page(4, 3)}], approver=self.owner)
        self.assertEqual("released", self.record(4)[0]["outcome"])
        self.assertEqual(set(), self.errors())

    def test_a_redeploy_binds_to_the_latest_record_of_the_app(self) -> None:
        self.release()
        self.rollback()
        # REL-002 is the latest record for both apps; the first release is not.
        self.assertEqual(("app_stage_mismatch", 409), self.refusal([{"path": record_path(3), "content": self.redeploy_page(3, 1)}]))

    def test_a_record_that_changes_no_page_and_retries_nothing_is_not_a_record_of_a_variant(self) -> None:
        self.release()
        page = self.redeploy_page(2, 1).replace("retry-of: REL-001\n", "")
        self.assertEqual(("release_record_invalid", 409), self.refusal([{"path": record_path(2), "content": page}]))

    def test_a_rollback_after_a_redeploy_binds_to_the_redeploy(self) -> None:
        self.release()
        self.rollback()
        self.apply("release-done", [{"path": record_path(3), "content": self.redeploy_page(3, 2)}], approver=self.owner)
        rows = [delivery("F-001", app, outcome="rolled-back", attempt=None) for app in ("backend", "worker")]
        stale = record_page(4, rows, rollback_of="REL-001", title="Rollback", summary="The release is rolled back.", rollback="Rolled back after errors.")
        self.assertEqual(("rollback_target_invalid", 409), self.refusal([{"path": record_path(4), "content": stale}]))
        current = record_page(4, rows, rollback_of="REL-003", title="Rollback", summary="The redeploy is rolled back.", rollback="Rolled back after errors.")
        self.apply("release-done", [{"path": record_path(4), "content": current}], approver=self.owner)
        self.assertEqual(set(), self.errors())


class CurrentDeliveryTests(ReleaseTwoFeatures):
    def test_the_current_delivery_of_an_app_is_global_to_its_target(self) -> None:
        self.release()
        second, record = self.second_released(2)
        self.apply("release-done", [{"path": FEATURE_TWO, "content": second}, {"path": record_path(2), "content": record}], approver=self.owner)
        # REL-002 delivered the backend later, so REL-001 is no longer its current delivery.
        rows = [delivery("F-001", "backend", outcome="rolled-back", attempt=None), delivery("F-001", "worker", outcome="rolled-back", attempt=None)]
        stale = record_page(3, rows, rollback_of="REL-001", title="Rollback", summary="The release is rolled back.", rollback="Rolled back.")
        error = self.refused("release-done", [{"path": record_path(3), "content": stale}], approver=self.owner)
        self.assertEqual(("rollback_target_invalid", 409), (error.code, error.status))
        rolled = [delivery("F-002", "backend", outcome="rolled-back", attempt=None, version=self.ARTIFACT_TWO)]
        current = record_page(3, rolled, features=["F-002"], rollback_of="REL-002", title="Rollback", summary="The release is rolled back.", rollback="Rolled back.")
        self.apply("release-done", [{"path": record_path(3), "content": current}], approver=self.owner)
        self.assertEqual("rolled-back", self.record(3)[0]["outcome"])

    def test_a_rollback_lists_all_the_items_of_a_shared_delivery(self) -> None:
        self.put(FEATURE_TWO, self.second_page("ready-for-release", "release", ["| backend | — | `build:backend#1` | release-1 | pending | — | — |"], "build:backend#1"))
        first, _record = self.all_released()
        second, _ = self.second_released(1, "build:backend#1")
        rows = [delivery("F-001", "backend"), delivery("F-001", "worker"), delivery("F-002", "backend")]
        shared = record_page(1, rows, features=["F-001", "F-002"], title="Release of F-001 and F-002", summary="F-001 and F-002 are delivered to production.")
        self.apply("release-done", [{"path": FEATURE, "content": first}, {"path": FEATURE_TWO, "content": second}, {"path": record_path(1), "content": shared}], approver=self.owner)
        only_one = [delivery("F-001", "backend", outcome="rolled-back", attempt=None), delivery("F-001", "worker", outcome="rolled-back", attempt=None)]
        partial = record_page(2, only_one, rollback_of="REL-001", title="Rollback", summary="The release is rolled back.", rollback="Rolled back.")
        self.assertEqual(("rollback_target_invalid", 409), self.refusal([{"path": record_path(2), "content": partial}]))
        every = only_one + [delivery("F-002", "backend", outcome="rolled-back", attempt=None, version="build:backend#1")]
        full = record_page(2, every, features=["F-001", "F-002"], rollback_of="REL-001", title="Rollback", summary="The release is rolled back.", rollback="Rolled back.")
        self.apply("release-done", [{"path": record_path(2), "content": full}], approver=self.owner)
        self.assertEqual(set(), self.errors())


if __name__ == "__main__":
    unittest.main()
