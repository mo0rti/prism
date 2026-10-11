#!/usr/bin/env python3
"""Build a deterministic, synthetic Prism wiki visualization demo.

The command writes into a newly-created destination.  It is deliberately
self-contained so the demo can be regenerated without changing a generated
project or the repository's real workspaces.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from prism_cli import __version__  # noqa: E402
from prism_cli.wiki_index import build_index  # noqa: E402
from prism_cli.app_model import apps_from_platforms  # noqa: E402
from prism_cli.workspace import write_workspace_manifest  # noqa: E402
from prism_cli.wiki_bugs import read_bug_pages  # noqa: E402
from prism_cli.wiki_incidents import read_incident_pages  # noqa: E402
from prism_cli.wiki_model import DesignTracks, app_stages_text, contract_citation, criterion_revision, read_feature_pages  # noqa: E402
from prism_cli.wiki_model import resolve_delivery_targets  # noqa: E402
from prism_cli.wiki_operations import (  # noqa: E402
    BUG_TABLE_COLUMNS,
    BUGS_HEADING,
    OPERATIONS_HEADING,
    OPERATIONS_TABLE_COLUMNS,
    bug_board_row,
    design_tracks_text,
    format_bug_row,
    format_operation_row,
    ids_text,
    open_bugs_of_feature,
    operation_row,
    table_text,
)
from prism_cli.wiki_releases import format_snapshot, read_release_records  # noqa: E402
from prism_cli.workspace import inspect_workspace  # noqa: E402
from prism_cli.wiki_transitions import ACTION_SPECS  # noqa: E402


PRODUCT_NAME = "TreasuryFlow"
PROJECT_SLUG = "treasury-flow"
PACKAGE_IDENTIFIER = "com.mortitech.treasuryflow"
DESCRIPTION = "A finance operations platform for payout approvals, settlements, and transaction oversight"
PLATFORMS = ["backend", "mobile-android", "mobile-ios"]  # the generated platform IDs, which are also the demo's app IDs
TEMPLATE_SOURCE = "synthetic-local-demo"
DEMO_TODAY = date.today()

WIKI_TEMPLATE_ROOT = REPO_ROOT / "template" / "knowledge" / "wiki"
INTAKE_TEMPLATE_ROOT = REPO_ROOT / "template" / "knowledge" / "intake"
# The processed intake item that the seeded features list in `sources`; the features' `sources` entries are workspace paths.
PROCESSED_ITEM = "2026-09-20-payout-workflow-brief"
PROCESSED_BRIEF = f"knowledge/intake/processed/{PROCESSED_ITEM}"

FEATURES: tuple[dict[str, Any], ...] = (
    {
        "id": "F-001",
        "slug": "create-payout-request",
        "title": "Create payout request",
        "status": "raw",
        "owner": "po",
        "advisory": "not-needed",
        "summary": "Operators create a payout request with a recipient, amount, and business reason so a manager can review it.",
        "story": "As an operator, I want to submit a payout request, so that the right manager can decide whether it should proceed.",
        "criteria": [
            "A request records its recipient, amount, currency, and reason.",
            "An operator can see whether the request is awaiting review.",
        ],
        "question": None,
        "related": "F-002",
    },
    {
        "id": "F-002",
        "slug": "approve-or-reject-payout",
        "title": "Approve or reject payout",
        "status": "in-dev",
        "owner": "dev",
        "advisory": "pending",
        "summary": "Managers review the request context and approve or reject a payout before settlement begins.",
        "story": "As a manager, I want to approve or reject a payout, so that funds move only after an accountable decision.",
        "criteria": [
            "A manager can approve or reject a pending request with a recorded decision.",
            "The request cannot enter settlement without an approval decision.",
        ],
        "question": {
            "number": "1",
            "text": "What is the fallback approval threshold when a manager is unavailable?",
            "owner": "po",
            "status": "open",
        },
        "related": "F-003",
    },
    {
        "id": "F-003",
        "slug": "settle-payout-and-review-history",
        "title": "Settle payout and review history",
        "status": "released",
        "owner": "none",
        "advisory": "done",
        "summary": "Finance admins settle an approved payout and can review the resulting transaction history.",
        "story": "As a finance admin, I want to settle an approved payout and review its history, so that every outcome is easy to inspect.",
        "criteria": [
            "An approved payout can be marked settled or failed with an outcome.",
            "The transaction history shows the request and settlement outcome together.",
        ],
        "question": None,
        "related": "F-001",
    },
    {
        "id": "F-004",
        "slug": "notify-managers-of-pending-approvals",
        "title": "Notify managers of pending approvals",
        "status": "specified",
        "owner": "po",
        "advisory": "not-needed",
        "summary": "Managers are told when a payout request waits for their decision so that no request stalls.",
        "story": "As a manager, I want a notice when a request waits for me, so that I can decide before the payout window closes.",
        "criteria": [
            "A manager receives a notice when a request is assigned to them.",
            "A request that waits for more than a day is shown first in the list of the manager.",
        ],
        "question": None,
        "related": "F-002",
    },
    {
        "id": "F-005",
        "slug": "reverse-a-settled-payout",
        "title": "Reverse a settled payout",
        "status": "ready-for-design",
        "owner": "designer",
        "advisory": "done",
        "summary": "Finance admins reverse a payout that settled by mistake and keep the reversal beside the original outcome.",
        "story": "As a finance admin, I want to reverse a settled payout, so that a mistake is corrected with a visible record.",
        "criteria": [
            "A settled payout can be reversed with a reason.",
            "The history shows the reversal beside the original settlement.",
        ],
        "question": None,
        "related": "F-003",
    },
    {
        "id": "F-006",
        "slug": "export-the-payout-ledger",
        "title": "Export the payout ledger",
        "status": "in-design",
        "owner": "designer",
        "advisory": "done",
        "summary": "Finance admins export the payout ledger for a period so that auditors can review it outside the product.",
        "story": "As a finance admin, I want to export the ledger of a period, so that auditors can review it.",
        "criteria": [
            "A ledger export lists every payout of the chosen period with its outcome.",
            "The export is available to finance admins only.",
        ],
        "question": None,
        "related": "F-003",
    },
    {
        "id": "F-007",
        "slug": "flag-unusual-payout-amounts",
        "title": "Flag unusual payout amounts",
        "status": "ready-for-dev",
        "owner": "dev",
        "advisory": "done",
        "summary": "A request whose amount is far above the usual range is flagged for a second look before approval.",
        "story": "As a manager, I want unusual amounts flagged, so that I look twice before I approve them.",
        "criteria": [
            "A request above the configured range is marked as unusual.",
            "The manager sees the usual range beside the flagged amount.",
        ],
        "question": None,
        "related": "F-002",
    },
    {
        "id": "F-008",
        "slug": "schedule-recurring-payouts",
        "title": "Schedule recurring payouts",
        "status": "ready-for-qa",
        "owner": "qa",
        "advisory": "done",
        "summary": "Operators schedule a payout that repeats so that a regular recipient is paid without a new request each time.",
        "story": "As an operator, I want to schedule a repeating payout, so that regular recipients are paid on time.",
        "criteria": [
            "A payout can be scheduled to repeat weekly or monthly.",
            "Each repeat goes through the same approval as a single payout.",
        ],
        "question": None,
        "related": "F-001",
    },
    {
        "id": "F-009",
        "slug": "attach-receipts-to-a-payout-request",
        "title": "Attach receipts to a payout request",
        "status": "in-qa",
        "owner": "qa",
        "advisory": "done",
        "summary": "Operators attach a receipt to a payout request so that the manager sees what the payment is for.",
        "story": "As an operator, I want to attach a receipt, so that the manager can see what the payout is for.",
        "criteria": [
            "A request accepts one receipt in PDF or image form.",
            "The manager opens the receipt from the request.",
        ],
        "question": None,
        "related": "F-001",
    },
    {
        "id": "F-010",
        "slug": "reconcile-settlements-with-the-bank-statement",
        "title": "Reconcile settlements with the bank statement",
        "status": "ready-for-release",
        "owner": "release",
        "advisory": "done",
        "summary": "Finance admins match each settlement with a line of the bank statement and see the ones that do not match.",
        "story": "As a finance admin, I want settlements matched with the statement, so that differences are found early.",
        "criteria": [
            "Each settlement is matched with a statement line by amount and date.",
            "A settlement without a match is listed for review.",
        ],
        "question": None,
        "related": "F-003",
    },
)


def _answers() -> dict[str, Any]:
    return {
        "project_name": PRODUCT_NAME,
        "project_slug": PROJECT_SLUG,
        "package_identifier": PACKAGE_IDENTIFIER,
        "description": DESCRIPTION,
    }


def _parse_today(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--today must use YYYY-MM-DD") from exc


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_page(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    rendered = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    _write_text(path, f"---\n{rendered}\n---\n\n{body}")


def _copy_template_tree(source_root: Path, destination_root: Path) -> None:
    for source in sorted(source_root.rglob("*")):
        if not source.is_file():
            continue
        if source.suffix != ".md" and source.name != ".gitkeep":
            continue
        destination = destination_root / source.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _write_synthetic_workspace_files(destination: Path, stage: str, today: date) -> None:
    _write_text(
        destination / "DEMO.md",
        f"""# TreasuryFlow synthetic local demo

