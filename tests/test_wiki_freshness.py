"""Log-derived freshness: `stale-page` (warning) and `never-verified` (information).

A page's last verification is the latest `verify` entry of `log.md` whose `paths` include it. Freshness only asks for
a review: it never changes a status, never gates a lifecycle action and never reaches the board's write path.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_lint import FRESHNESS_CODES, WIKI_BLOCKER_CODES, lint_wiki
from prism_cli.wiki_log import last_verifications
from prism_cli.wiki_transitions import build_board_transition_preflight, build_transition_preflight
from tests import real_temp  # noqa: F401
from tests.manifest_fixtures import manifest_text
from tests.test_board_service import _journey_feature_page
from tests.wiki_files import copy_template_knowledge, write_index, write_status_board

TODAY = date(2026, 10, 20)
WIKI = "knowledge/wiki"
FEATURE_PAGE = "features/F-001-payments.md"

PAGES = {
    "topics/payments.md": "---\nkind: topic\ntitle: Payments\nstatus: current\nsources: []\n---\n\n## Summary\nPayments settle in a day.\n\n## Key points\n- **Assumed:** Weekends are excluded.\n\n## Related pages\nNone yet.\n",
    "research/sync.md": "---\nkind: research\ntitle: Sync\nstatus: open\nsources: []\n---\n\n## Question\nWhich model?\n\n## Summary\nLast writer wins.\n\n## Findings\n- **Unknown:** Nothing yet.\n\n## Gaps\n- **Unknown:** Cost.\n",
    "plans/launch.md": "---\nkind: plan\ntitle: Launch\nstatus: active\nsources: []\n---\n\n## Summary\nThe launch runs.\n\n## Goal\nShip.\n\n## Current status\nStarted.\n\n## Next steps\n- **Proposed:** Go.\n\n## Blockers\nNo blockers.\n",
    "direction.md": "---\nkind: direction\nsources: []\n---\n\n## Summary\nReviewers come first.\n\n## Direction\n- **Proposed:** Forward.\n\n## Principles\n- Keep records.\n",
    "roadmap.md": "---\nkind: roadmap\nsources: []\n---\n\n## Summary\nThe export ships next.\n\n## Next\n- The export.\n\n## Later\n- Offline.\n",
    "personas/reviewer.md": "---\nid: P-001\nname: Reviewer\nsources: []\n---\n\n## Who they are\nA person assigned to review a document.\n\n## Goals\nRecord key points.\n\n## Pain points\nNotes get lost.\n\n## Features that serve this persona\nNone yet.\n",
    "business-rules/BR-001-keep.md": "---\nid: BR-001\ntitle: Keep outcomes\nsource: a meeting\n---\n\n## Rule\nA review keeps its outcome.\n\n## Rationale\nReviewers need to find it.\n\n## Affected features\nNone yet.\n\n## Exceptions\nNone.\n",
    "decisions/ADR-001-sessions.md": "---\nid: ADR-001\ntitle: Sessions\ndate: 2026-09-01\nstatus: accepted\n---\n\n## Context\nOne browser.\n\n## Decision\nUse sessions.\n\n## Rationale\nSimple.\n\n## Consequences\nThey expire.\n",
}
CURRENT_STATE = [name for name in PAGES if not name.startswith("decisions/")] + [FEATURE_PAGE]


def entry(day: date, operation: str, paths: list[str], by: str = "Riley") -> str:
    return f"## {day.isoformat()} {operation} | subject\n- paths: {', '.join(paths)}\n- evidence: none\n- by: {by}\n"


class FreshnessCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        copy_template_knowledge(self.root / "knowledge")
        (self.root / "prism.workspace.yml").write_text(manifest_text("Fresh", ["backend"], slug="fresh"), encoding="utf-8")
        (self.root / "backend").mkdir()
        self.wiki = self.root / "knowledge" / "wiki"
        for relative, text in PAGES.items():
            self.write(relative, text)
        self.write(FEATURE_PAGE, _journey_feature_page("F-001", "Payments", "raw", "po", [], ["| 1 | Which details? | po | open |"]))
        write_status_board(self.root, "| F-001 | Payments | raw | po | not-needed |\n")
        write_index(self.root)

    def write(self, relative: str, text: str) -> None:
        path = self.wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def append_log(self, *entries: str) -> None:
        log = self.wiki / "log.md"
        log.write_text(log.read_text(encoding="utf-8") + "\n" + "\n".join(entries), encoding="utf-8", newline="\n")

    def lint(self, today: date = TODAY):
        return lint_wiki(self.root, today=today)

    def freshness(self, today: date = TODAY) -> dict[str, str]:
        """Page path (relative to the wiki) to the freshness code lint reports for it."""

        return {
            Path(item.path).relative_to(self.wiki).as_posix(): item.code
            for item in self.lint(today).all_diagnostics
            if item.code in FRESHNESS_CODES
        }


class FreshnessTests(FreshnessCase):
    def test_nothing_is_verified_at_first_so_every_current_state_page_is_never_verified(self) -> None:
        result = self.lint()

        self.assertEqual({page: "never-verified" for page in CURRENT_STATE}, self.freshness())
        found = [item for item in result.information if item.code == "never-verified"]
        self.assertEqual(len(CURRENT_STATE), len(found))
        self.assertEqual({"info"}, {item.severity for item in result.information})
        # Only `prism wiki lint` reports it: the diagnostics every other reader sees carry no information finding.
        self.assertEqual([], [item for item in result.diagnostics if item.code == "never-verified"])
        self.assertEqual(len(CURRENT_STATE), len([item for item in result.to_dict()["diagnostics"] if item["code"] == "never-verified"]))
        self.assertTrue(result.is_clean)
        self.assertEqual(0, result.warning_count)
        self.assertEqual("high", result.to_dict()["confidence"])

    def test_a_recent_verification_is_fresh_across_every_page_kind(self) -> None:
        self.append_log(entry(TODAY - timedelta(days=3), "verify", [f"{WIKI}/{page}" for page in CURRENT_STATE]))
        self.assertEqual({}, self.freshness())
        self.assertEqual([], self.lint().information)

    def test_an_overdue_verification_is_stale_and_names_the_dates(self) -> None:
        self.append_log(entry(TODAY - timedelta(days=20), "verify", [f"{WIKI}/{page}" for page in CURRENT_STATE]))

        result = self.lint()

        self.assertEqual({page: "stale-page" for page in CURRENT_STATE}, self.freshness())
        found = [item for item in result.diagnostics if item.code == "stale-page"]
        self.assertEqual({"warning"}, {item.severity for item in found})
        self.assertIn((TODAY - timedelta(days=20)).isoformat(), found[0].message)
        self.assertIn("20 days ago", found[0].message)
        self.assertIn("`wiki-stale-after-days` is 14", found[0].message)
        self.assertTrue(result.is_clean, "a stale page is a warning, not an error")
        self.assertEqual(len(CURRENT_STATE), result.warning_count)

    def test_the_boundary_is_the_setting(self) -> None:
        self.append_log(entry(TODAY - timedelta(days=14), "verify", [f"{WIKI}/topics/payments.md"]), entry(TODAY - timedelta(days=15), "verify", [f"{WIKI}/research/sync.md"]))
        found = self.freshness()
        self.assertNotIn("topics/payments.md", found)
        self.assertEqual("stale-page", found["research/sync.md"])
        (self.wiki / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 30\n---\n", encoding="utf-8")
        self.assertNotIn("research/sync.md", self.freshness())
        (self.wiki / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 0\n---\n", encoding="utf-8")
        self.assertEqual("stale-page", self.freshness()["topics/payments.md"])

    def test_a_missing_or_malformed_setting_falls_back_to_fourteen_days(self) -> None:
        self.append_log(entry(TODAY - timedelta(days=20), "verify", [f"{WIKI}/topics/payments.md"]))
        (self.wiki / "SETTINGS.md").write_text("---\nwiki-stale-after-days: soon\n---\n", encoding="utf-8")
        self.assertEqual("stale-page", self.freshness()["topics/payments.md"])
        (self.wiki / "SETTINGS.md").unlink()
        self.assertEqual("stale-page", self.freshness()["topics/payments.md"])

    def test_the_latest_verification_of_a_page_counts(self) -> None:
        page = f"{WIKI}/topics/payments.md"
        self.append_log(entry(TODAY - timedelta(days=60), "verify", [page]), entry(TODAY - timedelta(days=2), "verify", [page]), entry(TODAY - timedelta(days=90), "verify", [page]))
        self.assertNotIn("topics/payments.md", self.freshness())

    def test_only_a_verify_entry_that_lists_the_page_counts(self) -> None:
        page = f"{WIKI}/topics/payments.md"
        self.append_log(
            entry(TODAY - timedelta(days=1), "po-intake", [page]),
            entry(TODAY - timedelta(days=1), "board-ingest", [page]),
            entry(TODAY - timedelta(days=1), "verify", [f"{WIKI}/research/sync.md"]),
            entry(TODAY - timedelta(days=1), "verify-all", [page]),
        )
        found = self.freshness()
        self.assertEqual("never-verified", found["topics/payments.md"])
        self.assertNotIn("research/sync.md", found)

    def test_a_malformed_entry_is_reported_by_the_log_check_and_not_read_as_a_verification(self) -> None:
        self.append_log(f"## {TODAY.isoformat()} verify\n- paths: {WIKI}/topics/payments.md\n")
        result = self.lint()
        self.assertEqual("never-verified", self.freshness()["topics/payments.md"])
        self.assertIn("malformed-log-entry", {item.code for item in result.diagnostics})

    def test_a_verification_from_the_future_is_not_stale(self) -> None:
        self.append_log(entry(TODAY + timedelta(days=5), "verify", [f"{WIKI}/topics/payments.md"]))
        self.assertNotIn("topics/payments.md", self.freshness())

    def test_records_the_log_the_index_and_generated_artifacts_are_exempt(self) -> None:
        (self.wiki / "WIKI_REPORT.md").write_text("# Report\n", encoding="utf-8")
        (self.wiki / "advisory").mkdir(exist_ok=True)
        (self.wiki / "advisory" / "F-001-review.md").write_text("---\nfeature-id: F-001\nreviewed: 2026-10-01\n---\n\n# Review\n", encoding="utf-8")
        exempt = {"decisions/ADR-001-sessions.md", "advisory/F-001-review.md", "advisory/BOARD.md", "log.md", "index.md", "status-board.md", "WIKI_REPORT.md", "SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "SETTINGS.md", "CONNECTED.md"}
        self.assertEqual(set(), exempt & set(self.freshness()))
        self.append_log(entry(TODAY - timedelta(days=99), "verify", [f"{WIKI}/{page}" for page in exempt]))
        self.assertEqual(set(), exempt & set(self.freshness()))

    def test_lint_changes_no_file(self) -> None:
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.lint()
        self.lint(TODAY + timedelta(days=400))
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_the_log_reader_takes_the_latest_date_per_path(self) -> None:
        text = (
            entry(date(2026, 10, 1), "verify", ["a.md", "b.md"])
            + "\n"
            + entry(date(2026, 10, 9), "verify", ["a.md"])
            + "\n"
            + entry(date(2026, 10, 5), "po-intake", ["c.md"])
            + "\n<!-- prism:board-history:v1 preview=x -->\n"
            + entry(date(2026, 10, 7), "verify", ["none"])
        )
        self.assertEqual({"a.md": date(2026, 10, 9), "b.md": date(2026, 10, 1)}, last_verifications(text))


class EvidenceWarningsNeverGateTests(FreshnessCase):
    """Evidence-label warnings ask for a better page. They are reported but never reach a transition gate."""

    def test_unlinked_and_unknown_labels_on_the_feature_page_keep_every_transition_check_as_it_was(self) -> None:
        def checks() -> tuple[str, list[tuple[str, str]]]:
            board = build_board_transition_preflight(self.root, "F-001", "po-specify")
            return board["classification"], [(c["code"], c["status"]) for c in board["checks"]]

        baseline = checks()
        page = self.wiki / FEATURE_PAGE
        page.write_text(
            page.read_text(encoding="utf-8") + "\n- **Decided:** Refunds settle in a day.\n- **Guessed:** Weekends count.\n",
            encoding="utf-8",
            newline="\n",
        )

        codes = {item.code for item in self.lint().diagnostics if Path(item.path).name == Path(FEATURE_PAGE).name}
        self.assertTrue({"unlinked-claim", "unknown-evidence-label"} <= codes, codes)
        after = checks()
        self.assertFalse([code for code, _ in after[1] if code.startswith("source-integrity:")], after)
        self.assertEqual(baseline, after)


class FreshnessNeverGatesTests(FreshnessCase):
    """Freshness asks for a review. It never changes a status and never reaches a gate or the board."""

    def test_the_freshness_codes_are_not_blocker_codes(self) -> None:
        self.assertEqual(set(), set(FRESHNESS_CODES) & set(WIKI_BLOCKER_CODES))

    def test_a_stale_and_a_never_verified_feature_page_keeps_every_transition_check_as_it_was(self) -> None:
        def checks(today: date) -> dict:
            envelope = build_transition_preflight(self.root, "F-001")
            return {"classification": envelope["facts"]["transition"]["classification"], "checks": [(c["code"], c["status"]) for c in envelope["facts"]["transition"]["checks"]]}

        baseline = checks(TODAY)
        self.assertEqual({"F-001": "never-verified"}, {"F-001": self.freshness()[FEATURE_PAGE]})
        self.assertFalse([code for code, _ in baseline["checks"] if code.startswith("source-integrity:")], baseline)

        self.append_log(entry(TODAY - timedelta(days=200), "verify", [f"{WIKI}/{FEATURE_PAGE}"]))
        self.assertEqual("stale-page", self.freshness()[FEATURE_PAGE])
        self.assertEqual(baseline, checks(TODAY))

        self.append_log(entry(TODAY, "verify", [f"{WIKI}/{FEATURE_PAGE}"]))
        self.assertNotIn(FEATURE_PAGE, self.freshness())
        self.assertEqual(baseline, checks(TODAY))

    def test_the_board_transition_preflight_does_not_see_freshness(self) -> None:
        board = build_board_transition_preflight(self.root, "F-001", "po-specify")
        self.assertFalse([item for item in board["checks"] if "never-verified" in item["code"] or "stale-page" in item["code"]], board["checks"])
        self.append_log(entry(TODAY - timedelta(days=200), "verify", [f"{WIKI}/{FEATURE_PAGE}"]))
        again = build_board_transition_preflight(self.root, "F-001", "po-specify")
        self.assertEqual((board["classification"], board["checks"]), (again["classification"], again["checks"]))

    def test_the_graph_keeps_a_feature_node_healthy(self) -> None:
        self.append_log(entry(TODAY - timedelta(days=200), "verify", [f"{WIKI}/{FEATURE_PAGE}"]))
        graph = build_graph(self.root)
        node = next(node for node in graph["facts"]["nodes"] if node["id"] == "F-001")
        self.assertEqual("ok", node["health"])
        self.assertIn("stale-page", {item["code"] for item in graph["diagnostics"]})

    def test_freshness_never_changes_a_page_status(self) -> None:
        before = {relative: (self.wiki / relative).read_bytes() for relative in (*PAGES, FEATURE_PAGE, "status-board.md")}
        self.append_log(entry(TODAY - timedelta(days=200), "verify", [f"{WIKI}/{page}" for page in CURRENT_STATE]))
        for days in (0, 30, 400):
            self.lint(TODAY + timedelta(days=days))
            build_transition_preflight(self.root, "F-001")
        self.assertEqual(before, {relative: (self.wiki / relative).read_bytes() for relative in before})

    def test_no_gate_or_board_write_path_reads_the_freshness_codes(self) -> None:
        # Outside lint, the gate skips every finding that does not gate, and the graph skips the freshness codes.
        root = Path(__file__).resolve().parents[1] / "prism_cli"
        offenders = []
        for source in sorted(root.glob("*.py")):
            text = source.read_text(encoding="utf-8")
            for code in ("stale-page", "never-verified"):
                if code in text and source.name not in {"wiki_lint.py"}:
                    offenders.append(f"{source.name}: {code}")
        self.assertEqual([], offenders)
        self.assertIn("not diagnostic.gates", (root / "wiki_transitions.py").read_text(encoding="utf-8"))
        self.assertIn("FRESHNESS_CODES", (root / "wiki_graph.py").read_text(encoding="utf-8"))
        for name in ("board_service.py", "board_reads.py", "board_server.py", "board_mcp.py"):
            self.assertNotIn("FRESHNESS_CODES", (root / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
