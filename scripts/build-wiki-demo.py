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
from prism_cli.workspace import write_workspace_manifest  # noqa: E402
from prism_cli.wiki_transitions import ACTION_SPECS  # noqa: E402


PRODUCT_NAME = "TreasuryFlow"
PROJECT_SLUG = "treasury-flow"
PACKAGE_IDENTIFIER = "com.mortitech.treasuryflow"
DESCRIPTION = "A finance operations platform for payout approvals, settlements, and transaction oversight"
PLATFORMS = ["backend", "mobile-android", "mobile-ios"]  # the generated platform IDs, which are also the demo's app IDs
AUTH_METHODS = ["password", "google"]
TEMPLATE_SOURCE = "synthetic-local-demo"
DEMO_TODAY = date.today()

WIKI_TEMPLATE_ROOT = REPO_ROOT / "template" / "knowledge" / "wiki"
INTAKE_TEMPLATE_ROOT = REPO_ROOT / "template" / "knowledge" / "intake"

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
        "status": "done",
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
)


def _answers() -> dict[str, Any]:
    return {
        "project_name": PRODUCT_NAME,
        "project_slug": PROJECT_SLUG,
        "package_identifier": PACKAGE_IDENTIFIER,
        "description": DESCRIPTION,
        "platforms": list(PLATFORMS),
        "auth_methods": list(AUTH_METHODS),
        "database": "postgres",
        "supporting_services": [],
        "use_docker": True,
        "cloud_provider": "azure",
        "web_hosting": "cloudflare",
        "github_org": "",
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
        destination / "CONTEXT.md",
        f"""# Context

{PRODUCT_NAME} is a synthetic finance operations story covering payout requests, manager approval,
and finance-admin settlement/history review. This local fixture is documentation only.
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
    for command in {spec.command for spec in ACTION_SPECS}:
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
        "docs": ["README.md", "CONTEXT.md", "docs/"],
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

Initialized for this synthetic local dashboard fixture on {today.isoformat()}.

## Project identity
- Name: {PRODUCT_NAME}
- Description: {DESCRIPTION}
- Apps: {', '.join(PLATFORMS)}
- Auth methods: {', '.join(AUTH_METHODS)}
- Infrastructure choices: Postgres, Docker, Azure
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

## {today.isoformat()}
- Seeded synthetic local `{stage}` stage for dashboard capture.
- This entry describes fixture generation, not observed project history or a real review event.
""",
    )


def _write_intake_item(destination: Path, name: str, *, quarantined: bool) -> None:
    queue = "quarantined" if quarantined else "pending"
    item_root = destination / "knowledge" / "intake" / queue / name
    if quarantined:
        _write_text(
            item_root / "CONFLICT.md",
            """# Synthetic quarantine marker

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


def _feature_frontmatter(feature: dict[str, Any], today: date) -> dict[str, Any]:
    return {
        "id": feature["id"],
        "title": feature["title"],
        "status": feature["status"],
        "owner": feature["owner"],
        "introduced": today.isoformat(),
        "last-updated": today.isoformat(),
        "apps": list(PLATFORMS),
        "sources": ["synthetic-local-demo"],
        "advisory-review": feature["advisory"],
    }


def _write_feature_pages(destination: Path, today: date) -> None:
    features_root = destination / "knowledge" / "wiki" / "features"
    for feature in FEATURES:
        criteria = "\n".join(f"- [ ] {criterion}" for criterion in feature["criteria"])
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

## Post-ship notes
No observed post-ship history is recorded in this synthetic fixture.
"""
        if feature["status"] == "done":
            body += f"""
## Delivery evidence
| App | Implementation | Tests | Release |
|---|---|---|---|
| backend | Synthetic local demo backend surface for {feature['id']} (no production implementation claim) | Synthetic local graph fixture checks for backend (no production test claim) | Synthetic local demo release marker for backend (no production release claim) |
| mobile-android | Synthetic local demo Android surface for {feature['id']} (no production implementation claim) | Synthetic local graph fixture checks for Android (no production test claim) | Synthetic local demo release marker for Android (no production release claim) |
| mobile-ios | Synthetic local demo iOS surface for {feature['id']} (no production implementation claim) | Synthetic local graph fixture checks for iOS (no production test claim) | Synthetic local demo release marker for iOS (no production release claim) |
"""
        _write_page(features_root / f"{feature['id']}-{feature['slug']}.md", _feature_frontmatter(feature, today), body)


def _write_linked_context(destination: Path, today: date) -> None:
    wiki_root = destination / "knowledge" / "wiki"
    for feature in FEATURES:
        feature_id = feature["id"]
        slug = feature["slug"]
        status = "implemented" if feature["status"] == "done" else "agreed"
        for platform in PLATFORMS:
            requirement_status = "done" if feature["status"] == "done" else "in-progress"
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
                "designer": "synthetic-demo",
                "date": today.isoformat(),
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
        _write_page(
            wiki_root / "api-contracts" / f"{feature_id}-{slug}.md",
            {"feature-id": feature_id, "version": 1, "status": status},
            f"""## Endpoints
- `POST /payout-requests`: create or submit a request.
- `POST /payout-requests/{{id}}/decision`: record an approval or rejection.

## Data models
The request carries an ID, amount, currency, actor, status, and outcome metadata.

## Authentication requirements
Require the role appropriate to the operation: operator, manager, or finance admin.

## Notes
This is a synthetic contract summary for graph relationships; it is not an implementation promise.
""",
        )
        required_action = "- [x] Review the threshold question with the product owner." if feature["status"] == "done" else "- [ ] Review the threshold question with the product owner."
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
            "introduced": today.isoformat(),
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
            "introduced": today.isoformat(),
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
            {"id": persona_id, "name": name, "introduced": today.isoformat(), "sources": ["synthetic-local-demo"]},
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


def _write_populated_index(destination: Path, today: date) -> None:
    rows = [
        f"| {feature['id']} | [{feature['title']}](features/{feature['id']}-{feature['slug']}.md) | {feature['status']} | {feature['owner']} | {feature['advisory']} | {today.isoformat()} |"
        for feature in FEATURES
    ]
    _write_text(
        destination / "knowledge" / "wiki" / "index.md",
        """# Feature Status Board

This file is maintained by the AI agent. Do not edit directly.

| ID | Feature | Status | Owner | Board Review | Introduced |
|----|---------|--------|-------|--------------|------------|
"""
        + "\n".join(rows)
        + """

## Other wiki pages
| Page | Type | Summary | Date |
|------|------|---------|------|
| [SCHEMA.md](SCHEMA.md) | meta | Wiki conventions and operational rules | n/a |
| [BOARD.md](advisory/BOARD.md) | config | Synthetic local advisory board state | n/a |
""",
    )


def _build_stage(destination: Path, stage: str, today: date) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    _write_synthetic_workspace_files(destination, stage, today)
    _write_workspace_contract(destination, today)
    _write_wiki_skeleton(destination, stage, today)
    if stage in {"intake", "populated"}:
        _write_intake_item(destination, "duplicate-settlement-brief", quarantined=True)
    if stage == "intake":
        _write_intake_item(destination, "payout-approval-brief", quarantined=False)
    if stage == "populated":
        _write_intake_item(destination, "future-refund-brief", quarantined=False)
        _write_feature_pages(destination, today)
        _write_linked_context(destination, today)
        _write_populated_index(destination, today)


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