This `{stage}` fixture was generated locally on {today.isoformat()} for Prism wiki visualization QA.
It is synthetic documentation for the payout request, approval, settlement, and history story.
It contains no production data, observed project history, deployment evidence, compliance claim,
or recorded human review. The fixture is safe to delete and regenerate into another new folder.
""",
    )
    _write_text(
        destination / "README.md",
        f"""# {PRODUCT_NAME}

Synthetic local visualization fixture for the Prism wiki graph and workflow dashboard.
The source of truth is `knowledge/wiki`; this folder does not contain an application build.
""",
    )
    _write_text(
        destination / "AGENTS.md",
        """# Local demo guidance

This generated folder is a synthetic, read-only visualization fixture. Do not treat it as a
production project or infer deployment, compliance, or observed-history evidence from it.
""",
    )
    _write_text(
        destination / "CLAUDE.md",
        """# Local demo guidance

Inspect `knowledge/wiki` and `knowledge/intake` as synthetic source material for dashboard QA.
""",
    )
    _write_text(destination / "docs" / "README.md", "# Demo documentation\n\nThis directory contains synthetic local demo context.")
    for relative in (".agents/skills", ".claude/commands", ".cursor/rules"):
        (destination / relative).mkdir(parents=True, exist_ok=True)
    template_root = Path(__file__).resolve().parents[1] / "template"
    for command in sorted({spec.command for spec in ACTION_SPECS if spec.enabled and spec.subject == "feature"}):
        for relative in (f".agents/skills/{command}/SKILL.md", f".claude/commands/{command}.md"):
            source = template_root / f"{relative}.jinja"
            # Lifecycle instructions have no project substitutions; capability
            # markers make the shipped demo's preview/copy path inspectable.
            _write_text(destination / relative, source.read_text(encoding="utf-8"))
    for platform in PLATFORMS:
        _write_text(
            destination / platform / "DEMO.md",
            f"# {platform}\n\nSynthetic app surface for local dashboard inspection; no implementation is included.",
        )
    for workflow in ("backend", "mobile-android", "mobile-ios"):
        _write_text(
            destination / ".github" / "workflows" / f"{workflow}.yml",
            f"# Synthetic local demo workflow placeholder for {workflow}.\n",
        )


def _write_workspace_contract(destination: Path, today: date) -> None:
    answers = _answers()
    answers_with_provenance = {
        "_src_path": TEMPLATE_SOURCE,
        "_commit": TEMPLATE_SOURCE,
        **answers,
    }
    _write_text(destination / ".copier-answers.yml", yaml.safe_dump(answers_with_provenance, sort_keys=False))
    write_workspace_manifest(
        destination,
        answers,
        prism_cli_version=__version__,
        template_source=TEMPLATE_SOURCE,
        template_version=TEMPLATE_SOURCE,
        template_commit=TEMPLATE_SOURCE,
        generated_at=f"{today.isoformat()}T00:00:00Z",
        apps=apps_from_platforms(list(PLATFORMS)),
    )
    manifest_path = destination / "prism.workspace.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    manifest["app_maturity"] = {
        "backend": {"level": "baseline", "caveat": "Synthetic local fixture; no application build claim."},
        "mobile-android": {"level": "baseline", "caveat": "Synthetic local fixture; no application build claim."},
        "mobile-ios": {"level": "experimental", "caveat": "Synthetic local fixture; no application build claim."},
    }
    manifest["paths"] = {
        "wiki_root": "knowledge/wiki",
        "intake_root": "knowledge/intake",
        "advisory_board": "knowledge/wiki/advisory/BOARD.md",
    }
    manifest["expected_surfaces"] = {
        "ai": ["AGENTS.md", "CLAUDE.md", ".agents/skills", ".claude/commands", ".cursor/rules"],
        "docs": ["README.md", "docs/"],
        "workflows": [
            ".github/workflows/backend.yml",
            ".github/workflows/mobile-android.yml",
            ".github/workflows/mobile-ios.yml",
        ],
    }
    _write_text(manifest_path, yaml.safe_dump(manifest, sort_keys=False))


def _write_wiki_skeleton(destination: Path, stage: str, today: date) -> None:
    wiki_root = destination / "knowledge" / "wiki"
    intake_root = destination / "knowledge" / "intake"
    _copy_template_tree(WIKI_TEMPLATE_ROOT, wiki_root)
    _copy_template_tree(INTAKE_TEMPLATE_ROOT, intake_root)
    for path in (
        intake_root / "pending",
        intake_root / "processed",
        intake_root / "quarantined",
    ):
        path.mkdir(parents=True, exist_ok=True)
        _write_text(path / ".gitkeep", "")

    if stage != "fresh":
        _write_text(
            wiki_root / "advisory" / "BOARD.md",
            """# Advisory Board

