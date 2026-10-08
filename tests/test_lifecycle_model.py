"""The lifecycle model of the full-lifecycle contract: registry, parsers, criteria, app stages, coverage, policy, lint and the service flows.

Parsers and calculations are exercised on page text; the lint cases seed one disposable workspace with per-app states; the
service flows drive F1, F2, F3, F6, F7, F8, F9 and F26 through the board service. Actions owned by later work packages are
registered and answer `action_unavailable`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService, _parse_markdown
from prism_cli.roles import RolePredicate, required_roles
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import (
    app_stage,
    app_stages,
    app_stages_text,
    artifact_reference_problem,
    canonical_json,
    criteria_high_water,
    criterion_revision,
    evidence_generation,
    expected_owner,
    minimum_stage,
    parse_criteria,
    parse_delivery_rows,
    parse_evidence_history,
    parse_qa_rows,
    parse_release_rows,
    qa_attempt,
    qa_coverage,
    read_feature_evidence,
    read_wiki_settings,
    release_attempt,
    row_digest,
    stale_qa_rows,
    status_rank,
    workflow_policy,
)
from prism_cli.wiki_transitions import (
    ACTION_BY_ID,
    ACTION_SPECS,
    ENABLED_PACKAGES,
    MODE_HUMAN_DIRECT,
    TRANSITION_CAPABILITY_VERSION,
    WRITE_SCOPES,
    build_board_transition_preflight,
    capability_marker,
    lookup_action,
)
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.workspace import inspect_workspace
from tests import real_temp  # noqa: F401
from tests.board_approval import apply_preview, human_with_roles
from tests.core_workflow_fixture import INTAKE_ITEM, create_core_workflow_fixture
from tests.test_apps_surfaces import run_cli
from tests.test_board_service import (
    _journey_feature_page,
    _journey_requirement_page,
    _read_revisions,
    _replace_body_section,
    _replace_body_section_text,
    _set_feature_stage,
    _set_requirement_status,
    _write_index_rows,
)

SOURCE = "knowledge/intake/processed/2026-10-06-document-review-brief"
FEATURE = "knowledge/wiki/features/F-001-document-review.md"
NO_API = {"has-ui": False, "serves-api": False}
SHA = "a" * 64
ARTIFACT = {"backend": "build:backend#1", "worker": "build:worker#1"}
TEXT_ONE = "A reviewer can record the outcome and requested follow-up."
TEXT_TWO = "A saved summary can be read back."


def delivery_row(app: str, artifact: str | None = None, contract: str = "none") -> str:
    return f"| {app} | `{artifact or ARTIFACT[app]}` | {contract} | Reviewed source record | Review check passed | checked |"


def qa_row(key: str, refs: list[str], artifacts: str, *, attempt: int = 1, result: str = "pass") -> str:
    return f"| {key} | {', '.join(refs)} | automated | {artifacts} | ci | qa-{attempt} | {result} | [run](https://ci.example/1) | checked |"


def ref(number: int, apps: list[str], text: str, *, integration: bool = False, feature_id: str = "F-001") -> str:
    return f"AC-{number}@{criterion_revision(feature_id, number, apps, integration, '', text)}"


def release_row(app: str, outcome: str = "pending", artifact: str | None = None) -> str:
    if outcome == "pending":
        return f"| {app} | — | `{artifact or ARTIFACT[app]}` | release-1 | pending | — | — |"
    return f"| {app} | production | `{artifact or ARTIFACT[app]}` | release-1 | {outcome} | [REL-001](https://records.example/REL-001) | checked |"


def table(header: str, rows: list[str]) -> str:
    columns = header.split("|")[1:-1]
    return "\n".join([header, "|" + "|".join("---" for _ in columns) + "|", *rows])


DELIVERY_HEADER = "| App | Artifact | Contract | Implementation | Tests | Basis |"
QA_HEADER = "| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |"
RELEASE_HEADER = "| App | Target | Version | Attempt | Outcome | Record | Basis |"


def body_of(
    criteria: list[str],
    *,
    delivery: list[str] | None = None,
    qa: list[str] | None = None,
    release: list[str] | None = None,
    history: str = "",
) -> str:
    return (
        "## Acceptance criteria\n"
        + "\n".join(f"- [ ] {line}" for line in criteria)
        + "\n\n## Delivery evidence\n"
        + table(DELIVERY_HEADER, delivery or [])
        + "\n\n## QA verification\n"
        + table(QA_HEADER, qa or [])
        + "\n\n## Release\n"
        + table(RELEASE_HEADER, release or [])
        + "\n\n## Evidence history\n"
        + history
        + "\n"
    )


class ParserTests(unittest.TestCase):
    """CONTRACTS 5.1 to 5.3: the evidence tables, the artifact grammars and the Evidence history."""

    def test_artifact_grammars(self) -> None:
        accepted = (
            "build:backend#412",
            "version:1.4.0",
            "version:1.4.0-rc.1",
            f"image:registry.example/app@sha256:{SHA}",
            "package:@scope/pkg@1.2.3",
            "commit:3f9c2ab",
        )
        for value in accepted:
            with self.subTest(value=value):
                self.assertIsNone(artifact_reference_problem(value))
        rejected = ("build-42", "version:", "version:1.4.0-rc.1+build.7", "image:app:latest", "commit:xyz", "commit:12345", "")
        for value in rejected:
            with self.subTest(value=value):
                self.assertIsNotNone(artifact_reference_problem(value))

    def test_delivery_rows_and_the_contract_cell(self) -> None:
        binding = f"F-001@v2:c1:{SHA}"
        body = body_of([f"AC-1 [backend] {TEXT_ONE}"], delivery=[delivery_row("backend", contract=binding)])
        rows, problems = parse_delivery_rows(body)
        self.assertEqual([], problems)
        self.assertEqual(("backend", "build:backend#1", ("F-001", 2, f"c1:{SHA}")), (rows[0].app, rows[0].artifact, rows[0].contract_binding))

        for contract in ("F-001", f"F-001@v2:c2:{SHA}", "agreed"):
            with self.subTest(contract=contract):
                _rows, problems = parse_delivery_rows(body_of([], delivery=[delivery_row("backend", contract=contract)]))
                self.assertEqual(["delivery_evidence_invalid"], [item.code for item in problems])
        _rows, problems = parse_delivery_rows(body_of([], delivery=["| backend | `build:backend#1` | none | Reviewed source record | n/a | checked |"]))
        self.assertIn("Tests", problems[0].message)
        _rows, problems = parse_delivery_rows(body_of([], delivery=["| backend | `build:backend#1` | none | Reviewed source record | Review check passed | maybe |"]))
        self.assertEqual(["basis_invalid"], [item.code for item in problems])

    def test_a_table_is_read_by_its_header_and_not_inside_fences_or_comments(self) -> None:
        # Case, bold and backticks of the header cells are ignored; another header is a problem and yields no rows.
        loose = "| **app** | Artifact | `Contract` | implementation | TESTS | Basis |\n|---|---|---|---|---|---|\n" + delivery_row("backend")
        rows, problems = parse_delivery_rows("## Delivery evidence\n" + loose + "\n")
        self.assertEqual(([], 1), ([item.problems for item in problems], len(rows)))
        rows, problems = parse_delivery_rows("## Delivery evidence\n| App | Implementation | Tests | Release |\n|---|---|---|---|\n| backend | x | y | z |\n")
        self.assertEqual(([], 1), (rows, len(problems)))
        fenced = "## Delivery evidence\n```\n" + table(DELIVERY_HEADER, [delivery_row("backend")]) + "\n```\n<!--\n" + delivery_row("worker") + "\n-->\n"
        self.assertEqual(([], []), parse_delivery_rows(fenced))
        self.assertEqual(([], []), parse_delivery_rows("## Delivery evidence\nNothing is delivered yet.\n"))

    def test_qa_rows_for_an_app_and_for_an_integration(self) -> None:
        one = ref(1, ["backend"], TEXT_ONE)
        two = ref(2, ["backend", "worker"], TEXT_TWO, integration=True)
        rows = [
            qa_row("backend", [one], "`build:backend#1`"),
            qa_row("integration: backend + worker", [two], "backend=`build:backend#1`; worker=`build:worker#1`", result="fail"),
        ]
        parsed, problems = parse_qa_rows(body_of([], qa=rows))
        self.assertEqual([], problems)
        self.assertEqual([("backend",), ("backend", "worker")], [row.apps for row in parsed])
        self.assertEqual([False, True], [row.integration for row in parsed])
        self.assertEqual({"backend": "build:backend#1", "worker": "build:worker#1"}, parsed[1].artifacts)
        self.assertEqual(["pass", "fail"], [row.result for row in parsed])

        for name, bad in {
            "unsorted participants": qa_row("integration: worker + backend", [two], "backend=`build:backend#1`; worker=`build:worker#1`"),
            "one participant": qa_row("integration: backend", [two], "backend=`build:backend#1`"),
            "criterion without revision": "| backend | AC-1 | automated | `build:backend#1` | ci | qa-1 | pass | [run](https://ci.example/1) | checked |",
            "unknown method": "| backend | " + one + " | guesswork | `build:backend#1` | ci | qa-1 | pass | [run](https://ci.example/1) | checked |",
            "attempt without qa- prefix": "| backend | " + one + " | automated | `build:backend#1` | ci | 1 | pass | [run](https://ci.example/1) | checked |",
            "unknown result": "| backend | " + one + " | automated | `build:backend#1` | ci | qa-1 | maybe | [run](https://ci.example/1) | checked |",
            "integration artifact for one participant": qa_row("integration: backend + worker", [two], "backend=`build:backend#1`"),
        }.items():
            with self.subTest(case=name):
                _parsed, problems = parse_qa_rows(body_of([], qa=[bad]))
                self.assertTrue(problems, name)

    def test_release_rows_staging_and_authoritative(self) -> None:
        rows = [
            "| backend | staging | `build:backend#1` | — | released | https://staging.example/1 | checked |",
            release_row("backend", "released"),
            release_row("worker"),
        ]
        parsed, problems = parse_release_rows(body_of([], release=rows))
        self.assertEqual([], problems)
        self.assertEqual([False, True, True], [row.authoritative for row in parsed])
        self.assertEqual([None, 1, 1], [row.attempt for row in parsed])
        for name, bad in {
            "released without record": "| backend | production | `build:backend#1` | release-1 | released | — | checked |",
            "pending with a target": "| backend | production | `build:backend#1` | release-1 | pending | — | — |",
            "unknown outcome": "| backend | production | `build:backend#1` | release-1 | shipped | [REL-001](https://records.example/REL-001) | checked |",
            "bad version": "| backend | production | 1.4.0 | release-1 | released | [REL-001](https://records.example/REL-001) | checked |",
        }.items():
            with self.subTest(case=name):
                _parsed, problems = parse_release_rows(body_of([], release=[bad]))
                self.assertTrue(problems, name)

    def test_evidence_history_entries(self) -> None:
        row = delivery_row("backend")
        archived = "| Delivery evidence |" + row.strip("|")
        history = "\n".join(
            [
                "### 2026-10-01 - qa-fail",
                "- Reason: The saved outcome is not read back.",
                "- Affected apps: backend, worker",
                "- Participants: worker",
                "- Affected tracks: none",
                "- Archived evidence:",
                f"  {archived}",
                "- Reaffirmed evidence: none",
                "- Requirement/API invalidations: No requirement or API page is invalidated.",
                "- Linked bugs: none",
            ]
        )
        entries = parse_evidence_history(body_of([], history=history))
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual(("2026-10-01", "qa-fail"), (entry.date, entry.action))
        self.assertEqual((["backend", "worker"], ["worker"]), (list(entry.affected_apps), list(entry.participants)))
        self.assertEqual("Delivery evidence", entry.archived_rows[0][0])
        self.assertEqual("backend", entry.archived_rows[0][1][0])
        # The generation of an app's row counts the entries that archived it.
        self.assertEqual(2, evidence_generation(entries, "Delivery evidence", "backend"))
        self.assertEqual(1, evidence_generation(entries, "Delivery evidence", "worker"))
        self.assertEqual(hashlib.sha256("|".join(cell.strip() for cell in entry.archived_rows[0][1]).encode("utf-8")).hexdigest(), row_digest(entry.archived_rows[0][1]))

    def test_attempt_counters(self) -> None:
        qa = "| QA verification | backend | AC-1@v1:x | automated | `build:backend#1` | ci | qa-1 | fail | run | checked |"
        history = "\n".join(
            [
                "### 2026-10-01 - qa-fail",
                "- Reason: The saved outcome is not read back.",
                "- Affected apps: backend",
                "- Participants: none",
                "- Affected tracks: none",
                "- Archived evidence:",
                f"  {qa}",
                "- Reaffirmed evidence: none",
                "- Requirement/API invalidations: No requirement or API page is invalidated.",
                "- Linked bugs: none",
            ]
        )
        entries = parse_evidence_history(body_of([], history=history))
        self.assertEqual((2, 1), (qa_attempt("backend", entries), qa_attempt("worker", entries)))
        records = [
            {"kind": "release", "delivery": [("F-001", "backend")]},
            {"kind": "rollback", "delivery": [("F-001", "backend")]},
            {"kind": "release", "delivery": [("F-002", "backend")]},
        ]
        self.assertEqual((2, 1), (release_attempt(records, "F-001", "backend"), release_attempt(records, "F-001", "worker")))


class CriteriaTests(unittest.TestCase):
    """CONTRACTS 4.1: criterion IDs, the applies-to forms, the revision and the high-water mark."""

    BODY = (
        "## Acceptance criteria\n"
        "- [ ] AC-1 [backend] A reviewer can save the outcome.\n"
        "- [x] **Decided:** AC-2 [integration: backend, worker] The saved outcome reaches the worker.\n"
        "- [ ] AC-3 [backend,worker]   Two   spaces   collapse.\n"
        "- [ ] No identifier here.\n"
        "- [ ] AC-4 [] Empty applies-to.\n"
        "- [ ] AC-5 [integration: backend] One participant only.\n\n"
        "## Next\nText.\n"
    )

    def test_the_forms_and_the_problems(self) -> None:
        items = parse_criteria(self.BODY, "F-001")
        self.assertEqual([1, 2, 3, None, 4, 5], [item.number for item in items])
        self.assertEqual([("backend",), ("backend", "worker"), ("backend", "worker")], [item.applies_to for item in items[:3]])
        self.assertEqual([False, True, False], [item.integration for item in items[:3]])
        self.assertEqual(("Decided", True), (items[1].label, items[1].checked))
        self.assertEqual("Two spaces collapse.", items[2].text)
        self.assertEqual(["criterion-id-required", "invalid-applies-to", "invalid-applies-to"], [item.problems[0][0] for item in items[3:]])
        self.assertTrue(all(item.revision for item in items[:3]))
        self.assertTrue(all(item.revision is None for item in items[3:]))

    def test_the_revision_covers_the_id_scope_label_and_text(self) -> None:
        base = criterion_revision("F-001", 1, ["backend"], False, "", "Text.")
        self.assertRegex(base, r"^v1:[0-9a-f]{64}$")
        expected = "v1:" + hashlib.sha256(canonical_json([1, "F-001", "AC-1", ["backend"], "", "Text."]).encode("utf-8")).hexdigest()
        self.assertEqual(expected, base)
        self.assertEqual(base, criterion_revision("F-001", 1, ["backend", "backend"], False, "", "Text."))
        for changed in (
            criterion_revision("F-002", 1, ["backend"], False, "", "Text."),
            criterion_revision("F-001", 2, ["backend"], False, "", "Text."),
            criterion_revision("F-001", 1, ["backend", "worker"], False, "", "Text."),
            criterion_revision("F-001", 1, ["backend", "worker"], True, "", "Text."),
            criterion_revision("F-001", 1, ["backend"], False, "Decided", "Text."),
            criterion_revision("F-001", 1, ["backend"], False, "", "Other text."),
        ):
            self.assertNotEqual(base, changed)
        parsed = parse_criteria("## Acceptance criteria\n- [ ] AC-1 [backend] Text.\n", "F-001")[0]
        self.assertEqual(base, parsed.revision)
        # Whitespace and the checkbox do not change it.
        again = parse_criteria("## Acceptance criteria\n- [x] AC-1 [backend]   Text.  \n", "F-001")[0]
        self.assertEqual(base, again.revision)

    def test_the_high_water_mark(self) -> None:
        self.assertEqual((5, None), criteria_high_water({"criteria-high-water": 5}))
        self.assertEqual((0, None), criteria_high_water({"criteria-high-water": 0}))
        self.assertEqual((None, None), criteria_high_water({}))
        for value in (-1, "5", True, 1.5):
            with self.subTest(value=value):
                mark, problem = criteria_high_water({"criteria-high-water": value})
                self.assertEqual((None, True), (mark, problem is not None))


class StageTests(unittest.TestCase):
    """CONTRACTS 4.2 and 4.4: the app stage rule order, the minimum, the design owner and the QA coverage."""

    def evidence(self, *, delivery: list[str] | None = None, qa: list[str] | None = None, release: list[str] | None = None):
        return read_feature_evidence(body_of([], delivery=delivery, qa=qa, release=release))

    def test_the_stage_rule_order(self) -> None:
        one = ref(1, ["backend"], TEXT_ONE)
        qa = qa_row("backend", [one], "`build:backend#1`")
        cases = [
            ("in-dev", self.evidence()),
            ("ready-for-qa", self.evidence(delivery=[delivery_row("backend")])),
            ("in-qa", self.evidence(delivery=[delivery_row("backend")], qa=[qa])),
            ("ready-for-release", self.evidence(delivery=[delivery_row("backend")], qa=[qa], release=[release_row("backend")])),
            ("released", self.evidence(delivery=[delivery_row("backend")], qa=[qa], release=[release_row("backend", "released")])),
            # A failed authoritative row is not released; the app waits for its release again.
            ("ready-for-release", self.evidence(delivery=[delivery_row("backend")], qa=[qa], release=[release_row("backend", "failed")])),
            # A released row wins over the rows before it, even when nothing else is recorded.
            ("released", self.evidence(release=[release_row("backend", "released")])),
        ]
        for expected, evidence in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, app_stage("backend", evidence))
        self.assertEqual({"backend": "ready-for-qa", "worker": "in-dev"}, app_stages(["backend", "worker"], self.evidence(delivery=[delivery_row("backend")])))

    def test_the_minimum_over_the_stages(self) -> None:
        self.assertEqual("in-dev", minimum_stage(["released", "in-dev", "in-qa"]))
        self.assertEqual("ready-for-release", minimum_stage(["released", "ready-for-release"]))
        self.assertIsNone(minimum_stage([]))

    def test_status_ranks_and_the_owner_by_status(self) -> None:
        order = ["raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "ready-for-qa", "in-qa", "ready-for-release", "released"]
        self.assertEqual(list(range(len(order))), [status_rank(item) for item in order])
        self.assertEqual("po", expected_owner("raw", ["backend"], None))
        self.assertEqual("dev", expected_owner("in-dev", ["backend"], None))
        self.assertEqual("qa", expected_owner("in-qa", ["backend"], None))
        self.assertEqual("release", expected_owner("ready-for-release", ["backend"], None))
        self.assertEqual("none", expected_owner("released", ["backend"], None))

    def test_qa_coverage_gaps(self) -> None:
        text_two = "The saved outcome reaches the worker."
        body = body_of(
            [f"AC-1 [backend] {TEXT_ONE}", f"AC-2 [integration: backend, worker] {text_two}"],
            delivery=[delivery_row("backend"), delivery_row("worker")],
        )
        criteria = parse_criteria(body, "F-001")
        one = ref(1, ["backend"], TEXT_ONE)
        two = ref(2, ["backend", "worker"], text_two, integration=True)
        app_row = qa_row("backend", [one], "`build:backend#1`")
        pair_row = qa_row("integration: backend + worker", [two], "backend=`build:backend#1`; worker=`build:worker#1`")

        def gaps(*rows: str, history: str = "") -> list[str]:
            evidence = read_feature_evidence(body_of([], delivery=[delivery_row("backend"), delivery_row("worker")], qa=list(rows)))
            entries = parse_evidence_history(body_of([], history=history))
            return [gap.code for gap in qa_coverage("backend", criteria, evidence, entries)]

        self.assertEqual(["criterion_not_covered", "integration_not_covered"], gaps())
        self.assertEqual(["integration_not_covered"], gaps(app_row))
        self.assertEqual([], gaps(app_row, pair_row))
        self.assertEqual(["criterion_not_covered", "qa_result_failed"], gaps(qa_row("backend", [one], "`build:backend#1`", result="fail"), pair_row))
        # A row on an artifact that is no longer the delivered one does not cover.
        self.assertEqual(["criterion_not_covered", "integration_not_covered"], gaps(qa_row("backend", [one], "`build:backend#9`"), pair_row.replace("backend=`build:backend#1`", "backend=`build:backend#9`")))
        # A row of another attempt does not cover.
        self.assertIn("criterion_not_covered", gaps(qa_row("backend", [one], "`build:backend#1`", attempt=2), pair_row))
        # A stale revision does not cover and is reported as stale.
        stale_ref = ref(1, ["backend"], "An older wording.")
        evidence = read_feature_evidence(body_of([], delivery=[delivery_row("backend"), delivery_row("worker")], qa=[qa_row("backend", [stale_ref], "`build:backend#1`")]))
        reasons = [reason for _row, reason in stale_qa_rows(criteria, evidence, [])]
        self.assertEqual(1, len(reasons))
        self.assertIn("revision", reasons[0])
        self.assertEqual([], [reason for _row, reason in stale_qa_rows(criteria, evidence, [], skip_apps=["backend"])])

    def test_the_status_board_cell(self) -> None:
        body = body_of([f"AC-1 [backend, worker] {TEXT_ONE}"], delivery=[delivery_row("backend")])
        self.assertEqual("—", app_stages_text("in-design", ["backend", "worker"], body, None))
        self.assertEqual("backend: ready-for-qa; worker: in-dev", app_stages_text("in-dev", ["backend", "worker"], body, None))


class RegistryTests(unittest.TestCase):
    """CONTRACTS 2.3, 2.8 and 1.8: every row is registered, only the rows of enabled packages are available."""

    def test_every_row_is_registered_once(self) -> None:
        rows = sorted({row for spec in ACTION_SPECS for row in spec.rows}, key=lambda item: (item[0] != "F", int(item[1:])))
        self.assertEqual([f"F{n}" for n in range(1, 28)] + [f"B{n}" for n in range(1, 15)], rows)
        names = [spec.action for spec in ACTION_SPECS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(ACTION_BY_ID))

    def test_only_the_rows_of_enabled_packages_are_available(self) -> None:
        self.assertEqual({"D1", "D2"}, set(ENABLED_PACKAGES))
        enabled = sorted(spec.action for spec in ACTION_SPECS if spec.enabled)
        self.assertEqual(
            sorted(
                [
                    "po-specify",
                    "po-handoff",
                    "design-start",
                    "design-ui-done",
                    "tech-design-done",
                    "design-handoff",
                    "dev-start",
                    "dev-done",
                    "dev-return-spec",
                    "dev-return-design",
                    "scope-edit",
                    "operation-repair",
                ]
            ),
            enabled,
        )
        for spec in ACTION_SPECS:
            with self.subTest(action=spec.action):
                self.assertEqual(spec.enabled, spec.available)
                if spec.enabled:
                    self.assertIsNone(spec.unavailable_reason)
                else:
                    self.assertIn(spec.package, spec.unavailable_reason)
                    self.assertNotIn(spec.package, {"D1", "D2"})

    def test_the_direct_human_actions_are_exactly_the_three_of_the_contract(self) -> None:
        human = sorted(spec.action for spec in ACTION_SPECS if MODE_HUMAN_DIRECT in spec.modes and spec.subject == "feature")
        self.assertEqual(["design-start", "dev-start", "po-handoff"], human)

    def test_roles_resolve_from_the_registry(self) -> None:
        self.assertEqual(RolePredicate(all_of=("po",)), required_roles("po-handoff", {}))
        self.assertEqual(RolePredicate(all_of=("dev",)), required_roles("dev-done", {}))
        self.assertEqual(RolePredicate(all_of=("tech-lead",)), required_roles("design-start", {"design_owner": "tech-lead"}))
        self.assertEqual(RolePredicate(all_of=("designer",)), required_roles("design-start", {"design_owner": "designer"}))
        # Without the model the design owner is not resolvable: either design role approves.
        unresolved = required_roles("design-start", {"action": "design-start", "feature_path": FEATURE, "apps": ["backend"]})
        self.assertEqual(("designer", "tech-lead"), tuple(sorted(unresolved.any_of)))
        self.assertIsNone(required_roles("scope-edit", {"status": "in-design"}))
        self.assertEqual(RolePredicate(all_of=("po",)), required_roles("scope-edit", {"status": "in-dev"}))
        self.assertEqual(RolePredicate(all_of=("po",)), required_roles("scope-edit", {}))
        self.assertIsNone(required_roles("not-an-action", {}))
        handoff = required_roles("design-handoff", {"design_owner": "designer", "completes": ["technical"]})
        self.assertEqual({"designer", "tech-lead"}, set(handoff.all_of))
        self.assertEqual(RolePredicate(all_of=("qa",)), required_roles("bug-close", {"disposition": "duplicate"}))

    def test_write_scopes_and_markers(self) -> None:
        self.assertEqual(
            {
                "po-specify",
                "po-handoff",
                "design-start",
                "design-ui-done",
                "tech-design-done",
                "design-handoff",
                "dev-start",
                "dev-done",
                "dev-return-spec",
                "dev-return-design",
                "scope-edit",
            },
            set(WRITE_SCOPES),
        )
        self.assertEqual(3, TRANSITION_CAPABILITY_VERSION)
        # A changed command is at contract v2; the marker is read by the skill layer and the template contract check.
        for action, version in (
            ("po-specify", 2),
            ("po-handoff", 2),
            ("design-start", 2),
            ("design-handoff", 2),
            ("dev-start", 2),
            ("dev-done", 2),
            ("dev-return-spec", 2),
            ("dev-return-design", 2),
            ("design-ui-done", 1),
            ("tech-design-done", 1),
        ):
            with self.subTest(action=action):
                command = lookup_action(action).command
                self.assertEqual(f"prism:{command}-contract:v{version}", capability_marker(lookup_action(action)))


class PolicyTests(unittest.TestCase):
    """CONTRACTS 1.6 and 7: the workflow policy and the delivery targets of SETTINGS.md."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "workspace")
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))["status"])
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["apps"].append({"id": "worker", "name": "worker", "stack": "other", "repository": "workspace", "path": "tools/worker", "capabilities": NO_API})
        (self.root / "tools" / "worker").mkdir(parents=True)
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        self.wiki = self.root / "knowledge" / "wiki"
        self.model = inspect_workspace(self.root).model

    def settings(self, frontmatter: dict | None) -> dict:
        text = "---\n" + yaml.safe_dump({"wiki-stale-after-days": 30, **(frontmatter or {})}, sort_keys=False) + "---\n\n# Settings\n"
        (self.wiki / "SETTINGS.md").write_text(text, encoding="utf-8")
        return workflow_policy(self.wiki, self.model)

    def test_defaults_come_from_the_stack(self) -> None:
        policy = self.settings({})
        self.assertEqual((True, [], False), (policy["valid"], policy["errors"], policy["qa_separate_from_dev"]))
        self.assertEqual({"kind": "deployment", "target": "production", "environments": []}, policy["delivery_targets"]["backend"])
        # An app of the `other` stack must declare a target before a release.
        self.assertNotIn("worker", policy["delivery_targets"])

    def test_declared_targets_override_the_defaults_and_the_separation_key_is_read(self) -> None:
        policy = self.settings(
            {
                "qa-separate-from-dev": True,
                "delivery-targets": {
                    "backend": {"target": "eu-production", "environments": ["staging", "eu-production"]},
                    "worker": {"kind": "artifact", "target": "internal-registry"},
                },
            }
        )
        self.assertTrue(policy["valid"], policy["errors"])
        self.assertTrue(policy["qa_separate_from_dev"])
        self.assertEqual({"kind": "deployment", "target": "eu-production", "environments": ["staging", "eu-production"]}, policy["delivery_targets"]["backend"])
        self.assertEqual({"kind": "artifact", "target": "internal-registry", "environments": []}, policy["delivery_targets"]["worker"])

    def test_a_malformed_value_is_an_error_and_never_read_as_the_default(self) -> None:
        bad = {
            "separation is a string": ({"qa-separate-from-dev": "yes"}, "invalid-workflow-policy"),
            "targets is a list": ({"delivery-targets": ["backend"]}, "invalid-delivery-target"),
            "unknown app": ({"delivery-targets": {"nowhere": {"target": "production"}}}, "invalid-delivery-target"),
            "unknown kind": ({"delivery-targets": {"backend": {"kind": "teleport"}}}, "invalid-delivery-target"),
            "unknown key": ({"delivery-targets": {"backend": {"region": "eu"}}}, "invalid-delivery-target"),
            "duplicate environment": ({"delivery-targets": {"backend": {"environments": ["staging", "staging"]}}}, "invalid-delivery-target"),
        }
        for name, (frontmatter, code) in bad.items():
            with self.subTest(case=name):
                policy = self.settings(frontmatter)
                self.assertFalse(policy["valid"])
                self.assertEqual(code, policy["errors"][0]["code"])
                self.assertFalse(policy["qa_separate_from_dev"])
        lint = lint_wiki(self.root)
        self.settings({"qa-separate-from-dev": "yes"})
        codes = {(item.code, item.severity) for item in lint_wiki(self.root).diagnostics}
        self.assertIn(("invalid-workflow-policy", "error"), codes)
        self.assertNotIn("invalid-workflow-policy", {item.code for item in lint.diagnostics})

    def test_the_revision_is_the_hash_of_the_canonical_policy(self) -> None:
        first = self.settings({"qa-separate-from-dev": True})
        again = self.settings({"qa-separate-from-dev": True})
        other = self.settings({"qa-separate-from-dev": False})
        self.assertEqual(first["revision"], again["revision"])
        self.assertNotEqual(first["revision"], other["revision"])
        settings = read_wiki_settings(self.wiki, self.model)
        expected = hashlib.sha256(canonical_json(settings.policy).encode("utf-8")).hexdigest()
        self.assertEqual(expected, settings.policy_revision)
        self.assertEqual(settings.policy_revision, workflow_policy(self.wiki, self.model)["revision"])


