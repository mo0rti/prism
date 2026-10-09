"""Two features that share an app: the co-release, the dependency gate and the contract snapshot (CONTRACTS 6.2, 8.1; cases 10.1 and 10.3)."""

from __future__ import annotations

import unittest

from tests.release_support import (
    FEATURE,
    FEATURE_TWO,
    REQUIREMENT_TWO,
    ReleaseTwoFeatures,
    delivery,
    record_page,
    record_path,
    release_row,
)

REQUIREMENT_ONE = "knowledge/wiki/app-requirements/F-001-backend.md"


class CoReleaseTests(ReleaseTwoFeatures):
    def together(self, version_two: str | None = None, outcome_two: str = "released") -> list[dict[str, str]]:
        """F-001 (both apps) and F-002 (backend) released by one record."""

        version_two = version_two or self.ARTIFACT_TWO
        first, _record = self.all_released()
        second, _ = self.second_released(1, version_two, outcome=outcome_two)
        rows = [
            delivery("F-001", "backend"),
            delivery("F-001", "worker"),
            delivery("F-002", "backend", version=version_two, outcome=outcome_two),
        ]
        record = record_page(1, rows, features=["F-001", "F-002"], title="Release of F-001 and F-002", summary="F-001 and F-002 are delivered to production.")
        return [{"path": FEATURE, "content": first}, {"path": FEATURE_TWO, "content": second}, {"path": record_path(1), "content": record}]

    def test_two_features_that_share_an_app_release_one_version_of_it_together(self) -> None:
        # F-001 delivers `build:backend#1` and F-002 `build:backend#3`: one deployment delivers one version.
        self.assertEqual(("release_artifact_conflict", 409), self.refusal(self.together()))

    def test_two_features_on_the_same_artifact_release_together(self) -> None:
        # The second feature is rebuilt on the artifact of the first, so one deployment delivers both.
        self.put(FEATURE_TWO, self.second_page("ready-for-release", "release", [self.pending_for("build:backend#1")], "build:backend#1"))
        first, _record = self.all_released()
        second, _ = self.second_released(1, "build:backend#1")
        rows = [delivery("F-001", "backend"), delivery("F-001", "worker"), delivery("F-002", "backend")]
        record = record_page(1, rows, features=["F-001", "F-002"], title="Release of F-001 and F-002", summary="F-001 and F-002 are delivered to production.")
        self.apply(
            "release-done",
            [{"path": FEATURE, "content": first}, {"path": FEATURE_TWO, "content": second}, {"path": record_path(1), "content": record}],
            approver=self.owner,
        )
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(["REL-001.md"], self.records())
        self.assertEqual(set(), self.errors())
        self.assertIn("F-002", self.read(record_path(1)))

    def pending_for(self, artifact: str) -> str:
        return f"| backend | — | `{artifact}` | release-1 | pending | — | — |"

    def test_features_released_one_after_the_other_deliver_the_app_twice(self) -> None:
        self.release()
        second, record = self.second_released(2)
        self.apply("release-done", [{"path": FEATURE_TWO, "content": second}, {"path": record_path(2), "content": record}], approver=self.owner)
        self.assertEqual(["REL-001.md", "REL-002.md"], self.records())
        self.assertEqual(set(), self.errors())

    def test_the_attempt_counts_the_records_of_the_feature_only(self) -> None:
        # F-001 failed once, so its retry is attempt 2; F-002's first attempt on the same app stays attempt 1.
        failed = self.released_page([release_row("backend", 1, outcome="failed"), release_row("worker", 1)], status="ready-for-release", owner="release")
        first = record_page(1, [delivery("F-001", "backend", outcome="failed", evidence="deployment: https://ci.example/deploy/aborted-4"), delivery("F-001", "worker")])
        self.settle(failed, first)
        second, record = self.second_released(2)
        self.apply("release-done", [{"path": FEATURE_TWO, "content": second}, {"path": record_path(2), "content": record}], approver=self.owner)
        self.assertEqual("released", self.evidence_of(FEATURE_TWO).authoritative_release("backend").outcome)

    def evidence_of(self, path: str):
        from prism_cli.board_service import _parse_markdown
        from prism_cli.wiki_model import read_feature_evidence

        return read_feature_evidence(_parse_markdown(self.read(path))[1])

    def test_a_co_release_fails_or_succeeds_for_the_app_as_a_whole(self) -> None:
        self.put(FEATURE_TWO, self.second_page("ready-for-release", "release", [self.pending_for("build:backend#1")], "build:backend#1"))
        first, _record = self.all_released()
        second, _ = self.second_released(1, "build:backend#1", outcome="failed")
        rows = [delivery("F-001", "backend"), delivery("F-001", "worker"), delivery("F-002", "backend", outcome="failed")]
        record = record_page(1, rows, features=["F-001", "F-002"], title="Release of F-001 and F-002", summary="F-001 and F-002 are delivered to production.")
        self.assertEqual(
            ("release_artifact_conflict", 409),
            self.refusal([{"path": FEATURE, "content": first}, {"path": FEATURE_TWO, "content": second}, {"path": record_path(1), "content": record}]),
        )


class DependencyTests(ReleaseTwoFeatures):
    def depend(self) -> None:
        """The backend requirement of F-001 depends on F-002."""

        page = self.read(REQUIREMENT_ONE)
        self.put(REQUIREMENT_ONE, page.replace("The document review record is available to the assigned reviewer.", "This app needs F-002 to be delivered first."))

    def test_a_feature_cannot_release_before_the_feature_it_depends_on(self) -> None:
        self.depend()
        feature, record = self.all_released()
        self.assertEqual(("dependency_not_released", 409), self.refuse(feature, record))

    def test_a_feature_releases_after_its_dependency(self) -> None:
        self.depend()
        second, second_record = self.second_released(1)
        self.apply("release-done", [{"path": FEATURE_TWO, "content": second}, {"path": record_path(1), "content": second_record}], approver=self.owner)
        feature, record = self.all_released(number=2)
        self.settle(feature, record, number=2)
        self.assertEqual(("released", "none"), self.status())

    def test_a_feature_releases_in_the_same_release_as_its_dependency(self) -> None:
        self.depend()
        # F-002 is rebuilt on the artifact of F-001, so one deployment delivers both and the dependency is satisfied by the same release.
        self.put(FEATURE_TWO, self.second_page("ready-for-release", "release", ["| backend | — | `build:backend#1` | release-1 | pending | — | — |"], "build:backend#1"))
        first, _record = self.all_released()
        second, _ = self.second_released(1, "build:backend#1")
        rows = [delivery("F-001", "backend"), delivery("F-001", "worker"), delivery("F-002", "backend")]
        record = record_page(1, rows, features=["F-001", "F-002"], title="Release of F-001 and F-002", summary="F-001 and F-002 are delivered to production.")
        self.apply("release-done", [{"path": FEATURE, "content": first}, {"path": FEATURE_TWO, "content": second}, {"path": record_path(1), "content": record}], approver=self.owner)
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(set(), self.errors())


if __name__ == "__main__":
    unittest.main()