Status: initialized for this synthetic local dashboard fixture.

The board area is present so Guide can show initialized state. This fixture does not record real
board membership, review, domain advice, or a production decision.
""",
        )
        _write_text(
            wiki_root / "advisory" / "PROJECT_FOUNDATION.md",
            f"""# Project Foundation

Synthetic local dashboard fixture.

## Project identity
- Name: {PRODUCT_NAME}
- Description: {DESCRIPTION}
- Apps: {', '.join(PLATFORMS)}
- Local development services: Postgres through Docker Compose
- Important correction or note: Synthetic local documentation; no application or compliance claim.

## Setup interview

This fixture does not contain an observed interview. The product story is seeded from the local
TreasuryFlow demo reference so the visualization can show relationships and workflow states.

## Risk summary
- Core trust surface: approval decision and settlement outcome visibility.
- Primary failure modes: an unauthorized approval or an incomplete settlement trail.
- Business impact: operators and managers need a clear accountable workflow.
- Vulnerable groups: none asserted by this synthetic fixture.
- Expertise gaps: domain validation is intentionally still an open question.

## Why this board

The board area is included to make the review state visible in a local dashboard fixture.

## Seed artifacts from setup
- [BOARD.md](BOARD.md)
- [Create payout request](../features/F-001-create-payout-request.md)
""",
        )
    _write_text(
        wiki_root / "log.md",
        f"""# Wiki change log

## {today.isoformat()} seed-demo | {stage} stage
- paths: knowledge/wiki
- evidence: none
- by: scripts/build-wiki-demo.py
Synthetic fixture generation for dashboard capture, not observed project history or a real review event.
""",
    )


def _write_processed_item(destination: Path) -> None:
    item_root = destination / "knowledge" / "intake" / "processed" / PROCESSED_ITEM
    _write_text(
        item_root / "brief.md",
        """# Synthetic payout workflow brief

