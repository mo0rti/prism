"""`release-done` ships verified bugs (CONTRACTS B14): with their feature, alone, and as the fix of a released feature (cases 10.2 and 10.3)."""

from __future__ import annotations

import unittest

from tests.release_support import (
    BUGS,
    FEATURE,
    FIX_HEADER,
    RELEASE_HEADER,
    VERIFICATION_HEADER,
    ReleaseTests,
    bug_page,
    delivery,
    fix_row,
    record_page,
    record_path,
    release_row,
    table,
    verification_row,
)

BUG = f"{BUGS}/BUG-001-summary-export-drops-comments.md"
BUG_TWO = f"{BUGS}/BUG-002-worker-restart-loses-jobs.md"


class ReleaseBugTests(ReleaseTests):
    def verified(self, bug_id: str = "BUG-001", apps: tuple[str, ...] = ("backend",), artifact: str = "build:backend#1", feature: str = "F-001", **kwargs: object) -> str:
        fix = table(FIX_HEADER, [fix_row(app, artifact if app == "backend" else f"build:{app}#1") for app in apps])
        verification = table(VERIFICATION_HEADER, [verification_row(app, artifact if app == "backend" else f"build:{app}#1") for app in apps])
        return bug_page(bug_id, status="verified", apps=list(apps), feature=feature, fix=fix, verification=verification, **kwargs)  # type: ignore[arg-type]

    def released_bug(self, release_rows: list[str], bug_id: str = "BUG-001", apps: tuple[str, ...] = ("backend",), artifact: str = "build:backend#1", feature: str = "F-001", status: str = "released") -> str:
        return self.verified(bug_id, apps, artifact, feature, release=table(RELEASE_HEADER, release_rows)).replace("status: verified", f"status: {status}").replace(
            "owner: release", "owner: none" if status == "released" else "owner: release"
        )

    # -- a bug ships with its feature -------------------------------------------------------------------------------------

    def test_a_verified_bug_of_the_feature_ships_with_the_release_of_its_app(self) -> None:
        self.put(BUG, self.verified())
        feature, record = self.all_released()
        self.assertEqual(("verified_bug_not_included", 409), self.refuse(feature, record))

    def test_a_bug_released_with_its_feature_is_released_and_listed_in_the_record(self) -> None:
        self.put(BUG, self.verified())
        feature = self.released_page([release_row("backend", 1), release_row("worker", 1)])
        record = record_page(1, [delivery("F-001", "backend"), delivery("BUG-001", "backend"), delivery("F-001", "worker")], bugs=["BUG-001"])
        bug = self.released_bug([release_row("backend", 1)])
        self.apply("release-done", [{"path": FEATURE, "content": feature}, {"path": BUG, "content": bug}, {"path": record_path(1), "content": record}], approver=self.owner)
        self.assertEqual(("released", "none"), self.status())
        self.assertIn("status: released", self.read(BUG))
        self.assertIn("owner: none", self.read(BUG))
        self.assertEqual(set(), self.errors())

    def test_a_bug_row_follows_the_bug_verification_and_its_own_attempt(self) -> None:
        self.put(BUG, self.verified())
        feature = self.released_page([release_row("backend", 1), release_row("worker", 1)])
        record = record_page(1, [delivery("F-001", "backend"), delivery("BUG-001", "backend"), delivery("F-001", "worker")], bugs=["BUG-001"])
        cases = {
            "wrong version": (self.released_bug([release_row("backend", 1, version="build:backend#7")]), "release_version_not_verified"),
            "wrong attempt": (self.released_bug([release_row("backend", 1, attempt=2)]), "release_attempt_mismatch"),
            "wrong target": (self.released_bug([release_row("backend", 1, target="staging-x")]), "release_target_mismatch"),
            "wrong record": (self.released_bug([release_row("backend", 9)]), "release_row_invalid"),
        }
        for name, (bug, code) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(
                    (code, 409),
                    self.refusal([{"path": FEATURE, "content": feature}, {"path": BUG, "content": bug}, {"path": record_path(1), "content": record}]),
                )

    def test_a_bug_that_is_not_verified_cannot_be_released(self) -> None:
        self.put(BUG, bug_page("BUG-001", status="fixed", apps=["backend"], fix=table(FIX_HEADER, [fix_row("backend", "build:backend#1")])))
        feature, record = self.all_released()
        bug = self.released_bug([release_row("backend", 1)])
        record = record_page(1, [delivery("F-001", "backend"), delivery("BUG-001", "backend"), delivery("F-001", "worker")], bugs=["BUG-001"])
        self.assertEqual(
            ("unsupported_source_pair", 409),
            self.refusal([{"path": FEATURE, "content": feature}, {"path": BUG, "content": bug}, {"path": record_path(1), "content": record}]),
        )

    def test_a_bug_release_changes_only_its_status_owner_and_release_rows(self) -> None:
        self.put(BUG, self.verified())
        feature = self.released_page([release_row("backend", 1), release_row("worker", 1)])
        record = record_page(1, [delivery("F-001", "backend"), delivery("BUG-001", "backend"), delivery("F-001", "worker")], bugs=["BUG-001"])
        retitled = self.released_bug([release_row("backend", 1)]).replace("severity: high", "severity: low")
        self.assertEqual(
            ("bug_frontmatter_scope", 409),
            self.refusal([{"path": FEATURE, "content": feature}, {"path": BUG, "content": retitled}, {"path": record_path(1), "content": record}]),
        )
        edited = self.released_bug([release_row("backend", 1)]).replace("The exported summary drops reviewer comments.", "It works.")
        code, status = self.refusal([{"path": FEATURE, "content": feature}, {"path": BUG, "content": edited}, {"path": record_path(1), "content": record}])
        self.assertEqual(409, status)
        self.assertIn("scope", code)

    # -- a bug alone (feature: none) -------------------------------------------------------------------------------------

    def test_a_bug_without_a_feature_is_released_alone(self) -> None:
        self.put(BUG, self.verified(feature="none"))
        feature = self.read(FEATURE)
        bug = self.released_bug([release_row("backend", 1)], feature="none")
        record = record_page(1, [delivery("BUG-001", "backend")], features=[], bugs=["BUG-001"], title="Hotfix of BUG-001", summary="BUG-001 is delivered to production.")
        preview = self.apply("release-done", [{"path": BUG, "content": bug}, {"path": record_path(1), "content": record}], approver=self.owner)
        self.assertEqual("release-done", preview["action"])
        self.assertEqual(("ready-for-release", "release"), self.status())
        self.assertEqual(feature, self.read(FEATURE))
        self.assertIn("status: released", self.read(BUG))
        self.assertEqual(set(), self.errors())

    def test_a_bug_with_two_apps_stays_verified_until_every_app_is_released(self) -> None:
        self.put(BUG, self.verified(apps=("backend", "worker"), feature="none"))
        failed = [release_row("backend", 1)]
        partial = self.released_bug(failed, apps=("backend", "worker"), feature="none", status="verified")
        rows = [delivery("BUG-001", "backend"), delivery("BUG-001", "worker", outcome="failed", evidence="deployment: https://ci.example/deploy/aborted-3")]
        record = record_page(1, rows, features=[], bugs=["BUG-001"], title="Hotfix of BUG-001", summary="BUG-001 is delivered to production.")
        bug = partial.replace(
            table(RELEASE_HEADER, failed),
            table(RELEASE_HEADER, [release_row("backend", 1), release_row("worker", 1, outcome="failed")]),
        )
        self.apply("release-done", [{"path": BUG, "content": bug}, {"path": record_path(1), "content": record}], approver=self.owner)
        self.assertIn("status: verified", self.read(BUG))
        self.assertIn("owner: release", self.read(BUG))
        # The retry settles the worker and the bug becomes released.
        done = self.released_bug([release_row("backend", 1), release_row("worker", 2, attempt=2)], apps=("backend", "worker"), feature="none")
        retry = record_page(2, [delivery("BUG-001", "worker", attempt=2)], features=[], bugs=["BUG-001"], title="Retry of BUG-001", summary="BUG-001 is delivered to production.", retry_of="REL-001")
        self.apply("release-done", [{"path": BUG, "content": done}, {"path": record_path(2), "content": retry}], approver=self.owner)
        self.assertIn("status: released", self.read(BUG))
        self.assertEqual(set(), self.errors())

    def test_a_bug_left_verified_after_an_all_released_row_set_is_refused(self) -> None:
        self.put(BUG, self.verified(feature="none"))
        stuck = self.released_bug([release_row("backend", 1)], feature="none", status="verified")
        record = record_page(1, [delivery("BUG-001", "backend")], features=[], bugs=["BUG-001"], title="Hotfix of BUG-001", summary="BUG-001 is delivered to production.")
        self.assertEqual(("invalid_transition_target", 409), self.refusal([{"path": BUG, "content": stuck}, {"path": record_path(1), "content": record}]))

    # -- a bug linked to a feature that is not released --------------------------------------------------------------------

    def test_a_bug_of_an_unreleased_feature_app_is_released_with_the_feature(self) -> None:
        self.put(BUG, self.verified())
        bug = self.released_bug([release_row("backend", 1)])
        record = record_page(1, [delivery("BUG-001", "backend")], features=[], bugs=["BUG-001"], title="Hotfix of BUG-001", summary="BUG-001 is delivered to production.")
        self.assertEqual(("bug_release_requires_feature", 409), self.refusal([{"path": BUG, "content": bug}, {"path": record_path(1), "content": record}]))

    # -- a fix of a released feature ---------------------------------------------------------------------------------------

    def test_a_bug_fix_updates_the_release_row_of_the_released_feature(self) -> None:
        self.release()
        self.put(BUG, self.verified(artifact="build:backend#2"))
        fixed_row = release_row("backend", 2, version="build:backend#2")
        # The feature app keeps its target, attempt and outcome; it changes the version and the record it names.
        old = self.evidence()
        self.assertEqual(1, old.authoritative_release("backend").attempt)
        feature = self.read(FEATURE).replace(release_row("backend", 1), fixed_row)
        bug = self.released_bug([release_row("backend", 2, version="build:backend#2")], artifact="build:backend#2")
        record = record_page(2, [delivery("BUG-001", "backend", version="build:backend#2")], features=[], bugs=["BUG-001"], title="Hotfix of BUG-001", summary="BUG-001 is delivered to production.")
        self.apply("release-done", [{"path": FEATURE, "content": feature}, {"path": BUG, "content": bug}, {"path": record_path(2), "content": record}], approver=self.owner)
        self.assertEqual(("released", "none"), self.status())
        row = self.evidence().authoritative_release("backend")
        self.assertEqual("build:backend#2", row.version.strip("`"))
        self.assertIn("REL-002", row.record)
        self.assertEqual(1, row.attempt)
        self.assertEqual(set(), self.errors())

    def test_a_bug_fix_of_a_released_feature_must_update_the_feature_row(self) -> None:
        self.release()
        self.put(BUG, self.verified(artifact="build:backend#2"))
        bug = self.released_bug([release_row("backend", 2, version="build:backend#2")], artifact="build:backend#2")
        record = record_page(2, [delivery("BUG-001", "backend", version="build:backend#2")], features=[], bugs=["BUG-001"], title="Hotfix of BUG-001", summary="BUG-001 is delivered to production.")
        self.assertEqual(("release_row_invalid", 409), self.refusal([{"path": BUG, "content": bug}, {"path": record_path(2), "content": record}]))

    def test_a_bug_fix_keeps_the_target_attempt_and_outcome_of_the_row(self) -> None:
        self.release()
        self.put(BUG, self.verified(artifact="build:backend#2"))
        bug = self.released_bug([release_row("backend", 2, version="build:backend#2")], artifact="build:backend#2")
        record = record_page(2, [delivery("BUG-001", "backend", version="build:backend#2")], features=[], bugs=["BUG-001"], title="Hotfix of BUG-001", summary="BUG-001 is delivered to production.")
        wrong_attempt = self.read(FEATURE).replace(release_row("backend", 1), release_row("backend", 2, version="build:backend#2", attempt=2))
        self.assertEqual(
            ("release_row_invalid", 409),
            self.refusal([{"path": FEATURE, "content": wrong_attempt}, {"path": BUG, "content": bug}, {"path": record_path(2), "content": record}]),
        )
        wrong_version = self.read(FEATURE).replace(release_row("backend", 1), release_row("backend", 2, version="build:backend#9"))
        self.assertEqual(
            ("release_version_not_verified", 409),
            self.refusal([{"path": FEATURE, "content": wrong_version}, {"path": BUG, "content": bug}, {"path": record_path(2), "content": record}]),
        )


if __name__ == "__main__":
    unittest.main()
