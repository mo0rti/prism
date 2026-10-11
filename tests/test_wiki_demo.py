import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from prism_cli.wiki_graph import build_graph, render_mermaid
from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, lint_wiki
from tests import real_temp  # noqa: F401


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "build-wiki-demo.py"
CHECK_DATE = date(2026, 9, 8)
STAGES = ["raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "ready-for-qa", "in-qa", "ready-for-release", "released"]


class WikiDemoBuilderTests(unittest.TestCase):
    def run_builder(
        self,
        destination: Path,
        stage: str = "all",
        today: date = CHECK_DATE,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--destination",
                str(destination),
                "--stage",
                stage,
                "--today",
                today.isoformat(),
                "--json",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def files_under(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    def test_all_stages_are_capture_ready_and_populated_graph_has_intended_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "treasuryflow-demo"
            result = self.run_builder(destination)
            self.assertEqual(0, result.returncode, result.stderr)
            metadata = json.loads(result.stdout)

            self.assertTrue(metadata["synthetic"])
            self.assertEqual(CHECK_DATE.isoformat(), metadata["today"])
            self.assertEqual({"fresh", "intake", "populated"}, set(metadata["stages"]))
            self.assertEqual(destination.resolve(), Path(metadata["destination"]).resolve())

            for stage in metadata["stages"].values():
                stage_root = Path(stage)
                self.assertTrue((stage_root / "DEMO.md").is_file())
                self.assertTrue((stage_root / "prism.workspace.yml").is_file())
                self.assertTrue((stage_root / ".copier-answers.yml").is_file())
                self.assertTrue((stage_root / "knowledge" / "wiki" / "SCHEMA.md").is_file())
                self.assertTrue((stage_root / "knowledge" / "wiki" / "features" / "_FORMAT.md").is_file())
                for platform in ("backend", "mobile-android", "mobile-ios"):
                    self.assertTrue((stage_root / platform).is_dir())

            fresh = Path(metadata["stages"]["fresh"])
            intake = Path(metadata["stages"]["intake"])
            populated = Path(metadata["stages"]["populated"])
            self.assertEqual("not-initialized", build_graph(fresh)["facts"]["setup_state"])
            self.assertEqual([], build_graph(fresh)["facts"]["intake"]["pending"])
            self.assertEqual(["2026-09-29-payout-approval-brief"], build_graph(intake)["facts"]["intake"]["pending"])
            self.assertEqual(["2026-09-28-duplicate-settlement-brief"], build_graph(intake)["facts"]["intake"]["quarantined"])

            lint_result = lint_wiki(populated, today=CHECK_DATE)
            blocker_codes = {diagnostic.code for diagnostic in lint_result.diagnostics} & WIKI_BLOCKER_CODES
            self.assertEqual({"pending-board-review", "unresolved-open-questions"}, blocker_codes)
            self.assertEqual(0, len([d for d in lint_result.diagnostics if d.code not in WIKI_BLOCKER_CODES]))

            graph = build_graph(populated)
            self.assertGreaterEqual(graph["facts"]["node_count"], 3)
            feature_ids = {node["id"] for node in graph["facts"]["nodes"] if node["type"] == "feature"}
            self.assertEqual({f"F-{number:03d}" for number in range(1, 11)}, feature_ids)
            # The demo shows a feature at every stage of the lifecycle.
            self.assertEqual(
                ["raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "ready-for-qa", "in-qa", "ready-for-release", "released"],
                sorted((node["status"] for node in graph["facts"]["nodes"] if node["type"] == "feature"), key=STAGES.index),
            )
            edge_kinds = {edge["kind"] for edge in graph["facts"]["edges"]}
            self.assertTrue({"related", "has-design", "has-contract", "has-requirement", "has-review", "constrained-by", "serves"} <= edge_kinds)
            self.assertEqual(["2026-09-30-future-refund-brief"], graph["facts"]["intake"]["pending"])
            self.assertEqual(["2026-09-28-duplicate-settlement-brief"], graph["facts"]["intake"]["quarantined"])
            self.assertEqual(
                {"pending-board-review", "unresolved-open-questions"},
                {fact["code"] for fact in graph["blocker_facts"]},
            )

    def test_the_populated_demo_shows_bugs_a_release_record_a_rollback_and_an_incident(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "treasuryflow-demo"
            result = self.run_builder(destination, stage="populated")
            self.assertEqual(0, result.returncode, result.stderr)
            wiki = destination / "knowledge" / "wiki"
            self.assertEqual(
                ["BUG-001", "BUG-002", "BUG-003"],
                sorted(path.name[:7] for path in (wiki / "bugs").glob("BUG-*.md")),
            )
            self.assertEqual(["REL-001.md", "REL-002.md"], sorted(path.name for path in (wiki / "releases").glob("REL-*.md")))
            self.assertEqual(["INC-001"], sorted(path.name[:7] for path in (wiki / "incidents").glob("INC-*.md")))
            release = (wiki / "releases" / "REL-001.md").read_text(encoding="utf-8")
            rollback = (wiki / "releases" / "REL-002.md").read_text(encoding="utf-8")
            self.assertIn("outcome: released", release)
            self.assertIn("## Contracts\n### F-003 backend", release.replace("\r\n", "\n"))
            self.assertIn("rollback-of: REL-001", rollback)
            board = (wiki / "status-board.md").read_text(encoding="utf-8").replace("\r\n", "\n")
            self.assertIn("## Bugs\n\n| ID | Bug | Status | Owner | Apps | Feature | Blocking |", board)
            self.assertIn("| BUG-002 | Rejected request keeps the approve button | fixed | qa | mobile-android | F-002 | no |", board)
            self.assertIn("## Operations", board)
            self.assertIn("| backend | production | F-003 | REL-002 | rolled-back | BUG-001, BUG-003 | INC-001 |", board)
            self.assertIn("| mobile-ios | app-store | F-003 | REL-001 | released | — | — |", board)
            # The feature that waits in QA shows the bugs that name it, and the released one is untouched.
            self.assertIn("| backend: in-dev; mobile-android: in-dev; mobile-ios: in-dev | BUG-001, BUG-002 |", board)

    def test_same_date_builds_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first"
            second = root / "second"
            first_result = self.run_builder(first, stage="populated")
            second_result = self.run_builder(second, stage="populated")
            self.assertEqual(0, first_result.returncode, first_result.stderr)
            self.assertEqual(0, second_result.returncode, second_result.stderr)
            self.assertEqual(self.files_under(first), self.files_under(second))

    def test_existing_destination_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "already-there"
            destination.mkdir()
            sentinel = destination / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            result = self.run_builder(destination, stage="populated")

            self.assertEqual(2, result.returncode)
            self.assertIn("Refusing to overwrite existing destination", result.stderr)
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
            self.assertEqual([sentinel], list(destination.iterdir()))

    def test_committed_mermaid_diagram_matches_seeded_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "treasuryflow-demo"
            result = self.run_builder(destination, stage="populated", today=date.today())
            self.assertEqual(0, result.returncode, result.stderr)
            expected = render_mermaid(build_graph(destination), "lifecycle")

        committed = (REPO_ROOT / "docs" / "wiki-visualization-demo.mmd").read_text(encoding="utf-8").rstrip()
        self.assertEqual(expected, committed)


if __name__ == "__main__":
    unittest.main()