Operators request payouts, managers approve or reject them, and finance admins settle them and review
the history. This note is synthetic source material for dashboard QA; it records no real interview.
""",
    )
    pages = "\n".join(
        f"- knowledge/wiki/features/{feature['id']}-{feature['slug']}.md ({feature['id']})" for feature in FEATURES
    )
    _write_text(item_root / "MANIFEST.md", f"# Processed intake\n\n{pages}")


def _write_intake_item(destination: Path, name: str, *, quarantined: bool) -> None:
    queue = "quarantined" if quarantined else "pending"
    item_root = destination / "knowledge" / "intake" / queue / name
    if quarantined:
        _write_text(
            item_root / "CONFLICT.md",
            """---
status: resolved
---

# Conflict: synthetic quarantine record

## Existing claim
- **Claim:** The existing page says payouts settle once per day.
- **Scope:** Synthetic dashboard QA data; no real feature.
- **Evidence:** [F-001](../../../wiki/features/F-001-example.md)

## Incoming claim
- **Claim:** The quarantined brief says payouts settle twice per day.
- **Scope:** Synthetic dashboard QA data; no real feature.
- **Evidence:** [brief.md](brief.md)

## Resolution
This item is visible in quarantine for dashboard QA. It does not represent an observed conflict,
human resolution, or accepted product decision.
""",
        )
    else:
        _write_text(
            item_root / "brief.md",
            """# Synthetic pending intake brief

Operators need a way to request a refund after a settled payout is reversed. This note remains
pending so the dashboard can show intake visibility without claiming that an intake command ran.
""",
        )


UI_PLATFORMS = ["mobile-android", "mobile-ios"]  # the demo apps that have a UI

CONTRACT_BODY = """## Endpoints
- `POST /payout-requests`: create or submit a request.
- `POST /payout-requests/{id}/decision`: record an approval or rejection.

## Data models
The request carries an ID, amount, currency, actor, status, and outcome metadata.

## Authentication requirements
Require the role appropriate to the operation: operator, manager, or finance admin.

## Notes
This is a synthetic contract summary for graph relationships; it is not an implementation promise.
"""


STAGES = ("raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "ready-for-qa", "in-qa", "ready-for-release", "released")
# Where each demo app is delivered: the default target of its stack.
TARGETS = {"backend": "production", "mobile-android": "play-store", "mobile-ios": "app-store"}
RELEASED_FEATURE = "F-003"


def _rank(feature: dict[str, Any]) -> int:
    return STAGES.index(feature["status"])


def _at_least(feature: dict[str, Any], status: str) -> bool:
    return _rank(feature) >= STAGES.index(status)


def _has_designed(feature: dict[str, Any]) -> bool:
    """A feature from `ready-for-dev` on carries both settled tracks, the design pages of its UI apps and a technical design page."""

    return _at_least(feature, "ready-for-dev")


def _feature_frontmatter(feature: dict[str, Any], today: date) -> dict[str, Any]:
    frontmatter = {
        "id": feature["id"],
        "title": feature["title"],
        "status": feature["status"],
        "owner": feature["owner"],
        "apps": list(PLATFORMS),
        "sources": [PROCESSED_BRIEF],
        "advisory-review": feature["advisory"],
        "criteria-high-water": len(feature["criteria"]),
    }
    if _has_designed(feature):
        frontmatter.update(DesignTracks("done", "done").frontmatter())
    elif feature["status"] == "in-design":
        # The design pages exist; the technical design is still being written.
        frontmatter.update(DesignTracks("done", "pending").frontmatter())
    return frontmatter


def _evidence_sections(feature: dict[str, Any]) -> str:
    """The evidence tables of a feature, by how far it has come.

    Empty until `ready-for-qa`; then a delivery row for each app, a passing QA row for each app from `in-qa`, a pending Release row
    for each app at `ready-for-release`, and a released Release row that names the release record when the feature is `released`.
    """

    delivery: list[str] = []
    qa: list[str] = []
    release: list[str] = []
    references = ", ".join(
        f"AC-{number}@{criterion_revision(feature['id'], number, PLATFORMS, False, '', text)}"
        for number, text in enumerate(feature["criteria"], start=1)
    )
    for platform in PLATFORMS:
        artifact = f"build:{platform}#1"
        if _at_least(feature, "ready-for-qa"):
            delivery.append(
                f"| {platform} | `{artifact}` | {contract_citation(feature['id'], 1, CONTRACT_BODY)} | Synthetic local demo {platform} surface for {feature['id']} (no production implementation claim) "
                f"| Synthetic local graph fixture checks for {platform} (no production test claim) | attested |"
            )
        if _at_least(feature, "in-qa"):
            qa.append(
                f"| {platform} | {references} | manual | `{artifact}` | ci | qa-1 | pass "
                f"| Synthetic local demo check of {platform} (no production test claim) | attested |"
            )
        if feature["status"] == "ready-for-release":
            release.append(f"| {platform} | — | `{artifact}` | release-1 | pending | — | — |")
        if feature["status"] == "released":
            release.append(
                f"| {platform} | {TARGETS[platform]} | `{artifact}` | release-1 | released | [REL-001](../releases/REL-001.md) | attested |"
            )
    rows = lambda items: "".join(f"{item}\n" for item in items)  # noqa: E731
    return (
        "\n## Delivery evidence\n| App | Artifact | Contract | Implementation | Tests | Basis |\n|---|---|---|---|---|---|\n" + rows(delivery)
        + "\n## QA verification\n| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |\n|---|---|---|---|---|---|---|---|---|\n" + rows(qa)
        + "\n## Release\n| App | Target | Version | Attempt | Outcome | Record | Basis |\n|---|---|---|---|---|---|---|\n" + rows(release)
        + "\n## Evidence history\n"
    )


def _write_feature_pages(destination: Path, today: date) -> None:
    features_root = destination / "knowledge" / "wiki" / "features"
    for feature in FEATURES:
        criteria = "\n".join(
            f"- [ ] AC-{number} [{', '.join(PLATFORMS)}] {criterion}" for number, criterion in enumerate(feature["criteria"], start=1)
        )
        question = ""
        if feature["question"]:
            item = feature["question"]
            question = (
                "\n## Open questions\n\n"
                "| # | Question | Owner | Status |\n"
                "|---|----------|-------|--------|\n"
                f"| {item['number']} | {item['text']} | {item['owner']} | {item['status']} |\n"
            )
        body = f"""## Summary
{feature['summary']}