class _Workspace(unittest.TestCase):
    """A disposable workspace with the apps `backend` and `worker` and the board pages of one feature."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "workspace")
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))["status"])
        (self.root / INTAKE_ITEM).parent.rename(self.root / SOURCE)
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["apps"].append({"id": "worker", "name": "worker", "stack": "other", "repository": "workspace", "path": "tools/worker", "capabilities": NO_API})
        (self.root / "tools" / "worker").mkdir(parents=True)
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    def page(
        self,
        status: str,
        owner: str,
        apps: list[str],
        criteria: list[str],
        *,
        delivery: list[str] | None = None,
        qa: list[str] | None = None,
        release: list[str] | None = None,
        history: str = "",
        high_water: int | None = None,
        questions: list[str] | None = None,
    ) -> str:
        page = _journey_feature_page("F-001", "Document review", status, owner, [SOURCE], questions or [])
        frontmatter, body = _parse_markdown(page)
        frontmatter["apps"] = apps
        frontmatter["criteria-high-water"] = len(criteria) if high_water is None else high_water
        page = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        scope = "\n".join(f"- **{app}**: Deliver the review summary in {app}." for app in apps)
        page = _replace_body_section_text(page, "App scope", scope)
        page = _replace_body_section_text(page, "Acceptance criteria", "\n".join(f"- [ ] {line}" for line in criteria))
        page = _replace_body_section_text(page, "Delivery evidence", table(DELIVERY_HEADER, delivery or []))
        page = _replace_body_section_text(page, "QA verification", table(QA_HEADER, qa or []))
        page = _replace_body_section_text(page, "Release", table(RELEASE_HEADER, release or []))
        return _replace_body_section_text(page, "Evidence history", history)

    def seed(self, status: str, owner: str, content: str) -> None:
        path = self.root / FEATURE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        _write_index_rows(self.root, [("F-001", "Document review", status, owner)])


class LintTests(_Workspace):
    """CONTRACTS 4.5: the lint codes of the lifecycle model on seeded per-app states."""

    BOTH = ["backend", "worker"]

    def codes(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.feature_id in {None, "F-001"} and item.severity == "error"}

    def criteria(self) -> list[str]:
        return [f"AC-1 [backend, worker] {TEXT_ONE}", f"AC-2 [backend] {TEXT_TWO}"]

    def delivered(self, apps: list[str] | None = None) -> list[str]:
        return [delivery_row(app) for app in apps or self.BOTH]

    def covering_qa(self, apps: list[str] | None = None) -> list[str]:
        rows = []
        for app in apps or self.BOTH:
            refs = [ref(1, self.BOTH, TEXT_ONE)] if app == "worker" else [ref(1, self.BOTH, TEXT_ONE), ref(2, ["backend"], TEXT_TWO)]
            rows.append(qa_row(app, refs, f"`{ARTIFACT[app]}`"))
        return rows

    def test_a_consistent_state_has_none_of_the_lifecycle_findings(self) -> None:
        states = {
            "in-dev, nothing delivered": ("in-dev", "dev", {}),
            "in-dev, one app delivered": ("in-dev", "dev", {"delivery": self.delivered(["backend"])}),
            "ready-for-qa": ("ready-for-qa", "qa", {"delivery": self.delivered()}),
            "in-qa": ("in-qa", "qa", {"delivery": self.delivered(), "qa": self.covering_qa()}),
            "ready-for-release": ("ready-for-release", "release", {"delivery": self.delivered(), "qa": self.covering_qa(), "release": [release_row(app) for app in self.BOTH]}),
            "released": ("released", "none", {"delivery": self.delivered(), "qa": self.covering_qa(), "release": [release_row(app, "released") for app in self.BOTH]}),
        }
        family = {
            "invalid-evidence-row", "app-row-ahead-of-status", "undeclared-app-row", "duplicate-app-row", "no-active-app-in-scope",
            "feature-status-not-minimum", "app-row-missing", "app-row-out-of-order", "stale-qa-evidence", "stale-delivery-evidence",
            "app-without-criteria", "invalid-applies-to", "duplicate-criterion-id", "criterion-high-water-invalid", "status-board-frontmatter-drift",
        }
        for name, (status, owner, rows) in states.items():
            with self.subTest(state=name):
                self.seed(status, owner, self.page(status, owner, self.BOTH, self.criteria(), **rows))
                self.assertEqual(set(), self.codes() & family, name)

    def test_rows_ahead_of_the_status(self) -> None:
        for status, owner in (("raw", "po"), ("specified", "po"), ("ready-for-dev", "dev")):
            with self.subTest(status=status):
                self.seed(status, owner, self.page(status, owner, self.BOTH, self.criteria(), delivery=self.delivered(["backend"])))
                self.assertIn("app-row-ahead-of-status", self.codes())

    def test_a_status_that_is_not_the_minimum_names_the_missing_rows(self) -> None:
        self.seed("ready-for-qa", "qa", self.page("ready-for-qa", "qa", self.BOTH, self.criteria(), delivery=self.delivered(["backend"])))
        codes = self.codes()
        self.assertIn("feature-status-not-minimum", codes)
        self.assertIn("app-row-missing", codes)
        messages = [item.message for item in lint_wiki(self.root).diagnostics if item.code == "app-row-missing"]
        self.assertTrue(any("`worker`" in message for message in messages), messages)
        # The other direction: every app delivered but the feature still in-dev.
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, self.criteria(), delivery=self.delivered()))
        self.assertIn("feature-status-not-minimum", self.codes())

    def test_criteria_findings(self) -> None:
        no_worker = [f"AC-1 [backend] {TEXT_ONE}", f"AC-2 [backend] {TEXT_TWO}"]
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, no_worker))
        self.assertIn("app-without-criteria", self.codes())

        outside = [f"AC-1 [backend, web] {TEXT_ONE}", f"AC-2 [backend, worker] {TEXT_TWO}"]
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, outside))
        self.assertIn("invalid-applies-to", self.codes())

        duplicate = [f"AC-1 [backend, worker] {TEXT_ONE}", f"AC-1 [backend] {TEXT_TWO}"]
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, duplicate))
        self.assertIn("duplicate-criterion-id", self.codes())

        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, self.criteria(), high_water=1))
        self.assertIn("criterion-high-water-invalid", self.codes())

    def test_evidence_findings(self) -> None:
        # A row of an app outside the scope, and two rows for one app.
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, self.criteria(), delivery=[delivery_row("backend"), delivery_row("backend")]))
        self.assertIn("duplicate-app-row", self.codes())
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, self.criteria(), delivery=[delivery_row("backend", "build:backend#1").replace("| backend |", "| web |", 1)]))
        self.assertIn("undeclared-app-row", self.codes())
        # A QA row of an app with no delivery evidence.
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, self.criteria(), qa=self.covering_qa(["backend"])))
        self.assertIn("app-row-out-of-order", self.codes())
        # A malformed row.
        broken = delivery_row("backend").replace("checked", "maybe")
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, self.criteria(), delivery=[broken]))
        self.assertIn("invalid-evidence-row", self.codes())
        # A delivery row bound to the contract of another feature.
        other = delivery_row("backend", contract=f"F-002@v1:c1:{SHA}")
        self.seed("in-dev", "dev", self.page("in-dev", "dev", self.BOTH, self.criteria(), delivery=[other]))
        self.assertIn("stale-delivery-evidence", self.codes())

    def test_a_qa_row_of_an_older_criterion_revision_is_stale(self) -> None:
        stale = [qa_row("backend", [ref(1, self.BOTH, "An older wording.")], f"`{ARTIFACT['backend']}`")]
        self.seed("in-qa", "qa", self.page("in-qa", "qa", self.BOTH, self.criteria(), delivery=self.delivered(), qa=stale))
        self.assertIn("stale-qa-evidence", self.codes())
        # The row of a released app is history and is never stale.
        released = self.page(
            "released",
            "none",
            self.BOTH,
            self.criteria(),
            delivery=self.delivered(),
            qa=self.covering_qa(),
            release=[release_row(app, "released") for app in self.BOTH],
        ).replace(TEXT_TWO, "A reworded criterion that the released rows never saw.", 1)
        self.seed("released", "none", released)
        self.assertNotIn("stale-qa-evidence", self.codes())

    def test_a_release_row_needs_qa_coverage(self) -> None:
        self.seed(
            "ready-for-release",
            "release",
            self.page("ready-for-release", "release", self.BOTH, self.criteria(), delivery=self.delivered(), qa=self.covering_qa(["backend"]), release=[release_row(app) for app in self.BOTH]),
        )
        self.assertIn("app-row-out-of-order", self.codes())

    def test_a_status_board_that_disagrees_with_the_stages_is_drift(self) -> None:
        self.seed("ready-for-qa", "qa", self.page("ready-for-qa", "qa", self.BOTH, self.criteria(), delivery=self.delivered()))
        self.assertNotIn("status-board-frontmatter-drift", self.codes())
        board = self.root / "knowledge" / "wiki" / "status-board.md"
        text = board.read_text(encoding="utf-8")
        board.write_text(text.replace("backend: ready-for-qa; worker: ready-for-qa", "backend: in-dev; worker: in-dev"), encoding="utf-8", newline="\n")
        self.assertIn("status-board-frontmatter-drift", self.codes())


class FlowTests(_Workspace):
    """F1, F2, F3, F6, F7, F8, F9 and F26 through the board service, and the actions of later packages."""

    BOTH = ["backend", "worker"]

    def setUp(self) -> None:
        super().setUp()
        self.seed("raw", "po", self.page("raw", "po", self.BOTH, [f"AC-1 [backend, worker] {TEXT_ONE}", f"AC-2 [backend] {TEXT_TWO}"], questions=["| 1 | Which details should the summary emphasize? | po | resolved: The key points. |"]))
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Workflow agent", "agent", True)["token"])
        # Every gated step is approved by this human, who holds every role and signs in to the board.
        self.human = human_with_roles(self.service, "Workflow owner")

    def read(self, relative: str) -> str:
        return self.service._read_text(self.root / relative)

    def skill(self, name: str, changes: list[dict[str, str]]) -> dict:
        preview = self.service.preview_skill(self.agent, name, changes, None, _read_revisions(self.service, self.agent, name, changes))
        self.assertEqual("ready", preview["classification"], f"{name}: {preview['checks']}")
        self.assertTrue(preview["applicable"], f"{name}: {preview['blockers']}")
        return preview

    def apply_skill(self, name: str, changes: list[dict[str, str]]) -> dict:
        preview = self.skill(name, changes)
        self.assertEqual("applied", apply_preview(self.service, self.agent, preview, str(uuid4()), approver=self.human)["state"])
        return preview

    def human_action(self, action: str) -> dict:
        preview = self.service.preview_transition(self.human, "F-001", action, {"semantic_review_acknowledged": True})
        self.assertEqual("ready", preview["classification"], f"{action}: {preview['checks']}")
        self.assertTrue(preview["applicable"], f"{action}: {preview['blockers']}")
        self.assertEqual("applied", apply_preview(self.service, self.human, preview, str(uuid4()))["state"])
        return preview

    def requirement(self, app: str, status: str) -> str:
        return _set_requirement_status(_journey_requirement_page("pending").replace("app: backend", f"app: {app}"), status)

    def rejection(self, name: str, changes: list[dict[str, str]]) -> BoardError:
        with self.assertRaises(BoardError) as caught:
            self.service.preview_skill(self.agent, name, changes, None, _read_revisions(self.service, self.agent, name, changes))
        return caught.exception

    def status(self) -> tuple[str, str]:
        frontmatter = _parse_markdown(self.read(FEATURE))[0]
        return frontmatter["status"], frontmatter["owner"]

    def deliver(self, app: str, status: str, owner: str) -> list[dict[str, str]]:
        current = self.read(FEATURE)
        body = _parse_markdown(current)[1]
        rows = [row.cells for row in read_feature_evidence(body).delivery]
        existing = [line for line in table(DELIVERY_HEADER, []).splitlines()[2:]]
        existing += [f"| {' | '.join(cells)} |" for cells in rows]
        updated = _replace_body_section(self.service, _set_feature_stage(current, status, owner, self.service), "Delivery evidence", table(DELIVERY_HEADER, [*existing, delivery_row(app)]))
        requirement_path = f"knowledge/wiki/app-requirements/F-001-{app}.md"
        return [
            {"path": FEATURE, "content": updated},
            {"path": requirement_path, "content": _set_requirement_status(self.read(requirement_path), "done")},
        ]

    def test_the_feature_goes_from_raw_to_ready_for_qa_through_f1_f2_f3_f6_f7_f8_f9(self) -> None:
        # F1: po-specify.
        specified = _set_feature_stage(self.read(FEATURE), "specified", "po", self.service)
        preview = self.apply_skill("po-specify", [{"path": FEATURE, "content": specified}])
        self.assertEqual(("po-specify", ("specified", "po")), (preview["action"], self.status()))
        # F2, F3: the direct human actions; the design owner of a scope with no UI is the tech lead.
        handoff = self.human_action("po-handoff")
        self.assertEqual({"status": "ready-for-design", "owner": "tech-lead"}, handoff["target"])
        self.human_action("design-start")
        self.assertEqual(("in-design", "tech-lead"), self.status())
        # F6: design-handoff writes one pending requirement per app.
        current = self.read(FEATURE)
        handed = _set_feature_stage(current, "ready-for-dev", "dev", self.service)
        self.apply_skill(
            "design-handoff",
            [
                {"path": FEATURE, "content": handed},
                {"path": "knowledge/wiki/app-requirements/F-001-backend.md", "content": self.requirement("backend", "pending")},
                {"path": "knowledge/wiki/app-requirements/F-001-worker.md", "content": self.requirement("worker", "pending")},
            ],
        )
        self.assertEqual(("ready-for-dev", "dev"), self.status())
        # F7: dev-start.
        self.human_action("dev-start")
        self.assertEqual(("in-dev", "dev"), self.status())

        # F8: the first app is delivered; the feature stays in-dev because worker is still in-dev.
        changes = self.deliver("backend", "in-dev", "dev")
        preview = self.apply_skill("dev-done", changes)
        self.assertEqual(("in-dev", "dev"), self.status())
        produced = preview["produces_evidence"]
        self.assertEqual([("delivery", "F-001", "backend", 1)], [(item["kind"], item["item_id"], item["app"], item["generation"]) for item in produced])
        cells = read_feature_evidence(_parse_markdown(self.read(FEATURE))[1]).delivery[0].cells
        self.assertEqual(row_digest(cells), produced[0]["row_digest"])
        self.assertEqual([], preview["separation_subjects"])
        self.assertIn("backend: ready-for-qa; worker: in-dev", self.read("knowledge/wiki/status-board.md"))
        # An app that already has a row is not delivered again, and a dev-done that names no app is refused.
        again = self.rejection("dev-done", self.deliver("backend", "in-dev", "dev"))
        self.assertIn(again.code, {"evidence_still_active", "delivery_evidence_required"})

        # F9: the last app moves the feature to ready-for-qa.
        preview = self.apply_skill("dev-done", self.deliver("worker", "ready-for-qa", "qa"))
        self.assertEqual(("ready-for-qa", "qa"), self.status())
        self.assertEqual(["worker"], [item["app"] for item in preview["produces_evidence"]])
        board = self.read("knowledge/wiki/status-board.md")
        self.assertIn("backend: ready-for-qa; worker: ready-for-qa", board)
        self.assertIn("| F-001 | Document review | ready-for-qa | qa |", board)
        self.assertEqual(set(), {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error" and item.feature_id == "F-001"})

    def test_dev_done_binds_each_delivery_row_to_the_operation_its_approver_applied(self) -> None:
        # The evidence the preview declares (`produces_evidence`) is what the journal binds at apply (CONTRACTS 1.6).
        self.walk_to_dev()
        preview = self.apply_skill("dev-done", self.deliver("backend", "in-dev", "dev"))
        produced = preview["produces_evidence"]
        self.assertEqual(1, len(produced))
        bound = self.service.store.connection.execute(
            "SELECT operation_id, row_digest, kind, generation FROM provenance WHERE board_id = ? AND item_id = 'F-001' AND app = 'backend'",
            (self.service._board_id,),
        ).fetchall()
        self.assertEqual([(produced[0]["row_digest"], "delivery", 1)], [(row[1], row[2], row[3]) for row in bound])
        operation = bound[0][0]
        intent = self.service.store.connection.execute("SELECT participant_id, intent_json FROM operations WHERE operation_id = ?", (operation,)).fetchone()
        self.assertEqual(produced, __import__("json").loads(intent[1])["produces_evidence"])
        # The approver, not the proposing agent, produced the evidence as far as separation is concerned.
        self.assertEqual(self.human.participant_id, intent[0])
        self.assertEqual({self.human.participant_id}, self.service._excluded_approvers(operation))
        found = self.service._producing_operation("delivery", "F-001", "backend", 1, produced[0]["row_digest"])
        self.assertEqual({"status": "match", "operation_id": operation}, found)

    def test_a_dev_done_status_must_be_the_minimum_of_the_stages(self) -> None:
        self.walk_to_dev()
        error = self.rejection("dev-done", self.deliver("backend", "ready-for-qa", "qa"))
        self.assertEqual(("app_stage_mismatch", 409), (error.code, error.status))
        self.assertEqual("in-dev", error.details["minimum"])

    def walk_to_dev(self) -> None:
        specified = _set_feature_stage(self.read(FEATURE), "specified", "po", self.service)
        self.apply_skill("po-specify", [{"path": FEATURE, "content": specified}])
        self.human_action("po-handoff")
        self.human_action("design-start")
        handed = _set_feature_stage(self.read(FEATURE), "ready-for-dev", "dev", self.service)
        self.apply_skill(
            "design-handoff",
            [
                {"path": FEATURE, "content": handed},
                {"path": "knowledge/wiki/app-requirements/F-001-backend.md", "content": self.requirement("backend", "pending")},
                {"path": "knowledge/wiki/app-requirements/F-001-worker.md", "content": self.requirement("worker", "pending")},
            ],
        )
        self.human_action("dev-start")

    def test_the_scope_edit_of_f26_removes_a_retired_app_and_archives_its_evidence(self) -> None:
        self.walk_to_dev()
        self.apply_skill("dev-done", self.deliver("backend", "in-dev", "dev"))
        self.apply_skill("dev-done", self.deliver("worker", "ready-for-qa", "qa"))
        code, _out, err = run_cli("app", "retire", "worker", str(self.root), "--apply", "--yes")
        self.assertEqual(0, code, err)
        self.service.close()
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Scope agent", "agent", True)["token"])
        self.human = human_with_roles(self.service, "Scope owner")

        current = self.read(FEATURE)
        body = _parse_markdown(current)[1]
        worker_row = read_feature_evidence(body).delivery_row("worker").cells
        frontmatter, _body = _parse_markdown(current)
        frontmatter["apps"] = ["backend"]
        edited = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
        edited = _replace_body_section_text(edited, "App scope", "- **backend**: Deliver the review summary in backend.")
        edited = _replace_body_section_text(
            edited, "Acceptance criteria", f"- [ ] AC-1 [backend] {TEXT_ONE}\n- [ ] AC-2 [backend] {TEXT_TWO}"
        )
        remaining = [line for line in table(DELIVERY_HEADER, []).splitlines()[2:]] + [delivery_row("backend")]
        edited = _replace_body_section_text(edited, "Delivery evidence", table(DELIVERY_HEADER, remaining))
        entry = "\n".join(
            [
                f"### {__import__('datetime').date.today().isoformat()} - scope-edit",
                "- Reason: The retired worker leaves the scope of the feature.",
                "- Affected apps: worker",
                "- Participants: none",
                "- Affected tracks: none",
                "- Archived evidence:",
                "  | Delivery evidence | " + " | ".join(cells.strip() for cells in worker_row) + " |",
                "- Reaffirmed evidence: none",
                "- Requirement/API invalidations: No requirement or API page is invalidated.",
                "- Linked bugs: none",
            ]
        )
        edited = _replace_body_section_text(edited, "Evidence history", entry)
        preview = self.service.preview_skill(self.agent, "feature-scope", [{"path": FEATURE, "content": edited}], None, _read_revisions(self.service, self.agent, "feature-scope", [{"path": FEATURE, "content": edited}]))
        self.assertEqual("scope-edit", preview["action"])
        self.assertEqual("ready", preview["classification"], preview["checks"])
        # From `ready-for-dev` on, the scope edit is the gated `scope-edit` action: `po` approves it.
        self.assertEqual({"all_of": ["po"], "any_of": []}, preview["approval"]["required_roles"])
        self.assertEqual("applied", apply_preview(self.service, self.agent, preview, str(uuid4()), approver=self.human)["state"])
        self.assertEqual(("ready-for-qa", "qa"), self.status())
        self.assertIn("backend: ready-for-qa", self.read("knowledge/wiki/status-board.md"))
        self.assertNotIn("worker", self.read("knowledge/wiki/status-board.md").split("| F-001 |", 1)[1].splitlines()[0])

    def test_actions_of_later_packages_answer_action_unavailable(self) -> None:
        self.walk_to_dev()
        for action in ("qa-pass", "release-done", "qa-return-design", "reopen-dev"):
            with self.subTest(action=action), self.assertRaises(BoardError) as caught:
                self.service.query(self.agent, "transition-preflight", "F-001", action)
            self.assertEqual("action_unavailable", caught.exception.code)
        unavailable = build_board_transition_preflight(self.root, "F-001", "qa-pass")
        self.assertEqual("unknown", unavailable["classification"])
        self.assertEqual("action-unavailable", unavailable["checks"][0]["code"])
        self.assertEqual("D3", lookup_action("qa-pass").package)

    def test_a_warning_check_does_not_block(self) -> None:
        from prism_cli.board_service import _classification

        checks = [
            {"code": "a", "status": "pass", "message": "ok"},
            {"code": "cross-app-dependency", "status": "warning", "message": "worker waits for backend"},
        ]
        self.assertEqual("ready", _classification(checks))
        self.assertEqual("blocked", _classification([*checks, {"code": "b", "status": "blocked", "message": "no"}]))
        self.assertEqual("unknown", _classification([*checks, {"code": "c", "status": "unknown", "message": "?"}]))


if __name__ == "__main__":
    unittest.main()
