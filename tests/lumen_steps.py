"""The nineteen steps of the Lumen Library case (CONTRACTS 10.1) as proposals, and the state each step leaves.

`LumenSteps` is a mixin. A host supplies `read`, `put` and `exists` for the workspace; each step method reads the pages as they are
and returns the `Proposal` that moves them on: the changes an Agent proposes over MCP, who approves them, and (for a step the
contract says is refused first) who is refused. The board test applies the proposals through the service. The direct-file test
writes the same changes straight into the files and checks them with lint alone.

`EXPECTED` is written from CONTRACTS 10.1 and 8.2: the status and owner, the app stages, the evidence rows, the records and the
status-board rows after each step. It never calls the code that derives them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prism_cli.wiki_model import contract_page_citation
from prism_cli.wiki_releases import format_snapshot
from tests.lumen_library import (
    APPS,
    BRIEF,
    CATALOG,
    CATALOG_BUILD,
    CATALOG_FIX_BUILD,
    CONTRACT_PATH,
    DESIGN_PATH,
    DESIGNER_ANSWER,
    DESIGNER_QUESTION,
    FEATURE_ID,
    FEATURE_PATH,
    INCIDENT_PATH,
    READER,
    READER_BUILD,
    READER_FIX_BUILD,
    RELEASE_DIR,
    REQUIREMENT_PATHS,
    TECH_PATH,
    TEXT_1,
    TEXT_1_EDITED,
    TODAY,
    append_history,
    bug_page,
    bug_path,
    contract_cell,
    contract_page,
    delivery_row,
    design_page,
    fix_row,
    history_entry,
    incident_page,
    pending_release_row,
    qa_row,
    raw_feature_page,
    record_row,
    ref_1,
    ref_2,
    ref_3,
    release_row,
    requirement_page,
    set_frontmatter,
    set_section,
    split_page,
    table,
    table_rows,
    technical_page,
    tracks,
    verification_row,
    with_rows,
)
from tests.release_pages import record_page

TARGET = {CATALOG: "production", READER: "play-store"}
BUG_1_TITLE = "Reserve button does nothing"
BUG_2_TITLE = "Reservation response lacks the pickup date"
BUG_3_TITLE = "Reservation cache ignores copy status"
BUG_1, BUG_2, BUG_3 = bug_path(1, BUG_1_TITLE), bug_path(2, BUG_2_TITLE), bug_path(3, BUG_3_TITLE)
QUESTION_PO = "| 3 | Should the reservation response include the pickup date? | po | open |"
PICKUP_ANSWER = TEXT_1_EDITED


@dataclass
class Proposal:
    """One write an Agent proposes: a skill with its changes (or a human-direct action), and who approves it."""

    label: str
    skill: str | None
    changes: list[dict[str, str]] = field(default_factory=list)
    person: str | None = None
    moves: list[dict[str, str]] | None = None
    direct: str | None = None
    refused: tuple[str, str] | None = None  # (person, code): the board refuses this person first


def change(path: str, content: str) -> dict[str, str]:
    return {"path": path, "content": content}


def line_of(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


class LumenSteps:
    """The proposals of the case. A host provides `read(path)`, `put(path, text)` and `exists(path)`."""

    # -- helpers ---------------------------------------------------------------------------------------------------------

    def read(self, relative: str) -> str:  # pragma: no cover - supplied by the host
        raise NotImplementedError

    def put(self, relative: str, text: str) -> None:  # pragma: no cover - supplied by the host
        raise NotImplementedError

    def exists(self, relative: str) -> bool:  # pragma: no cover - supplied by the host
        raise NotImplementedError

    def feature_text(self) -> str:
        return self.read(FEATURE_PATH)

    def evidence_rows(self):
        from prism_cli.wiki_model import read_feature_evidence

        return read_feature_evidence(split_page(self.feature_text())[1])

    def intake(self, name: str, pages: dict[str, str], label: str, note: str = "Captured: 2026-10-09\n\nThe source says what the pages record.\n") -> Proposal:
        """An `ingest` of a dated intake folder into `pages` (wiki-relative path to content)."""

        folder = f"knowledge/intake/pending/{name}"
        destination = folder.replace("pending", "processed", 1)
        self.put(f"{folder}/note.md", note)
        lines = ["# Processed intake", ""]
        for relative, content in pages.items():
            frontmatter = split_page(content)[0]
            identifier = frontmatter.get("id") or frontmatter.get("feature-id")
            lines.append(f"- knowledge/wiki/{relative}" + (f" ({identifier})" if identifier else ""))
        changes = [change(f"knowledge/wiki/{relative}", content) for relative, content in pages.items()]
        changes.append(change(f"{destination}/MANIFEST.md", "\n".join(lines) + "\n"))
        return Proposal(label, "ingest", changes, None, [{"source": folder, "destination": destination}])

    # -- 1 to 5: intake, specification and design -----------------------------------------------------------------------------

    def ingest_feature(self) -> Proposal:
        brief = f"knowledge/intake/pending/{BRIEF}"
        destination = brief.replace("pending", "processed", 1)
        changes = [change(FEATURE_PATH, raw_feature_page()), change(f"{destination}/MANIFEST.md", f"# Processed intake\n\n- {FEATURE_PATH} ({FEATURE_ID})\n")]
        return Proposal("ingest F-001", "ingest", changes, None, [{"source": brief, "destination": destination}])

    def po_specify(self) -> Proposal:
        page = set_frontmatter(self.feature_text(), {"status": "specified", "owner": "po"})
        return Proposal("po-specify", "po-specify", [change(FEATURE_PATH, page)], "Pat")

    def po_handoff(self) -> Proposal:
        page = set_frontmatter(self.feature_text(), {"status": "ready-for-design", "owner": "designer"})
        return Proposal("po-handoff", None, [change(FEATURE_PATH, page)], "Pat", direct="po-handoff")

    def tech_design_first(self) -> Proposal:
        page = set_frontmatter(self.feature_text(), {"status": "in-design", **tracks("pending", "done").frontmatter()})
        changes = [change(FEATURE_PATH, page), change(TECH_PATH, technical_page()), change(CONTRACT_PATH, contract_page())]
        return Proposal("tech-design-done (implicit pickup, contract agreed)", "tech-design-done", changes, "Theo")

    def design_clarify(self) -> Proposal:
        page = self.feature_text().replace(DESIGNER_QUESTION, DESIGNER_QUESTION.replace("open", "resolved: " + DESIGNER_ANSWER))
        page = set_frontmatter(page, tracks("pending", "pending").frontmatter())
        return Proposal("design-clarify (technical design page edited, technical pending)", "design-clarify", [change(FEATURE_PATH, page), change(TECH_PATH, technical_page(hold="three"))])

    def tech_design_again(self) -> Proposal:
        page = set_frontmatter(self.feature_text(), tracks("pending", "done").frontmatter())
        return Proposal("tech-design-done (again)", "tech-design-done", [change(FEATURE_PATH, page)], "Theo")

    def design_handoff(self) -> Proposal:
        page = set_frontmatter(self.feature_text(), {"status": "ready-for-dev", "owner": "dev", **tracks("done", "done").frontmatter(), "revalidation": []})
        page = set_section(page, "Design", "The book page design is in [the design page](../design/F-001-reserve-a-book.md).")
        changes = [change(FEATURE_PATH, page), change(DESIGN_PATH, design_page())]
        changes += [change(REQUIREMENT_PATHS[app], requirement_page(app)) for app in APPS]
        return Proposal("design-handoff (completes ui)", "design-handoff", changes, "Dana")

    # -- 6 to 14: development, QA, the failure and its bug ---------------------------------------------------------------------

    def deliver(self, app: str, artifact: str, status: str, owner: str, *, pull: int, contract: str = "implemented", revalidation: dict[str, list[str]] | None = None) -> list[dict[str, str]]:
        rows = [*table_rows(self.feature_text(), "Delivery evidence"), delivery_row(app, artifact, contract_cell(), pull=pull)]
        page = with_rows(self.feature_text(), "Delivery evidence", "delivery", rows)
        page = set_frontmatter(page, {"status": status, "owner": owner, **({"app-revalidation": revalidation} if revalidation else {})})
        changes = [change(FEATURE_PATH, page), change(REQUIREMENT_PATHS[app], set_frontmatter(self.read(REQUIREMENT_PATHS[app]), {"status": "done"}))]
        if status != "in-dev":
            changes.append(change(CONTRACT_PATH, set_frontmatter(self.read(CONTRACT_PATH), {"status": "implemented"})))
        return changes

    def dev_done_catalog(self) -> Proposal:
        return Proposal("dev-done catalog-api (implicit pickup)", "dev-done", self.deliver(CATALOG, CATALOG_BUILD, "in-dev", "dev", pull=31), "Devi")

    def qa_verify_catalog(self) -> Proposal:
        rows = [*table_rows(self.feature_text(), "QA verification"), qa_row(CATALOG, [ref_1()], f"`{CATALOG_BUILD}`", attempt=1)]
        return Proposal("qa-verify catalog-api AC-1 pass", "qa-verify", [change(FEATURE_PATH, with_rows(self.feature_text(), "QA verification", "qa", rows))], "Quinn")

    def ask_po(self) -> Proposal:
        page = self.feature_text()
        marker = next(line for line in page.splitlines() if line.startswith("| 2 |"))
        page = page.replace(marker, marker + "\n" + QUESTION_PO)
        return Proposal("ask the PO about the pickup date", "ask", [change(FEATURE_PATH, page)])

    def po_clarify(self) -> Proposal:
        page = self.feature_text().replace(f"AC-1 [{CATALOG}] {TEXT_1}", f"AC-1 [{CATALOG}] {TEXT_1_EDITED}")
        page = page.replace(QUESTION_PO, QUESTION_PO.replace("open", "resolved: " + PICKUP_ANSWER))
        return Proposal("po-clarify edits AC-1", "po-clarify", [change(FEATURE_PATH, page)])

    def qa_verify_replace(self) -> Proposal:
        page = with_rows(self.feature_text(), "QA verification", "qa", [qa_row(CATALOG, [ref_1(TEXT_1_EDITED)], f"`{CATALOG_BUILD}`", attempt=1)])
        return Proposal("qa-verify replaces the AC-1 row in qa-1", "qa-verify", [change(FEATURE_PATH, page)], "Quinn")

    def dev_done_reader(self) -> Proposal:
        return Proposal("dev-done reader-app", "dev-done", self.deliver(READER, READER_BUILD, "ready-for-qa", "qa", pull=32), "Devi")

    def qa_verify_reader_fail(self) -> Proposal:
        rows = [*table_rows(self.feature_text(), "QA verification"), qa_row(READER, [ref_2()], f"`{READER_BUILD}`", attempt=1, result="fail")]
        page = set_frontmatter(with_rows(self.feature_text(), "QA verification", "qa", rows), {"status": "in-qa", "owner": "qa"})
        changes = [change(FEATURE_PATH, page), change(BUG_1, bug_page(1, BUG_1_TITLE, READER_BUILD))]
        return Proposal("qa-verify reader-app AC-2 fail, opens BUG-001", "qa-verify", changes, "Quinn")

    def qa_fail_reader(self) -> Proposal:
        evidence = self.evidence_rows()
        archive = [("Delivery evidence", line_of(row.cells)) for row in evidence.delivery if row.app == READER]
        archive += [("QA verification", line_of(row.cells)) for row in evidence.qa if READER in row.apps]
        page = self.feature_text()
        page = with_rows(page, "Delivery evidence", "delivery", [line_of(row.cells) for row in evidence.delivery if row.app != READER])
        page = with_rows(page, "QA verification", "qa", [line_of(row.cells) for row in evidence.qa if READER not in row.apps])
        invalidations = f"{REQUIREMENT_PATHS[READER]}: done -> in-progress; {CONTRACT_PATH}: implemented -> agreed"
        page = append_history(page, history_entry("qa-fail", reason="The reserve button does nothing in the reader app.", affected=READER, archived=archive, invalidations=invalidations, linked="BUG-001"))
        page = set_frontmatter(page, {"status": "in-dev", "owner": "dev", "app-revalidation": {READER: ["implementation", "tests", "qa", "release"]}})
        changes = [
            change(FEATURE_PATH, page),
            change(REQUIREMENT_PATHS[READER], set_frontmatter(self.read(REQUIREMENT_PATHS[READER]), {"status": "in-progress"})),
            change(CONTRACT_PATH, set_frontmatter(self.read(CONTRACT_PATH), {"status": "agreed"})),
        ]
        return Proposal("qa-fail reader-app", "qa-fail", changes, "Quinn")

    def bug_start(self) -> Proposal:
        page = set_frontmatter(self.read(BUG_1), {"status": "in-fix", "owner": "dev"})
        return Proposal("BUG-001 bug-start", "bug-update", [change(BUG_1, page)], "Devi")

    def bug_fixed(self) -> Proposal:
        page = set_frontmatter(self.read(BUG_1), {"status": "fixed", "owner": "qa"})
        page = set_section(page, "Fix", table("fix", [fix_row(READER, READER_FIX_BUILD)]))
        return Proposal("BUG-001 bug-fixed on build:reader-app#91", "bug-update", [change(BUG_1, page)], "Devi")

    def dev_done_reader_again(self) -> Proposal:
        changes = self.deliver(READER, READER_FIX_BUILD, "ready-for-qa", "qa", pull=33, revalidation={READER: ["qa", "release"]})
        return Proposal("dev-done reader-app on the fix", "dev-done", changes, "Devi")

    def bug_verify(self) -> Proposal:
        page = set_frontmatter(self.read(BUG_1), {"status": "verified", "owner": "release"})
        page = set_section(page, "Verification", table("verification", [verification_row(READER, READER_FIX_BUILD)]))
        return Proposal("BUG-001 bug-verify", "bug-update", [change(BUG_1, page)], "Quinn", refused=("Devi", "separation_required"))

    def qa_pass(self) -> Proposal:
        rows = [
            *table_rows(self.feature_text(), "QA verification"),
            qa_row(READER, [ref_2()], f"`{READER_FIX_BUILD}`", attempt=2),
            qa_row(f"integration:{CATALOG}+{READER}", [ref_3()], f"{CATALOG}=`{CATALOG_BUILD}`; {READER}=`{READER_FIX_BUILD}`", attempt=2),
        ]
        page = with_rows(self.feature_text(), "QA verification", "qa", rows)
        page = with_rows(page, "Release", "release", [pending_release_row(CATALOG, CATALOG_BUILD), pending_release_row(READER, READER_FIX_BUILD)])
        page = set_frontmatter(page, {"status": "ready-for-release", "owner": "release", "app-revalidation": {READER: ["release"]}})
        return Proposal("qa-pass with the AC-2 and AC-3 rows in qa-2", "qa-pass", [change(FEATURE_PATH, page)], "Quinn", refused=("Devi", "separation_required"))

    # -- 15 and 16: the release, its failure and its retry -----------------------------------------------------------------------

    def contract_snapshots(self, *apps: str) -> str:
        text = self.read(CONTRACT_PATH)
        citation = contract_page_citation(*split_page(text))
        return "\n".join(format_snapshot(FEATURE_ID, app, citation, text) for app in apps)

    def release_partial(self) -> Proposal:
        page = with_rows(self.feature_text(), "Release", "release", [
            release_row(CATALOG, CATALOG_BUILD, 1, target=TARGET[CATALOG]),
            release_row(READER, READER_FIX_BUILD, 1, target=TARGET[READER], outcome="failed"),
        ])
        failed = "store: https://play.example/lumen/aborted-91"
        rows = [
            record_row(FEATURE_ID, CATALOG, CATALOG_BUILD, target=TARGET[CATALOG]),
            record_row(FEATURE_ID, READER, READER_FIX_BUILD, target=TARGET[READER], outcome="failed", evidence=failed),
            record_row("BUG-001", READER, READER_FIX_BUILD, target=TARGET[READER], outcome="failed", evidence=failed),
        ]
        record = record_page(1, rows, features=[FEATURE_ID], bugs=["BUG-001"], title="Release of F-001 and BUG-001", day=TODAY, summary="F-001 is delivered to production; the Play Store upload of the reader app fails.", contracts=self.contract_snapshots(CATALOG, READER))
        bug = set_section(self.read(BUG_1), "Release", table("release", [release_row(READER, READER_FIX_BUILD, 1, target=TARGET[READER], outcome="failed")]))
        changes = [change(FEATURE_PATH, page), change(BUG_1, bug), change(f"{RELEASE_DIR}/REL-001.md", record)]
        return Proposal("release-done F-001 BUG-001: catalog-api released, reader-app failed (REL-001)", "release-done", changes, "Remy")

    def release_retry(self) -> Proposal:
        page = with_rows(self.feature_text(), "Release", "release", [
            release_row(CATALOG, CATALOG_BUILD, 1, target=TARGET[CATALOG]),
            release_row(READER, READER_FIX_BUILD, 2, target=TARGET[READER], attempt=2),
        ])
        page = set_frontmatter(page, {"status": "released", "owner": "none"}, remove=["app-revalidation"])
        rows = [
            record_row(FEATURE_ID, READER, READER_FIX_BUILD, target=TARGET[READER], attempt=2),
            record_row("BUG-001", READER, READER_FIX_BUILD, target=TARGET[READER], attempt=2),
        ]
        record = record_page(2, rows, features=[FEATURE_ID], bugs=["BUG-001"], title="Retry of REL-001", day=TODAY, retry_of="REL-001", summary="The reader app is delivered to the Play Store on the second attempt.", contracts=self.contract_snapshots(READER))
        bug = set_frontmatter(self.read(BUG_1), {"status": "released", "owner": "none"})
        bug = set_section(bug, "Release", table("release", [release_row(READER, READER_FIX_BUILD, 2, target=TARGET[READER], attempt=2)]))
        changes = [change(FEATURE_PATH, page), change(BUG_1, bug), change(f"{RELEASE_DIR}/REL-002.md", record)]
        return Proposal("release-done retry: reader-app released, BUG-001 released (REL-002)", "release-done", changes, "Remy")

    # -- 17: a bug in a released feature ------------------------------------------------------------------------------------------

    def ingest_bug_2(self) -> Proposal:
        page = bug_page(2, BUG_2_TITLE, CATALOG_BUILD, apps=(CATALOG,), environment="production")
        return self.intake("2026-10-10-catalog-defect", {f"bugs/{BUG_2.rsplit('/', 1)[1]}": page}, "ingest BUG-002")

    def bug_2_start(self) -> Proposal:
        page = set_frontmatter(self.read(BUG_2), {"status": "in-fix", "owner": "dev"})
        return Proposal("BUG-002 bug-start", "bug-update", [change(BUG_2, page)], "Devi")

    def bug_2_fixed(self) -> Proposal:
        page = set_frontmatter(self.read(BUG_2), {"status": "fixed", "owner": "qa"})
        page = set_section(page, "Fix", table("fix", [fix_row(CATALOG, CATALOG_FIX_BUILD, pull=41)]))
        return Proposal("BUG-002 bug-fixed on build:catalog-api#413", "bug-update", [change(BUG_2, page)], "Devi")

    def bug_2_verified(self) -> Proposal:
        page = set_frontmatter(self.read(BUG_2), {"status": "verified", "owner": "release"})
        page = set_section(page, "Verification", table("verification", [verification_row(CATALOG, CATALOG_FIX_BUILD)]))
        return Proposal("BUG-002 bug-verify", "bug-update", [change(BUG_2, page)], "Quinn")

    def release_bug_2(self) -> Proposal:
        row = release_row(CATALOG, CATALOG_BUILD, 1, target=TARGET[CATALOG])
        page = self.feature_text()
        if row not in page:
            raise AssertionError("The catalog-api Release row of F-001 is not the one REL-001 wrote.")
        page = page.replace(row, release_row(CATALOG, CATALOG_FIX_BUILD, 3, target=TARGET[CATALOG]))
        bug = set_frontmatter(self.read(BUG_2), {"status": "released", "owner": "none"})
        bug = set_section(bug, "Release", table("release", [release_row(CATALOG, CATALOG_FIX_BUILD, 3, target=TARGET[CATALOG])]))
        record = record_page(
            3,
            [record_row("BUG-002", CATALOG, CATALOG_FIX_BUILD, target=TARGET[CATALOG])],
            features=[],
            bugs=["BUG-002"],
            title="Fix of BUG-002",
            day=TODAY,
            summary="BUG-002 is delivered to production.",
            contracts=self.contract_snapshots(CATALOG),
        )
        changes = [change(FEATURE_PATH, page), change(BUG_2, bug), change(f"{RELEASE_DIR}/REL-003.md", record)]
        return Proposal("release-done BUG-002 (REL-003): the catalog-api row of F-001 names it", "release-done", changes, "Remy")

    # -- 18 and 19: the incident, the rollback and the redeploy ----------------------------------------------------------------------

    def ingest_incident(self) -> Proposal:
        return self.intake("2026-10-11-outage-report", {f"incidents/{INCIDENT_PATH.rsplit('/', 1)[1]}": incident_page()}, "ingest INC-001 (cause unknown)")

    def rollback(self) -> Proposal:
        rows = [record_row("BUG-002", CATALOG, CATALOG_FIX_BUILD, target=TARGET[CATALOG], outcome="rolled-back", attempt=None)]
        record = record_page(
            4,
            rows,
            features=[],
            bugs=["BUG-002"],
            title="Rollback of REL-003",
            day=TODAY,
            rollback_of="REL-003",
            summary="REL-003 is rolled back after the reservation errors.",
            rollback="The catalog was rolled back to build 412 after reservations failed for 25 minutes.",
        )
        return Proposal("release-rollback REL-003 (REL-004)", "release-done", [change(f"{RELEASE_DIR}/REL-004.md", record)], "Remy")

    MITIGATION_LINK = "../../intake/processed/2026-10-11-mitigation/note.md"
    POSTMORTEM_LINK = "../../intake/processed/2026-10-12-postmortem/note.md"

    def incident_mitigated(self) -> Proposal:
        timeline = (
            f"- {TODAY} 08:15: Reservations started failing after REL-003.",
            f"- {TODAY} 08:40: REL-003 was rolled back by REL-004.",
            f"- {TODAY}: Mitigation recorded ([update]({self.MITIGATION_LINK}))",
        )
        page = incident_page(status="mitigated", mitigation="REL-003 was rolled back by REL-004 at 08:40.", releases=("REL-003", "REL-004"), timeline=timeline)
        return self.intake("2026-10-11-mitigation", {f"incidents/{INCIDENT_PATH.rsplit('/', 1)[1]}": page}, "ingest INC-001 update: mitigated")

    def redeploy_failed(self) -> Proposal:
        rows = [record_row("BUG-002", CATALOG, CATALOG_FIX_BUILD, target=TARGET[CATALOG], outcome="failed", attempt=None, evidence="deployment: https://ci.example/deploy/aborted-413")]
        record = record_page(5, rows, features=[], bugs=["BUG-002"], title="Redeploy of REL-004", day=TODAY, retry_of="REL-004", summary="The redeploy of build 413 fails.")
        return Proposal("release-redeploy REL-004 fails (REL-005)", "release-done", [change(f"{RELEASE_DIR}/REL-005.md", record)], "Remy")

    def redeploy_released(self) -> Proposal:
        rows = [record_row("BUG-002", CATALOG, CATALOG_FIX_BUILD, target=TARGET[CATALOG], attempt=None)]
        record = record_page(6, rows, features=[], bugs=["BUG-002"], title="Redeploy of REL-005", day=TODAY, retry_of="REL-005", summary="Build 413 is redeployed to production.")
        return Proposal("release-redeploy REL-005 (REL-006)", "release-done", [change(f"{RELEASE_DIR}/REL-006.md", record)], "Remy")

    def incident_resolved(self) -> Proposal:
        follow_up = BUG_3.rsplit("/", 1)[1]
        timeline = (
            f"- {TODAY} 08:15: Reservations started failing after REL-003.",
            f"- {TODAY} 08:40: REL-003 was rolled back by REL-004.",
            f"- {TODAY}: Mitigation recorded ([update]({self.MITIGATION_LINK}))",
            f"- {TODAY}: Cause recorded ([post-mortem]({self.POSTMORTEM_LINK}))",
            f"- {TODAY}: Resolved by the redeploy REL-006 ([post-mortem]({self.POSTMORTEM_LINK}))",
        )
        incident = incident_page(
            status="resolved",
            cause=f"The reservation cache ignored the copy status after REL-003 ([post-mortem]({self.POSTMORTEM_LINK})).",
            mitigation="REL-003 was rolled back by REL-004 at 08:40.",
            resolution="Build 413 was redeployed by REL-006 and reservations succeed again.",
            follow_ups=f"- [BUG-003](../bugs/{follow_up}): the cache defect behind the outage",
            follow_up_ids=("BUG-003",),
            releases=("REL-003", "REL-004", "REL-005", "REL-006"),
            timeline=timeline,
        )
        bug = bug_page(3, BUG_3_TITLE, "INC-001", apps=(CATALOG,), feature="none", environment="production", severity="medium", blocking=False)
        pages = {f"incidents/{INCIDENT_PATH.rsplit('/', 1)[1]}": incident, f"bugs/{follow_up}": bug}
        return self.intake("2026-10-12-postmortem", pages, "ingest INC-001 update: cause filled, resolved, follow-up BUG-003")


# The steps in order: (number, the proposals it takes). The contract numbers them 1 to 19.
SEQUENCE: list[tuple[int, list[str]]] = [
    (1, ["ingest_feature", "po_specify"]),
    (2, ["po_handoff"]),
    (3, ["tech_design_first"]),
    (4, ["design_clarify", "tech_design_again"]),
    (5, ["design_handoff"]),
    (6, ["dev_done_catalog"]),
    (7, ["qa_verify_catalog"]),
    (8, ["ask_po", "po_clarify", "qa_verify_replace"]),
    (9, ["dev_done_reader"]),
    (10, ["qa_verify_reader_fail"]),
    (11, ["qa_fail_reader"]),
    (12, ["bug_start", "bug_fixed", "dev_done_reader_again"]),
    (13, ["bug_verify"]),
    (14, ["qa_pass"]),
    (15, ["release_partial"]),
    (16, ["release_retry"]),
    (17, ["ingest_bug_2", "bug_2_start", "bug_2_fixed", "bug_2_verified", "release_bug_2"]),
    (18, ["ingest_incident", "rollback", "incident_mitigated"]),
    (19, ["redeploy_failed", "redeploy_released", "incident_resolved"]),
]

# The human approvals of the whole case, in order: (person, action). An ungated write (ingest, design-clarify, ask, po-clarify) has none.
APPROVALS: list[tuple[str, str]] = [
    ("Pat", "po-specify"),
    ("Pat", "po-handoff"),
    ("Theo", "tech-design-done"),
    ("Theo", "tech-design-done"),
    ("Dana", "design-handoff"),
    ("Devi", "dev-done"),
    ("Quinn", "qa-verify"),
    ("Quinn", "qa-verify"),
    ("Devi", "dev-done"),
    ("Quinn", "qa-verify"),
    ("Quinn", "qa-fail"),
    ("Devi", "bug-start"),
    ("Devi", "bug-fixed"),
    ("Devi", "dev-done"),
    ("Quinn", "bug-verify"),
    ("Quinn", "qa-pass"),
    ("Remy", "release-done"),
    ("Remy", "release-done"),
    ("Devi", "bug-start"),
    ("Devi", "bug-fixed"),
    ("Quinn", "bug-verify"),
    ("Remy", "release-done"),
    ("Remy", "release-rollback"),
    ("Remy", "release-redeploy"),
    ("Remy", "release-redeploy"),
]
# The seven confirmations of the happy path (CONTRACTS 10.1) are these actions; the apps are delivered separately, so dev-done counts twice.
HAPPY_PATH = ("po-specify", "po-handoff", "tech-design-done", "design-handoff", "dev-done", "dev-done", "qa-pass", "release-done")


# -- what each step leaves --------------------------------------------------------------------------------------------------------

DASH = "—"


def stages(catalog: str | None = None, reader: str | None = None) -> dict[str, str]:
    return {app: stage for app, stage in ((CATALOG, catalog), (READER, reader)) if stage is not None}


def ops(target: str, released: str, latest: str, outcome: str, bugs: str = DASH, incidents: str = DASH) -> tuple[str, ...]:
    return (target, released, latest, outcome, bugs, incidents)


@dataclass
class Expected:
    """The state after one step. `delivery` maps an app to its artifact; `qa` lists (row key, attempt, result); `release` maps an
    app to (target, version, attempt, outcome, record); `history` lists the actions of the Evidence history entries."""

    status: tuple[str, str]
    tracks: str = DASH
    stages: dict[str, str] = field(default_factory=dict)
    delivery: dict[str, str] = field(default_factory=dict)
    qa: list[tuple[str, int, str]] = field(default_factory=list)
    release: dict[str, tuple[str, str, int, str, str]] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    revalidation: dict[str, list[str]] = field(default_factory=dict)
    contract: str | None = None
    bugs: dict[str, tuple[str, str]] = field(default_factory=dict)
    feature_bugs: str = DASH
    records: dict[str, str] = field(default_factory=dict)
    incidents: dict[str, str] = field(default_factory=dict)
    operations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    next_action: str = "po-specify"


UI_DONE = "ui: done; technical: done"
ALL = ["implementation", "tests", "qa", "release"]
CAT_ROW = (CATALOG, 1, "pass")


def _qa(*rows: tuple[str, int, str]) -> list[tuple[str, int, str]]:
    return list(rows)


INTEGRATION = f"integration:{CATALOG}+{READER}"
_PENDING = {CATALOG: (DASH, CATALOG_BUILD, 1, "pending", DASH), READER: (DASH, READER_FIX_BUILD, 1, "pending", DASH)}

EXPECTED: dict[int, Expected] = {
    1: Expected(("specified", "po"), next_action="po-handoff"),
    2: Expected(("ready-for-design", "designer"), next_action="design-start"),
    3: Expected(("in-design", "designer"), tracks="ui: pending; technical: done", contract="agreed", next_action="design-ui-done"),
    4: Expected(("in-design", "designer"), tracks="ui: pending; technical: done", contract="agreed", next_action="design-handoff"),
    5: Expected(("ready-for-dev", "dev"), tracks=UI_DONE, contract="agreed", next_action="dev-start"),
    6: Expected(
        ("in-dev", "dev"), UI_DONE, stages("ready-for-qa", "in-dev"), {CATALOG: CATALOG_BUILD}, contract="agreed", next_action="qa-verify"
    ),
    7: Expected(
        ("in-dev", "dev"), UI_DONE, stages("in-qa", "in-dev"), {CATALOG: CATALOG_BUILD}, _qa(CAT_ROW), contract="agreed", next_action="dev-done"
    ),
    8: Expected(
        ("in-dev", "dev"), UI_DONE, stages("in-qa", "in-dev"), {CATALOG: CATALOG_BUILD}, _qa(CAT_ROW), contract="agreed", next_action="dev-done"
    ),
    9: Expected(
        ("ready-for-qa", "qa"),
        UI_DONE,
        stages("in-qa", "ready-for-qa"),
        {CATALOG: CATALOG_BUILD, READER: READER_BUILD},
        _qa(CAT_ROW),
        contract="implemented",
        next_action="qa-verify",
    ),
    10: Expected(
        ("in-qa", "qa"),
        UI_DONE,
        stages("in-qa", "in-qa"),
        {CATALOG: CATALOG_BUILD, READER: READER_BUILD},
        _qa(CAT_ROW, (READER, 1, "fail")),
        contract="implemented",
        bugs={"BUG-001": ("open", "dev")},
        feature_bugs="BUG-001",
        operations={READER: ops("play-store", DASH, DASH, DASH, bugs="BUG-001")},
        next_action="qa-fail",
    ),
    11: Expected(
        ("in-dev", "dev"),
        UI_DONE,
        stages("in-qa", "in-dev"),
        {CATALOG: CATALOG_BUILD},
        _qa(CAT_ROW),
        history=["qa-fail"],
        revalidation={READER: ALL},
        contract="agreed",
        bugs={"BUG-001": ("open", "dev")},
        feature_bugs="BUG-001",
        operations={READER: ops("play-store", DASH, DASH, DASH, bugs="BUG-001")},
        next_action="dev-done",
    ),
    12: Expected(
        ("ready-for-qa", "qa"),
        UI_DONE,
        stages("in-qa", "ready-for-qa"),
        {CATALOG: CATALOG_BUILD, READER: READER_FIX_BUILD},
        _qa(CAT_ROW),
        history=["qa-fail"],
        revalidation={READER: ["qa", "release"]},
        contract="implemented",
        bugs={"BUG-001": ("fixed", "qa")},
        feature_bugs="BUG-001",
        operations={READER: ops("play-store", DASH, DASH, DASH, bugs="BUG-001")},
        next_action="qa-pass",
    ),
    13: Expected(
        ("ready-for-qa", "qa"),
        UI_DONE,
        stages("in-qa", "ready-for-qa"),
        {CATALOG: CATALOG_BUILD, READER: READER_FIX_BUILD},
        _qa(CAT_ROW),
        history=["qa-fail"],
        revalidation={READER: ["qa", "release"]},
        contract="implemented",
        bugs={"BUG-001": ("verified", "release")},
        feature_bugs="BUG-001",
        operations={READER: ops("play-store", DASH, DASH, DASH, bugs="BUG-001")},
        next_action="qa-pass",
    ),
    14: Expected(
        ("ready-for-release", "release"),
        UI_DONE,
        stages("ready-for-release", "ready-for-release"),
        {CATALOG: CATALOG_BUILD, READER: READER_FIX_BUILD},
        _qa(CAT_ROW, (READER, 2, "pass"), (INTEGRATION, 2, "pass")),
        _PENDING,
        history=["qa-fail"],
        revalidation={READER: ["release"]},
        contract="implemented",
        bugs={"BUG-001": ("verified", "release")},
        feature_bugs="BUG-001",
        operations={READER: ops("play-store", DASH, DASH, DASH, bugs="BUG-001")},
        next_action="release-done",
    ),
    15: Expected(
        ("ready-for-release", "release"),
        UI_DONE,
        stages("released", "ready-for-release"),
        {CATALOG: CATALOG_BUILD, READER: READER_FIX_BUILD},
        _qa(CAT_ROW, (READER, 2, "pass"), (INTEGRATION, 2, "pass")),
        {
            CATALOG: ("production", CATALOG_BUILD, 1, "released", "REL-001"),
            READER: ("play-store", READER_FIX_BUILD, 1, "failed", "REL-001"),
        },
        history=["qa-fail"],
        revalidation={READER: ["release"]},
        contract="implemented",
        bugs={"BUG-001": ("verified", "release")},
        feature_bugs="BUG-001",
        records={"REL-001": "partial"},
        operations={
            CATALOG: ops("production", "F-001", "REL-001", "released"),
            READER: ops("play-store", DASH, "REL-001", "failed", bugs="BUG-001"),
        },
        next_action="release-done",
    ),
    16: Expected(
        ("released", "none"),
        UI_DONE,
        stages("released", "released"),
        {CATALOG: CATALOG_BUILD, READER: READER_FIX_BUILD},
        _qa(CAT_ROW, (READER, 2, "pass"), (INTEGRATION, 2, "pass")),
        {
            CATALOG: ("production", CATALOG_BUILD, 1, "released", "REL-001"),
            READER: ("play-store", READER_FIX_BUILD, 2, "released", "REL-002"),
        },
        history=["qa-fail"],
        contract="implemented",
        bugs={"BUG-001": ("released", "none")},
        records={"REL-001": "partial", "REL-002": "released"},
        operations={
            CATALOG: ops("production", "F-001", "REL-001", "released"),
            READER: ops("play-store", "F-001", "REL-002", "released"),
        },
        next_action="reopen-dev",
    ),
    17: Expected(
        ("released", "none"),
        UI_DONE,
        stages("released", "released"),
        {CATALOG: CATALOG_BUILD, READER: READER_FIX_BUILD},
        _qa(CAT_ROW, (READER, 2, "pass"), (INTEGRATION, 2, "pass")),
        {
            CATALOG: ("production", CATALOG_FIX_BUILD, 1, "released", "REL-003"),
            READER: ("play-store", READER_FIX_BUILD, 2, "released", "REL-002"),
        },
        history=["qa-fail"],
        contract="implemented",
        bugs={"BUG-001": ("released", "none"), "BUG-002": ("released", "none")},
        records={"REL-001": "partial", "REL-002": "released", "REL-003": "released"},
        operations={
            CATALOG: ops("production", "F-001", "REL-003", "released"),
            READER: ops("play-store", "F-001", "REL-002", "released"),
        },
        next_action="reopen-dev",
    ),
    18: Expected(
        ("released", "none"),
        UI_DONE,
        stages("released", "released"),
        {CATALOG: CATALOG_BUILD, READER: READER_FIX_BUILD},
        _qa(CAT_ROW, (READER, 2, "pass"), (INTEGRATION, 2, "pass")),
        {
            CATALOG: ("production", CATALOG_FIX_BUILD, 1, "released", "REL-003"),
            READER: ("play-store", READER_FIX_BUILD, 2, "released", "REL-002"),
        },
        history=["qa-fail"],
        contract="implemented",
        bugs={"BUG-001": ("released", "none"), "BUG-002": ("released", "none")},
        records={"REL-001": "partial", "REL-002": "released", "REL-003": "released", "REL-004": "rolled-back"},
        incidents={"INC-001": "mitigated"},
        operations={
            CATALOG: ops("production", "F-001", "REL-004", "rolled-back", incidents="INC-001"),
            READER: ops("play-store", "F-001", "REL-002", "released"),
        },
        next_action="reopen-dev",
    ),
    19: Expected(
        ("released", "none"),
        UI_DONE,
        stages("released", "released"),
        {CATALOG: CATALOG_BUILD, READER: READER_FIX_BUILD},
        _qa(CAT_ROW, (READER, 2, "pass"), (INTEGRATION, 2, "pass")),
        {
            CATALOG: ("production", CATALOG_FIX_BUILD, 1, "released", "REL-003"),
            READER: ("play-store", READER_FIX_BUILD, 2, "released", "REL-002"),
        },
        history=["qa-fail"],
        contract="implemented",
        bugs={"BUG-001": ("released", "none"), "BUG-002": ("released", "none"), "BUG-003": ("open", "dev")},
        records={"REL-001": "partial", "REL-002": "released", "REL-003": "released", "REL-004": "rolled-back", "REL-005": "failed", "REL-006": "released"},
        incidents={"INC-001": "resolved"},
        operations={
            CATALOG: ops("production", "F-001", "REL-006", "released", bugs="BUG-003"),
            READER: ops("play-store", "F-001", "REL-002", "released"),
        },
        next_action="reopen-dev",
    ),
}