## User story
{feature['story']}

## Acceptance criteria
{criteria}
{question}
## App scope
- **backend**: Implement the payout state transition and its audit fields.
- **mobile-android**: Show the request state and accountable decision.
- **mobile-ios**: Show the request state and accountable decision.

## Design
[Design handoff](../design/{feature['id']}-{feature['slug']}.md)

## Related features
- [{feature['related']}](F-{feature['related'][2:]}-{next(item['slug'] for item in FEATURES if item['id'] == feature['related'])}.md) - Supports the adjacent finance workflow step.

## API surface
[API contract](../api-contracts/{feature['id']}-{feature['slug']}.md)

## Board review summary
Synthetic review state is visible in the linked advisory page.
"""
        if feature["status"] != "raw":
            body += _evidence_sections(feature)
        _write_page(features_root / f"{feature['id']}-{feature['slug']}.md", _feature_frontmatter(feature, today), body)


def _write_linked_context(destination: Path, today: date) -> None:
    wiki_root = destination / "knowledge" / "wiki"
    for feature in FEATURES:
        feature_id = feature["id"]
        slug = feature["slug"]
        status = "implemented" if _at_least(feature, "ready-for-qa") else "agreed"
        for platform in PLATFORMS:
            requirement_status = "done" if _at_least(feature, "ready-for-qa") else "in-progress" if feature["status"] == "in-dev" else "pending"
            _write_page(
                wiki_root / "app-requirements" / f"{feature_id}-{platform}.md",
                {"feature-id": feature_id, "app": platform, "status": requirement_status},
                f"""## What to build
Implement the {feature['title'].lower()} workflow for the {platform} app.

## Technical constraints
Keep the state transition inspectable and preserve the request identity across apps.

## Design reference
{'Not applicable for backend.' if platform == 'backend' else f'[Design handoff](../design/{feature_id}-{slug}.md)'}

## API contract reference
[API contract](../api-contracts/{feature_id}-{slug}.md)

## Acceptance criteria
- The app reports the same request status as the shared workflow.
- Errors remain visible to the operator or manager.

## Dependencies
No unfinished app dependency is asserted in this synthetic fixture.
""",
            )
        _write_page(
            wiki_root / "design" / f"{feature_id}-{slug}.md",
            {
                "feature-id": feature_id,
                "title": f"{feature['title']} interaction design",
                "apps": UI_PLATFORMS,
                "figma": "not applicable",
            },
            f"""## Summary
The local visualization story shows the {feature['title'].lower()} flow and its decision state.

## Key design decisions
The decision and outcome remain visible in the same workflow context.

## States covered
Empty, loading, error, pending, success, and rejected states are described for visualization context.

## Component references
No external component reference is asserted by this synthetic fixture.

## Open design questions
No design question is recorded for this local fixture.
""",
        )
        if _has_designed(feature):
            impact = "\n".join(f"| {platform} | request workflow | Present or record the {feature['title'].lower()} state |" for platform in PLATFORMS)
            strategy = "\n".join(
                f"| AC-{number} | {', '.join(PLATFORMS)} | manual | end-to-end | Synthetic fixture check |" for number, _text in enumerate(feature["criteria"], start=1)
            )
            _write_page(
                wiki_root / "technical-design" / f"{feature_id}-{slug}.md",
                {"feature-id": feature_id, "title": f"{feature['title']} technical design", "apps": list(PLATFORMS), "decisions": []},
                f"""## Summary
The {feature['title'].lower()} flow reuses the shared request workflow in every app.

## Architecture impact
| App | Modules | Change |
|---|---|---|
{impact}

## Data model and migrations
No migration is asserted by this synthetic fixture.

## Security and privacy
Every operation requires the role named in the API contract.

## Non-functional requirements
No measurable target is asserted by this synthetic fixture.

## Risks
No risk beyond the shared workflow is asserted by this synthetic fixture.

## Decisions
No technical decision is recorded for this local fixture.

## API contract
[API contract](../api-contracts/{feature_id}-{slug}.md)

## Test strategy
| Criterion | Applies to | Method | Level | Notes |
|---|---|---|---|---|
{strategy}
""",
            )
        _write_page(
            wiki_root / "api-contracts" / f"{feature_id}-{slug}.md",
            {"feature-id": feature_id, "version": 1, "status": status},
            CONTRACT_BODY,
        )
        required_action = "- [x] Review the threshold question with the product owner." if feature["status"] == "released" else "- [ ] Review the threshold question with the product owner."
        _write_page(
            wiki_root / "advisory" / f"{feature_id}-review.md",
            {
                "feature-id": feature_id,
                "reviewed": today.isoformat(),
                "board-members-consulted": ["synthetic-domain-reviewer"],
            },
            f"""## 1. Conflicts
No conflicts identified in this synthetic fixture.

## 2. Gaps
The approval threshold remains an open product question where applicable.

## 3. Build order
Backend state transitions should precede client status presentation.

## 4. Biggest risk
An unclear approval boundary could make settlement accountability ambiguous.

## Board perspective summaries
Synthetic reviewer perspective included only to make the advisory relationship visible.

## Actions required before dev starts
{required_action}

## Actions that can be deferred
- Accessibility copy review can be revisited after the local demo.
""",
        )

    _write_page(
        wiki_root / "business-rules" / "BR-001-approval-before-settlement.md",
        {
            "id": "BR-001",
            "title": "Approval precedes settlement",
            "source": "synthetic-local-demo",
        },
        """## Rule
Only an approved payout request may enter settlement.

## Rationale
This keeps the manager decision visible before the finance-admin settlement step.

## Affected features
F-002 and F-003.

## Exceptions
No exceptions.
""",
    )
    _write_page(
        wiki_root / "business-rules" / "BR-002-auditable-outcome.md",
        {
            "id": "BR-002",
            "title": "Settlement outcome remains auditable",
            "source": "synthetic-local-demo",
        },
        """## Rule
A settled, failed, or cancelled payout keeps an inspectable outcome with its request.

## Rationale
Operators need to understand what happened to a payout request.

## Affected features
F-003.

## Exceptions
No exceptions.
""",
    )
    personas = (
        ("P-001", "operator", "Operator", "Creates payout requests and monitors their state.", "F-001"),
        ("P-002", "manager", "Manager", "Reviews requests and makes an accountable approval decision.", "F-002"),
        ("P-003", "finance-admin", "Finance Admin", "Settles approved requests and reviews transaction history.", "F-003"),
    )
    for persona_id, slug, name, description, feature_id in personas:
        _write_page(
            wiki_root / "personas" / f"{slug}.md",
            {"id": persona_id, "name": name, "sources": ["synthetic-local-demo"]},
            f"""## Who they are
{description}

## Goals
- Complete the relevant finance workflow step.
- See the current status and accountable actor.

## Pain points
Unclear state transitions make it difficult to know what needs attention.

## Features that serve this persona
- [{feature_id}](../features/{feature_id}-{next(item['slug'] for item in FEATURES if item['id'] == feature_id)}.md)
""",
        )
    _write_page(
        wiki_root / "decisions" / "ADR-001-stateful-payout-workflow.md",
        {"id": "ADR-001", "title": "Use explicit payout workflow states", "date": today.isoformat(), "status": "accepted"},
        """## Context
Payout requests pass through distinct operator, manager, and finance-admin steps.

## Decision
Represent draft, pending approval, approved, rejected, settled, failed, and cancelled as explicit states.

## Rationale
Explicit states make workflow ownership and history visible in the wiki graph.

## Consequences
Clients must render each state, while audits can follow one stable request identity.
""",
    )


BUG_HEADERS = {
    "fix": ("| App | Artifact | Implementation | Tests | Basis |", "|---|---|---|---|---|"),
}
BUGS: tuple[dict[str, Any], ...] = (
    {
        "id": "BUG-001",
        "slug": "approval-decision-is-not-saved",
        "title": "Approval decision is not saved",
        "status": "open",
        "owner": "dev",
        "feature": "F-002",
        "apps": ["backend"],
        "blocking": True,
        "severity": "high",
        "actual": "A manager approves a request and the decision is lost when the page reloads.",
    },
    {
        "id": "BUG-002",
        "slug": "rejected-request-keeps-the-approve-button",
        "title": "Rejected request keeps the approve button",
        "status": "fixed",
        "owner": "qa",
        "feature": "F-002",
        "apps": ["mobile-android"],
        "blocking": False,
        "severity": "medium",
        "actual": "A request that was rejected still shows an approve button on Android.",
    },
    {
        "id": "BUG-003",
        "slug": "settlement-cache-ignores-the-request-status",
        "title": "Settlement cache ignores the request status",
        "status": "open",
        "owner": "dev",
        "feature": "none",
        "apps": ["backend"],
        "blocking": False,
        "severity": "medium",
        "actual": "A cached settlement view shows a payout as approved after it was reversed.",
        "found_in": "INC-001",
    },
)


def _write_bug_pages(destination: Path) -> None:
    """Three bug pages: an open one and a fixed one of the feature in development, and the open follow-up of the incident."""

    for bug in BUGS:
        fix = ""
        if bug["status"] == "fixed":
            app = bug["apps"][0]
            header, separator = BUG_HEADERS["fix"]
            fix = (
                f"{header}\n{separator}\n"
                f"| {app} | `build:{app}#2` | Synthetic local demo fix for {bug['id']} (no production implementation claim) "
                f"| Synthetic local graph fixture checks for {app} (no production test claim) | attested |"
            )
        frontmatter = {
            "id": bug["id"],
            "title": bug["title"],
            "status": bug["status"],
            "owner": bug["owner"],
            "severity": bug["severity"],
            "blocking": bug["blocking"],
            "apps": list(bug["apps"]),
            "feature": bug["feature"],
            "found-in": bug.get("found_in", f"build:{bug['apps'][0]}#1"),
            "environment": "staging",
            "sources": [],
        }
        body = f"""## Summary
{bug['title']}.

## Steps to reproduce
1. Open the request in the {bug['apps'][0]} app.
2. Repeat the action that the report describes.

## Expected
The request keeps the state that the last action gave it.

## Actual
{bug['actual']}

## Impact
Managers and operators cannot rely on the state they see.

## Fix
{fix}

## Verification


## Release


## Evidence history
"""
        _write_page(destination / "knowledge" / "wiki" / "bugs" / f"{bug['id']}-{bug['slug']}.md", frontmatter, body)


def _release_record_page(number: int, title: str, today: date, rows: list[str], *, features: list[str], outcome: str, summary: str, contracts: str = "None.", rollback: str = "None.", rollback_of: str | None = None) -> tuple[dict[str, Any], str]:
    frontmatter: dict[str, Any] = {
        "id": f"REL-{number:03d}",
        "title": title,
        "date": today.isoformat(),
        "operation": "demo-seed",
        "outcome": outcome,
        "features": features,
        "bugs": [],
    }
    if rollback_of:
        frontmatter["rollback-of"] = rollback_of
    body = f"""## Summary
{summary}

## Delivery
| Item | App | Target | Version | Attempt | Outcome | Evidence | Basis |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## Contracts
{contracts}

## Rollback
{rollback}

## Notes
None.
"""
    return frontmatter, body


def _write_release_records(destination: Path, today: date) -> None:
    """REL-001 delivers the released feature to all three apps, and REL-002 rolls the backend delivery back."""

    wiki_root = destination / "knowledge" / "wiki"
    feature = next(item for item in FEATURES if item["id"] == RELEASED_FEATURE)
    contract_text = (wiki_root / "api-contracts" / f"{feature['id']}-{feature['slug']}.md").read_text(encoding="utf-8")
    citation = contract_citation(feature["id"], 1, CONTRACT_BODY)
    snapshots = "\n".join(format_snapshot(feature["id"], platform, citation, contract_text) for platform in PLATFORMS)
    proof = {"backend": "deployment", "mobile-android": "store", "mobile-ios": "store"}
    delivered = [
        f"| {feature['id']} | {platform} | {TARGETS[platform]} | `build:{platform}#1` | release-1 | released | {proof[platform]}: https://example.test/demo/{platform} | attested |"
        for platform in PLATFORMS
    ]
    frontmatter, body = _release_record_page(
        1, f"Release of {feature['id']}", today, delivered, features=[feature["id"]], outcome="released",
        summary=f"{feature['id']} is delivered to every app of the demo.", contracts=snapshots,
    )
    _write_page(wiki_root / "releases" / "REL-001.md", frontmatter, body)
    rolled_back = [f"| {feature['id']} | backend | {TARGETS['backend']} | `build:backend#1` | — | rolled-back | deployment: https://example.test/demo/rollback | attested |"]
    frontmatter, body = _release_record_page(
        2, "Rollback of REL-001", today, rolled_back, features=[feature["id"]], outcome="rolled-back",
        summary="The backend delivery of REL-001 is rolled back after settlement errors.",
        rollback="The backend was rolled back to the previous build after settlements failed for twenty minutes.", rollback_of="REL-001",
    )
    _write_page(wiki_root / "releases" / "REL-002.md", frontmatter, body)


def _write_incident(destination: Path, today: date) -> None:
    """INC-001: the settlement errors behind REL-002. The cause is not known yet, and BUG-003 follows from it."""

    frontmatter = {
        "id": "INC-001",
        "title": "Settlements fail after the release",
        "date": today.isoformat(),
        "status": "mitigated",
        "severity": "high",
        "apps": ["backend"],
        "releases": ["REL-001", "REL-002"],
        "follow-ups": ["BUG-003"],
    }
    bug = next(item for item in BUGS if item["id"] == "BUG-003")
    body = f"""## Impact
Finance admins could not settle approved payouts for twenty minutes.

## Timeline
- {today.isoformat()} 09:05: Settlements started failing after REL-001.
- {today.isoformat()} 09:25: The backend delivery of REL-001 was rolled back by REL-002.

## Cause
**Unknown:** The settlement path failed after REL-001; the failing path is not known yet.

## Mitigation
The backend delivery of REL-001 was rolled back by REL-002 at 09:25.

## Resolution


## Follow-ups
- [BUG-003](../bugs/{bug['id']}-{bug['slug']}.md): a settlement view that shows a stale state
"""
    _write_page(destination / "knowledge" / "wiki" / "incidents" / "INC-001-settlements-fail-after-the-release.md", frontmatter, body)


def _write_operation_pages(destination: Path, today: date) -> None:
    _write_bug_pages(destination)
    _write_release_records(destination, today)
    _write_incident(destination, today)


def _view_tables(destination: Path) -> str:
    """The Bugs and Operations tables of the demo board, derived from the pages with the readers the board uses."""

    wiki_root = destination / "knowledge" / "wiki"
    model = inspect_workspace(destination).model
    targets, _problems = resolve_delivery_targets(None, model)
    cells = {page.feature_id: app_stages_text(page.status, page.apps, page.page.body, model) for page in read_feature_pages(wiki_root)}
    bug_rows = [row for bug in read_bug_pages(wiki_root) if (row := bug_board_row(bug)) is not None]
    incidents, releases = read_incident_pages(wiki_root), read_release_records(wiki_root)
    operations = [
        format_operation_row(row)
        for app in model.apps
        if (
            row := operation_row(
                app.id,
                delivery_target=targets.get(app.id, {}).get("target"),
                feature_stage_cells=cells,
                bug_rows=bug_rows,
                incidents=incidents,
                releases=releases,
            )
        )
        is not None
    ]
    text = ""
    if bug_rows:
        text += "\n" + table_text(BUGS_HEADING, BUG_TABLE_COLUMNS, [format_bug_row(row) for row in sorted(bug_rows, key=lambda item: item["id"])])
    if operations:
        text += "\n" + table_text(OPERATIONS_HEADING, OPERATIONS_TABLE_COLUMNS, operations)
    return text


def _write_populated_index(destination: Path, today: date) -> None:
    wiki_root = destination / "knowledge" / "wiki"
    model = inspect_workspace(destination).model
    pages = {page.feature_id: page for page in read_feature_pages(wiki_root)}
    bug_rows = [row for bug in read_bug_pages(wiki_root) if (row := bug_board_row(bug)) is not None]
    rows = []
    for feature in FEATURES:
        page = pages[feature["id"]]
        stages = app_stages_text(page.status, page.apps, page.page.body, model)
        tracks = design_tracks_text(page.page.frontmatter)
        open_bugs = ids_text(open_bugs_of_feature(feature["id"], bug_rows))
        rows.append(
            f"| {feature['id']} | [{feature['title']}](features/{feature['id']}-{feature['slug']}.md) | {feature['status']} | {feature['owner']} | {feature['advisory']} "
            f"| {tracks} | {stages} | {open_bugs} |"
        )
    _write_text(
        wiki_root / "status-board.md",
        """# Feature Status Board

This file is maintained by the AI agent. Do not edit directly.

| ID | Feature | Status | Owner | Board Review | Design tracks | App stages | Open bugs |
|----|---------|--------|-------|--------------|---------------|------------|-----------|
"""
        + "\n".join(rows)
        + "\n"
        + _view_tables(destination),
    )
    # The general index lists every page the stage holds, one derived line each.
    _write_text(wiki_root / "index.md", build_index(wiki_root))


def _build_stage(destination: Path, stage: str, today: date) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    _write_synthetic_workspace_files(destination, stage, today)
    _write_workspace_contract(destination, today)
    _write_wiki_skeleton(destination, stage, today)
    if stage in {"intake", "populated"}:
        _write_intake_item(destination, "2026-09-28-duplicate-settlement-brief", quarantined=True)
    if stage == "intake":
        _write_intake_item(destination, "2026-09-29-payout-approval-brief", quarantined=False)
    if stage == "populated":
        _write_intake_item(destination, "2026-09-30-future-refund-brief", quarantined=False)
        _write_processed_item(destination)
        _write_feature_pages(destination, today)
        _write_linked_context(destination, today)
        _write_operation_pages(destination, today)
        _write_populated_index(destination, today)
    else:
        # The template ships `index.md` as a Jinja file, so the copied wiki has none; build it as the board does.
        wiki_root = destination / "knowledge" / "wiki"
        _write_text(wiki_root / "index.md", build_index(wiki_root))


def _reserve_destination(destination: Path) -> Path:
    resolved = destination.expanduser().resolve()
    if resolved.exists():
        raise FileExistsError(resolved)
    return resolved


def build_demo(destination: Path, stage: str, today: date) -> dict[str, Any]:
    base = _reserve_destination(destination)
    stages: dict[str, str] = {}
    if stage == "all":
        base.mkdir(parents=True, exist_ok=False)
        for name in ("fresh", "intake", "populated"):
            path = base / name
            _build_stage(path, name, today)
            stages[name] = str(path)
    else:
        _build_stage(base, stage, today)
        stages[stage] = str(base)
    return {
        "destination": str(base),
        "today": today.isoformat(),
        "synthetic": True,
        "stages": stages,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True, help="New directory to create for the demo fixture.")
    parser.add_argument("--stage", choices=("fresh", "intake", "populated", "all"), default="all")
    parser.add_argument("--today", type=_parse_today, default=date.today(), help="Fixture date (YYYY-MM-DD).")
    parser.add_argument("--json", action="store_true", help="Emit deterministic machine-readable metadata.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_demo(args.destination, args.stage, args.today)
    except FileExistsError as exc:
        print(f"Refusing to overwrite existing destination: {exc.filename or args.destination}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Unable to build demo: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Built synthetic TreasuryFlow wiki demo at {result['destination']}")
        for name, path in result["stages"].items():
            print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
